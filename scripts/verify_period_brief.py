"""赛训周期简报首页回归（#overview）。

跑法（仓库根目录）：
    $env:PYTHONIOENCODING='utf-8'; python scripts/verify_period_brief.py
    python scripts/verify_period_brief.py --real     # 再跑一遍真实 /api/briefing 数据

自起 server.py（随机空闲端口，跑完关掉）；只验前端，不写任何数据。

检查项（契约 docs/period_brief.md §2 + §3 + §4）：
  - 首页出现「赛训周期简报 / 赛训总览」，默认「本周」高亮，带实际范围与上期范围；
  - 周期切换有 loading 态，标题、战况句与数字随之变化，不残留上一期结论；
  - 证据对局可点，hash 变成 #match/<key>；
  - 今日 0 局 → 空态 +「查看最近一批」；点它切到 custom 区间且不写全局筛选；
  - 空库 → 沿用「还没有对局数据」弹窗，首页不整页换向导；
  - 取数失败 → 模块内错误 + 重试可恢复；
  - 「本期重点发现」全宽行式布局：每条 finding 一行、右栏恰好一个 .pbr-stat 数字块、
    标题单行不换行（Range.getClientRects 只占 1 行），1440/1180/1024/390 不溢出；
  - 「本期最值得复盘的比赛」区头工具栏（不是一排排胶囊/实心块）：
    排序按钮 data-pbr-sort-toggle + 排序弹层 data-pbr-sort-pop（10 个字段选项，点选后分组、
    区头计数、按钮文本同步，弹层关闭、焦点回按钮；Esc 与点外部关闭）；
    字段按钮 data-pbr-fields-toggle + 字段弹层 data-pbr-fields-pop（10 项、默认勾选 4、
    满 4 未选项 disabled、最少 1 项、即时改卡片数字、localStorage['pbr-watch-display-fields']
    持久化、reload 保持、恢复默认）；
  - 卡片数字 data-pbr-value 按字段目录顺序渲染（缺失「—」），排序字段在显示集合里才加 .is-focus；
  - 旧报文（无 watchFields）仍按 numbers 渲染，不出现工具按钮；
  - 1440 / 1180 / 1024 工具栏不换行；390 工具栏落到标题下方、两个弹层不溢出、无横向滚动；
  - 深色主题下工具栏与两个弹层文字可读（对比度断言）；
  - 正常路径 0 控制台报错（失败态那一步单独统计）。

默认用 Playwright 路由拦截注入契约形状的合成数据（mode=mock），保证布局与交互可重复验收；
--real 时额外用本机真实接口跑一遍结构冒烟（本期可能 0 局，只验外壳与空态）。
输出：test-results/period-brief/*.png + 终端摘要；失败时退出码 1。
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results' / 'period-brief'
OUT.mkdir(parents=True, exist_ok=True)

FALLBACK_KEY = 'channel-2f41bb5f40a84f2fb0b0b1d7cbc2f33e'
SOURCE_Q = 'source=db,bundle'
# 下钻深链用站内仍存在的分析页；只验「原样带 from/to」，不点开（目标页不在本任务范围）。
DEEP_ROUTE = '#cross'

failures = []
notes = []


def check(ok, message):
    if not ok:
        failures.append(message)
    return ok


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_for(url, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except urllib.error.HTTPError:
            return True
        except OSError:
            time.sleep(0.1)
    return False


def http_json(url):
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.load(response)


def real_match_key(base):
    """mock 里用真实对局 key：点证据对局能真的打开单局页，不会多出 404 噪音。"""
    try:
        rows = http_json(f'{base}/api/matches?{SOURCE_Q}')['matches']
        dated = [row['key'] for row in rows if row.get('date')]
        return dated[0] if dated else FALLBACK_KEY
    except Exception:
        return FALLBACK_KEY


# 复盘区 10 个字段目录（顺序固定，与后端 analysis_period.WATCH_FIELDS 一致）。
WATCH_META = (
    ('deficit', '最多落后', '全场最多落后多少金币', '金币'),
    ('deaths', '我方掉点', '我方掉点次数', '次'),
    ('giveback', '领先被反超', '领先 1000 金币以上、后来被反超', '金币'),
    ('fight', '团战打输', '打输的团战波数', '波'),
    ('at10', '10 分钟经济差', '10 分钟时我方领先 / 落后的金币', '金币'),
    ('duration', '时长', '这局打了多久', '时间'),
    ('dragon', '关键龙丢失', '关键龙丢了几条', '条'),
    ('tower', '被推塔', '被对手推掉的塔数', '座'),
    ('gold', '终局经济差', '终局时的经济差', '金币'),
    ('damage', '团队输出占比', '我方团队输出占全场的比例', '%'),
)
WATCH_LABEL = {item[0]: item[1] for item in WATCH_META}
WATCH_DISPLAY_DEFAULT = ['deficit', 'at10', 'deaths', 'duration']
WATCH_COUNTS = {'deficit': 17, 'deaths': 23, 'giveback': 9, 'fight': 15,
                'at10': 21, 'duration': 23, 'dragon': 18, 'tower': 20,
                'gold': 23, 'damage': 16}
WATCH_ROSTER = (
    ('项羽', '对抗路', '/catalog/icons/hero-105.png'),
    ('姜子牙', '中路', '/catalog/icons/hero-106.png'),
    ('黄忠', '发育路', '/catalog/icons/hero-107.png'),
    ('李白', '打野', '/catalog/icons/hero-108.png'),
    ('朵莉亚', '游走', '/catalog/icons/hero-109.png'),
)
# 8 局合成对局：故意让部分卡缺字段（at10 / giveback / dragon …），用来验「—」与缺失场景。
# game 'a' 同时出现在所有分组，用来验「同一局跨分组共享关注」。
MOCK_GAMES = {
    'a': {'date': '11-04', 'label': '11-04 · 对阵 #29', 'result': 'loss',
          'conclusion': '本期最长的一局，打了 27 分钟，10 分钟落后 2,500 金币，先看开局。',
          'values': {'deficit': '-4,500 金币', 'deaths': '32 次', 'giveback': '-3,100 金币',
                     'fight': '4 波', 'at10': '-2,500 金币', 'duration': '27:08',
                     'dragon': '3 条', 'tower': '6 座', 'gold': '-12,400 金币', 'damage': '38.2%'}},
    'b': {'date': '11-03', 'label': '11-03 · 对阵 #20', 'result': 'loss',
          'conclusion': '中期一波龙团被打出 0 换 4，经济差一路被拉开。',
          'values': {'deficit': '-3,900 金币', 'deaths': '28 次', 'giveback': '-2,600 金币',
                     'fight': '3 波', 'duration': '22:41', 'dragon': '2 条', 'tower': '5 座',
                     'gold': '-8,700 金币', 'damage': '41.5%'}},   # at10 缺失
    'c': {'date': '11-02', 'label': '11-02 · 对阵 #18', 'result': 'win',
          'conclusion': '开局领先一路兑现，19 分钟推平，可当作优势局的参照。',
          'values': {'deaths': '18 次', 'at10': '+1,600 金币', 'duration': '19:02',
                     'dragon': '4 条', 'gold': '+6,200 金币', 'damage': '52.0%'}},   # deficit/fight/tower/giveback 缺失
    'd': {'date': '11-02', 'label': '11-02 · 对阵 #17', 'result': 'loss',
          'conclusion': '10 分钟还咬着，最后 18 分钟被推掉两座高地。',
          'values': {'deficit': '-2,100 金币', 'deaths': '22 次', 'giveback': '-1,200 金币',
                     'fight': '2 波', 'at10': '-800 金币', 'duration': '18:30',
                     'tower': '3 座', 'gold': '-5,300 金币', 'damage': '44.1%'}},   # dragon 缺失
    'e': {'date': '11-03', 'label': '11-03 · 对阵 #22', 'result': 'loss',
          'conclusion': '前中期两波团战打输，经济差被滚到 9,000 金币。',
          'values': {'deficit': '-1,800 金币', 'deaths': '35 次', 'giveback': '-2,400 金币',
                     'fight': '5 波', 'at10': '-1,100 金币', 'duration': '24:12',
                     'dragon': '5 条', 'tower': '7 座', 'gold': '-9,200 金币', 'damage': '36.0%'}},
    'f': {'date': '11-04', 'label': '11-04 · 对阵 #31', 'result': 'loss',
          'conclusion': '对线期就落后，20 分钟被推平，可作为开局问题的参照。',
          'values': {'deficit': '-3,300 金币', 'deaths': '25 次', 'giveback': '-1,600 金币',
                     'fight': '4 波', 'at10': '-1,500 金币', 'duration': '20:40',
                     'tower': '4 座', 'gold': '-6,800 金币', 'damage': '39.4%'}},   # dragon 缺失
    'g': {'date': '11-03', 'label': '11-03 · 对阵 #13', 'result': 'win',
          'conclusion': '打野前期带起节奏，23 分钟结束比赛。',
          'values': {'deaths': '30 次', 'giveback': '-900 金币', 'fight': '2 波',
                     'at10': '-900 金币', 'duration': '23:15', 'dragon': '3 条',
                     'tower': '6 座', 'gold': '-7,400 金币', 'damage': '40.0%'}},   # deficit 缺失
    'h': {'date': '11-02', 'label': '11-02 · 对阵 #8', 'result': 'loss',
          'conclusion': '掉点太多，后期无力回天。',
          'values': {'deaths': '21 次', 'giveback': '-2,000 金币', 'fight': '1 波',
                     'duration': '21:05', 'dragon': '1 条', 'tower': '5 座',
                     'gold': '-3,900 金币', 'damage': '47.5%'}},   # deficit/at10 缺失
}
# 复盘卡关键时间点（0-3 个、按时间升序；空数组 = 不渲染时间点）
MOCK_MOMENTS = {
    'a': [{'t': 600, 'clock': '10:00', 'label': '10 分钟 -2,500'},
          {'t': 1200, 'clock': '20:00', 'label': '领先被反超'},
          {'t': 1691, 'clock': '28:11', 'label': '最多落后 4,500'}],
    'b': [{'t': 780, 'clock': '13:00', 'label': '丢暴君'}],
    'c': [],
    'd': [{'t': 480, 'clock': '08:00', 'label': '打输团战'},
          {'t': 1100, 'clock': '18:20', 'label': '被推塔'}],
    'e': [],
    'f': [{'t': 900, 'clock': '15:00', 'label': '丢主宰'}],
    'g': [{'t': 300, 'clock': '05:00', 'label': '我方掉点'}],
    'h': [],
}


# 每个字段各排 5 局（后端每组最多 30 局，前端不再截 3 张）；game 'a' 跨多个分组。
WATCH_GROUPS = {
    'deficit': ['a', 'b', 'd', 'e', 'f'],
    'deaths': ['a', 'c', 'e', 'g', 'h'],
    'giveback': ['a', 'b', 'd', 'e', 'f'],
    'fight': ['a', 'b', 'e', 'f', 'g'],
    'at10': ['a', 'c', 'd', 'e', 'g'],
    'duration': ['a', 'b', 'c', 'd', 'e'],
    'dragon': ['a', 'b', 'c', 'e', 'g'],
    'tower': ['a', 'b', 'd', 'e', 'g'],
    'gold': ['a', 'b', 'c', 'd', 'e'],
    'damage': ['a', 'b', 'c', 'd', 'e'],
}


def watch_card(game_id, game, field):
    """一张复盘卡：values[]（该局所有有值字段）+ 旧 numbers[] 兼容 + 合成 game key（跨组共享用）。"""
    values = [{'id': field_id, 'label': label, 'value': game['values'][field_id]}
              for field_id, label, _note, _unit in WATCH_META if field_id in game['values']]
    numbers = []
    focus = game['values'].get(field)
    if focus:
        numbers.append({'label': WATCH_LABEL[field], 'value': focus, 'focus': True})
    for item in values:
        if item['id'] == field:
            continue
        numbers.append({'label': item['label'], 'value': item['value']})
        if len(numbers) >= 4:
            break
    game_key = f'channel-mock-{game_id}'
    return {
        'id': f'watch_{game_id}_{field}',
        'kind': game['result'],
        'field': field,
        'title': game['label'],
        'conclusion': game['conclusion'],
        'values': values,
        'numbers': numbers[:4],
        'moments': MOCK_MOMENTS.get(game_id, []),
        'rosterText': ' · '.join(name for name, _lane, _icon in WATCH_ROSTER),
        'rosterPlayers': [{'name': name, 'lane': lane, 'icon': icon}
                          for name, lane, icon in WATCH_ROSTER],
        'evidence': [{'game': game_key, 'label': '这局过程', 'note': ''}],
        'primary_destination': f'#match/{game_key}',
        'n': 1, 'enough': True, 'counterexamples': [],
        'deep_destination': '', 'limitation': '',
    }


def watch_payload(key):
    """10 个字段目录（每组 5 局）+ 默认组（deficit）+ 4 个默认显示字段。"""
    groups = []
    for field_id, label, note, unit in WATCH_META:
        items = [watch_card(game_id, MOCK_GAMES[game_id], field_id)
                 for game_id in WATCH_GROUPS[field_id]]
        groups.append({'id': field_id, 'label': label, 'note': note, 'unit': unit,
                       'count': WATCH_COUNTS[field_id], 'empty': f'本期没有{label}的局。',
                       'items': items})
    default_items = next(group['items'] for group in groups if group['id'] == 'deficit')
    return groups, default_items


def payload(period, frm='', to='', key=FALLBACK_KEY, cover='6', sentence=None, n=5, days=3):
    """契约 §2 形状的合成数据；每个周期数字不同，用来验「切周期数字会变」。"""
    label = {'today': '今日', 'week': '本周', 'month': '本月', 'custom': '自定义',
             'recent': f'最近 {n} 场', 'days': f'最近 {days} 天'}[period]
    prev_label = {'today': '昨天', 'week': '上周同期', 'month': '上月同期', 'custom': '上一周期',
                  'recent': f'前 {n} 场', 'days': f'前 {days} 天'}[period]
    ranges = {
        'week': ('2026-11-09', '2026-11-15', '11-09 ~ 11-15', '2026-11-02', '2026-11-08', '11-02 ~ 11-08'),
        'month': ('2026-11-01', '2026-11-30', '11-01 ~ 11-30', '2026-10-01', '2026-10-30', '10-01 ~ 10-30'),
        'today': ('2026-11-13', '2026-11-13', '11-13 ~ 11-13', '2026-11-12', '2026-11-12', '11-12 ~ 11-12'),
        'recent': ('2026-11-02', '2026-11-04', '11-02 ~ 11-04', '2026-10-29', '2026-11-01', '10-29 ~ 11-01'),
        'days': ('2026-11-12', '2026-11-14', '11-12 ~ 11-14', '2026-11-09', '2026-11-11', '11-09 ~ 11-11'),
        'custom': (frm or '2026-11-02', to or '2026-11-02',
                   f'{(frm or "2026-11-02")[5:]} ~ {(to or "2026-11-02")[5:]}',
                   '2026-11-01', '2026-11-01', '11-01 ~ 11-01'),
    }[period]
    from_, to_, range_label, prev_from, prev_to, prev_range = ranges
    numbers = {'week': ('4/6', '5/5'), 'month': ('12/21', '15/18'),
               'custom': ('5/7', '3/7'), 'today': ('—', '—'),
               'recent': ('4/5', '3/5'), 'days': ('3/3', '2/3')}[period]
    default_sentence = {
        'recent': f'最近 {n} 场 4 胜 1 负，胜率 80.0%，比前 {n} 场多赢 1 场。',
        'days': f'最近 {days} 天 3 局 3 胜 0 负，胜率 100.0%，比前 {days} 天多赢 1 局。',
    }.get(period, '本周 6 局 4 胜 2 负，胜率 66.7%，比上周同期少赢 1 局。')
    sentence = sentence or default_sentence
    watch_fields, watch_items = watch_payload(key)
    return {
        'available': True,
        'reason': None,
        'generatedAt': '2026-11-13T18:30:00',
        'period': {
            'kind': period, 'label': label, 'from': from_, 'to': to_, 'rangeLabel': range_label,
            'n': n if period == 'recent' else None,
            'days': days if period == 'days' else None,
            'prev': {'label': prev_label, 'from': prev_from, 'to': prev_to, 'rangeLabel': prev_range},
        },
        'fallback_hint': None,
        'coverage': {
            'games': 6, 'decided': 6, 'withReplay': 6, 'withTimeline': 6, 'panelGames': 6,
            'versions': ['1.0'], 'opponents': 4, 'dateLabel': range_label,
            'note': f'本期收录 {cover} 局，其中 6 局可看比赛过程',
        },
        'record': {
            'wins': 4, 'losses': 2, 'decided': 6, 'winRate': 66.7,
            'prev': {'wins': 5, 'losses': 1, 'decided': 6, 'winRate': 83.3},
            'form': [
                {'result': 'win', 'date': '2026-11-02', 'opponent': '#a'},
                {'result': 'loss', 'date': '2026-11-03', 'opponent': '#b'},
                {'result': 'win', 'date': '2026-11-03', 'opponent': '#c'},
                {'result': 'win', 'date': '2026-11-04', 'opponent': '#d'},
                {'result': 'loss', 'date': '2026-11-04', 'opponent': '#e'},
                {'result': 'win', 'date': '2026-11-04', 'opponent': '#f'},
            ],
        },
        'summary': {'sentence': sentence, 'tone': 'down',
                    'note': '训练赛战绩来自营地终局面板，比赛过程以官方回放为准。'},
        'metrics': [
            {'id': 'record', 'label': '本期战绩', 'valueText': '4 胜 2 负', 'valueSub': None,
             'prevValueText': '5 胜 1 负', 'deltaText': '-1 场', 'tone': 'down',
             'sample': 6, 'prevSample': 6, 'total': 6, 'coverage': '6/6 局', 'enough': True,
             'note': '含仅有终局面板的局', 'rank': None},
            {'id': 'win_rate', 'label': '本期胜率', 'valueText': '4/6', 'valueSub': '66.7%',
             'prevValueText': '5/6（83.3%）', 'deltaText': '-16.6 个百分点', 'tone': 'down',
             'sample': 6, 'prevSample': 6, 'total': 6, 'coverage': '6/6 局', 'enough': True,
             'note': '已判定胜负的局里赢下的比例',
             'rank': {'pos': 4, 'total': 7, 'percentile': 50, 'tier': 'mid',
                      'tierText': '中等', 'text': '中等 4/7'}},
            {'id': 'lead_rate', 'label': '十分钟领先率', 'valueText': '5/6', 'valueSub': '83.3%',
             'prevValueText': None, 'deltaText': '上期暂无可比数据', 'tone': 'none',
             'sample': 6, 'prevSample': 0, 'total': 6, 'coverage': '6/6 局', 'enough': True,
             'note': '10 分钟时经济领先的局占比',
             'rank': {'pos': 1, 'total': 7, 'percentile': 100, 'tier': 'lead',
                      'tierText': '领先', 'text': '领先 1/7'}},
            {'id': 'lead_hold_rate', 'label': '十分钟领先兑现率', 'valueText': '4/5', 'valueSub': '80.0%',
             'prevValueText': None, 'deltaText': '上期暂无可比数据', 'tone': 'none',
             'sample': 5, 'prevSample': 0, 'total': 5, 'coverage': '5/5 局', 'enough': True,
             'note': '10 分钟领先的局最终赢下几局', 'rank': None},
            {'id': 'lead_econ', 'label': '十分钟平均经济差', 'valueText': '+2,480 金币', 'valueSub': None,
             'prevValueText': None, 'deltaText': '上期暂无可比数据', 'tone': 'none',
             'sample': 6, 'prevSample': 0, 'total': 6, 'coverage': '6/6 局', 'enough': True,
             'note': '10 分钟时我方领先 / 落后的金币',
             'rank': {'pos': 7, 'total': 7, 'percentile': 0, 'tier': 'behind',
                      'tierText': '落后', 'text': '落后 7/7'}},
            {'id': 'fight_rate', 'label': '团战胜率', 'valueText': '62/90', 'valueSub': '68.9%',
             'prevValueText': '50/80（62.5%）', 'deltaText': '+6.4 个百分点', 'tone': 'up',
             'sample': 90, 'prevSample': 80, 'total': 90, 'coverage': '90/90 波', 'enough': True,
             'note': '按每波团战的击杀结果统计',
             'rank': {'pos': 2, 'total': 7, 'percentile': 83.3, 'tier': 'lead',
                      'tierText': '领先', 'text': '领先 2/7'}},
            {'id': 'dragon_rate', 'label': '关键龙控制率', 'valueText': '12/20', 'valueSub': '60.0%',
             'prevValueText': None, 'deltaText': '上期暂无可比数据', 'tone': 'none',
             'sample': 20, 'prevSample': 0, 'total': 20, 'coverage': '20/20 个', 'enough': True,
             'note': '暗影主宰 / 暴君 / 暗影暴君里我方拿到的比例',
             'rank': {'pos': 5, 'total': 7, 'percentile': 33.3, 'tier': 'mid',
                      'tierText': '中等', 'text': '中等 5/7'}},
            {'id': 'first_tower_rate', 'label': '一塔率', 'valueText': '5/6', 'valueSub': '83.3%',
             'prevValueText': None, 'deltaText': '上期暂无可比数据', 'tone': 'none',
             'sample': 6, 'prevSample': 0, 'total': 6, 'coverage': '6/6 局', 'enough': True,
             'note': '每局第一座防御塔由我方拿到的比例',
             'rank': {'pos': 3, 'total': 7, 'percentile': 66.7, 'tier': 'mid',
                      'tierText': '中等', 'text': '中等 3/7'}},
        ],
        'findings': [
            {
                'id': 'lead_hold_down', 'kind': 'advantage',
                # 故意给一条长标题：验发现区标题单行省略，不把行撑成两行。
                'title': '十分钟领先后，丢掉优势的局变多了，而且大多发生在中后期团战',
                'conclusion': '本周 6 局十分钟领先，赢下 4 局；上周同期 5 局全胜。',
                'numbers': [{'label': '本期', 'value': numbers[0]}, {'label': '上期', 'value': numbers[1]}],
                'n': 6, 'enough': False,
                'evidence': [
                    {'game': key, 'label': '11-04 · 对阵 #29', 'note': '10 分钟领先 1.2k，后期被翻',
                     't': 1691, 'approx': True},
                    {'game': key, 'label': '11-05 · 对阵 #31', 'note': '领先 2k 后被追平',
                     't': 1500, 'approx': False},
                ],
                'counterexamples': [],
                'primary_destination': f'#match/{key}',
                'deep_destination': f'{DEEP_ROUTE}?from={from_}&to={to_}&{SOURCE_Q}',
                'limitation': '样本 6 局，只作本批观察；对照局不足时不能当稳定规律。',
            },
            {
                'id': 'fight_arrival_down', 'kind': 'fight', 'title': '开局人少还硬接团的情况变多了',
                'conclusion': '本周 9 场人数落后团战只赢 2 场，上周 7 场赢 4 场。',
                'numbers': [{'label': '本期', 'value': '2/9'}, {'label': '上期', 'value': '4/7'}],
                'n': 9, 'enough': True,
                'evidence': [{'game': key, 'label': '11-05 · 对阵 #30', 'note': '人数落后仍接团，被打出 0 换 4'}],
                'primary_destination': f'#match/{key}',
                'deep_destination': f'{DEEP_ROUTE}?from={from_}&to={to_}',
                'limitation': '只统计有回放的团战。',
            },
            {
                'id': 'objective_down', 'kind': 'objective', 'title': '龙塔争夺的收益变差了',
                'conclusion': '本周每局拿到 2.1 个资源/塔，上周 2.8 个。',
                'numbers': [{'label': '本期', 'value': '2.1'}, {'label': '上期', 'value': '2.8'}],
                'n': 6, 'enough': True,
                'evidence': [{'game': key, 'label': '11-04 · 对阵 #29', 'note': '龙团后 120 秒没转成推塔'}],
                'primary_destination': f'#match/{key}',
                'deep_destination': f'{DEEP_ROUTE}?from={from_}&to={to_}',
                'limitation': '按终局面板统计。',
            },
            {
                'id': 'comp_concentrated', 'kind': 'comp', 'title': '阵容更集中在中野',
                'conclusion': '本周 5 局用同一套中野双人组，上周用了 8 套不同组合。',
                'numbers': [{'label': '本期', 'value': '5 套'}, {'label': '上期', 'value': '8 套'}],
                'n': 6, 'enough': True,
                'evidence': [{'game': 'channel-find-4', 'label': '11-03 · 对阵 #22', 'note': '同一套中野组合'}],
                'primary_destination': '#match/channel-find-4',
                'deep_destination': f'{DEEP_ROUTE}?from={from_}&to={to_}',
                'limitation': '',
            },
            {
                'id': 'roster_death_up', 'kind': 'roster', 'title': '发育路一局死 3 次以上的情况变多了',
                'conclusion': '本周 23 局里有 7 局发育路一局死 3 次以上，上周 21 局里 4 局。',
                'numbers': [{'label': '本期', 'value': '7/23 局'}, {'label': '上期', 'value': '4/21 局'}],
                'n': 23, 'enough': True,
                'evidence': [{'game': 'channel-find-5', 'label': '11-04 · 对阵 #29', 'note': '发育路 0/5/2'}],
                'primary_destination': '#match/channel-find-5',
                'deep_destination': f'{DEEP_ROUTE}?from={from_}&to={to_}',
                'limitation': '',
            },
            {
                'id': 'opening_death', 'kind': 'training', 'title': '开局 5 分钟内掉点的情况变多了',
                'conclusion': '本周 6 局里有 4 局开局 5 分钟就掉点，上周 2 局。',
                'numbers': [{'label': '本期', 'value': '4/6'}, {'label': '上期', 'value': '2/6'}],
                'n': 6, 'enough': True,
                'evidence': [{'game': 'channel-find-6', 'label': '11-02 · 对阵 #17', 'note': '2:40 掉点'}],
                'primary_destination': '#match/channel-find-6',
                'deep_destination': f'{DEEP_ROUTE}?from={from_}&to={to_}',
                'limitation': '',
            },
        ],
        'findingsTitle': '本期重点发现',
        'findingsCountText': '6 条',
        'watchTitle': '本期最值得复盘的比赛',
        'watchCountText': '5 局',
        'watch': watch_items,
        'watchField': 'deficit',
        'watchFields': watch_fields,
        'watchDisplayFields': list(WATCH_DISPLAY_DEFAULT),
        'next': {
            'available': True, 'note': '',
            'items': [{'date': '2026-11-14', 'time': '19:30', 'opponent': '待命名战队 #29', 'note': '训练赛'}],
        },
        'sources': {'replay': 23, 'panel': 32, 'schedule': 1, 'note': '来源：官方回放 + 营地终局面板'},
        'notes': ['训练赛与正式比赛未区分，按来源筛选查看'],
    }


def empty_period_payload(key):
    data = payload('today', key=key)
    data.update({
        'available': False,
        'reason': '今日还没有登记对局。',
        'fallback_hint': {'from': '2026-11-02', 'to': '2026-11-02', 'label': '11-02 ~ 11-02', 'games': 7},
        'coverage': {'games': 0, 'decided': 0, 'withReplay': 0, 'withTimeline': 0, 'panelGames': 0,
                     'versions': [], 'opponents': 0, 'dateLabel': '11-13 ~ 11-13', 'note': ''},
        # 空周期 / 空库不能再沿用上一期的战绩，否则「本期无对局」会带着 4 胜 2 负。
        'record': {'wins': 0, 'losses': 0, 'decided': 0, 'winRate': None, 'form': [],
                   'prev': {'wins': 0, 'losses': 0, 'decided': 0, 'winRate': None}},
        'summary': None, 'metrics': [], 'findings': [],
        'watch': [], 'watchField': None, 'watchFields': [], 'watchDisplayFields': [],
    })
    return data


def empty_library_payload(key):
    data = empty_period_payload(key)
    data.update({'reason': '这个工作台还没有任何对局数据。', 'fallback_hint': None,
                 'next': {'available': False, 'note': '还没有登记下一场约训', 'items': []}})
    return data


def legacy_payload(key):
    """老报文：无 watchFields / moments，只有单组旧结构 watch（前端应完全兼容）。"""
    data = payload('week', key=key)
    data['watch'] = [{
        'id': 'watch_legacy', 'kind': 'loss', 'field': 'deficit',
        'title': '11-04 · 对阵 #29', 'conclusion': '老报文的一句话结论。',
        'numbers': [{'label': '时长', 'value': '27:08'},
                    {'label': '10 分钟经济差', 'value': '-2,500 金币'}],
        'rosterText': '项羽 · 姜子牙',
        'rosterPlayers': [{'name': '项羽', 'lane': '对抗路', 'icon': '/catalog/icons/hero-105.png'}],
        'evidence': [{'game': key, 'label': '这局过程', 'note': ''}],
    }]
    data['watchCountText'] = '1 局'
    data.pop('watchFields', None)
    data.pop('watchField', None)
    data.pop('watchDisplayFields', None)
    data.pop('watchNote', None)
    return data


class Mocker:
    """按 period 返回合成简报；seen 记下每次请求参数，用来断言「切周期真的重新取数」。"""

    def __init__(self, key):
        self.key = key
        self.seen = []
        self.mode = 'periods'   # periods | empty_library

    def handler(self, route):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(route.request.url).query)
        period = (query.get('period') or ['week'])[0]
        frm = (query.get('from') or [''])[0]
        to = (query.get('to') or [''])[0]
        n_raw = (query.get('n') or [''])[0]
        days_raw = (query.get('days') or [''])[0]
        self.seen.append({'period': period, 'from': frm, 'to': to, 'n': n_raw, 'days': days_raw})
        if self.mode == 'legacy':
            body = legacy_payload(self.key)
        elif self.mode == 'empty_library':
            body = empty_library_payload(self.key)
        elif period == 'today':
            body = empty_period_payload(self.key)
        elif period == 'month':
            time.sleep(0.45)    # 留出可观察的 loading 窗口
            body = payload('month', key=self.key, cover='21',
                           sentence='本月 21 局 12 胜 9 负，胜率 57.1%，比上月同期少赢 3 局。')
        elif period == 'recent':
            recent_n = int(n_raw or 5)
            body = payload('recent', key=self.key, cover='5', n=recent_n,
                           sentence=f'最近 {recent_n} 场 4 胜 1 负，胜率 80.0%，比前 {recent_n} 场多赢 1 场。')
        elif period == 'days':
            recent_days = int(days_raw or 3)
            body = payload('days', key=self.key, cover='3', days=recent_days,
                           sentence=f'最近 {recent_days} 天 3 局 3 胜 0 负，胜率 100.0%。')
        elif period == 'custom':
            body = payload('custom', frm=frm, to=to, key=self.key, cover='7',
                           sentence=f'{(frm or "11-02")[5:]} ~ {(to or "11-02")[5:]} 共 7 局 5 胜 2 负，胜率 71.4%。')
        else:
            body = payload('week', key=self.key)
        route.fulfill(status=200, content_type='application/json',
                      body=json.dumps(body, ensure_ascii=False))


def seed(page, clear_filters=True):
    script = "localStorage.setItem('training-tour-complete-v3','1');" \
             "localStorage.setItem('training-tour-complete','1');"
    if clear_filters:
        script += "localStorage.removeItem('training-rebuild-filters');"
    page.add_init_script(script)


def collect_errors(page, sink):
    def on_console(msg):
        if msg.type != 'error':
            return
        try:
            location = msg.location or {}
            suffix = ' @ %s:%s' % (location.get('url', ''), location.get('lineNumber', ''))
        except Exception:
            suffix = ''
        message = 'console: ' + msg.text + suffix
        # mock 卡片用的是合成 game key（channel-mock-*），点开单局必然 404；
        # 这里只过滤这条已知噪音，真实回归里的 Enter 劫持另有专门断言。
        if '/api/matches/channel-mock-' in message:
            return
        sink.append(message)
    page.on('console', on_console)
    page.on('pageerror', lambda exc: sink.append(
        'pageerror: ' + str(exc) + ' | stack: ' + str(getattr(exc, 'stack', exc))[:400]))


def settle(page, timeout=3000):
    """等 CSS 入场动画播完再截图：简报各区块有 fade-in，截早了会拍到半透明的中间帧。"""
    try:
        page.wait_for_function(
            "() => document.getAnimations().every((a) => "
            "a.playState === 'finished' || a.playState === 'idle')",
            timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(60)


def wait_brief(page, timeout=15000):
    page.wait_for_selector('[data-pbr-root] .pbr-summary, [data-pbr-root] .pbr-empty', timeout=timeout)
    settle(page)


def body_text(page):
    return page.inner_text('#content')


def overflow_px(page):
    return page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")


def boxes_fit(page, selector):
    return page.evaluate("""(sel) => {
      const width = document.documentElement.clientWidth;
      return [...document.querySelectorAll(sel)].every((node) => {
        const rect = node.getBoundingClientRect();
        return rect.width <= width + 1 && rect.right <= width + 1 && rect.left >= -1;
      });
    }""", selector)


def single_column(page, selector):
    """grid/flex 布局是否单列；不是 grid/flex 返回 None（调用方自行决定）。"""
    return page.evaluate("""(sel) => {
      const node = document.querySelector(sel);
      if (!node) return null;
      const style = getComputedStyle(node);
      if (style.display === 'grid') {
        return style.gridTemplateColumns.split(' ').filter(Boolean).length;
      }
      if (style.display === 'flex') {
        return style.flexDirection.startsWith('column') ? 1 : 2;
      }
      return null;
    }""", selector)


def findings_title_lines(page):
    """发现区每行标题占几行：对标题文本取 Range.getClientRects()，按 top 去重。

    标题用 CSS ellipsis 截断时 scrollWidth 可能大于 clientWidth，所以不能只看 scrollWidth；
    行数 = 文本矩形不同的 top 数（正常单行应为 1）。
    """
    return page.evaluate("""() => {
      const rows = [...document.querySelectorAll('.pbr-findings:not(.pbr-watch) .pbr-finding')];
      return rows.map((row, index) => {
        const title = row.querySelector('h3');
        if (!title) return {index, found: false, lines: 0, text: ''};
        const range = document.createRange();
        range.selectNodeContents(title);
        const rects = [...range.getClientRects()].filter((rect) => rect.width > 0.5);
        const tops = new Set(rects.map((rect) => Math.round(rect.top)));
        const style = getComputedStyle(title);
        return {
          index, found: true, lines: tops.size,
          nowrap: style.whiteSpace === 'nowrap',
          ellipsis: style.textOverflow === 'ellipsis',
          titleRight: title.getBoundingClientRect().right,
          rowRight: row.getBoundingClientRect().right,
          text: (title.textContent || '').trim().slice(0, 24),
        };
      });
    }""")


def watch_state(page):
    """复盘区当前状态：发区头工具栏（排序/字段按钮+弹层）、可见分组、卡片数字、localStorage。"""
    return page.evaluate("""() => {
      const parse = (text) => {
        const match = (text || '').match(/rgba?\\(([^)]+)\\)/);
        if (!match) return null;
        const parts = match[1].split(',').map((value) => parseFloat(value.trim()));
        return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
      };
      const luminance = (color) => {
        const channel = (value) => {
          const unit = value / 255;
          return unit <= 0.03928 ? unit / 12.92 : Math.pow((unit + 0.055) / 1.055, 2.4);
        };
        return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
      };
      /* 文字必须和背景有对比度：白字白底 / 同色底字是常见视觉回归。 */
      const contrast = (node) => {
        const style = getComputedStyle(node);
        let fg = parse(style.color);
        let bg = parse(style.backgroundColor);
        let parent = node.parentElement;
        let guard = 0;
        while ((!bg || bg.a < 1) && parent && guard < 12) {
          const parentBg = parse(getComputedStyle(parent).backgroundColor);
          if (parentBg && parentBg.a > 0) {
            bg = bg && bg.a < 1 ? {
              r: bg.r * bg.a + parentBg.r * (1 - bg.a),
              g: bg.g * bg.a + parentBg.g * (1 - bg.a),
              b: bg.b * bg.a + parentBg.b * (1 - bg.a), a: 1,
            } : parentBg;
          }
          parent = parent.parentElement;
          guard += 1;
        }
        if (!fg || !bg) return null;
        const fgLum = luminance(fg);
        const bgLum = luminance(bg);
        const light = Math.max(fgLum, bgLum);
        const dark = Math.min(fgLum, bgLum);
        return Math.round(((light + 0.05) / (dark + 0.05)) * 100) / 100;
      };
      const text = (node) => node ? (node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
      const shown = (node) => {
        if (!node) return false;
        if (node.hasAttribute('hidden')) return false;
        const rect = node.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
        const style = getComputedStyle(node);
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
      };
      const rectOf = (node) => {
        if (!node) return null;
        const rect = node.getBoundingClientRect();
        return { left: Math.round(rect.left * 10) / 10, right: Math.round(rect.right * 10) / 10,
                 top: Math.round(rect.top * 10) / 10, width: Math.round(rect.width * 10) / 10,
                 height: Math.round(rect.height * 10) / 10 };
      };
      const section = document.querySelector('.pbr-watch');
      if (!section) return null;
      const sortToggle = document.querySelector('[data-pbr-sort-toggle]');
      const sortPop = document.querySelector('[data-pbr-sort-pop]');
      const fieldsToggle = document.querySelector('[data-pbr-fields-toggle]');
      const fieldsPop = document.querySelector('[data-pbr-fields-pop]');
      const groupNodes = [...section.querySelectorAll('[data-pbr-watch-group]')];
      const activeGroups = groupNodes.filter((node) => !node.hasAttribute('hidden'));
      const cards = activeGroups.length ? [...activeGroups[0].querySelectorAll('.pbr-finding')] : [];
      const readCard = (card) => {
        const items = [...card.querySelectorAll('[data-pbr-value]')];
        return {
          count: items.length,
          values: items.map((node) => ({
            id: node.getAttribute('data-pbr-value'),
            label: text(node.querySelector('small')),
            value: text(node.querySelector('b') || node),
            focus: node.classList.contains('is-focus'),
            missing: node.classList.contains('is-missing') || text(node.querySelector('b') || node) === '—',
          })),
          roster: card.querySelectorAll('a.pbr-roster-item').length,
          rosterHref: card.querySelector('a.pbr-roster-item')
            ? card.querySelector('a.pbr-roster-item').getAttribute('href') : '',
        };
      };
      const readOption = (node, attr) => {
        const input = node.matches('input') ? node : node.querySelector('input[type="checkbox"]');
        /* 字段项是原生 checkbox，行文本在它的 <label> 里；排序项是 <button role=option> 本身。 */
        const row = node.matches('input') ? (node.closest('label') || node.parentElement || node) : node;
        const checked = Boolean(input && input.checked)
          || node.getAttribute('aria-checked') === 'true'
          || Boolean(input && input.getAttribute('aria-checked') === 'true');
        return {
          id: node.getAttribute(attr),
          text: text(row),
          selected: node.getAttribute('aria-selected') === 'true',
          checked,
          disabled: Boolean(node.disabled) || Boolean(input && input.disabled)
            || node.hasAttribute('disabled') || node.getAttribute('aria-disabled') === 'true'
            || Boolean(row.classList && row.classList.contains('is-disabled')),
          visible: shown(row),
          contrast: contrast(row.querySelector('b') || row),
        };
      };
      const sortOptions = [...document.querySelectorAll('[data-pbr-sort-option]')]
        .filter((node) => section.contains(node)).map((node) => readOption(node, 'data-pbr-sort-option'));
      const fieldOptions = [...document.querySelectorAll('[data-pbr-field-option]')]
        .filter((node) => section.contains(node)).map((node) => readOption(node, 'data-pbr-field-option'));
      const countNode = section.querySelector('[data-pbr-watch-count]');
      const titleNode = section.querySelector('.pbr-section-title h2');
      let storage = null;
      try { storage = localStorage.getItem('pbr-watch-display-fields'); } catch (error) {}
      const active = document.activeElement;
      return {
        exists: true,
        legacyChips: section.querySelectorAll('[data-pbr-watch]').length,
        legacyDisplays: document.querySelectorAll('[data-pbr-display]').length,
        oldControls: section.querySelectorAll('.pbr-watch-controls').length,
        sortToggle: sortToggle ? {
          exists: true, text: text(sortToggle),
          expanded: sortToggle.getAttribute('aria-expanded'),
          visible: shown(sortToggle), contrast: contrast(sortToggle),
          active: active === sortToggle,
        } : { exists: false },
        sortPop: sortPop ? { exists: true, visible: shown(sortPop), rect: rectOf(sortPop) } : { exists: false },
        fieldsToggle: fieldsToggle ? {
          exists: true, text: text(fieldsToggle),
          expanded: fieldsToggle.getAttribute('aria-expanded'),
          visible: shown(fieldsToggle), contrast: contrast(fieldsToggle),
          active: active === fieldsToggle,
        } : { exists: false },
        fieldsPop: fieldsPop ? { exists: true, visible: shown(fieldsPop), rect: rectOf(fieldsPop) } : { exists: false },
        sortOptions,
        fieldOptions,
        checkedIds: fieldOptions.filter((option) => option.checked).map((option) => option.id),
        disabledIds: fieldOptions.filter((option) => option.disabled).map((option) => option.id),
        visibleGroups: activeGroups.map((node) => node.getAttribute('data-pbr-watch-group')),
        groupCount: groupNodes.length,
        countText: text(countNode),
        cardCount: cards.length,
        cards: cards.map(readCard),
        focusIds: cards.length
          ? [...cards[0].querySelectorAll('[data-pbr-value].is-focus')].map((node) => node.getAttribute('data-pbr-value'))
          : [],
        focusCount: cards.reduce((sum, card) => sum + card.querySelectorAll('[data-pbr-value].is-focus').length, 0),
        titleBottom: titleNode ? Math.round(titleNode.getBoundingClientRect().bottom * 10) / 10 : null,
        sortTop: sortToggle ? Math.round(sortToggle.getBoundingClientRect().top * 10) / 10 : null,
        fieldsTop: fieldsToggle ? Math.round(fieldsToggle.getBoundingClientRect().top * 10) / 10 : null,
        sectionNote: text(section.querySelector('.pbr-section-head .pbr-section-note')),
        storage,
        resetButton: [...section.querySelectorAll('button')]
          .filter((node) => (node.textContent || '').includes('恢复默认')).length,
        text: section.innerText,
        viewport: { width: document.documentElement.clientWidth, height: document.documentElement.clientHeight },
      };
    }""")


def blur_active(page):
    """截图用：把当前焦点元素 blur 掉，避免截图里留下键盘焦点环。"""
    page.evaluate("() => { const node = document.activeElement; if (node && node.blur) node.blur(); }")
    page.wait_for_timeout(80)


def focus_watch_section(page):
    """截图用：把「复盘区」滚到视口上方，保证区头下方展开的弹层能完整入镜。"""
    page.evaluate("""() => {
      const node = document.querySelector('.pbr-watch');
      if (node) window.scrollTo(0, Math.max(0, node.getBoundingClientRect().top + window.scrollY - 90));
    }""")
    page.wait_for_timeout(150)


def metric_tiers(page):
    """指标大数字的等级配色：有 rank 的指标 value 上应有 is-lead/is-mid/is-behind。"""
    return page.evaluate("""() => {
      const text = (node) => node ? (node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
      const nodes = [...document.querySelectorAll('.pbr-metric')];
      return nodes.map((node) => {
        const value = node.querySelector('.pbr-metric-value');
        const rank = node.querySelector('.pbr-rank');
        let tier = null;
        if (rank) {
          if (rank.classList.contains('is-lead')) tier = 'lead';
          else if (rank.classList.contains('is-mid')) tier = 'mid';
          else if (rank.classList.contains('is-behind')) tier = 'behind';
        }
        return {
          label: text(node.querySelector('.pbr-metric-label')),
          hasRank: Boolean(rank),
          tier,
          valueClasses: value ? [...value.classList].filter((name) => /^is-(lead|mid|behind)$/.test(name)) : [],
          valueColor: value ? getComputedStyle(value).color : null,
          rankColor: rank ? getComputedStyle(rank).color : null,
          valueText: text(value),
        };
      });
    }""")


def findings_state(page):
    """重点发现区：滚动容器尺寸、行顺序、关注按钮与关注态、边框颜色。"""
    return page.evaluate("""() => {
      const list = document.querySelector('.pbr-findings:not(.pbr-watch) .pbr-finding-list');
      const rows = list ? [...list.querySelectorAll('.pbr-finding')] : [];
      const text = (node) => node ? (node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
      return {
        exists: Boolean(list),
        overflowY: list ? getComputedStyle(list).overflowY : null,
        scrollHeight: list ? list.scrollHeight : 0,
        clientHeight: list ? list.clientHeight : 0,
        scrollTop: list ? Math.round(list.scrollTop) : 0,
        focusable: list ? (list.tabIndex >= 0 || list.hasAttribute('tabindex')) : false,
        favCount: list ? list.querySelectorAll('[data-pbr-fav-finding]').length : 0,
        rows: rows.map((row) => {
          const button = row.querySelector('[data-pbr-fav-finding]');
          const style = getComputedStyle(row);
          return {
            id: button ? button.getAttribute('data-pbr-fav-finding') : '',
            title: text(row.querySelector('h3')),
            isFav: row.classList.contains('is-fav'),
            favText: text(button),
            borderColor: style.borderColor,
            borderLeftColor: style.borderLeftColor,
            boxShadow: style.boxShadow,
            backgroundColor: style.backgroundColor,
            hasFavButton: Boolean(button),
          };
        }),
      };
    }""")


def watch_hscroll_state(page):
    """复盘区：可见分组的横向滚动容器、每卡关注按钮/关注态、左右箭头按钮。"""
    return page.evaluate("""() => {
      const text = (node) => node ? (node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
      const section = document.querySelector('.pbr-watch');
      if (!section) return null;
      const groups = [...section.querySelectorAll('[data-pbr-watch-group]')];
      const visible = groups.find((node) => !node.hasAttribute('hidden')) || null;
      const isScroller = (node) => {
        if (!node) return false;
        const style = getComputedStyle(node);
        return (style.overflowX === 'auto' || style.overflowX === 'scroll')
          && node.scrollWidth > node.clientWidth + 1;
      };
      let scroller = null;
      if (visible) {
        if (isScroller(visible)) scroller = visible;
        else scroller = [...visible.querySelectorAll('*')].find(isScroller) || null;
      }
      const cards = visible ? [...visible.querySelectorAll('.pbr-finding')] : [];
      const readCard = (card) => {
        const button = card.querySelector('[data-pbr-fav-watch]');
        let gameKey = button ? button.getAttribute('data-pbr-fav-watch') : '';
        if (!gameKey) {
          const link = card.querySelector('a[href^="#match/"]');
          gameKey = link ? decodeURIComponent(link.getAttribute('href').replace('#match/', '')) : '';
        }
        const style = getComputedStyle(card);
        return {
          key: gameKey,
          title: text(card.querySelector('h3')),
          isFav: card.classList.contains('is-fav'),
          favText: text(button),
          borderColor: style.borderColor,
          hasFavButton: Boolean(button),
        };
      };
      const buttonOf = (selectors, glyphs) => {
        for (const selector of selectors) {
          const node = section.querySelector(selector);
          if (node) return node;
        }
        return [...section.querySelectorAll('button')].find((node) => glyphs.includes(text(node))) || null;
      };
      const info = (node) => node ? {
        exists: true, text: text(node),
        disabled: Boolean(node.disabled) || node.hasAttribute('disabled')
          || node.getAttribute('aria-disabled') === 'true',
        visible: node.getBoundingClientRect().width > 0,
      } : { exists: false };
      const prev = buttonOf(['[data-pbr-watch-prev]', '[data-pbr-watch-scroll-prev]',
                             '[data-pbr-scroll-prev]', '[aria-label*="上一"]'], ['‹', '←', '上一屏']);
      const next = buttonOf(['[data-pbr-watch-next]', '[data-pbr-watch-scroll-next]',
                             '[data-pbr-scroll-next]', '[aria-label*="下一"]'], ['›', '→', '下一屏']);
      return {
        group: visible ? visible.getAttribute('data-pbr-watch-group') : null,
        groupCount: groups.length,
        cards: cards.map(readCard),
        cardCount: cards.length,
        scroller: scroller ? {
          tag: scroller.tagName.toLowerCase(),
          className: scroller.className,
          scrollWidth: scroller.scrollWidth,
          clientWidth: scroller.clientWidth,
          scrollLeft: Math.round(scroller.scrollLeft),
          overflowX: getComputedStyle(scroller).overflowX,
        } : null,
        prev: info(prev),
        next: info(next),
        sectionWidth: section.clientWidth,
      };
    }""")


def arrow_locator(page, kind):
    """左右箭头按钮：data 属性名与实现一致（[data-pbr-watch-prev/next]），其余做兼容兜底。"""
    selectors = (['[data-pbr-watch-prev]', '[data-pbr-watch-scroll-prev]', '[data-pbr-scroll-prev]']
                 if kind == 'prev' else
                 ['[data-pbr-watch-next]', '[data-pbr-watch-scroll-next]', '[data-pbr-scroll-next]'])
    for selector in selectors:
        locator = page.locator(selector)
        if locator.count():
            return locator.first
    glyph = '‹' if kind == 'prev' else '›'
    for search in (glyph, '上一屏', '下一屏'):
        locator = page.locator('.pbr-watch button', has_text=search)
        if locator.count():
            return locator.first
    return None


def set_scroll(page, selector, value, axis='top'):
    page.evaluate("""([sel, amount, axisName]) => {
      const node = document.querySelector(sel);
      if (!node) return;
      if (axisName === 'left') node.scrollLeft = amount;
      else node.scrollTop = amount;
    }""", [selector, value, axis])


def period_state(page):
    """6 个周期按钮：kind / 文本 / aria-pressed / 是否可见。"""
    return page.evaluate("""() => {
      const text = (node) => node ? (node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
      return [...document.querySelectorAll('[data-pbr-period]')].map((node) => ({
        kind: node.getAttribute('data-pbr-period'),
        label: text(node),
        pressed: node.getAttribute('aria-pressed') === 'true',
        visible: node.getBoundingClientRect().width > 0,
      }));
    }""")


def moments_state(page):
    """可见复盘分组内每张卡的关键时间点 chips（clock/label/href）。"""
    return page.evaluate("""() => {
      const text = (node) => node ? (node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
      const section = document.querySelector('.pbr-watch');
      if (!section) return null;
      const groups = [...section.querySelectorAll('[data-pbr-watch-group]')];
      const visible = groups.find((node) => !node.hasAttribute('hidden')) || null;
      const cards = visible ? [...visible.querySelectorAll('.pbr-finding')] : [];
      return {
        group: visible ? visible.getAttribute('data-pbr-watch-group') : null,
        cards: cards.map((card) => {
          const container = card.querySelector('[data-pbr-moments]');
          const chips = container ? [...container.querySelectorAll('[data-pbr-moment]')] : [];
          const mainLink = card.querySelector('a[href^="#match/"]');
          return {
            key: card.getAttribute('data-watch-key') || '',
            mainHref: mainLink ? mainLink.getAttribute('href') : '',
            hasContainer: Boolean(container),
            moments: chips.map((chip) => {
              const clock = text(chip.querySelector('b'));
              const label = text(chip.querySelector('span'));
              const box = container ? container.getBoundingClientRect() : null;
              const rect = chip.getBoundingClientRect();
              return {
                clock,
                label,
                text: clock ? (clock + ' ' + label).trim() : text(chip),
                href: chip.getAttribute('href') || '',
                visible: Boolean(box) && rect.top >= box.top - 1 && rect.bottom <= box.bottom + 1,
              };
            }),
          };
        }),
      };
    }""")


def fav_workflow_state(page):
    """发现行/复盘卡上的关注工作流：已复盘按钮、结论按钮/文本/输入框、视图与忽略/导出控件。"""
    return page.evaluate("""() => {
      const text = (node) => node ? (node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
      const readItem = (el) => {
        const review = el.querySelector('[data-pbr-fav-review]');
        const noteButton = el.querySelector('[data-pbr-fav-note]');
        const noteText = el.querySelector('[data-pbr-note-text]');
        const input = el.querySelector('[data-pbr-note-input]');
        const favButton = el.querySelector('[data-pbr-fav-finding], [data-pbr-fav-watch]');
        return {
          key: favButton
            ? (favButton.getAttribute('data-pbr-fav-finding') || favButton.getAttribute('data-pbr-fav-watch'))
            : '',
          isFav: el.classList.contains('is-fav'),
          favText: text(favButton),
          review: review ? {
            exists: true, text: text(review),
            pressed: review.getAttribute('aria-pressed') === 'true',
            on: review.classList.contains('is-on'),
            height: Math.round(review.getBoundingClientRect().height),
          } : { exists: false },
          noteButton: noteButton ? { exists: true, text: text(noteButton) } : { exists: false },
          noteText: noteText ? { exists: true, text: text(noteText) } : { exists: false },
          input: input ? {
            exists: true,
            visible: input.getBoundingClientRect().height > 0,
            value: input.value || '',
          } : { exists: false },
        };
      };
      const findings = [...document.querySelectorAll('.pbr-findings:not(.pbr-watch) .pbr-finding')];
      const watchSection = document.querySelector('.pbr-watch');
      const groups = watchSection ? [...watchSection.querySelectorAll('[data-pbr-watch-group]')] : [];
      const visibleGroup = groups.find((node) => !node.hasAttribute('hidden')) || null;
      const watchCards = visibleGroup ? [...visibleGroup.querySelectorAll('.pbr-finding')] : [];
      const storage = {};
      for (const key of ['pbr-finding-favs', 'pbr-watch-favs', 'pbr-finding-ignored', 'pbr-view-mode']) {
        try { storage[key] = localStorage.getItem(key); } catch (error) {}
      }
      const viewButtons = [...document.querySelectorAll('[data-pbr-view-mode]')];
      const exportBtn = document.querySelector('[data-pbr-export]');
      const restoreBtn = document.querySelector('[data-pbr-restore-ignored]');
      return {
        findings: findings.map(readItem),
        watch: watchCards.map(readItem),
        storage,
        viewMode: (() => {
          const active = viewButtons.find((node) => node.getAttribute('aria-pressed') === 'true');
          return active ? active.getAttribute('data-pbr-view-mode') : null;
        })(),
        viewButtons: viewButtons.map((node) => ({
          mode: node.getAttribute('data-pbr-view-mode'),
          text: text(node),
          pressed: node.getAttribute('aria-pressed') === 'true',
        })),
        exportButton: exportBtn ? {
          exists: true, text: text(exportBtn),
          disabled: Boolean(exportBtn.disabled) || exportBtn.getAttribute('aria-disabled') === 'true',
        } : { exists: false },
        restoreIgnored: restoreBtn ? { exists: true, text: text(restoreBtn) } : { exists: false },
        ignoreButtons: document.querySelectorAll('[data-pbr-ignore-finding]').length,
        watchCountText: (() => {
          const node = document.querySelector('.pbr-watch [data-pbr-watch-count]');
          return text(node);
        })(),
        findingCountText: (() => {
          const node = document.querySelector('.pbr-findings:not(.pbr-watch) .pbr-section-chip');
          return text(node);
        })(),
      };
    }""")


def units_state(page):
    """单位弱化（.pbr-unit）与按钮高度、发现结论 clamp。"""
    return page.evaluate("""() => {
      const units = [...document.querySelectorAll('.pbr-unit')].map((node) => (
        (node.textContent || '').trim()));
      const clampNode = document.querySelector('.pbr-findings:not(.pbr-watch) .pbr-conclusion');
      const style = clampNode ? getComputedStyle(clampNode) : null;
      const button = document.querySelector('[data-pbr-fav-review]');
      const favButton = document.querySelector('[data-pbr-fav-finding], [data-pbr-fav-watch]');
      const watchNumbers = document.querySelector('.pbr-watch .pbr-num');
      const metricValue = document.querySelector('.pbr-metric-value');
      return {
        units,
        unitCount: units.length,
        clamp: style ? (style.webkitLineClamp || style.getPropertyValue('-webkit-line-clamp')) : null,
        reviewHeight: button ? Math.round(button.getBoundingClientRect().height) : null,
        favHeight: favButton ? Math.round(favButton.getBoundingClientRect().height) : null,
        watchNumberHtml: watchNumbers ? watchNumbers.innerHTML : '',
        metricValueHtml: metricValue ? metricValue.innerHTML : '',
      };
    }""")


def shortcut_state(page):
    """快捷键：提示文本、当前卡（.is-current / data-watch-key）、焦点元素。"""
    return page.evaluate("""() => {
      const text = (node) => node ? (node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
      const hint = document.querySelector('[data-pbr-shortcut-hint]');
      const section = document.querySelector('.pbr-watch');
      const groups = section ? [...section.querySelectorAll('[data-pbr-watch-group]')] : [];
      const visible = groups.find((node) => !node.hasAttribute('hidden')) || null;
      const current = visible ? visible.querySelector('.pbr-finding.is-current') : null;
      const active = document.activeElement;
      return {
        hint: hint ? { exists: true, text: text(hint) } : { exists: false },
        currentKey: current ? current.getAttribute('data-watch-key') : null,
        currentVisible: current ? current.getBoundingClientRect().width > 0 : false,
        activeTag: active ? active.tagName.toLowerCase() : '',
        activeKey: active && active.closest
          ? (active.closest('[data-watch-key]') ? active.closest('[data-watch-key]').getAttribute('data-watch-key') : '')
          : '',
        activeInsideWatch: Boolean(active && active.closest && active.closest('.pbr-watch')),
        firstCardKey: visible && visible.querySelector('.pbr-finding')
          ? (visible.querySelector('.pbr-finding').getAttribute('data-watch-key') || '') : '',
      };
    }""")


def read_storage(page, key):
    raw = page.evaluate("(key) => { try { return localStorage.getItem(key); } catch (e) { return null; } }", key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


def href_of(page, selector, default=''):
    locator = page.locator(selector).first
    return locator.get_attribute('href') if locator.count() else default


def run_mock(base, browser, key, mocker):
    def new_page(viewport):
        page = browser.new_page(viewport=viewport)
        seed(page)
        page.route('**/api/briefing*', mocker.handler)
        return page

    # ── 1) 默认首页：本周简报的标题、范围、战况、指标、变化、约训、覆盖 ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    text = body_text(page)
    check('赛训周期简报' in text, '首页缺少 kicker「赛训周期简报」')
    check('赛训总览' in text, '首页缺少标题「赛训总览」')
    check('本周赛训表现 · 对比上周同期' in text, '缺少副标题「本周赛训表现 · 对比上周同期」')
    check('11-09 ~ 11-15' in text and '11-02 ~ 11-08' in text, '副标题缺少本期 / 上期实际范围')
    check(page.locator('[data-pbr-period="week"]').get_attribute('aria-pressed') == 'true',
          '默认周期没有高亮「本周」')
    check(page.locator('[data-pbr-period]').count() == 6,
          '周期按钮应为 今日/本周/本月/近5场/近3天/自定义 六个：'
          + str(page.locator('[data-pbr-period]').count()))
    check('本周 6 局 4 胜 2 负，胜率 66.7%，比上周同期少赢 1 局。' in text, '缺少后端的战况句')
    check('训练赛战绩来自营地终局面板' in text, '缺少来源说明')
    check(page.locator('.pbr-metric').count() == 8, '指标数量不对：' + str(page.locator('.pbr-metric').count()))
    check(page.locator('.pbr-rank').count() == 6, '有排名的指标应有 6 项')
    check(page.locator('.pbr-meter').count() == 6, '百分位条应有 6 条（.pbr-meter）')
    check(page.locator('.pbr-rankbar').count() == 0, '过期类名 .pbr-rankbar 不应再出现')
    check('金币' in text and '66.7%' in text, '数值应为 xx/xx 加小号百分率与金币')
    check('（66.7%）' not in text, '百分率不应再用全角括号')
    check(page.locator('a.pbr-metric').count() == 0, '指标卡不应是链接')
    check('本期重点发现' in text, '缺少「本期重点发现」')
    check('本期最值得复盘的比赛' in text, '缺少「本期最值得复盘的比赛」')
    findings = page.locator('.pbr-findings:not(.pbr-watch) .pbr-finding')
    check(findings.count() == 6, '发现区应渲染全部 6 条（不再截 3 条），实际 ' + str(findings.count()))
    check(findings.locator('.pbr-stat').count() == 6, '每条发现行应恰好 1 个 .pbr-stat（右栏数字块），实际 '
          + str(findings.locator('.pbr-stat').count()))
    titles = findings_title_lines(page)
    broken = [item for item in titles if not item.get('found') or item.get('lines') != 1]
    check(not broken, '发现区标题换行了（应单行省略）：' + json.dumps(broken, ensure_ascii=False))
    check(all(item.get('titleRight', 0) <= item.get('rowRight', 0) + 1 for item in titles),
          '发现区标题超出所在行')
    notes.append('[mock] 发现区 %d 行，标题行数 %s' % (
        findings.count(), [item.get('lines') for item in titles]))
    watch = watch_state(page)
    check(watch is not None, '复盘区没有渲染出来')
    if watch:
        check(watch['legacyChips'] == 0, '旧版筛选胶囊 data-pbr-watch 不应再出现：' + str(watch['legacyChips']))
        check(watch['legacyDisplays'] == 0, '旧版显示字段胶囊 data-pbr-display 不应再出现')
        check(watch['oldControls'] == 0, '旧版 .pbr-watch-controls 边框盒子不应再出现')
        check(watch['groupCount'] == 10, f'复盘分组应为 10 组，实际 {watch["groupCount"]}')
        check(watch['visibleGroups'] == ['deficit'], '初始只应显示默认分组：' + str(watch['visibleGroups']))
        # 区头工具栏：排序按钮（当前字段 + N 局）与字段按钮（显示 4 项），默认都收起
        sort_toggle = watch['sortToggle']
        check(sort_toggle.get('exists'), '缺少排序按钮 [data-pbr-sort-toggle]')
        if sort_toggle.get('exists'):
            check('最多落后' in sort_toggle['text'], '排序按钮没显示当前字段：' + sort_toggle['text'])
            check('17 局' in sort_toggle['text'], '排序按钮没显示能看这一项的局数：' + sort_toggle['text'])
            check(sort_toggle['expanded'] == 'false',
                  '排序弹层默认应收起：aria-expanded=' + str(sort_toggle['expanded']))
            check(sort_toggle['visible'], '排序按钮不可见')
        fields_toggle = watch['fieldsToggle']
        check(fields_toggle.get('exists'), '缺少字段按钮 [data-pbr-fields-toggle]')
        if fields_toggle.get('exists'):
            check('4 项' in fields_toggle['text'], '字段按钮没显示「显示 4 项」：' + fields_toggle['text'])
            check(fields_toggle['expanded'] == 'false',
                  '字段弹层默认应收起：aria-expanded=' + str(fields_toggle['expanded']))
            check(fields_toggle['visible'], '字段按钮不可见')
        check(watch['sortPop'].get('exists'), '缺少排序弹层容器 [data-pbr-sort-pop]')
        check(not watch['sortPop'].get('visible'), '排序弹层默认不应展开')
        check(watch['fieldsPop'].get('exists'), '缺少字段弹层容器 [data-pbr-fields-pop]')
        check(not watch['fieldsPop'].get('visible'), '字段弹层默认不应展开')
        # 旧的长说明「按「X」从差到好排 · 点开看完整过程」应已删除（排序按钮本身表达）
        check('从差到好排 · 点开' not in watch['sectionNote'],
              '旧的长排序说明应移除：' + watch['sectionNote'])
        check(watch['cardCount'] == 5, '默认分组（deficit）应渲染 5 张卡（不再截 3 张），实际 '
              + str(watch['cardCount']))
        check(all(card['count'] == 4 for card in watch['cards']),
              '每张卡都应渲染 4 项（字段弹层控制所有卡）：' + str([card['count'] for card in watch['cards']]))
        first = watch['cards'][0]['values'] if watch['cards'] else []
        # 数字按字段目录顺序渲染（deficit→deaths→at10→duration），不是 watchDisplayFields 顺序
        check([item['label'] for item in first] == ['最多落后', '我方掉点', '10 分钟经济差', '时长'],
              '卡片数字应按字段目录顺序渲染：' + str([item['label'] for item in first]))
        check(watch['focusIds'] == ['deficit'],
              '当前排序字段（deficit）在显示集合里应高亮：' + str(watch['focusIds']))
        compact = [item for card in watch['cards'] for item in card['values']]
        check(sum(1 for item in compact if item['id'] == 'duration') == len(watch['cards']),
              '每张卡都应保留用户勾选的「时长」：' + str([card['values'] for card in watch['cards']]))
        # 区头「N 局」用后端 count（该字段本期总局数），不是渲染条数：deficit 17 局 / 渲染 5 张
        check(watch['countText'] == '17 局',
              '区头计数应为后端 count（17 局，不是渲染 5 张）：' + watch['countText'])
        check(watch['cards'] and all(card['roster'] == 5 for card in watch['cards']),
              '每张卡都应保留 5 个紧凑头像')
        check(watch['resetButton'] >= 1, '字段弹层缺少「恢复默认」按钮')
        # 工具栏是「文本按钮」而不是实心胶囊：文字对比度必须够。
        for label, node in (('排序按钮', sort_toggle), ('字段按钮', fields_toggle)):
            if node.get('exists') and node.get('contrast') is not None:
                check(node['contrast'] >= 2.5, f'{label}文字对比度不足：{node["contrast"]}')
    check('下一场约训' in text and '待命名战队 #29' in text, '缺少下一场约训')
    check('数据覆盖' in text, '缺少数据覆盖')
    check(href_of(page, '[data-pbr-all-games]') == '#matches', '「全部对局」应指向 #matches')
    check('查看最近一批' not in text, '有数据时不应出现空态入口')
    overflow = overflow_px(page)
    check(overflow <= 1, f'1440 宽度出现横向滚动（溢出 {overflow}px）')
    check(boxes_fit(page, '.pbr-findings:not(.pbr-watch) .pbr-finding'),
          '1440 宽度下发现行超出可视区域')
    check(boxes_fit(page, '.pbr-stat'), '1440 宽度下发现区数字块超出可视区域')
    page.screenshot(path=str(OUT / '30-overview-week-mock-1440.png'), full_page=False)
    notes.append(f'[mock] 首页本周：指标 {page.locator(".pbr-metric").count()} 个，'
                 f'发现 {findings.count()} 行，复盘可见 {len(watch["cards"]) if watch else 0} 局，正文 {len(text)} 字')

    # 中等宽度（1180 简报限宽 / 1024 三列折行）也要标题单行、不溢出。
    for width, shot in ((1180, '30b-overview-week-mock-1180.png'),
                        (1024, '30c-overview-week-mock-1024.png')):
        page.set_viewport_size({'width': width, 'height': 980})
        page.wait_for_timeout(250)
        settle(page)
        overflow = overflow_px(page)
        check(overflow <= 1, f'{width} 宽度出现横向滚动（溢出 {overflow}px）')
        check(boxes_fit(page, '.pbr-findings:not(.pbr-watch) .pbr-finding'),
                  f'{width} 宽度下发现行超出可视区域')
        check(boxes_fit(page, '.pbr-stat'), f'{width} 宽度下发现区数字块超出可视区域')
        titles = findings_title_lines(page)
        broken = [item for item in titles if not item.get('found') or item.get('lines') != 1]
        check(not broken, f'{width} 宽度下发现标题换行了：' + json.dumps(broken, ensure_ascii=False))
        width_state = watch_state(page)
        if width_state and width_state['sortToggle'].get('exists'):
            check(width_state['sortTop'] is not None and width_state['fieldsTop'] is not None
                  and abs(width_state['sortTop'] - width_state['fieldsTop']) <= 6,
                  f'{width} 宽度下复盘工具栏换行了：%s / %s'
                  % (width_state['sortTop'], width_state['fieldsTop']))
            check(boxes_fit(page, '[data-pbr-sort-toggle], [data-pbr-fields-toggle]'),
                  f'{width} 宽度下复盘工具按钮超出可视区')
        page.screenshot(path=str(OUT / shot), full_page=False)
        if width in (1180, 1024):
            focus_watch_section(page)
            settle(page)
            page.screenshot(path=str(OUT / (f'30{"b" if width == 1180 else "c"}2-watch-toolbar-{width}.png')),
                            full_page=False)
    page.set_viewport_size({'width': 1440, 'height': 980})
    page.wait_for_timeout(150)

    # ── 2) 证据对局的下钻链接（「更多分析」已从首页移除） ──
    evidence_href = href_of(page, '.pbr-evidence a')
    check(evidence_href.startswith('#match/'), '证据对局应链到 #match/<key>：' + evidence_href)
    if page.locator('.pbr-evidence a').count():
        page.locator('.pbr-evidence a').first.click()
        page.wait_for_function("() => location.hash.startsWith('#match/')", timeout=8000)
        check(page.evaluate('location.hash').startswith('#match/'), '点证据对局后 hash 没有变成 #match/')
        notes.append(f'[mock] 证据对局 → {page.evaluate("location.hash")}')
    check(not errors, '首页/对局页出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 3) 周期切换：loading、标题与数字变化、不残留旧结论 ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    mocker.seen.clear()
    check(page.evaluate("""() => {
      window.__pbSawLoading = false;
      const host = document.querySelector('[data-pbr-root]');
      new MutationObserver(() => {
        if (document.querySelector('.pbr-loading')) window.__pbSawLoading = true;
      }).observe(host, { childList: true, subtree: true });
      return true;
    }"""), '无法安装 loading 观察器')
    page.click('[data-pbr-period="month"]')
    page.wait_for_function("() => document.body.innerText.includes('本月 21 局 12 胜 9 负')", timeout=15000)
    time.sleep(0.1)
    check(page.evaluate('Boolean(window.__pbSawLoading)'), '切周期没有 loading 态')
    if page.evaluate('Boolean(window.__pbSawLoading)'):
        notes.append('[mock] 切周期出现 loading 态')
    text = body_text(page)
    check('本月赛训表现 · 对比上月同期' in text, '切到本月后副标题没变：' + page.locator('.pbr-sub').inner_text())
    check('本月 21 局 12 胜 9 负，胜率 57.1%，比上月同期少赢 3 局。' in text, '切到本月后战况句没变')
    check('本周 6 局 4 胜 2 负' not in text, '切周期后仍残留上一周期结论')
    check('12/21' in text, '切到本月后指标数字没跟着变')
    check(page.locator('[data-pbr-period="month"]').get_attribute('aria-pressed') == 'true',
          '切到本月后按钮没有高亮')
    check(mocker.seen and mocker.seen[-1]['period'] == 'month', '切周期没有重新请求 /api/briefing')
    page.screenshot(path=str(OUT / '30d-overview-month-mock-1440.png'), full_page=False)
    notes.append('[mock] 本月：' + page.locator('.pbr-sub').inner_text())

    # ── 4) 键盘可达：聚焦周期按钮按 Enter 切换 ──
    try:
        page.focus('[data-pbr-period="week"]')
        page.keyboard.press('Enter')
    except Exception:
        page.locator('[data-pbr-period="week"]').first.focus()
        page.keyboard.press('Enter')
    page.wait_for_timeout(700)
    # 第 4 轮加了全局 Enter 快捷键后，Enter 可能被复盘卡快捷键劫持（周期按钮失焦/跳对局）。
    hijacked = page.evaluate("() => location.hash.startsWith('#match/')")
    week_pressed = page.evaluate(
        "() => { const node = document.querySelector('[data-pbr-period=\"week\"]');"
        " return node ? node.getAttribute('aria-pressed') : null; }")
    check(not hijacked,
          '周期按钮的 Enter 被复盘卡快捷键劫持：hash 变成 '
          + str(page.evaluate('location.hash'))
          + '（period-brief.js 的 onDocumentKeyDown 未忽略 button/a 等交互元素）')
    check(week_pressed == 'true',
          '键盘 Enter 无法切换周期（本周）：aria-pressed=' + str(week_pressed))
    notes.append('[mock] 键盘 Enter 切换周期：'
                 + ('失败（被快捷键劫持，跳到 ' + str(page.evaluate('location.hash')) + '）'
                    if hijacked else '可用'))
    if hijacked:
        # 被劫持后页面已跳走，回首页继续后续用例
        page.goto(base + '/#overview', wait_until='load')
        wait_brief(page)

    # ── 5) 今日 0 局：空态 + 最近一批入口（不写全局筛选） ──
    mocker.seen.clear()
    page.click('[data-pbr-period="today"]')
    page.wait_for_selector('[data-pbr-root] .pbr-empty', timeout=15000)
    text = body_text(page)
    check('今日还没有对局' in text, '今日空态标题不对：' + text[:80])
    check('今日还没有登记对局。' in text, '空态没有保留后端给的原因')
    check('训练安排' in text, '空态缺少训练安排')
    check('待命名战队 #29' in text, '空态缺少下一场约训')
    check('查看最近一批（11-02 ~ 11-02）' in text, '空态缺少最近一批入口')
    check('本周 6 局 4 胜 2 负' not in text, '空态仍残留上一周期结论')
    check(not page.locator('.pbr-finding').count(), '空态仍渲染变化卡')
    page.screenshot(path=str(OUT / '30e-overview-today-empty-mock-1440.png'), full_page=False)
    notes.append('[mock] 今日空态 + 最近一批入口正常')
    page.click('[data-pbr-fallback]')
    page.wait_for_function("() => document.body.innerText.includes('自定义赛训表现')", timeout=15000)
    last = mocker.seen[-1] if mocker.seen else {}
    check(last.get('period') == 'custom' and last.get('from') == '2026-11-02' and last.get('to') == '2026-11-02',
          '「查看最近一批」没有切成 period=custom&from&to：' + json.dumps(last, ensure_ascii=False))
    saved = page.evaluate("JSON.parse(localStorage.getItem('training-rebuild-filters')||'{}')")
    check(not saved.get('from') and not saved.get('to'),
          '切周期污染了全局筛选：' + json.dumps(saved, ensure_ascii=False))
    notes.append(f'[mock] 最近一批 → custom 区间，全局筛选未被写入（{last.get("from")} ~ {last.get("to")}）')
    check(not errors, '周期切换/空态出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6) 全部对局：把本期区间交给对局页 ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    page.click('[data-pbr-all-games]')
    page.wait_for_function("() => location.hash === '#matches'", timeout=15000)
    check(page.evaluate('location.hash') == '#matches', '「全部对局」没有跳到 #matches')
    saved = page.evaluate("JSON.parse(localStorage.getItem('training-rebuild-filters')||'{}')")
    check(saved.get('from') == '2026-11-09' and saved.get('to') == '2026-11-15',
          '「全部对局」没有把本期区间写进筛选：' + json.dumps(saved, ensure_ascii=False))
    notes.append(f'[mock] 全部对局 → #matches，筛选 {saved.get("from")} ~ {saved.get("to")}')
    check(not errors, '对局页出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.5) 复盘区工具栏：排序弹层（开关/选项/计数/按钮文本/焦点/Esc/外部点击）+ 字段弹层（勾选/禁用/持久化/恢复默认/最少 1 项） ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)

    def active_is(selector):
        return page.evaluate("(sel) => document.activeElement === document.querySelector(sel)", selector)

    def ensure_sort_open():
        current = watch_state(page)
        if not (current and current['sortPop']['visible']):
            page.locator('[data-pbr-sort-toggle]').click()
            page.wait_for_timeout(200)

    def ensure_fields_open():
        current = watch_state(page)
        if not (current and current['fieldsPop']['visible']):
            page.locator('[data-pbr-fields-toggle]').click()
            page.wait_for_timeout(200)

    state = watch_state(page)
    check(state is not None, '复盘区没有渲染出来（工具栏用例）')
    if state and state['sortToggle'].get('exists'):
        # 1) 排序弹层：打开 → 10 个选项、aria-selected 唯一 → 选 deaths → 分组/计数/按钮文本同步、关闭、焦点回按钮
        ensure_sort_open()
        opened = watch_state(page)
        check(opened['sortToggle']['expanded'] == 'true', '点排序按钮后 aria-expanded 没有变 true')
        check(opened['sortPop']['visible'], '点排序按钮后排序弹层没有展开')
        check(len(opened['sortOptions']) == 10,
              '排序弹层应有 10 个字段选项，实际 ' + str(len(opened['sortOptions'])))
        selected = [item['id'] for item in opened['sortOptions'] if item['selected']]
        check(selected == ['deficit'], '排序弹层当前选中项应唯一（deficit）：' + str(selected))
        check(all(item['visible'] for item in opened['sortOptions']), '排序弹层选项没有全部可见')
        option_text = ' '.join(item['text'] for item in opened['sortOptions'])
        check('我方掉点' in option_text and '23 局' in option_text,
              '排序选项没带字段名与局数：' + option_text[:80])
        dim_options = [item for item in opened['sortOptions']
                       if item['contrast'] is not None and item['contrast'] < 2.5]
        check(not dim_options, '排序弹层选项文字对比度不足：'
              + json.dumps([{'id': item['id'], 'ratio': item['contrast']} for item in dim_options],
                           ensure_ascii=False))
        focus_watch_section(page)
        settle(page)
        page.screenshot(path=str(OUT / '31-watch-sort-pop-1440.png'), full_page=False)
        page.locator('[data-pbr-sort-option="deaths"]').click()
        page.wait_for_timeout(250)
        picked = watch_state(page)
        check(picked['visibleGroups'] == ['deaths'],
              '点排序选项后分组没切换：' + str(picked['visibleGroups']))
        check(picked['countText'] == '23 局',
              '区头计数没有跟着排序字段更新（deaths 后端 count 23 局）：' + picked['countText'])
        check(picked['sortToggle']['expanded'] == 'false', '选完排序项后弹层应收起')
        check(not picked['sortPop']['visible'], '选完排序项后弹层仍可见')
        check('我方掉点' in picked['sortToggle']['text'] and '23 局' in picked['sortToggle']['text'],
              '排序按钮文本没跟着更新：' + picked['sortToggle']['text'])
        check(active_is('[data-pbr-sort-toggle]'), '选完排序项后焦点没有回到排序按钮')
        check(picked['focusIds'] == ['deaths'],
              '排序字段（deaths）在显示集合里应高亮：' + str(picked['focusIds']))
        notes.append('[mock] 排序弹层选「我方掉点」→ ' + picked['sortToggle']['text'])

        # 2) Esc 关闭 + 焦点回按钮
        ensure_sort_open()
        check(watch_state(page)['sortPop']['visible'], '再次打开排序弹层失败')
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        escaped = watch_state(page)
        check(escaped['sortToggle']['expanded'] == 'false' and not escaped['sortPop']['visible'],
              'Esc 没有关闭排序弹层')
        check(active_is('[data-pbr-sort-toggle]'), 'Esc 关闭后焦点没有回到排序按钮')

        # 3) 点外部关闭
        ensure_sort_open()
        page.click('.pbr-summary')
        page.wait_for_timeout(200)
        outside = watch_state(page)
        check(outside['sortToggle']['expanded'] == 'false' and not outside['sortPop']['visible'],
              '点外部没有关闭排序弹层')
        notes.append('[mock] 排序弹层：Esc / 点外部可关闭，焦点回按钮')

        # 4) 切回默认排序字段 deficit
        ensure_sort_open()
        page.locator('[data-pbr-sort-option="deficit"]').click()
        page.wait_for_timeout(200)

    # 5) 字段弹层：默认 4 项、满 4 未选禁用；勾选/取消即时改卡片；localStorage；恢复默认；最少 1 项；reload 保持
    state = watch_state(page)
    fields_toggle = state['fieldsToggle'] if state else {'exists': False}
    check(fields_toggle.get('exists'), '缺少字段按钮 [data-pbr-fields-toggle]')
    if fields_toggle.get('exists'):
        ensure_fields_open()
        opened = watch_state(page)
        check(opened['fieldsPop']['visible'], '点字段按钮后字段弹层没有展开')
        check(opened['fieldsToggle']['expanded'] == 'true', '字段按钮 aria-expanded 没有变 true')
        check(len(opened['fieldOptions']) == 10,
              '字段弹层应有 10 个字段选项，实际 ' + str(len(opened['fieldOptions'])))
        check(sorted(opened['checkedIds']) == sorted(WATCH_DISPLAY_DEFAULT),
              '字段弹层默认应勾选 ' + str(WATCH_DISPLAY_DEFAULT) + '：' + str(opened['checkedIds']))
        check(len(opened['disabledIds']) == 6,
              '满 4 项时未选的 6 个应 disabled：' + str(opened['disabledIds']))
        check(all(card['count'] == 4 for card in opened['cards']),
              '默认所有卡都应渲染 4 项：' + str([card['count'] for card in opened['cards']]))
        dim_fields = [item for item in opened['fieldOptions']
                      if item['contrast'] is not None and item['contrast'] < 2.5]
        check(not dim_fields, '字段弹层选项文字对比度不足：'
              + json.dumps([{'id': item['id'], 'ratio': item['contrast']} for item in dim_fields],
                           ensure_ascii=False))
        focus_watch_section(page)
        settle(page)
        page.screenshot(path=str(OUT / '32-watch-fields-pop-1440.png'), full_page=False)

        # 取消 duration → 3 项：弹层保持打开、卡片数字即时变 3、未选不再禁用
        page.locator('[data-pbr-field-option="duration"]').click()
        page.wait_for_timeout(200)
        ensure_fields_open()
        un = watch_state(page)
        check(un['fieldsPop']['visible'], '勾选字段后弹层不应关闭')
        check(len(un['checkedIds']) == 3, '取消 duration 后应勾选 3 项：' + str(un['checkedIds']))
        check('duration' not in un['checkedIds'], 'duration 没有被取消')
        check(all(card['count'] == 3 for card in un['cards']),
              '取消字段后所有卡都应变 3：' + str([card['count'] for card in un['cards']]))
        check(not un['disabledIds'], '未满 4 项时不应有 disabled 选项：' + str(un['disabledIds']))
        stored = read_storage(page, 'pbr-watch-display-fields')
        check(isinstance(stored, list) and len(stored) == 3 and 'duration' not in stored,
              'localStorage 没写入 3 项：' + json.dumps(stored, ensure_ascii=False))

        # 勾 dragon → 4 项、卡片出现「关键龙丢失」
        page.locator('[data-pbr-field-option="dragon"]').click()
        page.wait_for_timeout(200)
        ensure_fields_open()
        full = watch_state(page)
        check(len(full['checkedIds']) == 4, '勾 dragon 后应 4 项：' + str(full['checkedIds']))
        labels = [item['label'] for card in full['cards'] for item in card['values']]
        check('关键龙丢失' in labels, '勾 dragon 后卡片没有「关键龙丢失」：' + str(labels[:12]))
        check(len(full['disabledIds']) == 6, '满 4 后未选字段应 disabled：' + str(full['disabledIds']))
        check(all(card['count'] == 4 for card in full['cards']),
              '满 4 后所有卡都应渲染 4 项：' + str([card['count'] for card in full['cards']]))
        check(full['focusIds'] == ['deficit'],
              '排序字段（deficit）在显示集合里时应高亮：' + str(full['focusIds']))
        stored = read_storage(page, 'pbr-watch-display-fields')
        check(isinstance(stored, list) and len(stored) == 4 and 'dragon' in stored,
              'localStorage 没写入 4 项：' + json.dumps(stored, ensure_ascii=False))

        # 满 4 时未选字段 disabled（点不动）：选择不变
        blocked = watch_state(page)
        check('gold' in blocked['disabledIds'],
              '满 4 后未选的 gold 应 disabled：' + str(blocked['disabledIds']))
        check(sorted(blocked['checkedIds']) == sorted(full['checkedIds']),
              '满 4 时选中集合不应变化：' + str(blocked['checkedIds']))
        check('gold' not in blocked['checkedIds'], '满 4 时不应把 gold 加进去')

        # 取消排序字段 deficit → 数字里没有它、is-focus 消失
        page.locator('[data-pbr-field-option="deficit"]').click()
        page.wait_for_timeout(200)
        ensure_fields_open()
        nofocus = watch_state(page)
        check(len(nofocus['checkedIds']) == 3, '取消 deficit 后应 3 项：' + str(nofocus['checkedIds']))
        check(nofocus['focusIds'] == [],
              '排序字段不在显示集合时不应有 is-focus：' + str(nofocus['focusIds']))
        labels = [item['label'] for item in nofocus['cards'][0]['values']]
        check('最多落后' not in labels, '取消 deficit 后卡片仍显示「最多落后」')
        compact_focus = [item for card in nofocus['cards'] for item in card['values']
                         if item['id'] == 'deficit']
        check(not compact_focus, '取消排序字段后所有卡都不应再显示 deficit')

        # 「恢复默认」→ 默认 4 项 + localStorage 默认
        reset = page.locator('[data-pbr-fields-pop] button', has_text='恢复默认')
        if not reset.count():
            reset = page.locator('.pbr-watch button', has_text='恢复默认')
        check(reset.count() >= 1, '字段弹层缺少「恢复默认」按钮')
        if reset.count():
            reset.first.click()
            page.wait_for_timeout(250)
        ensure_fields_open()
        reset_state = watch_state(page)
        check(sorted(reset_state['checkedIds']) == sorted(WATCH_DISPLAY_DEFAULT),
              '「恢复默认」没有回到默认 4 项：' + str(reset_state['checkedIds']))
        check(len(reset_state['disabledIds']) == 6, '恢复默认后满 4 应禁用未选项')
        stored = read_storage(page, 'pbr-watch-display-fields')
        check(sorted(stored or []) == sorted(WATCH_DISPLAY_DEFAULT),
              '「恢复默认」没有把 localStorage 写回默认：' + json.dumps(stored, ensure_ascii=False))
        notes.append('[mock] 字段弹层：勾选/禁用/恢复默认 normal')

        # 最少 1 项：取消到只剩 1 项，再点最后 1 项仍保持 1
        for field_id in ('duration', 'at10', 'deaths'):
            ensure_fields_open()
            page.locator(f'[data-pbr-field-option="{field_id}"]').click()
            page.wait_for_timeout(120)
        ensure_fields_open()
        one = watch_state(page)
        check(len(one['checkedIds']) == 1,
              '最少 1 项：应能取消到只剩 1 项：' + str(one['checkedIds']))
        check(all(card['count'] == 1 for card in one['cards']),
              '只剩 1 项时所有卡都应渲染 1 项：' + str([card['count'] for card in one['cards']]))
        last_id = one['checkedIds'][0]
        check(last_id in one['disabledIds'],
              '最少 1 项：最后 1 个已选项应 disabled：' + str(one['disabledIds']))
        page.locator(f'[data-pbr-field-option="{last_id}"]').click(force=True)
        page.wait_for_timeout(150)
        still = watch_state(page)
        check(len(still['checkedIds']) == 1,
              '最少 1 项：最后 1 项不应被取消：' + str(still['checkedIds']))
        notes.append('[mock] 字段弹层：最少 1 项生效')

        # Esc 关闭字段弹层 + 焦点回按钮
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        escaped_fields = watch_state(page)
        check(escaped_fields['fieldsToggle']['expanded'] == 'false'
              and not escaped_fields['fieldsPop']['visible'], 'Esc 没有关闭字段弹层')
        check(active_is('[data-pbr-fields-toggle]'), 'Esc 关闭字段弹层后焦点没有回到字段按钮')

        # reload 后保持：先恢复默认再改成 2 项（deficit + deaths）
        ensure_fields_open()
        reset_btn = page.locator('[data-pbr-fields-pop] button', has_text='恢复默认')
        if reset_btn.count():
            reset_btn.first.click()
            page.wait_for_timeout(250)
        ensure_fields_open()
        page.locator('[data-pbr-field-option="duration"]').click()
        page.wait_for_timeout(150)
        ensure_fields_open()
        page.locator('[data-pbr-field-option="at10"]').click()
        page.wait_for_timeout(200)
        stored = read_storage(page, 'pbr-watch-display-fields')
        check(isinstance(stored, list) and len(stored) == 2,
              'reload 前应写入 2 项：' + json.dumps(stored, ensure_ascii=False))
        expected_display = sorted(stored) if isinstance(stored, list) else []
        page.reload(wait_until='load')
        wait_brief(page)
        reloaded = watch_state(page)
        check(sorted(reloaded['checkedIds']) == expected_display,
              'reload 后字段选择没有保持：' + str(reloaded['checkedIds']))
        check(all(card['count'] == 2 for card in reloaded['cards']),
              'reload 后所有卡都应渲染 2 项：' + str([card['count'] for card in reloaded['cards']]))
        notes.append('[mock] 字段弹层：localStorage 持久化 reload 保持 → '
                     + json.dumps(stored, ensure_ascii=False))
    check(not errors, '复盘区工具栏/弹层出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.7) 指标大数字按等级配色：lead / mid / behind 三类都有，颜色与 .pbr-rank 同色 ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    metrics = metric_tiers(page)
    check(len(metrics) == 8, '指标应为 8 项：' + str(len(metrics)))
    ranked = [item for item in metrics if item['hasRank']]
    check(len(ranked) == 6, '带排名的指标应有 6 项：' + str(len(ranked)))
    for tier in ('lead', 'mid', 'behind'):
        items = [item for item in ranked if item['tier'] == tier]
        check(len(items) >= 1, '指标缺少 ' + tier + ' 等级：'
              + json.dumps([{'label': item['label'], 'tier': item['tier']} for item in ranked],
                           ensure_ascii=False))
        for item in items:
            check(item['valueClasses'] == ['is-' + tier],
                  '指标「%s」大数字 class 应为 is-%s，实际 %s'
                  % (item['label'], tier, item['valueClasses']))
            check(item['valueColor'] == item['rankColor'],
                  '指标「%s」大数字颜色 %s 与 .pbr-rank 的 %s 不一致'
                  % (item['label'], item['valueColor'], item['rankColor']))
    for item in metrics:
        if item['hasRank']:
            continue
        check(not item['valueClasses'],
              '无排名指标不应上色：%s %s' % (item['label'], item['valueClasses']))
    settle(page)
    page.screenshot(path=str(OUT / '30f-metrics-tiers-1440.png'), full_page=False)
    notes.append('[mock] 指标等级配色：' + json.dumps(
        [{'label': item['label'], 'tier': item['tier']} for item in ranked], ensure_ascii=False))
    check(not errors, '指标配色出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.8) 重点发现：不限条数 + 区块内上下滚动 + 关注（变色/置顶/时间/localStorage/reload/取消）──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    state = findings_state(page)
    check(state['exists'], '发现区列表没有渲染')
    check(len(state['rows']) == 6, '发现区应渲染全部 6 条（不截 3 条）：' + str(len(state['rows'])))
    check(state['overflowY'] in ('auto', 'scroll'),
          '发现区应是区块内滚动容器（overflow-y:auto），实际 ' + str(state['overflowY']))
    check(state['scrollHeight'] > state['clientHeight'] + 1,
          '发现 6 条时应出现内部滚动：scrollHeight=%s clientHeight=%s'
          % (state['scrollHeight'], state['clientHeight']))
    check(state['focusable'], '发现区滚动容器应可键盘聚焦（tabindex=0）')
    check(state['favCount'] == 6, '每条发现都应有 [data-pbr-fav-finding] 关注按钮：' + str(state['favCount']))
    check(all(row['hasFavButton'] for row in state['rows']), '有发现行缺少关注按钮')
    if state['favCount'] == 6 and len(state['rows']) == 6:
        ids_in_order = [row['id'] for row in state['rows']]
        first_id = ids_in_order[0]
        target = ids_in_order[2]
        set_scroll(page, '.pbr-findings:not(.pbr-watch) .pbr-finding-list', 120)
        page.wait_for_timeout(120)
        settle(page)
        page.screenshot(path=str(OUT / '40-findings-scroll-1440.png'), full_page=False)
        before_scroll = findings_state(page)['scrollTop']
        page.locator(f'[data-pbr-fav-finding="{target}"]').click()
        page.wait_for_timeout(300)
        fav = findings_state(page)
        check(fav['rows'][0]['id'] == target,
              '关注的发现应排到第一条：' + str([row['id'] for row in fav['rows']]))
        check(fav['rows'][0]['isFav'], '关注的发现行应加 is-fav')
        check('已关注' in fav['rows'][0]['favText'],
              '关注按钮文案应变成「已关注 · 时间」：' + fav['rows'][0]['favText'])
        check(bool(re.search(r'\d{2}-\d{2} \d{2}:\d{2}', fav['rows'][0]['favText'])),
              '关注时间格式应为 MM-DD HH:mm：' + fav['rows'][0]['favText'])
        stored = read_storage(page, 'pbr-finding-favs')
        check(isinstance(stored, dict) and target in stored and 'T' in str(stored[target]),
              'localStorage[pbr-finding-favs] 没写入 ISO 时间：'
              + json.dumps(stored, ensure_ascii=False))
        check(abs(fav['scrollTop'] - before_scroll) <= 8,
              '关注后上下滚动位置跳了：%s → %s' % (before_scroll, fav['scrollTop']))
        focused = page.evaluate(
            "() => document.activeElement ? document.activeElement.getAttribute('data-pbr-fav-finding') : null")
        check(focused == target, '关注后焦点没有留在同一个关注按钮：' + str(focused))
        normal_row = next((row for row in fav['rows'] if not row['isFav']), None)
        fav_row = fav['rows'][0]
        # 色带实现可能是 border-left 也可能是 inset box-shadow；只要与普通行不同即算「边框上颜色」
        banded = (fav_row['boxShadow'] != (normal_row and normal_row['boxShadow'])
                  or fav_row['borderLeftColor'] != (normal_row and normal_row['borderLeftColor'])
                  or fav_row['backgroundColor'] != (normal_row and normal_row['backgroundColor']))
        check(banded, '关注行缺少左侧 accent 色带/浅底：box-shadow=%s bg=%s'
              % (fav_row['boxShadow'], fav_row['backgroundColor']))
        # 截图时滚回顶部，让「关注置顶行（变色+已关注时间）」入镜
        set_scroll(page, '.pbr-findings:not(.pbr-watch) .pbr-finding-list', 0)
        page.wait_for_timeout(150)
        settle(page)
        page.screenshot(path=str(OUT / '41-findings-fav-1440.png'), full_page=False)
        notes.append('[mock] 发现关注：' + target + ' → 第一条（' + fav['rows'][0]['favText'] + '）')
        # reload 保持
        page.reload(wait_until='load')
        wait_brief(page)
        reloaded = findings_state(page)
        check(reloaded['rows'][0]['id'] == target, 'reload 后关注的发现没有保持置顶')
        check(reloaded['rows'][0]['isFav'] and '已关注' in reloaded['rows'][0]['favText'],
              'reload 后关注态/时间丢失')
        # 取消关注 → 恢复原顺序
        page.locator(f'[data-pbr-fav-finding="{target}"]').click()
        page.wait_for_timeout(300)
        unfav = findings_state(page)
        check(unfav['rows'][0]['id'] == first_id,
              '取消关注后应恢复原顺序（第一条应回到 %s）：%s'
              % (first_id, [row['id'] for row in unfav['rows']]))
        check(not any(row['isFav'] for row in unfav['rows']), '取消关注后不应有 is-fav 行')
        stored = read_storage(page, 'pbr-finding-favs')
        check(not isinstance(stored, dict) or target not in stored,
              '取消关注后 localStorage 应删掉该 id：'
              + json.dumps(stored, ensure_ascii=False))
        notes.append('[mock] 发现关注：reload 保持 / 取消恢复顺序')
    check(not errors, '发现区关注出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.9) 复盘比赛：不限条数 + 横向滑动 + 左右箭头 + 关注（同 key 跨分组共享）──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    shared_key = 'channel-mock-a'   # game a 出现在所有分组
    state = watch_hscroll_state(page)
    check(state and state['scroller'], '复盘分组应是横向滚动容器（scrollWidth > clientWidth）')
    check(state and state['cardCount'] == 5,
          '每个分组应渲染 5 张卡（不截 3 张）：' + str(state and state['cardCount']))
    check(state and all(card['hasFavButton'] for card in state['cards']), '有复盘卡缺少关注按钮')
    check(state and any(card['key'] == shared_key for card in state['cards']),
          '默认分组应包含用于跨组共享关注的 game key：' + shared_key)
    check(state and state['prev']['exists'] and state['next']['exists'],
          '区头缺少左右滚动箭头 [data-pbr-watch-prev/next]')
    check(state and state['prev']['disabled'], '初始在最左端时 ‹ 应 disabled')
    check(state and not state['next']['disabled'], '有溢出时 › 应可用')
    # count(17) > 实际列出(5) 时，横向轨道末尾应有一行「共 17 局 · 已列前 5 局」
    tail_text = page.evaluate("""() => {
      const node = document.querySelector('.pbr-watch .pbr-rail-tail');
      return node ? (node.textContent || '').replace(/\\s+/g, ' ').trim() : '';
    }""")
    check(bool(tail_text), 'count 大于列出条数时轨道末尾应有 .pbr-rail-tail 说明')
    check('共 17 局' in tail_text and '已列前 5 局' in tail_text,
          '轨道末尾应写「共 17 局 · 已列前 5 局」：' + tail_text)
    focus_watch_section(page)
    settle(page)
    page.screenshot(path=str(OUT / '42-watch-hscroll-1440.png'), full_page=False)
    if state and state['scroller']:
        # 点 › 向右滚一屏
        before_left = state['scroller']['scrollLeft']
        next_button = arrow_locator(page, 'next')
        check(next_button is not None, '找不到 › 滚动按钮')
        if next_button is not None:
            next_button.click()
            page.wait_for_timeout(450)
            scrolled = watch_hscroll_state(page)
            check(scrolled['scroller']['scrollLeft'] > before_left + 10,
                  '点 › 后没有向右滚动：%s → %s'
                  % (before_left, scrolled['scroller']['scrollLeft']))
            # 一直滚到最右：› disabled、‹ 可用
            for _ in range(8):
                button = arrow_locator(page, 'next')
                if button is None or button.is_disabled():
                    break
                button.click()
                page.wait_for_timeout(450)
            at_end = watch_hscroll_state(page)
            span = at_end['scroller']['scrollWidth'] - at_end['scroller']['clientWidth']
            check(at_end['scroller']['scrollLeft'] >= span - 6,
                  '没有滚到最右端：scrollLeft=%s span=%s'
                  % (at_end['scroller']['scrollLeft'], span))
            check(at_end['next']['disabled'], '滚到最右端后 › 应 disabled')
            check(not at_end['prev']['disabled'], '最右端时 ‹ 应可用')
            settle(page)
            page.screenshot(path=str(OUT / '42b-watch-rail-tail-1440.png'), full_page=False)
            # 回到最左：‹ disabled
            for _ in range(10):
                button = arrow_locator(page, 'prev')
                if button is None or button.is_disabled():
                    break
                button.click()
                page.wait_for_timeout(450)
            at_start = watch_hscroll_state(page)
            check(at_start['scroller']['scrollLeft'] <= 4,
                  '没有回到最左端：' + str(at_start['scroller']['scrollLeft']))
            check(at_start['prev']['disabled'], '回到最左端后 ‹ 应 disabled')
        # 关注第一张卡（game a）：横向位置保持
        state = watch_hscroll_state(page)
        before_left = state['scroller']['scrollLeft']
        page.locator('.pbr-watch [data-pbr-watch-group]:not([hidden]) '
                    f'[data-pbr-fav-watch="{shared_key}"]').click()
        page.wait_for_timeout(350)
        fav = watch_hscroll_state(page)
        check(fav['cards'][0]['key'] == shared_key, '关注的复盘卡应排到组内第一张：'
              + str([card['key'] for card in fav['cards']]))
        check(fav['cards'][0]['isFav'], '关注的复盘卡应加 is-fav')
        check('已关注' in fav['cards'][0]['favText'],
              '复盘卡关注文案应含「已关注」：' + fav['cards'][0]['favText'])
        check(bool(re.search(r'\d{2}-\d{2} \d{2}:\d{2}', fav['cards'][0]['favText'])),
              '复盘卡关注时间格式应为 MM-DD HH:mm：' + fav['cards'][0]['favText'])
        check(fav['cards'][0]['borderColor'] != state['cards'][0]['borderColor'],
              '关注卡边框应变色：%s → %s'
              % (state['cards'][0]['borderColor'], fav['cards'][0]['borderColor']))
        stored = read_storage(page, 'pbr-watch-favs')
        check(isinstance(stored, dict) and shared_key in stored and 'T' in str(stored[shared_key]),
              'localStorage[pbr-watch-favs] 没写入 ISO 时间：'
              + json.dumps(stored, ensure_ascii=False))
        check(abs(fav['scroller']['scrollLeft'] - before_left) <= 8,
              '关注卡片后横向滚动位置跳了：%s → %s'
              % (before_left, fav['scroller']['scrollLeft']))
        settle(page)
        page.screenshot(path=str(OUT / '43-watch-fav-1440.png'), full_page=False)
        notes.append('[mock] 复盘关注：' + shared_key + ' 置顶（' + fav['cards'][0]['favText'] + '）')
        # reload 后切到 deaths 分组：同一 game key 在其它分组也关注 + 置顶
        page.reload(wait_until='load')
        wait_brief(page)
        page.locator('[data-pbr-sort-toggle]').click()
        page.wait_for_timeout(250)
        page.locator('[data-pbr-sort-option="deaths"]').click()
        page.wait_for_timeout(350)
        shared = watch_hscroll_state(page)
        check(shared['group'] == 'deaths', '没有切到 deaths 分组：' + str(shared['group']))
        check(shared['cards'] and shared['cards'][0]['key'] == shared_key,
              '同一局在其它分组也应置顶关注：' + str([card['key'] for card in shared['cards'][:3]]))
        check(shared['cards'][0]['isFav'], '同一局在其它分组丢失关注态')
        # 取消关注 → 同 key 各分组都取消
        page.locator('.pbr-watch [data-pbr-watch-group]:not([hidden]) '
                    f'[data-pbr-fav-watch="{shared_key}"]').click()
        page.wait_for_timeout(350)
        unfav = watch_hscroll_state(page)
        check(not any(card['isFav'] for card in unfav['cards']),
              '取消关注后不应再有 is-fav 卡')
        stored = read_storage(page, 'pbr-watch-favs')
        check(not isinstance(stored, dict) or shared_key not in stored,
              '取消关注后 localStorage 应删掉该 key：'
              + json.dumps(stored, ensure_ascii=False))
        notes.append('[mock] 复盘关注：同 key 跨分组共享 / 取消生效')
    check(not errors, '复盘横滑/关注出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.10) 周期：6 个按钮 +「最近 5 场 / 最近 3 天」（请求参数、标题、不写全局筛选）──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    buttons = period_state(page)
    check([item['kind'] for item in buttons] == ['today', 'week', 'month', 'recent', 'days', 'custom'],
          '周期按钮应为 今日/本周/本月/近5场/近3天/自定义 六个：' + str([item['kind'] for item in buttons]))
    by_kind = {item['kind']: item for item in buttons}
    recent_label = by_kind['recent']['label'].replace(' ', '')
    days_label = by_kind['days']['label'].replace(' ', '')
    check('近5场' in recent_label, '「近5场」按钮文案不对：' + by_kind['recent']['label'])
    check('近3天' in days_label, '「近3天」按钮文案不对：' + by_kind['days']['label'])
    check(by_kind['week']['pressed'], '默认应高亮「本周」')
    mocker.seen.clear()
    check(page.locator('[data-pbr-period="recent"]').count() == 1, '缺少「近5场」周期按钮')
    if page.locator('[data-pbr-period="recent"]').count() == 1:
        page.locator('[data-pbr-period="recent"]').click()
        try:
            page.wait_for_function("() => document.body.innerText.includes('最近 5 场')", timeout=15000)
        except Exception:
            pass
    last = mocker.seen[-1] if mocker.seen else {}
    check(last.get('period') == 'recent' and last.get('n') == '5',
          '「近5场」请求参数不对：' + json.dumps(last, ensure_ascii=False))
    text = body_text(page)
    check('最近 5 场赛训表现' in text, '「近5场」副标题不对：' + page.locator('.pbr-sub').inner_text())
    check('最近 5 场 4 胜 1 负' in text, '「近5场」战况句没跟着变')
    check(page.locator('[data-pbr-period="recent"]').get_attribute('aria-pressed') == 'true',
          '「近5场」按钮没有高亮')
    check('本周 6 局 4 胜 2 负，胜率 66.7%，比上周同期少赢 1 局。' not in text,
          '切「近5场」后仍残留本周战况句')
    settle(page)
    page.screenshot(path=str(OUT / '40-period-recent-1440.png'), full_page=False)
    notes.append('[mock] 周期「近5场」→ period=recent&n=5')
    mocker.seen.clear()
    check(page.locator('[data-pbr-period="days"]').count() == 1, '缺少「近3天」周期按钮')
    if page.locator('[data-pbr-period="days"]').count() == 1:
        page.locator('[data-pbr-period="days"]').click()
        try:
            page.wait_for_function("() => document.body.innerText.includes('最近 3 天')", timeout=15000)
        except Exception:
            pass
    last = mocker.seen[-1] if mocker.seen else {}
    check(last.get('period') == 'days' and last.get('days') == '3',
          '「近3天」请求参数不对：' + json.dumps(last, ensure_ascii=False))
    text = body_text(page)
    check('最近 3 天 3 局 3 胜' in text, '「近3天」战况句没跟着变')
    saved = page.evaluate("JSON.parse(localStorage.getItem('training-rebuild-filters')||'{}')")
    check(not saved.get('from') and not saved.get('to'),
          '切新周期污染了全局筛选：' + json.dumps(saved, ensure_ascii=False))
    settle(page)
    page.screenshot(path=str(OUT / '40b-period-days-1440.png'), full_page=False)
    notes.append('[mock] 周期「近3天」→ period=days&days=3，未写全局筛选')
    check(not errors, '新周期出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.11) 复盘卡关键时间点：0-3 个、按时间升序、clock 格式、点击与卡片主链接一致 ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    moments = moments_state(page)
    check(moments is not None and moments['group'] == 'deficit',
          '默认应显示 deficit 分组：' + str(moments and moments['group']))
    cards = moments['cards'] if moments else []
    card_a = next((card for card in cards if card['key'] == 'channel-mock-a'), None)
    check(card_a is not None, '默认分组应包含 game a 的复盘卡')
    if card_a:
        check(len(card_a['moments']) == 3, 'game a 应有 3 个时间点：' + str(len(card_a['moments'])))
        clocks = [item['clock'] for item in card_a['moments']]
        check(clocks == ['10:00', '20:00', '28:11'],
              '时间点应按时间升序且 clock 正确：' + str(clocks))
        check(all(re.match(r'^\d{1,2}:\d{2}$', item['clock'] or '') for item in card_a['moments']),
              '时间点 clock 应匹配 ^MM:SS$：' + str([item['clock'] for item in card_a['moments']]))
        check(all(item['label'] for item in card_a['moments']),
              '时间点应带 label：' + str([item['label'] for item in card_a['moments']]))
        check(all(item['visible'] for item in card_a['moments']),
              '时间点 chips 被容器裁掉了：'
              + str([(item['clock'], item['visible']) for item in card_a['moments']]))
        check(all(item['href'] == card_a['mainHref'] and item['href'].startswith('#match/')
                  for item in card_a['moments']),
              '时间点链接应与卡片主链接一致：%s vs %s'
              % ([item['href'] for item in card_a['moments']], card_a['mainHref']))
    card_b = next((card for card in cards if card['key'] == 'channel-mock-b'), None)
    check(card_b is not None and len(card_b['moments']) == 1 and card_b['hasContainer'],
          '非首卡也应渲染时间点（b 有 1 个）')
    focus_watch_section(page)
    settle(page)
    page.screenshot(path=str(OUT / '41-watch-moments-1440.png'), full_page=False)
    # 空 moments 不渲染：切到 deaths 分组，game c 没有时间点
    page.locator('[data-pbr-sort-toggle]').click()
    page.wait_for_timeout(250)
    page.locator('[data-pbr-sort-option="deaths"]').click()
    page.wait_for_timeout(350)
    death_moments = moments_state(page)
    card_c = next((card for card in (death_moments or {}).get('cards', [])
                   if card['key'] == 'channel-mock-c'), None)
    check(card_c is not None, 'deaths 分组应包含 game c 的卡片')
    check(card_c and not card_c['hasContainer'] and not card_c['moments'],
          '空 moments 不应渲染时间点容器：%s' % (card_c and card_c['moments']))
    notes.append('[mock] 时间点：a=3 个升序 / b=1 / c 空；链接与主链接一致')
    check(not errors, '时间点出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.12) 关注工作流：关注 → 已复盘 → 结论（Enter 保存 / Esc 取消）→ localStorage 新结构 / 迁移 / reload ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    base_state = fav_workflow_state(page)
    check(base_state['exportButton']['exists'], '发现区缺少「导出清单」按钮')
    check(base_state['exportButton']['disabled'], '无关注项时导出按钮应 disabled')
    check(all(not item['review']['exists'] and not item['noteButton']['exists']
              for item in base_state['findings']),
          '未关注时不应出现「已复盘 / ＋结论」')
    target = base_state['findings'][1]['key'] if len(base_state['findings']) > 1 else None
    check(target is not None, '发现区行数不足，无法测关注工作流')
    if target:
        page.locator(f'[data-pbr-fav-finding="{target}"]').click()
        page.wait_for_timeout(300)
        fav_state = fav_workflow_state(page)
        row = fav_state['findings'][0]
        check(row['key'] == target and row['isFav'], '关注后发现行应置顶且 is-fav：' + str(row['key']))
        check(row['review']['exists'] and row['review']['pressed'] is False,
              '关注后应出现「已复盘」切换且默认未复盘')
        check(row['noteButton']['exists'], '关注后应出现「＋结论」按钮')
        check(fav_state['exportButton']['disabled'] is False, '有关注项后导出按钮应可用')
        data = read_storage(page, 'pbr-finding-favs')
        check(isinstance(data, dict) and isinstance(data.get(target), dict)
              and {'at', 'reviewedAt', 'note'} <= set(data[target]),
              '收藏结构应升级为 {at, reviewedAt, note}：' + json.dumps(data, ensure_ascii=False))
        if isinstance(data, dict) and isinstance(data.get(target), dict):
            check(data[target]['reviewedAt'] in (None, '') and data[target]['note'] == '',
                  '新关注的 reviewedAt 应为空（null 或 ""）、note 为空：'
                  + json.dumps(data[target], ensure_ascii=False))
        # 已复盘切换（前端未实现时先记失败、不超时）
        review_btn = page.locator(f'[data-pbr-fav-review="{target}"]')
        check(review_btn.count() >= 1, '关注后缺少「已复盘」按钮 [data-pbr-fav-review]')
        if review_btn.count() >= 1:
            review_btn.first.click()
        page.wait_for_timeout(250)
        marked = fav_workflow_state(page)['findings'][0]
        check(marked['review']['pressed'] and marked['review']['on'], '点「已复盘」后应选中')
        check('已复盘' in marked['review']['text'], '已复盘按钮文案不对：' + marked['review']['text'])
        data = read_storage(page, 'pbr-finding-favs')
        check(isinstance(data.get(target), dict) and data[target]['reviewedAt'],
              '已复盘应写入 reviewedAt：' + json.dumps(data, ensure_ascii=False))
        # 可取消再恢复
        page.locator(f'[data-pbr-fav-review="{target}"]').click()
        page.wait_for_timeout(200)
        check(not fav_workflow_state(page)['findings'][0]['review']['pressed'], '再点应取消已复盘')
        page.locator(f'[data-pbr-fav-review="{target}"]').click()
        page.wait_for_timeout(200)
        # ＋结论：Enter 保存
        note_btn = page.locator(f'[data-pbr-fav-note="{target}"]')
        check(note_btn.count() >= 1, '关注后缺少「＋结论」按钮 [data-pbr-fav-note]')
        if note_btn.count() >= 1:
            note_btn.first.click()
        page.wait_for_timeout(200)
        note_input = page.locator('[data-pbr-note-input]')
        check(note_input.count() == 1 and note_input.first.is_visible(),
              '点「＋结论」应出现单行输入框')
        if note_input.count():
            note_input.first.fill('这局开局太拖')
            page.keyboard.press('Enter')
            page.wait_for_timeout(300)
        noted = fav_workflow_state(page)['findings'][0]
        check(noted['noteText']['exists'] and '这局开局太拖' in noted['noteText']['text'],
              '结论应显示为 muted 文本：' + str(noted['noteText']))
        data = read_storage(page, 'pbr-finding-favs')
        check(isinstance(data.get(target), dict) and data[target]['note'] == '这局开局太拖',
              '结论应写入 localStorage：' + json.dumps(data, ensure_ascii=False))
        # Esc 取消不写
        if note_btn.count() >= 1:
            page.locator(f'[data-pbr-fav-note="{target}"]').click()
        page.wait_for_timeout(200)
        note_input = page.locator('[data-pbr-note-input]')
        if note_input.count():
            note_input.first.fill('不该保存')
            page.keyboard.press('Escape')
            page.wait_for_timeout(250)
        data = read_storage(page, 'pbr-finding-favs')
        check(isinstance(data.get(target), dict) and data[target]['note'] == '这局开局太拖',
              'Esc 取消不应改写结论：' + json.dumps(data, ensure_ascii=False))
        settle(page)
        page.screenshot(path=str(OUT / '42-finding-fav-workflow-1440.png'), full_page=False)
        notes.append('[mock] 发现关注工作流：已复盘/结论(Enter 保存, Esc 取消)/新结构写入')
        # reload 保持 + 旧 ISO 字符串迁移
        page.reload(wait_until='load')
        wait_brief(page)
        reloaded = fav_workflow_state(page)['findings'][0]
        check(reloaded['key'] == target and reloaded['isFav'], 'reload 后关注态丢失')
        check(reloaded['review']['pressed'] and '这局开局太拖' in reloaded['noteText']['text'],
              'reload 后已复盘/结论丢失')
        page.evaluate("(key) => localStorage.setItem('pbr-finding-favs',"
                      " JSON.stringify({[key]: '2026-11-13T10:00:00'}))", target)
        page.reload(wait_until='load')
        wait_brief(page)
        migrated = read_storage(page, 'pbr-finding-favs')
        check(isinstance(migrated.get(target), dict)
              and migrated[target]['at'] == '2026-11-13T10:00:00'
              and migrated[target]['reviewedAt'] in (None, '')
              and migrated[target]['note'] == '',
              '旧 ISO 字符串应迁移为 {at, reviewedAt, note}：' + json.dumps(migrated, ensure_ascii=False))
        notes.append('[mock] 关注工作流：reload 保持 / 旧 ISO 迁移')
    check(not errors, '关注工作流出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.13) 顶部三态视图「全部/关注/待复盘」：只过滤渲染、不重新取数、持久化 ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    modes = fav_workflow_state(page)['viewButtons']
    check([item['mode'] for item in modes] == ['all', 'fav', 'todo'],
          '视图控件应为 全部/关注/待复盘 三态：' + str([item['mode'] for item in modes]))
    check(fav_workflow_state(page)['viewMode'] == 'all', '默认视图应为「全部」')
    finding_key = fav_workflow_state(page)['findings'][0]['key']
    page.locator(f'[data-pbr-fav-finding="{finding_key}"]').click()
    page.wait_for_timeout(250)
    page.locator('[data-pbr-fav-watch]').first.click()
    page.wait_for_timeout(250)
    if page.locator(f'[data-pbr-fav-review="{finding_key}"]').count():
        page.locator(f'[data-pbr-fav-review="{finding_key}"]').click()
    else:
        check(False, '关注后缺少「已复盘」按钮（三态视图用例）')
    page.wait_for_timeout(250)
    mocker.seen.clear()
    check(page.locator('[data-pbr-view-mode]').count() == 3,
          '三态视图控件缺失（应 3 个按钮）：' + str(page.locator('[data-pbr-view-mode]').count()))
    if page.locator('[data-pbr-view-mode="fav"]').count():
        page.locator('[data-pbr-view-mode="fav"]').click()
    else:
        check(False, '缺少「关注」视图按钮')
    page.wait_for_timeout(300)
    fav_view = fav_workflow_state(page)
    check(fav_view['viewMode'] == 'fav', '切「关注」视图失败：' + str(fav_view['viewMode']))
    check(len(fav_view['findings']) == 1 and fav_view['findings'][0]['key'] == finding_key,
          '关注视图发现区应只剩关注项：' + str([item['key'] for item in fav_view['findings']]))
    check(len(fav_view['watch']) == 1, '关注视图复盘区应只剩关注卡：' + str(len(fav_view['watch'])))
    check(not mocker.seen, '切换视图不应重新请求 /api/briefing：' + json.dumps(mocker.seen, ensure_ascii=False))
    check(read_storage(page, 'pbr-view-mode') == 'fav', '视图选择应持久化到 localStorage')
    settle(page)
    page.screenshot(path=str(OUT / '43-view-fav-1440.png'), full_page=False)
    if page.locator('[data-pbr-view-mode="todo"]').count():
        page.locator('[data-pbr-view-mode="todo"]').click()
    else:
        check(False, '缺少「待复盘」视图按钮')
    page.wait_for_timeout(300)
    todo_view = fav_workflow_state(page)
    check(todo_view['viewMode'] == 'todo', '切「待复盘」视图失败')
    check(len(todo_view['findings']) == 0,
          '待复盘视图应排除已复盘发现：' + str([item['key'] for item in todo_view['findings']]))
    check(len(todo_view['watch']) == 1, '待复盘视图应保留未复盘关注卡：' + str(len(todo_view['watch'])))
    check(todo_view['watchCountText'] == '1 局',
          '待复盘视图区头计数应为匹配条数（1 局）：' + todo_view['watchCountText'])
    check(not mocker.seen, '切换「待复盘」不应重新请求接口')
    settle(page)
    page.screenshot(path=str(OUT / '44-view-todo-1440.png'), full_page=False)
    if page.locator('[data-pbr-view-mode="all"]').count():
        page.locator('[data-pbr-view-mode="all"]').click()
    page.wait_for_timeout(300)
    all_view = fav_workflow_state(page)
    check(len(all_view['findings']) == 6 and len(all_view['watch']) == 5,
          '回「全部」视图应恢复全部条目：发现 %d / 复盘 %d'
          % (len(all_view['findings']), len(all_view['watch'])))
    notes.append('[mock] 三态视图：关注/待复盘过滤 + 计数 + 不重取数 + 持久化')
    check(not errors, '三态视图出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.14) 忽略发现：「忽略」→ 隐藏 + localStorage + 区头「已忽略 N 条 · 恢复」；三视图都隐藏 ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    state = fav_workflow_state(page)
    ids = [item['key'] for item in state['findings']]
    check(state['ignoreButtons'] == len(ids), '每条发现都应有「忽略」按钮：%s vs %s'
          % (state['ignoreButtons'], len(ids)))
    ignore_target = ids[0] if ids else ''
    check(state['ignoreButtons'] == len(ids) and bool(ids), '忽略按钮缺失，跳过忽略交互')
    if state['ignoreButtons'] == len(ids) and ids:
        page.locator(f'[data-pbr-ignore-finding="{ignore_target}"]').click()
    page.wait_for_timeout(300)
    ignored = fav_workflow_state(page)
    check(ignore_target not in [item['key'] for item in ignored['findings']],
          '忽略后该行应从 DOM 消失')
    check(ignored['restoreIgnored']['exists'] and '已忽略 1 条' in ignored['restoreIgnored']['text'],
          '区头应出现「已忽略 N 条 · 恢复」：' + str(ignored['restoreIgnored']))
    settle(page)
    page.screenshot(path=str(OUT / '45-ignore-hidden-1440.png'), full_page=False)
    stored = read_storage(page, 'pbr-finding-ignored')
    check(isinstance(stored, dict) and ignore_target in stored,
          'pbr-finding-ignored 没写入：' + json.dumps(stored, ensure_ascii=False))
    check(ignore_target not in [i['key'] for i in fav_workflow_state(page)['findings']],
          '忽略项不应出现在全部视图')
    if page.locator('[data-pbr-view-mode="fav"]').count():
        page.locator('[data-pbr-view-mode="fav"]').click()
        page.wait_for_timeout(300)
        check(ignore_target not in [i['key'] for i in fav_workflow_state(page)['findings']],
              '忽略项不应出现在关注视图')
    if page.locator('[data-pbr-view-mode="all"]').count():
        page.locator('[data-pbr-view-mode="all"]').click()
        page.wait_for_timeout(250)
    if page.locator('[data-pbr-restore-ignored]').count():
        page.locator('[data-pbr-restore-ignored]').click()
    page.wait_for_timeout(300)
    restored = fav_workflow_state(page)
    check(len(restored['findings']) == len(ids), '恢复后忽略项应全部回来：%s vs %s'
          % (len(restored['findings']), len(ids)))
    check(not restored['restoreIgnored']['exists'], '恢复后不应再显示「已忽略」')
    settle(page)
    page.screenshot(path=str(OUT / '45b-ignore-restored-1440.png'), full_page=False)
    notes.append('[mock] 忽略：隐藏/持久化/三视图不显示/一键恢复')
    check(not errors, '忽略功能出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.15) 导出清单：expect_download + 文件名 + Markdown 分组/标题/结论/链接；无关注项 disabled ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    state = fav_workflow_state(page)
    check(state['exportButton']['exists'] and state['exportButton']['disabled'],
          '无关注项时导出按钮应 disabled')
    finding_title = ''
    finding_state = findings_state(page)
    target = finding_state['rows'][0]['id'] if finding_state['rows'] else None
    if target:
        finding_title = finding_state['rows'][0]['title']
        page.locator(f'[data-pbr-fav-finding="{target}"]').click()
        page.wait_for_timeout(250)
        page.locator(f'[data-pbr-fav-review="{target}"]').click()
        page.wait_for_timeout(250)
        page.locator(f'[data-pbr-fav-note="{target}"]').click()
        page.wait_for_timeout(200)
        note_input = page.locator('[data-pbr-note-input]')
        if note_input.count():
            note_input.first.fill('重点练开局')
            page.keyboard.press('Enter')
            page.wait_for_timeout(300)
    watch_state_now = watch_hscroll_state(page)
    watch_key = watch_state_now['cards'][0]['key'] if watch_state_now and watch_state_now['cards'] else ''
    watch_title = watch_state_now['cards'][0]['title'] if watch_state_now and watch_state_now['cards'] else ''
    page.locator('.pbr-watch [data-pbr-watch-group]:not([hidden]) [data-pbr-fav-watch]').first.click()
    page.wait_for_timeout(300)
    settle(page)
    page.screenshot(path=str(OUT / '46-export-ready-1440.png'), full_page=False)
    export_ready = page.locator('[data-pbr-export]').count() == 1
    if export_ready and not page.locator('[data-pbr-export]').first.is_disabled():
        export_ready = True
    if target and export_ready:
        with page.expect_download(timeout=20000) as download_info:
            page.locator('[data-pbr-export]').click()
        download = download_info.value
        check(bool(re.match(r'^赛训复盘清单-\d{4}-\d{2}-\d{2}\.md$', download.suggested_filename)),
              '导出文件名不对：' + download.suggested_filename)
        content = Path(download.path()).read_text(encoding='utf-8')
        check('## 重点发现' in content and '## 复盘比赛' in content,
              '导出 Markdown 应按「重点发现 / 复盘比赛」分组：' + content[:160])
        check(finding_title and finding_title in content,
              '导出内容应包含关注发现的标题：' + finding_title)
        check('重点练开局' in content, '导出内容应包含「我的结论」')
        check('已复盘' in content or '关注时间' in content, '导出内容应包含关注/已复盘时间')
        check(watch_title and watch_title in content, '导出内容应包含复盘对局标题：' + watch_title)
        check('#match/channel-mock-a' in content, '导出内容应包含对局链接')
        notes.append('[mock] 导出清单：%s（%d 字节，含两个分组）'
                     % (download.suggested_filename, len(content)))
    check(not errors, '导出出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.16) 细节：.pbr-unit 单位弱化 / 关注按钮 ≥28px / 发现结论 2 行 clamp ──
    page = browser.new_page(viewport={'width': 1440, 'height': 980})
    seed(page)
    # 让卡片显示包 波/条/座 的字段，才能验证这些单位也被 .pbr-unit 包裹
    page.add_init_script("localStorage.setItem('pbr-watch-display-fields',"
                         " JSON.stringify(['fight', 'dragon', 'tower', 'deficit']));")
    page.route('**/api/briefing*', mocker.handler)
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    units = units_state(page)
    check(units['unitCount'] >= 6, '.pbr-unit 数量过少：' + str(units['unitCount']))
    unit_text = ' '.join(units['units'])
    # 这组显示字段（fight/dragon/tower/deficit）覆盖 波/条/座/金币
    for unit in ('金币', '波', '条', '座'):
        check(unit in unit_text, '缺少 .pbr-unit 单位：' + unit + ' / ' + unit_text[:80])
    # 默认显示字段包含我方掉点（次），另开一页确认「次」也被 .pbr-unit 包裹
    default_page = new_page({'width': 1440, 'height': 980})
    default_page.goto(base + '/#overview', wait_until='load')
    wait_brief(default_page)
    default_units = units_state(default_page)
    default_text = ' '.join(default_units['units'])
    for unit in ('次', '金币', '局'):
        check(unit in default_text or unit in unit_text, '缺少 .pbr-unit 单位：' + unit)
    default_page.close()
    check(str(units['clamp']) == '2', '发现行结论应为 2 行 clamp：' + str(units['clamp']))
    check(units['watchNumberHtml'].count('pbr-unit') >= 1, '复盘卡数字单位应用 .pbr-unit 包裹')
    page.locator('[data-pbr-fav-finding]').first.click()
    page.wait_for_timeout(300)
    units_after = units_state(page)
    check(units_after['favHeight'] is not None and units_after['favHeight'] >= 28,
          '关注按钮高度应 ≥28px：' + str(units_after['favHeight']))
    check(units_after['reviewHeight'] is not None and units_after['reviewHeight'] >= 28,
          '已复盘按钮高度应 ≥28px：' + str(units_after['reviewHeight']))
    notes.append('[mock] 细节：.pbr-unit 单位 / 按钮 ≥28px / 结论 clamp 2')
    check(not errors, '细节断言出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.17) 快捷键：J/K 切卡、F 关注、Enter 打开；输入框内不触发 ──
    page = new_page({'width': 1440, 'height': 980})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    hint = shortcut_state(page)
    check(hint['hint']['exists'], '复盘区头应有快捷键提示 [data-pbr-shortcut-hint]')
    if hint['hint']['exists']:
        hint_text = hint['hint']['text']
        check('J/K' in hint_text or ('J' in hint_text and 'K' in hint_text),
              '快捷键提示应含 J/K：' + hint_text)
    page.click('.pbr-summary')
    page.keyboard.press('j')
    page.wait_for_timeout(300)
    j1 = shortcut_state(page)
    check(bool(j1['currentKey']), '按 J 后应聚焦一张复盘卡')
    check(j1['activeInsideWatch'], '按 J 后焦点应在复盘卡片内：' + j1['activeTag'])
    first_key = j1['currentKey']
    settle(page)
    page.screenshot(path=str(OUT / '47-shortcut-current-1440.png'), full_page=False)
    page.keyboard.press('j')
    page.wait_for_timeout(300)
    j2 = shortcut_state(page)
    check(j2['currentKey'] and j2['currentKey'] != first_key,
          '再按 J 应切到下一张卡：%s → %s' % (first_key, j2['currentKey']))
    page.keyboard.press('k')
    page.wait_for_timeout(300)
    j3 = shortcut_state(page)
    check(j3['currentKey'] == first_key, '按 K 应退回上一张卡：' + str(j3['currentKey']))
    page.keyboard.press('f')
    page.wait_for_timeout(350)
    fav_after_key = fav_workflow_state(page)
    current_card = next((item for item in fav_after_key['watch'] if item['key'] == j3['currentKey']), None)
    check(current_card is not None and current_card['isFav'], '按 F 应关注当前卡：' + str(j3['currentKey']))
    favs = read_storage(page, 'pbr-watch-favs')
    check(isinstance(favs, dict) and j3['currentKey'] in favs,
          'F 关注应写入 pbr-watch-favs：' + json.dumps(favs, ensure_ascii=False))
    # 输入框内 J 不切卡
    note_button = page.locator('.pbr-watch [data-pbr-watch-group]:not([hidden]) [data-pbr-fav-note]').first
    if note_button.count():
        note_button.click()
        page.wait_for_timeout(200)
        note_input = page.locator('[data-pbr-note-input]').first
        if note_input.count() and note_input.is_visible():
            before_key = shortcut_state(page)['currentKey']
            note_input.fill('')
            page.keyboard.type('j')
            after_key = shortcut_state(page)['currentKey']
            check(after_key == before_key, '输入框内按 J 不应切换复盘卡')
            page.keyboard.press('Escape')
            page.wait_for_timeout(200)
    notes.append('[mock] 快捷键：J/K 切卡、F 关注、输入框内不触发')
    # Enter 打开对局（会离开首页，放最后）。先确认焦点在「当前卡」上：
    # 新增的 interactive 守卫会在焦点位于 button/a 等元素时不劫持 Enter（正确行为），
    # 所以把焦点从「＋结论」按钮移回当前卡再按。
    current_key = shortcut_state(page)['currentKey']
    if not current_key:
        check(False, '按 J 没有产生当前卡，跳过 Enter 用例')
    page.evaluate("() => { const card = document.querySelector('.pbr-watch "
                  "[data-pbr-watch-group]:not([hidden]) .pbr-finding.is-current'); "
                  "if (card) card.focus(); }")
    page.wait_for_timeout(150)
    page.keyboard.press('Enter')
    page.wait_for_function("() => location.hash.startsWith('#match/')", timeout=10000)
    check(page.evaluate('location.hash').startswith('#match/'), 'Enter 应打开当前卡对局')
    notes.append('[mock] Enter 打开当前卡对局：' + page.evaluate('location.hash'))
    check(not errors, '快捷键出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 6.18) 老报文（无 watchFields / moments）：无时间点/快捷键/复盘关注，但发现区关注/忽略/导出/视图仍可用 ──
    page = browser.new_page(viewport={'width': 1440, 'height': 980})
    seed(page)
    mocker.mode = 'legacy'
    page.route('**/api/briefing*', mocker.handler)
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    check(page.locator('[data-pbr-moments]').count() == 0, '老报文不应渲染时间点容器')
    check(page.locator('[data-pbr-shortcut-hint]').count() == 0, '老报文不应渲染快捷键提示')
    check(page.locator('[data-pbr-fav-watch]').count() == 0, '老报文不应渲染复盘关注按钮')
    check(page.locator('[data-pbr-fav-review][data-pbr-fav-kind="watch"]').count() == 0,
          '老报文不应渲染复盘「已复盘」')
    check(page.locator('[data-pbr-fav-finding]').count() == 6, '老报文发现区仍应有关注按钮')
    check(page.locator('[data-pbr-ignore-finding]').count() == 6, '老报文发现区仍应有忽略按钮')
    check(page.locator('[data-pbr-view-mode]').count() == 3, '老报文视图过滤仍应可用')
    check(page.locator('[data-pbr-export]').count() == 1, '老报文导出按钮仍应可用')
    legacy_first = page.locator('[data-pbr-fav-finding]').first.get_attribute('data-pbr-fav-finding')
    page.locator(f'[data-pbr-fav-finding="{legacy_first}"]').click()
    page.wait_for_timeout(300)
    legacy_favs = read_storage(page, 'pbr-finding-favs')
    check(isinstance(legacy_favs, dict) and legacy_first in legacy_favs,
          '老报文发现区关注应可用：' + json.dumps(legacy_favs, ensure_ascii=False))
    notes.append('[mock] 老报文：无 moments/快捷键/复盘关注，发现区关注可用')
    check(not errors, '老报文出现控制台报错：' + ' | '.join(errors[:3]))
    mocker.mode = 'periods'
    page.close()

    # ── 6.6) 深色主题：工具栏/两个弹层文字可读、无横向滚动 ──
    page = browser.new_page(viewport={'width': 1440, 'height': 980})
    seed(page)
    page.add_init_script("localStorage.setItem('training-rebuild-theme','dark');")
    page.route('**/api/briefing*', mocker.handler)
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    check(page.evaluate("() => document.documentElement.dataset.theme") == 'dark',
          '深色主题没有生效（data-theme != dark）')
    state = watch_state(page)
    if state:
        for name, node in (('排序按钮', state['sortToggle']), ('字段按钮', state['fieldsToggle'])):
            if node.get('exists') and node.get('contrast') is not None:
                check(node['contrast'] >= 2.5,
                      f'深色主题下{name}文字对比度不足：{node["contrast"]}')
        page.locator('[data-pbr-sort-toggle]').click()
        page.wait_for_timeout(250)
        dark_sort = watch_state(page)
        check(dark_sort['sortPop']['visible'], '深色主题下排序弹层没有展开')
        dim = [item for item in dark_sort['sortOptions']
               if item['contrast'] is not None and item['contrast'] < 2.5]
        check(not dim, '深色主题下排序弹层选项文字对比度不足：'
              + json.dumps([{'id': item['id'], 'ratio': item['contrast']} for item in dim],
                           ensure_ascii=False))
        focus_watch_section(page)
        settle(page)
        page.screenshot(path=str(OUT / '33-watch-sort-pop-dark-1440.png'), full_page=False)
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        page.locator('[data-pbr-fields-toggle]').click()
        page.wait_for_timeout(250)
        dark_fields = watch_state(page)
        check(dark_fields['fieldsPop']['visible'], '深色主题下字段弹层没有展开')
        dim = [item for item in dark_fields['fieldOptions']
               if not item['disabled'] and item['contrast'] is not None and item['contrast'] < 2.5]
        check(not dim, '深色主题下字段弹层选项文字对比度不足：'
              + json.dumps([{'id': item['id'], 'ratio': item['contrast']} for item in dim],
                           ensure_ascii=False))
        focus_watch_section(page)
        settle(page)
        page.screenshot(path=str(OUT / '33b-watch-fields-pop-dark-1440.png'), full_page=False)
        page.keyboard.press('Escape')
        page.wait_for_timeout(150)
        # 暗色关注态：发现区关注一条 + 复盘卡关注一张
        page.evaluate("() => { const node = document.querySelector('.pbr-findings:not(.pbr-watch)'); if (node) window.scrollTo(0, Math.max(0, node.getBoundingClientRect().top + window.scrollY - 90)); }")
        page.wait_for_timeout(150)
        dark_finding_btn = page.locator('[data-pbr-fav-finding]').first
        if dark_finding_btn.count():
            dark_finding_btn.click()
            page.wait_for_timeout(250)
        settle(page)
        page.screenshot(path=str(OUT / '44-findings-fav-dark-1440.png'), full_page=False)
        focus_watch_section(page)
        page.wait_for_timeout(150)
        dark_watch_btn = page.locator('[data-pbr-fav-watch]').first
        if dark_watch_btn.count():
            dark_watch_btn.click()
            page.wait_for_timeout(250)
        settle(page)
        page.screenshot(path=str(OUT / '44b-watch-fav-dark-1440.png'), full_page=False)
        blur_active(page)
    overflow = overflow_px(page)
    check(overflow <= 1, f'深色主题 1440 宽度出现横向滚动（溢出 {overflow}px）')
    page.screenshot(path=str(OUT / '33c-overview-dark-1440.png'), full_page=False)
    notes.append('[mock] 深色主题：工具栏/两个弹层文字可读、无横向滚动')
    check(not errors, '深色主题出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── 7) 390 窄屏：一列、工具栏换行、两个弹层不溢出 ──
    page = new_page({'width': 390, 'height': 844})
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    overflow = overflow_px(page)
    check(overflow <= 1, f'390 宽度出现横向滚动（溢出 {overflow}px）')
    if page.locator('.pbr-metric').count() > 1:
        columns = single_column(page, '.pbr-metrics')
        check(columns is None or columns == 1, '390 宽度下指标没有单列：' + str(columns))
    check(single_column(page, '.pbr-findings:not(.pbr-watch) .pbr-finding-list') in (None, 1),
          '390 宽度下发现区没有单列')
    check(boxes_fit(page, '.pbr-findings:not(.pbr-watch) .pbr-finding, .pbr-metric, .pbr-summary, '
                    '.pbr-stat, .pbr-findings:not(.pbr-watch) .pbr-numbers'),
          '390 宽度下卡片内容超出可视区域')
    check(boxes_fit(page, '.pbr-watch [data-pbr-watch-group]:not([hidden])'),
          '390 宽度下复盘横向滚动容器超出可视区域')
    titles = findings_title_lines(page)
    broken = [item for item in titles if not item.get('found') or item.get('lines') != 1]
    check(not broken, '390 宽度下发现标题换行了：' + json.dumps(broken, ensure_ascii=False))
    state = watch_state(page)
    if state and state['sortToggle'].get('exists'):
        check(state['sortTop'] is not None and state['titleBottom'] is not None
              and state['sortTop'] >= state['titleBottom'] - 2,
              '390 宽度下工具栏应落到标题下方：sortTop=%s titleBottom=%s'
              % (state['sortTop'], state['titleBottom']))
        check(state['sortTop'] is not None and state['fieldsTop'] is not None
              and abs(state['sortTop'] - state['fieldsTop']) <= 6,
              '390 宽度下两个工具按钮应在同一行：%s / %s' % (state['sortTop'], state['fieldsTop']))
        check(boxes_fit(page, '[data-pbr-sort-toggle], [data-pbr-fields-toggle]'),
              '390 宽度下工具按钮超出可视区')
        page.locator('[data-pbr-sort-toggle]').click()
        page.wait_for_timeout(250)
        sort_state = watch_state(page)
        check(sort_state['sortPop']['visible'], '390 宽度下排序弹层没有展开')
        rect = sort_state['sortPop']['rect']
        check(rect and rect['left'] >= -1 and rect['right'] <= sort_state['viewport']['width'] + 1,
              '390 宽度下排序弹层溢出可视区：' + json.dumps(rect, ensure_ascii=False))
        focus_watch_section(page)
        settle(page)
        page.screenshot(path=str(OUT / '34c-watch-sort-pop-390.png'), full_page=False)
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        page.locator('[data-pbr-fields-toggle]').click()
        page.wait_for_timeout(250)
        fields_state = watch_state(page)
        check(fields_state['fieldsPop']['visible'], '390 宽度下字段弹层没有展开')
        rect = fields_state['fieldsPop']['rect']
        check(rect and rect['left'] >= -1 and rect['right'] <= fields_state['viewport']['width'] + 1,
              '390 宽度下字段弹层溢出可视区：' + json.dumps(rect, ensure_ascii=False))
        focus_watch_section(page)
        settle(page)
        page.screenshot(path=str(OUT / '34d-watch-fields-pop-390.png'), full_page=False)
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        blur_active(page)
        # 390 横滑 + 左右箭头 + 关注
        mobile = watch_hscroll_state(page)
        check(mobile and mobile['scroller'], '390 宽度下复盘分组应可横向滑动')
        check(mobile and mobile['cardCount'] == 5, '390 下每组仍应渲染 5 张卡：'
              + str(mobile and mobile['cardCount']))
        check(mobile and mobile['prev']['exists'] and mobile['next']['exists'],
              '390 宽度下缺少左右滚动箭头节点')
        check(mobile and not mobile['prev']['visible'] and not mobile['next']['visible'],
              '390 触摸端左右箭头应隐藏（直接横滑）：prev=%s next=%s'
              % (mobile and mobile['prev'].get('visible'), mobile and mobile['next'].get('visible')))
        before_left = mobile['scroller']['scrollLeft'] if mobile and mobile['scroller'] else 0
        if mobile and mobile['scroller']:
            set_scroll(page, '.pbr-watch [data-pbr-watch-group]:not([hidden])', 200, 'left')
            page.wait_for_timeout(200)
            moved = watch_hscroll_state(page)
            check(moved['scroller']['scrollLeft'] > before_left + 10,
                  '390 宽度下复盘轨道不能横向滑动')
            settle(page)
            page.screenshot(path=str(OUT / '45-watch-hscroll-390.png'), full_page=False)
        mobile_fav = page.locator('[data-pbr-fav-watch]').first
        if mobile_fav.count():
            mobile_fav.click()
            page.wait_for_timeout(300)
            mobile_fav_state = watch_hscroll_state(page)
            check(mobile_fav_state['cards'][0]['isFav'],
                  '390 宽度下关注的复盘卡没有置顶/变色')
            settle(page)
            page.screenshot(path=str(OUT / '46-watch-fav-390.png'), full_page=False)
    overflow = overflow_px(page)
    check(overflow <= 1, f'390 宽度打开过弹层后出现横向滚动（溢出 {overflow}px）')
    check(not errors, '390 宽度出现控制台报错：' + ' | '.join(errors[:3]))
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(200)
    settle(page)
    page.screenshot(path=str(OUT / '34-overview-week-mock-390.png'), full_page=False)
    page.screenshot(path=str(OUT / '34b-overview-week-mock-390-full.png'), full_page=True)
    notes.append(f'[mock] 390 宽度：工具栏换行、两弹层不溢出、指标 {page.locator(".pbr-metric").count()} 个')
    page.close()

    # ── 8) 空库：沿用「还没有对局数据」弹窗，首页不整页换向导 ──
    page = browser.new_page(viewport={'width': 1440, 'height': 980})
    seed(page)
    mocker.mode = 'empty_library'
    page.route('**/api/briefing*', mocker.handler)
    page.goto(base + '/#overview', wait_until='load')
    page.wait_for_selector('#filters[open]', timeout=15000)
    dialog = page.locator('#filters').inner_text()
    check('还没有对局数据' in dialog, '空库弹窗标题不对：' + dialog[:80])
    check('这个工作台不自带比赛数据' in dialog, '空库弹窗缺少首次使用说明')
    check(page.locator('[data-pbr-root]').count() == 1, '空库时首页整页被换掉了（没有简报容器）')
    check('赛训总览' in page.inner_text('#content'), '空库时首页标题丢了')
    page.screenshot(path=str(OUT / '35-empty-library-dialog-mock-1440.png'), full_page=False)
    notes.append('[mock] 空库：弹窗 + 首页外壳保留')
    mocker.mode = 'periods'
    page.close()

    # ── 9) 取数失败：模块内错误 + 重试恢复 ──
    page = browser.new_page(viewport={'width': 1440, 'height': 980})
    seed(page)
    state = {'failed': False}

    def flaky(route):
        if not state['failed']:
            state['failed'] = True
            route.fulfill(status=500, content_type='application/json', body='{"detail":"boom"}')
            return
        route.fulfill(status=200, content_type='application/json',
                      body=json.dumps(payload('week', key=key), ensure_ascii=False))

    page.route('**/api/briefing*', flaky)
    page.goto(base + '/#overview', wait_until='load')
    page.wait_for_selector('[data-pbr-root] .pbr-error', timeout=15000)
    error_text = page.inner_text('[data-pbr-root] .pbr-error')
    check('本期简报没读出来' in error_text, '取数失败没有模块内错误：' + error_text[:60])
    check(page.locator('[data-pbr-retry]').count() == 1, '取数失败没有重试按钮')
    check(page.locator('[data-pbr-root]').count() == 1, '取数失败把整页换掉了')
    page.screenshot(path=str(OUT / '36-error-retry-mock-1440.png'), full_page=False)
    page.click('[data-pbr-retry]')
    page.wait_for_selector('[data-pbr-root] .pbr-summary', timeout=15000)
    check('本周 6 局 4 胜 2 负' in page.inner_text('#content'), '重试后没有恢复简报')
    notes.append('[mock] 失败 → 模块内错误 + 重试恢复')
    page.close()


def run_real(base, browser):
    """真实数据冒烟：先看本周空态/最近一批入口，再固定 custom 11-02~11-04（23 局）验详情。"""
    # ── A) 本周（真实）：外壳 + 空态/最近一批入口 ──
    page = browser.new_page(viewport={'width': 1440, 'height': 980})
    seed(page)
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    text = body_text(page)
    check('赛训周期简报' in text, '[real] 首页缺少 kicker「赛训周期简报」')
    check('赛训总览' in text, '[real] 首页缺少标题「赛训总览」')
    check(page.locator('[data-pbr-period="week"]').count() == 1, '[real] 缺少「本周」周期按钮')
    available = page.locator('.pbr-summary').count() > 0
    overflow = overflow_px(page)
    check(overflow <= 1, f'[real] 1440 宽度出现横向滚动（溢出 {overflow}px）')
    page.screenshot(path=str(OUT / ('37-overview-real-week-1440.png' if not available
                                    else '37-overview-real-1440.png')), full_page=False)
    notes.append('[real] 本周：' + ('有数据' if available else '0 局（空态 + 最近一批入口）'))
    if not available:
        fallback = page.locator('[data-pbr-fallback]')
        if check(fallback.count() == 1, '[real] 本周 0 局却没有「查看最近一批」入口'):
            fallback_label = fallback.inner_text()
            fallback.click()
            page.wait_for_selector('[data-pbr-root] .pbr-summary', timeout=30000)
            settle(page)
            check('自定义赛训表现' in body_text(page), '[real] 最近一批没有切到自定义区间')
            notes.append('[real] 最近一批入口可用：' + fallback_label)
    check(not errors, '[real] 首页出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()

    # ── B) 固定 custom 11-02~11-04（真实 23 局）：详情 + 工具栏/弹层 ──
    page = browser.new_page(viewport={'width': 1440, 'height': 980})
    seed(page)
    page.add_init_script(
        "localStorage.setItem('training-rebuild-filters', JSON.stringify("
        "{from:'2026-11-02',to:'2026-11-04',source:['db','bundle']}));")
    errors = []
    collect_errors(page, errors)
    page.goto(base + '/#overview', wait_until='load')
    wait_brief(page)
    text = body_text(page)
    check('自定义赛训表现' in text, '[real] 固定 custom 11-02~11-04 没有生效：' + text[:60])
    check(page.locator('.pbr-summary').count() == 1, '[real] custom 11-02~11-04 没有数据（应 23 局）')
    check(page.locator('.pbr-metric').count() == 8, '[real] 指标不是 8 项')
    findings_rows = page.locator('.pbr-findings:not(.pbr-watch) .pbr-finding')
    check(findings_rows.count() <= 3, '[real] 重点发现超过 3 条')
    check(findings_rows.locator('.pbr-stat').count() == findings_rows.count(),
          '[real] 发现区每行不是恰好 1 个 .pbr-stat')
    titles = findings_title_lines(page)
    broken = [item for item in titles if not item.get('found') or item.get('lines') != 1]
    check(not broken, '[real] 发现标题换行了：' + json.dumps(broken, ensure_ascii=False))

    # 复盘区：区头工具栏（排序按钮 / 字段按钮 + 两个弹层）
    state = watch_state(page)
    check(state is not None, '[real] 复盘区没有渲染')
    if state and state['sortToggle'].get('exists'):
        check(state['legacyChips'] == 0 and state['legacyDisplays'] == 0,
              '[real] 旧版胶囊控件不应再出现')
        check(state['groupCount'] == 10,
              f'[real] 复盘分组应为 10 组，实际 {state["groupCount"]}')
        check(len(state['visibleGroups']) == 1,
              f'[real] 同时只应显示一组，实际 {state["visibleGroups"]}')
        check(all(card['count'] == 4 for card in state['cards']),
              '[real] 每张卡都应渲染 4 项：' + str([card['count'] for card in state['cards']]))
        check(state['sortToggle']['expanded'] == 'false' and not state['sortPop']['visible'],
              '[real] 排序弹层默认应收起')
        check(state['fieldsToggle']['expanded'] == 'false' and not state['fieldsPop']['visible'],
              '[real] 字段弹层默认应收起')
        # 排序弹层：打开 → 10 个选项、选中唯一 → 选另一个字段 → 分组/计数/按钮文本同步、关闭
        page.locator('[data-pbr-sort-toggle]').click()
        page.wait_for_timeout(300)
        opened = watch_state(page)
        check(opened['sortPop']['visible'], '[real] 排序弹层没有展开')
        check(len(opened['sortOptions']) == 10,
              f'[real] 排序弹层应有 10 个字段选项，实际 {len(opened["sortOptions"])}')
        selected = [item['id'] for item in opened['sortOptions'] if item['selected']]
        check(len(selected) == 1, '[real] 排序弹层当前选中项应唯一：' + str(selected))
        before = selected[0] if selected else None
        focus_watch_section(page)
        settle(page)
        page.screenshot(path=str(OUT / '38a-real-sort-pop-1440.png'), full_page=False)
        catalog_ids = [item[0] for item in WATCH_META]
        target = next((fid for fid in catalog_ids if fid != before), None)
        if target:
            page.locator(f'[data-pbr-sort-option="{target}"]').click()
            page.wait_for_timeout(350)
            after = watch_state(page)
            check(after['visibleGroups'] == [target],
                  f'[real] 点排序选项没有切换分组（应为 {target}）：' + str(after['visibleGroups']))
            rendered = len(after['cards'])
            count_number = int(re.sub(r'[^0-9]', '', after['countText']) or 0)
            check(after['countText'].endswith('局') and count_number >= rendered,
                  '[real] 区头计数应是后端 count（>= 渲染 %d 张）：%s'
                  % (rendered, after['countText']))
            check(after['sortToggle']['text'] != opened['sortToggle']['text'],
                  '[real] 排序按钮文本没跟着更新：' + after['sortToggle']['text'])
            check(after['sortToggle']['expanded'] == 'false' and not after['sortPop']['visible'],
                  '[real] 选完排序项后弹层应收起')
            notes.append(f'[real] 复盘排序 {before} → {target}（{after["countText"]}）')
        # 字段弹层：默认 4 项、未选禁用；取消一项即时生效；恢复默认；Esc 关闭
        page.locator('[data-pbr-fields-toggle]').click()
        page.wait_for_timeout(300)
        fstate = watch_state(page)
        check(fstate['fieldsPop']['visible'], '[real] 字段弹层没有展开')
        check(len(fstate['fieldOptions']) == 10,
              f'[real] 字段弹层应有 10 个选项，实际 {len(fstate["fieldOptions"])}')
        check(len(fstate['checkedIds']) == 4,
              '[real] 字段弹层默认应勾选 4 项：' + str(fstate['checkedIds']))
        check(len(fstate['disabledIds']) == 6,
              '[real] 满 4 项时未选项应禁用：' + str(fstate['disabledIds']))
        focus_watch_section(page)
        settle(page)
        page.screenshot(path=str(OUT / '38b-real-fields-pop-1440.png'), full_page=False)
        victim = fstate['checkedIds'][0] if fstate['checkedIds'] else None
        if victim:
            page.locator(f'[data-pbr-field-option="{victim}"]').click()
            page.wait_for_timeout(300)
            un = watch_state(page)
            check(un['fieldsPop']['visible'], '[real] 勾选字段后弹层不应关闭')
            check(len(un['checkedIds']) == 3,
                  '[real] 取消一项后应剩 3 项：' + str(un['checkedIds']))
            check(all(card['count'] == 3 for card in un['cards']),
                  '[real] 取消字段后所有卡都应变 3：'
                  + str([card['count'] for card in un['cards']]))
            stored = read_storage(page, 'pbr-watch-display-fields')
            check(isinstance(stored, list) and len(stored) == 3,
                  '[real] localStorage 没写入 3 项：' + json.dumps(stored, ensure_ascii=False))
            notes.append('[real] 字段弹层即时生效 → ' + json.dumps(stored, ensure_ascii=False))
        reset = page.locator('[data-pbr-fields-pop] button', has_text='恢复默认')
        if not reset.count():
            reset = page.locator('.pbr-watch button', has_text='恢复默认')
        check(reset.count() >= 1, '[real] 字段弹层缺少「恢复默认」')
        if reset.count():
            reset.first.click()
            page.wait_for_timeout(300)
        restored = watch_state(page)
        check(len(restored['checkedIds']) == 4,
              '[real] 恢复默认后应 4 项：' + str(restored['checkedIds']))
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        escaped = watch_state(page)
        check(escaped['fieldsToggle']['expanded'] == 'false'
              and not escaped['fieldsPop']['visible'], '[real] Esc 没有关闭字段弹层')
        notes.append('[real] 字段弹层：默认 4 / 即时生效 / 恢复默认 / Esc 关闭')
        blur_active(page)

    # 第 3 轮：发现不限条数 + 关注；复盘横滑 + 箭头 + 关注（真实数据）
    real_findings = findings_state(page)
    check(real_findings['exists'], '[real] 发现区没有渲染')
    check(real_findings['favCount'] == len(real_findings['rows']),
          '[real] 每条发现都应有「关注」按钮：%s vs %s'
          % (real_findings['favCount'], len(real_findings['rows'])))
    check(real_findings['overflowY'] in ('auto', 'scroll'),
          '[real] 发现区应是内部滚动容器：' + str(real_findings['overflowY']))
    real_watch = watch_hscroll_state(page)
    check(real_watch and real_watch['scroller'], '[real] 复盘分组应可横向滑动')
    check(real_watch and real_watch['cardCount'] >= 4,
          '[real] 复盘分组渲染条数异常（应 >=4）：' + str(real_watch and real_watch['cardCount']))
    check(real_watch and real_watch['prev']['exists'] and real_watch['next']['exists'],
          '[real] 缺少左右滚动箭头')
    if real_watch and real_watch['cards']:
        first_key = real_watch['cards'][0]['key']
        page.locator('.pbr-watch [data-pbr-watch-group]:not([hidden]) '
                    f'[data-pbr-fav-watch="{first_key}"]').click()
        page.wait_for_timeout(300)
        fav_real = watch_hscroll_state(page)
        check(fav_real['cards'][0]['key'] == first_key and fav_real['cards'][0]['isFav'],
              '[real] 关注复盘卡没有置顶/变色：%s / %s'
              % (fav_real['cards'][0]['key'], fav_real['cards'][0]['isFav']))
        stored = read_storage(page, 'pbr-watch-favs')
        check(isinstance(stored, dict) and first_key in stored,
              '[real] localStorage[pbr-watch-favs] 没写入：'
              + json.dumps(stored, ensure_ascii=False))
        page.locator('.pbr-watch [data-pbr-watch-group]:not([hidden]) '
                    f'[data-pbr-fav-watch="{first_key}"]').click()
        page.wait_for_timeout(250)
    if real_watch and real_watch['scroller']:
        before_left = real_watch['scroller']['scrollLeft']
        arrow = arrow_locator(page, 'next')
        if arrow is not None and not arrow.is_disabled():
            arrow.click()
            page.wait_for_timeout(450)
            moved = watch_hscroll_state(page)
            check(moved['scroller']['scrollLeft'] > before_left + 10,
                  '[real] 点 › 没有横向滑动')
    settle(page)
    page.screenshot(path=str(OUT / '38c-real-watch-hscroll-1440.png'), full_page=False)
    notes.append('[real] 第3轮：发现关注按钮 / 复盘横滑 / 左右箭头 / 关注均正常')

    watch_href = href_of(page, '.pbr-watch .pbr-watch-link a')
    if watch_href:
        check(not re.fullmatch(r'#match/\d+', watch_href),
              '[real] 复盘卡链接仍指向营地 seq：' + watch_href)
        notes.append(f'[real] 复盘卡 href = {watch_href}')
    check(href_of(page, '[data-pbr-all-games]') == '#matches', '[real] 「全部对局」应指向 #matches')
    evidence_href = href_of(page, '.pbr-evidence a')
    if evidence_href:
        check(evidence_href.startswith('#match/'), '[real] 证据对局不是 #match/<key>：' + evidence_href)
        notes.append(f'[real] 证据对局 href = {evidence_href}')
    overflow = overflow_px(page)
    check(overflow <= 1, f'[real] 有数据时 1440 宽度出现横向滚动（溢出 {overflow}px）')
    check(boxes_fit(page, '.pbr-findings:not(.pbr-watch) .pbr-finding, .pbr-stat'),
          '[real] 有数据时发现行/数字块超出可视区')
    page.screenshot(path=str(OUT / '38-overview-real-data-1440.png'), full_page=False)
    notes.append(f'[real] 有数据：指标 {page.locator(".pbr-metric").count()} 个，'
                 f'发现 {findings_rows.count()} 条，'
                 f'复盘可见 {len((watch_state(page) or {}).get("cards") or [])} 局，'
                 f'正文 {len(text)} 字')

    # ── C) 真实数据 390：无横向滚动、工具栏/弹层不溢出 ──
    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_timeout(400)
    settle(page)
    overflow = overflow_px(page)
    check(overflow <= 1, f'[real] 390 宽度出现横向滚动（溢出 {overflow}px）')
    check(boxes_fit(page, '.pbr-findings:not(.pbr-watch) .pbr-finding, .pbr-stat'),
          '[real] 390 宽度下发现行 / 数字块超出可视区')
    check(boxes_fit(page, '[data-pbr-sort-toggle], [data-pbr-fields-toggle]'),
          '[real] 390 宽度下复盘工具按钮超出可视区')
    real_mobile = watch_hscroll_state(page)
    check(real_mobile and real_mobile['scroller'],
          '[real] 390 宽度下复盘分组应可横向滑动')
    check(real_mobile and real_mobile['cards'],
          '[real] 390 宽度下缺少横滑卡片')
    check(real_mobile and not real_mobile['prev']['visible'] and not real_mobile['next']['visible'],
          '[real] 390 触摸端左右箭头应隐藏（直接横滑）')
    if real_mobile and real_mobile['scroller']:
        set_scroll(page, '.pbr-watch [data-pbr-watch-group]:not([hidden])', 180, 'left')
        page.wait_for_timeout(200)
        moved_mobile = watch_hscroll_state(page)
        check(moved_mobile['scroller']['scrollLeft'] > 10,
              '[real] 390 宽度下复盘轨道不能横向滑动')
    state390 = watch_state(page)
    if state390 and state390['sortToggle'].get('exists'):
        check(state390['sortTop'] is not None and state390['titleBottom'] is not None
              and state390['sortTop'] >= state390['titleBottom'] - 2,
              '[real] 390 宽度下工具栏应落到标题下方')
        page.locator('[data-pbr-sort-toggle]').click()
        page.wait_for_timeout(250)
        sort390 = watch_state(page)
        rect = sort390['sortPop']['rect']
        check(rect and rect['left'] >= -1 and rect['right'] <= sort390['viewport']['width'] + 1,
              '[real] 390 宽度下排序弹层溢出：' + json.dumps(rect, ensure_ascii=False))
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        page.locator('[data-pbr-fields-toggle]').click()
        page.wait_for_timeout(250)
        fields390 = watch_state(page)
        rect = fields390['fieldsPop']['rect']
        check(rect and rect['left'] >= -1 and rect['right'] <= fields390['viewport']['width'] + 1,
              '[real] 390 宽度下字段弹层溢出：' + json.dumps(rect, ensure_ascii=False))
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        blur_active(page)
    page.screenshot(path=str(OUT / '39-overview-real-390.png'), full_page=False)
    page.screenshot(path=str(OUT / '39b-overview-real-390-full.png'), full_page=True)
    notes.append('[real] 390 宽度无横向滚动，工具按钮/两个弹层不溢出')

    # 真实数据下点一次证据对局：key 必须能被站内单局页认出来（不是另一套数据源的 id）。
    detail_link = page.locator('.pbr-evidence a').first
    if detail_link.count():
        target = detail_link.get_attribute('href') or ''
        page.set_viewport_size({'width': 1440, 'height': 980})
        detail_link.click()
        page.wait_for_function("() => location.hash.startsWith('#match/')", timeout=15000)
        page.wait_for_selector('#content .page, #content .offline-card', timeout=20000)
        page.wait_for_timeout(1500)
        detail = page.inner_text('#content')
        check('暂时读不到数据' not in detail and '还没有选定' not in detail,
              '[real] 证据对局打不开单局页（key 不被站内路由识别）：' + target)
        notes.append(f'[real] 证据对局可打开：{page.evaluate("location.hash")}')
    check(not errors, '[real] 首页出现控制台报错：' + ' | '.join(errors[:3]))
    page.close()


    # ── D) 第 4 轮（真实数据）：复盘卡时间点 + 近5场 / 近3天 ──
    periods_page = browser.new_page(viewport={'width': 1440, 'height': 980})
    seed(periods_page)
    errors4 = []
    collect_errors(periods_page, errors4)
    periods_page.goto(base + '/#overview', wait_until='load')
    wait_brief(periods_page)
    real_moments = moments_state(periods_page)
    moments_cards = [card for card in (real_moments or {}).get('cards', []) if card['moments']]
    # 真实数据可能本期没有复盘卡（数据尚未回放 / 时间轴缺失），只验外壳时不应判失败。
    if moments_cards:
        check(all(re.match(r'^\d{1,2}:\d{2}', item['text']) for item in moments_cards[0]['moments']),
              '[real] 时间点 clock 格式不对：'
              + str([item['text'] for item in moments_cards[0]['moments']]))
        notes.append('[real] 复盘时间点格式正常：' + str(len(moments_cards)) + ' 张卡')
    else:
        notes.append('[real] 本期真实数据没有可复盘卡/时间点，跳过格式断言')
    periods_page.locator('[data-pbr-period="recent"]').click()
    # 切换周期后旧简报会先留在 DOM 里，等副标题真的换成「近5场」再读正文。
    periods_page.wait_for_function(
        "() => /近\\s*5\\s*场|最近 5 场/.test(document.querySelector('.pbr-sub')?.textContent || '')",
        timeout=15000)
    periods_page.wait_for_timeout(800)
    settle(periods_page)
    text_recent = body_text(periods_page)
    check('最近 5 场' in text_recent or '近5场' in text_recent or '最近这批' in text_recent,
          '[real] 「近5场」标题没变化：' + text_recent[:80])
    check(periods_page.locator('.pbr-summary').count() > 0
          or periods_page.locator('.pbr-empty').count() > 0,
          '[real] 「近5场」既没有数据也没有空态')
    settle(periods_page)
    periods_page.screenshot(path=str(OUT / '40c-real-recent-1440.png'), full_page=False)
    periods_page.locator('[data-pbr-period="days"]').click()
    periods_page.wait_for_function(
        "() => /近\\s*3\\s*天|最近 3 天/.test(document.querySelector('.pbr-sub')?.textContent || '')",
        timeout=15000)
    periods_page.wait_for_timeout(800)
    settle(periods_page)
    check(periods_page.locator('.pbr-summary').count() > 0
          or periods_page.locator('.pbr-empty').count() > 0,
          '[real] 「近3天」既没有数据也没有空态')
    text_days = body_text(periods_page)
    check('最近 3 天' in text_days or '近3天' in text_days or '最近' in text_days,
          '[real] 「近3天」标题没变化：' + text_days[:80])
    settle(periods_page)
    periods_page.screenshot(path=str(OUT / '40d-real-days-1440.png'), full_page=False)
    notes.append('[real] 第4轮：时间点 ' + str(len(moments_cards)) + ' 张卡；「近5场/近3天」可切换')
    check(not errors4, '[real] 新周期/时间点出现控制台报错：' + ' | '.join(errors4[:3]))
    periods_page.close()


def main():
    parser = argparse.ArgumentParser(description='赛训周期简报首页回归')
    parser.add_argument('--port', type=int, default=0, help='本地临时端口（默认自动挑空闲端口）')
    parser.add_argument('--real', action='store_true', help='额外用真实 /api/briefing 跑一遍冒烟')
    parser.add_argument('--strict', action='store_true', help='/api/briefing 未上线时直接失败')
    args = parser.parse_args()

    port = args.port or free_port()
    base = f'http://127.0.0.1:{port}'
    env = dict(os.environ, TRAINING_PORT=str(port), PYTHONIOENCODING='utf-8')
    process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=ROOT, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    mode = 'mock'
    try:
        if not wait_for(base + '/api/state'):
            failures.append(f'服务在 30 秒内没有起来（端口 {port} 可能被占用）')
            raise SystemExit(1)
        if process.poll() is not None:
            failures.append('server.py 启动后立刻退出（端口被占用或导入失败）')
            raise SystemExit(1)

        backend = False
        try:
            http_json(f'{base}/api/briefing?period=week&{SOURCE_Q}')
            backend = True
            notes.append('后端 /api/briefing 已可用')
        except Exception as exc:
            notes.append(f'后端 /api/briefing 还不可用（{type(exc).__name__}）：先验前端合成数据')
            if args.strict:
                failures.append('/api/briefing 未上线（--strict）')

        key = real_match_key(base)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                mocker = Mocker(key)
                run_mock(base, browser, key, mocker)
                if args.real:
                    if backend:
                        run_real(base, browser)
                    else:
                        failures.append('--real 需要 /api/briefing 可用')
            finally:
                browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    print('== 结果 ==')
    for note in notes:
        print('  ·', note)
    if failures:
        print('== 失败 ==')
        for item in failures:
            print('  ✗', item)
        print(json.dumps({'ok': False, 'mode': mode, 'failures': failures}, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps({'ok': True, 'mode': mode, 'screenshots': str(OUT)}, ensure_ascii=False))
    print('全部通过')


if __name__ == '__main__':
    main()
