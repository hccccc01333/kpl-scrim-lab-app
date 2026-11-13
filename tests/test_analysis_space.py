"""A1–A7 空间与团战：关联键、团战统计、孤立判定。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import analysis_space as sp  # noqa: E402


def write_game(tmp_path, seq, *, positions, heroes=None, fights=None, deaths=None,
               events=None, own_camp=1, roles=None):
    replay = tmp_path / 'replays' / f'camp-{seq}'
    replay.mkdir(parents=True, exist_ok=True)
    heroes = heroes or {pid: f'英雄{i}' for i, pid in enumerate(positions)}
    order = list(positions)
    players = [{'playerId': pid, 'camp': '1', 'hero': heroes[pid], 'heroId': index + 1}
               for index, pid in enumerate(order)]
    player_map = {f'obj{index}': {'heroId': index + 1, 'hero': heroes[pid], 'camp': '1'}
                  for index, pid in enumerate(order)}
    (replay / 'normalized.json').write_text(json.dumps({
        'match': {'durationSec': len(next(iter(positions.values()))), 'winCamp': '1'},
        'players': players,
        'battles': {'playerMap': player_map, 'fights': fights or [], 'deaths': deaths or []},
        'events': {'key': events or []},
        'economy': {'diff': [0] * 10},
    }), encoding='utf-8')
    (replay / 'positions.json').write_text(json.dumps({
        'players': [{'playerId': pid, 'posArr': arr} for pid, arr in positions.items()]
    }), encoding='utf-8')

    camp = tmp_path / 'camp_details'
    camp.mkdir(parents=True, exist_ok=True)
    role_rows = roles or [{'hero': heroes[pid], 'position': 0} for pid in order]
    (camp / f'{seq}.json').write_text(json.dumps({'data': {
        'head': {'acntCamp': own_camp, 'gameResult': True},
        'blueRoles': [{'basicInfo': {'playerId': f'camp{i}'},
                       'battleRecords': {'position': role['position'],
                                         'usedHero': {'heroName': role['hero']}}}
                      for i, role in enumerate(role_rows)],
        'redRoles': [],
    }}, ensure_ascii=False), encoding='utf-8')


def test_lane_joins_by_hero_not_by_camp_id(tmp_path):
    positions = {'p1': [[0, 0]] * 10, 'p2': [[5, 5]] * 10, 'p3': [[10, 10]] * 10}
    heroes = {'p1': '英雄A', 'p2': '英雄B', 'p3': '英雄C'}
    write_game(tmp_path, '1', positions=positions, heroes=heroes, roles=[
        {'hero': '英雄A', 'position': 3},
        {'hero': '英雄B', 'position': 1},
        {'hero': '英雄C', 'position': 4},
    ])
    games = sp.load_games(tmp_path / 'replays', tmp_path / 'camp_details')
    assert games[0]['lanes'] == {'p1': '打野', 'p2': '中路', 'p3': '游走'}


def test_fight_arrival_and_kill_diff(tmp_path):
    positions = {'p1': [[0, 0]] * 60}
    fight = {
        'fightId': '1', 'startSec': 10, 'endSec': 16, 'camp1': 5, 'camp2': 3,
        'participants': [
            {'objID': 'obj0', 'camp': '1', 'timeSec': 10},
            {'objID': 'obj1', 'camp': '2', 'timeSec': 17},
        ],
        'kills': [{'timeSec': 13, 'killerCamp': '1', 'victimCamp': '2'}],
        'details': [],
    }
    write_game(tmp_path, '2', positions=positions, fights=[fight])
    result = sp.fight_arrival(sp.load_games(tmp_path / 'replays', tmp_path / 'camp_details'))
    row = result['rows'][0]
    assert row['participants'] == 2
    assert row['killDiff'] == 1
    assert row['advStart'] == 1          # 开局 3 秒内只有蓝方到达
    assert row['lateJoins'] == 1         # 红方 17s 才到，lag 7 > 5
    assert result['buckets'][0]['winRate'] == 100.0


def test_kill_chain_pattern_and_wipe(tmp_path):
    positions = {'p1': [[0, 0]] * 60}
    fight = {
        'fightId': '2', 'startSec': 5, 'endSec': 20,
        'participants': [], 'details': [],
        'kills': [
            {'timeSec': 6, 'killerCamp': '1', 'victimCamp': '2'},
            {'timeSec': 7, 'killerCamp': '1', 'victimCamp': '2'},
            {'timeSec': 8, 'killerCamp': '1', 'victimCamp': '2'},
        ],
    }
    write_game(tmp_path, '3', positions=positions, fights=[fight])
    result = sp.kill_chains(sp.load_games(tmp_path / 'replays', tmp_path / 'camp_details'))
    row = result['rows'][0]
    assert row['sequence'] == '111'
    assert row['pattern'] == '3-0'
    assert row['maxConsecutive'] == 3
    assert row['ambiguous'] is False


def test_death_isolation_uses_teammate_distance(tmp_path):
    # 三人同阵营：p1 在死亡点，p2 很近，p3 很远
    positions = {
        'p1': [[0, 0]] * 60,
        'p2': [[2, 0]] * 60,
        'p3': [[90, 0]] * 60,
    }
    deaths = [{'objID': 'obj0', 'camp': '1', 'heroId': 1, 'x': 0, 'y': 0, 'timeSec': 30}]
    write_game(tmp_path, '4', positions=positions, deaths=deaths)
    result = sp.death_isolation(sp.load_games(tmp_path / 'replays', tmp_path / 'camp_details'))
    row = result['rows'][0]
    assert row['nearCount'] == 1
    assert row['isolated'] is False
    assert row['nearest'] == 2.0

def test_death_without_coordinates_is_skipped(tmp_path):
    """死亡事件缺坐标时跳过；修复前 math.dist((None,None), point) 抛 TypeError。"""
    positions = {'p1': [[10, 10]] * 60, 'p2': [[12, 10]] * 60, 'p3': [[90, 10]] * 60}
    deaths = [{'objID': 'obj0', 'camp': '1', 'heroId': 1, 'timeSec': 30}]
    write_game(tmp_path, '5', positions=positions, deaths=deaths)
    result = sp.death_isolation(sp.load_games(tmp_path / 'replays', tmp_path / 'camp_details'))
    assert result['deaths'] == 0


def test_zero_kill_fight_is_not_in_win_rate_denominator(tmp_path):
    """空团战（0 击杀）只进 n，不进胜率分母。"""
    positions = {'p1': [[0, 0]] * 60}
    fight = {
        'fightId': '9', 'startSec': 10, 'endSec': 16,
        'participants': [
            {'objID': 'obj0', 'camp': '1', 'timeSec': 10},
            {'objID': 'obj1', 'camp': '2', 'timeSec': 10},
        ],
        'kills': [],
        'details': [],
    }
    write_game(tmp_path, '9', positions=positions, fights=[fight])
    result = sp.fight_arrival(sp.load_games(tmp_path / 'replays', tmp_path / 'camp_details'))
    bucket = result['buckets'][0]
    assert bucket['n'] == 1
    assert bucket['decided'] == 0
    assert bucket['winRate'] is None
