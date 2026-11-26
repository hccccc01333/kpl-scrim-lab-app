"""新英雄同步：官方出了新英雄后，所有英雄名录都要跟得上。

2026-11-17 一批新英雄（刀锋宝贝 / 绯泪 / 星葵 / 卡芬妮 / 索文 / 莉莉安 / 皮皮）
曾只存在于外部 91m 数据与 hero_list 缓存里，头像名录、英雄标签表都没有，
表现为「头像挑不到 / OCR 认不出 / 面板没分路」。
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _json(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def test_new_heroes_are_in_catalog_with_icons():
    catalog = _json('resources/catalog.json')
    heroes = {e['name']: e for e in catalog['entries'] if e.get('kind') == 'hero'}
    for name in ('刀锋宝贝', '绯泪', '星葵', '卡芬妮', '索文', '莉莉安', '皮皮'):
        entry = heroes.get(name)
        assert entry, f'catalog 缺少 {name}'
        assert entry['id'].startswith('hero-')
        assert entry.get('icon', '').startswith('/catalog/icons/hero-')
        assert (ROOT / 'resources' / entry['icon'].replace('/catalog/', '', 1)).is_file(), name


def test_new_heroes_are_in_tags_with_pending_label():
    doc = _json('resources/hero_tags.json')
    heroes = doc['heroes']
    hero = heroes['刀锋宝贝']
    assert hero['id'] == 646
    assert hero['defaultType'] == '待分类'          # 不替赛训组猜打法类型
    assert set(hero['matrix']) == set(doc['capabilityDims'])
    assert all(value == 0 for value in hero['matrix'].values())


def test_every_cached_hero_is_in_catalog_and_tags():
    names = {str(v) for v in _json('resources/builtin/misc/hero_list.json').values()}
    catalog = {e['name'] for e in _json('resources/catalog.json')['entries']
               if e.get('kind') == 'hero'}
    tags = set(_json('resources/hero_tags.json')['heroes'])
    assert names <= catalog, f'catalog 缺少：{sorted(names - catalog)}'
    assert names <= tags, f'hero_tags 缺少：{sorted(names - tags)}'


def test_icon_file_matches_catalog_sha256():
    catalog = _json('resources/catalog.json')
    import hashlib
    for entry in catalog['entries']:
        if entry.get('kind') != 'hero' or not entry.get('sha256') or not entry.get('icon'):
            continue
        path = ROOT / 'resources' / entry['icon'].replace('/catalog/', '', 1)
        if path.is_file():
            assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], entry['name']
