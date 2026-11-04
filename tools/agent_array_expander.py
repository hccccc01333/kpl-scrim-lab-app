"""Expand C# databin fixed-buffer arrays (``*_bytes``) into readable CSVs.

Read-only reverse-engineering helper for docs/replay_binary_format.md 5.61-5.67.

What it does for each configured table
--------------------------------------
1. Reads the extracted block ``data/replays/_analysis/device/dtab_blocks/<idx>_<name>.bytes.bin``
   (0x98 stdr header + ``rows * stride`` bytes).
2. Loads the IL2CPP metadata field list of the matching ``ResData`` class and
   resolves every ``<field>_bytes`` fixed buffer through its compiler-generated
   nested type ``<<field>_bytes>e__FixedBuffer`` plus the
   ``System.Runtime.CompilerServices.FixedBufferAttribute(Type, int)`` custom
   attribute blob.  The attribute stores ``2 * element_count`` as a compressed
   integer (1 byte if < 0x80, otherwise ``0x80|hi`` + ``lo``).
3. Rebuilds the row layout: fields are serialized in declaration order with
   natural alignment; ``*_length`` fields are NOT serialized (they are runtime
   helpers); ``*_bytes`` occupies ``element_count * sizeof(element)`` bytes
   inline.  The computed struct size must equal ``stride`` (padding included),
   otherwise the table is reported as failed.
4. Locates the same table in ``dc.db`` and parses its local string pool, then
   resolves ``(tag, offset)`` string refs by first-use order.
5. Expands each array into flat rows:
   ``row_index, row_id, field, index, subfield, value``.
   Element width / member names come from the metadata when the fixed buffer
   element is a primitive (int/uint/ushort/byte/string); for byte buffers that
   the runtime reinterprets as structs the width is given by the verified spec
   below.

The tool never writes to replay files, never reads param.json and never uses
runtime dumps.

Verified rules (2026-11-01, this tool)
--------------------------------------
* ``*_length`` fields have NO serialized slot.  They are runtime helpers; the
  row is exactly the declaration-order layout without them.  Accepted for
  140 of the 185 tables in table_field_map.csv that carry ``_length``/``_bytes``
  (stride == computed size; 25 blocked by unresolved nested ``st*``, 20 mapping
  drift).  All nine expanded tables below satisfy it exactly.
* ``*_bytes`` is an inline fixed buffer, capacity comes from
  ``FixedBufferAttribute(typeof(T), N)``: bytes = N * sizeof(T).  The count
  therefore is NOT ``length x 8``; element widths observed are 2 (ushort),
  4 (int/uint), 8 (string ref / 2-int struct) and 12 (3-int struct).
* Concrete counts come from an explicit counter field when the table has one
  (iParamNum, bNum, bHeroNum/bStoryNum, dwNextNum/dwNum); otherwise the tool
  zero-terminates the buffer (last non-zero element + 1).
* String refs are ``(tag:u32, pool offset:u32)``; the local pool lives in the
  matching ``stdr`` table inside dc.db and is mapped in first-use order.

Outputs (data/replays/_analysis/datasets/agent_arrays/):
    <idx>_<name>.bytes.csv   expanded arrays per table
    _layouts.csv             field offsets / buffer capacities / element widths
    _summary.csv             per-table status, stride vs computed size, notes
    _model_check.csv         layout-rule check for all 185 array tables
"""
from __future__ import annotations

import csv
import glob
import os
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AN = ROOT / 'data' / 'replays' / '_analysis'
META = AN / 'global-metadata.dat'
BLOCKS = AN / 'device' / 'dtab_blocks'
DC_DB = AN / 'device' / 'dc.db'
OUT = AN / 'datasets' / 'agent_arrays'

# ---------------------------------------------------------------------------
# Metadata access
# ---------------------------------------------------------------------------

PRIMITIVE = {
    # typeIndex -> (kind, size)
    99432: ('string', 8),
    102472: ('uint32', 4),
    79278: ('int32', 4),
    79304: ('int32', 4),
    42911: ('byte', 1),
    102451: ('uint16', 2),
    102498: ('uint64', 8),
    98256: ('float32', 4),
}

RESDATA_NS = ('ResData', 'Assets.Scripts.GameSystem', 'CSProtocolWrapper')


class Metadata:
    def __init__(self, path: Path):
        self.blob = path.read_bytes()
        magic, version = struct.unpack_from('<Ii', self.blob, 0)
        assert magic == 0xFAB11BAF and version == 29, (hex(magic), version)
        p = lambda k: struct.unpack_from('<ii', self.blob, 8 + k * 8)
        self.str_off, self.str_size = p(2)
        m_off, m_size = p(5)
        self.fld_off, self.fld_size = p(11)
        nst_off, nst_size = p(15)
        typ_off, typ_size = p(19)
        self.ad_off, self.ad_size = p(24)
        ar_off, ar_size = p(25)
        self.blob_dir = self.blob[self.str_off:self.str_off + self.str_size]
        self.nst_off = nst_off
        self.types = []
        for i in range(typ_size // 88):
            v = struct.unpack_from('<16i8H2I', self.blob, typ_off + i * 88)
            self.types.append(dict(index=i, name=self.str(v[0]), ns=self.str(v[1]),
                                   first=v[8], count=v[18],
                                   nest_start=v[12], nest_count=v[20]))
        self.type_by_name = {}
        for t in self.types:
            self.type_by_name.setdefault((t['ns'], t['name']), t)
        self.methods = m_size // 32
        self.methods_off = m_off
        self.attr_range = {}
        for i in range(ar_size // 8):
            tok, start = struct.unpack_from('<II', self.blob, ar_off + i * 8)
            self.attr_range[tok] = start
        self.fixed_buffer_ctor = self._find_method(
            '.ctor', 'System.Runtime.CompilerServices.FixedBufferAttribute')

    def str(self, off: int) -> str:
        end = self.blob_dir.find(b'\x00', off)
        return self.blob_dir[off:end].decode('utf-8', 'replace')

    def _find_method(self, name: str, decl_name: str) -> int:
        decl = self.type_by_name.get(('System.Runtime.CompilerServices', decl_name))
        decl_idx = decl['index'] if decl else -1
        for i in range(self.methods):
            v = struct.unpack_from('<6i4H', self.blob, self.methods_off + i * 32)
            if self.str(v[0]) == name and v[1] == decl_idx:
                return i
        return -1

    def find_type(self, name: str) -> dict | None:
        for ns in RESDATA_NS:
            t = self.type_by_name.get((ns, name))
            if t:
                return t
        return None

    def fields(self, t: dict) -> list[tuple[str, int, int]]:
        out = []
        for k in range(t['count']):
            ni, ti, tok = struct.unpack_from('<2iI', self.blob, self.fld_off + (t['first'] + k) * 12)
            out.append((self.str(ni), ti, tok))
        return out

    def nested_types(self, t: dict) -> list[dict]:
        return [self.types[struct.unpack_from(
            '<I', self.blob, self.nst_off + (t['nest_start'] + k) * 4)[0]]
            for k in range(t['nest_count'])]

    def fixed_buffer(self, field_name: str, token: int, declaring: dict):
        """Return (element_count, element_kind, element_size) or None."""
        start = self.attr_range.get(token)
        if start is None:
            return None
        blob = self.blob[self.ad_off + start:self.ad_off + start + 32]
        if len(blob) < 15 or blob[0] != 1:
            return None
        if self.fixed_buffer_ctor >= 0 and struct.unpack_from('<I', blob, 1)[0] != self.fixed_buffer_ctor:
            return None
        # 01 <ctor:4> 02 00 00 ff c0 <elem type:3> 08 <len varint>
        b0 = blob[14]
        if b0 & 0x80:
            value = ((b0 & 0x7F) << 8) | blob[15]
        else:
            value = b0
        count = value // 2
        elem_kind, elem_size = 'byte', 1
        buf = next((n for n in self.nested_types(declaring)
                    if n['name'] == f'<{field_name}>e__FixedBuffer'), None)
        if buf is not None:
            for fn, fti, _tok in self.fields(buf):
                if fn == 'FixedElementField' and fti in PRIMITIVE:
                    elem_kind, elem_size = PRIMITIVE[fti]
                    break
        return count, elem_kind, elem_size


# ---------------------------------------------------------------------------
# Row layout
# ---------------------------------------------------------------------------

def field_kind(name: str):
    if name.endswith('_length'):
        return None
    if name.endswith('_bytes'):
        return ('array', 0, 1)
    if name.startswith('str') or name.startswith('sz'):
        return ('string', 8, 8)
    if name.startswith('ull'):
        return ('uint64', 8, 8)
    if name.startswith(('dw', 'i', 'f', 'n', 'u')):
        return ('int32', 4, 4)
    if name.startswith('w') and not name.startswith(('weapon', 'world')):
        return ('uint16', 2, 2)
    if name.startswith('b') or name.startswith('ch'):
        return ('byte', 1, 1)
    if name.startswith('st'):
        return ('struct', 0, 1)
    return ('int32', 4, 4)


class Layout:
    """Nested-callable sequential layout with fixed inline buffers."""

    def __init__(self, meta: Metadata, array_specs: dict, struct_sizes: dict | None = None):
        self.meta = meta
        self.specs = array_specs          # field name -> dict(width, members, count_field, ...)
        self.struct_sizes = struct_sizes or {}
        self.cache = {}

    def struct(self, cls: str, t: dict | None = None, depth: int = 0):
        if cls in self.cache:
            return self.cache[cls]
        t = t or self.meta.find_type(cls)
        if t is None:
            raise KeyError(f'type {cls} not found')
        if cls in self.struct_sizes:
            size, align = self.struct_sizes[cls]
            fields = {}
            self.cache[cls] = (size, align, fields)
            return self.cache[cls]
        off, align, fields = 0, 1, {}
        for name, _ti, tok in self.meta.fields(t):
            k = field_kind(name)
            if k is None:
                continue
            kind, size, a = k
            if kind == 'array':
                fb = self.meta.fixed_buffer(name, tok, t)
                if fb is None:
                    raise ValueError(f'{cls}.{name}: no FixedBufferAttribute')
                count, elem_kind, elem_size = fb
                size = count * elem_size
                a = 4 if elem_size == 1 else min(elem_size, 8)
                spec = self.specs.get(name, {})
                if spec.get('elem_width'):
                    width = spec['elem_width']
                else:
                    width = elem_size if elem_kind != 'byte' else 4
                fields[name] = dict(offset=None, size=size, kind='array',
                                    elem_kind=elem_kind, elem_size=elem_size,
                                    capacity_bytes=size,
                                    elem_width=width,
                                    count=count,
                                    count_field=spec.get('count_field'),
                                    members=spec.get('members') or ['value'],
                                    confidence=spec.get('confidence', 'high'),
                                    note=spec.get('note', ''))
                off = (off + a - 1) // a * a
                fields[name]['offset'] = off
                off += size
                align = max(align, a)
                continue
            if kind == 'struct':
                if name in self.struct_sizes:
                    size, a, sub = self.struct_sizes[name]
                else:
                    raise ValueError(f'{cls}.{name}: nested struct size unknown')
                off = (off + a - 1) // a * a
                fields[name] = dict(offset=off, size=size, kind='struct', align=a)
                off += size
                align = max(align, a)
                continue
            off = (off + a - 1) // a * a
            fields[name] = dict(offset=off, size=size, kind=kind)
            off += size
            align = max(align, a)
        size = (off + align - 1) // align * align
        self.cache[cls] = (size, align, fields)
        return self.cache[cls]


# ---------------------------------------------------------------------------
# dc.db local string pool
# ---------------------------------------------------------------------------

def load_block(pattern: str):
    files = glob.glob(str(BLOCKS / pattern))
    if not files:
        raise FileNotFoundError(pattern)
    path = Path(files[0])
    data = path.read_bytes()
    if data[:4] != b'stdr':
        raise ValueError(f'{path} is not a stdr block')
    stride = struct.unpack_from('<I', data, 0x14)[0]
    rows = struct.unpack_from('<I', data, 0x18)[0]
    if 0x98 + stride * rows != len(data):
        raise ValueError(f'{path}: block size mismatch')
    idx = int(path.name.split('_')[0])
    return path, data, stride, rows, idx


def find_dc_table(dc: bytes, stride: int, rows: int, head: bytes):
    pos = 0
    while True:
        p = dc.find(b'stdr', pos)
        if p < 0:
            return None
        pos = p + 1
        if p + 0x98 > len(dc):
            return None
        if struct.unpack_from('<I', dc, p + 0x14)[0] != stride:
            continue
        if struct.unpack_from('<I', dc, p + 0x18)[0] != rows:
            continue
        if dc[p + 0x98:p + 0x98 + 24] != head:
            continue
        return p
    return None


def parse_pool(dc: bytes, pool: int, limit: int = 200000):
    out, q = [], pool
    while len(out) < limit and q + 8 < len(dc):
        z = dc.find(b'\x00', q + 8, min(len(dc), q + 0x40000))
        if z < 0:
            break
        try:
            text = dc[q + 8:z].decode('utf-8')
        except UnicodeDecodeError:
            break
        out.append(text)
        q = (z + 1 + 3) & ~3
    return out


def string_ref_map(rows_data, stride, ref_slots, pool):
    """ref_slots: list of (offset, width) absolute row offsets; ordered per row."""
    refs, seen = [], set()
    for row in rows_data:
        for off, _w in ref_slots:
            if off + 8 > stride:
                continue
            hi, lo = struct.unpack_from('<II', row, off)
            if hi and lo and lo not in seen:
                seen.add(lo)
                refs.append(lo)
    return {ref: pool[i] for i, ref in enumerate(refs) if i < len(pool)}


# ---------------------------------------------------------------------------
# Per-table specs (verified against stride and row data)
# ---------------------------------------------------------------------------

TABLE_SPECS = [
    dict(block='*_TaskDyncValue.bytes.bin', cls='ResTaskDyncValue',
         note='int[5] buffer; count from iParamNum'),
    dict(block='*_Album.bytes.bin', cls='ResAlbum',
         note='uint[15] + uint[8]; counts from bHeroNum/bStoryNum',
         arrays={'HeroID_bytes': dict(count_field='bHeroNum'),
                 'StoryID_bytes': dict(count_field='bStoryNum')}),
    dict(block='*_ResPosFightValue2Grade.bytes.bin', cls='ResPosFightValue2Grade',
         note='3 x uint[5]'),
    dict(block='*_ResWealParam.bytes.bin', cls='ResWealParam',
         note='uint[5] NextId + int[15] Param; counts dwNextNum/dwNum',
         arrays={'NextId_bytes': dict(count_field='dwNextNum'),
                 'Param_bytes': dict(count_field='dwNum')}),
    dict(block='*_CommonSettle.bytes.bin', cls='ResCommonSettle',
         note='uint[5] AntiCheat + 3 byte[20] as int32 IDs',
         arrays={
             'astRandomRewardDetail_bytes': dict(elem_width=4, members=['dwRewardID'], confidence='medium'),
             'astFirstCompleteReward_bytes': dict(elem_width=4, members=['dwRewardID'], confidence='medium'),
             'astRaidsReward_bytes': dict(elem_width=4, members=['dwRewardID'], confidence='medium'),
         }),
    dict(block='*_CommReward.bytes.bin', cls='ResCommReward',
         note='byte[96] = 8 x {itemType,itemID,count}; count from bNum',
         arrays={'astReward_bytes': dict(elem_width=12, members=['dwItemType', 'dwItemID', 'dwCount'],
                                         count_field='bNum', confidence='high')}),
    dict(block='*_BattlePassRights.bytes.bin', cls='ResBattlePassRights',
         note='ushort[8] + byte[120] 12B struct + byte[32] 8B struct',
         arrays={'astAward_bytes': dict(elem_width=12, members=['dwItemType', 'dwItemID', 'dwCount'],
                                        confidence='medium'),
                 'astBuyLevelInfo_bytes': dict(elem_width=8, members=['dwLevel', 'dwValue'],
                                               confidence='medium')}),
    dict(block='*_YearStoryEventConfig.bytes.bin', cls='ResYearStoryEventConfig',
         note='byte[24]x2 (all-zero) + int[3] + byte[40] read as string[5]',
         arrays={'astStrParam_bytes': dict(elem_width=8, members=['strIdParam'],
                                           elem_kind_override='string', confidence='high')}),
    dict(block='*_NewbieGuideMainLineConf.bytes.bin', cls='NewbieGuideMainLineConf',
         note='byte[72]+byte[48]+byte[36]; element struct width ambiguous -> int32 fallback',
         arrays={k: dict(elem_width=4, members=['dwValue'], confidence='low')
                 for k in ('astTriggerTime_bytes', 'astTriggerCondition_bytes', 'astSkipCondition_bytes')}),
    # Attempted but not auto-solvable: nested st* structs have no size in metadata.
    dict(block='*_Trial.bytes.bin', cls='ResTrial', note='nested stReward'),
    dict(block='*_LuckyDrawPrice.bytes.bin', cls='ResLuckyDrawPrice', note='nested stDrawPoolInfo'),
    dict(block='*_WealStampInfo.bytes.bin', cls='ResWealStampInfo', note='nested stCommon/stFinalReward'),
    dict(block='*_ResNewHeroPracticeTargetInfo.bytes.bin', cls='ResNewHeroPracticeTargetInfo',
         note='nested stPerfectPassAward + ambiguous astTarget'),
]

INT_KINDS = {'int32': ('<i', 4), 'uint32': ('<I', 4), 'uint16': ('<H', 2),
             'uint64': ('<Q', 8), 'byte': ('<B', 1), 'float32': ('<f', 4)}


def expand_table(meta, spec, dc):
    path, data, stride, rows, idx = load_block(spec['block'])
    rows_data = [data[0x98 + i * stride:0x98 + (i + 1) * stride] for i in range(rows)]
    cls = spec['cls']
    t = meta.find_type(cls)
    if t is None:
        return None, dict(status='failed', reason=f'class {cls} not in metadata')
    lay = Layout(meta, spec.get('arrays', {}))
    try:
        size, align, fields = lay.struct(cls)
    except (KeyError, ValueError) as exc:
        return None, dict(status='failed', reason=str(exc))
    if size != stride:
        return None, dict(status='failed',
                          reason=f'layout {size} != stride {stride}')
    # string slots (fields + string arrays)
    slots = []
    for name, info in fields.items():
        if info['kind'] == 'string':
            slots.append((info['offset'], 8))
        elif info['kind'] == 'array' and info.get('elem_kind') == 'string':
            for k in range(info['capacity_bytes'] // 8):
                slots.append((info['offset'] + k * 8, 8))
        elif info['kind'] == 'array' and spec.get('arrays', {}).get(name, {}).get('elem_kind_override') == 'string':
            for k in range(info['capacity_bytes'] // 8):
                slots.append((info['offset'] + k * 8, 8))
    pool = []
    pos = find_dc_table(dc, stride, rows, data[0x98:0x98 + 24])
    if pos is not None:
        pool = parse_pool(dc, pos + struct.unpack_from('<I', dc, pos + 0x90)[0])
    refmap = string_ref_map(rows_data, stride, sorted(set(slots)), pool) if pool else {}

    # row id: first serialized 4-byte field when it is unique per row, otherwise
    # fall back to the physical row index (some tables are keyed by a packed byte).
    rid_off = None
    for name, info in fields.items():
        if info['kind'] in ('int32', 'uint32') and info['size'] == 4:
            rid_off = info['offset']
            break
    if rid_off is not None:
        keys = [struct.unpack_from('<I', row, rid_off)[0] for row in rows_data]
        if len(set(keys)) != len(keys):
            rid_off = None

    out_rows, layout_rows = [], []
    for name, info in fields.items():
        layout_rows.append(dict(table=path.name, cls=cls, field=name,
                                offset=info['offset'], size=info.get('capacity_bytes', info['size']),
                                kind=info['kind'], elem_kind=info.get('elem_kind', ''),
                                elem_width=info.get('elem_width', ''), count=info.get('count', ''),
                                confidence=info.get('confidence', ''),
                                note=info.get('note', '')))
    for ri, row in enumerate(rows_data):
        rid = struct.unpack_from('<I', row, rid_off)[0] if rid_off is not None else ri
        for name, info in fields.items():
            if info['kind'] != 'array':
                continue
            cap = info['capacity_bytes']
            width = info['elem_width']
            if width <= 0 or cap % width:
                continue
            ekind = spec.get('arrays', {}).get(name, {}).get('elem_kind_override') or info['elem_kind']
            members = info.get('members') or ['value']
            n_slots = cap // width
            count = n_slots
            cf = info.get('count_field')
            if cf and cf in fields:
                c_off = fields[cf]['offset']
                c_kind = fields[cf]['kind']
                if c_kind == 'byte':
                    count = row[c_off]
                elif c_kind == 'uint16':
                    count = struct.unpack_from('<H', row, c_off)[0]
                else:
                    count = struct.unpack_from('<I', row, c_off)[0]
            if count is None or count > n_slots:
                count = n_slots
            # zero-terminate when no explicit counter
            if not cf:
                last = -1
                for k in range(n_slots):
                    chunk = row[info['offset'] + k * width:
                                info['offset'] + (k + 1) * width]
                    if any(chunk):
                        last = k
                count = last + 1
            for k in range(max(0, count)):
                base = info['offset'] + k * width
                if ekind == 'string':
                    hi, lo = struct.unpack_from('<II', row, base)
                    val = refmap.get(lo)
                    if val is None:
                        val = '0x%08x:0x%08x' % (hi, lo) if (hi or lo) else ''
                    out_rows.append((ri, rid, name, k, 'strId', val))
                    continue
                if ekind in INT_KINDS and width == INT_KINDS[ekind][1] and len(members) == 1:
                    fmt, _ = INT_KINDS[ekind]
                    val = struct.unpack_from(fmt, row, base)[0]
                    out_rows.append((ri, rid, name, k, members[0], val))
                    continue
                # struct of 4-byte members
                for m, member in enumerate(members):
                    mo = base + m * 4
                    if mo + 4 > info['offset'] + cap:
                        break
                    val = struct.unpack_from('<i', row, mo)[0]
                    out_rows.append((ri, rid, name, k, member, val))
    return dict(block=path.name, idx=idx, cls=cls, stride=stride, rows=rows,
                size=size, fields=fields, rows_out=out_rows,
                layout_rows=layout_rows, pool=len(pool), refmap=len(refmap)), dict(status='ok')


def scan_model(meta):
    """Check the verified layout rule against every table with _length/_bytes.

    Writes ``_model_check.csv``: stride == computed size means the row layout
    (declaration order, natural alignment, no _length slot, fixed inline
    _bytes buffers) is reproduced exactly by metadata alone.
    """
    from collections import defaultdict
    map_path = AN / 'datasets' / 'table_field_map.csv'
    if not map_path.exists():
        return None
    by = defaultdict(dict)
    for r in csv.DictReader(map_path.open(encoding='utf-8-sig')):
        by[r['table']][r['field_name']] = r
    blocks = {}
    for mp in BLOCKS.glob('*.meta'):
        txt = mp.read_text(encoding='utf-8', errors='ignore')
        try:
            path = txt.split('path=')[1].split('\n')[0]
            idx = int(txt.split('index=')[1].split('\n')[0])
        except (IndexError, ValueError):
            continue
        blocks[path] = BLOCKS / f'{idx}_{Path(path).name}.bin'
    out = []
    for table, fields in by.items():
        if not any(n.endswith(('_length', '_bytes')) for n in fields):
            continue
        first = next(iter(fields.values()))
        stride = int(first['stride'])
        cls = first['type']
        blk = blocks.get(table)
        if blk is None:
            status, size, reason = 'no_block', '', 'block not extracted'
        elif meta.find_type(cls) is None:
            status, size, reason = 'no_class', '', f'{cls} not in metadata'
        else:
            try:
                size, _a, _f = Layout(meta, {}).struct(cls)
            except (KeyError, ValueError) as exc:
                status, size, reason = 'nested_or_attr', '', str(exc)
            else:
                status = 'fit' if size == stride else 'mismatch'
                reason = '' if status == 'fit' else 'extra field / mapping drift'
        out.append(dict(table=table, cls=cls, stride=stride, computed=size,
                        status=status, reason=reason))
    path = OUT / '_model_check.csv'
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['table', 'cls', 'stride', 'computed', 'status', 'reason'])
        w.writeheader()
        w.writerows(out)
    return out


def main():
    meta = Metadata(META)
    dc = DC_DB.read_bytes() if DC_DB.exists() else b''
    OUT.mkdir(parents=True, exist_ok=True)
    checked = scan_model(meta)
    if checked:
        from collections import Counter
        print('model check:', dict(Counter(r['status'] for r in checked)))
    summary, layouts = [], []
    ok = partial = fail = 0
    for spec in TABLE_SPECS:
        result, status = expand_table(meta, spec, dc)
        name = spec['block']
        if result is None:
            fail += 1
            summary.append(dict(table=name, cls=spec['cls'], status='failed',
                                stride='', computed='', rows='', arrays='', widths='',
                                reason=status['reason'], note=spec.get('note', '')))
            print(f'FAIL {name}: {status["reason"]}')
            continue
        arrays = [n for n, i in result['fields'].items() if i['kind'] == 'array']
        widths = ','.join(sorted({str(result['fields'][n]['elem_width']) for n in arrays}))
        confs = [result['fields'][n].get('confidence') for n in arrays]
        st = 'ok' if all(c == 'high' for c in confs) else 'partial'
        if st == 'ok':
            ok += 1
        else:
            partial += 1
        summary.append(dict(table=name, cls=result['cls'], status=st,
                            stride=result['stride'], computed=result['size'],
                            rows=result['rows'], arrays=';'.join(arrays), widths=widths,
                            reason='', note=spec.get('note', '')))
        layouts.extend(result['layout_rows'])
        out_path = OUT / f"{Path(result['block']).name.replace('.bin', '.csv')}"
        with out_path.open('w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['row_index', 'row_id', 'field', 'index', 'subfield', 'value'])
            w.writerows(result['rows_out'])
        print(f'{st.upper():7s} {name}: stride={result["stride"]} computed={result["size"]} '
              f'arrays={len(arrays)} rows_out={len(result["rows_out"])} -> {out_path.name}')
    with (OUT / '_summary.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['table', 'cls', 'status', 'stride', 'computed',
                                          'rows', 'arrays', 'widths', 'reason', 'note'])
        w.writeheader()
        w.writerows(summary)
    with (OUT / '_layouts.csv').open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(layouts[0].keys()) if layouts else
                           ['table', 'cls', 'field', 'offset', 'size', 'kind', 'elem_kind',
                            'elem_width', 'count', 'confidence', 'note'])
        w.writeheader()
        w.writerows(layouts)
    print(f'\ntables ok={ok} partial={partial} failed={fail} -> {OUT}')


if __name__ == '__main__':
    main()
