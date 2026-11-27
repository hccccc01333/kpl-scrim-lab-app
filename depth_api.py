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
                # 匹配页归档写的是 channel-* 的 match_meta + match_records，
                # 只盯 camp:* 会让确认后的对手卡在 facts 缓存里一直是旧占位名。
                row = connection.execute(
                    "SELECT COUNT(*), COALESCE(MAX(updated_at), 0) FROM match_meta").fetchone()
                parts.append(f'match-meta:{row[0]}:{row[1]}')
                records = connection.execute(
                    "SELECT match_key, COALESCE(enemy_team_id, ''), COALESCE(revision, 0) "
                    "FROM match_records ORDER BY match_key").fetchall()
                parts.append('match-records:' + '|'.join(f'{k}:{t}:{r}' for k, t, r in records))
                # 战队分析改名/合并也会改队名，facts 里的「vs 某队」标签要跟着刷新。
                for table in ('team_clusters', 'teams'):
                    try:
                        column = 'updated_at' if table == 'team_clusters' else 'revision'
                        row = connection.execute(
                            f'SELECT COUNT(*), COALESCE(MAX({column}), 0) FROM {table}').fetchone()
                        parts.append(f'{table}:{row[0]}:{row[1]}')
                    except sqlite3.OperationalError:
                        parts.append(f'{table}:none')
            finally:
                connection.close()
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

    缺失样本保留它在时间轴上的位置：先按原始下标换成时间，再只在有效点之间
    插值，不能把 None 直接删掉再重排（那样会把后面的经济点整体提前）。
    """
    if not diff or not duration:
        return None
    count = len(diff)
    step = duration / max(1, count - 1)
    points = [(index * step, value) for index, value in enumerate(diff)
              if value is not None]
    if not points:
        return None
    if seconds <= points[0][0]:
        value = points[0][1]
    elif seconds >= points[-1][0]:
        value = points[-1][1]
    else:
        value = points[-1][1]
        for index in range(1, len(points)):
            t0, v0 = points[index - 1]
            t1, v1 = points[index]
            if t0 <= seconds <= t1:
                value = v0 if t1 == t0 else v0 + (v1 - v0) * (seconds - t0) / (t1 - t0)
                break
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
        duel_pairs = defaultdict(list)
        for row in rows:
            duel_pairs[(row['ownPlayer'], row['enemyPlayer'], row['lane'])].append(row)
        players_out = []
        for (own_player, enemy_player, lane), group in duel_pairs.items():
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

    if analysis_id == 'lane_profile':
        # 05 选手对线画像：终局对位差 / CS 对位差 / 同路 1v1 击杀被单杀 /
        # 对线期死亡时间点 / 团战参与（支援代理）/ 掉点损失。
        # 只陈列条件与事实，不下「对线强弱」的结论；逐人分钟级经济快照
        # 覆盖率为 0，绝不插值补造。
        grouped = defaultdict(list)
        for p in facts.get('players') or []:
            lane = _lane_of(p)
            if lane == '未标注' or not p.get('hero'):
                continue
            grouped[(p['match'], p['camp'], lane)].append(p)
        win_camp = {str(g.get('id')): str(g.get('winCamp') or '')
                    for g in facts.get('replayGames') or []}
        for team in facts.get('teams') or []:
            if team.get('result') in (True, 1, '1', 'true'):
                win_camp.setdefault(str(team.get('match')),
                                    '1' if team.get('camp') == '蓝' else '2')
        kills_by_game = defaultdict(list)
        for k in facts.get('killEvents') or []:
            kills_by_game[k['game']].append(k)
        deaths_by_player = defaultdict(list)
        for d in facts.get('deathPoints') or []:
            if d.get('player'):
                deaths_by_player[d['player']].append(d)
        drops_by_player = defaultdict(list)
        for w in facts.get('dropWindows') or []:
            if w.get('player'):
                drops_by_player[w['player']].append(w)
        fights_by_game = defaultdict(list)
        for f in facts.get('fightFacts') or []:
            fights_by_game[f['game']].append(f)
        fight_rows_by_game = defaultdict(list)
        for fr in facts.get('fightRows') or []:
            fight_rows_by_game[fr['game']].append(fr)
        opponents = facts.get('opponents') or {}

        def won(camp, game):
            winner = win_camp.get(str(game)) or ''
            if not winner:
                return None
            return (winner == '1') if camp == '蓝' else (winner == '2')

        per_player = defaultdict(lambda: {'rows': [], 'soloKills': 0, 'soloDeaths': 0,
                                          'soloGames': set(), 'earlyDeaths': [], 'drops': [],
                                          'teamFights': 0, 'joinedFights': 0,
                                          'fightAssists': []})
        game_lanes = defaultdict(dict)
        for (game, camp, lane), people in grouped.items():
            if people:
                game_lanes[(game, lane)][camp] = people[0]
        for (game, lane), camps in game_lanes.items():
            for camp in ('蓝', '红'):
                enemy_camp = '红' if camp == '蓝' else '蓝'
                me, rival = camps.get(camp), camps.get(enemy_camp)
                if not me or not rival:
                    continue
                if me.get('gold') is None or rival.get('gold') is None:
                    continue
                o, e = me, rival
                sign = 1
                enemy_laner_hero, enemy_laner_label = e.get('hero') or '', _player_label(e)
                label = _player_label(o)
                if not label:
                    continue
                info = per_player[label]
                win = won(o['camp'], game)
                info['rows'].append({
                    'match': game, 'label': game_label(game),
                    'opponent': opponents.get(game) or '',
                    'lane': lane, 'hero': o.get('hero') or '', 'enemyHero': e.get('hero') or '',
                    'goldDiff': o['gold'] - e['gold'],
                    'csDiff': (round((o.get('cs') or 0) - (e.get('cs') or 0))
                               if o.get('cs') is not None and e.get('cs') is not None else None),
                    'win': win, 'start': o.get('start') or ''})
                info['soloGames'].add(game)
                for k in kills_by_game.get(game, []):
                    t = k.get('t')
                    if t is None or t > 480:
                        continue  # 只看对线期内的 1v1
                    if k.get('killerCamp') == o.get('camp') and k.get('killer') == o.get('hero') \
                            and k.get('victim') == enemy_laner_hero:
                        info['soloKills'] += 1
                    if k.get('killerCamp') == enemy_camp and k.get('killer') == enemy_laner_hero \
                            and k.get('victim') == o.get('hero'):
                        info['soloDeaths'] += 1
        for label, info in per_player.items():
            for death in deaths_by_player.get(label, []):
                if death.get('t') is not None and death['t'] <= 240:
                    info['earlyDeaths'].append({'match': death['game'], 't': death['t']})
            info['drops'] = drops_by_player.get(label, [])
            for game in {row['match'] for row in info['rows']}:
                my_camp = None
                for row in facts.get('players') or []:
                    if row['match'] == game and _player_label(row) == label:
                        my_camp = row['camp']
                        break
                if not my_camp:
                    continue
                team_fights = [f for f in fights_by_game.get(game, [])
                               if (f.get('camp1') == 1 and my_camp == '蓝')
                               or (f.get('camp1') == 2 and my_camp == '红')]
                joined = [fr for fr in fight_rows_by_game.get(game, [])
                          if _player_label(fr) == label]
                info['teamFights'] += len(team_fights)
                info['joinedFights'] += len(joined)
                info['fightAssists'].extend(
                    fr.get('assists') for fr in joined if fr.get('assists') is not None)

        players_out = []
        for label, info in per_player.items():
            rows = info['rows']
            if not rows:
                continue
            with_result = [r for r in rows if r['win'] is not None]
            cs_rows = [r for r in rows if r['csDiff'] is not None]
            recent = sorted(rows, key=lambda r: r['start'], reverse=True)[:3]
            players_out.append({
                'player': label, 'games': len(rows),
                'lanes': sorted({r['lane'] for r in rows}),
                'heroes': sorted({r['hero'] for r in rows}),
                'avgGoldDiff': round(statistics.mean(r['goldDiff'] for r in rows)),
                'avgCsDiff': (round(statistics.mean(r['csDiff'] for r in cs_rows))
                              if cs_rows else None),
                'aheadRate': round(sum(1 for r in rows if r['goldDiff'] > 0) / len(rows) * 100, 1),
                'winRate': (round(sum(1 for r in with_result if r['win']) / len(with_result) * 100, 1)
                            if with_result else None),
                'recentAvgGoldDiff': round(statistics.mean(r['goldDiff'] for r in recent)),
                'soloKills': info['soloKills'], 'soloDeaths': info['soloDeaths'],
                'earlyDeaths': len(info['earlyDeaths']),
                'earlyDeathMinutes': sorted({f"{int(d['t'] // 60)}:{int(d['t'] % 60):02d}"
                                             for d in info['earlyDeaths']})[:12],
                'teamFightRate': (round(info['joinedFights'] / info['teamFights'] * 100, 1)
                                  if info['teamFights'] else None),
                'avgFightAssists': (round(statistics.mean(info['fightAssists']), 2)
                                    if info['fightAssists'] else None),
                'dropCount': len(info['drops']),
                'dropAvgLoss': (round(statistics.mean(
                    abs(w.get('swing') or 0) for w in info['drops'] if w.get('swing') is not None))
                    if any(w.get('swing') is not None for w in info['drops']) else None),
                'dropFinal': sum(1 for w in info['drops'] if w.get('final')),
            })
        players_out.sort(key=lambda item: -item['games'])
        detail_rows = ([r for p in players_out if p['player'] == player
                        for r in per_player[p['player']]['rows']] if player else [])
        detail_rows.sort(key=lambda r: r['start'], reverse=True)
        return {'viz': 'laneProfile', 'players': players_out,
                'detail': detail_rows[:40],
                'note': ('对线画像只陈列条件与事实：终局对位经济差、补刀差、对线期 1v1 与死亡时间点、'
                         '团战参与与掉点损失。不定义「对线强弱」；逐人分钟级经济快照覆盖率 0，'
                         '不插值补造；支援到场用团战参与率代理，分钟级到位时间需要位置序列。')}

    if analysis_id == 'mastery':
        # 06 绝活研究：选手×英雄的指标矩阵 + 七类画像（对线/支援/团战/开团/
        # 运营/野区/后期核心）+ 同英雄他人参照。数据缺失的画像如实标注。
        rows = facts.get('players') or []
        hero_pool = defaultdict(list)
        for p in rows:
            if p.get('hero'):
                hero_pool[p['hero']].append(p)
        hero_to_label = {}
        for p in rows:
            if p.get('hero') and p.get('match'):
                hero_to_label[(p['match'], p.get('camp'), p['hero'])] = _player_label(p)
        first_by_fight = {}
        for k in facts.get('killEvents') or []:
            fid = (k['game'], k.get('fight'))
            prev = first_by_fight.get(fid)
            if prev is None or (k.get('t') is not None and prev.get('t') is not None
                                and k['t'] < prev['t']):
                first_by_fight[fid] = k
        first_by_game_hero = Counter()
        for (game, _fight), kill in first_by_fight.items():
            label = hero_to_label.get((str(game), str(kill.get('killerCamp') or '')
                                       .replace('1', '蓝').replace('2', '红'), kill.get('killer') or ''))
            if label:
                first_by_game_hero[(label, kill.get('killer') or '')] += 1
        groups = defaultdict(list)
        for p in rows:
            label, hero = _player_label(p), p.get('hero')
            if label and hero:
                groups[(label, hero)].append(p)

        def mean(items):
            values = [v for v in items if v is not None]
            return round(statistics.mean(values), 2) if values else None

        mastery = []
        for (label, hero), records in groups.items():
            if not records:
                continue
            wins = sum(1 for r in records if r.get('win') is True)
            decided = [r for r in records if r.get('win') is not None]
            bench = [r for r in hero_pool.get(hero, []) if _player_label(r) != label]
            bench_win = (round(sum(1 for r in bench if r.get('win') is True)
                               / len(bench) * 100, 1) if bench else None)
            bench_cs = mean([r.get('csPerMin') for r in bench])
            team_hero_damage = defaultdict(int)
            for r in rows:
                if r.get('heroDamage') is not None:
                    team_hero_damage[(r['match'], r['camp'])] += r['heroDamage']
            damage_shares = [r['heroDamage'] / team_hero_damage[(r['match'], r['camp'])] * 100
                             for r in records
                             if r.get('heroDamage') is not None
                             and team_hero_damage.get((r['match'], r['camp']))]
            entry = {
                'player': label, 'hero': hero, 'games': len(records),
                'winRate': (round(wins / len(decided) * 100, 1) if decided else None),
                'decided': len(decided), 'avgKda': mean([r.get('kda') for r in records]),
                'csPerMin': mean([r.get('csPerMin') for r in records]),
                'goldShare': mean([r.get('goldShare') for r in records]),
                'participation': mean([r.get('participation') for r in records]),
                'deathsPerGame': (round(sum(r.get('deaths') or 0 for r in records) / len(records), 2)),
                'jungleGold': mean([r.get('jungleGold') for r in records]),
                'towerDamage': mean([r.get('towerDamage') for r in records]),
                'towerCnt': sum(r.get('towerCnt') or 0 for r in records),
                'control': mean([r.get('control') for r in records]),
                'healing': mean([r.get('healing') for r in records]),
                'damageShare': (round(statistics.mean(damage_shares), 1) if damage_shares else None),
                'teamFightFirst': sum(count for (p, h), count in first_by_game_hero.items()
                                      if p == label and h == hero),
                'benchWinRate': bench_win, 'benchCsPerMin': bench_cs,
            }
            entry['winDelta'] = (round(entry['winRate'] - bench_win, 1)
                                 if entry['winRate'] is not None and bench_win is not None else None)
            entry['csDelta'] = (round(entry['csPerMin'] - bench_cs, 2)
                                if entry['csPerMin'] is not None and bench_cs is not None else None)
            mastery.append(entry)
        mastery.sort(key=lambda item: (-item['games'], -abs(item['winDelta'] or 0)))
        types_note = {
            '对线型': '对线期经济差与死亡时间点在「对线画像」分析里（需要分路映射）。',
            '支援型': '支援到场用团战参与率代理；分钟级到位时间需要位置序列，未实现。',
            '团战型': '参团率 / 对英雄输出占比 / 承伤已有；关键击杀（clutch）无采集定义，未实现。',
            '开团型': '开团＝该波团战第一次击杀（与官方回放 firstKillerCamp 同源）。',
            '运营型': '推塔伤害 / 推塔数已有；转线与带线牵制无对应事件，未实现。',
            '野区节奏型': '野怪经济已有；控龙是团队口径，入侵事件未跨局聚合。',
            '后期核心型': '终局经济占比 + 对英雄输出占比作代理；逐人分钟级经济快照覆盖 0，前期对比缺失。',
        }
        if player:
            mastery = [m for m in mastery if m['player'] == player]
        return {'viz': 'mastery', 'players': mastery[:60],
                'typesNote': types_note,
                'note': ('绝活判断需要四向对照：同选手其他英雄、同英雄其他选手（已给基准差）、'
                         '同英雄不同对位（见对位画像）、同选手不同体系（未实现）。'
                         '常用与高胜率不能直接定义绝活。')}

    raise HTTPException(status_code=404, detail='未知分析')


# 每个 router 实例持有一份 facts 缓存；匹配保存/战队合并后必须能远程清掉，
# 否则同一个进程里深度分析页继续显示旧的「待命名战队」。
_FACTS_CACHES = []


def invalidate_facts_cache():
    """清空所有深度分析 router 的 facts 缓存（工作区写入路径调用）。"""
    for entry in _FACTS_CACHES:
        entry['key'] = None
        entry['facts'] = None


def create_depth_router(root, db_path=None, profile_loader=None):
    """普通页面（单局复盘对位压制 / 英雄详情）需要的三份底层数据，不是分析专题。"""
    root = Path(root)
    router = APIRouter(prefix='/api/v3/facts', tags=['facts'])
    cache = {'key': None, 'facts': None}
    _FACTS_CACHES.append(cache)
    facts_kinds = ('lane_matchup', 'equip_matrix', 'equip_impact', 'lane_profile', 'mastery')

    def facts():
        profile = profile_loader() if profile_loader else None
        stamp = profile.get('stamp') if isinstance(profile, dict) else None
        key = _signature(root, db_path, stamp)
        if cache['key'] != key:
            meta = _camp_meta(db_path)
            # 战队分析是当前队名的唯一权威：把每局营地 seq 解析出的队名并进
            # 分边覆盖层，深度页的「vs 某队」标签与其他页面同一口径。
            try:
                import opponent_identity
                resolved = opponent_identity.resolve(
                    db_path, data_root(root) / 'camp_details')
                for seq, name in resolved['bySeq'].items():
                    if name:
                        meta.setdefault(seq, {})['opponent'] = name
                    elif meta.get(seq, {}).get('opponent'):
                        meta[seq]['opponent'] = resolved['aliases'].get(
                            meta[seq]['opponent'], meta[seq]['opponent'])
            except Exception:  # noqa: BLE001 - 解析失败保留教练手填的队名
                pass
            cache['facts'] = build_facts(root, meta, profile)
            cache['key'] = key
        return cache['facts']

    @router.get('/{kind}')
    def fact(kind: str, request: Request):
        if kind not in facts_kinds:
            raise HTTPException(status_code=404, detail='未知数据')
        f = facts()
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
        return {'payload': analysis_payload(
            f, kind, game_id, side=side, team=team, player=player, hero=hero,
            metric=metric, date_from=date_from, date_to=date_to,
            match_id=request.query_params.get('match') or None)}

    return router
