"""匹配页 10/10 时一次保存必须把十个人都落库。

回归点：旧 match_rosters 主键是 (match_key, team_id, player_id)，同一选手的
两个小号会互相覆盖，10 人只剩 9 人；teamId 为空的行还会被静默丢弃。
"""
import os
import sqlite3

os.environ.setdefault('TRAINING_ALLOW_REMOTE', '1')

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from studio_api import create_studio_router  # noqa: E402


KEY = 'verify-10of10'


def _client(tmp_path):
    app = FastAPI()
    app.include_router(create_studio_router(
        tmp_path / 'studio.sqlite3', tmp_path / 'media', tmp_path / 'settings'))
    return TestClient(app)


def _rows():
    rows = []
    for side in ('blue', 'red'):
        for slot in range(5):
            rows.append({
                'matchKey': KEY, 'side': side,
                'role': 'own' if side == 'blue' else 'enemy',
                'slot': slot, 'name': f'昵称-{side}-{slot}',
                'position': '打野', 'hero': f'英雄{slot}',
                # 同一选手占两个槽位：旧主键会覆盖掉其中一个。
                'playerId': f'player-{side}-{slot % 2}',
                'teamId': '', 'ownCamp': 'blue',
            })
    return rows


def test_save_all_ten_rows_with_duplicate_player_ids(tmp_path):
    client = _client(tmp_path)
    resp = client.post('/api/studio/matching/players', json={'rows': _rows()})
    assert resp.status_code == 200
    assert resp.json()['matches'] == 1
    assert resp.json()['nicknames'] == 10

    db = tmp_path / 'studio.sqlite3'
    with sqlite3.connect(db) as connection:
        rosters = connection.execute(
            'SELECT side, slot, player_id FROM match_rosters '
            'WHERE match_key=? ORDER BY side, slot', (KEY,)).fetchall()
        nicknames = connection.execute(
            'SELECT count(*) FROM player_nickname_pool WHERE match_key=?',
            (KEY,)).fetchone()[0]

    assert len(rosters) == 10, f'应落库 10 人，实际 {len(rosters)}'
    assert nicknames == 10, f'昵称池应落库 10 条，实际 {nicknames}'
    # 每个槽位都在，且同一 player_id 占多个槽位时没有互相覆盖。
    assert [(side, slot) for side, slot, _ in rosters] == [
        (side, slot) for side in ('blue', 'red') for slot in range(5)]
    assert len({pid for _, _, pid in rosters}) == 4


def test_save_three_games_of_same_opponent_in_one_request(tmp_path):
    """赛训场景：同一支战队三局、选手没变 → 一次请求把三局全部保存。"""
    client = _client(tmp_path)
    rows = []
    for game_no in range(3):
        key = f'verify-same-opponent-g{game_no + 1}'
        for side in ('blue', 'red'):
            for slot in range(5):
                rows.append({
                    'matchKey': key, 'side': side,
                    'role': 'own' if side == 'blue' else 'enemy',
                    'slot': slot, 'name': f'昵称-{side}-{slot}',
                    'position': '打野', 'hero': f'英雄{slot}',
                    # 三局是同一批选手：ID 不变。
                    'playerId': f'player-{side}-{slot}',
                    'teamId': '', 'ownCamp': 'blue',
                })
    resp = client.post('/api/studio/matching/players', json={'rows': rows})
    assert resp.status_code == 200
    assert resp.json()['matches'] == 3, '三局应一次全部落库'

    with sqlite3.connect(tmp_path / 'studio.sqlite3') as connection:
        per_game = connection.execute(
            'SELECT match_key, count(*) FROM match_rosters '
            "WHERE match_key LIKE 'verify-same-opponent%' "
            'GROUP BY match_key ORDER BY match_key').fetchall()
    assert len(per_game) == 3
    assert [count for _, count in per_game] == [10, 10, 10]


def test_saved_matches_can_be_read_back_after_update(tmp_path):
    """更新/刷新后要能按对局读回已保存的匹配，不能只靠规则和昵称池重算。

    回归点：对手战队改名或规则失效时，归档局的对手一侧会被重算成「待匹配」
    （10/10 变 5/10）。保存时落库的逐局阵容必须可以原样读回。
    """
    client = _client(tmp_path)
    rows = _rows()
    assert client.post('/api/studio/matching/players', json={'rows': rows}).status_code == 200

    resp = client.get('/api/studio/matching/players', params={'matchKey': KEY})
    assert resp.status_code == 200
    saved = resp.json()['rows']
    assert len(saved) == 10
    assert {(r['side'], r['slot'], r['playerId']) for r in saved} == {
        (r['side'], r['slot'], r['playerId']) for r in rows}

    # 不带筛选项时也能读回，供匹配页一次拿到所有归档局的历史匹配。
    all_rows = client.get('/api/studio/matching/players').json()['rows']
    assert len(all_rows) == 10


def test_rule_save_syncs_nickname_pool(tmp_path):
    """只建规则不点归档，选手档案也要能按游戏名认出选手 ID。"""
    client = _client(tmp_path)
    created = client.post('/api/studio/matching/rules', json={
        'side': 'own', 'nickname': '游走喵', 'playerId': 'p-own',
    })
    assert created.status_code == 200

    with sqlite3.connect(tmp_path / 'studio.sqlite3') as connection:
        rows = connection.execute(
            'SELECT side, player_id FROM player_nickname_pool '
            'WHERE nickname=?', ('游走喵',)).fetchall()
    assert rows == [('own', 'p-own')]
