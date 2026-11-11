"""往工作台灌入 10 局验证数据（走真实通道流程：建局→官方→营地→审核→保存）。

    python scripts/seed_validation_matches.py [--limit 10] [--base http://127.0.0.1:8766]

选局：data/camp_details 里有详情、且 data/official_replays/camp-* 有公开缓存的局。
日期取列表缓存的数据；对手记为「排位验证」，训练分组「验证数据」。
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DETAIL_DIR = ROOT / 'data' / 'camp_details'
STORE = ROOT / 'data' / 'official_replays'
LIST_CACHE = ROOT / 'data' / 'camp_lists'


def api(base, path, payload=None, method=None):
    url = base + path
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode('utf-8')
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=data, headers=headers,
                                     method=method or ('POST' if payload is not None else 'GET'))
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        body = error.read().decode('utf-8', 'replace')
        return error.code, {'detail': body[:300]}


def pick_matches(limit):
    dates = {}
    for cache in LIST_CACHE.glob('*.json'):
        try:
            entries = json.loads(cache.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        for entry in entries:
            seq = str(entry.get('gameSeq') or '')
            dt = int(entry.get('dtEventTime') or 0)
            if seq and dt:
                dates[seq] = dt
    picked = []
    for detail in sorted(DETAIL_DIR.glob('*.json')):
        seq = detail.stem
        if not (STORE / f'camp-{seq}' / 'normalized.json').is_file():
            continue
        import time as _time
        day = (_time.strftime('%Y-%m-%d', _time.localtime(dates[seq])) if seq in dates else '')
        picked.append({'seq': seq, 'date': day})
        if len(picked) >= limit:
            break
    return picked


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--base', default='http://127.0.0.1:8766')
    args = parser.parse_args()
    status, existing = api(args.base, '/api/channels')
    if status != 200:
        raise SystemExit(f'连不上工作台：{status} {existing}')
    existing_seqs = {(channel.get('official') or {}).get('id', ''): channel
                     for channel in existing.get('channels') or []}
    picked = pick_matches(args.limit)
    print(f'准备灌入 {len(picked)} 局')
    ok = failed = 0
    for item in picked:
        seq, day = item['seq'], item['date']
        existing_channel = existing_seqs.get(f'camp-{seq}')
        if existing_channel:
            if (existing_channel.get('saved') or {}).get('status') == 'saved':
                print(f'  跳过 {seq}（已保存）')
                continue
            channel_id = existing_channel['id']
            if (existing_channel.get('review') or {}).get('status') != 'reviewed':
                api(args.base, f'/api/channels/{channel_id}/review',
                    {'reviewedBy': '验证脚本', 'notes': '功能验证数据'})
            status, value = api(args.base, f'/api/channels/{channel_id}/save', {})
            if status == 200:
                ok += 1
                print(f'  补保存 {seq}（已建通道）')
            else:
                failed += 1
                print(f'  失败 {seq} 补保存：{value}')
            continue
        steps = {}
        status, channel = api(args.base, '/api/channels', {'match': {
            'date': day, 'opponent': '排位验证', 'session': '验证数据', 'version': ''}})
        if status != 200:
            print(f'  失败 {seq} 建局：{channel}')
            failed += 1
            continue
        channel_id = channel['id']
        status, value = api(args.base, f'/api/channels/{channel_id}/official',
                            {'officialId': f'camp-{seq}'})
        steps['official'] = status
        if status != 200:
            print(f'  失败 {seq} 官方回放：{value}')
            failed += 1
            continue
        status, value = api(args.base, f'/api/channels/{channel_id}/camp', {'gameSeq': seq})
        steps['camp'] = status
        if status != 200:
            print(f'  失败 {seq} 营地面板：{value}')
            failed += 1
            continue
        status, value = api(args.base, f'/api/channels/{channel_id}/review',
                            {'reviewedBy': '验证脚本', 'notes': '功能验证数据'})
        steps['review'] = status
        if status != 200:
            print(f'  失败 {seq} 审核：{value}')
            failed += 1
            continue
        status, value = api(args.base, f'/api/channels/{channel_id}/save', {})
        steps['save'] = status
        if status != 200:
            print(f'  失败 {seq} 保存：{value}')
            failed += 1
            continue
        ok += 1
        print(f'  完成 {seq} · {day} · bundle {(value.get("channel") or {}).get("saved", {}).get("bundleKey", "")[:18]}')
    status, state = api(args.base, '/api/state')
    print(f'灌入结果：成功 {ok}，失败 {failed}；当前比赛数 {len((state or {}).get("matches") or [])}')


if __name__ == '__main__':
    main()
