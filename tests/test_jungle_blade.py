"""打野刀 → 打野定位标签：同一英雄按本局出装区分坦野 / 野核。"""
import camp_tiles
import jungle_blade


def test_classify_blade_types():
    assert jungle_blade.classify(['巡守利斧', '抵抗之靴'])['kind'] == 'tank'
    assert jungle_blade.classify(['巨人之握'])['type'] == '坦野'
    red = jungle_blade.classify(['贪婪之噬', '影刃'])
    assert red['kind'] == 'core' and red['blade'] == '贪婪之噬'
    assert jungle_blade.classify(['追击刀锋'])['kind'] == 'core'
    assert jungle_blade.classify(['游击弯刀'])['kind'] == 'core'
    assert jungle_blade.classify(['符文大剑'])['kind'] == 'core'


def test_no_blade_returns_none():
    assert jungle_blade.classify([]) is None
    assert jungle_blade.classify(['抵抗之靴', '暗影战斧']) is None
    assert jungle_blade.classify(None) is None
    assert jungle_blade.classify('贪婪之噬') is None   # 必须是列表


def test_same_hero_different_blade_different_tag():
    """大司命：肉刀坦野、红刀野核，同一英雄两种口径。"""
    tank = jungle_blade.classify(['巨人之握'])
    core = jungle_blade.classify(['贪婪之噬'])
    assert tank['kind'] != core['kind']


def test_attach_reads_blade_from_camp_panel(tmp_path):
    """营地面板的 finalEquips 要挂到打野 player 的 blade 字段。"""
    seq = '123'
    panel = {'data': {'blueRoles': [{
        'basicInfo': {},
        'battleRecords': {
            'usedHero': {'heroName': '大司命'}, 'position': 3,
            'finalEquips': [{'equipId': 1533, 'equipName': '贪婪之噬'}],
        },
    }], 'redRoles': []}}
    (tmp_path / f'{seq}.json').write_text(
        __import__('json').dumps(panel, ensure_ascii=False), encoding='utf-8')

    detail = {'officialReplay': {'id': f'camp-{seq}'},
              'players': [{'camp': 'blue', 'hero': '大司命', 'position': '打野'}]}
    camp_tiles.attach(detail, tmp_path)
    blade = detail['players'][0].get('blade')
    assert blade and blade['blade'] == '贪婪之噬' and blade['kind'] == 'core'


def test_attach_ignores_non_jungle_blade(tmp_path):
    """非打野位不出打野刀，即便装备里有也不挂（避免误标）。"""
    seq = '124'
    panel = {'data': {'blueRoles': [{
        'battleRecords': {
            'usedHero': {'heroName': '张良'}, 'position': 1,
            'finalEquips': [{'equipId': 1533, 'equipName': '贪婪之噬'}],
        },
    }], 'redRoles': []}}
    (tmp_path / f'{seq}.json').write_text(
        __import__('json').dumps(panel, ensure_ascii=False), encoding='utf-8')
    detail = {'officialReplay': {'id': f'camp-{seq}'},
              'players': [{'camp': 'blue', 'hero': '张良', 'position': '中路'}]}
    camp_tiles.attach(detail, tmp_path)
    assert 'blade' not in detail['players'][0]
