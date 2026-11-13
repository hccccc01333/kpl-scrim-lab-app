"""营地战绩增量同步（独立实现）。

拉取指定营地账号的战绩列表（水位线增量），逐局拉取对局详情（含 BP、
十人面板、出装）落盘到 data/camp_details/<gameSeq>.json。

    python tools/camp_sync.py <friendUserId> [--max-pages N]

约定：
- 水位记录在 data/camp_sync_state.json：每账号保存最后一条对局的
  dtEventTime（秒），下次只拉这个时间之后的新局。
- 请求间隔 2 秒，把风控暴露压到人工水平。
- 页数：增量同步默认 8 页；首次全量（无水位）自动翻到营地详情保留期边界
  或 hasMore=false（上限 60 页，约 900 局），不再静默截断在 8 页≈127 局。
- 列表里每局自 battleType/mapName，训练赛筛选在工作台侧做，这里全量入库。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camp_client import battle_detail, battle_list, load_account  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

_SEQ_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def _safe_seq(value):
    """对局 ID 只允许单段安全字符，避免拼路径时穿越到其它目录。"""
    text = str(value or '').strip()
    if not text or text in ('.', '..') or not _SEQ_RE.match(text):
        return ''
    return text
STATE_PATH = Path(os.environ['CAMP_SYNC_STATE']) if 'CAMP_SYNC_STATE' in os.environ \
    else ROOT / 'data' / 'camp_sync_state.json'
DETAIL_DIR = Path(os.environ.get('CAMP_DETAIL_DIR', ROOT / 'data' / 'camp_details'))
REQUEST_INTERVAL = 2.0
INCREMENTAL_MAX_PAGES = 8
FULL_PULL_MAX_PAGES = 60


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


def sync(friend_user_id: str, max_pages: int | None = None) -> dict:
    """max_pages=None 时自动决定：首次全量（无水位）翻到详情保留期边界或
    hasMore=false（上限 60 页），增量同步沿用 8 页。"""
    state = load_state()
    watermark = int(state.get(friend_user_id) or 0)
    load_account()  # 提前校验凭证（无凭证直接抛错），避免跑到一半才发现没登录
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)

    summary = {'fetched': 0, 'saved': 0, 'cached': 0, 'failed': 0, 'pages': 0,
               'gameSeqs': []}
    cursor = watermark
    newest = watermark
    if max_pages is None:
        max_pages = FULL_PULL_MAX_PAGES if watermark == 0 else INCREMENTAL_MAX_PAGES
    # 营地详情只保留最近 DETAIL_TTL_DAYS 天：整页都超出保留期后继续翻页
    # 只会拿到无法入库的列表项，到此为止。
    window_start = time.time() - DETAIL_TTL_DAYS * 86400
    oldest_fetched = 0

    for _ in range(max_pages):
        result = battle_list(friend_user_id, cursor)
        body = result.get('body') or {}
        if body.get('returnCode') not in (0, '0'):
            raise SystemExit(f"列表接口失败：{json.dumps(body, ensure_ascii=False)[:200]}")
        data = body.get('data') or {}
        entries = data.get('list') or []
        summary['pages'] += 1

        page_times = [int(e.get('dtEventTime') or 0) for e in entries
                      if e.get('dtEventTime')]
        if page_times:
            oldest_fetched = min(page_times)
            summary['oldest'] = oldest_fetched
        if page_times and max(page_times) < window_start:
            summary['reachedWindow'] = True
            break
        new_entries = [e for e in entries if int(e.get('dtEventTime') or 0) > watermark]
        if not new_entries:
            summary['reachedWindow'] = bool(page_times and min(page_times) < window_start)
            break

        for entry in new_entries:
            seq = _safe_seq(entry.get('gameSeq'))
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
                                                    'usedTime': entry.get('usedTime'),
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


MAX_CONSECUTIVE_FAILURES = 5

# 营地只提供最近一个月的战局详情：更早的局调用详情接口会返回
# -30457「暂不支持查看一个月前的战绩详情」。这里的口径与前端 capture-page.js
# 的 CAMP_DETAIL_TTL_DAYS 保持一致。
DETAIL_TTL_DAYS = 31
DETAIL_EXPIRED_CODE = '-30457'


def detail_expired(entry: dict, now: float | None = None) -> bool:
    """这局是否已超出营地的详情保留期（约一个月）。

    先用 startedAt（北京时间 ISO），没有再用 dtEventTime - usedTime。
    判断不出来时返回 False：宁可多问一次接口，也不凭空把局划成不可用。
    """
    started = str((entry or {}).get('startedAt') or '')
    moment = 0.0
    if len(started) >= 19:
        try:
            moment = datetime.strptime(started[:19], '%Y-%m-%dT%H:%M:%S').timestamp()
        except ValueError:
            moment = 0.0
    if not moment:
        event = int((entry or {}).get('dtEventTime') or 0)
        used = int((entry or {}).get('usedTime') or 0)
        moment = float(event - used) if event else 0.0
    if not moment:
        return False
    return (now or time.time()) - moment > DETAIL_TTL_DAYS * 86400


def _note_failure(summary: dict, seq: str, message: str) -> None:
    """记录失败原因（最多留 20 条），让界面能说清「为什么没进去」。"""
    errors = summary.setdefault('errors', [])
    if len(errors) < 20:
        errors.append({'gameSeq': seq, 'message': str(message)[:200]})


def sync_entries(camp_user_id: str, entries, interval: float = 2.0, on_progress=None) -> dict:
    """按教练勾选的对局条目逐条拉取详情并落盘（两段式同步的第二段）。

    entries 是 /api/camp/list 返回的条目原样回传；已入库的局跳过；
    水位推进到已入库条目的最新 dtEventTime（未勾选的最新局下次仍会列出）。
    on_progress(done, total, game_seq, phase) 可选，供界面显示真实入库进度。

    单局失败（网络抖动、营地没这局详情）只记在该局的失败原因里，不打断整批；
    连续失败 MAX_CONSECUTIVE_FAILURES 次才停下，避免对着坏接口空转。
    登录态失效仍然整批中止，由上层提示重新扫码。
    """
    state = load_state()
    watermark = int(state.get(camp_user_id) or 0)
    newest = watermark
    summary = {'fetched': 0, 'saved': 0, 'cached': 0, 'failed': 0, 'gameSeqs': [],
               'errors': [], 'aborted': '', 'unsupported': 0, 'unsupportedSeqs': []}
    total = len(entries)
    streak = 0
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            continue
        seq = _safe_seq(entry.get('gameSeq'))
        if not seq:
            summary['failed'] += 1
            continue
        if on_progress:
            try:
                on_progress(index, total, seq, 'detail')
            except Exception:
                pass
        summary['fetched'] += 1
        event_time = int(entry.get('dtEventTime') or 0)
        out_path = DETAIL_DIR / f'{seq}.json'
        if out_path.is_file():
            summary['cached'] += 1
            newest = max(newest, event_time)
            streak = 0
            continue
        if detail_expired(entry):
            # 超过一个月的局营地不给详情，直接标出来，不用再发请求。
            summary['unsupported'] += 1
            summary['unsupportedSeqs'].append(seq)
            _note_failure(summary, seq, '营地只提供最近一个月的战局详情')
            streak = 0
            continue
        try:
            detail = battle_detail(
                seq, str(entry.get('gameSvrId') or ''), str(entry.get('relaySvrId') or ''),
                str(entry.get('battleType') or 0),
                str(entry.get('uniqueRoleId') or entry.get('roleId') or 0))
        except Exception as error:  # noqa: BLE001 - 单局网络异常不该作废整批
            if getattr(error, 'auth_invalid', False):
                raise
            summary['failed'] += 1
            streak += 1
            _note_failure(summary, seq, f'{type(error).__name__}: {error}')
            if streak >= MAX_CONSECUTIVE_FAILURES:
                summary['aborted'] = f'连续 {streak} 局拉取失败，已停下：{error}'
                break
            time.sleep(interval)
            continue
        detail_body = detail.get('body') or {}
        code_text = str(detail_body.get('returnCode'))
        if code_text == DETAIL_EXPIRED_CODE or '暂不支持查看' in str(detail_body.get('returnMsg')):
            # 接口明确说这局不给详情：记成「营地无详情」，不算网络失败，也不重试。
            summary['unsupported'] += 1
            summary['unsupportedSeqs'].append(seq)
            _note_failure(summary, seq, '营地只提供最近一个月的战局详情（-30457）')
            streak = 0
            continue
        if detail_body.get('returnCode') not in (0, '0'):
            summary['failed'] += 1
            streak += 1
            _note_failure(summary, seq, f"returnCode={detail_body.get('returnCode')} "
                                        f"{str(detail_body.get('returnMsg'))[:60]}")
            if streak >= MAX_CONSECUTIVE_FAILURES:
                summary['aborted'] = (f'连续 {streak} 局拉取失败，已停下：'
                                      f"returnCode={detail_body.get('returnCode')}")
                break
            time.sleep(interval)
            continue
        out_path.write_text(json.dumps({**detail_body,
                                        '_campEntry': {
                                            'dtEventTime': entry.get('dtEventTime'),
                                            'usedTime': entry.get('usedTime'),
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
        streak = 0
        time.sleep(interval)
    if newest > watermark:
        state[camp_user_id] = newest
        save_state(state)
    summary['watermark'] = newest
    return summary


def main(argv):
    parser = argparse.ArgumentParser(description='营地战绩增量同步')
    parser.add_argument('friend_user_id', help='营地账号 ID（数字）')
    parser.add_argument('--max-pages', type=int, default=None,
                        help='翻页上限；缺省自动（首次全量 60 页，增量 8 页）')
    parser.add_argument('--reset', action='store_true', help='忽略水位，从头同步')
    args = parser.parse_args(argv)
    if args.reset:
        state = load_state()
        state.pop(args.friend_user_id, None)
        save_state(state)
    summary = sync(args.friend_user_id, args.max_pages)
    if summary.get('oldest'):
        print(f"已覆盖到 {datetime.fromtimestamp(summary['oldest']):%Y-%m-%d %H:%M}"
              + ('（营地详情保留期边界）' if summary.get('reachedWindow') else ''))
    print(f"同步完成：{summary}")


if __name__ == '__main__':
    main(sys.argv[1:])
