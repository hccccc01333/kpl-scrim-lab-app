"""赛训指标注册表：指标定义是运行时契约，新增指标先在这里登记。

当前 P0 只计算比赛结果与训练课/周维度的指标；依赖时间轴、逐人面板的指标
先登记为「数据源未接入」，查询服务会返回 missingReason，而不是 0。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class MetricDefinition:
    id: str
    label: str
    entity: str
    unit: str
    description: str
    source: tuple[str, ...]
    direction: int = 1
    available: bool = False
    category: str = 'performance'
    version: int = 1


def _m(*args, **kwargs) -> MetricDefinition:
    return MetricDefinition(*args, **kwargs)


METRICS: dict[str, MetricDefinition] = {
    # 赛训过程：训练管理的主指标，不把胜率/时长当训练成绩
    'training.session_game_count': _m(
        'training.session_game_count', '训练局数', 'session', 'count',
        '本场训练课实际完成的对局数量', ('match_records',), category='training', available=True),
    'training.session_duration': _m(
        'training.session_duration', '训练总时长', 'session', 'seconds',
        '本场训练课关联对局的总时长', ('match_records',), direction=0, category='training', available=True),
    'training.session_goal_count': _m(
        'training.session_goal_count', '训练目标数', 'session', 'count',
        '本场设置的训练目标数量', ('schedules',), category='training', available=True),
    'training.session_goal_completion': _m(
        'training.session_goal_completion', '目标达成率', 'session', 'percent',
        '本场训练目标中状态为达成的比例', ('schedules',), category='training', available=True),
    'training.session_goal_metric_coverage': _m(
        'training.session_goal_metric_coverage', '目标绑定指标覆盖率', 'session', 'percent',
        '本场目标中绑定了可计算指标的比例', ('schedules', 'metrics_registry'), category='training', available=True),
    'training.session_review_completion': _m(
        'training.session_review_completion', '复盘完成率', 'session', 'percent',
        '本场训练课是否已完成赛后复盘', ('schedules',), category='training', available=True),
    'training.session_attendance_count': _m(
        'training.session_attendance_count', '出勤人数', 'session', 'count',
        '本场记录到出勤的选手数量', ('schedules', 'players'), category='training', available=True),
    'training.session_attendance_rate': _m(
        'training.session_attendance_rate', '出勤率', 'session', 'percent',
        '出勤人数 / 本队有效选手数', ('schedules', 'players'), category='training', available=False),
    'training.session_match_link_coverage': _m(
        'training.session_match_link_coverage', '对局关联覆盖率', 'session', 'percent',
        '本场已关联到有效对手的对局比例', ('match_records', 'teams'), category='training', available=True),

    # 周维度赛训指标
    'training.week_session_count': _m(
        'training.week_session_count', '训练课数', 'week', 'count',
        '本周登记的训练课数量', ('schedules',), category='training', available=True),
    'training.week_game_count': _m(
        'training.week_game_count', '训练局数', 'week', 'count',
        '本周训练课关联的对局数量', ('match_records',), category='training', available=True),
    'training.week_duration': _m(
        'training.week_duration', '训练总时长', 'week', 'seconds',
        '本周训练课关联对局的总时长', ('match_records',), direction=0, category='training', available=True),
    'training.week_goal_count': _m(
        'training.week_goal_count', '训练目标数', 'week', 'count',
        '本周训练目标总数', ('schedules',), category='training', available=True),
    'training.week_goal_completion': _m(
        'training.week_goal_completion', '目标达成率', 'week', 'percent',
        '本周训练目标中状态为达成的比例', ('schedules',), category='training', available=True),
    'training.week_goal_metric_coverage': _m(
        'training.week_goal_metric_coverage', '目标绑定指标覆盖率', 'week', 'percent',
        '本周目标中绑定了可计算指标的比例', ('schedules', 'metrics_registry'), category='training', available=True),
    'training.week_review_completion': _m(
        'training.week_review_completion', '复盘完成率', 'week', 'percent',
        '本周训练课中已完成赛后复盘的比例', ('schedules',), category='training', available=True),
    'training.week_attendance_rate': _m(
        'training.week_attendance_rate', '出勤率', 'week', 'percent',
        '本周出勤人数 / 本队有效选手数', ('schedules', 'players'), category='training', available=False),
    'training.week_match_link_coverage': _m(
        'training.week_match_link_coverage', '对局关联覆盖率', 'week', 'percent',
        '本周已关联到有效对手的对局比例', ('match_records', 'teams'), category='training', available=True),
    'training.week_intervention_count': _m(
        'training.week_intervention_count', '训练干预数', 'week', 'count',
        '本周登记的训练干预数量', ('training',), category='training', available=True),
    'training.week_effect_mean': _m(
        'training.week_effect_mean', '平均效应量', 'week', 'ratio',
        '本周可评估训练干预的平均效应量', ('training', 'effect'), category='training', available=False),

    # 对局上下文：保留，但不作为赛训主指标/默认目标指标
    'session.match_count': _m(
        'session.match_count', '对局数', 'session', 'count',
        '本场训练课关联的对局数量', ('match_records',), category='performance', available=True),
    'session.win_count': _m(
        'session.win_count', '胜场', 'session', 'count',
        '本场训练课有胜负结果的对局中，本队获胜的场数', ('match_records',), available=True),
    'session.loss_count': _m(
        'session.loss_count', '负场', 'session', 'count',
        '本场训练课有胜负结果的对局中，本队失利的场数', ('match_records',), available=True),
    'session.win_rate': _m(
        'session.win_rate', '胜率', 'session', 'percent',
        '胜场 / (胜场 + 负场)，缺失胜负的结果不计入分母', ('match_records',), available=True),
    'session.avg_duration': _m(
        'session.avg_duration', '平均时长', 'session', 'seconds',
        '本场有有效时长的对局平均时长', ('match_records',), direction=-1, available=True),
    'session.goal_completion': _m(
        'session.goal_completion', '目标达成率', 'session', 'percent',
        '本场训练目标中状态为达成的比例', ('match_records', 'schedules'), available=True),

    # 周报
    'week.match_count': _m(
        'week.match_count', '对局数', 'week', 'count',
        '本周对局数量', ('match_records',), available=True),
    'week.win_count': _m(
        'week.win_count', '胜场', 'week', 'count',
        '本周有胜负结果的对局中，本队获胜的场数', ('match_records',), available=True),
    'week.loss_count': _m(
        'week.loss_count', '负场', 'week', 'count',
        '本周有胜负结果的对局中，本队失利的场数', ('match_records',), available=True),
    'week.win_rate': _m(
        'week.win_rate', '胜率', 'week', 'percent',
        '本周胜场 / (胜场 + 负场)', ('match_records',), available=True),
    'week.avg_duration': _m(
        'week.avg_duration', '平均时长', 'week', 'seconds',
        '本周有有效时长的对局平均时长', ('match_records',), direction=-1, available=True),
    'week.goal_completion': _m(
        'week.goal_completion', '目标达成率', 'week', 'percent',
        '本周训练目标中状态为达成的比例', ('match_records', 'schedules'), available=True),

    # 已登记、等待数据源接入：让目标和报告能明确显示「缺什么」，不估造。
    'session.gold_diff_10': _m(
        'session.gold_diff_10', '10 分钟经济差', 'session', 'gold',
        '本队与对手在 10 分钟节点的经济差', ('camp_details', 'timeline'), available=False),
    'session.first_blood_rate': _m(
        'session.first_blood_rate', '一血率', 'session', 'percent',
        '本队拿到第一滴血的对局占比', ('camp_details', 'events'), available=False),
    'session.objective_rate': _m(
        'session.objective_rate', '控龙率', 'session', 'percent',
        '本队击杀暴君/主宰等关键中立资源的占比', ('camp_details', 'events'), available=False),
    'team.gpm': _m(
        'team.gpm', '分均经济', 'team', 'gold',
        '团队总经济 / 有效分钟', ('camp_details', 'player_stats'), available=False),
    'team.dpm': _m(
        'team.dpm', '分均输出', 'team', 'damage',
        '团队英雄伤害 / 有效分钟', ('camp_details', 'player_stats'), available=False),
    'team.tpm': _m(
        'team.tpm', '分均承伤', 'team', 'damage',
        '团队承受伤害 / 有效分钟', ('camp_details', 'player_stats'), available=False),
    'player.kda': _m(
        'player.kda', 'KDA', 'player', 'ratio',
        '(击杀 + 助攻) / max(1, 死亡)', ('camp_details', 'player_stats'), available=False),
    'player.participation': _m(
        'player.participation', '参团率', 'player', 'percent',
        '选手参与击杀 / 团队总击杀', ('camp_details', 'player_stats'), available=False),
    'player.damage_conversion': _m(
        'player.damage_conversion', '伤害转化率', 'player', 'ratio',
        '英雄伤害 / 总经济', ('camp_details', 'player_stats'), available=False),
}


def get_metric(metric_id: str) -> MetricDefinition | None:
    return METRICS.get(str(metric_id or '').strip())


def list_metrics(entity: str | None = None) -> list[dict]:
    items = [asdict(item) for item in METRICS.values()]
    if entity:
        items = [item for item in items if item['entity'] == entity]
    return items


def goal_metrics() -> list[dict]:
    """训练目标可选指标：训练课维度，包含暂不可用项（前端会标灰）。"""
    return list_metrics('session')


def as_dict(metric: MetricDefinition) -> dict:
    return asdict(metric)
