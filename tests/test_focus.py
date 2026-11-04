"""训练闭环：指标校验与逐场评估（纯单元；CRUD/备份在 test_app 里走完整服务）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import focus

ROSTER_IDS = {f'b{i}' for i in range(1, 6)}


def confirmed_match(match_id, date, opponent, side, winner, own_players, enemy_players, duration=20):
    players = []
    enemy_side = 'right' if side == 'left' else 'left'
    for side_name, rows in ((side, own_players), (enemy_side, enemy_players)):
        for slot, row in enumerate(rows):
            hero, gold, kills, deaths, assists = row
            players.append({'side': side_name, 'slot': slot,
                            'playerId': f'b{slot + 1}' if side_name == side else None,
                            'hero': hero, 'position': ['对抗路', '打野', '中路', '发育路', '游走'][slot],
                            'kills': kills, 'deaths': deaths, 'assists': assists,
                            'gold': gold, 'damage': 20000, 'taken': 15000,
                            'participation': 60, 'rating': '11.0', 'equipment': ''})
    left_score, right_score = (12, 8) if winner == 'left' else (8, 12)
    return {'id': match_id, 'status': 'confirmed', 'revision': 1, 'date': date, 'opponent': opponent,
            'side': side, 'winner': winner, 'duration': duration, 'session': '训练赛', 'version': '12.1',
            'reviewed': True, 'scores': {'left': left_score, 'right': right_score}, 'imageIds': [],
            'players': players}


class FocusUnitTests(unittest.TestCase):
    def test_validate_item(self):
        with self.assertRaises(ValueError):
            focus.validate_item({'title': 'x', 'metric': 'made_up'}, ROSTER_IDS)
        with self.assertRaises(ValueError):
            focus.validate_item({'title': 'x', 'metric': 'kda', 'scopeType': 'player', 'scopeId': 'ghost'}, ROSTER_IDS)
        with self.assertRaises(ValueError):
            focus.validate_item({'title': 'x', 'metric': 'laneDiff', 'scopeType': 'player', 'scopeId': 'b1'}, ROSTER_IDS)
        item = focus.validate_item({'title': '中路支援', 'metric': 'kda', 'scopeId': 'b1',
                                    'direction': 'up', 'target': '2.0'}, ROSTER_IDS)
        self.assertEqual(item['scopeType'], 'player')
        self.assertEqual(item['target'], 2.0)
        team = focus.validate_item({'title': '全队', 'metric': 'win'}, ROSTER_IDS)
        self.assertEqual(team['scopeType'], 'team')
        lane = focus.validate_item({'title': '上路线', 'metric': 'laneDiff', 'scopeId': '对抗路'}, ROSTER_IDS)
        self.assertEqual(lane['scopeId'], '对抗路')

    def test_evaluate_player_and_team(self):
        own_a = [('铠', 9000, 3, 1, 5), ('李白', 10000, 2, 1, 6), ('貂蝉', 9500, 1, 2, 7),
                 ('后羿', 11000, 4, 1, 3), ('张飞', 7000, 0, 1, 8)]
        enemy_a = [('猪八戒', 8000, 1, 3, 1), ('孙悟空', 8000, 1, 3, 1), ('小乔', 8000, 1, 3, 1),
                   ('狄仁杰', 8000, 1, 3, 1), ('鬼谷子', 8000, 1, 3, 1)]
        own_b = [('铠', 8500, 1, 4, 2), ('李白', 9500, 2, 3, 3), ('貂蝉', 9000, 0, 3, 4),
                 ('后羿', 10000, 1, 4, 2), ('张飞', 6500, 0, 2, 5)]
        enemy_b = [('猪八戒', 9000, 3, 1, 4), ('孙悟空', 9000, 3, 1, 4), ('小乔', 9000, 3, 1, 4),
                   ('狄仁杰', 9000, 3, 1, 4), ('鬼谷子', 9000, 3, 1, 4)]
        matches = [
            confirmed_match('A', '2026-10-01', '对手A', 'left', 'left', own_a, enemy_a),
            confirmed_match('B', '2026-10-02', '对手B', 'left', 'right', own_b, enemy_b),
        ]
        items = focus.evaluate(matches, [
            {'title': '铠的KDA', 'metric': 'kda', 'scopeType': 'player', 'scopeId': 'b1',
             'direction': 'up', 'target': 2.0, 'status': 'active'},
            {'title': '全队经济差', 'metric': 'teamGoldDiff', 'scopeType': 'team', 'scopeId': '',
             'direction': 'up', 'target': None, 'status': 'active'},
        ])
        kda = items[0]
        self.assertEqual([point['value'] for point in kda['points']], [8.0, 0.75])
        self.assertEqual(kda['baseline'], 4.38)  # 基线取前 3 场均值（此处共 2 场）
        self.assertEqual(kda['recent'], 4.38)
        self.assertEqual(kda['targetRate'], 50.0)  # 目标 ≥2.0：两场中一场达标
        team = items[1]
        self.assertEqual([point['value'] for point in team['points']], [6500.0, -1500.0])
        self.assertEqual(team['baseline'], 2500.0)

    def test_lane_diff(self):
        matches = [confirmed_match('A', '2026-10-01', '对手A', 'left', 'left',
                                   [('铠', 9000, 3, 1, 5), ('李白', 10000, 2, 1, 6), ('貂蝉', 9500, 1, 2, 7),
                                    ('后羿', 11000, 4, 1, 3), ('张飞', 7000, 0, 1, 8)],
                                   [('猪八戒', 8000, 1, 3, 1), ('孙悟空', 8000, 1, 3, 1), ('小乔', 8000, 1, 3, 1),
                                    ('狄仁杰', 8000, 1, 3, 1), ('鬼谷子', 8000, 1, 3, 1)])]
        items = focus.evaluate(matches, [{'title': '上路线', 'metric': 'laneDiff', 'scopeType': 'position',
                                          'scopeId': '对抗路', 'direction': 'up', 'target': None, 'status': 'active'}])
        self.assertEqual([point['value'] for point in items[0]['points']], [1000])


if __name__ == '__main__':
    unittest.main()
