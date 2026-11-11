"""选手赛训级对局分析：对位、资源定位与教练视角洞察。

    python tools/camp_insights.py 540599032 [--refresh-list]

数据管线：
  morebattlelist（时间/英雄/胜负/四元组，缓存 data/camp_lists/<id>.json）
  × data/camp_details/<gameSeq>.json（双方十人面板 + ban）
  × 公开接口 matchInfo（对手英雄名，缓存 data/official_replays/）
  → 赛训级聚合（对位/资源定位/画像）→ 自包含 HTML（双主题）。

口径说明：同序位对位 = blueRoles[i] 对 redRoles[i]（camp 数组顺序），
该假设需在训练赛样本上验证后再用于结论。
"""
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hero_catalog  # noqa: E402
import camp_replay  # noqa: E402

DETAIL_DIR = Path(os.environ.get('CAMP_DETAIL_DIR', ROOT / 'data' / 'camp_details'))
LIST_DIR = Path(os.environ.get('CAMP_LIST_DIR', ROOT / 'data' / 'camp_lists'))
OUT_DIR = Path(os.environ.get('CAMP_REPORT_DIR', ROOT / 'data' / 'camp_reports'))
INTERVAL = 2.0


def _num(value):
    try:
        return float(value if value not in (None, '') else 0)
    except (TypeError, ValueError):
        return 0.0


def esc(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def fetch_list(camp_user_id: str, refresh: bool = False, max_pages: int = 30) -> list:
    LIST_DIR.mkdir(parents=True, exist_ok=True)
    cache = LIST_DIR / f'{camp_user_id}.json'
    if cache.is_file() and not refresh:
        return json.loads(cache.read_text(encoding='utf-8'))
    import camp_client
    entries, cursor = [], 0
    for _ in range(max_pages):
        result = camp_client.call('/game/morebattlelist', {
            'lastTime': cursor, 'recommendPrivacy': 0, 'apiVersion': 5,
            'friendUserId': camp_user_id, 'option': 0})
        body = result.get('body') or {}
        if body.get('returnCode') not in (0, '0'):
            raise SystemExit(f'列表接口失败：{json.dumps(body, ensure_ascii=False)[:200]}')
        data = body.get('data') or {}
        entries.extend(data.get('list') or [])
        if not data.get('hasMore'):
            break
        next_cursor = int(data.get('lastTime') or 0)
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(INTERVAL)
    cache.write_text(json.dumps(entries, ensure_ascii=False), encoding='utf-8')
    return entries


def official_players_for(game_seq: str, entry: dict):
    """公开接口的十人（playerId→heroName），缓存于 data/official_replays/。"""
    official_id = f'camp-{game_seq}'
    try:
        normalized = camp_replay.read_normalized(official_id)
        return normalized[1].get('players') or []
    except camp_replay.CampReplayError:
        pass
    game_svr = str(entry.get('gameSvrId') or '')
    relay_svr = str(entry.get('relaySvrId') or '')
    if not game_svr or not relay_svr:
        return []
    match = __import__('re').search(r'playerid=(\d+)', str(entry.get('analyseUrl') or ''))
    player_id = match.group(1) if match else 'undefined'
    url = ('https://camp.qq.com/h5/webdist/battle-replay/index.html?'
           + __import__('urllib.parse', fromlist=['urlencode']).urlencode({
               'gameseq': game_seq, 'gamesvrentity': game_svr,
               'relaysvrentity': relay_svr, 'playerid': player_id}))
    try:
        result = camp_replay.import_link(url)
        _, normalized = camp_replay.read_normalized(result.get('id'))
        return normalized.get('players') or []
    except Exception:
        return []


def load_curve(game_seq: str, camp: str):
    """公开接口缓存的团队金币曲线（约30秒一点），转成本人视角的经济差序列。"""
    path = camp_replay.STORE / f'camp-{game_seq}' / 'normalized.json'
    if not path.is_file():
        return None
    try:
        normalized = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    economy = normalized.get('economy') or {}
    blue, red = economy.get('blue') or [], economy.get('red') or []
    if not blue or not red:
        return None
    diffs = [float(b) - float(r) for b, r in zip(blue, red)]
    return [round(value if camp == 'blue' else -value, 1) for value in diffs]


def load_matches(camp_user_id: str, refresh: bool = False):
    entries = fetch_list(camp_user_id, refresh)
    by_seq = {str(entry.get('gameSeq') or ''): entry for entry in entries}
    matches = []
    for path in sorted(DETAIL_DIR.glob('*.json')):
        game_seq = path.stem
        entry = by_seq.get(game_seq)
        if entry is None:
            continue
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        data = body.get('data') or {}
        head = data.get('head') or {}
        me_role, opp_role, team_money, ten_money = None, None, 0.0, []
        for roles_key, camp in (('blueRoles', 'blue'), ('redRoles', 'red')):
            roles = data.get(roles_key) or []
            for index, role in enumerate(roles):
                basic = role.get('basicInfo') or {}
                money = _num((role.get('battleStats') or {}).get('money'))
                ten_money.append(money)
                if str(basic.get('roleId') or '') == str(head.get('roleId') or ''):
                    me_role = {'camp': camp, 'index': index, 'basic': basic,
                               'stats': role.get('battleStats') or {}}
                elif me_role and camp == me_role['camp']:
                    team_money += money
        if not me_role:
            continue
        opp_roles = data.get('redRoles' if me_role['camp'] == 'blue' else 'blueRoles') or []
        opp_role = opp_roles[me_role['index']] if me_role['index'] < len(opp_roles) else None
        opp_basic = (opp_role or {}).get('basicInfo') or {}
        opp_stats = (opp_role or {}).get('battleStats') or {}
        stats = me_role['stats']
        dt = int((body.get('_campEntry') or {}).get('dtEventTime') or entry.get('dtEventTime') or 0)
        matches.append({
            'gameSeq': game_seq, 'dt': dt,
            'time': datetime.fromtimestamp(dt).strftime('%m-%d %H:%M') if dt else '—',
            'win': (entry.get('winCamp') == '1' and head.get('acntCamp') == 1)
                   or (entry.get('winCamp') == '2' and head.get('acntCamp') == 2)
                   or bool(head.get('gameResult')),
            'hero': hero_catalog.hero_name(head.get('heroId'), default=f"#{head.get('heroId')}"),
            'k': int(_num(head.get('killCnt'))), 'd': int(_num(head.get('deadCnt'))),
            'a': int(_num(head.get('assistCnt'))), 'grade': _num(head.get('gradeGame')),
            'money': _num(stats.get('money')), 'damage': _num(stats.get('totalHeroHurtCnt')),
            'taken': _num(stats.get('totalBehurtCnt')),
            'joinPct': round(_num(stats.get('joinGamePercent')) * 100, 1),
            'soldier': _num(stats.get('killSoldier')), 'ctrl': _num(stats.get('ctrlTime')),
            'transRate': _num(stats.get('hurtTransRate')),
            'perDeath': _num(stats.get('behurtPerDeath')),
            'camp': me_role['camp'], 'index': me_role['index'],
            'teamMoney': team_money, 'tenMoney': sorted(ten_money, reverse=True),
            'oppName': (opp_basic.get('roleName') or '').strip() or None,
            'oppMoney': _num(opp_stats.get('money')),
            'oppK': int(_num(opp_stats.get('killCnt'))),
            'oppD': int(_num(opp_stats.get('deadCnt'))),
            'oppA': int(_num(opp_stats.get('assistCnt'))),
            'oppPlayerId': str(opp_basic.get('playerId') or ''),
        })
    matches.sort(key=lambda m: m['dt'])
    for match in matches:
        entry = by_seq.get(match['gameSeq']) or {}
        players = official_players_for(match['gameSeq'], entry)
        # 公开接口身份字段已脱敏（playerId 与营地详情不同体系），按阵营内顺序对应
        opp_camp = '2' if match['camp'] == 'red' else '1'
        opp_players = [p for p in players if str(p.get('camp')) == opp_camp]
        match['oppHero'] = (opp_players[match['index']].get('hero')
                            if match['index'] < len(opp_players) else None)
        match['econCurve'] = load_curve(match['gameSeq'], match['camp'])
    bans = Counter()
    for path in sorted(DETAIL_DIR.glob('*.json')):
        try:
            body = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        data = body.get('data') or {}
        for team_key in ('blueTeam', 'redTeam'):
            for item in (data.get(team_key) or {}).get('banHeros') or []:
                bans[hero_catalog.hero_name(item.get('heroId'), default=f"#{item.get('heroId')}")] += 1
    return matches, bans


def aggregate(matches, bans):
    total = len(matches)
    wins = sum(1 for m in matches if m['win'])
    avg = lambda key: sum(m[key] for m in matches) / max(total, 1)

    def econ_rank(m):
        return 1 + sum(1 for value in m['tenMoney'] if value > m['money'])

    for m in matches:
        m['econRank'] = econ_rank(m)
        m['econPct'] = m['money'] / m['teamMoney'] * 100 if m['teamMoney'] else 0
        m['laneDiff'] = m['money'] - m['oppMoney']
    econ_ranks = sorted(round(m['econRank'], 1) for m in matches)
    lane_rows = defaultdict(lambda: {'games': 0, 'wins': 0, 'diff': 0.0})
    for m in matches:
        opp_label = m.get('oppHero') or m.get('oppName') or '未知对手'
        row = lane_rows[opp_label]
        row['games'] += 1
        row['wins'] += 1 if m['win'] else 0
        row['diff'] += m['laneDiff']
    lane_table = [{'opp': opp, **values, 'avgDiff': values['diff'] / values['games']}
                  for opp, values in lane_rows.items()]
    lane_table.sort(key=lambda item: -item['avgDiff'])
    totals = {'games': total, 'wins': wins, 'winRate': wins / max(total, 1) * 100,
              'kda': (sum(m['k'] + m['a'] for m in matches) / max(sum(m['d'] for m in matches), 1)),
              'damage': avg('damage'), 'taken': avg('taken'), 'money': avg('money'),
              'joinPct': avg('joinPct'), 'soldier': avg('soldier'), 'ctrl': avg('ctrl'),
              'grade': avg('grade'), 'econRank': sum(econ_ranks) / max(len(econ_ranks), 1),
              'laneWinRate': sum(1 for m in matches if m['laneDiff'] > 0) / max(total, 1) * 100,
              'econPct': sum(m['econPct'] for m in matches) / max(total, 1)}
    hero_pool = defaultdict(lambda: {'games': 0, 'wins': 0, 'k': 0, 'd': 0, 'a': 0})
    for m in matches:
        pool = hero_pool[m['hero']]
        pool['games'] += 1
        pool['wins'] += 1 if m['win'] else 0
        pool['k'] += m['k']
        pool['d'] += m['d']
        pool['a'] += m['a']
    radar_dims = [('对英雄输出', 'damage'), ('输出转化率', 'transRate'), ('每死承伤', 'perDeath'),
                  ('参团率', 'joinPct'), ('补刀', 'soldier'), ('控制时长', 'ctrl')]
    p90 = lambda key: sorted(m[key] for m in matches)[min(total - 1, int(total * 0.9))] if total else 1
    radar = [{'label': label, 'avg': avg(key), 'norm': min(1.0, avg(key) / p90(key)) if p90(key) else 0}
             for label, key in radar_dims]
    factors = []
    for key, label in [('damage', '对英雄输出'), ('taken', '承伤'), ('money', '经济'),
                       ('joinPct', '参团率'), ('soldier', '补刀'), ('ctrl', '控制时长'),
                       ('grade', '评分')]:
        win_games = [m[key] for m in matches if m['win']]
        lose_games = [m[key] for m in matches if not m['win']]
        if not win_games or not lose_games:
            continue
        w_avg = sum(win_games) / len(win_games)
        l_avg = sum(lose_games) / len(lose_games)
        factors.append({'label': label, 'win': w_avg, 'lose': l_avg,
                        'delta': (w_avg - l_avg) / abs(l_avg) * 100 if l_avg else 0})
    factors.sort(key=lambda item: -abs(item['delta']))
    # 王者标准时间分段：0–4 前期 / 4–10 中期 / 10+ 后期（金币点约 30 秒一个）
    def seg_value(curve, minute, camp):
        if not curve:
            return None
        index = min(int(minute * 60 / 30), len(curve) - 1) if minute is not None else len(curve) - 1
        return curve[index]

    segments = []
    for key, label, minute in (('early', '前期 0–4 分', 4), ('mid', '中期 4–10 分', 10),
                               ('late', '后期 10 分+', None)):
        values = [(seg_value(m.get('econCurve'), minute, m['camp']), m['win'])
                  for m in matches if m.get('econCurve')]
        values = [(value, win) for value, win in values if value is not None]
        segments.append({'key': key, 'label': label, 'games': len(values),
                         'avgDiff': sum(v for v, _ in values) / len(values) if values else 0,
                         'winRate': sum(1 for _, win in values if win) / len(values) * 100 if values else 0})
    early_rows = [(seg_value(m.get('econCurve'), 4, m['camp']), m['win'])
                  for m in matches if m.get('econCurve')]
    early_rows = [(value, win) for value, win in early_rows if value is not None]
    lead = [win for value, win in early_rows if value > 0]
    behind = [win for value, win in early_rows if value <= 0]
    conversion = {'earlyGames': len(early_rows),
                  'leadGames': len(lead), 'leadWin': sum(1 for w in lead if w) / len(lead) * 100 if lead else 0,
                  'behindGames': len(behind), 'behindWin': sum(1 for w in behind if w) / len(behind) * 100 if behind else 0}
    return {'matches': matches, 'totals': totals, 'hero_pool': hero_pool, 'bans': bans,
            'radar': radar, 'factors': factors, 'econRanks': econ_ranks,
            'laneTable': lane_table, 'segments': segments, 'conversion': conversion,
            'outPct': sum((m['damage'] / (m['teamMoney'] or 1) * 100) for m in matches) / max(total, 1)}


def svg_bars(rows, color, unit='', width=640):
    max_value = max((value for _, value, _ in rows), default=1) or 1
    row_h = 24
    height = len(rows) * row_h + 6
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    for index, (label, value, suffix) in enumerate(rows):
        y = index * row_h + 3
        bar_w = max(2, (width - 210) * value / max_value)
        parts.append(f'<text x="0" y="{y + 14}" font-size="12" fill="var(--ink)">{esc(label)[:14]}</text>')
        parts.append(f'<rect x="150" y="{y}" width="{bar_w:.0f}" height="15" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{150 + bar_w + 6:.0f}" y="{y + 14}" font-size="12" '
                     f'fill="var(--ink)">{value}{suffix}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def svg_lane_diff(matches, width=640, height=190):
    if not matches:
        return ''
    inner_w, inner_h = width - 70, height - 60
    scale = max(abs(m['laneDiff']) for m in matches) * 1.15 or 1
    step = inner_w / max(len(matches) - 1, 1)
    zero = 20 + inner_h / 2
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    parts.append(f'<line x1="36" y1="{zero:.0f}" x2="{width - 20}" y2="{zero:.0f}" '
                 f'stroke="var(--muted)" stroke-width="0.8"/>')
    for index, m in enumerate(matches):
        x = 36 + index * step
        bar = inner_h / 2 * abs(m['laneDiff']) / scale
        color = '#97C459' if m['laneDiff'] >= 0 else '#F09595'
        y = zero - bar if m['laneDiff'] >= 0 else zero
        parts.append(f'<rect x="{x - max(step - 8, 2) / 2:.1f}" y="{y:.1f}" width="{max(step - 8, 2):.1f}" '
                     f'height="{max(bar, 1):.1f}" rx="2" fill="{color}"/>')
        if index % max(1, len(matches) // 9) == 0:
            parts.append(f'<text x="{x:.0f}" y="{height - 20}" font-size="10" fill="var(--muted)" '
                         f'text-anchor="middle">{esc(m["time"][:5])}</text>')
    parts.append(f'<text x="0" y="{zero - inner_h / 2:.0f}" font-size="10" fill="var(--muted)">'
                 f'+{scale / 1000:.0f}k</text>')
    parts.append(f'<text x="0" y="{zero + inner_h / 2:.0f}" font-size="10" fill="var(--muted)">'
                 f'-{scale / 1000:.0f}k</text>')
    parts.append(f'<text x="{width - 20}" y="{zero - 6:.0f}" font-size="11" fill="var(--muted)" '
                 f'text-anchor="end">同序位经济差（正=压钱）</text>')
    parts.append('</svg>')
    return ''.join(parts)


def svg_radar(radar, size=280):
    import math
    center, radius = size / 2, size / 2 - 44
    axes = len(radar)
    parts = [f'<svg viewBox="0 0 {size} {size + 10}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    for ring in (0.25, 0.5, 0.75, 1.0):
        pts = ' '.join(f'{center + radius * ring * math.cos(math.radians(-90 + i * 360 / axes)):.1f},'
                       f'{center + radius * ring * math.sin(math.radians(-90 + i * 360 / axes)):.1f}'
                       for i in range(axes))
        parts.append(f'<polygon points="{pts}" fill="none" stroke="var(--grid)" stroke-width="0.5"/>')
    polygon = []
    for index, dim in enumerate(radar):
        angle = math.radians(-90 + index * 360 / axes)
        x, y = center + radius * math.cos(angle), center + radius * math.sin(angle)
        parts.append(f'<line x1="{center}" y1="{center}" x2="{x:.1f}" y2="{y:.1f}" '
                     f'stroke="var(--grid)" stroke-width="0.5"/>')
        lx = center + (radius + 20) * math.cos(angle)
        ly = center + (radius + 16) * math.sin(angle)
        anchor = 'middle' if abs(math.cos(angle)) < 0.3 else ('start' if math.cos(angle) > 0 else 'end')
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="11" fill="var(--muted)" '
                     f'text-anchor="{anchor}">{esc(dim["label"])}</text>')
        vx = center + (radius - 4) * dim['norm'] * math.cos(angle)
        vy = center + (radius - 4) * dim['norm'] * math.sin(angle)
        polygon.append(f'{vx:.1f},{vy:.1f}')
        parts.append(f'<circle cx="{vx:.1f}" cy="{vy:.1f}" r="3" fill="#534AB7"/>')
        parts.append(f'<text x="{vx + 6:.1f}" y="{vy - 5:.1f}" font-size="10" fill="var(--ink)">'
                     f'{dim["avg"]:.1f}</text>')
    parts.append(f'<polygon points="{" ".join(polygon)}" fill="#7F77DD" opacity="0.28" '
                 f'stroke="#534AB7" stroke-width="1.5"/>')
    parts.append('</svg>')
    return ''.join(parts)


def svg_diverging(factors, width=640):
    row_h = 26
    height = len(factors) * row_h + 26
    max_delta = max((abs(f['delta']) for f in factors), default=1) or 1
    half = (width - 300) / 2
    center = 220 + half
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    for index, factor in enumerate(factors):
        y = index * row_h + 6
        bar = half * min(1, abs(factor['delta']) / max_delta)
        color = '#97C459' if factor['delta'] >= 0 else '#F09595'
        x = center if factor['delta'] >= 0 else center - bar
        parts.append(f'<text x="0" y="{y + 14}" font-size="12" fill="var(--ink)">{esc(factor["label"])}</text>')
        parts.append(f'<text x="{center - half - 10:.0f}" y="{y + 14}" font-size="11" '
                     f'fill="var(--muted)" text-anchor="end">败 {factor["lose"]:.1f}</text>')
        parts.append(f'<rect x="{x:.1f}" y="{y}" width="{bar:.1f}" height="14" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{x + bar + 6 if factor["delta"] >= 0 else x - 6:.1f}" y="{y + 14}" '
                     f'font-size="12" fill="var(--ink)" text-anchor="{"start" if factor["delta"] >= 0 else "end"}">'
                     f'{factor["delta"]:+.0f}%</text>')
    parts.append(f'<text x="{center - half:.0f}" y="{height - 4}" font-size="11" fill="var(--muted)">'
                 f'← 败局更高</text>')
    parts.append(f'<text x="{center + half:.0f}" y="{height - 4}" font-size="11" fill="var(--muted)" '
                 f'text-anchor="end">胜局更高 →</text>')
    parts.append('</svg>')
    return ''.join(parts)


def svg_segments(matches, width=640, height=200):
    rows = [m for m in matches if m.get('econCurve')]
    if len(rows) < 2:
        return '<p class="helper">过程金币数据不足，无法绘制分段趋势。</p>'

    def seg_value(curve, minute):
        return curve[-1] if minute is None else curve[min(int(minute * 60 / 30), len(curve) - 1)]

    series = [('前期末', '#D85A30', 4), ('中期末', '#BA7517', 10), ('终局', '#185FA5', None)]
    all_values = [seg_value(m['econCurve'], minute) for m in rows for _, _, minute in series]
    scale = max(max(all_values), abs(min(all_values)), 1) * 1.15
    inner_w, inner_h = width - 70, height - 58
    step = inner_w / max(len(rows) - 1, 1)
    zero = 22 + inner_h / 2
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" xmlns="http://www.w3.org/2000/svg">']
    parts.append(f'<line x1="36" y1="{zero:.0f}" x2="{width - 20}" y2="{zero:.0f}" '
                 f'stroke="var(--muted)" stroke-width="0.8"/>')
    for _label, color, minute in series:
        points = ' '.join(f'{36 + index * step:.1f},'
                          f'{zero - inner_h / 2 * seg_value(m["econCurve"], minute) / scale:.1f}'
                          for index, m in enumerate(rows))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.8"/>')
    for index, m in enumerate(rows):
        if index % max(1, len(rows) // 9) == 0:
            parts.append(f'<text x="{36 + index * step:.0f}" y="{height - 22}" font-size="10" '
                         f'fill="var(--muted)" text-anchor="middle">{esc(m["time"][:5])}</text>')
    legend_x = 36
    for label, color, _minute in series:
        parts.append(f'<rect x="{legend_x}" y="{height - 12}" width="10" height="10" fill="{color}"/>')
        parts.append(f'<text x="{legend_x + 14}" y="{height - 3}" font-size="11" fill="var(--ink)">'
                     f'{label}</text>')
        legend_x += 92
    parts.append('</svg>')
    return ''.join(parts)


def build_report(camp_user_id: str, agg) -> str:
    totals = agg['totals']
    matches = agg['matches']
    lane_table = agg['laneTable']
    best_lane = lane_table[0] if lane_table else None
    worst_lane = lane_table[-1] if len(lane_table) > 1 else None
    insights = [
        f"资源定位：十人经济排名平均 {totals['econRank']:.1f}（1=全场最高）,"
        f"对局内经济占比均值 {totals['econPct']:.0f}%",
        f"对位强度：同序位对位压钱胜率 {totals['laneWinRate']:.0f}%"
        + (f"；对 {best_lane['opp']} 场均压 {best_lane['avgDiff']:.0f} 金最狠" if best_lane else ''),
        (f"被压制点：对 {worst_lane['opp']} 场均落后 {abs(worst_lane['avgDiff']):.0f} 金"
         if worst_lane and worst_lane['avgDiff'] < 0 else ''),
        f"节奏转化：前期领先 {agg['conversion']['leadGames']} 局胜率 {agg['conversion']['leadWin']:.0f}%"
        f"，前期落后 {agg['conversion']['behindGames']} 局胜率 {agg['conversion']['behindWin']:.0f}%",
        f"产出结构：场均对英雄输出 {totals['damage'] / 1000:.1f}k、承伤 {totals['taken'] / 1000:.1f}k、"
        f"参团 {totals['joinPct']:.0f}%",
    ]
    hero_bars = svg_bars([(f'{hero}（{info["games"]}局 {info["wins"]}胜）', info['games'], '局')
                          for hero, info in sorted(agg['hero_pool'].items(),
                                                   key=lambda kv: -kv[1]['games'])[:10]], '#185FA5')
    ban_bars = svg_bars([(name, count, '次') for name, count in agg['bans'].most_common(10)], '#854F0B')
    lane_diff_chart = svg_lane_diff(matches)
    radar = svg_radar(agg['radar'])
    diverging = svg_diverging(agg['factors'])
    lane_rows = ''.join(
        f'<tr><td>{esc(row["opp"])}</td><td>{row["games"]}</td>'
        f'<td>{row["wins"] / row["games"] * 100:.0f}%</td>'
        f'<td class="{"win" if row["avgDiff"] >= 0 else "lose"}">{row["avgDiff"]:+.0f}</td></tr>'
        for row in lane_table[:12])
    match_rows = ''.join(
        f'<tr><td>{esc(m["time"])}</td><td>{esc(m["hero"])}</td>'
        f'<td class="{"win" if m["win"] else "lose"}">{"胜" if m["win"] else "负"}</td>'
        f'<td>{m["k"]}/{m["d"]}/{m["a"]}</td><td>{m["grade"]:.1f}</td>'
        f'<td>{m["money"] / 1000:.1f}k</td><td>{m["econRank"]}</td>'
        f'<td>{m["econPct"]:.0f}%</td><td>{m["damage"] / 1000:.1f}k</td>'
        f'<td>{m["taken"] / 1000:.1f}k</td><td>{m["joinPct"]:.0f}%</td>'
        f'<td>{m["soldier"]:.0f}</td><td class="{"win" if m["laneDiff"] >= 0 else "lose"}">'
        f'{m["laneDiff"]:+.0f}</td></tr>'
        for m in reversed(matches))
    insight_html = ''.join(f'<div class="insight">{esc(text)}</div>' for text in insights if text)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>赛训对位分析 · {esc(camp_user_id)}</title>
<style>
:root{{--ink:#222;--muted:#777;--grid:#e5e3da;--card:#fff;--bg:#fafafa;--line:#e3e1d8;--accent:#534AB7}}
@media (prefers-color-scheme:dark){{:root{{--ink:#eee;--muted:#9a9a9a;--grid:#3a3a3a;
      --card:#1e1e22;--bg:#141416;--line:#333;--accent:#AFA9EC}}}}
body{{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:0 auto;max-width:760px;
     color:var(--ink);background:var(--bg);padding:24px 16px}}
h1{{font-size:20px;font-weight:500;margin:0 0 4px}} h2{{font-size:15px;font-weight:500;margin:34px 0 12px}}
.sub{{color:var(--muted);font-size:13px;margin-bottom:16px}}
.insight{{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);
         border-radius:8px;padding:10px 14px;margin-bottom:8px;font-size:13px;line-height:1.6}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}}
.label{{font-size:12px;color:var(--muted)}} .value{{font-size:19px;font-weight:500;margin-top:2px}}
.panel{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:14px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}
th,td{{border:1px solid var(--line);padding:4px 8px;text-align:center}}
th{{background:var(--card);font-weight:500}}
.win{{color:#3B6D11}}.lose{{color:#A32D2D}}
.helper{{color:var(--muted);font-size:12px;line-height:1.6}}
</style></head><body>
<h1>赛训对位分析 · {esc(camp_user_id)}</h1>
<p class="sub">生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} ·
{totals['games']} 局完整十人面板 · 口径：同序位对位 = blueRoles[i] 对 redRoles[i]（待训练赛样本验证）</p>
{insight_html}

<h2>对位趋势（同序位经济差）</h2>
<div class="panel">{lane_diff_chart}
<p class="helper">每局本人经济 − 对方同序位经济。正柱=压钱，负柱=被压。
配合胜率看：压钱但输的局，问题通常不在对线。</p></div>

<h2>对位英雄战绩</h2>
<div class="panel"><table><thead><tr><th>对位英雄</th><th>场次</th><th>我方胜率</th><th>场均经济差</th></tr></thead>
<tbody>{lane_rows}</tbody></table>
<p class="helper">按场均经济差排序。样本 &lt; 3 局的行仅供参考。</p></div>

<h2>节奏分段 <span class="helper">（王者口径：0–4 前期 / 4–10 中期 / 10+ 后期，约 30 秒金币点）</span></h2>
<div class="panel">
  <div class="cards" style="grid-template-columns:repeat(3,1fr)">
    {''.join(f'<div class="card"><div class="label">{esc(seg["label"])}</div>'
             f'<div class="value">{"+" if seg["avgDiff"] >= 0 else ""}{seg["avgDiff"] / 1000:.1f}k</div>'
             f'<div class="label" style="margin-top:2px">经济差 · 胜率 {seg["winRate"]:.0f}%（{seg["games"]} 局）</div></div>'
             for seg in agg['segments'])}
  </div>
  {svg_segments(matches)}
  <p class="helper">前期领先（4 分钟经济差 &gt; 0）{agg['conversion']['leadGames']} 局，胜率
  {agg['conversion']['leadWin']:.0f}%；前期落后/持平 {agg['conversion']['behindGames']} 局，胜率
  {agg['conversion']['behindWin']:.0f}%。差值就是这套体系里"前期优势转化"的效率。</p>
</div>

<h2>资源与产出</h2>
<div class="cards">
  <div class="card"><div class="label">十人经济排名均值</div><div class="value">{totals['econRank']:.1f}</div></div>
  <div class="card"><div class="label">队内经济占比</div><div class="value">{totals['econPct']:.0f}%</div></div>
  <div class="card"><div class="label">同序位压钱胜率</div><div class="value">{totals['laneWinRate']:.0f}%</div></div>
  <div class="card"><div class="label">场均评分</div><div class="value">{totals['grade']:.1f}</div></div>
  <div class="card"><div class="label">场均对英雄输出</div><div class="value">{totals['damage'] / 1000:.1f}k</div></div>
  <div class="card"><div class="label">场均承伤</div><div class="value">{totals['taken'] / 1000:.1f}k</div></div>
  <div class="card"><div class="label">场均参团</div><div class="value">{totals['joinPct']:.0f}%</div></div>
  <div class="card"><div class="label">场均补刀</div><div class="value">{totals['soldier']:.0f}</div></div>
</div>

<h2>六维画像 <span class="helper">（以个人 90 分位归一，外圈=自己的巅峰状态）</span></h2>
<div class="panel" style="max-width:340px;margin:0 auto">{radar}</div>

<h2>胜败因子 <span class="helper">（胜局均值 vs 败局均值，相关性非因果）</span></h2>
<div class="panel">{diverging}</div>

<h2>禁用频率 <span class="helper">（双方合计 · {sum(agg['bans'].values())} 次）</span></h2>
<div class="panel">{ban_bars}</div>

<h2>英雄池</h2>
<div class="panel">{hero_bars}</div>

<h2>逐局明细</h2>
<table><thead><tr><th>时间</th><th>英雄</th><th>胜负</th><th>KDA</th><th>评分</th><th>经济</th><th>经济排名</th><th>队内占比</th><th>对英雄输出</th><th>承伤</th><th>参团</th><th>补刀</th><th>对位差</th></tr></thead>
<tbody>{match_rows}</tbody></table>
<p class="helper">数据来源：营地登录态接口（battledetail 十人面板）+ 公开接口（英雄名）。
生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}。非官方工具，仅用于赛训分析。</p>
</body></html>"""


def main(argv):
    camp_user_id = argv[1] if len(argv) > 1 else '540599032'
    refresh = '--refresh-list' in argv
    matches, bans = load_matches(camp_user_id, refresh)
    if not matches:
        raise SystemExit('没有可分析的对局：先在采集通道页同步，或 --refresh-list 刷新列表')
    agg = aggregate(matches, bans)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f'camp-insights-{camp_user_id}.html'
    out.write_text(build_report(camp_user_id, agg), encoding='utf-8')
    print(f'报告已生成：{out}（{len(matches)} 局）')


if __name__ == '__main__':
    main(sys.argv)
