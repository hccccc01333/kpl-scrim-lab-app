"""V3 adapters for the existing replay-analysis modules."""
from threading import Lock
import importlib.util
from pathlib import Path

import analysis_economy
# V1's analysis module has process-wide calibration state. Load a private
# module instance so a concurrent legacy endpoint cannot change the app's units.
_spec = importlib.util.spec_from_file_location('_analysis_space', Path(__file__).resolve().parent.parent / 'analysis_space.py')
analysis_space = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analysis_space)
import map_calibration

_space_lock = Lock()


def space(replays_dir, camp_dir, data_dir):
    """Analyze raw coordinate distances, then express them in map-width units."""
    calibration = map_calibration.load(data_dir) or map_calibration.compute(replays_dir)
    with _space_lock:
        # The source stores raw coordinates. Keeping raw coordinates during the
        # analysis avoids mixing normalized coordinates with raw thresholds.
        result = analysis_space.all_analyses(replays_dir, camp_dir, None)
        # The legacy helper includes structures alongside neutral objectives.
        # Only dtType=1 is a monster/resource event; dtType=2 is a structure.
        games = analysis_space.load_games(replays_dir, camp_dir, None)
        resource_games = [dict(game, events=[event for event in game['events']
                           if event.get('eventType') == 'dragontower' and str(event.get('dtType')) == '1'])
                          for game in games]
        result['resources'] = analysis_space.resource_contest(resource_games)
    width = calibration.get('width') if calibration.get('calibrated') else None
    if width and width > 0:
        for field, keys in (
            ('routes', ('pathLength', 'displacement')),
            ('trio', ('avgSpread',)),
            ('deaths', ('nearest',)),
        ):
            for row in result[field]['rows']:
                for key in keys:
                    if isinstance(row.get(key), (int, float)):
                        row[key] = round(row[key] / width, 3)
        result['routes']['note'] = '原始坐标计算后按本批地图宽度换算；路线相似度是路径长度与位移的近似比较。'
        result['trio']['note'] = f'三人两两距离不超过 {analysis_space.R_TRIO / width:.3f} 个地图宽度记为集结。'
        result['deaths']['note'] = f'最近队友超过 {analysis_space.R_NEAR / width:.3f} 个地图宽度记为孤立；坐标只描述距离。'
        result['resources']['note'] = (f'资源点以击杀者位置近似；前 30 秒内双方均进入 '
                                       f'{analysis_space.R_NEAR * 1.5 / width:.3f} 个地图宽度记为争夺。')
    result['calibrated'] = bool(width and width > 0)
    result['calibration'] = calibration
    result['distanceUnit'] = '地图宽度' if result['calibrated'] else '回放相对单位'
    return result


def advantage_from_games(games, landmark=600):
    """Exclude matches that cannot contain the requested observation."""
    buckets = {name: {'n': 0, 'wins': 0} for name, _, _ in analysis_economy.BUCKETS}
    rows = []
    for game in games:
        if game.get('win') is None or game.get('duration', 0) < landmark or len(game.get('diff') or []) < 2:
            continue
        lead = analysis_economy._value_at(landmark, game['diff'], game['duration'])
        own_lead = lead if game['ownCamp'] == 'blue' else -lead
        bucket = next(name for name, low, high in analysis_economy.BUCKETS if low <= own_lead < high)
        buckets[bucket]['n'] += 1
        buckets[bucket]['wins'] += int(game['win'])
        rows.append({'game': game['seq'], 'ownCamp': game['ownCamp'],
                     'leadAt10': round(own_lead), 'bucket': bucket, 'won': game['win']})
    summary = []
    for name, _, _ in analysis_economy.BUCKETS:
        item = buckets[name]
        lower, upper = analysis_economy._wilson(item['wins'], item['n'])
        summary.append({'bucket': name, **item,
                        'winRate': round(item['wins'] / item['n'] * 100, 1) if item['n'] else None,
                        'ciLow': round(lower, 1) if lower is not None else None,
                        'ciHigh': round(upper, 1) if upper is not None else None,
                        'enough': item['n'] >= 10})
    total = sum(item['n'] for item in summary)
    wins = sum(item['wins'] for item in summary)
    return {'games': len(games), 'landmark': landmark, 'rows': rows, 'buckets': summary,
            'overall': {'n': total, 'wins': wins, 'winRate': round(wins / total * 100, 1) if total else None},
            'note': '只包含时长达到 10 分钟且有胜负的对局。经济时刻按采样索引近似，分桶样本不足 10 局时仅供观察。'}


def economy(replays_dir, camp_dir):
    games = analysis_economy.load_games(replays_dir, camp_dir)
    return {'turning': analysis_economy.turning_points(replays_dir, camp_dir, limit=200),
            'advantage': advantage_from_games(games)}


def training_effects(camp_dir, workspace):
    """Use dates only when the source actually includes a four-digit year."""
    import json
    import re
    from pathlib import Path
    import analysis_profile
    rows = [row for row in analysis_profile.load_rows(camp_dir) if row.get('side') == 'own']
    dates = {}
    for path in Path(camp_dir).glob('*.json'):
        try:
            data = json.loads(path.read_text(encoding='utf-8')).get('data') or {}
            raw = str((data.get('battle') or {}).get('startTime') or '')
            match = re.match(r'^(\d{4}-\d{2}-\d{2})(?:\s|$)', raw)
            dates[path.stem] = match.group(1) if match else ''
        except (OSError, ValueError, AttributeError):
            continue
    for row in rows:
        row['date'] = dates.get(row['seq'], '')
    return {'results': [dict(item, effect=analysis_profile.training_effect(rows, item))
                        for item in workspace.list_training()],
            'dateNote': '来源没有完整年份时不参与训练前后比较。'}
