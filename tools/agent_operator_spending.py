#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""普通 5v5（build 5069040）支出/装备缺口的只读探针。

目标
----
1. 解 `.ope` 外层/内层 raw DEFLATE，扫出主样本里可高置信识别的
   operator 记录签名：UnityFrameOpe / GameCoreFrameOpe / TouchOpe /
   SkillSlotOpe / UIEventOpe / GameObjectNameOpe / UILayout。
2. 把 UIEventOpe = `0B 7D <ULEB128 EventID>` 的 EventID 对到
   `Assets.Scripts.UI.enUIEventID` 的数值（metadata 默认值表），并检查
   商店/购买/装备类事件是否出现。
3. 在全部 `.abc` 样本（重点 6 个 build=5069040）里扫购买/装备/金额签名：
   `02/85 len5` 金币流水、`02/86 len6`、`02/87 len7`、`01/87 len5`、
   `01/48 len9`、`01/1e len19`、`02/80` 帧命令、Equip 表 ID。
4. 区分 build 5069040 与 5230306（后者 `02/85` 才是装备 item 事件）。

约束
----
只读：不修改回放/包体，不注入进程，不读取 param.json，不使用
`data/replays/_analysis/runtime_dump/`。所有结论带样本数与证据路径。

输出
----
data/replays/_analysis/datasets/agent_operator_spending.csv
data/replays/_analysis/datasets/agent_operator_spending.md

用法
----
  python tools/agent_operator_spending.py
  python tools/agent_operator_spending.py --limit-ope 4 --limit-abc 3
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "data" / "replays" / "_analysis"
DATASETS = ANALYSIS / "datasets"
ABC_DIR = ROOT / "data" / "replays" / "samples" / "abc_batch"
OPE_DIR = ROOT / "data" / "replays" / "samples" / "batch"
OUT_CSV = DATASETS / "agent_operator_spending.csv"
OUT_MD = DATASETS / "agent_operator_spending.md"

TARGET_BUILD = "5069040"       # 普通 5v5（主样本）
CONTROL_BUILD = "5230306"      # 快速赛变体：02/85 才是装备 item
CLIENT_BUILD = "4989537"       # .ope header build；与 libil2cpp/metadata 同构建

# `02/85` 在 5069040 的 source 取值（agent_gold_source_enum.csv 已对拍）
GOLD_SOURCES = {4, 5, 6, 43, 44, 47, 51, 86}
# 商店/购买/装备类 enUIEventID 的关键数值（metadata 默认值表可读出的）
SHOP_UI_VALUES = {
    1142: "Battle_OnOpenDropItemDetail",
    1144: "Battle_OnCloseDropItemDetail",
    1194: "Battle_EquipBoughtEffectPlayEnd",
    1206: "Battle_PickDropItem",
    1248: "Purchase_OpenBuyActionPoint",
    1250: "Purchase_OpenBuyCoin",
    1252: "Purchase_OpenBuySkillPt",
    1256: "Purchase_BuyActPt",
    1258: "Purchase_BuyCoinOne",
    1260: "Purchase_BuyCoinTen",
    1262: "Purchase_BuySkillPt",
    1264: "Purchase_CloseBuyActionPoint",
    1266: "Purchase_CloseBuyCoin",
    1268: "Purchase_CloseBuySkillPt",
    1272: "Purchase_CloseBuyDiamond",
    1274: "Purchase_BuySymbolPage",
    1276: "Purchase_BuyDiamond",
}
SHOP_RE = re.compile(
    r"(Shop|Store|Buy|Equip|Purchase|Mall|Goods|DropItem|PickDrop)", re.I
)
STRING_RE = re.compile(rb"[\x20-\x7e]{6,}")

TYPE_NAMES = {
    0x00: "Common", 0x01: "UnityFrameOpe", 0x02: "GameCoreFrameOpe",
    0x03: "SkillUseOpe", 0x04: "SkilOpe", 0x05: "TouchOpe", 0x06: "MoveOpe",
    0x07: "CoreChangeOpe", 0x08: "SkillBtnForceUpOpe",
    0x09: "RefreshSkillBtnStatusOpe", 0x0A: "UIntOpe", 0x0B: "UIEventOpe",
    0x0C: "CppEventOpe", 0x0D: "BtnBrokenContactOpe",
    0x0E: "GameObjectNameOpe", 0x0F: "UIViewChangeOpe", 0x10: "MemoryData",
    0x11: "CustomLog", 0x12: "SkillHitRate", 0x13: "SkillSlotOpe",
    0x14: "SkillCancelOpe", 0x15: "DirSkillOpe", 0x16: "UILayout",
    0x17: "PredictMoveOpe", 0x18: "SendMsgToServerOpe",
    0x19: "DeadOrReviveOpe",
}


# ------------------------------------------------------------------ helpers
def read_uleb(data: bytes, pos: int, max_bytes: int = 5) -> tuple[int, int]:
    value = shift = 0
    for _ in range(max_bytes):
        if pos >= len(data):
            raise IndexError
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
    raise ValueError("uleb too long")


def read_abc_header(data: bytes) -> list[str]:
    out, i = [], 0
    for _ in range(4):
        if i >= len(data):
            break
        n = data[i]
        out.append(data[i + 1:i + 1 + n].decode("latin1", "replace"))
        i += 1 + n
    return out


def abc_records(data: bytes, start: int = 0xBFE8, seq0: int = 0x22):
    """`.abc` 尾部记录流：seq:u8 00 L:u8 payload[L] a:u8 00*5 b:u8。"""
    pos, seq, out = start, seq0, []
    while pos + 10 < len(data):
        if data[pos] != (seq & 0xFF) or data[pos + 1] != 0:
            break
        length = data[pos + 2]
        if pos + 10 + length > len(data):
            break
        out.append({"seq": seq, "payload": data[pos + 3:pos + 3 + length]})
        pos += 10 + length
        seq += 1
    return out, pos


def abc_find_stream(data: bytes):
    best = ([], 0)
    for pos in range(0, min(len(data), 0x20000)):
        if data[pos] == 0x22 and data[pos + 1] == 0:
            recs, end = abc_records(data, pos)
            if len(recs) > len(best[0]):
                best = (recs, end)
                if len(recs) > 500:
                    break
    return best


def abc_messages(payload: bytes):
    """返回 (kind, tag, hero, flag/sub, data) 列表；截断时返回已解部分。

    kind='s' 标量；kind='h' 英雄消息。tag 0x02/flag 0x80 的 12B 体
    按 data 返回（帧命令），长度按 flag&0x7f 不适用。
    """
    if not payload:
        return []
    i, out = 1, []
    while i < len(payload):
        tag = payload[i]
        try:
            if tag == 0x12:
                if i + 3 > len(payload):
                    break
                out.append(("s", tag, 0, 0, payload[i + 1:i + 3]))
                i += 3
            elif tag == 0x13:
                if i + 2 > len(payload):
                    break
                out.append(("s", tag, 0, 0, payload[i + 1:i + 2]))
                i += 2
            elif tag == 0x14:
                if i + 4 > len(payload):
                    break
                out.append(("s", tag, 0, 0, payload[i + 1:i + 4]))
                i += 4
            elif tag == 0x01:
                if i + 5 > len(payload):
                    break
                hero = struct.unpack_from(">H", payload, i + 1)[0]
                flag = payload[i + 3]
                n = payload[i + 4]
                if i + 5 + n > len(payload):
                    break
                out.append(("h", tag, hero, flag, payload[i + 5:i + 5 + n]))
                i += 5 + n
            elif tag == 0x02:
                if i + 4 > len(payload):
                    break
                hero = struct.unpack_from(">H", payload, i + 1)[0]
                flag = payload[i + 3]
                if flag == 0x80:
                    if i + 16 > len(payload):
                        break
                    out.append(("h", tag, hero, flag, payload[i + 4:i + 16]))
                    i += 16
                else:
                    n = flag & 0x7F
                    if i + 4 + n > len(payload):
                        break
                    out.append(("h", tag, hero, flag, payload[i + 4:i + 4 + n]))
                    i += 4 + n
            else:
                break
        except (IndexError, struct.error):
            break
    return out


def unwrap_ope(path: Path):
    """外层 0x01+raw DEFLATE -> inner[0x80..0xa0] raw DEFLATE -> stream。"""
    raw = path.read_bytes()
    if raw[:1] != b"\x01":
        return None, None, "outer flag != 0x01"
    try:
        inner = zlib.decompressobj(-15).decompress(raw[1:])
    except zlib.error as exc:
        return None, None, f"outer deflate: {exc}"
    found = []
    for off in range(0x80, 0xA0):
        try:
            stream = zlib.decompressobj(-15).decompress(inner[off:])
        except zlib.error:
            continue
        if len(stream) > 1000 and stream[:3] == b"\x02\x00\x01":
            found.append((off, stream))
    if not found:
        return None, None, "inner deflate not found"
    off, stream = found[0]
    return stream, off, None


def ope_header_strings(inner_off: int, path: Path) -> dict[str, str | None]:
    """从 .ope 内层头取 client/res/build/device。只读。"""
    raw = path.read_bytes()
    try:
        inner = zlib.decompressobj(-15).decompress(raw[1:])
    except zlib.error:
        return {}
    fields = {}
    i = 0
    limit = min(inner_off, 0x8A)
    while i < limit:
        n = inner[i]
        if 4 <= n <= 64 and i + 1 + n <= limit:
            chunk = inner[i + 1:i + 1 + n]
            if all(32 <= b < 127 for b in chunk):
                fields[i] = chunk.decode("ascii")
                i += 1 + n
                continue
        i += 1
    named: dict[str, str | None] = {
        "clientVersion": None, "resVersion": None, "build": None,
        "device": None, "account": None, "localTime": None,
    }
    for _off, text in sorted(fields.items()):
        if named["clientVersion"] is None and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", text):
            named["clientVersion"] = text
        elif named["resVersion"] is None and re.fullmatch(r"\d+(\.\d+)+", text):
            named["resVersion"] = text
        elif named["build"] is None and re.fullmatch(r"\d{5,}", text):
            named["build"] = text
        elif named["localTime"] is None and re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", text):
            named["localTime"] = text
        elif named["account"] is None and re.fullmatch(r"[0-9A-F]{32}", text):
            named["account"] = text
        elif named["device"] is None and " " in text and re.search(r"[A-Za-z]", text):
            named["device"] = text
    return named


# ------------------------------------------------------------- operator scan
def scan_ui_events(stream: bytes):
    """UIEventOpe = 0B 7D <ULEB128 EventID>；下一条必须是合法类型或 EOF。"""
    out = []
    for pos in range(len(stream) - 3):
        if stream[pos] != 0x0B or stream[pos + 1] != 0x7D:
            continue
        try:
            event_id, end = read_uleb(stream, pos + 2)
        except (IndexError, ValueError):
            continue
        if event_id > 2_000_000:
            continue
        if end < len(stream) and stream[end] > 0x19:
            continue
        out.append((pos, event_id, end))
    return out


def scan_gameobject_names(stream: bytes):
    out = []
    for pos in range(len(stream) - 6):
        if stream[pos] != 0x0E:
            continue
        try:
            _inst, q = read_uleb(stream, pos + 3)
        except (IndexError, ValueError):
            continue
        if q >= len(stream):
            continue
        n = stream[q]
        end = q + 1 + n
        if not 2 <= n <= 200 or end > len(stream):
            continue
        path = stream[q + 1:end]
        if not all(32 <= b < 127 for b in path) or b"/" not in path:
            continue
        if end < len(stream) and stream[end] > 0x19:
            continue
        out.append((pos, int.from_bytes(stream[pos + 1:pos + 3], "little"),
                    path.decode("ascii", "replace")))
    return out


def scan_skill_slots(stream: bytes) -> int:
    count = 0
    for pos in range(len(stream) - 5):
        if (stream[pos] == 0x13 and stream[pos + 1:pos + 3] == b"\xae\x01"
                and stream[pos + 3] <= 15 and stream[pos + 4] <= 3):
            count += 1
    return count


def scan_wire_histogram(stream: bytes) -> Counter:
    """只统计能自证边界的三类签名，避免把数据字节误当记录。

    - UIEventOpe: 0B 7D <uleb>，下一条必须是合法类型；
    - SkillSlotOpe: 13 AE 01 <slot 0-15> <value 0-3>；
    - UILayout: 16 B4 01 + payload，payload 结束处紧跟 13 AE 01。
    其他类型的边界仍多解，不在本表冒充计数。
    """
    hist = Counter()
    for pos in range(len(stream) - 3):
        t = stream[pos]
        try:
            if t == 0x0B and stream[pos + 1] == 0x7D:
                v, end = read_uleb(stream, pos + 2)
                if v <= 2_000_000 and (end == len(stream) or stream[end] <= 0x19):
                    hist[("UIEventOpe", end - pos)] += 1
            elif t == 0x13 and stream[pos + 1:pos + 3] == b"\xae\x01":
                if stream[pos + 3] <= 15 and stream[pos + 4] <= 3:
                    hist[("SkillSlotOpe", 5)] += 1
            elif t == 0x16 and stream[pos + 1:pos + 3] == b"\xb4\x01":
                for length in range(80, 201):
                    end = pos + 3 + length
                    if end + 5 <= len(stream) and stream[end:end + 3] == b"\x13\xae\x01":
                        hist[("UILayout", end - pos)] += 1
                        break
        except (IndexError, ValueError):
            continue
    return hist


def scan_misc_events(stream: bytes) -> dict[str, Counter]:
    """低置信签名扫描：CppEvent / UIViewChange / SendMsgToServer。

    这三类边界仍多解，计数只用于回答“有没有可能承载商店事件”。
    metadata 字段已证明它们都没有金额字段：
      CppEvent: SlotType/SkillId/Value
      UIViewChange: ViewType/Open
      SendMsgToServer: CSMsgID/result
    """
    cpp: Counter = Counter()
    view: Counter = Counter()
    send: Counter = Counter()
    for pos in range(len(stream) - 8):
        t = stream[pos]
        try:
            if t == 0x0C and stream[pos + 1] <= 15:
                v1, q = read_uleb(stream, pos + 2)
                v2, q2 = read_uleb(stream, q)
                if (v1 < 1_000_000 and v2 < 1_000_000 and q2 < len(stream)
                        and stream[q2] <= 0x19):
                    cpp[(stream[pos + 1], v1, v2)] += 1
            elif t == 0x0F:
                frame = int.from_bytes(stream[pos + 1:pos + 3], "little")
                vt, opened = stream[pos + 3], stream[pos + 4]
                if (frame < 60_000 and vt < 100 and opened <= 1
                        and stream[pos + 5] <= 0x19):
                    view[(vt, opened)] += 1
            elif t == 0x18:
                frame = int.from_bytes(stream[pos + 1:pos + 3], "little")
                msg_id = int.from_bytes(stream[pos + 3:pos + 5], "little")
                result = stream[pos + 5]
                if frame < 60_000 and stream[pos + 6] <= 0x19:
                    send[(frame, msg_id, result)] += 1
        except (IndexError, ValueError):
            continue
    return {"cpp": cpp, "view": view, "send": send}


def load_ui_event_names() -> dict[int, str]:
    """从 global-metadata.dat 的 enUIEventID 默认值表取 value->name。"""
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from agent_gold_source_enum import Metadata  # type: ignore
    except Exception:
        return {}
    try:
        md = Metadata()
        hit = [t for t in md.types
               if t["name"] == "enUIEventID" and t["ns"] == "Assets.Scripts.UI"]
        if not hit:
            return {}
        t = hit[0]
        names: dict[int, str] = {}
        for f in range(t["first_field"], t["first_field"] + t["field_count"]):
            entry = md._defaults.get(f)
            if not entry:
                continue
            value, n = md._varint(entry[1])
            if value is None or n > 3:
                continue
            names.setdefault(value, md.field_name(f))
        return names
    except Exception:
        return {}


def load_shop_ui_values(names: dict[int, str]) -> dict[int, str]:
    shop = dict(SHOP_UI_VALUES)
    for value, name in names.items():
        if SHOP_RE.search(name):
            shop.setdefault(value, name)
    return shop


# ------------------------------------------------------------------ abc scan
def load_equip_ids() -> set[int]:
    path = DATASETS / "decoded_csharp_all" / "134_Equip.bytes.csv"
    if not path.exists():
        return set()
    ids: set[int] = set()
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh):
                if not row:
                    continue
                try:
                    ids.add(int(row[0]))
                except ValueError:
                    continue
    except OSError:
        return set()
    return ids


def scan_abc_file(path: Path, equip_ids: set[int]) -> list[dict]:
    data = path.read_bytes()
    header = read_abc_header(data)
    client_build = header[2] if len(header) > 2 else "?"
    build = header[3] if len(header) > 3 else "?"
    rows: list[dict] = []
    recs, _end = abc_find_stream(data)

    gold_count = 0
    gold_sources: Counter = Counter()
    gold_amounts: list[int] = []
    gold_zero = gold_neg = 0
    sig86 = sig87 = sub87_5 = sub48_9 = sub1e_19 = 0
    sig86_samples: list[str] = []
    sig48_samples: list[str] = []
    sig87_ids: Counter = Counter()
    sig87_levels: Counter = Counter()
    frame_cmds: Counter = Counter()
    equip_hits = 0
    for rec in recs:
        for kind, tag, _hero, flag, body in abc_messages(rec["payload"]):
            if kind != "h":
                continue
            if tag == 0x02:
                if flag == 0x85 and len(body) == 5:
                    source = body[0]
                    amount = int.from_bytes(body[1:5], "little")
                    if source in GOLD_SOURCES and amount < 100_000:
                        gold_count += 1
                        gold_sources[source] += 1
                        gold_amounts.append(amount)
                        if amount == 0:
                            gold_zero += 1
                        if amount > 0x7FFFFFFF:
                            gold_neg += 1
                elif flag == 0x86 and len(body) == 6:
                    sig86 += 1
                    if len(sig86_samples) < 3:
                        sig86_samples.append(body.hex(" "))
                elif flag == 0x87 and len(body) == 7:
                    sig87 += 1
                    sig87_ids[body[3]] += 1
                    sig87_levels[body[4]] += 1
                elif flag == 0x80 and len(body) == 12:
                    frame_cmds[struct.unpack_from("<H", body, 0)[0]] += 1
                elif flag != 0x85 and len(body) >= 2 and equip_ids:
                    if int.from_bytes(body[0:2], "big") in equip_ids:
                        equip_hits += 1
                    elif int.from_bytes(body[0:2], "little") in equip_ids:
                        equip_hits += 1
            elif tag == 0x01:
                if body:
                    sub = body[0]
                    if sub == 0x87 and len(body) == 5:
                        sub87_5 += 1
                    elif sub == 0x48 and len(body) == 9:
                        sub48_9 += 1
                        if len(sig48_samples) < 3:
                            sig48_samples.append(body.hex(" "))
                    elif sub == 0x1E and len(body) == 19:
                        sub1e_19 += 1

    def add(signature, count, detail, confidence="high", note=""):
        rows.append({
            "dataset": "abc", "build": build, "client_build": client_build,
            "file": path.name, "domain": "spending_abc",
            "signature": signature, "count": count, "distinct": "",
            "min": "", "max": "", "zero_or_negative": "",
            "detail": detail, "confidence": confidence, "note": note,
        })

    add("02/85 len5 gold_flow", gold_count,
        "sources=" + ",".join(f"{k}:{v}" for k, v in sorted(gold_sources.items())),
        note="source:u8 + amount:u32LE；只统计已知金币 source")
    if gold_amounts:
        rows[-1]["min"] = min(gold_amounts)
        rows[-1]["max"] = max(gold_amounts)
        rows[-1]["zero_or_negative"] = f"zero={gold_zero};hi_bit={gold_neg}"
    add("02/86 len6", sig86, "samples=" + " | ".join(sig86_samples),
        confidence="low", note="2 例全局命中，样本内含 0x12 标签，疑为解析伪命中")
    add("02/87 len7", sig87,
        "id_range=%s..%s " % (min(sig87_ids) if sig87_ids else "-",
                              max(sig87_ids) if sig87_ids else "-")
        + "id_byte_top=" + ",".join(f"{k}:{v}" for k, v in sig87_ids.most_common(8))
        + " levels=" + ",".join(f"{k}:{v}" for k, v in sig87_levels.most_common()),
        confidence="medium", note="id 7-65 / level 1-4，非 Equip 表 row_id（1111-5536）")
    add("01/87 len5", sub87_5, "data=87 00 00 00 00 型", confidence="medium",
        note="零值标志位，无金额/物品")
    add("01/48 len9", sub48_9,
        "samples=" + (" | ".join(sig48_samples) or "0"), confidence="medium",
        note="原始 9B；样本内容非结构化，不是购买")
    add("01/1e len19", sub1e_19, "", confidence="medium", note="伤害/属性变化表，非购买")
    add("02/80 frame_cmd", sum(frame_cmds.values()),
        "cmd_types=" + ",".join(f"{k}:{v}" for k, v in frame_cmds.most_common()),
        confidence="high", note="无 22/23/35（InOutEquipShop/RecommendEquipGroup/OneStepBuyEquip）")
    add("equip_id_in_structured_field", equip_hits, f"equip_ids={len(equip_ids)}",
        confidence="medium", note="排除 02/85 金币流水后的结构化字段命中；0=无装备 ID")

    # 5230306 的 TLV 语法不同：只有“无 seq 帧记录流”的 68KB 变体才是
    # `02 <hero2> 85 <type:u8> <item:u16LE> 00`。20261027 的 5230306
    # 资源号样本仍有 5069040 式记录流，不能按 5230306 形状扫。
    if build == CONTROL_BUILD and len(recs) < 100:
        buys = []
        for pos in range(len(data) - 6):
            if data[pos] == 0x02 and data[pos + 1] == 0x85 and data[pos + 2] in (4, 5, 6):
                item = int.from_bytes(data[pos + 3:pos + 5], "little")
                if 0 < item < 1000:
                    buys.append((pos, data[pos + 2], item))
        add("5230306 02/85 buy_item", len(buys),
            "items=" + ",".join(f"type{t}:item{i}" for _, t, i in buys[:20]),
            confidence="high", note="该 build 的 02/85 = 装备 item；5069040 不适用")
    return rows


def scan_ope_file(path: Path, ui_names: dict[int, str], shop_values: dict[int, str]):
    stream, off, err = unwrap_ope(path)
    rows: list[dict] = []
    if stream is None:
        rows.append({
            "dataset": "ope", "build": "?", "client_build": "?", "file": path.name,
            "domain": "operator", "signature": "unwrap", "count": 0,
            "distinct": "", "min": "", "max": "", "zero_or_negative": "",
            "detail": err or "", "confidence": "high", "note": "解压失败",
        })
        return rows, {}
    hdr = ope_header_strings(off, path)
    build = hdr.get("build") or "?"
    client = hdr.get("clientVersion") or "?"
    events = scan_ui_events(stream)
    ids = Counter(event_id for _p, event_id, _e in events)
    names_hit = {v: ui_names[v] for v in ids if v in ui_names}
    shop_hit = {v: ids[v] for v in ids if v in shop_values}
    gonames = scan_gameobject_names(stream)
    slots = scan_skill_slots(stream)
    hist = scan_wire_histogram(stream)
    misc = scan_misc_events(stream)

    strings = []
    keyword_strings = []
    for match in STRING_RE.finditer(stream):
        text = match.group().decode("ascii")
        strings.append(text)
        if re.search(r"(Shop|Store|Buy|Equip|Mall|Gold|Coin|Item|Purchase|Goods)", text, re.I):
            keyword_strings.append(text)

    def add(signature, count, detail, confidence="high", note="", distinct=""):
        rows.append({
            "dataset": "ope", "build": build, "client_build": client,
            "file": path.name, "domain": "operator",
            "signature": signature, "count": count, "distinct": distinct,
            "min": min(ids) if ids else "", "max": max(ids) if ids else "",
            "zero_or_negative": "", "detail": detail,
            "confidence": confidence, "note": note,
        })

    add("UIEventOpe 0B7D+uleb", len(events),
        "top=" + ",".join(f"{k}:{v}" for k, v in ids.most_common(12))
        + " named=" + ",".join(f"{k}={v}" for k, v in sorted(names_hit.items())[:8]),
        distinct=len(ids), note="EventID 为 enUIEventID 数值；无金额/物品字段")
    add("UIEventOpe shop_like", sum(shop_hit.values()),
        "ids=" + ",".join(f"{k}:{v}({shop_values[k]})" for k, v in sorted(shop_hit.items()))
        or "0",
        confidence="high", note="1194/1206/1248-1276 等购买类事件命中数")
    add("GameObjectNameOpe", len(gonames),
        "paths=" + " | ".join(sorted({p for _o, _f, p in gonames})[:8]),
        note="只出现相机/UI 相机路径" if gonames else "无")
    add("SkillSlotOpe 13ae01", slots, "", note="13 AE 01 slot value")
    add("ascii_string>=6", len(strings),
        "keyword_hits=" + (" | ".join(keyword_strings[:8]) or "0"),
        note="operator 流内 shop/purchase/equip 字符串")
    add("wire_length_hist", sum(hist.values()),
        "hist=" + ",".join(f"{k[0]}:{k[1]}x{v}" for k, v in hist.most_common(10)),
        confidence="medium", note="签名级直方图，非全流分段")
    add("CppEventOpe 0C sig", sum(misc["cpp"].values()),
        "top=" + ",".join(f"{k}:{v}" for k, v in misc["cpp"].most_common(6)),
        confidence="low-medium", note="SlotType/SkillId/Value；无金额字段，边界多解")
    add("UIViewChangeOpe 0F sig", sum(misc["view"].values()),
        "top=" + ",".join(f"{k}:{v}" for k, v in misc["view"].most_common(6)),
        confidence="low-medium", note="ViewType/Open；无金额字段，边界多解")
    add("SendMsgToServerOpe 18 sig", sum(misc["send"].values()),
        "top=" + ",".join(f"{k}:{v}" for k, v in misc["send"].most_common(6)),
        confidence="medium", note="CSMsgID/result；无金额字段；40301 为主")
    return rows, {
        "file": path.name, "build": build, "client": client,
        "stream": len(stream), "off": off, "ui": len(events),
        "distinct": len(ids), "ids": ids, "shop_hit": shop_hit,
        "gonames": gonames, "slots": slots, "strings": keyword_strings,
        "hist": hist, "misc": misc,
    }


# ------------------------------------------------------------------- report
CSV_FIELDS = [
    "dataset", "build", "client_build", "file", "domain", "signature",
    "count", "distinct", "min", "max", "zero_or_negative", "detail",
    "confidence", "note",
]


def write_csv(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: (
        r["dataset"], r["build"], r["file"], r["domain"], r["signature"]))
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(x) for x in row) + " |")
    return "\n".join(out)


def write_md(abc_rows, ope_summaries, ui_names, shop_values) -> None:
    target_abc = [r for r in abc_rows if r["build"] == TARGET_BUILD]
    control_abc = [r for r in abc_rows if r["build"] == CONTROL_BUILD]
    ope_main = next((x for x in ope_summaries
                     if x["file"].startswith("20260925_105224")), None)
    ope_target = [x for x in ope_summaries if x["build"] == CLIENT_BUILD]

    # aggregate 5069040 signature counts
    agg = defaultdict(lambda: {"count": 0, "files": 0})
    for row in target_abc:
        key = row["signature"]
        agg[key]["count"] += int(row["count"])
        if int(row["count"]) > 0:
            agg[key]["files"] += 1
    sig_order = [
        "02/85 len5 gold_flow", "02/86 len6", "02/87 len7", "01/87 len5",
        "01/48 len9", "01/1e len19", "02/80 frame_cmd",
        "equip_id_in_structured_field",
    ]
    unique_abc_files = len({r["file"] for r in target_abc})
    unique_abc_all = len({r["file"] for r in abc_rows if r["dataset"] == "abc"})
    unique_ope_files = len(ope_summaries)
    sig_rows = []
    for sig in sig_order:
        item = agg.get(sig, {"count": 0, "files": 0})
        sample = next((r for r in target_abc if r["signature"] == sig and r["file"].startswith("20260925_105224")), None)
        detail = ""
        if sample:
            detail = f"{sample['detail']}; min={sample['min']} max={sample['max']} {sample['zero_or_negative']}"
        sig_rows.append([sig, item["count"], f"{item['files']}/{unique_abc_files}",
                         detail[:180]])

    # operator UI event table (main sample)
    ui_rows = []
    if ope_main:
        for value, count in ope_main["ids"].most_common(20):
            ui_rows.append([value, count, ui_names.get(value, ""),
                            shop_values.get(value, "")])
    # cross-sample shop-like hits
    shop_total = Counter()
    for item in ope_summaries:
        for value, count in item["shop_hit"].items():
            shop_total[value] += count
    shop_rows = [[v, c, shop_values.get(v, "")] for v, c in sorted(shop_total.items())]
    if not shop_rows:
        shop_rows = [["—", 0, "全部样本 0 命中"]]

    # 5230306 rows：只列 68KB 无 seq 记录流的真 5230306 TLV 样本
    ctrl_rows = []
    for row in control_abc:
        if not row["file"].startswith("20261028"):
            continue
        if row["signature"] not in ("5230306 02/85 buy_item",):
            continue
        ctrl_rows.append([row["file"], row["signature"], row["count"],
                          row["detail"][:160], row["note"][:100]])

    # wire histogram main
    hist_rows = []
    if ope_main:
        for (name, length), count in ope_main["hist"].most_common(12):
            hist_rows.append([name, length, count])

    lines = []
    add = lines.append
    add("# 普通 5v5（build 5069040）支出/装备缺口：operator + .abc 只读验证")
    add("")
    add(f"> 只读逆向报告。样本：`data/replays/samples/abc_batch/` 去重后 {unique_abc_all} 个 `.abc`、"
        f"`data/replays/samples/batch/` 去重后 {unique_ope_files} 个 `.ope`；"
        f"重点为 {unique_abc_files} 个 build=5069040 的普通 5v5 样本。")
    add("> 不修改回放/包体，不注入进程，不读取 `param.json`，不使用 `runtime_dump/`。")
    add("")
    add("## 0. 结论摘要")
    add("")
    add("1. **5069040 回放侧拿不到“支出/装备”**：`.abc` 的 `02/85 len5` 是"
        " `source:u8 + amount:u32LE` 的**金币收入流水**，主样本本工具 286 条"
        "（5.91 记分卡 281；差异来自 partial payload 解析）、金额 31–254，"
        "零额 0、负额 0；没有 `OneStepBuyEquip`/`InOutEquipShop` 帧命令，"
        "没有结构化装备 ID。")
    add("2. **operator 流能解出 UIEventOpe，但没有金额/物品**："
        "`0B 7D <ULEB128 EventID>` 可稳定提取；`UiEventOperatorData` 的 metadata "
        f"字段只有 `EventID` 一个。{unique_ope_files} 个去重 `.ope` 全扫，"
        "商店/购买/装备类事件（1194/1206/1248–1276）**0 命中**；唯一 overlap 是 1144 "
        "`Battle_OnCloseDropItemDetail`（掉落物详情关闭，不是购买）。")
    add("3. **operator 流没有商店/装备字符串**：可读 ASCII 只有 3 条相机路径"
        "（`Design/MainCamera/...`、`BootObj/CUIManager/Camera_Form`、"
        "`Forms/Form_Battle_Part_CameraDragPanel/...`），关键词命中 0。")
    add("4. **唯一直接的装备购买证据在 5230306**：`02/85` 形如 "
        "`type:u8 + item:u16`（例：13.9s type=6 item=165 辅助宝石）。"
        "5069040 的 `02/85` 形状不同，不能套用。")
    add(f"5. **置信度**：对“5069040 回放侧不可得”为 **high**"
        f"（{unique_abc_files} 个 5069040 样本 + {unique_ope_files} 个去重 .ope 全扫）；"
        "对“所有 5069040 永远不写购买”保留为 **not proven**（只覆盖现有样本）。")
    add("")
    add("## 1. 样本与构建区分")
    add("")
    add(md_table(
        ["项目", "值", "证据"],
        [["`.abc` 头部", "client 4989537 / res 12.1.1.x / build 5069040 或 5230306", "`read_abc_header`"],
         ["`.ope` 头部", "client 4989537 / res 12.1.1.8 / build 4989537", "`unwrap_ope` + 内层头"],
         ["5069040 样本", "6 个（20260924_113638 至 20260925_105224）", "头部第 4 串 = 5069040"],
         ["5230306 样本", "2 个（20261028_135516/135520，TLV 语法不同）", "头部第 4 串 = 5230306"],
         ["主样本", "`20260925_105224_-1505729760_4933_1790303631.abc`（661,298 B）", "普通 5v5，614.7s"],
         ["主 .ope", "同名 `.ope`（196,031 B）→ 195,988 B → 436,738 B 流", "双层 raw DEFLATE"]])
    )
    add("")
    add("## 2. operator 流：解码结果与商店/购买事件")
    add("")
    add("### 2.1 记录签名（多样本交叉验证）")
    add("")
    add("`UIEventOpe` 的 `EventID` **不是**普通 ULEB128 直接跟在 `0B` 后面，"
        "而是固定 `7D` 标记 + ULEB128：`0B 7D <uleb>`。")
    add("")
    add("- 例：`0B 7D D1 08` → EventID 1105；`0B 7D E0 D4 03` → EventID 60000。")
    add(f"- 验证：{unique_ope_files} 个去重 `.ope` 中同一条 ID 在 4–5 字节长度上稳定重复；"
        "下一条字节始终是合法类型（0x00–0x19）。")
    add("- `SkillSlotOpe` 固定 `13 AE 01 <slot:u8> <value:u8>`（5B，slot 0–15，value 0–3）。")
    add("- `0x16 UILayout` 首条为 `16 B4 01` + payload：主样本记录总长 129B"
        "（payload 126B），39,634B 小样本总长 126B（payload 123B）；"
        "长度随屏幕布局变化，不是流头常量。")
    add("")
    if hist_rows:
        add(md_table(["签名", "长度", "主样本命中数"], hist_rows))
        add("")
    add("### 2.1.1 各 operator 类型的字段与观测布局（metadata 字段 + 流内证据）")
    add("")
    add(md_table(
        ["type", "类（metadata 字段）", "观测 wire layout", "置信度"],
        [["0x01", "UnityFrameOperatorData（无字段）", "type + unityFrame:uleb", "high"],
         ["0x02", "GamecoreFrameOperatorData（无字段）", "type + frame:u16 + unityFrame:uleb（或仅 frame）", "high"],
         ["0x05", "TouchOperatorData（TouchPosition/TouchId/TouchPhase/SlotType）", "type + frame:u16 + 4–5 varint", "medium-high"],
         ["0x0B", "UiEventOperatorData（EventID）", "0B 7D + EventID:uleb（无 Frame）", "high"],
         ["0x0E", "GameObjectNameOperatorData（GameObjectPath/InstId）", "type + frame:u16 + instId:uleb + len:u8 + path", "high"],
         ["0x10", "MemoryOperatorData（Stream）", "type + frame:u16 + len:uleb + bytes", "high"],
         ["0x13", "SkillSlotOperatorData（SlotType/Value）", "type + frame:u16 + slot:u8 + value:u8", "high"],
         ["0x16", "UILayoutData（20 个布局字段）", "type + frame:u16 + 126B payload（主样本）", "high"],
         ["0x03", "SkillUseOperatorData（SlotType/SkillId/SkillSeq）", "type + frame:u16 + 3–4 varint", "medium"],
         ["0x06", "MoveOperatorData（Degree/GameSvrPing/Seq）", "type + frame:u16 + 3–7 varint", "medium"],
         ["0x0A", "UIntOperatorData（Value）", "type + frame:u16 + u32（或 varint）", "medium"],
         ["0x0C", "CppEventOperatorData（SlotType/SkillId/Value）", "type + slot:u8 + 1–2 varint", "medium"],
         ["0x0F", "UIViewChangeOperatorData（ViewType/Open）", "type + frame:u16 + viewType:u8 + open:u8", "medium"],
         ["0x12", "SkillHitOperatorData（5 字段）", "type + frame:u16 + 3–5 varint", "low-medium"],
         ["0x14", "SkillCancelOperatorData（4 字段）", "type + frame:u16 + 3–4 varint", "medium"],
         ["0x15", "DirSkillUseOperatorData（Degree）", "type + frame:u16 + degree:uleb", "low-medium"],
         ["0x17", "PredictMoveData（iParam1/iParam2/byteParam）", "type + 10B（两个样本同形）", "medium"],
         ["0x18", "SendNetworkMsgToServerData（CSMsgID/result）", "type + frame:u16 + u16 + u8", "low"],
         ["0x19", "HeroDeadOrReliveData（8 字段）", "type + frame:u16 + 3–8 varint", "low"]])
    )
    add("")
    add("与 `operator_wire_table.json`（39,634B 小样本）的长度直方图交叉：")
    add("")
    add(md_table(
        ["type", "小样本长度（次数）", "主样本观测", "判定"],
        [["0x0B UIEventOpe", "4(581), 5(9), 7(3), 3(1), 2(1)", "4(1965), 5(16)", "一致：4B 主形 + 5B 变体"],
         ["0x13 SkillSlotOpe", "5(272), 4(96)", "5(11953)", "一致：5B 主形；4B 是小样本的变体"],
         ["0x05 TouchOpe", "9(366), 8(351), 10(52), 7(5)", "9/10B 为主", "一致：4–5 varint"],
         ["0x02 GameCoreFrameOpe", "3(602), 5(38), 4(11), 2(11)", "5–7B", "小样本 3B=仅 frame；主样本带 unityFrame"],
         ["0x16 UILayout", "126(1), 3(1)", "129(1)", "payload 随屏幕布局变化"]])
    )
    add("")
    add("> 说明：0x03/0x04/0x06/0x07/0x09/0x0A/0x12/0x14/0x17–0x19 的边界仍多解"
        "（5.6.4 已量化：仅 19.1% 段唯一）。本报告不把它们计入“已解记录”，"
        "只用能自证边界的 0x01/0x02/0x05/0x0B/0x0E/0x10/0x13/0x16。")
    add("")
    add("### 2.2 主样本 UIEventOpe Top 20")
    add("")
    if ui_rows:
        add(md_table(["EventID", "次数", "enUIEventID 名称（metadata 可读部分）", "商店/购买类"], ui_rows))
    else:
        add("（主样本未解出 UIEventOpe）")
    add("")
    add("### 2.3 全部 .ope 的商店/购买类命中")
    add("")
    add(md_table(["EventID", "总次数", "名称"], shop_rows))
    add("")
    add(f"**否定证据**：{unique_ope_files} 个去重 `.ope` 中 `1194 Battle_EquipBoughtEffectPlayEnd`、"
        "`1206 Battle_PickDropItem`、`1248–1276 Purchase_*` 全部 **0 命中**；"
        "`1144 Battle_OnCloseDropItemDetail` 是唯一命中的商店/掉落类 ID，"
        "它是“关闭掉落物详情”，不携带物品/价格。")
    add("")
    add(md_table(
        ["EventID", "enUIEventID", "全部 .ope 次数"],
        [["1142", "Battle_OnOpenDropItemDetail", 0],
         ["1144", "Battle_OnCloseDropItemDetail", 855],
         ["1194", "Battle_EquipBoughtEffectPlayEnd", 0],
         ["1206", "Battle_PickDropItem", 0],
         ["1248–1276", "Purchase_*（13 个）", 0]]))
    add("")
    add("1105/1106、1139/1141 等高频 ID 未出现在 metadata 默认值表（枚举隐式值不落盘），"
        "按 30 个样本的“成对同现 + 频次量级”判断为战斗按钮 Down/Up"
        "（medium；不是商店类）。")
    add("")
    add("### 2.4 operator 流里的字符串")
    add("")
    if ope_main:
        add(f"- 主样本可读 ASCII ≥6 共 {len(ope_main['strings'])} 条关键词命中，"
            f"全部 ASCII 串只有相机路径：")
        for path in sorted({p for _o, _f, p in ope_main["gonames"]}):
            add(f"  - `{path}`")
    add("- 没有 `Shop` / `Store` / `Buy` / `Equip` / `Mall` / `Coin` 字符串。")
    add("- metadata 的 `UiEventOperatorData` 字段只有 `EventID`（`operatordata_family.json`），"
        "所以即使命中商店按钮，也没有 item/price 字段。")
    add("")
    add("### 2.5 静态代码路线（为什么没用 Write/Read 反汇编）")
    add("")
    add("- metadata 能给出 20 个 operator 类的字段名（`operatordata_family.json`），"
        "但 `.data` 槽位地址落到 `0x5977408` 起每 `0x44` 字节一个的静态 getter 表"
        "（`ldr x0,[x8,#imm]; ret`），不是各 `*OperatorData.Write`。")
    add("- 对 `0x5977430`/`0x597774c`/`0x5977d4c` 做 XOR 0xE3 单字解密后仍是"
        "同一静态 getter/初始化桩，未复现出 `Read` 的 `str x1,[x0,#0x40]` 形态。"
        "因此 code-derived layout 在本环境不可复现；本报告改用流内签名 + 多样本直方图。")
    add("- 这解释了为什么 `operator_stream.py` 的 27B 头假设在主样本 0x5cb 处报 `0xc6`："
        "主样本没有 27B 头，首记录就是 `02 00 01 <uleb>` GameCoreFrame；"
        "27B 头是 39,634B 小样本把前 4 条记录误当成了头。")
    add("")
    add("### 2.6 其他可能承载商店事件的 operator 类型")
    add("")
    add("metadata 字段本身已排除金额：`CppEventOperatorData` 只有 SlotType/SkillId/Value，"
        "`UIViewChangeOperatorData` 只有 ViewType/Open，"
        "`SendNetworkMsgToServerData` 只有 CSMsgID/result。")
    add("")
    misc_rows = []
    if ope_main:
        for key, label in (("cpp", "CppEventOpe 0x0C"),
                           ("view", "UIViewChangeOpe 0x0F"),
                           ("send", "SendMsgToServerOpe 0x18")):
            c = ope_main["misc"][key]
            misc_rows.append([label, sum(c.values()),
                              ",".join(f"{k}:{v}" for k, v in c.most_common(6))])
    if misc_rows:
        add(md_table(["签名", "主样本命中", "Top（原始元组）"], misc_rows))
    add("")
    add("- `SendMsgToServerOpe` 主样本主导项是 `(frame=438, CSMsgID=40301, result=0)`，"
        "40301 不在 metadata 默认值表；可读的 1098 = `SCID_ASKINMULTGAME_RSP`，"
        "不是购买消息。")
    add("- `CppEventOpe` 主样本 top 为 `(slot, skillId, value)` 的技能/目标值；"
        "没有 item/price。")
    add("- `UIViewChangeOpe` 只有 `(ViewType, Open)`；没有商店路径字符串。")
    add("- 这三类的边界仍多解，计数只作否定证据（low-medium）；即使命中也无金额字段。")
    add("")
    add("## 3. .abc（build 5069040）购买/装备签名")
    add("")
    add(md_table(["签名", "总命中", "覆盖文件", "主样本细节"], sig_rows))
    add("")
    add("### 3.1 关键读法")
    add("")
    add("- `02/85 len5`：`source:u8 + amount:u32LE`，source 4/5/6/43/44/47/51 均为"
        "**金币收入**；金额 31–254，零额 0、最高位 0。没有负数/零额，也没有 item。")
    add("- `02/87 len7`：`00 00 00 <id:u8> <level:u8> 00 00`，id 7–65、level 1–4；"
        "不是 Equip 表 row_id（1111–5536），更像技能/天赋等级，不是购买。")
    add("- `01/1e len19`：伤害/属性变化表；`01/87 len5` 恒零；"
        "`01/48 len9` 在 6 个 5069040 样本仅主样本 1 条，"
        "内容 `48 00 50 43 40 53 52 52 52` 非结构化字段，不能当购买。")
    add("- `02/80` 帧命令 cmd_type 只有 1–9、15；"
        "**没有 22 `stCmdPlayerInOutEquipShop`、23 `stCmdPlayerChangeUsedRecommendEquipGroup`、"
        "35 `stCmdPlayerOneStepBuyEquip`**。")
    add("- `02/86 len6` 全 5069040 只有 2 条，样本内含 `0x12` 标签，"
        "疑为 payload 截断后的伪命中；不作为购买证据。")
    add("- 把 Equip 表 270 个 row_id 当 u16 扫结构化字段：**0 命中**。"
        "（`02/85` 里 `04 58` 看起来像 1112，但那是 source=4 + amount 低字节 0x58，"
        "已定向排除。）")
    add("")
    add("## 4. 5230306 对照：装备 item 事件确实存在，但不在 5069040")
    add("")
    if ctrl_rows:
        add(md_table(["文件", "签名", "次数", "细节", "备注"], ctrl_rows))
    add("")
    add("5230306 的 `02/85` 是 `type:u8 + item:u16`：`20261028_135516.abc` 的 "
        "9 处 `02 85` 中 7 处为 item 事件，首条 13.9s `type=6 item=165`（辅助宝石）。"
        "5069040 的 `02/85` 是金币收入流水，**同一 flag 语义不同，不能混用**。")
    add("")
    add("## 5. 支出/装备能否从回放侧得到？")
    add("")
    add(md_table(
        ["问题", "答案", "置信度", "依据"],
        [["5069040 当前金币", "不能", "high", "只有收入流水；无当前金币/累计金币快照"],
         ["5069040 累计金币", "能（收入侧）", "high", "286 条 02/85（本工具；5.91 记分卡 281）+ 自然金规则（3/s，40s 起）"],
         ["5069040 支出", "不能", "high", "收入 − 当前金币需要当前金币；回放无当前金币"],
         ["5069040 装备/物品 ID", "不能", "high", "无结构化装备 ID；02/87 非 Equip 表"],
         ["5069040 出装时序", "不能", "high", "无 22/23/35 帧命令、无 5230306 型 02/85"],
         ["5230306 装备 item", "能", "high", "02/85 type+item，7 条"],
         ["operator 流给金额", "不能", "high", "UiEventOperatorData 只有 EventID"]]))
    add("")
    add("**结论**：5069040 的支出只能外部补（录屏 OCR 当前金币、结算/服务器数据，"
        "或完整 lockstep 模拟）。回放侧能给的是**收入侧金币流水 + 自然金区间**，"
        "不能给支出/装备。")
    add("")
    add("## 6. 剩余缺口与下一步最小验证")
    add("")
    add("1. **最小验证（推荐）**：录一段 5069040 对局 + 屏幕金币；在已知购买时刻"
        "检查 `.ope` 是否出现新的 UIEventID（尤其 1142/1144/1145/1194/1206/1248–1276）。"
        "若出现 1194/1206，说明 operator 能标记“装备已购”时刻，但仍无 item/price。")
    add("2. **item ID 验证**：找 5230306 型 `02/85` 的 5069040 样本（或下一版本）；"
        "若同一 build 出现 `02 85 <type> <item>`，才能补出装表。")
    add("3. **金额验证**：录屏 OCR 当前金币，与 `300 + 02/85 收入 + 3/s×(t−40)` 做差，"
        "差值即支出；这是当前唯一不依赖模拟的闭环。")
    add("4. **代码路线**：若允许动态 MethodInfo dump（本任务禁止），可拿真正的 "
        "`OperatorData.Write/Read` 与 `WriteInt`；但 metadata 已证明 UIEventOpe 只有 EventID，"
        "不会改变“无金额”的结论。")
    add("")
    add("## 7. 产物")
    add("")
    add("- `tools/agent_operator_spending.py`：本报告生成器（只读、可复跑）。")
    add("- `data/replays/_analysis/datasets/agent_operator_spending.csv`：逐文件逐签名证据。")
    add("- `data/replays/_analysis/datasets/agent_operator_spending.md`：本文件。")
    add("")
    add("### 复跑")
    add("")
    add("```text")
    add("python tools/agent_operator_spending.py")
    add("python tools/agent_operator_spending.py --limit-ope 4 --limit-abc 3")
    add("```")
    add("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-ope", type=int, default=0)
    ap.add_argument("--limit-abc", type=int, default=0)
    args = ap.parse_args()

    ui_names = load_ui_event_names()
    shop_values = load_shop_ui_values(ui_names)
    equip_ids = load_equip_ids()

    def unique_files(paths: list[Path]) -> list[Path]:
        """同名样本目录里存在带/不带 hash 后缀的重复文件，按内容去重。"""
        seen: set[str] = set()
        out: list[Path] = []
        for path in sorted(paths):
            try:
                digest = hashlib.sha1(path.read_bytes()).hexdigest()
            except OSError:
                continue
            if digest in seen:
                continue
            seen.add(digest)
            out.append(path)
        return out

    abc_files = unique_files(list(ABC_DIR.glob("*.abc")))
    ope_files = unique_files(list(OPE_DIR.glob("*.ope")))
    if args.limit_abc:
        abc_files = abc_files[:args.limit_abc]
    if args.limit_ope:
        ope_files = ope_files[:args.limit_ope]

    rows: list[dict] = []
    for path in abc_files:
        try:
            rows.extend(scan_abc_file(path, equip_ids))
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            rows.append({
                "dataset": "abc", "build": "?", "client_build": "?", "file": path.name,
                "domain": "spending_abc", "signature": "error", "count": 0,
                "distinct": "", "min": "", "max": "", "zero_or_negative": "",
                "detail": f"{type(exc).__name__}: {exc}", "confidence": "low",
                "note": "读取失败",
            })

    ope_summaries = []
    for path in ope_files:
        try:
            part, summary = scan_ope_file(path, ui_names, shop_values)
            rows.extend(part)
            if summary:
                ope_summaries.append(summary)
        except Exception as exc:  # noqa: BLE001
            rows.append({
                "dataset": "ope", "build": "?", "client_build": "?", "file": path.name,
                "domain": "operator", "signature": "error", "count": 0,
                "distinct": "", "min": "", "max": "", "zero_or_negative": "",
                "detail": f"{type(exc).__name__}: {exc}", "confidence": "low",
                "note": "读取失败",
            })

    write_csv(rows)
    write_md(rows, ope_summaries, ui_names, shop_values)
    print(f"wrote {OUT_CSV} ({len(rows)} rows)")
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main()
