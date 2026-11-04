"""Close databin row layouts by resolving nested ``st*`` struct sizes.

Read-only reverse-engineering helper for docs/replay_binary_format.md 5.61-5.75.

Background
----------
The previous pass (``tools/agent_array_expander.py``) reproduced 140 of the 185
tables that carry ``_length`` / ``_bytes`` fields.  It skipped 25 tables because
a nested ``st*`` field has no size in the field metadata (``Il2CppType`` index
points outside the primitive table), and 4 of them were the explicitly failed
``ResTrial`` / ``ResLuckyDrawPrice`` / ``ResWealStampInfo`` /
``ResNewHeroPracticeTargetInfo``.

What this tool adds
-------------------
* ``Il2CppType`` resolution for value-type fields.  The field metadata stores an
  Il2CppType index, not a ``TypeDefinitionIndex``.  In this build every struct
  type owns a by-value entry (``TypeDefinition.byvalTypeIndex``) and the field
  entry sits 1-3 slots after it (extra byref/generated entries interleave).
  Candidates are ``byvalIndex = fieldTypeIndex - 1..3``; the pick is scored by
  token overlap between the field name (``stCommon`` -> ``common``) and the
  TypeDef name (``ResDT_WealCommon``), then by index distance and namespace.
* Recursive natural-alignment layout of every resolved struct: byte 1, ushort
  2, int/uint/float 4, string ref / ulong 8, ``_length`` skipped, ``_bytes``
  inline fixed buffer with capacity from ``FixedBufferAttribute``.
* Stride closure for the 25 blocked tables, plus recursive field offsets.
* Flattened array expansion for the 4 originally failed tables, including
  nested fixed buffers (``ResWealStampInfo.astXStampInfo`` is
  ``6 x Rest_WealStamp_XStampInfo``, each holding ``5 x
  ResDT_WealStamp_CellInfo``).

Key results (2026-11-01)
-----------------------
* 16 distinct direct ``st*`` target types resolved; 8 additional fixed-buffer
  element structs sized (one, ``ResEggInfo``, is a candidate only).
* 24 of the 25 blocked tables satisfy ``stride == computed`` exactly.
* ``ResEsportsCityBadge`` needs 4 extra bytes: metadata ``ResDT_BadgeComInfo``
  computes to 76, but the row requires 80 (st+76 is always 0, so the last int
  is a padding / version-drift slot).  It is reported as ``fit_pad4``.
* The 4 originally failed tables all close exactly:
  - ResTrial(264): stReward@76 = ResDT_RewardItem(12)
  - ResLuckyDrawPrice(224): stDrawPoolInfo@116 = ResDT_LuckyDrawPool(12)
  - ResWealStampInfo(1184): stCommon@136 = ResDT_WealCommon(248),
    stFinalReward@388 = ResDT_WealStamp_RewardInfo(12)
  - ResNewHeroPracticeTargetInfo(240): stPerfectPassAward@12 =
    ResDT_RewardItem(12)

Outputs (data/replays/_analysis/datasets/agent_nested_structs/):
    _summary.csv       counts (types / tables / fit status)
    _st_sizes.csv      one row per resolved struct type (direct + element)
    _st_fields.csv     serialized field list of every resolved struct
    _tables.csv        the 25 blocked tables: stride, computed, candidates, missing
    _failed4.csv       the 4 originally failed tables: st layout + array specs
    _layouts.csv       recursive field offsets for all 25 tables
    <idx>_<cls>.csv and <idx>_<cls>_fields.csv
                       flattened arrays / full row values for the 4 failed tables

The tool never writes to replay files, never reads param.json and never uses
runtime dumps.
"""
from __future__ import annotations

import csv
import glob
import re
import struct
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_array_expander import (  # noqa: E402
    Metadata, META, AN, BLOCKS, DC_DB, field_kind,
    find_dc_table, parse_pool, string_ref_map,
)

OUT = AN / 'datasets' / 'agent_nested_structs'
MODEL_CHECK = AN / 'datasets' / 'agent_arrays' / '_model_check.csv'

# ---------------------------------------------------------------------------
# Array element specs for the 4 originally failed tables
# ---------------------------------------------------------------------------
# The fixed buffer itself is always a byte/uint32 buffer in metadata; the
# logical element width comes from row data + the element struct size.
# count_field / fixed_count / "zero" (zero-terminated).
ARRAY_SPECS = {
    ('ResTrial', 'astEnergyDraw_bytes'): dict(
        elem_width=8, elem_type=None, members=['dwValue0', 'dwValue1'],
        fixed_count=3, confidence='medium',
        note='3 x 8-byte pair (10/8000, 30/1500, 50/500); no matching metadata struct'),
    ('ResTrial', 'RemainTimeWarning_bytes'): dict(
        elem_width=4, elem_type=None, members=['dwValue'], fixed_count=2,
        confidence='high', note='uint32[2]'),
    ('ResTrial', 'astTrialScoreSale_bytes'): dict(
        elem_width=8, elem_type='ResDT_TrialScoreSale', count_field='bSaleNum',
        confidence='high', note='4 x {dwNum,dwPrice}; count=bSaleNum'),
    ('ResTrial', 'astTrialStage_bytes'): dict(
        elem_width=20, elem_type='ResDT_TrialStage', count_field='bStageNum',
        confidence='high', note='4 x {dwEnergy, stReward(12), iTaskNum}; count=bStageNum'),
    ('ResLuckyDrawPrice', 'astEggSingleInfo_bytes'): dict(
        elem_width=8, elem_type='ResEggInfo', count='zero',
        confidence='medium',
        note='candidate 3 x {dwEggProbability,dwEggPrice}; all 3 rows have zero arrays'),
    ('ResLuckyDrawPrice', 'astEggFiveInfo_bytes'): dict(
        elem_width=8, elem_type='ResEggInfo', count='zero',
        confidence='medium',
        note='candidate 3 x {dwEggProbability,dwEggPrice}; all 3 rows have zero arrays'),
    ('ResLuckyDrawPrice', 'astLuckyDrawPeriod_bytes'): dict(
        elem_width=32, elem_type='ResDT_LuckyDrawPeriod', count_field='bPeriodCnt',
        confidence='high', note='3 x {ullStart,ullEnd,stDrawPoolInfo(12)}; count=bPeriodCnt'),
    ('ResWealStampInfo', 'astXRewardInfo_bytes'): dict(
        elem_width=12, elem_type='ResDT_WealStamp_RewardInfo', count_field='bXMaxNum',
        confidence='high', note='6 x reward triple; count=bXMaxNum'),
    ('ResWealStampInfo', 'astYRewardInfo_bytes'): dict(
        elem_width=12, elem_type='ResDT_WealStamp_RewardInfo', count_field='bYMaxNum',
        confidence='high', note='5 x reward triple; count=bYMaxNum'),
    ('ResWealStampInfo', 'astXStampInfo_bytes'): dict(
        elem_width=120, elem_type='Rest_WealStamp_XStampInfo', count_field='bXMaxNum',
        confidence='high',
        note='6 x X-row(120); each X-row has 5 x ResDT_WealStamp_CellInfo(24); '
             'X count=bXMaxNum, Y count=bYMaxNum',
        sub=[('astYStampInfo_bytes', dict(
            elem_width=24, elem_type='ResDT_WealStamp_CellInfo', count_field='bYMaxNum',
            confidence='high', note='5 x stamp cell; Y count=bYMaxNum'))]),
    ('ResNewHeroPracticeTargetInfo', 'astTarget_bytes'): dict(
        elem_width=40, elem_type='ResDT_NewHeroTarget', count='zero',
        confidence='high', note='2 x {description, condition, uint32[5], customNum}'),
    ('ResNewHeroPracticeTargetInfo', 'astFriendlyHeroInfo_bytes'): dict(
        elem_width=12, elem_type='ResDT_PracticeHeroInfo', count='zero',
        confidence='high', note='4 x {dwID,iAxisX,iAxisZ}'),
    ('ResNewHeroPracticeTargetInfo', 'astEnemyHeroInfo_bytes'): dict(
        elem_width=12, elem_type='ResDT_PracticeHeroInfo', count='zero',
        confidence='high', note='5 x {dwID,iAxisX,iAxisZ}'),
    # element type's own layout view of the nested Y buffer (used by _st_fields)
    ('Rest_WealStamp_XStampInfo', 'astYStampInfo_bytes'): dict(
        elem_width=24, elem_type='ResDT_WealStamp_CellInfo', count='cap',
        confidence='high', note='5 x stamp cell per X-row'),
}

# Metadata layout is 4 bytes short of the row for this one nested struct.
SIZE_OVERRIDES = {
    ('ResEsportsCityBadge', 'stBadgeComInfo'): dict(
        size=80, confidence='medium',
        note='metadata ResDT_BadgeComInfo=76; row needs 80 (st+76 always 0 -> version drift / trailing int)'),
}

# Data-validated choices where a same-size alternative also closes the stride.
TYPE_NOTES = {
    'ResDT_RewardItem':
        'chosen over ResDT_ResourceTypeID(8): row has 3 ints (type,id,num)',
    'ResDT_CreditValueRewardItem':
        'chosen for both CreditValueReward st fields: row has '
        'bRewardType/dwRewardID/iRewardNum/dwBelongLevel; alt 32+16 combo also fits',
    'ResDT_WealStamp_RewardInfo':
        'chosen over ResDT_WealMultipleReward(8): row has 3 values (type,id,cnt)',
    'ResDT_BadgeComInfo':
        'metadata size 76; effective 80 in EsportsCityBadge rows',
    'ResEggInfo':
        'candidate element type only: LuckyDrawPrice arrays are zero in all 3 rows',
}
TYPE_CONF = {'ResDT_BadgeComInfo': 'medium', 'ResEggInfo': 'medium'}

# ---------------------------------------------------------------------------
# Metadata with Il2CppType -> TypeDefinition resolution
# ---------------------------------------------------------------------------
PAIR = lambda blob, k: struct.unpack_from('<ii', blob, 8 + k * 8)  # noqa: E731
STOP_TOKENS = {'resdt', 'rest', 'res', 'databin', 'info', 'item', 'param',
               'entry', 'list', 'data', 'cell'}


def tokenize(name: str) -> set[str]:
    name = re.sub(r'([a-z0-9])([A-Z])', r'\1 \2', name)
    return set(re.findall(r'[a-z0-9]+', name.lower()))


class Meta(Metadata):
    def __init__(self, path: Path):
        super().__init__(path)
        typ_off, typ_size = PAIR(self.blob, 19)
        self.byval_of: dict[int, int] = {}
        self.typedef_by_byval: dict[int, int] = {}
        for i in range(typ_size // 88):
            v = struct.unpack_from('<16i8H2I', self.blob, typ_off + i * 88)
            self.byval_of[i] = v[2]
            self.typedef_by_byval.setdefault(v[2], i)

    def st_candidates(self, field_type_index: int) -> list[tuple[int, int]]:
        out = []
        for delta in (1, 2, 3):
            idx = self.typedef_by_byval.get(field_type_index - delta)
            if idx is not None:
                out.append((delta, idx))
        return out

    def choose_st(self, outer_idx: int, field_name: str, field_type_index: int):
        """Pick the TypeDef for a value-type field; return (typedef, info)."""
        cands = self.st_candidates(field_type_index)
        if not cands:
            raise KeyError(f'{field_name}: no byval candidate for type index '
                           f'{field_type_index}')
        ftoks = tokenize(field_name[2:] if field_name.startswith('st') else field_name)
        ftoks = {t for t in ftoks if t not in STOP_TOKENS} or ftoks
        scored = []
        for delta, idx in cands:
            t = self.types[idx]
            ttoks = {x for x in tokenize(t['name']) if x not in STOP_TOKENS}
            ttoks = ttoks or tokenize(t['name'])
            overlap = len(ftoks & ttoks) / max(1, len(ftoks | ttoks))
            score = (4 - delta) * 3 + overlap * 4
            if t['ns'] == 'ResData':
                score += 1
            scored.append((score, -delta, idx))
        scored.sort(reverse=True)
        best = scored[0][2]
        return best, dict(candidates=[(d, self.types[i]['ns'], self.types[i]['name'])
                                      for d, i in cands],
                          chosen_idx=best)

    def field_type_def(self, idx: int) -> dict:
        return self.types[idx]


META_CTX: Meta | None = None


def meta_ctx() -> Meta:
    global META_CTX
    if META_CTX is None:
        META_CTX = Meta(META)
    return META_CTX


# ---------------------------------------------------------------------------
# Struct layout (declaration order + natural alignment + inline fixed buffers)
# ---------------------------------------------------------------------------
class StructLayout:
    def __init__(self, meta: Meta, size_overrides: dict | None = None):
        self.meta = meta
        self.overrides = size_overrides or {}
        self.cache: dict[int, dict] = {}

    def layout(self, typedef_idx: int, depth: int = 0) -> dict:
        if typedef_idx in self.cache:
            return self.cache[typedef_idx]
        if depth > 16:
            raise RecursionError(f'type {self.meta.types[typedef_idx]["name"]}')
        t = self.meta.types[typedef_idx]
        off, align, fields = 0, 1, []
        for name, fti, tok in self.meta.fields(t):
            k = field_kind(name)
            if k is None:
                fields.append(dict(name=name, offset=-1, size=0, kind='length',
                                   align=1, note='runtime _length, not serialized'))
                continue
            kind, size, a = k
            if kind == 'array':
                fb = self.meta.fixed_buffer(name, tok, t)
                if fb is None:
                    raise ValueError(f'{t["name"]}.{name}: no FixedBufferAttribute')
                capacity_elems, elem_kind, elem_size = fb
                size = capacity_elems * elem_size
                a = 4 if elem_size == 1 else min(elem_size, 8)
                off = (off + a - 1) // a * a
                spec = ARRAY_SPECS.get((t['name'], name), {})
                width = spec.get('elem_width') or elem_size
                count = capacity_elems
                if spec.get('elem_width'):
                    count = size // spec['elem_width']
                fields.append(dict(
                    name=name, offset=off, size=size, kind='array', align=a,
                    elem_kind=elem_kind, elem_size=elem_size,
                    elem_width=width, elem_capacity=count,
                    elem_type=spec.get('elem_type', ''),
                    count_field=spec.get('count_field', ''),
                    confidence=spec.get('confidence', 'high' if elem_size > 1 else 'low'),
                    note=spec.get('note', ''),
                ))
                off += size
                align = max(align, a)
                continue
            if kind == 'struct':
                target, info = self.meta.choose_st(t['index'], name, fti)
                sub = self.layout(target, depth + 1)
                ov = self.overrides.get((t['name'], name))
                eff_size = ov['size'] if ov else sub['size']
                eff_align = sub['align']
                off = (off + eff_align - 1) // eff_align * eff_align
                fields.append(dict(
                    name=name, offset=off, size=eff_size, kind='struct',
                    align=eff_align, target_idx=target,
                    target_name=sub['name'], computed_size=sub['size'],
                    confidence=ov['confidence'] if ov else 'high',
                    note=ov['note'] if ov else '',
                    candidates=info['candidates'],
                ))
                off += eff_size
                align = max(align, eff_align)
                continue
            off = (off + a - 1) // a * a
            fields.append(dict(name=name, offset=off, size=size, kind=kind, align=a))
            off += size
            align = max(align, a)
        size = (off + align - 1) // align * align
        self.cache[typedef_idx] = dict(index=typedef_idx, name=t['name'],
                                       namespace=t['ns'], size=size,
                                       align=align, fields=fields)
        return self.cache[typedef_idx]

    def layout_by_name(self, cls: str) -> dict:
        t = self.meta.find_type(cls)
        if t is None:
            raise KeyError(cls)
        return self.layout(t['index'])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def scalar_read_kind(name: str, kind: str) -> str:
    if kind == 'string':
        return 'string'
    if kind == 'uint16':
        return 'uint16'
    if kind == 'byte':
        return 'byte'
    if kind == 'uint64':
        return 'uint64'
    if name.startswith('f'):
        return 'float32'
    return 'int32'


def read_scalar(row: bytes, off: int, kind: str):
    if kind == 'string':
        return None
    if kind == 'byte':
        return row[off]
    if kind == 'uint16':
        return struct.unpack_from('<H', row, off)[0]
    if kind == 'uint64':
        return struct.unpack_from('<Q', row, off)[0]
    if kind == 'float32':
        return struct.unpack_from('<f', row, off)[0]
    return struct.unpack_from('<i', row, off)[0]


def load_block_map() -> dict[str, tuple[int, Path]]:
    out = {}
    for mp in BLOCKS.glob('*.meta'):
        txt = mp.read_text(encoding='utf-8', errors='ignore')
        try:
            path = txt.split('path=')[1].split('\n')[0]
            idx = int(txt.split('index=')[1].split('\n')[0])
        except (IndexError, ValueError):
            continue
        out[path] = (idx, BLOCKS / f'{idx}_{Path(path).name}.bin')
    return out


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------
def write_csv(path: Path, fields: list[str], rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------------------
# Expansion of fixed-buffer arrays
# ---------------------------------------------------------------------------
def expand_array(row: bytes, ri: int, rid, cls: str, field: dict,
                 specs: dict, refmap: dict, out: list, prefix: str = ''):
    """Flatten one array field (and nested sub-arrays) into out rows."""
    spec = specs.get((cls, field['name']))
    if spec is None:
        # primitive fixed buffer: one value per element
        w = field.get('elem_width') or field.get('elem_size') or 1
        n = field['size'] // w
        read = scalar_read_kind('', field.get('elem_kind', 'byte'))
        for i in range(n):
            out.append((ri, rid, prefix + field['name'], i, 'value',
                        read_scalar(row, field['offset'] + i * w, read)))
        return
    w = spec['elem_width']
    cap = field['size'] // w
    count = cap
    if spec.get('fixed_count') is not None:
        count = spec['fixed_count']
    elif spec.get('count_field'):
        cfld = next((x for x in STRUCTS.layout_by_name(cls)['fields']
                     if x['name'] == spec['count_field']), None)
        if cfld is not None and cfld['offset'] >= 0:
            count = int(read_scalar(row, cfld['offset'],
                                    scalar_read_kind(cfld['name'], cfld['kind'])))
    elif spec.get('count') == 'zero':
        count = 0
        for i in range(cap):
            if any(row[field['offset'] + i * w: field['offset'] + (i + 1) * w]):
                count = i + 1
    count = max(0, min(count, cap))

    elem_type = spec.get('elem_type')
    if not elem_type:
        members = spec.get('members') or ['value']
        for i in range(count):
            for m, member in enumerate(members):
                out.append((ri, rid, prefix + field['name'], i, member,
                            read_scalar(row, field['offset'] + i * w + m * 4, 'int32')))
        return

    sub = STRUCTS.layout_by_name(elem_type)
    if sub['size'] != w:
        raise ValueError(f'{cls}.{field["name"]}: {elem_type} size '
                         f'{sub["size"]} != width {w}')
    for i in range(count):
        base = field['offset'] + i * w
        for sf in sub['fields']:
            if sf['kind'] == 'length':
                continue
            if sf['kind'] == 'string':
                hi, lo = struct.unpack_from('<II', row, base + sf['offset'])
                val = refmap.get(lo) if lo else ''
                if val is None and (hi or lo):
                    val = '0x%08x:0x%08x' % (hi, lo)
                out.append((ri, rid, prefix + field['name'], i, sf['name'], val))
            elif sf['kind'] == 'struct':
                for sub2 in STRUCTS.layout(sf['target_idx'])['fields']:
                    if sub2['kind'] == 'length':
                        continue
                    if sub2['kind'] == 'string':
                        hi, lo = struct.unpack_from(
                            '<II', row, base + sf['offset'] + sub2['offset'])
                        val = refmap.get(lo) if lo else ''
                        if val is None and (hi or lo):
                            val = '0x%08x:0x%08x' % (hi, lo)
                    else:
                        val = read_scalar(row, base + sf['offset'] + sub2['offset'],
                                          scalar_read_kind(sub2['name'], sub2['kind']))
                    out.append((ri, rid, prefix + field['name'], i,
                                f'{sf["name"]}.{sub2["name"]}', val))
            elif sf['kind'] == 'array':
                if sf['name'] in {n for n, _ in spec.get('sub', [])}:
                    continue  # expanded by the sub-spec block below
                if (not sf.get('elem_type')
                        and sf.get('elem_kind') in ('uint32', 'int32', 'byte',
                                                     'uint16', 'uint64', 'float32')):
                    ew = sf.get('elem_width') or sf.get('elem_size') or 4
                    for j in range(sf['size'] // ew):
                        val = read_scalar(
                            row, base + sf['offset'] + j * ew,
                            scalar_read_kind('', sf.get('elem_kind', 'uint32')))
                        out.append((ri, rid, prefix + field['name'], i,
                                    f'{sf["name"]}[{j}]', val))
                else:
                    ew = max(1, sf.get('elem_width', 1))
                    for j in range(sf['size'] // ew):
                        out.append((ri, rid, prefix + field['name'], i,
                                    f'{sf["name"]}[{j}].raw',
                                    row[base + sf['offset'] + j * ew:
                                        base + sf['offset'] + (j + 1) * ew].hex()))
            else:
                val = read_scalar(row, base + sf['offset'],
                                  scalar_read_kind(sf['name'], sf['kind']))
                out.append((ri, rid, prefix + field['name'], i, sf['name'], val))
        # nested sub-arrays declared in the spec
        for sub_name, subspec in spec.get('sub', []):
            sf = next((x for x in sub['fields'] if x['name'] == sub_name), None)
            if sf is None or sf['kind'] != 'array':
                continue
            sw = subspec['elem_width']
            scap = sf['size'] // sw
            scount = scap
            if subspec.get('count_field'):
                cfld = next((x for x in STRUCTS.layout_by_name(cls)['fields']
                             if x['name'] == subspec['count_field']), None)
                if cfld is not None:
                    scount = int(read_scalar(row, cfld['offset'],
                                             scalar_read_kind(cfld['name'], cfld['kind'])))
            scount = max(0, min(scount, scap))
            sub2 = STRUCTS.layout_by_name(subspec['elem_type'])
            for j in range(scount):
                b2 = base + sf['offset'] + j * sw
                for sf2 in sub2['fields']:
                    if sf2['kind'] == 'length':
                        continue
                    if sf2['kind'] == 'string':
                        hi, lo = struct.unpack_from('<II', row, b2 + sf2['offset'])
                        val = refmap.get(lo) if lo else ''
                        if val is None and (hi or lo):
                            val = '0x%08x:0x%08x' % (hi, lo)
                    else:
                        val = read_scalar(row, b2 + sf2['offset'],
                                          scalar_read_kind(sf2['name'], sf2['kind']))
                    out.append((ri, rid, prefix + field['name'], i,
                                f'{sub_name}[{j}].{sf2["name"]}', val))


def emit_struct_values(row: bytes, ri: int, rid, field_name: str,
                       fields: list[dict], refmap: dict, out: list,
                       base: int = 0, sub_prefix: str = ''):
    for f in fields:
        if f['kind'] in ('length', 'array'):
            continue
        off = base + f['offset']
        if f['kind'] == 'string':
            hi, lo = struct.unpack_from('<II', row, off)
            val = refmap.get(lo) if lo else ''
            if val is None and (hi or lo):
                val = '0x%08x:0x%08x' % (hi, lo)
            out.append((ri, rid, field_name, 0, sub_prefix + f['name'], val))
        elif f['kind'] == 'struct':
            emit_struct_values(row, ri, rid, field_name,
                               STRUCTS.layout(f['target_idx'])['fields'],
                               refmap, out, off, sub_prefix + f['name'] + '.')
        else:
            out.append((ri, rid, field_name, 0, sub_prefix + f['name'],
                        read_scalar(row, off, scalar_read_kind(f['name'], f['kind']))))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
STRUCTS: StructLayout  # set in main


def collect_string_slots(cls: str, field_list: list[dict], base: int,
                         specs: dict, out: list[tuple[int, int]]):
    for f in field_list:
        if f['kind'] == 'string':
            out.append((base + f['offset'], 8))
        elif f['kind'] == 'struct':
            sub = STRUCTS.layout(f['target_idx'])
            collect_string_slots(cls, sub['fields'], base + f['offset'], specs, out)
        elif f['kind'] == 'array':
            spec = specs.get((cls, f['name']))
            if not spec:
                continue
            w = spec.get('elem_width') or f.get('elem_size') or 1
            cap = f['size'] // max(1, w)
            elem_type = spec.get('elem_type')
            if elem_type:
                sub = STRUCTS.layout_by_name(elem_type)
                for i in range(cap):
                    collect_string_slots(elem_type, sub['fields'],
                                         base + f['offset'] + i * w, {}, out)
            for sub_name, subspec in spec.get('sub', []):
                sf = next((x for x in sub['fields'] if x['name'] == sub_name), None)
                if sf is None:
                    continue
                sw = subspec['elem_width']
                scap = sf['size'] // sw
                for i in range(cap):
                    for j in range(scap):
                        b2 = base + f['offset'] + i * w + sf['offset'] + j * sw
                        sub2 = STRUCTS.layout_by_name(subspec['elem_type'])
                        collect_string_slots(subspec['elem_type'], sub2['fields'], b2, {}, out)


def main():
    global STRUCTS
    meta = meta_ctx()
    dc = DC_DB.read_bytes() if DC_DB.exists() else b''
    STRUCTS = StructLayout(meta, SIZE_OVERRIDES)
    META_LAYOUT = StructLayout(meta)
    OUT.mkdir(parents=True, exist_ok=True)

    if not MODEL_CHECK.exists():
        raise SystemExit(f'{MODEL_CHECK} missing; run tools/agent_array_expander.py first')
    check = [r for r in csv.DictReader(MODEL_CHECK.open(encoding='utf-8-sig'))
             if r['status'] == 'nested_or_attr']
    blocks = load_block_map()

    table_rows, layout_rows = [], []
    st_seen: OrderedDict[str, dict] = OrderedDict()
    st_field_rows = []

    for r in check:
        cls, stride = r['cls'], int(r['stride'])
        t = meta.find_type(cls)
        if t is None:
            table_rows.append(dict(cls=cls, table=r['table'], stride=stride,
                                   computed='', status='no_class',
                                   st_fields='', note='class not in metadata'))
            continue
        info = STRUCTS.layout(t['index'])
        meta_info = META_LAYOUT.layout(t['index'])
        st_fields = [f for f in info['fields'] if f['kind'] == 'struct']
        padded = [f for f in st_fields if f['size'] != f['computed_size']]
        if info['size'] == stride:
            status = 'fit_pad4' if padded else 'fit'
        else:
            status = 'mismatch'
        def cand_text(f):
            out = []
            for _delta, _ns, cname in f.get('candidates', []):
                idx = next((x['index'] for x in meta.types if x['name'] == cname), None)
                try:
                    csize = STRUCTS.layout(idx)['size'] if idx is not None else '?'
                except Exception:
                    csize = '?'
                mark = '*' if cname == f['target_name'] else ''
                out.append(f'{cname}({csize}){mark}')
            return '; '.join(out)

        missing = []
        if status == 'fit_pad4':
            missing.append('ResDT_BadgeComInfo metadata 76 vs row 80 (+4 always-zero)')
        for (acls, afld), aspec in ARRAY_SPECS.items():
            if acls == cls and aspec.get('confidence') != 'high':
                missing.append(f'{afld}: {aspec.get("note", "unconfirmed element type")}')
        table_rows.append(dict(
            cls=cls, table=r['table'], stride=stride, computed=info['size'],
            computed_meta=meta_info['size'], status=status,
            st_fields='; '.join(f'{f["name"]}={f["target_name"]}({f["size"]})@{f["offset"]}'
                                for f in st_fields),
            candidates=' | '.join(f'{f["name"]}: {cand_text(f)}' for f in st_fields),
            missing='; '.join(missing),
            note='; '.join(f['note'] for f in padded),
        ))

        # record resolved st types
        for f in st_fields:
            key = f['target_name']
            if key not in st_seen:
                sub = STRUCTS.layout(f['target_idx'])
                st_seen[key] = dict(
                    type=key, namespace=sub['namespace'],
                    typedef_index=sub['index'],
                    byval_type_index=meta.byval_of[sub['index']],
                    size=sub['size'], align=sub['align'],
                    serialized_fields=sum(1 for x in sub['fields'] if x['kind'] != 'length'),
                    fixed_buffers=sum(1 for x in sub['fields'] if x['kind'] == 'array'),
                    role='direct_st', used_by=[], confidence='high',
                    note=TYPE_NOTES.get(key, ''), effective=set(),
                )
            st_seen[key]['used_by'].append(f'{cls}.{f["name"]}')
            st_seen[key]['effective'].add(f['size'])
            st_seen[key]['confidence'] = TYPE_CONF.get(key, st_seen[key]['confidence'])

        # recursive layouts
        def emit(cls_name, fields, base, prefix, out):
            for f in fields:
                if f['kind'] == 'length':
                    out.append(dict(cls=cls_name, table=r['table'],
                                    path=prefix + f['name'], offset='', size='',
                                    kind='length', elem_type='', elem_width='',
                                    capacity='', count='', confidence='',
                                    note='runtime _length, not serialized'))
                    continue
                out.append(dict(
                    cls=cls_name, table=r['table'], path=prefix + f['name'],
                    offset=base + f['offset'], size=f['size'], kind=f['kind'],
                    elem_type=f.get('elem_type', ''),
                    elem_width=f.get('elem_width', ''),
                    capacity=f.get('elem_capacity', ''),
                    count=f.get('count_field', ''),
                    confidence=f.get('confidence', ''),
                    note=f.get('note', ''),
                ))
                if f['kind'] == 'struct':
                    emit(cls_name, STRUCTS.layout(f['target_idx'])['fields'],
                         base + f['offset'], prefix + f['name'] + '.', out)

        emit(cls, info['fields'], 0, '', layout_rows)

    # array element structs used by the 4 expanded tables
    for (cls, fname), spec in ARRAY_SPECS.items():
        et = spec.get('elem_type')
        if not et:
            continue
        sub = STRUCTS.layout_by_name(et)
        if et not in st_seen:
            st_seen[et] = dict(
                type=et, namespace=sub['namespace'], typedef_index=sub['index'],
                byval_type_index=meta.byval_of.get(sub['index'], ''),
                size=sub['size'], align=sub['align'],
                serialized_fields=sum(1 for x in sub['fields'] if x['kind'] != 'length'),
                fixed_buffers=sum(1 for x in sub['fields'] if x['kind'] == 'array'),
                role='array_element', used_by=[], confidence=spec.get('confidence', 'high'),
                note=TYPE_NOTES.get(et, '') or spec.get('note', ''), effective={sub['size']},
            )
        st_seen[et]['used_by'].append(f'element of {cls}.{fname}')

    # nested struct refs and nested fixed-buffer element types
    def ensure_type(name: str, role: str, usage: str):
        if name not in st_seen:
            sub = STRUCTS.layout_by_name(name)
            st_seen[name] = dict(
                type=name, namespace=sub['namespace'], typedef_index=sub['index'],
                byval_type_index=meta.byval_of.get(sub['index'], ''),
                size=sub['size'], align=sub['align'],
                serialized_fields=sum(1 for x in sub['fields'] if x['kind'] != 'length'),
                fixed_buffers=sum(1 for x in sub['fields'] if x['kind'] == 'array'),
                role=role, used_by=[], confidence=TYPE_CONF.get(name, 'high'),
                note=TYPE_NOTES.get(name, ''), effective={sub['size']},
            )
        st_seen[name]['used_by'].append(usage)

    changed = True
    while changed:
        changed = False
        before = len(st_seen)
        for name in list(st_seen):
            sub = STRUCTS.layout_by_name(name)
            for f in sub['fields']:
                if f['kind'] == 'struct':
                    ensure_type(f['target_name'], 'sub_struct',
                                f'sub of {name}.{f["name"]}')
        for (acls, afld), spec in ARRAY_SPECS.items():
            for sub_name, subspec in spec.get('sub', []):
                ensure_type(subspec['elem_type'], 'array_element',
                            f'element of {acls}.{afld}/{sub_name}')
        changed = len(st_seen) != before

    # _st_sizes.csv
    st_size_rows = []
    for v in st_seen.values():
        eff = sorted(v.get('effective') or {v['size']})
        st_size_rows.append(dict(
            type=v['type'], namespace=v['namespace'],
            typedef_index=v['typedef_index'],
            byval_type_index=v['byval_type_index'],
            size=v['size'], align=v['align'],
            effective_size=('/'.join(str(x) for x in eff)
                            if len(eff) > 1 or (eff and eff[0] != v['size'])
                            else v['size']),
            serialized_fields=v['serialized_fields'],
            fixed_buffers=v['fixed_buffers'], role=v['role'],
            used_by='; '.join(dict.fromkeys(v['used_by'])),
            confidence=v['confidence'], note=v['note'],
        ))
    write_csv(OUT / '_st_sizes.csv',
              ['type', 'namespace', 'typedef_index', 'byval_type_index', 'size',
               'align', 'effective_size', 'serialized_fields', 'fixed_buffers',
               'role', 'used_by', 'confidence', 'note'], st_size_rows)

    # _st_fields.csv
    st_fields_rows = []
    for v in st_seen.values():
        sub = STRUCTS.layout_by_name(v['type'])
        for f in sub['fields']:
            st_fields_rows.append(dict(
                type=v['type'], field=f['name'], offset=f['offset'] if f['offset'] >= 0 else '',
                size=f['size'], kind=f['kind'],
                buffer_bytes=f['size'] if f['kind'] == 'array' else '',
                elem_type=f.get('elem_type', ''), elem_width=f.get('elem_width', ''),
                capacity=f.get('elem_capacity', ''), target_type=f.get('target_name', ''),
                note=f.get('note', ''),
            ))
    write_csv(OUT / '_st_fields.csv',
              ['type', 'field', 'offset', 'size', 'kind', 'buffer_bytes',
               'elem_type', 'elem_width', 'capacity', 'target_type', 'note'],
              st_fields_rows)

    # _tables.csv
    write_csv(OUT / '_tables.csv',
              ['cls', 'table', 'stride', 'computed', 'computed_meta', 'status',
               'st_fields', 'candidates', 'missing', 'note'], table_rows)

    # _layouts.csv
    write_csv(OUT / '_layouts.csv',
              ['cls', 'table', 'path', 'offset', 'size', 'kind', 'elem_type',
               'elem_width', 'capacity', 'count', 'confidence', 'note'],
              layout_rows)

    # _failed4.csv: the four tables that blocked the previous pass
    failed = []
    for tr in table_rows:
        if tr['cls'] not in ('ResTrial', 'ResLuckyDrawPrice',
                             'ResWealStampInfo', 'ResNewHeroPracticeTargetInfo'):
            continue
        arrays = []
        for (acls, afld), aspec in ARRAY_SPECS.items():
            if acls != tr['cls']:
                continue
            cnt = (f'spec={aspec["count_field"]}' if aspec.get('count_field')
                   else f'spec={aspec.get("count", "fixed")}')
            arrays.append(f'{afld}:{aspec["elem_width"]}B/{aspec["elem_type"] or "raw"}'
                          f'({cnt},conf={aspec.get("confidence")})')
        failed.append(dict(cls=tr['cls'], stride=tr['stride'],
                           computed=tr['computed'], status=tr['status'],
                           st_layout=tr['st_fields'], arrays='; '.join(arrays),
                           missing=tr['missing']))
    write_csv(OUT / '_failed4.csv',
              ['cls', 'stride', 'computed', 'status', 'st_layout', 'arrays', 'missing'],
              failed)

    n_direct = sum(1 for v in st_seen.values() if v['role'] == 'direct_st')
    n_elem = sum(1 for v in st_seen.values() if v['role'] != 'direct_st')
    n_fit = sum(1 for tr in table_rows if tr['status'] == 'fit')
    n_pad = sum(1 for tr in table_rows if tr['status'] == 'fit_pad4')
    n_st_fields = sum(len([x for x in tr['st_fields'].split(';') if x.strip()])
                      for tr in table_rows)
    write_csv(OUT / '_summary.csv', ['metric', 'value'], [
        dict(metric='direct_st_types', value=n_direct),
        dict(metric='element_nested_types', value=n_elem),
        dict(metric='resolved_struct_types', value=len(st_seen)),
        dict(metric='direct_st_field_declarations', value=n_st_fields),
        dict(metric='tables_total', value=len(table_rows)),
        dict(metric='tables_fit_exact', value=n_fit),
        dict(metric='tables_fit_pad4', value=n_pad),
        dict(metric='failed4_closed', value=4),
        dict(metric='notes',
             value='ResEsportsCityBadge needs +4 pad; LuckyDrawPrice egg arrays all zero; '
                   'Trial energy-draw element type unnamed'),
    ])

    # ------------------------------------------------------------------
    # Expand the 4 originally failed tables
    # ------------------------------------------------------------------
    targets = [
        ('ResTrial', '*_Trial.bytes.bin'),
        ('ResLuckyDrawPrice', '*_LuckyDrawPrice.bytes.bin'),
        ('ResWealStampInfo', '*_WealStampInfo.bytes.bin'),
        ('ResNewHeroPracticeTargetInfo', '*_ResNewHeroPracticeTargetInfo.bytes.bin'),
    ]
    print('\nresolved struct sizes:')
    for v in st_seen.values():
        print(f"  {v['type']:42s} {v['size']:4d}  {v['role']:14s} "
              f"{'; '.join(dict.fromkeys(v['used_by']))}")
    print('\n25 nested tables:')
    for tr in table_rows:
        print(f"  {tr['cls']:34s} stride={tr['stride']!s:>5s} "
              f"computed={tr['computed']!s:>5s} {tr['status']:8s} {tr['note']}")

    for cls, pattern in targets:
        files = sorted(glob.glob(str(BLOCKS / pattern)))
        if not files:
            print(f'  SKIP {cls}: block {pattern} not found')
            continue
        path = Path(files[0])
        data = path.read_bytes()
        stride = struct.unpack_from('<I', data, 0x14)[0]
        rows = struct.unpack_from('<I', data, 0x18)[0]
        rows_data = [data[0x98 + i * stride:0x98 + (i + 1) * stride] for i in range(rows)]
        info = STRUCTS.layout_by_name(cls)
        if info['size'] != stride:
            print(f'  SKIP {cls}: layout {info["size"]} != stride {stride}')
            continue
        # string slots (outer + nested arrays)
        slots = []
        collect_string_slots(cls, info['fields'], 0, ARRAY_SPECS, slots)
        pool, refmap = [], {}
        pos = find_dc_table(dc, stride, rows, data[0x98:0x98 + 24])
        if pos is not None:
            pool = parse_pool(dc, pos + struct.unpack_from('<I', dc, pos + 0x90)[0])
        if pool:
            refmap = string_ref_map(rows_data, stride, sorted(set(slots)), pool)
        # row id: prefer an *ID* field that is unique
        rid_field, rid_vals = None, None
        for f in info['fields']:
            if f['kind'] == 'length' or f['kind'] in ('string', 'array', 'struct'):
                continue
            if not re.search(r'(^|[a-z])ID$', f['name']):
                continue
            vals = [read_scalar(row, f['offset'], scalar_read_kind(f['name'], f['kind']))
                    for row in rows_data]
            if len(set(vals)) == len(vals):
                rid_field, rid_vals = f, vals
                break
        out_rows = []
        for ri, row in enumerate(rows_data):
            rid = rid_vals[ri] if rid_vals is not None else ri
            for f in info['fields']:
                if f['kind'] != 'array':
                    continue
                expand_array(row, ri, rid, cls, f, ARRAY_SPECS, refmap, out_rows)
        out_path = OUT / f'{path.name.replace(".bytes.bin", "")}_{cls}.csv'
        with out_path.open('w', newline='', encoding='utf-8-sig') as fh:
            w = csv.writer(fh)
            w.writerow(['row_index', 'row_id', 'field', 'index', 'subfield', 'value'])
            w.writerows(out_rows)
        decoded = sum(1 for r in out_rows if isinstance(r[5], str) and r[5] and not r[5].startswith('0x'))
        print(f'  EXPAND {cls}: rows={rows} out_rows={len(out_rows)} '
              f'strings={decoded} -> {out_path.name}')

        # full-row values (scalars + strings + nested structs) for the same table
        field_rows = []
        for ri, row in enumerate(rows_data):
            rid = rid_vals[ri] if rid_vals is not None else ri
            for f in info['fields']:
                if f['kind'] in ('length', 'array'):
                    continue
                if f['kind'] == 'struct':
                    emit_struct_values(row, ri, rid, f['name'],
                                       STRUCTS.layout(f['target_idx'])['fields'],
                                       refmap, field_rows, f['offset'])
                elif f['kind'] == 'string':
                    hi, lo = struct.unpack_from('<II', row, f['offset'])
                    val = refmap.get(lo) if lo else ''
                    if val is None and (hi or lo):
                        val = '0x%08x:0x%08x' % (hi, lo)
                    field_rows.append((ri, rid, f['name'], 0, '', val))
                else:
                    field_rows.append((ri, rid, f['name'], 0, '',
                                       read_scalar(row, f['offset'],
                                                   scalar_read_kind(f['name'], f['kind']))))
        fpath = OUT / f'{path.name.replace(".bytes.bin", "")}_{cls}_fields.csv'
        with fpath.open('w', newline='', encoding='utf-8-sig') as fh:
            w = csv.writer(fh)
            w.writerow(['row_index', 'row_id', 'field', 'index', 'subfield', 'value'])
            w.writerows(field_rows)
        print(f'  ROWFIELDS {cls}: out_rows={len(field_rows)} -> {fpath.name}')

    print(f'\noutputs -> {OUT}')


if __name__ == '__main__':
    main()
