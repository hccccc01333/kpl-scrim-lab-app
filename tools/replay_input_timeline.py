"""Build a per-hero input timeline from a build-5247758 .abc replay.

Joins the decoded frame-command stream (PLAYER_MOVE / PLAYER_ATTACK /
PLAYER_ATTACKWITHOBJ / CSSYNC / BUYEQUIP / LEARNSKILL / CC) with the .abc
roster so every event carries the hero name. Movements are signed input
directions in degrees, not world positions: the client never records hero
coordinates here, so no trajectory or distance is derived. Nothing is
written to the database; this is a read-only analysis export.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import replay_time  # noqa: E402
from replay_parser import (  # noqa: E402
    PLAYER_EVENT_BODY_LENGTHS,
    inspect_replay,
    digest,
)
from tools.replay_frame_commands import (  # noqa: E402
    FRAME_RATE,
    battle_time,
    hero_inputs,
)
from tools.replay_opening_packet import opening_packet  # noqa: E402
from tools.replay_record_stream import _iter_1051  # noqa: E402
from tools.replay_frame_commands import events as events_source  # noqa: E402

PRICE_TABLES = (
    ROOT / "resources" / "equip_prices.csv",
    ROOT / "data" / "replays" / "_analysis" / "datasets" / "agent_equip_prices.csv",
)


def load_prices():
    """battle_item buy prices (item_id -> price); empty dict when unavailable."""
    for path in PRICE_TABLES:
        if not path.exists():
            continue
        prices = {}
        with path.open(encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                section = row.get("section")
                if section is not None and section != "battle_item":
                    continue
                try:
                    prices[int(row["item_id"])] = int(row["buy_price"])
                except (KeyError, TypeError, ValueError):
                    continue
        if prices:
            return prices
    return {}


def annotate_buys(buys, prices):
    """Extend buy rows with the item's battle-table price: [.., price].

    Prices are reference costs only: the purchase-flag semantics are
    unresolved (既有校准), so no spent-gold totals are derived here.
    """
    return [row + [prices.get(row[1])] for row in buys]


def integrate_path(moves, cap=4000):
    """Direction-integrated shape estimate from PLAYER_MOVE rows.

    One unit step per move entry along the calibrated world vector
    (cos dir°, sin dir°). This is a SHAPE of steering history only: move
    speed is unknown, dead/immobilized time is indistinguishable from
    movement, so the accumulated position drifts — against the sparse 0x82
    kind-2 ground-truth anchors the residual reaches 18k-65k units on a
    ±50k map (既有校准). Never present it as a position or trajectory.
    """
    x = y = 0.0
    points = [[0, 0.0, 0.0]]
    for frame, dir_deg, _mag, _sign, _seq in moves:
        x += math.cos(math.radians(dir_deg))
        y += math.sin(math.radians(dir_deg))
        points.append([frame, round(x, 2), round(y, 2)])
    if len(points) > cap:
        step = (len(points) + cap - 1) // cap
        points = points[::step]
    return points


def extract_wrapper_tlvs(data):
    """Walk the tail stream's 0x01-wrapped per-entity TLVs (既有校准).

    Returns {entityId: {"angle": [[frame, deg]], "tlv": [[frame, len, hex]]}}.
    `angle` comes from the 3-byte 0x2d sample (u16BE degrees 0-359, emitted on
    change for a subset of heroes including the recorder; empirically
    ≈ (dir_deg + 180) mod 360). Everything else stays raw.
    """
    frames = inspect_replay(data).get("frames")
    out = {}
    if not frames or frames.get("status") != "frame-stream":
        return out
    for frame, _offset, payload in _iter_payload_frames(data, frames):
        if not payload:
            continue
        index, size = 1, len(payload)
        while index < size:
            tag = payload[index]
            if tag == 0x12:
                index += 3
                continue
            if tag == 0x13:
                index += 2
                continue
            if tag == 0x14:
                index += 4
                continue
            if tag == 0x01:
                if index + 5 > size:
                    break
                entity = int.from_bytes(payload[index + 1:index + 3], "big")
                length = payload[index + 4]
                if index + 5 + length > size:
                    break
                body = payload[index + 5:index + 5 + length]
                row = out.setdefault(entity, {"angle": [], "tlv": []})
                if length == 3 and body[0] == 0x2D:
                    row["angle"].append([frame, (body[1] << 8) | body[2]])
                else:
                    row["tlv"].append([frame, length, body.hex()])
                index += 5 + length
                continue
            if tag == 0x02:
                if index + 4 > size:
                    break
                subtype = payload[index + 3]
                length = PLAYER_EVENT_BODY_LENGTHS.get(subtype)
                if length is None or index + 4 + length > size:
                    break
                index += 4 + length
                continue
            break
    return out


def _iter_payload_frames(data, frames):
    position, index = frames["start"], 0
    while position < frames["end"]:
        length = data[position + 2]
        yield index + 1, position, data[position + 3:position + 3 + length]
        position += 10 + length
        index += 1

SKILL_LABELS = {128: "objective", 129: "directional", 130: "position"}


def build_unit_map(blocks):
    """Map hero units (8-12 / 16-20) to roster blocks by camp order."""
    mapping = {}
    slots = {}
    for block in blocks:
        camp = block.get("camp")
        if camp not in (1, 2):
            continue
        slot = slots.get(camp, 0)
        slots[camp] = slot + 1
        unit = (8 if camp == 1 else 16) + slot
        mapping[unit] = {
            "camp": camp, "slot": slot,
            "entityId": block.get("entityId"),
            "hero": block.get("heroName") or block.get("heroId"),
            "self": bool(block.get("self")),
        }
    return mapping


def single_game_timeline(abc: bytes) -> dict:
    """Entry-level command timeline for an ID1051 single-game replay.

    Old-build single-game streams carry per-entry event messages with the
    POV hero's skill level-ups (02/87), buy echo (02/85), facing angle
    samples (02/83) and paired kill notices (02/84) — 既有校准-5.136.
    Actors are small ids whose mapping to roster blocks is unresolved, so
    events stay actor-tagged instead of hero-named.
    """
    header = opening_packet(abc)
    skill_levelups, buys, facing, kill_notices, frame_commands = [], [], [], [], []
    initial_states = {}
    prices = load_prices()
    last_seq = 0
    for rec in _iter_1051(abc, header):
        d = rec["decoded"]
        frame = rec["sequence"]
        last_seq = frame
        if d["kind"] == "cc" and "states" in d and frame <= 10:
            initial_states.setdefault(str(frame), {}).update(d["states"])
        if d["kind"] == "event":
            name = d.get("name")
            if name == "skill_levelup":
                skill_levelups.append([frame, d["actor"], d["skill"], d["level_index"]])
            elif name == "facing_angle":
                facing.append([frame, d["angle_deg"], d["index"]])
            elif name == "kill_notice":
                kill_notices.append([frame, int(d["data"][0:2], 16)])
            elif name == "buy_equip":
                price = prices.get(d["equip_id"])
                buys.append([frame, d["equip_id"], d["rest"], price])
            elif name == "frame_commands":
                frame_commands.append([frame, d["actor"], d["cmd_type"],
                                       d["value"], d["cmd_seq"]])
    return {"route": 1051,
            "builds": header["builds"],
            "timeBase": {"framesPerSecond": FRAME_RATE,
                         "battleStartFrame": list(replay_time.BATTLE_START_FRAME_APPROX),
                         "lastEntryFrame": last_seq,
                         "note": "t ≈ (frame − battleStart)/15；校准依据 既有校准（±1s）。"
                                 "帧率常量见 replay_time.py，引擎实测的 15.1515 尚未并入。"},
            "skillLevelups": skill_levelups,
            "buys": buys,
            "facingAngles": facing,
            "killNotices": kill_notices,
            "frameCommands": frame_commands,
            "initialStates": initial_states,
            "initialStatesNote": "帧 ≤10 的 CC 键值（仅己方英雄）：8c=2 + 85=1 = 打野签名（与狩猎宽刃 1511 首购对拍，两局 2/2 验证，候选惩击召唤师标记）；14/2b/73 逐英雄含义未解（既有校准）",
            "schema": {"skillLevelups": "[frame, actor, skill, levelIndex]",
                       "buys": "[frame, equip_id, rest_hex, price]（rest 内含 POV object 字节，位置随构建变化）",
                       "facingAngles": "[frame, angle_deg, index]",
                       "killNotices": "[frame, camp?]"},
            "limitations": [
                "actor 为小 id，到十人块英雄的映射未解；事件按 actor 留存。",
                "各子类型语义见 既有校准-5.136。",
                "对局秒为 15fps 换算近似（±1s）。",
            ]}


def timeline(abc: bytes) -> dict:
    info = inspect_replay(abc)
    blocks = info.get("blocks") or []
    if not blocks:
        raise ValueError("该 .abc 未解析出十人块，无法建立 unit->英雄 映射")
    inputs = hero_inputs(abc)
    if inputs["status"] == "unsupported-route":
        report = single_game_timeline(abc)
        report["abc"] = {"sha256": digest(abc), "size": len(abc)}
        report["resourceVersion"] = info["header"]["versions"][1]
        return report
    if inputs["status"] == "no-record-stream":
        raise ValueError(f"该 .abc 无法解码输入时间轴：{inputs['error']}")
    prices = load_prices()
    roster = build_unit_map(blocks)
    entity_unit = {row["entityId"]: unit for unit, row in roster.items() if row["entityId"]}
    heroes = {unit: {**row, "unit": unit,
                     "moves": [], "attacks": [], "buys": [],
                     "learnSkill": [], "skills": [], "cc": [], "positions": []}
              for unit, row in roster.items()}
    unknown_units = []
    for unit, item in inputs["units"].items():
        hero = heroes.get(int(unit))
        if hero is None:
            unknown_units.append(int(unit))
            continue
        hero["moves"] = item["moves"]
        hero["attacks"] = item["attacks"]
    for entity, item in inputs["entities"].items():
        hero = heroes.get(entity_unit.get(int(entity)))
        if hero is None:
            continue
        hero["buys"] = annotate_buys(item["buys"], prices)
        hero["learnSkill"] = item["learnSkill"]
        hero["skills"] = [[row[0], SKILL_LABELS.get(row[1], row[1]), row[2]]
                          for row in item["skills"]]
        hero["cc"] = item["cc"]
    # 0x82 kind-2 tail-stream samples are the hero's own world coordinates
    # (既有校准): attach them as sparse position anchors when available.
    player_events = info.get("playerEvents") or {}
    for ev in (player_events.get("positions") or {}).get("events", []):
        if ev.get("kind") != 2:
            continue
        hero = heroes.get(entity_unit.get(ev["entityId"]))
        if hero is not None:
            hero["positions"].append([ev["frame"], ev["x"], ev["y"]])
    # 0x01-wrapped TLVs: 0x2d angle samples + raw rows for future decoding.
    for entity, row in extract_wrapper_tlvs(abc).items():
        hero = heroes.get(entity_unit.get(int(entity)))
        if hero is None:
            continue
        hero["angleSamples"] = row["angle"]
        hero["stateTlv"] = row["tlv"]
    # Early CC key-value push per hero (frame <= 10): 8c=2 marks the jungler
    # (summoner spell, verified against 狩猎宽刃 first buys — 既有校准).
    for ev in events_source(abc):
        if ev["name"] == "CC" and ev["frame"] <= 10:
            buf = bytes.fromhex(ev["buffer_hex"])
            hero = heroes.get(entity_unit.get(ev["object_id"]))
            if hero is None:
                continue
            states = hero.setdefault("initialStates", {})
            if len(buf) == 2 and buf[0] != 0x02:
                states[f"{buf[0]:02x}"] = buf[1]
            elif len(buf) == 3 and buf[0] == 0x02:
                states[f"{buf[1]:02x}"] = buf[2]
    # Direction-integrated shape estimate (既有校准): explicitly NOT a
    # position — attached per hero for the workbench estimate layer.
    for hero in heroes.values():
        hero["pathEstimate"] = integrate_path(hero["moves"])
    # First/last activity over confirmed gameplay inputs only: CC rows (frame 3
    # in samples) have unresolved semantics and would fake a pre-battle input.
    activity = [row[0] for hero in heroes.values()
                for row in (*hero["moves"], *hero["attacks"], *hero["buys"],
                            *hero["learnSkill"], *hero["skills"])]
    first_input = min(activity) if activity else None
    last_activity = max(activity) if activity else None
    manual_buys = [row[0] for hero in heroes.values() for row in hero["buys"]
                   if len(row) > 3 and row[3] in (0, 1)]
    # Battle 0:00 sits within the first second of the stream (既有校准):
    # last manual buy happens before input locks at victory, so victory frame
    # >= lastManualBuy and the displayed duration pins F0 to [0..14].
    # The engine dump measures 15.1515 fps, but the record-stream sequence has
    # not been proven to be that same counter, so this stays on the documented
    # baseline (replay_time.FPS).
    last_manual = max(manual_buys) if manual_buys else None
    estimated_duration = round(max(last_manual - 7, 0) / FRAME_RATE, 1) if last_manual is not None else None
    return {"abc": {"sha256": digest(abc), "size": len(abc)},
            "resourceVersion": info["header"]["versions"][1],
            "unitSchema": "unit = 8 + (camp-1)*8 + slot; camp2 units 16-20 (build 5247758 samples)",
            "roster": heroes,
            "unknownUnits": sorted(set(unknown_units)),
            "audit": {"frameRecords": inputs["frameRecords"],
                      "fullyParsedFrames": inputs["fullyParsedFrames"],
                      "unresolvedFrames": inputs["unresolvedFrames"],
                      "entryCounts": inputs["entryCounts"]},
            "timeBase": {"framesPerSecond": FRAME_RATE,
                         "battleStartFrame": list(replay_time.BATTLE_START_FRAME_APPROX),
                         "firstInputFrame": first_input,
                         "lastActivityFrame": last_activity,
                         "lastManualBuyFrame": last_manual,
                         "estimatedBattleSeconds": estimated_duration,
                         "uncertaintySeconds": 1,
                         "streamSeconds": round((last_activity - first_input + 1) / FRAME_RATE, 2),
                         "note": "t ≈ (frame − battleStart)/15 s，battleStart ∈ [0..14] 帧，误差 ≤ ±1s。"
                                 "校准依据 既有校准：某局样本与赛后截图同局（十人 1251 评分"
                                 "与英雄逐一一致），页面时长 11:33 = 693s，最后手动购买帧 10409 → "
                                 "(10409−[0..14])/15 = 692.9-693.9s ✓；流末尾为胜利动画（输入已锁定）。"
                                 "引擎 dump 实测 15.1515 fps（57 帧/3762 ms），但回放 seq 是否同一计数器"
                                 "未验证，故未并入；见 replay_time.py。",
                         "verifiedFor": "5247758 样本；未逐构建验证"},
            "moveSchema": "[frame, dir_deg, mag, sign, seq]; dir_deg 与方向技能瞄准同角度系，世界向量 = (cos dir°, sin dir°)（native 轴 +y 向南），罗盘 = (90+dir)%360，见 既有校准",
            "attackSchema": "[frame, hasTarget, target_object_id, seq, flag]",
            "buySchema": "[frame, equip_id, object_id, flag, price]；flag 语义未解（0/1/24/90/210），price 为战斗装备表参考价（缺失为 null），不据此合计支出",
            "angleSchema": "[frame, angle_deg 0-359] 0x2d 变化采样；经验上 ≈ (dir_deg+180)%360（云缨 r=0.86），精确语义（朝向/瞄准）未定；仅部分英雄有（录制者必有）",
            "tlvSchema": "[frame, length, hex] 0x01 包装内的其余嵌套 TLV（0x1e/0x1f/0x2c/0x2d 之外及长度 14/17/19/28 等），留档待解",
            "pathSchema": "[frame, x, y] 方向积分形状估算：每条移动输入 1 单位步进；漂移严重（对锚点残差 1.8万-6.5万，地图 ±5万），仅示意转向历史，绝非位置/轨迹，见 既有校准",
            "positionSchema": "[frame, x, y] 来自尾部帧流 0x82 kind=2，稀疏锚点非逐帧轨迹",
            "limitations": [
                "输入方向角不是逐帧世界坐标；positions 仅 0x82 稀疏采样，pathEstimate 为漂移的方向积分形状，均不构成真实轨迹。",
                "seq/flag 位的确切触发语义未解，仅随事件保留。",
                "AI 英雄（人机局）不发 PLAYER_MOVE，移动由引擎确定性模拟。",
                "对局秒为 15fps 换算近似（±1s，见 timeBase.note）；流末尾含胜利动画帧。",
            ]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("abc", type=Path)
    parser.add_argument("--out", type=Path, help="new JSON file for the full timeline")
    parser.add_argument("--force", action="store_true", help="overwrite an existing --out file")
    args = parser.parse_args()
    data = args.abc.read_bytes()
    try:
        report = timeline(data)
    except ValueError as exc:
        print(json.dumps({"file": str(args.abc), "error": str(exc)}, ensure_ascii=False))
        return 2
    if args.out:
        if args.out.exists() and not args.force:
            print(json.dumps({"file": str(args.abc),
                              "error": f"{args.out} 已存在，未覆盖（--force 可覆盖）"},
                             ensure_ascii=False))
            return 3
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                            encoding="utf-8")
    rows = []
    for unit in sorted(report["roster"]):
        hero = report["roster"][unit]
        rows.append({"unit": unit, "hero": hero["hero"], "camp": hero["camp"],
                     "slot": hero["slot"], "entityId": hero["entityId"],
                     "moves": len(hero["moves"]), "attacks": len(hero["attacks"]),
                     "buys": len(hero["buys"]), "skills": len(hero["skills"])})
    print(json.dumps({"file": str(args.abc), "unknownUnits": report["unknownUnits"],
                      "heroes": rows}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
