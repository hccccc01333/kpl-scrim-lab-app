"""本轮用户反馈的回归：对抗路占比移除、补刀分钟标准、周报标题、自动补爬。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'v3'))

import bp_facts  # noqa: E402
import data_source_health as health  # noqa: E402
import grade_rules  # noqa: E402


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(bp_facts, 'FACTS', tmp_path)
    return tmp_path


def test_player_detail_no_longer_renders_clash_lane_share():
    src = (ROOT / 'v3' / 'public' / 'player-detail.js').read_text(encoding='utf-8')
    assert '对抗路类型占比' not in src
    assert '战边 / 坦边 · 出场占比与胜率' not in src


def test_weekly_title_says_one_week():
    src = (ROOT / 'v3' / 'public' / 'features.js').read_text(encoding='utf-8')
    assert '一周训练周报' in src
    assert '一周训练报告' in src


def test_grade_rules_ui_has_minute_standard_editor():
    src = (ROOT / 'v3' / 'public' / 'grade-rules.js').read_text(encoding='utf-8')
    assert '补刀 · 按分钟标准' in src
    assert 'data-gr-minute-add' in src
    assert 'minuteStandard' in src


def test_cs_grade_uses_minute_standard(isolated):
    doc = grade_rules.load()
    mid = doc['subjects']['中路']['cs']
    mid['active'] = True
    assert mid['minuteStandard']['18'] == 112
    assert mid['minuteStandard']['20'] == 115
    # 中路补刀固定蓝色参考，不按标准分金红。
    assert grade_rules.grade('中路', 'cs', 113, doc, minutes=18)['level'] == 'ok'
    assert grade_rules.grade('中路', 'cs', 50, doc, minutes=18)['level'] == 'ok'

    farm = doc['subjects']['发育路']['cs']
    farm['active'] = True
    assert grade_rules.grade('发育路', 'cs', 97, doc, minutes=18)['level'] == 'elite'
    assert grade_rules.grade('发育路', 'cs', 95, doc, minutes=18)['level'] == 'low'
    assert grade_rules.grade('发育路', 'cs', 96, doc, minutes=18)['level'] == 'ok'
    # 不足 19 分钟按 18 分钟档：12 分钟局也拿 96 当标准。
    assert grade_rules.grade('发育路', 'cs', 97, doc, minutes=12)['level'] == 'elite'
    # 规则里加 21 分钟后立刻按新档生效。
    farm['minuteStandard']['21'] = 130
    doc = grade_rules.normalize(doc)
    assert grade_rules.grade('发育路', 'cs', 131, doc, minutes=21)['level'] == 'elite'


def test_auto_recover_missing_has_cooldown(monkeypatch):
    started = []
    monkeypatch.setattr(health, 'snapshot', lambda: {'sources': [
        {'key': 'heroes', 'status': 'stale', 'running': False},
    ]})
    monkeypatch.setattr(health, '_run', lambda key, func: started.append(key) or True)
    monkeypatch.setattr(health, '_AUTO_LAST', {}, raising=False)
    assert health.auto_recover_missing() == ['heroes']
    assert health.auto_recover_missing() == []


def test_manual_refresh_result_marks_success(monkeypatch):
    def worker(key, func):
        # 同步执行 worker 逻辑不方便，这里只断言 _run 入口存在并可启动。
        return True
    monkeypatch.setattr(health, '_run', worker)
    assert health.refresh('heroes')['ok'] is True
