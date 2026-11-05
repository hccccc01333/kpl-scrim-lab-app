"""营地战绩增量同步（独立实现）。

拉取指定营地账号的战绩列表（水位线增量），逐局拉取对局详情（含 BP、
十人面板、出装）落盘到 data/camp_details/<gameSeq>.json。

    python tools/camp_sync.py <friendUserId> [--max-pages 8]

约定：
- 水位记录在 data/camp_sync_state.json：每账号保存最后一条对局的
  dtEventTime（秒），下次只拉这个时间之后的新局。
- 请求间隔 2 秒，单次最多 8 页，把风控暴露压到人工水平。
- 列表里每局自 battleType/mapName，训练赛筛选在工作台侧做，这里全量入库。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib import parse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camp_client import battle_detail, battle_list, load_account  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path(os.environ['CAMP_SYNC_STATE']) if 'CAMP_SYNC_STATE' in os.environ \
    else ROOT / 'data' / 'camp_sync_state.json'
DETAIL_DIR = Path(os.environ.get('CAMP_DETAIL_DIR', ROOT / 'data' / 'camp_details'))
REQUEST_INTERVAL = 2.0


def load_state() -> dict:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding='utf-8'))
        except ValueError:
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')


def entry_role_id(entry: dict) -> str:
    """列表条目不带角色 ID，要从内嵌跳转链接里解析（toAppRoleId / uniqueRoleId）。"""
    for source, pattern in ((entry.get('battleDetailUrl') or '', r'toAppRoleId=(\d+)'),
                            (entry.get('analyseUrl') or '', r'uniqueRoleId=(\d+)'),
                            (entry.get('detailUrl') or '', r'uniqueRoleId=(\d+)')):
        if not source:
            continue
        match = re.search(pattern, source)
        if match:
            return match.group(1)
    return '0'


def sync(friend_user_id: str, max_pages: int = 8) -> dict:
    state = load_state()
    watermark = int(state.get(friend_user_id) or 0)
    account = load_account()  # 提前校验凭证，避免跑到一半发现没登录
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)

    summary = {'fetched': 0, 'saved': 0, 'cached': 0, 'failed': 0, 'pages': 0,
               'gameSeqs': []}
    cursor = watermark
    newest = watermark

    for _ in range(max_pages):
        result = battle_list(friend_user_id, cursor)
        body = result.get('body') or {}
        if body.get('returnCode') not in (0, '0'):
            raise SystemExit(f"列表接口失败：{json.dumps(body, ensure_ascii=False)[:200]}")
        data = body.get('data') or {}
        entries = data.get('list') or []
        summary['pages'] += 1

        new_entries = [e for e in entries if int(e.get('dtEventTime') or 0) > watermark]
        if not new_entries:
            break

        for entry in new_entries:
            seq = str(entry.get('gameSeq') or '')
            event_time = int(entry.get('dtEventTime') or 0)
            newest = max(newest, event_time)
            summary['fetched'] += 1
            if not seq:
                summary['failed'] += 1
                continue
            out_path = DETAIL_DIR / f'{seq}.json'
            if out_path.is_file():
                summary['cached'] += 1
                continue
            detail = battle_detail(
                seq, str(entry.get('gameSvrId') or ''), str(entry.get('relaySvrId') or ''),
                str(entry.get('battleType') or 0), entry_role_id(entry))
            detail_body = detail.get('body') or {}
            if detail_body.get('returnCode') not in (0, '0'):
                summary['failed'] += 1
                print(f"  详情失败 {seq}: returnCode={detail_body.get('returnCode')} "
                      f"{str(detail_body.get('returnMsg'))[:60]}", file=sys.stderr)
            else:
                out_path.write_text(json.dumps({**detail_body,
                                                '_campEntry': {
                                                    'dtEventTime': entry.get('dtEventTime'),
                                                    'mapName': entry.get('mapName'),
                                                    'gametime': entry.get('gametime'),
                                                    'battleType': entry.get('battleType'),
                                                    'winCamp': entry.get('winCamp'),
                                                    'killcnt': entry.get('killcnt'),
                                                    'deadcnt': entry.get('deadcnt'),
                                                    'assistcnt': entry.get('assistcnt'),
                                                }},
                                               ensure_ascii=False, indent=1),
                                    encoding='utf-8')
                summary['saved'] += 1
                summary['gameSeqs'].append(seq)
                print(f"  已入库 {seq} · {entry.get('mapName')} · {entry.get('gametime')}")
            time.sleep(REQUEST_INTERVAL)

        if not data.get('hasMore'):
            break
        next_cursor = int(data.get('lastTime') or newest)
        if next_cursor <= cursor or next_cursor <= watermark:
            break
        cursor = next_cursor
        time.sleep(REQUEST_INTERVAL)

    state[friend_user_id] = newest
    save_state(state)
    summary['watermark'] = newest
    return summary


def sync_entries(camp_user_id: str, entries, interval: float = 2.0) -> dict:
    """按教练勾选的对局条目逐条拉取详情并落盘（两段式同步的第二段）。

    entries 是 /api/camp/list 返回的条目原样回传；已入库的局跳过；
    水位推进到已入库条目的最新 dtEventTime（未勾选的最新局下次仍会列出）。
    """
    state = load_state()
    watermark = int(state.get(camp_user_id) or 0)
    newest = watermark
    summary = {'fetched': 0, 'saved': 0, 'cached': 0, 'failed': 0, 'gameSeqs': []}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        seq = str(entry.get('gameSeq') or '')
        if not seq:
            summary['failed'] += 1
            continue
        summary['fetched'] += 1
        event_time = int(entry.get('dtEventTime') or 0)
        out_path = DETAIL_DIR / f'{seq}.json'
        if out_path.is_file():
            summary['cached'] += 1
            newest = max(newest, event_time)
            continue
        detail = battle_detail(
            seq, str(entry.get('gameSvrId') or ''), str(entry.get('relaySvrId') or ''),
            str(entry.get('battleType') or 0), str(entry.get('uniqueRoleId') or entry.get('roleId') or 0))
        detail_body = detail.get('body') or {}
        if detail_body.get('returnCode') not in (0, '0'):
            summary['failed'] += 1
            continue
        out_path.write_text(json.dumps({**detail_body,
                                        '_campEntry': {
                                            'dtEventTime': entry.get('dtEventTime'),
                                            'mapName': entry.get('mapName'),
                                            'gametime': entry.get('gametime'),
                                            'battleType': entry.get('battleType'),
                                            'winCamp': entry.get('winCamp'),
                                            'killcnt': entry.get('killcnt'),
                                            'deadcnt': entry.get('deadcnt'),
                                            'assistcnt': entry.get('assistcnt'),
                                        }},
                                       ensure_ascii=False, indent=1),
                            encoding='utf-8')
        summary['saved'] += 1
        summary['gameSeqs'].append(seq)
        newest = max(newest, event_time)
        time.sleep(interval)
    if newest > watermark:
        state[camp_user_id] = newest
        save_state(state)
    summary['watermark'] = newest
    return summary


def main(argv):
    parser = argparse.ArgumentParser(description='营地战绩增量同步')
    parser.add_argument('friend_user_id', help='营地账号 ID（数字）')
    parser.add_argument('--max-pages', type=int, default=8)
    parser.add_argument('--reset', action='store_true', help='忽略水位，从头同步')
    args = parser.parse_args(argv)
    if args.reset:
        state = load_state()
        state.pop(args.friend_user_id, None)
        save_state(state)
    summary = sync(args.friend_user_id, args.max_pages)
    print(f"同步完成：{summary}")


if __name__ == '__main__':
    main(sys.argv[1:])
