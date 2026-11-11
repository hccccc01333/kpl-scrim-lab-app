"""生成「单局复盘一页纸」的样张 HTML（纯静态，未接入产品）。

用法：python scripts/mock_report_page.py
输出：docs/mockups/report-single-match.html
数据取自一局真实对局（/api/matches/<key> 的返回），只为看排版效果。
"""
from __future__ import annotations

import html
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(r'D:\tmp\match.json')
OUT = ROOT / 'docs' / 'mockups' / 'report-single-match.html'

LANES = ('对抗路', '打野', '中路', '发育路', '游走')


def esc(value):
    return html.escape(str(value if value is not None else ''))


def num(value):
    return value if isinstance(value, (int, float)) else None


def signed(value, digits=0):
    if value is None:
        return '—'
    return f'{"+" if value > 0 else ""}{value:,.{digits}f}'


def clock(seconds):
    seconds = int(seconds or 0)
    return f'{seconds // 60}:{seconds % 60:02d}'


def gold10(process, own_camp):
    points = (process or {}).get('timeline') or []
    best = None
    for point in points:
        t = num(point.get('gameTime'))
        blue, red = num(point.get('blueGold')), num(point.get('redGold'))
        if t is None or blue is None or red is None:
            continue
        if best is None or abs(t - 600) < abs(best[0] - 600):
            best = (t, blue - red)
    if best is None:
        return None, None
    diff = best[1] if own_camp == 'blue' else -best[1]
    return diff, best[0]


def build(data):
    own = data.get('ownCamp') or 'blue'
    foe = 'red' if own == 'blue' else 'blue'
    draft = data.get('draft') or {}
    picks = draft.get('picks') or {}
    own_side = 'left' if own == 'blue' else 'right'
    foe_side = 'right' if own_side == 'left' else 'left'
    own_heroes = [p.get('name') for p in (picks.get(own_side) or [])]
    foe_heroes = [p.get('name') for p in (picks.get(foe_side) or [])]

    players = [p for p in (data.get('players') or []) if p.get('camp') == own]
    players.sort(key=lambda p: LANES.index(p['position']) if p.get('position') in LANES else 9)
    totals = ((data.get('teamTotals') or {}).get(own) or {}).get('totals') or {}
    foe_totals = ((data.get('teamTotals') or {}).get(foe) or {}).get('totals') or {}

    diff10, t10 = gold10(data.get('process'), own)
    final_diff = None
    if num(totals.get('gold')) is not None and num(foe_totals.get('gold')) is not None:
        final_diff = totals['gold'] - foe_totals['gold']
    scores = data.get('scores') or {}
    kills_own = scores.get(own)
    kills_foe = scores.get(foe)
    duration = data.get('duration') or 0

    facts = data.get('bpFacts') or {}
    ladder = (facts.get('ladder') or {}).get('lanes') or []
    kpl = facts.get('kpl') or {}

    # 结论句：只陈述能算的
    parts = []
    if diff10 is not None:
        parts.append(f'10 分钟经济差 <b>{signed(diff10)}</b>')
    if kills_own is not None and kills_foe is not None:
        parts.append(f'击杀 <b>{int(kills_own)} : {int(kills_foe)}</b>')
    judgeable = [row for row in ladder if row.get('n')]
    if judgeable:
        even = sum(1 for row in judgeable if row.get('state') == 'even')
        parts.append(f'巅峰千强五路对位可判 {len(judgeable)} 路，其中 <b>{even}</b> 路打平')
    else:
        parts.append('五路对位在巅峰千强都没有可用样本')
    conclusion = '，'.join(parts)

    # KPI 四格
    kpis = [
        ('10 分钟经济差', signed(diff10), f'第 {clock(t10)} 读取' if t10 else '无时间轴'),
        ('终局经济差', signed(final_diff), '十人结算面板'),
        ('击杀', f'{int(kills_own or 0)} : {int(kills_foe or 0)}', '本局'),
        ('时长', clock(duration), '从开局到结算'),
    ]

    lane_rows = []
    for row in ladder:
        state = {'ahead': ('我方占优', 'ok'), 'behind': ('我方吃亏', 'bad'),
                 'even': ('打平', 'flat')}.get(row.get('state'), ('无样本', 'muted'))
        if row.get('n'):
            detail = (f"巅峰千强 {row['n']:,} 局 · 实际 {row['wr']}% vs 预期 {row['expected']}% "
                      f"· 超额 {signed(row['excess'], 1)}")
        else:
            picks_txt = []
            if row.get('minePick') is not None:
                picks_txt.append(f"我方使用率 {row['minePick']}%")
            if row.get('foePick') is not None:
                picks_txt.append(f"对手使用率 {row['foePick']}%")
            detail = '、'.join(picks_txt) + '，低于 3% 门槛'
        lane_rows.append(f"""<tr><td class="lane">{esc(row.get('lane'))}</td>
      <td>{esc(row.get('mine'))} <i>vs</i> {esc(row.get('foe'))}</td>
      <td><span class="tag {state[1]}">{state[0]}</span></td>
      <td class="note">{detail}</td></tr>""")

    player_rows = []
    for p in players:
        gold = num(p.get('gold'))
        gpm = gold / (duration / 60) if gold and duration else None
        damage = num(p.get('damage'))
        share = (damage / totals['damage'] * 100) if damage and totals.get('damage') else None
        kda = f"{int(p.get('kills') or 0)} / {int(p.get('deaths') or 0)} / {int(p.get('assists') or 0)}"
        player_rows.append(f"""<tr><td class="lane">{esc(p.get('position'))}</td>
      <td><b>{esc(p.get('hero'))}</b></td>
      <td class="num">{'—' if gpm is None else f'{gpm:,.0f}'}</td>
      <td class="num">{'—' if share is None else f'{share:.1f}%'}</td>
      <td class="num">{'—' if p.get('participation') is None else f'{p.get("participation"):.0f}%'}</td>
      <td class="num">{kda}</td></tr>""")

    # 关键节点：用经济时间轴上的拐点（不猜击杀，事件流里只有经济采样）
    timeline = []
    sign = 1 if own == 'blue' else -1
    for point in ((data.get('process') or {}).get('timeline') or []):
        t = num(point.get('gameTime'))
        blue, red = num(point.get('blueGold')), num(point.get('redGold'))
        if t is None or blue is None or red is None:
            continue
        timeline.append((float(t), (blue - red) * sign))
    timeline.sort()
    nodes = []
    if timeline:
        for mark in (1000, 3000, 6000):
            hit = next((t for t, diff in timeline if diff >= mark), None)
            if hit is not None:
                nodes.append((hit, f'拉开到 +{mark:,}', '经济差首次越过这条线'))
        peak_t, peak = max(timeline, key=lambda item: item[1])
        end_t, end_diff = timeline[-1]
        if abs(peak_t - end_t) < 30:
            nodes.append((end_t, f'终局 {signed(end_diff)}', '本局经济差最高点，也是最后一次采样'))
        else:
            nodes.append((peak_t, f'优势最大 {signed(peak)}', '本局经济差最高点'))
            nodes.append((end_t, f'终局 {signed(end_diff)}', '最后一次采样'))
    nodes_html = ''.join(
        f'<li><span class="t">{clock(t)}</span><span class="n">{esc(label)}</span>'
        f'<span class="d">{esc(text)}</span></li>' for t, label, text in nodes) or '<li class="muted">本局没有经济时间轴</li>'

    kpl_hits = (kpl.get('pairs') or [])[:2] + (kpl.get('trios') or [])[:1]
    kpl_html = ' · '.join(f"{' + '.join(h['heroes'])}（{h['n']} 场）" for h in kpl_hits) or '无'

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>单局复盘 · {esc(data.get('date'))}</title>
<style>
  @page {{ size: A4; margin: 14mm 13mm; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 18mm 15mm; background: #eceeef; color: #1d2a2e;
         font: 12.5px/1.65 "Microsoft YaHei", "PingFang SC", "Noto Sans SC", sans-serif;
         -webkit-font-smoothing: antialiased; }}
  .page {{ width: 210mm; min-height: 297mm; margin: 0 auto; padding: 15mm 14mm;
           background: #fff; box-shadow: 0 10px 40px rgba(15,46,41,.14); }}
  .brand {{ display: flex; justify-content: space-between; align-items: baseline;
            border-bottom: 2px solid #176B69; padding-bottom: 7px; }}
  .brand b {{ color: #0F2E29; letter-spacing: .04em; }}
  .brand span {{ color: #7d8c8f; font-size: 11px; }}
  h1 {{ font-size: 25px; line-height: 1.3; margin: 14px 0 6px; color: #0F2E29; letter-spacing: .01em; }}
  .meta {{ color: #6b7b7e; font-size: 12px; }}
  .meta i {{ font-style: normal; margin: 0 8px; color: #b9c4c6; }}
  .win {{ color: #176B69; font-weight: 700; }}
  .kpis {{ display: flex; gap: 10px; margin: 16px 0 4px; }}
  .kpi {{ flex: 1; border: 1px solid #e3e8e8; border-radius: 6px; padding: 9px 11px; }}
  .kpi span {{ display: block; color: #7d8c8f; font-size: 10.5px; }}
  .kpi b {{ display: block; font-size: 21px; color: #0F2E29; letter-spacing: -.01em;
            font-variant-numeric: tabular-nums; }}
  .kpi small {{ color: #98a6a8; font-size: 10px; }}
  h2 {{ font-size: 13.5px; margin: 20px 0 8px; color: #0F2E29; display: flex; align-items: center; gap: 8px; }}
  h2:before {{ content: ""; width: 3px; height: 14px; background: #176B69; border-radius: 2px; }}
  h2 small {{ color: #98a6a8; font-weight: 400; font-size: 10.5px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11.5px; }}
  th {{ text-align: left; color: #7d8c8f; font-weight: 500; font-size: 10.5px;
        border-bottom: 1px solid #dfe4e5; padding: 5px 6px; }}
  td {{ padding: 6px; border-bottom: 1px solid #f0f3f3; vertical-align: top; }}
  td.lane {{ color: #176B69; font-weight: 600; white-space: nowrap; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .tag {{ font-size: 10px; padding: 1px 7px; border-radius: 999px; white-space: nowrap; }}
  .tag.ok {{ background: #e7f2f0; color: #176B69; }}
  .tag.bad {{ background: #fbeceb; color: #b4453c; }}
  .tag.flat {{ background: #eef1f2; color: #5d6f73; }}
  .tag.muted {{ background: #f6f7f7; color: #98a6a8; }}
  .note {{ color: #7d8c8f; font-size: 10.5px; }}
  .bp {{ display: flex; gap: 10px; }}
  .bp > div {{ flex: 1; border: 1px solid #e3e8e8; border-radius: 6px; padding: 9px 11px; }}
  .bp .side {{ font-size: 10.5px; color: #7d8c8f; margin-bottom: 4px; }}
  .bp .heroes {{ font-size: 12.5px; color: #1d2a2e; }}
  ol.nodes {{ list-style: none; margin: 0; padding: 0; }}
  ol.nodes li {{ display: flex; gap: 10px; padding: 5px 0; border-bottom: 1px dashed #edf0f0; font-size: 11.5px; }}
  ol.nodes .t {{ color: #176B69; font-variant-numeric: tabular-nums; width: 42px; flex: none; }}
  ol.nodes .n {{ color: #1d2a2e; width: 120px; flex: none; }}
  ol.nodes .d {{ color: #6b7b7e; }}
  .foot {{ margin-top: 18px; padding-top: 9px; border-top: 1px solid #e3e8e8;
           color: #98a6a8; font-size: 10px; display: flex; justify-content: space-between; gap: 14px; }}
  .foot b {{ color: #6b7b7e; font-weight: 500; }}
  .src {{ color: #7d8c8f; font-size: 10.5px; margin-top: 6px; }}
  .tag-src {{ display: inline-block; border: 1px solid #dfe4e5; border-radius: 3px;
              padding: 0 5px; margin-right: 5px; font-size: 9.5px; color: #7d8c8f; }}
</style></head>
<body><div class="page">
  <div class="brand"><b>KPL 赛训工作台 · 单局复盘</b><span>样张 v0 · 未接入产品</span></div>

  <h1>{esc(data.get('title') or '训练赛')} <span class="win">· {('胜利' if data.get('result') == 'win' else '失利')}</span></h1>
  <p class="meta">{esc(data.get('date'))}<i>·</i>对阵 {esc(data.get('opponent') or '对手未填')}<i>·</i>{esc(data.get('mode') or '训练赛')}<i>·</i>{clock(duration)}</p>

  <h2>一句话结论</h2>
  <p class="src">{conclusion}。</p>

  <div class="kpis">{''.join(f'<div class="kpi"><span>{esc(k)}</span><b>{v}</b><small>{esc(s)}</small></div>' for k, v, s in kpis)}</div>

  <h2>BP 与对位 <small>对位判定用巅峰千强大盘，超额 = 实际 − 两英雄基准期望</small></h2>
  <div class="bp">
    <div><div class="side">我方（{esc('蓝方' if own == 'blue' else '红方')}）</div><div class="heroes">{' · '.join(esc(h) for h in own_heroes)}</div></div>
    <div><div class="side">对手（{esc('红方' if own == 'blue' else '蓝方')}）</div><div class="heroes">{' · '.join(esc(h) for h in foe_heroes)}</div></div>
  </div>
  <table style="margin-top:10px"><thead><tr><th>分路</th><th>对位</th><th>结论</th><th>依据</th></tr></thead>
  <tbody>{''.join(lane_rows)}</tbody></table>
  <p class="src">赛事命中：{esc(kpl_html)}</p>

  <h2>关键节点 <small>经济时间轴上的拐点（约 30 秒一点，官方回放）</small></h2>
  <ol class="nodes">{nodes_html}</ol>

  <h2>五人数据 <small>分均经济与输出占比来自营地十人面板</small></h2>
  <table><thead><tr><th>分路</th><th>英雄</th><th class="num">分均经济</th><th class="num">输出占比</th><th class="num">参团</th><th class="num">K/D/A</th></tr></thead>
  <tbody>{''.join(player_rows)}</tbody></table>

  <div class="foot"><span>数据范围：本局 · 生成于 2026-11-11 10:40 · 工作台 v1.5.33</span>
  <span>赛训组内部使用</span></div>
  <p class="src"><span class="tag-src">营地十人面板</span><span class="tag-src">官方回放事件</span><span class="tag-src">巅峰千强对位</span><span class="tag-src">KPL 组合</span>
  每个数字都标了来源；缺的数据留空，不估算。</p>
</div></body></html>"""


def main():
    data = json.loads(SRC.read_text(encoding='utf-8'))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(data), encoding='utf-8')
    print('wrote', OUT)


if __name__ == '__main__':
    main()
