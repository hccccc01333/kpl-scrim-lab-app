"""外部数据源状态语义：0 数据不算正常，成功空同步 / 失败 / 从未同步可区分。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import data_source_health as health  # noqa: E402


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    paths = {
        'CATALOG': tmp_path / 'resources' / 'catalog.json',
        'TAGS': tmp_path / 'resources' / 'hero_tags.json',
        'HERO_LIST': tmp_path / 'data' / 'hero_list.json',
        'KPL_MANIFEST': tmp_path / 'data' / 'kpl' / 'manifest.json',
        'KPL_MANIFEST_SEED': tmp_path / 'resources' / 'builtin' / 'misc' / 'manifest.json',
        'ROLE_POOLS': tmp_path / 'data' / 'peak' / 'matchup_raw' / 'role_pools.json',
        'ROLE_POOLS_SEED': tmp_path / 'resources' / 'builtin' / 'peak' / 'matchup_raw' / 'role_pools.json',
    }
    monkeypatch.setattr(health, 'ROOT', tmp_path)
    for name, path in paths.items():
        monkeypatch.setattr(health, name, path)
    monkeypatch.setattr(health, '_STATE', {'running': {}, 'last': {}})
    monkeypatch.setattr(health, '_external_hero_names', lambda: set())
    import peak_crawl
    monkeypatch.setattr(peak_crawl, 'status', lambda: {})
    return paths


def test_successful_empty_sync_is_not_normal(isolated):
    write_json(isolated['CATALOG'], {'entries': [], 'updatedAt': '2026-11-28T10:00:00'})
    write_json(isolated['KPL_MANIFEST'], {'games': 0, 'updatedAt': '2026-11-28T10:00:00'})
    write_json(health.ROOT / 'data' / 'facts' / 'hero_external_stats.json', {})
    write_json(health.ROOT / 'data' / 'peak' / 'state.json', {
        'startedAt': '2026-11-28T09:00:00', 'finishedAt': '2026-11-28T10:00:00',
        'lastError': '', 'pairs': 0,
    })

    doc = health.snapshot()

    assert doc['counts']['ok'] == 0
    assert doc['counts']['warn'] == 4
    assert len(doc['needsAction']) == 4
    for card in doc['sources']:
        assert card['count'] == 0
        assert card['syncState'] == 'success-empty'
        assert card['status'] == 'warn'
        assert card['label'] == '已同步·无数据'
        assert card['canRetry'] is True


def test_never_synced_is_distinct_from_successful_empty(isolated):
    doc = health.snapshot()

    assert doc['counts']['ok'] == 0
    assert doc['counts']['warn'] == 4
    for card in doc['sources']:
        assert card['count'] == 0
        assert card['syncState'] == 'never'
        assert card['label'] == '从未同步'
        assert card['status'] == 'warn'


def test_failure_overrides_cached_success_and_preserves_data(isolated):
    write_json(isolated['CATALOG'], {
        'entries': [{'kind': 'hero', 'name': '甲'}], 'updatedAt': '2026-11-28T10:00:00',
    })
    health._STATE['last']['heroes'] = {'ok': False, 'message': '同步失败：网络中断'}
    write_json(health.ROOT / 'data' / 'peak' / 'state.json', {
        'startedAt': '2026-11-28T09:00:00', 'finishedAt': '2026-11-28T10:00:00',
        'lastError': 'timeout', 'pairs': 0,
    })
    write_json(isolated['KPL_MANIFEST'], {
        'games': 0, 'errors': 2, 'updatedAt': '2026-11-28T10:00:00',
    })

    cards = {card['key']: card for card in health.snapshot()['sources']}

    assert cards['heroes']['status'] == 'error'
    assert cards['heroes']['syncState'] == 'failure'
    assert cards['heroes']['label'] == '同步失败'
    assert '网络中断' in cards['heroes']['detail']
    assert '仍保留' in cards['heroes']['detail']
    assert cards['peak']['syncState'] == 'failure'
    assert cards['peak']['label'] == '同步失败'
    assert cards['kpl']['syncState'] == 'failure'
    assert cards['kpl']['label'] == '同步失败'


def test_persisted_peak_state_survives_process_restart(isolated):
    write_json(health.ROOT / 'data' / 'peak' / 'state.json', {
        'startedAt': '2026-11-28T09:00:00', 'finishedAt': '2026-11-28T10:00:00',
        'lastError': '', 'pairs': 0,
    })

    card = health._peak_card()

    assert card['syncState'] == 'success-empty'
    assert card['label'] == '已同步·无数据'
    assert card['status'] == 'warn'


def test_external_peak_running_is_not_marked_empty_or_failure(isolated, monkeypatch):
    import peak_crawl
    monkeypatch.setattr(peak_crawl, 'status', lambda: {
        'running': True, 'pairs': 0, 'finishedAt': '2026-11-28T09:00:00', 'lastError': '',
    })
    health._STATE['last']['peak'] = {'ok': False, 'message': '同步失败：已有一轮刷新在跑'}

    card = health._peak_card()

    assert card['status'] == 'running'
    assert card['syncState'] == 'running'
    assert card['label'] == '正在同步'
    assert card['canRetry'] is True


def test_peak_refresh_concurrency_skip_is_not_a_failure(isolated, monkeypatch):
    import peak_crawl
    monkeypatch.setattr(peak_crawl, 'status', lambda: {'running': True})
    monkeypatch.setattr(peak_crawl, 'refresh', lambda **kwargs: pytest.fail('不应重复启动刷新'))

    result = health._refresh_peak()

    assert result['ok'] is True
    assert result['skipped'] is True


def test_all_four_sources_use_the_same_refresh_entry(isolated, monkeypatch):
    calls = []

    def fake_run(key, func):
        calls.append((key, callable(func)))
        return True

    monkeypatch.setattr(health, '_run', fake_run)
    assert all(card['canRetry'] for card in health.snapshot()['sources'])
    for key in ('heroes', 'kpl', 'peak', 'stats'):
        assert health.refresh(key)['ok'] is True
    assert calls == [(key, True) for key in ('heroes', 'kpl', 'peak', 'stats')]


def test_auto_recovery_includes_local_stats_rebuild(isolated, monkeypatch):
    calls = []
    monkeypatch.setattr(health, 'snapshot', lambda: {'sources': [{
        'key': 'stats', 'status': 'warn', 'syncState': 'never', 'running': False,
    }]})
    monkeypatch.setattr(health, '_AUTO_LAST', {})
    monkeypatch.setattr(health, '_run', lambda key, func: calls.append((key, callable(func))) or True)

    assert health.auto_recover_missing() == ['stats']
    assert calls == [('stats', True)]


def test_frontend_has_one_reload_entry_and_native_disclosure():
    page = (ROOT / 'v3' / 'public' / 'source-health-page.js').read_text(encoding='utf-8')
    assert 'class="control sh-refresh" data-sh-reload' in page
    assert '<details class="sh-status-details" data-sh-status-details>' in page
    assert 'data-sync-state=' in page
    assert "card.syncState === 'success-empty'" in page
    assert "card.syncState === 'never'" in page
    assert '重新同步' in page
    assert '重新爬取' not in page
    assert 'openSources.has' in page
    assert 'setInterval(' not in page
    assert 'pending ? 3000 : 30000' in page
