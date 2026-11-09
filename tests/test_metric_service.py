import metric_service
import metrics_registry
from workspace_store import Workspace


def setup_workspace(tmp_path):
    ws = Workspace(tmp_path / 'training.sqlite3')
    ws.ensure_schema()
    return ws


def test_registry_has_executable_core_metrics():
    ids = {item['id'] for item in metrics_registry.list_metrics('session')}
    assert {'session.match_count', 'session.win_rate', 'session.avg_duration', 'session.goal_completion'} <= ids
    assert metrics_registry.get_metric('session.gold_diff_10').available is False


def test_session_metrics_and_goal_auto_attainment(tmp_path):
    ws = setup_workspace(tmp_path)
    ws.upsert_match('metric-a', date='2026-11-02', session='验证数据',
                    own_side='blue', winner='blue', duration=600)
    ws.upsert_match('metric-b', date='2026-11-02', session='验证数据',
                    own_side='red', winner='blue', duration=900)
    schedule_id = ws.save_schedule(date='2026-11-02', session='验证数据')
    values = metric_service.compute_session(ws, schedule_id)
    assert values['session.match_count']['value'] == 2
    assert values['session.win_count']['value'] == 1
    assert values['session.loss_count']['value'] == 1
    assert values['session.win_rate']['value'] == 50.0
    assert values['session.avg_duration']['value'] == 750.0

    goals = metric_service.enrich_goals([
        {'label': '胜率达到一半', 'metricId': 'session.win_rate', 'target': '50', 'status': 'pending'},
        {'label': '控制时长', 'metricId': 'session.avg_duration', 'target': '700', 'status': 'pending'},
        {'label': '未接入指标', 'metricId': 'session.gold_diff_10', 'target': '1000', 'status': 'pending'},
    ], values)
    assert goals[0]['status'] == 'achieved'
    assert goals[0]['actual'] == 50.0
    assert goals[1]['status'] == 'missed'
    assert goals[1]['comparator'] == '<='
    assert goals[2]['status'] == 'pending'
    assert goals[2]['missingReason'] == 'source_not_connected'


def test_training_metrics_are_separate_from_match_context(tmp_path):
    ws = setup_workspace(tmp_path)
    ws.upsert_match('training-a', date='2026-11-02', session='验证数据',
                    own_side='blue', winner='blue', duration=600)
    schedule_id = ws.save_schedule(date='2026-11-02', session='验证数据')
    ws.save_session_review(
        schedule_id,
        goals=[{'label': '目标一', 'metricId': 'training.session_review_completion',
                'target': '100', 'status': 'achieved'}],
        review='完成', review_status='done', attendance=[])
    values = metric_service.compute_session(ws, schedule_id)
    assert values['training.session_game_count']['value'] == 1
    assert values['training.session_duration']['value'] == 600
    assert values['training.session_review_completion']['value'] == 100.0
    assert values['training.session_goal_metric_coverage']['value'] == 100.0
    assert values['training.session_goal_completion']['value'] == 100.0
    assert values['session.match_count']['value'] == 1
    assert metrics_registry.get_metric('training.session_game_count').category == 'training'


def test_week_metrics(tmp_path):
    ws = setup_workspace(tmp_path)
    ws.upsert_match('week-a', date='2026-11-03', own_side='blue', winner='blue', duration=600)
    ws.upsert_match('week-b', date='2026-11-04', own_side='blue', winner='red', duration=900)
    ws.upsert_match('week-c', date='2026-11-12', own_side='blue', winner='blue', duration=600)
    data = metric_service.compute_week(ws, '2026-11-02')
    values = data['metrics']
    assert values['week.match_count']['value'] == 2
    assert values['week.win_rate']['value'] == 50.0
    assert values['week.avg_duration']['value'] == 750.0
