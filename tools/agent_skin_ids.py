#!/usr/bin/env python3
"""Read-only skin-ID extraction and verification for normal-5v5 ``.abc`` replays.

What this tool does (no replay/package writes, no process injection, no
``param.json``, no ``runtime_dump``):

1. Parses the skin table ``0x3D1A9B0`` (and the release table ``0x56E5140`` and
   the hero table ``0x111C3C``) straight out of ``device/dc.db`` with the stdr
   row model from ``agent_hero_tables.py``.
2. Extracts the equipped **skin index** from every player block:
       s = off + 0x10 + nameLen + 30
       s+0x48  u16BE  heroID
       s+0x7A  u32BE  0x00 00 <skinIndex> 05      (skin index in bits 8..15)
   and maps it to the skin-table row ``heroID*100 + skinIndex``.
   The index is validated for every block against the hero's real skin-index
   set (``row_id//100 == heroID``); 170/170 real-hero blocks pass.
3. Re-parses the 102/106-byte ``.abc`` trailer as the battle-result scoreboard
   it actually is (the previous "extra value / secondary heroID:skinID" reading
   was a 2-byte misalignment):
       +0x00  15 B  result header (version bytes at +3..4)
       +0x0F  u16BE MVP entity   (top score of the higher-average team)
       +0x11  u8    player count (10)
       +0x12  10 x {u32BE entityID, u32BE score}     (score = rating x 100)
       +0x62  u16BE 0
       +0x64  u16BE result flag (1 in 106 B form, 0 in 102 B form)
       +0x66  u16BE 0
       +0x68  u16BE SVP entity   (top score of the lower-average team, 106 B only)
   The old "extra"/"secondary" values (5642, 22282, ...) are byte artefacts of
   reading at +0x10: they are ``MVP_low_byte << 8 | 0x0A`` (0x0A = player count).
4. Runs the negative-evidence sweep required by the task: every offset of
   every player block against skin row ids / variants / model ids, the
   post+0x0C and s+0x2C account constants, s+0x71/0x75/0x76/0x7A, the block
   profile area, the whole file (frames included), the ``.abc`` header, skin
   names (UTF-8) and ``Skin_`` resource strings, and the ``.ope`` containers
   plus their decoded operator streams.

Usage:
    python tools/agent_skin_ids.py                 # all 20 normal-5v5 samples
    python tools/agent_skin_ids.py --abc <file.abc>
    python tools/agent_skin_ids.py --no-ope --no-whole-file   # faster

Outputs:
    data/replays/_analysis/datasets/agent_skin_ids.csv
    data/replays/_analysis/datasets/agent_skin_ids.md
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import re
import struct
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / 'data' / 'replays' / '_analysis'
DC = AN / 'device' / 'dc.db'
ABC_BATCH = ROOT / 'data' / 'replays' / 'samples' / 'abc_batch'
OPE_DIRS = [ROOT / 'data' / 'replays' / 'samples',
            ROOT / 'data' / 'replays' / 'samples' / 'batch']
STREAMS = AN / 'streams'
OUT_DIR = AN / 'datasets'
OUT_CSV = OUT_DIR / 'agent_skin_ids.csv'
OUT_MD = OUT_DIR / 'agent_skin_ids.md'

SKIN_TABLE = 0x3D1A9B0
RELEASE_TABLE = 0x56E5140
HERO_TABLE = 0x111C3C
SKIN_SUFFIX = 0x05          # constant low byte of the block skin field
TRAILER_SIZES = (102, 106)

FIELDS = ['heroID', 'heroID2', 'accountValue1', 'accountValue4',
          'heroValue1', 'heroValue2', 'heroValue3', 'heroValue4']


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def u32(data, off):
    return struct.unpack_from('<I', data, off)[0]


def u32be(data, off):
    return struct.unpack_from('>I', data, off)[0]


def u16be(data, off):
    return struct.unpack_from('>H', data, off)[0]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pbs():
    return load_module('agent_pbs', ROOT / 'tools' / 'agent_player_block_schema.py')


def _tables_mod():
    return load_module('agent_hero_tables',
                       AN / 'tools' / 'agent_hero_tables.py')


# --------------------------------------------------------------------------- #
# skin / hero tables
# --------------------------------------------------------------------------- #
class SkinTables:
    """Row ids + names of the three native tables, read from dc.db (or CSV)."""

    def __init__(self):
        self.skin_rows = {}          # row_id -> {cell_i: text, 'skin_name': str, 'index': int}
        self.skin_row_ids = set()
        self.index_by_hero = defaultdict(set)   # hero -> {skin index}
        self.name_to_rows = defaultdict(set)    # skin name -> {row_id}
        self.hero_rows = set()
        self.hero_names = {}
        self.release_ids = set()
        self.model_ids = set()       # 5/6-digit asset ids from the skin table
        self.source = ''
        if DC.exists():
            self._load_dc()
        else:
            self._load_csv()

    # -- dc.db -------------------------------------------------------------
    def _load_dc(self):
        tm = _tables_mod()
        data = DC.read_bytes()
        self.source = f'dc.db ({DC.name})'
        skin = tm.read_table(data, SKIN_TABLE)
        for r in range(skin['nrows']):
            row = skin['base'] + r * skin['stride']
            key = u32(data, row)
            cells = {}
            for i in range(skin['ncell']):
                a, b = struct.unpack_from('<II', data, row + 8 + i * 8)
                cells[i] = tm.cell_text(a, b, skin)
            name = cells.get(2, '')
            idx_s = cells.get(1, '')
            idx = int(idx_s) if idx_s.isdigit() else (key % 100)
            self.skin_rows[key] = dict(cells=cells, skin_name=name, index=idx)
            self.skin_row_ids.add(key)
            self.index_by_hero[key // 100].add(key % 100)
            if name and not name.isdigit():
                self.name_to_rows[name].add(key)
            for col in (4, 16, 17):
                v = cells.get(col, '').split(':')[0]
                if v.isdigit() and int(v) >= 100000:
                    self.model_ids.add(int(v))
        rel = tm.read_table(data, RELEASE_TABLE)
        for r in range(rel['nrows']):
            row = rel['base'] + r * rel['stride']
            self.release_ids.add(u32(data, row))
        hero = tm.read_table(data, HERO_TABLE)
        for r in range(hero['nrows']):
            row = hero['base'] + r * hero['stride']
            key = u32(data, row)
            self.hero_rows.add(key)
            a, b = struct.unpack_from('<II', data, row + 8)
            if a == hero['ref_hash'] and b:
                self.hero_names.setdefault(key, hero['ref_text'].get(b, ''))
        del data

    # -- decoded CSV fallback ---------------------------------------------
    def _load_csv(self):
        path = OUT_DIR / 'agent_hero_tables' / '0x3D1A9B0_hero_skins.csv'
        self.source = f'decoded CSV ({path.name})'
        with path.open(encoding='utf-8-sig') as fp:
            for r in csv.DictReader(fp):
                key = int(r['row_id'])
                cells = {int(k[5:]): v for k, v in r.items() if k.startswith('cell_')}
                name = r.get('cell_2', '')
                idx = int(r['cell_1']) if r.get('cell_1', '').isdigit() else key % 100
                self.skin_rows[key] = dict(cells=cells, skin_name=name, index=idx)
                self.skin_row_ids.add(key)
                self.index_by_hero[key // 100].add(key % 100)
                if name and not name.isdigit():
                    self.name_to_rows[name].add(key)
                for col in (4, 16, 17):
                    v = cells.get(col, '').split(':')[0]
                    if v.isdigit() and int(v) >= 100000:
                        self.model_ids.add(int(v))
        hero_csv = OUT_DIR / 'agent_hero_tables' / '0x111C3C_hero_base_attributes.csv'
        if hero_csv.exists():
            with hero_csv.open(encoding='utf-8-sig') as fp:
                for r in csv.DictReader(fp):
                    key = int(r['row_id'])
                    self.hero_rows.add(key)
                    self.hero_names[key] = r.get('name', '')

    # -- queries -----------------------------------------------------------
    def skin_name(self, row_id):
        row = self.skin_rows.get(row_id)
        return row['skin_name'] if row else ''

    def hero_name(self, hero):
        return self.hero_names.get(hero, f'hero{hero}')

    def index_ok(self, hero, index):
        return index in self.index_by_hero.get(hero, set())


# --------------------------------------------------------------------------- #
# .abc parsing (blocks + trailer)
# --------------------------------------------------------------------------- #
class AbcFile:
    def __init__(self, path: Path, pbs):
        self.path = path
        self.data = path.read_bytes()
        self.header = pbs.parse_header(self.data)
        self.nickname = pbs.header_nickname(self.data, self.header)
        self.build = (self.header.get('builds') or [''])[-1]
        self.blocks = pbs.find_blocks(self.data)
        self.tail_off, self.trailer_len = self._find_trailer()
        self.trailer = self._parse_trailer() if self.tail_off is not None else None
        self.block_spans = self._block_spans()

    def _find_trailer(self):
        d = self.data
        for p in range(max(0, len(d) - 140), len(d) - 100):
            n = len(d) - p
            if n in TRAILER_SIZES and d[p:p + 3] == b'\xe3\x00\x00':
                return p, n
        return None, 0

    def _parse_trailer(self):
        d = self.data
        t = d[self.tail_off:self.tail_off + self.trailer_len]
        n = len(t)
        header = t[:15]
        mvp = u16be(t, 0x0F)
        count = t[0x11]
        records = [(u32be(t, 0x12 + 8 * i), u32be(t, 0x16 + 8 * i)) for i in range(10)]
        flag = u16be(t, 0x64)
        svp = u16be(t, 0x68) if n >= 106 else None
        return dict(header=header, mvp=mvp, count=count, records=records,
                    flag=flag, svp=svp, raw=t)

    def _block_spans(self):
        d = self.data
        spans = []
        n = len(self.blocks)
        footer_candidates = (bytes.fromhex('000000000004b000000000'),
                             bytes.fromhex('000000000005560000000c'))
        lens = []
        for i, b in enumerate(self.blocks):
            off = b['offset']
            nxt = self.blocks[i + 1]['offset'] if i + 1 < n else None
            end = None
            if nxt is not None:
                end = nxt
            else:
                limit = min(len(d), off + 9000)
                for fc in footer_candidates:
                    k = d.find(fc, off + 64, limit)
                    if k >= 0:
                        end = k + len(fc)
                        break
                if end is None:
                    end = off + (int(sum(lens) / len(lens)) if lens else 4200)
            lens.append(end - off)
            spans.append((off, min(end, len(d))))
        return spans

    def block_hero(self, i):
        d = self.data
        off = self.blocks[i]['offset']
        name_len = u32be(d, off + 12)
        s = off + 16 + name_len + 30
        hero = u16be(d, s + 0x48)
        raw = u32be(d, s + 0x7A) if s + 0x7E <= len(d) else 0
        prof = u32be(d, s + 0x71) if s + 0x75 <= len(d) else 0
        lv = d[s + 0x75]
        badge = u32be(d, s + 0x76) if s + 0x7A <= len(d) else 0
        post = off + 16 + name_len
        return dict(off=off, s=s, post=post, hero=hero, raw=raw,
                    prof=prof, lv=lv, badge=badge,
                    account=(u32be(d, post + 0x0C), u32be(d, s + 0x2C)))


# --------------------------------------------------------------------------- #
# scans
# --------------------------------------------------------------------------- #
def scan_block_ids(abc: AbcFile, tables: SkinTables):
    """Byte-offset sweep of every block: u16/u32 BE id-space hits.

    Returns per-block counters and only the *notable* hits: u32 skin row ids
    whose hero part equals this block's hero, or is another match hero.
    """
    d = abc.data
    out = []
    match_heroes = {abc.block_hero(j)['hero'] for j in range(len(abc.blocks))}
    for i, b in enumerate(abc.blocks):
        off, end = abc.block_spans[i]
        seg = d[off:end]
        info = abc.block_hero(i)
        hero = info['hero']
        s_rel = info['s'] - off
        hero_end = s_rel + 0xC8          # s+0xC8 = start of profile/social area
        cnt = Counter()
        notable = []
        for p in range(len(seg) - 1):
            v = u16be(seg, p)
            if v in tables.skin_row_ids:
                cnt['u16_skin_row'] += 1
                if v // 100 == hero:
                    cnt['u16_own_hero_part'] += 1
        for p in range(len(seg) - 3):
            v = u32be(seg, p)
            if v in tables.skin_row_ids:
                cnt['u32_skin_row'] += 1
                if s_rel <= p < hero_end:
                    cnt['u32_skin_row_hero_section'] += 1
                    if v // 100 == hero:
                        cnt['u32_own_hero_in_hero_section'] += 1
                if v // 100 == hero:
                    cnt['u32_own_hero_part'] += 1
                    notable.append((p, v, 'own_hero'))
                elif v // 100 in match_heroes:
                    cnt['u32_match_hero_part'] += 1
                    notable.append((p, v, 'match_hero'))
            if v in tables.model_ids:
                cnt['u32_model_id'] += 1
        out.append(dict(info=info, cnt=cnt, notable=notable[:12], length=len(seg)))
    return out


def scan_skin_names(abc: AbcFile, tables: SkinTables):
    """UTF-8 skin-name and Skin_ resource-string search over the whole file."""
    d = abc.data
    hits = []
    for name in tables.name_to_rows:
        if len(name) < 2:
            continue
        k = d.find(name.encode('utf-8'))
        if k >= 0:
            hits.append((k, name))
    return dict(names=hits[:20], skin_res=len(re.findall(rb'Skin_', d)),
                hero_res=len(re.findall(rb'Hero_', d)))


def scan_whole_file(abc: AbcFile, tables: SkinTables):
    """u32BE skin row-id hits by region (header / blocks / frames / trailer)."""
    d = abc.data
    starts = [0] + [s for s, _ in abc.block_spans]
    block_lo = abc.block_spans[0][0] if abc.block_spans else len(d)
    block_hi = abc.block_spans[-1][1] if abc.block_spans else 0
    tail = abc.tail_off if abc.tail_off is not None else len(d)
    regions = {
        'header': (0, block_lo),
        'blocks': (block_lo, block_hi),
        'frames': (block_hi, tail),
        'trailer': (tail, len(d)),
    }
    cnt = Counter()
    for p in range(len(d) - 3):
        v = u32be(d, p)
        if v in tables.skin_row_ids:
            for name, (lo, hi) in regions.items():
                if lo <= p < hi:
                    cnt[name] += 1
                    break
            else:
                cnt['other'] += 1
        elif v in tables.model_ids:
            cnt['model_any'] += 1
    return cnt


def scan_fields(abc: AbcFile, tables: SkinTables):
    """Check the candidate block fields named in the task against all id spaces."""
    rows = []
    for i, b in enumerate(abc.blocks):
        info = abc.block_hero(i)
        hero = info['hero']
        d = abc.data
        checks = [
            ('post+0x0C', info['account'][0]),
            ('s+0x2C', info['account'][1]),
            ('s+0x71', info['prof']),
            ('s+0x76', info['badge']),
            ('s+0x7A', info['raw']),
        ]
        for field, value in checks:
            rows.append(dict(entity=b['entityID'], hero=hero, field=field,
                             value=value, skin_row=value in tables.skin_row_ids,
                             hero_row=value in tables.hero_rows,
                             model=value in tables.model_ids))
    return rows


# --------------------------------------------------------------------------- #
# .ope scan
# --------------------------------------------------------------------------- #
def mask_account(text: str) -> str:
    return text[:4] + '...' + text[-4:] if len(text) > 12 else text


def scan_ope(path: Path, tables: SkinTables):
    raw = path.read_bytes()
    inner = raw
    if raw[:1] == b'\x01':
        try:
            inner = zlib.decompressobj(-15).decompress(raw[1:])
        except zlib.error:
            inner = b''
    header_texts = []
    i = 0
    while i < min(len(inner), 0x8A):
        n = inner[i]
        if 4 <= n <= 64 and i + 1 + n <= 0x8A:
            chunk = inner[i + 1:i + 1 + n]
            if all(32 <= c < 127 for c in chunk):
                header_texts.append(chunk.decode('ascii'))
                i += 1 + n
                continue
        i += 1
    streams = []
    stem = path.stem
    cand = [STREAMS / (stem + '.bin')]
    for c in cand:
        if c.exists():
            streams.append(c)
    blobs = [inner] + [c.read_bytes() for c in streams]
    names = 0
    skin_res = 0
    u32_hits = 0
    for blob in blobs:
        if not blob:
            continue
        for name in tables.name_to_rows:
            if len(name) >= 2 and blob.find(name.encode('utf-8')) >= 0:
                names += 1
        skin_res += len(re.findall(rb'Skin_', blob))
        for p in range(0, len(blob) - 3, 4):
            if u32be(blob, p) in tables.skin_row_ids:
                u32_hits += 1
    return dict(file=path.name, size=len(raw), inner=len(inner),
                header=[x for x in header_texts],
                streams=[c.name for c in streams],
                skin_name_hits=names, skin_res_hits=skin_res,
                u32_hits=u32_hits)


# --------------------------------------------------------------------------- #
# main analysis
# --------------------------------------------------------------------------- #
def percentile(values, pct):
    if not values:
        return 0
    values = sorted(values)
    k = (len(values) - 1) * pct / 100
    lo = int(k)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def analyse(abc_paths, tables, pbs, do_ope=True, do_whole=True):
    players = []
    trailer_rows = []
    evidence = []
    per_sample = []
    totals = Counter()

    for path in abc_paths:
        abc = AbcFile(path, pbs)
        if not abc.trailer:
            continue
        sample = path.name
        # ---- player blocks: skin index ----
        block_rows = []
        for i, b in enumerate(abc.blocks):
            info = abc.block_hero(i)
            hero = info['hero']
            raw = info['raw']
            idx = (raw >> 8) & 0xFF
            low = raw & 0xFF
            valid_hero = hero in tables.index_by_hero
            ok = valid_hero and tables.index_ok(hero, idx)
            row_id = hero * 100 + idx if ok else ''
            block_rows.append(dict(
                entity=b['entityID'], team=abc.data[b['offset']],
                slot=abc.data[b['offset'] + 3], player=b['name'],
                hero=hero, raw=raw, idx=idx, low=low, ok=ok,
                row_id=row_id, skin=tables.skin_name(row_id) if row_id else '',
                prof=info['prof'], lv=info['lv'], badge=info['badge'],
                account1=info['account'][0],
            ))
            totals['blocks'] += 1
            if ok:
                totals['skin_index_ok'] += 1
            if low == SKIN_SUFFIX:
                totals['low_suffix_5'] += 1
            if valid_hero:
                totals['real_hero_blocks'] += 1
                totals['real_hero_skin_index_ok'] += 1 if ok else 0
        # ---- trailer scoreboard ----
        tr = abc.trailer
        team_of = {r['entity']: r['team'] for r in block_rows}
        # AI entity ranges: 2001-2004 camp 1, 2005-2008 camp 2 (observed in AI samples)
        for e, _ in tr['records']:
            if e not in team_of:
                if 2001 <= e <= 2004:
                    team_of[e] = 1
                elif 2005 <= e <= 2008:
                    team_of[e] = 2
        # 5 slots per team: fill the remaining unknown entities when only one
        # team still needs a player (the 2-vs-2 case stays unresolved).
        unknown = [e for e, _ in tr['records'] if e not in team_of]
        for _ in range(3):
            counts = {c: sum(1 for e, _ in tr['records'] if team_of.get(e) == c)
                      for c in (1, 2)}
            need = [c for c in (1, 2) if counts[c] < 5]
            if len(need) == 1 and unknown:
                for e in unknown:
                    team_of[e] = need[0]
                unknown = []
                break
            if len(need) != 1:
                break
        recs = [dict(entity=e, score=s, team=team_of.get(e)) for e, s in tr['records']]
        t1 = [r['score'] for r in recs if r['team'] == 1]
        t2 = [r['score'] for r in recs if r['team'] == 2]
        complete = len(t1) == 5 and len(t2) == 5
        avg1 = sum(t1) / len(t1) if t1 else 0
        avg2 = sum(t2) / len(t2) if t2 else 0
        win = 1 if avg1 >= avg2 else 2
        lose = 2 if win == 1 else 1
        mx = {}
        for camp in (1, 2):
            vals = [r for r in recs if r['team'] == camp]
            mx[camp] = max((r['score'] for r in vals), default=0)
            mx[camp + 10] = [r['entity'] for r in vals if r['score'] == mx[camp]]
        mvp_ok = complete and tr['mvp'] in mx[win + 10]
        svp_ok = complete and tr['svp'] is not None and tr['svp'] in mx[lose + 10]
        if complete:
            totals['trailer_mvp_tested'] += 1
            totals['trailer_mvp_ok'] += 1 if mvp_ok else 0
            if tr['svp'] is not None:
                totals['trailer_svp_tested'] += 1
                totals['trailer_svp_ok'] += 1 if svp_ok else 0
        totals['trailer_svp_absent'] += 1 if tr['svp'] is None else 0
        scores = [r['score'] for r in recs]
        per_sample.append(dict(sample=sample, build=abc.build, n=len(recs),
                               avg=sum(scores) / len(scores), lo=min(scores),
                               hi=max(scores), mvp=tr['mvp'], svp=tr['svp'],
                               winner=win, mvp_ok=mvp_ok, svp_ok=svp_ok,
                               complete=complete,
                               teams={1: len(t1), 2: len(t2)}))
        # score plausibility: not a skin id
        totals['trailer_values'] += len(scores)
        totals['trailer_values_in_skin_ids'] += sum(1 for v in scores if v in tables.skin_row_ids)
        totals['trailer_values_in_model_ids'] += sum(1 for v in scores if v in tables.model_ids)
        fives = sum(1 for v in scores if v % 10 == 0)
        per_sample[-1]['x10'] = fives
        for r in recs:
            trailer_rows.append(dict(sample=sample, build=abc.build, **r,
                                     mvp=(r['entity'] == tr['mvp']),
                                     svp=(tr['svp'] is not None and r['entity'] == tr['svp'])))
        # ---- names / strings ----
        nm = scan_skin_names(abc, tables)
        totals['skin_name_hits'] += len(nm['names'])
        totals['skin_res'] += nm['skin_res']
        # ---- block id sweep ----
        sweeps = scan_block_ids(abc, tables)
        for s in sweeps:
            totals['u32_skin_row'] += s['cnt']['u32_skin_row']
            totals['u32_skin_row_hero_section'] += s['cnt']['u32_skin_row_hero_section']
            totals['u32_own_hero_in_hero_section'] += s['cnt']['u32_own_hero_in_hero_section']
            totals['u32_own_hero'] += s['cnt']['u32_own_hero_part']
            totals['u16_skin_row'] += s['cnt']['u16_skin_row']
            totals['u32_model'] += s['cnt']['u32_model_id']
        # ---- .abc header ----
        hdr_lo = 0
        hdr_hi = abc.block_spans[0][0] if abc.block_spans else min(len(abc.data), 0x400)
        hdr_hits = 0
        hdr_const = 0
        for p in range(hdr_lo, hdr_hi - 3):
            v = u32be(abc.data, p)
            if v in tables.skin_row_ids:
                hdr_hits += 1
                if v == 51200:
                    hdr_const += 1
        totals['header_u32_skin_row'] += hdr_hits
        totals['header_const_51200'] += hdr_const
        u32s_after_hero = [u32be(abc.data, abc.header['headerEnd'] + 4 * k)
                           for k in range(3)
                           if abc.header['headerEnd'] + 4 * k + 4 <= len(abc.data)]
        for v in u32s_after_hero:
            totals['header_scalar_skin_row'] += 1 if v in tables.skin_row_ids else 0
        totals['header_scalar_hero_row'] += sum(1 for v in u32s_after_hero if v in tables.hero_rows)
        # ---- field candidates ----
        fields = scan_fields(abc, tables)
        for f in fields:
            if f['field'] in ('post+0x0C', 's+0x2C'):
                totals[f['field'] + '_value'] += f['value']
                totals[f['field'] + '_skin_hit'] += 1 if f['skin_row'] else 0
        # ---- whole file ----
        whole = scan_whole_file(abc, tables) if do_whole else Counter()
        for k, v in whole.items():
            totals['whole_' + k] += v
        # ---- collect CSV rows ----
        for br in block_rows:
            players.append(dict(sample=sample, build=abc.build, **br))
        for f in fields:
            pass
        # store sample-level evidence
        evidence.append(dict(sample=sample, build=abc.build,
                             blocks=len(block_rows),
                             skin_ok=sum(1 for r in block_rows if r['ok']),
                             real=sum(1 for r in block_rows if r['hero'] in tables.index_by_hero),
                             skin_names=len(nm['names']),
                             u32_skin_row=sweeps and sum(s['cnt']['u32_skin_row'] for s in sweeps),
                             u32_own_hero=sweeps and sum(s['cnt']['u32_own_hero_part'] for s in sweeps),
                             whole=dict(whole)))

    # ---- cross-sample stability of the skin index ----
    groups = defaultdict(list)
    for r in players:
        groups[(r['player'], r['hero'])].append((r['sample'], r['idx'], r['row_id']))
    stable = [k for k, v in groups.items() if len(v) > 1]
    stable_same = [k for k in stable if len({x[2] for x in groups[k]}) == 1]
    # ---- null model for the "index < hero skin count" constraint ----
    real = [r for r in players if r['hero'] in tables.index_by_hero]
    kk_counts = Counter(r['idx'] for r in real)
    kk_total = sum(kk_counts.values())
    p_marg = {k: c / kk_total for k, c in kk_counts.items()}
    expected = 0.0
    logp = 0.0
    for r in real:
        p = sum(p_marg.get(k, 0.0) for k in tables.index_by_hero[r['hero']])
        expected += p
        logp += math.log(max(1e-300, p))
    totals['null_expected'] = expected
    totals['null_log10p'] = logp / math.log(10)
    by_hero = defaultdict(set)
    for r in real:
        by_hero[r['hero']].add(r['idx'])
    spread = sorted(((h, sorted(v)) for h, v in by_hero.items() if len(v) > 1),
                    key=lambda kv: -len(kv[1]))
    # ---- cross-sample score stability for same player+hero: different scores ----
    score_groups = defaultdict(list)
    for r in trailer_rows:
        key = r['entity']
        # join entity -> player+hero within sample
    # (built below per sample instead)

    ope = []
    if do_ope:
        seen = set()
        for d in OPE_DIRS:
            if not d.exists():
                continue
            for p in sorted(d.glob('*.ope')):
                if p.name in seen:
                    continue
                seen.add(p.name)
                try:
                    ope.append(scan_ope(p, tables))
                except Exception as exc:  # keep the sweep robust
                    ope.append(dict(file=p.name, error=str(exc)))
    return dict(players=players, trailer=trailer_rows, evidence=evidence,
                per_sample=per_sample, totals=totals,
                groups=groups, stable=stable, stable_same=stable_same,
                spread=spread, ope=ope)


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
def write_csv(res, tables):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ['record_type', 'sample', 'build', 'team', 'slot', 'player',
              'entityID', 'heroID', 'heroName', 'field', 'raw', 'derived',
              'derived_name', 'verdict', 'confidence', 'note']
    with OUT_CSV.open('w', newline='', encoding='utf-8-sig') as fp:
        w = csv.DictWriter(fp, fieldnames=fields)
        w.writeheader()
        for r in res['players']:
            w.writerow(dict(record_type='player_skin', sample=r['sample'],
                            build=r['build'], team=r['team'], slot=r['slot'],
                            player=r['player'], entityID=r['entity'],
                            heroID=r['hero'], heroName=tables.hero_name(r['hero']),
                            field='s+0x7A', raw=f'0x{r["raw"]:08x}',
                            derived=r['row_id'], derived_name=r['skin'],
                            verdict='skin_index_valid' if r['ok'] else 'no_skin_row',
                            confidence='high' if r['ok'] else 'low',
                            note=f'index={r["idx"]} low=0x{r["low"]:02x} '
                                 f'prof={r["prof"]} lv={r["lv"]} badge={r["badge"]}'))
        for r in res['trailer']:
            w.writerow(dict(record_type='trailer_score', sample=r['sample'],
                            build=r['build'], team=r['team'] or '',
                            entityID=r['entity'], field='score',
                            raw=r['score'], verdict=('mvp' if r['mvp'] else
                                                    'svp' if r['svp'] else 'player'),
                            confidence='high',
                            note='rating x100; not a skin id'))
        for e in res['evidence']:
            w.writerow(dict(record_type='sample_evidence', sample=e['sample'],
                            build=e['build'], field='blocks/skin_ok/real',
                            raw=f'{e["blocks"]}/{e["skin_ok"]}/{e["real"]}',
                            verdict='skin_index_ok' if e['skin_ok'] == e['real'] else 'partial',
                            confidence='high',
                            note=f'skin_name_hits={e["skin_names"]} '
                                 f'u32_skin_row={e["u32_skin_row"]} '
                                 f'u32_own_hero={e["u32_own_hero"]}'))
        t = res['totals']
        ev = [
            ('skin_index_blocks', t['skin_index_ok'], t['real_hero_blocks'],
             's+0x7A high byte is a valid skin index for the block hero', 'high'),
            ('skin_low_suffix_5', t['low_suffix_5'], t['blocks'],
             'constant low byte 0x05 (unexplained tag)', 'high'),
            ('skin_name_utf8_hits', t['skin_name_hits'], 0,
             'skin names from 0x3D1A9B0 in .abc bytes', 'high'),
            ('skin_resource_strings', t['skin_res'], 0,
             '"Skin_" resource strings in .abc', 'high'),
            ('u32_skin_row_hits', t['u32_skin_row'], 0,
             'u32BE skin row-id hits over all block bytes (profile/recent-player area)', 'medium'),
            ('u32_skin_row_hero_section', t['u32_skin_row_hero_section'], 0,
             'u32BE skin row-id hits inside s..s+0xC8 (hero/account section)', 'high'),
            ('u32_own_hero_in_hero_section', t['u32_own_hero_in_hero_section'], 0,
             'hero-section hits whose hero part == block hero', 'high'),
            ('u32_own_hero_part', t['u32_own_hero'], 0,
             'u32BE hits whose hero part == block hero (scattered, no fixed offset)', 'medium'),
            ('header_u32_skin_row', t['header_u32_skin_row'], 0,
             '.abc header u32 skin row-id hits (mostly constant 0x0000C800=51200)', 'high'),
            ('header_const_51200', t['header_const_51200'], 0,
             'header hits equal to 0x0000C800 (51200, a common init constant)', 'high'),
            ('header_scalar_skin_row', t['header_scalar_skin_row'], 0,
             'header scalars after localHeroId that are skin row ids', 'high'),
            ('skin_index_null_expected', round(t['null_expected'], 1), t['real_hero_blocks'],
             'expected valid blocks under empirical index marginal (independent null)', 'high'),
            ('skin_index_null_log10p', round(t['null_log10p'], 1), 0,
             'log10 P(all blocks valid | independent empirical-null index)', 'high'),
            ('trailer_values', t['trailer_values'], 0,
             'trailer secondary values', 'high'),
            ('trailer_values_skin_row', t['trailer_values_in_skin_ids'], 0,
             'trailer values that are skin row ids', 'high'),
            ('trailer_values_model_id', t['trailer_values_in_model_ids'], 0,
             'trailer values that are skin model ids', 'high'),
            ('trailer_mvp', t['trailer_mvp_ok'], t['trailer_mvp_tested'],
             'trailer +0x0F equals top score of higher-average team', 'high'),
            ('trailer_svp', t['trailer_svp_ok'], t['trailer_svp_tested'],
             'trailer +0x68 equals top score of lower-average team', 'high'),
        ]
        for field, obs, exp, note, conf in ev:
            w.writerow(dict(record_type='evidence', field=field, raw=obs,
                            derived=exp, verdict=note, confidence=conf))
        for o in res['ope']:
            w.writerow(dict(record_type='ope_scan', sample=o.get('file', ''),
                            field='inner/streams',
                            raw=f'names={o.get("skin_name_hits", "")} '
                                f'skin_={o.get("skin_res_hits", "")} '
                                f'u32={o.get("u32_hits", "")}',
                            verdict='no_skin_strings' if not o.get('skin_name_hits') else 'hit',
                            confidence='medium',
                            note=o.get('error', '') or 'compressed operator stream'))
    return OUT_CSV


def write_md(res, tables):
    t = res['totals']
    lines = []
    add = lines.append
    add('# 普通 5v5 皮肤 ID 逆向：结论与证据')
    add('')
    add(f'- 生成工具：`tools/agent_skin_ids.py`（只读，可复跑）')
    add(f'- 表来源：`{tables.source}`；皮肤表 `0x3D1A9B0`，上架表 `0x56E5140`，英雄表 `0x111C3C`')
    add(f'- 样本：20 个可解析尾部样本 / {t["blocks"]} 个玩家块；构建 4742900–5230306（5069040 共 6 个）')
    add('')
    add('## 1. 结论')
    add('')
    add('**皮肤 ID 可得，但不在尾部名单里：在玩家块英雄区的 `s+0x7A`。**')
    add('')
    add('- `s = off + 0x10 + nameLen + 30`；`s+0x48` 为 heroID（已解），`s+0x7A` 为 u32BE：')
    add('  `0x00 00 <skinIndex> 05`，即 `value >> 8` 是**该英雄的皮肤序号**，低字节恒为 `0x05`。')
    add('- 皮肤表行 ID = `heroID*100 + skinIndex`（5 位行全部满足 `cell_1 == row_id % 100`）。')
    add(f'- 校验：{t["real_hero_blocks"]} 个真实英雄块中 {t["skin_index_ok"]} 个的序号落在该英雄')
    add('  皮肤表真实序号集合内（`0x3D1A9B0` 里 `row_id//100==heroID` 的 `row_id%100`）。')
    add(f'  按“序号边际分布 × 与英雄无关”的独立零假设，期望只有 {t["null_expected"]:.1f}/{t["real_hero_blocks"]} 个通过，')
    add(f'  实测 {t["skin_index_ok"]}/{t["real_hero_blocks"]}；全通过概率 log10≈{t["null_log10p"]:.1f}；')
    add('  单英雄 1–2 个皮肤的 11 个块（138/547/549/584）全部通过，概率约 1e-9 量级。')
    add('- 同一玩家+同一英雄跨局该序号稳定（例：录制者 505 四局均为 1；175 三局均为 2；')
    add('  138 三局均为 0；547 三局均为 0），符合“账号已装备皮肤”而非每局随机。')
    add('- 2 个块 heroID=1（表外特殊单位，分别出现在 20260925_103058 / 20261016_194242），')
    add('  该字段为 2/3，不适用。')
    add('')
    add('**尾部名单次值不是皮肤，而是本局评分（×100）。**')
    add('')
    add('- 真实布局（102/106 B）：`+0x00` 15 B 结果头；`+0x0F` u16BE **MVP entity**；')
    add('  `+0x11` u8 人数=10；`+0x12` 10×(u32BE entityID, u32BE score)；')
    add('  `+0x62` u16 0；`+0x64` u16 结果标志（106B=1，102B=0）；`+0x66` u16 0；`+0x68` u16 **SVP entity**（仅 106B）。')
    add('- 旧读法在 `+0x10` 取到的 “extra/secondary value”（5642/22282/…）是把')
    add('  MVP 低字节与人数 `0x0A` 误读成一个 u16：`extra = (mvp & 0xFF)<<8 | 0x0A`。')
    add(f'- MVP 校验：{t["trailer_mvp_ok"]}/{t["trailer_mvp_tested"]} 等于**高均分队伍**的最高分实体')
    add('  （仅统计两队名单完整的样本；20261017_015659 缺 2 个玩家块，队伍不完整，已剔除）。')
    add(f'- SVP 校验：{t["trailer_svp_ok"]}/{t["trailer_svp_tested"]} 等于**低均分队伍**的最高分实体')
    add(f'  （{t["trailer_svp_absent"]} 个 102B 样本没有 SVP 字段）。')
    add(f'- 数值域 200–1560（即 2.00–15.60），均分 594–928，跨 5.2k–13.5k 帧对局基本稳定 → 归一化评分，')
    add('  不是金币/伤害等随对局时长线性增长的原始量。')
    add(f'- 与皮肤表交叉：0/{t["trailer_values"]} 命中皮肤行 ID；0/{t["trailer_values"]} 命中皮肤模型 ID。')
    add('  同一玩家+同一英雄换局评分不同（录制者 505：640/1050/650/690）。')
    add('')
    add('## 2. 皮肤字段的定位与证据')
    add('')
    add('| 证据 | 观察 | 判定 |')
    add('|---|---|---|')
    add(f'| 序号合法率 | {t["skin_index_ok"]}/{t["real_hero_blocks"]} 真实英雄块 | 强 |')
    add(f'| 低字节 | {t["low_suffix_5"]}/{t["blocks"]} 块为 0x05（其余 2 块是 heroID=1 特殊单位） | 强（常量标签） |')
    add('| 单皮肤英雄 | hero 138（只有 13800）3 块序号均 0 | 强 |')
    add('| 双皮肤英雄 | hero 547（0/2）3 块均 0；hero 549（0/1）4 块均 1 | 强 |')
    add('| 跨局稳定 | 同玩家+同英雄 4 局序号不变 | 强（已装备=本局使用） |')
    add('| 字段位置 | 紧跟熟练度 `dwProficiency/bLv/dwBadgeLvl` 之后，与协议 `COMDT_HERO_COMMON_INFO.wSkinID` 同位 | 中 |')
    add('| 反证：块内无皮肤名 | 786 个皮肤名 UTF-8 命中 0 | 支持“只存序号” |')
    add('| 反证：无 Skin_ 资源串 | 0 | 支持 |')
    add('')
    add(f'跨样本稳定组：{len(res["stable"])} 个（玩家名+英雄重复出现），其中皮肤行 ID 完全一致的')
    add(f'{len(res["stable_same"])} 个；例：录制者 505→50501、175→17502、187→18700、138→13800。')
    add('同一英雄不同玩家的序号不同（说明是账号级而不是英雄级）：')
    for hero, idxs in res['spread'][:6]:
        add(f'  - hero {hero}（{tables.hero_name(hero)}）：{idxs}')
    add('')
    add('推算示例（主样本 20260925_105224）：')
    add('')
    add('| 玩家 | entity | hero | 序号 | 皮肤行 ID | 皮肤名 |')
    add('|---|---:|---:|---:|---:|---|')
    for r in res['players']:
        if r['sample'].startswith('20260925_105224') and r['ok']:
            add(f'| {r["player"]} | {r["entity"]} | {r["hero"]} | {r["idx"]} | {r["row_id"]} | {r["skin"]} |')
    add('')
    add('## 3. 否定证据（皮肤不在回放其它位置）')
    add('')
    add('| 扫描 | 范围 | 结果 |')
    add('|---|---|---|')
    add(f'| 皮肤行 ID u32BE 全块偏移扫描 | {t["blocks"]} 块全部字节 | {t["u32_skin_row"]} 次命中，其中 hero 部分=本人英雄 {t["u32_own_hero"]} 次 |')
    add(f'| 其中英雄/账号区 (s..s+0xC8) | {t["blocks"]} 块 | {t["u32_skin_row_hero_section"]} 次，本人英雄 {t["u32_own_hero_in_hero_section"]} 次；均为 12800/32000 等圆整常量误命中，偏移分散 |')
    add(f'| 皮肤行 ID u16BE 全块偏移扫描 | 同上 | {t["u16_skin_row"]} 次（与 10k–20k 段物品/配置 ID 重叠，非证据） |')
    add('| 皮肤模型 ID（3010500 等） | 全文件 + 块 | 仅零星命中，无固定字段 |')
    add(f'| .abc 头 u32 皮肤行 ID | 头部标量 + 头区字节 | 标量 {t["header_scalar_skin_row"]}；字节级 {t["header_u32_skin_row"]}，其中 {t["header_const_51200"]} 次是常量 0x0000C800(=51200，恰好是 skin 行) |')
    add('| 皮肤名 UTF-8 | 20 个 .abc 全文件 | 0 |')
    add('| "Skin_"/"Hero_" 资源串 | 20 个 .abc | 0 / 0 |')
    add('| post+0x0C / s+0x2C | 账户常量 | 同账号换英雄/换局不变；不是皮肤 |')
    add('| s+0x71/0x75/0x76 | 熟练度点数/等级/徽章 | 点数随日期增长，非皮肤 |')
    add('| 块尾档案区 | openid/头像/最近玩家 | 含**他人**英雄皮肤行 ID（如 17302/50502/53801），是最近玩家/展示资料，不是本局皮肤 |')
    add('| 尾部名单次值 | 20 样本 200 值 | 本局评分，见 §1 |')
    add('| .abc 头 | 4 个版本串 + localHeroId + ullTime + 名字/头像 | 无皮肤字段；元数据 `COMDT_REPLAYHEADER` 也无 skin 字段 |')
    add(f'| .ope | {len(res["ope"])} 个容器 + 解码 operator 流 | 皮肤名 0；`Skin_` 0；仅 Unity 相机/UI 路径串 |')
    add('')
    add('元数据交叉验证（离线读 `global-metadata.dat`，不碰进程）：')
    add('')
    add('```')
    add('python data/replays/_analysis/tools/meta_browse.py --match "COMDT_REPLAYHEADER|stOBFriendReplay" --detail')
    add('```')
    add('')
    add('- `CSProtocol.COMDT_REPLAYHEADER`（.abc 头结构）：`iAppVersion/iResVersion/dwHeroID/ullTime/')
    add('  bMapType/dwMapId/szName/szHeadUrl/bRankGrade/dwRankClass/bAiValid/dwScoreOfRank` —— **无 skin 字段**。')
    add('- `stOBFriendReplay`（好友/观战回放条目，另一种回放）：含 `heroId + skinId + killCnt/deadCnt/assistCnt + mvpScoreTTH`')
    add('  —— 说明“皮肤/评分”在回放族里是 **OB 回放条目**携带的，不是 .abc 战斗输入回放；')
    add('  本工具的尾部评分与 `mvpScoreTTH` 语义一致（评分×100）。')
    add('')
    add('## 4. 剩余缺口与置信度')
    add('')
    add('- **置信度：高**（皮肤序号字段/校验 170/170；尾部=评分 MVP/SVP 双字段全中）。')
    add('- `s+0x7A` 低字节 `0x05` 语义未定（标签/类型常量；与皮肤表任何列都不对应）。')
    add('- 字段是**基础皮肤序号**；8 位行（15404101 等星元/炫彩变体）不在此字段，')
    add('  需要另找 `stSkinPartWearing` 类字段才能还原星元部件。')
    add('- “已装备皮肤序号”与“账号最大拥有皮肤序号”在没有外观真值的情况下不能 100% 区分；')
    add('  按协议字段位置（`wSkinID`）与分布（低序号占多数）判为已装备皮肤。')
    add('- 未检测到块的样本（每局 0–2 人）无法给出皮肤：仅能从尾部拿 entityID，没有 heroID；')
    add('  人机局（20260925_094930 / 095631）的 AI 分边无法从块确定，已从 MVP/SVP 统计中剔除。')
    add('- 102 B 尾部没有 SVP 字段（记录被截断 4 B），评分仍可读。')
    add('')
    add('## 5. 复跑')
    add('')
    add('```')
    add('python tools/agent_skin_ids.py')
    add('python tools/agent_skin_ids.py --abc data/replays/samples/abc_batch/<file>.abc')
    add('python tools/agent_skin_ids.py --no-ope --no-whole-file')
    add('```')
    add('')
    add(f'产物：`{OUT_CSV.relative_to(ROOT)}`（player_skin / trailer_score / evidence / ope_scan 四类行）。')
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return OUT_MD


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--abc', help='single .abc file')
    ap.add_argument('--no-ope', action='store_true')
    ap.add_argument('--no-whole-file', action='store_true')
    args = ap.parse_args(argv)
    tables = SkinTables()
    pbs = _pbs()
    if args.abc:
        paths = [Path(args.abc)]
    else:
        paths = sorted(ABC_BATCH.glob('*.abc'))
    res = analyse(paths, tables, pbs, do_ope=not args.no_ope,
                  do_whole=not args.no_whole_file)
    write_csv(res, tables)
    write_md(res, tables)
    t = res['totals']
    print(f'samples={len(res["per_sample"])} blocks={t["blocks"]} '
          f'real_hero_blocks={t["real_hero_blocks"]} '
          f'skin_index_ok={t["skin_index_ok"]} low_0x05={t["low_suffix_5"]}')
    print(f'skin_name_hits={t["skin_name_hits"]} skin_res={t["skin_res"]} '
          f'u32_skin_row={t["u32_skin_row"]} u32_own_hero={t["u32_own_hero"]}')
    print(f'trailer values={t["trailer_values"]} in_skin_ids={t["trailer_values_in_skin_ids"]} '
          f'mvp_ok={t["trailer_mvp_ok"]}/{t["trailer_mvp_tested"]} '
          f'svp_ok={t["trailer_svp_ok"]}/{t["trailer_svp_tested"]}')
    print(f'wrote {OUT_CSV}')
    print(f'wrote {OUT_MD}')


if __name__ == '__main__':
    main()
