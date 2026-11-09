"""指标查询服务：训练课/周报/目标达成共用一套口径。

P0 只从 match_records 与 schedules 计算；缺时间轴/逐人面板的指标返回
missingReason，不返回 0，也不在前端另算一套。
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

import metrics_registry


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _target_number(value):
    text = str(value or '').replace(',', '').strip()
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group(0)) if match else None


def _json_list(raw):
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw or '[]')
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _goal_list(value):
    goals = _json_list(value)
    out = []
    for item in goals:
        if isinstance(item, str):
            out.append({'label': item, 'status': 'pending'})
        elif isinstance(item, dict):
            out.append(dict(item))
    return out


def _match_result(match):
    own = str(match.get('own_side') or '')
    winner = str(match.get('winner') or '')
    if own in ('blue', 'red') and winner in ('blue', 'red'):
        return 'win' if own == winner else 'loss'
    return None


def _metric(defn, value, *, sample_size=0, expected=0, reason=None, source=None):
    coverage = (sample_size / expected) if expected else (1.0 if value is not None else 0.0)
    return {
        'id': defn.id,
        'label': defn.label,
        'entity': defn.entity,
        'unit': defn.unit,
        'value': value,
        'sampleSize': int(sample_size or 0),
        'expected': int(expected or 0),
        'coverage': round(min(1.0, max(0.0, coverage)), 3) if expected else None,
        'source': list(source or defn.source),
        'direction': defn.direction,
        'missingReason': reason,
        'version': defn.version,
    }


def _missing(defn, reason):
    return _metric(defn, None, reason=reason)


def _compute(prefix, matches, goals):
    values = {}
    total = len(matches)
    results = [_match_result(match) for match in matches]
    wins = results.count('win')
    losses = results.count('loss')
    decided = wins + losses
    durations = [float(match['duration']) for match in matches
                 if _number(match.get('duration')) and float(match['duration']) > 0]
    completed = sum(1 for goal in goals if goal.get('status') == 'achieved')
    goal_total = len(goals)

    for defn in metrics_registry.list_metrics(prefix):
        if defn.get('category') != 'performance':
            continue
        metric_id = defn['id']
        if metric_id.endswith('.match_count'):
            values[metric_id] = _metric(metrics_registry.get_metric(metric_id), total,
                                        sample_size=total, expected=total)
        elif metric_id.endswith('.win_count'):
            values[metric_id] = _metric(metrics_registry.get_metric(metric_id), wins,
                                        sample_size=decided, expected=total)
        elif metric_id.endswith('.loss_count'):
            values[metric_id] = _metric(metrics_registry.get_metric(metric_id), losses,
                                        sample_size=decided, expected=total)
        elif metric_id.endswith('.win_rate'):
            value = round(wins / decided * 100, 1) if decided else None
            values[metric_id] = _metric(metrics_registry.get_metric(metric_id), value,
                                        sample_size=decided, expected=total,
                                        reason=None if decided else 'no_decided_matches')
        elif metric_id.endswith('.avg_duration'):
            value = round(sum(durations) / len(durations), 1) if durations else None
            values[metric_id] = _metric(metrics_registry.get_metric(metric_id), value,
                                        sample_size=len(durations), expected=total,
                                        reason=None if durations else 'no_duration')
        elif metric_id.endswith('.goal_completion'):
            value = round(completed / goal_total * 100, 1) if goal_total else None
            values[metric_id] = _metric(metrics_registry.get_metric(metric_id), value,
                                        sample_size=goal_total, expected=goal_total,
                                        reason=None if goal_total else 'no_goals')
        else:
            values[metric_id] = _missing(metrics_registry.get_metric(metric_id), 'source_not_connected')
    return values


def _goal_coverage(goals):
    if not goals:
        return None
    bound = 0
    for goal in goals:
        metric = metrics_registry.get_metric(str(goal.get('metricId') or ''))
        if metric and metric.available:
            bound += 1
    return round(bound / len(goals) * 100, 1)


def _link_coverage(ws, matches):
    if not matches:
        return None
    team_ids = {team['id'] for team in ws.list_teams()}
    linked = sum(1 for match in matches if str(match.get('enemy_team_id') or '') in team_ids)
    return round(linked / len(matches) * 100, 1)


def _duration(matches):
    values = [float(match['duration']) for match in matches
              if _number(match.get('duration')) and float(match['duration']) > 0]
    return sum(values) if values else None, len(values)


def _training_session(ws, schedule, matches):
    goals = _goal_list(schedule.get('goals'))
    completed = sum(1 for goal in goals if goal.get('status') == 'achieved')
    duration, duration_samples = _duration(matches)
    attendance = _json_list(schedule.get('attendance'))
    players = ws.list_players()
    attendance_rate = (round(len(attendance) / len(players) * 100, 1)
                       if players and attendance else None)
    values = {
        'training.session_game_count': _metric(
            metrics_registry.get_metric('training.session_game_count'), len(matches),
            sample_size=len(matches), expected=len(matches)),
        'training.session_duration': _metric(
            metrics_registry.get_metric('training.session_duration'), duration,
            sample_size=duration_samples, expected=len(matches),
            reason=None if duration is not None else 'no_duration'),
        'training.session_goal_count': _metric(
            metrics_registry.get_metric('training.session_goal_count'), len(goals),
            sample_size=len(goals), expected=len(goals)),
        'training.session_goal_completion': _metric(
            metrics_registry.get_metric('training.session_goal_completion'),
            round(completed / len(goals) * 100, 1) if goals else None,
            sample_size=len(goals), expected=len(goals),
            reason=None if goals else 'no_goals'),
        'training.session_goal_metric_coverage': _metric(
            metrics_registry.get_metric('training.session_goal_metric_coverage'), _goal_coverage(goals),
            sample_size=len(goals), expected=len(goals),
            reason=None if goals else 'no_goals'),
        'training.session_review_completion': _metric(
            metrics_registry.get_metric('training.session_review_completion'),
            100.0 if schedule.get('review_status') == 'done' else 0.0,
            sample_size=1, expected=1),
        'training.session_attendance_count': _metric(
            metrics_registry.get_metric('training.session_attendance_count'), len(attendance),
            sample_size=len(attendance), expected=len(players) or len(attendance)),
        'training.session_attendance_rate': _metric(
            metrics_registry.get_metric('training.session_attendance_rate'), attendance_rate,
            sample_size=len(attendance), expected=len(players),
            reason=None if attendance_rate is not None else ('no_roster' if not players else 'no_attendance')),
        'training.session_match_link_coverage': _metric(
            metrics_registry.get_metric('training.session_match_link_coverage'), _link_coverage(ws, matches),
            sample_size=len(matches), expected=len(matches),
            reason=None if matches else 'no_matches'),
    }
    return values


def _training_week(ws, schedules, matches):
    # 周训练指标只统计「挂到训练课上的对局」，不把同周未归课的比赛算进训练负荷。
    linked = {}
    for schedule in schedules:
        for match in ws.session_matches(schedule).get('matches') or []:
            linked[str(match.get('match_key'))] = match
    matches = list(linked.values())
    session_count = len(schedules)
    goals = []
    for schedule in schedules:
        goals.extend(_goal_list(schedule.get('goals')))
    completed = sum(1 for goal in goals if goal.get('status') == 'achieved')
    reviewed = sum(1 for schedule in schedules if schedule.get('review_status') == 'done')
    duration, duration_samples = _duration(matches)
    attendance = []
    for schedule in schedules:
        attendance.extend(_json_list(schedule.get('attendance')))
    players = ws.list_players()
    attendance_rate = (round(len(set(attendance)) / len(players) * 100, 1)
                       if players and attendance else None)
    dates = sorted(str(schedule.get('date') or '') for schedule in schedules if schedule.get('date'))
    first, last = (dates[0], dates[-1]) if dates else ('9999-12-31', '0000-01-01')
    connection = ws.connect()
    try:
        interventions = connection.execute(
            'SELECT COUNT(*) FROM training WHERE start_date <= ? AND IFNULL(end_date, ?) >= ?',
            (last, last, first)).fetchone()[0]
    except Exception:  # noqa: BLE001
        interventions = 0
    finally:
        connection.close()
    values = {
        'training.week_session_count': _metric(
            metrics_registry.get_metric('training.week_session_count'), session_count,
            sample_size=session_count, expected=session_count),
        'training.week_game_count': _metric(
            metrics_registry.get_metric('training.week_game_count'), len(matches),
            sample_size=len(matches), expected=len(matches)),
        'training.week_duration': _metric(
            metrics_registry.get_metric('training.week_duration'), duration,
            sample_size=duration_samples, expected=len(matches),
            reason=None if duration is not None else 'no_duration'),
        'training.week_goal_count': _metric(
            metrics_registry.get_metric('training.week_goal_count'), len(goals),
            sample_size=len(goals), expected=len(goals)),
        'training.week_goal_completion': _metric(
            metrics_registry.get_metric('training.week_goal_completion'),
            round(completed / len(goals) * 100, 1) if goals else None,
            sample_size=len(goals), expected=len(goals),
            reason=None if goals else 'no_goals'),
        'training.week_goal_metric_coverage': _metric(
            metrics_registry.get_metric('training.week_goal_metric_coverage'), _goal_coverage(goals),
            sample_size=len(goals), expected=len(goals),
            reason=None if goals else 'no_goals'),
        'training.week_review_completion': _metric(
            metrics_registry.get_metric('training.week_review_completion'),
            round(reviewed / session_count * 100, 1) if session_count else None,
            sample_size=session_count, expected=session_count,
            reason=None if session_count else 'no_sessions'),
        'training.week_attendance_rate': _metric(
            metrics_registry.get_metric('training.week_attendance_rate'), attendance_rate,
            sample_size=len(set(attendance)), expected=len(players),
            reason=None if attendance_rate is not None else ('no_roster' if not players else 'no_attendance')),
        'training.week_match_link_coverage': _metric(
            metrics_registry.get_metric('training.week_match_link_coverage'), _link_coverage(ws, matches),
            sample_size=len(matches), expected=len(matches),
            reason=None if matches else 'no_matches'),
        'training.week_intervention_count': _metric(
            metrics_registry.get_metric('training.week_intervention_count'), interventions,
            sample_size=interventions, expected=interventions),
        'training.week_effect_mean': _missing(
            metrics_registry.get_metric('training.week_effect_mean'), 'source_not_connected'),
    }
    return values


def compute_session(ws, schedule_id, override=None):
    schedule = ws.get_schedule(schedule_id)
    if not schedule:
        return {}
    if override:
        schedule = dict(schedule)
        schedule.update(override)
    linked = ws.session_matches(schedule)
    matches = linked.get('matches') or []
    goals = _goal_list(schedule.get('goals'))
    values = _compute('session', matches, goals)
    values.update(_training_session(ws, schedule, matches))
    return values


def week_range(start=None):
    if start and re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(start)):
        first = date.fromisoformat(str(start))
    else:
        today = date.today()
        first = today - timedelta(days=(today.weekday()))
    last = first + timedelta(days=6)
    return first.isoformat(), last.isoformat()


def compute_week(ws, start=None):
    first, last = week_range(start)
    schedules = [schedule for schedule in ws.list_schedules()
                 if first <= str(schedule.get('date') or '') <= last]
    matches = [match for match in ws.available_matches(500)
               if first <= str(match.get('date') or '') <= last]
    goals = []
    for schedule in schedules:
        goals.extend(_goal_list(schedule.get('goals')))
    values = _compute('week', matches, goals)
    values.update(_training_week(ws, schedules, matches))
    return {'start': first, 'end': last, 'metrics': values}


def _val(metrics, metric_id):
    return (metrics.get(metric_id) or {}).get('value')


def dashboard(ws, weeks=8):
    """赛训看板：最近 N 周训练过程指标、训练日热力、目标结构和最近训练课。"""
    weeks = max(2, min(16, int(weeks or 8)))
    today = date.today()
    current_start = today - timedelta(days=today.weekday())
    starts = [current_start - timedelta(days=7 * offset) for offset in range(weeks - 1, -1, -1)]
    week_items = []
    for first in starts:
        data = compute_week(ws, first.isoformat())
        metrics = data['metrics']
        week_items.append({
            'start': data['start'],
            'end': data['end'],
            'label': f'{data["start"][5:]}–{data["end"][5:]}',
            'sessionCount': _val(metrics, 'training.week_session_count') or 0,
            'gameCount': _val(metrics, 'training.week_game_count') or 0,
            'duration': _val(metrics, 'training.week_duration'),
            'goalCompletion': _val(metrics, 'training.week_goal_completion'),
            'reviewCompletion': _val(metrics, 'training.week_review_completion'),
            'goalMetricCoverage': _val(metrics, 'training.week_goal_metric_coverage'),
            'linkCoverage': _val(metrics, 'training.week_match_link_coverage'),
        })
    schedules = ws.list_schedules()
    teams = {team['id']: team['name'] for team in ws.list_teams(include_archived=True)}
    day_map = {}
    for schedule in schedules:
        linked = ws.session_matches(schedule).get('matches') or []
        day = str(schedule.get('date') or '')
        if not day:
            continue
        bucket = day_map.setdefault(day, {'sessions': 0, 'games': 0})
        bucket['sessions'] += 1
        bucket['games'] += len(linked)
    first_day = starts[0]
    last_day = starts[-1] + timedelta(days=6)
    days = []
    cursor = first_day
    while cursor <= last_day:
        key = cursor.isoformat()
        bucket = day_map.get(key, {'sessions': 0, 'games': 0})
        days.append({'date': key, 'weekday': cursor.weekday(), 'sessions': bucket['sessions'],
                     'games': bucket['games']})
        cursor += timedelta(days=1)
    current_schedules = [schedule for schedule in schedules
                         if starts[-1].isoformat() <= str(schedule.get('date') or '') <= (starts[-1] + timedelta(days=6)).isoformat()]
    goal_counts = {'achieved': 0, 'partial': 0, 'missed': 0, 'pending': 0}
    for schedule in current_schedules:
        for goal in _goal_list(schedule.get('goals')):
            status = goal.get('status') if goal.get('status') in goal_counts else 'pending'
            goal_counts[status] += 1
    recent = []
    for schedule in sorted(schedules, key=lambda item: str(item.get('date') or ''), reverse=True)[:6]:
        linked = ws.session_matches(schedule).get('matches') or []
        goals = _goal_list(schedule.get('goals'))
        recent.append({
            'id': schedule.get('id'),
            'date': schedule.get('date'),
            'opponent': teams.get(str(schedule.get('opponent_team_id') or ''), '未指定对手'),
            'session': schedule.get('session') or '训练组未定',
            'games': len(linked),
            'goals': len(goals),
            'achieved': sum(1 for goal in goals if goal.get('status') == 'achieved'),
            'reviewed': schedule.get('review_status') == 'done',
        })
    return {'weeks': week_items, 'days': days, 'goals': goal_counts, 'recent': recent,
            'current': week_items[-1] if week_items else None}


def goal_metrics():
    return metrics_registry.goal_metrics()


def _comparator(goal, metric):
    explicit = str(goal.get('comparator') or '').strip()
    if explicit in ('>=', '<=', '>', '<', '=='):
        return explicit
    return '<=' if metric and metric.get('direction') == -1 else '>='


def _compare(actual, target, comparator):
    if actual is None or target is None:
        return None
    if comparator == '>=':
        return actual >= target
    if comparator == '>':
        return actual > target
    if comparator == '<=':
        return actual <= target
    if comparator == '<':
        return actual < target
    return actual == target


def enrich_goals(goals, values):
    """用指标结果刷新目标状态；指标不可用或没有目标值时保留人工状态。"""
    out = []
    for raw in goals or []:
        goal = dict(raw) if isinstance(raw, dict) else {'label': str(raw)}
        metric_id = str(goal.get('metricId') or '').strip()
        metric = values.get(metric_id) if metric_id else None
        target = _target_number(goal.get('target'))
        actual = metric.get('value') if metric else None
        reason = metric.get('missingReason') if metric else ('no_metric' if not metric_id else 'unknown_metric')
        if metric and actual is not None and target is not None:
            comparator = _comparator(goal, metric)
            passed = _compare(actual, target, comparator)
            goal['actual'] = actual
            goal['comparator'] = comparator
            goal['auto'] = True
            goal['status'] = 'achieved' if passed else 'missed'
            goal['missingReason'] = None
        else:
            goal.setdefault('status', 'pending')
            goal['actual'] = actual if actual is not None else None
            goal['auto'] = False
            if target is None:
                reason = 'no_target'
            goal['missingReason'] = reason
        out.append(goal)
    return out


def enrich_schedule(ws, schedule):
    """给 API 返回的训练课补上只读的指标与目标评估，不写回数据库。"""
    if not schedule:
        return schedule
    values = compute_session(ws, schedule.get('id'))
    result = dict(schedule)
    result['goals'] = json.dumps(enrich_goals(_goal_list(schedule.get('goals')), values),
                                 ensure_ascii=False)
    result['metrics'] = values
    return result
