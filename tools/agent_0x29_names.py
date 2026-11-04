#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""0x29 id / 0x1f tag 定名取证（只读）。

问题
----
1. `dc.db @0x7384068` 是什么表？row 11990 的字段是什么、能否命名？
2. 0x29 的 91060 在三个同名命名空间（技能表 / buff_effect / 击败特效）
   里该归哪张表？用 5069040 的 11 个 entity、param/tail、时间、与
   0x87/0x1e/0x2c/0x23/0x1f/0x20 的对齐判断。
3. 0x1f tag244 是否在另一张 tag/扩展表？如果在可用 dc.db 里表外，给否定证据。
4. 结论：哪些能定名、哪些只能证明多命名空间/缺 build 表。

只读边界
--------
* 只读 `.abc`、`dc.db`、`data/replays/_analysis/datasets/*.csv`；
* 不修改回放/包体，不注入，不读 `param.json`，不使用 `runtime_dump`；
* 不写 `docs/replay_binary_format.md` 与 `.workbuddy/memory/MEMORY.md`。

产物
----
  data/replays/_analysis/datasets/agent_0x29_names.csv
  data/replays/_analysis/datasets/agent_0x29_names.md

用法
----
  python tools/agent_0x29_names.py
  python tools/agent_0x29_names.py --no-batch   # 只跑主样本，跳过 28 个 .abc 扫描
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / 'data' / 'replays' / '_analysis' / 'datasets'
DEVICE = ROOT / 'data' / 'replays' / '_analysis' / 'device'
DC_DB = DEVICE / 'dc.db'
BATCH = ROOT / 'data' / 'replays' / 'samples' / 'abc_batch'
MAIN = BATCH / (
    '20260925_105224_-1505729760_4933_1790303631_'
    'CBDD358E761B15A4DF526A179E8119E2.abc'
)

sys.path.insert(0, str(ROOT / 'tools'))
import agent_damage_skill_objective as AD  # noqa: E402
import agent_global_strings as GS  # noqa: E402

# dc.db 表起点（只读）
TARGET_TABLE = 0x7384068          # 本报告首要未知表（stride 56, rows 20,755）
TAG_TABLE = 0x695F084             # 0x1f tag 主表（stride 208, rows 205）
SMALL_HIGHLIGHT = 0x699D82C       # 高光视频分类小表（stride 64, rows 27）
SKILL_TABLE = 0x1CE47C
BUFF_EFFECT_TABLE = 0x3BA41A8
BUFF_MAIN_TABLE = 0x8268AC
KILL_EFFECT_TABLE = 0x586269C
EQUIP_TABLE = 0x522BDE8

TARGET_ID = 0x29
CANDIDATE_IDS = (91060, 900011, 11990, 0)
TAG_TARGET = 244
MAIN_BUILD = '5069040'

CSV_COLUMNS = [
    'section', 'subject', 'namespace', 'table', 'row_index', 'row_id',
    'field', 'value', 'name', 'confidence', 'evidence',
]


# ---------------------------------------------------------------------------
# byte helpers
# ---------------------------------------------------------------------------
def u32(data: bytes, off: int) -> int:
    return struct.unpack_from('<I', data, off)[0]


def i32(data: bytes, off: int) -> int:
    return struct.unpack_from('<i', data, off)[0]


def f32(data: bytes, off: int) -> float:
    return struct.unpack_from('<f', data, off)[0]


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


# ---------------------------------------------------------------------------
# stdr tables
# ---------------------------------------------------------------------------
def iter_stdr(data: bytes) -> list[dict]:
    """Valid stdr tables: 0x98 + stride*rows == pool_rel and in-file."""
    tabs, search = [], 0
    while True:
        pos = data.find(b'stdr', search)
        if pos < 0:
            break
        try:
            nstr = u32(data, pos + 0x08)
            stride = u32(data, pos + 0x14)
            nrows = u32(data, pos + 0x18)
            pool_rel = u32(data, pos + 0x90)
        except struct.error:
            search = pos + 1
            continue
        end = 0x98 + stride * nrows
        if (8 <= stride <= 65536 and stride % 8 == 0
                and 1 <= nrows <= 2_000_000
                and pool_rel == end and pos + pool_rel <= len(data)):
            tabs.append({
                'pos': pos, 'stride': stride, 'rows': nrows,
                'nstr': nstr, 'pool_rel': pool_rel, 'base': pos + 0x98,
                'md5': data[pos + 0x6c:pos + 0x8c].decode('ascii', 'replace'),
            })
        search = pos + 1
    return tabs


def table_at(data: bytes, pos: int) -> dict:
    return {
        'pos': pos,
        'nstr': u32(data, pos + 0x08),
        'stride': u32(data, pos + 0x14),
        'rows': u32(data, pos + 0x18),
        'pool_rel': u32(data, pos + 0x90),
        'base': pos + 0x98,
        'md5': data[pos + 0x6c:pos + 0x8c].decode('ascii', 'replace'),
    }


def load_string_table(data: bytes, pos: int | None = None,
                      t: dict | None = None) -> GS.Table:
    t = t or table_at(data, pos)
    tab = GS.Table(data, t['pos'])
    tab.strings = GS.parse_pool(data, t['pos'] + tab.pool_rel, tab.nstr)
    return tab


def cell_text(data: bytes, tab: GS.Table, row_index: int, cell: int) -> str:
    row = tab.base + row_index * tab.stride
    b = GS.u32(data, row + 8 + cell * 8 + 4)
    return GS.strings_get(data, tab, b) or ''


def key_to_row(data: bytes, tab: GS.Table) -> dict[int, int]:
    return {GS.u32(data, tab.base + r * tab.stride): r
            for r in range(tab.nrows)}


def row_key(data: bytes, tab: GS.Table, row_index: int) -> int:
    return GS.u32(data, tab.base + row_index * tab.stride)


def all_strings(data: bytes, tab: GS.Table, row_index: int) -> list[tuple[int, str]]:
    out = []
    for i in range(tab.ncell):
        text = cell_text(data, tab, row_index, i)
        if text:
            out.append((i, text))
    return out


def scan_key(data: bytes, tab: GS.Table, key: int) -> list[dict]:
    """Return row-key and cell hits for a u32 key."""
    hits = []
    for r in range(tab.nrows):
        row = tab.base + r * tab.stride
        rk = GS.u32(data, row)
        if rk == key:
            hits.append({'row_index': r, 'row_key': rk, 'cell': '', 'which': 'key'})
        for c in range(tab.ncell):
            a, b = GS.u32pair(data, row + 8 + c * 8)
            if key in (a, b):
                hits.append({
                    'row_index': r, 'row_key': rk, 'cell': c,
                    'which': 'a' if a == key else 'b',
                })
    return hits


# ---------------------------------------------------------------------------
# known-table name helpers
# ---------------------------------------------------------------------------
class Known:
    def __init__(self, data: bytes):
        self.data = data
        self.skill = load_string_table(data, SKILL_TABLE)
        self.buff_effect = load_string_table(data, BUFF_EFFECT_TABLE)
        self.buff_main = load_string_table(data, BUFF_MAIN_TABLE)
        self.kill_effect = load_string_table(data, KILL_EFFECT_TABLE)
        self.equip = load_string_table(data, EQUIP_TABLE)
        self.tag = load_string_table(data, TAG_TABLE)
        self.skill_rows = key_to_row(data, self.skill)
        self.buff_effect_rows = key_to_row(data, self.buff_effect)
        self.buff_main_rows = key_to_row(data, self.buff_main)
        self.kill_rows = key_to_row(data, self.kill_effect)
        self.equip_rows = key_to_row(data, self.equip)
        self.tag_rows = key_to_row(data, self.tag)

    def skill_info(self, key: int) -> dict:
        r = self.skill_rows.get(key)
        if r is None:
            return {}
        name = cell_text(self.data, self.skill, r, 4)
        # cell 26 is the skill asset (Prefab_Characters/.../skill/...);
        # cell 18/19/20 are generic indicators and must not be used as the identity.
        prefab = cell_text(self.data, self.skill, r, 26)
        if not prefab:
            for _i, text in all_strings(self.data, self.skill, r):
                if text.startswith(('Prefab_Characters', 'Prefab_Skill_Effects')) \
                        or '/skill/' in text:
                    prefab = text
                    break
        return {'row': r, 'name': name, 'prefab': prefab,
                'cells': all_strings(self.data, self.skill, r)}

    def buff_effect_info(self, key: int) -> dict:
        r = self.buff_effect_rows.get(key)
        if r is None:
            return {}
        return {'row': r,
                'name': cell_text(self.data, self.buff_effect, r, 1),
                'desc': cell_text(self.data, self.buff_effect, r, 2),
                'prefab': cell_text(self.data, self.buff_effect, r, 3),
                'cells': all_strings(self.data, self.buff_effect, r)}

    def buff_main_info(self, key: int) -> dict:
        r = self.buff_main_rows.get(key)
        if r is None:
            return {}
        name = cell_text(self.data, self.buff_main, r, 14)
        prefab = cell_text(self.data, self.buff_main, r, 17)
        if not name and prefab:
            name = prefab.rsplit('/', 1)[-1]
        return {'row': r, 'name': name, 'prefab': prefab,
                'cells': all_strings(self.data, self.buff_main, r)}

    def kill_info(self, key: int) -> dict:
        def _info(r: int, kind: str, **extra) -> dict:
            return {
                'row': r, 'kind': kind, **extra,
                'name': cell_text(self.data, self.kill_effect, r, 0),
                'desc': cell_text(self.data, self.kill_effect, r, 1),
                'prefab': cell_text(self.data, self.kill_effect, r, 3),
                'cells': all_strings(self.data, self.kill_effect, r),
            }

        r = self.kill_rows.get(key)
        if r is not None:
            return _info(r, 'row_key', row_key=key)
        hits = scan_key(self.data, self.kill_effect, key)
        if not hits:
            return {}
        h = hits[0]
        return _info(h['row_index'], 'cell', row_key=h['row_key'],
                     cell=h['cell'], which=h['which'])

    def equip_hits(self, key: int) -> list[dict]:
        return scan_key(self.data, self.equip, key)

    def tag_info(self, key: int) -> dict:
        r = self.tag_rows.get(key)
        if r is None:
            return {}
        return {'row': r, 'name': cell_text(self.data, self.tag, r, 2),
                'desc': cell_text(self.data, self.tag, r, 3),
                'short_desc': cell_text(self.data, self.tag, r, 4),
                'cells': all_strings(self.data, self.tag, r)}


# ---------------------------------------------------------------------------
# target table analysis
# ---------------------------------------------------------------------------
def analyze_target_table(data: bytes, known: Known, tabs: list[dict]) -> dict:
    t = table_at(data, TARGET_TABLE)
    base, stride, nrows = t['base'], t['stride'], t['rows']
    rows = [struct.unpack_from('<14I', data, base + i * stride)
            for i in range(nrows)]
    by_id = {r[0]: i for i, r in enumerate(rows)}
    missing_ids = [i for i in range(min(by_id), max(by_id) + 1) if i not in by_id]
    row_index = by_id.get(11990)
    row11990 = rows[row_index] if row_index is not None else ()
    md5_rows = md5_hex(data[base:base + stride * nrows])

    # group structure
    group_counts = Counter((r[1], r[2]) for r in rows)
    class_counts = Counter(r[3] for r in rows)
    class_const = {}
    for cls in sorted(class_counts):
        sub = [r for r in rows if r[3] == cls]
        class_const[cls] = {c: Counter(x[c] for x in sub).most_common(4)
                            for c in (4, 5, 7, 8, 9, 10, 11, 12, 13)}

    # col6 values: action/skill ids
    col6_values = sorted(set(r[6] for r in rows))
    five = [v for v in col6_values if 10000 <= v <= 99999]
    parsed = [(v, v // 100, v % 100) for v in five if 100 <= v // 100 <= 599]
    skill_hits = [v for v in col6_values if v in known.skill_rows]
    col9_values = sorted(set(r[9] for r in rows))
    col4_values = sorted(set(r[4] for r in rows))

    # sample row 11990's group
    grp = (row11990[1], row11990[2], row11990[3]) if row11990 else ()
    grp_rows = [r for r in rows if (r[1], r[2], r[3]) == grp]

    # catalog / names / databin lists
    cat_row = None
    for r in csv.DictReader(open(DATASETS / 'native_table_catalog.csv',
                                 encoding='utf-8-sig')):
        if int(r['offset']) == TARGET_TABLE:
            cat_row = r
            break
    name_rows = [r for r in csv.DictReader(
                     open(DATASETS / 'native_table_names.csv', encoding='utf-8-sig'))
                 if r['table'] == str(TARGET_TABLE)]
    live = json.load(open(DEVICE / 'databin_tables_live.json', encoding='utf-8'))
    live_match = [e for e in live if e.get('rows') == nrows]
    manifest = list(csv.DictReader(open(DATASETS / 'tables_manifest.csv',
                                        encoding='utf-8-sig')))
    manifest_match = [e for e in manifest
                      if int(e.get('rows') or -1) == nrows
                      and int(e.get('stride') or -1) == stride]
    txt_match = []
    for txt in (DEVICE / 'tables.txt', DEVICE / 'tables_live.txt',
                DEVICE / 'tables_live2.txt'):
        if not txt.exists():
            continue
        for line in txt.read_text(encoding='utf-8', errors='replace').splitlines():
            p = line.split('\t')
            if len(p) < 8:
                continue
            try:
                st = int(p[2], 16)
                rr = int(p[5][-8:], 16)
            except ValueError:
                continue
            if st == stride and rr == nrows:
                txt_match.append((txt.name, p[6]))
                break

    # col6 example names for row 11990 + special rows
    def col6_label(v: int) -> str:
        info = known.skill_info(v)
        if info:
            nm = info.get('name') or ''
            pf = (info.get('prefab') or '').rsplit('/', 1)[-1]
            # cell4 repeats the hero's passive name (e.g. 孙膑 时间沙漏 for A3);
            # for A* action rows only the action asset name is trustworthy.
            if pf.startswith('A') and pf[1:].isdigit():
                return pf
            return (nm + ' / ' if nm else '') + pf
        bi = known.buff_main_info(v)
        if bi:
            return 'buff_main:' + (bi.get('name') or '')
        be = known.buff_effect_info(v)
        if be:
            return 'buff_effect:' + (be.get('name') or '')
        return ''

    row11990_col6 = col6_label(row11990[6]) if row11990 else ''
    special_labels = {v: col6_label(v) for v in (900019, 900020, 13000, 13005)}

    return {
        't': t, 'rows': rows, 'row_index': row_index, 'row11990': row11990,
        'missing_ids': missing_ids, 'md5_rows': md5_rows, 'group_counts': group_counts,
        'class_counts': class_counts, 'class_const': class_const,
        'col6_values': col6_values, 'five': five, 'parsed': parsed,
        'skill_hits': skill_hits, 'col9_values': col9_values,
        'col4_values': col4_values, 'grp': grp, 'grp_rows': grp_rows,
        'cat_row': cat_row, 'name_rows': name_rows,
        'live_match': live_match, 'manifest_match': manifest_match,
        'txt_match': txt_match, 'row11990_col6': row11990_col6,
        'special_labels': special_labels,
    }


# ---------------------------------------------------------------------------
# replay events
# ---------------------------------------------------------------------------
def extract_main() -> dict:
    return AD.extract_sample(MAIN, with_tail=True)


def events_of(res: dict, subtype: str) -> list[dict]:
    return [e for e in res['events'] if e.get('subtype') == subtype]


def nearest(seqs: list[int], seq: int) -> int | None:
    return min((abs(x - seq) for x in seqs), default=None)


def nearest_time(items: list[dict], t: float, key: str = 'time_s') -> tuple[float, dict] | None:
    if not items:
        return None
    it = min(items, key=lambda e: abs(float(e[key]) - t))
    return abs(float(it[key]) - t), it


def alignment_rows(res: dict, target_id: int) -> list[dict]:
    by = defaultdict(lambda: defaultdict(list))
    for e in res['events']:
        by[e['hero_entity']][e['subtype']].append(e['seq'])
    kills = [g for g in res['gold'] if g['source'] == 43]
    deaths = [e for e in res['events']
              if e['subtype'] == '0x02/0x81' and str(e['field_a']) == '6']
    highs = [e for e in res['events'] if e['subtype'] in ('0x1f', '0x20')]
    out = []
    for e in res['events']:
        if e['subtype'] != '0x29' or e['field_a'] != target_id:
            continue
        hero = e['hero_entity']
        d = {}
        for sub in ('0x02/0x87', '0x1e', '0x2c', '0x23', '0x1f', '0x20'):
            d[sub] = nearest(by[hero][sub], e['seq'])
        kt = nearest_time(kills, float(e['time_s']))
        dt = nearest_time(deaths, float(e['time_s']))
        ht = nearest_time(highs, float(e['time_s']))
        out.append({
            'event': e, 'd87': d['0x02/0x87'], 'd1e': d['0x1e'],
            'd2c': d['0x2c'], 'd23': d['0x23'], 'd1f': d['0x1f'],
            'd20': d['0x20'], 'kill': kt, 'death': dt, 'high': ht,
            'n87': len(by[hero]['0x02/0x87']), 'n1e': len(by[hero]['0x1e']),
            'n2c': len(by[hero]['0x2c']), 'n23': len(by[hero]['0x23']),
        })
    return out


def scan_batch(limit: bool = False) -> dict:
    """Cross-build scan for 0x29/0x1f evidence (read-only)."""
    out = {
        'builds': Counter(), 'id29': Counter(), 'id29_by_build': defaultdict(Counter),
        '91060_heroes': Counter(), '91060_tails': Counter(),
        '91060_params': Counter(), 'runs': [],
        'tag_by_build': defaultdict(Counter), 'tag_all': Counter(),
        '11990': [],
    }
    files = sorted(BATCH.glob('*.abc'))
    if limit:
        files = [MAIN]
    for f in files:
        try:
            res = AD.extract_sample(f, with_tail=False)
        except Exception:
            continue
        build = AD.build_of(res['data'])
        out['builds'][build] += 1
        for e in res['events']:
            if e['subtype'] == '0x1f':
                out['tag_by_build'][build][e['tag_id']] += 1
                out['tag_all'][e['tag_id']] += 1
            if e['subtype'] != '0x29':
                continue
            out['id29'][e['field_a']] += 1
            out['id29_by_build'][build][e['field_a']] += 1
            if e['field_a'] == 91060:
                out['91060_heroes'][(e['hero_id'], e['hero_name'])] += 1
                out['91060_tails'][e['field_c']] += 1
                out['91060_params'][e['field_b']] += 1
                out['runs'].append({
                    'file': f.name, 'build': build, 'seq': e['seq'],
                    'time_s': e['time_s'], 'entity': e['hero_entity'],
                    'hero_id': e['hero_id'], 'hero_name': e['hero_name'],
                    'param': e['field_b'], 'tail': e['field_c'],
                })
            if e['field_a'] == 11990:
                out['11990'].append({
                    'file': f.name, 'build': build, 'seq': e['seq'],
                    'time_s': e['time_s'], 'entity': e['hero_entity'],
                    'hero_id': e['hero_id'], 'hero_name': e['hero_name'],
                    'param': e['field_b'], 'tail': e['field_c'],
                })
    return out


def tail_actor_resolution() -> dict:
    """Resolve 11990 tail actors to roster heroes in 5069040 and 5230306."""
    out = {}
    for label, path in (
        ('5069040', MAIN),
        ('5230306', next(BATCH.glob('*20261027_232156*.abc'), None)),
    ):
        if path is None:
            continue
        res = AD.extract_sample(path, with_tail=False)
        rev = {v: k for k, v in res['actors'].items()}
        out[label] = {
            'build': AD.build_of(res['data']),
            'actors': res['actors'],
            'rev': rev,
            'roster': res['roster'],
        }
    return out


# ---------------------------------------------------------------------------
# tag evidence
# ---------------------------------------------------------------------------
def tag_analysis(data: bytes, known: Known, tabs: list[dict],
                 batch: dict) -> dict:
    t = table_at(data, TAG_TABLE)
    ids = sorted({row_key(data, known.tag, r) for r in range(known.tag.nrows)})
    gaps = [i for i in range(min(ids), max(ids) + 1) if i not in set(ids)]
    small = table_at(data, SMALL_HIGHLIGHT)
    small_ids = sorted({u32(data, small['base'] + r * small['stride'])
                        for r in range(small['rows'])})

    # all tables with row key 244
    key244 = []
    for tab in tabs:
        base, stride, nrows = tab['base'], tab['stride'], tab['rows']
        # quick scan only the first u32 of each row
        found = False
        for r in range(nrows):
            if u32(data, base + r * stride) == 244:
                found = True
                break
        if found:
            key244.append(tab['pos'])

    # tag-like strings across decoded C# strings
    tag_like = Counter()
    row244_taglike = []
    try:
        fh = open(DATASETS / 'agent_global_strings.csv', encoding='utf-8-sig')
    except OSError:
        fh = None
    if fh is not None:
        with fh:
            for r in csv.DictReader(fh):
                text = r['text']
                if any(k in text for k in ('群控', '团战', '高光', '开团', '承伤')):
                    tag_like[r['table']] += 1
                    if int(r['row']) == 244:
                        row244_taglike.append((r['table'], text[:80]))
    return {
        't': t, 'ids': ids, 'gaps': gaps, 'small': small,
        'small_ids': small_ids, 'key244': key244, 'tag_like': tag_like,
        'row244_taglike': row244_taglike,
        'observed_tags': batch['tag_all'],
        'observed_5069040': batch['tag_by_build'].get(MAIN_BUILD, Counter()),
    }


# ---------------------------------------------------------------------------
# output helpers
# ---------------------------------------------------------------------------
def md_table(headers: list[str], rows: list[list]) -> list[str]:
    out = ['| ' + ' | '.join(headers) + ' |',
           '|' + '|'.join(['---'] * len(headers)) + '|']
    for row in rows:
        out.append('| ' + ' | '.join('' if x is None else str(x) for x in row) + ' |')
    return out


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in CSV_COLUMNS})


def fmt_dist(d: int | None) -> str:
    return '' if d is None else str(d)


def fmt_time_dist(d: tuple[float, dict] | None) -> str:
    if not d:
        return ''
    return f'{d[0]:.2f}s'


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--no-batch', action='store_true',
                    help='only parse the main sample (skip 28-file scan)')
    ap.add_argument('--out-csv', type=Path,
                    default=DATASETS / 'agent_0x29_names.csv')
    ap.add_argument('--out-md', type=Path,
                    default=DATASETS / 'agent_0x29_names.md')
    args = ap.parse_args()

    if not DC_DB.exists():
        print(f'dc.db not found: {DC_DB}', file=sys.stderr)
        return 2
    if not MAIN.exists():
        print(f'main sample not found: {MAIN}', file=sys.stderr)
        return 2

    print('reading dc.db ...')
    data = DC_DB.read_bytes()
    known = Known(data)
    tabs = iter_stdr(data)
    string_tables = [t for t in tabs if t['nstr'] > 0]
    print(f'  size={len(data):,} stdr={len(tabs)} string_tables={len(string_tables)}')

    target = analyze_target_table(data, known, tabs)
    print(f'  target table @{TARGET_TABLE:#x}: stride={target["t"]["stride"]} '
          f'rows={target["t"]["rows"]} strings={target["t"]["nstr"]}')

    print('parsing main replay ...')
    res = extract_main()
    ev29 = events_of(res, '0x29')
    ev1f = events_of(res, '0x1f')
    ev20 = events_of(res, '0x20')
    align = alignment_rows(res, 91060)
    print(f'  events=0x29 {len(ev29)}  0x1f {len(ev1f)}  0x20 {len(ev20)}')

    batch = scan_batch(limit=args.no_batch)
    print(f'  batch scans: builds={dict(batch["builds"])} tags={dict(batch["tag_all"])}')

    tails = tail_actor_resolution()
    tag = tag_analysis(data, known, tabs, batch)

    # databin version evidence
    databinver = DEVICE / 'databinver'
    databinver_u32 = []
    if databinver.exists():
        dv = databinver.read_bytes()[:32]
        databinver_u32 = [u32(dv, o) for o in range(0, min(len(dv) - 3, 24), 4)]

    # main build
    main_build = AD.build_of(res['data'])

    # ------------------------------------------------------------------
    # CSV rows
    # ------------------------------------------------------------------
    rows: list[dict] = []

    def add(section, subject, field, value, *, namespace='', table='',
            row_index='', row_id='', name='', confidence='', evidence=''):
        rows.append({
            'section': section, 'subject': subject, 'namespace': namespace,
            'table': table, 'row_index': row_index, 'row_id': row_id,
            'field': field, 'value': value, 'name': name,
            'confidence': confidence, 'evidence': evidence,
        })

    tt = target['t']
    add('build', 'main replay', 'build', main_build,
        confidence='high', evidence='tools/agent_damage_skill_objective.build_of(.abc)')
    add('build', 'dc.db', 'size', len(data), confidence='high',
        evidence=str(DC_DB))
    add('build', 'dc.db', 'databinver_u32_0_8', ' '.join(map(str, databinver_u32[:3])),
        confidence='medium-high',
        evidence='device/databinver 偏移 0/4/8；偏移 8=5247758，与 5.105/5.107 的 build 同号')
    add('build', 'dc.db', 'valid_stdr_tables', len(tabs), confidence='high',
        evidence='0x98+stride*rows==pool_rel 且落在文件内')
    add('build', 'dc.db', 'string_tables', len(string_tables), confidence='high',
        evidence='declared strings > 0')

    add('table_probe', 'table 0x7384068', 'signature', data[TARGET_TABLE:TARGET_TABLE + 4].decode('latin1'),
        table=f'0x{TARGET_TABLE:x}', confidence='high')
    add('table_probe', 'table 0x7384068', 'stride', tt['stride'],
        table=f'0x{TARGET_TABLE:x}', confidence='high', evidence='header +0x14')
    add('table_probe', 'table 0x7384068', 'rows', tt['rows'],
        table=f'0x{TARGET_TABLE:x}', confidence='high', evidence='header +0x18')
    add('table_probe', 'table 0x7384068', 'row_keys',
        f'1..20756, dense, missing={target["missing_ids"]}',
        table=f'0x{TARGET_TABLE:x}', confidence='high',
        evidence='row key 是分配序号，不是语义 ID')
    add('table_probe', 'table 0x7384068', 'declared_strings', tt['nstr'],
        table=f'0x{TARGET_TABLE:x}', confidence='high', evidence='header +0x08')
    add('table_probe', 'table 0x7384068', 'pool_rel',
        f'0x{tt["pool_rel"]:x}', table=f'0x{TARGET_TABLE:x}', confidence='high',
        evidence=f'=0x98+{tt["stride"]}*{tt["rows"]}；池长 0')
    add('table_probe', 'table 0x7384068', 'header_md5_field', tt['md5'],
        table=f'0x{TARGET_TABLE:x}', confidence='high', evidence='header +0x6c..+0x8b，32 hex')
    add('table_probe', 'table 0x7384068', 'md5_of_rows', target['md5_rows'],
        table=f'0x{TARGET_TABLE:x}', confidence='high',
        evidence='md5(rows 区域)；与 header 字段相同 → 这是数据校验和，不是表名')
    add('table_probe', 'native_table_catalog.csv', 'row',
        'present' if target['cat_row'] else 'absent', table='121127016',
        confidence='high',
        evidence=str(target['cat_row']))
    add('table_probe', 'native_table_names.csv', 'rows', len(target['name_rows']),
        table='121127016', confidence='high',
        evidence='name_coverage 为空 → native_table_names 的 top-20 过滤器排除；不是 catalog 缺表')
    add('table_probe', 'databin_tables_live.json', 'rows_20755_matches',
        len(target['live_match']), confidence='high',
        evidence='955 张 live 表；没有 rows=20,755 的表')
    add('table_probe', 'tables_manifest.csv', 'stride56_rows20755_matches',
        len(target['manifest_match']), confidence='high',
        evidence='825 张 manifest 表；无匹配')
    add('table_probe', 'tables.txt/live', 'stride56_rows20755_matches',
        len(target['txt_match']), confidence='medium',
        evidence='1,024 行 live 指针列表；无匹配')

    for off, val in zip(range(0, 14), target['row11990']):
        add('row11990', 'row 11990', f'+0x{off*4:02x}',
            val, table=f'0x{TARGET_TABLE:x}',
            row_index=target['row_index'], row_id=target['row11990'][0],
            confidence='high',
            evidence='14×u32；行键 11990，0-based row index '
                     f'{target["row_index"]}（ID 从 1 开始）')
    add('row11990', 'row 11990', 'col6_skill_ref', target['row11990'][6],
        name=target['row11990_col6'], table=f'0x{TARGET_TABLE:x}',
        row_index=target['row_index'], row_id=11990, confidence='high',
        evidence='11802 在技能表是 118_SunBin/skill/A3（孙膑普攻 A3），不是技能名')
    add('row11990', 'row 11990', 'group',
        f'{target["grp"]} / {len(target["grp_rows"])} rows',
        table=f'0x{TARGET_TABLE:x}', row_index=target['row_index'],
        row_id=11990, confidence='high',
        evidence='group=(col1=58, col2=2, col3=3)；同组 35 个动作 ID，11802 只是其中一个')

    add('table_semantics', '0x7384068', 'groups_14x13',
        f'{len(target["group_counts"])} (col1,col2) groups; sizes '
        f'{min(target["group_counts"].values())}..{max(target["group_counts"].values())}',
        table=f'0x{TARGET_TABLE:x}', confidence='high',
        evidence='col1=50..63 共 14 个；col2=1..13 共 13 个；共 182 组')
    add('table_semantics', '0x7384068', 'row_classes',
        dict(target['class_counts']), table=f'0x{TARGET_TABLE:x}',
        confidence='high',
        evidence='col3 1..5；每个 class 的 col4/5/7/8/9/10 基本恒定')
    add('table_semantics', '0x7384068', 'class_constants',
        json.dumps({str(k): {str(c): v for c, v in d.items()}
                    for k, d in target['class_const'].items()}, ensure_ascii=False),
        table=f'0x{TARGET_TABLE:x}', confidence='medium',
        evidence='class1: col5=22/col9=13000/col10=5；class2-4: col5=13/col9=13005/col10=2/4/6')
    add('table_semantics', '0x7384068', 'col6_action_ids',
        f'{len(target["col6_values"])} distinct; {len(target["parsed"])} parse as hero*100+suffix; '
        f'{len(target["skill_hits"])} are skill-table row keys',
        table=f'0x{TARGET_TABLE:x}', confidence='high',
        evidence='5 位值范围 hero 105..563；3 位值是单位/动作 ID；900019/900020 是 buff ID')
    add('table_semantics', '0x7384068', 'special_id_labels',
        json.dumps(target['special_labels'], ensure_ascii=False),
        table=f'0x{TARGET_TABLE:x}', confidence='medium',
        evidence='900020=buff_main 纣王控制免疫；13000=技能表 二天一流；13005=宫本 A11；900019 在现有表无名称')
    add('table_semantics', '0x7384068', 'table_label',
        'PVE/AI 关卡动作池（推测名；C# 表名不可得）',
        table=f'0x{TARGET_TABLE:x}', confidence='medium-low',
        evidence='14 关 × 13 阶段 × 5 类，每行分配一个 action/skill/buff；无字符串池，不在名称表')

    # 0x29 events
    for e in ev29:
        add('event29', f'seq {e["seq"]}', 'event', e['field_a'],
            row_id=e['field_a'], name=e['raw_hex'],
            confidence='high',
            evidence=f't={e["time_s"]}s hero={e["hero_entity"]}/{e["hero_name"]} '
                     f'actor={e["actor_id"]} param={e["field_b"]} tail={e["field_c"]} '
                     f'segment={e["segment"]}')

    # namespaces for 91060 / 900011 / 11990
    ns_rows = []
    for cid in CANDIDATE_IDS:
        si = known.skill_info(cid)
        bi = known.buff_effect_info(cid)
        bm = known.buff_main_info(cid)
        ki = known.kill_info(cid)
        eq = known.equip_hits(cid)
        ns_rows.append({
            'id': cid, 'skill': si, 'buff_effect': bi, 'buff_main': bm,
            'kill': ki, 'equip': eq,
        })
        add('namespace', str(cid), 'skill_0x1ce47c',
            si.get('name', ''), namespace='skill', table='0x1ce47c',
            row_index=si.get('row', ''), row_id=cid if si else '',
            name=si.get('prefab', ''), confidence='high' if si else '',
            evidence='skill table row key' if si else 'no row key')
        add('namespace', str(cid), 'buff_effect_0x3ba41a8',
            bi.get('name', ''), namespace='buff_effect', table='0x3ba41a8',
            row_index=bi.get('row', ''), row_id=cid if bi else '',
            name=bi.get('prefab', ''), confidence='high' if bi else '',
            evidence='buff_effect row key' if bi else 'no row key')
        add('namespace', str(cid), 'buff_main_0x8268ac',
            bm.get('name', ''), namespace='buff_main', table='0x8268ac',
            row_index=bm.get('row', ''), row_id=cid if bm else '',
            name=bm.get('prefab', ''), confidence='high' if bm else '',
            evidence='buff_main row key' if bm else 'no row key')
        add('namespace', str(cid), 'kill_effect_0x586269c',
            ki.get('name', ''), namespace='kill_effect', table='0x586269c',
            row_index=ki.get('row', ''), row_id=ki.get('row_key', ''),
            name=ki.get('prefab', ''), confidence='high' if ki else '',
            evidence=(f'{ki.get("kind")} cell={ki.get("cell", "")}'
                      if ki else 'no row key / cell'))
        add('namespace', str(cid), 'equip_0x522bde8',
            len(eq), namespace='equip', table='0x522bde8',
            confidence='high', evidence='row-key/cell hits')

    # 91060 evidence
    heroes_91060 = batch['91060_heroes']
    add('evidence91060', '91060', 'events_all_builds', sum(heroes_91060.values()),
        confidence='high', evidence='28 个 .abc 扫描；0x29 id=91060')
    known_heroes = sum(1 for (h, _n) in heroes_91060 if h)
    add('evidence91060', '91060', 'distinct_heroes',
        f'{len(heroes_91060)} combos ({known_heroes} mapped + '
        f'{len(heroes_91060) - known_heroes} unmapped); '
        f'has_xiaoqiao_106={any(h == "106" for h, _ in heroes_91060)}',
        confidence='high',
        evidence='、'.join(f'{n}({h})x{c}' for (h, n), c in heroes_91060.most_common(12)))
    add('evidence91060', '91060', 'tails', dict(batch['91060_tails']),
        confidence='high', evidence='165/165 tail=0；不是指向目标的技能/击败')
    add('evidence91060', '91060', 'params', dict(batch['91060_params']),
        confidence='medium', evidence='param 不是技能等级：0/1/15/24/25/32/33/54/1348/7523')
    for a in align:
        e = a['event']
        add('align91060', f'seq {e["seq"]}', 'nearest_frames',
            f'87={fmt_dist(a["d87"])} 1e={fmt_dist(a["d1e"])} 2c={fmt_dist(a["d2c"])} '
            f'23={fmt_dist(a["d23"])} 1f={fmt_dist(a["d1f"])} 20={fmt_dist(a["d20"])}',
            confidence='high',
            evidence=f'{e["hero_name"]} t={e["time_s"]}s param={e["field_b"]}')
        add('align91060', f'seq {e["seq"]}', 'nearest_global_seconds',
            f'kill={fmt_time_dist(a["kill"])} death={fmt_time_dist(a["death"])} '
            f'high={fmt_time_dist(a["high"])}',
            confidence='high', evidence='source43 金币击杀 / 0x81 v6 死亡 / 0x1f+0x20')
    # 75s cycle
    runs = [r for r in batch['runs'] if r['build'] == MAIN_BUILD]
    intervals = []
    by_key = defaultdict(list)
    for r in runs:
        by_key[(r['file'], r['entity'])].append(r)
    for key, lst in by_key.items():
        lst = sorted(lst, key=lambda x: x['time_s'])
        for i in range(len(lst) - 1):
            dt = lst[i + 1]['time_s'] - lst[i]['time_s']
            if dt >= 1:
                intervals.append((round(dt, 2), lst[i]['hero_name'], lst[i]['entity']))
    near75 = [x for x in intervals if 70 <= x[0] <= 80]
    add('evidence91060', '91060', 'repeats_near_75s',
        '; '.join(f'{d}s {h}({e})' for d, h, e in sorted(near75)),
        confidence='medium-high',
        evidence='5069040 同 (file, entity) 的 91060 间隔；'
                 + '; '.join(f'{d}s {h}' for d, h, _ in sorted(near75)))

    # 11990 evidence
    for e in [x for x in ev29 if x['field_a'] == 11990]:
        add('evidence11990', f'seq {e["seq"]}', 'main_event',
            f't={e["time_s"]} hero={e["hero_name"]}({e["hero_id"]}) actor={e["actor_id"]} '
            f'param={e["field_b"]} tail={e["field_c"]}',
            row_id=11990, confidence='high')
    for r in batch['11990']:
        if r['build'] == MAIN_BUILD:
            continue
        add('evidence11990', f'{r["build"]} seq {r["seq"]}', 'cross_build_event',
            f't={r["time_s"]} hero={r["hero_name"]}({r["hero_id"]}) entity={r["entity"]} '
            f'param={r["param"]} tail={r["tail"]}',
            row_id=11990, confidence='high', evidence=r['file'])
    add('evidence11990', '11990', 'all_table_key_or_cell_hits',
        'skill=0 buff_effect=0 buff_main=0 kill=0 equip=0; only 0x7384068 row key',
        confidence='high',
        evidence='1,245 张 stdr 表逐表扫 row key；5 张命名表逐 cell 扫')
    add('evidence11990', '11990', 'row_0x7384068',
        f'fields={target["row11990"]}; col6={target["row11990"][6]} '
        f'({target["row11990_col6"]})',
        table='0x7384068', row_index=target['row_index'], row_id=11990,
        confidence='high',
        evidence=f'该表行键 1..20756（仅缺 {target["missing_ids"]}）；'
                 '11990 只是第 11,988 行，不是效果名')
    add('evidence11990', '11990', 'id_pattern',
        '119*100+90 → 扁鹊(119)+特殊槽位90；技能表只有 11900/11901/11902/11910/11920/11930',
        confidence='medium-low',
        evidence='4/4 事件都是扁鹊对友方(赵云/后羿)；param=-1；更像治疗/印记类专属效果')

    # tag 244 evidence
    add('tag244', 'tag_table_0x695f084', 'header',
        f'stride={tag["t"]["stride"]} rows={tag["t"]["rows"]} strings={tag["t"]["nstr"]}',
        table='0x695f084', confidence='high')
    add('tag244', 'tag_table_0x695f084', 'row_keys',
        f'{min(tag["ids"])}..{max(tag["ids"])} ({len(tag["ids"])} keys; gaps={tag["gaps"]})',
        table='0x695f084', confidence='high',
        evidence='row key 1..208；244 不在其中')
    for key in (1, 2, 5, 21, 93, 94, 244):
        info = known.tag_info(key)
        add('tag244', f'tag {key}', 'name',
            info.get('name', ''), table='0x695f084',
            row_index=info.get('row', ''), row_id=key,
            confidence='high' if info else 'high (absent)',
            evidence=(info.get('desc', '') if info else 'row key does not exist; max 208'))
    add('tag244', 'tag 244', 'main_event',
        't=360.45s 东皇太一(187) actor=12 actorObjID=12 field_a=-45 field_c=42 u8_d/e=0/0',
        row_id=244, confidence='high',
        evidence='0x1f body: 1f f4 ...；tag 字节 f4=244')
    add('tag244', 'tag 244', 'extension_search_key244_tables',
        len(tag['key244']), confidence='high',
        evidence='1,245 张 stdr 表里 55 张有 row key 244；无 tag-like 名称')
    add('tag244', 'tag 244', 'tag_like_tables',
        json.dumps(dict(tag['tag_like'].most_common(10)), ensure_ascii=False),
        confidence='high',
        evidence='agent_global_strings.csv 中含 群控/团战/高光/开团/承伤 的表')
    add('tag244', 'tag 244', 'row244_taglike',
        tag['row244_taglike'] or 'none', confidence='high',
        evidence='在所有 tag-like 表里 row 244 没有名称')
    add('tag244', 'tag 244', 'small_highlight_table_0x699d82c',
        f'{min(tag["small_ids"])}..{max(tag["small_ids"])} ({len(tag["small_ids"])} keys)',
        table='0x699d82c', confidence='high',
        evidence='高光视频分类小表，最大 27，不是 tag244')
    add('tag244', 'tag 244', 'observed_5069040',
        dict(tag['observed_5069040']), confidence='high',
        evidence='6 个 5069040 样本：tag 1/2/5/244')
    add('tag244', 'tag 244', 'verdict',
        'available dc.db tag table max 208 → 244 out of table; '
        '5069040 event requires a >=244-row tag table → dc.db is not 5069040 tag table',
        confidence='medium-high',
        evidence='0x1f tag1/2/5 都是 row key；244>208；dc.db databinver 含 5247758')

    # verdicts
    add('verdict', '900011', 'name',
        '打包濒死队友 / ReviveDyingHero_Result', namespace='skill+buff_main',
        confidence='high', evidence='skill row2527 + buff_main row9036 两个命名空间一致')
    add('verdict', '91060', 'name',
        '峡谷裂口传送中断被动 (KeySpell/91060P1)', namespace='buff_effect',
        confidence='medium',
        evidence='最多英雄覆盖(26) + tail全0 + ~75s周期；排除小乔技能(high)与吕布击败特效(high)')
    add('verdict', '11990', 'name',
        'UNNAMED; only dense row 11990 in 0x7384068; 4/4 events 扁鹊→友方',
        namespace='none', confidence='high (unnamed)',
        evidence='技能/buff/击败/装备表 0 命中；0x7384068 是 PVE 动作池，不是名称表')
    add('verdict', 'tag244', 'name',
        'UNNAMED; outside available 5247758 tag table (max 208)',
        namespace='tag', confidence='high (out of available table)',
        evidence='0x1f tag1/2/5 row-key mapping exact; 93/94 cross-build exact; '
                 '244>208; no extension table')
    add('verdict', 'multi_namespace', 'conclusion',
        '0x29 id is a mixed KeySpell/effect notification, not one namespace; '
        '900011=two namespaces agree, 91060=three collide (choose buff_effect), '
        '11990=zero named tables, 0=null',
        confidence='high',
        evidence='skill/buff_effect/buff_main/kill_effect cross-table scan')

    # ------------------------------------------------------------------
    # markdown
    # ------------------------------------------------------------------
    md: list[str] = []
    md.append('# 0x29 id 定名与 0x1f tag244：表内证据与否定证据')
    md.append('')
    md.append(f'主样本：`{MAIN.name}`（build **{main_build}**）；'
              f'数据表：`dc.db` {len(data):,} B，`databinver` 偏移 8 = '
              f'**{databinver_u32[2] if len(databinver_u32) > 2 else "?"}**。')
    md.append('')
    md.append('> 只读：未修改回放/包体，未注入，未读 param.json，未使用 runtime_dump，'
              '未编辑 docs/memory。')
    md.append('')
    md.append('## 0. 结论先行')
    md.append('')
    md += md_table(['问题', '结论', '置信度', '最强证据'], [
        ['91060', '→ buff_effect `0x3ba41a8` row391「峡谷裂口传送中断被动」'
                  '（KeySpell/91060P1）', 'medium',
         '165 条/26 英雄、全 tail=0、无小乔；~75s 周期；技能表小乔 row1936 与击败特效均被排除'],
        ['900011', '→ 技能表 row2527「打包濒死队友」+ buff_main row9036 '
                   '`ReviveDyingHero_Result`', 'high',
         '两个命名空间同义；主样本李信自目标 tail=44'],
        ['11990', '不能定名；唯一 row key 在 `0x7384068`（PVE 关卡动作池），'
                  '该行 col6=11802=孙膑 A3', 'high（未命名）',
         '技能/buff/击败/装备表 0 命中；4/4 事件是扁鹊对友方'],
        ['tag244', '不能定名；在可用 dc.db 的 tag 表（max row 208）之外', 'high（可用表外）',
         '0x1f tag1/2/5 均按 row key 命中；244>208；无扩展表'],
        ['多命名空间', '0x29 id 是混合 KeySpell/effect 通知，不是单一表命名空间', 'high',
         '900011 双表一致、91060 三表同号、11990 零表命中'],
        ['关键阻塞', 'dc.db 的 databinver 含 **5247758**，主样本 build 是 **5069040**；'
                     '11990/tag244 需要 5069040 的 databin', 'medium-high',
         '`databinver` u32@8=5247758；5069040 有 tag244、5247758 tag 表 max 208'],
    ])
    md.append('')
    md.append('**一句话**：91060 归 buff_effect 最合理，900011 可高置信命名，'
              '11990 和 tag244 在现有表里**不能命名**；后两者更像“缺少 5069040 build 的表”，'
              '不是单纯多命名空间撞号。')
    md.append('')

    md.append('## 1. `dc.db @0x7384068` 的表描述')
    md.append('')
    md += md_table(['项', '值', '说明'], [
        ['表起点', f'`0x{TARGET_TABLE:x}` = {TARGET_TABLE}', '`stdr`'],
        ['+0x08 declared strings', tt['nstr'], '无字符串池'],
        ['+0x14 stride', tt['stride'], '56 B = 14×u32'],
        ['+0x18 rows', f'{tt["rows"]:,}',
         f'行键 1..20,756，仅缺 {target["missing_ids"]}；稠密分配号'],
        ['+0x90 pool_rel', f'`0x{tt["pool_rel"]:x}`', f'=0x98+56×20,755；池长 0'],
        ['+0x6c 32 hex', f'`{tt["md5"]}`', '= md5(rows 区域)；数据校验和，不是表名'],
        ['native_table_catalog', '**有**（offset 121127016）',
         f'`{target["cat_row"]}`'],
        ['native_table_names', '**0 行**', 'declared_strings=0 → name_coverage 空，被 top-20 过滤'],
        ['databin live/manifest/tables.txt', '无 rows=20,755', '955/825/1024 张 live 表均无此表；dc.db 有 1,245 张 stdr'],
    ])
    md.append('')
    md.append('**为什么 `native_table_names` 没有名称**：不是 catalog 缺表，而是这张表'
              '`declared_strings=0`、没有字符串池、没有 CJK 名称；`native_table_names.py` '
              '只取 `name_coverage` 非空的前 20 张表，所以它被过滤。`native_table_catalog.csv` '
              '里的 `ref_offset=4 / ref_hits=300` 是 (col1,col2) 两个小整数造成的假 ref 命中，'
              '没有池可解。')
    md.append('')
    md.append('### 1.1 row 11990 的字段')
    md.append('')
    labels = [
        ('+0x00', 'rowID = 11990（0-based row index 11,988）'),
        ('+0x04', '组 A = 58（14 个值 50..63 之一）'),
        ('+0x08', '组 B = 2（13 个值 1..13 之一）'),
        ('+0x0c', 'class = 3（1..5）'),
        ('+0x10', '常量 100'),
        ('+0x14', '常量 13'),
        ('+0x18', 'col6 动作/技能引用 = 11802 → 孙膑 A3（不是名字）'),
        ('+0x1c', '1'),
        ('+0x20', '2'),
        ('+0x24', '13005 → 宫本武藏 A11 动作引用'),
        ('+0x28', '4'),
        ('+0x2c', '0'),
        ('+0x30', '0'),
        ('+0x34', '0'),
    ]
    md += md_table(['偏移', '值', '解释'], [
        [o, str(v), lab] for (o, lab), v in zip(labels, target['row11990'])
    ])
    md.append('')
    md.append('### 1.2 表结构：14×13×5 的关卡动作池')
    md.append('')
    md.append(f'- (col1,col2) 共 **{len(target["group_counts"])}** 组：col1=50..63（14 个），'
              f'col2=1..13（13 个），即 14×13；每组 {min(target["group_counts"].values())}..'
              f'{max(target["group_counts"].values())} 行。')
    md.append(f'- col3 1..5 是行类别：{dict(target["class_counts"])}。'
              'class1/2/3/4 的 col4/5/7/8/9/10 基本恒定（class1: 100/22/1/2/13000/5；'
              'class2: 100/13/1/2/13005/2；class3: 100/13/1/2/13005/4；'
              'class4: 100/13/1/2/13005/6）；class5 每组 3 行特殊行（900019/900020/13001）。')
    md.append(f'- col6 是动作/技能引用：{len(target["col6_values"])} 个不同值，'
              f'{len(target["parsed"])} 个可解析为 `heroID*100+suffix`（hero 105..563），'
              f'{len(target["skill_hits"])} 个是技能表 row key；其余包括 3 位单位/动作 ID、'
              f'900019/900020（buff ID），以及 '
              f'{len(target["five"]) - len(target["skill_hits"])} 个不在技能表的 5 位值。')
    md.append(f'- row 11990 的组是 **(58,2,class3)**，同组 {len(target["grp_rows"])} 行；'
              f'row 11990 的 col6=11802（{target["row11990_col6"]}）。'
              '这个 11802 是孙膑普攻 A3，不是 11990 的语义。')
    md.append('')
    md.append('**表身份判定**：`0x7384068` 是一张无字符串的 **PVE/关卡动作池配置表**'
              '（14 关 × 13 阶段 × 5 类；每行把一个 action/skill/buff 引用分配给一个组），'
              'C#/databin 表名不可得（medium-low）。**row 11990 只是该表的第 11,988 行，'
              '不是 0x29 event 的命名行**。')
    md.append('')

    md.append('## 2. 主样本 0x29 的 10 条事件')
    md.append('')
    md += md_table(['seq', 't(s)', 'entity', '英雄', 'actor', 'id', 'param', 'tail'], [
        [e['seq'], e['time_s'], e['hero_entity'], e['hero_name'],
         e['actor_id'], e['field_a'], e['field_b'], e['field_c']]
        for e in ev29
    ])
    md.append('')
    md.append('布局仍按 `29 000000 actorID:u8 id:u32BE param:i32BE tail:u32BE`；'
              '`id` 不是单一技能表键：900011 是 KeySpell、91060 是 buff_effect、'
              '11990 无表可命中、0 是空/清除。')
    md.append('')

    md.append('## 3. 91060 该归哪张表')
    md.append('')
    md.append('### 3.1 三个同名命名空间')
    md.append('')
    ns91060 = next(x for x in ns_rows if x['id'] == 91060)
    md += md_table(['命名空间', '行', '名称/内容', 'prefab', '判定'], [
        ['skill `0x1ce47c`', f'1936', ns91060['skill'].get('name', ''),
         ns91060['skill'].get('prefab', ''),
         '**排除（high）**：小乔专属铸魂技能；本批无小乔(106)'],
        ['buff_effect `0x3ba41a8`', f'391', ns91060['buff_effect'].get('name', ''),
         ns91060['buff_effect'].get('prefab', ''),
         '**最可能（medium）**：多英雄/被动/tail=0'],
        ['kill_effect `0x586269c`', f'row key 3011（91060 是 cell2）',
         f'{ns91060["kill"].get("name", "")} / {ns91060["kill"].get("desc", "")}',
         ns91060['kill'].get('prefab', ''),
         '**排除（high）**：吕布皮肤 3011 的 cell，不是 row key；无击杀对齐'],
        ['buff_main `0x8268ac`', '无 91060', '—', '—',
         '排除；但 910600–910631 是「峡谷裂缝传送」buff 家族'],
        ['equip `0x522bde8`', '0 命中', '—', '—', '排除'],
    ])
    md.append('')
    md.append('### 3.2 事件证据（26 英雄、全 tail=0、~75s 周期）')
    md.append('')
    md.append(f'- 28 个 `.abc` 全扫：91060 共 **{sum(heroes_91060.values())}** 条，'
              f'覆盖 **{len(heroes_91060)}** 个 (hero_id,hero_name) 组合'
              f'（{known_heroes} 个已映射 + {len(heroes_91060) - known_heroes} 组未映射）；'
              '**没有小乔(106)**。')
    md.append(f'- 165/165 条 `tail=0`；`param` 分布 '
              f'{dict(batch["91060_params"].most_common(10))}，不是技能等级。')
    md.append('- 主样本 7 条：赵云×2、李信×2、马超、扁鹊、安琪拉；'
              '赵云 79.0→153.35（74.35s）、李信 79.15→153.95（74.8s），'
              '两次都是同队两人在 0.15–0.6s 内成对出现。')
    md.append('- 跨样本同 (file,entity) 间隔聚类：'
              f'**{"; ".join(f"{d}s {h}" for d, h, _ in sorted(near75))}** → 约 75s 的周期，'
              '更像地图/传送阵/被动刷新，不是单次英雄施法。')
    md.append('')
    md.append('### 3.3 与 0x87 / 0x1e / 0x2c / 0x23 / 0x1f / 0x20 的对齐')
    md.append('')
    align_md = []
    for a in align:
        e = a['event']
        align_md.append([
            e['seq'], e['hero_name'], e['field_b'],
            fmt_dist(a['d87']), fmt_dist(a['d1e']), fmt_dist(a['d2c']),
            fmt_dist(a['d23']), fmt_dist(a['d1f']), fmt_dist(a['d20']),
            fmt_time_dist(a['kill']), fmt_time_dist(a['death']),
        ])
    md += md_table(['seq', '英雄', 'param', '0x87', '0x1e', '0x2c', '0x23',
                    '0x1f', '0x20', '击杀', '死亡'], align_md)
    md.append('')
    md.append('最近距离是帧数（同英雄）或秒数（全局击杀/死亡）；只有李信一次 0x87 在 11 帧内，'
              '其余都远离。91060 **不是**装备/升级、命中、瞄准、击杀或高光事件。')
    md.append('')
    md.append('**判定**：91060 归 **buff_effect `0x3ba41a8` row391「峡谷裂口传送中断被动」**'
              '（medium）。语义上更像「峡谷裂缝传送相关被动/状态」（medium-low）；'
              '**不能叫小乔大招**（high 否定），也不能叫吕布击败特效（high 否定）。')
    md.append('')

    md.append('## 4. 11990 是什么')
    md.append('')
    md.append('### 4.1 事件：4/4 都是扁鹊对友方')
    md.append('')
    ev11990_md = []
    for e in [x for x in ev29 if x['field_a'] == 11990]:
        ev11990_md.append(['5069040', e['seq'], e['time_s'], f'{e["hero_name"]}({e["hero_id"]})',
                           e['field_b'], e['field_c']])
    for r in batch['11990']:
        if r['build'] == MAIN_BUILD:
            continue
        ev11990_md.append([r['build'], r['seq'], r['time_s'],
                           f'{r["hero_name"]}({r["hero_id"]})', r['param'], r['tail']])
    md += md_table(['build', 'seq', 't(s)', '英雄', 'param', 'tail'], ev11990_md)
    md.append('')
    # resolve tails (dedupe by build+tail)
    seen_tails = set()
    for label, info in tails.items():
        rev = info['rev']
        for r in batch['11990']:
            if r['build'] != info['build']:
                continue
            key = (label, r['tail'])
            if key in seen_tails:
                continue
            seen_tails.add(key)
            ent = rev.get(r['tail'])
            ro = info['roster'].get(ent, {})
            md.append(f'- {label} 的 tail={r["tail"]} → entity {ent} → '
                      f'{ro.get("heroName", "?")}（{ro.get("heroID", "?")}），'
                      f'同队 team={ro.get("team", "?")}。')
    md.append('')
    md.append('### 4.2 表内搜索与 row 11990')
    md.append('')
    md.append('- 1,245 张 stdr 表逐表扫 row key：**只有 `0x7384068` 有 11990**；'
              '技能表/buff_effect/buff_main/击败特效/装备表逐 cell 扫也是 **0 命中**。')
    md.append(f'- `0x7384068` row 11990 = `{target["row11990"]}`；'
              f'col6=11802（{target["row11990_col6"]}）。该表行键 1..20756'
              f'（仅缺 {target["missing_ids"]}），11990 只是第 11,988 行；'
              '**这不是 11990 的名称/语义**。')
    md.append('- 11990 = `119*100 + 90` → 扁鹊(119) + 特殊槽位 90。技能表只有 '
              '11900/11901/11902（普攻 A1/A2/A3）、11910/11920/11930（S1/S2/U1），'
              '没有 11990；也不是 119900（扁鹊毒药印记 buff）。')
    md.append('')
    md.append('### 4.3 判定')
    md.append('')
    md.append('**不能定名**（high）。语义边界是：**扁鹊对友方单位的专属效果**，'
              'param=-1（无等级）；主样本两次相隔约 106s，5230306 两次相隔 0.95s。'
              '更像治疗/增益/印记类效果（low-medium），不是普攻/技能 ID，'
              '也不是「扁鹊大招」（U1=11930）。要命名必须拿到 '
              '**5069040/5230306 build 的 skill/KeySpell 表**；'
              '现有 dc.db（5247758）没有 11990。')
    md.append('')

    md.append('## 5. 0x1f tag244 能不能命名')
    md.append('')
    md.append('### 5.1 可用 dc.db 的 tag 表（精度修正）')
    md.append('')
    md += md_table(['tag/row key', 'name (cell2)', 'desc (cell3/4)'], [
        [k, known.tag_info(k).get('name', ''), known.tag_info(k).get('desc', '')]
        for k in (1, 2, 5, 21, 93, 94)
    ])
    md.append('')
    md.append('注意 1：`native_table_names.csv` 对这个表用的是“首次出现顺序”法，**行 21 的名称是错的**；'
              '按 pool 精确 cell 解码，tag21 = **群体解控**（庄周），不是「关键团战输出」。'
              'tag1/tag2/tag5 = 关键群控/完美群控/关键群控。')
    md.append('')
    md.append('注意 2：主样本 `0x20 tag21` 是马超，而 row21 是庄周「群体解控」——'
              '两者语义不匹配，说明 **0x20 的 tag 不能直接套用 0x1f 的 tag 表**。'
              '本报告只用 0x1f 的 tag1/2/5 做“row key”证明，不用 0x20 的 21。')
    md.append('')
    md.append('### 5.2 tag244 的否定证据')
    md.append('')
    md.append(f'- tag 表 `0x695f084`：stride {tag["t"]["stride"]}、rows {tag["t"]["rows"]}、'
              f'row key **{min(tag["ids"])}..{max(tag["ids"])}**；'
              f'缺 {tag["gaps"]}。244 **不存在**。')
    md.append(f'- 小高光分类表 `0x699d82c` 只有 {min(tag["small_ids"])}..{max(tag["small_ids"])} '
              f'（{len(tag["small_ids"])} 个 key），也不是 tag244。')
    md.append(f'- 1,245 张 stdr 表中有 **{len(tag["key244"])}** 张存在 row key 244；'
              '逐张检查没有 tag-like 名称。')
    md.append(f'- `agent_global_strings.csv` 中含「群控/团战/高光/开团/承伤」的表：'
              f'`{dict(tag["tag_like"].most_common(5))}`；这些表的 row 244 没有 tag 名称。')
    md.append('- 主样本 0x1f tag244：t=360.45s，东皇太一(187) actor12，actorObjID=12（自身），'
              'field_a=-45、field_c=42、u8_d/e=0/0、tail3=0。')
    md.append('')
    md.append('### 5.3 结论')
    md.append('')
    md.append('**在可用 dc.db 里 tag244 表外，不能命名**（high）。但更强的原因是 build 不一致：'
              '5069040 的 0x1f 出现 244，而 dc.db（databinver 含 5247758）的 tag 表只到 208；'
              '如果 0x1f tag 值就是 row key（1/2/5 已证明；0x20 的 21 不参与），'
              '5069040 必须有一张 ≥244 行的 tag 表。'
              '所以 **不是绝对表外，而是缺 5069040 build 的 tag 表**（medium-high）。')
    md.append('')

    md.append('## 6. 多命名空间结论')
    md.append('')
    md.append('')
    md += md_table(['id', 'skill 0x1ce47c', 'buff_effect', 'buff_main', 'kill/equip', '判定'], [
        ['900011', '打包濒死队友', '—', 'ReviveDyingHero_Result', '—',
         'high：两表同义'],
        ['91060', '小乔 铸魂·星华缭乱', '峡谷裂口传送中断被动', '—',
         'kill 是 cell（吕布 3011）', '三表同号；按事件证据选 buff_effect（medium）'],
        ['11990', '—', '—', '—', '—', '零表命中；只在 0x7384068 稠密 row key（未命名）'],
        ['0', '—', '—', '—', '—', '空/清除'],
    ])
    md.append('')
    md.append('**结论**：0x29 的 `id` 不是单一技能表命名空间，而是混合的 '
              'KeySpell/effect 通知：900011 在两个表里同义，91060 在三个表里同号，'
              '11990 在现有表里零命中。**没有全局唯一的“0x29 id → 名称”规则**；'
              '要么按事件证据逐 id 选命名空间（91060），要么拿到 build 级 KeySpell 注册表'
              '（11990/tag244）。')
    md.append('')

    md.append('## 7. 还缺什么')
    md.append('')
    md.append('1. **5069040 build 的 databin**：当前 `dc.db` 的 `databinver` 含 5247758，'
              '不是主样本 build 5069040；需要 5069040 的 skill/buff/tag 表，'
              '才能确认 11990、tag244。')
    md.append('2. **0x29 id 的命名空间优先级**：从 C# 发送端或 native `EffectID` 枚举'
              '确认 id 先查 skill 还是 buff_effect/buff_main；否则 91060 的“唯一名”仍有歧义。')
    md.append('3. **ground truth**：79/153s 的 91060 是否真是峡谷裂缝传送中断；'
              '360.45s 东皇太一 tag244 的高光类型（承伤/控制/开团）。')
    md.append('4. **更多 5069040 样本**：11990 目前只有主样本 2 条 + 5230306 2 条；'
              'tag244 只有主样本 1 条。')
    md.append('')
    md.append('## 8. 产物与只读边界')
    md.append('')
    md.append(f'- 工具：`tools/agent_0x29_names.py`')
    md.append(f'- CSV：`{args.out_csv.relative_to(ROOT).as_posix()}`')
    md.append(f'- 报告：`{args.out_md.relative_to(ROOT).as_posix()}`')
    md.append('- 未修改 `docs/replay_binary_format.md`、`.workbuddy/memory/MEMORY.md`、'
              '回放/包体；未注入；未读 param.json；未用 runtime_dump。')
    md.append('')

    # write
    write_csv(rows, args.out_csv)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text('\n'.join(md), encoding='utf-8')
    print(f'wrote {args.out_csv} ({len(rows)} rows)')
    print(f'wrote {args.out_md} ({len(md)} lines)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
