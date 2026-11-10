"""营地派生卡片（dataBehaviorV2）与「清单直拉回放」的参数拼装。

这两件事都属于「数据一直在，只是没人读」：卡片在 camp_details 里，
gameSvrId / relaySvrId 在 camp_lists 里。测试只锁解析与对齐，不发网络请求。
"""
import json
import tempfile
import unittest
from pathlib import Path

import camp_replay
import camp_tiles


def role(position, hero, blocks):
    return {'battleRecords': {'position': position,
                              'usedHero': {'heroName': hero}},
            'dataBehaviorV2': blocks}


def block(title, items):
    return {'title': title,
            'dataCounts': [{'name': name, 'data': value, 'dataNote': note}
                           for name, value, note in items]}


class ParseValueTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(camp_tiles.parse_value('16'), (16.0, ''))
        self.assertEqual(camp_tiles.parse_value('10.7'), (10.7, ''))
        self.assertEqual(camp_tiles.parse_value('71%'), (71.0, '%'))
        self.assertEqual(camp_tiles.parse_value('38S'), (38.0, 's'))
        self.assertEqual(camp_tiles.parse_value('2.3万'), (23000.0, ''))
        self.assertEqual(camp_tiles.parse_value(12), (12.0, ''))

    def test_unparsable_keeps_raw_only(self):
        self.assertEqual(camp_tiles.parse_value('--'), (None, ''))
        self.assertEqual(camp_tiles.parse_value(''), (None, ''))
        self.assertEqual(camp_tiles.parse_value(None), (None, ''))


class ParseTilesTests(unittest.TestCase):
    def test_groups_order_and_known_keys(self):
        tiles = camp_tiles.parse_tiles(role(4, '钟馗', [
            block('分路表现', [('视野价值', '32', '5%')]),
            block('团队贡献', [('控制时长', '49S', '1%')]),
            block('战斗操作', [('勾中敌方英雄', '16', '100%')]),
        ]))
        self.assertEqual([tile['group'] for tile in tiles], ['lane', 'team', 'fight'])
        self.assertEqual([tile['name'] for tile in tiles], ['视野价值', '控制时长', '勾中敌方英雄'])
        self.assertEqual(tiles[0]['key'], 'vision')
        self.assertEqual(tiles[0]['value'], 32.0)
        self.assertEqual(tiles[1]['unit'], 's')
        self.assertEqual(tiles[2]['key'], 'hook_hit')
        self.assertIn('游走', tiles[2]['roles'])

    def test_unknown_tile_is_kept_verbatim(self):
        tiles = camp_tiles.parse_tiles(role(3, '孙悟空', [block('分路表现', [('未来新卡', '7', '')])]))
        self.assertEqual(tiles[0]['name'], '未来新卡')
        self.assertEqual(tiles[0]['key'], '')
        self.assertEqual(tiles[0]['raw'], '7')

    def test_missing_block_yields_empty_list(self):
        self.assertEqual(camp_tiles.parse_tiles({'battleRecords': {}}), [])
        self.assertEqual(camp_tiles.parse_tiles({}), [])


class AttachTests(unittest.TestCase):
    def _detail_file(self, folder, seq):
        payload = {'data': {
            'blueRoles': [role(4, '钟馗', [block('团队贡献', [('视野价值', '32', '')])])],
            'redRoles': [role(2, '公孙离', [block('分路表现', [('经济转有效伤害', '6.9', '')])])],
        }}
        (folder / f'{seq}.json').write_text(json.dumps(payload, ensure_ascii=False),
                                            encoding='utf-8')

    def test_attach_by_camp_and_hero(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            self._detail_file(folder, '1793606215')
            detail = {
                'officialReplay': {'id': 'camp-1793606215'},
                'players': [
                    {'camp': 'blue', 'hero': '钟馗', 'position': ''},
                    {'camp': 'red', 'hero': '公孙离', 'position': ''},
                    {'camp': 'blue', 'hero': '不在面板上'},
                ],
            }
            camp_tiles.attach(detail, folder)
            self.assertEqual(detail['campTilesSource']['players'], 2)
            self.assertEqual(detail['players'][0]['campTiles'][0]['name'], '视野价值')
            self.assertEqual(detail['players'][0]['position'], '游走')
            self.assertEqual(detail['players'][1]['campTiles'][0]['value'], 6.9)
            self.assertNotIn('campTiles', detail['players'][2])

    def test_missing_file_leaves_players_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            detail = {'officialReplay': {'id': 'camp-404'},
                      'players': [{'camp': 'blue', 'hero': '钟馗'}]}
            camp_tiles.attach(detail, Path(temp))
            self.assertNotIn('campTiles', detail['players'][0])
            self.assertNotIn('campTilesSource', detail)

    def test_sources_as_list_does_not_crash(self):
        detail = {'sources': ['bundle'], 'players': []}
        self.assertEqual(camp_tiles.game_seq(detail), '')
        camp_tiles.attach(detail, Path('.'))
        self.assertEqual(detail['players'], [])


class LinkFromEntryTests(unittest.TestCase):
    ENTRY = {'gameSeq': '1793803913', 'gameSvrId': '120245', 'relaySvrId': '-1656708288',
             'battleType': 12, 'pvpType': 5,
             'analyseUrl': 'https://camp.qq.com/h5/webdist/team-analyzev2.html'
                           '?gameseq=1793803913&relaysvrentity=-1656708288&playerid=1085983157'}

    def test_builds_link_from_list_entry(self):
        link = camp_replay.link_from_entry(self.ENTRY)
        self.assertEqual(link['kind'], 'personal')
        self.assertEqual(link['gameSvr'], '120245')
        self.assertEqual(link['relaySvr'], '-1656708288')
        # playerid 从 analyseUrl 取：清单里没有独立的 playerId 字段
        self.assertEqual(link['playerId'], '1085983157')
        self.assertEqual(link['battleType'], '12')

    def test_missing_server_ids_are_rejected(self):
        for broken in ({'gameSeq': '1'}, {'gameSeq': '1', 'gameSvrId': '2'}):
            with self.assertRaises(camp_replay.CampReplayError):
                camp_replay.link_from_entry(broken)

    def test_payload_matches_personal_endpoint_contract(self):
        payload = camp_replay.payload_for(camp_replay.link_from_entry(self.ENTRY))
        self.assertEqual(payload['gameSeq'], '1793803913')
        self.assertEqual(payload['gameSvr'], '120245')
        self.assertEqual(payload['relaySvr'], '-1656708288')
        self.assertNotIn('eId', payload)


if __name__ == '__main__':
    unittest.main()
