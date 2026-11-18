"""战队风格四象限：终局面板代理指标的唯一实现（docs/team_page_v2.md §2.3）。

为什么单独一层
--------------
「战队风格」和「战队详情」两个页面看的是同一批营地终局面板，必须用同一套算法，
否则同一支队在两个页面的点位会打架。所以 x/y、四象限、时间窗、证据文案都在
这里算一次，`team_clusters.list_teams` 与 `team_clusters.team_deep` 共用。

口径（逐局，双向都算）
----------------------
* 经济集中度：`top1Share = max(队友经济) / sum(队友经济) * 100`；同池 q33/q66 定中线，
  `x = clamp(100 * (q66 - top1Share) / (q66 - q33), 0, 100)`，x 越大越偏多核。
* 节奏倾向：`fightPerMin = (击杀 + 助攻) / 分钟`、
  `macroPerMin = (推塔 + 0.7 * 控龙) / 分钟`；
  同池分别取百分位排名 pf / pm，`y = clamp(50 + (pf - pm) / 2, 0, 100)`，
  y 越大越偏打架。两项都高/都低时落在 50 附近，不会被单项拉满。
* 象限：x < 50 且 y >= 50 → 单核进攻；x >= 50 且 y >= 50 → 多点进攻；
  x < 50 且 y < 50 → 保核运营；x >= 50 且 y < 50 → 多线牵制。
* 窗口：7 / 15 / 30 天 + 全部；锚点 = 该队最近一局日期（不是今天）。

纪律
----
这是**终局面板代理**，不是时间轴：能说的只有「经济怎么分、终局打了多少、推了多少」，
主动开团 / 中野辅联动 / 兵线处理 / 领先后怎么打一律写「证据不足」。
字段缺失返回 None，不用 0 冒充。
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta

QUADRANTS = ('单核进攻', '多点进攻', '保核运营', '多线牵制')
WINDOW_KEYS = ('7', '15', '30')
SAMPLE_MIN = 3
QUADRANT_SHARE = 0.5

# 三条固定缺口：终局面板没有时间轴/位置轨迹、手序只有模板/部分显式、指标只能同路对比。
MISSING = (
    '没有时间轴与位置轨迹：主动开团、中野辅联动、兵线处理、领先后怎么打暂不能判断',
    '营地名单按格式自动还原（征召 18 / KPL 20 / 排位·巅峰 20）；显式逐手核验只覆盖部分局',
    '经济/输出/承伤按分路统计，同路对比才有意义',
)

_START_RE = re.compile(
    r'^\s*(?:(\d{4})-)?(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?')


# ---------------------------------------------------------------- 小工具
def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _mean(values, digits=1):
    if not values:
        return None
    return round(sum(values) / len(values), digits)


def quantile(values, q: float):
    """线性插值分位数；空列表返回 None。"""
    points = sorted(value for value in values or [] if value is not None)
    if not points:
        return None
    if len(points) == 1:
        return points[0]
    position = (len(points) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return points[int(position)]
    return points[low] + (points[high] - points[low]) * (position - low)


def percentile_rank(values, value):
    """同池百分位排名（0–100）：池里不大于该值的比例。缺值返回 None。"""
    points = [item for item in values or [] if item is not None]
    if value is None or not points:
        return None
    return sum(1 for item in points if item <= value) / len(points) * 100


def parse_start(text):
    """解析营地开局时间：兼容 `MM-DD HH:MM` 与 `YYYY-MM-DD ...`。"""
    match = _START_RE.match(str(text or ''))
    if not match:
        return None
    year, month, day, hour, minute = match.groups()
    try:
        return {'year': int(year) if year else None, 'month': int(month),
                'day': int(day), 'hour': int(hour or 0), 'minute': int(minute or 0)}
    except (TypeError, ValueError):
        return None


def _reference(reference_year=None):
    """无年份日期的参考年份：优先用数据内最近的完整日期，否则退回当前年份。"""
    return reference_year if reference_year is not None else date.today().year


def resolve_days(starts) -> dict:
    """批量把开局时间解析成日期。

    营地详情通常只有 `MM-DD HH:MM`；数据里出现完整日期时按它补年份，
    跨年时取不晚于参考日期的最近一年。完全没有年份信息时不猜跨年。
    """
    parsed = [(text, parse_start(text)) for text in starts]
    full = [(text, item) for text, item in parsed if item and item['year']]
    reference_year, reference_day = None, None
    if full:
        _, latest = max(full, key=lambda pair: (pair[1]['year'], pair[1]['month'],
                                                pair[1]['day'], pair[1]['hour'],
                                                pair[1]['minute']))
        reference_year = latest['year']
        reference_day = (latest['month'], latest['day'])
    reference_year = _reference(reference_year)
    out = {}
    for text, item in parsed:
        if not item:
            out[text] = None
            continue
        year = item['year'] or reference_year
        if item['year'] is None and reference_day and \
                (item['month'], item['day']) > reference_day:
            year -= 1
        try:
            out[text] = date(year, item['month'], item['day'])
        except ValueError:
            out[text] = None
    return out


def day_label(value) -> str | None:
    """日期显示成 `MM-DD`；接受 str（营地时间）或 date。"""
    if isinstance(value, date):
        return f'{value.month:02d}-{value.day:02d}'
    item = parse_start(value)
    return f'{item["month"]:02d}-{item["day"]:02d}' if item else None


def quadrant_of(x, y):
    """按 §2.3 的四象限分界；任一坐标缺失返回 None。"""
    if x is None or y is None:
        return None
    if x < 50:
        return '单核进攻' if y >= 50 else '保核运营'
    return '多点进攻' if y >= 50 else '多线牵制'


# ---------------------------------------------------------------- 逐局记录
def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _top1(roster):
    """经济第一：max(选手经济) / sum(选手经济)；有选手缺少经济时只用有值的样本。"""
    known = [player for player in roster or [] if player.get('gold') is not None]
    total = sum(player['gold'] for player in known)
    if not known or not total:
        return None, None
    best = max(known, key=lambda player: player['gold'])
    return ({'name': best.get('name') or '', 'hero': best.get('hero') or '',
             'lane': best.get('lane') or ''},
            round(best['gold'] / total * 100, 1))


def _record(seq, side, day, duration, roster, stats, gold_diff):
    stats = stats or {}
    minutes = round(duration / 60, 3) if duration and duration > 0 else None
    kills = _num(stats.get('kills'))
    assists = _num(stats.get('assists'))
    towers = _num(stats.get('towers'))
    dragons = _num(stats.get('dragons'))
    fight = None
    if minutes and kills is not None and assists is not None:
        fight = round((kills + assists) / minutes, 3)
    macro = None
    if minutes and towers is not None and dragons is not None:
        macro = round((towers + 0.7 * dragons) / minutes, 3)
    top1, share = _top1(roster)
    return {
        'seq': str(seq or ''), 'side': side, 'day': day,
        'duration': int(duration) if duration else None, 'minutes': minutes,
        'top1': top1, 'top1Share': share,
        'fightPerMin': fight, 'macroPerMin': macro,
        'kills': kills, 'assists': assists, 'towers': towers, 'dragons': dragons,
        'gold': _num(stats.get('gold')), 'win': stats.get('win'), 'goldDiff': gold_diff,
    }


def build_index(panels) -> dict:
    """把面板展开成「队-局」记录：我方一份、对手一份，双向进同池。

    返回 {'own': [...], 'enemy': {seq: record}, 'both': [...], 'pool': {...},
          'thresholds': {...}}。`own` 是唯一那支本队，`enemy` 按 seq 索引对手记录；
    调用方用 seqs 从 `enemy` 里取某支对手战队的逐局记录（合并战队同样适用）。
    """
    starts = [panel.get('start') or '' for panel in panels or []]
    days = resolve_days(starts)
    own_records, enemy_records, both = [], {}, []
    for panel in panels or []:
        seq = panel.get('seq')
        start = panel.get('start') or ''
        day = days.get(start)
        duration = panel.get('duration')
        try:
            duration = float(duration) if duration not in (None, '') else None
        except (TypeError, ValueError):
            duration = None
        own_stats = panel.get('own_stats') or {}
        enemy_stats = panel.get('enemy_stats') or {}
        own_gold = _num(own_stats.get('gold'))
        enemy_gold = _num(enemy_stats.get('gold'))
        own_diff = round(own_gold - enemy_gold, 1) if own_gold is not None and enemy_gold is not None else None
        enemy_diff = round(enemy_gold - own_gold, 1) if own_gold is not None and enemy_gold is not None else None
        own_record = _record(seq, 'own', day, duration, panel.get('own_roster'),
                             own_stats, own_diff)
        enemy_record = _record(seq, 'enemy', day, duration, panel.get('enemy_roster'),
                               enemy_stats, enemy_diff)
        own_records.append(own_record)
        if seq is not None:
            enemy_records[str(seq)] = enemy_record
        both.extend([own_record, enemy_record])
    thresholds = _thresholds(both)
    return {'own': own_records, 'enemy': enemy_records, 'both': both,
            'pool': _public_pool(both, thresholds), 'thresholds': thresholds}


def _thresholds(records) -> dict:
    top1_values = [record['top1Share'] for record in records
                   if record.get('top1Share') is not None]
    fight_values = [record['fightPerMin'] for record in records
                    if record.get('fightPerMin') is not None]
    macro_values = [record['macroPerMin'] for record in records
                    if record.get('macroPerMin') is not None]
    return {'top1': [quantile(top1_values, 0.33), quantile(top1_values, 0.66)],
            'fight': fight_values, 'macro': macro_values}


def _public_pool(records, thresholds) -> dict:
    top1 = [round(value, 1) if value is not None else None
            for value in thresholds.get('top1') or (None, None)]
    return {'n': len(records), 'top1': top1,
            'note': '同池 33/66 分位用来定经济集中度中线；'
                    '打架/运营按同池百分位比较，两项都高或都低时落在中间。'}


# ---------------------------------------------------------------- 逐局风格
def game_style(record, thresholds) -> dict:
    """单局点位与证据卡；缺值一律 null，不用 0 冒充。"""
    out = {'x': None, 'y': None, 'quadrant': None, 'top1': None,
           'fightPerMin': None, 'macroPerMin': None,
           'evidence': [], 'missing': list(MISSING)}
    if not record:
        return out
    out['fightPerMin'] = record.get('fightPerMin')
    out['macroPerMin'] = record.get('macroPerMin')
    share = record.get('top1Share')
    top1 = record.get('top1')
    if top1 and share is not None:
        out['top1'] = {**top1, 'share': share}
    thresholds = thresholds or {}
    low, high = (thresholds.get('top1') or (None, None))
    if share is not None and low is not None and high is not None:
        if high > low:
            out['x'] = round(_clamp(100 * (high - share) / (high - low)), 1)
        else:
            # 全池经济集中度没有差异（样本同质）时不硬拉边：落在中线，标注证据不足
            out['x'] = 50.0
    rank = percentile_rank(thresholds.get('fight'), record.get('fightPerMin'))
    macro_rank = percentile_rank(thresholds.get('macro'), record.get('macroPerMin'))
    if rank is not None and macro_rank is not None:
        # 池里没有差异时两个百分位相同，y 自然落在 50，不会被单项拉满
        out['y'] = round(_clamp(50 + (rank - macro_rank) / 2), 1)
    out['quadrant'] = quadrant_of(out['x'], out['y'])
    out['evidence'] = evidence_of(record)
    return out


def evidence_of(record) -> list:
    """能落到页面文案的证据：只写终局面板真的有的数。"""
    if not record:
        return []
    items = []
    top1, share = record.get('top1'), record.get('top1Share')
    if top1 and share is not None:
        items.append(f'经济第一是{top1.get("lane") or "未知分路"} {share}%')
    fight = record.get('fightPerMin')
    if fight is not None:
        items.append(f'每分钟击杀+助攻 {round(fight, 1)}')
    macro = record.get('macroPerMin')
    if macro is not None:
        items.append(f'每分钟推塔+控龙 {round(macro, 2)}')
    towers, dragons = record.get('towers'), record.get('dragons')
    if towers is not None and dragons is not None:
        items.append(f'推塔 {int(towers)} 座 / 控龙 {int(dragons)} 条')
    diff = record.get('goldDiff')
    if diff is not None:
        items.append(f'最终经济差 {"+" if diff > 0 else ""}{int(round(diff))}')
    return items


# ---------------------------------------------------------------- 时间窗与汇总
def _window(records, thresholds, anchor_day, days) -> dict:
    if days is None:
        picked = list(records)
    elif anchor_day is None:
        picked = []
    else:
        # 「最近 7 天」= 含锚点在内的 7 个自然日（anchor-6 … anchor）
        lower = anchor_day - timedelta(days=int(days) - 1)
        picked = [record for record in records
                  if record.get('day') and lower <= record['day'] <= anchor_day]
    counts = {name: 0 for name in QUADRANTS}
    xs, ys, top1s, fights, macros = [], [], [], [], []
    for record in picked:
        style = game_style(record, thresholds)
        if style['x'] is not None:
            xs.append(style['x'])
        if style['y'] is not None:
            ys.append(style['y'])
        if style['quadrant']:
            counts[style['quadrant']] += 1
        if record.get('top1Share') is not None:
            top1s.append(record['top1Share'])
        if record.get('fightPerMin') is not None:
            fights.append(record['fightPerMin'])
        if record.get('macroPerMin') is not None:
            macros.append(record['macroPerMin'])
    games = len(picked)
    known = sum(counts.values())
    top = max(counts.values()) if counts else 0
    share = round(top / games * 100, 1) if games and known else None
    quadrant = None
    if games >= SAMPLE_MIN and known and top / games >= QUADRANT_SHARE:
        quadrant = max(counts, key=counts.get)
    return {
        'games': games, 'quadrant': quadrant, 'share': share,
        'x': _mean(xs, 1), 'y': _mean(ys, 1), 'counts': counts,
        'avg': {'top1Share': _mean(top1s, 1), 'fightPerMin': _mean(fights, 2),
                'macroPerMin': _mean(macros, 2)},
        'sufficient': games >= SAMPLE_MIN,
    }


def _main(windows) -> dict:
    """主要倾向：优先 30 天窗口；不足 3 局退回全部；都没有则象限为 null。"""
    window = windows.get('30') or {}
    if not window.get('games') or window['games'] < SAMPLE_MIN:
        window = windows.get('all') or {}
    if not window.get('games'):
        return {'quadrant': None, 'share': None, 'x': None, 'y': None, 'sufficient': False}
    return {'quadrant': window.get('quadrant'), 'share': window.get('share'),
            'x': window.get('x'), 'y': window.get('y'),
            'sufficient': bool(window.get('sufficient'))}


def style(records, index) -> dict:
    """某支战队的风格结构（§2.1）；records 为它的「队-局」记录。"""
    records = [record for record in records or [] if record]
    thresholds = (index or {}).get('thresholds') or {}
    days = [record['day'] for record in records if record.get('day')]
    anchor_day = max(days) if days else None
    windows = {}
    for key in WINDOW_KEYS:
        windows[key] = _window(records, thresholds, anchor_day, int(key))
    windows['all'] = _window(records, thresholds, anchor_day, None)
    return {
        'games': len(records),
        'anchor': day_label(anchor_day),
        'windows': windows,
        'pool': (index or {}).get('pool') or {'n': 0, 'top1': [None, None], 'note': ''},
        'main': _main(windows),
    }
