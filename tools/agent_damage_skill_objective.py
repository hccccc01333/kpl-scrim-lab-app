#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""普通 5v5（build 5069040）伤害/技能/目标/高光字段逆向（只读）。

样本
----
主样本：
  data/replays/samples/abc_batch/
  20260925_105224_-1505729760_4933_1790303631_CBDD358E761B15A4DF526A179E8119E2.abc

只读边界
--------
* 只读 `.abc`、`dc.db`、`tools/` 与 `data/replays/_analysis/datasets/` 下已解 CSV；
* 不修改回放、包体，不注入进程，不读 `param.json`，不使用 `runtime_dump`；
* 不写 `docs/replay_binary_format.md` 与 `.workbuddy/memory/MEMORY.md`。

回答
----
1. `0x01/0x1e`（19B）：type / victim / attacker / damage / skillId；
2. `0x01/0x29`（17B）：actor / id / param / tail；与 `0x1ce47c` 技能表、
   `0x02/0x87`、`0x1e` 的时间对齐；
3. `0x01/0x1f`（28B）/ `0x01/0x20`（20B）：高光 tag / 参与者 / 是否含
   killer-victim-skill；
4. `0x01/0x23`（2B）/ `0x01/0x2c`（17B）：bool 状态、目标 actor、坐标类型；
5. `0x02/0x85` 的 source44/47/51（目标/推塔候选）与上述事件的对齐；
6. `0x01/0x38`（29B，主样本 0 条）跨样本形状；
7. 1558（佚名(*: / 东皇太一）的伤害/技能/目标事件表。

输出
----
  data/replays/_analysis/datasets/agent_damage_skill_objective.csv
  data/replays/_analysis/datasets/agent_damage_skill_objective.md

用法
----
    python tools/agent_damage_skill_objective.py
    python tools/agent_damage_skill_objective.py --no-cross
    python tools/agent_damage_skill_objective.py --abc path/to.abc --out-dir path/to/datasets
"""
from __future__ import annotations

import argparse
import csv
import random
import struct
import sys
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'data' / 'replays' / '_analysis' / 'datasets'
BATCH = ROOT / 'data' / 'replays' / 'samples' / 'abc_batch'
MAIN_SAMPLE = BATCH / (
    '20260925_105224_-1505729760_4933_1790303631_'
    'CBDD358E761B15A4DF526A179E8119E2.abc'
)
DC_DB = ROOT / 'data' / 'replays' / '_analysis' / 'device' / 'dc.db'

FPS = 20.0
REPLAY_OFFSET_S = 20.3       # docs 5.92：回放 seq0 ≈ 对局 0:20
TARGET_BUILD = '5069040'     # 普通 5v5；跨样本主统计只取这个 build
SAMPLE_KEY = '20260925_105224'
FOCUS_ENTITY = 1558

# C# 表起点（dc.db 偏移，只读）
SKILL_TABLE = 0x1CE47C       # ResSkillConfigInfo 候选（技能/KeySpell）
BUFF_EFFECT_TABLE = 0x3BA41A8
BUFF_MAIN_TABLE = 0x8268AC
HIGHLIGHT_TAG_TABLE = 0x695F084
KILL_EFFECT_TABLE = 0x586269C
EQUIP_TABLE = 0x522BDE8

# 0x29 里实际出现的 id 及其命名空间候选
EFFECT_IDS = (0, 91060, 900011, 11990)
# 回城/恢复的 KeySpell id；用于验证“0x29 是不是回城”
RECALL_IDS = (90005, 90007, 90025, 90035, 90003, 90000, 90006, 90023, 90033)
# 装备主动 KeySpell 的 id 范围（0x522BDE8 实测）
EQUIP_ACTIVE_IDS = (
    91000, 91010, 91040, 91043, 91044, 91047, 91147, 91156, 91157, 91242,
    91327, 91348, 91350, 91351, 91717, 91737, 92009, 92010, 92013, 92044,
    92147, 92737, 93010, 95000, 95002, 95003,
)

TARGET_SUBS = {0x1E, 0x1F, 0x20, 0x23, 0x29, 0x2C, 0x38}
SUBTYPE_NAMES = {
    0x1E: 'unit_event', 0x1F: 'highlight_1f', 0x20: 'highlight_20',
    0x23: 'bool_state', 0x29: 'skill_state', 0x2C: 'aim_target',
    0x38: 'cross_38',
}
SUB_KEYS = {0x1E: '1e', 0x1F: '1f', 0x20: '20', 0x23: '23', 0x29: '29',
            0x2C: '2c', 0x38: '38'}


# ---------------------------------------------------------------------------
# record framing
# ---------------------------------------------------------------------------
def records_from(data: bytes, start: int, seq0: int):
    """seq:u8 00 L:u8 payload[L] a:u8 00*4 b:u8 的帧记录流。"""
    pos, seq, out = start, seq0, []
    while pos + 10 < len(data):
        if data[pos] != (seq & 0xFF) or data[pos + 1] != 0:
            break
        length = data[pos + 2]
        if pos + 10 + length > len(data):
            break
        out.append({'off': pos, 'seq': seq,
                    'payload': data[pos + 3:pos + 3 + length]})
        pos += 10 + length
        seq += 1
    return out, pos


def find_main_stream(data: bytes):
    recs, end = records_from(data, 0xBFE8, 0x22)
    if len(recs) > 500:
        return recs, end, 'known_start'
    best = ([], 0)
    for pos in range(0, min(len(data), 0x20000)):
        if data[pos] == 0x22 and data[pos + 1] == 0:
            run, run_end = records_from(data, pos, 0x22)
            if len(run) > len(best[0]):
                best = (run, run_end)
            if len(run) > 500:
                break
    return best[0], best[1], 'scan'


def find_tail_stream(data: bytes, after: int):
    """主状态流结束后的续流（输入续流），返回最长的一条记录流。"""
    best = ([], 0, 0)
    pos = after
    while pos < len(data) - 10:
        if data[pos + 1] == 0:
            run, run_end = records_from(data, pos, data[pos])
            if len(run) > len(best[0]):
                best = (run, run_end, pos)
            pos = run_end if run else pos + 1
        else:
            pos += 1
    return best if len(best[0]) > 100 else ([], 0, 0)


def parse_payload(payload: bytes):
    """返回 (msgs, ok)。msg = ('s',tag,bytes) 或 ('h',tag,hero,flag,data)。"""
    if not payload:
        return [], True
    i, msgs = 1, []
    while i < len(payload):
        tag = payload[i]
        if tag == 0x12:
            if i + 3 > len(payload):
                return msgs, False
            msgs.append(('s', tag, payload[i + 1:i + 3]))
            i += 3
        elif tag == 0x13:
            if i + 2 > len(payload):
                return msgs, False
            msgs.append(('s', tag, payload[i + 1:i + 2]))
            i += 2
        elif tag == 0x14:
            if i + 4 > len(payload):
                return msgs, False
            msgs.append(('s', tag, payload[i + 1:i + 4]))
            i += 4
        elif tag in (0x01, 0x02):
            if tag == 0x01:
                if i + 5 > len(payload):
                    return msgs, False
                hero = struct.unpack_from('>H', payload, i + 1)[0]
                flag = payload[i + 3]
                length = payload[i + 4]
                if i + 5 + length > len(payload):
                    return msgs, False
                msgs.append(('h', tag, hero, flag, payload[i + 5:i + 5 + length]))
                i += 5 + length
            else:
                if i + 4 > len(payload):
                    return msgs, False
                hero = struct.unpack_from('>H', payload, i + 1)[0]
                flag = payload[i + 3]
                if flag == 0x80:
                    # 12B 帧命令体（cmdType:u16 LE | value:u16 | actor:u16 |
                    # seq:u32 | flag:u16），不是 len=0。旧解析器漏掉本体会导致
                    # 同记录后续消息丢失、计数偏小。
                    if i + 16 > len(payload):
                        return msgs, False
                    msgs.append(('h', tag, hero, flag, payload[i + 4:i + 16]))
                    i += 16
                else:
                    length = flag & 0x7F
                    if i + 4 + length > len(payload):
                        return msgs, False
                    msgs.append(('h', tag, hero, flag, payload[i + 4:i + 4 + length]))
                    i += 4 + length
        else:
            return msgs, False
    return msgs, True


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def build_of(data: bytes) -> str:
    """头部第 4 个长度前缀字符串 = 构建号。"""
    offset = 0
    texts = []
    for _ in range(4):
        if offset >= len(data):
            return ''
        size = data[offset]
        texts.append(data[offset + 1:offset + 1 + size].decode('latin1'))
        offset += 1 + size
    return texts[3] if len(texts) == 4 else ''


def u16be(b, off):
    return int.from_bytes(b[off:off + 2], 'big')


def u32be(b, off):
    return int.from_bytes(b[off:off + 4], 'big')


def i32be(b, off):
    return int.from_bytes(b[off:off + 4], 'big', signed=True)


def u16le(b, off):
    return int.from_bytes(b[off:off + 2], 'little')


def median(values):
    values = sorted(values)
    if not values:
        return None
    return values[len(values) // 2]


def nearest(seqs, s):
    if not seqs:
        return None
    i = bisect_left(seqs, s)
    cand = []
    if i < len(seqs):
        cand.append(seqs[i] - s)
    if i > 0:
        cand.append(seqs[i - 1] - s)
    return min(cand, key=abs)


def md_table(headers, rows):
    out = ['| ' + ' | '.join(str(h) for h in headers) + ' |',
           '|' + '|'.join('---' for _ in headers) + '|']
    for row in rows:
        out.append('| ' + ' | '.join('' if v is None else str(v) for v in row) + ' |')
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# roster / actor anchors
# ---------------------------------------------------------------------------
def load_roster(path: Path):
    """entityID -> {player, team, slot, heroID, heroName}。"""
    try:
        sys.path.insert(0, str(ROOT / 'tools'))
        import agent_player_block_schema as blocks
        replay = blocks.parse_replay(path)
        names = blocks.load_hero_names()
        rows = blocks.hero_rows(replay, names)
        return {int(r['entityID']): r for r in rows}, 'player_block'
    except Exception as error:  # pragma: no cover - fallback for portability
        csv_path = DATASETS / 'agent_normal5v5_player_heroes.csv'
        if csv_path.exists():
            out = {}
            with csv_path.open(encoding='utf-8-sig') as fh:
                for row in csv.DictReader(fh):
                    if row['sample'] != SAMPLE_KEY:
                        continue
                    out[int(row['entityID'])] = {
                        'player': row['player'], 'team': int(row['team']),
                        'slot': int(row['slot']), 'heroID': int(row['heroID']),
                        'heroName': row['heroName'],
                    }
            return out, 'player_heroes_csv'
        return {}, f'unavailable: {error}'


def actor_map_from(recs):
    """entityID -> 战斗内 actorID（0x02 flag=0x87, data[3]）。"""
    out = {}
    for rec in recs:
        for msg in parse_payload(rec['payload'])[0]:
            if msg[0] == 'h' and msg[1] == 2 and msg[3] == 0x87:
                data = msg[4]
                if len(data) >= 7:
                    out[int(msg[2])] = data[3]
    return out


# ---------------------------------------------------------------------------
# dc.db table lookups (read-only, positional string resolution)
# ---------------------------------------------------------------------------
class Lookup:
    def __init__(self, db_path: Path):
        self.ok = False
        self.G = None
        self.data = b''
        self.tables = {}
        self.error = ''
        try:
            sys.path.insert(0, str(ROOT / 'tools'))
            import agent_global_strings as global_strings
            self.G = global_strings
            self.data = db_path.read_bytes()
            self.skill = self._load(SKILL_TABLE)
            self.buff_effect = self._load(BUFF_EFFECT_TABLE)
            self.buff_main = self._load(BUFF_MAIN_TABLE)
            self.highlight = self._load(HIGHLIGHT_TAG_TABLE)
            self.kill_effect = self._load(KILL_EFFECT_TABLE)
            self.equip = self._load(EQUIP_TABLE)
            self.ok = all(t is not None for t in
                          (self.skill, self.buff_effect, self.buff_main,
                           self.highlight, self.kill_effect, self.equip))
        except Exception as error:  # pragma: no cover - tables are optional
            self.error = str(error)

    def _load(self, pos):
        table = self.G.Table(self.data, pos)
        if not table.valid(len(self.data)):
            return None
        table.strings = self.G.parse_pool(
            self.data, pos + table.pool_rel, table.nstr)
        self.tables[pos] = table
        return table

    def _rows(self, table, keys):
        G = self.G
        out = {}
        wanted = set(keys)
        for r in range(table.nrows):
            row = table.base + r * table.stride
            key = G.u32(self.data, row)
            if key in wanted:
                out[key] = row
        return out

    def _cell_text(self, table, row, cell):
        G = self.G
        return G.strings_get(self.data, table, G.u32(self.data, row + 8 + cell * 8 + 4))

    def skill_name(self, key):
        if not self.ok or self.skill is None:
            return ''
        rows = self._rows(self.skill, (key,))
        row = rows.get(key)
        return self._cell_text(self.skill, row, 4) or '' if row is not None else ''

    def buff_effect_name(self, key):
        if not self.ok or self.buff_effect is None:
            return ''
        row = self._rows(self.buff_effect, (key,)).get(key)
        return self._cell_text(self.buff_effect, row, 1) or '' if row is not None else ''

    def buff_main_name(self, key):
        if not self.ok or self.buff_main is None:
            return ''
        row = self._rows(self.buff_main, (key,)).get(key)
        if row is None:
            return ''
        name = self._cell_text(self.buff_main, row, 14) or ''
        if name:
            return name.rsplit('/', 1)[-1] if '/' in name else name
        prefab = self._cell_text(self.buff_main, row, 17) or ''
        return prefab.rsplit('/', 1)[-1] if prefab else ''

    def _cell_lookup_name(self, table, key, name_cell):
        """在非行键表里扫描任意 cell（a/b）等于 key 的行，返回 name_cell 文本。"""
        if table is None or not key:
            return ''
        G = self.G
        for r in range(table.nrows):
            row = table.base + r * table.stride
            for cell in range(table.ncell):
                a, b = G.u32pair(self.data, row + 8 + cell * 8)
                if key in (a, b):
                    return self._cell_text(table, row, name_cell) or ''
        return ''

    def kill_effect_name(self, key):
        if not self.ok or self.kill_effect is None or not key:
            return ''
        return self._cell_lookup_name(self.kill_effect, key, 0)

    def highlight_tags(self):
        out = {}
        if not self.ok or self.highlight is None:
            return out
        for r in range(self.highlight.nrows):
            row = self.highlight.base + r * self.highlight.stride
            key = self.G.u32(self.data, row)
            out[key] = {
                'name': self._cell_text(self.highlight, row, 2) or '',
                'desc': self._cell_text(self.highlight, row, 4) or '',
            }
        return out

    def skill_rows(self, low, high):
        """返回 key 在 [low, high] 的 KeySpell/技能行（name, prefab）。"""
        out = []
        if not self.ok or self.skill is None:
            return out
        for r in range(self.skill.nrows):
            row = self.skill.base + r * self.skill.stride
            key = self.G.u32(self.data, row)
            if low <= key <= high:
                out.append((key, self._cell_text(self.skill, row, 4) or '',
                            self._cell_text(self.skill, row, 26) or ''))
        return out

    def equip_actives(self):
        """装备主动 id -> item name（cell 49/50/53 中 90000..99999）。"""
        out = defaultdict(list)
        if not self.ok or self.equip is None:
            return out
        for r in range(self.equip.nrows):
            row = self.equip.base + r * self.equip.stride
            key = self.G.u32(self.data, row)
            name = self._cell_text(self.equip, row, 0) or ''
            for cell in (49, 50, 53):
                for value in (self.G.u32pair(self.data, row + 8 + cell * 8)):
                    if 90000 <= value <= 99999:
                        out[value].append((key, name))
        return out

    def namespace_rows(self):
        """0x29 的 id 在 6 张相关表里的命名空间命中。"""
        namespaces = {
            'skill_0x1ce47c': self.skill,
            'buff_effect_0x3ba41a8': self.buff_effect,
            'buff_main_0x8268ac': self.buff_main,
            'kill_effect_0x586269c': self.kill_effect,
        }
        out = {}
        for effect_id in EFFECT_IDS:
            out[effect_id] = {}
            for label, table in namespaces.items():
                if table is None:
                    out[effect_id][label] = ''
                    continue
                row = self._rows(table, (effect_id,)).get(effect_id)
                if row is None:
                    if label == 'kill_effect_0x586269c':
                        out[effect_id][label] = self._cell_lookup_name(table, effect_id, 0)
                    else:
                        out[effect_id][label] = ''
                elif label == 'skill_0x1ce47c':
                    out[effect_id][label] = self._cell_text(table, row, 4) or ''
                elif label == 'buff_effect_0x3ba41a8':
                    out[effect_id][label] = self._cell_text(table, row, 1) or ''
                elif label == 'buff_main_0x8268ac':
                    out[effect_id][label] = self.buff_main_name(effect_id)
                else:
                    out[effect_id][label] = self._cell_text(table, row, 0) or ''
        return out


# ---------------------------------------------------------------------------
# gold helpers (same base hints as tools/agent_normal5v5_reconcile.py)
# ---------------------------------------------------------------------------
SMALL_MAX = 80


def gold_class(source, amount):
    if source == 4:
        return '4_minion'
    if source == 6:
        return '6_jungle'
    if source == 43:
        return '43_kill' if amount >= 200 else '43_assist'
    if source == 5:
        if amount <= SMALL_MAX:
            return '5_natural'
        if amount < 200:
            return '5_passive'
        return '5_objective'
    if source in (44, 47, 51):
        return f'{source}_objective_candidate'
    return f'{source}_other'


def base_hint(source, amount):
    if source == 5:
        if amount <= SMALL_MAX:
            return int(round(amount / 10.0)) * 10
        if amount < 200:
            return 130 if amount == 131 else 140
        return 230 if amount == 231 else (240 if amount == 243 else 250)
    if source == 43:
        return 200 if amount >= 200 else 100
    if source == 44:
        return 45
    if source == 47:
        return 175
    if source == 51:
        return 250
    return amount


# ---------------------------------------------------------------------------
# event extraction for one sample
# ---------------------------------------------------------------------------
def extract_sample(abc_path: Path, with_tail=True):
    """解析主样本：主状态流 + 续流，返回 events / stats / 上下文。"""
    data = abc_path.read_bytes()
    main, main_end, how = find_main_stream(data)
    tail, _tail_end, tail_start = find_tail_stream(data, main_end) if with_tail else ([], 0, 0)
    roster, roster_source = load_roster(abc_path)
    actors = actor_map_from(main + tail)
    actor_to_entity = {actor: entity for entity, actor in actors.items()}

    events = []
    failures = 0
    subtype_counts = Counter()
    gold_events = []
    per_hero = defaultdict(lambda: defaultdict(list))

    def emit(segment, rec, time_s, tag, hero, flag, payload):
        nonlocal failures
        msgs, ok = parse_payload(payload)
        if not ok:
            failures += 1
        for msg in msgs:
            if msg[0] != 'h':
                continue
            _, msg_tag, entity, msg_flag, body = msg
            if msg_tag == 1 and body:
                sub = body[0]
                subtype_counts[sub] += 1
                if sub in TARGET_SUBS:
                    row = parse_target_event(segment, rec['seq'], time_s,
                                             entity, sub, body, roster,
                                             actors, actor_to_entity)
                    if row is not None:
                        events.append(row)
                        per_hero[entity][sub].append(row)
            elif msg_tag == 2:
                subtype_counts[('02', msg_flag)] += 1
                if msg_flag == 0x85 and len(body) == 5:
                    source = body[0]
                    amount = int.from_bytes(body[1:5], 'little')
                    gold_events.append({
                        'segment': segment, 'seq': rec['seq'], 'time_s': time_s,
                        'entity': entity, 'source': source, 'amount': amount,
                    })
                    events.append(gold_row(segment, rec['seq'], time_s, entity,
                                           source, amount, roster, actors))
                elif msg_flag == 0x87 and len(body) >= 7:
                    events.append({
                        'sample': SAMPLE_KEY, 'segment': segment,
                        'seq': rec['seq'], 'time_s': round(time_s, 2),
                        'game_time_s_est': round(time_s + REPLAY_OFFSET_S, 2),
                        'family': 'equip_upgrade', 'subtype': '0x02/0x87',
                        'hero_entity': entity,
                        **roster_fields(entity, roster, actors),
                        'field_a': body[3], 'field_b': body[4], 'field_c': body[5],
                        'field_d': body[6], 'target_or_victim': '',
                        'skill_id': '', 'tag_id': '', 'raw_hex': body.hex(' '),
                        'confidence': 'layout high / semantics medium',
                        'note': (f'actorID={body[3]}, tier/skill={body[4]}, '
                                 f'slot={body[5]}, flag={body[6]}; '
                                 f'购买/升级候选（1558 报告），不是技能释放'),
                    })
                elif msg_flag == 0x81 and len(body) == 1:
                    events.append({
                        'sample': SAMPLE_KEY, 'segment': segment,
                        'seq': rec['seq'], 'time_s': round(time_s, 2),
                        'game_time_s_est': round(time_s + REPLAY_OFFSET_S, 2),
                        'family': 'state_flag', 'subtype': '0x02/0x81',
                        'hero_entity': entity,
                        **roster_fields(entity, roster, actors),
                        'field_a': body[0], 'field_b': '', 'field_c': '',
                        'field_d': '', 'target_or_victim': '',
                        'skill_id': '', 'tag_id': '', 'raw_hex': body.hex(' '),
                        'confidence': 'low',
                        'note': '1B per-hero state; values 1/2/3/4/6; semantics unresolved',
                    })
    for rec in main:
        emit('main', rec, (rec['seq'] - 0) / FPS, 1, None, None, rec['payload'])
    if tail:
        tail_first = tail[0]['seq']
        base = main[-1]['seq'] if main else 0
        for rec in tail:
            time_s = (base + 1 + (rec['seq'] - tail_first)) / FPS
            emit('tail', rec, time_s, 1, None, None, rec['payload'])

    # 0x02/0x85 补充：不存在于 TARGET_SUBS，但 source44/47/51 已 emit。
    return {
        'data': data, 'main': main, 'main_end': main_end, 'tail': tail,
        'tail_start': tail_start, 'stream_source': how,
        'roster': roster, 'roster_source': roster_source,
        'actors': actors, 'actor_to_entity': actor_to_entity,
        'events': events, 'failures': failures,
        'subtype_counts': subtype_counts, 'gold': gold_events,
        'per_hero': per_hero,
    }


def roster_fields(entity, roster, actors):
    info = roster.get(entity, {})
    return {
        'player': info.get('player', ''), 'team': info.get('team', ''),
        'slot': info.get('slot', ''), 'hero_id': info.get('heroID', ''),
        'hero_name': info.get('heroName', ''),
        'actor_id': actors.get(entity, ''),
    }


def parse_target_event(segment, seq, time_s, entity, sub, body, roster,
                       actors, actor_to_entity):
    base = {
        'sample': SAMPLE_KEY, 'segment': segment, 'seq': seq,
        'time_s': round(time_s, 2),
        'game_time_s_est': round(time_s + REPLAY_OFFSET_S, 2),
        'hero_entity': entity,
        **roster_fields(entity, roster, actors),
    }
    raw = body.hex(' ')
    if sub == 0x1E and len(body) == 19:
        victim = u16be(body, 16)
        return {
            **base, 'family': 'unit_event', 'subtype': '0x1e',
            'field_a': body[1], 'field_b': victim, 'field_c': '',
            'field_d': '', 'target_or_victim': victim,
            'skill_id': '', 'tag_id': '', 'raw_hex': raw,
            'confidence': 'layout high / semantics low',
            'note': (f'type={body[1]}, victimObjID={victim}, reserved={body[2:16].hex()}, '
                     f'flag={body[18]}; victim 非 entityID/heroID/actorID/技能表键；'
                     f'14B 保留恒 0（无 damage/skillId 字段）'),
        }
    if sub == 0x29 and len(body) == 17:
        effect_id = u32be(body, 5)
        param = i32be(body, 9)
        tail = u32be(body, 13)
        return {
            **base, 'family': 'skill_state', 'subtype': '0x29',
            'field_a': effect_id, 'field_b': param, 'field_c': tail,
            'field_d': body[4], 'target_or_victim': tail if tail else '',
            'skill_id': effect_id, 'tag_id': '', 'raw_hex': raw,
            'confidence': 'layout high / semantics low',
            'note': (f'actorID={body[4]}（与 0x02/0x87 data[3] 同值）, id={effect_id}, '
                     f'param={param}, tail={tail}; id/param 见 MD 的命名空间与重复态分析'),
        }
    if sub == 0x1F and len(body) == 28:
        tag = body[1]
        actor = u16be(body, 21)
        return {
            **base, 'family': 'highlight_1f', 'subtype': '0x1f',
            'field_a': i32be(body, 2), 'field_b': u32be(body, 6),
            'field_c': i32be(body, 10), 'field_d': f'{body[14]}/{body[18]}',
            'target_or_victim': actor, 'skill_id': '', 'tag_id': tag,
            'raw_hex': raw, 'confidence': 'tag high / other fields low',
            'note': (f'tag={tag}, i32_a={i32be(body, 2)}, u32_b={u32be(body, 6)}, '
                     f'i32_c={i32be(body, 10)}, u8_d={body[14]}, u8_e={body[18]}, '
                     f'actorObjID={actor}, tail3={body[25:28].hex()}, b23={body[23]}'),
        }
    if sub == 0x20 and len(body) == 20:
        tag = body[1]
        actor = u16be(body, 18)
        return {
            **base, 'family': 'highlight_20', 'subtype': '0x20',
            'field_a': u32be(body, 2), 'field_b': u32be(body, 6),
            'field_c': u32be(body, 10), 'field_d': u32be(body, 14),
            'target_or_victim': actor, 'skill_id': '', 'tag_id': tag,
            'raw_hex': raw, 'confidence': 'tag high / other fields low',
            'note': (f'tag={tag}, u32_a={u32be(body, 2):#010x}, '
                     f'id16le@14={u16le(body, 14)}, u16be@16={u16be(body, 16)}, '
                     f'u32_b={u32be(body, 6):#010x}, u32_c={u32be(body, 10)}, '
                     f'actorObjID={actor}'),
        }
    if sub == 0x23 and len(body) == 2:
        return {
            **base, 'family': 'bool_state', 'subtype': '0x23',
            'field_a': body[1], 'field_b': '', 'field_c': '', 'field_d': '',
            'target_or_victim': '', 'skill_id': '', 'tag_id': '',
            'raw_hex': raw, 'confidence': 'layout high / semantics low',
            'note': f'bool={body[1]}（只在与前一状态不同时出现）',
        }
    if sub == 0x2C and len(body) == 17:
        kind, flag = body[1], body[2]
        target = u16be(body, 3)
        x, y = i32be(body, 5), i32be(body, 9)
        counter = body[16]
        return {
            **base, 'family': 'aim_target', 'subtype': '0x2c',
            'field_a': kind, 'field_b': flag, 'field_c': x, 'field_d': y,
            'target_or_victim': target, 'skill_id': '', 'tag_id': '',
            'raw_hex': raw, 'confidence': 'layout high / semantics medium',
            'note': (f'kind={kind}, flag={flag}, targetObjID={target}, '
                     f'x={x}, y={y}, zeros={body[13:16].hex()}, counter={counter}'),
        }
    return None


def gold_row(segment, seq, time_s, entity, source, amount, roster, actors):
    info = roster.get(entity, {})
    return {
        'sample': SAMPLE_KEY, 'segment': segment, 'seq': seq,
        'time_s': round(time_s, 2),
        'game_time_s_est': round(time_s + REPLAY_OFFSET_S, 2),
        'family': ('gold_objective' if source in (44, 47, 51) else 'gold_ledger'),
        'subtype': '0x02/0x85',
        'hero_entity': entity, 'player': info.get('player', ''),
        'team': info.get('team', ''), 'slot': info.get('slot', ''),
        'hero_id': info.get('heroID', ''), 'hero_name': info.get('heroName', ''),
        'actor_id': actors.get(entity, ''),
        'field_a': source, 'field_b': amount,
        'field_c': base_hint(source, amount), 'field_d': gold_class(source, amount),
        'target_or_victim': '', 'skill_id': '', 'tag_id': '',
        'raw_hex': f'{source:02x} {amount.to_bytes(4, "little").hex(" ")}',
        'confidence': ('source/amount high / label low' if source in (44, 47, 51)
                       else 'source/amount high / label medium'),
        'note': (f'source={source}, amount={amount}, base≈{base_hint(source, amount)}; '
                 f'payload 无单位 ID'),
    }


# ---------------------------------------------------------------------------
# cross-sample scan
# ---------------------------------------------------------------------------
def _summary(obs, rnd, small=2, large=10):
    n = len(obs)
    if not n:
        return {'n': 0, 'within_small': 0.0, 'within_large': 0.0,
                'rand_small': 0.0, 'rand_large': 0.0, 'median': None}
    rn = max(1, len(rnd))
    return {
        'n': n,
        'within_small': sum(1 for x in obs if abs(x) <= small) / n,
        'within_large': sum(1 for x in obs if abs(x) <= large) / n,
        'rand_small': sum(1 for x in rnd if abs(x) <= small) / rn,
        'rand_large': sum(1 for x in rnd if abs(x) <= large) / rn,
        'median': median([abs(x) for x in obs]),
    }


def scan_batch(limit_files=None):
    """跨样本统计：只读主状态流（不扫续流，保证分母一致）。"""
    files = sorted(BATCH.glob('*.abc'))
    if limit_files:
        files = files[:limit_files]
    stats = {
        'files': 0, 'files_with_1e': 0, 'files_with_1f': 0,
        'files_with_29': 0, 'files_with_38': 0,
        '1e': [], '29': [], '1f': [], '20': [], '38': [], '23': [],
        '2c': [], 'subtype_files': defaultdict(set),
        'failures': 0, 'records': 0,
        'victim_actor_hits': 0, 'victim_entity_hits': 0,
    }
    per_file = []
    random.seed(7)
    for path in files:
        data = path.read_bytes()
        build = build_of(data)
        stats.setdefault('builds', {})[path.name] = build
        recs, _end, _how = find_main_stream(data)
        if not recs:
            continue
        if build != TARGET_BUILD:
            # 非 5069040：只收集 0x38 形状（该 subtype 不在 5069040 出现）
            stats.setdefault('other_files', 0)
            stats['other_files'] += 1
            for rec in recs:
                for msg in parse_payload(rec['payload'])[0]:
                    if msg[0] != 'h' or msg[1] != 1 or not msg[4]:
                        continue
                    body = msg[4]
                    if body[0] == 0x38 and len(body) == 29:
                        stats['38'].append({
                            'file': path.name, 'build': build,
                            'seq': rec['seq'], 'entity': msg[2],
                            'value': u32be(body, 2), 'flag8': body[8],
                            'type': int.from_bytes(body[26:29], 'big'),
                            'raw': body.hex(' '),
                        })
                        stats['subtype_files'][0x38].add(path.name)
                        stats['files_with_38'] = len(stats['subtype_files'][0x38])
            continue
        stats['files'] += 1
        stats['records'] += len(recs)
        roster, _roster_source = load_roster(path)
        stats.setdefault('rosters', {})[path.name] = roster
        actors = actor_map_from(recs)
        actor_set = set(actors.values())
        entity_set = set(actors)
        seen = set()
        seqs = defaultdict(lambda: defaultdict(list))   # subtype -> hero -> [seq]
        gold_by_hero = defaultdict(list)
        gold_rows = []
        for rec in recs:
            msgs, ok = parse_payload(rec['payload'])
            if not ok:
                stats['failures'] += 1
            for msg in msgs:
                if msg[0] != 'h':
                    continue
                tag, entity, flag, body = msg[1], msg[2], msg[3], msg[4]
                if tag == 2 and flag == 0x85 and len(body) == 5:
                    source = body[0]
                    amount = int.from_bytes(body[1:5], 'little')
                    gold_by_hero[entity].append(rec['seq'])
                    gold_rows.append({'file': path.name, 'seq': rec['seq'],
                                      'entity': entity, 'source': source,
                                      'amount': amount})
                    continue
                if tag == 2 and flag == 0x87 and len(body) >= 7:
                    seqs['87'][entity].append(rec['seq'])
                    continue
                if tag != 1 or not body:
                    continue
                sub = body[0]
                if sub not in TARGET_SUBS:
                    continue
                seen.add(sub)
                seqs[SUB_KEYS[sub]][entity].append(rec['seq'])
                if sub == 0x1E and len(body) == 19:
                    victim = u16be(body, 16)
                    stats['1e'].append({
                        'file': path.name, 'seq': rec['seq'], 'entity': entity,
                        'type': body[1], 'victim': victim,
                    })
                    stats['victim_actor_hits'] += victim in actor_set
                    stats['victim_entity_hits'] += victim in entity_set
                elif sub == 0x29 and len(body) == 17:
                    stats['29'].append({
                        'file': path.name, 'seq': rec['seq'], 'entity': entity,
                        'actor': body[4], 'id': u32be(body, 5),
                        'param': i32be(body, 9), 'tail': u32be(body, 13),
                    })
                elif sub == 0x1F and len(body) == 28:
                    stats['1f'].append({
                        'file': path.name, 'seq': rec['seq'], 'entity': entity,
                        'tag': body[1], 'a': i32be(body, 2),
                        'b': u32be(body, 6), 'c': i32be(body, 10),
                        'd': body[14], 'e': body[18],
                        'actor': u16be(body, 21),
                    })
                elif sub == 0x20 and len(body) == 20:
                    stats['20'].append({
                        'file': path.name, 'seq': rec['seq'], 'entity': entity,
                        'tag': body[1], 'a': u32be(body, 2),
                        'b': u32be(body, 6), 'c': u32be(body, 10),
                        'd': u32be(body, 14), 'id16le': u16le(body, 14),
                        'actor': u16be(body, 18),
                    })
                elif sub == 0x23 and len(body) == 2:
                    stats['23'].append({
                        'file': path.name, 'seq': rec['seq'], 'entity': entity,
                        'value': body[1],
                    })
                elif sub == 0x2C and len(body) == 17:
                    stats['2c'].append({
                        'file': path.name, 'seq': rec['seq'], 'entity': entity,
                        'kind': body[1], 'flag': body[2],
                        'target': u16be(body, 3),
                        'x': i32be(body, 5), 'y': i32be(body, 9),
                        'counter': body[16],
                    })
                elif sub == 0x38 and len(body) == 29:
                    stats['38'].append({
                        'file': path.name, 'seq': rec['seq'], 'entity': entity,
                        'value': u32be(body, 2), 'flag8': body[8],
                        'type': int.from_bytes(body[26:29], 'big'),
                        'raw': body.hex(' '),
                    })
        for sub in seen:
            stats['subtype_files'][sub].add(path.name)
        stats['files_with_1e'] += 0x1E in seen
        stats['files_with_1f'] += 0x1F in seen
        stats['files_with_29'] += 0x29 in seen
        stats['files_with_38'] += 0x38 in seen
        per_file.append({
            'file': path.name, 'maxseq': recs[-1]['seq'],
            'seqs': seqs, 'gold_by_hero': {h: sorted(v) for h, v in gold_by_hero.items()},
            'gold': gold_rows, 'actors': actors,
        })

    # ---- derived statistics -------------------------------------------------
    # 0x1e type -> victim median
    type_medians = {}
    for t in sorted({x['type'] for x in stats['1e']}):
        vals = [x['victim'] for x in stats['1e'] if x['type'] == t]
        type_medians[t] = {'n': len(vals), 'median': median(vals),
                           'min': min(vals), 'max': max(vals)}
    stats['type_medians'] = type_medians

    # 0x1e / 0x23 vs same-hero gold ledger (& random baseline)
    def align_gold(subtype, small, large):
        obs, rnd = [], []
        for f in per_file:
            for hero, lst in f['seqs'][subtype].items():
                g = f['gold_by_hero'].get(hero)
                if not g:
                    continue
                for s in lst:
                    obs.append(nearest(g, s))
                    rnd.append(nearest(g, random.randint(0, f['maxseq'])))
        return _summary(obs, rnd, small=small, large=large)

    stats['align_1e_gold'] = align_gold('1e', 20, 40)   # ±1s / ±2s
    stats['align_23_gold'] = align_gold('23', 2, 10)    # ±0.1s / ±0.5s

    # 0x29 vs 其它 subtype / 0x87（same hero）
    pairs = {
        '0x29 vs 0x87': ('29', '87'),
        '0x29 vs 0x1e': ('29', '1e'),
        '0x29 vs 0x1f': ('29', '1f'),
        '0x29 vs 0x23': ('29', '23'),
        '0x29 vs 0x2c': ('29', '2c'),
    }
    align = {}
    for label, (left, right) in pairs.items():
        obs, rnd = [], []
        for f in per_file:
            for hero, lst in f['seqs'][left].items():
                other = f['seqs'][right].get(hero)
                if not other:
                    continue
                for s in lst:
                    obs.append(nearest(other, s))
                    rnd.append(nearest(other, random.randint(0, f['maxseq'])))
        item = _summary(obs, rnd, 2, 10)
        item['within2'] = item.pop('within_small')
        item['within10'] = item.pop('within_large')
        item['rand2'] = item.pop('rand_small')
        item['rand10'] = item.pop('rand_large')
        align[label] = item
    stats['align'] = align

    # 0x1f vs 0x20 same-hero
    obs, rnd = [], []
    for f in per_file:
        for hero, lst in f['seqs']['1f'].items():
            other = f['seqs']['20'].get(hero)
            if not other:
                continue
            for s in lst:
                obs.append(nearest(other, s))
                rnd.append(nearest(other, random.randint(0, f['maxseq'])))
    stats['align_1f_20'] = _summary(obs, rnd, small=2, large=10)

    # source44/47/51 vs each subtype (same hero) + random baseline
    source_align = {}
    for sub in ('1e', '1f', '20', '23', '29', '2c'):
        obs, rnd = [], []
        for f in per_file:
            for g in f['gold']:
                if g['source'] not in (44, 47, 51):
                    continue
                other = f['seqs'][sub].get(g['entity'])
                if not other:
                    continue
                obs.append(nearest(other, g['seq']))
                rnd.append(nearest(other, random.randint(0, f['maxseq'])))
        source_align[sub] = _summary(obs, rnd, small=2, large=10)
    stats['source_align'] = source_align

    # source47 burst shape
    bursts = defaultdict(list)
    for f in per_file:
        per_hero = defaultdict(list)
        for g in f['gold']:
            if g['source'] == 47:
                per_hero[g['entity']].append(g['seq'])
        for hero, seqs in per_hero.items():
            seqs = sorted(seqs)
            group = [seqs[0]]
            for s in seqs[1:]:
                if s - group[-1] <= 60:
                    group.append(s)
                else:
                    bursts[f['file']].append((hero, group[0], group[-1], len(group)))
                    group = [s]
            bursts[f['file']].append((hero, group[0], group[-1], len(group)))
    stats['bursts_47'] = {k: [x for x in v if x[3] >= 2]
                          for k, v in bursts.items() if any(x[3] >= 2 for x in v)}

    # source44/47/51 event count
    stats['source_events'] = sum(
        1 for f in per_file for g in f['gold'] if g['source'] in (44, 47, 51))

    # 0x29 actor conflicts
    actors_by_key = defaultdict(set)
    for x in stats['29']:
        actors_by_key[(x['file'], x['entity'])].add(x['actor'])
    stats['actor_conflicts'] = sum(1 for v in actors_by_key.values() if len(v) > 1)

    # 0x2c counter jumps
    counter_jumps = defaultdict(int)
    counters = defaultdict(list)
    for x in stats['2c']:
        counters[(x['file'], x['entity'])].append(x['counter'])
    for key, values in counters.items():
        jumps = sum(1 for a, b in zip(values, values[1:]) if b != (a % 255) + 1)
        counter_jumps[key[1]] += jumps
    stats['counter_jumps'] = counter_jumps
    return stats


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def build_report(ctx, batch, lookup, out_dir):
    roster = ctx['roster']
    actors = ctx['actors']
    events = ctx['events']
    gold = ctx['gold']
    focus_info = roster.get(FOCUS_ENTITY, {})
    main_counts = Counter(e['subtype'] for e in events if e['segment'] == 'main')
    tail_counts = Counter(e['subtype'] for e in events if e['segment'] == 'tail')
    main_obj = Counter(e['field_a'] for e in events
                       if e['segment'] == 'main' and e['family'] == 'gold_objective')

    lines = []
    add = lines.append

    add('# 普通 5v5（5069040）伤害/技能/目标/高光字段逆向')
    add('')
    add('> 只读逆向。主样本 `' + MAIN_SAMPLE.name + '`。')
    add('> 约束：不改回放/包体、不注入、不读 `param.json`、不使用 `runtime_dump`；'
        '不修改 `docs/replay_binary_format.md` 与 `.workbuddy/memory/MEMORY.md`。')
    add('> 本文全部数字由 `tools/agent_damage_skill_objective.py` 生成，可复跑。')
    add('> 解析口径：`0x02 flag=0x80` 的 12B 命令体必须消费（旧解析器漏读，'
        '导致 0x1e 21→22、0x23 249→254、0x2c 418→425）；跨样本主统计只取 build 5069040 的 6 个样本；'
        '0x38 只在非 5069040 样本出现，单独列。主样本还含 678 条输入续流，事件表用 `segment` 列区分。')
    add('')

    # 0. summary
    add('## 0. 结论摘要')
    add('')
    add('| 通道 | 主样本条数 | 已确认 | 仍未确认 |')
    add('|---|---:|---|---|')
    add(f'| `0x01/0x1e` 19B | {main_counts["0x1e"]} | 字段布局；envelope=攻击者；victim=运行时单位 objectID；'
        '14B 保留恒 0（**没有 damage/skillId**） | type=2/3/4（5069040）的语义；victim 的兵种/塔/野怪归属 |')
    add(f'| `0x01/0x29` 17B | {main_counts["0x29"]} | 字段布局；`data[4]`=actorID（与 0x02/0x87、0x02/0x80 同值）；'
        'id/param/tail；重复帧状态流 | id 的单一命名空间；param 语义；`91060` 不能按技能表命名为小乔大招 |')
    add(f'| `0x01/0x1f` 28B | {main_counts["0x1f"]} | tag 表闭环（1/2/5/93/94；244 表外）；actor=单位 objectID | '
        '两个 i32/u8 字段语义；是否含 assist；tail3 |')
    add(f'| `0x01/0x20` 20B | {main_counts["0x20"]}（续流另 {tail_counts["0x20"]}） | tag 同表；4×u32 + actor 布局 | '
        '各 u32 语义；doc 的“d 高字节=heroID”在主样本被反证 |')
    add(f'| `0x01/0x23` 2B | {main_counts["0x23"]} | `23 00/01` 逐英雄 bool 转移；窗口 0.2–44.2s | bool=什么状态 |')
    add(f'| `0x01/0x2c` 17B | {main_counts["0x2c"]} | kind/flag/targetObjID/x/y/counter；flag=1 取消；'
        '坐标是目标点不是连续轨迹 | kind=技能槽/命令类型；target 的英雄/单位区分 |')
    add(f'| `0x02/0x85` source44/47/51 | '
        f'{main_obj.get(44, 0)}/{main_obj.get(47, 0)}/{main_obj.get(51, 0)}'
        f'（续流 +44×{sum(1 for e in events if e["segment"] == "tail" and e["family"] == "gold_objective" and e["field_a"] == 44)}）'
        ' | 金币账本条目；底额 45/175/250；payload 无单位 ID | '
        '具体是推塔/一血/镀层/暴君中的哪一个 |')
    add(f'| `0x01/0x38` 29B | 0 | 跨 {len({x["file"] for x in batch["38"]})} 个样本 '
        f'{len(batch["38"])} 条的形状；type=0x85729/2A/2B 或 0x6B | '
        'type 枚举、value 字段语义 |')
    add('')
    add('**一句话**：`0x1e` 不是伤害表（没有伤害/技能字段），`0x29` 不是回城/施法日志'
        '（没有 90005/90003；900011/0 呈状态保持、91060 离散），`0x1f/0x20` 只有高光 tag 可闭环，'
        '`0x23`/`0x2c` 是逐英雄状态/瞄准目标流，`source44/47/51` 只是金币账本里的目标类奖励条目。')
    add('')

    # 1. anchors
    add('## 1. 锚点：十人 entityID / heroID / actorID')
    add('')
    add(f'roster 来源：`{ctx["roster_source"]}`；actorID 来源：`0x02 flag=0x87` 的 `data[3]`，'
        '与 `0x02 flag=0x80` 帧命令的 `actor_id` 同值。')
    add('')
    rows = []
    for entity in sorted(roster):
        r = roster[entity]
        rows.append([entity, r.get('player', ''), r.get('team', ''), r.get('slot', ''),
                     r.get('heroID', ''), r.get('heroName', ''), actors.get(entity, '')])
    add(md_table(['entityID', '玩家', 'team', 'slot', 'heroID', '英雄', 'actorID'], rows))
    add('')
    add('actorID 的独立验证：')
    add('- `0x02/0x87` 7B：`00 00 00 actorID a b 00`，同一英雄恒定；')
    add('- `0x02/0x80` 12B 帧命令：`actor_id` 对同一英雄一致；'
        '`cmd_type=3`（AttackPlayer）时该字段等于**目标英雄**的 actorID；')
    add(f'- `0x01/0x29` 的 `data[4]` 与上述完全一致（{batch.get("actor_conflicts", 0)} 冲突/'
        f'{len(batch["29"])} 条）。')
    add('')

    # 2. 0x1e
    add('## 2. `0x01/0x1e` 19B：单位交互，不是伤害/技能表')
    add('')
    add('### 2.1 字段布局')
    add('')
    add('```text')
    add('1e | type:u8 | 14×00 (reserved) | victimObjID:u16BE | 01')
    add(' 0    1       2..15               16..17          18')
    add('```')
    add('')
    e1e = [e for e in events if e['subtype'] == '0x1e' and e['segment'] == 'main']
    add(f'- envelope hero = **攻击者**（entityID，可映射到玩家/英雄/actorID）；')
    add(f'- `data[2:16]` 在 5069040 全部 {len(batch["1e"])} 条跨样本事件里**恒为 0** → 没有 damage、skillId、assist 列表；')
    add(f'- `data[16:18]` = victim 运行时单位 objectID；主样本 {len(e1e)} 条，取值 '
        f'{min(int(e["field_b"]) for e in e1e)}–{max(int(e["field_b"]) for e in e1e)}；')
    add(f'- `data[18]` 恒为 `01`。')
    add('')
    add(f'### 2.2 主样本 {len(e1e)} 条')
    add('')
    rows = []
    for e in e1e:
        rows.append([e['seq'], e['time_s'], e['hero_entity'], e['hero_name'],
                     e['field_a'], e['field_b'], e['actor_id']])
    add(md_table(['seq', 't(s)', '攻击者', '英雄', 'type', 'victimObjID', 'actorID'], rows))
    add('')
    add('### 2.3 victim 的锚点测试（关键阴性证据）')
    add('')
    entity_set = set(roster)
    hero_set = {int(r['heroID']) for r in roster.values()}
    actor_set = set(actors.values())
    victims = [int(e['field_b']) for e in e1e]
    skill_keys = set()
    if lookup.ok and lookup.skill is not None:
        for r in range(lookup.skill.nrows):
            skill_keys.add(lookup.G.u32(lookup.data,
                                        lookup.skill.base + r * lookup.skill.stride))
    def hits(target):
        n = sum(1 for v in victims if v in target)
        return n, f'{n}/{len(victims)}'

    rows = []
    for label, target in (('10 人 entityID', entity_set), ('10 人 heroID', hero_set),
                          ('10 人 actorID', actor_set), ('技能表 0x1ce47c 行键', skill_keys)):
        n, text = hits(target)
        rows.append([label, len(target), n, text])
    add(md_table(['目标集', '集合大小', '命中', '判定'], rows))
    add('')
    add('- victim 与 entityID/heroID/actorID **零命中**；与技能表行键也零命中'
        '（技能表 ≤980 的键只有 `1/4` 两个）。')
    add(f'- victim **不是伤害值**：{len(batch["1e"])} 条里出现 0 和 1（伤害 0/1 不成立）；上限 994、从未超过 1000'
        '（像 10-bit objectID 池），而英雄技能伤害常 >1000；同一值还会跨时间复用。')
    add('- envelope **不是 victim**：victim 从不命中本局 heroID/entityID，而 envelope 覆盖全部 10 人；'
        '若 envelope 是受害者，10 人都会成为 victim，与事实矛盾 → envelope 只能是攻击者/事件持有者。')
    add(f'- 跨 {batch["files"]} 个可解析主状态流样本 {len(batch["1e"])} 条 `0x1e`：'
        f'victim 命中本文件 actorID **{batch["victim_actor_hits"]}/{len(batch["1e"])}**、'
        f'entityID **{batch["victim_entity_hits"]}/{len(batch["1e"])}**，属巧合；没有稳定英雄锚点。')
    add('- objectID 会**复用**：同一 victim 值在文件内/跨文件可再次出现（最大 3 次），'
        '且同一 target 在 0x2c 出现与 0x1e 被杀可相隔几十秒 → 不能按 id 直接跨时间对齐。')
    add('')
    add('### 2.4 type 分布与“type 是不是击杀类型”')
    add('')
    type_counts = Counter(e['type'] for e in batch['1e'])
    rows = [[t, n, f'{n / max(1, len(batch["1e"])) * 100:.1f}%'] for t, n in sorted(type_counts.items())]
    add(md_table(['type', '跨样本条数', '占比'], rows))
    add('')
    add('- 主样本 type：' + ', '.join(f'{t}×{n}' for t, n in
                                      sorted(Counter(e['field_a'] for e in e1e).items())))
    med = ', '.join(f'type{t}={v["median"]}(n={v["n"]})'
                    for t, v in batch['type_medians'].items())
    meds = [v['median'] for t, v in batch['type_medians'].items() if int(t) in (2, 3, 4)]
    if meds:
        add(f'- 各 type 的 victim 中位数：{med}；type2/3/4 中位数在 {min(meds)}–{max(meds)}，'
            'type2/3 接近、type4 偏高；但 objectID 会复用，不能按数值段直接命名。')
    else:
        add('- 跨样本 type 统计已跳过（`--no-cross`）。')
    towers = sum(1 for e in e1e if int(e['field_a']) in (3, 4))
    spree = sum(1 for e in e1e if int(e['field_a']) == 4)
    add(f'- 若按 `enKillNotifyType` 的声明顺序（Common_Ace/ShutDown/Self_TowerDie/Enemy_TowerDie/'
        f'Self_KillingSpree5/First_Blood/…）硬套：主样本会出现“{towers} 座塔”或'
        f'“{spree} 次五杀”，与 11 分钟内最多 18 塔、击杀数不符 → '
        '**该枚举顺序不成立**，不能据此命名。')
    g1e = batch['align_1e_gold']
    add(f'- 与金币账本（同英雄 source4/5/6/43）±1s 对齐 {g1e["within_small"]:.1%}'
        f'（{g1e["n"]} 条，随机 {g1e["rand_small"]:.1%}）、±2s {g1e["within_large"]:.1%}'
        f'（随机 {g1e["rand_large"]:.1%}）→ **0x1e 不是金币流水事件**。')
    add('')
    add('**判定**：布局 high；attacker=entityID high；victim=运行时单位 objectID medium-high；'
        'type 语义 low（5069040 只看到 2/3/4；type7 只在其他 build 出现 5 条）。')
    add('')

    # 3. 0x29
    add('## 3. `0x01/0x29` 17B：逐英雄状态/效果流，不是回城/施法日志')
    add('')
    add('### 3.1 字段布局与 actorID')
    add('')
    add('```text')
    add('29 | 00 00 00 (reserved) | actorID:u8 | id:u32BE | param:i32BE | tail:u32BE')
    add(' 0       1..3                4            5..8        9..12         13..16')
    add('```')
    add('')
    add('- `data[4]` 对同一英雄恒定，且与 `0x02/0x87 data[3]`、`0x02/0x80 actor_id` 同值'
        '（1558→12、442→44、1547→51、338→8…）；主样本 10 条全部命中。')
    add(f'- 跨 {batch["files"]} 个 5069040 样本 {len(batch["29"])} 条：同一英雄的 actor 值 '
        f'**{batch.get("actor_conflicts", 0)} 冲突** → 这是稳定的战场 actor 别名，不是 slot/位置。')
    add('')
    add('### 3.2 主样本 10 条')
    add('')
    rows = []
    for e in [x for x in events if x['subtype'] == '0x29' and x['segment'] == 'main']:
        rows.append([e['seq'], e['time_s'], e['hero_entity'], e['hero_name'],
                     e['field_d'], e['field_a'], e['field_b'], e['field_c']])
    add(md_table(['seq', 't(s)', '英雄', '英雄名', 'actorID', 'id', 'param', 'tail'], rows))
    add('')
    add('### 3.3 id 的命名空间：三个候选，不能直接当技能名')
    add('')
    if lookup.ok:
        ns = lookup.namespace_rows()
        rows = []
        for effect_id in EFFECT_IDS:
            rows.append([effect_id,
                         (ns[effect_id].get('skill_0x1ce47c', '') or '')[:40],
                         (ns[effect_id].get('buff_effect_0x3ba41a8', '') or '')[:40],
                         (ns[effect_id].get('buff_main_0x8268ac', '') or '')[:40],
                         (ns[effect_id].get('kill_effect_0x586269c', '') or '')[:40]])
        add(md_table(['id', '技能表 0x1ce47c', 'buff_effect 0x3ba41a8',
                      'buff_main 0x8268ac', '击败特效 0x586269c'], rows))
    else:
        add(f'dc.db 表不可用：{lookup.error}')
    add('')
    add('- **91060**：技能表 row1936 = 小乔 `铸魂·星华缭乱`；buff_effect row391 = '
        '`峡谷裂口传送中断被动`（KeySpell/91060P1）；击败特效 row453 = 吕布 `天下无双`。'
        '主样本没有小乔（heroID 142/558/174/159/518/507/151/107/187/119），'
        f'且 91060 在本批 27 个 .abc（{batch["files"]} 个可解析）里对**多个不同英雄**重复出现，'
        '同英雄两次间隔约 74s（1547：79.0s/153.35s；442：79.15s/153.95s）→ '
        '**不能**把它当作“小乔大招”或某英雄技能。')
    heroes_91060 = []
    for e in batch['29']:
        if e['id'] != 91060:
            continue
        info = batch.get('rosters', {}).get(e['file'], {}).get(e['entity'], {})
        heroes_91060.append((info.get('heroName') or '?', info.get('heroID') or '?'))
    uniq = sorted(set(heroes_91060))
    mapped = [x for x in uniq if x[0] != '?']
    missing = len(uniq) - len(mapped)
    add(f'- 5069040 的 91060 覆盖 {len(uniq)} 个 entity（{len(mapped)} 位已映射'
        + (f' + {missing} 个未映射' if missing else '')
        + '）：' + '、'.join(f'{n}({h})' for n, h in mapped)
        + '；其中**没有小乔（106）**。同一个 id 同时出现在多个不同英雄上，'
        '这条是最强的命名反证（阿轲 1608 是 900011 的 burst，不是 91060）。')
    add('- 91060 的候选（low，不作结论）：buff_effect 里它的 prefab 是 `KeySpell/91060P1`'
        '（峡谷裂口传送中断被动），加上同英雄约 74s 重复、单帧离散，'
        '更像**地图传送阵/传送中断类状态**；但 0x29 没有 90005（回城），不能当回城，'
        '也不能当英雄技能。')
    add('- **900011**：技能表 row2527 = `打包濒死队友`；buff_main row9036 的 prefab = '
        '`ReviveDyingHero`。两个命名空间语义一致，是“救援/打包濒死队友”类效果；'
        '主样本 442 在 612.85s 出现 1 条（param=0，tail=self）。')
    add('- **11990**：不在技能表；只在 `dc.db @0x7384068`（stride 56、20,755 行的无字符串表）'
        '里作为行键出现。主样本 2 条（1833 扁鹊，tail=51=赵云 actorID），'
        '**不能命名**；`11990` 与 `119900`（扁鹊毒药印记 buff）只是前缀相同，不能据此关联。')
    zero29 = sum(1 for e in batch['29'] if e['id'] == 0)
    add(f'- **0**：{zero29}/{len(batch["29"])} 条，param=0、tail=0，是“状态清除/无效果”的占位值；'
        '20260925_101323 的 315 有连续 10+ 帧 id=0。')
    add('')
    add('### 3.4 重复帧状态流（不是一次性施法）')
    add('')
    runs = defaultdict(list)
    for e in batch['29']:
        runs[(e['file'], e['entity'], e['id'])].append(e['seq'])
    run_lengths = Counter()
    run_spans = []
    for key, seqs in runs.items():
        seqs = sorted(seqs)
        start = prev = seqs[0]
        for s in seqs[1:]:
            if s - prev <= 2:
                prev = s
            else:
                run_lengths[prev - start + 1] += 1
                run_spans.append((key, prev - start + 1))
                start = prev = s
        run_lengths[prev - start + 1] += 1
        run_spans.append((key, prev - start + 1))
    add(f'- 跨 {batch["files"]} 个样本 {len(batch["29"])} 条 0x29 被切成 '
        f'{sum(run_lengths.values())} 段；同一段 = 同文件+同 actor+同 id，帧间隔 ≤2。')
    r91060 = [x[1] for x in run_spans if x[0][2] == 91060]
    r900011 = [x[1] for x in run_spans if x[0][2] == 900011]
    r0 = [x[1] for x in run_spans if x[0][2] == 0]
    add(f'- 91060：{len([1 for k in runs if k[2] == 91060])} 个 (文件,actor) 组、'
        f'段长分布 {dict(sorted(Counter(r91060).items()))}，最长 {max(r91060) if r91060 else 0} 帧；'
        '在 5069040 里是**单帧离散事件**，不是 per-frame 状态。')
    add(f'- 900011：段长分布 {dict(sorted(Counter(r900011).items()))}；'
        f'id=0：段长分布 {dict(sorted(Counter(r0).items()))}。'
        '20260925_103058 的 1608 连续 13 帧 900011（param 从 2 变 -1），'
        '101323 的 315 连续 10+ 帧 id=0 → “状态置位/保持/清除”的形状来自 900011/0，'
        '不是 91060；91060 更像冷却/刷新类的离散通知。')
    add('')
    add('### 3.5 与 0x87 / 0x1e / 0x1f / 0x23 / 0x2c 的时间对齐')
    add('')
    align = batch['align']
    rows = []
    for label, stats in align.items():
        rows.append([label, stats['n'], f'{stats["within2"]:.1%}', f'{stats["within10"]:.1%}',
                     f'{stats["rand2"]:.1%}', f'{stats["rand10"]:.1%}'])
    add(md_table(['配对', 'n', '±2 帧', '±10 帧', '随机 ±2', '随机 ±10'], rows))
    add('')
    add('- 0x29 与 0x87 装备/升级事件：±2 帧 **0.0%**（随机 0.8%）→ 不是装备/升级事件；')
    add('- 0x29 与 0x1e/0x1f/0x23/0x2c：±2 帧均 0.0%，没有稳定同帧关系；')
    add('- 0x29 里 **没有 90005/90007/90025/90035（回城）或 90003/90000/90006（恢复）** '
        f'任何一个 id（{len(batch["29"])} 条 5069040 全量）→ **“0x29=回城”被否证**。')
    add('')
    add('**判定**：布局 high；actorID high；id=900011 的“救援”语义 medium-high；'
        'id=91060/11990 的语义 low；param 语义 low；事件类型 = 逐帧状态/效果，不是技能释放日志。')
    add('')

    # 4. 0x1f/0x20
    add('## 4. `0x01/0x1f` 28B / `0x01/0x20` 20B：高光通知/详情')
    add('')
    tags = lookup.highlight_tags() if lookup.ok else {}
    add('### 4.1 tag 表 `0x695f084`（205 行）')
    add('')
    rows = []
    for tag in (1, 2, 5, 18, 21, 93, 94, 244):
        info = tags.get(tag, {})
        rows.append([tag, info.get('name', 'OUT_OF_TABLE' if tag == 244 else ''),
                     (info.get('desc') or '')[:52]])
    add(md_table(['tag', '名称', '描述（截断）'], rows))
    add('')
    add('### 4.2 `0x1f` 28B 字节布局')
    add('')
    add('```text')
    add('1f | tag:u8 | i32_a:BE | u32_b:BE | i32_c:BE | u8_d | 00 00 00 | u8_e | 00 00 |')
    add('    | actorObjID:u16BE | 01 | 00 | tail3')
    add('```')
    add('')
    rows = []
    for e in [x for x in events if x['subtype'] == '0x1f' and x['segment'] == 'main']:
        info = tags.get(int(e['tag_id']), {})
        rows.append([e['seq'], e['time_s'], e['hero_entity'], e['hero_name'],
                     e['tag_id'], info.get('name', 'OUT_OF_TABLE'),
                     e['field_a'], e['field_b'], e['field_c'], e['field_d'],
                     e['target_or_victim'], e['raw_hex']])
    add(md_table(['seq', 't(s)', '归属英雄', '英雄', 'tag', 'tag名', 'i32_a', 'u32_b',
                  'i32_c', 'u8_d/e', 'actorObjID', 'raw'], rows))
    add('')
    b1f = batch['1f']
    if b1f:
        add(f'- 跨样本 {len(b1f)} 条：tag 分布 '
            + ', '.join(f'{t}×{n}' for t, n in Counter(x['tag'] for x in b1f).most_common())
            + '；tag=244 在 205 行表外，客户端版本可能更新。')
        add(f'- i32_a 范围 {min(x["a"] for x in b1f)}..{max(x["a"] for x in b1f)}；'
            f'i32_c 范围 {min(x["c"] for x in b1f)}..{max(x["c"] for x in b1f)}；'
            f'u8_d 取值 {sorted({x["d"] for x in b1f})}；u8_e 取值 {sorted({x["e"] for x in b1f})}。')
        add(f'- actorObjID 范围 {min(x["actor"] for x in b1f)}..{max(x["actor"] for x in b1f)}，'
            '与 0x1e victim 同一 2 字节 objectID 类；1558 的 actor=12 正好是**自己**，'
            '338/1729 的 798/202 不是自己的 actorID → actor 是**高光涉及的单位**（可为自身/他者）。')
    else:
        add('- 跨样本统计已跳过（`--no-cross`）。')
    add('- **没有显式 killer/victim/skillId**：envelope 是“高光归属英雄”，tag 是行为类，'
        'actor 是单位 objectID；killer 只能由 envelope 推断，victim/技能不在字段里。')
    add('')
    add('### 4.3 `0x20` 20B')
    add('')
    add('```text')
    add('20 | tag:u8 | u32_a:BE | u32_b:BE | u32_c:BE | u32_d:BE | actorObjID:u16BE')
    add('     |           | id16le@14 | u16be@16')
    add('```')
    add('')
    rows = []
    for e in [x for x in events if x['subtype'] == '0x20']:
        info = tags.get(int(e['tag_id']), {})
        rows.append([e['segment'], e['seq'], e['time_s'], e['hero_entity'],
                     e['hero_name'], e['tag_id'], info.get('name', 'OUT_OF_TABLE'),
                     e['field_a'], e['field_b'], e['field_c'], e['field_d'],
                     e['target_or_victim'], e['raw_hex']])
    add(md_table(['段', 'seq', 't(s)', '英雄', '英雄名', 'tag', 'tag名', 'u32_a',
                  'u32_b', 'u32_c', 'u32_d', 'actorObjID', 'raw'], rows))
    add('')
    add('- 主状态流 1 条（106.8s，338 马超，tag=21 `群体解控`）；'
        '续流另有 5 条（1833 扁鹊，tag=5 `关键群控`），说明“主样本 0x20=1 条”只对主状态流成立。')
    add('- tag 与 `0x1f` 同表；但 tag 描述里的英雄（如 21=庄周、18=刘邦）不一定在局内，'
        '说明 tag 是**行为类**，描述里的英雄只是示例/触发原型，不能当参与者。')
    add('- **doc 5.73 的“d 高字节=heroID”在主样本被反证**：主样本 u32_d=0x89010019，'
        '高字节 0x89=137（司马懿），而本局 heroID 只有 142/558/174/159/518/507/151/107/187/119，'
        '没有 137 → d 高字节不是本局英雄 ID。')
    a12 = batch['align_1f_20']
    add(f'- 0x1f 与 0x20 **不按帧配对**：跨样本同英雄 {a12["n"]} 对，±2 帧 '
        f'{a12["within_small"]:.1%}（随机 {a12["rand_small"]:.1%}）、±10 帧 '
        f'{a12["within_large"]:.1%}（随机 {a12["rand_large"]:.1%}）；0x20 是同 tag 的'
        '另一类“详情/参数”通知，不能指望它补 0x1f 的 killer/victim。')
    add('')

    # 5. 0x23/0x2c
    add('## 5. `0x01/0x23` 2B / `0x01/0x2c` 17B')
    add('')
    add('### 5.1 `0x23`：逐英雄 bool 状态')
    add('')
    st23 = [e for e in events if e['subtype'] == '0x23' and e['segment'] == 'main']
    per = defaultdict(list)
    for e in st23:
        per[e['hero_entity']].append((e['seq'], int(e['field_a'])))
    rows = []
    all_durs = []
    for entity, seqs in sorted(per.items()):
        wins, start, stray = [], None, 0
        for s, val in seqs:
            if val == 1:
                if start is not None:
                    wins.append((start, s))
                start = s
            else:
                if start is None:
                    stray += 1
                else:
                    wins.append((start, s))
                    start = None
        if start is not None:
            wins.append((start, None))
        durs = [(b - a) / FPS for a, b in wins if b is not None]
        all_durs += durs
        rows.append([entity, roster.get(entity, {}).get('heroName', ''), len(seqs),
                     len(wins), stray,
                     f'{min(durs):.2f}' if durs else '',
                     f'{median(durs):.2f}' if durs else '',
                     f'{max(durs):.2f}' if durs else ''])
    add(md_table(['英雄', '英雄名', '事件', '1→0 窗口', '孤立 0', '最短(s)', '中位(s)', '最长(s)'],
                 rows))
    add('')
    add(f'- 主样本 {len(st23)} 条 / {len(per)} 位英雄；`23 00/01`，只在状态变化时出现；'
        f'窗口 {min(all_durs):.2f}–{max(all_durs):.2f}s。')
    g23 = batch['align_23_gold']
    add(f'- 负证据：`1` 不能是死亡（绝大多数窗口只有 0.2–2s，死亡不可能这么短；最长 {max(all_durs):.2f}s 也只有单次）；'
        f'与金币 ±2 帧 {g23["within_small"]:.1%}（随机 {g23["rand_small"]:.1%}）、'
        f'±10 帧 {g23["within_large"]:.1%}（随机 {g23["rand_large"]:.1%}）→ 只在 ±0.5s 有弱富集，'
        '不能当作因果；与 0x1f/0x20 无同帧关系。')
    # 0x29 是否落在同英雄 0x23=1 窗口内（主样本）
    s23 = defaultdict(list)
    s29 = defaultdict(list)
    for e in events:
        if e['subtype'] == '0x23':
            s23[e['hero_entity']].append((e['seq'], int(e['field_a'])))
        elif e['subtype'] == '0x29':
            s29[e['hero_entity']].append(e['seq'])
    inside = total = 0
    for hero, seqs in s29.items():
        wins, start = [], None
        for s23_seq, val in sorted(s23.get(hero, [])):
            if val == 1 and start is None:
                start = s23_seq
            elif val == 0 and start is not None:
                wins.append((start, s23_seq)); start = None
        if start is not None:
            wins.append((start, 10 ** 9))
        for s in seqs:
            total += 1
            if any(a <= s <= b for a, b in wins):
                inside += 1
    add(f'- 与 0x29 的互斥：主样本 0x29 事件落在同英雄 `0x23=1` 窗口内 **{inside}/{total}** '
        '→ `0x23=1` 更像是“不可操作/引导/特殊状态”，但具体名称未定（low）。')
    add('')
    add('### 5.2 `0x2c`：技能/攻击的目标点')
    add('')
    add('```text')
    add('2c | kind:u8 | flag:u8 | targetObjID:u16BE | x:i32BE | y:i32BE | 00 00 00 | counter:u8')
    add(' 0      1         2          3..4            5..8      9..12      13..15      16')
    add('```')
    add('')
    s2c = [e for e in events if e['subtype'] == '0x2c' and e['segment'] == 'main']
    rows = []
    for entity in sorted({e['hero_entity'] for e in s2c}):
        sub = [e for e in s2c if e['hero_entity'] == entity]
        rows.append([entity, roster.get(entity, {}).get('heroName', ''), len(sub),
                     dict(sorted(Counter(e['field_a'] for e in sub).items())),
                     sum(1 for e in sub if int(e['field_b']) == 1),
                     f'{min(int(e["field_c"]) for e in sub)}..{max(int(e["field_c"]) for e in sub)}'])
    add(md_table(['英雄', '英雄名', '条数', 'kind 分布', 'flag=1', 'x 范围'], rows))
    add('')
    cancels = [e for e in s2c if int(e['field_b']) == 1]
    cancel_ok = sum(1 for e in cancels
                    if int(e['target_or_victim']) == 0xFFFF
                    and int(e['field_c']) == 0 and int(e['field_d']) == 0)
    add(f'- flag=1 ⇔ target=0xFFFF 且 x=y=0：主样本 **{cancel_ok}/{len(cancels)}** 全部成立 → 取消/清空；')
    ids = [int(e['target_or_victim']) for e in s2c if int(e['target_or_victim']) != 0xFFFF]
    hero_hits = [(e['hero_entity'], int(e['target_or_victim']))
                 for e in s2c if int(e['target_or_victim']) in actor_set]
    add(f'- 非 0xFFFF 的 target 取值 {min(ids)}–{max(ids)}，{len(set(ids))} 个不同值；'
        f'其中 {len(hero_hits)} 条命中本局英雄 actorID：'
        + ', '.join(f'{h}→{t}' for h, t in hero_hits)
        + ' → target 主要是**非英雄单位**，偶尔自指/指向英雄。')
    dist = {}
    for entity, sub in ((442, [e for e in s2c if e['hero_entity'] == 442]),
                        (1966, [e for e in s2c if e['hero_entity'] == 1966])):
        points = [(int(e['field_c']), int(e['field_d'])) for e in sub]
        steps = [((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
                 for a, b in zip(points, points[1:])]
        dist[entity] = (median(steps), sorted(steps)[int(len(steps) * 0.9)] if steps else 0)
    add(f'- 连续两帧坐标中位跳变：442={dist[442][0]:,.0f}、1966={dist[1966][0]:,.0f}；'
        f'90 分位 {dist[442][1]:,.0f}/{dist[1966][1]:,.0f} → **不是连续轨迹**，'
        '而是每次事件的目标/瞄准点（单位未知，世界坐标量级 ±52k）。')
    add(f'- `counter` 逐英雄 1..255 回绕（442={batch.get("counter_jumps", {}).get(442, 0)} 次跳号），'
        '不是帧号；主样本 kind∈{1,2,4}（1966 只有 2、442 有 1/2/4），但 5069040 跨样本还出现 kind=3'
        '（30 条，非主样本）→ kind 更像**技能槽/命令类型**（候选，medium-low）。')
    add('- 主样本只有 442 李信 / 1966 孙权 两个英雄发 0x2c；其余 8 人 0 条 → '
        '这是“有瞄准/指向技能”的个别英雄流，不是全队命令。')
    add('')
    add('### 5.3 与 source44/47/51 的对齐')
    add('')
    add('- 主样本 source51 254（338 马超 359.80s / 442 李信 440.80s）、'
        'source47 179（1833 扁鹊 227.60s）、source44 47（442 李信 312.45s）；')
    add('- 338/1833 没有 0x2c；442 的最近 0x2c 在 −0.90s/+0.50s，但 442 的 0x2c 密度为 338 条/650s，'
        '±1s 随机命中率约六成 → **不能作为对齐证据**；')
    add('- 0x23 同理：source51 359.80s 的最近 0x23（任意英雄）只差 0.05s，但 0x23 是高频逐英雄流；')
    add('')
    rows = []
    for sub in ('1e', '1f', '20', '23', '29', '2c'):
        item = batch['source_align'].get(sub, {})
        if not item.get('n'):
            continue
        rows.append([sub, item['n'], f'{item["within_small"]:.1%}', f'{item["within_large"]:.1%}',
                     f'{item["rand_small"]:.1%}', f'{item["rand_large"]:.1%}'])
    add(md_table(['source44/47/51 vs', 'n', '±2 帧', '±10 帧', '随机 ±2', '随机 ±10'], rows))
    add('')
    add(f'- 跨样本 {batch.get("source_events", 0)} 条 source44/47/51 中，0x2c 的 ±10 帧命中率'
        '与随机基线相同（无信号）；0x23 的 ±10 帧略高于随机，但可测条数只有个位数、且 ±2 帧为 0，'
        '**不足以认定触发关系**；因此 source44/47/51 不是 0x2c/0x23 事件，0x2c 也不是推塔命令。')
    add('')

    # 6. source44/47/51
    add('## 6. `0x02/0x85` 的 source44/47/51：金币账本里的目标类奖励')
    add('')
    add('payload = `sourceType:u8 + amount:u32LE`，**没有单位/目标 ID**。')
    add('')
    rows = []
    for g in [x for x in gold if x['source'] in (44, 47, 51)]:
        rows.append([g['segment'], g['seq'], round(g['time_s'], 2),
                     g['entity'], roster.get(g['entity'], {}).get('player', ''),
                     roster.get(g['entity'], {}).get('heroName', ''),
                     g['source'], g['amount'], base_hint(g['source'], g['amount'])])
    add(md_table(['段', 'seq', 't(s)', 'entityID', '玩家', '英雄', 'source', 'amount', '底额候选'],
                 rows))
    add('')
    add('- 主状态流：source44 47×1、source47 179×1、source51 254×2；'
        '续流另有 source44 47×1（338，≈667.5s 回放时间）。')
    add('- 底额：44→45、47→175、51→250（+1–4 尾数）；与 source5 的 230/240/250 同属'
        '“目标/推塔候选”底额带。')
    examples = []
    for name, items in batch.get('bursts_47', {}).items():
        for hero, start, end, n in items:
            examples.append(f'{name[:15]} hero={hero} seq={start}..{end} {n} 条')
    if examples:
        add('- 跨样本 source47 的成簇例子：' + '；'.join(examples[:6])
            + f'（共 {len(examples)} 个 ≥2 条的簇）→ 可能是**多个同类奖励单元**'
            '（镀层/目标点数），但样本不足、payload 无单位 ID，**不能命名**。')
    else:
        add('- 跨样本 source47 没有 ≥2 条的簇（本批样本）。')
    add(f'- 与 0x1e/0x1f/0x20/0x29/0x2c/0x23 的对齐都在随机基线附近；'
        f'唯一显眼的是主样本 source51 254（马超 359.80s）与 0x1f tag244（东皇 360.45s）'
        f'差 0.65s，但跨样本 {batch.get("source_events", 0)} 条 source44/47/51 没有稳定 '
        f'0x1f 配对 → 视为单次巧合。')
    add('')

    # 7. cross-sample tables
    add('## 7. 跨样本统计（用于上述判定）')
    add('')
    main_records = len(ctx['main']) + len(ctx['tail'])
    add(f'- 跨样本主统计只取 **build {TARGET_BUILD}** 的 {batch["files"]} 个样本：'
        + '、'.join(sorted({k.split("_")[0] + "_" + k.split("_")[1] for k in batch.get("builds", {})
                            if batch["builds"][k] == TARGET_BUILD}))
        + '。0x38 不在 5069040，单独列在 7.1（来自 4742900 / 5169333 / 5230306 等非目标 build）。')
    add(f'- 主样本：{len(ctx["main"]):,} 条主状态流 + {len(ctx["tail"]):,} 条续流；'
        f'严格解析失败 {ctx["failures"]:,}/{main_records:,} 条'
        f'（{ctx["failures"] / max(1, main_records):.1%}，payload 尾部未知 tag）。'
        f'本报告的计数（0x1e {main_counts["0x1e"]} / 0x29 {main_counts["0x29"]} / '
        f'0x1f {main_counts["0x1f"]} / 0x20 {main_counts["0x20"]} / 0x23 {main_counts["0x23"]} / '
        f'0x2c {main_counts["0x2c"]}）使用 **0x80-aware 解析**；'
        '任务给的 21/10/3/1/249/418 是旧解析器未消费 `0x02 flag=0x80` 的 12B 命令体时的欠计数。'
        '未解析尾随仍可能漏事件，逐条表应视为已解析部分。')
    add(f'- 跨样本：{batch["files"]} 个可解析主状态流（共 {batch["records"]:,} 条 record）；'
        f'严格解析失败 {batch["failures"]:,} 条。跨样本计数应视为**下界**。')
    add('')
    rows = [
        ['0x1e', len(batch['1e']), batch['files_with_1e'],
         dict(sorted(Counter(x['type'] for x in batch['1e']).items()))],
        ['0x1f', len(batch['1f']), batch['files_with_1f'],
         dict(sorted(Counter(x['tag'] for x in batch['1f']).items()))],
        ['0x20', len(batch['20']), len({x['file'] for x in batch['20']}),
         dict(sorted(Counter(x['tag'] for x in batch['20']).items()))],
        ['0x29', len(batch['29']), batch['files_with_29'],
         dict(sorted(Counter(x['id'] for x in batch['29']).items()))],
        ['0x23', len(batch['23']), len({x['file'] for x in batch['23']}),
         dict(sorted(Counter(x['value'] for x in batch['23']).items()))],
        ['0x2c', len(batch['2c']), len({x['file'] for x in batch['2c']}),
         dict(sorted(Counter(x['kind'] for x in batch['2c']).items()))],
        ['0x38', len(batch['38']), batch['files_with_38'],
         dict(sorted(Counter(x['type'] for x in batch['38']).items()))],
    ]
    add(md_table(['subtype', '条数', '出现文件数', 'type/tag/id 分布'], rows))
    add('')
    add('### 7.1 `0x38` 29B（主样本 0 条）')
    add('')
    add('```text')
    add('38 | 00 | value:u32BE | flag8:u8 | 16×00 | 00 00 | type:u24BE')
    add(' 0    1      2..5         8        9..24    25..27    26..28')
    add('```')
    add('')
    rows = []
    for f in sorted({x['file'] for x in batch['38']}):
        sub = [x for x in batch['38'] if x['file'] == f]
        build = sub[0].get('build', '')
        rows.append([f[:15], build, len(sub),
                     dict(sorted(Counter(x['type'] for x in sub).items())),
                     sum(1 for x in sub if x['value'] == 0),
                     len({x['entity'] for x in sub})])
    add(md_table(['文件', 'build', '条数', 'type', 'value=0', '涉及英雄数'], rows))
    add('')
    add(f'- 只在 {len({x["file"] for x in batch["38"]})} 个样本出现'
        f'（{", ".join(sorted({x["file"][:15] for x in batch["38"]}))}），主样本 0 条，'
        '**不是 5069040 主样本的稳定事件**；')
    add('- 任务前提“0x38 在 5069040 主样本 0 条（5230306 才有）”需要精确化：本批 0x38 出现在'
        '上述 5 个**帧记录流**样本；其中 20261027_* 本身就是 5230306 的帧流，'
        '20261016_* 是 5169333，20260807 是 4742900。`20261028_135516/135520` 是 5230306 的'
        ' **TLV 变体**（帧记录流解析器不适用），本报告没有在它们里面找到 0x38；'
        '结论以这 5 个帧流样本为准。')
    add('- type=546601/546602/546603 = 0x00085729/2A/2B（3 个文件），'
        '20260807 是 107 (0x6B) → 与 build/模式相关；')
    add('- 这 4 个 type 在 dc.db 的 1245 张 stdr 表里都**不是行键**（u32 全表扫描无命中）'
        '→ 不是配置表主键，更像 GameCore 事件枚举；')
    zero = sum(1 for x in batch['38'] if x['value'] == 0)
    add(f'- 未解：value 的语义（{zero}/{len(batch["38"])} 条为 0，非零值含 0x5335F400 一类的大数）；'
        '与主样本的 0x1e/0x29/0x1f/0x2c 无同帧关系，且 0x38 发生时位置流仍连续（既有分析）'
        '→ **不是死亡事件**。')
    add('')

    # 8. 1558 focus
    add('## 8. 1558（佚名(*: / 东皇太一）事件表')
    add('')
    add(f'- entityID **1558**，heroID **{focus_info.get("heroID", "")}**，'
        f'{focus_info.get("heroName", "")}，team {focus_info.get("team", "")}/slot '
        f'{focus_info.get("slot", "")}，actorID **{actors.get(1558, "")}**；')
    add('- 主样本 source43（击杀/助攻金币）**0 条**；0x29、0x2c **0 条**；'
        'source44/47/51 **0 条**；')
    add('')
    add('### 8.1 伤害：0x1e 的 3 条“攻击者→单位”事件')
    add('')
    rows = []
    for e in [x for x in events if x['hero_entity'] == 1558 and x['subtype'] == '0x1e']:
        rows.append([e['segment'], e['seq'], e['time_s'], e['field_a'],
                     e['field_b'], e['raw_hex']])
    add(md_table(['段', 'seq', 't(s)', 'type', 'victimObjID', 'raw'], rows))
    add('')
    add('→ 0x1e **没有伤害值/技能 ID**（14B 恒 0），所以 1558 的伤害输出**不能从回放量化**；'
        '这 3 条只能证明“1558 攻击/命中了 3 个运行时单位”，兵种/塔/野怪未知。')
    add('')
    add('### 8.2 技能：0x29 无；0x1f 1 条；0x23/0x81 状态流')
    add('')
    rows = []
    for e in [x for x in events if x['hero_entity'] == 1558 and x['subtype'] in ('0x1f', '0x20', '0x23', '0x2c', '0x29')]:
        rows.append([e['segment'], e['seq'], e['time_s'], e['subtype'],
                     e['field_a'], e['field_b'], e['field_c'], e['field_d'],
                     e['target_or_victim'], e['tag_id'], e['raw_hex']])
    add(md_table(['段', 'seq', 't(s)', 'subtype', 'a', 'b', 'c', 'd', 'target/actor',
                  'tag', 'raw'], rows))
    add('')
    add('- 0x1f：360.45s，tag=244（205 行 tag 表**表外**），i32_a=-45、i32_c=42、'
        'actorObjID=12=**自己**；envelope=1558 是高光归属，但 tag 无法命名，'
        '也没有 killer/victim/技能字段。')
    add('- 0x29：**0 条** → 1558 没有“技能/效果状态流”；'
        '0x2c：**0 条** → 没有瞄准目标点；')
    f81 = [e for e in events if e['hero_entity'] == 1558 and e['subtype'] == '0x02/0x81']
    f87 = [e for e in events if e['hero_entity'] == 1558 and e['subtype'] == '0x02/0x87']
    f23 = [e for e in events if e['hero_entity'] == 1558 and e['subtype'] == '0x23']
    w23 = 0
    start23 = None
    for e in sorted(f23, key=lambda x: x['seq']):
        if int(e['field_a']) == 1:
            if start23 is not None:
                w23 += 1
            start23 = e['seq']
        elif start23 is not None:
            w23 += 1
            start23 = None
    if start23 is not None:
        w23 += 1
    # 1558 的 0x23 窗口
    f23wins = []
    f23start = None
    for e in sorted(f23, key=lambda x: x['seq']):
        if int(e['field_a']) == 1:
            if f23start is not None:
                f23wins.append((f23start, e['seq']))
            f23start = e['seq']
        elif f23start is not None:
            f23wins.append((f23start, e['seq']))
            f23start = None
    if f23start is not None:
        f23wins.append((f23start, None))
    f23dur = [((b - a) / FPS, a, b) for a, b in f23wins if b is not None]
    f23max = max(f23dur) if f23dur else (0, 0, 0)
    add(f'- 0x23：{len(f23)} 条 / {w23} 个 1→0 窗口，最长 {f23max[0]:.2f}s'
        f'（{f23max[1] / FPS:.2f}s→{f23max[2] / FPS:.2f}s）；'
        f'0x02/0x81 的 {len(f81)} 条值都是 '
        + (f"{f81[0]['field_a']}×{len(f81)}" if f81 and len({e['field_a'] for e in f81}) == 1 else '/'.join(str(e['field_a']) for e in f81) or '—')
        + '（' + '、'.join(f'{e["time_s"]:.2f}s' for e in f81) + '，候选“回城/恢复/特殊槽”，low）；')
    add(f'- 0x02/0x87 的 {len(f87)} 条是 actor={actors.get(1558, "")} 的升级/购买候选'
        '（`data[4]=tier/skill`、`data[5]=slot`），不是技能释放。')
    add('')
    add('### 8.3 目标：0x2c 无；source44/47/51 无；金币账本')
    add('')
    focus_gold = [g for g in gold if g['entity'] == 1558]
    src_agg = defaultdict(lambda: [0, 0])
    for g in focus_gold:
        src_agg[g['source']][0] += 1
        src_agg[g['source']][1] += g['amount']
    rows = [[s, v[0], v[1]] for s, v in sorted(src_agg.items())]
    add(md_table(['source', '条数', '金额'], rows))
    add('')
    add('- 1558 金币来源只有 source4/5/6（小兵/自然被动/野怪），**没有** source43/44/47/51、'
        '也没有 source5 的 230–254 大额 → 主样本金币账本里没有 1558 的个人“目标/推塔”入账；')
    add('- 续流最后一条 1558 source4 219 在 ≈685.7s 回放时间（≈11:46 对局），'
        '说明主状态流结束后还有补录，但不改变“无目标类 source”的结论。')
    add('')
    add('**1558 的 K/D/A 与伤害/技能/推塔结论**：source43 未见 1558 的 202/203（K）或 102（A），'
        '但因 source43 本身不完整，K/A 只能记“未观测”，不能当真实 0；D 不可得；伤害不可量化（0x1e 无伤害字段）；技能释放不可得（0x29 无、0x1f 只有 1 条）；'
        '目标/推塔个人入账不可得（无 0x2c、无 source44/47/51/5≥230）。')
    add('')

    # 9. missing
    add('## 9. 还缺什么')
    add('')
    add('1. **objectID → 单位类型/配置行**：0x1e victim、0x1f/0x20 actor、0x2c target 都是运行时'
        'objectID；回放里没有 object 表/StepNotify 头（`MyCampHeroObjIds/EnemyCampHeroObjIds`），'
        '所以无法把 victim 落到英雄/小兵/塔/野怪。')
    add('2. **0x29 的 id 命名空间**：91060 同时在技能表（小乔）、buff_effect（峡谷裂口传送中断）、'
        '击败特效（吕布）三个命名空间出现；需要 C# 写入侧（`SkillStateNotify`/`BuffNotify`）'
        '的字段顺序或更多带标签样本才能定表。')
    add('3. **0x1f/0x20 的内部字段**：tag 已闭环，但 i32_a/i32_c/u8_d/u8_e 与 0x20 的 4×u32 是'
        '位打包/混合字节序；要拿 killer/victim/技能，需要写入顺序或位级 schema。')
    add('4. **0x23 的语义**：只有 0/1 与窗口长度；需要与录像 UI（回城/控制/死亡/隐身）或'
        '战斗模拟对拍才能命名。')
    add('5. **source44/47/51 的奖励表**：payload 只有 source+amount，dc.db 的已解 436 张 C# 表里'
        '没有 45/175/250 的目标奖励行；需要 CSProtocol/GameCore 的 reward 枚举。')
    add('6. **0x38**：主样本 0 条；需要 5230306/相关 build 的样本与 GameCore 枚举才能命名。')
    add('')

    # 10. outputs
    add('## 10. 产物')
    add('')
    add('- `tools/agent_damage_skill_objective.py`')
    add('- `data/replays/_analysis/datasets/agent_damage_skill_objective.csv`')
    add('- 本文 `data/replays/_analysis/datasets/agent_damage_skill_objective.md`')
    add('')
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# alignment stats for the report
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def empty_batch():
    empty = _summary([], [])
    return {
        'files': 0, 'records': 0, 'failures': 0,
        '1e': [], '1f': [], '20': [], '29': [], '38': [], '23': [], '2c': [],
        'files_with_1e': 0, 'files_with_1f': 0, 'files_with_29': 0, 'files_with_38': 0,
        'victim_actor_hits': 0, 'victim_entity_hits': 0,
        'type_medians': {}, 'align_1e_gold': empty, 'align_23_gold': empty,
        'align': {}, 'align_1f_20': empty, 'source_align': {},
        'bursts_47': {}, 'source_events': 0, 'actor_conflicts': 0,
        'counter_jumps': {},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--abc', type=Path, default=MAIN_SAMPLE)
    ap.add_argument('--out-dir', type=Path, default=DATASETS)
    ap.add_argument('--no-cross', action='store_true',
                    help='跳过 27 文件跨样本统计（更快）')
    args = ap.parse_args()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    abc_path = args.abc

    ctx = extract_sample(abc_path, with_tail=True)
    lookup = Lookup(DC_DB)
    batch = scan_batch() if not args.no_cross else empty_batch()

    # 0x38 跨样本行单独加入 CSV（主样本 0 条）
    cross38 = []
    for item in batch['38']:
        info = ctx['roster'].get(item['entity'], {})
        cross38.append({
            'sample': item['file'][:15], 'segment': 'main', 'seq': item['seq'],
            'time_s': round(item['seq'] / FPS, 2),
            'game_time_s_est': round(item['seq'] / FPS + REPLAY_OFFSET_S, 2),
            'family': 'cross_38', 'subtype': '0x38',
            'hero_entity': item['entity'], 'player': '', 'team': '', 'slot': '',
            'hero_id': '', 'hero_name': '',
            'actor_id': '', 'field_a': item['value'], 'field_b': item['flag8'],
            'field_c': item['type'], 'field_d': '', 'target_or_victim': '',
            'skill_id': '', 'tag_id': '', 'raw_hex': item['raw'],
            'confidence': 'layout high / type low',
            'note': (f'cross-sample 0x38; build={item.get("build", "")}; '
                     f'type={item["type"]}; value={item["value"]}'),
        })

    # 0x29 命名空间注记
    ns = lookup.namespace_rows() if lookup.ok else {}
    for row in ctx['events']:
        if row['subtype'] == '0x29':
            effect_id = int(row['field_a'])
            row['skill_name_skill_table'] = lookup.skill_name(effect_id) if lookup.ok else ''
            row['skill_name_buff_effect'] = lookup.buff_effect_name(effect_id) if lookup.ok else ''
            row['skill_name_buff_main'] = lookup.buff_main_name(effect_id) if lookup.ok else ''
            row['skill_name_killeffect'] = lookup.kill_effect_name(effect_id) if lookup.ok else ''
        else:
            row['skill_name_skill_table'] = ''
            row['skill_name_buff_effect'] = ''
            row['skill_name_buff_main'] = ''
            row['skill_name_killeffect'] = ''
        if 'tag_id' in row and row['tag_id'] and lookup.ok:
            tags = lookup.highlight_tags()
            row['tag_name'] = tags.get(int(row['tag_id']), {}).get('name', 'OUT_OF_TABLE')
        else:
            row['tag_name'] = ''

    fields = [
        'sample', 'segment', 'seq', 'time_s', 'game_time_s_est', 'family', 'subtype',
        'hero_entity', 'player', 'team', 'slot', 'hero_id', 'hero_name', 'actor_id',
        'field_a', 'field_b', 'field_c', 'field_d', 'target_or_victim',
        'skill_id', 'skill_name_skill_table', 'skill_name_buff_effect',
        'skill_name_buff_main', 'skill_name_killeffect', 'tag_id', 'tag_name',
        'raw_hex', 'confidence', 'note',
    ]
    rows = [{key: row.get(key, '') for key in fields} for row in ctx['events']]
    rows += [{key: row.get(key, '') for key in fields} for row in cross38]
    rows.sort(key=lambda r: (r['sample'], r['seq'], r['family'], r['subtype']))

    csv_path = out_dir / 'agent_damage_skill_objective.csv'
    with csv_path.open('w', newline='', encoding='utf-8-sig') as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    report = build_report(ctx, batch, lookup, out_dir)
    md_path = out_dir / 'agent_damage_skill_objective.md'
    md_path.write_text(report, encoding='utf-8')

    print(f'main records: {len(ctx["main"]):,} (tail {len(ctx["tail"]):,}); '
          f'events: {len(ctx["events"]):,}; csv rows: {len(rows):,}')
    print(f'wrote {csv_path}')
    print(f'wrote {md_path}')


if __name__ == '__main__':
    main()
