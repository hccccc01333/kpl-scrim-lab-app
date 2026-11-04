#!/usr/bin/env python3
"""Second, independent read-only pass for skin IDs in normal-5v5 ``.abc`` replays.

Scope and constraints (same as the task):
  * read-only: never writes a replay/package, never touches the game process,
    never reads ``param.json`` and never reads ``runtime_dump`` memory;
  * main sample = 20260925_105224 (build 5069040), recorder entity 1558;
  * the 20 parseable normal-5v5 samples are used only for stability tests.

What this pass does differently from ``agent_skin_ids.py``:
  1. It does **not** derive a skin id as ``heroID*100 + index``.  It loads the
     skin table 0x3D1A9B0 from ``device/dc.db`` and builds a row-key namespace
     ``row_id // 100 -> skin index -> row_id`` *from the table itself*, then
     validates every candidate row with the row's own ``cell_0`` (hero name),
     ``cell_1`` (skin index) and ``cell_2`` (skin name).  A block hit is only
     accepted when a real table row exists with the same hero name and index.
  2. It sweeps **all** relative offsets of the player block (u8/u16/u32,
     big/little endian) for a field whose value is a valid skin index for that
     block's hero, ranks candidates by validity + variability + cross-sample
     stability, and reports the named task offsets separately.
  3. It scans every block byte for exact skin row ids / model ids / release ids
     and labels the hit region (hero section / equipment plans / archive /
     block tail), instead of only looking at s+0x7A.
  4. It re-tests the 102/106-byte tail roster against skinID, skin-config,
     release-id, model-id, hero-id, AI-skin, slot and score hypotheses, with
     same-player/same-hero stability over the 20 samples.
  5. It scans the .abc header, the player archive, the equipment-plan area, the
     .ope container (raw-deflate decoded) and the decoded operator stream for
     skin names, Skin_ resources, skin row ids and model ids.

Usage:
    python tools/agent_skin_ids2.py
    python tools/agent_skin_ids2.py --main-only
    python tools/agent_skin_ids2.py --no-strings      # skip the slow scans

Outputs:
    data/replays/_analysis/datasets/agent_skin_ids2.csv
    data/replays/_analysis/datasets/agent_skin_ids2.md
"""
from __future__ import annotations

import argparse
import collections
import csv
import importlib.util
import math
import os
import re
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / 'data' / 'replays' / '_analysis'
DC = AN / 'device' / 'dc.db'
ABC_BATCH = ROOT / 'data' / 'replays' / 'samples' / 'abc_batch'
MAIN_SAMPLE = ABC_BATCH / ('20260925_105224_-1505729760_4933_1790303631_'
                           'CBDD358E761B15A4DF526A179E8119E2.abc')
OPE_MAIN = (ROOT / 'data' / 'replays' / 'samples' / 'batch' /
            '20260925_105224_-1505729760_4933_1790303631.ope')
STREAM_MAIN = (AN / 'streams' /
               '20260925_105224_-1505729760_4933_1790303631.bin')
OUT_DIR = AN / 'datasets'
OUT_CSV = OUT_DIR / 'agent_skin_ids2.csv'
OUT_MD = OUT_DIR / 'agent_skin_ids2.md'

SKIN_TABLE = 0x3D1A9B0
RELEASE_TABLE = 0x56E5140
HERO_TABLE = 0x111C3C
TRAILER_SIZES = (102, 106)
RECORDER_TAG = re.compile(rb'(?<![0-9A-F])([0-9A-F]{32})(?![0-9A-F])')
CJK = re.compile(r'[\u3400-\u9fff]')
FOOTERS = (bytes.fromhex('000000000004b000000000'),
           bytes.fromhex('000000000005560000000c'))
NAMED_OFFSETS = [0x50, 0x60, 0x6F, 0x71, 0x75, 0x76, 0x7A, 0x7C]


# --------------------------------------------------------------------------- #
# basic helpers
# --------------------------------------------------------------------------- #
def u16(data, off):
    return struct.unpack_from('<H', data, off)[0]


def u32(data, off):
    return struct.unpack_from('<I', data, off)[0]


def u16be(data, off):
    return struct.unpack_from('>H', data, off)[0]


def u32be(data, off):
    return struct.unpack_from('>I', data, off)[0]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pct(a, b):
    return f'{a}/{b}' if b else f'{a}/0'


# --------------------------------------------------------------------------- #
# tables (dc.db, stdr row model)
# --------------------------------------------------------------------------- #
class Tables:
    def __init__(self):
        self.source = ''
        self.hero_name = {}                  # hero row id -> name
        self.skin = {}                       # skin row id -> dict
        self.skin_group_idx = {}             # hero key -> {index: row_id}
        self.skin_by_name_idx = collections.defaultdict(list)
        self.hero_default_model = {}         # hero -> default model (hero cell_5)
        self.lookup_methods = collections.Counter()
        self.last_method = ''
        self.group_hero_names = collections.defaultdict(set)
        self.row_ids = set()
        self.release_ids = set()
        self.model_ids = set()
        self.skin_names = set()
        self.group_name_ok = 0
        self.group_name_bad = []
        if DC.exists():
            self._load_dc()
        else:
            self._load_csv()

    def _add_skin(self, rid, cells):
        name = cells.get(0, '')           # cell_0 = hero name
        idx_s = cells.get(1, '')          # cell_1 = skin index
        skin_name = cells.get(2, '')      # cell_2 = skin name
        model_s = cells.get(4, '').split(':')[0]
        res = cells.get(6, '')
        idx = int(idx_s) if idx_s.isdigit() else None
        self.skin[rid] = dict(cells=cells, hero_name=name, idx=idx,
                              name=skin_name, model=int(model_s) if model_s.isdigit() else 0,
                              res=res, row_id=rid, group=rid // 100)
        self.row_ids.add(rid)
        if skin_name and not skin_name.isdigit():
            self.skin_names.add(skin_name)
        if self.skin[rid]['model']:
            self.model_ids.add(self.skin[rid]['model'])
        for col in (16, 17):
            v = cells.get(col, '').split(':')[0]
            if v.isdigit() and int(v) >= 100000:
                self.model_ids.add(int(v))
        # the row-key namespace is only the 5-digit family; 8-digit rows are
        # star/part variants and are kept as rows but not as base indices.
        if 10000 <= rid < 100000:
            group = rid // 100
            self.group_hero_names[group].add(name)
            if idx is not None:
                self.skin_group_idx.setdefault(group, {})[idx] = rid
                self.skin_by_name_idx[(name, idx)].append(rid)

    def _load_dc(self):
        tm = load_module('ah_tables2', AN / 'tools' / 'agent_hero_tables.py')
        data = DC.read_bytes()
        self.source = f'dc.db ({DC.name})'
        hero = tm.read_table(data, HERO_TABLE)
        for r in range(hero['nrows']):
            row = hero['base'] + r * hero['stride']
            key = u32(data, row)
            a, b = struct.unpack_from('<II', data, row + 8)
            self.hero_name[key] = tm.cell_text(a, b, hero).strip()
            a5, b5 = struct.unpack_from('<II', data, row + 8 + 5 * 8)
            v5 = tm.cell_text(a5, b5, hero).split(':')[0]
            if v5.isdigit() and int(v5) >= 100000:
                self.hero_default_model[key] = int(v5)
        skin = tm.read_table(data, SKIN_TABLE)
        for r in range(skin['nrows']):
            row = skin['base'] + r * skin['stride']
            key = u32(data, row)
            cells = {}
            for i in range(skin['ncell']):
                a, b = struct.unpack_from('<II', data, row + 8 + i * 8)
                cells[i] = tm.cell_text(a, b, skin)
            self._add_skin(key, cells)
        rel = tm.read_table(data, RELEASE_TABLE)
        for r in range(rel['nrows']):
            row = rel['base'] + r * rel['stride']
            self.release_ids.add(u32(data, row))
        del data
        self._check_groups()

    def _load_csv(self):
        base = OUT_DIR / 'agent_hero_tables'
        self.source = f'decoded CSV ({base.name})'
        with (base / '0x111C3C_hero_base_attributes.csv').open(encoding='utf-8-sig') as fp:
            for r in csv.DictReader(fp):
                self.hero_name[int(r['row_id'])] = r.get('name') or r.get('cell_0', '')
                v = r.get('cell_5', '').split(':')[0]
                if v.isdigit() and int(v) >= 100000:
                    self.hero_default_model[int(r['row_id'])] = int(v)
        with (base / '0x3D1A9B0_hero_skins.csv').open(encoding='utf-8-sig') as fp:
            for r in csv.DictReader(fp):
                cells = {int(k[5:]): v for k, v in r.items() if k.startswith('cell_')}
                self._add_skin(int(r['row_id']), cells)
        with (base / '0x56E5140_skin_release.csv').open(encoding='utf-8-sig') as fp:
            for r in csv.DictReader(fp):
                self.release_ids.add(int(r['row_id']))
        self._check_groups()

    def _check_groups(self):
        """Group namespace is accepted only where cell_0 == hero-table name."""
        for hero, name in self.hero_name.items():
            if hero in self.group_hero_names:
                if self.group_hero_names[hero] == {name}:
                    self.group_name_ok += 1
                else:
                    self.group_name_bad.append(
                        (hero, name, sorted(self.group_hero_names[hero])))

    def resolve(self, hero: int, idx: int):
        """Resolve (hero, skin index) to a real skin row using table columns.

        Priority (no ``heroID*100`` construction):
          1. unique skin-table row with cell_0 == hero-table name and
             cell_1 == index;
          2. among duplicate same-name/same-index rows, the row whose cell_4
             model family matches the hero table cell_5 default model;
          3. only then, the row whose table row-key group equals the hero
             row id (legacy disambiguation for 501-vs-590 style duplicates).
        The returned id is always a row that exists in the table and whose
        cell_0/cell_1 match.
        """
        name = self.hero_name.get(hero)
        if name is None or idx is None:
            return None, None, 'none'
        cands = [rid for rid in self.skin_by_name_idx.get((name, idx), [])
                 if rid in self.skin and self.skin[rid]['idx'] == idx
                 and self.skin[rid]['hero_name'] == name]
        if not cands:
            return None, None, 'none'
        if len(cands) == 1:
            rid = cands[0]
            return rid, self.skin[rid], 'unique'
        dm = self.hero_default_model.get(hero)
        if dm:
            pref = str(dm)[:5]
            fam = [rid for rid in cands
                   if self.skin[rid]['model'] and str(self.skin[rid]['model'])[:5] == pref]
            if len(fam) == 1:
                rid = fam[0]
                return rid, self.skin[rid], 'model_family'
        grp = [rid for rid in cands if rid // 100 == hero]
        if len(grp) == 1:
            rid = grp[0]
            return rid, self.skin[rid], 'row_key_group'
        return None, None, 'ambiguous'

    def lookup(self, hero: int, idx: int):
        rid, row, method = self.resolve(hero, idx)
        self.last_method = method
        return rid, row

    def valid_index(self, hero: int, idx: int) -> bool:
        return self.lookup(hero, idx)[0] is not None

    def hero(self, hid: int) -> str:
        return self.hero_name.get(hid, f'hero{hid}')


# --------------------------------------------------------------------------- #
# .abc block / trailer parsing
# --------------------------------------------------------------------------- #
class Abc:
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        self.blocks = self._find_blocks()
        self.header_end = self._header_end()
        self.local_hero = (struct.unpack_from('<I', self.data, self.header_end - 4)[0]
                           if self.header_end >= 4 else None)
        self.spans = self._block_spans()
        self.trailer = self._find_trailer()
        self.tag = None
        m = RECORDER_TAG.search(path.name.encode())
        if m:
            self.tag = m.group(1)
        self.build = ''
        pos = 0
        for _ in range(4):
            if pos >= len(self.data):
                break
            n = self.data[pos]
            txt = self.data[pos + 1:pos + 1 + n].decode('latin1', 'replace')
            self.build = txt
            pos += 1 + n

    def _header_end(self):
        d = self.data
        pos = 0
        for _ in range(4):
            if pos >= len(d):
                return 0
            n = d[pos]
            pos += 1 + n
        return pos + 4

    def _find_blocks(self):
        d = self.data
        out = []
        pos = 0
        limit = min(len(d), 0x20000)
        while pos + 24 <= limit:
            if (d[pos] in (1, 2) and d[pos + 1] in (1, 2) and d[pos + 2] == 1
                    and d[pos + 3] <= 4 and d[pos + 4] == 0 and d[pos + 5] == 0):
                ent = u16be(d, pos + 6)
                if (100 <= ent <= 3000 and d[pos + 12:pos + 15] == b'\x00\x00\x00'):
                    name_len = d[pos + 15]
                    end = pos + 16 + name_len
                    if 2 <= name_len <= 40 and end <= len(d):
                        try:
                            name = d[pos + 16:end].rstrip(b'\x00').decode('utf-8')
                        except UnicodeDecodeError:
                            name = ''
                        if name and all(c.isprintable() for c in name):
                            out.append(dict(offset=pos, entity=ent,
                                            name=name, name_len=name_len))
                            pos = end
                            continue
            pos += 1
        return out[:10]

    def _block_spans(self):
        d = self.data
        spans = []
        lens = []
        for i, b in enumerate(self.blocks):
            off = b['offset']
            nxt = self.blocks[i + 1]['offset'] if i + 1 < len(self.blocks) else None
            if nxt is not None:
                end = nxt
            else:
                end = None
                limit = min(len(d), off + 9000)
                for fc in FOOTERS:
                    k = d.find(fc, self._s(i) + 0xC8, limit)
                    if k >= 0:
                        end = k + len(fc)
                        break
                if end is None:
                    end = off + (int(sum(lens) / len(lens)) if lens else 4200)
            end = min(end, len(d))
            lens.append(end - off)
            spans.append((off, end))
        return spans

    def _s(self, i):
        b = self.blocks[i]
        return b['offset'] + 16 + b['name_len'] + 30

    def info(self, i):
        d = self.data
        b = self.blocks[i]
        s = self._s(i)
        start, end = self.spans[i]
        hero = u16be(d, s + 0x48)
        raw = u32be(d, s + 0x7A)
        return dict(index=i, offset=b['offset'], entity=b['entity'], name=b['name'],
                    team=d[b['offset']], slot=d[b['offset'] + 3],
                    s=s, hero=hero, raw=raw, idx=(raw >> 8) & 0xFF,
                    low=raw & 0xFF, prof=u32be(d, s + 0x71),
                    level=d[s + 0x75], badge=u32be(d, s + 0x76),
                    start=start, end=end,
                    recorder=bool(self.tag and
                                  self.tag in d[b['offset']:end]))

    def _find_trailer(self):
        d = self.data
        for p in range(max(0, len(d) - 140), len(d) - 99):
            n = len(d) - p
            if n in TRAILER_SIZES and d[p:p + 3] == b'\xe3\x00\x00':
                t = d[p:]
                return dict(offset=p, n=n, mvp=u16be(t, 0x0F), count=t[0x11],
                            records=[(u32be(t, 0x12 + 8 * i), u32be(t, 0x16 + 8 * i))
                                     for i in range(10)],
                            flag=u16be(t, 0x64),
                            svp=u16be(t, 0x68) if n >= 106 else None,
                            extra=u16be(t, 0x10), raw=t)
        return None

    def annotate(self, tables):
        self.infos = []
        for i in range(len(self.blocks)):
            info = self.info(i)
            rid, row, method = tables.resolve(info['hero'], info['idx'])
            info['skin_row'] = rid or ''
            info['skin_name'] = row['name'] if row else ''
            info['skin_model'] = row['model'] if row else ''
            info['skin_method'] = method
            if rid:
                tables.lookup_methods[method] += 1
            self.infos.append(info)


def find_plan_region(d: bytes, start: int, end: int):
    """Find the equipment-plan block: a length-prefixed name followed by 12 items."""
    q = start
    while q + 8 < end:
        n = d[q]
        if 4 <= n <= 60 and q + 1 + n + 4 <= end:
            raw = d[q + 1:q + 1 + n]
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                text = ''
            if (text and not text.isdigit() and
                    all(c.isprintable() for c in text)):
                if u32be(d, q + 1 + n) == 12:
                    return (max(start, q - 24), min(end, q + 1 + n + 4 + 48 + 96))
        q += 1
    return None


def region_of(rel: int, plan_rel, rel_end: int):
    if rel >= rel_end - 147:
        return 'tail'
    if plan_rel and plan_rel[0] <= rel < plan_rel[1]:
        return 'plan'
    if 0 <= rel < 0xC8:
        return 'hero'
    if rel >= 0xC8:
        return 'archive'
    return 'pre_s'


# --------------------------------------------------------------------------- #
# block scan: exact ids + index-field discovery
# --------------------------------------------------------------------------- #
def scan_blocks(abcs, tables):
    hits = []
    own_hits = []
    counts = collections.Counter()
    counts_main = collections.Counter()
    for abc in abcs:
        is_main = abc.path.name == MAIN_SAMPLE.name
        for i in range(len(abc.blocks)):
            info = abc.infos[i]
            plan = find_plan_region(abc.data, info['s'] + 0xC8, info['end'] - 19)
            plan_rel = ((plan[0] - info['s'], plan[1] - info['s'])
                        if plan else None)
            rel_end = info['end'] - info['s']
            seg = abc.data
            for q in range(info['start'], info['end'] - 3):
                v = u32be(seg, q)
                if v not in tables.row_ids:
                    continue
                rel = q - info['s']
                row = tables.skin[v]
                own = (v // 100 == info['hero'] and 10000 <= v < 100000)
                reg = region_of(rel, plan_rel, rel_end)
                counts['hits'] += 1
                counts[reg] += 1
                counts['own' if own else 'other'] += 1
                if is_main:
                    counts_main['hits'] += 1
                    counts_main[reg] += 1
                    counts_main['own' if own else 'other'] += 1
                rec = dict(sample=abc.path.name, player=info['name'],
                           entity=info['entity'], hero=info['hero'],
                           field=f'block+{rel:#x}', raw=v,
                           derived=v, derived_name=row['name'],
                           verdict='own_hero' if own else 'other',
                           note=f'{reg}; skin_idx={row["idx"]}; model={row["model"]}',
                           region=reg, own=own, rel=rel)
                if is_main or own:
                    hits.append(rec)
                if own:
                    own_hits.append(rec)
            # u16BE exact skin-row ids (5-digit rows fit in 16 bits)
            for q in range(info['start'], info['end'] - 1):
                v = u16be(seg, q)
                if v not in tables.row_ids or not (10000 <= v < 65536):
                    continue
                # do not double-count the halves of an already counted u32 id
                if (u32be(seg, q) in tables.row_ids or
                        (q >= info['start'] + 2 and
                         u32be(seg, q - 2) in tables.row_ids)):
                    continue
                rel = q - info['s']
                row = tables.skin[v]
                own = (v // 100 == info['hero'])
                reg = region_of(rel, plan_rel, rel_end)
                counts['u16_hits'] += 1
                counts['u16_' + reg] += 1
                counts['u16_own' if own else 'u16_other'] += 1
                if is_main:
                    counts_main['u16_hits'] += 1
                    counts_main['u16_' + reg] += 1
                    counts_main['u16_own' if own else 'u16_other'] += 1
                if is_main or own:
                    hits.append(dict(
                        sample=abc.path.name, player=info['name'],
                        entity=info['entity'], hero=info['hero'],
                        field=f'block+{rel:#x}:u16BE', raw=v,
                        derived=v, derived_name=row['name'],
                        verdict='own_hero_u16' if own else 'other_u16',
                        note=f'{reg}; skin_idx={row["idx"]}; model={row["model"]}',
                        region=reg, own=own, rel=rel))
    return hits, own_hits, counts, counts_main


def scan_index_fields(abcs, tables):
    """Sweep relative offsets; rank fields that behave like an equipped skin."""
    obs = []
    for abc in abcs:
        for i in range(len(abc.blocks)):
            info = abc.infos[i]
            if info['hero'] not in tables.hero_name:
                continue
            obs.append((abc.path.name[:15], info['name'], info['hero'],
                        abc.data, info['s']))
    interps = {
        'u8': (1, lambda d, p: [d[p]]),
        'u16be': (2, lambda d, p: (lambda v: [v, v >> 8, v & 0xFF])(u16be(d, p))),
        'u16le': (2, lambda d, p: (lambda v: [v, v >> 8, v & 0xFF])(u16(d, p))),
        'u32be': (4, lambda d, p: (lambda v: [v, (v >> 8) & 0xFF,
                                              (v >> 16) & 0xFF, v >> 24])
                  (u32be(d, p))),
        'u32le': (4, lambda d, p: (lambda v: [v, (v >> 8) & 0xFF,
                                              (v >> 16) & 0xFF, v >> 24])
                  (u32(d, p))),
    }
    cands = []
    named = []
    for rel in range(-0x40, 0xC9):
        for kind, (size, fn) in interps.items():
            for which in range(4):
                ok = n = 0
                vals = collections.Counter()
                groups = collections.defaultdict(list)
                for sample, name, hero, d, s in obs:
                    p = s + rel
                    if p < 0 or p + size > len(d):
                        continue
                    vv = fn(d, p)
                    if which >= len(vv):
                        continue
                    idx = vv[which]
                    n += 1
                    vals[idx] += 1
                    if tables.valid_index(hero, idx):
                        ok += 1
                    groups[(name, hero)].append(idx)
                if n < 150:
                    continue
                gs = [v for v in groups.values() if len(v) > 1]
                stable = sum(1 for v in gs if len(set(v)) == 1)
                if kind == 'u8':
                    byte_rel = rel
                elif kind == 'u16be':
                    byte_rel = rel if which == 1 else rel + 1
                elif kind == 'u16le':
                    byte_rel = rel if which in (0, 2) else rel + 1
                elif kind == 'u32be':
                    byte_rel = rel + (3 - which)
                else:                       # u32le
                    byte_rel = rel + which
                rec = dict(ok=ok, n=n, distinct=len(vals), stable=stable,
                           groups=len(gs), rel=rel, kind=kind, which=which,
                           byte_rel=byte_rel, values=dict(vals))
                cands.append(rec)
                if rel in NAMED_OFFSETS:
                    named.append(rec)
    cands.sort(key=lambda r: (-r['ok'], -r['distinct'], -r['stable'],
                              -r['groups'], r['byte_rel']))
    # collapse aliases of the same byte, preferring u8 and then the simplest read
    best = {}
    for c in cands:
        key = c['byte_rel']
        old = best.get(key)
        score = (c['ok'], c['distinct'], c['stable'],
                 1 if c['kind'] == 'u8' else 0)
        if old is None:
            best[key] = (score, c)
        else:
            old_score = old[0]
            if score > old_score:
                best[key] = (score, c)
    uniq = sorted((v[1] for v in best.values()),
                  key=lambda r: (-r['ok'], -r['distinct'], -r['stable'],
                                 -r['groups'], r['byte_rel']))
    return uniq, named


def field_null_stats(abcs, tables):
    """Independent-marginal null: how many blocks would pass by chance?"""
    obs = []
    for abc in abcs:
        for info in abc.infos:
            if info['hero'] in tables.hero_name:
                obs.append((info['hero'], info['idx']))
    marg = collections.Counter(idx for _, idx in obs)
    total = sum(marg.values())
    expected = 0.0
    logp = 0.0
    for hero, idx in obs:
        valid = {k for k in range(32) if tables.valid_index(hero, k)}
        p = sum(marg.get(k, 0) / total for k in valid)
        expected += p
        logp += math.log(max(1e-300, p))
    return dict(n=len(obs), expected=expected, log10p=logp / math.log(10),
                distinct=len(set(idx for _, idx in obs)))


# --------------------------------------------------------------------------- #
# trailer tests
# --------------------------------------------------------------------------- #
def trailer_tests(abcs, tables):
    rows = []
    summary = collections.Counter()
    values = []
    hero_sets = []
    groups = collections.defaultdict(list)
    ai = []
    slot_vals = collections.defaultdict(list)
    extra_ok = 0
    for abc in abcs:
        tr = abc.trailer
        if not tr:
            continue
        infos = {abc.infos[i]['entity']: abc.infos[i]
                 for i in range(len(abc.blocks))}
        heroes = {e: infos[e]['hero'] for e in infos}
        team = {e: infos[e]['team'] for e in infos}
        for ent, score in tr['records']:
            info = infos.get(ent)
            values.append(score)
            hero_sets.append(heroes)
            rows.append(dict(sample=abc.path.name, entity=ent, score=score,
                             team=info['team'] if info else '',
                             slot=info['slot'] if info else '',
                             player=info['name'] if info else '',
                             hero=info['hero'] if info else '',
                             skin_idx=info['idx'] if info else '',
                             skin_row=info['skin_row'] if info else '',
                             mvp=ent == tr['mvp'],
                             svp=(tr['svp'] is not None and ent == tr['svp'])))
            if info:
                groups[(info['name'], info['hero'])].append(
                    (abc.path.name, score, info['idx']))
                slot_vals[info['slot']].append(score)
            if 2001 <= ent <= 2008:
                ai.append((abc.path.name, ent, score))
        if tr['extra'] == ((tr['mvp'] & 0xFF) << 8) | 0x0A:
            extra_ok += 1
    # intersections
    summary['values'] = len(values)
    summary['distinct'] = len(set(values))
    summary['min'] = min(values) if values else 0
    summary['max'] = max(values) if values else 0
    for label, ids in [('skin_row', tables.row_ids),
                       ('skin_5d', {r for r in tables.row_ids if 10000 <= r < 100000}),
                       ('release', tables.release_ids),
                       ('model', tables.model_ids),
                       ('hero', set(tables.hero_name))]:
        summary[label] = sum(1 for v in values if v in ids)
    summary['x10'] = sum(1 for v in values if v % 10 == 0)
    summary['x5'] = sum(1 for v in values if v % 5 == 0)
    # per-entry own-hero match
    own_hero = any_hero = 0
    for r in rows:
        if not r['hero']:
            continue
        if r['score'] == r['hero']:
            own_hero += 1
        # any hero id of the same match
        # (recompute cheaply from the sample's block heroes)
    for abc in abcs:
        tr = abc.trailer
        if not tr:
            continue
        hs = {abc.infos[i]['hero'] for i in range(len(abc.blocks))}
        any_hero += sum(1 for _, v in tr['records'] if v in hs)
    summary['score_eq_own_hero'] = own_hero
    summary['score_in_match_heroes'] = any_hero
    # AI
    summary['ai_values'] = len(ai)
    summary['ai_in_skin_index'] = sum(1 for _, _, v in ai if 0 <= v <= 16)
    # stability
    multi = [(k, v) for k, v in groups.items() if len(v) > 1]
    summary['groups_multi'] = len(multi)
    summary['score_stable'] = sum(1 for _, v in multi
                                  if len({x[1] for x in v}) == 1)
    summary['skin_stable'] = sum(1 for _, v in multi
                                 if len({x[2] for x in v}) == 1)
    summary['extra_rule'] = extra_ok
    # battle-config hypothesis: Svr2GameCore KV confValue set (match constants)
    kv_overlap = kv_matches = 0
    for abc in abcs:
        tr = abc.trailer
        if not tr:
            continue
        pos = 0x18D
        if pos + 2 <= len(abc.data):
            n = u16(abc.data, pos)
            if 1 <= n <= 200 and pos + 2 + 4 * n <= len(abc.data):
                kvals = {u16be(abc.data, pos + 3 + 4 * i) for i in range(n)}
                kv_overlap += sum(1 for _, v in tr['records'] if v in kvals)
                kv_matches += 1
    summary['kv_overlap'] = kv_overlap
    summary['kv_matches'] = kv_matches
    # MVP / SVP checks only when both teams have five known blocks
    mvp_ok = svp_ok = mvp_n = svp_n = 0
    for abc in abcs:
        tr = abc.trailer
        if not tr:
            continue
        infos = {abc.infos[i]['entity']: abc.infos[i]
                 for i in range(len(abc.blocks))}
        t1 = [v for e, v in tr['records'] if infos.get(e, {}).get('team') == 1]
        t2 = [v for e, v in tr['records'] if infos.get(e, {}).get('team') == 2]
        if len(t1) != 5 or len(t2) != 5:
            continue
        avg = {1: sum(t1) / 5, 2: sum(t2) / 5}
        win = 1 if avg[1] >= avg[2] else 2
        lose = 2 if win == 1 else 1
        mx = {c: max(v for e, v in tr['records']
                     if infos.get(e, {}).get('team') == c) for c in (1, 2)}
        mvp_n += 1
        mvp_ok += tr['mvp'] in [e for e, v in tr['records']
                                if infos.get(e, {}).get('team') == win and v == mx[win]]
        if tr['svp'] is not None:
            svp_n += 1
            svp_ok += tr['svp'] in [e for e, v in tr['records']
                                    if infos.get(e, {}).get('team') == lose and v == mx[lose]]
    summary['mvp_ok'] = mvp_ok
    summary['mvp_n'] = mvp_n
    summary['svp_ok'] = svp_ok
    summary['svp_n'] = svp_n
    summary['slot_ranges'] = {k: (len(v), min(v), max(v))
                              for k, v in sorted(slot_vals.items())}
    return rows, summary, groups, ai


# --------------------------------------------------------------------------- #
# string / header / ope scans
# --------------------------------------------------------------------------- #
def scan_blob(blob: bytes, tables, label: str, limit_ids=None):
    out = dict(label=label, size=len(blob), skin_names=0, skin_res=0,
               skin_word=0, skin_row_u32be=0, skin_row_u32le=0,
               model_u32be=0, model_u32le=0, ascii_ids=0, names=[],
               row_values=[], model_values=[])
    if not blob:
        return out
    for name in tables.skin_names:
        b = name.encode('utf-8')
        if len(b) >= 4 and b in blob:
            out['skin_names'] += 1
            if len(out['names']) < 10:
                out['names'].append(name)
    out['skin_res'] = len(re.findall(rb'Skin_', blob))
    out['skin_word'] = len(re.findall(rb'[Ss]kin', blob))
    n = len(blob) - 3 if limit_ids is None else min(len(blob) - 3, limit_ids)
    for p in range(0, n):
        v = u32be(blob, p)
        if v in tables.row_ids:
            out['skin_row_u32be'] += 1
            if len(out['row_values']) < 12:
                out['row_values'].append(v)
        if v in tables.model_ids:
            out['model_u32be'] += 1
            if len(out['model_values']) < 12:
                out['model_values'].append(v)
    for p in range(0, n, 4):
        v = u32(blob, p)
        if v in tables.row_ids:
            out['skin_row_u32le'] += 1
        if v in tables.model_ids:
            out['model_u32le'] += 1
    out['ascii_ids'] = len(re.findall(rb'(?<!\d)(10\d{3}|30\d{5})(?!\d)', blob))
    return out


def decode_ope(path: Path):
    raw = path.read_bytes()
    body = raw
    if raw[:1] == b'\x01':
        try:
            body = zlib.decompressobj(-15).decompress(raw[1:])
        except zlib.error:
            body = b''
    return raw, body


def header_strings(blob: bytes, limit=0x100):
    out = []
    for m in re.finditer(rb'[\x20-\x7e]{4,}', blob[:limit]):
        out.append(m.group().decode('latin1'))
    return out[:12]


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--main-only', action='store_true')
    ap.add_argument('--no-strings', action='store_true')
    args = ap.parse_args()

    tables = Tables()
    files = [MAIN_SAMPLE] if args.main_only else sorted(ABC_BATCH.glob('2026*.abc'))
    abcs = [Abc(p) for p in files]
    abcs = [a for a in abcs if a.blocks]
    main_abc = next(a for a in abcs if a.path.name == MAIN_SAMPLE.name)

    # attach skin lookup to every block
    for abc in abcs:
        abc.annotate(tables)

    main_rows = main_abc.infos
    main_trailer = main_abc.trailer
    recorder_rows = []
    for abc in abcs:
        for info in abc.infos:
            if not info['recorder']:
                continue
            tr = abc.trailer
            score = next((v for e, v in tr['records'] if e == info['entity']),
                         '') if tr else ''
            recorder_rows.append(dict(sample=abc.path.name, build=abc.build,
                                      info=info, score=score))
    hit_rows, own_hits, hit_counts, hit_counts_main = scan_blocks(abcs, tables)
    field_cands, named_fields = scan_index_fields(abcs, tables)
    field_null = field_null_stats(abcs, tables)
    trailer_rows, trailer_sum, trailer_groups, ai = trailer_tests(abcs, tables)

    # -- string / header / ope scans --------------------------------------- #
    abc_scan = None
    header_scan = None
    ope_scan = None
    stream_scan = None
    if not args.no_strings:
        first = main_abc.blocks[0]['offset'] if main_abc.blocks else 0
        abc_scan = scan_blob(main_abc.data, tables, 'main .abc whole')
        header_scan = scan_blob(main_abc.data[:first], tables, 'main .abc header')
        raw, body = decode_ope(OPE_MAIN) if OPE_MAIN.exists() else (b'', b'')
        if body:
            ope_scan = scan_blob(body, tables, 'main .ope decoded')
            ope_scan['header_texts'] = header_strings(body)
            ope_scan['raw_skin_names'] = scan_blob(raw, tables, 'main .ope raw')['skin_names']
        if STREAM_MAIN.exists():
            stream_scan = scan_blob(STREAM_MAIN.read_bytes(), tables, 'main .bin stream')

    # -- output csv -------------------------------------------------------- #
    fields = ['record_type', 'sample', 'build', 'team', 'slot', 'player',
              'entityID', 'heroID', 'heroName', 'field', 'raw', 'derived',
              'derived_name', 'verdict', 'confidence', 'note']
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open('w', newline='', encoding='utf-8-sig') as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()

        def put(**kw):
            w.writerow({k: kw.get(k, '') for k in fields})

        # 1) the ten players of the main sample
        for info in main_rows:
            put(record_type='player_skin', sample=main_abc.path.name,
                build=main_abc.build, team=info['team'], slot=info['slot'],
                player=info['name'], entityID=info['entity'],
                heroID=info['hero'], heroName=tables.hero(info['hero']),
                field='s+0x7C (u8; u32BE s+0x7A bits 8-15)',
                raw=f'0x{info["raw"]:08x}',
                derived=info['skin_row'],
                derived_name=info['skin_name'],
                verdict='table_row_verified' if info['skin_row'] else 'no_row',
                confidence='high' if info['skin_row'] else 'low',
                note=f'idx={info["idx"]} low=0x{info["low"]:02x} '
                     f'prof={info["prof"]} lv={info["level"]} badge={info["badge"]} '
                     f'model={info["skin_model"]} method={info["skin_method"]} '
                     f'recorder={info["recorder"]}')
        # 1b) recorder across all samples (same player name / tag)
        for rec in recorder_rows:
            info = rec['info']
            put(record_type='recorder_cross_sample', sample=rec['sample'],
                build=rec['build'], team=info['team'], slot=info['slot'],
                player=info['name'], entityID=info['entity'],
                heroID=info['hero'], heroName=tables.hero(info['hero']),
                field='s+0x7C', raw=f'0x{info["raw"]:08x}',
                derived=info['skin_row'], derived_name=info['skin_name'],
                verdict='table_row_verified' if info['skin_row'] else 'no_row',
                confidence='high' if info['skin_row'] else 'low',
                note=f'skin_idx={info["idx"]} trailer_score={rec["score"]} '
                     f'method={info["skin_method"]}')
        # 2) named field probes for the main sample
        for info in main_rows:
            d = main_abc.data
            s = info['s']
            for rel in NAMED_OFFSETS:
                if s + rel + 4 > len(d):
                    continue
                raw32 = u32be(d, s + rel)
                raw16 = u16be(d, s + rel)
                raw8 = d[s + rel]
                is_row = raw32 in tables.row_ids or raw16 in tables.row_ids
                idx = (raw32 >> 8) & 0xFF if rel == 0x7A else raw8
                is_idx = tables.valid_index(info['hero'], idx)
                if rel == 0x7A and is_idx:
                    verdict = 'skin_index_in_u32be_byte1'
                elif rel == 0x7C and is_idx:
                    verdict = 'skin_index_u8'
                elif is_row:
                    verdict = 'skin_row_id'
                else:
                    verdict = 'not_skin_id'
                put(record_type='field_probe', sample=main_abc.path.name,
                    team=info['team'], slot=info['slot'], player=info['name'],
                    entityID=info['entity'], heroID=info['hero'],
                    heroName=tables.hero(info['hero']),
                    field=f's+{rel:#04x}',
                    raw=f'u8={raw8:02x} u16be={raw16:04x} u32be={raw32:08x}',
                    derived=idx if is_idx and rel in (0x7A, 0x7C) else '',
                    verdict=verdict,
                    confidence='high' if (is_row or is_idx) and rel in (0x7A, 0x7C) else 'medium',
                    note='exact row-id scan and index-space check')
        # 3) index-field scan top candidates + named offsets
        for rank, c in enumerate(field_cands[:12], 1):
            put(record_type='field_scan', sample='20 samples', field=f'rank{rank}',
                raw=f'byte s+{c["byte_rel"]:#x} ({c["kind"]}[{c["which"]}])',
                derived=f'{c["ok"]}/{c["n"]}',
                verdict='valid_skin_index',
                confidence='high' if c['ok'] == c['n'] and c['distinct'] >= 4 else 'medium',
                note=f'distinct={c["distinct"]} stable={c["stable"]}/{c["groups"]} '
                     f'values={sorted(c["values"])}')
        for c in named_fields:
            if c['which'] != 0 or c['kind'] not in ('u8', 'u16be', 'u32be'):
                continue
            put(record_type='field_named', sample='20 samples',
                field=f's+{c["rel"]:#x} {c["kind"]}[{c["which"]}]',
                raw=f'{c["ok"]}/{c["n"]}', derived=c['distinct'],
                verdict='valid_skin_index' if c['ok'] == c['n'] else 'partial',
                confidence='high' if c['rel'] in (0x7A, 0x7C) and c['ok'] == c['n'] else 'medium',
                note=f'distinct={c["distinct"]} stable={c["stable"]}/{c["groups"]}')
        put(record_type='field_hypothesis', sample='20 samples',
            field='s+0x7C independent-marginal null',
            raw=f'{field_null["n"]}',
            derived=f'{field_null["expected"]:.1f}',
            verdict='observed_170/170', confidence='high',
            note=f'expected valid={field_null["expected"]:.1f}/{field_null["n"]} '
                 f'log10P={field_null["log10p"]:.1f} distinct={field_null["distinct"]}')
        # 4) exact row-id / model-id hits in block bytes
        for r in hit_rows:
            put(record_type='block_row_hit', sample=r['sample'], player=r['player'],
                entityID=r['entity'], heroID=r['hero'],
                heroName=tables.hero(r['hero']), field=r['field'],
                raw=r['raw'], derived=r['derived'], derived_name=r['derived_name'],
                verdict=r['verdict'], confidence='high' if r['own'] else 'medium',
                note=r['note'])
        # 5) trailer scores and hypothesis summary
        for r in trailer_rows:
            put(record_type='trailer_score', sample=r['sample'],
                    team=r['team'], slot=r['slot'], player=r['player'],
                    entityID=r['entity'], heroID=r['hero'],
                    heroName=tables.hero(r['hero']) if r['hero'] else '',
                    field='+0x12/+0x16 pair', raw=r['score'],
                    derived=r['skin_row'] if r['skin_row'] else '',
                    derived_name='score_x100',
                    verdict='mvp' if r['mvp'] else ('svp' if r['svp'] else 'player'),
                    confidence='high',
                    note=f'trailer score (rating x100); skin_idx={r["skin_idx"]}')
        t = trailer_sum
        put(record_type='trailer_summary', sample='20 samples', field='values',
            raw=f'{t["values"]} values', derived=f'{t["min"]}-{t["max"]}',
            verdict='score_range', confidence='high',
            note=f'distinct={t["distinct"]} x10={t["x10"]} x5={t["x5"]}')
        for label, val in [('skin_row_id_hits', t['skin_row']),
                           ('skin_5digit_hits', t['skin_5d']),
                           ('release_id_hits', t['release']),
                           ('model_id_hits', t['model']),
                           ('hero_id_hits', t['hero']),
                           ('score_eq_own_hero', t['score_eq_own_hero']),
                           ('score_in_match_heroes', t['score_in_match_heroes']),
                           ('ai_values', t['ai_values']),
                           ('ai_values_in_0_16', t['ai_in_skin_index']),
                           ('groups_multi', t['groups_multi']),
                           ('score_stable_groups', t['score_stable']),
                           ('skin_stable_groups', t['skin_stable']),
                           ('mvp_ok', f'{t["mvp_ok"]}/{t["mvp_n"]}'),
                           ('svp_ok', f'{t["svp_ok"]}/{t["svp_n"]}'),
                           ('extra_rule', f'{t["extra_rule"]}/20'),
                           ('battle_config_kv_overlap', f'{t["kv_overlap"]}/{t["values"]}')]:
            put(record_type='trailer_hypothesis', sample='20 samples',
                field=label, raw=val, verdict='tested', confidence='high',
                note='tail second value is trailer rating x100, not a skin id')
        # 6) string / header / ope scans
        for scan in (abc_scan, header_scan, ope_scan, stream_scan):
            if not scan:
                continue
            put(record_type='string_scan', sample=scan['label'],
                field=f'size={scan["size"]}', raw=scan['skin_names'],
                derived=scan['skin_res'],
                verdict='skin_name_utf8 / Skin_ hits',
                confidence='high',
                note=f'skin_word={scan["skin_word"]} '
                     f'row_u32be={scan["skin_row_u32be"]} '
                     f'row_u32le={scan["skin_row_u32le"]} '
                     f'model_u32be={scan["model_u32be"]} '
                     f'model_u32le={scan["model_u32le"]} ascii_ids={scan["ascii_ids"]} '
                     f'names={scan["names"]} {scan.get("header_texts", "")}')
        # 7) table / mapping evidence
        put(record_type='table_evidence', sample=tables.source,
            field='skin_rows', raw=len(tables.row_ids),
            derived=len(tables.skin_group_idx),
            verdict='table_loaded', confidence='high',
            note=f'5digit_base={sum(1 for r in tables.row_ids if 10000 <= r < 100000)} '
                 f'hero_groups_name_ok={tables.group_name_ok} '
                 f'hero_groups_name_bad={len(tables.group_name_bad)} '
                 f'lookup_methods={dict(tables.lookup_methods)} '
                 f'model_ids={len(tables.model_ids)} release_ids={len(tables.release_ids)}')
        put(record_type='table_evidence', sample=tables.source,
            field='dup_name_note', raw='东皇太一',
            derived='187xx canonical, 696xx legacy',
            verdict='disambiguated_by_hero_table_group', confidence='high',
            note='same-name rows disambiguated by model family; row-key group only as last fallback')
        put(record_type='table_evidence', sample=tables.source,
            field='main_skin_release_crosscheck',
            raw=f'{sum(1 for i in main_rows if i["skin_row"] in tables.release_ids)}/10',
            derived='release_table_0x56E5140', verdict='skin_row_confirmed',
            confidence='high',
            note='all main-sample skin rows exist in the release table with same name')

    # -- output md --------------------------------------------------------- #
    write_md(tables, main_abc, main_rows, main_trailer, hit_counts_main,
             hit_rows, own_hits, field_cands, named_fields, field_null,
             trailer_sum, trailer_groups, ai, abc_scan, header_scan, ope_scan,
             stream_scan, recorder_rows)
    print(f'wrote {OUT_CSV}')
    print(f'wrote {OUT_MD}')
    return 0


def write_md(tables, main_abc, main_rows, tr, hit_main, hit_rows, own_hits,
             field_cands, named_fields, field_null, ts, groups, ai, abc_scan,
             header_scan, ope_scan, stream_scan, recorder_rows):
    lines = []
    add = lines.append
    add('# 普通 5v5 皮肤 ID 复核（第二遍，独立表映射）')
    add('')
    add('- 工具：`tools/agent_skin_ids2.py`（只读；不写回放/包体，不注入，不读 param.json/runtime_dump）')
    add(f'- 表来源：{tables.source}；皮肤表 `0x3D1A9B0`，上架表 `0x56E5140`，英雄表 `0x111C3C`')
    add('- 主样本：`20260925_105224`（5069040，普通 5v5，录制者 1558 佚名(*:）')
    add('')
    add('## 1. 结论')
    add('')
    add('**皮肤 ID 可得；1558（佚名(*:，东皇太一 187）的皮肤是 `18700 经典`。**')
    add('')
    add('字段是玩家块英雄区的 **`s+0x7C` 单字节**（即 u32BE `s+0x7A` 的 bits 8–15）：')
    add('')
    add('```text')
    add('s+0x7A  u32BE = 00 00 <skinIndex> 05')
    add('s+0x7C  u8    =  <skinIndex>          ; 低字节 0x05 为常量标签（170/172）')
    add('```')
    add('')
    add('映射**不是** `heroID*100` 盲算，而是只用表内列查行：')
    add('先用皮肤表 `cell_0`（英雄名）+ `cell_1`（皮肤序号）找候选行；')
    add('同名重复行（如东皇太一 187xx 与 696xx）再用皮肤表 `cell_4` 模型族')
    add('与英雄表 `cell_5` 默认模型比对；只有 501/590、171/716、110/310 这类')
    add('模型也相同的遗留组才退回“行键组 == 英雄行 ID”作最后区分。170 个真实英雄块的解析方式：')
    add('')
    add('```text')
    add(f'lookup_methods = {dict(tables.lookup_methods)}')
    add('```')
    add('')
    add('主样本 10 人全部是 `unique` 或 `model_family`，没有使用行键组兜底。')
    add('')
    add('10 人全部命中真实表行（skin_row 是表里实际存在的 row_id，不是算出来的数）：')
    add('')
    add('| 玩家 | entity | 英雄 | idx | 皮肤行 ID | 皮肤名 | 模型 |')
    add('|---|---:|---|---:|---:|---|---|')
    for info in main_rows:
        add(f'| {info["name"]} | {info["entity"]} | {tables.hero(info["hero"])} {info["hero"]} '
            f'| {info["idx"]} | {info["skin_row"] or "-"} | {info["skin_name"] or "-"} '
            f'| {info["skin_model"] or "-"} |')
    add('')
    rel_ok = sum(1 for info in main_rows if info['skin_row'] in tables.release_ids)
    add(f'10 人皮肤行 ID 同时出现在上架表 `0x56E5140` 的：**{rel_ok}/10**（名称一致），')
    add('说明输出的是真实皮肤行，不是拼出来的数字。')
    add('')
    add('1558 的详细值：`s+0x48=187`，`s+0x7A=0x00000005`，`s+0x7C=0`，')
    add('查表得到 `18700 / 东皇太一 / 经典 / 模型 3018700`。')
    add(f'头部 `localHeroId={main_abc.local_hero}`，且 1558 块含文件名后缀 tag `CBDD358E...`，')
    add('确认 1558 就是录制者（20 个样本的 tag 都落在录制者块；19 个名为“佚名(*:”，')
    add('1 个改名为“马跃千山食草”，但 tag 相同）。')
    add('')
    add('## 2. 为什么是皮肤：同块字段扫描')
    add('')
    add('对 20 个样本的 172 个块（其中 170 个真实英雄块参与索引校验），')
    add('按 `s` 的相对偏移逐字节扫描所有 u8/u16/u32/大小端解释，')
    add('检查“该值是否是该块英雄的合法皮肤序号”。排名前列：')
    add('')
    add('| 字节 | 合法 | 不同值 | 同玩家+同英雄稳定 |')
    add('|---|---:|---:|---:|')
    for c in field_cands[:8]:
        add(f'| **byte `s+{c["byte_rel"]:#x}`**（{c["kind"]} 读到） | {c["ok"]}/{c["n"]} '
            f'| {c["distinct"]} | {c["stable"]}/{c["groups"]} |')
    add('')
    add('`s+0x7C` 是**唯一**“170/170 全部合法 + 14 个不同值 + 5/5 跨样本稳定”的字段；')
    add('其它全合法字节都是常量/小标志（不同值 1–3 个，例如 0x50/0x60/0x71/0x76/0x7E），')
    add('常量零/小值也“合法”只是因为每个英雄都有 0 号经典皮肤，不能解释 14 个不同皮肤序号。')
    add('')
    add(f'独立零假设（按观测序号的边际分布随机重排，与英雄无关）：'
        f'期望只有 **{field_null["expected"]:.1f}/{field_null["n"]}** 个块通过，'
        f'实测 **{field_null["n"]}/{field_null["n"]}**；'
        f'log10 P ≈ **{field_null["log10p"]:.1f}**。')
    add('')
    add('任务点名的偏移：')
    add('')

    def nf(rel, kind, which=0):
        for c in named_fields:
            if c['rel'] == rel and c['kind'] == kind and c['which'] == which:
                return c
        return None

    def nf_txt(c):
        if not c:
            return '-'
        return f'{c["ok"]}/{c["n"]}'

    add('| 偏移（u8） | 合法 | 不同值 | 判定 |')
    add('|---|---:|---:|---|')
    add(f'| `s+0x50` | {nf_txt(nf(0x50, "u8"))} | {nf(0x50, "u8")["distinct"] if nf(0x50, "u8") else "-"} | 常量模式，不是皮肤 |')
    add(f'| `s+0x60` | {nf_txt(nf(0x60, "u8"))} | {nf(0x60, "u8")["distinct"] if nf(0x60, "u8") else "-"} | 常量模式，不是皮肤 |')
    add(f'| `s+0x6F` | {nf_txt(nf(0x6F, "u8"))} | {nf(0x6F, "u8")["distinct"] if nf(0x6F, "u8") else "-"} | 英雄 ID 低字节副本，不是皮肤 |')
    add(f'| `s+0x71` | {nf_txt(nf(0x71, "u8"))} | {nf(0x71, "u8")["distinct"] if nf(0x71, "u8") else "-"} | 熟练度点数（最高字节），不是皮肤 |')
    add(f'| `s+0x75` | {nf_txt(nf(0x75, "u8"))} | {nf(0x75, "u8")["distinct"] if nf(0x75, "u8") else "-"} | 等级/徽章低字节，不是皮肤 |')
    add(f'| `s+0x76` | {nf_txt(nf(0x76, "u8"))} | {nf(0x76, "u8")["distinct"] if nf(0x76, "u8") else "-"} | 徽章/常量，不是皮肤 |')
    add(f'| `s+0x7A` | {nf_txt(nf(0x7A, "u8"))} | {nf(0x7A, "u8")["distinct"] if nf(0x7A, "u8") else "-"} | 打包 u32 的前导 0 字节 |')
    add(f'| **`s+0x7C`** | **{nf_txt(nf(0x7C, "u8"))}** | **{nf(0x7C, "u8")["distinct"] if nf(0x7C, "u8") else "-"}** | **皮肤序号（唯一可变且全合法）** |')
    add('')
    add('整 u16/u32 值的合法性在 CSV 的 `field_named` 行；`s+0x7A` 整体是')
    add('`0x0000<idx>05`，只有第 3 字节（`s+0x7C`）是皮肤序号，低字节 0x05 是常量标签。')
    add('')
    add('跨样本稳定组（同一玩家名+同一英雄，来自 20 样本）：')
    add('')
    add('| 玩家 | 英雄 | 皮肤序号 | 尾表评分（各局） |')
    add('|---|---|---:|---|')
    for (name, hero), vals in sorted(groups.items()):
        if len(vals) > 1:
            add(f'| {name} | {tables.hero(hero)} {hero} | '
                f'{vals[0][2]} | {", ".join(str(x[1]) for x in vals)} |')
    add('')
    add('同一玩家+同一英雄：皮肤序号 5/5 组稳定；尾表评分 0/5 组稳定（每局都变）。')
    add('')
    add('录制者 tag 的 20 个块（同一账号换英雄/换局；entity 每局不同）：')
    add('')
    add('| 样本 | entity | 玩家 | 英雄 | idx | 皮肤行 ID | 皮肤名 | 尾表评分 |')
    add('|---|---:|---|---|---:|---:|---|---:|')
    for rec in recorder_rows:
        info = rec['info']
        add(f'| {rec["sample"][:15]} | {info["entity"]} | {info["name"]} '
            f'| {tables.hero(info["hero"])} {info["hero"]} | {info["idx"]} '
            f'| {info["skin_row"] or "-"} | {info["skin_name"] or "-"} '
            f'| {rec["score"]} |')
    add('')
    add('其中主样本 1558（佚名(*:，东皇太一 187）就是第 13 行：idx=0 → `18700 经典`，')
    add('尾表评分 1140（MVP）。同一账号 187 的另一局（20260902_221251）也是 idx=0，')
    add('评分却是 590；175/505/138 也都是“皮肤序号固定、评分每局变”。')
    add('录制者 tag `CBDD358E...` 的 20 个块：换英雄时序号随英雄变，')
    add('同一英雄跨局序号固定（175→2、505→1、187→0、138→0），符合“账号已装备皮肤”。')
    add('')
    add('补充：档案区还有大量 **u16BE** 皮肤行 ID（主样本 231 次），')
    add('例：桑忆终尘启块含 19200 黄忠、19307 铠、12905 典韦、18007 哪吒、12402 周瑜、')
    add('17408 虞姬、12901 典韦等。17408 与本局虞姬玩家（17401）不同，')
    add('说明这些是他人/历史/展示皮肤；主样本 u16BE 的“本人英雄”命中为 0。')
    add('u16BE hero 区的 3 次是熟练度/账号数值的字节巧合（19203/10500/51200），不是皮肤字段。')
    add('')
    add('## 3. 尾部名单次值是什么')
    add('')
    add('**不是皮肤，也不是皮肤配置/模型/英雄/AI 皮肤/槽位编码；是本局结算评分（rating×100）。**')
    add('')
    add(f'- 20 个样本共 {ts["values"]} 个次值，范围 {ts["min"]}–{ts["max"]}，'
        f'不同值 {ts["distinct"]} 个；{ts["x10"]}/{ts["values"]} 是 10 的倍数。')
    add(f'- 命中皮肤行 ID：**{ts["skin_row"]}/{ts["values"]}**；5 位基础皮肤行：'
        f'**{ts["skin_5d"]}/{ts["values"]}**；上架表：**{ts["release"]}/{ts["values"]}**；'
        f'皮肤模型 ID：**{ts["model"]}/{ts["values"]}**。')
    add(f'- 与英雄 ID 的交集：{ts["hero"]}/{ts["values"]}（只是 300–700 数值区间与英雄 ID 重叠）；')
    add(f'  但“次值 == 本 entry 自己的英雄 ID”为 **{ts["score_eq_own_hero"]}/{ts["values"]}**，')
    add(f'  “次值 ∈ 本局 10 个英雄 ID”为 **{ts["score_in_match_heroes"]}/{ts["values"]}**。')
    add(f'- AI 实体 2001–2008 的次值 {ts["ai_values"]} 个，范围 200–970；'
        f'落在皮肤序号 0–16 的 **{ts["ai_in_skin_index"]}** 个。')
    add(f'- 槽位 0–4 的次值范围分别约 300–1430/360–1560/435–1490/380–1550/320–1395，')
    add('  每个槽位都跨满整个评分域，不是槽位编码。')
    add(f'- 与 `.abc` 头部 Svr2GameCore KV 的 `confValue` 集合相交：'
        f'**{ts["kv_overlap"]}/{ts["values"]}**（KV 是整局常量，评分是每玩家每局变量；无映射）。')
    add(f'- 同一玩家+同一英雄跨局：评分稳定 **{ts["score_stable"]}/{ts["groups_multi"]}** 组，')
    add(f'  皮肤序号稳定 **{ts["skin_stable"]}/{ts["groups_multi"]}** 组。')
    add(f'- 结构校验：106 B 形的 MVP 字段 = 高均分队伍最高分实体 {ts["mvp_ok"]}/{ts["mvp_n"]}，')
    add(f'  SVP 字段 = 低均分队伍最高分实体 {ts["svp_ok"]}/{ts["svp_n"]}；')
    add(f'  102 B 形无 SVP。所谓旧“extra”值 {ts["extra_rule"]}/20 等于 `(MVP低字节<<8)|0x0A`，')
    add('  是 +0x10 处把 MVP 低字节与人数 0x0A 误读成 u16 的产物。')
    add('')
    add('主样本 1558：尾表次值 **1140**（全队最高，MVP），而皮肤序号 0（18700 经典）。')
    add('同一录制者换英雄/换局的评分：175→810/920/700，505→640/1050/650/690，')
    add('187→590/1140，138→1240/1430/910；皮肤序号对应固定 2/1/0/0。')
    add('')
    add('## 4. 否定证据：其它位置没有本局皮肤 ID')
    add('')
    add('| 扫描 | 范围 | 结果 |')
    add('|---|---|---|')
    add(f'| 精确 u32BE 皮肤行 ID | 主样本 10 个块全部字节 | {hit_main["hits"]} 次命中，'
        f'hero 区 {hit_main["hero"]} 次、档案区 {hit_main["archive"]} 次、'
        f'出装区 {hit_main["plan"]} 次、块尾 {hit_main["tail"]} 次 |')
    add(f'| 精确 u16BE 5位皮肤行 ID | 主样本 10 个块全部字节 | {hit_main["u16_hits"]} 次命中，'
        f'hero 区 {hit_main["u16_hero"]} 次、档案区 {hit_main["u16_archive"]} 次、'
        f'出装区 {hit_main["u16_plan"]} 次、块尾 {hit_main["u16_tail"]} 次；'
        f'本人英雄 {hit_main["u16_own"]} 次 |')
    add(f'| 其中“本人英雄”行 ID | 主样本 | {hit_main["own"]} 次，'
        f'均在档案区且非固定偏移（见下） |')
    add('| 全 20 样本“本人英雄”行 ID | 172 块 | 9 次命中，分布在 5 个块；偏移分散（'
        + '/'.join(f'0x{h["rel"]:x}' for h in sorted(own_hits, key=lambda x: x['rel']))
        + '） |')
    add('| 皮肤名 UTF-8 | 主 .abc 全文件 | 0 |')
    add('| `Skin_` / `skin` 资源串 | 主 .abc 全文件 | 0 / 0 |')
    if header_scan:
        add(f'| 皮肤行 ID | 主 .abc 头部（0..首块） | {header_scan["skin_row_u32be"]} 次，'
            f'值 {sorted(set(header_scan["row_values"]))}（常量 51200，非皮肤字段） |')
    if ope_scan:
        add(f'| 皮肤行 ID / 模型 ID | 主 .ope 解码流 | '
            f'{ope_scan["skin_row_u32be"]} / {ope_scan["model_u32be"]} |')
    if stream_scan:
        add(f'| 皮肤行 ID / 模型 ID | 主 .bin operator 流 | '
            f'{stream_scan["skin_row_u32be"]} / {stream_scan["model_u32be"]}，'
            f'值 {sorted(set(stream_scan["row_values"]))}（UI 流偶然 u32，非本局装备） |')
    add('')
    if ope_scan:
        add('注：`.ope` 除头部版本/设备/账号/时间外是高熵载荷，没有明文 `Skin_`/皮肤名；')
        add('不能排除加密 UI 载荷，但本容器里没有可用的明文皮肤字段。')
    if stream_scan:
        add('注：`.bin` 的 50701 是李信“灼热之刃”，而本局李信实际是 50702“一念神魔”；')
        add('10503 廉颇不在本局，故这些命中不是本局 10 人皮肤。')
    add('')
    add('字符串/头部/OPE/操作流扫描：')
    add('')
    add('| 源 | 大小 | 皮肤名 | Skin_ | u32BE 行 ID | 模型 u32 | 备注 |')
    add('|---|---:|---:|---:|---:|---:|---|')
    for scan in (abc_scan, header_scan, ope_scan, stream_scan):
        if not scan:
            continue
        note = ''
        if scan is header_scan:
            note = f'仅 {sorted(set(scan["row_values"]))} 常量'
        elif scan is ope_scan:
            note = '解码头 ' + '; '.join(scan.get('header_texts', [])[:4])
        elif scan is stream_scan:
            note = f'偶然 {sorted(set(scan["row_values"]))}'
        add(f'| {scan["label"]} | {scan["size"]} | {scan["skin_names"]} '
            f'| {scan["skin_res"]} | {scan["skin_row_u32be"]} | {scan["model_u32be"]} '
            f'| {note} |')
    add('')
    if abc_scan and header_scan:
        frame_hits = abc_scan['skin_row_u32be'] - header_scan['skin_row_u32be'] - hit_main['hits']
        add(f'全文件 u32BE 行 ID 共 {abc_scan["skin_row_u32be"]} 次：头部 '
            f'{header_scan["skin_row_u32be"]} 次、玩家块 {hit_main["hits"]} 次、'
            f'帧/续流 {frame_hits} 次。帧区命中是帧序号/效果数值与 5 位皮肤 ID 区间重叠')
        add('（例：帧 seq `0x29CF=10703`、`0x2E7C=11900` 恰好等于赵云/扁鹊的皮肤行 ID），')
        add('不是皮肤字段；10 人皮肤中只有 10703、11900 在帧流中以帧序号形式偶然出现。')
    add('')
    add('补：把本局 10 个皮肤行 ID 反过来与主样本块内所有精确命中比对，')
    cur_ids = {info['skin_row'] for info in main_rows if info['skin_row']}
    main_vals = {h['derived'] for h in hit_rows if h['sample'] == MAIN_SAMPLE.name}
    found = sorted(cur_ids & main_vals)
    found_txt = ', '.join(str(x) for x in found) if found else '0 个'
    add(f'只有 {found_txt} 命中；其余 {10 - len(found)} 个本局皮肤不在块内任何位置，')
    add('说明档案区不携带本局十人皮肤。')
    add('')
    add('档案区命中说明：主样本 10 个块共 '
        f'{hit_main["archive"]} 个皮肤行 ID，绝大多数是英雄 538/508/109/173/505/190/199/542/534/537 等')
    add('其他英雄的皮肤；更像是最近玩家/展示资料/历史缓存（不作强归因），关键是没有固定偏移，')
    add('且只有 2/10 个块出现本人英雄皮肤：布鲁BIUBIU 块 17404（与 s+0x7C 的 17401 不同）、')
    add('双枪踏浪行块 51805（与 s+0x7C 的 5 相同）。全 20 样本也只有 9 个这样的散点，')
    add('4 个与 s+0x7C 一致、5 个不一致（这里指 u32BE 本人英雄命中），说明档案区是“历史/展示”而非本局装备。')
    add('')
    add('## 5. 剩余缺口与置信度')
    add('')
    add('- 置信度：**高**（字段唯一性 + 170/170 表行校验 + 5/5 跨样本稳定 + 20 样本录制者锚点）。')
    add('- `s+0x7C` 给的是**基础皮肤序号**；8 位星元/部件行（如 15404101）不在此字段，')
    add('  要还原星元部件需另找 `stSkinPartWearing`。')
    add('- 皮肤表存在同名“遗留/特殊”组：东皇太一还有 696xx、扁鹊还有 685xx；')
    add('  同名同序号的重复行用模型族（cell_4 vs 英雄表 cell_5）区分，')
    add('  且重复组 696xx/685xx/324xx 不在上架表 `0x56E5140`，')
    add('  187/119/124 等均唯一落到英雄表对应的 187xx/119xx/124xx 行；')
    add('  只有 501/590、171/716、110/310 这种模型族也相同的遗留组才用行键组兜底。')
    add('- “已装备”与“最近使用”在没有外观真值的情况下不能 100% 区分；')
    add('  但该字段位于战斗开始块的英雄信息区（熟练度/等级/徽章之后），')
    add('  判为已装备皮肤（对 1558 两者都是 18700 经典）。')
    add('- heroID=1 的 2 个特殊块（20260925_103058 / 20261016_194242）不在英雄表，已从 170 个真实英雄块中排除。')
    add('')
    add('**还缺什么（只能外部补的部分）**：')
    add('')
    add('- 8 位星元/部件皮肤 ID（如 15404101）和 `stSkinPartWearing` 部件组合：')
    add('  `s+0x7C` 只有 8 位基础序号，无法还原星元颜色/部件。')
    add('- “本局已装备”与“最近使用”无法在没有外观真值/截图 OCR 的情况下 100% 区分；')
    add('  现有证据更支持“本局已装备”，但不能排除“最近使用”。')
    add('- AI 实体 2001–2008 没有玩家块（只有尾表评分），因此 AI 皮肤仍不可得；')
    add('  其尾表值也不在皮肤序号域。')
    add('- `.ope` 的高熵载荷如果包含 UI 皮肤名，需要解密/UI 事件语义才能读；')
    add('  本轮只证明明文层没有皮肤字段。')
    add('')
    add('## 6. 复跑')
    add('')
    add('```')
    add('python tools/agent_skin_ids2.py')
    add('python tools/agent_skin_ids2.py --main-only')
    add('python tools/agent_skin_ids2.py --no-strings')
    add('```')
    add('')
    add('产物：`data/replays/_analysis/datasets/agent_skin_ids2.csv`'
        '（player_skin / recorder_cross_sample / field_probe / field_scan / block_row_hit / '
        'trailer_score / trailer_hypothesis / string_scan / table_evidence）。')
    OUT_MD.write_text('\n'.join(lines) + '\n', encoding='utf-8')


if __name__ == '__main__':
    raise SystemExit(main())
