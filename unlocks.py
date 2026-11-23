"""数据解锁（v2）：分析页按赛事语料阈值自动解锁（方案文档「解锁 v2」）。

单一阈值源：阈值引用 tiers（按等级）；计数走 scope 层与 training_series，
与初始化清单卡同一口径。前端只做呈现（锁卡 / 进度 / CTA），不隐藏菜单。
口径纪律：BP 名单 / 楼层缺失是页内「待补任务」，不做锁。
"""
import json


def _settings_league(db_path):
    try:
        import sqlite3
        with sqlite3.connect(str(db_path)) as connection:
            row = connection.execute('SELECT body FROM settings WHERE id=1').fetchone()
            return (json.loads(row[0]) if row else {}).get('league') or None
    except Exception:  # noqa: BLE001 - 旧库/IO 异常退回默认等级
        return None


def compute(workspace, db_path, competition_id=None):
    """返回 {routes: {...}}；未选赛事时全部锁定并引导先选赛事。"""
    import tiers
    league = _settings_league(db_path) or tiers.DEFAULT_LEAGUE
    corpus_need = tiers.threshold_for(league) or 20
    series = workspace.list_series(competition=competition_id or None, limit=500)
    confirmed = [item for item in series if item.get('status') == 'confirmed']
    confirmed_series = len(confirmed)
    confirmed_games = sum(len(item.get('games') or []) for item in confirmed)
    any_series = bool(series) or bool(workspace.unfiled_series(limit=1))

    def route(label, unlocked, n, need, unit, hint, cta):
        return {'label': label, 'unlocked': bool(unlocked), 'n': n, 'need': need,
                'unit': unit, 'hint': hint, 'cta': cta}

    routes = {
        'biggame': route(
            '大场分析', confirmed_series >= 1, confirmed_series, 1, '个已确认系列',
            '把对局编成 BO3/5/7 并确认',
            ([['#series-builder', '去编组']] if any_series else
             [['#capture', '去采集'], ['#series-builder', '去编组']])),
        'cross': route(
            '跨局分析', confirmed_games >= corpus_need, confirmed_games, corpus_need,
            '局语料', '继续采集并确认系列赛',
            [['#capture', '去采集'], ['#series-builder', '去编组']]),
    }
    if not competition_id:
        for item in routes.values():
            item['hint'] = '先在赛事页选择或创建赛事'
            item['cta'] = [['#competitions', '去选赛事']]
    return {'competition': competition_id, 'league': league, 'routes': routes}
