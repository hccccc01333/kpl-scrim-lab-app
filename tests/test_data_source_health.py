"""管理页「外部数据源爬取情况」的状态汇总与重试入口。"""
import pathlib

import data_source_health as health

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_snapshot_has_four_cards_with_required_fields():
    doc = health.snapshot()
    assert [card['key'] for card in doc['sources']] == ['heroes', 'kpl', 'peak', 'stats']
    for card in doc['sources']:
        assert card['name'] and card['description'] and card['auto']
        assert card['status'] in ('ok', 'stale', 'warn', 'error', 'running')
        assert isinstance(card['count'], int)
        assert isinstance(card['canRetry'], bool)
    assert set(doc['counts']) >= {'ok', 'stale', 'warn', 'error', 'running'}
    assert doc['offlineHint']


def test_external_name_matching_ignores_form_variants():
    names = health._external_hero_names()
    assert health._norm_hero('元流之子(刺客)') == health._norm_hero('元流之子_刺客')
    have = health._have_hero_names()
    normalized = {health._norm_hero(n) for n in have}
    missing = {n for n in names - health.FORM_ALIASES if health._norm_hero(n) not in normalized}
    assert '刀锋宝贝' not in missing


def test_hero_card_is_ok_after_sync():
    card = health._hero_card()
    assert card['status'] == 'ok', card['detail']
    assert card['count'] >= 140


def test_refresh_rejects_unknown_source():
    result = health.refresh('not-a-source')
    assert result['ok'] is False
    assert '不支持' in result['message']


def test_auto_sync_is_noop_when_nothing_missing():
    assert health.auto_sync_heroes() is False


def test_frontend_wiring():
    app = (ROOT / 'v3' / 'public' / 'app.js').read_text(encoding='utf-8')
    html = (ROOT / 'v3' / 'public' / 'index.html').read_text(encoding='utf-8')
    page = ROOT / 'v3' / 'public' / 'source-health-page.js'
    css = ROOT / 'v3' / 'public' / 'source-health.css'
    assert page.is_file() and css.is_file()
    assert "'source-health', '外部数据源'" in app
    assert "'source-health': () => '<div data-sh-root></div>'" in app
    assert "'管理', ['snapshot-center', 'sources', 'docs', 'source-health']" in app
    assert "createSourceHealthPage" in app
    assert 'source-health.css?v=' in html
