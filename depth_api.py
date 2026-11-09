"""Read-only depth analysis API.

Two workbench-owned data layers, no replay-codec artefacts:

  L1  camp ten-player panels      data/camp_details/*.json          31 games / 310 rows
  L2  camp official replay sync   data/official_replays/camp-*/*    21 matched games
                                  (per-second positions, ~30s team gold, key events,
                                   team fights with per-kill hero ledger, death coords)

The .abc frame-command replay research is deliberately out of scope.  Camp
official replay data is part of the existing camp sync pipeline (server.py
already exposes /api/official/replays), so intra-match time and spatial
analyses are real, cross-game analyses here — not single-game demos.

Nothing writes to source data. Account ids, nicknames and open ids are never
returned: players are mapped to stable anonymous labels. Every analysis
carries its purpose, depth level, sample size and honest boundary.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from bp_camp import POSITION_LANES
from camp_time import camp_times
from paths import data_root
from fastapi import APIRouter, HTTPException, Request

DEPTH_SCALE = [
    {'level': 'D0', 'label': '陈列', 'meaning': '单值与排名，回答「是多少」'},
    {'level': 'D1', 'label': '对照', 'meaning': '与同位置 / 对手 / 全期基线比，回答「偏高还是偏低」'},
    {'level': 'D2', 'label': '交叉', 'meaning': '两个以上维度切片 + 分位，回答「哪类组合不一样」'},
    {'level': 'D3', 'label': '过程', 'meaning': '真实时间轴或空间轨迹，回答「先后顺序与窗口」'},
    {'level': 'D4', 'label': '解释', 'meaning': '效应量 / 置换检验 / 控制混杂；本项目只给描述性证据，不宣称因果'},
    {'level': 'D5', 'label': '预测', 'meaning': '样本量不支持，本项目明确不做'},
]

NUM_FIELDS = {
    'cs': 'killSoldier', 'gold': 'money', 'exp': 'exp', 'level': 'heroLevel',
    'kills': 'killCnt', 'deaths': 'deadCnt', 'assists': 'assistCnt', 'kda': 'kda',
    'heroDamage': 'totalHeroHurtCnt', 'damage': 'totalHurtCnt',
    'taken': 'totalBehurtCnt', 'heroTaken': 'totalBeheroHurtCnt',
    'conversion': 'hurtTransRate', 'takenPerDeath': 'behurtPerDeath',
    'participation': 'joinGamePercent', 'healing': 'healCnt',
    'jungleGold': 'monsterCoin', 'control': 'ctrlTime',
    'towerDamage': 'buildingDamage', 'towerCnt': 'towerCnt',
    'mvpScore': 'mvpScoreTth',
}
FIELD_LABELS = {
    'cs': '补刀', 'gold': '总经济', 'level': '等级', 'kills': '击杀', 'deaths': '死亡',
    'assists': '助攻', 'kda': 'KDA', 'heroDamage': '对英雄输出', 'damage': '总输出',
    'taken': '总承伤', 'conversion': '伤害转化比', 'takenPerDeath': '每死承伤',
    'participation': '参团率', 'healing': '治疗量', 'jungleGold': '野怪经济',
    'control': '控制时长', 'towerDamage': '对塔伤害', 'towerCnt': '推塔数',
    'gpm': '分均经济', 'dpm': '分均输出', 'csPerMin': '分均补刀',
    'goldShare': '经济占比', 'damageShare': '对英雄输出占比',
}
# 营地 battleRecords.position 编码 → 中文路名，与 bp_camp.POSITION_LANES 同源
# （映射已按本批营地数据各编码的高频英雄核对）。此前这里直接显示原始编码
# 「分路 0–4」，被误读成未标注的战队分组，故改为中文路名。
LANES = [POSITION_LANES[i] for i in range(5)]

# 营地昵称常夹带零宽字符（如「信则\u2060\u2061有\u2062」），按可见文本认领前先清洗。
_ZERO_WIDTH = {code: None for code in
               (*range(0x200b, 0x2010), *range(0x2060, 0x2065), 0xfeff, *range(0xfe00, 0xfe10))}
_START_MINUTE = re.compile(
    r'(?:(?:\d{4})[-/])?(\d{1,2})[-/](\d{1,2})[ T]+(\d{1,2}):(\d{2})')


def _clean_text(value):
    """去掉零宽字符与首尾空白；昵称和名单索引都走同一套规则。"""
    return str(value or '').translate(_ZERO_WIDTH).strip()


def _start_minute(value):
    """从营地 startTime 取出 'MM-DD HH:MM'；兼容带年份 / ISO 分隔的写法。"""
    text = _clean_text(value)
    if not text:
        return None
    match = _START_MINUTE.match(text)
    if not match:
        return None
    return (f'{int(match.group(1)):02d}-{int(match.group(2)):02d} '
            f'{int(match.group(3)):02d}:{match.group(4)}')


def _build_game_labels(matches, extra_ids, opponents):
    """对局可读标签：'MM-DD HH:MM · vs 对手'，同一分钟多局追加「第k局」。

    标签只用于展示，原始对局 id 字段保持不变。取不到开赛时间时按列表顺序
    生成「vs 对手 · 第N局」/「训练赛 · 第N局」，不把一串数字直接暴露给教练。
    """
    entries, seen = [], set()
    for match in matches:
        game_id = str(match.get('id') or '')
        if not game_id or game_id in seen:
            continue
        seen.add(game_id)
        entries.append((game_id, str(match.get('start') or ''),
                        str(match.get('opponent') or '')))
    for game_id in extra_ids:
        game_id = str(game_id or '')
        if not game_id or game_id in seen:
            continue
        seen.add(game_id)
        entries.append((game_id, '', _clean_text((opponents or {}).get(game_id))))

    labels = {}
    grouped = defaultdict(list)
    unstarted = []
    for index, (game_id, start, opponent) in enumerate(entries, 1):
        minute = _start_minute(start)
        if minute:
            grouped[minute].append((start, game_id, opponent))
        else:
            unstarted.append((index, game_id, opponent))
    for minute, group in grouped.items():
        group.sort(key=lambda item: (item[0], item[1]))
        for index, (_, game_id, opponent) in enumerate(group, 1):
            opponent = _clean_text(opponent or (opponents or {}).get(game_id))
            tail = f' · vs {opponent}' if opponent else ' · 训练赛'
            suffix = f' 第{index}局' if len(group) > 1 else ''
            labels[game_id] = f'{minute}{tail}{suffix}'
    for index, game_id, opponent in unstarted:
        opponent = _clean_text(opponent or (opponents or {}).get(game_id))
        prefix = f'vs {opponent}' if opponent else '训练赛'
        labels[game_id] = f'{prefix} · 第{index}局'
    return labels


def _roster_index(profile):
    """名单索引：memberId → {name, team}；兼容 list / dict 两种 roster 形态。"""
    profile = profile if isinstance(profile, dict) else {}
    roster = profile.get('roster') or profile.get('members') or []
    if isinstance(roster, dict):
        items = []
        for key, value in roster.items():
            if isinstance(value, dict):
                items.append({'id': value.get('id') or key,
                              'name': value.get('name') or value.get('label'),
                              'team': value.get('team')})
            else:
                items.append({'id': key, 'name': value})
    else:
        items = roster if isinstance(roster, list) else []
    members = {}
    for item in items:
        if isinstance(item, dict):
            member_id = _clean_text(item.get('id') or item.get('memberId'))
            name = _clean_text(item.get('name') or item.get('label'))
            team = _clean_text(item.get('team'))
        elif isinstance(item, str):
            member_id = name = _clean_text(item)
            team = ''
        else:
            continue
        if member_id and name:
            members[member_id] = {'name': name, 'team': team}
    return members


def _alias_index(table):
    """昵称 → memberId；key 同样去零宽字符，避免名单里「看起来一样」却认不领。"""
    index = {}
    if isinstance(table, dict):
        for key, value in table.items():
            label = _clean_text(key)
            if label and value not in (None, ''):
                index[label] = str(value)
    return index


def _identity_resolver(profile):
    """把 profile 编译成昵称解析函数：返回 (显示名或 None, 是否已认领)。"""
    profile = profile if isinstance(profile, dict) else {}
    roster = _roster_index(profile)
    aliases = _alias_index(profile.get('aliases'))
    enemy_aliases = _alias_index(profile.get('enemyAliases'))
    team_name = _clean_text(profile.get('teamName'))

    def resolve(nickname):
        nickname = _clean_text(nickname)
        if not nickname:
            return None, False
        member_id = aliases.get(nickname)
        if member_id is None:
            member_id = enemy_aliases.get(nickname)
        member = roster.get(member_id) if member_id is not None else None
        if not member:
            return None, False
        name, team = member['name'], member['team']
        # 与 identity_label 保持一致：跨战队时写成「战队.选手名」，避免同名混淆。
        if team and team != team_name and not name.startswith(team + '.'):
            name = f'{team}.{name}'
        return name, True

    return resolve


def _player_label(player):
    """玩家行的展示名：已认领用名单名，未认领用营地昵称，缺失才退回 P0X。"""
    return player.get('name') or player.get('player') or '未知'


def _filter_players(players, player=None, hero=None):
    player = _clean_text(player) or None
    hero = _clean_text(hero) or None
    if player:
        players = [p for p in players if _player_label(p) == player]
    if hero:
        players = [p for p in players if p.get('hero') == hero]
    return players


def _by_player_rows(players, metrics, sort_key, limit=40):
    """按显示名聚合的中位数下钻表；字段无值就省略，跳过没有任何指标的行。"""
    groups = defaultdict(list)
    for player in players:
        groups[_player_label(player)].append(player)
    rows = []
    for label, group in groups.items():
        row = {'label': label, 'bound': any(bool(p.get('bound')) for p in group),
               'n': len(group)}
        for metric in metrics:
            value = median([p.get(metric) for p in group])
            if value is not None:
                row[metric] = value
        if len(row) > 3:
            rows.append(row)
    rows.sort(key=lambda row: (row.get(sort_key) is None, -(row.get(sort_key) or 0),
                               -row['n'], row['label']))
    return rows[:limit]


def num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        v = float(value)
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def median(values):
    clean = [v for v in values if v is not None]
    return round(statistics.median(clean), 3) if clean else None


def quantile(values, q):
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    return round(clean[min(len(clean) - 1, max(0, int(round((len(clean) - 1) * q))))], 3)


def pearson(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 4:
        return None
    ax = statistics.mean(p[0] for p in pairs)
    ay = statistics.mean(p[1] for p in pairs)
    dx = [p[0] - ax for p in pairs]
    dy = [p[1] - ay for p in pairs]
    den = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    return round(sum(a * b for a, b in zip(dx, dy)) / den, 3) if den else None


def _signature(root, db_path=None, stamp=None):
    parts = []
    for pattern in ('data/camp_details/*.json',
                    'data/official_replays/camp-*/normalized.json',
                    'data/official_replays/camp-*/positions.json',
                    'data/official_replays/camp-*/raw.json'):
        for path in sorted(root.glob(pattern)):
            stat = path.stat()
            parts.append(f'{path.name}:{stat.st_mtime_ns}:{stat.st_size}')
    if db_path is not None:
        # 分边标注写在 match_meta（match_key = 'camp:<gameSeq>'）覆盖层里，
        # 不动数据文件；标注变化也要让 facts 缓存失效。
        try:
            connection = sqlite3.connect(db_path)
            try:
                row = connection.execute(
                    "SELECT COUNT(*), COALESCE(MAX(updated_at), 0) FROM match_meta "
                    "WHERE match_key LIKE 'camp:%'").fetchone()
            finally:
                connection.close()
            parts.append(f'camp-meta:{row[0]}:{row[1]}')
        except sqlite3.OperationalError:
            parts.append('camp-meta:none')
    if stamp is not None and str(stamp) != '':
        # 名单 / 昵称认领的指纹：settings 变化后 facts 必须重建，否则缓存里全是旧绑定。
        parts.append(f'profile:{stamp}')
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()[:16]


def _camp_meta(db_path):
    """读营地局的分边标注：match_meta 里 match_key = 'camp:<gameSeq>' 的覆盖层。

    我方阵营默认由 head.acntCamp（取数账号 = 本方选手账号，1=蓝 2=红）自动推断；
    这里只取教练的手动覆盖（ownCamp: blue/red）与对手命名（opponent）。
    """
    if not db_path:
        return {}
    try:
        connection = sqlite3.connect(db_path)
        try:
            rows = connection.execute(
                "SELECT match_key, body FROM match_meta WHERE match_key LIKE 'camp:%'").fetchall()
        finally:
            connection.close()
    except sqlite3.OperationalError:
        return {}
    result = {}
    for key, body in rows:
        try:
            value = json.loads(body)
        except (TypeError, ValueError):
            continue
        result[str(key)[len('camp:'):]] = value if isinstance(value, dict) else {}
    return result


def _safe_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def build_facts(root: Path, camp_meta=None, profile=None):
    """Load panels and camp official replays once; return JSON-ready facts.

    profile 来自工作台设置（aliases / enemyAliases / roster / teamName + stamp）；
    只有名单里认领过的昵称会变成名单名，未认领的保留营地昵称（便于按选手筛选）。
    """
    players, teams, matches = [], [], []
    anon = {}
    camp_meta = camp_meta or {}
    resolve_identity = _identity_resolver(profile)

    def anonymous(raw):
        raw = str(raw or '')
        if not raw:
            return '未知'
        key = hashlib.sha256(raw.encode()).hexdigest()[:12]
        if key not in anon:
            anon[key] = f'P{len(anon) + 1:02d}'
        return anon[key]

    panel_lane = {}
    for path in sorted((data_root(root) / 'camp_details').glob('*.json')):
        body = _safe_json(path)
        if not body:
            continue
        data = body.get('data') or {}
        battle = data.get('battle') or {}
        head = data.get('head') or {}
        match_id = path.stem
        duration = num(battle.get('usedTime'))
        times = camp_times(body)
        start_text = times.get('startedAt') or battle.get('startTime') or ''
        # 我方阵营：match_meta 的手动覆盖优先，否则用 head.acntCamp 自动推断
        # （营地详情取数账号 = 本方选手账号，1 = 蓝、2 = 红）。
        meta = camp_meta.get(match_id) or {}
        own_camp = {'blue': '蓝', 'red': '红'}.get(str(meta.get('ownCamp') or ''))
        own_source = 'manual' if own_camp else None
        if not own_camp:
            code = num(head.get('acntCamp'))
            own_camp = '蓝' if code == 1 else '红' if code == 2 else None
            own_source = 'auto' if own_camp else None
        matches.append({'id': match_id, 'start': start_text,
                        'duration': duration, 'gameType': battle.get('gameType'),
                        'result': head.get('gameResult'),
                        'ownCamp': own_camp, 'ownCampSource': own_source,
                        'opponent': str(meta.get('opponent') or '')})
        team_money = {}
        for side in ('blueTeam', 'redTeam'):
            team = data.get(side) or {}
            if isinstance(team, dict):
                team_money[team.get('acntCamp')] = num(team.get('money'))
        for side, camp_code in (('blueRoles', 1), ('redRoles', 2)):
            team = data.get('blueTeam' if camp_code == 1 else 'redTeam') or {}
            bans = [x.get('heroName') for x in (team.get('banHeros') or []) if isinstance(x, dict)]
            picks = [x.get('heroName') for x in (team.get('pickHeros') or []) if isinstance(x, dict)]
            teams.append({'match': match_id, 'camp': '蓝' if camp_code == 1 else '红',
                          'result': team.get('gameResult'), 'money': num(team.get('money')),
                          'kills': num(team.get('killCnt')), 'towers': num(team.get('towerCnt')),
                          'bans': [x for x in bans if x], 'picks': [x for x in picks if x],
                          'dragons': {k: num(team.get(k)) for k in
                                      ('ldragon1', 'ldragon2', 'bdragon1', 'bdragon2', 'bdragon3')}})
            for person in data.get(side) or []:
                stats = person.get('battleStats') or {}
                record = person.get('battleRecords') or {}
                basic = person.get('basicInfo') or {}
                hero = (record.get('usedHero') or {}).get('heroName') or ''
                equips = [e.get('equipName') for e in (record.get('finalEquips') or []) if isinstance(e, dict)]
                lane = num(record.get('position'))
                panel_lane[(match_id, str(camp_code), hero)] = lane
                # 已认领用名单名；未认领用营地昵称，教练才能在「选手」筛选里对上人。
                # 没有昵称时才退回 P0X（不把 playerId 直接写进 facts）。
                raw_name = _clean_text(basic.get('roleName'))
                display_name, bound = resolve_identity(raw_name)
                row = {'match': match_id,
                       'player': display_name or raw_name or anonymous(basic.get('playerId') or basic.get('roleId')),
                       'name': display_name, 'raw': raw_name, 'bound': bound,
                       'camp': '蓝' if camp_code == 1 else '红', 'hero': hero, 'lane': lane,
                       'equips': [e for e in equips if e],
                       'summoner': (record.get('skill') or {}).get('skillName') or '',
                       'duration': duration, 'start': start_text}
                for key, source in NUM_FIELDS.items():
                    row[key] = num(stats.get(source))
                if row['gold'] is not None and duration:
                    row['gpm'] = round(row['gold'] / (duration / 60), 2)
                    row['csPerMin'] = round((row['cs'] or 0) / (duration / 60), 2)
                if row['damage'] is not None and duration:
                    row['dpm'] = round(row['damage'] / (duration / 60), 2)
                if row['gold'] is not None and team_money.get(camp_code):
                    row['goldShare'] = round(row['gold'] / team_money[camp_code] * 100, 2)
                players.append(row)
        for camp_code in (1, 2):
            group = [p for p in players if p['match'] == match_id
                     and p['camp'] == ('蓝' if camp_code == 1 else '红')]
            total = sum(p['heroDamage'] or 0 for p in group)
            for p in group:
                p['damageShare'] = round((p['heroDamage'] or 0) / total * 100, 2) if total else None

    # Camp official replay sync: per-second positions, ~30s team gold, key events,
    # plus team fights / hero kill ledger / death positions rebuilt from raw.json.
    # 回放层只带英雄，不带昵称；按 (对局, 阵营, 英雄) 回连面板行，
    # 让「选手」筛选能作用到位置热区 / 团战贡献 / 掉点这些回放分析。
    identity_by_hero = {(p['match'], p['camp'], p['hero']): _player_label(p)
                        for p in players if p.get('hero')}
    replay_games, replay_players = [], []
    kill_events, fight_facts, fight_rows, death_points = [], [], [], []
    drop_windows, drop_roster = [], []
    position_points = 0
    for folder in sorted((data_root(root) / 'official_replays').glob('camp-*')):
        norm = _safe_json(folder / 'normalized.json')
        pos = _safe_json(folder / 'positions.json')
        if not norm:
            continue
        game_id = folder.name.replace('camp-', '')
        has_panel = (data_root(root) / 'camp_details' / f'{game_id}.json').exists()
        match_meta = norm.get('match') or {}
        duration = num(match_meta.get('durationSec'))
        economy = norm.get('economy') or {}
        diff = [num(v) for v in (economy.get('diff') or [])]
        blue = [num(v) for v in (economy.get('blue') or [])]
        red = [num(v) for v in (economy.get('red') or [])]
        events = norm.get('events') or {}
        flat_events = []
        for kind in ('key', 'extended', 'equipment'):
            for event in events.get(kind) or []:
                if not isinstance(event, dict):
                    continue
                flat_events.append({'t': num(event.get('timeSec')),
                                    'type': event.get('eventType') or kind,
                                    'camp': event.get('killerCamp') or event.get('dtCamp'),
                                    'kind': kind})
        replay_games.append({'id': game_id, 'duration': duration,
                             'winCamp': match_meta.get('winCamp'), 'hasPanel': has_panel,
                             'diff': diff, 'blue': blue, 'red': red, 'events': flat_events})

        battles = norm.get('battles') or {}
        player_map = battles.get('playerMap') or {}
        for fight in battles.get('fights') or []:
            fid = str(fight.get('fightId') or '')
            start = num(fight.get('startSec'))
            for kill in fight.get('kills') or []:
                killer = player_map.get(kill.get('killer') or '') or {}
                victim = player_map.get(kill.get('victim') or '') or {}
                kill_events.append({
                    'game': game_id, 'fight': fid, 't': num(kill.get('timeSec')),
                    'killer': killer.get('hero') or '', 'killerCamp': kill.get('killerCamp'),
                    'victim': victim.get('hero') or '', 'victimCamp': kill.get('victimCamp'),
                    'duration': duration, 'winCamp': match_meta.get('winCamp')})
            for row in fight.get('details') or []:
                obj = row.get('objID') or ''
                info = player_map.get(obj) or {}
                hero = info.get('hero') or ''
                camp_code = str(row.get('camp') or '')
                fight_rows.append({
                    'game': game_id, 'fight': fid, 't': start, 'objID': obj,
                    'hero': hero, 'camp': '蓝' if camp_code == '1' else '红',
                    'player': identity_by_hero.get((game_id, '蓝' if camp_code == '1' else '红', hero), ''),
                    'lane': panel_lane.get((game_id, camp_code, hero)),
                    'hurt': num(row.get('hurt')), 'taken': num(row.get('taken')),
                    'heal': num(row.get('heal')),
                    'hardCtrl': num(row.get('hardCtrl')), 'softCtrl': num(row.get('softCtrl')),
                    'support': num(row.get('support')),
                    'kills': num(row.get('kills')), 'deaths': num(row.get('deaths')),
                    'assists': num(row.get('assists')),
                    'lowHP': num(row.get('lowHP')), 'beginHP': num(row.get('beginHP')),
                    'endHP': num(row.get('endHP')), 'ultimates': num(row.get('ultimates'))})
            fight_facts.append({
                'game': game_id, 'fight': fid, 'start': start,
                'end': num(fight.get('endSec')), 'duration': duration,
                'firstCamp': fight.get('firstKillerCamp'),
                'camp1': num(fight.get('camp1')), 'camp2': num(fight.get('camp2')),
                'participants': len(fight.get('participants') or []),
                'kills': len(fight.get('kills') or []),
                'winCamp': match_meta.get('winCamp')})
        for death in battles.get('deaths') or []:
            info = player_map.get(death.get('objID') or '') or {}
            camp_code = str(death.get('camp') or '')
            death_points.append({
                'game': game_id, 't': num(death.get('timeSec')),
                'x': num(death.get('x')), 'y': num(death.get('y')),
                'camp': '蓝' if camp_code == '1' else '红',
                'hero': info.get('hero') or '',
                'player': identity_by_hero.get((game_id, '蓝' if camp_code == '1' else '红',
                                                info.get('hero') or ''), ''),
                'lane': panel_lane.get((game_id, camp_code, info.get('hero') or '')),
                'duration': duration})

        # Death-window (掉点) facts: playBaseInfoArr.deathPosArr timestamps
        # paired with reportData.playerPosInfo.revivePosArr timestamps.  Both
        # are official measured points, not a respawn formula.  A death with no
        # following revive ended with the match (终局未复活).
        raw = _safe_json(folder / 'raw.json') or {}
        raw_data = raw.get('data') or {}
        dur = duration or 0
        obj_to_play = {str(p.get('inBattleObjID') or ''): str(p.get('playID') or '')
                       for p in raw_data.get('playBaseInfoArr') or []}
        revive_by_play = {}
        for row in (raw_data.get('reportData') or {}).get('playerPosInfo') or []:
            points = []
            for q in row.get('revivePosArr') or []:
                if isinstance(q, (list, tuple)) and len(q) >= 3:
                    value = num(q[2])
                    if value is not None:
                        points.append(value)
            revive_by_play[str(row.get('playerID') or '')] = sorted(points)
        kill_by_victim = defaultdict(list)
        for fight in battles.get('fights') or []:
            for kill in fight.get('kills') or []:
                killer = (player_map.get(str(kill.get('killer') or '')) or {}).get('hero') or ''
                kill_by_victim[str(kill.get('victim') or '')].append(
                    (num(kill.get('timeSec')), killer, str(fight.get('fightId') or '')))
        for obj, info in player_map.items():
            camp_code = str(info.get('camp') or '')
            hero = info.get('hero') or ''
            drop_roster.append({'game': game_id, 'objID': obj, 'hero': hero,
                                'camp': '蓝' if camp_code == '1' else '红',
                                'player': identity_by_hero.get((game_id, '蓝' if camp_code == '1' else '红', hero), ''),
                                'lane': panel_lane.get((game_id, camp_code, hero))})
        deaths_by_obj = defaultdict(list)
        for death in battles.get('deaths') or []:
            deaths_by_obj[str(death.get('objID') or '')].append(death)
        for obj, deaths in deaths_by_obj.items():
            info = player_map.get(obj) or {}
            camp_code = str(info.get('camp') or '')
            hero = info.get('hero') or ''
            revives = revive_by_play.get(obj_to_play.get(obj, ''), [])
            used = set()
            for death in sorted(deaths, key=lambda d: num(d.get('timeSec')) or 0):
                t = num(death.get('timeSec'))
                if t is None:
                    continue
                pick = next(((j, r) for j, r in enumerate(revives)
                             if j not in used and t < r <= dur and r - t < 120), None)
                if pick:
                    used.add(pick[0])
                    end, final = pick[1], False
                else:
                    end, final = dur, True
                start_blue = _diff_interp(diff, dur, t)
                end_blue = _diff_interp(diff, dur, end)
                if start_blue is None or end_blue is None:
                    continue
                own = 1 if camp_code == '1' else -1
                nearby = [c for c in kill_by_victim.get(obj, [])
                          if c[0] is not None and abs(c[0] - t) <= 5]
                killer, fight_id = '', ''
                if nearby:
                    _, killer, fight_id = min(nearby, key=lambda c: abs(c[0] - t))
                drop_windows.append({
                    'game': game_id, 'objID': obj, 'hero': hero,
                    'camp': '蓝' if camp_code == '1' else '红',
                    'player': identity_by_hero.get((game_id, '蓝' if camp_code == '1' else '红', hero), ''),
                    'lane': panel_lane.get((game_id, camp_code, hero)),
                    't': t, 'end': end, 'final': final, 'windowSec': round(end - t, 1),
                    'x': num(death.get('x')), 'y': num(death.get('y')),
                    'killer': killer, 'fight': fight_id,
                    'startBlue': start_blue, 'endBlue': end_blue,
                    'diffStart': own * start_blue, 'diffEnd': own * end_blue,
                    'loss': own * (start_blue - end_blue),
                    'duration': duration, 'winCamp': match_meta.get('winCamp')})

        pos_by_id = {str(p.get('playerId')): p.get('posArr') or []
                     for p in (pos or {}).get('players') or []}
        for person in norm.get('players') or []:
            pid = str(person.get('playerId'))
            camp = str(person.get('camp'))
            hero = person.get('hero') or ''
            coords = [[num(x), num(y)] for x, y in pos_by_id.get(pid, [])
                      if num(x) is not None and num(y) is not None]
            position_points += len(coords)
            replay_players.append({'game': game_id, 'playerId': pid, 'hero': hero,
                                   'camp': '蓝' if camp == '1' else '红',
                                   'player': identity_by_hero.get((game_id, '蓝' if camp == '1' else '红', hero), ''),
                                   'lane': panel_lane.get((game_id, camp, hero)),
                                   'coords': coords})
    matched = [g for g in replay_games if g['hasPanel']]
    matched_ids = {g['id'] for g in matched}
    replay_players = [p for p in replay_players if p['game'] in matched_ids]
    kill_events = [k for k in kill_events if k['game'] in matched_ids]
    fight_facts = [f for f in fight_facts if f['game'] in matched_ids]
    fight_rows = [r for r in fight_rows if r['game'] in matched_ids]
    death_points = [d for d in death_points if d['game'] in matched_ids]
    drop_windows = [w for w in drop_windows if w['game'] in matched_ids]
    drop_roster = [r for r in drop_roster if r['game'] in matched_ids]

    own_camps = {m['id']: m['ownCamp'] for m in matches if m['ownCamp']}
    opponents = {m['id']: m['opponent'] for m in matches if m['opponent']}
    labels = _build_game_labels(matches, [g['id'] for g in matched], opponents)

    catalog_groups = defaultdict(lambda: {'label': '', 'bound': False, 'n': 0})
    for row in players:
        item = catalog_groups[_player_label(row)]
        item['label'] = _player_label(row)
        item['bound'] = item['bound'] or bool(row.get('bound'))
        item['n'] += 1
    players_catalog = sorted(catalog_groups.values(),
                             key=lambda item: (-item['n'], item['label']))

    camp_summary = {
        'games': len(matches),
        'auto': sum(1 for m in matches if m['ownCampSource'] == 'auto'),
        'manual': sum(1 for m in matches if m['ownCampSource'] == 'manual'),
        'named': len(opponents),
        'opponents': [{'name': name, 'games': count} for name, count in
                      Counter(m['opponent'] for m in matches if m['opponent']).most_common()],
    }
    return {'players': players, 'teams': teams, 'matches': matches,
            'replayGames': matched, 'replayPlayers': replay_players,
            'killEvents': kill_events, 'fightFacts': fight_facts,
            'fightRows': fight_rows, 'deathPoints': death_points,
            'dropWindows': drop_windows, 'dropRoster': drop_roster,
            'ownCamps': own_camps, 'opponents': opponents, 'campMeta': camp_summary,
            'labels': labels, 'playersCatalog': players_catalog,
            'counts': {'games': len(matches), 'players': len(players), 'teams': len(teams),
                       'anonymousPlayers': len(anon), 'replayGames': len(matched),
                       'positionPoints': position_points,
                       'events': sum(len(g['events']) for g in matched),
                       'fights': len(fight_facts), 'heroKills': len(kill_events),
                       'fightRows': len(fight_rows), 'deathPoints': len(death_points),
                       'dropWindows': len(drop_windows),
                       'dropRevived': sum(1 for w in drop_windows if not w['final']),
                       'dropFinal': sum(1 for w in drop_windows if w['final'])}}


def _coverage(players, key):
    have = sum(1 for p in players if p.get(key) is not None)
    return {'have': have, 'total': len(players), 'pct': round(have / len(players) * 100) if players else 0}


def _lane_of(p):
    lane = p.get('lane')
    return LANES[int(lane)] if lane is not None and 0 <= int(lane) < len(LANES) else '未标注'


def _gold_at(game, seconds):
    diff = game['diff']
    if not diff or not game['duration']:
        return None
    step = game['duration'] / max(1, len(diff) - 1)
    idx = min(len(diff) - 1, max(0, round(seconds / step)))
    return diff[idx]


def _diff_interp(diff, duration, seconds):
    """Blue-minus-red team gold at an arbitrary second, linear interpolation.

    Camp only stores ~30s gold samples.  A death window (median 30s) can start
    and end inside the same sample bucket, so nearest-point lookup would hide
    the whole effect.  Interpolated values are rounded to 10 gold and must be
    labelled as approximate; nothing here is a per-player gold ledger.
    """
    clean = [v for v in diff if v is not None]
    if not clean or not duration:
        return None
    step = duration / max(1, len(clean) - 1)
    x = min(len(clean) - 1, max(0.0, seconds / step))
    i = int(x)
    j = min(len(clean) - 1, i + 1)
    value = clean[i] + (clean[j] - clean[i]) * (x - i)
    return int(round(value / 10.0) * 10)


def _drop_chains(windows):
    """Merge overlapping death windows into one non-double-counted cluster.

    Five players dying in the same fight all overlap the same team-gold swing.
    Summing their per-window losses would count that swing five times, so the
    cluster view reports one blue-minus-red change per contiguous window group.
    """
    by_game = defaultdict(list)
    for w in windows:
        by_game[w['game']].append(w)
    chains = []
    for game, group in by_game.items():
        group.sort(key=lambda w: w['t'])
        current = []
        for w in group + [None]:
            if w is not None and current and w['t'] <= max(x['end'] for x in current) + 3:
                current.append(w)
                continue
            if current:
                last = max(current, key=lambda x: x['end'])
                blue = sum(1 for x in current if x['camp'] == '蓝')
                chains.append({
                    'game': game, 't': min(x['t'] for x in current), 'end': last['end'],
                    'n': len(current), 'blue': blue, 'red': len(current) - blue,
                    'heroes': [x['hero'] for x in current],
                    'startBlue': current[0]['startBlue'], 'endBlue': last['endBlue'],
                    'swing': last['endBlue'] - current[0]['startBlue'],
                    'final': any(x['final'] for x in current),
                    'duration': current[0]['duration'],
                })
            current = [w] if w is not None else []
    chains.sort(key=lambda c: (c['game'], c['t']))
    return chains


def _apply_side(facts, side, team=None):
    """按「我方 / 对方（可再限定某个对手战队）」过滤行级 facts，返回过滤后的副本。

    ownCamps 给出每局我方所在的营地方（蓝/红），由 head.acntCamp 自动推断、
    match_meta（camp:<gameSeq>）可手动覆盖；该局无法判定我方时其行不计入。
    双边过程数据（killEvents / fightFacts / replayGames / matches）不过滤：
    击杀与经济差本来就是两方对照，单边视角只过滤行级明细。
    """
    if side not in ('own', 'opp'):
        return facts
    own_camps = facts.get('ownCamps') or {}
    opponents = facts.get('opponents') or {}

    def keep(row):
        game = row.get('game') or row.get('match')
        own = own_camps.get(game)
        if own is None:
            return False
        if side == 'own':
            return row.get('camp') == own
        if team and opponents.get(game) != team:
            return False
        return row.get('camp') != own

    result = dict(facts)
    for key in ('players', 'teams', 'replayPlayers', 'fightRows',
                'deathPoints', 'dropWindows', 'dropRoster'):
        result[key] = [row for row in facts.get(key, []) if keep(row)]
    return result


def _filter_matches(facts, team=None, date_from=None, date_to=None, match_id=None):
    """先按对局筛选，再用同一批局计算面板与回放结果。"""
    team = _clean_text(team) or None
    if not (team or date_from or date_to or match_id):
        return facts
    opponents = facts.get('opponents') or {}
    match_ids = set()
    for match in facts.get('matches') or []:
        key = str(match.get('id'))
        if match_id and key != match_id:
            continue
        if team and _clean_text(opponents.get(key)) != team:
            continue
        if date_from or date_to:
            try:
                played = date.fromisoformat(_clean_text(match.get('start'))[:10])
            except ValueError:
                continue
            if (date_from and played < date_from) or (date_to and played > date_to):
                continue
        match_ids.add(key)
    result = dict(facts)
    for key in ('matches', 'teams', 'players', 'replayGames', 'replayPlayers',
                'killEvents', 'fightFacts', 'fightRows', 'deathPoints',
                'dropWindows', 'dropRoster'):
        rows = []
        for row in facts.get(key) or []:
            game = str(row.get('game') or row.get('match') or row.get('id') or '')
            if game in match_ids:
                rows.append(row)
        result[key] = rows
    return result


def analysis_payload(facts, analysis_id, game_id=None, side=None, team=None,
                     player=None, hero=None, metric=None, date_from=None, date_to=None, match_id=None):
    facts = _filter_matches(facts, team, date_from, date_to, match_id)
    facts = _apply_side(facts, side, team)
    players = _filter_players(facts['players'], player, hero)
    pool_players = facts['players']
    teams = facts['teams']
    games = facts['replayGames']
    n = len(players)
    labels = facts.get('labels') or {}

    def replay_rows(key):
        rows = facts.get(key) or []
        if player:
            rows = [row for row in rows if row.get('player') == player]
        if hero:
            rows = [row for row in rows if row.get('hero') == hero]
        return rows

    replay_players = replay_rows('replayPlayers')
    fight_rows = replay_rows('fightRows')
    death_points = replay_rows('deathPoints')
    drop_windows = replay_rows('dropWindows')
    drop_roster = replay_rows('dropRoster')
    if player:
        visible = ({row.get('game') for row in replay_players}
                   | {row.get('game') for row in fight_rows}
                   | {row.get('game') for row in death_points}
                   | {row.get('game') for row in drop_windows})
        games = [g for g in games if g['id'] in visible]

    def game_label(value):
        key = str(value or '')
        return labels.get(key) or ('未命名对局' if key else '—')

    if analysis_id == 'cross_lane_hero':
        metric = 'csPerMin'
        groups = defaultdict(list)
        for p in players:
            if p['lane'] is not None and p['hero'] and p.get(metric) is not None:
                groups[(_lane_of(p), p['hero'])].append(p[metric])
        heroes = [h for h, _ in Counter(p['hero'] for p in players if p['hero']).most_common(12)]
        rows = LANES + ['未标注']
        cells = [[{'value': median(groups.get((lane, hero), [])),
                   'n': len(groups.get((lane, hero), []))} for hero in heroes] for lane in rows]
        lane_stats = [{'label': lane, 'n': sum(1 for p in players if _lane_of(p) == lane),
                       'median': median([p.get(metric) for p in players if _lane_of(p) == lane])}
                      for lane in rows]
        return {'viz': 'matrix', 'rows': rows, 'cols': heroes, 'cells': cells,
                'unit': '分均补刀', 'laneStats': lane_stats,
                'note': ('分路已按营地坐标映射为中文路名：对抗路 / 中路 / 发育路 / 打野 / 游走；'
                         '带斜纹的格子样本不足 3 局，别读结论。')}

    if analysis_id == 'cross_resource_output':
        pts = [p for p in players if p.get('goldShare') is not None and p.get('damageShare') is not None]
        return {'viz': 'scatter',
                'points': [{'x': p['goldShare'], 'y': p['damageShare'], 'label': p['hero'],
                            'group': _lane_of(p),
                            'detail': f"{_player_label(p)} · 对英雄输出 {(p['heroDamage'] or 0):,.0f}"}
                           for p in pts],
                'xLabel': '经济占比 %', 'yLabel': '对英雄输出占比 %',
                'ref': {'x': median([p['goldShare'] for p in pts]),
                        'y': median([p['damageShare'] for p in pts])},
                'corr': pearson([p['goldShare'] for p in pts], [p['damageShare'] for p in pts]),
                'byPlayer': _by_player_rows(
                    players, ('cs', 'gold', 'heroDamage', 'conversion', 'gpm',
                              'goldShare', 'damageShare'), 'damageShare'),
                'note': '右上 = 吃得多打得多，右下 = 吃得多打得少。占比按同局五人合计，输出只算对英雄伤害。'}

    if analysis_id == 'cs_conversion':
        valid = [p for p in players if p.get('cs') is not None and p.get('gold') is not None]
        pairs = [{'x': p['cs'], 'y': p['gold'], 'label': p['hero'], 'group': _lane_of(p),
                  'detail': f"野怪经济 {p['jungleGold'] or 0:,.0f}"} for p in valid]
        second = [{'x': p['gold'], 'y': p['heroDamage'], 'label': p['hero'], 'group': _lane_of(p),
                   'detail': f"转化比 {p['conversion']}"}
                  for p in valid if p.get('heroDamage') is not None]
        lanes = []
        for lane in LANES:
            values = [p['cs'] for p in players if _lane_of(p) == lane and p.get('cs') is not None]
            lanes.append({'label': lane, 'n': len(values), 'p25': quantile(values, .25),
                          'p50': median(values), 'p75': quantile(values, .75), 'p90': quantile(values, .9)})
        return {'viz': 'chain',
                'links': [{'title': '补刀 → 总经济', 'points': pairs, 'xLabel': '补刀数', 'yLabel': '总经济',
                           'corr': pearson([p['x'] for p in pairs], [p['y'] for p in pairs])},
                          {'title': '总经济 → 对英雄输出', 'points': second, 'xLabel': '总经济',
                           'yLabel': '对英雄输出',
                           'corr': pearson([p['x'] for p in second], [p['y'] for p in second])}],
                'lanes': lanes,
                'byPlayer': _by_player_rows(
                    players, ('cs', 'gold', 'heroDamage', 'conversion', 'gpm',
                              'goldShare', 'damageShare'), 'conversion'),
                'note': '三段链条只看「相关」不看因果；补刀和经济只有终局值，没有先后顺序，r 越接近 1 两端越同步。'}

    if analysis_id == 'equip_matrix':
        counts = defaultdict(Counter)
        lane_total = Counter(_lane_of(p) for p in players)
        for p in players:
            for item in p['equips']:
                counts[_lane_of(p)][item] += 1
        top = Counter(i for p in players for i in p['equips']).most_common(14)
        cols = [i for i, _ in top]
        rows = LANES + ['未标注']
        cells = [[{'value': round(counts[lane][item] / max(1, lane_total[lane]) * 100, 1),
                   'n': counts[lane][item]} for item in cols] for lane in rows]
        return {'viz': 'matrix', 'rows': rows, 'cols': cols, 'cells': cells,
                'unit': '该分路携带率 %',
                'items': [{'label': i, 'count': c, 'pct': round(c / n * 100, 1)} for i, c in top],
                'note': '按终局六格统计携带率；看不出出装顺序，也别用来判断装备成型快慢。'}

    if analysis_id == 'equip_impact':
        top = [i for i, _ in Counter(i for p in players for i in p['equips']).most_common(12)]
        metrics = ['conversion', 'gpm', 'takenPerDeath']
        rows = []
        for item in top:
            with_rows = [p for p in players if item in p['equips']]
            without = [p for p in players if item not in p['equips']]
            deltas = {}
            for metric in metrics:
                a = median([p.get(metric) for p in with_rows])
                b = median([p.get(metric) for p in without])
                deltas[metric] = {'with': a, 'without': b,
                                  'delta': round(a - b, 3) if a is not None and b is not None else None}
            rows.append({'label': item, 'withN': len(with_rows), 'withoutN': len(without),
                         'deltas': deltas})
        return {'viz': 'impact', 'rows': rows,
                'metricLabels': {m: FIELD_LABELS[m] for m in metrics},
                'note': '两组中位数之差只是对照读数：英雄、分路、局势都没控制，不能当「这件装备更强」的证据。'}

    if analysis_id == 'time_cross_match':
        by_match = defaultdict(list)
        for p in players:
            by_match[p['match']].append(p)
        meta = {m['id']: m for m in facts['matches']}
        rows = []
        for key, group in sorted(by_match.items(),
                                 key=lambda kv: (meta.get(kv[0], {}).get('start') or '', kv[0])):
            m = meta.get(key, {})
            rows.append({'id': key, 'label': game_label(key),
                         'start': m.get('start') or '', 'duration': m.get('duration'),
                         'avgGpm': median([p.get('gpm') for p in group]),
                         'avgCs': median([p.get('cs') for p in group]),
                         'avgGold': median([p.get('gold') for p in group]),
                         'heroes': [p['hero'] for p in group if p['hero']][:3]})
        hours = Counter()
        for r in rows:
            try:
                hours[int(str(r['start']).split(' ')[-1].split(':')[0])] += 1
            except (ValueError, IndexError):
                continue
        points = [{'x': r['duration'] / 60, 'y': r['avgGpm'], 'label': r['label'], 'group': None,
                   'detail': f"平均补刀 {r['avgCs']}"}
                  for r in rows if r['duration'] and r['avgGpm'] is not None]
        return {'viz': 'timeline', 'games': rows,
                'hours': [{'hour': h, 'count': c} for h, c in sorted(hours.items())],
                'scatter': {'points': points, 'xLabel': '对局时长（分）',
                            'yLabel': '十人分均经济中位数',
                            'corr': pearson([p['x'] for p in points], [p['y'] for p in points])},
                'note': '按开赛时间排序、按时长换算分均指标，是跨局对比不是局内过程曲线；对局集中在同一天，别推断长期趋势。'}

    if analysis_id == 'time_economy':
        landmarks = [120, 300, 600, 900]
        active = [g for g in games if str(g['id']) == str(game_id)] if game_id else list(games)
        if not active:
            active = list(games)
        curves, grid = [], []
        for g in active:
            if not g['diff'] or not g['duration']:
                continue
            step = g['duration'] / max(1, len(g['diff']) - 1)
            curves.append({'id': g['id'], 'label': game_label(g['id']),
                           'duration': g['duration'],
                           'points': [[round(i * step), d] for i, d in enumerate(g['diff']) if d is not None],
                           'winCamp': g['winCamp']})
            grid.append({'id': g['id'], 'label': game_label(g['id']), 'duration': g['duration'],
                         'diffAt': {t: _gold_at(g, t) for t in landmarks},
                         'winCamp': g['winCamp']})
        lead = [r for r in grid if r['diffAt'].get(600) is not None]
        lead_win = sum(1 for r in lead if r['diffAt'][600] > 0 and str(r['winCamp']) == '1')
        return {'viz': 'economy', 'curves': curves, 'grid': grid, 'landmarks': landmarks,
                'games': [{'id': g['id'], 'label': game_label(g['id']),
                           'duration': g['duration'], 'winCamp': g['winCamp']} for g in games],
                'selected': game_id or '',
                'leadAt10': {'n': len(lead), 'blueLead': sum(1 for r in lead if r['diffAt'][600] > 0),
                             'blueLeadWins': lead_win},
                'note': '约 30 秒一个金币点，中间不补数值；检查点取最近的实测值，末列「胜方」来自营地原始字段。'}

    if analysis_id == 'time_events':
        active = [g for g in games if str(g['id']) == str(game_id)] if game_id else list(games)
        if not active:
            active = list(games)
        by_minute = defaultdict(Counter)
        totals = Counter()
        for g in active:
            for e in g['events']:
                if e['t'] is None:
                    continue
                by_minute[int(e['t'] // 60)][e['type']] += 1
                totals[e['type']] += 1
        names = [k for k, _ in totals.most_common(5)]
        minutes = [{'minute': m, 'values': {k: c.get(k, 0) for k in names}}
                   for m, c in sorted(by_minute.items())]
        swings = []
        for g in active:
            for e in g['events']:
                if e['type'] not in ('dragontower', 'killbuff') or e['t'] is None:
                    continue
                before, at, after = (_gold_at(g, e['t'] - 60), _gold_at(g, e['t']),
                                     _gold_at(g, e['t'] + 60))
                if before is None or after is None:
                    continue
                swings.append({'game': g['id'], 'label': game_label(g['id']),
                               't': e['t'], 'type': e['type'],
                               'camp': e['camp'], 'before': before, 'after': after,
                               'delta': round(after - before, 1)})
        return {'viz': 'events', 'minutes': minutes, 'names': names, 'totals': dict(totals),
                'games': [{'id': g['id'], 'label': game_label(g['id']),
                           'duration': g['duration']} for g in games],
                'selected': game_id or '',
                'swings': swings[:120], 'swingCount': len(swings),
                'note': '事件来自官方回放事件表；swing = 事件前后各 60 秒的经济差变化，是时间关联不是因果。'}

    if analysis_id == 'lane_matchup':
        own_camps = facts.get('ownCamps') or {}
        opponents = facts.get('opponents') or {}
        win_camp = {str(g.get('id')): str(g.get('winCamp') or '')
                    for g in facts.get('replayGames') or []}
        for team in facts.get('teams') or []:
            if team.get('result') in (True, 1, '1', 'true'):
                win_camp.setdefault(str(team.get('match')),
                                    '1' if team.get('camp') == '蓝' else '2')
        grouped = defaultdict(list)
        for p in facts.get('players') or []:
            lane = _lane_of(p)
            if lane == '未标注' or not p.get('hero'):
                continue
            grouped[(p['match'], p['camp'], lane)].append(p)

        def kda_of(player):
            values = (player.get('kills'), player.get('deaths'), player.get('assists'))
            if any(value is None for value in values):
                return None
            return (values[0] + values[2]) / max(1, values[1])

        rows = []
        for game, own in own_camps.items():
            enemy = '红' if own == '蓝' else '蓝'
            for (g, camp, lane), people in grouped.items():
                if g != game or camp != own:
                    continue
                if player:
                    people = [p for p in people if _player_label(p) == player]
                enemies = grouped.get((game, enemy, lane)) or []
                if not people or not enemies:
                    continue
                o, e = people[0], enemies[0]
                if o.get('gold') is None or e.get('gold') is None:
                    continue
                gold_diff = o['gold'] - e['gold']
                kda_o, kda_e = kda_of(o), kda_of(e)
                kda_diff = round(kda_o - kda_e, 2) if kda_o is not None and kda_e is not None else None
                damage_diff = (round((o.get('heroDamage') or 0) - (e.get('heroDamage') or 0))
                               if o.get('heroDamage') is not None and e.get('heroDamage') is not None
                               else None)
                winner = win_camp.get(game) or ''
                win = None
                if winner:
                    win = (winner == '1') if own == '蓝' else (winner == '2')
                rows.append({
                    'match': game, 'label': game_label(game),
                    'opponent': opponents.get(game) or '',
                    'lane': lane, 'ownPlayer': _player_label(o), 'ownHero': o.get('hero') or '',
                    'enemyPlayer': _player_label(e), 'enemyHero': e.get('hero') or '',
                    'ownGold': o['gold'], 'enemyGold': e['gold'], 'goldDiff': gold_diff,
                    'ownKda': kda_o, 'enemyKda': kda_e, 'kdaDiff': kda_diff,
                    'ownDamage': o.get('heroDamage'), 'enemyDamage': e.get('heroDamage'),
                    'damageDiff': damage_diff, 'ahead': gold_diff > 0, 'win': win,
                    'winLabel': '胜' if win is True else '负' if win is False else '—'})

        lanes = []
        for lane in LANES:
            group = [row for row in rows if row['lane'] == lane]
            if not group:
                continue
            with_result = [row for row in group if row['win'] is not None]
            ahead = [row for row in group if row['ahead']]
            ahead_with_result = [row for row in ahead if row['win'] is not None]
            lanes.append({
                'lane': lane, 'n': len(group),
                'avgGoldDiff': round(statistics.mean(row['goldDiff'] for row in group)),
                'aheadRate': round(len(ahead) / len(group) * 100, 1),
                'avgKdaDiff': (round(statistics.mean(row['kdaDiff'] for row in group
                                                     if row['kdaDiff'] is not None), 2)
                               if any(row['kdaDiff'] is not None for row in group) else None),
                'winWhenAhead': (round(sum(1 for row in ahead_with_result if row['win'])
                                       / len(ahead_with_result) * 100, 1)
                                 if ahead_with_result else None),
                'winRate': (round(sum(1 for row in with_result if row['win'])
                                  / len(with_result) * 100, 1) if with_result else None)})

        hero_pairs = defaultdict(list)
        for row in rows:
            hero_pairs[(row['ownHero'], row['enemyHero'])].append(row)
        heroes = []
        for (own_hero, enemy_hero), group in hero_pairs.items():
            with_result = [row for row in group if row['win'] is not None]
            heroes.append({'ownHero': own_hero, 'enemyHero': enemy_hero, 'n': len(group),
                           'avgGoldDiff': round(statistics.mean(row['goldDiff'] for row in group)),
                           'aheadRate': round(sum(1 for row in group if row['ahead']) / len(group) * 100, 1),
                           'winRate': (round(sum(1 for row in with_result if row['win'])
                                             / len(with_result) * 100, 1) if with_result else None),
                           'avgKdaDiff': (round(statistics.mean(row['kdaDiff'] for row in group
                                                                if row['kdaDiff'] is not None), 2)
                                          if any(row['kdaDiff'] is not None for row in group) else None)})
        heroes.sort(key=lambda item: (-item['n'], -item['avgGoldDiff']))
        player_pairs = defaultdict(list)
        for row in rows:
            player_pairs[(row['ownPlayer'], row['enemyPlayer'], row['lane'])].append(row)
        players_out = []
        for (own_player, enemy_player, lane), group in player_pairs.items():
            players_out.append({'ownPlayer': own_player, 'enemyPlayer': enemy_player,
                                'lane': lane, 'n': len(group),
                                'avgGoldDiff': round(statistics.mean(row['goldDiff'] for row in group)),
                                'aheadRate': round(sum(1 for row in group if row['ahead']) / len(group) * 100, 1),
                                'winRate': (round(sum(1 for row in group if row['win'])
                                                  / len([row for row in group if row['win'] is not None]) * 100, 1)
                                            if any(row['win'] is not None for row in group) else None)})
        players_out.sort(key=lambda item: (-item['n'], -item['avgGoldDiff']))
        return {'viz': 'matchup', 'lanes': lanes, 'roads': rows,
                'heroes': heroes[:20], 'players': players_out[:20],
                'note': ('只统计「对局分边」能判定我方阵营、且同分路双方各有一人的局；'
                         '经济差 = 我方 − 对方终局金币，KDA 差 = 我方 − 对方。'
                         '这是对线结果对照，不等于个人能力评价，也不能推断因果。')}

    if analysis_id == 'compare_baseline':
        metric_keys = ['gpm', 'dpm', 'participation', 'goldShare', 'damageShare']
        metric_keys = [k for k in metric_keys if k in FIELD_LABELS]
        selected_metric = metric if metric in metric_keys else 'gpm'
        scale = lambda key, value: value * 100 if key == 'participation' and value is not None else value
        pools = {key: defaultdict(list) for key in metric_keys}
        for p in pool_players:
            for key in metric_keys:
                if p.get(key) is not None:
                    pools[key][_lane_of(p)].append(scale(key, p[key]))
        by_player = defaultdict(list)
        for p in players:
            if any(p.get(key) is not None for key in metric_keys):
                by_player[_player_label(p)].append(p)
        rows = []
        for label, group in by_player.items():
            lane = _lane_of(group[0])
            metrics = {}
            for key in metric_keys:
                values = [scale(key, p[key]) for p in group if p.get(key) is not None]
                if not values:
                    metrics[key] = None
                    continue
                value = median(values)
                pool = pools[key][lane]
                rank = (sum(1 for v in pool if v < value) / len(pool) * 100) if pool else None
                metrics[key] = {'value': value, 'baseline': median(pool),
                                'p75': quantile(pool, .75), 'p90': quantile(pool, .9),
                                'percentile': round(rank, 1) if rank is not None else None,
                                'n': len(pool)}
            chosen = metrics.get(selected_metric) or {}
            rows.append({'player': label, 'bound': any(bool(p.get('bound')) for p in group),
                         'lane': lane, 'n': len(group), 'metrics': metrics,
                         'value': chosen.get('value'),
                         'baseline': chosen.get('baseline'), 'p75': chosen.get('p75'),
                         'p90': chosen.get('p90'), 'percentile': chosen.get('percentile'),
                         'heroes': sorted({p['hero'] for p in group if p['hero']})[:4]})
        rows.sort(key=lambda r: (r['value'] is None, -(r['value'] or 0)))
        return {'viz': 'baseline', 'rows': rows[:60], 'metric': FIELD_LABELS[selected_metric],
                'metrics': [{'key': key, 'label': FIELD_LABELS[key]} for key in metric_keys],
                'note': ('同位置 = 对抗路 / 打野 / 中路 / 发育路 / 游走；参照 = 同位置所有已记录行（含对手）的'
                         '中位数与分位。分位只描述这批样本内的相对位置，不评价具体队员。')}

    if analysis_id == 'compare_camp':
        definitions = [('gold', '总经济'), ('heroDamage', '对英雄输出'), ('gpm', '分均经济'),
                       ('taken', '总承伤'), ('towerDamage', '对塔伤害'), ('cs', '补刀')]
        rows = []
        for key, label in definitions:
            blue = [p[key] for p in players if p['camp'] == '蓝' and p.get(key) is not None]
            red = [p[key] for p in players if p['camp'] == '红' and p.get(key) is not None]
            b, r = median(blue), median(red)
            rows.append({'label': label, 'blue': b, 'red': r, 'blueN': len(blue), 'redN': len(red),
                         'deltaPct': round((b - r) / r * 100, 1) if b is not None and r else None})
        by_match = defaultdict(dict)
        for t in teams:
            by_match[t['match']][t['camp']] = t['money']
        diffs = [{'match': k, 'label': game_label(k),
                  'blue': v.get('蓝'), 'red': v.get('红'),
                  'diff': (v.get('蓝') - v.get('红')) if v.get('蓝') is not None and v.get('红') is not None else None}
                 for k, v in sorted(by_match.items())]
        return {'viz': 'camp', 'rows': rows, 'byMatch': diffs,
                'note': '营地是观察者视角，蓝红不固定是我方 / 对手；这张图用来查数据偏差，不是比阵营强弱。'}

    if analysis_id == 'resource_bp':
        bans = Counter(b for t in teams for b in t['bans'])
        picks = Counter(x for t in teams for x in t['picks'])
        objectives = [{'match': t['match'], 'label': game_label(t['match']),
                       'camp': t['camp'], 'towers': t['towers'],
                       'dragons': (sum(v for v in t['dragons'].values() if v is not None)
                                   if any(v is not None for v in t['dragons'].values()) else None),
                       'result': t['result'], 'money': t['money']} for t in teams]
        return {'viz': 'bp',
                'bans': [{'label': k, 'value': v} for k, v in bans.most_common(16)],
                'picks': [{'label': k, 'value': v} for k, v in picks.most_common(16)],
                'objectives': objectives,
                'note': '禁用 / 选用来自营地团队层；龙塔是终局计数，看不出先后节奏，要看节奏用「事件密度」那张图。'}

    if analysis_id == 'stability':
        groups = defaultdict(list)
        for p in players:
            if p.get('kda') is not None:
                groups[p['hero']].append(p['kda'])
        rows = []
        for hero, values in groups.items():
            if len(values) < 2:
                continue
            rows.append({'label': hero, 'n': len(values), 'mean': round(statistics.mean(values), 2),
                         'p10': quantile(values, .1), 'p50': median(values), 'p90': quantile(values, .9),
                         'sd': round(statistics.pstdev(values), 2),
                         'floor': round(min(values), 2), 'ceiling': round(max(values), 2)})
        rows.sort(key=lambda r: -r['n'])
        return {'viz': 'stability', 'rows': rows[:24], 'metric': FIELD_LABELS['kda'],
                'note': '同一英雄聚合了不同选手和对局，看的是英雄波动，不是某个选手的状态稳定性。'}

    if analysis_id == 'time_kill_rhythm':
        active = [g for g in games if str(g['id']) == str(game_id)] if game_id else list(games)
        if not active:
            active = list(games)
        active_ids = {g['id'] for g in active}
        kills = [k for k in facts['killEvents']
                 if k['t'] is not None and k['game'] in active_ids]
        by_minute = defaultdict(Counter)
        for k in kills:
            by_minute[int(k['t'] // 60)]['蓝' if str(k['killerCamp']) == '1' else '红'] += 1
        minutes = [{'minute': m, 'blue': c['蓝'], 'red': c['红']}
                   for m, c in sorted(by_minute.items())]
        phases = []
        for label, lo, hi in (('前期 0–4 分', 0, 240), ('中期 4–10 分', 240, 600),
                              ('后期 10 分+', 600, 10 ** 9)):
            group = [k for k in kills if lo <= k['t'] < hi]
            observed = sum(max(0, min(hi, g['duration'] or 0) - lo) for g in active
                           if (g['duration'] or 0) > lo)
            phases.append({'label': label, 'n': len(group),
                           'pct': round(len(group) / len(kills) * 100, 1) if kills else 0,
                           'rate': round(len(group) / (observed / 60), 2) if observed else None})
        first_blood = []
        for g in active:
            values = [k['t'] for k in kills if k['game'] == g['id']]
            if values:
                first_blood.append(min(values))
        bursts = []
        for g in active:
            buckets = Counter(int(k['t'] // 60) for k in kills if k['game'] == g['id'])
            for minute, count in buckets.items():
                if count >= 3:
                    bursts.append({'game': g['id'], 'label': game_label(g['id']),
                                   't': minute * 60, 'n': count})
        bursts.sort(key=lambda b: (-b['n'], b['game']))
        sizes = Counter(f['kills'] for f in facts['fightFacts'] if f['game'] in active_ids)
        ledger = [{'game': k['game'], 'label': game_label(k['game']),
                   't': k['t'], 'killer': k['killer'],
                   'victim': k['victim'], 'camp': '蓝' if str(k['killerCamp']) == '1' else '红',
                   'fight': k['fight']}
                  for k in sorted(kills, key=lambda x: (x['game'], x['t']))[:30]]
        return {'viz': 'killrhythm', 'minutes': minutes, 'phases': phases,
                'games': [{'id': g['id'], 'label': game_label(g['id']),
                           'duration': g['duration']} for g in games],
                'selected': game_id or '',
                'firstBlood': {'median': median(first_blood), 'p25': quantile(first_blood, .25),
                               'p75': quantile(first_blood, .75), 'n': len(first_blood)},
                'bursts': bursts[:20], 'burstCount': len(bursts),
                'sizes': [{'kills': k, 'fights': v} for k, v in sorted(sizes.items())],
                'ledger': ledger,
                'note': ('击杀时刻来自官方回放逐次记录，与终局面板总击杀逐局一致；'
                         '阶段速率按该阶段实际时长折算，爆发窗口按 60 秒分桶。')}

    if analysis_id == 'death_point_economy':
        wins = drop_windows
        roster = drop_roster
        selected = next((g for g in games if g['id'] == game_id), None)
        if selected is None and games:
            counts = {g['id']: sum(1 for w in wins if w['game'] == g['id']) for g in games}
            typical = median(list(counts.values()))
            selected = min(games, key=lambda g: (abs(counts[g['id']] - typical), g['id']))
        selected_id = selected['id'] if selected else None
        g_wins = [w for w in wins if w['game'] == selected_id]
        g_roster = [r for r in roster if r['game'] == selected_id]
        by_obj = defaultdict(list)
        for w in g_wins:
            by_obj[w['objID']].append(w)
        window_keys = ('t', 'end', 'final', 'windowSec', 'diffStart', 'diffEnd',
                       'loss', 'killer', 'fight', 'x', 'y')
        teams_out = []
        for camp in ('蓝', '红'):
            people = []
            for r in g_roster:
                if r['camp'] != camp:
                    continue
                ws = sorted(by_obj.get(r['objID'], []), key=lambda w: w['t'])
                people.append({
                    'hero': r['hero'], 'lane': _lane_of(r),
                    'windows': [{k: w[k] for k in window_keys} for w in ws],
                    'n': len(ws),
                    'totalLoss': sum(w['loss'] for w in ws),
                    'avgLoss': round(statistics.mean([w['loss'] for w in ws])) if ws else None,
                    'maxLoss': max((w['loss'] for w in ws), default=None)})
            people.sort(key=lambda p: (p['lane'] == '未标注', str(p['lane'])))
            teams_out.append({'camp': camp, 'people': people,
                              'deaths': sum(p['n'] for p in people),
                              'totalLoss': sum(p['totalLoss'] for p in people)})
        curve = []
        if selected and selected['diff'] and selected['duration']:
            step = selected['duration'] / max(1, len(selected['diff']) - 1)
            curve = [[round(i * step), d] for i, d in enumerate(selected['diff'])
                     if d is not None]
        chains = _drop_chains(g_wins)
        worst = max(g_wins, key=lambda w: w['loss']) if g_wins else None
        game_options = [{'id': g['id'], 'label': game_label(g['id']),
                         'duration': g['duration'],
                         'deaths': sum(1 for w in wins if w['game'] == g['id']),
                         'winCamp': g['winCamp']} for g in games]
        return {
            'viz': 'dropwindow', 'games': game_options, 'selected': selected_id,
            'selectedLabel': game_label(selected_id) if selected_id else None,
            'duration': selected['duration'] if selected else None,
            'winCamp': selected['winCamp'] if selected else None,
            'teams': teams_out, 'curve': curve,
            'chains': [{**chain, 'label': game_label(chain['game'])} for chain in chains],
            'headline': {
                'deaths': len(g_wins),
                'final': sum(1 for w in g_wins if w['final']),
                'sumWindowLoss': sum(w['loss'] for w in g_wins),
                'chains': len(chains),
                'chainSwing': sum(abs(c['swing']) for c in chains),
                'worst': ({'hero': worst['hero'], 'camp': worst['camp'],
                           't': worst['t'], 'loss': worst['loss'],
                           'killer': worst['killer']} if worst else None)},
            'note': ('阵亡和复活时刻都是官方实测点（终局未复活按对局结束计）。'
                     '金币差约 30 秒一个点，窗口两端是插值约数；正数 = 本队经济差恶化。'
                     '窗口内还有兵线、野怪、推塔等其他收入，是时间关联不是阵亡本身的净损失；'
                     '同一团战多人阵亡时窗口重叠，逐笔别相加，团队口径看下方「掉点集群」。')}

    raise HTTPException(status_code=404, detail='未知分析')


def analyses_catalog(facts):
    players = facts['players']
    n = len(players)
    cov = {k: _coverage(players, k) for k in
           ('cs', 'gold', 'heroDamage', 'conversion', 'jungleGold', 'lane', 'gpm', 'goldShare', 'damageShare')}
    games = facts['counts']['games']
    replay_games = facts['counts']['replayGames']
    points = facts['counts']['positionPoints']

    def item(aid, direction, title, subtitle, purpose, level, status, samples, boundary, viz, fields,
             sided=True):
        # sided=False：双边过程图与全队层面的分析；filters 告诉前端该分析可用的
        # 筛选器：side（我方/对方）/ team（按对手战队）/ player / hero。
        filters = ['side'] if sided else []
        if aid in ('cs_conversion', 'cross_resource_output',
                   'cross_teamfight_contribution', 'death_point_economy',
                   'death_point_impact', 'space_heatmap', 'space_lane', 'space_deaths'):
            filters = ['side', 'player']
        elif aid in ('cross_lane_hero', 'equip_matrix', 'equip_impact', 'stability'):
            filters = ['side', 'hero']
        elif aid in ('compare_baseline', 'lane_matchup'):
            filters = ['side', 'player'] if aid == 'compare_baseline' else ['team', 'player']
        elif aid.startswith('time_') or aid == 'cross_space_time':
            filters = ['team']
        elif aid in ('compare_camp', 'resource_bp'):
            filters = [] if aid == 'compare_camp' else ['side']
        return {'id': aid, 'direction': direction, 'title': title, 'subtitle': subtitle,
                'purpose': purpose,
                'depth': level, 'status': status, 'samples': samples,
                'boundary': boundary, 'viz': viz, 'fields': fields, 'sided': sided,
                'filters': filters}

    return [
        item('cross_lane_hero', '交叉', '哪条路用哪个英雄补刀更稳', '分路 × 英雄的补刀效率对照',
             '每个格子是一组分路 + 英雄的平均补刀，颜色越深数值越高。用来定分路人选和训练重点。',
             'D2', '可运行', f'{games} 局 / {cov["lane"]["have"]} 人有分路 / {cov["cs"]["have"]} 人有补刀',
             '带斜纹的格子样本太少（不足 3 局），不作参考。', 'matrix',
             ['position', 'killSoldier', 'usedTime', 'usedHero']),
        item('cross_resource_output', '交叉', '谁吃了资源没打出输出', '经济占比 vs 输出占比，错配一眼看出',
             '点越靠右吃得越多、越靠上打得越多。点在虚线下方 = 吃钱多干活少，就是要复盘的人。',
             'D2', '可运行', f'{n} 人 / {cov["goldShare"]["have"]} 人可算占比',
             '这是相关不是因果；未认领身份显示营地昵称，同名会合并。', 'scatter',
             ['money', 'totalHeroHurtCnt', 'team.money']),
        item('cs_conversion', '补刀', '谁的补刀没变成钱、钱没变成伤害', '补刀 → 经济 → 输出，三段链条看断在哪',
             '三张图各管一段：补刀高钱少 = 补刀质量差；钱多伤害少 = 打法保守。找断点下药。',
             'D2', '可运行', f'{cov["cs"]["have"]} 人补刀 / {cov["gold"]["have"]} 人经济 / {cov["heroDamage"]["have"]} 人对英雄输出',
             '只有终局值，说的是「相关」，不能说「补刀导致赢」。', 'chain',
             ['killSoldier', 'money', 'totalHeroHurtCnt', 'monsterCoin', 'hurtTransRate']),
        item('equip_matrix', '装备', '每个位置实际在出什么装', '分路 × 装备携带率，核心装覆盖一眼看清',
             '看每条路的高频装备；该出的核心装覆盖率低、或别人出了你的装，都是出装讨论的抓手。',
             'D2', '可运行', f'{n} 人 × 6 格 / 100+ 种装备',
             '取终局六格，不含出装顺序和成型时间。', 'matrix',
             ['finalEquips', 'position']),
        item('equip_impact', '装备', '带某件装的人产出差多少', '高频装备携带者 vs 其他人的产出对照',
             '逐件对比携带者与未携带者的输出 / 经济 / 承伤，为出装复盘给一个可核对的读数。',
             'D2', '可运行', f'{n} 人 / 前 12 件高频装 / 3 项指标',
             '只是分组对照，没控制英雄和局势，不能当「这件装更强」的证据。', 'impact',
             ['finalEquips', 'hurtTransRate', 'gpm', 'behurtPerDeath']),
        item('time_cross_match', '时间', '这批训练赛的节奏与效率', '逐局分均经济 + 时段分布 + 时长效率',
             '对局按开赛时间排开：状态起伏看折线，熬夜局 vs 白天局看时段分布，长局短局看散点。',
             'D2', '可运行', f'{games} 局 / 按开始时刻排序',
             '对局集中在同一天，不能推断长期趋势或状态起伏。', 'timeline',
             ['startTime', 'usedTime', 'gpm', 'killSoldier'], sided=False),
        item('time_economy', '时间', '优势从哪建立、领先守住了吗', '每局经济差曲线 + 10 分钟检查点',
             '蓝线 = 蓝方领先、红线 = 落后。曲线看优势怎么滚起来；检查点回答「10 分钟的领先最后赢没赢」。',
             'D3', '可运行', f'{replay_games} 局 / 每局 20–54 个团队金币点',
             '约 30 秒一个金币点，检查点取最近实测值，不插值、不外推。', 'economy',
             ['economy.diff', 'durationSec', 'winCamp'], sided=False),
        item('time_events', '时间', '事件集中在哪几分钟、抢完资源赚没赚', '分钟事件密度 + 事件前后经济差变化',
             '柱子高的分钟就是交火密集区，回看直接跳那里；资源事件后经济差上行 = 赚，下行 = 亏。',
             'D3', '可运行', f'{facts["counts"]["events"]:,} 条带时间戳事件 / {replay_games} 局',
             'swing 只是事件前后 60 秒的经济变化，是时间关联不是因果。', 'events',
             ['events.key', 'events.extended', 'economy.diff'], sided=False),
        item('lane_matchup', '对比', '同分路对位：谁压谁', '同分路双方经济 / KDA 对照 + 英雄对位',
             '逐路看我方与对方同分路的经济差、KDA 差和占优率；英雄对位表回答「这个英雄遇到谁会吃亏」。',
             'D3', '可运行', f'{len(facts["ownCamps"])} 局可判定阵营 / {len(facts["players"])} 人行级样本',
             '只统计双方同分路各有一人且终局经济齐全的局；对线结果不是个人能力评价，也不作因果推断。',
             'matchup', ['position', 'money', 'killCnt', 'deadCnt', 'assistCnt', 'usedHero']),
        item('compare_baseline', '对比', '谁在同位置里算突出', '相对同位置平均的分位排行',
             '每人跟同位置比：蓝条 = 常见区间、竖线 = 同位置平均、蓝点 = 本人。分位越高越突出。',
             'D2', '可运行', f'{n} 个身份 / {games} 局',
             '未认领身份显示营地昵称；分位只描述这批样本内的相对位置。', 'baseline',
             ['gpm', 'position', 'player']),
        item('compare_camp', '对比', '蓝红两侧数据有没有偏差', '采集视角体检：蓝 vs 红产出对照',
             '检查数据本身：若蓝红出现系统性落差，复盘结论要先把视角偏差扣掉再看。',
             'D1', '可运行', f'{len(facts["teams"])} 个队侧 / {games} 局',
             '营地是观察者视角，蓝红不固定是我方 / 对手，不作阵营优劣结论。', 'camp',
             ['camp', 'money', 'totalHeroHurtCnt', 'killSoldier'], sided=False),
        item('resource_bp', 'BP 与资源', '常禁什么、常选什么、资源抢得怎样', '禁用 / 选用排行 + 终局龙塔计数',
             'BP 习惯底稿：左边常禁、右边常选；推塔和资源计数跟赛果字段对照看是否同向。',
             'D2', '可运行', f'{len(facts["teams"])} 个队侧 / {games} 局',
             '龙塔是终局计数，看不出节奏；胜负字段只覆盖单侧。', 'bp',
             ['banHeros', 'pickHeros', 'towerCnt', 'ldragon*', 'bdragon*']),
        item('stability', '稳定性', '哪个英雄稳定、哪个大起大落', '英雄逐局表现分布：常见区间 + 上限下限',
             '只看均值会误判：蓝条 = P10–P90 常态区间，两端刻度是最好 / 最差局，波动值越大越不稳。',
             'D1', '可运行', f'{n} 行 / {len({p["hero"] for p in players})} 个英雄',
             '按英雄聚合了不同选手和对局，别当作某个选手的状态稳定性。', 'stability',
             ['kda', 'usedHero']),
        item('time_kill_rhythm', '击杀', '什么时候开打：首杀、爆发与团战', '逐分钟击杀分布 + 首杀时刻 + 爆发窗口',
             '用真实击杀时刻看节奏：首杀多早、中期架打多密、哪局哪分钟炸过。逐次流水直接定位回看。',
             'D3', '可运行',
             f'{facts["counts"]["heroKills"]:,} 次逐次击杀 / {facts["counts"]["fights"]:,} 场团战 / {replay_games} 局',
             '击杀时刻与终局面板逐局一致；爆发窗口是 60 秒固定桶，只描述节奏不解释胜因。',
             'killrhythm', ['battle.killInfo', 'battle.startTime/endTime', 'matchInfo.killCnt'],
             sided=False),
        item('death_point_economy', '掉点', '每次阵亡掉多少经济', '逐人掉点窗口 + 团队经济差过程',
             '每一笔 = 一次阵亡到复活的窗口，读数是窗口内团队经济差变化。掉点流水直接指到人。',
             'D3', '可运行',
             (f'{facts["counts"]["dropWindows"]:,} 次掉点窗口 / {replay_games} 局 / '
              f'{facts["counts"]["dropRevived"]:,} 次实测复活 / {facts["counts"]["dropFinal"]:,} 次终局未复活'),
             '金币差约 30 秒一个点，窗口两端是插值约数；是时间关联不是因果。',
             'dropwindow',
             ['playBaseInfoArr.deathPosArr', 'reportData.playerPosInfo.revivePosArr',
              'ecoDistance', 'battle.killInfo']),
    ]


def create_depth_router(root, db_path=None, profile_loader=None):
    root = Path(root)
    router = APIRouter(prefix='/api/depth', tags=['depth'])
    cache = {'key': None, 'facts': None}

    def facts():
        # profile_loader 由 server 注入（读 settings 的 aliases / roster / stamp）；
        # 不传时与旧行为完全一致，测试可直接调 build_facts / _signature。
        profile = profile_loader() if profile_loader else None
        stamp = profile.get('stamp') if isinstance(profile, dict) else None
        key = _signature(root, db_path, stamp)
        if cache['key'] != key:
            cache['facts'] = build_facts(root, _camp_meta(db_path), profile)
            cache['key'] = key
        return cache['facts']

    @router.get('/catalog')
    def catalog():
        f = facts()
        unbound = sum(1 for p in f['players'] if not p.get('bound'))
        return {
            'depthScale': DEPTH_SCALE,
            'analyses': analyses_catalog(f),
            'layers': [
                {'id': 'L1', 'name': '营地十人面板', 'detail': 'data/camp_details/*.json',
                 'samples': f"{f['counts']['games']} 局 / {f['counts']['players']} 人 / {unbound} 人未认领",
                 'limits': '终局值为主；未认领身份用营地昵称显示，跨局个人结论仍需先绑定名单'},
                {'id': 'L2', 'name': '营地官方回放同步', 'detail': 'data/official_replays/camp-*/',
                 'samples': (f"{f['counts']['replayGames']} 局与面板匹配 / {f['counts']['positionPoints']:,} 位置点 / "
                             f"{f['counts']['heroKills']:,} 次逐次击杀 / {f['counts']['fights']:,} 场团战 / "
                             f"{f['counts']['dropWindows']:,} 次掉点窗口"),
                 'limits': ('位置 1 Hz、金币约 30 秒一点；团战/击杀/死亡坐标由 raw.json 的 '
                            'battle/battleDetail/deathPosArr 重建，复活时刻取 reportData.playerPosInfo.revivePosArr；'
                            '不是逐帧，也不是 .abc 帧命令回放')},
            ],
            'coverage': {k: _coverage(f['players'], k) for k in
                         ('cs', 'gold', 'heroDamage', 'damage', 'taken', 'conversion',
                          'jungleGold', 'healing', 'control', 'towerDamage',
                          'participation', 'lane', 'gpm', 'dpm', 'goldShare', 'damageShare')},
            'fieldLabels': FIELD_LABELS,
            'campMeta': f.get('campMeta'),
            'games': [{'id': item['id'], 'label': f['labels'].get(item['id'], ''),
                       'opponent': item.get('opponent') or '', 'date': str(item.get('start') or '')[:10],
                       'ownCamp': item.get('ownCamp')}
                      for item in reversed(f['matches'])],
            'labels': f.get('labels') or {},
            'players': f.get('playersCatalog') or [],
            'playersCatalog': f.get('playersCatalog') or [],
            'heroes': [name for name, _ in Counter(
                p['hero'] for p in f['players'] if p.get('hero')).most_common()],
            'counts': f['counts'],
        }

    @router.get('/analysis/{analysis_id}')
    def analysis(analysis_id: str, request: Request):
        f = facts()
        meta = next((a for a in analyses_catalog(f) if a['id'] == analysis_id), None)
        if not meta:
            raise HTTPException(status_code=404, detail='未知分析')
        game_id = request.query_params.get('game')
        side = request.query_params.get('side') or None
        team = (request.query_params.get('team') or '').strip() or None
        player = (request.query_params.get('player') or '').strip() or None
        hero = (request.query_params.get('hero') or '').strip() or None
        metric = (request.query_params.get('metric') or '').strip() or None
        start = request.query_params.get('from')
        end = request.query_params.get('to')
        try:
            date_from = date.fromisoformat(start) if start else None
            date_to = date.fromisoformat(end) if end else None
        except ValueError as error:
            raise HTTPException(status_code=400, detail='日期须为 YYYY-MM-DD') from error
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=400, detail='开始日期不能晚于结束日期')
        if side not in (None, 'own', 'opp'):
            raise HTTPException(status_code=400, detail='side 取值无效（own / opp）')
        return {'meta': meta, 'payload': analysis_payload(
            f, analysis_id, game_id, side=side, team=team, player=player, hero=hero,
            metric=metric, date_from=date_from, date_to=date_to,
            match_id=request.query_params.get('match') or None)}

    return router
