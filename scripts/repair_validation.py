"""重建验证数据的营地映射：清空壳通道 + 重 attach camp + 重新审核保存。

    python scripts/repair_validation.py [--base http://127.0.0.1:8766]

只处理 session 含「验证数据」的通道：
  - saved != saved 的空壳 → 直接删除（sqlite）
  - 已保存的 → 重跑 attach camp（新逻辑：normalized 优先 + 阵营顺序匹配 hero）
    → 重新审核 → 重新保存 → 刷新分析层
"""
import argparse
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / 'data' / 'training.sqlite3'


def api(base, path, payload=None):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    headers = {'Content-Type': 'application/json'} if data else {}
    request = urllib.request.Request(base + path, data=data, headers=headers,
                                     method='POST' if data is not None else 'GET')
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        return error.code, {'detail': error.read().decode('utf-8', 'replace')[:200]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8766')
    args = parser.parse_args()
    connection = sqlite3.connect(DB)
    rows = connection.execute('SELECT id, body FROM channels').fetchall()
    seed = [(row_id, json.loads(body)) for row_id, body in rows
            if '验证数据' in (body or '')]
    kept, removed = [], []
    for row_id, channel in seed:
        if (channel.get('saved') or {}).get('status') == 'saved':
            kept.append((row_id, channel))
        else:
            removed.append(row_id)
    print(f'验证通道：保留 {len(kept)} · 删除空壳 {len(removed)}')
    for row_id in removed:
        connection.execute('DELETE FROM channels WHERE id = ?', (row_id,))
    connection.commit()
    connection.close()
    ok = failed = 0
    for row_id, channel in kept:
        game_seq = ((channel.get('official') or {}).get('id') or '')[5:]
        status, value = api(args.base, f'/api/channels/{row_id}/camp',
                            {'gameSeq': game_seq, 'actor': '修复脚本'})
        if status != 200:
            print(f'  camp 失败 {game_seq}: {value}')
            failed += 1
            continue
        api(args.base, f'/api/channels/{row_id}/review',
            {'reviewedBy': '验证脚本', 'notes': '功能验证数据'})
        status, value = api(args.base, f'/api/channels/{row_id}/save', {})
        if status != 200:
            print(f'  save 失败 {game_seq}: {value}')
            failed += 1
            continue
        heroes = [p.get('hero') for p in (value.get('bundle') or {}).get('players') or []][:5]
        ok += 1
        print(f'  重建 {game_seq} · heroes {heroes}')
    status, _ = api(args.base, '/api/analysis/reload', {})
    print(f'完成：成功 {ok} · 失败 {failed} · reload {status}')


if __name__ == '__main__':
    main()
