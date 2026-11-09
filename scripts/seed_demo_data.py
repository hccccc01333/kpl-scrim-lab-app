#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed a synthetic demo dataset for README screenshots.

Everything here is fabricated: team names, player names and match results are
invented for illustration. No real match, account or nickname is used.

    python scripts/seed_demo_data.py --base http://127.0.0.1:8766

The script talks to the running server through its own HTTP API, so the
seeded data goes through the same validation path as manual entry.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROSTER = [
    ('demo-p1', '示例选手·一', '对抗路'),
    ('demo-p2', '示例选手·二', '打野'),
    ('demo-p3', '示例选手·三', '中路'),
    ('demo-p4', '示例选手·四', '发育路'),
    ('demo-p5', '示例选手·五', '游走'),
]

ENEMY_ROSTER = [
    ('演示对手·甲', '对抗路'),
    ('演示对手·乙', '打野'),
    ('演示对手·丙', '中路'),
    ('演示对手·丁', '发育路'),
    ('演示对手·戊', '游走'),
]

HEROES = [
    '孙悟空', '吕布', '诸葛亮', '公孙离', '廉颇',
    '韩信', '娜可露露', '不知火舞', '马可波罗', '鬼谷子',
    '赵云', '铠', '王昭君', '伽罗', '张飞',
    '花木兰', '兰陵王', '甄姬', '后羿', '牛魔',
]

POSITIONS = ['对抗路', '打野', '中路', '发育路', '游走']
SESSIONS = ['训练赛', '内部对抗', 'BO5', 'BO3']
VERSIONS = ['S41', 'S40', 'S39']


def call(base, path, payload=None, method=None):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    headers = {'Content-Type': 'application/json'} if data else {}
    request = urllib.request.Request(
        base + path, data=data, headers=headers,
        method=method or ('POST' if data is not None else 'GET'))
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        return error.code, {'detail': error.read().decode('utf-8', 'replace')[:300]}


def build_players(rng):
    """Ten player slots: five roster players plus five opponents.

    Kill totals are derived from the score so the record passes the same
    consistency checks a manually entered match has to pass.
    """
    players = []
    left_heroes = rng.sample(HEROES, 5)
    right_heroes = rng.sample([h for h in HEROES if h not in left_heroes], 5)
    for index in range(5):
        players.append({
            'side': 'left', 'slot': index,
            'playerId': ROSTER[index][0], 'name': ROSTER[index][1],
            'position': ROSTER[index][2], 'hero': left_heroes[index],
            'kills': 0, 'deaths': 0, 'assists': 0,
            'gold': rng.randint(6000, 12000),
            'damage': rng.randint(4000, 22000),
            'taken': rng.randint(1000, 9000),
        })
    for index in range(5):
        players.append({
            'side': 'right', 'slot': index,
            'playerId': '', 'name': ENEMY_ROSTER[index][0],
            'position': ENEMY_ROSTER[index][1], 'hero': right_heroes[index],
            'kills': 0, 'deaths': 0, 'assists': 0,
            'gold': rng.randint(5500, 12500),
            'damage': rng.randint(3500, 24000),
            'taken': rng.randint(800, 9500),
        })
    return players


def spread_kills(players, side, total, rng):
    """Distribute a team's kill count across its five players."""
    team = [p for p in players if p['side'] == side]
    remaining = total
    for index, player in enumerate(team):
        if index == len(team) - 1:
            share = remaining
        else:
            share = min(remaining, rng.randint(0, max(1, total // 2)))
            remaining -= share
        player['kills'] = max(0, share)
        player['deaths'] = rng.randint(0, 5)
        player['assists'] = rng.randint(0, 8)
    return players


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8766')
    parser.add_argument('--games', type=int, default=12)
    parser.add_argument('--with-camp', action='store_true',
                        help='同时写营地阵容面板与数据包（战队档案 / 英雄榜 / BP 页需要）')
    args = parser.parse_args()

    status, health = call(args.base, '/api/health')
    if status != 200:
        raise SystemExit('服务未启动：' + args.base)

    if args.with_camp:
        # 服务端在 /api/health 里报了真实数据目录，面板和 bundle 直接写进去。
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import make_mock_camps

        data_dir = Path(health['matchesDir']).parent
        info = make_mock_camps.generate(data_dir)
        print(f"camp panels: {info['games']} 局 -> {info['panels']}")
        print(f"bundles: {info['matches']}")

        # 聚类出来的战队默认叫「待命名战队 #N」，给它们补上演示队名。
        names = list(make_mock_camps.BUNDLE_NAMES.values())
        status, listing = call(args.base, '/api/studio/teams')
        renamed = 0
        assigned = 0
        for team in (listing or {}).get('teams') or []:
            if str(team.get('name') or '').strip():
                continue  # 已经命过名的战队不动
            # 面板里的昵称带战队前缀（青岚·辰 / 白虎·刀），队名直接从它推出来；
            # 推不出来的（替补簇等）按顺序补一个。
            players = team.get('players') or []
            first = players[0] if players else ''
            raw = first.get('name') if isinstance(first, dict) else str(first)
            prefix = raw.split('·')[0].strip() if raw and '·' in raw else ''
            if prefix:
                label = f'{prefix}战队'
            elif assigned < len(names):
                label = names[assigned]
            else:
                label = f'{names[assigned % len(names)]}{assigned - len(names) + 2}'
            code, _ = call(args.base, '/api/studio/teams/rename',
                           {'id': team['id'], 'name': label}, method='POST')
            if code == 200:
                renamed += 1
            assigned += 1
        print(f"teams renamed: {renamed}")

    rng = random.Random(20261105)

    status, body = call(args.base, '/api/settings', {
        'teamName': '示例战队',
        'roster': [
            {'id': pid, 'name': name, 'position': pos, 'team': '示例战队'}
            for pid, name, pos in ROSTER
        ],
    }, method='PUT')
    print('settings:', status, body if status != 200 else 'ok')

    created = 0
    for index in range(args.games):
        players = build_players(rng)
        left_score = rng.randint(5, 18)
        right_score = rng.randint(5, 18)
        spread_kills(players, 'left', left_score, rng)
        spread_kills(players, 'right', right_score, rng)
        match = {
            'date': f'2026-1{1 + index % 2}-{index % 9 + 1:02d}',
            'opponent': rng.choice(['星轨战队', '潮汐战队', '熔岩战队', '青岚战队']),
            'version': rng.choice(VERSIONS),
            'session': rng.choice(SESSIONS),
            'side': 'left', 'winner': 'left' if left_score > right_score else 'right',
            'scores': {'left': left_score, 'right': right_score},
            # /api/matches 的 duration 单位是分钟（手动录入表单也是分钟），
            # 后端会换算成秒；这里写秒会让首页显示「1805:00」这种离谱时长。
            'duration': rng.randint(18, 32),
            'status': 'confirmed',
            'reviewed': True,
            'players': players,
            'bp': '',
            'events': [],
            'notes': '演示用合成记录。',
        }
        status, body = call(args.base, '/api/matches', match)
        if status == 200:
            created += 1
        else:
            print('  match failed:', status, body)
    print('matches created:', created)


if __name__ == '__main__':
    main()
