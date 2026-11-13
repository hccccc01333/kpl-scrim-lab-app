"""BP 抗针对：禁选排行、分路可用池、稳定选手样本与空数据处理。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bp_camp as bp  # noqa: E402
import facts_fixtures as fx  # noqa: E402


def add_bans(root, *, enemy_bans, own_bans=None):
    """给 fixtures 里的 camp_details 补 blueTeam/redTeam.banHeros。"""
    for path in sorted((Path(root) / 'camp_details').glob('*.json')):
        payload = json.loads(path.read_text(encoding='utf-8'))
        data = payload.get('data') or {}
        own = str((data.get('head') or {}).get('acntCamp') or '1')
        own_key, enemy_key = ('blueTeam', 'redTeam') if own == '1' else ('redTeam', 'blueTeam')
        for key, heroes in ((own_key, own_bans or []), (enemy_key, enemy_bans)):
            data[key]['banHeros'] = [{'heroName': hero} for hero in heroes]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')


def make_facts(tmp_path, count=3):
    cases = [{'seq': f'200{i}', 'own_camp': '1', 'own_win': True} for i in range(count)]
    fx.write_dataset(tmp_path, cases, calibration=True)
    # 敌人每局禁我方中路/游走常用英雄；我方禁对手的辅助。
    add_bans(tmp_path, enemy_bans=['妲己', '钟馗', '张良'])
    return fx.load_fixture_facts(tmp_path)


def test_lanes_and_bans(tmp_path):
    facts = make_facts(tmp_path)
    report = bp.bp_report(facts)
    assert report['available'] is True
    assert report['coverage']['panelGames'] == 3
    assert report['coverage']['gamesWithBans'] == 3
    assert [item['hero'] for item in report['bans']['overall']][:3] == ['妲己', '钟馗', '张良']
    assert len(report['lanes']) == 5
    lane = next(item for item in report['lanes'] if item['lane'] == '中路')
    assert lane['games'] >= 1
    assert '妲己' in lane['bannedHits']
    assert lane['poolDepth'] == 0 and lane['thin'] is True
    support = next(item for item in report['lanes'] if item['lane'] == '游走')
    assert '钟馗' in support['bannedHits']


def test_players_only_stable_samples(tmp_path):
    facts = make_facts(tmp_path, count=3)
    report = bp.bp_report(facts)
    assert report['coverage']['players'] == len(report['players'])
    assert all(item['games'] >= bp.MIN_PLAYER_GAMES for item in report['players'])
    # 每个 fixture 选手只打同一分路，3 局后应保留在稳定样本里。
    assert len(report['players']) >= 1
    assert report['team']['suggestions']


def test_opponent_filter_and_empty(tmp_path):
    facts = make_facts(tmp_path)
    opponent = facts['opponents'][0]['id']
    report = bp.bp_report(facts, opponent=opponent)
    assert report['available'] is True
    assert report['coverage']['panelGames'] == 3
    assert report['bans']['byOpponent'][0]['id'] == opponent
    empty = bp.bp_report({'rows': [], 'panels': {}, 'opponents': []})
    assert empty['available'] is False and empty['reason']
