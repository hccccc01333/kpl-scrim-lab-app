# -*- coding: utf-8 -*-
"""
replay_codec / build_review.py

「单局解析数据核对台」：把逐条命令、技能朝向、购买、加点、死亡区间、
检查点状态全部摊开成可查、可筛选、可导出的界面。

定位：这是**数据核对界面**，不是产品页面。可交付物是
  sample_data/20261102_command_events.csv 等结构化表 + 本页字段字典。

数据分层（页面必须标注，不得混用）：
  文件解码  逐条帧命令（带施法者）、显式世界坐标、帧命令计数
  UI 采样   官方逐秒位置、30 秒团队经济、结算面板
  引擎实测  10 个检查点的 KDA / 等级 / 金币
  推断      检查点 deaths 累计差分得到的「死亡区间」，只能到区间级
  不提供    逐条死亡时刻、逐条击杀归属、逐帧血量/坐标、伤害

死亡口径（重要）：.abc 内没有逐条死亡事件；0x81=死亡 已被逐字节推翻，
结算包在 30 个样本 0 命中。本页的死亡只来自检查点差分，且检查点止于
09:37，之后 2 分钟的死亡没有检查点覆盖。地图上不再画「红叉」——
那会让人误以为多人同一秒阵亡；改为红色虚线环 + 区间 +N 徽标。

用法：
  python build_review.py
  python build_review.py --data-dir <sample_data> --out <html>
"""

import argparse
import csv
import json
import math
import os
from collections import defaultdict, Counter

SAMPLE = "20261102_161129"
GRID = 57.0
HERO_ABBR = {
    "钟馗": "钟", "妲己": "妲", "孙悟空": "猴", "关羽": "关",
    "百里守约": "百", "公孙离": "离", "吕布": "吕", "貂蝉": "貂",
    "兰陵王": "兰", "张良": "张",
}
SKILL_NAMES = {
    "USEDIRECTIONALSKILL": "方向技能",
    "USEOBJECTIVESKILL": "目标技能",
    "USEPOSITIONSKILL": "位置技能",
    "BUYEQUIP": "购买装备",
    "LEARNSKILL": "技能加点",
    "CC": "状态标记",
}


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def jdump(v):
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def jsafe(v):
    # 防止数据里出现 </script> 提前闭合脚本
    return jdump(v).replace("</", "<\\/")


def load_all(d):
    pos = read_csv(os.path.join(d, "20261102_official_positions.csv"))
    coords = read_csv(os.path.join(d, "20261102_replay_coords.csv"))
    events_all = read_csv(os.path.join(d, "20261102_command_events.csv"))
    frames = read_csv(os.path.join(d, "20261102_frame_commands.csv"))
    death = read_csv(os.path.join(d, "20261102_death_intervals.csv"))
    ledger = read_csv(os.path.join(d, "20261102_death_ledger.csv"))
    tg = read_csv(os.path.join(d, "20261102_team_gold.csv"))
    panel = read_csv(os.path.join(d, "20261102_panel_truth.csv"))
    state = read_csv(os.path.join(d, "state_series_161129_10pt.csv"))

    t1 = max(int(float(r["t_sec"])) for r in pos)
    meta = {}
    for r in pos:
        meta[r["entity"]] = (r["hero"],
                             "blue" if str(r["camp"]) == "1" else "red")

    # 十人逐秒位置
    px = defaultdict(dict)
    for r in pos:
        px[r["entity"]][int(float(r["t_sec"]))] = (
            float(r["grid_x"]), float(r["grid_y"]))
    players = []
    for e, (hero, camp) in sorted(meta.items()):
        players.append({
            "entity": e, "hero": hero, "camp": camp,
            "abbr": HERO_ABBR.get(hero, hero[:1]),
            "x": [px[e].get(t, [None, None])[0] for t in range(t1 + 1)],
            "y": [px[e].get(t, [None, None])[1] for t in range(t1 + 1)],
        })
    players.sort(key=lambda p: (p["camp"], p["hero"]))

    # 页面事件浏览器只放语义明确的事件；CC 语义未定名，留在 CSV 供核对
    ev = []
    for r in events_all:
        if r["name"] == "CC":
            continue
        ev.append({
            "t": int(r["t_sec"]), "frame": int(r["frame"]),
            "e": r["entity"], "hero": r["hero"], "camp": r["camp"],
            "n": r["name"], "d": r["detail"],
            "slot": r["slot"], "ot": r["object_target"],
            "deg": float(r["degree"]) / 100.0 if r["degree"] else None,
            "tx": float(r["target_x"]) / 1000.0 if r["target_x"] else None,
            "ty": float(r["target_y"]) / 1000.0 if r["target_y"] else None,
        })
    ev.sort(key=lambda x: (x["t"], x["frame"], x["e"]))

    # 显式世界坐标（沿用 build_map 的 +3s 对齐结果）
    co = []
    for r in coords:
        x, z = float(r["x"]), float(r["z"])
        if (x, z) == (0.0, 0.0):
            continue
        kind = {"tail_0x02_82_aim": "aim",
                "tail_0x01_2c_target": "target",
                "tail_0x01_len14_position": "anchor"}.get(r["source"])
        if not kind:
            continue
        t = int(round(float(r["time_s"]) + 3))
        if 0 <= t <= t1:
            co.append({"t": t, "k": kind, "e": r["entity_id"],
                       "hero": r["hero"], "gx": round(x / 1000, 2),
                       "gy": round(z / 1000, 2)})
    co.sort(key=lambda c: (c["t"], c["k"]))

    # 死亡区间 + 对账
    di = [{"hero": r["hero"], "camp": r["camp"],
           "s": int(r["start_sec"]), "e": int(r["end_sec"]),
           "sc": r["start_clock"], "ec": r["end_clock"],
           "n": int(r["deaths_delta"])} for r in death]
    ld = [{"hero": r["hero"], "camp": r["camp"],
           "panel": int(r["panel_deaths"]),
           "last": int(r["checkpoint_last_deaths"]),
           "unc": int(r["uncovered_deaths"]),
           "cov": int(r["covered_intervals"])} for r in ledger]

    # 检查点：团队合计 + 逐人 KDA / 等级 / 金币
    cps = defaultdict(lambda: {"blue": 0, "red": 0, "bk": 0, "rk": 0})
    clock = {}
    cph = defaultdict(dict)
    for r in state:
        s = int(float(r["second"]))
        clock[s] = r["clock"]
        side = "blue" if r["camp"] == "blue" else "red"
        cps[s][side] += int(float(r["gold"]))
        cps[s]["bk" if side == "blue" else "rk"] += int(float(r["kills"]))
        cph[r["hero"]][str(s)] = {
            "k": int(float(r["kills"])), "d": int(float(r["deaths"])),
            "a": int(float(r["assists"])), "lv": int(float(r["level"])),
            "g": int(float(r["gold"])),
        }
    cp = [{"t": s, "clock": clock[s], **cps[s]} for s in sorted(cps)]

    tgold = [{"t": int(float(r["t_sec"])), "b": int(r["blue"]),
              "r": int(r["red"]), "d": int(r["diff"])} for r in tg]
    pn = [{"e": r["entity"], "hero": r["hero"],
           "camp": "blue" if str(r["team"]) == "1" else "red",
           "k": int(r["kills"]), "d": int(r["deaths"]),
           "a": int(r["assists"]), "g": int(r["gold"]),
           "s": float(r["score"])} for r in panel]

    # 十人事件矩阵
    mat = []
    for p in players:
        h = p["hero"]
        c = Counter(x["n"] for x in ev if x["hero"] == h)
        cc = Counter(x["k"] for x in co if x["hero"] == h)
        l = next((z for z in ld if z["hero"] == h), {})
        pa = next((z for z in pn if z["hero"] == h), {})
        mat.append({
            "hero": h, "camp": p["camp"],
            "dir": c["USEDIRECTIONALSKILL"], "obj": c["USEOBJECTIVESKILL"],
            "pos": c["USEPOSITIONSKILL"], "buy": c["BUYEQUIP"],
            "learn": c["LEARNSKILL"],
            "panel_d": l.get("panel", 0), "last": l.get("last", 0),
            "unc": l.get("unc", 0), "cov": l.get("cov", 0),
            "aim": cc["aim"], "target": cc["target"], "anchor": cc["anchor"],
            "k": pa.get("k", 0), "d": pa.get("d", 0), "a": pa.get("a", 0),
            "gold": pa.get("g", 0), "score": pa.get("s", 0),
        })

    # 死亡热力：10 人 × 9 个检查点区间
    bounds = [c["t"] for c in cp]
    heat = []
    for p in players:
        row = []
        for s0, s1 in zip(bounds, bounds[1:]):
            row.append(sum(x["n"] for x in di
                           if x["hero"] == p["hero"] and x["s"] == s0))
        heat.append({"hero": p["hero"], "camp": p["camp"], "row": row})

    # 技能槽位矩阵 + 方向角度直方图（24 箱 × 15°）
    slot_vals = sorted({int(x["slot"]) for x in ev
                        if x["n"].startswith("USE") and x["slot"]})
    slots = []
    for p in players:
        row = []
        for s in slot_vals:
            row.append(sum(1 for x in ev if x["hero"] == p["hero"]
                           and x["n"].startswith("USE")
                           and x["slot"] == str(s)))
        slots.append({"hero": p["hero"], "row": row})
    hist = [0] * 24
    for x in ev:
        if x["deg"] is not None:
            idx = int((x["deg"] + 180) // 15) % 24
            hist[idx] += 1

    n_cmd = sum(int(r["total"]) for r in frames
                if r["sample"] == SAMPLE)
    return {
        "players": players, "ev": ev, "co": co, "di": di, "ld": ld,
        "cp": cp, "cph": dict(cph), "tg": tgold, "panel": pn, "mat": mat,
        "heat": heat, "slots": slots, "slot_vals": slot_vals, "hist": hist,
        "t1": t1, "n_cmd": n_cmd,
        "n_ev_all": len(events_all),
        "n_cc": sum(1 for r in events_all if r["name"] == "CC"),
        "n_skill": sum(1 for x in ev if x["n"].startswith("USE")),
        "n_buy": sum(1 for x in ev if x["n"] == "BUYEQUIP"),
        "n_learn": sum(1 for x in ev if x["n"] == "LEARNSKILL"),
        "n_coord": len(co),
        "panel_deaths": sum(z["panel"] for z in ld),
        "cp_deaths": sum(z["last"] for z in ld),
        "unc_deaths": sum(z["unc"] for z in ld),
        "di_sum": sum(x["n"] for x in di),
        "n_intervals": len(bounds) - 1,
        "cp_last_clock": clock[bounds[-1]],
        "cp_last_sec": bounds[-1],
    }


def html_table(headers, rows, cls=""):
    h = ['<table class="%s"><thead><tr>' % cls]
    h += ["<th>%s</th>" % x for x in headers]
    h.append("</tr></thead><tbody>")
    for r in rows:
        h.append("<tr>" + "".join("<td>%s</td>" % c for c in r) + "</tr>")
    h.append("</tbody></table>")
    return "".join(h)


def terrain_svg():
    """静态峡谷底图。颜色全部走 CSS 变量，支持深/浅底图切换。

    自绘示意，非官方素材：蓝方基地在左下、红方在右上，河道为左上→右下
    对角线，三路为左上折线 / 反对角 / 右下折线。坐标与格坐标 ±57 对齐。
    """
    o = []
    A = o.append
    # 两个半场
    A('<path d="M24 24 L24 576 L576 576 Z" fill="var(--jungle)" opacity=".92"/>')
    A('<path d="M24 24 L576 24 L576 576 Z" fill="var(--jungle2)" opacity=".92"/>')
    # 草丛 / 野区色块
    for cx, cy, rx, ry in [(150, 470, 44, 27), (220, 512, 34, 22),
                           (96, 348, 29, 44), (300, 438, 36, 20),
                           (450, 130, 44, 27), (380, 88, 34, 22),
                           (504, 252, 29, 44), (300, 162, 36, 20)]:
        A('<ellipse cx="%d" cy="%d" rx="%d" ry="%d" fill="#1f7a52" '
          'opacity=".13"/>' % (cx, cy, rx, ry))
    # 河道（左上 → 右下）
    A('<path d="M24 24 L576 576" stroke="var(--river-edge)" '
      'stroke-width="76" fill="none" opacity=".45"/>')
    A('<path d="M24 24 L576 576" stroke="var(--river)" '
      'stroke-width="60" fill="none"/>')
    A('<path d="M24 24 L576 576" stroke="var(--river-core)" '
      'stroke-width="22" fill="none" opacity=".72"/>')
    # 三路
    lanes = [("M24 576 L24 24 L576 24", "上路"),
             ("M24 576 L576 24", "中路"),
             ("M24 576 L576 576 L576 24", "下路")]
    for d, _ in lanes:
        A('<path d="%s" stroke="var(--lane-edge)" stroke-width="30" '
          'fill="none" stroke-linejoin="round" opacity=".55"/>' % d)
        A('<path d="%s" stroke="var(--lane)" stroke-width="22" '
          'fill="none" stroke-linejoin="round"/>' % d)
        A('<path d="%s" stroke="var(--lane-dash)" stroke-width="1.3" '
          'fill="none" stroke-dasharray="7 12" opacity=".85"/>' % d)
    # 防御塔：每方每路 3 座
    towers = []
    # 边界塔收进路面内侧：既不被 clip 裁成半个小三角，也不像装饰边框
    for y in (470, 390, 310):
        towers.append((48, y, "blue"))
    for x in (470, 390, 310):
        towers.append((x, 48, "red"))
    for x in (130, 210, 290):
        towers.append((x, 552, "blue"))
    for y in (130, 210, 290):
        towers.append((552, y, "red"))
    for p in (0.18, 0.33, 0.47):
        towers.append((24 + 552 * p, 576 - 552 * p, "blue"))
    for p in (0.53, 0.67, 0.82):
        towers.append((24 + 552 * p, 576 - 552 * p, "red"))
    for x, y, c in towers:
        col = "var(--tower-b)" if c == "blue" else "var(--tower-r)"
        side = "蓝" if c == "blue" else "红"
        A('<rect x="%.1f" y="%.1f" width="10.5" height="10.5" rx="1.5" '
          'fill="var(--mapbg)" stroke="%s" stroke-width="2" '
          'transform="rotate(45 %.1f %.1f)"><title>%s方防御塔</title></rect>'
          % (x - 5.25, y - 5.25, col, x, y, side))
    # 红蓝 BUFF 野怪点
    for x, y, lab, col in [(168, 424, "蓝BUFF", "#3b82f6"),
                           (250, 496, "红BUFF", "#ef4444"),
                           (432, 176, "蓝BUFF", "#3b82f6"),
                           (350, 104, "红BUFF", "#ef4444")]:
        A('<circle cx="%d" cy="%d" r="8" fill="none" stroke="%s" '
          'stroke-width="1.8" opacity=".9"/>' % (x, y, col))
        A('<circle cx="%d" cy="%d" r="3" fill="%s" opacity=".85"/>'
          % (x, y, col))
        A('<text x="%d" y="%d" text-anchor="middle" font-size="9" '
          'fill="var(--terrain-txt)">%s</text>' % (x, y + 23, lab))
    # 主宰 / 暴君坑
    for x, y, lab, col in [(404, 272, "主宰", "#a78bfa"),
                           (222, 430, "暴君", "#fbbf24")]:
        A('<path d="M%d %d L%d %d L%d %d L%d %d Z" fill="none" '
          'stroke="%s" stroke-width="1.8" opacity=".85"/>'
          % (x, y - 13, x + 13, y, x, y + 13, x - 13, y, col))
        A('<text x="%d" y="%d" text-anchor="middle" font-size="9.5" '
          'fill="var(--terrain-txt)">%s</text>' % (x, y + 27, lab))
    # 基地水晶
    for x, y, c, lab in [(80, 520, "blue", "蓝方基地"),
                         (520, 80, "red", "红方基地")]:
        col = "#3b82f6" if c == "blue" else "#ef4444"
        A('<circle cx="%d" cy="%d" r="27" fill="none" stroke="%s" '
          'stroke-width="2" opacity=".65"/>' % (x, y, col))
        A('<path d="M%d %d L%d %d L%d %d L%d %d L%d %d L%d %d Z" '
          'fill="%s" opacity=".88"/>'
          % (x, y - 17, x + 15, y - 8, x + 15, y + 8,
             x, y + 17, x - 15, y + 8, x - 15, y - 8, col))
        A('<circle cx="%d" cy="%d" r="4.5" fill="#fff"/>' % (x, y))
        A('<text x="%d" y="%d" text-anchor="middle" font-size="10.5" '
          'font-weight="600" fill="var(--terrain-txt)">%s</text>'
          % (x, y + 44, lab))
    # 区域标注
    txt = [("上路", 152, 46, 0), ("下路", 452, 560, 0),
           ("中路", 218, 348, -45), ("河道", 452, 452, 45),
           ("蓝方野区", 330, 520, 0), ("红方野区", 270, 80, 0)]
    for lab, x, y, rot in txt:
        tr = ' transform="rotate(%d %d %d)"' % (rot, x, y) if rot else ""
        A('<text x="%d" y="%d" text-anchor="middle" font-size="11" '
          'letter-spacing="1" fill="var(--terrain-txt)" opacity=".9"%s>'
          '%s</text>' % (x, y, tr, lab))
    A('<rect x="24" y="24" width="552" height="552" rx="10" fill="none" '
      'stroke="var(--lane-edge)" stroke-width="2"/>')
    return "".join(o)


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>单局解析数据核对台 · __SAMPLE__</title>
<style>
:root{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--blue:#3b82f6;
 --red:#ef4444;--aim:#fb923c;--obj:#a78bfa;--pos:#fbbf24;--warn:#b91c1c;
 --mapbg:#0a1424;--jungle:#101f36;--jungle2:#13243c;
 --lane:#2b3a50;--lane-edge:#3c4d66;--lane-dash:#5b6b84;
 --river:#102f52;--river-core:#1a4d80;--river-edge:#265684;
 --terrain-txt:#8095b1;--tower-b:#60a5fa;--tower-r:#f87171;}
body.light{--mapbg:#eef3f8;--jungle:#e6edf5;--jungle2:#e9f0f7;
 --lane:#dfe7f0;--lane-edge:#cbd7e4;--lane-dash:#b6c4d4;
 --river:#cfe3f7;--river-core:#b9d8f4;--river-edge:#a9cbe9;
 --terrain-txt:#6b7d94;--tower-b:#2563eb;--tower-r:#dc2626;}
*{box-sizing:border-box}
body{margin:0;background:#eef2f7;color:var(--ink);font-family:-apple-system,
 BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;
 font-size:13px;line-height:1.55}
.wrap{max-width:1440px;margin:18px auto;background:#fff;
 border:1px solid var(--line);border-radius:12px;padding:22px 26px 30px;
 box-shadow:0 2px 14px rgba(15,23,42,.05)}
h1{font-size:21px;font-weight:650;margin:0 0 3px}
h2{font-size:15px;font-weight:650;margin:26px 0 9px;padding-bottom:6px;
 border-bottom:2px solid var(--ink)}
h3{font-size:13px;font-weight:650;margin:14px 0 7px}
.sub{color:var(--muted);font-size:12px}
.tag{display:inline-block;padding:1px 8px;border-radius:20px;font-size:10.5px;
 font-weight:600;margin-left:5px;vertical-align:middle}
.t-file{background:#e0f2fe;color:#075985}.t-ui{background:#fef3c7;color:#92400e}
.t-engine{background:#dcfce7;color:#166534}.t-inf{background:#f3e8ff;color:#6b21a8}
.stats{display:flex;gap:8px;flex-wrap:wrap;margin:14px 0 8px}
.stats div{flex:1 1 118px;border:1px solid var(--line);border-radius:8px;
 padding:8px 10px;background:#f8fafc}
.stats b{display:block;font-size:19px;font-variant-numeric:tabular-nums;line-height:1.2}
.stats span{font-size:10.5px;color:var(--muted)}
.notice{background:#f8fafc;border-left:4px solid #0f172a;border-radius:0 8px 8px 0;
 padding:10px 14px;font-size:12.5px;margin:12px 0}
.warn{background:#fef2f2;border-left:3px solid #ef4444;padding:10px 14px;
 border-radius:0 7px 7px 0;font-size:12.5px;margin:12px 0}
.snap{display:flex;gap:0;flex-wrap:wrap;align-items:stretch;margin:14px 0 4px;
 border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#f8fafc}
.snap>div{padding:10px 15px;border-right:1px solid var(--line);min-width:118px;flex:1}
.snap>div:last-child{border-right:0}
.snap b{display:block;font-size:20px;font-variant-numeric:tabular-nums;line-height:1.2}
.snap span{font-size:10.5px;color:var(--muted)}
.snap .clockcell{background:#0f172a;color:#fff;min-width:158px;flex:0 0 auto}
.snap .clockcell b{font-size:29px;letter-spacing:1px}
.snap .clockcell span{color:#94a3b8}
.snap .hl{background:#fff7ed}.snap .hl b{color:#c2410c}
.grid{display:flex;gap:18px;flex-wrap:wrap;margin-top:14px;align-items:flex-start}
.mapbox{flex:1.15 1 540px;min-width:360px}.side{flex:1 1 400px;min-width:330px}
svg.map{width:100%;height:auto;background:var(--mapbg);border:1px solid #1e293b;
 border-radius:10px;display:block;box-shadow:0 3px 16px rgba(2,6,23,.18)}
body.light svg.map{border-color:var(--line)}
.ctrl{display:flex;align-items:center;gap:7px;flex-wrap:wrap;margin:10px 0 0;
 padding:9px 10px;border:1px solid var(--line);border-radius:9px;background:#f8fafc}
.ctrl .row{display:flex;align-items:center;gap:7px;flex-wrap:wrap;width:100%}
.ctrl .row.seek input[type=range]{flex:1 1 200px}
button{border:1px solid var(--line);background:#fff;border-radius:6px;
 padding:5px 11px;font-size:12px;cursor:pointer;font-weight:500}
button.primary{background:#0f172a;color:#fff;border-color:#0f172a}
button:hover{border-color:#94a3b8}
button.ghost{background:transparent}
input[type=range]{accent-color:#0f172a;min-width:120px}
select,input[type=text],input[type=number]{border:1px solid var(--line);
 border-radius:6px;padding:5px 7px;font-size:12px;background:#fff}
.clock{font-variant-numeric:tabular-nums;font-size:19px;font-weight:650;
 min-width:62px;text-align:right}
.layers{display:flex;gap:10px;flex-wrap:wrap;margin:9px 0 0;font-size:11.5px;
 color:var(--muted);padding:8px 10px;border:1px dashed var(--line);border-radius:8px}
.layers label{cursor:pointer;white-space:nowrap}
.layers input{vertical-align:middle;margin-right:3px;accent-color:#0f172a}
.legend{display:grid;grid-template-columns:repeat(auto-fit,minmax(163px,1fr));
 gap:8px;margin:10px 0 0}
.legend div{border:1px solid var(--line);border-radius:7px;padding:7px 10px;
 font-size:11px;background:#fff;line-height:1.45}
.legend b{display:block;font-size:11.5px;margin-bottom:1px}
.sw{display:inline-block;width:11px;height:11px;border-radius:3px;
 vertical-align:-1px;margin-right:5px}
table{width:100%;border-collapse:collapse;font-size:11.5px}
th{text-align:left;color:var(--muted);font-size:10px;font-weight:600;
 padding:5px 5px;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:4px 5px;border-bottom:1px solid #f1f5f9;font-variant-numeric:tabular-nums}
tr.blue td:first-child{border-left:3px solid var(--blue)}
tr.red td:first-child{border-left:3px solid var(--red)}
tbody tr{cursor:pointer}tbody tr:hover{background:#f1f5f9}
.dim{color:#94a3b8}
.scroll{max-height:330px;overflow:auto;border:1px solid var(--line);border-radius:8px}
.scroll table{border-collapse:collapse}.scroll thead th{position:sticky;top:0;
 background:#f8fafc;z-index:1}
.evcards{max-height:330px;overflow:auto;border:1px solid var(--line);
 border-radius:8px;background:#fafbfd;padding:6px}
.evgroup{margin-bottom:6px;border-radius:7px;overflow:hidden;cursor:pointer}
.evgroup.cur{outline:2px solid #0f172a}
.evsec{display:flex;justify-content:space-between;padding:3px 8px;
 background:#eef2f7;font-size:10.5px;color:var(--muted);font-weight:600}
.evgroup.cur .evsec{background:#0f172a;color:#fff}
.evsec .now{color:#fbbf24;margin-left:5px}
.evcard{background:#fff;border-left:3px solid #cbd5e1;padding:4px 8px;
 margin:3px 4px;border-radius:0 5px 5px 0;font-size:11.5px}
.evcard .evhero{font-weight:650;margin-right:6px}
.evcard .evkind{font-size:10px;padding:1px 6px;border-radius:10px;
 background:#f1f5f9;color:#475569;margin-right:6px}
.evcard .evdetail{color:#334155;font-size:11px;margin-top:1px}
.evempty{color:#cbd5e1;font-size:11px;padding:2px 12px}
.dcard{border:1px solid #fecaca;background:#fff7f7;border-radius:8px;
 padding:9px 11px;font-size:11.5px;margin:8px 0}
.dcard .dhead{font-weight:650;color:#991b1b;font-size:12.5px;margin-bottom:5px}
.dcard .dhead span{font-weight:400;color:#b91c1c;font-size:10.5px;
 margin-left:6px}
.drow{display:inline-flex;align-items:center;gap:5px;background:#fff;
 border:1px solid #fee2e2;border-radius:6px;padding:2px 8px;margin:2px 4px 2px 0}
.drow b{color:#b91c1c}
.dfoot{margin-top:6px;color:#7f1d1d;font-size:10.5px}
.dnil{color:var(--muted);font-size:11.5px;padding:6px 2px}
.cap{font-size:11px;color:var(--muted);margin:6px 0 0;line-height:1.65}
.filters{display:flex;gap:7px;flex-wrap:wrap;align-items:center;margin:9px 0}
.filters label{font-size:11px;color:var(--muted)}
.pager{display:flex;gap:8px;align-items:center;margin:8px 0;font-size:11.5px}
.tl{width:100%;height:auto;border:1px solid var(--line);border-radius:8px;
 background:#fcfdff;display:block;cursor:crosshair}
.heat td{text-align:center;min-width:34px}
.heat .v0{color:#cbd5e1}.heat .v1{background:#fee2e2;color:#991b1b;font-weight:600}
.heat .l2{background:#fca5a5;color:#7f1d1d;font-weight:700}
footer{margin-top:24px;padding-top:10px;border-top:1px solid var(--line);
 font-size:10.5px;color:var(--muted)}
code{background:#f1f5f9;padding:1px 4px;border-radius:3px;font-size:11px}
@media(max-width:900px){.wrap{padding:16px 12px;margin:0;border:0}
 .snap .clockcell{min-width:130px}}
</style>
</head>
<body>
<div class="wrap">
<h1>单局解析数据核对台 <span class="tag t-file">文件解码</span>
<span class="tag t-engine">引擎实测</span><span class="tag t-ui">UI 采样</span>
<span class="tag t-inf">推断</span></h1>
<p class="sub">样本 __SAMPLE__ · 11:33 · 5v5 ·
<b>这是数据核对界面，不是产品页</b>；可交付物是
<code>20261102_command_events.csv</code> 等结构化表与页面底部字段字典。</p>

<div class="stats">
 <div><b>__N_CMD__</b><span>帧命令总数（0 未解析）</span></div>
 <div><b>__N_EV__</b><span>带施法者的逐条事件</span></div>
 <div><b>__N_SKILL__</b><span>技能释放（含槽位/朝向）</span></div>
 <div><b>__N_BUY__</b><span>逐条购买（含装备名）</span></div>
 <div><b>__N_LEARN__</b><span>逐条加点</span></div>
 <div><b>__N_COORD__</b><span>显式世界坐标</span></div>
 <div><b>__N_DEATH__</b><span>结算死亡总数（面板）</span></div>
 <div><b>__N_CP__</b><span>引擎检查点</span></div>
</div>

<div class="snap">
 <div class="clockcell"><b id="snapTime">00:00</b><span>当前时刻 · 营地秒号</span></div>
 <div class="hl"><b id="snapSkill">0</b><span>本秒技能释放</span></div>
 <div><b id="snapBuy">0</b><span>本秒购买 / 加点</span></div>
 <div><b id="snapDeath">—</b><span>当前区间死亡差分</span></div>
 <div><b id="snapGold">—</b><span>最近经济差（30s 采样）</span></div>
 <div><b id="snapCp">—</b><span>最近引擎检查点</span></div>
</div>
<p class="cap">快照条随播放/拖动实时更新；经济差与检查点取「不晚于当前秒的最近采样点」，
不是当前秒的插值。</p>

<div class="grid">
 <div class="mapbox">
  <h3 style="margin-top:0">峡谷复盘图 · 当前秒事件 <span class="tag t-file">文件解码</span>
    <span class="tag t-ui">UI 采样 · 1 Hz</span></h3>
  <svg class="map" viewBox="0 0 600 600" id="map" role="img"
       xmlns="http://www.w3.org/2000/svg">
   <title>王者峡谷示意图：十人位置、技能朝向与落点、死亡检查点区间</title>
   <defs>
    <clipPath id="sq"><rect x="24" y="24" width="552" height="552" rx="10"/></clipPath>
    <marker id="arrowSkill" markerWidth="10" markerHeight="10" refX="8" refY="5"
      orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0 0 L10 5 L0 10 Z" fill="#fb923c"/></marker>
    <marker id="arrowPos" markerWidth="10" markerHeight="10" refX="8" refY="5"
      orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0 0 L10 5 L0 10 Z" fill="#fbbf24"/></marker>
    <filter id="dotShadow" x="-70%" y="-70%" width="240%" height="240%">
      <feDropShadow dx="0" dy="1.5" stdDeviation="2" flood-color="#000"
        flood-opacity=".6"/></filter>
   </defs>
   <g clip-path="url(#sq)">
    <rect x="24" y="24" width="552" height="552" fill="var(--mapbg)"/>
    <g id="terrain">__TERRAIN__</g>
    <g id="trails"></g><g id="links"></g>
    <g id="lAnchor"></g><g id="lTarget"></g><g id="lAim"></g>
    <g id="arrows"></g>
   </g>
   <g id="dots"></g><g id="labels"></g>
  </svg>

  <div class="ctrl">
   <div class="row">
    <button class="primary" id="play">▶ 播放</button>
    <button id="btnPrevSkill" title="跳到上一条技能">⏮ 上一技能</button>
    <button id="btnNextSkill" title="跳到下一条技能">下一技能 ⏭</button>
    <button id="btnNextDeath" title="跳到下一个有死亡差分的检查点区间">下一死亡区间 ⏭</button>
    <button id="btnReset">⟲ 回到 00:00</button>
    <button class="ghost" id="theme">切换浅色底图</button>
   </div>
   <div class="row seek">
    <input type="range" id="seek" min="0" max="__T1__" value="0" step="1">
    <span class="clock" id="clock">00:00</span>
    <select id="speed"><option value="1">1×</option><option value="2">2×</option>
     <option value="4" selected>4×</option><option value="8">8×</option></select>
    <select id="win"><option value="10">落点 ±10s</option>
     <option value="20" selected>落点 ±20s</option>
     <option value="60">落点 ±60s</option><option value="9999">落点全场</option></select>
   </div>
  </div>
  <div class="layers">
   <label><input type="checkbox" id="ckTrail" checked>轨迹（1 Hz 采样连线）</label>
   <label><input type="checkbox" id="ckArrow" checked>技能朝向箭头</label>
   <label><input type="checkbox" id="ckAim" checked>技能落点</label>
   <label><input type="checkbox" id="ckTarget" checked>目标技能标记</label>
   <label><input type="checkbox" id="ckAnchor" checked>位置锚点</label>
   <label><input type="checkbox" id="ckDeath" checked>死亡区间徽标</label>
   <label>英雄名 <select id="labelMode" style="padding:2px 5px;font-size:11px">
     <option value="all" selected>十人全部</option>
     <option value="active">仅本秒有事件 / 死亡区间者</option>
     <option value="none">不显示</option>
    </select></label>
   <label>轨迹范围 <select id="trailMode" style="padding:2px 5px;font-size:11px">
     <option value="active" selected>仅本秒有事件者</option>
     <option value="all">十人全部</option><option value="focus">仅聚焦英雄</option>
    </select></label>
  </div>
  <div class="legend">
   <div><b>英雄位置</b><span class="sw" style="background:#3b82f6"></span>蓝方 /
    <span class="sw" style="background:#ef4444"></span>红方，圆内为简称，
    旁附全名标签（左右交替避让）；团战太挤时可在图层区切换为
    「仅本秒有事件 / 死亡区间者」。<b>黄环</b>=本秒有事件，
    <b>红虚线环</b>=处于死亡差分区间。</div>
   <div><b>方向技能</b><span class="sw" style="background:#fb923c"></span>橙箭头 =
    施法朝向（<code>degree/100</code>），带角度标注；近 2 秒余辉半透明。</div>
   <div><b>位置技能 / 落点</b><span class="sw" style="background:#fbbf24"></span>
    黄虚线 = 施法者→地面落点，橙菱形 = 文件内显式落点坐标（按时间窗渐隐）。</div>
   <div><b>目标技能</b><span class="sw" style="background:#a78bfa"></span>
    紫小环 = 该秒对某对象施法；<code>object_target</code> 是另一套 ID，
    <b>未映射到十人</b>，因此不画目标连线。</div>
   <div><b>死亡（推断）</b><span class="sw" style="background:#991b1b"></span>
    <code>+N</code> 徽标 = 该英雄在<b>整个检查点区间</b>内 deaths 增量为 N，
    <b>不是这一秒阵亡</b>，也不是死亡坐标。</div>
   <div><b>轨迹（UI 采样）</b>虚线 + 每秒小点 = 营地 1 Hz 位置连线，
    相邻秒之间<b>不是真实走位</b>；默认只画本秒有事件者。</div>
  </div>
  <p class="cap">空格播放/暂停，← / → 逐秒，N 跳下一条技能，Shift + ← / → 跳 ±10 秒。
    点击右侧英雄行可聚焦单人。峡谷为自绘示意图（格坐标 ±57，蓝方出生
    −55/−57、红方 +55/+57），非官方素材；底图只用于判断大致方位，不用于测距。</p>
 </div>

 <div class="side">
  <h3 style="margin-top:0">当前秒前后 · 逐条事件 <span class="tag t-file">文件解码</span></h3>
  <div class="evcards" id="evcards"></div>
  <p class="cap" id="evcap"></p>

  <h3>当前检查点区间 · 死亡差分 <span class="tag t-inf">推断</span></h3>
  <div class="dcard" id="dcard"></div>

  <h3>十人位置与最近检查点状态 <span class="tag t-ui">UI 采样</span>
   <span class="tag t-engine">引擎实测</span></h3>
  <div class="scroll" style="max-height:270px">
   <table><thead><tr><th>阵营</th><th>英雄</th><th>格坐标</th><th>位移</th>
    <th>本秒技能</th><th>最近 KDA</th><th>Lv</th></tr></thead>
    <tbody id="roster"></tbody></table>
  </div>
  <p class="cap">位移 = 与上一整秒的网格距离（计算值）；最近 KDA / Lv 取
    <b>不晚于当前秒的最后一个引擎检查点</b>，不是实时值，也不是结算数据。</p>
 </div>
</div>

<h2>全时间轴 · 事件 / 死亡 / 经济 / 检查点</h2>
<svg class="tl" id="tl" viewBox="0 0 1000 310" xmlns="http://www.w3.org/2000/svg">
 <title>分层时间线</title>
</svg>
<p class="cap">自上而下：技能释放（按秒堆叠）／购买·加点／
  <b>死亡区间（10 行，每行一个英雄，红条 = 检查点区间宽度，数字 = 该区间 deaths 增量）</b>／
  检查点（绿竖线）／团队经济差（30 秒采样折线）。
  点击时间线任意位置跳转到该秒。<b>死亡条是区间，不是死亡时刻</b>。</p>

<h2>逐条事件浏览器 <span class="tag t-file">文件解码</span></h2>
<div class="filters">
 <label>类型</label><select id="fKind"><option value="">全部</option>
  <option value="USE">技能释放</option><option value="USEDIRECTIONALSKILL">方向技能</option>
  <option value="USEOBJECTIVESKILL">目标技能</option><option value="USEPOSITIONSKILL">位置技能</option>
  <option value="BUYEQUIP">购买装备</option><option value="LEARNSKILL">技能加点</option></select>
 <label>英雄</label><select id="fHero"><option value="">全部 10 人</option>__HERO_OPT__</select>
 <label>秒</label><input type="number" id="fT0" value="0" min="0" max="__T1__" style="width:66px">
 <span>–</span><input type="number" id="fT1" value="__T1__" min="0" max="__T1__" style="width:66px">
 <label>关键词</label><input type="text" id="fKey" placeholder="装备名 / 槽位 / 角度" style="width:150px">
 <button id="fReset">重置</button><button id="fExport">导出当前筛选 CSV</button>
</div>
<div class="pager"><span id="fCount"></span>
 <button id="pPrev">上一页</button><span id="pInfo"></span><button id="pNext">下一页</button></div>
<div class="scroll">
 <table><thead><tr><th>时刻</th><th>帧</th><th>英雄</th><th>阵营</th>
  <th>类型</th><th>详情（原始字段解读）</th><th>来源</th></tr></thead>
 <tbody id="evt"></tbody></table>
</div>
<p class="cap">点击任意行跳转到该秒并在地图上定位。语义未定名的
  <code>CC</code> __N_CC__ 条<b>未进入浏览器</b>（保留在 CSV 供核对），
  避免淹没技能与购买。</p>

<h2>十人事件矩阵 <span class="tag t-file">文件解码</span>
 <span class="tag t-engine">引擎实测</span><span class="tag t-ui">UI 采样</span></h2>
__MATRIX_HTML__
<p class="cap">技能/购买/加点/落点/目标点/锚点 = 文件解码逐条计数；
  死亡（面板）= 结算 UI 采样；检查点覆盖/未覆盖 = 引擎实测差分。
  逐人技能计数来自命令里的 <code>object_id</code>，不是 packed 输入归因。</p>

<h2>死亡：能知道什么、不能知道什么 <span class="tag t-inf">推断</span></h2>
<div class="warn"><b>文件里没有逐条死亡事件。</b>
  <code>0x81 mode6 = 死亡</code> 已被 D1 逐字节推翻（实为
  USEDIRECTIONALSKILL），<code>SCPKG_GAME_OVER_RSP</code> 在 30 个 .abc 样本
  0 命中，存活标记 <code>CC</code> 也不是规律心跳、不能用来切死亡时刻。
  因此本页只给出<b>检查点之间的 deaths 累计差分</b>：能说「谁在哪个时间窗死了几次」，
  <b>不能说「几点几分几秒死亡」</b>。地图上一律不画死亡坐标。</div>
<h3>死亡区间热力（行 = 英雄，列 = 检查点区间，数字 = 该区间 deaths 增量）</h3>
__HEAT_HTML__
<div class="notice"><b>对账</b>：结算面板总死亡 <b>__N_DEATH__</b> 次；
  检查点最后一点（__CP_LAST__，__CP_LAST_S__s）累计 <b>__CP_DEATHS__</b> 次；
  区间差分合计 <b>__DI_SUM__</b> 次（首检查点之前已有死亡，无更早检查点可比）；
  <b>末段 __UNC_DEATHS__ 次死亡落在 __CP_LAST__ 之后，没有检查点覆盖</b>。
  所以「未覆盖」不是解析失败，是采样窗口到此为止。</div>

<h2>技能：槽位与朝向 <span class="tag t-file">文件解码</span></h2>
__SLOTS_HTML__
<h3>方向技能朝角分布（__N_DIR__ 条，15° 分箱）</h3>
<div class="legend">__HIST_HTML__</div>
<p class="cap"><code>degree</code> 为 i32，值域 −17,700…17,920，按
  <code>degree / 100 = 度</code> 解读（±180° 与值域吻合，medium-high）。
  角度是<b>施法朝向</b>，不是技能命中方向；地图上箭头仅示意，不代表弹道或射程。</p>

<h2>字段字典与来源口径</h2>
__DICT_HTML__
<div class="legend">
 <div><b>文件解码 · 可复现</b>88,627 条帧命令 0 未解析；8,311 条带施法者事件；
  295 条显式世界坐标。逐条可对照 .abc 字节偏移。</div>
 <div><b>UI / 官方接口采样</b>10 人 × 693 秒逐秒位置（1 Hz）、23 点团队经济
  （30 s）、10 人结算面板。不是 .abc 内容。</div>
 <div><b>引擎实测</b>10 个检查点 × 10 人的金币 / KDA / 等级，
  来自暂停帧只读内存采样。</div>
 <div><b>推断 / 计算</b>死亡区间（检查点差分）、逐秒位移、团队重心、
  朝角换算。均标注，不进正式统计口径。</div>
</div>
<div class="warn"><b>不提供</b>：逐条死亡时刻、精确击杀归属、逐帧坐标、
  逐帧血量、伤害量、完整经济账本、逐帧命中判定。
  这些不是「没解出来」，是 lockstep 回放只存输入、没把状态写进文件。</div>

<footer>生成脚本 replay_codec/build_review.py · 输入 sample_data/*.csv ·
  玩家昵称、账号 ID 已脱敏，仅显示英雄名 · 峡谷为自绘示意图，非官方素材 ·
  时间轴统一到营地秒号，回放帧按 (frame−31.4)/15.1515 + 3s 映射
  （138 锚点实测，中位残差 3.85 格，非帧级校准）。</footer>
</div>

<script>
const P=__POSITIONS__,EV=__EVENTS__,CO=__COORDS__,DI=__DEATH__,CP=__CP__;
const TG=__TGOLD__,CPH=__CPH__,T1=__T1__;
const GRID=57,OFF=24,SIZE=552;
const sx=g=>OFF+(g+GRID)/(2*GRID)*SIZE, sy=g=>OFF+(GRID-g)/(2*GRID)*SIZE;
const COL={blue:"#3b82f6",red:"#ef4444"};
const KIND={USEDIRECTIONALSKILL:"方向技能",USEOBJECTIVESKILL:"目标技能",
 USEPOSITIONSKILL:"位置技能",BUYEQUIP:"购买装备",LEARNSKILL:"技能加点"};
const KC={USEDIRECTIONALSKILL:"#fb923c",USEOBJECTIVESKILL:"#a78bfa",
 USEPOSITIONSKILL:"#fbbf24",BUYEQUIP:"#38bdf8",LEARNSKILL:"#34d399"};
const fmt=s=>String(Math.floor(s/60)).padStart(2,"0")+":"+String(s%60).padStart(2,"0");
const esc=s=>String(s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"})[c]);
const G=id=>document.getElementById(id);
let t=0,timer=null,page=0,filtered=[],focus=null;
const PAGE=100;
const fade=(dt,win)=>win>1000 ? 0.42 : (dt>win ? null : .92-.55*dt/win);
// 按秒建索引，时间线绘制不必对 694 秒反复全表扫描
const EBY={};EV.forEach(e=>(EBY[e.t]||(EBY[e.t]=[])).push(e));
const at=s=>EBY[s]||[];

function snapshot(t){
 const now=EV.filter(e=>e.t===t);
 const sk=now.filter(e=>e.n.startsWith("USE")).length;
 const bl=now.filter(e=>e.n==="BUYEQUIP"||e.n==="LEARNSKILL").length;
 const dz=DI.filter(z=>z.s<=t&&t<=z.e);
 const dn=dz.reduce((s,z)=>s+z.n,0);
 const cp=[...CP].reverse().find(c=>c.t<=t);
 const tg=[...TG].reverse().find(x=>x.t<=t);
 G("snapTime").textContent=fmt(t);
 G("snapSkill").textContent=sk;
 G("snapBuy").textContent=bl;
 G("snapDeath").textContent=dz.length?"+"+dn:"—";
 G("snapGold").textContent=tg?(tg.d>0?"+":"")+tg.d:"—";
 G("snapCp").textContent=cp?cp.clock:"—";
}

function render(t){
 snapshot(t);
 const win=Number(G("win").value);
 const S={trail:G("ckTrail").checked,arrow:G("ckArrow").checked,
  aim:G("ckAim").checked,target:G("ckTarget").checked,
  anchor:G("ckAnchor").checked,death:G("ckDeath").checked};
 const mode=G("trailMode").value,lm=G("labelMode").value;
 const dz=DI.filter(z=>z.s<=t&&t<=z.e);
 const dmap={};dz.forEach(z=>dmap[z.hero]=(dmap[z.hero]||0)+z.n);
 let tr="",d="",lb="",rows="",arr="",lk="";
 const lay={anchor:"",target:"",aim:""};
 const labs=[];

 // 轨迹：1 Hz 采样点用虚线连，并画出每秒采样点，不伪装成真实走位
 if(S.trail){
  P.forEach(p=>{
   const act=EV.some(e=>e.t===t&&e.hero===p.hero);
   if(mode==="active"&&!act)return;
   if(mode==="focus"&&focus!==p.entity)return;
   const pts=[];
   for(let k=Math.max(0,t-8);k<=t;k++)
    if(p.x[k]!==null&&p.x[k]!==undefined)pts.push([sx(p.x[k]),sy(p.y[k])]);
   if(pts.length<2)return;
   tr+='<polyline points="'+pts.map(q=>q[0].toFixed(1)+","+q[1].toFixed(1)).join(" ")+
    '" fill="none" stroke="'+COL[p.camp]+'" stroke-width="1.5" stroke-opacity=".6" '+
    'stroke-dasharray="3 4" stroke-linejoin="round"/>';
   pts.slice(0,-1).forEach(q=>tr+='<circle cx="'+q[0].toFixed(1)+'" cy="'+
    q[1].toFixed(1)+'" r="1.9" fill="'+COL[p.camp]+'" opacity=".75"/>');
  });
 }

 // 技能：方向箭头（含近 2 秒余辉）、位置技能连线、目标技能标记
 EV.filter(e=>e.t>=t-2&&e.t<=t).forEach(e=>{
  const p=P.find(q=>q.hero===e.hero);
  if(!p||p.x[e.t]===null||p.x[e.t]===undefined)return;
  const X=sx(p.x[e.t]),Y=sy(p.y[e.t]),cur=e.t===t,op=cur?1:.3;
  if(e.n==="USEDIRECTIONALSKILL"&&e.deg!==null&&S.arrow){
   const a=(e.deg-90)*Math.PI/180,L=cur?46:30;
   const ex=X+L*Math.cos(a),ey=Y+L*Math.sin(a);
   arr+='<g opacity="'+op+'"><line x1="'+X.toFixed(1)+'" y1="'+Y.toFixed(1)+
    '" x2="'+ex.toFixed(1)+'" y2="'+ey.toFixed(1)+'" stroke="#fb923c" '+
    'stroke-width="'+(cur?3:2)+'" marker-end="url(#arrowSkill)"/></g>';
   if(cur)arr+='<text x="'+(ex+5).toFixed(1)+'" y="'+(ey-4).toFixed(1)+
    '" font-size="10" font-weight="600" fill="#fdba74">'+e.deg.toFixed(0)+'°</text>';
  }
  if(e.n==="USEPOSITIONSKILL"&&e.tx!==null&&cur&&S.aim){
   const TX=sx(e.tx),TY=sy(e.ty);
   lk+='<line x1="'+X.toFixed(1)+'" y1="'+Y.toFixed(1)+'" x2="'+TX.toFixed(1)+
    '" y2="'+TY.toFixed(1)+'" stroke="#fbbf24" stroke-width="2" '+
    'stroke-dasharray="6 4" marker-end="url(#arrowPos)" opacity=".95"/>'+
    '<circle cx="'+TX.toFixed(1)+'" cy="'+TY.toFixed(1)+'" r="10" fill="none" '+
    'stroke="#fbbf24" stroke-width="1.4" opacity=".75"/>';
  }
  if(e.n==="USEOBJECTIVESKILL"&&cur&&S.target){
   lk+='<circle cx="'+(X+15).toFixed(1)+'" cy="'+(Y-15).toFixed(1)+
    '" r="5" fill="none" stroke="#a78bfa" stroke-width="2.2">'+
    '<title>目标技能 · 对象 ID '+esc(e.ot||"—")+'（另一套 ID，未映射到十人）</title>'+
    '</circle>';
  }
 });

 // 文件内显式世界坐标三层（按时间窗渐隐）
 CO.forEach(c=>{
  if((c.k==="aim"&&!S.aim)||(c.k==="target"&&!S.target)||
     (c.k==="anchor"&&!S.anchor))return;
  const a=fade(Math.abs(c.t-t),win);if(a===null)return;
  const X=sx(c.gx).toFixed(1),Y=sy(c.gy).toFixed(1),op=a.toFixed(2);
  if(c.k==="aim")
   lay.aim+='<path d="M'+X+' '+(Number(Y)-6)+' L'+(Number(X)+6)+' '+Y+
    ' L'+X+' '+(Number(Y)+6)+' L'+(Number(X)-6)+' '+Y+' Z" fill="#fb923c" '+
    'stroke="#fff" stroke-width="'+(c.t===t?1.6:.8)+'" opacity="'+op+'">'+
    '<title>'+esc(c.hero)+' 技能落点 '+fmt(c.t)+'</title></path>';
  else if(c.k==="target")
   lay.target+='<circle cx="'+X+'" cy="'+Y+'" r="3.6" fill="#a78bfa" '+
    'stroke="#fff" stroke-width=".9" opacity="'+op+'"/>';
  else
   lay.anchor+='<rect x="'+(Number(X)-4.5)+'" y="'+(Number(Y)-4.5)+
    '" width="9" height="9" fill="none" stroke="#22d3ee" stroke-width="1.8" '+
    'opacity="'+op+'"/>';
 });

 // 英雄点 + 全名标签（带防重叠错位）
 P.forEach(p=>{
  const x=p.x[t],y=p.y[t];
  if(x===null||x===undefined){
   rows+='<tr class="'+p.camp+'"><td>'+(p.camp==="blue"?"蓝":"红")+'</td>'+
    '<td>'+esc(p.hero)+'</td><td class="dim">—</td><td class="dim">—</td>'+
    '<td class="dim">—</td><td class="dim">—</td><td class="dim">—</td></tr>';
   return;
  }
  const X=sx(x),Y=sy(y);
  const act=EV.filter(e=>e.t===t&&e.hero===p.hero);
  const isFocus=focus===p.entity;
  const dim=(focus&&!isFocus) ? 0.42 : 1;
  let s='<g opacity="'+dim+'">';
  if(act.length)s+='<circle cx="'+X.toFixed(1)+'" cy="'+Y.toFixed(1)+
   '" r="16" fill="none" stroke="#facc15" stroke-width="2.2" opacity=".95"/>';
  if(dmap[p.hero]&&S.death)s+='<circle cx="'+X.toFixed(1)+'" cy="'+Y.toFixed(1)+
   '" r="20" fill="none" stroke="#ef4444" stroke-width="1.7" '+
   'stroke-dasharray="3 3"/>';
  s+='<circle cx="'+X.toFixed(1)+'" cy="'+Y.toFixed(1)+'" r="'+
   (isFocus?12:10.5)+'" fill="'+COL[p.camp]+'" stroke="#fff" stroke-width="2.5" '+
   'filter="url(#dotShadow)"/>'+
   '<text x="'+X.toFixed(1)+'" y="'+(Y+3.6).toFixed(1)+'" text-anchor="middle" '+
   'font-size="10.5" font-weight="700" fill="#fff">'+esc(p.abbr)+'</text>';
  if(dmap[p.hero]&&S.death){
   const bx=X+9,by=Y+9;
   s+='<g><rect x="'+bx.toFixed(1)+'" y="'+by.toFixed(1)+'" width="21" '+
    'height="15" rx="7.5" fill="#991b1b" stroke="#fff" stroke-width="1"/>'+
    '<text x="'+(bx+10.5).toFixed(1)+'" y="'+(by+11).toFixed(1)+'" '+
    'text-anchor="middle" font-size="9.5" font-weight="700" fill="#fff">+'+
    dmap[p.hero]+'</text><title>'+esc(p.hero)+' 在 '+dz.find(z=>z.hero===p.hero).sc+
    '–'+dz.find(z=>z.hero===p.hero).ec+' 区间内 deaths +'+dmap[p.hero]+
    '（差分，不是这一秒阵亡，也不是死亡坐标）</title></g>';
  }
  s+='</g>';
  d+=s;
  const tag=act.length>0||dmap[p.hero]||isFocus;
  if(lm==="all"||(lm==="active"&&tag))
   labs.push({x:X,y:Y,hero:p.hero,camp:p.camp,focus:isFocus});
  let mv="—";
  if(t>0&&p.x[t-1]!==null&&p.x[t-1]!==undefined)
   mv=Math.hypot(x-p.x[t-1],y-p.y[t-1]).toFixed(1);
  const ns=act.filter(e=>e.n.startsWith("USE")).length;
  const ks=Object.keys(CPH[p.hero]||{}).map(Number).filter(s=>s<=t)
   .sort((a,b)=>b-a);
  const c=ks.length?CPH[p.hero][ks[0]]:null;
  rows+='<tr class="'+p.camp+'" data-e="'+p.entity+'"><td>'+
   (p.camp==="blue"?"蓝":"红")+'</td><td>'+esc(p.hero)+'</td><td>'+
   x.toFixed(0)+", "+y.toFixed(0)+'</td><td>'+mv+'</td><td>'+(ns||"—")+
   '</td><td'+(c?'':' class="dim"')+'>'+(c?c.k+"/"+c.d+"/"+c.a:"—")+
   '</td><td'+(c?'':' class="dim"')+'>'+(c?c.lv:"—")+'</td></tr>';
 });
 // 中央团战时左右交替摆放，避免十个标签全叠在一侧；同侧再做垂直避让
 labs.forEach((l,i)=>l.side=l.x>430?"L":(l.x<170?"R":(i%2?"L":"R")));
 ["R","L"].forEach(side=>{
  let last=-100;
  labs.filter(l=>l.side===side).sort((a,b)=>a.y-b.y).forEach(l=>{
   l.ly=Math.max(l.y,last+15.5);last=l.ly;
  });
 });
 labs.forEach(l=>{
  const w=l.hero.length*11+11;
  let bx=l.side==="R"?l.x+13:l.x-13-w;
  bx=Math.max(28,Math.min(576-w-6,bx));
  const by=Math.max(28,Math.min(558,l.ly-7));
  lb+='<g opacity="'+((focus&&!l.focus) ? 0.55 : 1)+'"><rect x="'+bx.toFixed(1)+
   '" y="'+by.toFixed(1)+'" width="'+w+'" height="14.5" rx="7" fill="'+
   COL[l.camp]+'" opacity=".94" stroke="#fff" stroke-opacity=".6" '+
   'stroke-width="1"/><text x="'+(bx+w/2).toFixed(1)+'" y="'+(by+10.4).toFixed(1)+
   '" text-anchor="middle" font-size="10" font-weight="650" fill="#fff">'+
   esc(l.hero)+'</text></g>';
 });

 G("trails").innerHTML=tr;G("links").innerHTML=lk;G("arrows").innerHTML=arr;
 G("dots").innerHTML=d;G("labels").innerHTML=lb;
 Object.keys(lay).forEach(k=>G("l"+k[0].toUpperCase()+k.slice(1)).innerHTML=lay[k]);
 G("roster").innerHTML=rows;
 Array.from(G("roster").querySelectorAll("tr[data-e]")).forEach(r=>
  r.onclick=()=>{focus=focus===r.dataset.e?null:r.dataset.e;render(t);});

 // 侧栏：当前秒前后 ±2 秒的逐条事件卡
 const from=Math.max(0,t-2),to=Math.min(T1,t+2);
 let cards="",total=0;
 for(let s=from;s<=to;s++){
  const es=EV.filter(e=>e.t===s);total+=es.length;
  cards+='<div class="evgroup '+(s===t?"cur":"")+'" data-t="'+s+'">'+
   '<div class="evsec"><span>'+fmt(s)+(s===t?'<span class="now">当前秒</span>':'')+
   '</span><span class="evn">'+es.length+' 条</span></div>';
  cards+=es.length?es.map(e=>'<div class="evcard" style="border-left-color:'+
   KC[e.n]+'"><span class="evhero" style="color:'+COL[e.camp]+'">'+esc(e.hero)+
   '</span><span class="evkind">'+(KIND[e.n]||e.n)+'</span>'+
   '<span class="evdetail">'+esc(e.d)+'</span></div>').join(""):
   '<div class="evempty">— 该秒无逐条技能 / 购买 / 加点事件</div>';
  cards+='</div>';
 }
 const box=G("evcards");box.innerHTML=cards;
 const cg=box.querySelector(".evgroup.cur");
 if(cg)box.scrollTop=Math.max(0,cg.offsetTop-box.offsetTop-54);
 G("evcap").textContent="窗口 "+fmt(from)+"–"+fmt(to)+" 共 "+total+
  " 条；当前秒 "+EV.filter(e=>e.t===t).length+" 条。点击任一秒可跳转。";
 Array.from(G("evcards").querySelectorAll(".evgroup")).forEach(g=>
  g.onclick=()=>{setPlaying(false);t=Number(g.dataset.t);render(t);});

 // 侧栏：当前检查点区间的死亡差分
 if(dz.length){
  const sum=dz.reduce((s,z)=>s+z.n,0);
  let dh='<div class="dhead">'+dz[0].sc+" – "+dz[0].ec+
   '<span>检查点区间 · '+dz.length+' 人</span></div>';
  dz.slice().sort((a,b)=>b.n-a.n).forEach(z=>dh+='<div class="drow">'+
   '<span style="color:'+COL[z.camp]+'">■</span> '+esc(z.hero)+
   ' <b>+'+z.n+'</b></div>');
  dh+='<div class="dfoot">该区间合计 <b>+'+sum+'</b> 次 deaths 增量 · '+
   '<b>这是区间差分，不是这一秒的死亡时刻，也不是死亡坐标</b>。</div>';
  G("dcard").innerHTML=dh;
 }else{
  G("dcard").innerHTML='<div class="dnil">当前秒不在任何「有死亡差分」的'+
   '检查点区间内。<b>这不代表没有死亡</b>——检查点只到 '+G("snapCp").textContent+
   ' / 09:37，之后没有采样覆盖，且区间之间也可能无常驻差分。</div>';
 }

 G("clock").textContent=fmt(t);G("seek").value=t;
 const cur=G("tlcursor");
 if(cur){const xx=Xtl(t).toFixed(1);cur.setAttribute("x1",xx);cur.setAttribute("x2",xx);}
 const band=G("tlband");
 if(band)band.setAttribute("x",Xtl(Math.max(0,t-2)).toFixed(1));
}

const Xtl=v=>58+v/T1*936;

function drawTimeline(){
 const s=G("tl");let o="";
 const bands=[[10,64,"#f8fafc","技能释放（按秒堆叠）"],
  [80,34,"#fafaf9","购买 · 加点"],[120,110,"#fef2f2","死亡区间（10 行）"],
  [236,30,"#f0fdf4","引擎检查点"],[270,38,"#f8fafc","团队经济差（30s）"]];
 bands.forEach(([y,h,c,lab])=>{
  o+='<rect x="0" y="'+y+'" width="1000" height="'+h+'" fill="'+c+'"/>';
  o+='<text x="4" y="'+(y+11)+'" font-size="9" fill="#64748b">'+lab+'</text>';
 });
 // 秒刻度
 [0,120,240,360,480,600].forEach(v=>{if(v>T1)return;
  const x=Xtl(v);
  o+='<line x1="'+x.toFixed(1)+'" y1="6" x2="'+x.toFixed(1)+'" y2="306" '+
   'stroke="#e2e8f0" stroke-width="1"/>'+
   '<text x="'+x.toFixed(1)+'" y="305" font-size="9" fill="#94a3b8" '+
   'text-anchor="middle">'+fmt(v)+'</text>';});
 // 技能堆叠柱
 const kinds=[["USEDIRECTIONALSKILL","#fb923c"],["USEOBJECTIVESKILL","#a78bfa"],
  ["USEPOSITIONSKILL","#fbbf24"]];
 let mx=1;
 for(let i=0;i<=T1;i++){
  const n=at(i).filter(e=>e.n.startsWith("USE")).length;
  if(n>mx)mx=n;
 }
 const step=936/(T1+1);
 for(let i=0;i<=T1;i++){
  const es=at(i);
  let acc=0;
  kinds.forEach(([k,c])=>{
   const v=es.filter(e=>e.n===k).length;if(!v)return;
   const h=46*v/mx,y=72-acc-h;
   o+='<rect x="'+Xtl(i).toFixed(2)+'" y="'+y.toFixed(2)+'" width="'+
    Math.max(step,.8).toFixed(2)+'" height="'+h.toFixed(2)+'" fill="'+c+'"/>';
   acc+=h;
  });
  const b=es.filter(e=>e.n==="BUYEQUIP").length,
        l=es.filter(e=>e.n==="LEARNSKILL").length;
  if(b)o+='<rect x="'+Xtl(i).toFixed(2)+'" y="'+(110-22*Math.min(b,6)/6).toFixed(2)+
   '" width="'+Math.max(step,.8).toFixed(2)+'" height="'+
   (22*Math.min(b,6)/6).toFixed(2)+'" fill="#38bdf8"/>';
  if(l)o+='<circle cx="'+(Xtl(i)+step/2).toFixed(2)+'" cy="90" r="2" fill="#34d399"/>';
 }
 // 死亡区间 10 行：左侧英雄名 + 红条 + 数字
 P.forEach((p,i)=>{
  const y=124+i*10.4;
  o+='<text x="4" y="'+(y+7.6).toFixed(1)+'" font-size="8.5" fill="'+
   COL[p.camp]+'">'+esc(p.hero)+'</text>';
  o+='<line x1="58" y1="'+(y+9).toFixed(1)+'" x2="1000" y2="'+(y+9).toFixed(1)+
   '" stroke="#fee2e2" stroke-width=".7"/>';
 });
 DI.forEach(z=>{
  const i=P.findIndex(q=>q.hero===z.hero);if(i<0)return;
  const x=Xtl(z.s),w=Math.max(3,Xtl(z.e)-Xtl(z.s)),y=124+i*10.4;
  o+='<rect x="'+x.toFixed(1)+'" y="'+y.toFixed(1)+'" width="'+w.toFixed(1)+
   '" height="8.6" rx="2" fill="'+(z.n>1?"#b91c1c":"#ef4444")+'" opacity=".9">'+
   '<title>'+esc(z.hero)+' '+z.sc+'–'+z.ec+' 区间 deaths +'+z.n+
   '（差分，时刻未知）</title></rect>';
  if(w>13)o+='<text x="'+(x+3).toFixed(1)+'" y="'+(y+7).toFixed(1)+
   '" font-size="7.5" fill="#fff" font-weight="700">+'+z.n+'</text>';
 });
 CP.forEach(c=>{
  const x=Xtl(c.t);
  o+='<line x1="'+x.toFixed(1)+'" y1="238" x2="'+x.toFixed(1)+'" y2="262" '+
   'stroke="#16a34a" stroke-width="1.6"/>'+
   '<text x="'+x.toFixed(1)+'" y="261" font-size="8" fill="#166534" '+
   'text-anchor="middle">'+c.clock+'</text>';
 });
 const md=Math.max(...TG.map(x=>Math.abs(x.d)),1);
 o+='<line x1="58" y1="290" x2="1000" y2="290" stroke="#cbd5e1"/>'+
  '<polyline points="'+TG.map(x=>Xtl(x.t).toFixed(1)+","+
   (290-x.d/md*20).toFixed(1)).join(" ")+'" fill="none" stroke="#2563eb" '+
  'stroke-width="1.8"/>';
 o+='<rect id="tlband" x="'+Xtl(0).toFixed(1)+'" y="6" width="'+
  (Xtl(2)-Xtl(0)).toFixed(1)+'" height="300" fill="#0f172a" opacity=".05"/>';
 o+='<line id="tlcursor" x1="58" y1="4" x2="58" y2="306" stroke="#0f172a" '+
  'stroke-width="1.8"/>';
 s.innerHTML=o;
 s.onclick=e=>{
  const r=s.getBoundingClientRect();
  const x=(e.clientX-r.left)/r.width*1000;
  setPlaying(false);
  t=Math.max(0,Math.min(T1,Math.round((x-58)/936*T1)));render(t);
 };
}

function applyFilter(){
 const k=G("fKind").value,h=G("fHero").value,
  a=Number(G("fT0").value),b=Number(G("fT1").value),q=G("fKey").value.trim();
 filtered=EV.filter(e=>{
  if(k&&(k==="USE"?!e.n.startsWith("USE"):e.n!==k))return false;
  if(h&&e.hero!==h)return false;
  if(e.t<a||e.t>b)return false;
  if(q&&(e.d+e.n+e.hero).indexOf(q)<0)return false;
  return true;
 });
 page=0;G("fCount").textContent="筛选结果 "+filtered.length+" 条 / 共 "+EV.length+" 条";
 renderPage();
}
function renderPage(){
 const st=page*PAGE,rows=filtered.slice(st,st+PAGE);
 G("evt").innerHTML=rows.map(e=>
  '<tr data-t="'+e.t+'"><td>'+fmt(e.t)+'</td><td>'+e.frame+'</td>'+
  '<td>'+esc(e.hero)+'</td><td>'+(e.camp==="blue"?"蓝":"红")+'</td>'+
  '<td>'+(KIND[e.n]||e.n)+'</td><td>'+esc(e.d)+'</td>'+
  '<td class="dim">文件解码</td></tr>').join("")||
  '<tr><td colspan="7" class="dim">无匹配事件</td></tr>';
 G("pInfo").textContent="第 "+(page+1)+" / "+Math.max(1,Math.ceil(filtered.length/PAGE))+" 页";
 Array.from(G("evt").querySelectorAll("tr[data-t]")).forEach(r=>
  r.onclick=()=>{setPlaying(false);t=Number(r.dataset.t);render(t);
   window.scrollTo({top:0,behavior:"smooth"});});
}
function exportCSV(){
 const head=["t_sec","frame","hero","camp","type","detail"];
 const lines=[head.join(",")].concat(filtered.map(e=>
  [e.t,e.frame,e.hero,e.camp,e.n,'"'+e.d.replace(/"/g,'""')+'"'].join(",")));
 const blob=new Blob(["\ufeff"+lines.join("\n")],{type:"text/csv;charset=utf-8"});
 const a=document.createElement("a");a.href=URL.createObjectURL(blob);
 a.download="replay_events_filtered.csv";a.click();URL.revokeObjectURL(a.href);
}
function setPlaying(on){
 if(on){if(timer)return;const sp=Number(G("speed").value);
  timer=setInterval(()=>{t=t>=T1?0:t+1;render(t);},Math.max(40,Math.round(1000/sp)));
  G("play").textContent="⏸ 暂停";}
 else{clearInterval(timer);timer=null;G("play").textContent="▶ 播放";}
}
function jump(target){
 setPlaying(false);t=Math.max(0,Math.min(T1,target));render(t);
}
function nextSkill(dir){
 const a=EV.filter(e=>e.n.startsWith("USE")&&(dir>0?e.t>t:e.t<t));
 if(!a.length)return;
 jump(dir>0?a[0].t:a[a.length-1].t);
}
G("play").onclick=()=>setPlaying(!timer);
G("seek").oninput=e=>jump(Number(e.target.value));
G("win").onchange=()=>render(t);
["ckTrail","ckArrow","ckAim","ckTarget","ckAnchor","ckDeath",
 "labelMode","trailMode"].forEach(id=>G(id).onchange=()=>render(t));
G("btnPrevSkill").onclick=()=>nextSkill(-1);
G("btnNextSkill").onclick=()=>nextSkill(1);
G("btnNextDeath").onclick=()=>{
 const a=DI.filter(z=>z.s>t).sort((x,y)=>x.s-y.s);if(a.length)jump(a[0].s);};
G("btnReset").onclick=()=>{focus=null;jump(0);};
G("theme").onclick=()=>{
 const light=document.body.classList.toggle("light");
 G("theme").textContent=light?"切换深色底图":"切换浅色底图";};
["fKind","fHero","fT0","fT1"].forEach(id=>G(id).onchange=applyFilter);
G("fKey").oninput=applyFilter;
G("fReset").onclick=()=>{G("fKind").value="";G("fHero").value="";
 G("fT0").value=0;G("fT1").value=T1;G("fKey").value="";applyFilter();};
G("fExport").onclick=exportCSV;
G("pPrev").onclick=()=>{if(page>0){page--;renderPage();}};
G("pNext").onclick=()=>{if((page+1)*PAGE<filtered.length){page++;renderPage();}};
document.onkeydown=e=>{
 if(e.code==="Space"){e.preventDefault();setPlaying(!timer);}
 if(e.code==="ArrowLeft"){setPlaying(false);jump(e.shiftKey?t-10:t-1);}
 if(e.code==="ArrowRight"){setPlaying(false);jump(e.shiftKey?t+10:t+1);}
 if(e.code==="KeyN"){nextSkill(1);}
};
drawTimeline();applyFilter();render(0);
</script>
</body>
</html>
"""


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description="生成单局解析数据核对台 HTML")
    ap.add_argument("--data-dir", default=os.path.join(here, "sample_data"))
    ap.add_argument("--out", default=os.path.join(
        here, "output", "20261102_161129_review.html"))
    args = ap.parse_args()
    A = load_all(args.data_dir)

    # 十人矩阵
    mh = ["英雄", "阵营", "方向技能", "目标技能", "位置技能", "购买", "加点",
          "技能合计", "面板死亡", "检查点覆盖", "末段未覆盖", "落点", "目标点",
          "锚点", "结算 KDA", "结算金币", "评分"]
    mr = []
    for m in A["mat"]:
        tot = m["dir"] + m["obj"] + m["pos"]
        mr.append([m["hero"], "蓝" if m["camp"] == "blue" else "红",
                   m["dir"], m["obj"], m["pos"], m["buy"], m["learn"], tot,
                   m["panel_d"], m["last"], m["unc"], m["aim"], m["target"],
                   m["anchor"], "%d/%d/%d" % (m["k"], m["d"], m["a"]),
                   format(m["gold"], ","), m["score"]])
    matrix_html = html_table(mh, mr, "blue")

    # 死亡热力
    hh = ["英雄"] + ["%s–%s" % (c["clock"], nc["clock"])
                     for c, nc in zip(A["cp"], A["cp"][1:])] + ["合计"]
    hr = []
    for z in A["heat"]:
        cells = []
        for v in z["row"]:
            cls = "v0" if v == 0 else ("v1" if v == 1 else "l2")
            cells.append('<td class="%s">%s</td>' % (cls, v if v else "·"))
        hr.append(["<td>%s</td>" % z["hero"], *cells,
                   "<td><b>%d</b></td>" % sum(z["row"])])
    heat_html = '<table class="heat"><thead><tr>' + "".join(
        "<th>%s</th>" % x for x in hh) + "</tr></thead><tbody>"
    for z, r in zip(A["heat"], hr):
        heat_html += '<tr class="%s">' % z["camp"] + "".join(r) + "</tr>"
    heat_html += "</tbody></table>"

    # 技能槽位矩阵
    sh = ["英雄"] + ["槽位 %d" % s for s in A["slot_vals"]] + ["合计"]
    sr = []
    for z in A["slots"]:
        sr.append([z["hero"]] + [v if v else "·" for v in z["row"]]
                  + [sum(z["row"])])
    slots_html = html_table(sh, sr)

    hist_max = max(A["hist"]) or 1
    hist_html = "".join(
        '<div><b>%d°–%d°</b> %d 次 · %s</div>' %
        (i * 15 - 180, i * 15 - 165, v,
         "█" * max(1, round(v / hist_max * 12)))
        for i, v in enumerate(A["hist"]) if v)

    dict_rows = [
        ["t_sec", "营地秒号", "回放帧按 (frame−31.4)/15.1515 + 3s 映射；138 锚点实测，非帧级校准"],
        ["frame", "回放帧号", "直接来自帧命令流"],
        ["name", "命令类型", "USEDIRECTIONALSKILL / USEOBJECTIVESKILL / USEPOSITIONSKILL / BUYEQUIP / LEARNSKILL / CC"],
        ["entity / hero / camp", "施法者", "命令 object_id，映射到 10 个已知 entity；不来自 packed 输入归因"],
        ["slot", "技能槽位", "1/2/3 为主，另有 4/5/6/7/9/15（普攻/召唤师技能等，未逐一定名）"],
        ["degree", "施法朝向", "i32，值域 ±18000；按 /100 = 度解读；不是命中方向"],
        ["target_x / target_y", "地面落点", "i32 世界坐标，/1000 = 营地网格；不是施法者位置"],
        ["object_target", "目标技能对象", "另一套对象 ID（8…65 等），与十人 entity 不重合；未映射，故不画目标连线"],
        ["equip_id / equip_name", "购买装备", "58 个装备名全部有映射，来自 20261102_buy_events.csv"],
        ["level / skill_seq", "加点等级 / 技能序号", "逐条加点命令与技能释放序号"],
        ["detail", "可读解读", "仅对上述原始字段做格式化，不添加推断"],
        ["CC", "状态标记", "6,224 条，语义未定名；不作死亡判据，未进入事件浏览器"],
    ]
    dict_html = html_table(["字段", "含义", "口径 / 边界"], dict_rows)

    hero_opt = "".join('<option value="%s">%s</option>' %
                       (p["hero"], p["hero"]) for p in A["players"])
    repl = {
        "__POSITIONS__": jsafe(A["players"]),
        "__EVENTS__": jsafe(A["ev"]),
        "__COORDS__": jsafe(A["co"]),
        "__DEATH__": jsafe(A["di"]),
        "__CP__": jsafe(A["cp"]),
        "__TGOLD__": jsafe(A["tg"]),
        "__CPH__": jsafe(A["cph"]),
        "__T1__": str(A["t1"]),
        "__N_CMD__": format(A["n_cmd"], ","),
        "__N_EV__": format(A["n_ev_all"], ","),
        "__N_SKILL__": format(A["n_skill"], ","),
        "__N_BUY__": str(A["n_buy"]),
        "__N_LEARN__": str(A["n_learn"]),
        "__N_COORD__": str(A["n_coord"]),
        "__N_DEATH__": str(A["panel_deaths"]),
        "__N_CP__": str(len(A["cp"])),
        "__N_CC__": format(A["n_cc"], ","),
        "__N_DIR__": str(sum(A["hist"])),
        "__CP_DEATHS__": str(A["cp_deaths"]),
        "__UNC_DEATHS__": str(A["unc_deaths"]),
        "__DI_SUM__": str(A["di_sum"]),
        "__N_INTERVALS__": str(A["n_intervals"]),
        "__CP_LAST__": A["cp_last_clock"],
        "__CP_LAST_S__": str(A["cp_last_sec"]),
        "__SAMPLE__": SAMPLE,
        "__TERRAIN__": terrain_svg(),
        "__HERO_OPT__": hero_opt,
        "__MATRIX_HTML__": matrix_html,
        "__HEAT_HTML__": heat_html,
        "__SLOTS_HTML__": slots_html,
        "__HIST_HTML__": hist_html,
        "__DICT_HTML__": dict_html,
    }
    doc = TEMPLATE
    for k, v in repl.items():
        doc = doc.replace(k, v)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)
    print("OK events=%d(all %d, cc %d) skills=%d coords=%d death=%d "
          "size=%d bytes" %
          (len(A["ev"]), A["n_ev_all"], A["n_cc"], A["n_skill"],
           A["n_coord"], len(A["di"]), len(doc.encode("utf-8"))))
    print("OUT " + os.path.abspath(args.out))


if __name__ == "__main__":
    main()
