"""决策台测试用合成数据（不依赖真实赛训库）。

设计目标：
- 结构与真实营地载荷一致（camp_details / normalized.json / positions.json）。
- 默认一局即可跑通「失利链 / 优势 / 团战 / 资源 / 开局」的最小闭环。
- 每个 builder 只覆盖必要字段，其他字段留空；测试按需覆盖。

用法::

    from decision_fixtures import write_dataset, load_fixture_facts
    root = write_dataset(tmp_path)                  # 一局默认数据
    facts = load_fixture_facts(root)
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LANES = ['对抗路', '中路', '发育路', '打野', '游走']
HEROES = {
    'own': ['关羽', '妲己', '百里守约', '孙悟空', '钟馗'],
    'enemy': ['吕布', '貂蝉', '公孙离', '兰陵王', '张良'],
}
HERO_IDS = {
    'own': [101, 102, 103, 104, 105],
    'enemy': [201, 202, 203, 204, 205],
}
# 默认面板数据：经济占比与输出占比刻意做出差异，供资源分配测试使用
DEFAULT_GOLD = [7600, 8200, 8800, 9000, 6200]
DEFAULT_HERO_DAMAGE = [22000, 88000, 96000, 42000, 12000]
DEFAULT_TOWER_DAMAGE = [4200, 1800, 5200, 1200, 600]
DEFAULT_CONTROL = [22, 18, 8, 12, 41]
DEFAULT_HEAL = [4200, 3600, 2800, 2600, 16200]
DEFAULT_CS = [52, 61, 70, 38, 12]
DEFAULT_JUNGLE = [120, 180, 240, 980, 60]


def _stats(gold, damage, tower, control, heal, cs, jungle, *, kills, deaths, assists):
    return {
        'killCnt': kills, 'deadCnt': deaths, 'assistCnt': assists,
        'money': gold, 'totalHurtCnt': damage * 3, 'totalHeroHurtCnt': damage,
        'totalBehurtCnt': max(8000, 60000 - damage // 3),
        'joinGamePercent': '0.55', 'buildingDamage': tower, 'ctrlTime': control,
        'healCnt': heal, 'killSoldier': cs, 'monsterCoin': jungle,
        'gradeGame': '9.5', 'exp': 12000,
    }


def make_panel(seq, *, own_camp='1', own_win=True, start='11-02 12:00', used=600,
               enemy_names=None, own_names=None):
    own_names = own_names or ['我方' + lane for lane in LANES]
    enemy_names = enemy_names or ['对手' + lane for lane in LANES]
    data = {
        'head': {'gameResult': own_win, 'acntCamp': int(own_camp),
                 'roleName': own_names[0], 'playerId': 'panel-own-0'},
        'battle': {'usedTime': used, 'startTime': start, 'mapName': '训练赛'},
        'blueRoles': [], 'redRoles': [],
        'blueTeam': {'acntCamp': 1, 'gameResult': own_win, 'money': 40000},
        'redTeam': {'acntCamp': 2, 'gameResult': not own_win, 'money': 38000},
    }
    own_camp = int(own_camp)
    for index, lane in enumerate(LANES):
        for camp, side, names, base in ((1, 'blue', own_names, 'own'),
                                        (2, 'red', enemy_names, 'enemy')):
            is_own = (camp == own_camp)
            kills = [3, 2, 4, 1, 0][index] if is_own else [1, 2, 0, 3, 1][index]
            deaths = [0, 1, 0, 2, 1][index] if is_own else [2, 3, 1, 1, 2][index]
            assists = [8, 6, 5, 7, 9][index] if is_own else [4, 3, 2, 2, 5][index]
            stats = _stats(
                gold=panel_gold(base, index), damage=DEFAULT_HERO_DAMAGE[index],
                tower=DEFAULT_TOWER_DAMAGE[index], control=DEFAULT_CONTROL[index],
                heal=DEFAULT_HEAL[index], cs=DEFAULT_CS[index], jungle=DEFAULT_JUNGLE[index],
                kills=kills, deaths=deaths, assists=assists)
            role = {
                'basicInfo': {'playerId': f'panel-{base}-{index}',
                              'roleName': names[index]},
                'battleStats': stats,
                'battleRecords': {
                    'position': index,
                    'usedHero': {'heroName': HEROES[base][index],
                                 'heroId': HERO_IDS[base][index]},
                },
            }
            data['blueRoles' if camp == 1 else 'redRoles'].append(role)
    return {'result': 0, 'data': data}


def panel_gold(base, index):
    if base == 'enemy':
        return max(4000, DEFAULT_GOLD[index] - 1300)
    return DEFAULT_GOLD[index]


def default_players(duration=600):
    players = []
    for side in ('own', 'enemy'):
        camp = '1' if side == 'own' else '2'
        for index, lane in enumerate(LANES):
            players.append({
                'playerId': f'{camp}-{index}',
                'camp': camp,
                'hero': HEROES[side][index],
                'heroId': HERO_IDS[side][index],
                'kills': 0, 'deaths': 0, 'assists': 0,
            })
    return players


def default_player_map():
    mapping = {}
    for side in ('own', 'enemy'):
        camp = '1' if side == 'own' else '2'
        for index, hero_id in enumerate(HERO_IDS[side]):
            mapping[str(hero_id)] = {'heroId': hero_id, 'hero': HEROES[side][index],
                                     'camp': camp}
    return mapping


def default_diff():
    # 蓝方视角：先领先到 2400，再回撤到 -400（供优势回撤/翻盘测试）
    return [0, 300, 800, 1600, 2400, 2100, 1500, 900, 200, -400]


def default_fights():
    participants = []
    for index in range(5):
        participants.append({'objID': f'10{index + 1}', 'camp': '1',
                             'timeSec': 300 + (0 if index < 3 else 2), 'beginner': 1 if index == 4 else 0})
    for index in range(5):
        participants.append({'objID': f'20{index + 1}', 'camp': '2',
                             'timeSec': 301 + (0 if index < 4 else 2), 'beginner': 0})
    details = []
    for index in range(5):
        details.append({'fightId': 'f1', 'objID': f'10{index + 1}', 'camp': '1',
                        'kills': 0, 'deaths': 0 if index > 1 else 1, 'assists': 1,
                        'hurt': 1200 + index * 100, 'taken': 900, 'heal': 0,
                        'hardCtrl': 100, 'softCtrl': 200, 'lowHP': 0,
                        'beginHP': 4000, 'endHP': 2500, 'ultimates': 1})
    for index in range(5):
        details.append({'fightId': 'f1', 'objID': f'20{index + 1}', 'camp': '2',
                        'kills': 1 if index == 0 else 0, 'deaths': 2 if index < 2 else 0,
                        'assists': 0, 'hurt': 800, 'taken': 1500, 'heal': 0,
                        'hardCtrl': 0, 'softCtrl': 100, 'lowHP': 0,
                        'beginHP': 4200, 'endHP': 0 if index < 2 else 3000, 'ultimates': 0})
    return [{
        'fightId': 'f1', 'startSec': 300.0, 'endSec': 316.0,
        'firstKillerCamp': '2', 'camp1': 5, 'camp2': 3,
        'participants': participants,
        'kills': [
            {'timeSec': 306.0, 'killerCamp': '1', 'killer': '104', 'victimCamp': '2', 'victim': '201'},
            {'timeSec': 309.0, 'killerCamp': '1', 'killer': '103', 'victimCamp': '2', 'victim': '202'},
            {'timeSec': 312.0, 'killerCamp': '2', 'killer': '202', 'victimCamp': '1', 'victim': '101'},
        ],
        'details': details,
    }]


def default_deaths():
    return [
        {'objID': '101', 'camp': '1', 'heroId': 101, 'x': -20.0, 'y': 10.0, 'timeSec': 312},
        {'objID': '201', 'camp': '2', 'heroId': 201, 'x': 20.0, 'y': -10.0, 'timeSec': 306},
    ]


def default_events():
    return [
        {'eventType': 'dragontower', 'timeSec': 360.0, 'dtType': '1', 'dtId': '9',
         'dtCamp': '2', 'killerCamp': '1', 'killerId': '104',
         'kills': [{'camp': '1', 'killerId': '104', 'hurtTotal': '8000'}]},
        {'eventType': 'dragontower', 'timeSec': 470.0, 'dtType': '2', 'dtId': '1',
         'dtCamp': '2', 'killerCamp': '2', 'killerId': '202',
         'kills': [{'camp': '2', 'killerId': '202', 'hurtTotal': '6000'}]},
        {'eventType': 'dragontower', 'timeSec': 560.0, 'dtType': '2', 'dtId': '10',
         'dtCamp': '1', 'killerCamp': '1', 'killerId': '103', 'kills': []},
    ]


def default_positions(duration=600):
    players = []
    for side in ('own', 'enemy'):
        camp = '1' if side == 'own' else '2'
        for index in range(5):
            arr = []
            for second in range(duration + 5):
                # 沿一条斜线缓慢移动，保证没有 (0,0)
                x = (-40 if camp == '1' else 40) + index * 2 + second * 0.01
                y = -30 + index * 12 + second * 0.005
                arr.append([round(x, 2), round(y, 2)])
            players.append({'playerId': f'{camp}-{index}', 'points': len(arr), 'posArr': arr})
    return {'players': players}


def make_replay(seq, *, own_camp='1', win_camp='1', duration=600, diff=None,
                events=None, fights=None, deaths=None, players=None, player_map=None):
    own_camp = str(own_camp)
    return {
        'schema': 'decision-fixture/1',
        'source': 'fixture',
        'match': {
            'winCamp': str(win_camp), 'durationSec': float(duration),
            'teamGold': {'blue': 40000, 'red': 38000},
            'goldPoints': len(diff or default_diff()),
            'goldIntervalSecApprox': 30,
            'keyEvents': len(events if events is not None else default_events()),
            'extendedEvents': 0, 'equipmentEvents': 0,
        },
        'economy': {'diff': list(diff if diff is not None else default_diff()),
                    'blue': [], 'red': [], 'note': 'fixture'},
        'events': {'key': list(events if events is not None else default_events()),
                   'extended': [], 'equipment': []},
        'players': players if players is not None else default_players(duration),
        'battles': {
            'fights': list(fights if fights is not None else default_fights()),
            'deaths': list(deaths if deaths is not None else default_deaths()),
            'playerMap': player_map if player_map is not None else default_player_map(),
            'counts': {},
        },
        'positions': {'players': 10},
        'warnings': [],
    }


def write_case(root, seq, *, panel=True, replay=True, positions=True, calibration=False, **kwargs):
    """写一局数据；kwargs 透传给 make_panel / make_replay（同名字段各取所需）。"""
    root = Path(root)
    camp_dir = root / 'camp_details'
    replay_dir = root / 'official_replays' / f'camp-{seq}'
    camp_dir.mkdir(parents=True, exist_ok=True)
    replay_dir.mkdir(parents=True, exist_ok=True)
    own_camp = str(kwargs.get('own_camp', '1'))
    own_win = bool(kwargs.get('own_win', True))
    if panel:
        panel_payload = make_panel(seq, own_camp=own_camp, own_win=own_win,
                                   start=kwargs.get('start', '11-02 12:00'),
                                   used=kwargs.get('duration', 600))
        (camp_dir / f'{seq}.json').write_text(
            json.dumps(panel_payload, ensure_ascii=False), encoding='utf-8')
    if replay:
        replay_kwargs = {key: kwargs[key] for key in
                         ('own_camp', 'win_camp', 'duration', 'diff', 'events', 'fights', 'deaths',
                          'players', 'player_map') if key in kwargs}
        replay_kwargs.setdefault('win_camp', '1' if own_win else '2')
        normalized = make_replay(seq, **replay_kwargs)
        (replay_dir / 'normalized.json').write_text(
            json.dumps(normalized, ensure_ascii=False), encoding='utf-8')
    if positions:
        payload = kwargs.get('positions_payload') or default_positions(kwargs.get('duration', 600))
        (replay_dir / 'positions.json').write_text(
            json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    if calibration:
        payload = calibration if isinstance(calibration, dict) else {
            'calibrated': True,
            'bounds': {'xMin': -53.0, 'xMax': 53.0, 'yMin': -53.0, 'yMax': 53.0},
            'width': 106.0, 'height': 106.0, 'diagonal': 149.91,
            'source': 'fixture',
        }
        (root / 'map_calibration.json').write_text(
            json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    return root


def write_dataset(root, cases=None, *, calibration=False):
    """cases: [{'seq': ..., **kwargs}, ...]；默认写一局。"""
    cases = cases or [{'seq': '1001'}]
    for case in cases:
        case = dict(case)
        seq = case.pop('seq')
        write_case(root, seq, calibration=calibration, **case)
    if calibration:
        # write_case 已写 calibration；这里保证空目录也有
        target = Path(root) / 'map_calibration.json'
        if not target.exists():
            write_case(root, 'calibration-only', panel=False, replay=False,
                       positions=False, calibration=calibration)
    return Path(root)


def load_fixture_facts(root, *, db_path=None):
    import decision_facts
    root = Path(root)
    return decision_facts.load_facts(root / 'official_replays', root / 'camp_details',
                                     root, db_path=db_path)


def find_game(facts, seq=None):
    seq = seq or facts['order'][0]
    return facts['games'][seq]


def make_abs_positions(values, duration=600):
    """快速构造 positions payload：values = {playerId: [(x, y), ...]}，缺失秒用 (0,0)。"""
    players = []
    for player_id, points in values.items():
        arr = [[0, 0] for _ in range(duration + 5)]
        for second, point in enumerate(points):
            if second < len(arr):
                arr[second] = [float(point[0]), float(point[1])]
        players.append({'playerId': player_id, 'points': len(arr), 'posArr': arr})
    return {'players': players}


def distance(a, b):
    return math.dist(a, b)
