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
import urllib.error
import urllib.request

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
    args = parser.parse_args()

    status, _ = call(args.base, '/api/health')
    if status != 200:
        raise SystemExit('服务未启动：' + args.base)

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
            'duration': rng.randint(1100, 1900),
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
