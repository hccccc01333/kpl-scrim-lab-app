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

# 演示用虚构人名。教练档案页读的是「战队档案」里的 coach 字段：
# 本队教练存在 settings.coach，对手教练存在战队覆盖层 / 工作区 teams.coach。
OWN_COACH = '示例教练'
TEAM_COACHES = [
    ('青岚', '陈砚'), ('赤霄', '林澈'), ('苍梧', '周衍'), ('白虎', '沈舟'),
    ('流云', '顾言'), ('惊蛰', '苏禾'), ('逐风', '唐越'),
]
SPARE_COACHES = ['许棠', '陆川', '江野', '温言']
# make_mock_camps 从 900000 起按 137 递增写面板；真实营地 seq 是十位数。
DEMO_SEQ_START = 900000
DEMO_SEQ_STOP = 1000000


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


def load_mock_camps():
    """导入同目录的演示营地生成器（脚本直接运行时 scripts/ 已在 sys.path）。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import make_mock_camps
    return make_mock_camps


def coach_name(label, taken):
    """按队名前缀挑一个不重名的虚构教练名。"""
    for prefix, name in TEAM_COACHES:
        if prefix in (label or '') and name not in taken:
            return name
    for name in SPARE_COACHES:
        if name not in taken:
            return name
    return '示例教练'


def camp_panels(data_dir):
    folder = Path(data_dir) / 'camp_details'
    return sorted(folder.glob('*.json')) if folder.is_dir() else []


def is_demo_panel(path):
    stem = Path(path).stem
    return stem.isdigit() and DEMO_SEQ_START <= int(stem) < DEMO_SEQ_STOP


def has_bundles(data_dir):
    folder = Path(data_dir) / 'matches'
    return folder.is_dir() and any(folder.glob('*.json'))


def prepare_camps(data_dir, force):
    """准备演示营地数据，返回 (是否生成, 是否演示数据, mock 模块)。

    教练档案 / 战队档案 / BP 页只读营地十人面板，所以纯 12 场对局记录
    撑不起这些页面。全新演示目录自动补一套面板；目录里已有非演示面板时
    绝不覆盖，避免把真实数据洗掉。``--with-camp`` 只强制刷新演示面板。
    """
    panels = camp_panels(data_dir)
    demo_only = bool(panels) and all(is_demo_panel(path) for path in panels)
    if panels and not demo_only:
        print('camp panels: 检测到已有营地数据，跳过演示面板生成以免覆盖')
        return False, False, None
    if not force:
        if panels:  # 上次 seed 已经写过演示面板，直接复用
            return False, True, load_mock_camps()
        if has_bundles(data_dir):
            print('camp panels: 已存在对局数据包，跳过自动生成（需要演示营地请加 --with-camp）')
            return False, False, None
    mock = load_mock_camps()
    info = mock.generate(data_dir)
    print(f"camp panels: {info['games']} 局 -> {info['panels']}")
    print(f"bundles: {info['matches']}")
    return True, True, mock


def rename_demo_teams(base, labels):
    """给聚类出来的演示战队补队名和主教练；已命名的真实战队不动。"""
    status, listing = call(base, '/api/studio/teams')
    if status != 200:
        print('teams:', status, listing)
        return 0
    used, renamed, assigned = set(), 0, 0
    for team in (listing or {}).get('teams') or []:
        current_name = str(team.get('name') or '').strip()
        current_coach = str(team.get('coach') or '').strip()
        if current_coach:
            used.add(current_coach)
            continue
        if current_name:
            # 兼容旧版 seed：队名已经写过但教练为空的演示战队，只补教练。
            if not any(prefix in current_name for prefix, _ in TEAM_COACHES):
                continue
            label = current_name
        else:
            # 面板里的昵称带战队前缀（青岚·辰 / 白虎·刀），队名直接从它推出来；
            # 推不出来的（替补簇等）按顺序补一个。
            players = team.get('players') or []
            first = players[0] if players else ''
            raw = first.get('name') if isinstance(first, dict) else str(first)
            prefix = raw.split('·')[0].strip() if raw and '·' in raw else ''
            if prefix:
                label = f'{prefix}战队'
            elif assigned < len(labels):
                label = labels[assigned]
            else:
                label = f'{labels[assigned % len(labels)]}{assigned - len(labels) + 2}'
            assigned += 1
        payload = {'id': team['id'], 'coach': coach_name(label, used)}
        if not current_name:
            payload['name'] = label
        code, body = call(base, '/api/studio/teams/rename', payload, method='POST')
        if code == 200:
            renamed += 1
            used.add(payload['coach'])
        else:
            print('  team rename failed:', code, body)
    print(f'teams renamed: {renamed}')
    return renamed


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

    # 服务端在 /api/health 里报了真实数据目录。营地面板决定战队 / 教练档案
    # / BP 三页有没有内容，所以全新演示目录默认补一套；已有真实面板时只跳过。
    data_dir = Path(health['matchesDir']).parent
    _, demo_camp, mock = prepare_camps(data_dir, args.with_camp)
    if demo_camp and mock is not None:
        rename_demo_teams(args.base, list(mock.BUNDLE_NAMES.values()))

    rng = random.Random(20261105)

    # 先读旧设置再合并：直接 PUT 一份最小设置会把已有的 teams / coach /
    # 赛季等字段整段冲掉。名单也只增不减，服务端不允许丢掉老队员。
    status, state = call(args.base, '/api/state')
    state_ok = status == 200 and isinstance(state, dict)
    existing = {}
    if state_ok:
        existing = state.get('settings') if isinstance(state.get('settings'), dict) else {}
    demo_roster = [
        {'id': pid, 'name': name, 'position': pos, 'team': '示例战队'}
        for pid, name, pos in ROSTER
    ]
    demo_ids = {player['id'] for player in demo_roster}
    old_roster = existing.get('roster') if isinstance(existing.get('roster'), list) else []
    settings_payload = dict(existing)
    settings_payload.update({
        'teamName': '示例战队',
        'roster': [p for p in old_roster
                   if isinstance(p, dict) and p.get('id') not in demo_ids] + demo_roster,
    })
    if not str(settings_payload.get('coach') or '').strip():
        settings_payload['coach'] = OWN_COACH
    status, body = call(args.base, '/api/settings', settings_payload, method='PUT')
    print('settings:', status, body if status != 200 else 'ok')

    existing_ids = {
        str(match.get('id')) for match in (state.get('matches') or [])
        if isinstance(match, dict) and match.get('id')
    } if state_ok else set()
    created = skipped = 0
    for index in range(args.games):
        match_id = f'demo-seed-{index + 1:02d}'
        if match_id in existing_ids:
            skipped += 1
            continue
        players = build_players(rng)
        left_score = rng.randint(5, 18)
        right_score = rng.randint(5, 18)
        spread_kills(players, 'left', left_score, rng)
        spread_kills(players, 'right', right_score, rng)
        match = {
            'id': match_id,
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
            existing_ids.add(match_id)
        else:
            print('  match failed:', status, body)
    print('matches created:', created, f'(skipped existing: {skipped})' if skipped else '')


if __name__ == '__main__':
    main()
