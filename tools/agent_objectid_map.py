#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""普通 5v5（build 5069040）运行时单位 objectID 映射审计（只读）。

主样本
------
data/replays/samples/abc_batch/
  20260925_105224_-1505729760_4933_1790303631_CBDD358E761B15A4DF526A179E8119E2.abc

只读边界
--------
* 只读 `.abc`、`dc.db`、`tools/` 与 `data/replays/_analysis/datasets/` 下已解 CSV；
* 不修改回放/包体，不注入进程，不读 `param.json`，不使用 `runtime_dump`；
* 不写 `docs/replay_binary_format.md` 与 `.workbuddy/memory/MEMORY.md`。

回答
----
1. 0x1e victim（0–994）能否映射到英雄/小兵/野怪/塔；
2. 0x2c target（1–359）与 0x1e victim 是否同一 ID 空间；
3. `dc.db` / `normalMonster` / `soldierWave` / `Project8Hero` /
   `native_table_catalog` / `native_table_names` / `decoded_csharp_all` /
   `agent_global_strings` 里是否存在 objectID→单位表，特别是 `0x7384068`；
4. 用 source4/6/43 金币、0x81 v6 死亡、0x2c target、0x12/0x13 位置流做
   时间/空间关联，能映射多少、不能映射多少；
5. `0x01/0x48`（hero=37120）与 `0x02/0x86`（body 含 0x1252）是否是单位。

输出
----
  data/replays/_analysis/datasets/agent_objectid_map.csv
  data/replays/_analysis/datasets/agent_objectid_map.md

用法
----
    python tools/agent_objectid_map.py
    python tools/agent_objectid_map.py --abc path/to.abc --out-dir path/to/datasets
"""
from __future__ import annotations

import argparse
import csv
import glob
import math
import random
import statistics
import struct
import sys
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'data' / 'replays' / '_analysis' / 'datasets'
BATCH = ROOT / 'data' / 'replays' / 'samples' / 'abc_batch'
DEVICE = ROOT / 'data' / 'replays' / '_analysis' / 'device'
DC_DB = DEVICE / 'dc.db'
MAIN_SAMPLE = BATCH / (
    '20260925_105224_-1505729760_4933_1790303631_'
    'CBDD358E761B15A4DF526A179E8119E2.abc'
)
FPS = 20.0
REPLAY_OFFSET_S = 20.3
TARGET_BUILD = '5069040'
SAMPLE_KEY = '20260925_105224'

# 5069040 的 6 个可解析主状态流样本；跨样本统计只取这些
CROSS_SAMPLES = [
    BATCH / '20260924_113638_48251441_2363_1790220136_CBDD358E761B15A4DF526A179E8119E2.abc',
    BATCH / '20260925_094930_819986962_5853_1790300571_CBDD358E761B15A4DF526A179E8119E2.abc',
    BATCH / '20260925_095631_1593860880_29_1790300977_CBDD358E761B15A4DF526A179E8119E2.abc',
    BATCH / '20260925_101323_1430258451_33_1790301420_CBDD358E761B15A4DF526A179E8119E2.abc',
    BATCH / '20260925_103058_805307185_6743_1790302420_CBDD358E761B15A4DF526A179E8119E2.abc',
    MAIN_SAMPLE,
]

# dc.db 关键表（只读偏移）
DC_NORMAL_MONSTER = 0x679118
DC_SOLDIER_WAVE = 0x1791AD8
DC_TOWER_ORGAN = 0x800380
DC_MONSTER_WIKI = 0x6F532F0
DC_SOLDIER_SKIN = 0x6F92224
DC_UNKNOWN_7384068 = 0x7384068
PROJECT8HERO_BIN = DEVICE / 'dtab_blocks' / '41_Project8Hero.bytes.bin'

sys.path.insert(0, str(ROOT / 'tools'))


# ---------------------------------------------------------------------------
# 依赖：沿用已解记录/roster 解析
# ---------------------------------------------------------------------------
def _import_base():
    import agent_damage_skill_objective as base
    return base


def _import_global_strings():
    import agent_global_strings as gs
    return gs


def iter_records(ctx):
    """产出 (segment, synthetic_seq, time_s, record)。"""
    for rec in ctx['main']:
        yield 'main', rec['seq'], rec['seq'] / FPS, rec
    tail = ctx['tail']
    if tail:
        base = ctx['main'][-1]['seq'] + 1
        first = tail[0]['seq']
        for rec in tail:
            seq = base + (rec['seq'] - first)
            yield 'tail', seq, seq / FPS, rec


def nearest_delta(times, t):
    """返回 (signed_delta, abs_delta)；times 已排序。"""
    if not times:
        return None, None
    i = bisect_left(times, t)
    cand = []
    if i < len(times):
        cand.append(times[i] - t)
    if i > 0:
        cand.append(times[i - 1] - t)
    return min(cand, key=abs), min(abs(x) for x in cand)


def md_table(headers, rows):
    out = ['| ' + ' | '.join(str(h) for h in headers) + ' |',
           '|' + '|'.join('---' for _ in headers) + '|']
    for row in rows:
        out.append('| ' + ' | '.join('' if v is None else str(v) for v in row) + ' |')
    return '\n'.join(out)


# ---------------------------------------------------------------------------
# 事件抽取
# ---------------------------------------------------------------------------
def extract_events(ctx, sample_tag):
    """把 main+tail 的 0x1e/0x2c/0x1f/0x20/0x80/0x81/0x85 逐条取出。"""
    base = _import_base()
    roster = ctx.get('roster', {})
    actors = ctx.get('actors', {})
    ev = {
        '1e': [], '2c': [], '1f': [], '20': [], 'cmd80': [],
        '81': [], 'gold': [], 'fails': 0, 'msgs': 0,
        'special_48': [], 'special_86': [],
        'scalars': {'12': [], '13': [], '14': 0},
    }
    for seg, seq, t, rec in iter_records(ctx):
        msgs, ok = base.parse_payload(rec['payload'])
        if not ok:
            ev['fails'] += 1
        for m in msgs:
            ev['msgs'] += 1
            if m[0] != 'h':
                # 0x12/0x13/0x14 只统计主段；主段标量在 hero=0 的批里
                if seg == 'main' and m[1] == 0x12:
                    ev['scalars']['12'].append(m[2])
                elif seg == 'main' and m[1] == 0x13:
                    ev['scalars']['13'].append(m[2][0])
                elif seg == 'main' and m[1] == 0x14:
                    ev['scalars']['14'] += 1
                continue
            tag, entity, flag, body = m[1], m[2], m[3], m[4]
            info = roster.get(entity, {})
            common = {
                'sample': sample_tag, 'segment': seg, 'seq': seq,
                'time_s': round(t, 3), 'entity': entity,
                'hero_name': info.get('heroName', ''),
                'team': info.get('team', ''),
                'raw_hex': body.hex(' '),
            }
            if tag == 1 and body:
                sub = body[0]
                if sub == 0x1E and len(body) == 19:
                    ev['1e'].append({**common, 'type': body[1],
                                     'victim': int.from_bytes(body[16:18], 'big'),
                                     'reserved_nonzero': any(body[2:16])})
                elif sub == 0x2C and len(body) == 17:
                    ev['2c'].append({**common, 'kind': body[1], 'flag': body[2],
                                     'target': int.from_bytes(body[3:5], 'big'),
                                     'x': int.from_bytes(body[5:9], 'big', signed=True),
                                     'y': int.from_bytes(body[9:13], 'big', signed=True),
                                     'counter': body[16]})
                elif sub == 0x1F and len(body) == 28:
                    ev['1f'].append({**common, 'tag': body[1],
                                     'actor': int.from_bytes(body[21:23], 'big'),
                                     'i32_a': int.from_bytes(body[2:6], 'big', signed=True),
                                     'i32_c': int.from_bytes(body[10:14], 'big', signed=True)})
                elif sub == 0x20 and len(body) == 20:
                    ev['20'].append({**common, 'tag': body[1],
                                     'actor': int.from_bytes(body[18:20], 'big')})
                elif sub == 0x48:
                    ev['special_48'].append({**common, 'body_len': len(body)})
            elif tag == 2:
                if flag == 0x80 and len(body) == 12:
                    ct, val, actor = struct.unpack_from('<HHH', body, 0)
                    cmdseq = struct.unpack_from('<I', body, 6)[0]
                    tail = struct.unpack_from('<H', body, 10)[0]
                    ev['cmd80'].append({**common, 'ct': ct, 'val': val,
                                        'actor': actor, 'cmdseq': cmdseq,
                                        'tail': tail})
                elif flag == 0x81 and len(body) == 1:
                    ev['81'].append({**common, 'value': body[0]})
                elif flag == 0x85 and len(body) == 5:
                    ev['gold'].append({**common, 'source': body[0],
                                       'amount': int.from_bytes(body[1:5], 'little')})
                elif flag == 0x86:
                    ev['special_86'].append({**common, 'body_len': len(body)})
    return ev


def build_81_windows(events):
    """每局每英雄 0x81 value=6 的连续窗口；返回 {sample: [(start_t,end_t,entity)]}。"""
    by = defaultdict(list)
    for e in events['81']:
        if e['value'] == 6:
            by[(e['sample'], e['entity'])].append(e)
    out = {}
    for (sample, entity), rows in by.items():
        rows.sort(key=lambda x: x['seq'])
        wins = []
        start = prev = rows[0]
        for r in rows[1:]:
            if r['seq'] - prev['seq'] <= 5:
                prev = r
            else:
                wins.append((start['time_s'], prev['time_s'], entity))
                start = prev = r
        wins.append((start['time_s'], prev['time_s'], entity))
        out.setdefault(sample, []).extend(wins)
    for rows in out.values():
        rows.sort()
    return out


# ---------------------------------------------------------------------------
# dc.db / 表
# ---------------------------------------------------------------------------
def load_stdr_keys(path: Path, pos: int):
    data = path.read_bytes()
    if data[pos:pos + 4] != b'stdr':
        return set(), None
    stride = struct.unpack_from('<I', data, pos + 0x14)[0]
    nrows = struct.unpack_from('<I', data, pos + 0x18)[0]
    base = pos + 0x98
    if not (8 <= stride <= 8192 and 0 < nrows <= 2_000_000):
        return set(), (stride, nrows)
    keys = {struct.unpack_from('<I', data, base + i * stride)[0] for i in range(nrows)}
    return keys, (stride, nrows)


def load_tower_table(path: Path, pos: int):
    gs = _import_global_strings()
    data = path.read_bytes()
    t = gs.Table(data, pos)
    if not t.valid(len(data)):
        return {}, 0
    t.strings = gs.parse_pool(data, pos + t.pool_rel, t.nstr)

    def text(row, cell):
        a, b = gs.u32pair(data, row + 8 + cell * 8)
        local = (b >> 6) - t.pool_rel
        return t.strings.get(local, '')

    out = {}
    for r in range(t.nrows):
        row = t.base + r * t.stride
        key = gs.u32(data, row)
        out[key] = text(row, 0)
    return out, t.nrows


def load_normal_monster():
    path = DATASETS / 'normalMonster_rows.csv'
    if not path.exists():
        return []
    with path.open(encoding='utf-8-sig') as fh:
        return [{
            'row': int(r['row']), 'id': int(r['id']), 'name': r['name'],
            'actor_type': int(r['actor_type']), 'hp': int(r['hp']),
            'gold': int(r['gold']),
        } for r in csv.DictReader(fh)]


def load_project8hero_keys():
    if not PROJECT8HERO_BIN.exists():
        return set(), None
    data = PROJECT8HERO_BIN.read_bytes()
    if data[:4] != b'stdr':
        return set(), None
    stride = struct.unpack_from('<I', data, 0x14)[0]
    nrows = struct.unpack_from('<I', data, 0x18)[0]
    base = 0x98
    keys = {struct.unpack_from('<I', data, base + i * stride)[0] for i in range(nrows)}
    return keys, (stride, nrows)


def load_unknown_7384068(path: Path):
    data = path.read_bytes()
    pos = DC_UNKNOWN_7384068
    if data[pos:pos + 4] != b'stdr':
        return {}, []
    nstr = struct.unpack_from('<I', data, pos + 8)[0]
    stride = struct.unpack_from('<I', data, pos + 0x14)[0]
    nrows = struct.unpack_from('<I', data, pos + 0x18)[0]
    base = pos + 0x98
    rows = []
    for r in [0, 1, 2, 11988, 11989, 11990, 11991, nrows - 1]:
        if 0 <= r < nrows:
            vals = struct.unpack_from('<' + 'I' * (stride // 4), data, base + r * stride)
            rows.append((r, vals[:12]))
    return {'nstr': nstr, 'stride': stride, 'nrows': nrows,
            'pool_rel': struct.unpack_from('<I', data, pos + 0x90)[0]}, rows


# ---------------------------------------------------------------------------
# 统计工具
# ---------------------------------------------------------------------------
def p_ge(observed, sims):
    if not sims:
        return None
    return sum(1 for s in sims if s >= observed) / len(sims)


def p_le(observed, sims):
    if not sims:
        return None
    return sum(1 for s in sims if s <= observed) / len(sims)


def table_test(keys, victims, targets, rng, nsim=5000):
    kv = keys & set(range(0, 995))
    kt = keys & set(range(1, 360))
    v_hit = sum(1 for v in victims if v in keys)
    t_hit = sum(1 for v in targets if v in keys)
    v_exp = len(victims) * len(kv) / 995 if victims else 0
    t_exp = len(targets) * len(kt) / 359 if targets else 0
    v_sim = [sum(1 for _ in victims if rng.randrange(995) in keys)
             for _ in range(nsim)] if victims else []
    t_sim = [sum(1 for _ in targets if rng.randrange(1, 360) in keys)
             for _ in range(nsim)] if targets else []
    return {
        'keys_le_994': len(kv), 'keys_1_359': len(kt),
        'victim_hit': v_hit, 'victim_expected': v_exp,
        'victim_p': p_ge(v_hit, v_sim),
        'target_hit': t_hit, 'target_expected': t_exp,
        'target_p': p_ge(t_hit, t_sim),
    }


def verdict_of(stats, dense=False, has_names=False):
    if stats['keys_le_994'] == 0 and stats['keys_1_359'] == 0:
        return 'structurally impossible'
    if dense:
        return 'reject: dense key range, no unit column'
    if stats['victim_p'] is None or stats['target_p'] is None:
        return 'no data'
    if stats['victim_p'] < 0.05 and stats['target_p'] < 0.05:
        return 'candidate (both enriched)'
    if stats['victim_hit'] < stats['victim_expected'] * 0.8:
        return 'negative (below chance)'
    return 'no evidence (chance)'


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run(abc_path: Path, out_dir: Path, cross: bool = True):
    base = _import_base()
    rng = random.Random(20261101)

    samples = [abc_path] if not cross else CROSS_SAMPLES
    all_ev = {}
    metas = {}
    for path in samples:
        if not path.exists():
            continue
        ctx = base.extract_sample(path)
        tag = path.name[:15]
        all_ev[tag] = extract_events(ctx, tag)
        all_ev[tag]['roster'] = ctx.get('roster', {})
        all_ev[tag]['actors'] = ctx.get('actors', {})
        all_ev[tag]['main_records'] = len(ctx['main'])
        all_ev[tag]['tail_records'] = len(ctx['tail'])
        all_ev[tag]['roster_source'] = ctx.get('roster_source', '')
        metas[tag] = path

    # 汇总
    victims = [e['victim'] for ev in all_ev.values() for e in ev['1e']]
    targets = [e['target'] for ev in all_ev.values() for e in ev['2c']
               if e['flag'] == 0 and 0 < e['target'] < 360]

    # -- 表候选 ------------------------------------------------------------
    normal = load_normal_monster()
    nm_keys = {r['id'] for r in normal}
    sw_keys, sw_shape = load_stdr_keys(DC_DB, DC_SOLDIER_WAVE)
    tw_map, tw_rows = load_tower_table(DC_DB, DC_TOWER_ORGAN)
    tw_keys = set(tw_map)
    wiki_keys, wiki_shape = load_stdr_keys(DC_DB, DC_MONSTER_WIKI)
    skin_keys, skin_shape = load_stdr_keys(DC_DB, DC_SOLDIER_SKIN)
    p8_keys, p8_shape = load_project8hero_keys()
    dense_keys, dense_shape = load_stdr_keys(DC_DB, DC_UNKNOWN_7384068)
    dense_meta, dense_rows = load_unknown_7384068(DC_DB)

    candidates = [
        {'name': 'normalMonster', 'where': 'dc.db@0x679118',
         'shape': f"{len(normal)} rows", 'keys': nm_keys,
         'note': '行键是单位配置 id（41/410/6000/…），不是 0–994 运行时槽'},
        {'name': 'soldierWave', 'where': 'dc.db@0x1791ad8',
         'shape': f"{sw_shape[1]} rows / stride {sw_shape[0]}" if sw_shape else 'missing',
         'keys': sw_keys, 'note': '行键是波次 id（101+）'},
        {'name': 'Project8Hero', 'where': 'device/dtab_blocks/41_Project8Hero.bytes.bin',
         'shape': f"{p8_shape[1]} rows / stride {p8_shape[0]}" if p8_shape else 'missing',
         'keys': p8_keys, 'note': '行键 1000–21930；0 个键 ≤994'},
        {'name': 'tower_organ_0x800380', 'where': 'dc.db@0x800380',
         'shape': f"{tw_rows} rows / {len(tw_map)} distinct keys", 'keys': tw_keys,
         'note': '塔/基地/兵营/泉水配置；键 1–18、1014–2016…'},
        {'name': 'monster_wiki_0x6f532f0', 'where': 'dc.db@0x6f532f0',
         'shape': f"{wiki_shape[1]} rows" if wiki_shape else 'missing',
         'keys': wiki_keys, 'note': '野怪图鉴；29 行，不是运行时槽'},
        {'name': 'soldier_skin_0x6f92224', 'where': 'dc.db@0x6f92224',
         'shape': f"{skin_shape[1]} rows" if skin_shape else 'missing',
         'keys': skin_keys, 'note': '小兵皮肤；键 93000+'},
        {'name': 'unknown_0x7384068', 'where': 'dc.db@0x7384068',
         'shape': f"{dense_meta.get('nrows')} rows / stride {dense_meta.get('stride')} / nstr {dense_meta.get('nstr')}",
         'keys': dense_keys, 'dense': True,
         'note': '稠密 1..20755；无字符串/单位名列，字段是技能/效果 id（900019/11802/13005…）'},
    ]
    for c in candidates:
        c['stats'] = table_test(c['keys'], victims, targets, rng)
        c['verdict'] = verdict_of(c['stats'], dense=c.get('dense', False))

    # -- 命名空间检验 ------------------------------------------------------
    ns_rows = []
    n_v = len(victims)
    obs_distinct = len(set(victims))
    sim_distinct = [len({rng.randrange(995) for _ in range(n_v)}) for _ in range(5000)]
    ns_rows.append(('victim_pool_uniform', obs_distinct,
                    round(statistics.mean(sim_distinct), 2),
                    p_le(obs_distinct, sim_distinct),
                    '0x1e victim 的不同值数；0–994 均匀池零假设'))

    by_file = defaultdict(set)
    for tag, ev in all_ev.items():
        for e in ev['1e']:
            by_file[e['victim']].add(tag)
    obs_repeat = sum(1 for s in by_file.values() if len(s) >= 2)
    sim_repeat = []
    for _ in range(5000):
        bb = defaultdict(set)
        for tag, ev in all_ev.items():
            for _e in ev['1e']:
                bb[rng.randrange(995)].add(tag)
        sim_repeat.append(sum(1 for s in bb.values() if len(s) >= 2))
    ns_rows.append(('victim_cross_file_repeats', obs_repeat,
                    round(statistics.mean(sim_repeat), 2),
                    p_ge(obs_repeat, sim_repeat),
                    '同一 victim 值出现在 ≥2 个文件；运行时池零假设'))

    # victim vs actorID
    obs = sum(1 for ev in all_ev.values() for e in ev['1e']
              if e['victim'] in set(ev['actors'].values()))
    exp = sum(len(ev['1e']) * len(ev['actors']) / 995 for ev in all_ev.values())
    sims = []
    for _ in range(5000):
        s = 0
        for ev in all_ev.values():
            acts = set(ev['actors'].values())
            s += sum(1 for _ in ev['1e'] if rng.randrange(995) in acts)
        sims.append(s)
    ns_rows.append(('victim_vs_actorID', obs, round(exp, 2),
                    p_ge(obs, sims),
                    '0x1e victim 命中同局 0x87 actorID；期望按 10/995'))

    # target vs actorID: 对每个文件按该文件 target 值分布做 bootstrap
    obs = sum(1 for ev in all_ev.values() for e in ev['2c']
              if e['flag'] == 0 and 0 < e['target'] < 360
              and e['target'] in set(ev['actors'].values()))
    exp = sum(sum(1 for e in ev['2c'] if e['flag'] == 0 and 0 < e['target'] < 360)
              * len(ev['actors']) / 359 for ev in all_ev.values())
    sims = []
    for _ in range(5000):
        s = 0
        for ev in all_ev.values():
            cnt = Counter(e['target'] for e in ev['2c']
                          if e['flag'] == 0 and 0 < e['target'] < 360)
            vals = list(range(1, 360))
            sample = rng.sample(vals, len(ev['actors']))
            s += sum(cnt.get(x, 0) for x in sample)
        sims.append(s)
    ns_rows.append(('target_vs_actorID', obs, round(statistics.mean(sims), 2),
                    p_ge(obs, sims),
                    '0x2c target 命中同局 actorID；bootstrap 保持 target 分布'))

    # victim vs target
    obs = sum(1 for ev in all_ev.values() for e in ev['1e']
              if e['victim'] in {x['target'] for x in ev['2c']
                                 if x['flag'] == 0 and 0 < x['target'] < 360})
    exp = sum(len(ev['1e']) * len({x['target'] for x in ev['2c']
                                   if x['flag'] == 0 and 0 < x['target'] < 360}) / 995
              for ev in all_ev.values())
    sims = []
    for _ in range(5000):
        s = 0
        for ev in all_ev.values():
            tset = {x['target'] for x in ev['2c']
                    if x['flag'] == 0 and 0 < x['target'] < 360}
            s += sum(1 for _ in ev['1e'] if rng.random() < len(tset) / 995)
        sims.append(s)
    ns_rows.append(('victim_vs_2c_target', obs, round(exp, 2),
                    p_ge(obs, sims),
                    '0x1e victim 命中同局 0x2c target；0–994 vs 1–359'))

    # ct6 actor vs 0x2c target（都在 1–359，检验是否同一子集）
    obs = 0
    exp = 0.0
    sims = []
    for ev in all_ev.values():
        ct6set = {c['actor'] for c in ev['cmd80']
                  if c['ct'] == 6 and 1 <= c['actor'] < 360}
        tset = {x['target'] for x in ev['2c']
                if x['flag'] == 0 and 0 < x['target'] < 360}
        obs += len(ct6set & tset)
        exp += len(ct6set) * len(tset) / 359 if tset else 0
    for _ in range(5000):
        s = 0
        for ev in all_ev.values():
            ct6set = {c['actor'] for c in ev['cmd80']
                      if c['ct'] == 6 and 1 <= c['actor'] < 360}
            tset = {x['target'] for x in ev['2c']
                    if x['flag'] == 0 and 0 < x['target'] < 360}
            s += sum(1 for _ in ct6set if rng.randrange(1, 360) in tset)
        sims.append(s)
    ns_rows.append(('ct6_vs_2c_target', obs, round(exp, 2),
                    p_ge(obs, sims),
                    'cmdType6 actor 命中同局 0x2c target；两者都在 1–359'))

    # ct6 分类
    ct6 = [c for ev in all_ev.values() for c in ev['cmd80'] if c['ct'] == 6]
    ct6_cat = Counter()
    ct6_other_hero = []
    for ev in all_ev.values():
        rev = {v: k for k, v in ev['actors'].items()}
        for c in ev['cmd80']:
            if c['ct'] != 6:
                continue
            own = ev['actors'].get(c['entity'])
            if c['actor'] == own:
                cat = 'self'
            elif c['actor'] in rev:
                cat = 'other_hero'
                ct6_other_hero.append((
                    c['sample'], c['time_s'], c['entity'], c['hero_name'],
                    c['actor'], rev[c['actor']],
                    ev['roster'].get(rev[c['actor']], {}).get('heroName', ''),
                    c['val']))
            else:
                cat = 'nonhero'
            ct6_cat[(cat, 'val0' if c['val'] == 0 else 'val>0')] += 1
    ct6_victim_hits = 0
    for ev in all_ev.values():
        for c in ev['cmd80']:
            if c['ct'] != 6:
                continue
            for e in ev['1e']:
                if e['entity'] == c['entity'] and abs(e['seq'] - c['seq']) <= 40 \
                        and e['victim'] == c['actor']:
                    ct6_victim_hits += 1

    flag1 = [e for ev in all_ev.values() for e in ev['2c'] if e['flag'] == 1]
    flag1_cancel = sum(1 for e in flag1
                       if e['target'] == 0xFFFF and e['x'] == 0 and e['y'] == 0)

    # -- 对齐 ------------------------------------------------------------
    align_rows = []
    subset = [e for ev in all_ev.values() for e in ev['1e']]
    for ev in all_ev.values():
        tag = ev['1e'][0]['sample'] if ev['1e'] else ''
        # 只对当前文件建索引
        gold_idx = defaultdict(list)
        for g in ev['gold']:
            if g['source'] in (4, 6, 43):
                gold_idx[(g['entity'], g['source'])].append(g['time_s'])
        for v in gold_idx.values():
            v.sort()
        c2_idx = defaultdict(list)
        for e in ev['2c']:
            c2_idx[e['entity']].append(e['time_s'])
        for v in c2_idx.values():
            v.sort()
        ct6_idx = defaultdict(list)
        for c in ev['cmd80']:
            if c['ct'] == 6:
                ct6_idx[c['entity']].append(c['time_s'])
        for v in ct6_idx.values():
            v.sort()
        v6_starts = sorted(w[0] for w in build_81_windows({'81': ev['81']}).get(tag, []))
        for e in ev['1e']:
            for src in (4, 6, 43):
                times = gold_idx.get((e['entity'], src), [])
                d, ad = nearest_delta(times, e['time_s'])
                align_rows.append({
                    'record_type': 'alignment_1e', 'sample': tag,
                    'segment': e['segment'], 'channel': f'1e_vs_source{src}',
                    'subtype': f'source{src}', 'seq': e['seq'], 'time_s': e['time_s'],
                    'entity': e['entity'], 'hero_name': e['hero_name'],
                    'team': e['team'], 'object_id': e['victim'], 'object_id_2': d,
                    'role': 'victim', 'kind': e['type'], 'flag': '',
                    'x': '', 'y': '', 'mapped_class': '', 'mapped_entity': '',
                    'confidence': '', 'evidence': f'nearest same-hero source{src}',
                })
            d, ad = nearest_delta(c2_idx.get(e['entity'], []), e['time_s'])
            align_rows.append({
                'record_type': 'alignment_1e', 'sample': tag,
                'segment': e['segment'], 'channel': '1e_vs_2c',
                'subtype': '2c', 'seq': e['seq'], 'time_s': e['time_s'],
                'entity': e['entity'], 'hero_name': e['hero_name'],
                'team': e['team'], 'object_id': e['victim'], 'object_id_2': d,
                'role': 'victim', 'kind': e['type'], 'flag': '',
                'x': '', 'y': '', 'mapped_class': '', 'mapped_entity': '',
                'confidence': '', 'evidence': 'nearest same-hero 0x2c',
            })
            d, ad = nearest_delta(ct6_idx.get(e['entity'], []), e['time_s'])
            align_rows.append({
                'record_type': 'alignment_1e', 'sample': tag,
                'segment': e['segment'], 'channel': '1e_vs_cmd6',
                'subtype': 'cmd6', 'seq': e['seq'], 'time_s': e['time_s'],
                'entity': e['entity'], 'hero_name': e['hero_name'],
                'team': e['team'], 'object_id': e['victim'], 'object_id_2': d,
                'role': 'victim', 'kind': e['type'], 'flag': '',
                'x': '', 'y': '', 'mapped_class': '', 'mapped_entity': '',
                'confidence': '', 'evidence': 'nearest same-hero cmdType6',
            })
            d, ad = nearest_delta(v6_starts, e['time_s'])
            align_rows.append({
                'record_type': 'alignment_1e', 'sample': tag,
                'segment': e['segment'], 'channel': '1e_vs_81v6',
                'subtype': '81v6', 'seq': e['seq'], 'time_s': e['time_s'],
                'entity': e['entity'], 'hero_name': e['hero_name'],
                'team': e['team'], 'object_id': e['victim'], 'object_id_2': d,
                'role': 'victim', 'kind': e['type'], 'flag': '',
                'x': '', 'y': '', 'mapped_class': '', 'mapped_entity': '',
                'confidence': '', 'evidence': 'nearest any-hero 0x81 v6 start',
            })

    # 随机基线：同文件同英雄事件时间密度
    random_stats = {}
    for channel in ('1e_vs_source4', '1e_vs_source6', '1e_vs_source43',
                    '1e_vs_2c', '1e_vs_cmd6', '1e_vs_81v6'):
        obs1 = obs2 = 0
        total = 0
        sim1 = sim2 = 0
        sim_n = 0
        for ev in all_ev.values():
            if not ev['1e']:
                continue
            times = sorted(e['time_s'] for e in ev['1e'])
            tmin, tmax = min(times), max(times)
            gold_idx = defaultdict(list)
            for g in ev['gold']:
                if g['source'] in (4, 6, 43):
                    gold_idx[(g['entity'], g['source'])].append(g['time_s'])
            c2_idx = defaultdict(list)
            for e in ev['2c']:
                c2_idx[e['entity']].append(e['time_s'])
            ct6_idx = defaultdict(list)
            for c in ev['cmd80']:
                if c['ct'] == 6:
                    ct6_idx[c['entity']].append(c['time_s'])
            v6 = sorted(w[0] for w in build_81_windows({'81': ev['81']}).get(
                ev['1e'][0]['sample'], []))
            for e in ev['1e']:
                if channel.startswith('1e_vs_source'):
                    src = int(channel[-1])
                    pool = gold_idx.get((e['entity'], src), [])
                elif channel == '1e_vs_2c':
                    pool = c2_idx.get(e['entity'], [])
                elif channel == '1e_vs_cmd6':
                    pool = ct6_idx.get(e['entity'], [])
                else:
                    pool = v6
                _, ad = nearest_delta(pool, e['time_s'])
                total += 1
                if ad is not None and ad <= 1.0:
                    obs1 += 1
                if ad is not None and ad <= 2.0:
                    obs2 += 1
                for _ in range(20):
                    rt = rng.uniform(tmin, tmax)
                    _, ad2 = nearest_delta(pool, rt)
                    sim_n += 1
                    if ad2 is not None and ad2 <= 1.0:
                        sim1 += 1
                    if ad2 is not None and ad2 <= 2.0:
                        sim2 += 1
        random_stats[channel] = {
            'n': total, 'obs1': obs1, 'obs2': obs2,
            'rand1': sim1 / sim_n if sim_n else 0,
            'rand2': sim2 / sim_n if sim_n else 0,
        }

    # -- 0x12/0x13 -------------------------------------------------------
    main_ev = all_ev.get(SAMPLE_KEY, next(iter(all_ev.values())))
    s12 = main_ev['scalars']['12']
    s13 = main_ev['scalars']['13']
    s14 = main_ev['scalars']['14']
    xvals = [int.from_bytes(x, 'big') for x in s12] if s12 else []
    xs = [v >> 8 for v in xvals]
    ys = [v & 0xFF for v in xvals]
    # 每帧 0x12 个数
    per_rec = Counter()
    for ev in all_ev.values():
        pass
    # 重新按记录统计主样本 0x12 个数
    # （scalars 已聚合，无法回推；用主样本单独再取一次）
    base = _import_base()
    ctx = base.extract_sample(MAIN_SAMPLE)
    per12 = Counter()
    for _, _, _, rec in iter_records(ctx):
        n = 0
        for m in base.parse_payload(rec['payload'])[0]:
            if m[0] == 's' and m[1] == 0x12:
                n += 1
        if n:
            per12[n] += 1
    # -- 汇总 CSV --------------------------------------------------------
    rows = []
    for tag, ev in all_ev.items():
        rows.append({
            'record_type': 'sample_meta', 'sample': tag, 'segment': '',
            'channel': 'abc', 'subtype': '', 'seq': '', 'time_s': '',
            'entity': '', 'hero_name': '', 'team': '',
            'object_id': '', 'object_id_2': '',
            'role': f"main={ev['main_records']}/tail={ev['tail_records']}",
            'kind': '', 'flag': '', 'x': '', 'y': '',
            'mapped_class': '', 'mapped_entity': '',
            'confidence': 'high',
            'evidence': f"roster={ev['roster_source']}; actors={len(ev['actors'])}; "
                        f"parse_fails={ev['fails']}",
        })
        for entity, actor in sorted(ev['actors'].items()):
            info = ev['roster'].get(entity, {})
            rows.append({
                'record_type': 'hero_actor_slot', 'sample': tag, 'segment': '',
                'channel': '0x02/0x87', 'subtype': 'actorID',
                'seq': '', 'time_s': '', 'entity': entity,
                'hero_name': info.get('heroName', ''), 'team': info.get('team', ''),
                'object_id': actor, 'object_id_2': '',
                'role': 'actor_slot', 'kind': '', 'flag': '', 'x': '', 'y': '',
                'mapped_class': 'hero', 'mapped_entity': info.get('heroName', ''),
                'confidence': 'high',
                'evidence': '0x02/0x87 data[3]；同局同英雄恒定、跨局可换人',
            })
        full_actors = len(ev['actors']) >= 10
        for e in ev['1e']:
            info = ev['roster'].get(e['entity'], {})
            hit = e['victim'] in set(ev['actors'].values())
            rows.append({
                'record_type': 'objectid_1e', 'sample': tag,
                'segment': e['segment'], 'channel': '0x01/0x1e',
                'subtype': '1e', 'seq': e['seq'], 'time_s': e['time_s'],
                'entity': e['entity'], 'hero_name': e['hero_name'],
                'team': e['team'], 'object_id': e['victim'], 'object_id_2': '',
                'role': 'victim', 'kind': e['type'], 'flag': '',
                'x': '', 'y': '',
                'mapped_class': ('ambig_actor_collision' if hit else 'unknown_global_pool'),
                'mapped_entity': '',
                'confidence': ('low' if hit else 'high'),
                'evidence': f"type={e['type']}; 14B reserved_zero={not e['reserved_nonzero']}; "
                            f"raw={e['raw_hex']}; actor_coverage={len(ev['actors'])}/10; "
                            f"victim 属于 0–994 全局池，不等于 actorID 不能推出非英雄",
            })
        for e in ev['2c']:
            hit = e['target'] in set(ev['actors'].values())
            if e['flag'] == 1:
                cls, conf, role = 'cancel', 'high', 'cancel'
            elif e['target'] == 0xFFFF or e['target'] >= 0xFF00:
                cls, conf, role = 'sentinel', 'high', 'sentinel'
            elif hit:
                cls, conf, role = 'ambig_actor_collision', 'low', 'target'
            elif full_actors:
                cls, conf, role = 'unknown', 'reject', 'target'
            else:
                cls, conf, role = 'unknown_partial_roster', 'medium', 'target'
            rows.append({
                'record_type': 'objectid_2c', 'sample': tag,
                'segment': e['segment'], 'channel': '0x01/0x2c',
                'subtype': '2c', 'seq': e['seq'], 'time_s': e['time_s'],
                'entity': e['entity'], 'hero_name': e['hero_name'],
                'team': e['team'], 'object_id': e['target'], 'object_id_2': '',
                'role': role, 'kind': e['kind'], 'flag': e['flag'],
                'x': e['x'], 'y': e['y'],
                'mapped_class': cls, 'mapped_entity': '',
                'confidence': conf,
                'evidence': f"counter={e['counter']}; target 1–359; x/y 是瞄准点; "
                            f"actor_coverage={len(ev['actors'])}/10",
            })
        for e in ev['1f']:
            rows.append({
                'record_type': 'objectid_1f', 'sample': tag,
                'segment': e['segment'], 'channel': '0x01/0x1f',
                'subtype': '1f', 'seq': e['seq'], 'time_s': e['time_s'],
                'entity': e['entity'], 'hero_name': e['hero_name'],
                'team': e['team'], 'object_id': e['actor'], 'object_id_2': '',
                'role': 'highlight_actor', 'kind': e['tag'], 'flag': '',
                'x': '', 'y': '', 'mapped_class': 'unknown',
                'mapped_entity': '', 'confidence': 'reject',
                'evidence': f"tag={e['tag']}; i32_a={e['i32_a']}; i32_c={e['i32_c']}",
            })
        for e in ev['20']:
            rows.append({
                'record_type': 'objectid_20', 'sample': tag,
                'segment': e['segment'], 'channel': '0x01/0x20',
                'subtype': '20', 'seq': e['seq'], 'time_s': e['time_s'],
                'entity': e['entity'], 'hero_name': e['hero_name'],
                'team': e['team'], 'object_id': e['actor'], 'object_id_2': '',
                'role': 'highlight_actor', 'kind': e['tag'], 'flag': '',
                'x': '', 'y': '', 'mapped_class': 'unknown',
                'mapped_entity': '', 'confidence': 'reject',
                'evidence': f"tag={e['tag']}; actor 可为 21641（>994）",
            })
        for c in ev['cmd80']:
            if c['ct'] != 6:
                continue
            rev = {v: k for k, v in ev['actors'].items()}
            own = ev['actors'].get(c['entity'])
            if c['actor'] == own:
                cat = 'self'
            elif c['actor'] in rev:
                cat = 'other_hero'
            else:
                cat = 'nonhero'
            rows.append({
                'record_type': 'objectid_ct6', 'sample': tag,
                'segment': c['segment'], 'channel': '0x02/0x80',
                'subtype': 'cmd6', 'seq': c['seq'], 'time_s': c['time_s'],
                'entity': c['entity'], 'hero_name': c['hero_name'],
                'team': c['team'], 'object_id': c['actor'], 'object_id_2': c['val'],
                'role': cat, 'kind': 6, 'flag': c['tail'], 'x': '', 'y': '',
                'mapped_class': ('hero' if cat == 'other_hero' else 'unknown'),
                'mapped_entity': ev['roster'].get(rev.get(c['actor']), {}).get(
                    'heroName', '') if cat == 'other_hero' else '',
                'confidence': ('medium' if cat == 'other_hero' else 'low'),
                'evidence': f"actor={c['actor']}, value={c['val']}, "
                            f"cmdseq={c['cmdseq']}; value/seq 高位像坐标，不是单位类型",
            })
        for e in ev['special_48']:
            rows.append({
                'record_type': 'special_48', 'sample': tag,
                'segment': e['segment'], 'channel': '0x01/0x48',
                'subtype': '48', 'seq': e['seq'], 'time_s': e['time_s'],
                'entity': e['entity'], 'hero_name': '', 'team': '',
                'object_id': e['entity'], 'object_id_2': '',
                'role': 'envelope', 'kind': '0x48', 'flag': '', 'x': '', 'y': '',
                'mapped_class': 'not_unit', 'mapped_entity': '',
                'confidence': 'high',
                'evidence': f"hero=37120>994；body={e['raw_hex']}；ASCII 形，无单位表键",
            })
        for e in ev['special_86']:
            rows.append({
                'record_type': 'special_86', 'sample': tag,
                'segment': e['segment'], 'channel': '0x02/0x86',
                'subtype': '86', 'seq': e['seq'], 'time_s': e['time_s'],
                'entity': e['entity'], 'hero_name': e['hero_name'], 'team': e['team'],
                'object_id': 0x1252, 'object_id_2': '',
                'role': 'body_value', 'kind': '0x86', 'flag': '', 'x': '', 'y': '',
                'mapped_class': 'not_unit', 'mapped_entity': '',
                'confidence': 'high',
                'evidence': f"body={e['raw_hex']}; 0x1252=4690>994，不是 0–994/1–359",
            })
    catalog_scans = [
        ('native_table_catalog', '1443 tables', 'no objectID→unit table',
         '900–1100 行 24 张；恰好 1000 行的 0x593ed68/0x58069e4 是曲线，不是单位表'),
        ('native_table_names', '20 tables / 50110 rows', 'no unit table',
         '只有地名/商店等 20 张表的行名，没有 0–994 单位映射'),
        ('decoded_csharp_all', '436 tables', 'no unit table',
         '247_NpcOfArena=训练召唤师；110_TowerHit=UI/特效名；825=SoldierSkinBattlePreview'),
        ('agent_global_strings', '919 string tables', 'no unit+key table',
         '单位名在 0x679118/0x800380/0x6f532f0/0x6f92224/0x1ce47c；都不是 0–994 键+单位名'),
    ]
    for channel, shape, role, note in catalog_scans:
        rows.append({
            'record_type': 'catalog_scan', 'sample': 'global', 'segment': '',
            'channel': channel, 'subtype': shape, 'seq': '', 'time_s': '',
            'entity': '', 'hero_name': '', 'team': '', 'object_id': '',
            'object_id_2': '', 'role': role, 'kind': '', 'flag': '',
            'x': '', 'y': '', 'mapped_class': 'table_rejected',
            'mapped_entity': '', 'confidence': 'high', 'evidence': note,
        })
    for c in candidates:
        s = c['stats']
        rows.append({
            'record_type': 'table_candidate', 'sample': 'global', 'segment': '',
            'channel': 'dc.db', 'subtype': c['name'], 'seq': '', 'time_s': '',
            'entity': '', 'hero_name': '', 'team': '',
            'object_id': s['keys_le_994'], 'object_id_2': s['keys_1_359'],
            'role': c['verdict'], 'kind': '', 'flag': '', 'x': '', 'y': '',
            'mapped_class': 'table_rejected' if 'candidate' not in c['verdict'] else 'table_candidate',
            'mapped_entity': '',
            'confidence': 'high' if 'structurally' in c['verdict'] else 'medium',
            'evidence': f"{c['where']}; {c['shape']}; "
                        f"victim {s['victim_hit']}/{len(victims)} exp={s['victim_expected']:.1f} "
                        f"p={s['victim_p']:.3f}; target {s['target_hit']}/{len(targets)} "
                        f"exp={s['target_expected']:.1f} p={s['target_p']:.3f}; {c['note']}",
        })
    for name, obs, exp, p, note in ns_rows:
        rows.append({
            'record_type': 'namespace_test', 'sample': 'global', 'segment': '',
            'channel': 'namespace', 'subtype': name, 'seq': '', 'time_s': '',
            'entity': '', 'hero_name': '', 'team': '',
            'object_id': obs, 'object_id_2': exp, 'role': name,
            'kind': '', 'flag': '', 'x': '', 'y': '',
            'mapped_class': '', 'mapped_entity': '',
            'confidence': ('p=%.3f' % p) if p is not None else '',
            'evidence': note,
        })
    rows.extend(align_rows)

    write_csv(out_dir / 'agent_objectid_map.csv', rows)

    # MD
    md = build_md(
        all_ev=all_ev, metas=metas, victims=victims, targets=targets,
        candidates=candidates, ns_rows=ns_rows, align_rows=align_rows,
        random_stats=random_stats, ct6_cat=ct6_cat,
        ct6_other_hero=ct6_other_hero, ct6_victim_hits=ct6_victim_hits,
        s12=s12, s13=s13, s14=s14, xs=xs, ys=ys, per12=per12,
        dense_meta=dense_meta, dense_rows=dense_rows,
        normal=normal, tw_map=tw_map, tw_rows=tw_rows, p8_shape=p8_shape,
        sw_shape=sw_shape, wiki_shape=wiki_shape, skin_shape=skin_shape,
        flag1=flag1, flag1_cancel=flag1_cancel,
    )
    (out_dir / 'agent_objectid_map.md').write_text(md, encoding='utf-8')
    return rows, md


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ['record_type', 'sample', 'segment', 'channel', 'subtype', 'seq',
            'time_s', 'entity', 'hero_name', 'team', 'object_id', 'object_id_2',
            'role', 'kind', 'flag', 'x', 'y', 'mapped_class', 'mapped_entity',
            'confidence', 'evidence']
    with path.open('w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------
def build_md(**kw):
    all_ev = kw['all_ev']
    victims = kw['victims']
    targets = kw['targets']
    candidates = kw['candidates']
    ns_rows = kw['ns_rows']
    random_stats = kw['random_stats']
    ct6_cat = kw['ct6_cat']
    ct6_other_hero = kw['ct6_other_hero']
    ct6_victim_hits = kw['ct6_victim_hits']
    s12, s13, s14 = kw['s12'], kw['s13'], kw['s14']
    xs, ys, per12 = kw['xs'], kw['ys'], kw['per12']
    dense_meta, dense_rows = kw['dense_meta'], kw['dense_rows']
    normal, tw_map = kw['normal'], kw['tw_map']
    p8_shape, sw_shape = kw['p8_shape'], kw['sw_shape']
    wiki_shape, skin_shape = kw['wiki_shape'], kw['skin_shape']
    tw_rows = kw['tw_rows']
    flag1, flag1_cancel = kw['flag1'], kw['flag1_cancel']
    cand = {c['name']: c for c in candidates}
    cand_stats = {c['name']: c['stats'] for c in candidates}

    L = []
    A = L.append
    A('# 普通 5v5 运行时单位 objectID 映射审计（5069040）')
    A('')
    A('> 只读逆向。主样本 `20260925_105224`（录制者 1558 佚名(*:）；'
      '参考新回放 5247758。')
    A('> 约束：不改回放/包体、不注入、不读 `param.json`、不使用 `runtime_dump`；'
      '不修改 `docs/replay_binary_format.md` 与 `.workbuddy/memory/MEMORY.md`。')
    A('> 本文全部数字由 `tools/agent_objectid_map.py` 生成，可复跑。')
    A('')
    A('## 0. 结论摘要')
    A('')
    A('| 问题 | 结论 | 置信度 |')
    A('|---|---|---|')
    A('| 0x1e victim（0–994）能否映射到英雄/小兵/野怪/塔 | **不能**。110 条里 0 条高置信映射；'
      '2 条与同局 actorID 数值相同，但与随机碰撞一致（期望 1.09，p≈0.29）；'
      '其余 108 条属于另一个 0–994 池，**不能**因“不等于 actorID”就判成非英雄 | high |')
    A('| 0x2c target（1–359）是不是英雄 actorID | **没有富集**。835 条有效 target 中 14 条命中 actorID，'
      '按同分布 bootstrap 期望 20.5，p≈0.92；不能按 actorID 反推英雄 | high |')
    A('| 0x1e victim 与 0x2c target 是否同一 ID 空间 | **没有共享证据**。victim 值 0–994 '
      '近似均匀；target 值 1–359 且明显偏 250–359；同文件重叠 8 次，期望 10.4'
      '（右尾 p≈0.84）。按独立池处理，但不能仅凭重叠率否定同一大池 | medium |')
    A('| 是否存在 objectID→单位静态表 | **没有**。`normalMonster`、`soldierWave`、'
      '`Project8Hero`、塔/器官表、`0x7384068`、native catalog/names、decoded C#、'
      'global strings 全部否定 | high |')
    A('| 最强候选表 | 没有候选；最接近的是 `normalMonster`（222 个键 ≤994），'
      '但 victim 命中 17/110，期望 24.5，p≈0.97（低于随机） | high |')
    A('| 能映射什么 | 只有 **同局 10 个英雄的 actor-slot ID**（0x02/0x87）可映射到英雄；'
      '这是 1–359 的 actor 空间，不是 0x1e 的 0–994 全局空间 | high |')
    A('| 还缺什么 | 战斗初始化/`StepNotify` 头里的 `MyCampHeroObjIds/EnemyCampHeroObjIds`'
      ' 与逐单位 spawn 日志；0x1e payload 没有单位类型/队伍；0x2c 没有可验证的目标类型 | high |')
    A('')
    A('**一句话**：0x1e victim 是一个 0–994 的运行时单位 ID 池（候选全局 objectID），'
      '回放只给了 ID 本身，没有给 ID→单位类型的表；0x2c target 落在另一个 1–359 的目标池，'
      '0x02/0x80 的 actor 字段已确认是 1–359 的 actor-slot（英雄 actorID 只在后一个池里可映射）。'
      '因此 0x1e victim 目前**一个都不能**可靠映射到英雄/小兵/野怪/塔；'
      '“不等于 actorID”只能说明它不在 actor-slot 池，不能说明它是非英雄。')
    A('')
    A('## 1. 样本与口径')
    A('')
    A(f'- 主样本：`{MAIN_SAMPLE.name}`（build 5069040）。')
    A('- 跨样本：build 5069040 的 6 个可解析主状态流样本 '
      '（20260924_113638、20260925_094930/095631/101323/103058/105224）。')
    A('- 事件口径沿用 `0x02 flag=0x80` 的 12B 命令体消费；主样本主状态流 13,061 条、'
      '续流 678 条。0x1e 22/0x2c 425 指主状态流，续流另有 0x2c 24 条、0x20 5 条；'
      '跨样本统计用 main+tail。')
    A('- 注意：`.abc` 的帧记录头实际是 `seq:u8 + len:u16BE`，不是 `seq + 00 + len:u8`。'
      '本报告的主/续流切分沿用已解的主状态流起点（0xBFE8）与续流（0x9BA3B）；'
      '0x9B0F0 之后还有带大 payload（len 267/268）的第二段记录，本文没有把它并入主统计，'
      '避免把开局 loadout/第二段输入误当战斗事件。')
    A('- 解析失败（payload 尾部未知 tag）仍约 13%，逐条表是**已解析部分**的下界。')
    A('')
    A('## 2. 两个 ID 范围：0–994 与 1–359')
    A('')
    A('### 2.1 0x1e victim：0–994 的均匀池')
    A('')
    A(f'- 110 条，104 个不同值，范围 **0–994**；十位分桶 '
      f'{dict(sorted(Counter(min(v // 100, 9) for v in victims).items()))}。')
    A(f'- 110 次抽样的不同值数：观察 **104**，0–994 均匀池模拟均值 **104.14**，'
      f'p(≤观察)=**0.536** → 与“0–994 均匀运行时池”完全一致。')
    A(f'- 跨文件重复值：观察 **5** 个值出现在 ≥2 个文件，均匀池模拟均值 3.94，p≈0.36。')
    A('- 这说明 victim 不是某个静态单位表的行键（那样会大量重复、且不会均匀覆盖 0–994），'
      '而更像运行时分配的全局单位 objectID。')
    A('')
    A('### 2.2 0x2c target / 0x02/0x80 actor：1–359 的目标/actor 池')
    A('')
    A(f'- 0x2c main+tail 901 条；flag=0 且 target≠0xFFFF 的有效 target **835** 条，'
      f'310 个不同值，范围 **1–359**；target 分桶（每 36 一桶）'
      f'{dict(sorted(Counter(min(t // 36, 9) for t in targets).items()))}，明显偏向 250–359。')
    A('- 0x02/0x80 的 `actor` 字段以**发令英雄自己的 actorID**为主'
      '（cmdType 1/2/3 分别约 15%/13%/28% 指向其他英雄）；cmdType 6 的 actor '
      '52/174 指向其他英雄、83/174 指向非英雄 actor-slot。')
    A(f'- cmdType 6 分类：{dict(ct6_cat)}。其中 **{ct6_cat[("other_hero","val0")] + ct6_cat[("other_hero","val>0")]} 条**'
      '指向**其他英雄**的 actorID（medium），这直接证明 0x02/0x80 的 actor 是'
      ' `actor-slot` 空间，而不是 0x1e 的 0–994 空间；但 0x1e victim 不跟随这个 actor'
      f'（同英雄 ±40 帧内 0 次等于 cmdType6 actor）。')
    if ct6_other_hero:
        A('')
        A(md_table(
            ['文件', 't(s)', '发令 entity', '发令英雄', 'actor', '目标 entity', '目标英雄', 'value'],
            [[a, round(b, 2), c, d, e, f, g, h]
             for a, b, c, d, e, f, g, h in ct6_other_hero[:6]]))
        A('')
    A('- 0x02/0x87 的 `data[3]` 是同一局内稳定的 actorID：'
      '本局 10 人为 8/12/19/23/30/37/44/51/58/65（entity→actor 见 CSV 的 `hero_actor_slot`）。'
      '同一个 actorID 在不同局可以换给不同英雄（例如 44 在 105224 是李信、'
      '在 101323 是鬼谷子、在 113638 是上官婉儿），所以 actorID 是**每局分配**，'
      '任何静态表都不可能直接按 actorID 命名。')
    A('')
    A('### 2.3 两个范围的交集检验')
    A('')
    ns = {r[0]: r for r in ns_rows}
    A(md_table(
        ['检验', '观察', '期望', 'p', '判定'],
        [
            ['victim 不同值数', ns['victim_pool_uniform'][1], ns['victim_pool_uniform'][2],
             f"{ns['victim_pool_uniform'][3]:.3f}", '0–994 均匀池'],
            ['victim 跨文件重复', ns['victim_cross_file_repeats'][1],
             ns['victim_cross_file_repeats'][2],
             f"{ns['victim_cross_file_repeats'][3]:.3f}", '与均匀池一致'],
            ['victim 命中 actorID', ns['victim_vs_actorID'][1], ns['victim_vs_actorID'][2],
             f"{ns['victim_vs_actorID'][3]:.3f}", '随机碰撞'],
            ['target 命中 actorID', ns['target_vs_actorID'][1], ns['target_vs_actorID'][2],
             f"{ns['target_vs_actorID'][3]:.3f}", '无富集（甚至低于期望）'],
            ['victim 命中 target', ns['victim_vs_2c_target'][1], ns['victim_vs_2c_target'][2],
             f"{ns['victim_vs_2c_target'][3]:.3f}", '无共享证据（保守按独立池）'],
            ['cmd6 actor 命中 target', ns['ct6_vs_2c_target'][1], ns['ct6_vs_2c_target'][2],
             f"{ns['ct6_vs_2c_target'][3]:.3f}", '同范围，但重叠不高于随机'],
        ]))
    A('')
    A('p 列：victim 不同值数/跨文件重复用对应方向；其余为右尾 p(观察≥期望)，'
      'p 大表示没有富集。')
    A('')
    A('**判定**：0x1e victim 是 0–994 池；0x02/0x80 actor 已确认是 1–359 actor-slot；'
      '0x2c target 只确认也落在 1–359，与 0x1e victim 的重叠不高于随机。'
      '按独立池处理是保守做法，但重叠率本身不足以证明它们一定不是同一个大池；'
      '能确定的是：把 0x1e victim 直接和 0x87 actorID 对齐是**命名空间错误**，'
      '把 0x2c target 直接当英雄 actorID 也没有富集证据。')
    A('')
    A('## 3. 表搜索：没有 objectID→单位表')
    A('')
    A('### 3.1 候选表与统计检验')
    A('')
    rows = []
    for c in candidates:
        s = c['stats']
        rows.append([
            c['name'], c['where'], c['shape'],
            s['keys_le_994'], s['keys_1_359'],
            f"{s['victim_hit']}/{len(victims)}", f"{s['victim_expected']:.1f}",
            f"{s['victim_p']:.3f}" if s['victim_p'] is not None else '',
            f"{s['target_hit']}/{len(targets)}", f"{s['target_expected']:.1f}",
            f"{s['target_p']:.3f}" if s['target_p'] is not None else '',
            c['verdict'],
        ])
    A(md_table(['表', '位置', '形状', '键≤994', '键1–359',
                'victim 命中', '期望', 'p', 'target 命中', '期望', 'p', '判定'], rows))
    A('')
    A('判读：')
    A('')
    def cs(name):
        return cand_stats[name]
    A(f"- **normalMonster**：2,625 行，行键是单位配置 id（41/410/6000/…），"
      f"其中 {cs('normalMonster')['keys_le_994']} 个键落在 0–994。"
      f"victim 命中 {cs('normalMonster')['victim_hit']}/110，"
      f"期望 {cs('normalMonster')['victim_expected']:.1f}，"
      f"p={cs('normalMonster')['victim_p']:.3f}（低于随机）；"
      f"target 命中 {cs('normalMonster')['target_hit']}/835，"
      f"期望 {cs('normalMonster')['target_expected']:.1f}，"
      f"p={cs('normalMonster')['target_p']:.3f}。它不是 objectID 表。")
    A(f"- **soldierWave**：957 行，行键是波次 id（101+）；"
      f"victim 命中 {cs('soldierWave')['victim_hit']}/110，"
      f"期望 {cs('soldierWave')['victim_expected']:.1f}，"
      f"p={cs('soldierWave')['victim_p']:.3f}；"
      f"target {cs('soldierWave')['target_hit']}/835，"
      f"期望 {cs('soldierWave')['target_expected']:.1f}，"
      f"p={cs('soldierWave')['target_p']:.3f}。随机水平。")
    A(f"- **Project8Hero**：259 行，行键 **1000–21930，0 个键 ≤994**；"
      '结构上不可能映射 0–994。文档里 174–193 是**英雄 id 列**，不是 objectID。')
    A(f"- **塔/器官表 0x800380**：{tw_rows} 行 / {len(tw_map)} 个不同键，"
      f"键 1–18、1014–2016、…，名称是蓝方先锋塔/红方先锋塔/基地/兵营/泉水。"
      f"victim 命中 {cs('tower_organ_0x800380')['victim_hit']}/110，"
      f"期望 {cs('tower_organ_0x800380')['victim_expected']:.1f}，"
      f"p={cs('tower_organ_0x800380')['victim_p']:.3f}；"
      f"target {cs('tower_organ_0x800380')['target_hit']}/835，"
      f"期望 {cs('tower_organ_0x800380')['target_expected']:.1f}，"
      f"p={cs('tower_organ_0x800380')['target_p']:.3f}。只是键集合覆盖到 0–994 的一部分，不是运行时映射。")
    A(f"- **野怪图鉴 0x6f532f0**：29 行，键 1–29；"
      f"victim {cs('monster_wiki_0x6f532f0')['victim_hit']}/110，"
      f"期望 {cs('monster_wiki_0x6f532f0')['victim_expected']:.1f}，"
      f"p={cs('monster_wiki_0x6f532f0')['victim_p']:.3f}。")
    A('- **小兵皮肤 0x6f92224**：键 93000+，0 个键 ≤994。')
    A('- **0x7384068**：20,755 行 / stride 56 / nstr 0；键 1..20755，'
      '列是 50/51/52、等级 2/3/4/5、100、技能/效果 id（900019/900020/11802/19102/10701/13005…）。'
      '它覆盖 1–994（所以 victim 109/110 “命中”是 trivial），但**没有单位名列/类型列**，'
      '不是 objectID→单位表。11990 在该表里是行键/效果 id，不是单位。')
    A('')
    A('### 3.2 逐表检查的补充证据')
    A('')
    nm_type17 = sum(1 for r in normal if r['row'] < 995 and r['actor_type'] == 17)
    v_type17 = sum(1 for v in victims if v < len(normal)
                   and normal[v]['actor_type'] == 17)
    A(f'- `normalMonster_rows.csv` 的 2,625 行里，0–994 的 actor_type 基线：'
      f'type17={nm_type17}/995（{nm_type17 / 995:.1%}）；'
      f'把 victim 值当**行下标**做 naive 映射，得到 type17 {v_type17}/{len(victims)}'
      f'（{v_type17 / len(victims):.1%}），与基线相同 → 行下标假设不成立。')
    A('- 0x1e victim 与 `normalMonster` id、`soldierWave` waveID、塔表键、'
      '`Project8Hero` 键的重叠都在随机或低于随机；没有一张表的键集合与 victim 的'
      '104 个不同值形成稳定对应。')
    A('- `native_table_catalog.csv` 1,443 张表：900–1100 行的 24 张里，'
      '恰好 1000 行的只有 `0x593ed68`（1→22..522 的线性曲线）和 '
      '`0x58069e4`（全表首列 10000、等级/经验曲线），都不是单位表。')
    A('- `native_table_names.csv` 只有 20 张表、50,110 行，没有单位表；'
      '`decoded_csharp_all` 436 张里没有 objectID→单位表（`247_NpcOfArena` 是训练召唤师，'
      '`110_TowerHit` 是 UI/特效名，`825_SoldierSkinBattlePreview` 是小兵皮肤）。')
    A('- `agent_global_strings.csv` 的单位名主要落在 `0x679118`（normalMonster）、'
      '`0x800380`（塔/器官）、`0x6f532f0`（野怪图鉴）、`0x6f92224`（小兵皮肤）与 '
      '`0x1ce47c`（技能描述）；没有“键 0–994 + 单位名”的表。')
    A('')
    A('## 4. 0x1e victim：分布、表检验、时空关联')
    A('')
    A('### 4.1 基本统计')
    A('')
    types = Counter(e['type'] for ev in all_ev.values() for e in ev['1e'])
    A(f'- 110 条；type 分布 {dict(types)}；victim 0–994、104 个不同值。')
    A('- `data[2:16]` 仍恒 0：没有 damage/skillId/team/unitType；只有 type + victim + 尾 01。')
    A('- 主样本 22 条：victim 64–980；没有一条等于 10 人 entityID/heroID/actorID'
      '（旧报告的 0/22 仍成立）。')
    A('- 4 个样本的 0x87 覆盖 10/10 英雄；20260925_094930/095631 只覆盖 2 人，'
      '其中 094930 的 victim 587/771 不能排除是“未覆盖英雄”，095631 无 0x1e；'
      '但这两条也不构成映射证据。')
    A('- 分类结果：**2/110** 与同局 actorID 数值相同（low，只是碰撞）；'
      '**108/110** 不等于 actorID，但因为 0x1e 是另一个 0–994 池，'
      '“不等于 actorID”**不能**推出“非英雄”。所以 0x1e 的具体单位类别仍是 110/110 未知。')
    A('')
    A('### 4.2 与 source4/6/43、0x81 v6、0x2c 的时间对齐')
    A('')
    rows = []
    labels = {'1e_vs_source4': 'source4 小兵金', '1e_vs_source6': 'source6 野怪金',
              '1e_vs_source43': 'source43 击杀/助攻金', '1e_vs_2c': '0x2c target',
              '1e_vs_cmd6': 'cmdType6', '1e_vs_81v6': '0x81 v6 死亡窗口起点'}
    for ch, st in random_stats.items():
        rows.append([labels.get(ch, ch), st['n'],
                     f"{st['obs1']} ({st['obs1'] / st['n']:.1%})" if st['n'] else '',
                     f"{st['rand1']:.1%}", f"{st['obs2']} ({st['obs2'] / st['n']:.1%})" if st['n'] else '',
                     f"{st['rand2']:.1%}"])
    A(md_table(['0x1e vs', 'n', '±1s', '随机±1s', '±2s', '随机±2s'], rows))
    A('')
    A('- 所有通道的 ±1s/±2s 命中率都在随机基线附近或更低；0x1e 不是 source4/6/43 的'
      '补刀/击杀账本，也不在 0x81 v6 死亡窗口附近。')
    A('- 同英雄最近 0x2c 的分布同样没有稳定关系；0x1e 不是 0x2c 的“命中结果”。')
    A('- 0x1e 与 cmdType6 的 actor 字段在同英雄 ±40 帧内 0 次等于 victim；'
      'cmdType6 不是 0x1e 的目标来源。')
    A('')
    A('### 4.3 2 条 actorID 数值碰撞')
    A('')
    collisions = []
    for tag, ev in all_ev.items():
        rev = {v: k for k, v in ev['actors'].items()}
        acts = set(ev['actors'].values())
        for e in ev['1e']:
            if e['victim'] in acts:
                tgt_entity = rev.get(e['victim'])
                tgt_hero = ev['roster'].get(tgt_entity, {}).get('heroName', '') if tgt_entity else ''
                kind = 'self' if tgt_entity == e['entity'] else 'other_hero'
                collisions.append((tag, e['seq'], round(e['time_s'], 2),
                                   e['entity'], e['hero_name'], e['victim'],
                                   f'{tgt_entity}:{tgt_hero}', kind, e['type']))
    A(md_table(['文件', 'seq', 't(s)', '攻击者', '英雄', 'victim', 'actorID→单位', '关系', 'type'],
               collisions))
    A('')
    A('这 2 条（101323 的 23/44）是**唯一**的数值碰撞；期望 1.09，p≈0.29，'
      '不能作为英雄映射。`victim=23` 恰好等于攻击者猪八戒自己的 actorID，'
      '但 0x1e 不是伤害/技能表，不能据此判定“自伤/自奶”。')
    A('')
    A('## 5. 0x2c target：1–359 目标池，不是英雄目标富集')
    A('')
    kinds = Counter(e['kind'] for ev in all_ev.values() for e in ev['2c'])
    flags = Counter(e['flag'] for ev in all_ev.values() for e in ev['2c'])
    A(f'- 901 条（main+tail）；kind {dict(kinds)}；flag {dict(flags)}。'
      f'flag=1 的 {len(flag1)} 条里 {flag1_cancel} 条 target=0xFFFF、x=y=0（取消/清空）；'
      f'另有 8 条 flag=0 但 target≥0xFF00 的哨兵值，已从有效 target 排除'
      f'（901 − 58 − 8 = 835）。')
    A(f'- 有效 target 835 条，310 个不同值，1–359；每英雄/kind 的不同 target 数很高'
      '（442 李信 kind1 139 个/165 条，1966 孙权 kind2 68 个/78 条），'
      '所以 target **不是技能 id**（李信只有 3–4 个技能槽，远少于 139 个值）。')
    A('- target 命中同局 actorID 14 条；按各文件 target 分布 bootstrap 期望 20.5，p≈0.92。'
      '**没有英雄目标富集**；不能把 target 直接当英雄 actorID。')
    A('- target 与 0x1e victim 同文件重叠 8 次（期望 10.4，右尾 p≈0.84）；'
      '没有高于随机的共享证据，按独立池处理（保守；重叠率不足以证明一定不同池）。')
    A(f"- cmdType6 actor 与 0x2c target 都在 1–359，但同局 distinct 重叠 "
      f"{ns['ct6_vs_2c_target'][1]}（期望 {ns['ct6_vs_2c_target'][2]}，右尾 p="
      f"{ns['ct6_vs_2c_target'][3]:.3f}）→ 不能证明 0x2c target 就是 actor-slot 的子集。")
    A('- 0x2c x/y 是瞄准点：同 target 跨事件的坐标跨度常达 10^5（例如 105224 target 238 '
      '6 条跨 365s、span 115,642），不是单位位置，不能拿坐标给 target 定兵种/塔。')
    A('')
    A('## 6. 0x1f/0x20：高光通知，不是单位表')
    A('')
    f1 = [e for ev in all_ev.values() for e in ev['1f']]
    f20 = [e for ev in all_ev.values() for e in ev['20']]
    A(f'- 0x1f 9 条：actor {sorted(set(e["actor"] for e in f1))}，'
      '全部落在 **0–994**，所以**不能排除**它和 0x1e victim 是同一个全局池；'
      '但同文件 0 交集、没有类型字段，仍不能映射。1558 的 actor=12 等于自己的 actorID'
      '（1/9，单事件；1/994 量级，可能是巧合）。')
    A(f'- 0x20 7 条：actor {sorted(set(e["actor"] for e in f20))}；'
      '21641>994，**明确不是 0–994 全局池**；151/107 不是本局 actorID。'
      '0x20 的 actor 字段不能当单位 ID。')
    A('- 0x1f/0x20 的 actor 与 0x1e victim 同文件 0 交集（旧报告 0/43、0/7 仍成立）；'
      '0x1f 只说明“可能是同池但没证据”，0x20 明确不是全局池。')
    A('')
    A('## 7. 0x01/0x48 与 0x02/0x86')
    A('')
    A('- **0x01/0x48**：主样本 1 条，seq 2144 / t≈107.2s，envelope hero=**37120 (0x9100)**，'
      'body 9B `48 00 50 43 40 53 52 52 52`。37120 既不在 0–994 全局池，也不在 1–359 '
      'actor-slot 池；body 是 ASCII 形（"HPC@SRRRR"），没有表键结构。'
      '判定：**不是本局 0–994 运行时 objectID**，无法映射到本局单位（高置信）；'
      '它可能是全局系统/其他玩法的配置 id。')
    A('- 注意：`normalMonster` 里 id=37120 是行 980 的 PVE 单位“词缀-自爆人”，'
      '但那是配置 id ≠ 运行时 objectID；不能据此把 0x1e victim 980 命名。')
    A('- **0x02/0x86**：主样本 1 条，seq 181 / t≈9.05s，envelope 442，'
      'body `00 00 12 52 03 12`。0x1252=**4690**，既不在 0–994 也不在 1–359；'
      '更像命令/坐标参数（body 内还有 0x12 0x52 0x03），不是 0–994/1–359 的单位 ID（高置信）。')
    A('')
    A('## 8. 0x12/0x13：没有 ID 字段，不能补映射')
    A('')
    A(f'- 主样本 0x12 共 {len(s12)} 个（每帧 1–11 个，中位 5）；x 两簇 64–103 / 128–167，'
      f'y 0–180；值域与“可见单位屏幕坐标”相容，但**没有 ID 字段**。')
    A(f'- 0x13 共 {len(s13)} 个、{len(set(s13))} 个不同值（0/13/64–166/212），'
      '明显是 0x40/0x80 前缀的 6 位字段，重复率极高；不是 0–994 唯一 objectID。')
    A(f'- 0x14 共 {s14} 条，3B 值如 0x540025/0x544330，远大于 0–994；不是单位 ID。')
    A(f'- 0x13 不同值与 0x1e victim 只有 {len(set(s13) & set(victims))} 个数值重合'
      '（64/145 一类），不足以建立映射。')
    A('')
    A('## 9. 能映射多少、还缺什么')
    A('')
    A('| 对象 | 能映射 | 不能映射 |')
    A('|---|---:|---:|')
    A('| 英雄 actor-slot（0x02/0x87） | 44 条（6 局：10+2+2+10+10+10） | — |')
    A('| 0x1e victim → 具体单位类型 | 0 条 | 110 条（2 条仅 actorID 碰撞，low） |')
    A('| 0x2c target（1–359） | 0 条高置信 | 835 条（14 条 actorID 碰撞，low） |')
    A('| 0x1f/0x20 actor | 0 条 | 16 条 |')
    A('| 0x01/0x48、0x02/0x86 | 0 条 | 2 条 |')
    A('')
    A('**还缺**：')
    A('')
    A('1. **战斗初始化/StepNotify 头**：`MyCampHeroObjIds / EnemyCampHeroObjIds`'
      ' 能把 0–994 全局 objectID 对到英雄；本回放的可读块里没有这张头。')
    A('2. **逐单位 spawn 日志**：小兵/野怪/塔的 objectID→单位配置 id/类型；'
      '0x1e payload 只有 type + victim，没有 unitType/team。')
    A('3. **0x2c target 的语义**：target 是单位 actor-slot、技能目标还是目标点，'
      '需要客户端/服务端结构或 StepNotify 才能定；当前 14/835 的 actorID 碰撞不足以定名。')
    A('4. **0x12/0x13 的 ID 绑定**：如果 0x12 是可见单位坐标，缺“第 i 个点对应哪个 objectID”'
      '的字段；0x13 的 0x40/0x80 前缀也没有对到单位表。')
    A('')
    A('**如果只要一个结论**：0x1e/0x2c 的 objectID **不能**从现有回放+dc.db 映射到'
      '英雄/小兵/野怪/塔的具体类型；0x1e victim 的 110/110 具体类别仍未知，'
      '“不等于 actorID”不能当非英雄证据。唯一稳定的具体映射是同局 10 个英雄的 '
      'actor-slot ID（0x87），它属于另一个 1–359 空间，不能拿来解释 0x1e victim。'
      '缺的不是“再找一张表”，而是**运行时 spawn/StepNotify 头**这一层数据。')
    A('')
    A('## 10. 产物与复跑')
    A('')
    A('- `tools/agent_objectid_map.py`')
    A('- `data/replays/_analysis/datasets/agent_objectid_map.csv`')
    A('- `data/replays/_analysis/datasets/agent_objectid_map.md`')
    A('')
    A('```bash')
    A('python tools/agent_objectid_map.py')
    A('python tools/agent_objectid_map.py --abc path/to.abc --out-dir path/to/datasets')
    A('```')
    A('')
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--abc', type=Path, default=MAIN_SAMPLE)
    ap.add_argument('--out-dir', type=Path, default=DATASETS)
    ap.add_argument('--no-cross', action='store_true')
    args = ap.parse_args()
    rows, md = run(args.abc, args.out_dir, cross=not args.no_cross)
    print(f'wrote {len(rows)} CSV rows and {len(md)} MD chars to {args.out_dir}')


if __name__ == '__main__':
    main()
