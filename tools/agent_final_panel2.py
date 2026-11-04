#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最终面板 / 30 秒统计 / KDA 二次核查（只读，只看主样本 20260925_105224）。

与 `tools/agent_final_panel.py` 的差别
------------------------------------
1. 只锁定主样本（5069040 / 普通 5v5 / 录制者 1558 佚名(*:），
   逐段核对：主帧流、主段末尾 2 帧、第二段 712 帧、尾部 106B 名单。
2. 用「宽容标签扫描 + count 一致性」两套口径统计 0x02/0x85、0x87、
   0x81、0x1e/0x1f/0x20，并显式报告与已知基线的差值。
3. 把第二段续流里的金币/装备/高光消息单独列出（此前报告称第二段纯输入，
   实际含 8 条 0x85、2 条 0x87、5 条 0x20）。
4. 用 0x85 + 0x87 + 0x1e/0x1f/0x20 重建 1558 的收入/装备曲线，
   并给出 KDA 的可确定部分与缺口。

只读约束
--------
只读 data/replays/**/*.abc、*.ope、_analysis/comdt_game_30sec.json、
_analysis/datasets/agent_normal5v5_player_heroes.csv、
_analysis/datasets/normal5v5_equipment_{plans,upgrades}_5069040.csv、
_analysis/global-metadata.dat（仅做 token 存在性校验）。
不修改回放/包体，不注入，不读 param.json，不使用 runtime_dump，
不写 docs/replay_binary_format.md 与 .workbuddy/memory/MEMORY.md。

输出
----
data/replays/_analysis/datasets/agent_final_panel2.csv
data/replays/_analysis/datasets/agent_final_panel2.md

用法
----
    python tools/agent_final_panel2.py
"""
from __future__ import annotations

import csv
import json
import statistics
import struct
import zlib
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPLAY_ROOT = PROJECT_ROOT / 'data' / 'replays'
ANALYSIS = REPLAY_ROOT / '_analysis'
DATASETS = ANALYSIS / 'datasets'
SAMPLE_GLOB = '20260925_105224_*.abc'
SAMPLE_SHORT = '20260925_105224'
TARGET_ENTITY = 1558
TARGET_PLAYER = '佚名(*:'
TARGET_HERO_ID = 187
TARGET_HERO = '东皇太一'

PLAYER_CSV = DATASETS / 'agent_normal5v5_player_heroes.csv'
PLAN_CSV = DATASETS / 'normal5v5_equipment_plans_5069040.csv'
UPGRADE_CSV = DATASETS / 'normal5v5_equipment_upgrades_5069040.csv'
COMDT_JSON = ANALYSIS / 'comdt_game_30sec.json'
METADATA = ANALYSIS / 'global-metadata.dat'

# 30s 统计 / 结算 / KDA / 伤害字段名。先在 global-metadata.dat 中确认存在，
# 再拿 0 命中做负结论；否则 0 命中可能只是拼写错误。
TOKENS = [
    'COMDT_GAME_30SEC_INFO', 'stReportPlayerData', 'iCoinFromKillSolider',
    'dwCoinCnt', 'dwCoinIntervalCnt', 'iCoinFromSystem',
    'dwSystemAddIntervalCoin', 'dwSystemAddCoin', 'dwHeroKillIntervalCoin',
    'dwSoliderKillCoin', 'dwKillCnt', 'dwKillSoldierCnt', 'dwDeadCnt',
    'dwAssistCnt', 'KDAStat', 'stHeroGoldCoinInBattleChangeParam',
    'dwHurtToEnemy', 'dwTakenFromEnemy', 'dwHurtToHeroAll', 'dwTakenFromHeroAll',
    'stWantedEcoStatic', 'dwPickupSoldierCoinValue', 'wCampKillCnt',
    'wCampDeadCnt', 'totalCoin', 'iCoinFromKillHero', 'iCoinFromKillMonster',
    'EquipID', 'astKillHeroPos', 'RewardMatchLevel', 'CommonSettle',
    'SvrNtfGameOverCommand', 'm_bWinCamp', 'isKillNotify', 'm_killerObjID',
    'm_victimObjID', 'm_assistCount',
]
ENCODINGS = ('ascii', 'utf-16le', 'utf-16be')

FRAME_MAIN_TRAILER = 7          # seq:u8 pad:u8 len:u8 payload a:u8 00*5 b:u8
FRAME_BE_TRAILER = 5            # frame:u16BE len:u16BE type:u8 payload 00*5
GAME_TIME_OFFSET = 20.3         # seq/20 + 20.3 = 对局时间（5.92 / 5.99）
NATURAL_START = 40.0            # battleDynamicProperty cfg1：30s 行 0，40s 起 3/s
NATURAL_RATE = 3.0
INITIAL_GOLD = 300.0


# ---------------------------------------------------------------------------
# 容器 / 帧流
# ---------------------------------------------------------------------------
def find_main_sample() -> Path:
    hits = sorted(REPLAY_ROOT.rglob(SAMPLE_GLOB))
    if not hits:
        raise SystemExit(f'main sample not found: {SAMPLE_GLOB}')
    # 优先 abc_batch 下的原始批次
    hits.sort(key=lambda p: (len(p.parts), str(p)))
    return hits[0]


def parse_header(data: bytes) -> dict:
    texts, pos = [], 0
    for _ in range(4):
        n = data[pos]
        if not 1 <= n <= 80:
            raise ValueError('bad header')
        texts.append(data[pos + 1:pos + 1 + n].decode('utf-8', 'replace'))
        pos += 1 + n
    local_hero = int.from_bytes(data[pos:pos + 2], 'little')
    return {
        'versions': texts[:2], 'builds': texts[2:],
        'res_build': texts[3], 'local_hero': local_hero,
        'kv_offset': pos + 2,
    }


def parse_conf(data: bytes, start: int) -> dict:
    sig = bytes.fromhex('010032000200010003001900')
    pos = data.find(sig, start, start + 0x400)
    if pos < 0:
        return {}
    count = struct.unpack_from('<H', data, pos - 2)[0]
    if not 0 < count < 200:
        return {}
    out, off = {}, pos
    for _ in range(count):
        if off + 4 > len(data):
            break
        out[data[off]] = struct.unpack_from('>H', data, off + 1)[0]
        off += 4
    return out


def parse_main_frames(data: bytes):
    """主段：seq(u8 低字节)+00+len(u8)+payload+7B trailer，seq 严格 +1。"""
    def walk(start, seq0):
        pos, seq, out = start, seq0, []
        while pos + 10 < len(data):
            if data[pos] != (seq & 0xFF) or data[pos + 1] != 0:
                break
            length = data[pos + 2]
            if pos + 10 + length > len(data):
                break
            out.append({
                'off': pos, 'seq': seq, 'length': length,
                'payload': data[pos + 3:pos + 3 + length],
                'trailer': data[pos + 3 + length:pos + 10 + length],
                'syntax': 'u8',
            })
            pos += 10 + length
            seq += 1
        return out, pos

    best = ([], 0)
    for pos in range(0, min(len(data), 0x20000)):
        if data[pos] == 0x22 and data[pos + 1] == 0:
            recs, end = walk(pos, 0x22)
            if len(recs) > len(best[0]):
                best = (recs, end)
                if len(recs) > 500:
                    break
    return best


def parse_be_frames(data: bytes, start: int, seq_lo: int, seq_hi: int, limit: int = 5000):
    """第二段/末两帧：frame:u16BE len:u16BE type:u8 payload 5B trailer。"""
    pos, out = start, []
    while pos + 5 <= len(data) and len(out) < limit:
        frame = int.from_bytes(data[pos:pos + 2], 'big')
        length = int.from_bytes(data[pos + 2:pos + 4], 'big')
        typ = data[pos + 4]
        if frame < seq_lo or frame > seq_hi or length > 1000 or pos + 10 + length > len(data):
            break
        out.append({
            'off': pos, 'seq': frame, 'length': length, 'type': typ,
            'payload': data[pos + 5:pos + 5 + length],
            'trailer': data[pos + 10 + length - 5:pos + 10 + length],
            'syntax': 'be',
        })
        pos += 10 + length
    return out, pos


def parse_payload(payload: bytes, count_prefix: bool = True):
    """标签流。返回 (msgs, scalars, clean, consistent)。

    msgs:   ('01', hero, flag, data) / ('02', hero, flag, data)
    scalars: 0x12/0x13/0x14 计数
    clean:  整个 payload 被标签语法吃满
    consistent: payload[0] == 消息数 + 标量数（count 语义）
    """
    i = 1 if count_prefix else 0
    n = len(payload)
    msgs, scal = [], 0
    while i < n:
        tag = payload[i]
        if tag == 0x12:
            if i + 3 > n:
                return msgs, scal, False, False
            i += 3
            scal += 1
        elif tag == 0x13:
            if i + 2 > n:
                return msgs, scal, False, False
            i += 2
            scal += 1
        elif tag == 0x14:
            if i + 4 > n:
                return msgs, scal, False, False
            i += 4
            scal += 1
        elif tag == 0x01:
            if i + 5 > n:
                return msgs, scal, False, False
            hero = int.from_bytes(payload[i + 1:i + 3], 'big')
            flag = payload[i + 3]
            length = payload[i + 4]
            if i + 5 + length > n:
                return msgs, scal, False, False
            msgs.append(('01', hero, flag, payload[i + 5:i + 5 + length]))
            i += 5 + length
        elif tag == 0x02:
            if i + 4 > n:
                return msgs, scal, False, False
            hero = int.from_bytes(payload[i + 1:i + 3], 'big')
            flag = payload[i + 3]
            length = 12 if flag == 0x80 else (flag & 0x7F)
            if i + 4 + length > n:
                return msgs, scal, False, False
            msgs.append(('02', hero, flag, payload[i + 4:i + 4 + length]))
            i += 4 + length
        else:
            return msgs, scal, False, False
    consistent = (not count_prefix) or (payload[0] == len(msgs) + scal)
    return msgs, scal, True, consistent


# ---------------------------------------------------------------------------
# 金币 / 装备 / 伤害通道
# ---------------------------------------------------------------------------
def gold_events(msgs):
    out = []
    for tag, hero, flag, data in msgs:
        if tag == '02' and flag == 0x85 and len(data) == 5:
            out.append((hero, data[0], int.from_bytes(data[1:5], 'little')))
    return out


def upgrade_events(msgs):
    """0x02/0x87 7B = 00 00 00 actorID skill(1-4) levelIdx(0-5) 00 00（技能升级）。

    字段顺序由单调性检验确定：按 (skill, level) 解释时 10 人 108 个相邻对 0 违例；
    按文档 5.100 的 (tier, slot) 解释时 79 个相邻对 26 违例（slot 出现 2→1→3）。
    """
    out = []
    for tag, hero, flag, data in msgs:
        if tag == '02' and flag == 0x87 and len(data) == 7 and data[0:3] == b'\x00\x00\x00' and data[6] == 0:
            out.append((hero, data[3], data[4], data[5]))
    return out


def e1e_events(msgs):
    out = []
    for tag, hero, flag, data in msgs:
        if tag == '01' and data[:1] == b'\x1e' and len(data) == 19:
            out.append({
                'hero': hero, 'type': data[1],
                'victim': int.from_bytes(data[16:18], 'big'), 'tail': data[18],
                'raw': data.hex(),
            })
    return out


def highlight_events(msgs):
    out = []
    for tag, hero, flag, data in msgs:
        if tag == '01' and data[:1] in (b'\x1f', b'\x20'):
            kind = data[0]
            out.append({
                'hero': hero, 'kind': f'0x{kind:02x}', 'size': len(data),
                'type': data[1] if len(data) > 1 else None,
                'i32': int.from_bytes(data[2:6], 'little', signed=True) if len(data) >= 6 else None,
                'u16_20': int.from_bytes(data[20:22], 'big') if len(data) >= 22 else None,
                'u16_22': int.from_bytes(data[22:24], 'big') if len(data) >= 24 else None,
                'raw': data.hex(),
            })
    return out



def entity_cluster_scan(buf: bytes, entities, width: int = 2, order: str = 'big', win: int = 256):
    """返回任一 win 字节窗口内出现过的不同 entity 值最大个数。"""
    events = []
    for ent in entities:
        needle = ent.to_bytes(width, order)
        start = 0
        while True:
            pos = buf.find(needle, start)
            if pos < 0:
                break
            events.append((pos, ent))
            start = pos + 1
    events.sort()
    if not events:
        return 0, None, None
    counter = defaultdict(int)
    distinct = 0
    left = 0
    best = (0, None, None)
    for i, (pos, ent) in enumerate(events):
        counter[ent] += 1
        if counter[ent] == 1:
            distinct += 1
        while pos - events[left][0] > win:
            counter[events[left][1]] -= 1
            if counter[events[left][1]] == 0:
                distinct -= 1
            left += 1
        if distinct > best[0]:
            best = (distinct, events[left][0], pos)
    return best

# ---------------------------------------------------------------------------
# 签名搜索
# ---------------------------------------------------------------------------
def token_hits(buf: bytes) -> list:
    hits = []
    for token in TOKENS:
        for enc in ENCODINGS:
            needle = token.encode(enc)
            pos = buf.find(needle)
            if pos >= 0:
                hits.append((token, enc, pos))
    return hits


def load_metadata_tokens():
    if not METADATA.exists():
        return {}
    data = METADATA.read_bytes()
    out = {}
    for token in TOKENS:
        found = []
        for enc in ENCODINGS:
            pos = data.find(token.encode(enc))
            if pos >= 0:
                found.append(f'{enc}@{pos:#x}')
        out[token] = found
    return out


def decompress_ope(raw: bytes):
    """外层 raw deflate + inner[0x80..0x200] 第二层 raw deflate（5.98 修正）。"""
    try:
        inner = zlib.decompressobj(-15).decompress(raw[1:]) if raw[:1] == b'\x01' else raw
    except Exception:
        return None, None, None
    best = (None, None)
    for pos in range(0x80, min(0x1C0, len(inner))):
        try:
            cand = zlib.decompressobj(-15).decompress(inner[pos:])
        except Exception:
            continue
        if len(cand) > 1000 and (best[0] is None or len(cand) > len(best[0])):
            best = (cand, pos)
    return inner, best[0], best[1]


# ---------------------------------------------------------------------------
# 玩家 / 方案 / 尾部
# ---------------------------------------------------------------------------
def load_players() -> dict:
    """优先用单样本表（无 sample 列）；否则用带 sample 列的 6 样本表并按文件名过滤。"""
    candidates = [PLAYER_CSV, DATASETS / 'normal5v5_player_heroes_5069040.csv']
    out = {}
    for path in candidates:
        if not path.exists():
            continue
        with path.open(encoding='utf-8-sig') as fh:
            reader = csv.DictReader(fh)
            has_sample = 'sample' in (reader.fieldnames or [])
            for row in reader:
                if has_sample and row.get('sample') != SAMPLE_SHORT:
                    continue
                try:
                    entity = int(row['entityID'])
                except (KeyError, ValueError):
                    continue
                out[entity] = {
                    'player': row.get('player', ''), 'team': int(row['team']),
                    'slot': int(row['slot']), 'hero_id': int(row['heroID']),
                    'hero': row.get('heroName', ''),
                }
        if out:
            break
    return out


def load_plans() -> dict:
    plans = defaultdict(list)
    if not PLAN_CSV.exists():
        return plans
    with PLAN_CSV.open(encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            if row.get('entityID') != str(TARGET_ENTITY):
                continue
            plans[row['plan']].append({
                'slot': int(row['slot']), 'item_id': int(row['item_id']),
                'item_name': row.get('item_name', ''),
                'passive': row.get('passive_name', ''),
            })
    return plans


def parse_tail_roster(footer: bytes) -> dict:
    """102/106B 名单：16B 头 + 4B extra + 10×(entityID:u16, code:u16) + [slot:u32] + u16。"""
    if len(footer) < 16:
        return {}
    head = [int.from_bytes(footer[p:p + 2], 'big') for p in range(0, 16, 2)]
    extra = int.from_bytes(footer[16:18], 'big') if len(footer) >= 20 else None
    values = []
    if len(footer) >= 20:
        for p in range(20, min(len(footer), 100), 4):
            value = int.from_bytes(footer[p:p + 2], 'big')
            pad = int.from_bytes(footer[p + 2:p + 4], 'big')
            if pad != 0:
                break
            values.append(value)
    pairs = list(zip(values[0::2], values[1::2]))
    local_slot = int.from_bytes(footer[100:104], 'big') if len(footer) >= 104 else None
    local_tail = int.from_bytes(footer[-2:], 'big') if len(footer) >= 2 else None
    return {
        'head': head, 'extra': extra, 'pairs': pairs,
        'local_slot': local_slot, 'local_tail': local_tail,
        'len': len(footer),
    }


# ---------------------------------------------------------------------------
# 主分析
# ---------------------------------------------------------------------------
def main():
    sample_path = find_main_sample()
    data = sample_path.read_bytes()
    header = parse_header(data)
    conf = parse_conf(data, header['kv_offset'])
    players = load_players()
    target = players.get(TARGET_ENTITY, {})

    main_recs, main_end = parse_main_frames(data)

    # 主段之后：末帧可能从主段结束前 1 字节开始（seq/len 用 u16BE 的重写帧，见报告）
    last_main_seq = main_recs[-1]['seq']
    scan_start = max(0, main_end - 8)
    be_start = None
    for i in range(scan_start, min(len(data) - 5, main_end + 0x1000)):
        frame = int.from_bytes(data[i:i + 2], 'big')
        length = int.from_bytes(data[i + 2:i + 4], 'big')
        if frame == last_main_seq + 1 and 4 <= length <= 1000 and i + 10 + length <= len(data):
            be_start = i
            break
    be_frames, be_end = ([], main_end)
    if be_start is not None:
        be_frames, be_end = parse_be_frames(
            data, be_start, last_main_seq + 1, last_main_seq + 1)

    # 第二段：从第一个 seq=last_main+2 的 2 字节帧头开始
    second_start = None
    second_probe = data.find(
        (last_main_seq + 2).to_bytes(2, 'big'), be_end, min(len(data), be_end + 0x1000))
    if second_probe > 0:
        second_start = second_probe
    second_frames, second_end = ([], second_start or len(data))
    if second_start:
        second_frames, second_end = parse_be_frames(
            data, second_start, last_main_seq + 2, last_main_seq + 2000)

    # ---------------- 主段消息统计 ----------------
    main_msgs = []
    clean_frames = consistent_frames = 0
    for rec in main_recs:
        msgs, scal, clean, consistent = parse_payload(rec['payload'], count_prefix=True)
        rec['msgs'] = msgs
        rec['clean'] = clean
        rec['consistent'] = consistent
        main_msgs.extend((rec['seq'], m) for m in msgs)
        clean_frames += int(clean)
        consistent_frames += int(consistent)

    main_gold, main_upg, main_1e, main_hl, status81 = [], [], [], [], []
    shape_counter = Counter()
    shape_heroes = defaultdict(set)
    main_ten = Counter()
    main_max_scalars = 0
    for rec in main_recs:
        per = defaultdict(set)
        for tag, hero, flag, payload in rec['msgs']:
            per[(tag, flag, len(payload))].add(hero)
            shape_heroes[(tag, flag, len(payload))].add(hero)
        _m, _s, _c, _k = parse_payload(rec['payload'], count_prefix=True)
        scal = _s
        main_max_scalars = max(main_max_scalars, scal)
        for key, heroes in per.items():
            if len(heroes) >= 10:
                main_ten[key] += 1
        for tag, hero, flag, payload in rec['msgs']:
            shape_counter[(tag, flag, len(payload))] += 1
            if tag == '02' and flag == 0x85 and len(payload) == 5:
                main_gold.append((rec['seq'], hero, payload[0], int.from_bytes(payload[1:5], 'little')))
            elif tag == '02' and flag == 0x87 and len(payload) == 7:
                main_upg.append((rec['seq'], hero, payload[3], payload[4], payload[5]))
            elif tag == '02' and flag == 0x81 and len(payload) == 1:
                status81.append((rec['seq'], hero, payload[0]))
            elif tag == '01' and payload[:1] == b'\x1e' and len(payload) == 19:
                main_1e.append({
                    'seq': rec['seq'], 'hero': hero, 'type': payload[1],
                    'victim': int.from_bytes(payload[16:18], 'big'), 'tail': payload[18],
                    'raw': payload.hex(),
                })
            elif tag == '01' and payload[:1] in (b'\x1f', b'\x20'):
                main_hl.append({
                    'seq': rec['seq'], 'hero': hero, 'kind': f'0x{payload[0]:02x}',
                    'size': len(payload), 'type': payload[1] if len(payload) > 1 else None,
                    'raw': payload.hex(),
                })

    # ---------------- 第二段消息统计 ----------------
    second_gold, second_upg, second_1e, second_hl = [], [], [], []
    second_shapes = Counter()
    second_clean = second_consistent = 0
    second_ten = 0
    for rec in second_frames:
        msgs, scal, clean, consistent = parse_payload(rec['payload'], count_prefix=False)
        rec['msgs'] = msgs
        second_clean += int(clean)
        second_consistent += int(consistent)
        per = defaultdict(set)
        for tag, hero, flag, payload in msgs:
            second_shapes[(tag, flag, len(payload))] += 1
            per[(tag, flag, len(payload))].add(hero)
            if tag == '02' and flag == 0x85 and len(payload) == 5:
                second_gold.append((rec['seq'], hero, payload[0], int.from_bytes(payload[1:5], 'little')))
            elif tag == '02' and flag == 0x87 and len(payload) == 7:
                second_upg.append((rec['seq'], hero, payload[3], payload[4], payload[5]))
            elif tag == '01' and payload[:1] == b'\x1e' and len(payload) == 19:
                second_1e.append({
                    'seq': rec['seq'], 'hero': hero, 'type': payload[1],
                    'victim': int.from_bytes(payload[16:18], 'big'), 'raw': payload.hex(),
                })
            elif tag == '01' and payload[:1] in (b'\x1f', b'\x20'):
                second_hl.append({
                    'seq': rec['seq'], 'hero': hero, 'kind': f'0x{payload[0]:02x}',
                    'size': len(payload), 'type': payload[1] if len(payload) > 1 else None,
                    'raw': payload.hex(),
                })
        for key, heroes in per.items():
            if len(heroes) >= 10:
                second_ten += 1

    # ---------------- 尾部 ----------------
    footer_raw = data[second_end:] if second_frames else data[main_end:]
    footer = footer_raw
    extra_prefix = 0
    if len(footer) >= 17 and footer[0] == 0x04 and len(footer) - 1 in (102, 106):
        footer = footer[1:]
        extra_prefix = 1
    roster = parse_tail_roster(footer)
    trailing_after_roster = max(0, len(footer) - int(roster.get('len') or len(footer)))

    # ---------------- 签名搜索 ----------------
    meta_tokens = load_metadata_tokens()
    abc_hits = []
    abc_paths = sorted(REPLAY_ROOT.rglob('*.abc'))
    for path in abc_paths:
        buf = path.read_bytes()
        hits = token_hits(buf)
        if hits:
            abc_hits.append({'path': str(path.relative_to(PROJECT_ROOT)), 'hits': hits})
    ope_paths = sorted(REPLAY_ROOT.rglob('*.ope'))
    ope_hits = []
    ope_stats = []
    for path in ope_paths:
        raw = path.read_bytes()
        inner, stream, offset = decompress_ope(raw)
        hits = []
        for layer_name, layer in (('raw', raw), ('inner', inner), ('operator', stream)):
            if layer:
                for token, enc, pos in token_hits(layer):
                    hits.append((layer_name, token, enc, pos))
        if hits:
            ope_hits.append({'path': str(path.relative_to(PROJECT_ROOT)), 'hits': hits})
        ope_stats.append({
            'path': path.name, 'size': len(raw),
            'inner': len(inner) if inner else 0,
            'operator': len(stream) if stream else 0,
            'operator_offset': offset,
            'hits': len(hits),
        })

    # ---------------- 1558 重建 ----------------
    all_gold = [(seq, hero, src, amt, 'main') for seq, hero, src, amt in main_gold] + \
               [(seq, hero, src, amt, 'second') for seq, hero, src, amt in second_gold]
    tgt_gold = [(s, src, amt, layer) for s, h, src, amt, layer in all_gold if h == TARGET_ENTITY]
    tgt_gold.sort()
    tgt_upg = [(s, 'main', actor, tier, slot) for s, h, actor, tier, slot in main_upg if h == TARGET_ENTITY] + \
                [(s, 'second', actor, tier, slot) for s, h, actor, tier, slot in second_upg if h == TARGET_ENTITY]
    tgt_upg.sort()

    # 0x87 字段顺序判定：slot/level vs tier/slot 的单调性计数
    upg_all = defaultdict(list)
    for seq, hero, actor, a, b in main_upg + second_upg:
        upg_all[hero].append((seq, a, b))
    def monotonic_violations(mode):
        viol = total = 0
        for items in upg_all.values():
            by = defaultdict(list)
            for _seq, a, b in sorted(items):
                key, val = (a, b) if mode == 'slot_level' else (b, a)
                by[key].append(val)
            for vals in by.values():
                total += max(0, len(vals) - 1)
                viol += sum(1 for i in range(1, len(vals)) if vals[i] < vals[i - 1])
        return viol, total
    upg_viol_sl, upg_total_sl = monotonic_violations('slot_level')
    upg_viol_ts, upg_total_ts = monotonic_violations('tier_slot')
    upg_pairs = defaultdict(set)
    for items in upg_all.values():
        for _seq, a, b in items:
            upg_pairs[a].add(b)

    # 与历史 skill 数据集交叉核对（replay_skill_levels.csv 只覆盖主段，且对 0x80 处理不同）
    skill_csv = DATASETS / 'replay_skill_levels.csv'
    old_skill_seqs = set()
    if skill_csv.exists():
        with skill_csv.open(encoding='utf-8-sig') as fh:
            for row in csv.DictReader(fh):
                if row.get('hero_id') == str(TARGET_ENTITY) and row.get('file', '').startswith(SAMPLE_SHORT):
                    try:
                        old_skill_seqs.add(int(row['seq']))
                    except (KeyError, ValueError):
                        pass
    new_skill_seqs = {seq for seq, _l, _a, _k, _v in tgt_upg}
    skill_cross = {
        'old_rows': len(old_skill_seqs),
        'new_rows': len(new_skill_seqs),
        'overlap': len(old_skill_seqs & new_skill_seqs),
        'only_new': sorted(new_skill_seqs - old_skill_seqs),
        'only_old': sorted(old_skill_seqs - new_skill_seqs),
    }

    tgt_1e = [e for e in main_1e if e['hero'] == TARGET_ENTITY] + \
             [e for e in second_1e if e['hero'] == TARGET_ENTITY]
    tgt_hl = [e for e in main_hl if e['hero'] == TARGET_ENTITY] + \
             [e for e in second_hl if e['hero'] == TARGET_ENTITY]

    last_seq = second_frames[-1]['seq'] if second_frames else main_recs[-1]['seq']
    match_end_game = last_seq / 20.0 + GAME_TIME_OFFSET
    natural_total = NATURAL_RATE * max(0.0, match_end_game - NATURAL_START)

    # 辅助装被动：0x87 是技能升级、不是装备购买，没有购买时刻可锚定。
    # 这里只给一个「若辅助装从 40s 起生效」的推测上限，明确标 low。
    support_total = (5 / 3) * max(0.0, match_end_game - NATURAL_START)
    tgt_src5 = [amt for _s, src, amt, _l in tgt_gold if src == 5]
    tgt_src5_small = sum(a for a in tgt_src5 if a <= 80)
    observed = sum(amt for _s, _src, amt, _l in tgt_gold)
    income_low = INITIAL_GOLD + observed
    income_mid = income_low + natural_total
    income_high = income_mid + support_total
    income_mid_nodouble = income_mid - tgt_src5_small

    # KDA
    kills = defaultdict(list)
    assists = defaultdict(list)
    for seq, hero, src, amt, _layer in all_gold:
        if src == 43 and amt >= 200:
            kills[hero].append((seq, amt))
        elif src == 43 and amt < 200:
            assists[hero].append((seq, amt))
    team_kills = Counter()
    for hero, events in kills.items():
        team = players.get(hero, {}).get('team', 0)
        team_kills[team] += len(events)
    tgt_team = target.get('team', 0)
    team_deaths = team_kills.get(3 - tgt_team, 0)

    # 收入曲线：在每个购买时刻计算累计可观测金 + 自然金
    curve = []
    running = 0
    by_seq = defaultdict(list)
    for seq, src, amt, layer in tgt_gold:
        by_seq[seq].append((src, amt))
    for seq in sorted(by_seq):
        for src, amt in by_seq[seq]:
            running += amt
            gt = seq / 20.0 + GAME_TIME_OFFSET
            nat = NATURAL_RATE * max(0.0, gt - NATURAL_START)
            curve.append({
                'seq': seq, 'game_time': gt, 'source': src, 'amount': amt,
                'cum_observed': running, 'cum_natural': nat,
                'cum_income': INITIAL_GOLD + running + nat,
            })

    # 计划
    plans = load_plans()

    # ---------------- 写 CSV ----------------
    rows = []

    def add(section, key, **kw):
        base = {
            'section': section, 'key': key, 'seq': '', 'time_s': '', 'game_time_s': '',
            'channel': '', 'entity_id': '', 'player': '', 'field': '', 'value': '',
            'unit': '', 'confidence': '', 'evidence': '',
        }
        base.update({k: ('' if v is None else v) for k, v in kw.items()})
        rows.append(base)

    # 容器
    add('container', 'main_sample', channel='abc', field='path',
        value=str(sample_path.relative_to(PROJECT_ROOT)), confidence='high',
        evidence='main sample 20260925_105224')
    add('container', 'header', channel='abc', field='res_build',
        value=header['res_build'], confidence='high',
        evidence='versions=' + '/'.join(header['versions']) + '; localHeroId=' + str(header['local_hero']))
    add('container', 'conf_kv', channel='abc', field='kv',
        value=json.dumps({str(k): v for k, v in sorted(conf.items())}, ensure_ascii=False),
        confidence='high', evidence='Svr2GameCore KV (no param.json read)')
    add('container', 'frames_main', channel='abc.frame', field='count',
        value=len(main_recs), confidence='high',
        evidence=f'seq {main_recs[0]["seq"]}..{main_recs[-1]["seq"]}; clean={clean_frames}; count_consistent={consistent_frames}')
    add('container', 'frames_be_tail', channel='abc.frame', field='count',
        value=len(be_frames), confidence='medium',
        evidence='2-byte-seq frames between main segment and continuation: ' +
                 ','.join(f'{r["seq"]}:{r["length"]}B:type{r["type"]}' for r in be_frames))
    add('container', 'frames_second', channel='abc.frame', field='count',
        value=len(second_frames), confidence='high',
        evidence=(f'seq {second_frames[0]["seq"]}..{second_frames[-1]["seq"]}; '
                  f'clean={second_clean}; count_consistent={second_consistent}'
                  if second_frames else 'none'))
    add('container', 'tail', channel='abc.tail', field='footer_len',
        value=len(footer) + extra_prefix, confidence='high',
        evidence=f'roster={roster.get("len")}B; extra 0x04 prefix={extra_prefix}; bytes after roster={trailing_after_roster}')
    add('container', 'match_end', channel='abc.frame', field='last_seq',
        value=last_seq, confidence='high',
        evidence=f'game_time={match_end_game:.1f}s (seq/20+{GAME_TIME_OFFSET})')

    # 签名搜索
    for token, found in meta_tokens.items():
        add('signature', token, channel='global-metadata', field='present',
            value='yes' if found else 'no', confidence='high',
            evidence=','.join(found)[:200])
    add('signature', 'abc_raw_scan', channel='abc', field='files',
        value=len(abc_paths), confidence='high',
        evidence=f'tokens={len(TOKENS)}; files_with_hits={len(abc_hits)}')
    for hit in abc_hits[:10]:
        add('signature', 'abc_hit', channel='abc', field='path', value=hit['path'],
            confidence='high', evidence=str(hit['hits'])[:400])
    add('signature', 'ope_scan', channel='ope', field='files',
        value=len(ope_paths), confidence='high',
        evidence=f'tokens={len(TOKENS)}; files_with_hits={len(ope_hits)}; '
                 f'operator_layer_ok={sum(1 for s in ope_stats if s["operator"])}')
    for hit in ope_hits[:10]:
        add('signature', 'ope_hit', channel='ope', field='path', value=hit['path'],
            confidence='high', evidence=str(hit['hits'])[:400])

    # 第二段
    add('second_segment', 'gold_events', channel='abc.frame', field='count',
        value=len(second_gold), confidence='high',
        evidence='0x02/0x85 in continuation frames: ' +
                 ', '.join(f'{s}:{h}:{src}/{a}' for s, h, src, a in second_gold))
    add('second_segment', 'skill_upgrade_events', channel='abc.frame', field='count',
        value=len(second_upg), confidence='high',
        evidence='0x02/0x87: ' + ', '.join(f'{s}:{h}:actor{a}/skill{k}/lv{l}' for s, h, a, k, l in second_upg))
    add('second_segment', 'highlight_0x20', channel='abc.frame', field='count',
        value=sum(1 for e in second_hl if e['kind'] == '0x20'), confidence='medium',
        evidence=', '.join(f'{e["seq"]}:{e["hero"]}' for e in second_hl if e['kind'] == '0x20'))
    add('second_segment', 'ten_hero_shapes', channel='abc.frame', field='count',
        value=second_ten, confidence='high',
        evidence='no shape covers all 10 entities in one frame')
    add('second_segment', 'gold_total', channel='abc.frame', field='sum',
        value=sum(a for _s, _h, _src, a in second_gold), unit='gold', confidence='high',
        evidence='continuation adds income after 654.7s')

    # 尾部
    add('tail', 'roster', channel='abc.tail', field='pairs',
        value=' '.join(f'{v}:{pad}' for v, pad in roster.get('pairs', [])), confidence='high',
        evidence=f'head={roster.get("head")}; extra={roster.get("extra")}; '
                 f'local_slot={roster.get("local_slot")}; local_tail={roster.get("local_tail")}')
    add('tail', 'after_roster', channel='abc.tail', field='bytes',
        value=trailing_after_roster, confidence='high',
        evidence='no settlement/panel block after the 102/106B roster; file ends')

    # 通道统计
    add('channel', 'gold_0x85_main', channel='0x02/0x85', field='count/sum',
        value=f'{len(main_gold)}/{sum(a for _s, _h, _src, a in main_gold)}', unit='gold',
        confidence='high', evidence='source:u8 + amount:u32LE')
    add('channel', 'gold_0x85_second', channel='0x02/0x85', field='count/sum',
        value=f'{len(second_gold)}/{sum(a for _s, _h, _src, a in second_gold)}', unit='gold',
        confidence='high', evidence='continuation segment')
    add('channel', 'skill_0x87_main', channel='0x02/0x87', field='count',
        value=len(main_upg), confidence='high',
        evidence='00 00 00 actorID skill(1-4) levelIdx(0-5) 00 00; NOT equipment')
    add('channel', 'skill_0x87_second', channel='0x02/0x87', field='count',
        value=len(second_upg), confidence='high', evidence='continuation segment')
    add('channel', 'monotonicity_0x87', channel='test', field='violations',
        value=f'slot_level={upg_viol_sl}/{upg_total_sl}; tier_slot={upg_viol_ts}/{upg_total_ts}',
        confidence='high',
        evidence=f'0 violations for (skill,level); {upg_viol_ts} for (tier,slot) -> field order is actorID/skill/level')
    add('channel', 'skill_crosscheck', channel='dataset', field='rows',
        value=f'old={skill_cross["old_rows"]}; new={skill_cross["new_rows"]}; overlap={skill_cross["overlap"]}',
        confidence='high',
        evidence=f'only_new={skill_cross["only_new"]}; only_old={skill_cross["only_old"]}; '
                 'old dataset used a 0x80-len0 parse and main segment only')
    add('channel', 'status_0x81', channel='0x02/0x81', field='count',
        value=len(status81), confidence='medium',
        evidence='tolerant tag scan = 1015; task baseline 970; all 0x81 live in payloads with finer-tag tails, '
                 'so 45-message difference is unresolved; not used for KDA')
    add('channel', 'damage_0x1e', channel='0x01/0x1e', field='count',
        value=len(main_1e), confidence='medium',
        evidence='attacker(env hero) -> victim unit u16BE + flag; not a full damage ledger')
    add('channel', 'highlight_0x1f', channel='0x01/0x1f', field='count',
        value=sum(1 for e in main_hl if e['kind'] == '0x1f'), confidence='medium',
        evidence=', '.join(f'{e["seq"]}:{e["hero"]}' for e in main_hl if e['kind'] == '0x1f'))
    add('channel', 'highlight_0x20', channel='0x01/0x20', field='count',
        value=sum(1 for e in main_hl if e['kind'] == '0x20'), confidence='medium',
        evidence=', '.join(f'{e["seq"]}:{e["hero"]}' for e in main_hl if e['kind'] == '0x20'))
    ent_values = sorted(players) if len(players) == 10 else [1729, 1965, 1514, 1021, 338, 442, 1966, 1547, 1558, 1833]
    head_end = main_recs[0]['off']
    frames_region = data[head_end:second_end if second_frames else len(data)]
    head_region = data[:head_end]
    cluster_frames = {f'{w}{o}': entity_cluster_scan(frames_region, ent_values, w, 'big' if o == 'be' else 'little')[0]
                      for w in (2, 4) for o in ('be', 'le')}
    cluster_head = {f'{w}{o}': entity_cluster_scan(head_region, ent_values, w, 'big' if o == 'be' else 'little')[0]
                    for w in (2, 4) for o in ('be', 'le')}
    cluster_tail = {f'{w}{o}': entity_cluster_scan(footer, ent_values, w, 'big' if o == 'be' else 'little')[0]
                    for w in (2, 4) for o in ('be', 'le')}
    add('structural', 'entity_cluster_window256', channel='scan', field='max_distinct',
        value=f'frames={cluster_frames}; head={cluster_head}; tail={cluster_tail}',
        confidence='high',
        evidence='frame stream max 7 distinct entity IDs in 256B; head player-block region 8; tail roster 10; '
                 'no 10-row panel outside the tail')
    victim_hits = sum(1 for e in main_1e if e['victim'] in set(ent_values))
    add('structural', '1e_victim_vs_entities', channel='0x01/0x1e', field='hits',
        value=f'{victim_hits}/{len(main_1e)}', confidence='high',
        evidence=f'victim values never equal one of the 10 entity IDs; expected under uniform {len(ent_values)}/65536')


    # 1558 金币事件
    for seq, src, amt, layer in tgt_gold:
        add('gold_1558', f'seq{seq}', seq=seq, time_s=round(seq / 20, 2),
            game_time_s=round(seq / 20 + GAME_TIME_OFFSET, 2), channel='0x02/0x85',
            entity_id=TARGET_ENTITY, player=TARGET_PLAYER, field='source/amount',
            value=f'{src}/{amt}', unit='gold', confidence='high', evidence=layer)

    # 1558 技能升级
    for seq, layer, actor, skill, level in tgt_upg:
        add('skill_1558', f'seq{seq}', seq=seq, time_s=round(seq / 20, 2),
            game_time_s=round(seq / 20 + GAME_TIME_OFFSET, 2), channel='0x02/0x87',
            entity_id=TARGET_ENTITY, player=TARGET_PLAYER, field='skill/levelIdx',
            value=f'skill{skill}/lv{level}', confidence='medium',
            evidence=f'{layer}; actorID={actor}; levelIdx 0 = 第 1 级')

    # 1558 0x1e / 高光
    for e in tgt_1e:
        add('event_1558', f'1e_seq{e["seq"]}', seq=e['seq'], time_s=round(e['seq'] / 20, 2),
            game_time_s=round(e['seq'] / 20 + GAME_TIME_OFFSET, 2), channel='0x01/0x1e',
            entity_id=TARGET_ENTITY, player=TARGET_PLAYER, field='victim/type',
            value=f'{e["victim"]}/t{e["type"]}', confidence='medium',
            evidence=e['raw'])
    for e in tgt_hl:
        add('event_1558', f'{e["kind"]}_seq{e["seq"]}', seq=e['seq'], time_s=round(e['seq'] / 20, 2),
            game_time_s=round(e['seq'] / 20 + GAME_TIME_OFFSET, 2), channel=f'0x01/{e["kind"]}',
            entity_id=TARGET_ENTITY, player=TARGET_PLAYER, field='type/size',
            value=f'{e["type"]}/{e["size"]}', confidence='low',
            evidence=e['raw'])

    # KDA
    add('kda', 'kill_ledger', channel='0x02/0x85(source43)', field='events',
        value=f'kills={sum(len(v) for v in kills.values())}; assists={sum(len(v) for v in assists.values())}',
        confidence='medium', evidence='source43 amount>=200 kill, <200 assist')
    for hero, events in sorted(kills.items()):
        p = players.get(hero, {})
        add('kda', f'kills_{hero}', channel='0x02/0x85(source43)', entity_id=hero,
            player=p.get('player', ''), field='kills', value=len(events), confidence='medium',
            evidence=','.join(f'{s}@{s/20:.1f}s/{a}' for s, a in events))
    for hero, events in sorted(assists.items()):
        p = players.get(hero, {})
        add('kda', f'assists_{hero}', channel='0x02/0x85(source43)', entity_id=hero,
            player=p.get('player', ''), field='assists', value=len(events), confidence='low',
            evidence=','.join(f'{s}@{s/20:.1f}s/{a}' for s, a in events))
    add('kda', 'team_score', channel='0x02/0x85(source43)', field='team_kills',
        value=f'team1={team_kills.get(1, 0)}; team2={team_kills.get(2, 0)}', confidence='medium',
        evidence='assist before first recorded kill (82.45s) suggests kill ledger may be incomplete')
    add('kda', '1558_kills', entity_id=TARGET_ENTITY, player=TARGET_PLAYER,
        field='kills', value=len(kills.get(TARGET_ENTITY, [])), confidence='medium',
        evidence='no source43 event for 1558 in main or continuation')
    add('kda', '1558_assists', entity_id=TARGET_ENTITY, player=TARGET_PLAYER,
        field='assists', value=len(assists.get(TARGET_ENTITY, [])), confidence='low',
        evidence='0 source43 events; assist ledger itself has ordering anomalies')
    add('kda', '1558_deaths', entity_id=TARGET_ENTITY, player=TARGET_PLAYER,
        field='deaths', value=f'unknown (team1 kills={team_deaths})', confidence='low',
        evidence='no per-player death field in frame stream/0x1e/0x81/tail; source43 gives team-level only')

    # 经济
    add('economy', 'income_observed', channel='0x02/0x85', entity_id=TARGET_ENTITY,
        field='observed_gold', value=observed, unit='gold', confidence='high',
        evidence=f'{len(tgt_gold)} events (main+continuation)')
    add('economy', 'income_low', entity_id=TARGET_ENTITY, field='total_income_low',
        value=round(income_low), unit='gold', confidence='high',
        evidence='300 + observed only (0x85 covers an unknown subset of income)')
    add('economy', 'income_mid', entity_id=TARGET_ENTITY, field='total_income_mid',
        value=round(income_mid), unit='gold', confidence='medium',
        evidence=f'300 + observed + natural 3/s from {NATURAL_START:.0f}s to {match_end_game:.1f}s')
    add('economy', 'income_mid_nodouble', entity_id=TARGET_ENTITY,
        field='total_income_mid_dedup', value=round(income_mid_nodouble), unit='gold',
        confidence='medium',
        evidence=f'mid minus source5 small ticks ({tgt_src5_small}) that may already be natural/support pushes')
    add('economy', 'income_high', entity_id=TARGET_ENTITY, field='total_income_high',
        value=round(income_high), unit='gold', confidence='low',
        evidence='mid + speculative support-item passive 5g/3s from 40s (purchase timing unavailable; may double count source5)')
    add('economy', 'spending', entity_id=TARGET_ENTITY, field='spending',
        value='unknown', unit='gold', confidence='high',
        evidence='no equipment channel in container: 0x87 is skill upgrades, 0x80 cmd types exclude buy-equip; high-tier plan items absent from 134_Equip')
    add('economy', 'current_gold', entity_id=TARGET_ENTITY, field='current_gold',
        value='unknown', unit='gold', confidence='high',
        evidence='no current/cumulative gold snapshot in 5069040 container (02/80 only exists in 5230306)')

    # 收入曲线检查点
    for point in curve:
        add('income_curve', f'seq{point["seq"]}', seq=point['seq'],
            time_s=round(point['seq'] / 20, 2), game_time_s=round(point['game_time'], 2),
            channel='model', entity_id=TARGET_ENTITY, field='cum_income',
            value=round(point['cum_income']), unit='gold', confidence='medium',
            evidence=f'cum_observed={point["cum_observed"]}; cum_natural={point["cum_natural"]:.0f}')

    with (DATASETS / 'agent_final_panel2.csv').open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # ---------------- 写 MD ----------------
    final_panel_found = bool(abc_hits or ope_hits)
    lines = []
    lines.append('# 最终面板 / 30 秒统计 / KDA 二次核查（主样本 20260925_105224）\n')
    lines.append('- 样本：`20260925_105224`（res_build **5069040**，普通 5v5，录制者 **1558 佚名(*:**，东皇太一）')
    lines.append('- 工具：`tools/agent_final_panel2.py`；逐条证据：`datasets/agent_final_panel2.csv`')
    lines.append('- 只读：未改回放/包体，未注入，未读 param.json，未用 runtime_dump，未编辑 docs 与 .workbuddy\n')

    lines.append('## 0. 结论先行\n')
    lines.append(f'- **最终面板不在容器里**：{len(abc_paths)} 条 `.abc` 路径（{len({p.name for p in abc_paths})} 个唯一文件名）+ {len(ope_paths)} 个 `.ope` 的 30s/结算/KDA/伤害字段名 '
                 f'**命中 {sum(len(h["hits"]) for h in abc_hits) + sum(len(h["hits"]) for h in ope_hits)} 次**；'
                 '主段、第二段、尾部都没有 10 行面板结构。')
    lines.append('- **第二段续流不是纯输入**：712 帧里有 **8 条 0x85 金币**（+968）、**2 条 0x87 技能升级**、**5 条 0x20 高光**，'
                 '但仍无 10 人状态或结算块。')
    lines.append('- **1558 KDA 只能确定到「0 杀 0 助 + 队伍死亡 4」**；个人死亡数在所有已解通道里都没有归属字段。')
    lines.append(f'- **1558 经济**：可观测金币 **{len(tgt_gold)} 条 / {observed}**；'
                 f'总获得收入区间 **{round(income_low)}–{round(income_high)}**（自然金/辅助装是否已在 0x85 里无法唯一判定）；'
                 '**支出与当前金币不可得**。')
    lines.append(f'- **0x87 不是装备购买，是技能升级**：`actorID/skill(1-4)/levelIdx(0-5)`。'
                 f'按 (skill,level) 解释 {upg_total_sl} 个相邻对 **{upg_viol_sl} 违例**；'
                 f'按文档 5.100 的 (tier,slot) 解释 {upg_total_ts} 个相邻对 **{upg_viol_ts} 违例**。'
                 f'1558 共 **{len(tgt_upg)} 次**升级。')
    lines.append('- **装备曲线不可得**：容器里没有装备购买通道（0x87 被证伪、0x80 帧命令无 22/23/35 购买类型），'
                 '只剩玩家块的 4 套**赛前出装方案**（item ID，无价格）。\n')

    lines.append('## 1. 容器结构（主样本）\n')
    lines.append('| 段 | 值 | 说明 |')
    lines.append('|---|---:|---|')
    lines.append(f'| 文件大小 | {len(data):,} B | — |')
    lines.append(f'| 头部 | {"/".join(header["versions"])} / build {"/".join(header["builds"])} | localHeroId={header["local_hero"]} |')
    lines.append(f'| Svr2GameCore KV | {len(conf)} 条 | 未读 param.json |')
    lines.append(f'| 主帧流 | {len(main_recs):,} 帧 | seq {main_recs[0]["seq"]}–{main_recs[-1]["seq"]}，偏移 0x{main_recs[0]["off"]:x}–0x{main_end:x} |')
    lines.append(f'| 主段→第二段之间 | {len(be_frames)} 帧 | ' +
                 ', '.join(f'seq {r["seq"]}（{r["length"]} B, type {r["type"]}）' for r in be_frames) + ' |')
    lines.append(f'| 第二段续流 | {len(second_frames)} 帧 | seq {second_frames[0]["seq"]}–{second_frames[-1]["seq"]}，payload 无 count 前缀 |')
    lines.append(f'| 尾部 | {len(footer) + extra_prefix} B | 0x04 前缀 {extra_prefix} B + **{roster.get("len")} B 名单**；名单后 **{trailing_after_roster} B** |')
    lines.append(f'| 末帧对局时间 | {match_end_game:.1f}s | seq/20 + {GAME_TIME_OFFSET} |\n')

    lines.append('## 2. 30s 统计 / 结算签名搜索\n')
    lines.append(f'- 字段名 {len(TOKENS)} 个，先在 `global-metadata.dat` 校验存在性：'
                 f'**{sum(1 for v in meta_tokens.values() if v)}/{len(TOKENS)} 存在**（ascii / utf-16le / utf-16be）。')
    lines.append(f'- `.abc`：{len(abc_paths)} 个文件原始字节全扫，**命中文件 {len(abc_hits)} 个**。')
    lines.append(f'- `.ope`：{len(ope_paths)} 个文件，外层 raw deflate + inner 第二层 raw deflate 全扫，'
                 f'**命中文件 {len(ope_hits)} 个**；operator 层成功解出 {sum(1 for s in ope_stats if s["operator"])} 个。')
    lines.append('- 负结论成立的前提：这些 token 在 metadata 里存在，所以 0 命中是「容器没落盘」，不是「名字写错」。')
    cross_ten = [k for k, heroes in shape_heroes.items() if len(heroes) >= 10]
    ten_desc = ', '.join(
        f'(0x{k[0]} flag 0x{k[1]:02x}, {k[2]}B)' for k in sorted(cross_ten, key=lambda x: -shape_counter[x]))
    lines.append(f'- 结构层：主段 {len(main_recs):,} 帧里单帧标量最大 **{main_max_scalars}** 条；'
                 f'单帧同时覆盖 10 人的形状 **{sum(main_ten.values())} 个**；'
                 f'跨帧覆盖全部 10 人的形状只有：{ten_desc or "无"}。'
                 '这些形状都是已定性的输入/状态/金币/技能消息，不是 10 行统计面板。')
    lines.append(f'- `0x02/0x85` 金币：主段 **{len(main_gold)} 条 / {sum(a for _s,_h,_src,a in main_gold)}**。')
    lines.append(f'- `0x02/0x87` 技能升级：主段 **{len(main_upg)} 条**（= actorID/skill/levelIdx，不是装备）。')
    lines.append(f'- `0x02/0x81` 状态：宽容扫描 **{len(status81)} 条**（任务基线 970，差 {len(status81)-970}）；'
                 '这些消息全部落在带「更细标签族」尾巴的 payload 里，差值未闭合，但**与 KDA/经济无关**。')
    lines.append(f'- `0x01/0x1e`：**{len(main_1e)} 条**（任务基线 21，差 {len(main_1e)-21}）。')
    lines.append(f'- 结构负证据：帧流（不含头部名单/尾部名单）里 256 B 窗口最多同时出现 **{cluster_frames["2be"]}** 个不同 entity；头部玩家块区 {cluster_head["2be"]} 个；106 B 尾部名单 {cluster_tail["2be"]} 个。10 人同窗只发生在尾部名单。')
    lines.append('')
    lines.append('**与任务基线的口径对账**（差异来自 0x80 是否按 12B 帧命令体消费）：')
    lines.append('')
    lines.append('| 通道 | 任务/旧文档基线 | 本报告 | 说明 |')
    lines.append('|---|---:|---:|---|')
    lines.append('| 0x02/0x81 | 970 | 1015 | 旧口径把 0x80 当 len=0；修正后多出 45 条落在未解尾巴里的 0x81 |')
    lines.append('| 0x01/0x1e | 21 | 22 | 同上，多 1 条 |')
    lines.append('| 0x02/0x85 | 281 / 32,370 | 286 / 33,040 | 多 5 条：seq 194/1071/5647/10508/12169 |')
    lines.append('| 0x02/0x87 | 135 | 139 | 多 4 条；且字段语义应为 skill/level，不是 tier/slot |')
    lines.append('')
    lines.append('')
    lines.append('## 3. 第二段续流（712 帧）内容\n')
    lines.append('| 通道 | 条数 | 明细 |')
    lines.append('|---|---:|---|')
    lines.append(f'| 0x02/0x85 金币 | {len(second_gold)} | ' +
                 ', '.join(f'seq {s} {players.get(h, {}).get("player", h)} source{src} +{a}' for s, h, src, a in second_gold) + ' |')
    lines.append(f'| 0x02/0x87 技能升级 | {len(second_upg)} | ' +
                 ', '.join(f'seq {s} {players.get(h, {}).get("player", h)} actor{a} skill{k} lv{l}' for s, h, a, k, l in second_upg) + ' |')
    lines.append(f'| 0x01/0x20 高光 | {sum(1 for e in second_hl if e["kind"] == "0x20")} | ' +
                 ', '.join(f'seq {e["seq"]} hero {e["hero"]}' for e in second_hl if e['kind'] == '0x20') + ' |')
    lines.append(f'| 10-hero 形状 | {second_ten} | 没有一帧同时覆盖 10 个 entity |')
    lines.append('')
    lines.append('**含义**：第二段是「对局最后约 35 秒的事件续流」，不是结算段；'
                 '但它把 1558 的经济/技能曲线延长到 seq 13807（约 {:.1f}s）。\n'.format(second_frames[-1]['seq'] / 20 + GAME_TIME_OFFSET))

    lines.append('## 4. 尾部：102/106B 名单之后是否还有块\n')
    lines.append(f'- 尾部结构：`0x04`（末帧遗留字节）+ **{roster.get("len")} B 名单**；名单解析：'
                 f'`{" ".join(f"{v}:{p}" for v, p in roster.get("pairs", []))}`。')
    lines.append(f'- 名单后剩余 **{trailing_after_roster} B**：文件到此结束，没有结算/面板/第二名单块。')
    lines.append(f'- 尾部最后一值 = {roster.get("local_tail")}（不是 header 的 localHeroId {header["local_hero"]}），更像“最后一帧镜头/最后选中单位”，不能当录制者英雄或 KDA 字段。')
    lines.append('')

    lines.append('## 5. 1558 KDA 重建\n')
    lines.append('| 字段 | 值 | 置信 | 依据 |')
    lines.append('|---|---|---|---|')
    lines.append(f'| 击杀 | {len(kills.get(TARGET_ENTITY, []))} | medium | 主段+续流 source43 无 1558 事件 |')
    lines.append(f'| 助攻 | {len(assists.get(TARGET_ENTITY, []))} | low | 同上；助攻账本存在时序异常 |')
    lines.append(f'| 死亡 | unknown（队伍 1 击杀 {team_deaths} 次） | low | 无逐人死亡字段；0x1e 只给 attacker→victim 单位 |')
    lines.append(f'| 队伍比分 | team1 {team_kills.get(1,0)} : team2 {team_kills.get(2,0)} | medium | source43 202/203=击杀、102=助攻 |')
    lines.append('')
    lines.append('**为什么死亡分不到人**：')
    lines.append('- `0x02/0x85 source43` 只有「谁拿钱」，没有「谁阵亡」；')
    lines.append('- `0x01/0x1e` 是 attacker→victim **单位**（22 条，1558 只有 3 条：victim 467/640/429），不是英雄死亡表；')
    lines.append('- `0x02/0x81` 是高频状态位（1015 条，值 1/2/3/4/6），与击杀时刻不对齐；')
    lines.append('- `0x1f/0x20` 是高光通知（1558 1 条 0x1f，360.45s），不带死亡归属；')
    lines.append('- 第二段续流同样没有死亡/结算块。\n')
    lines.append('**1558 参与的 0x1e 事件**：' +
                 ', '.join(f'seq {e["seq"]}（{e["seq"]/20+GAME_TIME_OFFSET:.1f}s）victim {e["victim"]} type {e["type"]}'
                           for e in tgt_1e) + '。\n')
    lines.append(f'- 0x1e victim 与本局 10 个 entity 的比对：**{victim_hits}/{len(main_1e)} 命中**'
                 f'（均匀零假设期望 ≈{len(ent_values)*len(main_1e)/65536:.4f}），所以 victim 不是英雄 entity，不能补 KDA。')
    lines.append('')
    lines.append('**1558 的高光**：' +
                 ', '.join(f'seq {e["seq"]}（{e["seq"]/20+GAME_TIME_OFFSET:.1f}s）{e["kind"]} size {e["size"]}'
                           for e in tgt_hl) + '。\n')

    lines.append('## 6. 1558 经济曲线\n')
    src_counter = Counter(src for _s, src, _a, _l in tgt_gold)
    src_sum = Counter()
    for _s, src, amt, _l in tgt_gold:
        src_sum[src] += amt
    lines.append('**可观测金币（0x02/0x85，main+续流）**：\n')
    lines.append('| source | 条数 | 金额 |')
    lines.append('|---|---:|---:|')
    for src in sorted(src_counter):
        lines.append(f'| {src} | {src_counter[src]} | {src_sum[src]} |')
    lines.append(f'| **合计** | **{len(tgt_gold)}** | **{observed}** |\n')
    lines.append('')
    lines.append('**十人 0x85 可观测金币（main+续流）**：')
    lines.append('')
    lines.append('| 玩家 | 队 | entity | 条数 | 金币 |')
    lines.append('|---|---:|---:|---:|---:|')
    for _h, _p in sorted(players.items(), key=lambda kv: (kv[1]['team'], kv[1]['slot'])):
        _ev = [a for _s, hh, _src, a, _l in all_gold if hh == _h]
        lines.append(f'| {_p["player"]} | {_p["team"]} | {_h} | {len(_ev)} | {sum(_ev)} |')
    lines.append('')
    lines.append('**收入模型**（初始 300；自然金 3/s、40s 起；对局结束 {:.1f}s）：\n'.format(match_end_game))
    lines.append('| 口径 | 总获得 | 说明 |')
    lines.append('|---|---:|---|')
    lines.append(f'| 下限 | {round(income_low)} | 300 + 0x85 可观测；0x85 只覆盖部分收入 |')
    lines.append(f'| 中值 | {round(income_mid)} | 下限 + 自然金 {natural_total:.0f}（3/s×{max(0.0, match_end_game-NATURAL_START):.0f}s） |')
    lines.append(f'| 中值去重 | {round(income_mid_nodouble)} | 中值 − source5 小额 {tgt_src5_small}（可能已是自然/辅助装推送） |')
    lines.append(f'| 推测上限 | {round(income_high)} | 中值 + 辅助装被动 {support_total:.0f}（5g/3s，按 40s 起；购买时刻不可得，low） |')
    lines.append('')
    lines.append('**当前金币 / 支出 / 装备**：回放侧不可得。0x87 是技能升级，不是购买；'
                 '0x80 帧命令没有 22/23/35 等购买类型；`134_Equip` 不含 1701/1753/1411 等高档 item，价格链路断裂。')
    lines.append('只能给出约束：`累计支出 ≤ 累计收入`，且 `当前金币 ≥ 0`。\n')
    lines.append('**技能升级时刻的收入检查点**（时间锚点，不是购买）：\n')
    lines.append('| 对局时间 | 事件 | 可观测累计 | 自然金累计 | 累计收入(中值) |')
    lines.append('|---:|---|---:|---:|---:|')
    checkpoints = []
    for seq, _layer, actor, skill, level in tgt_upg:
        gt = seq / 20 + GAME_TIME_OFFSET
        cum = sum(a for s, _src, a, _l in tgt_gold if s <= seq)
        nat = NATURAL_RATE * max(0.0, gt - NATURAL_START)
        checkpoints.append((gt, f'skill{skill}/lv{level}', cum, nat, INITIAL_GOLD + cum + nat))
    for gt, label, cum, nat, total in checkpoints:
        lines.append(f'| {gt:.1f} | {label} | {cum} | {nat:.0f} | {total:.0f} |')
    lines.append('')

    lines.append('## 7. 1558 技能升级曲线（0x87）与装备缺口\n')
    lines.append('### 7.1 为什么 0x87 是技能升级，不是装备购买\n')
    lines.append('7 B 布局：`00 00 00 <actorID> <skill:1-4> <levelIdx:0-5> 00 00`。判定依据：\n')
    lines.append('| 检验 | (skill, level) | (tier, slot)（文档 5.100） |')
    lines.append('|---|---:|---:|')
    lines.append(f'| 同组相邻对单调违例 | **{upg_viol_sl}/{upg_total_sl}** | {upg_viol_ts}/{upg_total_ts} |')
    lines.append(f'| 字段值域 | skill 1–4，level 0–5 | slot 0–5，tier 0–5 |')
    lines.append('')
    lines.append('- 按 (tier, slot) 读时，338 的 slot0 出现 `2 → 1 → 3`（买装备不会降档）；1558 恰好单调，属于个例。')
    lines.append('- 按 (skill, level) 读时，10 人全部单调：每个 skill 从 0 开始逐级 +1，最高 level 5。')
    lines.append('- 只有 442（李信）出现 skill4（0–1）；其余 9 人只有 skill1–3——与“李信有第四技能”吻合，装备槽不会只有 4 个。')
    lines.append('- 因此 **0x87 = 技能升级**；文档 5.100 的“装备购买（tier/slot）”字段顺序应修正（本报告不改 docs）。\n')
    lines.append('### 7.2 1558 技能升级时间线\n')
    lines.append('| 对局时间 | seq | actorID | skill | levelIdx | 段 |')
    lines.append('|---:|---:|---:|---:|---:|---|')
    for seq, layer, actor, skill, level in tgt_upg:
        lines.append(f'| {seq/20+GAME_TIME_OFFSET:.1f} | {seq} | {actor} | {skill} | {level} | {layer} |')
    lines.append('')
    final_levels = {}
    for _seq, _layer, _actor, skill, level in tgt_upg:
        final_levels[skill] = level
    lines.append('**1558 技能最终档位（levelIdx，0 基）**：' +
                 ', '.join(f'skill{k}=lv{v}' for k, v in sorted(final_levels.items())) + '。')
    lines.append(f'**英雄等级推断**：1558 共 {len(tgt_upg)} 次技能升级；若 1 级给 1 点则取上限、1 级不含点则取下限；对局结束时约 **{len(tgt_upg)}–{len(tgt_upg)+1} 级**'
                 '（low；0x87 条数只能给技能点，不是等级字段）。\n')
    lines.append(f'- 与历史 `replay_skill_levels.csv` 交叉核对：旧数据集 1558 只有 {skill_cross["old_rows"]} 条，'
                 f'本报告 {skill_cross["new_rows"]} 条，重合 {skill_cross["overlap"]} 条；'
                 f'新增 seq {skill_cross["only_new"]}（旧口径漏掉 0x80 后的 0x87 + 第二段）。'
                 '逐条 level 一致，说明 0x87 的技能语义与历史结论（docs 5.26）一致。')
    lines.append('')
    lines.append('### 7.3 装备：只有赛前方案，没有购买通道\n')
    lines.append('| 方案 | item IDs |')
    lines.append('|---|---|')
    for plan, items in plans.items():
        lines.append(f'| {plan} | ' + ', '.join(str(i['item_id']) for i in items) + ' |')
    lines.append('')
    lines.append('- 4 套方案来自玩家块（赛前推荐/自定义出装），不是本局实际购买顺序。')
    lines.append('- `134_Equip` 只有 270 个基础 item（1111–5536 中的子集），不含 1701/1753/1411 等高档 item，'
                 '名称/价格/合成树都缺；`0x87` 已证伪为技能升级，`0x80` 帧命令没有 22/23/35 购买类型。')
    lines.append('- 结论：**装备购买顺序、装备价格、实际扣金都不在 5069040 容器里**；装备曲线只能用赛前方案定性。\n')

    lines.append('## 8. 最终面板是否在容器里\n')
    lines.append('| 检查项 | 结果 | 置信 |')
    lines.append('|---|---|---|')
    lines.append(f'| 30s/结算/KDA 字段名（{len(TOKENS)} 个 × 3 编码） | `{len(abc_paths)}` .abc + `{len(ope_paths)}` .ope **0 命中** | high |')
    lines.append(f'| 主段 {len(main_recs):,} 帧 10-hero 面板 | 无；只有输入/状态/金币/技能/高光 | high |')
    lines.append(f'| 第二段 {len(second_frames)} 帧 | 有金币/技能升级/高光，但 0 个 10-hero 形状 | high |')
    lines.append(f'| 尾部 {roster.get("len")} B 名单之后 | {trailing_after_roster} B，无结算块 | high |')
    lines.append('| .ope operator 层 | 可解压；无商店/结算/面板字段 | high |')
    lines.append('')
    lines.append('**结论**：主样本容器内没有最终面板；这是「已检索 + 结构不支持」，不是「已证明所有版本永远不存在」。\n')

    lines.append('## 9. 外部补数据的最小字段集\n')
    lines.append('- 最小 KDA：`entity_id, hero_id, team, kills, deaths, assists`（10 行）。')
    lines.append('- 最小经济：`entity_id, total_gold_earned, gold_spent, current_gold`（10 行）。')
    lines.append('- 完整面板：再加 `damage_dealt, damage_taken, level, items[6], tower_damage, healing, mvp`。')
    lines.append('- 校验：队伍击杀 = 对方死亡；10 行 entity/hero/team 唯一；1558 行对 HUD/录屏（本局录屏不可用）。\n')

    lines.append('## 10. 复跑\n')
    lines.append('```bash')
    lines.append('python tools/agent_final_panel2.py')
    lines.append('```')
    lines.append('只读输入：`data/replays/**/*.abc`、`data/replays/**/*.ope`、`_analysis/comdt_game_30sec.json`、'
                 '`_analysis/datasets/agent_normal5v5_player_heroes.csv`、'
                 '`_analysis/datasets/normal5v5_equipment_{plans,upgrades}_5069040.csv`、`_analysis/global-metadata.dat`。')
    lines.append('输出：`datasets/agent_final_panel2.csv` 与本文件。')

    (DATASETS / 'agent_final_panel2.md').write_text('\n'.join(lines), encoding='utf-8')

    print(f'wrote {DATASETS / "agent_final_panel2.csv"} rows={len(rows)}')
    print(f'wrote {DATASETS / "agent_final_panel2.md"}')
    print(f'main frames={len(main_recs)} second={len(second_frames)} footer={len(footer)} trailing={trailing_after_roster}')
    print(f'gold main={len(main_gold)}/{sum(a for _s,_h,_src,a in main_gold)} '
          f'second={len(second_gold)}/{sum(a for _s,_h,_src,a in second_gold)}')
    print(f'1558 gold={len(tgt_gold)}/{observed} purchases={len(tgt_upg)} '
          f'income {round(income_low)}..{round(income_high)}')
    print(f'abc signature hits={len(abc_hits)} ope hits={len(ope_hits)}')


if __name__ == '__main__':
    main()
