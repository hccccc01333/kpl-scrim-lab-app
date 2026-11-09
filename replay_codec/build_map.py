# -*- coding: utf-8 -*-
"""
replay_codec / build_map.py

生成「单局地图复刻 + 回放操作层」：一个可离线打开的单文件 HTML。

数据来源（必须在页面上标注，不得混淆）：
  位置轨迹 —— 官方营地个人回放的逐秒网格坐标（1 Hz，[-57,57]），
              「UI / 官方接口采样」，不是 .abc 解码，也不是逐帧。
  操作层   —— .abc 显式世界坐标（文件解码，100% 可复现）：
              * 0x02/0x82 USEPOSITIONSKILL 地面落点（skill aim）
              * 0x01/0x2c 位置指令目标点（target）
              * 0x01 len14 X/Y/Z 位置关键帧（anchor，唯一真实位置通道）
  事件条   —— .abc 帧命令按秒聚合（文件解码）。

坐标一致性：脚本用 anchor 类锚点自动搜索「回放时间 +N s」与营地逐秒
位置最贴合的整数秒偏移，缩放固定 world/1000（不拟合缩放，避免过拟合），
并把中位/p90/分实体残差写进页面。这是统计一致性，不是帧级时间校准。

红线：0x82/0x2c 是落点与目标点，不是施法者站位；虚线只是「该秒营地
位置 → 回放落点」的指向示意，不是弹道/射程/命中。

用法：
  python build_map.py
  python build_map.py --positions <csv> --frames <csv> --coords <csv> --out <html>
"""

import argparse
import csv
import json
import math
import os
import statistics
from collections import defaultdict

SAMPLE = "20261102_161129"
GRID = 57.0
WORLD_PER_GRID = 1000.0   # 引擎世界坐标 → 营地网格的固定换算（不拟合）

HERO_ABBR = {
    "钟馗": "钟", "妲己": "妲", "孙悟空": "猴", "关羽": "关",
    "百里守约": "百", "公孙离": "离", "吕布": "吕", "貂蝉": "貂",
    "兰陵王": "兰", "张良": "张",
}

KIND = {
    "tail_0x02_82_aim": "aim",
    "tail_0x01_2c_target": "target",
    "tail_0x01_len14_position": "anchor",
}


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_positions(path):
    """返回 (players, lookup, t0, t1)。lookup[(entity,t)]=(gx,gy) 供校准/指向线用。"""
    rows = read_csv(path)
    ents = {}
    lookup = {}
    for r in rows:
        e = r["entity"]
        if e not in ents:
            ents[e] = {
                "entity": e,
                "hero": r["hero"],
                "abbr": HERO_ABBR.get(r["hero"], r["hero"][:1]),
                "camp": "blue" if str(r["camp"]) == "1" else "red",
                "xs": {}, "ys": {},
            }
        t = int(float(r["t_sec"]))
        gx, gy = float(r["grid_x"]), float(r["grid_y"])
        ents[e]["xs"][t] = gx
        ents[e]["ys"][t] = gy
        lookup[(e, t)] = (gx, gy)
    times = sorted({int(float(r["t_sec"])) for r in rows})
    t0, t1 = times[0], times[-1]
    players = []
    for e, v in ents.items():
        players.append({
            "entity": e, "hero": v["hero"], "abbr": v["abbr"],
            "camp": v["camp"],
            "x": [v["xs"].get(t) for t in range(t0, t1 + 1)],
            "y": [v["ys"].get(t) for t in range(t0, t1 + 1)],
        })
    players.sort(key=lambda p: (p["camp"], p["hero"]))
    return players, lookup, t0, t1


def camp_at(lookup, entity, t):
    """营地逐秒位置的线性插值；缺秒返回 None。"""
    lo = int(math.floor(t))
    a = lookup.get((entity, lo))
    b = lookup.get((entity, lo + 1))
    if a and b:
        f = t - lo
        return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
    return a or b


def calibrate(coords, lookup):
    """只用位置锚点搜索整数秒偏移；缩放固定，不拟合平移/旋转。"""
    anchors = [c for c in coords if c["kind"] == "anchor"]
    best = None
    for dt in range(-30, 31):
        ds = []
        for c in anchors:
            p = camp_at(lookup, c["entity"], c["time_s"] + dt)
            if p:
                ds.append(math.hypot(c["gx"] - p[0], c["gy"] - p[1]))
        if len(ds) < len(anchors) * 0.8:
            continue
        score = statistics.median(ds)
        if best is None or (score, abs(dt)) < (best["score"], abs(best["dt"])):
            best = {"dt": dt, "score": score, "n": len(ds), "ds": ds}
    if best is None:
        return {"dt": 0, "median": None, "p90": None, "mean": None,
                "n": 0, "per_entity": {}}
    ds = sorted(best["ds"])
    per = defaultdict(list)
    for c in anchors:
        p = camp_at(lookup, c["entity"], c["time_s"] + best["dt"])
        if p:
            per[c["hero"]].append(math.hypot(c["gx"] - p[0], c["gy"] - p[1]))
    return {
        "dt": best["dt"],
        "median": round(statistics.median(ds), 2),
        "mean": round(sum(ds) / len(ds), 2),
        "p90": round(ds[min(len(ds) - 1, int(len(ds) * 0.9))], 2),
        "n": len(ds),
        "per_entity": {h: {"n": len(v), "median": round(statistics.median(v), 2)}
                       for h, v in sorted(per.items())},
    }


def load_coords(path, lookup, dt, t1):
    """把 .abc 显式世界坐标换算到网格，并附上同一秒的营地位置（用于指向线）。"""
    out = []
    for r in read_csv(path):
        kind = KIND.get(r["source"])
        if not kind:
            continue
        x, z = float(r["x"]), float(r["z"])
        if (x, z) == (0.0, 0.0):
            continue
        t = int(round(float(r["time_s"]) + dt))
        if t < 0 or t > t1:
            continue
        caster = camp_at(lookup, r["entity_id"], t)
        out.append({
            "t": t, "kind": kind, "entity": r["entity_id"],
            "hero": r["hero"],
            "camp": "blue" if str(r["camp"]) == "1" else "red",
            "gx": round(x / WORLD_PER_GRID, 3),
            "gy": round(z / WORLD_PER_GRID, 3),
            "cx": round(caster[0], 2) if caster else None,
            "cy": round(caster[1], 2) if caster else None,
        })
    out.sort(key=lambda c: (c["t"], c["kind"], c["entity"]))
    return out


def load_events(path, sample, t1):
    rows = [r for r in read_csv(path) if r.get("sample") == sample]
    keys = ("skill", "cc", "attack", "buy", "pos_skill")
    ev = {k: [0] * (t1 + 1) for k in keys}
    for r in rows:
        t = int(float(r["time_sec"]))
        if t < 0 or t > t1:
            continue
        ev["skill"][t] += sum(int(r.get(c) or 0) for c in
                              ("USEDIRECTIONALSKILL", "USEPOSITIONSKILL",
                               "USEOBJECTIVESKILL"))
        ev["pos_skill"][t] += int(r.get("USEPOSITIONSKILL") or 0)
        ev["cc"][t] += int(r.get("CC") or 0)
        ev["attack"][t] += sum(int(r.get(c) or 0) for c in
                               ("PLAYER_ATTACK", "PLAYER_ATTACKWITHOBJ",
                                "BASEATTACK"))
        ev["buy"][t] += int(r.get("BUYEQUIP") or 0) + int(r.get("LEARNSKILL") or 0)
    return ev


def build_stats(coords, t1):
    by_kind = defaultdict(list)
    for c in coords:
        by_kind[c["kind"]].append(c)
    bins = [0] * (t1 // 60 + 1)
    for c in by_kind["aim"]:
        bins[min(len(bins) - 1, c["t"] // 60)] += 1
    peak = max(range(len(bins)), key=lambda i: bins[i]) if any(bins) else 0
    return {
        "counts": {k: len(v) for k, v in by_kind.items()},
        "entities": {k: sorted({c["hero"] for c in v}) for k, v in by_kind.items()},
        "aim_times": sorted({c["t"] for c in by_kind["aim"]}),
        "bins": bins,
        "peak_min": peak,
        "peak_n": bins[peak],
        "total": len(coords),
    }


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>单局地图复刻 · 回放操作层 · __SAMPLE__</title>
<style>
:root{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--blue:#2563eb;--red:#dc2626;
 --aim:#ea580c;--target:#7c3aed;--anchor:#0891b2;}
*{box-sizing:border-box}
body{margin:0;background:#eef2f7;color:var(--ink);font-family:-apple-system,
 BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
 font-size:14px;line-height:1.6}
.wrap{max-width:1120px;margin:24px auto;background:#fff;border:1px solid var(--line);
 border-radius:12px;padding:28px 32px 34px}
h1{font-size:22px;font-weight:600;margin:0 0 4px}
h2{font-size:15px;font-weight:600;margin:26px 0 8px;padding-bottom:7px;
 border-bottom:2px solid var(--ink)}
.sub{color:var(--muted);font-size:12.5px}
.tag{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;
 font-weight:600;margin-left:6px;vertical-align:middle}
.t-ui{background:#fef3c7;color:#92400e}
.t-file{background:#e0f2fe;color:#075985}
.t-off{background:#f1f5f9;color:#64748b}
.lead{background:#f8fafc;border:1px solid var(--line);border-left:4px solid #0f172a;
 border-radius:0 8px 8px 0;padding:12px 16px;margin:16px 0 4px;font-size:13.5px}
.grid{display:flex;gap:20px;flex-wrap:wrap;margin-top:18px}
.mapbox{flex:1 1 540px;min-width:340px}
.side{flex:0 1 285px;min-width:235px}
svg.map{width:100%;height:auto;background:#f8fafc;border:1px solid var(--line);
 border-radius:10px;display:block}
.ctrl{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin:14px 0 6px}
button{border:1px solid var(--line);background:#fff;border-radius:7px;padding:7px 13px;
 font-size:12.5px;cursor:pointer;font-weight:500}
button.primary{background:#0f172a;color:#fff;border-color:#0f172a}
button:hover{border-color:#94a3b8}
input[type=range]{flex:1 1 210px;min-width:170px;accent-color:#0f172a}
select{border:1px solid var(--line);border-radius:7px;padding:6px 8px;font-size:12.5px}
.clock{font-variant-numeric:tabular-nums;font-size:19px;font-weight:600;min-width:62px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:var(--muted);font-size:10.5px;font-weight:600;
 padding:6px 4px;border-bottom:1px solid var(--line)}
td{padding:5px 4px;border-bottom:1px solid #f1f5f9;font-variant-numeric:tabular-nums}
tr.blue td:first-child{border-left:3px solid var(--blue)}
tr.red td:first-child{border-left:3px solid var(--red)}
tbody tr{cursor:pointer}
tbody tr:hover{background:#f8fafc}
tbody tr.focus{background:#e0f2fe}
.dim{color:#94a3b8}
.layers{border:1px solid var(--line);border-radius:9px;padding:10px 12px;margin-top:14px}
.layers b{display:block;font-size:12px;margin-bottom:6px}
.layers label{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;
 margin:3px 12px 3px 0;cursor:pointer;white-space:nowrap}
.layers input{accent-color:#0f172a}
.sw{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:2px}
.detail{margin-top:14px;border:1px solid var(--line);border-radius:9px;padding:10px 12px}
.detail b{display:block;font-size:12px;margin-bottom:6px}
.kv{display:flex;justify-content:space-between;font-size:11.5px;padding:2px 0;
 border-bottom:1px dotted #f1f5f9}
.kv span:last-child{font-variant-numeric:tabular-nums;font-weight:600}
.events{margin-top:8px;border:1px solid var(--line);border-radius:9px;padding:10px 12px 4px}
.cap{font-size:11.5px;color:var(--muted);margin:4px 0 0}
.note{background:#fffbeb;border-left:3px solid #f59e0b;padding:10px 14px;
 border-radius:0 7px 7px 0;font-size:12.5px;margin:14px 0}
.warn{background:#fef2f2;border-left:3px solid #ef4444;padding:10px 14px;
 border-radius:0 7px 7px 0;font-size:12.5px;margin:14px 0}
.legend{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}
.legend div{flex:1 1 190px;border:1px solid var(--line);border-radius:8px;
 padding:9px 11px;font-size:12px}
.legend b{display:block;font-size:12.5px}
.small{font-size:11.5px;color:var(--muted)}
footer{margin-top:26px;padding-top:12px;border-top:1px solid var(--line);
 font-size:11px;color:var(--muted)}
@media(max-width:700px){.wrap{padding:18px 14px;margin:0;border:0}.side{flex:1 1 100%}}
</style>
</head>
<body>
<div class="wrap">
<h1>单局地图复刻 · 回放操作层
<span class="tag t-ui">轨迹：官方逐秒</span>
<span class="tag t-file">落点/事件：文件解码</span></h1>
<p class="sub">样本 __SAMPLE__ · 5v5 · __DUR__ · 10 人 × __NSEC__ 个逐秒位置
 · __NCMD__ 条帧命令 · 峡谷为自绘示意图，非官方地图素材</p>

<div class="lead">本局回放直接给出了 <b>__N_AIM__ 个技能落点</b>（0x02/0x82）、
<b>__N_TARGET__ 条位置指令目标点</b>（0x01/0x2c）与 <b>__N_ANCHOR__ 个绝对位置锚点</b>，
共 __N_COORD__ 条显式世界坐标。落点只涉及 __AIM_HEROES__，
锚点只涉及 __ANCHOR_HEROES__；技能落点最密集在 <b>__PEAK__</b>（该分钟 __PEAK_N__ 次）。
营地接口只有 1 Hz 位置，<b>没有这些落点</b>——这一层只有回放文件能给。</div>

<div class="grid">
  <div class="mapbox">
    <svg class="map" viewBox="0 0 500 500" id="map" role="img"
         xmlns="http://www.w3.org/2000/svg">
      <title>王者峡谷示意图：十人逐秒位置与回放技能落点</title>
      <desc>蓝方左下、红方右上。圆点为营地整秒位置；橙色菱形为回放技能落点；
            紫色小圆为目标指令点；青色方框为回放绝对位置锚点。</desc>
      <defs>
        <clipPath id="sq"><rect x="20" y="20" width="460" height="460" rx="6"/></clipPath>
      </defs>
      <g clip-path="url(#sq)">
        <rect x="20" y="20" width="460" height="460" fill="#f1f5f9"/>
        <path d="M20 20 L480 480" stroke="#dbeafe" stroke-width="46" fill="none"/>
        <path d="M20 480 L480 20" stroke="#e2e8f0" stroke-width="20" fill="none"/>
        <path d="M20 480 L20 20 L480 20" stroke="#e2e8f0" stroke-width="20" fill="none"/>
        <path d="M20 480 L480 480 L480 20" stroke="#e2e8f0" stroke-width="20" fill="none"/>
        <g fill="#dcfce7" opacity="0.85">
          <circle cx="120" cy="300" r="17"/><circle cx="200" cy="380" r="15"/>
          <circle cx="300" cy="120" r="17"/><circle cx="380" cy="200" r="15"/>
          <circle cx="150" cy="150" r="13"/><circle cx="350" cy="350" r="13"/>
        </g>
        <g fill="#cbd5e1">
          <rect x="18" y="360" width="9" height="9" rx="2"/>
          <rect x="18" y="250" width="9" height="9" rx="2"/>
          <rect x="18" y="140" width="9" height="9" rx="2"/>
          <rect x="140" y="18" width="9" height="9" rx="2"/>
          <rect x="250" y="18" width="9" height="9" rx="2"/>
          <rect x="360" y="18" width="9" height="9" rx="2"/>
          <rect x="473" y="140" width="9" height="9" rx="2"/>
          <rect x="473" y="250" width="9" height="9" rx="2"/>
          <rect x="473" y="360" width="9" height="9" rx="2"/>
          <rect x="140" y="473" width="9" height="9" rx="2"/>
          <rect x="250" y="473" width="9" height="9" rx="2"/>
          <rect x="360" y="473" width="9" height="9" rx="2"/>
        </g>
      </g>
      <circle cx="42" cy="458" r="15" fill="#bfdbfe" stroke="#2563eb" stroke-width="2"/>
      <circle cx="458" cy="42" r="15" fill="#fecaca" stroke="#dc2626" stroke-width="2"/>
      <text x="42" y="462" text-anchor="middle" font-size="10" fill="#1d4ed8">蓝</text>
      <text x="458" y="46" text-anchor="middle" font-size="10" fill="#b91c1c">红</text>
      <g id="trails"></g>
      <g id="links"></g>
      <g id="lAnchor"></g>
      <g id="lTarget"></g>
      <g id="lAim"></g>
      <g id="dots"></g>
    </svg>

    <div class="ctrl">
      <button class="primary" id="play">播放</button>
      <input type="range" id="seek" min="0" max="__T1__" value="0" step="1">
      <span class="clock" id="clock">00:00</span>
      <select id="speed">
        <option value="1">1×</option><option value="2">2×</option>
        <option value="4" selected>4×</option><option value="8">8×</option>
      </select>
      <select id="window">
        <option value="10">窗口 ±10s</option>
        <option value="20" selected>窗口 ±20s</option>
        <option value="60">窗口 ±60s</option>
        <option value="9999">显示全场</option>
      </select>
      <button id="nextAim" title="跳到下一次技能落点">下一落点 →</button>
    </div>
    <p class="cap">空格播放/暂停，← / → 逐秒，Shift + ← / → 跳落点。
      点击右侧英雄行可聚焦单人。落点按时间窗渐隐，越近越清晰；
      指向虚线只在该秒确有落点时绘制，用「下一落点」可逐次定位。</p>
  </div>

  <div class="side">
    <h2 style="margin-top:0">当前秒十人位置</h2>
    <table><thead><tr><th>阵营</th><th>英雄</th><th>格坐标</th><th>位移</th></tr></thead>
      <tbody id="roster"></tbody></table>
    <p class="cap">位移 = 与上一整秒的网格距离；「—」表示该秒无坐标。</p>

    <div class="layers"><b>图层开关</b>
      <label><input type="checkbox" id="ckTrail" checked>轨迹拖尾</label>
      <label><input type="checkbox" id="ckAim" checked>
        <i class="sw" style="background:#ea580c"></i>技能落点</label>
      <label><input type="checkbox" id="ckLink" checked>指向连线</label>
      <label><input type="checkbox" id="ckTarget" checked>
        <i class="sw" style="background:#7c3aed"></i>目标点</label>
      <label><input type="checkbox" id="ckAnchor" checked>
        <i class="sw" style="background:#0891b2"></i>位置锚点</label>
    </div>

    <div class="detail"><b>当前秒操作明细 <span class="small">文件解码</span></b>
      <div class="kv"><span>技能释放 / 其中位置技能</span><span id="dSkill">—</span></div>
      <div class="kv"><span>攻击 / 控制</span><span id="dAtk">—</span></div>
      <div class="kv"><span>购买 / 加点</span><span id="dBuy">—</span></div>
      <div class="kv"><span>回放落点 / 目标点 / 锚点</span><span id="dCoord">—</span></div>
    </div>
  </div>
</div>

<h2>同时间轴 · 操作事件密度 <span class="tag t-file">文件解码</span></h2>
<div class="events">
  <svg id="ebars" viewBox="0 0 1000 130" width="100%" role="img"
       xmlns="http://www.w3.org/2000/svg">
    <title>逐秒操作事件密度与技能落点时刻</title>
    <desc>技能、控制、攻击、购买加点四类命令的逐秒堆叠柱，底部橙线为落点时刻。</desc>
  </svg>
  <p class="cap">蓝：攻击指令　橙：技能释放　红：控制/状态　灰：购买/加点；
    底部橙色短竖线 = 该秒有回放技能落点。竖线随地图时间轴同步。</p>
</div>

<h2>技能落点分布 <span class="tag t-file">文件解码</span></h2>
<div class="events">
  <svg id="sbars" viewBox="0 0 1000 130" width="100%" role="img"
       xmlns="http://www.w3.org/2000/svg">
    <title>按分钟统计的 0x82 技能落点次数</title>
    <desc>每分钟回放中出现的地面技能落点数量。</desc>
  </svg>
  <p class="cap">仅统计 <code>0x02/0x82 USEPOSITIONSKILL</code> 的 78 条地面落点，
    与 CSSYNC 帧命令镜像逐字节一致。这是施法目标点，不是命中数、不是伤害。</p>
</div>

<h2>两套坐标的一致性校验 <span class="tag t-file">文件解码</span></h2>
<div class="note" style="background:#f0f9ff;border-left-color:#0891b2">
<b>做法</b>：取回放里 __CAL_N__ 条绝对位置锚点（<code>0x01 len14</code>，X/Y/Z，Y 恒为 0），
按固定换算 <code>格坐标 = 世界坐标 / 1000</code> 投到同一张图，
在 −30…+30 秒里搜索与营地逐秒位置中位偏差最小的整数秒偏移。
<b>实测</b>：偏移 <b>__CAL_DT__</b> s 时最贴合，中位偏差 <b>__CAL_MED__ 格</b>
（均值 __CAL_MEAN__ 格、p90 __CAL_P90__ 格）。
分人：__CAL_PER__。<br>
<b>这只是统计一致性，不是帧级时间校准</b>：锚点只有 3 人、18 个不同位置，
且营地本身只有 1 Hz 整数格；因此页面上的落点与营地圆点仍可能有数秒／十余格错位。
没有拟合缩放、旋转或平移，避免拿稀疏样本过拟合出「看起来很准」的假象。</div>

<div class="warn"><b>精度红线（请照此读图）</b>：
① <b>落点不是站位</b>——<code>0x82</code> 是地面技能的施法目标点，
<code>0x2c</code> 是位置指令的目标点，两者都不是发射者当时的位置；
② <b>虚线不是弹道</b>——它只连接「该秒营地里该英雄的 1 Hz 位置」与「回放里的落点」，
用来示意指向方向，不代表飞行轨迹、射程或命中判定；
③ <b>锚点不是轨迹</b>——回放的位置通道只覆盖 3/10 人、90/10,509 帧（0.86%），
整局 18 个不同位置，4 人完全没有坐标；
④ <b>轨迹不是逐帧</b>——营地 1 Hz 整数格，相邻秒连线只是连线，不代表真实走位；
⑤ 峡谷为自绘示意图，非官方地图素材。</div>

<h2>来源与置信度</h2>
<div class="legend">
  <div><b>文件解码 · 可复现</b>__NCMD__ 条帧命令 0 未解析；__N_COORD__ 条显式世界坐标
    （78 落点 / 79 目标点 / 138 锚点）。本图的操作层与两条分布图。</div>
  <div><b>UI / 官方接口采样</b>10 人 × 693 秒逐秒网格位置，1 Hz，全十人覆盖；
    本图圆点、拖尾与指向线起点。</div>
  <div><b>引擎实测</b>本图未使用。10 个检查点的金币/KDA/等级见单局报告。</div>
  <div><b>估算</b>本图未使用。未插值、未补点、未外推；缺的显示「—」。</div>
</div>

<footer>生成脚本：replay_codec/build_map.py · 输入：
  20261102_official_positions.csv / 20261102_replay_coords.csv /
  20261102_frame_commands.csv · 玩家昵称、账号 ID 已脱敏，仅显示英雄名 ·
  未使用官方地图素材。</footer>
</div>

<script>
const P = __POSITIONS__;
const E = __EVENTS__;
const C = __COORDS__;
const S = __STATS__;
const T1 = __T1__;
const GRID = 57.0;
const SIZE = 460, OFF = 20;
const sx = g => OFF + (g + GRID) / (2 * GRID) * SIZE;
const sy = g => OFF + (GRID - g) / (2 * GRID) * SIZE;
const COL = {blue:"#2563eb", red:"#dc2626"};
const fmt = s => String(Math.floor(s/60)).padStart(2,"0") + ":" + String(s%60).padStart(2,"0");
const esc = s => String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"})[c]);
const ck = id => document.getElementById(id).checked;

let t = 0, timer = null, focus = null;
const dots = document.getElementById("dots");
const trails = document.getElementById("trails");
const links = document.getElementById("links");
const roster = document.getElementById("roster");
const seek = document.getElementById("seek");
const clock = document.getElementById("clock");
const playBtn = document.getElementById("play");
const layers = {anchor:"lAnchor", target:"lTarget", aim:"lAim"};

function fade(dt, win) {
  if (win > 1000) return 0.42;
  if (dt > win) return null;
  return 0.95 - 0.6 * (dt / win);
}

function render(t) {
  const win = Number(document.getElementById("window").value);
  let d = "", tr = "", rows = "", lk = "";
  const lay = {anchor:"", target:"", aim:""};
  P.forEach(p => {
    const x = p.x[t], y = p.y[t];
    const soft = focus && focus !== p.entity ? 0.16 : 1;
    if (x === null || y === null || x === undefined) {
      rows += `<tr class="${p.camp}${focus===p.entity?" focus":""}"><td>${p.camp==="blue"?"蓝":"红"}</td>`+
              `<td>${esc(p.hero)}</td><td class="dim">—</td><td class="dim">—</td></tr>`;
      return;
    }
    let pts = [];
    for (let k = Math.max(0, t-8); k <= t; k++) {
      if (p.x[k] !== null && p.y[k] !== null && p.x[k] !== undefined)
        pts.push(`${sx(p.x[k]).toFixed(1)},${sy(p.y[k]).toFixed(1)}`);
    }
    if (pts.length > 1 && ck("ckTrail"))
      tr += `<polyline points="${pts.join(" ")}" fill="none" stroke="${COL[p.camp]}"`+
            ` stroke-width="1.6" stroke-opacity="${(0.35*soft).toFixed(2)}" stroke-linejoin="round"/>`;
    const px = sx(x).toFixed(1), py = sy(y).toFixed(1);
    d += `<g opacity="${soft}"><circle cx="${px}" cy="${py}" r="7.5" fill="${COL[p.camp]}"`+
         ` stroke="#fff" stroke-width="2"/>`+
         `<text x="${px}" y="${Number(py)+3.4}" text-anchor="middle" font-size="8.5"`+
         ` fill="#fff" font-weight="600">${esc(p.abbr)}</text></g>`;
    let move = "—";
    if (t > 0 && p.x[t-1] !== null && p.x[t-1] !== undefined) {
      const dx = x - p.x[t-1], dy = y - p.y[t-1];
      move = Math.sqrt(dx*dx + dy*dy).toFixed(1);
    }
    rows += `<tr class="${p.camp}${focus===p.entity?" focus":""}" data-e="${p.entity}">`+
            `<td>${p.camp==="blue"?"蓝":"红"}</td>`+
            `<td>${esc(p.hero)}</td><td>${x.toFixed(0)}, ${y.toFixed(0)}</td>`+
            `<td>${move}</td></tr>`;
  });

  const counts = {aim:0, target:0, anchor:0};
  C.forEach(c => {
    const dt = Math.abs(c.t - t);
    const a = fade(dt, win);
    if (a === null) return;
    if (c.kind === "aim" && !ck("ckAim")) return;
    if (c.kind === "target" && !ck("ckTarget")) return;
    if (c.kind === "anchor" && !ck("ckAnchor")) return;
    if (c.t === t) counts[c.kind]++;
    const soft = focus && focus !== c.entity ? 0.25 : 1;
    const op = (a * soft).toFixed(2);
    const X = sx(c.gx).toFixed(1), Y = sy(c.gy).toFixed(1);
    let mark = "";
    if (c.kind === "aim") {
      const r = (c.t === t ? 7 : 5);
      mark = `<path d="M${X} ${Number(Y)-r} L${Number(X)+r} ${Y} L${X} ${Number(Y)+r}`+
             ` L${Number(X)-r} ${Y} Z" fill="#ea580c" stroke="#fff" stroke-width="1.2"`+
             ` opacity="${op}"><title>${esc(c.hero)} 技能落点 ${fmt(c.t)}</title></path>`;
      if (ck("ckLink") && c.cx !== null && c.t === t) {
        lk += `<line x1="${sx(c.cx).toFixed(1)}" y1="${sy(c.cy).toFixed(1)}" x2="${X}" y2="${Y}"`+
              ` stroke="#ea580c" stroke-width="1.5" stroke-dasharray="4 4"`+
              ` stroke-opacity="0.75"/>`;
      }
    } else if (c.kind === "target") {
      mark = `<circle cx="${X}" cy="${Y}" r="3.6" fill="#7c3aed" stroke="#fff"`+
             ` stroke-width="1" opacity="${op}"><title>${esc(c.hero)} 目标点 ${fmt(c.t)}</title></circle>`;
    } else {
      const s = 4.5;
      mark = `<g opacity="${op}"><rect x="${Number(X)-s}" y="${Number(Y)-s}"`+
             ` width="${s*2}" height="${s*2}" fill="none" stroke="#0891b2" stroke-width="1.8"/>`+
             `<path d="M${Number(X)-7} ${Y} h14 M${X} ${Number(Y)-7} v14"`+
             ` stroke="#0891b2" stroke-width="1" opacity="0.8"/></g>`;
    }
    lay[c.kind] += mark;
  });

  dots.innerHTML = d; trails.innerHTML = tr; links.innerHTML = lk;
  Object.keys(layers).forEach(k => document.getElementById(layers[k]).innerHTML = lay[k]);
  roster.innerHTML = rows;
  Array.from(roster.querySelectorAll("tr[data-e]")).forEach(row => {
    row.onclick = () => { focus = focus === row.dataset.e ? null : row.dataset.e; render(t); };
  });
  clock.textContent = fmt(t); seek.value = t;
  cursor.setAttribute("x1", (t/T1*1000).toFixed(1));
  cursor.setAttribute("x2", (t/T1*1000).toFixed(1));

  document.getElementById("dSkill").textContent =
    (E.skill[t]||0) + " / " + (E.pos_skill[t]||0);
  document.getElementById("dAtk").textContent =
    (E.attack[t]||0) + " / " + (E.cc[t]||0);
  document.getElementById("dBuy").textContent = (E.buy[t]||0);
  document.getElementById("dCoord").textContent =
    counts.aim + " / " + counts.target + " / " + counts.anchor;
}

const eb = document.getElementById("ebars");
let cursor;
function drawEvents() {
  const keys = [["attack","#60a5fa"],["skill","#f59e0b"],
                ["cc","#ef4444"],["buy","#94a3b8"]];
  let max = 1;
  for (let i = 0; i <= T1; i++) {
    let s = 0; keys.forEach(([k]) => s += E[k][i] || 0);
    if (s > max) max = s;
  }
  let out = `<line x1="0" y1="110" x2="1000" y2="110" stroke="#e2e8f0"/>`;
  const step = 1000 / (T1 + 1);
  for (let i = 0; i <= T1; i++) {
    let acc = 0;
    keys.forEach(([k, c]) => {
      const v = E[k][i] || 0;
      if (!v) return;
      const h = 100 * v / max;
      const y = 110 - acc - h;
      out += `<rect x="${(i*step).toFixed(2)}" y="${y.toFixed(2)}"`+
             ` width="${Math.max(step,0.7).toFixed(2)}" height="${h.toFixed(2)}"`+
             ` fill="${c}"/>`;
      acc += h;
    });
  }
  S.aim_times.forEach(s => {
    out += `<line x1="${(s/T1*1000).toFixed(1)}" y1="111" x2="${(s/T1*1000).toFixed(1)}"`+
           ` y2="118" stroke="#ea580c" stroke-width="1.4"/>`;
  });
  [0, 120, 240, 360, 480, 600].forEach(s => {
    if (s > T1) return;
    const x = s / T1 * 1000;
    out += `<text x="${x.toFixed(1)}" y="128" font-size="10" fill="#94a3b8"`+
           ` text-anchor="middle">${fmt(s)}</text>`;
  });
  out += `<line id="cursor" x1="0" y1="4" x2="0" y2="112" stroke="#0f172a"`+
         ` stroke-width="1.5"/>`;
  eb.innerHTML = out;
  cursor = document.getElementById("cursor");
}

function drawSkillBins() {
  const sb = document.getElementById("sbars");
  const b = S.bins, max = Math.max(1, ...b);
  const step = 1000 / b.length;
  let out = `<line x1="0" y1="100" x2="1000" y2="100" stroke="#e2e8f0"/>`;
  b.forEach((v, i) => {
    const h = 92 * v / max;
    const c = i === S.peak_min ? "#ea580c" : "#fdba74";
    out += `<rect x="${(i*step+2).toFixed(1)}" y="${(100-h).toFixed(1)}"`+
           ` width="${Math.max(2,step-4).toFixed(1)}" height="${h.toFixed(1)}" fill="${c}"/>`;
    if (v) out += `<text x="${(i*step+step/2).toFixed(1)}" y="${(96-h).toFixed(1)}"`+
           ` font-size="10" fill="#9a3412" text-anchor="middle">${v}</text>`;
    out += `<text x="${(i*step+step/2).toFixed(1)}" y="116" font-size="10"`+
           ` fill="#94a3b8" text-anchor="middle">${i}′</text>`;
  });
  sb.innerHTML = out;
}

function gotoAim(dir) {
  const ts = S.aim_times;
  let target;
  if (dir > 0) target = ts.find(v => v > t);
  else target = ts.slice().reverse().find(v => v < t);
  if (target === undefined) target = dir > 0 ? ts[0] : ts[ts.length-1];
  if (target === undefined) return;
  setPlaying(false); t = target; render(t);
}

function setPlaying(on) {
  if (on) {
    if (timer) return;
    const sp = Number(document.getElementById("speed").value);
    timer = setInterval(() => {
      t = t >= T1 ? 0 : t + 1;
      render(t);
    }, Math.max(40, Math.round(1000 / sp)));
    playBtn.textContent = "暂停";
  } else {
    clearInterval(timer); timer = null;
    playBtn.textContent = "播放";
  }
}

playBtn.onclick = () => setPlaying(!timer);
seek.oninput = e => { t = Number(e.target.value); render(t); };
document.getElementById("speed").onchange = () => { setPlaying(false); setPlaying(true); };
document.getElementById("window").onchange = () => render(t);
document.getElementById("nextAim").onclick = () => gotoAim(1);
["ckTrail","ckAim","ckLink","ckTarget","ckAnchor"].forEach(id =>
  document.getElementById(id).onchange = () => render(t));
document.onkeydown = e => {
  if (e.code === "Space") { e.preventDefault(); setPlaying(!timer); }
  if (e.code === "ArrowLeft")  {
    if (e.shiftKey) gotoAim(-1);
    else { setPlaying(false); t = Math.max(0, t-1); render(t); }
  }
  if (e.code === "ArrowRight") {
    if (e.shiftKey) gotoAim(1);
    else { setPlaying(false); t = Math.min(T1, t+1); render(t); }
  }
};

drawEvents();
drawSkillBins();
render(0);
</script>
</body>
</html>
"""


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="生成单局地图复刻 + 回放操作层 HTML")
    ap.add_argument("--positions", default=os.path.join(
        here, "sample_data", "20261102_official_positions.csv"))
    ap.add_argument("--frames", default=os.path.join(
        here, "sample_data", "20261102_frame_commands.csv"))
    ap.add_argument("--coords", default=os.path.join(
        here, "sample_data", "20261102_replay_coords.csv"))
    ap.add_argument("--sample", default=SAMPLE)
    ap.add_argument("--out", default=os.path.join(
        here, "output", "20261102_161129_map.html"))
    args = ap.parse_args()

    players, lookup, t0, t1 = load_positions(args.positions)
    raw = []
    for r in read_csv(args.coords):
        x, z = float(r["x"]), float(r["z"])
        if (x, z) == (0.0, 0.0):
            continue
        kind = KIND.get(r["source"])
        if not kind:
            continue
        raw.append({"time_s": float(r["time_s"]), "entity": r["entity_id"],
                    "hero": r["hero"], "kind": kind,
                    "gx": x / WORLD_PER_GRID, "gy": z / WORLD_PER_GRID})
    cal = calibrate(raw, lookup)
    coords = load_coords(args.coords, lookup, cal["dt"], t1)
    stats = build_stats(coords, t1)
    events = load_events(args.frames, args.sample, t1)
    n_cmd = sum(int(r.get("total") or 0)
                for r in read_csv(args.frames) if r.get("sample") == args.sample)

    per = "；".join("%s %d 条 / 中位 %.2f 格" % (h, v["n"], v["median"])
                   for h, v in cal["per_entity"].items())
    dtxt = ("+%d" % cal["dt"]) if cal["dt"] >= 0 else str(cal["dt"])
    peak = "%02d:%02d–%02d:%02d" % (stats["peak_min"], 0,
                                    stats["peak_min"] + 1, 0)
    counts = stats["counts"]
    repl = {
        "__POSITIONS__": json.dumps(players, ensure_ascii=False,
                                    separators=(",", ":")),
        "__EVENTS__": json.dumps(events, ensure_ascii=False,
                                 separators=(",", ":")),
        "__COORDS__": json.dumps(coords, ensure_ascii=False,
                                 separators=(",", ":")),
        "__STATS__": json.dumps(stats, ensure_ascii=False,
                                separators=(",", ":")),
        "__T1__": str(t1),
        "__NSEC__": str(t1 + 1),
        "__NCMD__": format(n_cmd, ","),
        "__DUR__": "%02d:%02d" % (t1 // 60, t1 % 60),
        "__SAMPLE__": args.sample,
        "__N_AIM__": str(counts.get("aim", 0)),
        "__N_TARGET__": str(counts.get("target", 0)),
        "__N_ANCHOR__": str(counts.get("anchor", 0)),
        "__N_COORD__": str(stats["total"]),
        "__AIM_HEROES__": "、".join(stats["entities"].get("aim", [])) or "—",
        "__ANCHOR_HEROES__": "、".join(stats["entities"].get("anchor", [])) or "—",
        "__PEAK__": peak,
        "__PEAK_N__": str(stats["peak_n"]),
        "__CAL_N__": str(cal["n"]),
        "__CAL_DT__": dtxt,
        "__CAL_MED__": "%.2f" % cal["median"] if cal["median"] is not None else "—",
        "__CAL_MEAN__": "%.2f" % cal["mean"] if cal["mean"] is not None else "—",
        "__CAL_P90__": "%.2f" % cal["p90"] if cal["p90"] is not None else "—",
        "__CAL_PER__": per or "—",
    }
    doc = TEMPLATE
    for k, v in repl.items():
        doc = doc.replace(k, v)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)
    print("OK players=%d seconds=%d cmds=%s coords=%s cal_dt=%+ds med=%s size=%d" %
          (len(players), t1 + 1, n_cmd, stats["counts"], cal["dt"],
           cal["median"], len(doc.encode("utf-8"))))
    print("OUT " + os.path.abspath(args.out))


if __name__ == "__main__":
    main()
