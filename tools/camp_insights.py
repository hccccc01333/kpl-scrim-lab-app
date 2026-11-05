"""选手对局分析报告：三级递进（基础图表 → 进阶可视化 → 高级分析）。

    python tools/camp_insights.py 540599032 [--refresh-list]

数据管线：
  morebattlelist（时间/英雄/胜负，本地缓存 data/camp_lists/<id>.json）
  × data/camp_details/<gameSeq>.json（本人完整面板 + 双方 ban）
  → 三级聚合 → 自包含 HTML（内联 SVG，双主题，无外部依赖）。
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

ROOT = ROOT
DETAIL_DIR = Path(os.environ.get('CAMP_DETAIL_DIR', ROOT / 'data' / 'camp_details'))
LIST_DIR = Path(os.environ.get('CAMP_LIST_DIR', ROOT / 'data' / 'camp_lists'))
OUT_DIR = Path(os.environ.get('CAMP_REPORT_DIR', ROOT / 'data' / 'camp_reports'))
INTERVAL = 2.0

PALETTE = {'win': '#C0DD97', 'lose': '#F7C1C1', 'damage': '#D85A30', 'taken': '#378ADD',
           'money': '#639922', 'join': '#7F77DD', 'soldier': '#1D9E75', 'ctrl': '#D4537E',
           'grade': '#BA7517', 'ban': '#854F0B', 'grid': 'var(--grid)', 'text': 'var(--ink)'}


def _num(value):
    try:
        return float(value if value not in (None, '') else 0)
    except (TypeError, ValueError):
        return 0.0


def esc(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def fetch_list(camp_user_id: str, refresh: bool = False, max_pages: int = 8) -> list:
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
        stats = None
        for roles_key in ('blueRoles', 'redRoles'):
            for role in data.get(roles_key) or []:
                if str((role.get('basicInfo') or {}).get('roleId') or '') == str(head.get('roleId') or ''):
                    stats = role.get('battleStats') or {}
                    break
        if not stats:
            continue
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
        })
    matches.sort(key=lambda m: m['dt'])
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
    totals = {'games': total, 'wins': wins,
              'winRate': wins / max(total, 1) * 100,
              'kda': (sum(m['k'] + m['a'] for m in matches) / max(sum(m['d'] for m in matches), 1)),
              'damage': avg('damage'), 'taken': avg('taken'), 'money': avg('money'),
              'joinPct': avg('joinPct'), 'soldier': avg('soldier'),
              'transRate': avg('transRate'), 'perDeath': avg('perDeath'), 'ctrl': avg('ctrl'),
              'grade': avg('grade')}
    hero_pool = defaultdict(lambda: {'games': 0, 'wins': 0, 'k': 0, 'd': 0, 'a': 0,
                                     'damage': 0.0, 'soldier': 0.0})
    for m in matches:
        pool = hero_pool[m['hero']]
        pool['games'] += 1
        pool['wins'] += 1 if m['win'] else 0
        pool['k'] += m['k']
        pool['d'] += m['d']
        pool['a'] += m['a']
        pool['damage'] += m['damage']
        pool['soldier'] += m['soldier']
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
        delta = (w_avg - l_avg) / abs(l_avg) * 100 if l_avg else 0
        factors.append({'label': label, 'win': w_avg, 'lose': l_avg, 'delta': delta})
    factors.sort(key=lambda item: -abs(item['delta']))
    grades = [m['grade'] for m in matches if m['grade']]
    streaks, current, current_kind = [], 0, None
    for m in matches:
        kind = m['win']
        if current_kind is None or kind == current_kind:
            current += 1
        else:
            streaks.append((current_kind, current))
            current = 1
        current_kind = kind
    if current_kind is not None:
        streaks.append((current_kind, current))
    recent = matches[-5:]
    earlier = matches[:-5][-5:] if len(matches) > 5 else []
    form = {'recent': {'games': len(recent), 'wins': sum(1 for m in recent if m['win']),
                       'damage': sum(m['damage'] for m in recent) / max(len(recent), 1),
                       'kda': (sum(m['k'] + m['a'] for m in recent) / max(sum(m['d'] for m in recent), 1))},
            'earlier': {'games': len(earlier), 'wins': sum(1 for m in earlier if m['win']),
                        'damage': sum(m['damage'] for m in earlier) / max(len(earlier), 1),
                        'kda': (sum(m['k'] + m['a'] for m in earlier) / max(sum(m['d'] for m in earlier), 1))}}
    return {'matches': matches, 'totals': totals, 'hero_pool': hero_pool, 'bans': bans,
            'radar': radar, 'factors': factors,
            'grade_hist': Counter(min(int(g // 2) * 2, 12) for g in grades),
            'streaks': streaks, 'form': form}


def svg_head(width, height, title):
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
            f'xmlns="http://www.w3.org/2000/svg"><title>{esc(title)}</title>')


def bars_chart(rows, color, unit='', width=640):
    max_value = max((value for _, value, _ in rows), default=1) or 1
    row_h = 24
    height = len(rows) * row_h + 6
    parts = [svg_head(width, height, '条形图')]
    for index, (label, value, suffix) in enumerate(rows):
        y = index * row_h + 3
        bar_w = max(2, (width - 210) * value / max_value)
        parts.append(f'<text x="0" y="{y + 14}" font-size="12" fill="var(--ink)">{esc(label)[:14]}</text>')
        parts.append(f'<rect x="150" y="{y}" width="{bar_w:.0f}" height="15" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{150 + bar_w + 6:.0f}" y="{y + 14}" font-size="12" '
                     f'fill="var(--ink)">{value}{suffix}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def timeline_chart(matches, width=640, height=150):
    if not matches:
        return ''
    step = min(26, (width - 60) / max(len(matches), 1))
    parts = [svg_head(width, height, '胜负时间线')]
    for index, m in enumerate(matches):
        x = 30 + index * step
        color = '#97C459' if m['win'] else '#F09595'
        parts.append(f'<rect x="{x:.0f}" y="18" width="{min(step - 4, 18)}" height="88" rx="3" fill="{color}"/>')
        if index % max(1, len(matches) // 10) == 0:
            parts.append(f'<text x="{x + 6:.0f}" y="122" font-size="11" fill="var(--muted)" '
                         f'text-anchor="middle">{esc(m["time"][:5])}</text>')
    parts.append(f'<text x="30" y="140" font-size="11" fill="var(--muted)">绿=胜 红=负 · 共 {len(matches)} 局</text>')
    parts.append('</svg>')
    return ''.join(parts)


def trend_chart(matches, width=640, height=200):
    if len(matches) < 2:
        return '<p class="helper">局数不足，无法绘制趋势。</p>'
    inner_w, inner_h = width - 70, height - 60
    keys = [('damage', '#D85A30', '对英雄输出'), ('taken', '#378ADD', '承伤'), ('money', '#639922', '经济')]
    scale = max(max(m[key] for m in matches) for key, _, _ in keys) * 1.1 or 1
    step = inner_w / (len(matches) - 1)
    parts = [svg_head(width, height, '数值趋势')]
    for grid_y in range(5):
        y = 20 + inner_h * grid_y / 4
        parts.append(f'<line x1="36" y1="{y:.0f}" x2="{width - 20}" y2="{y:.0f}" '
                     f'stroke="var(--grid)" stroke-width="0.5"/>')
        parts.append(f'<text x="0" y="{y + 4:.0f}" font-size="10" fill="var(--muted)">'
                     f'{scale * (4 - grid_y) / 4 / 1000:.0f}k</text>')
    for index, m in enumerate(matches):
        x = 36 + index * step
        color = '#97C459' if m['win'] else '#F09595'
        parts.append(f'<rect x="{x - max(step - 6, 2) / 2:.1f}" y="20" width="{max(step - 6, 2):.1f}" '
                     f'height="{inner_h}" fill="{color}" opacity="0.35"/>')
    for key, color, _label in keys:
        points = ' '.join(f'{36 + index * step:.1f},{20 + inner_h - inner_h * m[key] / scale:.1f}'
                          for index, m in enumerate(matches))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.8"/>')
    for index, m in enumerate(matches):
        if index % max(1, len(matches) // 9) == 0:
            parts.append(f'<text x="{36 + index * step:.0f}" y="{height - 24}" font-size="10" '
                         f'fill="var(--muted)" text-anchor="middle">{esc(m["time"][:5])}</text>')
    legend_x = 36
    for _, color, label in keys:
        parts.append(f'<rect x="{legend_x}" y="{height - 12}" width="10" height="10" fill="{color}"/>')
        parts.append(f'<text x="{legend_x + 14}" y="{height - 3}" font-size="11" fill="var(--ink)">{label}</text>')
        legend_x += 96
    parts.append('</svg>')
    return ''.join(parts)


def radar_chart(radar, size=280):
    center, radius = size / 2, size / 2 - 46
    axes = len(radar)
    points = []
    polygon = []
    for index, dim in enumerate(radar):
        angle = -90 + index * 360 / axes
        rad = angle * 3.14159265 / 180
        x = center + radius * dim['norm'] * (1 if index == 0 else 1) * (
            (rad != 0) and __import__('math').cos(rad) or 0) if False else 0
    # 六边形坐标
    import math
    coords = []
    for index, dim in enumerate(radar):
        angle = math.radians(-90 + index * 360 / axes)
        coords.append((center + radius * math.cos(angle), center + radius * math.sin(angle)))
    parts = [svg_head(size, size + 20, '六维画像')]
    for ring in (0.25, 0.5, 0.75, 1.0):
        ring_pts = ' '.join(f'{center + radius * ring * math.cos(math.radians(-90 + i * 360 / axes)):.1f},'
                            f'{center + radius * ring * math.sin(math.radians(-90 + i * 360 / axes)):.1f}'
                            for i in range(axes))
        parts.append(f'<polygon points="{ring_pts}" fill="none" stroke="var(--grid)" stroke-width="0.5"/>')
    for index, dim in enumerate(radar):
        angle = math.radians(-90 + index * 360 / axes)
        x, y = center + radius * math.cos(angle), center + radius * math.sin(angle)
        parts.append(f'<line x1="{center}" y1="{center}" x2="{x:.1f}" y2="{y:.1f}" '
                     f'stroke="var(--grid)" stroke-width="0.5"/>')
        lx = center + (radius + 18) * math.cos(angle)
        ly = center + (radius + 14) * math.sin(angle)
        anchor = 'middle' if abs(math.cos(angle)) < 0.3 else ('start' if math.cos(angle) > 0 else 'end')
        parts.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="11" fill="var(--muted)" '
                     f'text-anchor="{anchor}">{esc(dim["label"])}</text>')
        value_x = center + (radius - 4) * dim['norm'] * math.cos(angle)
        value_y = center + (radius - 4) * dim['norm'] * math.sin(angle)
        polygon.append(f'{value_x:.1f},{value_y:.1f}')
    parts.append(f'<polygon points="{" ".join(polygon)}" fill="#7F77DD" opacity="0.28" '
                 f'stroke="#534AB7" stroke-width="1.5"/>')
    for index, dim in enumerate(radar):
        angle = math.radians(-90 + index * 360 / axes)
        vx = center + (radius - 4) * dim['norm'] * math.cos(angle)
        vy = center + (radius - 4) * dim['norm'] * math.sin(angle)
        parts.append(f'<circle cx="{vx:.1f}" cy="{vy:.1f}" r="3" fill="#534AB7"/>')
        parts.append(f'<text x="{vx + 6:.1f}" y="{vy - 4:.1f}" font-size="10" fill="var(--ink)">'
                     f'{dim["avg"]:.1f}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def diverging_chart(factors, width=640):
    row_h = 26
    height = len(factors) * row_h + 10
    max_delta = max((abs(f['delta']) for f in factors), default=1) or 1
    half = (width - 260) / 2
    parts = [svg_head(width, height, '胜败因子对比')]
    for index, factor in enumerate(factors):
        y = index * row_h + 6
        bar = half * min(1, abs(factor['delta']) / max_delta)
        color = '#97C459' if factor['delta'] >= 0 else '#F09595'
        x = width / 2 + 30 if factor['delta'] >= 0 else width / 2 + 30 - bar
        parts.append(f'<text x="0" y="{y + 14}" font-size="12" fill="var(--ink)">{esc(factor["label"])}</text>')
        parts.append(f'<text x="{width / 2 - 40:.0f}" y="{y + 14}" font-size="11" fill="var(--muted)" '
                     f'text-anchor="end">{factor["lose"]:.1f}</text>')
        parts.append(f'<rect x="{x:.1f}" y="{y}" width="{bar:.1f}" height="14" rx="3" fill="{color}"/>')
        parts.append(f'<text x="{x + bar + 6 if factor["delta"] >= 0 else x - 6:.1f}" y="{y + 14}" '
                     f'font-size="12" fill="var(--ink)" text-anchor="{"start" if factor["delta"] >= 0 else "end"}">'
                     f'{factor["delta"]:+.0f}%</text>')
    parts.append(f'<text x="{width / 2 + 30 - half:.0f}" y="{height}" font-size="11" '
                 f'fill="var(--muted)">← 败局更高</text>')
    parts.append(f'<text x="{width / 2 + 30 + half:.0f}" y="{height}" font-size="11" '
                 f'fill="var(--muted)" text-anchor="end">胜局更高 →</text>')
    parts.append('</svg>')
    return ''.join(parts)


def histogram(grades, width=640):
    order = [0, 2, 4, 6, 8, 10, 12]
    counts = {bucket: grades.get(bucket, 0) for bucket in order}
    max_count = max(counts.values()) or 1
    bar_w = (width - 80) / len(order) - 10
    height = 130
    parts = [svg_head(width, height, '评分分布')]
    for index, bucket in enumerate(order):
        count = counts[bucket]
        bar = max(2, inner_h_local(count, max_count, 70))
        x = 40 + index * (bar_w + 10)
        parts.append(f'<rect x="{x:.0f}" y="{100 - bar:.0f}" width="{bar_w:.0f}" height="{bar:.0f}" '
                     f'rx="3" fill="#BA7517"/>')
        parts.append(f'<text x="{x + bar_w / 2:.0f}" y="{92 - bar:.0f}" font-size="11" fill="var(--ink)" '
                     f'text-anchor="middle">{count}</text>')
        parts.append(f'<text x="{x + bar_w / 2:.0f}" y="118" font-size="11" fill="var(--muted)" '
                     f'text-anchor="middle">{bucket}–{bucket + 2}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def inner_h_local(value, max_value, height):
    return height * value / (max_value or 1)


def build_report(camp_user_id: str, agg) -> str:
    totals = agg['totals']
    hero_rows = sorted(agg['hero_pool'].items(), key=lambda kv: -kv[1]['games'])
    hero_bars = bars_chart([(f'{hero}（{info["games"]}局 {info["wins"]}胜）', info['games'], '局')
                            for hero, info in hero_rows[:10]], '#185FA5')
    ban_bars = bars_chart([(name, count, '次') for name, count in agg['bans'].most_common(10)],
                          '#854F0B')
    timeline = timeline_chart(agg['matches'])
    trend = trend_chart(agg['matches'])
    radar = radar_chart(agg['radar'])
    diverging = diverging_chart(agg['factors'])
    grade_hist = histogram(agg['grade_hist'])
    hero_detail_rows = ''.join(
        f'<tr><td>{esc(hero)}</td><td>{info["games"]}</td>'
        f'<td>{info["wins"] / info["games"] * 100:.0f}%</td>'
        f'<td>{(info["k"] + info["a"]) / max(info["d"], 1):.2f}</td>'
        f'<td>{info["damage"] / info["games"] / 1000:.1f}k</td>'
        f'<td>{info["soldier"] / info["games"]:.0f}</td></tr>'
        for hero, info in hero_rows)
    match_rows = ''.join(
        f'<tr><td>{esc(m["time"])}</td><td>{esc(m["hero"])}</td>'
        f'<td class="{"win" if m["win"] else "lose"}">{"胜" if m["win"] else "负"}</td>'
        f'<td>{m["k"]}/{m["d"]}/{m["a"]}</td><td>{m["grade"]:.1f}</td>'
        f'<td>{m["damage"] / 1000:.1f}k</td><td>{m["taken"] / 1000:.1f}k</td>'
        f'<td>{m["money"] / 1000:.1f}k</td><td>{m["joinPct"]:.0f}%</td><td>{m["soldier"]:.0f}</td>'
        f'<td>{m["ctrl"]:.0f}s</td><td>{m["transRate"]:.2f}</td></tr>'
        for m in reversed(agg['matches']))
    streak_text = ' · '.join(f"{'连胜' if kind else '连败'}{count}" for kind, count in agg['streaks'][-6:])
    factor_rows = ''.join(
        f'<div class="factor"><span>{esc(f["label"])}</span>'
        f'<span>胜局 {f["win"]:.1f} · 败局 {f["lose"]:.1f}</span>'
        f'<span class="{"pos" if f["delta"] >= 0 else "neg"}">{f["delta"]:+.0f}%</span></div>'
        for f in agg['factors'][:5])
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>营地对局分析 · {esc(camp_user_id)}</title>
<style>
:root{{--ink:#222;--muted:#777;--grid:#e5e3da;--card:#fff;--bg:#fafafa;--line:#e3e1d8;
      --accent:#534AB7}}
@media (prefers-color-scheme:dark){{:root{{--ink:#eee;--muted:#9a9a9a;--grid:#3a3a3a;
      --card:#1e1e22;--bg:#141416;--line:#333;--accent:#AFA9EC}}}}
body{{font-family:system-ui,'Microsoft YaHei',sans-serif;margin:0 auto;max-width:760px;
     color:var(--ink);background:var(--bg);padding:24px 16px}}
h1{{font-size:20px;font-weight:500;margin:0 0 4px}} h2{{font-size:15px;font-weight:500;margin:34px 0 12px}}
.level{{font-size:11px;padding:2px 8px;border-radius:999px;vertical-align:2px;margin-right:8px}}
.l1{{background:#EAF3DE;color:#3B6D11}}.l2{{background:#FAEEDA;color:#854F0B}}.l3{{background:#E6F1FB;color:#185FA5}}
.sub{{color:var(--muted);font-size:13px;margin-bottom:18px}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}}
.label{{font-size:12px;color:var(--muted)}} .value{{font-size:19px;font-weight:500;margin-top:2px}}
.panel{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:14px}}
table{{border-collapse:collapse;width:100%;font-size:12px}}
th,td{{border:1px solid var(--line);padding:4px 8px;text-align:center}}
th{{background:var(--background-secondary,var(--card));font-weight:500}}
.win{{color:#3B6D11}}.lose{{color:#A32D2D}}
.factor{{display:flex;justify-content:space-between;padding:6px 0;border-top:1px solid var(--line);font-size:13px}}
.factor:first-child{{border-top:none}}
.pos{{color:#3B6D11}}.neg{{color:#A32D2D}}
nav{{display:flex;gap:10px;margin:14px 0}} nav a{{font-size:13px;color:var(--accent);text-decoration:none}}
.helper{{color:var(--muted);font-size:12px}}
</style></head><body>
<h1>营地对局分析 · {esc(camp_user_id)}</h1>
<p class="sub">生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')} · 数据来源：营地登录态接口 ·
共 {totals['games']} 局有完整面板 · 连胜段：{esc(streak_text or '—')}</p>
<nav><a href="#l1">① 基础图表</a><a href="#l2">② 进阶可视化</a><a href="#l3">③ 高级分析</a><a href="#detail">逐局明细</a></nav>

<h2 id="l1"><span class="level l1">基础</span>一页看懂</h2>
<div class="cards">
  <div class="card"><div class="label">场次</div><div class="value">{totals['games']}</div></div>
  <div class="card"><div class="label">胜率</div><div class="value">{totals['winRate']:.0f}%</div></div>
  <div class="card"><div class="label">场均 KDA</div><div class="value">{totals['kda']:.2f}</div></div>
  <div class="card"><div class="label">场均评分</div><div class="value">{totals['grade']:.1f}</div></div>
  <div class="card"><div class="label">场均对英雄输出</div><div class="value">{totals['damage'] / 1000:.1f}k</div></div>
  <div class="card"><div class="label">场均承伤</div><div class="value">{totals['taken'] / 1000:.1f}k</div></div>
  <div class="card"><div class="label">场均经济</div><div class="value">{totals['money'] / 1000:.1f}k</div></div>
  <div class="card"><div class="label">场均参团</div><div class="value">{totals['joinPct']:.0f}%</div></div>
</div>
<div class="panel"><h2 style="margin-top:0">胜负时间线</h2>{timeline}</div>
<div class="panel"><h2 style="margin-top:0">英雄池（场次 / 胜负）</h2>{hero_bars}</div>

<h2 id="l2"><span class="level l2">进阶</span>趋势与对手</h2>
<div class="panel"><h2 style="margin-top:0">数值趋势（底色 = 胜 / 负）</h2>{trend}
<p class="helper">输出用对英雄口径（打团贡献）；经济含全部收入。赢的局通常对应哪条线抬高，可以直接目视。</p></div>
<div class="panel"><h2 style="margin-top:0">禁用频率（双方合计 · {sum(agg['bans'].values())} 次）</h2>{ban_bars}
<p class="helper">反映这些局里的版本强禁与对手习惯；样本越大越可信。</p></div>
<div class="panel"><h2 style="margin-top:0">分英雄深度</h2>
<table><thead><tr><th>英雄</th><th>场次</th><th>胜率</th><th>KDA</th><th>场均对英雄输出</th><th>场均补刀</th></tr></thead>
<tbody>{hero_detail_rows}</tbody></table></div>

<h2 id="l3"><span class="level l3">高级</span>画像与因子</h2>
<div class="panel" style="display:flex;gap:18px;flex-wrap:wrap;align-items:center">
  <div style="flex:0 0 300px">{radar}</div>
  <div style="flex:1;min-width:240px"><h2 style="margin-top:0">六维画像说明</h2>
    <p class="helper">六个维度都是营地接口独有口径，以个人 90 分位的场均水平归一——
    越接近外圈代表该维度越接近自己的巅峰状态。中心数值为场均原始值。</p>
    <div class="factor"><span>对英雄输出</span><span>{agg['radar'][0]['avg'] / 1000:.1f}k 场均</span></div>
    <div class="factor"><span>输出转化率</span><span>{agg['radar'][1]['avg']:.2f}</span></div>
    <div class="factor"><span>每死承伤</span><span>{agg['radar'][2]['avg'] / 1000:.1f}k 场均</span></div>
    <div class="factor"><span>参团率</span><span>{agg['radar'][3]['avg']:.0f}%</span></div>
    <div class="factor"><span>补刀</span><span>{agg['radar'][4]['avg']:.0f}</span></div>
    <div class="factor"><span>控制时长</span><span>{agg['radar'][5]['avg']:.0f}s</span></div>
  </div></div>
<div class="panel"><h2 style="margin-top:0">胜败因子对比（胜局均值 vs 败局均值）</h2>{diverging}
<p class="helper">样本 {totals['games']} 局，为相关性而非因果；差值越大说明该指标与胜负的关联越强，训练时可优先关注。</p></div>
<div class="panel" style="display:flex;gap:18px;flex-wrap:wrap">
  <div style="flex:1;min-width:280px"><h2 style="margin-top:0">评分分布</h2>{grade_hist}</div>
  <div style="flex:1;min-width:240px"><h2 style="margin-top:0">状态对比（近 5 局 vs 之前 5 局）</h2>
    <div class="factor"><span>胜率</span><span>{agg['form']['earlier']['wins'] / max(agg['form']['earlier']['games'], 1) * 100:.0f}% →
      {agg['form']['recent']['wins'] / max(agg['form']['recent']['games'], 1) * 100:.0f}%</span></div>
    <div class="factor"><span>场均对英雄输出</span><span>{agg['form']['earlier']['damage'] / 1000:.1f}k →
      {agg['form']['recent']['damage'] / 1000:.1f}k</span></div>
    <div class="factor"><span>场均 KDA</span><span>{agg['form']['earlier']['kda']:.2f} →
      {agg['form']['recent']['kda']:.2f}</span></div>
    <p class="helper">箭头前后分别为"之前 5 局 → 近 5 局"。</p></div>
</div>

<h2 id="detail"><span class="level l2">明细</span>逐局数据</h2>
<table><thead><tr><th>时间</th><th>英雄</th><th>胜负</th><th>KDA</th><th>评分</th><th>对英雄输出</th><th>承伤</th><th>经济</th><th>参团</th><th>补刀</th><th>控制</th><th>转化率</th></tr></thead>
<tbody>{match_rows}</tbody></table>
<p class="helper">数据来源：营地登录态接口（battledetail），数值为官方口径；生成于
{datetime.now().strftime('%Y-%m-%d %H:%M')}。非官方工具，仅用于赛训分析。</p>
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
    print(f'报告已生成：{out}（{len(matches)} 局，{len(bans)} 个禁用英雄）')


if __name__ == '__main__':
    main(sys.argv)
