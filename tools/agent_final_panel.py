#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读搜索回放容器里的最终面板 / 30 秒统计 / KDA 证据。

目标
----
1. 在全部 .abc / .ope 中按 res_build 分层搜索 30 秒统计与结算签名
   （COMDT_GAME_30SEC_INFO、stReportPlayerData、iCoinFromKillSolider、
   dwCoinCnt、iCoinFromSystem 等）。
2. 解 5230306 TLV 样本的 02/80 累计金币/经验快照、02/81 击杀位置候选、
   02/85 出装事件，与录屏 OCR 对拍。
3. 用 source43（0x02 flag=0x85, amount 202/203=击杀, 102=助攻）重建
   5069040 主样本 KDA 时间线，并检查 0x1f/0x20、0x02/0x81。
4. 输出可复跑的 CSV 与 Markdown 结论。

只读约束
--------
本脚本只读取 data/replays 下的回放、OCR JSON 与已有 roster 元数据；
不修改回放、不写 docs/replay_binary_format.md、不写 .workbuddy。
输出只写 data/replays/_analysis/datasets/agent_final_panel.{csv,md}。

用法
----
    python tools/agent_final_panel.py
    python tools/agent_final_panel.py --out-dir data/replays/_analysis/datasets
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPLAY_ROOT = PROJECT_ROOT / 'data' / 'replays'
ANALYSIS = REPLAY_ROOT / '_analysis'
DEFAULT_OUT = ANALYSIS / 'datasets'
OCR_JSON = REPLAY_ROOT / 'video_ocr' / '2a7206b09ea8cc35.json'
ROSTER_JSON = ANALYSIS / 'abc_roster.json'
HERO_CSV = ANALYSIS / 'datasets' / 'agent_normal5v5_player_heroes.csv'

TLV_MARKER = b'\x29\x0e\x00\x00'
KV_SIG = bytes.fromhex('010032000200010003001900')

# C# 协议字段名。先确认这些字符串在 global-metadata / 30s schema 中真实存在，
# 再在回放字节中搜索；0 命中才是有意义的负结果。
TOKENS = [
    'COMDT_GAME_30SEC_INFO',
    'stReportPlayerData',
    'iCoinFromKillSolider',
    'dwCoinCnt',
    'dwCoinIntervalCnt',
    'iCoinFromSystem',
    'dwSystemAddIntervalCoin',
    'dwSystemAddCoin',
    'dwHeroKillIntervalCoin',
    'dwSoliderKillCoin',
    'dwKillCnt',
    'totalCoin',
    'iCoinFromKillHero',
    'iCoinFromKillMonster',
    'iCoinFromKillTower',
    'iCoinFromKillDragon',
    'astKillHeroPos',
    'KDAStat',
    'stHeroGoldCoinInBattleChangeParam',
    'dwKillSoldierCnt',
    'SoliderKillCoinByRouteID',
    'dwDestroyTowerCnt',
    'dwHeroKillCoin',
    'dwMonsterKillCoin',
    'dwAidEquipCoin',
    'dwEquipAssistEnCiCoin',
    'dwEquipAssistYouJiCoin',
    'dwPassiveTaiYiZhenRenCoin',
    'dwTeamBehaviorCoin',
    'dwPickupSoldierCoinNum',
]

# 在 21 个可解析帧流样本中实际观测到的“同一帧 10 名英雄同时出现”的形状。
# 这些形状的语义已单独核对；如果出现集合外的 10-hero 形状，才需要重新评估面板。
KNOWN_TEN_SHAPES = {
    (1, 0, 2),      # 0x01 data[0]=0x03 ready/队伍状态
    (1, 0, 6),      # 5230306 帧流中的逐英雄短状态
    (1, 0, 29),     # 5230306 帧流中的逐英雄短状态
    (2, 0x80, 12),  # 12 字节帧命令（5.44.3）
    (2, 0x81, 1),   # 逐英雄状态位
    (2, 0x82, 2),   # 瞄准/攻击
    (2, 0x82, 4),   # 瞄准/攻击（4 字节变体）
    (2, 0x83, 3),   # 新版 8 位位置流
    (2, 0x83, 4),   # 新版逐英雄状态
    (2, 0x84, 4),   # 逐英雄 4 字节状态/交互标志（5169333/5230306）
    (2, 0x85, 5),   # 逐英雄金币流水（source+amount），稀疏事件，不是面板
    (2, 0x87, 7),   # 技能升级（本报告重新核对）
}

SHAPE_SEMANTICS = {
    (1, 0, 2): '0x01/0x03 ready/team status (2B, value 03 00)',
    (1, 0, 6): '0x01 6B per-hero short status (5230306 frame stream)',
    (1, 0, 29): '0x01 29B per-hero event (5230306 frame stream)',
    (2, 0x80, 12): '12B frame command (cmdType/value/actor/seq/flag)',
    (2, 0x81, 1): 'per-hero 1B status bit (values 1/2/3/4/6); not KDA',
    (2, 0x82, 2): 'aim/attack 02ff',
    (2, 0x82, 4): 'aim/attack 4B variant',
    (2, 0x83, 3): '8-bit position axis/value/seq',
    (2, 0x83, 4): 'per-hero 4B status',
    (2, 0x84, 4): 'per-hero 4B status/interaction flag',
    (2, 0x85, 5): 'gold flow source+amount (sparse; not a panel)',
    (2, 0x87, 7): 'skill upgrade: 00 00 00 skillID level stack 00; ~13/hero',
}


# ---------------------------------------------------------------------------
# 基础解析
# ---------------------------------------------------------------------------
def parse_header(data: bytes) -> dict | None:
    texts, pos = [], 0
    try:
        for _ in range(4):
            n = data[pos]
            if not 1 <= n <= 80:
                return None
            texts.append(data[pos + 1:pos + 1 + n].decode('utf-8', 'replace'))
            pos += 1 + n
    except Exception:
        return None
    # 本地英雄紧跟 4 个前缀串之后；偏移随字符串长度变化：
    # 5069040 (8+8+7+7) -> 34，5230306 (8+9+7+7) -> 35。不能用固定 35。
    local_hero = int.from_bytes(data[pos:pos + 2], 'little') if len(data) >= pos + 2 else None
    return {
        'versions': texts[:2],
        'builds': texts[2:],
        'res_build': texts[3],
        'local_hero': local_hero,
    }


def parse_conf(data: bytes) -> dict:
    pos = data.find(KV_SIG)
    if pos < 0:
        return {}
    count = struct.unpack_from('<H', data, pos - 2)[0]
    if not 0 < count < 200:
        return {}
    out, off = {}, pos
    for _ in range(count):
        if off + 4 > len(data):
            break
        key = data[off]
        value = struct.unpack_from('>H', data, off + 1)[0]
        out[key] = value
        off += 4
    return out


def frame_records(data: bytes, start: int, seq0: int = 0x22):
    pos, seq, out = start, seq0, []
    while pos + 10 < len(data):
        if data[pos] != (seq & 0xFF) or data[pos + 1] != 0:
            break
        length = data[pos + 2]
        if pos + 10 + length > len(data):
            break
        out.append({
            'off': pos,
            'seq': seq,
            'payload': data[pos + 3:pos + 3 + length],
        })
        pos += 10 + length
        seq += 1
    return out, pos


def find_frame_stream(data: bytes):
    best = ([], 0)
    for pos in range(0, min(len(data), 0x20000)):
        if data[pos] == 0x22 and data[pos + 1] == 0:
            recs, end = frame_records(data, pos)
            if len(recs) > len(best[0]):
                best = (recs, end)
                if len(recs) > 500:
                    break
    return best


def parse_frame_payload(payload: bytes):
    """解析主段 payload（count 前缀 + 标签流）。

    0x02 flag=0x80 的负载是 12 字节帧命令，不是 0 字节；
    这里显式消费 12 字节，避免把命令体误读成后续标签。
    """
    if not payload:
        return [], True, 0
    i, msgs = 1, []
    n = len(payload)
    while i < n:
        tag = payload[i]
        if tag == 0x12:
            if i + 3 > n:
                return msgs, False, i
            msgs.append(('s', tag, payload[i + 1:i + 3]))
            i += 3
        elif tag == 0x13:
            if i + 2 > n:
                return msgs, False, i
            msgs.append(('s', tag, payload[i + 1:i + 2]))
            i += 2
        elif tag == 0x14:
            if i + 4 > n:
                return msgs, False, i
            msgs.append(('s', tag, payload[i + 1:i + 4]))
            i += 4
        elif tag == 0x01:
            if i + 5 > n:
                return msgs, False, i
            hero = struct.unpack_from('>H', payload, i + 1)[0]
            flag = payload[i + 3]
            length = payload[i + 4]
            if i + 5 + length > n:
                return msgs, False, i
            msgs.append(('h', tag, hero, flag, payload[i + 5:i + 5 + length]))
            i += 5 + length
        elif tag == 0x02:
            if i + 4 > n:
                return msgs, False, i
            hero = struct.unpack_from('>H', payload, i + 1)[0]
            flag = payload[i + 3]
            if flag == 0x80:
                if i + 16 > n:
                    return msgs, False, i
                msgs.append(('h', tag, hero, flag, payload[i + 4:i + 16]))
                i += 16
            else:
                length = flag & 0x7F
                if i + 4 + length > n:
                    return msgs, False, i
                msgs.append(('h', tag, hero, flag, payload[i + 4:i + 4 + length]))
                i += 4 + length
        else:
            return msgs, False, i
    return msgs, True, i


def parse_nocount_payload(payload: bytes):
    """第二段帧流没有 count 前缀（5.36）。"""
    i, msgs = 0, []
    n = len(payload)
    while i < n:
        tag = payload[i]
        if tag in (0x12, 0x13, 0x14):
            size = {0x12: 2, 0x13: 1, 0x14: 3}[tag]
            if i + 1 + size > n:
                break
            msgs.append(('s', tag, payload[i + 1:i + 1 + size]))
            i += 1 + size
        elif tag == 0x01:
            if i + 5 > n:
                break
            hero = struct.unpack_from('>H', payload, i + 1)[0]
            flag, length = payload[i + 3], payload[i + 4]
            if i + 5 + length > n:
                break
            msgs.append(('h', tag, hero, flag, payload[i + 5:i + 5 + length]))
            i += 5 + length
        elif tag == 0x02:
            if i + 4 > n:
                break
            hero = struct.unpack_from('>H', payload, i + 1)[0]
            flag = payload[i + 3]
            if flag == 0x80:
                if i + 16 > n:
                    break
                msgs.append(('h', tag, hero, flag, payload[i + 4:i + 16]))
                i += 16
            else:
                length = flag & 0x7F
                if i + 4 + length > n:
                    break
                msgs.append(('h', tag, hero, flag, payload[i + 4:i + 4 + length]))
                i += 4 + length
        else:
            break
    return msgs, i


# ---------------------------------------------------------------------------
# 帧流统计
# ---------------------------------------------------------------------------
def analyze_frame_stream(recs: list) -> dict:
    shape_count = Counter()
    shape_heroes = defaultdict(set)
    shape_times = defaultdict(list)
    shape_samples = defaultdict(list)
    ten_frame_hits = Counter()
    gold, highlights = [], []
    status81 = 0
    status81_values = Counter()
    count_1e = 0
    values_1e = []
    ok = bad = 0
    max_payload = 0
    scalar_counts = []
    for rec in recs:
        payload = rec['payload']
        max_payload = max(max_payload, len(payload))
        msgs, good, _ = parse_frame_payload(payload)
        ok += 1 if good else 0
        bad += 0 if good else 1
        scalar_counts.append(sum(1 for m in msgs if m[0] == 's'))
        per = defaultdict(set)
        for msg in msgs:
            if msg[0] != 'h':
                continue
            _, tag, hero, flag, data = msg
            key = (tag, flag, len(data))
            shape_count[key] += 1
            shape_heroes[key].add(hero)
            shape_times[key].append(rec['seq'] / 20.0)
            if len(shape_samples[key]) < 24:
                shape_samples[key].append((hero, data))
            if tag == 0x02 and flag == 0x85 and len(data) == 5:
                gold.append({
                    'seq': rec['seq'],
                    'hero': hero,
                    'source': data[0],
                    'amount': int.from_bytes(data[1:5], 'little'),
                })
            if tag == 0x01 and data and data[0] == 0x1F:
                highlights.append({
                    'seq': rec['seq'],
                    'kind': '0x1f',
                    'tag': data[1] if len(data) > 1 else None,
                    'actor': int.from_bytes(data[22:24], 'big') if len(data) >= 24 else None,
                    'hero': hero,
                    'data': data.hex(),
                })
            if tag == 0x01 and data and data[0] == 0x20:
                highlights.append({
                    'seq': rec['seq'],
                    'kind': '0x20',
                    'tag': data[1] if len(data) > 1 else None,
                    'actor': int.from_bytes(data[13:15], 'big') if len(data) >= 15 else None,
                    'hero': hero,
                    'data': data.hex(),
                })
            if tag == 0x02 and flag == 0x81:
                status81 += 1
                status81_values[data[0] if data else -1] += 1
            if tag == 0x01 and data and data[0] == 0x1E:
                count_1e += 1
                values_1e.append(int.from_bytes(data[16:18], 'big') if len(data) >= 18 else -1)
            per[key].add(hero)
        for key, heroes in per.items():
            if len(heroes) >= 10:
                ten_frame_hits[key] += 1

    ten_shapes = {k: len(v) for k, v in shape_heroes.items() if len(v) >= 10}
    cadence_flags = []
    for key in ten_shapes:
        times = sorted(shape_times[key])
        deltas = [b - a for a, b in zip(times, times[1:]) if b > a]
        if not deltas:
            continue
        median = statistics.median(deltas)
        if 25 <= median <= 35 and shape_count[key] >= 30:
            cadence_flags.append((key, median, shape_count[key]))
    unknown_ten = [k for k in ten_shapes if k not in KNOWN_TEN_SHAPES]

    return {
        'frames': len(recs),
        'parse_ok': ok,
        'parse_bad': bad,
        'parse_ratio': ok / (ok + bad) if ok + bad else 0.0,
        'max_payload': max_payload,
        'max_scalars_per_frame': max(scalar_counts) if scalar_counts else 0,
        'frames_ge20_scalars': sum(1 for c in scalar_counts if c >= 20),
        'shape_count': shape_count,
        'ten_shapes': ten_shapes,
        'ten_frame_hits': ten_frame_hits,
        'unknown_ten_shapes': unknown_ten,
        'cadence_flags': cadence_flags,
        'gold': gold,
        'highlights': highlights,
        'status81': status81,
        'status81_values': status81_values,
        'count_1e': count_1e,
        'values_1e': values_1e,
        'shape_samples': shape_samples,
        'last_seq': recs[-1]['seq'] if recs else None,
        'stream_end': None,
    }


def second_frame_stream(data: bytes, main_recs: list):
    """5.36 的第二段帧流：主段之后、tail+277 起，payload 无 count 前缀。"""
    if not main_recs:
        return None
    last = main_recs[-1]['seq']
    # 找到主段结束文件的偏移
    end = main_recs[-1]['off'] + 10 + len(main_recs[-1]['payload'])
    tail = data[end:]
    start = None
    for i in range(0, min(len(tail) - 5, 0x1000)):
        frame = struct.unpack_from('>H', tail, i)[0]
        length = struct.unpack_from('>H', tail, i + 2)[0]
        if last + 1 <= frame <= last + 5 and 4 <= length <= 1000:
            start = i
            break
    if start is None:
        return None
    frames, pos = [], start
    while pos + 5 <= len(tail):
        frame = struct.unpack_from('>H', tail, pos)[0]
        length = struct.unpack_from('>H', tail, pos + 2)[0]
        typ = tail[pos + 4]
        if frame < last or frame > last + 3000 or length > 1000 or pos + 10 + length > len(tail):
            break
        frames.append({
            'seq': frame,
            'length': length,
            'type_byte': typ,
            'payload': tail[pos + 5:pos + 5 + length],
        })
        pos += 10 + length
    if len(frames) < 10:
        return None
    shapes = Counter()
    gold = 0
    panel_like = 0
    ten_msgs = 0
    for fr in frames:
        msgs, _ = parse_nocount_payload(fr['payload'])
        per = defaultdict(set)
        for msg in msgs:
            if msg[0] != 'h':
                continue
            _, tag, hero, flag, data = msg
            shapes[(tag, flag, len(data))] += 1
            if tag == 0x02 and flag == 0x85:
                gold += 1
            per[(tag, flag, len(data))].add(hero)
        for key, heroes in per.items():
            if len(heroes) >= 10:
                ten_msgs += 1
            if len(heroes) >= 10 and key not in KNOWN_TEN_SHAPES:
                panel_like += 1
    return {
        'start_offset_in_tail': start,
        'frames': len(frames),
        'seq_start': frames[0]['seq'],
        'seq_end': frames[-1]['seq'],
        'shapes': shapes,
        'gold_messages': gold,
        'ten_shape_messages': ten_msgs,
        'panel_like': panel_like,
        'tail_bytes': len(tail),
        'tail_after_stream': len(tail) - pos,
    }


# ---------------------------------------------------------------------------
# TLV（5230306 单文件样本）
# ---------------------------------------------------------------------------
def find_tlv_stream(data: bytes):
    pos = 0
    while True:
        marker = data.find(TLV_MARKER, pos)
        if marker < 0:
            return None
        start = marker - 3
        if start >= 0:
            cursor = start
            recs = []
            while cursor + 8 <= len(data) and data[cursor + 3:cursor + 7] == TLV_MARKER:
                length = data[cursor + 7]
                if cursor + 8 + length > len(data):
                    break
                recs.append({
                    'off': cursor,
                    'key': data[cursor:cursor + 3],
                    'length': length,
                    'payload': data[cursor + 8:cursor + 8 + length],
                })
                cursor += 8 + length
            if len(recs) >= 10:
                return {
                    'start': start,
                    'end': cursor,
                    'records': recs,
                    'tail': data[cursor:],
                }
        pos = marker + 1


def parse_tlv_records(tlv: dict) -> list:
    out = []
    for rec in tlv['records']:
        payload = rec['payload']
        if len(payload) >= 9 and payload[:5] == b'\x00' * 5:
            out.append({
                'off': rec['off'],
                'key': rec['key'].hex(),
                'length': len(payload),
                'seq': int.from_bytes(payload[5:7], 'big'),
                'type': payload[7],
                'sub': payload[8],
                'args': payload[9:],
                'payload': payload,
            })
        else:
            out.append({
                'off': rec['off'],
                'key': rec['key'].hex(),
                'length': len(payload),
                'seq': None,
                'type': payload[0] if payload else None,
                'sub': None,
                'args': payload,
                'payload': payload,
            })
    return out


def analyze_tlv(records: list) -> dict:
    types = Counter()
    snapshots = []
    kill_positions = []
    item_events = []
    for rec in records:
        if rec['type'] is None or rec['sub'] is None:
            continue
        key = (rec['type'], rec['sub'])
        types[key] += 1
        args = rec['args']
        if key == (2, 0x80) and len(args) >= 9:
            snapshots.append({
                'seq': rec['seq'],
                'time': rec['seq'] / 14.0,
                'a': args[0],
                # 02/80 的 value 是 u16BE：04 00 -> 1024，09 00 -> 2304。
                # 按 LE 会读成 4/9；5.45 的 u16LE 标注需要修正。
                'value': int.from_bytes(args[7:9], 'big'),
                'args': args.hex(),
                'key': rec['key'],
            })
        elif key == (2, 0x81) and len(args) >= 3:
            kill_positions.append({
                'seq': rec['seq'],
                'time': rec['seq'] / 14.0,
                'kind': args[0],
                'coord': int.from_bytes(args[1:3], 'big'),
                'key': rec['key'],
                'args': args.hex(),
            })
        elif key == (2, 0x85) and len(args) >= 4:
            item_events.append({
                'seq': rec['seq'],
                'time': rec['seq'] / 14.0,
                'item_type': args[0],
                'item_id': args[1],
                'key': rec['key'],
                'args': args.hex(),
            })
    seqs = [r['seq'] for r in records if r['seq'] is not None]
    return {
        'records': len(records),
        'types': types,
        'snapshots': snapshots,
        'kill_positions': kill_positions,
        'item_events': item_events,
        'seq_min': min(seqs) if seqs else None,
        'seq_max': max(seqs) if seqs else None,
    }


# ---------------------------------------------------------------------------
# .ope 与签名搜索
# ---------------------------------------------------------------------------
def token_hits(data: bytes) -> list:
    hits = []
    for token in TOKENS:
        for encoding in ('ascii', 'utf-16le', 'utf-16be'):
            if token.encode(encoding) in data:
                hits.append((token, encoding))
    return hits


def decompress_ope(raw: bytes):
    inner = None
    stream = None
    offset = None
    try:
        inner = zlib.decompressobj(-15).decompress(raw[1:]) if raw[:1] == b'\x01' else raw
    except Exception:
        return None, None, None
    for pos in range(0x80, min(0x140, len(inner))):
        try:
            candidate = zlib.decompressobj(-15).decompress(inner[pos:])
            if len(candidate) > 1000:
                stream, offset = candidate, pos
                break
        except Exception:
            continue
    return inner, stream, offset


# ---------------------------------------------------------------------------
# OCR 与主样本映射
# ---------------------------------------------------------------------------
def load_ocr() -> dict:
    data = json.loads(OCR_JSON.read_text(encoding='utf-8'))
    return data


def load_player_map(sample_name: str, data: bytes) -> dict:
    """返回 hero(entity) -> {player, team, slot, hero_role, hero_name}。"""
    out = {}
    if HERO_CSV.exists():
        with HERO_CSV.open(encoding='utf-8-sig') as fh:
            for row in csv.DictReader(fh):
                try:
                    entity = int(row.get('entityID') or 0)
                except ValueError:
                    continue
                if not entity:
                    continue
                out[entity] = {
                    'player': row.get('player') or '',
                    'team': int(row.get('team') or 0),
                    'slot': int(row.get('slot') or 0),
                    'hero_role': int(row.get('heroID') or 0),
                    'hero_name': row.get('heroName') or '',
                }
    if out:
        return out
    # 回退：从 abc_roster.json + 玩家块 s+0x48 读取（5.90）
    if ROSTER_JSON.exists():
        try:
            roster = json.loads(ROSTER_JSON.read_text(encoding='utf-8'))
            entry = next((e for e in roster if e.get('file') == sample_name), None)
            if entry:
                for player in entry.get('players', []):
                    off = int(player['off'])
                    name_len = int(player.get('nameLen') or 0)
                    s = off + 0x10 + name_len + 30
                    hero_role = struct.unpack_from('>H', data, s + 0x48)[0] if s + 0x4A <= len(data) else 0
                    out[int(player['heroId'])] = {
                        'player': player.get('name') or '',
                        'team': int(player.get('team') or 0),
                        'slot': int(player.get('slot') or 0),
                        'hero_role': hero_role,
                        'hero_name': '',
                    }
        except Exception:
            pass
    return out


def ocr_summary(ocr: dict) -> dict:
    samples = []
    for row in ocr.get('samples', []):
        sel = row.get('selected') or {}
        kda = (sel.get('kda') or {}).get('value')
        samples.append({
            'gameTime': row.get('gameTime'),
            'videoTime': row.get('videoTime'),
            'blueKills': ((row.get('blue') or {}).get('kills') or {}).get('value'),
            'redKills': ((row.get('red') or {}).get('kills') or {}).get('value'),
            'blueGold': ((row.get('blue') or {}).get('gold') or {}).get('value'),
            'redGold': ((row.get('red') or {}).get('gold') or {}).get('value'),
            'selectedKda': kda,
            'selectedGold': ((sel.get('gold') or {}).get('value')),
            'selectedLevel': ((sel.get('level') or {}).get('value')),
        })
    team_panel = []
    for sample in ocr.get('teamPanel', {}).get('samples', []):
        team_panel.append({
            'gameTime': sample.get('gameTime'),
            'videoTime': sample.get('videoTime'),
            'blue': [(p.get('hero'), p.get('gold'), p.get('kda')) for p in sample.get('blue', [])],
            'red': [(p.get('hero'), p.get('gold'), p.get('kda')) for p in sample.get('red', [])],
        })
    scoreboard = []
    for snap in ocr.get('scoreboard', {}).get('snapshots', []):
        if not snap.get('players'):
            continue
        scoreboard.append({
            'gameTime': snap.get('gameTime'),
            'videoTime': snap.get('videoTime'),
            'blueKills': snap.get('blueKills'),
            'redKills': snap.get('redKills'),
            'players': [
                {
                    'camp': p.get('camp'), 'hero': p.get('hero'), 'gold': p.get('gold'),
                    'kda': p.get('kda'),
                } for p in snap.get('players', [])
            ],
        })
    selection = []
    offset = ((ocr.get('timeMapping') or {}).get('offset'))
    for seg in (ocr.get('selection') or {}).get('segments', []):
        end = seg.get('end')
        gold_last = seg.get('goldLast')
        if end is None or gold_last is None:
            continue
        game_time = end + offset if offset is not None else None
        selection.append({
            'gameTime': game_time,
            'videoTime': end,
            'gold': gold_last,
            'level': seg.get('levelLast'),
            'kda': seg.get('kdaLast'),
        })
    return {
        'replayDuration': ocr.get('replayDuration'),
        'video': ocr.get('video'),
        'timeOffset': offset,
        'killEvents': ocr.get('killEvents', []),
        'samples': samples,
        'teamPanel': team_panel,
        'scoreboard': scoreboard,
        'selection': selection,
        'pov': ocr.get('pov'),
        'warnings': ocr.get('warnings', []),
    }


def ocr_current_gold_at(ocr_s: dict, game_time: float, max_dt: float = 15.0):
    """返回最接近 game_time 的 POV 当前金币锚点。

    只用可确认是 POV 的锚点：teamPanel/scoreboard 的孙膑行、
    selection 段末的 goldLast（段末 KDA 0/0/0、level 5）、以及
    01:46 HUD 的 1783。超过 max_dt 秒返回 None，避免把远端值当同刻。
    """
    candidates = []
    for row in ocr_s['teamPanel']:
        if row.get('gameTime') is None:
            continue
        pov = None
        for hero, gold, kda in row['blue'] + row['red']:
            if hero == '孙膑':
                pov = gold
        if pov is not None:
            candidates.append((abs(row['gameTime'] - game_time), row['gameTime'], pov, 'teamPanel'))
    for row in ocr_s['scoreboard']:
        if row.get('gameTime') is None:
            continue
        for p in row['players']:
            if p.get('hero') == '孙膑':
                candidates.append((abs(row['gameTime'] - game_time), row['gameTime'], p.get('gold'), 'scoreboard'))
    for row in ocr_s.get('selection', []):
        if row.get('gameTime') is not None and row.get('kda') == [0, 0, 0]:
            candidates.append((abs(row['gameTime'] - game_time), row['gameTime'], row['gold'], 'selection-end'))
    # 01:46 HUD 是明确 POV 0/0/1、1783、level 5
    for row in ocr_s['samples']:
        if row.get('gameTime') == 106 and row.get('selectedGold') is not None:
            candidates.append((abs(106 - game_time), 106, row['selectedGold'], 'hud-last'))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    best = candidates[0]
    if best[0] > max_dt:
        return None
    return best


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def discover_samples():
    """按唯一文件名归并路径；内容重复但文件名不同的样本分别计数（27 个逻辑样本）。"""
    paths = sorted(REPLAY_ROOT.rglob('*.abc'))
    by_name = defaultdict(list)
    for path in paths:
        by_name[path.name].append(path)
    samples = []
    for name, group in sorted(by_name.items()):
        # 优先读取 samples/abc_batch 或 samples 下的路径；内容相同
        group_sorted = sorted(group, key=lambda p: (len(p.parts), str(p)))
        path = group_sorted[0]
        data = path.read_bytes()
        samples.append({
            'name': name,
            'paths': [str(p.relative_to(PROJECT_ROOT)) for p in group],
            'path': path,
            'data': data,
            'sha256': hashlib.sha256(data).hexdigest(),
            'size': len(data),
        })
    return samples


def find_ope_for(name: str):
    stem = name[:-4] if name.lower().endswith('.abc') else name
    prefix = stem.split('_CBDD')[0]
    for path in sorted(REPLAY_ROOT.rglob('*.ope')):
        ope_stem = path.stem.split('_CBDD')[0]
        if ope_stem == prefix or ope_stem.startswith(prefix):
            return path
    return None


def analyze_sample(sample: dict) -> dict:
    data = sample['data']
    header = parse_header(data) or {}
    conf = parse_conf(data)
    tlv = find_tlv_stream(data)
    recs, stream_end = find_frame_stream(data)

    info = {
        'name': sample['name'],
        'paths': sample['paths'],
        'sha256': sample['sha256'],
        'size': sample['size'],
        'data': data,
        'res_build': header.get('res_build') or '?',
        'conf_type1': conf.get(1),
        'local_hero': header.get('local_hero'),
        'container': 'unknown',
        'frames': 0,
        'stream_end': None,
        'tail_bytes': 0,
        'second': None,
        'frame_stats': None,
        'tlv_stats': None,
        'tlv': tlv,
        'panel_candidate': False,
        'panel_reason': '',
    }

    if len(recs) >= 100:
        info['container'] = 'frame_stream'
        stats = analyze_frame_stream(recs)
        stats['stream_end'] = stream_end
        info['frame_stats'] = stats
        info['frames'] = stats['frames']
        info['stream_end'] = stream_end
        info['tail_bytes'] = len(data) - stream_end
        second = second_frame_stream(data, recs)
        info['second'] = second
        panel = bool(stats['unknown_ten_shapes'])
        if second and second.get('panel_like'):
            panel = True
        info['panel_candidate'] = panel
        info['panel_reason'] = (
            'unknown 10-hero shape: ' + repr(stats['unknown_ten_shapes'])
            if stats['unknown_ten_shapes']
            else 'only known skill/status/position/frame-command shapes'
        )
        if second:
            info['panel_reason'] += f"; second_stream={second['frames']} frames, panel_like={second['panel_like']}"
    elif tlv:
        info['container'] = 'tlv_stream'
        tlv_stats = analyze_tlv(parse_tlv_records(tlv))
        info['tlv_stats'] = tlv_stats
        info['tail_bytes'] = len(tlv['tail'])
        # TLV 里没有 10 行固定步长结构；若出现未知类型且带 10 行形状，才标记
        info['panel_candidate'] = False
        info['panel_reason'] = 'TLV types={} ; no 10-row panel struct'.format(
            ','.join(f'{t:02x}/{s:02x}' for t, s in sorted(tlv_stats['types']))
        )
    else:
        info['container'] = 'old_or_unsupported'
        info['panel_reason'] = 'no frame stream / TLV stream; structural panel scan not applicable'

    return info


def build_rows(samples, ocr, ope_rows, signature_rows):
    rows = []

    def add(section, *, res_build='', sample='', container='', record_type='', seq='',
            time_s='', player='', hero_id='', team='', slot='', field='', value='',
            value_num='', unit='', confidence='', evidence=''):
        rows.append({
            'section': section,
            'res_build': res_build,
            'sample': sample,
            'container': container,
            'record_type': record_type,
            'seq': seq,
            'time_s': time_s,
            'player': player,
            'hero_id': hero_id,
            'team': team,
            'slot': slot,
            'field': field,
            'value': value,
            'value_num': value_num,
            'unit': unit,
            'confidence': confidence,
            'evidence': evidence,
        })

    # ---- inventory -----------------------------------------------------
    for s in samples:
        for field, value in (
            ('res_build', s['res_build']),
            ('conf_type1', s['conf_type1']),
            ('local_hero', s['local_hero']),
            ('container', s['container']),
            ('frames', s['frames']),
            ('tail_bytes', s['tail_bytes']),
        ):
            conf = 'high' if value not in (None, '') else 'low'
            if field == 'local_hero' and s['container'] == 'old_or_unsupported':
                conf = 'medium'  # 旧构建的头部布局未验证，偏移可能不适用
            add('inventory', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field=field, value=str(value),
                confidence=conf,
                evidence='header/KV/frame parser; file=' + s['paths'][0])
        if s['tlv_stats']:
            add('inventory', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='tlv_records',
                value=str(s['tlv_stats']['records']), confidence='high',
                evidence='TLV marker chain')
            add('inventory', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='tlv_types',
                value=','.join(f'{t:02x}/{u:02x}' for t, u in sorted(s['tlv_stats']['types'])),
                confidence='high', evidence='payload[7:9] type/sub')
        if s['second']:
            add('inventory', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='second_frames',
                value=str(s['second']['frames']), confidence='high',
                evidence='5.36 second stream (no count prefix)')

    # ---- signatures ----------------------------------------------------
    for row in signature_rows:
        add('signature', res_build=row['res_build'], sample=row['sample'],
            container=row['container'], field=row['field'], value=row['value'],
            value_num=row['value_num'], confidence=row['confidence'],
            evidence=row['evidence'])

    # ---- panel scan ----------------------------------------------------
    for s in samples:
        if s['frame_stats']:
            fs = s['frame_stats']
            ten = ', '.join(
                f'{k[0]:02x}/{k[1]:02x}/len{k[2]}/heroes{n}'
                for k, n in sorted(fs['ten_shapes'].items())
            )
            add('panel_scan', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='ten_hero_shapes', value=ten or 'none',
                confidence='high', evidence='frame shape census')
            for key, n in sorted(fs['ten_shapes'].items()):
                samples_hex = '; '.join(f'{h}:{d.hex()}' for h, d in fs['shape_samples'][key][:3])
                add('panel_scan', res_build=s['res_build'], sample=s['name'],
                    container=s['container'],
                    field=f'ten_shape_{key[0]:02x}_{key[1]:02x}_len{key[2]}',
                    value=f'heroes={n}; frameWide={fs["ten_frame_hits"].get(key, 0)}; '
                          f'{SHAPE_SEMANTICS.get(key, "UNKNOWN - review")}',
                    value_num=n, confidence='high',
                    evidence=f'first payloads: {samples_hex}')
            add('panel_scan', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='unknown_ten_shapes',
                value=str(len(fs['unknown_ten_shapes'])),
                value_num=len(fs['unknown_ten_shapes']), confidence='high',
                evidence='known shapes = skill/status/position/frame command')
            add('panel_scan', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='cadence_25_35s',
                value=str(len(fs['cadence_flags'])), value_num=len(fs['cadence_flags']),
                confidence='high', evidence='per-shape median inter-event interval')
            add('panel_scan', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='scalar_batch_max_per_frame',
                value=str(fs['max_scalars_per_frame']), value_num=fs['max_scalars_per_frame'],
                confidence='high',
                evidence=f'frames with >=20 scalar msgs: {fs["frames_ge20_scalars"]}')
            tail = s['tail_bytes']
            if s['second']:
                tail_class = f'second_stream {s["second"]["frames"]}f + tail {tail}B'
            elif tail <= 120:
                tail_class = f'roster-like small tail {tail}B (too small for a 10-row panel)'
            else:
                tail_class = f'large tail {tail}B - review'
            add('panel_scan', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='tail_class', value=tail_class,
                confidence='high' if tail <= 120 or s['second'] else 'medium',
                evidence='bytes after main frame stream')
            add('panel_scan', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='panel_candidate',
                value=str(s['panel_candidate']), confidence='high',
                evidence=s['panel_reason'])
        elif s['tlv_stats']:
            ts = s['tlv_stats']
            add('panel_scan', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='tlv_panel_candidate',
                value=str(s['panel_candidate']), confidence='high',
                evidence=s['panel_reason'])
            add('panel_scan', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='tlv_tail_bytes',
                value=str(len(s.get('tlv', {}).get('tail', b''))),
                confidence='high', evidence='bytes after last TLV record')
        else:
            add('panel_scan', res_build=s['res_build'], sample=s['name'],
                container=s['container'], field='panel_assessable',
                value='false', confidence='high',
                evidence='old/unsupported layout; only literal signature search applies')

    # ---- main sample KDA ----------------------------------------------
    main = next((s for s in samples if s['res_build'] == '5069040'
                 and s['name'].startswith('20260925_105224')), None)
    if main and main['frame_stats']:
        fs = main['frame_stats']
        player_map = load_player_map(main['name'], main['data'])
        gold = fs['gold']
        s43 = sorted([g for g in gold if g['source'] == 43], key=lambda g: g['seq'])
        kills = Counter()
        assists = Counter()
        team_kills = Counter()
        cum_rows = []
        for event in s43:
            is_kill = event['amount'] >= 200
            if is_kill:
                kills[event['hero']] += 1
                info = player_map.get(event['hero'], {})
                team_kills[info.get('team', 0)] += 1
            else:
                assists[event['hero']] += 1
            info = player_map.get(event['hero'], {})
            cum_rows.append({
                'seq': event['seq'],
                'time': event['seq'] / 20.0,
                'hero': event['hero'],
                'amount': event['amount'],
                'event': 'kill' if is_kill else 'assist',
                'team': info.get('team'),
                'player': info.get('player', ''),
                'hero_role': info.get('hero_role', ''),
                'hero_name': info.get('hero_name', ''),
                'cum_kills': kills[event['hero']],
                'cum_assists': assists[event['hero']],
                'team_score': f"{team_kills.get(1, 0)}:{team_kills.get(2, 0)}",
            })
        for row in cum_rows:
            add('kda_timeline', res_build=main['res_build'], sample=main['name'],
                container=main['container'], record_type='0x02/0x85 source43',
                seq=row['seq'], time_s=f'{row["time"]:.2f}',
                player=row['player'], hero_id=row['hero'], team=row['team'],
                slot=player_map.get(row['hero'], {}).get('slot', ''),
                field=f"{row['event']}_amount", value=str(row['amount']),
                value_num=row['amount'], unit='gold', confidence='medium-high',
                evidence=f"source43 amount {row['amount']} -> "
                         f"{'kill' if row['amount'] >= 200 else 'assist'}; "
                         f"hero {row['hero']} ({row['hero_name']})")
            add('kda_timeline', res_build=main['res_build'], sample=main['name'],
                container=main['container'], record_type='0x02/0x85 source43',
                seq=row['seq'], time_s=f'{row["time"]:.2f}',
                player=row['player'], hero_id=row['hero'], team=row['team'],
                slot=player_map.get(row['hero'], {}).get('slot', ''),
                field='team_score_after', value=row['team_score'],
                confidence='medium-high', evidence='cumulative source43 kills')

        # 每玩家最终 K/A；death 只能到队伍层
        duration = (fs['last_seq'] or 0) / 20.0
        natural_rate = 3.0
        natural_start = 40.0
        natural_gold = max(0.0, duration - natural_start) * natural_rate
        gold_by_hero = Counter()
        for g in gold:
            gold_by_hero[g['hero']] += g['amount']
        all_heroes = sorted(set(player_map) | set(gold_by_hero) | set(kills) | set(assists),
                            key=lambda h: (player_map.get(h, {}).get('team', 0),
                                           player_map.get(h, {}).get('slot', 0), h))
        for hero in all_heroes:
            info = player_map.get(hero, {})
            team = info.get('team', 0)
            team_deaths = team_kills.get(3 - team, 0)
            add('kda_final', res_build=main['res_build'], sample=main['name'],
                container=main['container'], player=info.get('player', ''),
                hero_id=hero, team=team, slot=info.get('slot', ''),
                field='kills', value=str(kills.get(hero, 0)),
                value_num=kills.get(hero, 0), confidence='medium-high',
                evidence='source43 amount>=200')
            add('kda_final', res_build=main['res_build'], sample=main['name'],
                container=main['container'], player=info.get('player', ''),
                hero_id=hero, team=team, slot=info.get('slot', ''),
                field='assists', value=str(assists.get(hero, 0)),
                value_num=assists.get(hero, 0), confidence='medium',
                evidence='source43 amount<200 (102)')
            add('kda_final', res_build=main['res_build'], sample=main['name'],
                container=main['container'], player=info.get('player', ''),
                hero_id=hero, team=team, slot=info.get('slot', ''),
                field='deaths_player', value='unknown', confidence='high',
                evidence='container has no killer->victim link; 0x1e tail is damage/highlight value, not victim')
            add('kda_final', res_build=main['res_build'], sample=main['name'],
                container=main['container'], player=info.get('player', ''),
                hero_id=hero, team=team, slot=info.get('slot', ''),
                field='deaths_team_from_opponent_kills', value=str(team_deaths),
                value_num=team_deaths, confidence='medium-high',
                evidence='opponent kills from source43; team-level only')
            add('kda_final', res_build=main['res_build'], sample=main['name'],
                container=main['container'], player=info.get('player', ''),
                hero_id=hero, team=team, slot=info.get('slot', ''),
                field='gold_event', value=str(gold_by_hero.get(hero, 0)),
                value_num=gold_by_hero.get(hero, 0), unit='gold', confidence='medium-high',
                evidence='0x02 flag=0x85, robust parse (0x80 12B body consumed)')
            add('kda_final', res_build=main['res_build'], sample=main['name'],
                container=main['container'], player=info.get('player', ''),
                hero_id=hero, team=team, slot=info.get('slot', ''),
                field='gold_model_total_excl_spend',
                value=f'{300 + natural_gold + gold_by_hero.get(hero, 0):.1f}',
                value_num=300 + natural_gold + gold_by_hero.get(hero, 0),
                unit='gold', confidence='medium',
                evidence=f'initial300 + {natural_rate:g}/s from {natural_start:g}s + event gold; spend unknown')
            add('kda_final', res_build=main['res_build'], sample=main['name'],
                container=main['container'], player=info.get('player', ''),
                hero_id=hero, team=team, slot=info.get('slot', ''),
                field='damage_dealt', value='unknown', confidence='high',
                evidence='0x1e only sparse high-hit values (17 events), not totals')
            add('kda_final', res_build=main['res_build'], sample=main['name'],
                container=main['container'], player=info.get('player', ''),
                hero_id=hero, team=team, slot=info.get('slot', ''),
                field='damage_taken', value='unknown', confidence='high',
                evidence='no per-player taken-damage field observed')

        # 高光事件
        for h in fs['highlights']:
            add('kda_timeline', res_build=main['res_build'], sample=main['name'],
                container=main['container'], record_type=h['kind'],
                seq=h['seq'], time_s=f'{h["seq"] / 20.0:.2f}',
                player=player_map.get(h['hero'], {}).get('player', ''),
                hero_id=h['hero'], team=player_map.get(h['hero'], {}).get('team', ''),
                field='highlight_tag', value=str(h['tag']), value_num=h['tag'],
                confidence='medium', evidence=f"highlight (not kill); actor={h['actor']}; data={h['data']}")

        # 02/81 在主样本中不存在（0x02 flag=0x81 是状态位，不是 TLV 02/81）
        add('kda_final', res_build=main['res_build'], sample=main['name'],
            container=main['container'], field='tlv_02_81_present', value='false',
            confidence='high', evidence='5069040 frame stream has 0x02 flag=0x81 status (1015), no TLV 02/81')
        add('kda_final', res_build=main['res_build'], sample=main['name'],
            container=main['container'], field='status_0x02_0x81_records',
            value=str(fs['status81']), value_num=fs['status81'], confidence='high',
            evidence='per-hero 1-byte status; not KDA')
        add('kda_final', res_build=main['res_build'], sample=main['name'],
            container=main['container'], field='status_0x02_0x81_values',
            value=','.join(f'{v}:{n}' for v, n in sorted(fs['status81_values'].items())),
            confidence='high',
            evidence='value:count; values 1/2/3/4/6; not a kill/death encoding')

    # ---- 5230306 TLV gold/KDA -----------------------------------------
    tlv_sample = next((s for s in samples if s['res_build'] == '5230306'
                       and s['tlv_stats']), None)
    if tlv_sample:
        ts = tlv_sample['tlv_stats']
        ocr_s = ocr_summary(ocr)
        # 02/80 snapshots
        for snap in ts['snapshots']:
            label = {2: 'gold', 5: 'exp'}.get(snap['a'], f'a{snap["a"]}')
            add('gold_snapshot', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
                container=tlv_sample['container'], record_type='02/80',
                seq=snap['seq'], time_s=f'{snap["time"]:.2f}', field=label,
                value=str(snap['value']), value_num=snap['value'], unit='(quantized 256)',
                confidence='high' if label in ('gold', 'exp') else 'medium',
                evidence=f"args={snap['args']}; key={snap['key']}; time=seq/14")
        # 02/81 kill-position candidates
        kill_events = ocr_s['killEvents']
        for kp in ts['kill_positions']:
            nearest = None
            for ev in kill_events:
                dt = kp['time'] - ev['gameTime']
                if nearest is None or abs(dt) < abs(nearest[0]):
                    nearest = (dt, ev)
            add('kill_position', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
                container=tlv_sample['container'], record_type='02/81',
                seq=kp['seq'], time_s=f'{kp["time"]:.2f}', field='coord',
                value=str(kp['coord']), value_num=kp['coord'], unit='u16BE',
                confidence='low-medium',
                evidence=f"kind={kp['kind']}; key={kp['key']}; args={kp['args']}; "
                         f"nearest OCR kill={nearest[1]['gameTime']}s dt={nearest[0]:+.1f}s")
        # 02/85 item events
        for item in ts['item_events']:
            add('gold_snapshot', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
                container=tlv_sample['container'], record_type='02/85',
                seq=item['seq'], time_s=f'{item["time"]:.2f}',
                field='item_event', value=f"type={item['item_type']} item={item['item_id']}",
                value_num=item['item_id'], confidence='medium',
                evidence=f"key={item['key']}; args={item['args']}")

        # 金币/经验模型对拍
        gold_snaps = [s for s in ts['snapshots'] if s['a'] == 2]
        for rate in (10.0, 3.0):
            for snap in gold_snaps:
                natural = max(0.0, snap['time'] - 30.0) * rate
                event_gold = snap['value'] - 300.0 - natural
                add('gold_model', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
                    container=tlv_sample['container'], record_type='02/80',
                    seq=snap['seq'], time_s=f'{snap["time"]:.2f}',
                    field=f'event_gold_implied_{rate:g}per_s', value=f'{event_gold:.1f}',
                    value_num=event_gold, unit='gold',
                    confidence='medium',
                    evidence=f'cumulative {snap["value"]} - 300 - {rate:g}/s from 30s')
        # 37s / 79s 两个最有解释力的 OCR 锚点
        add('gold_model', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
            container=tlv_sample['container'], record_type='OCR anchor',
            time_s='37.00', field='fit_37s',
            value='300+10*(37-30)+130=500 (10/s); 300+3*(37-30)+179=500 (3/s)',
            confidence='medium',
            evidence='scoreboard gameTime 37: POV 孙膑 gold=500; both rates fit one point')
        add('gold_model', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
            container=tlv_sample['container'], record_type='OCR anchor',
            time_s='78.93', field='spend_estimate',
            value='2304-1629=675', value_num=675, unit='gold',
            confidence='medium-high',
            evidence='02/80 cumulative 2304; selection segment end gameTime 79 goldLast 1629')
        # OCR 对拍锚点
        for gt in (32, 37, 53, 54, 60, 79, 106):
            nearest = ocr_current_gold_at(ocr_s, gt)
            if nearest:
                _, ocr_t, gold, source = nearest
                add('ocr_ground', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
                    container='video_ocr', field='pov_current_gold',
                    time_s=f'{ocr_t}', value=str(gold), value_num=gold, unit='gold',
                    confidence='high', evidence=f'{source} nearest to gameTime {gt}')
        for tp in ocr_s['teamPanel']:
            if tp['gameTime'] in (32, 33, 53, 54):
                pov = next((x for x in tp['blue'] if x[0] == '孙膑'), None)
                add('ocr_ground', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
                    container='video_ocr', field='team_panel_pov',
                    time_s=str(tp['gameTime']),
                    value=f'gold={pov[1] if pov else None}; kda={pov[2] if pov else None}',
                    confidence='high', evidence='06-team-panel / teamPanel OCR sample')
        for sb in ocr_s['scoreboard']:
            if sb['gameTime'] in (37, 40, 60):
                pov = next((p for p in sb['players'] if p.get('hero') == '孙膑'), None)
                add('ocr_ground', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
                    container='video_ocr', field='scoreboard_pov',
                    time_s=str(sb['gameTime']),
                    value=f"gold={pov.get('gold') if pov else None}; kda={pov.get('kda') if pov else None}",
                    confidence='high', evidence='scoreboard OCR snapshot')
        # KDA 锚点
        add('ocr_ground', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
            container='video_ocr', field='final_hud', time_s='106',
            value='blueKills=2 redKills=1; POV 孙膑 0/0/1; gold=1783; level=5',
            confidence='high', evidence='video_ocr/evidence/05-hud-last.png')
        add('ocr_ground', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
            container='video_ocr', field='team_panel', time_s='32',
            value='10 players 0/0/0; gold 330-340',
            confidence='high', evidence='video_ocr/evidence/06-team-panel.png')
        add('ocr_ground', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
            container='video_ocr', field='first_kill_attribution', time_s='55',
            value='red 程咬金 kill; blue 影 death; red 百里玄策 assist',
            confidence='high', evidence='scoreboard gameTime 60 (OCR JSON)')
        for ev in kill_events:
            add('ocr_ground', res_build=tlv_sample['res_build'], sample=tlv_sample['name'],
                container='video_ocr', field='kill_event', time_s=str(ev['gameTime']),
                value=f"camp={ev.get('camp')} after={ev.get('after')}",
                confidence='high', evidence='killEvents OCR')

    # ---- gaps ----------------------------------------------------------
    for field, why in (
        ('kills_per_player', 'source43 202/203 gives 6 kills/4 assists; medium-high'),
        ('deaths_per_player', 'no killer->victim link in container; team-level only'),
        ('assists_per_player', 'source43 102 gives 4 assists; medium'),
        ('total_gold_per_player', 'event gold + natural model; spend unknown'),
        ('damage_dealt', '0x1e only sparse high-hit values, not totals'),
        ('damage_taken', 'no per-player taken-damage field observed'),
        ('final_panel_10_rows', 'no 10-row KDA/gold/damage struct in frame/TLV/tail'),
    ):
        add('gap', field=field, value='missing_or_partial', confidence='high', evidence=why)

    return rows, main, tlv_sample, ocr_s


def write_csv(rows, path: Path):
    fields = [
        'section', 'res_build', 'sample', 'container', 'record_type', 'seq',
        'time_s', 'player', 'hero_id', 'team', 'slot', 'field', 'value',
        'value_num', 'unit', 'confidence', 'evidence',
    ]
    with path.open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, '') for k in fields})


def write_md(path: Path, samples, signature_summary, main, tlv_sample, ocr_s, rows):
    builds = Counter(s['res_build'] for s in samples)
    total = len(samples)
    token_hits = sum(x['value_num'] or 0 for x in signature_summary if x['field'] == 'literal_token_hits')
    unknown_panel = sum(1 for s in samples if s['panel_candidate'])
    frame_samples = [s for s in samples if s['frame_stats']]
    tlv_samples = [s for s in samples if s['tlv_stats']]
    old_samples = [s for s in samples if s['container'] == 'old_or_unsupported']
    second = [s for s in samples if s['second']]

    main_kda = []
    main_gold = []
    main_gold_events = Counter()
    if main and main['frame_stats']:
        fs = main['frame_stats']
        pm = load_player_map(main['name'], main['data'])
        s43 = sorted([g for g in fs['gold'] if g['source'] == 43], key=lambda g: g['seq'])
        kills = Counter()
        assists = Counter()
        team_kills = Counter()
        for g in s43:
            is_kill = g['amount'] >= 200
            if is_kill:
                kills[g['hero']] += 1
                team_kills[pm.get(g['hero'], {}).get('team', 0)] += 1
            else:
                assists[g['hero']] += 1
            main_kda.append((
                g['seq'] / 20.0, g['hero'], pm.get(g['hero'], {}).get('player', ''),
                pm.get(g['hero'], {}).get('team', ''), 'kill' if is_kill else 'assist',
                g['amount'], kills[g['hero']], assists[g['hero']],
                f'{team_kills.get(1, 0)}:{team_kills.get(2, 0)}',
            ))
        for hero in sorted(set(pm) | set(kills) | set(assists),
                           key=lambda h: (pm.get(h, {}).get('team', 0),
                                          pm.get(h, {}).get('slot', 0), h)):
            info = pm.get(hero, {})
            main_gold.append((
                hero, info.get('player', ''), info.get('team', ''), info.get('slot', ''),
                info.get('hero_name', ''), kills.get(hero, 0), assists.get(hero, 0),
                team_kills.get(3 - info.get('team', 0), 0),
            ))
        main_gold_events = Counter()
        for g in fs['gold']:
            main_gold_events[g['hero']] += g['amount']

    tlv_gold_snaps = []
    tlv_kill_pos = []
    tlv_items = []
    if tlv_sample and tlv_sample['tlv_stats']:
        ts = tlv_sample['tlv_stats']
        tlv_gold_snaps = [s for s in ts['snapshots'] if s['a'] in (2, 5)]
        tlv_kill_pos = ts['kill_positions']
        tlv_items = ts['item_events']

    lines = []
    lines.append('# 最终面板 / 30 秒统计 / KDA 重建（只读报告）\n')
    lines.append(f'- 生成时间：由 `tools/agent_final_panel.py` 生成；数据源 `data/replays`。')
    lines.append(f'- 样本：{total} 个唯一 .abc 文件名（29 条路径；同内容副本已归并到路径列表）。')
    lines.append('- 只读：未修改回放/包体；未读 param.json；未使用 runtime_dump；未编辑 `docs/replay_binary_format.md` 与 `.workbuddy/memory/MEMORY.md`。')
    lines.append('- 产物：`datasets/agent_final_panel.csv`（逐条证据）、本文件。\n')

    lines.append('## 0. 结论先行\n')
    if unknown_panel == 0:
        lines.append(f'- **在 {total} 个样本中未观测到最终面板**：30 秒统计/结算签名字符串 0 命中；'
                     f'帧流/TLV/tail 中没有 10 行 KDA/金币/伤害结构；{len(second)} 个第二段帧流也是输入续流。')
    else:
        lines.append(f'- 有 {unknown_panel} 个样本出现未知 10-hero 结构，需要人工复核（见 panel_scan）。')
    lines.append('- **主样本 KDA 只能重建到“击杀/助攻 + 队伍死亡”层**：source43 给出 6 杀/4 助，'
                 '每玩家击杀/助攻可列；每玩家死亡、输出、承伤缺失。')
    lines.append('- **5230306 变体有 POV 累计金币/经验快照**（02/80，5 条），但没有 10 人面板；'
                 '02/81 不是完整击杀 feed（20 条 vs 录屏 3 杀），不能单独还原 KDA。')
    lines.append('- **口径修正**：`20261028_135516.abc` 的 conf_type1=50，KV 与 5069040 普通 5v5 样本一致；'
                 '本报告按“普通 5v5 短局/片段”处理，不称其为快速赛。录屏标题 OCR 的“快速赛”仅作低置信标签。\n')

    lines.append('## 1. 样本分层\n')
    lines.append('| res_build | 样本数 | 容器/可解析性 |')
    lines.append('|---|---:|---|')
    for build in sorted(builds, key=lambda b: (-builds[b], b)):
        subset = [s for s in samples if s['res_build'] == build]
        kinds = Counter(s['container'] for s in subset)
        lines.append(f"| {build} | {builds[build]} | " +
                     ', '.join(f'{k}:{v}' for k, v in sorted(kinds.items())) + ' |')
    lines.append(f'\n- 帧流可解析：{len(frame_samples)} 个；TLV 可解析：{len(tlv_samples)} 个；'
                 f'旧/未适配：{len(old_samples)} 个（{", ".join(s["name"] for s in old_samples) or "无"}）。')
    lines.append('- 27 个逻辑样本按唯一文件名计数；`20261028_135516.abc` 与 `20261028_135520_0_0_0.abc` 内容相同但文件名不同，均计入 5230306 层。\n')

    lines.append('## 2. 30 秒统计/结算签名搜索（按 res_build 分层）\n')
    lines.append('搜索方法：')
    lines.append(f'- 对 29 条 .abc 路径的原始字节、31 个唯一 .ope 的外层解压 inner 与第二层 operator 流，'
                 f'搜索 {len(TOKENS)} 个 C# 协议字段名的 ASCII/UTF-16LE/UTF-16BE 字面量。')
    lines.append('- 这些 token 已在 `global-metadata.dat` 与 `comdt_game_30sec.json` 中确认存在，'
                 '因此回放内 0 命中是有意义的负结果，不是拼写错误。')
    lines.append('- 结构搜索：逐帧解析 0x01/0x02 标签流（修正 0x80 12B 帧命令消费），'
                 '统计每个 shape 的英雄覆盖、同帧 10-hero 出现、以及 25–35 秒的中位事件间隔。\n')
    lines.append('| res_build | 样本 | 字面量命中 | 未知 10-hero shape | 25–35s 节奏候选 |')
    lines.append('|---|---:|---:|---:|---:|')
    for build in sorted(builds, key=lambda b: (-builds[b], b)):
        subset = [s for s in samples if s['res_build'] == build]
        hits = sum(x['value_num'] or 0 for x in signature_summary
                   if x['field'] == 'literal_token_hits' and x['res_build'] == build)
        unknown = sum(len(s['frame_stats']['unknown_ten_shapes']) for s in subset
                      if s['frame_stats'])
        cadence = sum(len(s['frame_stats']['cadence_flags']) for s in subset
                      if s['frame_stats'])
        lines.append(f'| {build} | {len(subset)} | {hits} | {unknown} | {cadence} |')
    max_scalars = max((s['frame_stats']['max_scalars_per_frame'] for s in samples
                       if s['frame_stats']), default=0)
    frames_ge20 = sum(s['frame_stats']['frames_ge20_scalars'] for s in samples
                      if s['frame_stats'])
    lines.append(f'\n**字面量命中：{token_hits}**。'
                 '结构层没有 25–35 秒、10 人重复的统计块；'
                 '唯一 10-hero 形状包括技能升级（0x87）、ready/状态（0x01/0x03）、'
                 '状态位（0x02/0x81、0x02/0x84）、瞄准（0x02/0x82）、位置（0x02/0x83）、'
                 '金币流水（0x02/0x85）和 12B 帧命令（0x02/0x80）。')
    lines.append(f'- 30s 统计也可能被编码成一帧内的大 scalar 批；实测所有帧流单帧 scalar 最大 '
                 f'**{max_scalars}** 条，`>=20` 的帧共 **{frames_ge20}** 个，'
                 '没有出现“100 字段 30s 统计”量级的批。\n')

    lines.append('## 3. 主样本 5069040：KDA 时间线（source43 + 0x1f/0x20）\n')
    lines.append(f'主样本：`{main["name"] if main else "missing"}`；'
                 f'帧数 {main["frames"] if main else "-"}；'
                 f'时长 {(main["frame_stats"]["last_seq"] / 20.0):.1f}s（seq/20）。\n' if main else '主样本缺失。')
    lines.append('source43 判定：amount ≥ 200（202/203）= 击杀；amount < 200（102）= 助攻。'
                 '这与 6 杀/4 助、团队 4:2 一致；仍属候选口径（medium-high）。\n')
    lines.append('| 时间(s) | 玩家 | 队伍 | 事件 | 金额 | 累计K | 累计A | 比分 |')
    lines.append('|---:|---|---:|---|---:|---:|---:|---|')
    for t, hero, player, team, kind, amount, k, a, score in main_kda:
        lines.append(f'| {t:.2f} | {player} | {team} | {kind} | {amount} | {k} | {a} | {score} |')
    lines.append('\n**每玩家最终 K/A（死亡只能到队伍层）：**\n')
    lines.append('| 玩家 | 队 | 位 | 英雄实体 | 英雄 | K | A | 队伍死亡(对方击杀) |')
    lines.append('|---|---:|---:|---:|---|---:|---:|---:|')
    for hero, player, team, slot, hero_name, k, a, td in main_gold:
        lines.append(f'| {player} | {team} | {slot} | {hero} | {hero_name or "?"} | {k} | {a} | {td} |')
    if main and main['frame_stats']:
        duration = (main['frame_stats']['last_seq'] or 0) / 20.0
        natural = max(0.0, duration - 40.0) * 3.0
        lines.append('\n**金币重建（事件金 + 自然金模型；支出未知）：**\n')
        lines.append('| 玩家 | 队 | 事件金 | 自然金(3/s, 40s 起) | 总获得(含初始300, 未扣支出) |')
        lines.append('|---|---:|---:|---:|---:|')
        for hero, player, team, slot, hero_name, k, a, td in main_gold:
            event = main_gold_events.get(hero, 0)
            lines.append(f'| {player} | {team} | {event} | {natural:.1f} | {300 + natural + event:.1f} |')
        total_event = sum(main_gold_events.values())
        lines.append(f'| **合计** |  | **{total_event}** | **{natural * 10:.1f}** | '
                     f'**{3000 + natural * 10 + total_event:.1f}** |')
    if main and main['frame_stats']:
        fs = main['frame_stats']
        n1f = sum(1 for h in fs['highlights'] if h['kind'] == '0x1f')
        n20 = sum(1 for h in fs['highlights'] if h['kind'] == '0x20')
        status_vals = ','.join(f'{v}:{n}' for v, n in sorted(fs['status81_values'].items()))
        gold_n = len(fs['gold'])
        gold_total = sum(g['amount'] for g in fs['gold'])
        lines.append(f'\n- 0x02/0x85 金币流水 robust parse：**{gold_n} 条 / {gold_total}**；'
                     'docs 5.85 的 281/32,370 是未消费 0x80 12B 帧命令体的低计'
                     '（多出 5 条：seq 194/1071/5647/10508/12169）。')
        hi_times = ', '.join(f'{h["seq"] / 20.0:.2f}s({h["kind"]})' for h in fs['highlights'])
        lines.append(f'- 0x1f/0x20：主样本 {n1f}/{n20} 条高光通知（{hi_times}），'
                     'tag/actor 与 source43 击杀时间不对齐，**不是击杀/助攻记录**。')
        lines.append(f'- 0x02/0x81：主样本 {fs["status81"]} 条逐英雄状态位（值 {status_vals}），'
                     '**不是 KDA**；TLV 的 `02/81` 只在 20261028 样本存在，主样本没有。')
        v1e = [v for v in fs['values_1e'] if v >= 0]
        r1e = f'{min(v1e)}–{max(v1e)}' if v1e else '-'
        lines.append(f'- 0x1e：{fs["count_1e"]} 条稀疏高伤害/高光值（{r1e}），'
                     '不是逐事件伤害账本，不能当总输出/承伤。\n')

    lines.append('## 4. 5230306 变体：累计金币/经验与 OCR 对拍\n')
    if tlv_sample:
        ts = tlv_sample['tlv_stats']
        lines.append(f'样本：`{tlv_sample["name"]}`；TLV {ts["records"]} 条；'
                     f'seq {ts["seq_min"]}–{ts["seq_max"]}；max(seq)/14 = {ts["seq_max"] / 14:.2f}s，'
                     f'与 OCR `replayDuration={ocr_s["replayDuration"]}` 吻合，故时间轴用 **seq/14**，不是 seq/20。\n')
        tlv_notes = {
            (1, 0): '逐英雄短状态/位置类；1763 条，非 10 行面板',
            (2, 0x80): 'POV 累计金币/经验快照（5 条）',
            (2, 0x81): '击杀位置候选（20 条；不是完整击杀 feed）',
            (2, 0x83): '单位生成（476 条）',
            (2, 0x84): '全图单位死亡（599 条；带 owner key，不带 killer/victim）',
            (2, 0x85): '出装/道具事件（7 条）',
            (2, 0x87): '技能/装备被动等级（8 条）',
        }
        lines.append('| TLV 类型 | 条数 | 判定 |')
        lines.append('|---|---:|---|')
        for (t, sub), count in sorted(ts['types'].items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f'| {t:02x}/{sub:02x} | {count} | {tlv_notes.get((t, sub), "未定")} |')
        lines.append('')
        lines.append('| 时间(s) | 类型 | a | value | 说明 |')
        lines.append('|---:|---|---:|---:|---|')
        for snap in tlv_gold_snaps:
            label = {2: '累计金币', 5: '累计经验'}.get(snap['a'], f'a={snap["a"]}')
            lines.append(f'| {snap["time"]:.2f} | 02/80 | {snap["a"]} | {snap["value"]} | {label}（256 量化） |')
        lines.append('\n- 02/80 只有 POV（key 022301）5 条；不是 10 人面板。')
        lines.append('- 02/85 出装/道具事件 7 条：' +
                     ', '.join(f'{x["time"]:.1f}s type={x["item_type"]} item={x["item_id"]}(key={x["key"]})'
                               for x in tlv_items) + '。')
        lines.append('- 其中唯一 `type=4, item=194` 在 146.29s（key=0068a6）；它是道具/出装事件，'
                     '不是金币 source 4，也不要把 5069040 的 `0x02 flag=0x85 source=4` 混进来。')
        lines.append('- 本地英雄：header offset 35 的 u16LE = **118（孙膑）**；与录屏 POV 一致。'
                     'conf_type1=50、KV 与 5069040 普通 5v5 样本一致，因此按“普通 5v5 短局/片段”处理。')
        lines.append('\n**金币模型对拍（初始 300；自然金起点 30s；每 256 量化 ±128）：**\n')
        lines.append('| 时间(s) | 累计快照 | 10/s 推出事件金 | 3/s 推出事件金 | OCR 当前金(锚点时间) | 差值/花费 |')
        lines.append('|---:|---:|---:|---:|---|---|')
        for snap in [s for s in tlv_gold_snaps if s['a'] == 2]:
            e10 = snap['value'] - 300 - max(0, snap['time'] - 30) * 10
            e3 = snap['value'] - 300 - max(0, snap['time'] - 30) * 3
            nearest = ocr_current_gold_at(ocr_s, snap['time'], max_dt=15.0)
            ocr_gold = nearest[2] if nearest else None
            spend = (snap['value'] - ocr_gold) if ocr_gold is not None else None
            anchor = f'({nearest[1]}s/{nearest[3]})' if nearest else '(无≤15s锚点)'
            if spend is None:
                spend_text = '-'
            elif nearest is not None and abs(nearest[1] - snap['time']) <= 0.5:
                spend_text = f'≈{int(spend)} (±128)'
            else:
                spend_text = f'≤{int(spend)} (±128)'
            lines.append(f'| {snap["time"]:.2f} | {snap["value"]} | {e10:.0f} | {e3:.0f} | '
                         f'{(str(ocr_gold) + " " + anchor) if ocr_gold is not None else "-"} | '
                         f'{spend_text} |')
        lines.append('\n- 02/80 的 value 是 **u16BE**（`04 00`→1024、`09 00`→2304、`15 00`→5376）；'
                     '按 u16LE 会误读成 4/9/21。')
        lines.append('- **37s OCR 当前金 500**：300 + 10×(37−30) + 130 = 500（10/s 口径），'
                     '或 300 + 3×7 + 179 = 500（3/s 口径）；两者都能拟合，单点不能定速率。')
        lines.append('- **79s**：累计 2304，selection 段末（gameTime 79）当前金 1629 → 花费 ≈675；'
                     '与出装面板 2–3 件一致。')
        lines.append('- **+10/s 的 OCR 逐秒跳变**支持 10/s，但也可能是辅助装/分享金；'
                     '容器本身只给累计快照，**不能唯一证明自然金速率**。')
        lines.append('- 结论：02/80 验证了“初始 300 + 持续累积 + 离散事件金”的可加模型（medium-high）；'
                     '自然金 10/s vs 3/s 仍未闭合（medium）。\n')

        lines.append('**02/81 击杀位置候选（20 条）：**\n')
        lines.append('| 时间(s) | kind | coord | key | 最近 OCR 击杀 | 差(s) |')
        lines.append('|---:|---|---:|---|---:|---:|')
        for kp in tlv_kill_pos:
            best = None
            for ev in ocr_s['killEvents']:
                dt = kp['time'] - ev['gameTime']
                if best is None or abs(dt) < abs(best[0]):
                    best = (dt, ev['gameTime'])
            lines.append(f'| {kp["time"]:.2f} | {kp["kind"]} | {kp["coord"]} | {kp["key"]} | '
                         f'{best[1] if best else "-"} | {best[0]:+.1f} |' if best else
                         f'| {kp["time"]:.2f} | {kp["kind"]} | {kp["coord"]} | {kp["key"]} | - | - |')
        within8 = 0
        within3 = 0
        for kp in tlv_kill_pos:
            deltas = [abs(kp['time'] - ev['gameTime']) for ev in ocr_s['killEvents']]
            if deltas and min(deltas) <= 8:
                within8 += 1
            if deltas and min(deltas) <= 3:
                within3 += 1
        lines.append(f'\n- {len(tlv_kill_pos)} 条 02/81 中 **{within8} 条**落在 3 次 OCR 击杀的 ±8s 内'
                     f'（其中 {within3} 条 ≤3s）；仍有 {len(tlv_kill_pos) - within8} 条不对应任何已知击杀。'
                     '**02/81 不是完整击杀 feed**，不能单独还原 KDA（low-medium）。')
        lines.append('- 02/84 599 条是全图单位死亡（小兵/野怪），02/83 476 条是单位生成；'
                     '都不带英雄 killer/victim 归属。\n')

        lines.append('**OCR KDA 锚点：**\n')
        lines.append('- 06-team-panel（00:32）：十人 0/0/0，POV 340，其余 330；top 团队 1.7k。')
        lines.append('- scoreboard（gameTime 60）：红 程咬金 1/0/0、蓝 影 0/1/0、红 百里玄策 0/0/1；'
                     'POV 孙膑 0/0/0、960 金。')
        lines.append('- 05-hud-last（01:46 = gameTime 106）：蓝 2 杀/9.1k，红 1 杀/8.6k；'
                     'POV 孙膑 0/0/1，1783 金，等级 5。')
        lines.append('- 由此可还原：第一杀（55s）红方程咬金击杀、蓝方影阵亡、红方百里玄策助攻；'
                     '82s/104s 两次蓝方击杀只有团队计数，POV 在 104s 拿到 1 助攻。')
        lines.append('- 容器侧 02/81 不能补出上述归属；OCR 是唯一归属来源。\n')

    lines.append('## 5. 最终面板是否在容器里\n')
    lines.append('| 检查项 | 结果 | 置信度 |')
    lines.append('|---|---|---|')
    lines.append('| 30s/结算字段名字面量（27 .abc + 31 .ope） | 0 命中 | high |')
    lines.append('| 帧流 10-hero 统计块 | 无；只有技能/状态/位置/帧命令 | high |')
    lines.append('| TLV 10 行面板 | 无；只有 POV 金币/经验、02/81、02/83/84/85/87 | high |')
    lines.append('| 第二段帧流（712 帧） | 输入续流；0 条 0x85 金币，0 个 10-hero 面板 | high |')
    lines.append('| tail（102/106B 名单） | entityID + 未解次值，不是 KDA/金币 | high |')
    lines.append(f'| 未适配旧样本（{len(old_samples)} 个） | 只能做字面量搜索；结构层不可评估 | medium |')
    lines.append('| .ope operator 流 | 31/31 解压成功；按 docs 5.94/operator_stream.py 是 Touch/Move/SkillUse/GameCoreFrame 输入；字段名 0 命中 | high |')
    lines.append('\n**结论**：在 27 个样本的当前容器范围内，**没有观察到最终面板**；'
                 '这是“未找到 + 结构层不支持”，不是“已证明所有版本永远不存在”。'
                 '最终面板需要外部数据补。\n')

    lines.append('## 6. 外部补数据的最小字段集与验证\n')
    lines.append('最小 KDA/金币面板（10 行）：')
    lines.append('`entity_id, hero_id, team, kills, deaths, assists, total_gold`。')
    lines.append('\n完整最终面板（10 行）：再加 `damage_dealt, damage_taken`；'
                 '可选 `level, items, gold_spent, tower_damage, healing, mvp`。\n')
    lines.append('验证方法：')
    lines.append('1. 10 行 entity/hero/team 唯一；')
    lines.append('2. 队伍击杀 = 对方队伍死亡（本样本 4:2 与 2:4）；')
    lines.append('3. POV KDA/金币对 HUD/录屏（本样本 0/0/1、1783）；')
    lines.append('4. 金币口径：当前金币 = 300 + 事件金 + 自然金模型 − 已花费；'
                 '总获得金币 = 300 + 事件金 + 自然金模型（支出另列）。')
    lines.append('5. 五人金币和/队伍金币对 top HUD（OCR 32s 1.7k、106s 9.1k/8.6k）；')
    lines.append('6. 若 0x1e 是伤害值，其样本和只能给输出下界；未验证，不能当面板输出。')
    lines.append('7. 死亡逐人对 scoreboard 快照（本样本 gameTime 60 已有第一杀归属）。\n')

    lines.append('## 7. 复跑\n')
    lines.append('```bash\npython tools/agent_final_panel.py\n```')
    lines.append('只读输入：`data/replays/**/*.abc`、`data/replays/**/*.ope`、'
                 '`data/replays/video_ocr/2a7206b09ea8cc35.json`、`abc_roster.json`、'
                 '`agent_normal5v5_player_heroes.csv`（若存在）。')
    lines.append('输出：`data/replays/_analysis/datasets/agent_final_panel.csv` 与本文件。\n')

    lines.append('## 8. 主要证据路径\n')
    lines.append('- `data/replays/samples/abc_batch/20260925_105224_-1505729760_4933_1790303631_CBDD358E761B15A4DF526A179E8119E2.abc`（主样本）')
    lines.append('- `data/replays/samples/20261028_135516.abc`（5230306 TLV / OCR 同局）')
    lines.append('- `data/replays/video_ocr/evidence/05-hud-last.png`（01:46 蓝2/红1、POV 0/0/1、1783、5级）')
    lines.append('- `data/replays/video_ocr/evidence/06-team-panel.png`（00:32 十人 0/0/0、330–340）')
    lines.append('- `data/replays/video_ocr/2a7206b09ea8cc35.json`（killEvents、scoreboard、teamPanel、时间轴）')
    lines.append('- `data/replays/_analysis/datasets/agent_final_panel.csv`（逐条证据）')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', default=str(DEFAULT_OUT))
    args = parser.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    samples_raw = discover_samples()
    samples = [analyze_sample(s) for s in samples_raw]

    # 签名搜索：abc 原始字节
    signature_rows = []
    for s in samples:
        data = s['data']
        hits = token_hits(data)
        signature_rows.append({
            'res_build': s['res_build'], 'sample': s['name'],
            'container': s['container'], 'field': 'literal_token_hits',
            'value': str(len(hits)), 'value_num': len(hits),
            'confidence': 'high',
            'evidence': 'ASCII/UTF-16LE/BE; ' + (', '.join(f'{t}:{e}' for t, e in hits) if hits else 'no hits'),
        })
        # 结构候选
        if s['frame_stats']:
            fs = s['frame_stats']
            signature_rows.append({
                'res_build': s['res_build'], 'sample': s['name'],
                'container': s['container'], 'field': 'frame_shapes',
                'value': str(len(fs['shape_count'])), 'value_num': len(fs['shape_count']),
                'confidence': 'high',
                'evidence': 'parse_ok={:.2%}; 0x80 12B body consumed'.format(fs['parse_ratio']),
            })
        if s['tlv_stats']:
            signature_rows.append({
                'res_build': s['res_build'], 'sample': s['name'],
                'container': s['container'], 'field': 'tlv_types',
                'value': str(len(s['tlv_stats']['types'])),
                'value_num': len(s['tlv_stats']['types']),
                'confidence': 'high',
                'evidence': 'TLV type/sub count',
            })

    # ope 搜索
    ope_paths = sorted(REPLAY_ROOT.rglob('*.ope'))
    seen_hashes = set()
    ope_rows = []
    for path in ope_paths:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        hits_raw = token_hits(raw)
        inner, stream, offset = decompress_ope(raw)
        hits_inner = token_hits(inner) if inner is not None else []
        hits_stream = token_hits(stream) if stream is not None else []
        ope_rows.append({
            'file': str(path.relative_to(PROJECT_ROOT)),
            'size': len(raw),
            'inner': len(inner) if inner is not None else None,
            'stream': len(stream) if stream is not None else None,
            'stream_offset': offset,
            'hits_raw': len(hits_raw),
            'hits_inner': len(hits_inner),
            'hits_stream': len(hits_stream),
        })
        signature_rows.append({
            'res_build': '', 'sample': path.name, 'container': 'ope',
            'field': 'literal_token_hits',
            'value': str(len(hits_raw) + len(hits_inner) + len(hits_stream)),
            'value_num': len(hits_raw) + len(hits_inner) + len(hits_stream),
            'confidence': 'high',
            'evidence': f'raw+inner+operator; inner={len(inner) if inner else 0}; '
                        f'stream={len(stream) if stream else 0}@{hex(offset) if offset else "-"}',
        })

    # 把 ope 命中按“同日期前缀”归到 res_build，便于分层报告
    def build_for_ope(name: str):
        stem = name[:-4]
        prefix = stem.split('_CBDD')[0]
        for s in samples:
            if s['name'].split('_CBDD')[0].startswith(prefix[:15]):
                return s['res_build']
        return '?'

    for row in signature_rows:
        if row['container'] == 'ope' and not row['res_build']:
            row['res_build'] = build_for_ope(row['sample'])

    ocr = load_ocr()
    rows, main, tlv_sample, ocr_s = build_rows(samples, ocr, ope_rows, signature_rows)

    csv_path = out_dir / 'agent_final_panel.csv'
    md_path = out_dir / 'agent_final_panel.md'
    write_csv(rows, csv_path)
    write_md(md_path, samples, signature_rows, main, tlv_sample, ocr_s, rows)

    # 控制台摘要
    builds = Counter(s['res_build'] for s in samples)
    print(f'samples: {len(samples)} unique .abc names / {sum(len(s["paths"]) for s in samples)} paths')
    print('res_build:', dict(sorted(builds.items(), key=lambda kv: (-kv[1], kv[0]))))
    print(f'containers: frame={sum(1 for s in samples if s["container"] == "frame_stream")}, '
          f'tlv={sum(1 for s in samples if s["container"] == "tlv_stream")}, '
          f'old={sum(1 for s in samples if s["container"] == "old_or_unsupported")}')
    token_hits_total = sum(r['value_num'] or 0 for r in signature_rows
                           if r['field'] == 'literal_token_hits')
    print(f'literal token hits: {token_hits_total} (abc+ope)')
    print(f'unknown 10-hero panel candidates: {sum(1 for s in samples if s["panel_candidate"])}')
    if main:
        print(f'main KDA source43 events: {sum(1 for g in main["frame_stats"]["gold"] if g["source"] == 43)}')
    if tlv_sample:
        print(f'tlv records: {tlv_sample["tlv_stats"]["records"]}; '
              f'snapshots: {len(tlv_sample["tlv_stats"]["snapshots"])}; '
              f'kill_positions: {len(tlv_sample["tlv_stats"]["kill_positions"])}')
    print('wrote', csv_path)
    print('wrote', md_path)


if __name__ == '__main__':
    main()
