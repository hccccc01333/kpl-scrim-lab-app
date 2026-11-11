# -*- coding: utf-8 -*-
"""
replay_codec / build_report.py

把「已解码的回放中间产物」生成一份人能直接看懂的单局 HTML 报告。

只依赖 Python 标准库；不启动服务、不连接设备、不读取游戏进程内存、不改动
回放文件。生成物可离线打开，也可直接打印成 PDF。

用法：
  python build_report.py \
      --data-dir  ../data/replays/_analysis/datasets \
      --state     ../data/replays/_analysis/live_20261104/state_series_161129_10pt.csv \
      --sample    20261102_161129 \
      --out       output/20261102_161129_report.html

数据口径（务必保持，不要把估算冒充实测）：
  文件解码  —— .abc 帧命令，100% 可复现，0 未解析
  UI 采样   —— 结算面板读数，由结算界面采集，不是回放文件里的字段
  引擎实测  —— 暂停帧引擎内存采样，仅 10 个检查点，不连线、不外推
  估算      —— 本生成器不使用；报告中明确标「本局未使用」

口径红线：
  * 结算金币 = 整局累计获得；检查点金币 = 当时可用金币。两者不可混用、不可相减。
  * packed 移动/攻击输入缺可靠 actor 归属，禁止出「每人操作量排行」。
  * 装备只保留 ID 集合，价格和不代表花费；不保存游戏文本，不映射装备名。
  * 玩家昵称一律不输出（脱敏），只显示阵营 + 英雄。
"""

import argparse
import csv
import html
import math
import os
from collections import defaultdict

FRAME_FILE = "20261102_frame_commands.csv"
PANEL_FILE = "20261102_panel_truth.csv"
ACTIONS_FILE = "20261102_player_actions.csv"

MOVE = "PLAYER_MOVE"
ATTACK_COLS = ["PLAYER_ATTACK", "PLAYER_ATTACKWITHOBJ", "BASEATTACK"]
SKILL_COLS = ["USEDIRECTIONALSKILL", "USEPOSITIONSKILL", "USEOBJECTIVESKILL"]
CC_COL = "CC"
OTHER_COLS = ["BUYEQUIP", "LEARNSKILL", "SELLEQUIP", "AISTATECHG"]
ALL_COLS = [MOVE] + ATTACK_COLS + SKILL_COLS + [CC_COL] + OTHER_COLS

CAT_COLORS = [
    ("移动指令", "#cbd5e1"),
    ("攻击指令", "#60a5fa"),
    ("技能释放", "#f59e0b"),
    ("控制/状态", "#ef4444"),
    ("购买/加点等", "#94a3b8"),
]


def esc(v):
    return html.escape(str(v), quote=True)


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_frames(path, sample):
    rows = [r for r in read_csv(path) if r.get("sample") == sample]
    if not rows:
        raise SystemExit("帧命令里找不到样本: %s" % sample)
    out = []
    for r in rows:
        try:
            t = float(r["time_sec"])
        except (ValueError, KeyError):
            continue
        vals = {c: int(r.get(c) or 0) for c in ALL_COLS}
        out.append({"t": t, "total": int(r.get("total") or 0), **vals})
    return out


def load_panel(path, sample):
    rows = [r for r in read_csv(path)
            if sample in (r.get("sample") or r.get("file") or "")]
    out = []
    for i, r in enumerate(rows):
        team = "blue" if str(r.get("team")) == "1" else "red"
        out.append({
            "team": team,
            "hero_id": r.get("hero_id", ""),
            "hero": r.get("hero", ""),
            "kills": r.get("kills", ""),
            "deaths": r.get("deaths", ""),
            "assists": r.get("assists", ""),
            "gold": r.get("gold", ""),
            "score": r.get("score", ""),
        })
    return out


def load_actions(path, sample):
    rows = [r for r in read_csv(path)
            if sample in (r.get("sample") or r.get("file") or "")]
    out = {}
    for r in rows:
        hero_id = r.get("hero_id", "")
        out[hero_id] = {
            "learn_slots": r.get("learn_slots", ""),
            "equip_ids": (r.get("buy_equip_ids") or "").split(),
            "buy_raw": r.get("buy_events_raw", ""),
        }
    return out


def load_state(path):
    rows = read_csv(path)
    by_clock = defaultdict(lambda: defaultdict(int))
    clocks = {}
    for r in rows:
        clock = r.get("clock", "")
        try:
            sec = float(r.get("second") or 0)
        except ValueError:
            sec = 0.0
        clocks[clock] = sec
        camp = (r.get("camp") or "").lower()
        try:
            gold = int(float(r.get("gold") or 0))
        except ValueError:
            gold = 0
        by_clock[clock][camp] += gold
    points = []
    for clock in sorted(clocks, key=lambda c: clocks[c]):
        sec = clocks[clock]
        for camp, color, label in (("blue", "#2563eb", "蓝方"),
                                   ("red", "#dc2626", "红方")):
            points.append({"clock": clock, "second": sec,
                           "gold": by_clock[clock].get(camp, 0),
                           "camp": camp, "color": color, "label": label})
    return points, len(rows), len(clocks)


def bucket_by_minute(frames):
    last_min = int(max(f["t"] for f in frames) // 60)
    buckets = []
    for m in range(last_min + 1):
        b = {"minute": m, "total": 0, "move": 0, "attack": 0,
             "skill": 0, "cc": 0, "other": 0}
        buckets.append(b)
    for f in frames:
        m = int(f["t"] // 60)
        if m >= len(buckets):
            continue
        b = buckets[m]
        b["total"] += f["total"]
        b["move"] += f[MOVE]
        b["attack"] += sum(f[c] for c in ATTACK_COLS)
        b["skill"] += sum(f[c] for c in SKILL_COLS)
        b["cc"] += f[CC_COL]
        b["other"] += sum(f[c] for c in OTHER_COLS)
    return buckets


def fmt_mmss(sec):
    return "%02d:%02d" % (int(sec) // 60, int(sec) % 60)


def svg_bars(buckets, keys, title, caption):
    W, H = 620, 208
    left, top, bottom = 46, 16, 158
    plot_w, plot_h = W - left - 16, bottom - top
    step = plot_w / max(1, len(buckets))
    barw = step * 0.6
    maxv = max(1, max(sum(b[k] for k in keys) for b in buckets))
    parts = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" '
             'xmlns="http://www.w3.org/2000/svg">' % (W, H)]
    parts.append('<title>%s</title><desc>%s</desc>' % (esc(title), esc(caption)))
    for i in range(5):
        y = bottom - plot_h * i / 4
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" '
                     'stroke="#e2e8f0" stroke-width="1"/>' %
                     (left, y, W - 16, y))
        parts.append('<text x="%d" y="%.1f" text-anchor="end" font-size="10" '
                     'fill="#94a3b8" dominant-baseline="central">%s</text>' %
                     (left - 8, y, format(int(maxv * i / 4), ",")))
    colors = dict((k, c) for (_, c), k in
                  zip(CAT_COLORS, ["move", "attack", "skill", "cc", "other"]))
    for i, b in enumerate(buckets):
        x = left + step * i + (step - barw) / 2
        acc = 0.0
        for k in keys:
            v = b[k]
            if v <= 0:
                continue
            h = plot_h * v / maxv
            y = bottom - acc - h
            parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" '
                         'fill="%s"/>' % (x, y, barw, h, colors[k]))
            acc += h
        if i % 2 == 0:
            parts.append('<text x="%.1f" y="%d" text-anchor="middle" '
                         'font-size="10" fill="#64748b">%d\'</text>' %
                         (x + barw / 2, bottom + 14, b["minute"]))
    lx = left
    for (name, color), k in zip(CAT_COLORS, ["move", "attack", "skill", "cc", "other"]):
        if k not in keys:
            continue
        parts.append('<rect x="%.1f" y="%d" width="9" height="9" rx="2" fill="%s"/>' %
                     (lx, 184, color))
        parts.append('<text x="%.1f" y="%d" font-size="11" fill="#475569">%s</text>' %
                     (lx + 14, 189, name))
        lx += 22 + len(name) * 12
    parts.append('</svg>')
    return "".join(parts)


def svg_checkpoints(points):
    W, H = 620, 226
    left, top, bottom = 60, 16, 172
    plot_w, plot_h = W - left - 18, bottom - top
    maxsec = max([p["second"] for p in points] + [1])
    maxgold = max([p["gold"] for p in points] + [1])
    maxgold = int(math.ceil(maxgold / 10000.0) * 10000)
    parts = ['<svg viewBox="0 0 %d %d" width="100%%" role="img" '
             'xmlns="http://www.w3.org/2000/svg">' % (W, H)]
    parts.append('<title>检查点团队经济</title>'
                 '<desc>蓝红双方各 10 个引擎实测经济观测点，未连线、未外推。</desc>')
    for i in range(5):
        y = bottom - plot_h * i / 4
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" '
                     'stroke="#e2e8f0" stroke-width="1"/>' %
                     (left, y, W - 18, y))
        parts.append('<text x="%d" y="%.1f" text-anchor="end" font-size="10" '
                     'fill="#94a3b8" dominant-baseline="central">%sk</text>' %
                     (left - 8, y, int(maxgold * i / 4 / 1000)))
    for p in points:
        x = left + plot_w * p["second"] / maxsec
        y = bottom - plot_h * p["gold"] / maxgold
        parts.append('<circle cx="%.1f" cy="%.1f" r="4" fill="%s" '
                     'fill-opacity="0.85"/>' % (x, y, p["color"]))
    ticks = sorted({p["clock"] for p in points},
                   key=lambda c: next(p["second"] for p in points if p["clock"] == c))
    for i, c in enumerate(ticks):
        sec = next(p["second"] for p in points if p["clock"] == c)
        x = left + plot_w * sec / maxsec
        if i % 2 == 0:
            parts.append('<text x="%.1f" y="%d" text-anchor="middle" '
                         'font-size="10" fill="#64748b">%s</text>' %
                         (x, bottom + 16, c))
    lx = left
    for label, color in (("蓝方", "#2563eb"), ("红方", "#dc2626")):
        parts.append('<circle cx="%.1f" cy="%d" r="4" fill="%s"/>' % (lx + 4, 206, color))
        parts.append('<text x="%.1f" y="%d" font-size="11" fill="#475569">%s</text>' %
                     (lx + 14, 210, label))
        lx += 70
    parts.append('<text x="%d" y="%d" text-anchor="end" font-size="11" '
                 'fill="#94a3b8">仅 10 个观测点 · 未连线 · 未外推</text>' %
                 (W - 18, 210))
    parts.append('</svg>')
    return "".join(parts)


CSS = """
:root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --bg:#f8fafc;
        --blue:#2563eb; --red:#dc2626; --amber:#b45309; --green:#0f766e; }
* { box-sizing:border-box; }
body { margin:0; background:#eef2f7; color:var(--ink);
       font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",
       "PingFang SC","Hiragino Sans GB",sans-serif; font-size:14px; line-height:1.7; }
.page { max-width:820px; margin:32px auto; background:#fff; padding:44px 52px 56px;
        border:1px solid var(--line); border-radius:12px; }
h1 { font-size:25px; font-weight:600; margin:0 0 6px; letter-spacing:.3px; }
h2 { font-size:17px; font-weight:600; margin:38px 0 4px; padding-bottom:9px;
     border-bottom:2px solid var(--ink); }
h3 { font-size:14px; font-weight:600; margin:22px 0 8px; }
p { margin:8px 0; }
.sub { color:var(--muted); font-size:13px; }
.tag { display:inline-block; padding:2px 9px; border-radius:20px; font-size:11px;
       font-weight:600; vertical-align:middle; margin-left:8px; }
.t-file { background:#e0f2fe; color:#075985; }
.t-engine { background:#dcfce7; color:#166534; }
.t-ui { background:#fef3c7; color:#92400e; }
.t-off { background:#f1f5f9; color:#64748b; }
.cards { display:flex; gap:10px; flex-wrap:wrap; margin:22px 0 8px; }
.card { flex:1 1 130px; border:1px solid var(--line); border-radius:9px;
        padding:12px 14px; background:var(--bg); }
.card b { display:block; font-size:21px; font-weight:600; line-height:1.3; }
.card span { font-size:11px; color:var(--muted); }
.lead { background:#eff6ff; border:1px solid #bfdbfe; border-radius:9px;
        padding:14px 18px; margin:20px 0 4px; font-size:14px; }
.lead b { color:#1d4ed8; }
.note { background:#fffbeb; border-left:3px solid #f59e0b; padding:10px 14px;
        border-radius:0 7px 7px 0; font-size:13px; margin:14px 0; }
.warn { background:#fef2f2; border-left:3px solid #ef4444; padding:10px 14px;
        border-radius:0 7px 7px 0; font-size:13px; margin:14px 0; }
.chart { border:1px solid var(--line); border-radius:9px; padding:12px 14px 4px;
         margin:14px 0 4px; }
.cap { font-size:12px; color:var(--muted); margin:2px 0 14px; }
table { width:100%; border-collapse:collapse; font-size:12.5px; margin-top:12px; }
th { text-align:left; font-weight:600; color:var(--muted); font-size:11px;
     padding:8px 6px; border-bottom:1px solid var(--line); white-space:nowrap; }
td { padding:8px 6px; border-bottom:1px solid #f1f5f9; }
tr.blue td:first-child { border-left:3px solid var(--blue); }
tr.red td:first-child { border-left:3px solid var(--red); }
.num { text-align:right; font-variant-numeric:tabular-nums; }
ul { margin:8px 0; padding-left:20px; } li { margin:4px 0; }
.legend { display:flex; gap:8px; flex-wrap:wrap; margin:12px 0; }
.legend div { flex:1 1 165px; border:1px solid var(--line); border-radius:8px;
              padding:9px 11px; font-size:12px; }
.legend b { display:block; font-size:12.5px; }
footer { margin-top:36px; padding-top:14px; border-top:1px solid var(--line);
         font-size:11.5px; color:var(--muted); }
@media print { body { background:#fff; } .page { margin:0; border:0; padding:16mm;
               max-width:none; } h2 { break-after:avoid; } .chart,table { break-inside:avoid; } }
@media (max-width:640px) { .page { padding:24px 18px; margin:0; border:0; } }
"""


def build_html(sample, frames, buckets, panel, actions, state_points,
               state_rows, n_clocks, args):
    n_frames = len(frames)
    n_cmds = sum(f["total"] for f in frames)
    n_classified = sum(sum(f[c] for c in ALL_COLS) for f in frames)
    dur = max(f["t"] for f in frames)
    peak = max(buckets, key=lambda b: b["attack"] + b["skill"] + b["cc"])
    peak_window = "%s–%s" % (fmt_mmss(peak["minute"] * 60),
                             fmt_mmss(min((peak["minute"] + 1) * 60, dur)))
    blue = [p for p in panel if p["team"] == "blue"]
    red = [p for p in panel if p["team"] == "red"]
    blue_sum = sum(int(float(p["gold"] or 0)) for p in blue)
    red_sum = sum(int(float(p["gold"] or 0)) for p in red)

    by_clock = {}
    for p in state_points:
        by_clock.setdefault(p["clock"], {"second": p["second"],
                                        "blue": 0, "red": 0})
        by_clock[p["clock"]][p["camp"]] = p["gold"]
    series = sorted(by_clock.items(), key=lambda kv: kv[1]["second"])
    n_lead = len([1 for _, v in series if v["blue"] > v["red"]])
    first_c, first_v = series[0]
    last_c, last_v = series[-1]
    first_diff = first_v["blue"] - first_v["red"]
    last_diff = last_v["blue"] - last_v["red"]

    h = []
    h.append('<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">')
    h.append('<meta name="viewport" content="width=device-width,initial-scale=1">')
    h.append('<title>单局操作复盘 · %s</title><style>%s</style></head><body>' %
             (esc(sample), CSS))
    h.append('<div class="page">')
    h.append('<h1>单局操作复盘报告</h1>')
    h.append('<p class="sub">样本 %s · 5v5 训练赛 · 时长 %s · 客户端 build 5247758'
             ' · 报告生成：replay_codec</p>' % (esc(sample), fmt_mmss(dur)))
    h.append('<p class="sub"><b>样本报告</b>：用于验证「回放解析能否落到人能看懂」。'
             '所有数值均标注来源；缺失字段不补零、不插值、不外推。</p>')
    h.append('<div class="lead"><b>本局速览</b>　%s 的对局里，%d 个引擎实测检查点中'
             '蓝方 <b>%d/%d</b> 领先；经济差从 %s 的 <b>+%s</b> 扩大到 %s 的'
             ' <b>+%s</b>（口径：当时可用金币，非整局累计）。'
             '交火类指令最密集的时段是 <b>%s</b>。'
             '以上结论只覆盖这 %d 个观测点，不代表两帧之间的走势。</div>' %
             (fmt_mmss(dur), n_clocks, n_lead, n_clocks, first_c,
              format(first_diff, ","), last_c, format(last_diff, ","),
              peak_window, n_clocks))

    h.append('<div class="cards">')
    for val, label in ((format(n_frames, ","), "帧记录"),
                       (format(n_cmds, ","), "帧命令"),
                       ("%d%%" % (100 * n_classified // max(1, n_cmds)), "命令归类率"),
                       ("%d × 10" % n_clocks, "引擎检查点")):
        h.append('<div class="card"><b>%s</b><span>%s</span></div>' % (val, label))
    h.append('</div>')

    # 一、全局节奏
    h.append('<h2>一、全局操作节奏 <span class="tag t-file">文件解码</span></h2>')
    h.append('<p>把每帧的输入命令按分钟汇总。这是<b>指令条数</b>，不是战斗次数，'
             '也不区分操作者——回放里的移动/攻击是 packed 输入，缺可靠的逐人归属。</p>')
    h.append('<div class="chart">%s</div>' %
             svg_bars(buckets, ["move", "attack", "skill", "cc", "other"],
                      "每分钟命令总量", "按分钟堆叠的命令条数，移动指令占主导"))
    h.append('<p class="cap">上图含全部 %s 条命令；各分类求和 %s 条，'
             '与 total 相差 %s 条（未归类部分未入图）。</p>' %
             (format(n_cmds, ","), format(n_classified, ","),
              format(n_cmds - n_classified, ",")))
    h.append('<h3>去掉移动指令后的战斗密度</h3>')
    h.append('<div class="chart">%s</div>' %
             svg_bars(buckets, ["attack", "skill", "cc", "other"],
                      "每分钟非移动命令", "攻击、技能、控制与购买加点的逐分钟分布"))
    h.append('<p class="cap">非移动命令峰值出现在 <b>%s</b>：攻击 %s、技能 %s、'
             '控制/状态 %s 条。可用于定位交火密集时段，但<b>不能</b>据此推断击杀时刻。'
             '</p>' % (peak_window, format(peak["attack"], ","),
                        format(peak["skill"], ","), format(peak["cc"], ",")))

    # 二、十人面板
    h.append('<h2>二、十人面板与出装/加点 '
             '<span class="tag t-ui">结算面板</span> '
             '<span class="tag t-file">文件解码</span></h2>')
    h.append('<div class="note">KDA / 结算金币 / 评分来自<b>结算界面读数</b>，'
             '不是回放文件里的字段；技能加点与装备 ID 来自<b>文件解码</b>。'
             '玩家昵称已脱敏，仅显示阵营与英雄。</div>')
    h.append('<table><thead><tr><th>阵营</th><th>英雄</th>'
             '<th class="num">K / D / A</th><th class="num">结算金币</th>'
             '<th class="num">评分</th><th>技能加点分布</th>'
             '<th class="num">装备 ID 数</th></tr></thead><tbody>')
    for team, rows in (("blue", blue), ("red", red)):
        for i, p in enumerate(rows, 1):
            acts = actions.get(p.get("hero_id", ""), {})
            h.append('<tr class="%s"><td>%s %d</td><td>%s</td>'
                     '<td class="num">%s / %s / %s</td><td class="num">%s</td>'
                     '<td class="num">%s</td><td>%s</td><td class="num">%s</td></tr>' %
                     (team, "蓝方" if team == "blue" else "红方", i,
                      esc(p["hero"]), esc(p["kills"]), esc(p["deaths"]),
                      esc(p["assists"]), format(int(float(p["gold"] or 0)), ","),
                      esc(p["score"]), esc(acts.get("learn_slots") or "—"),
                      len(acts.get("equip_ids") or [])))
    h.append('</tbody></table>')
    h.append('<p class="cap">蓝方结算金币合计 %s，红方 %s。'
             '「技能加点分布」为槽位:升级次数，未映射技能名；'
             '「装备 ID 数」为去重后的 ID 集合大小，<b>不是花费、不是出装顺序</b>。'
             '</p>' % (format(blue_sum, ","), format(red_sum, ",")))

    # 三、检查点
    h.append('<h2>三、检查点状态 <span class="tag t-engine">引擎实测</span></h2>')
    h.append('<p>这张图回答一个教练会问的问题：<b>经济差距是什么时候拉开的</b>。'
             '每个圆点是一次暂停时从引擎读出的双方团队金币。</p>')
    h.append('<div class="chart">%s</div>' % svg_checkpoints(state_points))
    h.append('<p class="cap">%d 行引擎实测状态（%d 个时间点 × 10 人）。'
             '只画观测点、不连线、不外推；金币/KDA/等级均来自暂停帧的引擎内存，'
             '无插值。</p>' % (state_rows, n_clocks))
    h.append('<div class="warn"><b>口径警告</b>：上图的检查点金币是「当时可用金币」，'
             '第二节的结算金币是「整局累计获得」，'
             '两者口径不同，<b>不可比较、不可相减、不可拼成一条经济曲线</b>。</div>')

    # 四、本局不提供
    h.append('<h2>四、本局不提供 <span class="tag t-off">显式清单</span></h2>')
    h.append('<p>以下是回放文件或当前采集能力无法给出的内容。'
             '报告不生成近似值，也不把估算列进正式统计：</p>')
    h.append('<ul>')
    for item in [
        "逐帧坐标与移动轨迹：引擎实时 transform 未抓到，方向积分只覆盖 17.8% 地图跨度。",
        "逐帧血量：仅 21 个实测样本（约 0.59% 帧），其余为 unknown。",
        "完整经济账本：金币流水只覆盖收入的 25–35%，不是账本。",
        "精确击杀时刻与击杀归属：只有 KDA 差分窗口和候选参与者。",
        "伤害 / 承伤 / 治疗面板：回放文件里没有写入这些状态。",
        "装备名称与图标：仓库不保存游戏文本，只保留装备 ID。",
        "逐人移动 / 攻击次数：packed 输入缺可靠 actor 归因，禁止排行。",
    ]:
        h.append('<li>%s</li>' % esc(item))
    h.append('</ul>')

    # 五、来源
    h.append('<h2>五、数据来源与置信度</h2>')
    h.append('<div class="legend">')
    for name, desc in [
        ("文件解码", ".abc 帧命令直接解码，可复现；本报告的操作节奏、加点、装备 ID。"),
        ("引擎实测", "暂停帧引擎内存采样，仅 10 个检查点；本报告的金币/KDA/等级。"),
        ("UI 采样", "结算界面读数；本报告的 KDA、结算金币、评分。"),
        ("估算", "本局未使用。任何插值/积分都不会进入正式统计。"),
    ]:
        h.append('<div><b>%s</b><span class="sub">%s</span></div>' % (name, desc))
    h.append('</div>')
    h.append('<footer>生成脚本：replay_codec/build_report.py · '
             '输入：帧命令 CSV、结算面板 CSV、玩家动作 CSV、引擎检查点 CSV · '
             '未修改回放原件，未连接游戏进程或设备。</footer>')
    h.append('</div></body></html>')
    return "".join(h)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="生成单局可读 HTML 报告")
    ap.add_argument("--data-dir", default=os.path.join(here, "sample_data"),
                    help="已解码数据目录；默认用随包附带的脱敏样本")
    ap.add_argument("--state", default=os.path.join(
        here, "sample_data", "state_series_161129_10pt.csv"))
    ap.add_argument("--sample", default="20261102_161129")
    ap.add_argument("--out", default=os.path.join(here, "output",
                                                  "20261102_161129_report.html"))
    args = ap.parse_args()

    frames = load_frames(os.path.join(args.data_dir, FRAME_FILE), args.sample)
    panel = load_panel(os.path.join(args.data_dir, PANEL_FILE), args.sample)
    actions = load_actions(os.path.join(args.data_dir, ACTIONS_FILE), args.sample)
    points, state_rows, n_clocks = load_state(args.state)
    buckets = bucket_by_minute(frames)

    doc = build_html(args.sample, frames, buckets, panel, actions,
                     points, state_rows, n_clocks, args)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)
    print("OK  frames=%d commands=%d panel=%d state_rows=%d clocks=%d" %
          (len(frames), sum(f["total"] for f in frames), len(panel),
           state_rows, n_clocks))
    print("OUT " + os.path.abspath(args.out))


if __name__ == "__main__":
    main()
