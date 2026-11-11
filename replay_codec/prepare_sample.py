# -*- coding: utf-8 -*-
"""
replay_codec / prepare_sample.py

从主项目的已解码数据里，导出一份**可随独立仓库一起分发**的脱敏样本数据。

脱敏规则（红线：账号 tag / 头像 / OpenID 不外传）：
  * 删除所有玩家昵称列（player / name）；
  * 把含账号标识的完整 .abc 文件名替换为样本短名；
  * 只保留公开可解释的数值列，不导出头像、OpenID、账号 tag。

产物写入 replay_codec/sample_data/，随后 `python build_report.py` 不传任何
参数即可在任意机器上复现同一份报告。

用法：
  python prepare_sample.py --data-dir <datasets> --state <state_series.csv>
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict

# 时间基准的常量只有一处：主项目的 replay_time.py。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import replay_time  # noqa: E402

SAMPLE = "20261102_161129"

# 回放帧 → 营地秒号。这里沿用引擎实测时钟 replay_time.FPS_ENGINE（15.1515，
# F0 = 31.4）；+3s 是「对齐营地逐秒位置数组下标」的实测偏移（138 条位置锚点，
# 见 build_map.py 的 calibrate），属于位置对齐，不是时间基准的一部分。
# 产品侧仍用 docs 5.129 的 15 fps，两者差异与未验证环节见 replay_time.py。
ALIGN_DT = 3

EVENT_FIELDS = ["frame", "t_sec", "name", "entity", "hero", "camp",
                "slot", "degree", "target_x", "target_y", "object_target",
                "equip_id", "equip_name", "buy_price", "level",
                "skill_seq", "auto_flag", "detail"]

DEATH_FIELDS = ["hero", "camp", "start_sec", "end_sec", "start_clock",
                "end_clock", "deaths_delta", "source"]

LEDGER_FIELDS = ["hero", "camp", "panel_deaths", "checkpoint_last_deaths",
                 "uncovered_deaths", "covered_intervals", "note"]

PANEL_KEEP = ["team", "entity", "hero_id", "hero", "kills", "deaths",
              "assists", "gold", "score"]
ACTIONS_KEEP = ["entity", "hero_id", "unit", "score", "buy_events_raw",
                "unique_buy_items", "buy_equip_ids", "learn_events",
                "learn_slots", "learn_slots"]
STATE_DROP = {"player", "name"}

# 回放显式坐标：只保留定位所需字段，player / raw_context 含昵称与内部路径
COORD_KEEP = ["frame", "time_s", "entity_id", "hero", "camp", "x", "z",
              "source", "position_role", "confidence"]


def read_csv(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    ap = argparse.ArgumentParser(description="导出脱敏样本数据")
    ap.add_argument("--data-dir", default=os.path.join(
        root, "data", "replays", "_analysis", "datasets"))
    ap.add_argument("--state", default=os.path.join(
        root, "data", "replays", "_analysis", "live_20261104",
        "state_series_161129_10pt.csv"))
    ap.add_argument("--positions", default=os.path.join(
        root, "data", "replays", "_analysis", "datasets",
        "20261102_official_positions.csv"))
    ap.add_argument("--coords", default=os.path.join(
        root, "data", "replays", "_analysis", "live_20261104",
        "position_samples", "position_samples.csv"))
    ap.add_argument("--frame-events", default=os.path.join(
        root, "data", "replays", "_analysis", "datasets",
        "frame_events_20261102_161129.jsonl"))
    ap.add_argument("--buy-events", default=os.path.join(
        root, "data", "replays", "_analysis", "datasets",
        "20261102_buy_events.csv"))
    ap.add_argument("--team-gold", default=os.path.join(
        root, "data", "replays", "_analysis", "datasets",
        "20261102_official_team_gold.csv"))
    ap.add_argument("--out-dir", default=os.path.join(here, "sample_data"))
    args = ap.parse_args()
    os.makedirs(args.out_dir, exist_ok=True)

    # 帧命令：只留目标局，本身不含账号信息
    frames = [r for r in read_csv(os.path.join(args.data_dir,
              "20261102_frame_commands.csv")) if r.get("sample") == SAMPLE]
    ff = list(frames[0].keys())
    write_csv(os.path.join(args.out_dir, "20261102_frame_commands.csv"),
              frames, ff)

    # 结算面板：换成样本短名，去掉昵称
    panel = [r for r in read_csv(os.path.join(args.data_dir,
             "20261102_panel_truth.csv")) if SAMPLE in r.get("file", "")]
    for r in panel:
        r["sample"] = SAMPLE
    pf = ["sample"] + [c for c in PANEL_KEEP if c in panel[0]]
    write_csv(os.path.join(args.out_dir, "20261102_panel_truth.csv"), panel, pf)

    # 玩家动作：换成样本短名，去掉昵称和逐人操作量列（归因不可靠）
    acts = [r for r in read_csv(os.path.join(args.data_dir,
            "20261102_player_actions.csv")) if SAMPLE in r.get("file", "")]
    drop = {"file", "player", "name", "move_events", "attack_events",
            "attackwithobj_events", "move_events_file_total",
            "attack_events_file_total", "attackwithobj_events_file_total",
            "per_player_attribution", "unique_equip_price_sum_unverified"}
    for r in acts:
        r["sample"] = SAMPLE
    af = ["sample"] + [c for c in acts[0] if c not in drop and c != "sample"]
    write_csv(os.path.join(args.out_dir, "20261102_player_actions.csv"),
              acts, af)

    # 引擎检查点：去掉昵称，其余数值列全保留
    state = read_csv(args.state)
    sf = [c for c in state[0] if c not in STATE_DROP]
    write_csv(os.path.join(args.out_dir, "state_series_161129_10pt.csv"),
              state, sf)

    # 官方逐秒位置：去掉昵称，只保留定位所需的数值列
    pos = read_csv(args.positions)
    posf = [c for c in pos[0] if c not in STATE_DROP]
    write_csv(os.path.join(args.out_dir, "20261102_official_positions.csv"),
              pos, posf)

    # 回放显式世界坐标：三类通道（位置锚点 / 0x82 技能落点 / 0x2c 目标点）
    coords = []
    for r in read_csv(args.coords):
        if (float(r["x"]), float(r["z"])) == (0.0, 0.0):
            continue  # 目标取消帧与 null 位置，不是坐标
        coords.append({k: r[k] for k in COORD_KEEP})
    write_csv(os.path.join(args.out_dir, "20261102_replay_coords.csv"),
              coords, COORD_KEEP)

    # entity → 英雄/阵营（来自官方逐秒位置表，已脱敏）
    meta = {}
    for r in pos:
        meta[r["entity"]] = (r["hero"],
                             "blue" if str(r["camp"]) == "1" else "red")

    # 装备名/价格：按 (frame, entity, equip_id) 关联逐条购买事件
    equip = {}
    for r in read_csv(args.buy_events):
        if SAMPLE not in r.get("file", ""):
            continue
        equip[(r["frame"], r["entity"], r["equip_id"])] = (
            r["equip_name"], r["buy_price"])

    # 逐条帧命令：只导出带施法者 object_id 的事件（其余为无归属的
    # 移动/攻击 packed 输入，不做逐人归因）
    cmd_rows = []
    with open(args.frame_events, "r", encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            oid = x.get("object_id")
            if oid is None:
                continue
            e = str(oid)
            if e not in meta:
                continue
            hero, camp = meta[e]
            fd = x.get("fields") or {}
            t = int(round(replay_time.engine_seconds(x["frame"]) + ALIGN_DT))
            if t < 0 or t > 692:
                continue
            name = x["name"]
            row = {k: "" for k in EVENT_FIELDS}
            row.update({"frame": x["frame"], "t_sec": t, "name": name,
                        "entity": e, "hero": hero, "camp": camp})
            if name == "USEDIRECTIONALSKILL":
                deg = fd.get("degree", "")
                row.update({"slot": fd.get("slot", ""), "degree": deg,
                            "skill_seq": fd.get("skill_seq", ""),
                            "auto_flag": fd.get("drag_flag", "")})
                row["detail"] = ("槽位%s · 朝向%s° · 第%s次" %
                                 (fd.get("slot", "?"),
                                  ("%.1f" % (deg / 100.0)) if deg != "" else "?",
                                  fd.get("skill_seq", "?")))
            elif name == "USEOBJECTIVESKILL":
                row.update({"slot": fd.get("slot", ""),
                            "object_target": fd.get("object_id", ""),
                            "skill_seq": fd.get("skill_seq", "")})
                row["detail"] = ("槽位%s · 目标对象%s" %
                                 (fd.get("slot", "?"), fd.get("object_id", "?")))
            elif name == "USEPOSITIONSKILL":
                tx, ty = fd.get("target_x", ""), fd.get("target_y", "")
                row.update({"slot": fd.get("slot", ""), "target_x": tx,
                            "target_y": ty, "skill_seq": fd.get("skill_seq", "")})
                row["detail"] = ("槽位%s · 落点(%s, %s) 格" %
                                 (fd.get("slot", "?"),
                                  ("%.1f" % (tx / 1000.0)) if tx != "" else "?",
                                  ("%.1f" % (ty / 1000.0)) if ty != "" else "?"))
            elif name == "BUYEQUIP":
                eid = str(fd.get("equip_id", ""))
                ename, price = equip.get((str(x["frame"]), e, eid), ("", ""))
                row.update({"equip_id": eid, "equip_name": ename,
                            "buy_price": price,
                            "auto_flag": fd.get("auto_buy", "")})
                row["detail"] = ("%s · %s金" % (ename or ("装备" + eid),
                                               price or "?"))
            elif name == "LEARNSKILL":
                row.update({"slot": fd.get("slot", ""),
                            "level": fd.get("level", ""),
                            "auto_flag": fd.get("auto_learn", "")})
                row["detail"] = ("槽位%s · 等级%s" %
                                 (fd.get("slot", "?"), fd.get("level", "?")))
            elif name == "CC":
                row["detail"] = "状态标记（语义未定名，不作死亡判据）"
            cmd_rows.append(row)
    cmd_rows.sort(key=lambda r: (int(r["frame"]), r["entity"]))
    write_csv(os.path.join(args.out_dir, "20261102_command_events.csv"),
              cmd_rows, EVENT_FIELDS)

    # 死亡：文件内无逐条死亡事件。只导出「引擎实测检查点的 deaths 累计差分」
    # 得到的区间增量，并单列一张与结算面板的对账表。
    per = defaultdict(dict)
    for r in state:
        per[r["hero"]][float(r["second"])] = {
            "d": int(float(r["deaths"])), "clock": r["clock"],
            "camp": r["camp"],
        }
    clocks = sorted({(float(r["second"]), r["clock"]) for r in state})
    panel_deaths = {r["hero"]: int(r["deaths"]) for r in panel}
    death_rows, ledger_rows = [], []
    for hero, d in sorted(per.items()):
        camp = "blue" if str(next(iter(d.values()))["camp"]) == "blue" else "red"
        n_cov = 0
        for (s0, c0), (s1, c1) in zip(clocks, clocks[1:]):
            if s0 not in d or s1 not in d:
                continue
            delta = d[s1]["d"] - d[s0]["d"]
            if delta > 0:
                n_cov += 1
                death_rows.append({
                    "hero": hero, "camp": camp,
                    "start_sec": int(s0), "end_sec": int(s1),
                    "start_clock": c0, "end_clock": c1,
                    "deaths_delta": delta,
                    "source": "engine-checkpoint-diff",
                })
        last = d[clocks[-1][0]]["d"] if clocks[-1][0] in d else 0
        tot = panel_deaths.get(hero, 0)
        ledger_rows.append({
            "hero": hero, "camp": camp, "panel_deaths": tot,
            "checkpoint_last_deaths": last,
            "uncovered_deaths": tot - last,
            "covered_intervals": n_cov,
            "note": ("检查点止于 %s（%ds），其后死亡未覆盖" %
                     (clocks[-1][1], int(clocks[-1][0]))),
        })
    write_csv(os.path.join(args.out_dir, "20261102_death_intervals.csv"),
              death_rows, DEATH_FIELDS)
    write_csv(os.path.join(args.out_dir, "20261102_death_ledger.csv"),
              ledger_rows, LEDGER_FIELDS)

    # 官方 30 秒团队经济采样（UI/官方接口，非 .abc）
    tg = [{"t_sec": r["t_approx_sec"], "blue": r["blue"],
           "red": r["red"], "diff": r["diff"]}
          for r in read_csv(args.team_gold)]
    write_csv(os.path.join(args.out_dir, "20261102_team_gold.csv"),
              tg, ["t_sec", "blue", "red", "diff"])

    print("sample_data written: frames=%d panel=%d actions=%d state=%d "
          "pos=%d coords=%d cmds=%d deaths=%d ledger=%d teamgold=%d" %
          (len(frames), len(panel), len(acts), len(state), len(pos),
           len(coords), len(cmd_rows), len(death_rows), len(ledger_rows),
           len(tg)))
    print("OUT " + args.out_dir)


if __name__ == "__main__":
    main()
