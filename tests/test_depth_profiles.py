"""05 对线画像 / 06 绝活研究：facts 聚合的纯函数守卫。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from depth_api import analysis_payload  # noqa: E402


def facts_fixture():
    """两局 × 双方 × 同分路各一人 + 回放事实（1v1 / 早期死亡 / 团战 / 掉点）。"""
    players = []
    for match, start in (('m-1', '2026-11-02 18:00'), ('m-2', '2026-11-06 18:00')):
        players.append({'match': match, 'camp': '蓝', 'hero': '夏洛特', 'name': '实训选手',
                        'lane': 0, 'gold': 9000, 'cs': 210, 'kills': 4, 'deaths': 1,
                        'assists': 5, 'heroDamage': 30000, 'taken': 18000,
                        'participation': 0.7, 'csPerMin': 11.4, 'goldShare': 27.5, 'jungleGold': 300, 'towerDamage': 4000,
                        'towerCnt': 2, 'control': 12, 'healing': 0, 'win': True,
                        'start': start, 'duration': 1100})
        players.append({'match': match, 'camp': '红', 'hero': '马超', 'name': '对手上单',
                        'lane': 0, 'gold': 7600, 'cs': 180, 'kills': 1, 'deaths': 3,
                        'assists': 2, 'heroDamage': 22000, 'taken': 26000,
                        'participation': 0.5, 'csPerMin': 9.8, 'goldShare': 23.4, 'jungleGold': 0, 'towerDamage': 1000,
                        'towerCnt': 0, 'control': 3, 'healing': 0, 'win': False,
                        'start': start, 'duration': 1100})
        # 同英雄跨阵营对照：m-2 红方中路也用夏洛特（只在第二局出现）
        players.append({'match': 'm-2', 'camp': '红', 'hero': '夏洛特', 'name': '对手中单',
                        'lane': 1, 'gold': 7000, 'cs': 160, 'kills': 0, 'deaths': 4,
                        'assists': 1, 'heroDamage': 15000, 'taken': 20000,
                        'participation': 0.4, 'csPerMin': 8.7, 'goldShare': 21.0,
                        'jungleGold': 0, 'towerDamage': 500, 'towerCnt': 0, 'control': 1,
                        'healing': 0, 'win': False, 'start': '2026-11-06 18:00',
                        'duration': 1100})
    return {
        'players': players,
        'teams': [{'match': 'm-1', 'camp': '蓝', 'result': True},
                  {'match': 'm-2', 'camp': '蓝', 'result': True}],
        'matches': [{'key': 'm-1', 'opponent': '对手A'}, {'key': 'm-2', 'opponent': '对手B'}],
        'replayGames': [{'id': 'm-1', 'winCamp': '1'}, {'id': 'm-2', 'winCamp': '1'}],
        'killEvents': [
            {'game': 'm-1', 'fight': 'f1', 't': 200, 'killer': '夏洛特', 'killerCamp': '蓝',
             'victim': '马超', 'victimCamp': '红'},
            {'game': 'm-1', 'fight': 'f1', 't': 150, 'killer': '马超', 'killerCamp': '红',
             'victim': '夏洛特', 'victimCamp': '蓝'},
        ],
        'fightFacts': [
            {'game': 'm-1', 'fight': 'f1', 'start': 140, 'end': 200, 'camp1': 1, 'camp2': 2},
            {'game': 'm-1', 'fight': 'f2', 'start': 500, 'end': 540, 'camp1': 1, 'camp2': 2},
        ],
        'fightRows': [
            {'game': 'm-1', 'fight': 'f1', 'hero': '夏洛特', 'camp': '蓝', 'name': '实训选手',
             'assists': 1},
        ],
        'deathPoints': [
            {'game': 'm-2', 't': 180, 'camp': '蓝', 'hero': '夏洛特', 'player': '实训选手'},
        ],
        'dropWindows': [
            {'game': 'm-2', 'player': '实训选手', 'swing': -600, 'final': False},
        ],
        'ownCamps': {}, 'opponents': {'m-1': '对手A', 'm-2': '对手B'},
    }


def test_lane_profile_aggregates_per_player():
    payload = analysis_payload(facts_fixture(), 'lane_profile')
    assert payload['viz'] == 'laneProfile'
    player = next(p for p in payload['players'] if p['player'] == '实训选手')
    assert player['games'] == 2
    assert player['avgGoldDiff'] == 1400  # 9000-7600 两局相同
    assert player['aheadRate'] == 100.0
    assert player['winRate'] == 100.0
    assert player['avgCsDiff'] == 30
    assert player['soloKills'] == 1 and player['soloDeaths'] == 1
    assert player['earlyDeaths'] == 1
    assert player['teamFightRate'] == 50.0  # 2 场团战参与了 1 场
    assert player['dropCount'] == 1 and player['dropAvgLoss'] == 600
    assert player['recentAvgGoldDiff'] == 1400


def test_lane_profile_player_filter_returns_detail_rows():
    payload = analysis_payload(facts_fixture(), 'lane_profile', player='实训选手')
    assert payload['detail'] and payload['detail'][0]['hero'] == '夏洛特'
    assert payload['detail'][0]['enemyHero'] == '马超'


def test_mastery_benchmarks_and_teamfight_first():
    payload = analysis_payload(facts_fixture(), 'mastery')
    assert payload['viz'] == 'mastery'
    entry = next(m for m in payload['players']
                 if m['player'] == '实训选手' and m['hero'] == '夏洛特')
    assert entry['games'] == 2 and entry['winRate'] == 100.0
    # m-2 红方中路也用了一次夏洛特（0/1 负）→ 同英雄基准来自那一局
    assert entry['benchWinRate'] == 0.0 and entry['winDelta'] == 100.0
    assert entry['teamFightFirst'] == 0  # f1 首杀是 t=150 的马超
    assert entry['csPerMin'] is not None
    rival = next(m for m in payload['players']
                 if m['player'] == '对手上单' and m['hero'] == '马超')
    # 马超只有对手上单一人使用 → 基准如实为 None；f1 首杀记到他名下
    assert rival['benchWinRate'] is None and rival['winDelta'] is None
    assert rival['teamFightFirst'] == 1
    assert '第一次击杀' in payload['typesNote']['开团型']


def test_mastery_player_filter():
    payload = analysis_payload(facts_fixture(), 'mastery', player='对手上单')
    assert all(m['player'] == '对手上单' for m in payload['players'])
    assert payload['players'][0]['hero'] == '马超'
