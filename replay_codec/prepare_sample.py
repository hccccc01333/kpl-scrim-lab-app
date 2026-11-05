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
import os

SAMPLE = "20261102_161129"

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

    print("sample_data written: frames=%d panel=%d actions=%d state=%d "
          "pos=%d coords=%d" %
          (len(frames), len(panel), len(acts), len(state), len(pos),
           len(coords)))
    print("OUT " + args.out_dir)


if __name__ == "__main__":
    main()
