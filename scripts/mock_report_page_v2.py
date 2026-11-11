"""生成「单局复盘赛报」v2 样张（纯静态，未接入产品）。

这一版针对上一版的两个硬伤重做：
* **没重点** —— 加一个占 1/3 页的核心判断区：一句人话 + 三个支撑数字，
  不再把一堆数字平铺成表格。
* **没报告感** —— 加报告抬头（编号 / 呈报 / 密级）、编号化的发现（01 02 03）、
  页脚页码与数据口径，形态上像一份正式呈报的材料。

用法：python scripts/mock_report_page_v2.py
输出：docs/mockups/report-v2.html
"""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path(r'D:\tmp\match.json')
OUT = ROOT / 'docs' / 'mockups' / 'report-v2.html'

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


def series(process, own):
    sign = 1 if own == 'blue' else -1
    out = []
    for point in (process or {}).get('timeline') or []:
        t, blue, red = num(point.get('gameTime')), num(point.get('blueGold')), num(point.get('redGold'))
        if t is None or blue is None or red is None:
            continue
        out.append((float(t), (blue - red) * sign))
    return sorted(out)


def at(points, seconds):
    if not points:
        return None
    near = min(points, key=lambda item: abs(item[0] - seconds))
    return near[1]


def build(data):
    own = data.get('ownCamp') or 'blue'
    foe = 'red' if own == 'blue' else 'blue'
    draft = data.get('draft') or {}
    picks = draft.get('picks') or {}
    own_side = 'left' if own == 'blue' else 'right'
    foe_side = 'right' if own_side == 'left' else 'left'
    own_heroes = [p.get('name') for p in (picks.get(own_side) or [])]
    foe_heroes = [p.get('name') for p in (picks.get(foe_side) or [])]

    players = {(p.get('camp'), p.get('position')): p for p in (data.get('players') or [])}
    own_players = [players.get((own, lane)) for lane in LANES]
    own_players = [p for p in own_players if p]
    duration = float(data.get('duration') or 0) or 1
    totals = ((data.get('teamTotals') or {}).get(own) or {}).get('totals') or {}
    scores = data.get('scores') or {}

    points = series(data.get('process'), own)
    d10 = at(points, 600)
    d4 = at(points, 240)
    final = points[-1][1] if points else None
    mid_gain = (d10 - d4) if (d10 is not None and d4 is not None) else None
    # 10 分钟后对手把差距最小压到多少（反扑幅度）
    after10 = [value for t, value in points if t >= 600]
    drawdown = (d10 - min(after10)) if after10 and d10 is not None else None

    # 各分路终局经济差，找出最大的那条
    lane_rows = []
    for lane in LANES:
        mine, other = players.get((own, lane)), players.get((foe, lane))
        if not mine or not other:
            continue
        g1, g2 = num(mine.get('gold')), num(other.get('gold'))
        diff = (g1 - g2) if g1 is not None and g2 is not None else None
        gpm = (g1 / (duration / 60)) if g1 else None
        lane_rows.append({'lane': lane, 'mine': mine, 'foe': other, 'diff': diff,
                          'gpm': gpm, 'hero': mine.get('hero'), 'foeHero': other.get('hero')})
    engine = max((row for row in lane_rows if row['diff'] is not None),
                 key=lambda row: row['diff'], default=None)

    # 核心判断：一句人话，只用能算出来的东西
    if d10 is not None and final is not None:
        if final > 0 and d10 > 0:
            headline = '对线期就拉开了，之后没给对手翻盘窗口'
        elif final > 0 and d10 <= 0:
            headline = '前期被压，靠中后期一波翻回来'
        elif final < 0 and d10 > 0:
            headline = '前期领先没守住，被翻'
        else:
            headline = '全程被压，没找到翻盘点'
    else:
        headline = '本局缺少经济时间轴，只给能确认的经验'

    support = []
    if d10 is not None:
        support.append(('10 分钟经济差', signed(d10), '官方回放 · 团队金币采样'))
    if mid_gain is not None:
        support.append(('发育期净增', signed(mid_gain), '4→10 分钟'))
    if engine:
        support.append(('最大分路差', f"{engine['lane']} {signed(engine['diff'])}", '营地十人面板'))

    # 编号化发现
    findings = []
    if engine and engine['gpm']:
        findings.append((
            '经济是从这一路滚起来的',
            f"{engine['lane']} {esc(engine['hero'])} 分均 {engine['gpm']:.0f}，"
            f"对位 {esc(engine['foeHero'])} 终局净差 {signed(engine['diff'])}。",
        ))
    if mid_gain is not None:
        findings.append((
            '发育期把差距做大了',
            f"4 分钟 {signed(d4)} → 10 分钟 {signed(d10)}，这段净增 {signed(mid_gain)}。",
        ))
    if drawdown is not None:
        if drawdown < 500:
            findings.append((
                '领先之后没给机会',
                f'10 分钟后差距从 {signed(d10)} 一路走到 {signed(final)}，没被追近。',
            ))
        else:
            findings.append((
                '领先后被追近过一次',
                f'10 分钟后被追近 {signed(-drawdown)}，最低到 {signed(min(after10))}，'
                f'之后重新拉开到 {signed(final)}。',
            ))

    facts = data.get('bpFacts') or {}
    ladder = (facts.get('ladder') or {}).get('lanes') or []
    judgeable = [row for row in ladder if row.get('n')]
    no_sample = [row for row in ladder if not row.get('n')]
    kpl = facts.get('kpl') or {}
    kpl_hits = (kpl.get('pairs') or [])[:2]
    kpl_text = '、'.join(f"{' + '.join(h['heroes'])}（{h['n']} 场）" for h in kpl_hits) or '无'

    lane_html = ''.join(
        f"""<tr><td class="lane">{esc(row['lane'])}</td>
        <td>{esc(row['hero'])} <i>vs</i> {esc(row['foeHero'])}</td>
        <td class="num">{signed(row['diff'])}</td>
        <td class="num">{'—' if not row['gpm'] else f"{row['gpm']:.0f}"}</td>
        <td class="num">{'—' if row['mine'].get('participation') is None else f"{row['mine']['participation']:.0f}%"}</td>
        <td class="num">{'—' if row['mine'].get('deaths') is None else int(row['mine']['deaths'])}</td></tr>"""
        for row in lane_rows)

    finding_html = ''.join(
        f"""<div class="find"><span class="idx">{index:02d}</span>
        <div><b>{esc(title)}</b><p>{text}</p></div></div>"""
        for index, (title, text) in enumerate(findings, 1))

    bp_text = (f"对位可判 {len(judgeable)} 路"
               + (f"（{len(no_sample)} 路样本不足）" if no_sample else '')
               + f"；KPL 出现过 {kpl_text}。")

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>单局复盘赛报</title>
<style>
  @page {{ size: A4; margin: 0; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #dfe3e4; color: #16262a;
        font: 12px/1.7 "Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif; }}
  .page {{ width: 210mm; min-height: 297mm; margin: 0 auto; background: #fff;
           padding: 16mm 15mm 13mm; display: flex; flex-direction: column; }}
  /* 抬头 */
  .masthead {{ display: flex; justify-content: space-between; align-items: flex-end;
               border-bottom: 3px solid #0F2E29; padding-bottom: 8px; }}
  .masthead .title {{ font-size: 11px; letter-spacing: .34em; color: #0F2E29; font-weight: 700; }}
  .masthead .meta {{ font-size: 9.5px; color: #77878a; letter-spacing: .06em; }}
  .masthead .meta b {{ color: #0F2E29; font-weight: 600; }}
  /* 对阵 */
  .versus {{ display: flex; align-items: baseline; justify-content: space-between;
             margin: 12px 0 2px; }}
  .versus h1 {{ margin: 0; font-size: 30px; line-height: 1.15; letter-spacing: -.01em;
                color: #0F2E29; font-weight: 700; }}
  .versus .result {{ font-size: 13px; letter-spacing: .3em; color: #0F6B5E; font-weight: 700; }}
  .subline {{ color: #77878a; font-size: 10.5px; letter-spacing: .04em; }}
  /* 核心判断 */
  .verdict {{ margin: 14px 0 0; padding: 16px 0 14px; border-top: 1px solid #dfe4e4;
              border-bottom: 1px solid #dfe4e4; }}
  .verdict .kicker {{ font-size: 9.5px; letter-spacing: .3em; color: #8a9a9c; margin-bottom: 6px; }}
  .verdict h2 {{ margin: 0; font-size: 27px; line-height: 1.32; color: #0F2E29; font-weight: 700;
                 letter-spacing: -.005em; }}
  .support {{ display: flex; margin-top: 14px; }}
  .support > div {{ flex: 1; padding-right: 12px; }}
  .support > div + div {{ padding-left: 14px; border-left: 1px solid #e6eaea; }}
  .support span {{ display: block; font-size: 9.5px; color: #8a9a9c; letter-spacing: .08em; }}
  .support b {{ display: block; font-size: 19px; color: #0F2E29; font-variant-numeric: tabular-nums;
                letter-spacing: -.01em; }}
  .support small {{ color: #a6b3b4; font-size: 8.5px; }}
  /* 发现 */
  h3 {{ font-size: 9.5px; letter-spacing: .3em; color: #8a9a9c; font-weight: 600;
        margin: 20px 0 8px; }}
  .find {{ display: flex; gap: 12px; padding: 9px 0; border-bottom: 1px dashed #e6eaea; }}
  .find .idx {{ font-size: 15px; color: #c3cfd0; font-weight: 700; letter-spacing: .02em;
                font-variant-numeric: tabular-nums; width: 26px; flex: none; }}
  .find b {{ display: block; font-size: 13.5px; color: #0F2E29; }}
  .find p {{ margin: 2px 0 0; color: #5c6f72; font-size: 11.5px; }}
  /* 表格 */
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th {{ text-align: left; font-weight: 500; font-size: 9.5px; color: #8a9a9c;
        letter-spacing: .06em; padding: 5px 6px; border-bottom: 1px solid #dfe4e4; }}
  td {{ padding: 6px; border-bottom: 1px solid #eef1f1; vertical-align: top; }}
  td.lane {{ color: #0F6B5E; font-weight: 600; white-space: nowrap; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr.total td {{ border-bottom: 2px solid #0F2E29; font-weight: 600; color: #0F2E29; }}
  /* 附录 */
  .appendix {{ margin-top: auto; padding-top: 10px; }}
  .appendix .line {{ display: flex; gap: 10px; font-size: 10px; color: #77878a; }}
  .appendix .line b {{ color: #0F2E29; font-weight: 600; }}
  .foot {{ display: flex; justify-content: space-between; align-items: flex-end;
           margin-top: 10px; padding-top: 7px; border-top: 1px solid #dfe4e4;
           font-size: 9px; color: #a6b3b4; letter-spacing: .05em; }}
  .page-no {{ font-size: 10px; color: #0F2E29; letter-spacing: .18em; }}
</style></head>
<body><div class="page">

  <div class="masthead">
    <div class="title">赛 训 复 盘 报 告</div>
    <div class="meta">编号 <b>R-{esc(str(data.get('date') or '').replace('-', ''))}-01</b> ·
      呈报 <b>赛训组</b> · 密级 <b>内部</b></div>
  </div>

  <div class="versus">
    <h1>{esc(data.get('title') or '训练赛')}</h1>
    <div class="result">{('胜 利' if data.get('result') == 'win' else '失 利')}</div>
  </div>
  <div class="subline">{esc(data.get('date'))} · 对阵 {esc(data.get('opponent') or '未填写')} ·
    {esc(data.get('mode') or '训练赛')} · {clock(duration)} · 击杀 {esc(scores.get(own))} : {esc(scores.get(foe))}</div>

  <div class="verdict">
    <div class="kicker">核 心 判 断</div>
    <h2>{esc(headline)}</h2>
    <div class="support">
      {''.join(f'<div><span>{esc(label)}</span><b>{value}</b><small>{esc(source)}</small></div>'
               for label, value, source in support)}
    </div>
  </div>

  <h3>本 局 三 个 发 现</h3>
  {finding_html}

  <h3>分 路 对 照</h3>
  <table><thead><tr><th>分路</th><th>对位</th><th class="num">终局净差</th>
  <th class="num">分均经济</th><th class="num">参团</th><th class="num">死亡</th></tr></thead>
  <tbody>{lane_html}
    <tr class="total"><td>合计</td><td>五路净差之和</td>
      <td class="num">{signed(sum(r['diff'] for r in lane_rows if r['diff'] is not None))}</td>
      <td class="num">—</td><td class="num">—</td><td class="num">—</td></tr>
  </tbody></table>

  <h3>阵 容 与 对 位 依 据</h3>
  <table><tbody>
    <tr><td class="lane">我方</td><td colspan="5">{' · '.join(esc(h) for h in own_heroes)}</td></tr>
    <tr><td class="lane">对手</td><td colspan="5">{' · '.join(esc(h) for h in foe_heroes)}</td></tr>
    <tr><td class="lane">口径</td><td colspan="5">{esc(bp_text)} 对位判定用巅峰千强，超额 = 实际 − 两英雄基准期望。</td></tr>
  </tbody></table>

  <div class="appendix">
    <div class="line"><b>数据范围</b><span>本局 · 生成于 2026-11-11 · 工作台 v1.5.33</span></div>
    <div class="line"><b>数据来源</b><span>营地十人面板 · 官方回放事件与金币采样 · 巅峰千强对位 · KPL 组合</span></div>
    <div class="foot"><span>缺的数据留空，不估算 · 赛训组内部材料，请勿外传</span><span class="page-no">1 / 1</span></div>
  </div>
</div></body></html>"""


def main():
    data = json.loads(SRC.read_text(encoding='utf-8'))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(data), encoding='utf-8')
    print('wrote', OUT)


if __name__ == '__main__':
    main()
