"""赛训组配置的变更历史：记录、摘要、回滚快照、上限。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import bp_facts  # noqa: E402
import config_history  # noqa: E402


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(bp_facts, 'FACTS', tmp_path)
    return tmp_path


def test_record_and_list(isolated):
    old = {'revision': 0, 'pairs': [{'heroes': ['A', 'B']}], 'trios': []}
    new = {'revision': 1, 'pairs': [{'heroes': ['A', 'B']}, {'heroes': ['C', 'D']}], 'trios': []}
    entry = config_history.record('combo_pool', old, new)
    assert entry['revision'] == 2   # 保存后修订号（new 的 revision + 1）
    assert entry['at']
    entries = config_history.list_entries('combo_pool')
    assert len(entries) == 1
    assert entries[0]['id'] == entry['id']
    assert entries[0]['hasSnapshot'] is True
    assert 'doc' not in entries[0]   # 列表不含大快照


def test_snapshot_and_none(isolated):
    old = {'revision': 1, 'subjects': {'游走': {}}}
    config_history.record('grade_rules', old, {'revision': 2})
    config_history.record('grade_rules', None, {'revision': 3})
    entries = config_history.list_entries('grade_rules')
    assert len(entries) == 2
    assert entries[0]['hasSnapshot'] is False   # 最新的一条快照为 None
    assert config_history.get_snapshot('grade_rules', entries[0]['id']) is None
    assert config_history.get_snapshot('grade_rules', entries[1]['id']) == old


def test_diff_summary_combo(isolated):
    old = {'pairs': [{'heroes': ['A', 'B']}, {'heroes': ['C', 'D']}], 'trios': []}
    new = {'pairs': [{'heroes': ['A', 'B']}, {'heroes': ['E', 'F']}], 'trios': [{'heroes': ['A', 'B', 'C']}]}
    s = config_history.diff_summary('combo_pool', old, new)
    assert '双人组合' in s and '删除 1' in s and '新增 1' in s
    assert '三人体系' in s and '新增 1' in s
    assert config_history.diff_summary('combo_pool', None, new) == '首次保存（由内置默认转为自定义）'


def test_diff_summary_grade(isolated):
    old = {'subjects': {'游走': {'participation': {'thresholds': [80, 70, 60]}}}}
    new = {'subjects': {'游走': {'participation': {'thresholds': [90, 80, 70]}}}}
    s = config_history.diff_summary('grade_rules', old, new)
    assert '游走' in s and '阈值' in s


def test_max_entries(isolated):
    for i in range(config_history.MAX_ENTRIES + 5):
        config_history.record('combo_pool', {'revision': i}, {'revision': i + 1})
    entries = config_history.list_entries('combo_pool', limit=100)
    assert len(entries) == config_history.MAX_ENTRIES


def test_clear(isolated):
    config_history.record('combo_pool', {'revision': 0}, {'revision': 1})
    config_history.clear('combo_pool')
    assert config_history.list_entries('combo_pool') == []
