"""Resolve C# table string refs in dc.db (read-only, no game process).

Encoding (derived and verified on every string table in dc.db)
--------------------------------------------------------------
A C# table serialized as ``stdr`` (stride/rows/pool) stores string cells as
two u32 values::

    cell = (hash32, value32)

    hash32   per-table string-pool namespace id.  It is constant for every
             string field of one table and unique across the 919 string
             tables in dc.db.  It does NOT change per row/field/string.
    value32  byte offset of the string record inside the original table
             asset, shifted left by 6 bits (low 6 bits are reserved/flag
             bits and are zero in this build)::

                 file_offset = value32 >> 6
                 local_offset = file_offset - pool_rel
                 pool_rel = u32(header + 0x90)

Table layout::

    +0x00  "stdr"
    +0x08  string count (u32)
    +0x14  stride       (u32)
    +0x18  row count    (u32)
    +0x90  pool offset relative to table start (u32)
    +0x98  rows: nrows * stride
           string pool starts exactly at 0x98 + nrows*stride (== +0x90)
    pool record: hash64 | UTF-8 bytes | NUL | pad to 4 bytes

Consequences
------------
* offset32 is NOT an offset into one global pool inside dc.db.  It is a
  file-relative offset into the table's own source asset.  Dividing by 64
  and subtracting the *absolute* pool address in dc.db goes negative; the
  correct base is the *relative* pool offset from header +0x90.
* The pair (hash32, value32) is globally unique because the hash is unique
  per table.  A global string map is therefore a list of per-table pools
  keyed by that hash -- there is no single shared string blob to find.
* Resolution is positional, so it also works for tables whose local pool
  contains unreferenced strings (unlike the 5.64 first-use-order method).
  For the skill table both methods agree: 13,298/13,298 distinct refs.

Verified results (this dc.db):
* 1,245 stdr tables, 326 have no string pool (nstr == 0).
* 919 string tables; dominant string hash fully resolves with exact
  position matches: 783,075 / 783,075 ref occurrences (100%).
* 300 tables have distinct-ref count == declared string count; for all
  300 the first ref equals pool_rel << 6.
* All 919 hashes are unique; no two tables share a string namespace.

Output (data/replays/_analysis/datasets/agent_global_strings.csv):
    table,row,ref,text,confidence

    table       table start in dc.db, e.g. 0x1ce47c
    row         0-based row index of the first occurrence (distinct mode)
                or of this occurrence (--all-occurrences)
    ref         0x<hash32>:0x<value32>
    text        decoded UTF-8 string (empty when unresolved)
    confidence  exact | order | raw

Usage:
    python tools/agent_global_strings.py
    python tools/agent_global_strings.py --table 0x1ce47c
    python tools/agent_global_strings.py --all-occurrences
    python tools/agent_global_strings.py --out path/to/other.csv
"""
from __future__ import annotations

import argparse
import csv
import struct
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "replays" / "_analysis" / "device" / "dc.db"
DEFAULT_OUT = (
    ROOT / "data" / "replays" / "_analysis" / "datasets" / "agent_global_strings.csv"
)
SKILL_TABLE = 0x1CE47C
SKILL_ROW_IDS = (1936, 2527)


def u32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


def u32pair(data: bytes, off: int) -> tuple[int, int]:
    return struct.unpack_from("<II", data, off)


def is_float_bits(value: int) -> bool:
    """True for the common 0.5..100.0 float bit patterns seen in int cells."""
    return 0x3F000000 <= value <= 0x42C80000 or 0xBF000000 <= value <= 0xC2C80000


def parse_pool(data: bytes, pool: int, nstr: int) -> dict[int, str]:
    """Parse pool records: hash64 + UTF-8 + NUL + 4-byte padding.

    Returns local record offset -> text.
    """
    out: dict[int, str] = {}
    q = 0
    for _ in range(nstr):
        start = pool + q
        if start + 8 >= len(data):
            break
        z = data.find(b"\x00", start + 8)
        if z < 0:
            break
        out[q] = data[start + 8:z].decode("utf-8", "replace")
        q = ((z + 1 + 3) & ~3) - pool
        if q <= 0:
            break
    return out


class Table:
    __slots__ = (
        "pos", "nstr", "stride", "nrows", "pool_rel", "base", "ncell", "strings",
    )

    def __init__(self, data: bytes, pos: int) -> None:
        self.pos = pos
        self.nstr = u32(data, pos + 0x08)
        self.stride = u32(data, pos + 0x14)
        self.nrows = u32(data, pos + 0x18)
        self.pool_rel = u32(data, pos + 0x90)
        self.base = pos + 0x98
        self.ncell = (self.stride - 8) // 8 if self.stride >= 8 else 0
        self.strings: dict[int, str] = {}

    def valid(self, size: int) -> bool:
        if not (8 <= self.stride <= 65536 and self.stride % 8 == 0):
            return False
        if not (1 <= self.nrows <= 2_000_000):
            return False
        if not (0 <= self.nstr <= 4_000_000):
            return False
        end = self.base + self.stride * self.nrows
        pool = self.pos + self.pool_rel
        return (
            end <= size
            and pool <= size
            and end == pool  # verified layout; allows reading the pool safely
        )


def iter_tables(data: bytes) -> list[Table]:
    tables: list[Table] = []
    search = 0
    while True:
        pos = data.find(b"stdr", search)
        if pos < 0:
            break
        table = Table(data, pos)
        if table.valid(len(data)):
            tables.append(table)
        search = pos + 1
    return tables


def detect_ref_hash(
    data: bytes, table: Table
) -> tuple[int | None, Counter, dict[int, set[int]]]:
    """Pick the string-pool namespace hash by exact position matches.

    A candidate (a, b) is accepted when b is a multiple of 64 and
    (b >> 6) - pool_rel is exactly a pool record start.  The true hash
    resolves many distinct records; integer params may collide once or twice
    but never dominate.
    """
    pool_rel = table.pool_rel
    strings = table.strings
    counts: Counter = Counter()
    distinct: dict[int, set[int]] = {}
    for r in range(table.nrows):
        row = table.base + r * table.stride
        for i in range(table.ncell):
            a, b = u32pair(data, row + 8 + i * 8)
            if not a or not b or b % 64:
                continue
            local = (b >> 6) - pool_rel
            if local in strings:
                counts[a] += 1
                distinct.setdefault(a, set()).add(local)
    if not counts:
        return None, counts, distinct

    def score(a: int) -> tuple[int, int, int]:
        # distinct coverage first, then plausibility of a namespace id,
        # then raw occurrence count.
        plausible = int(a > 0xFFFF and not is_float_bits(a))
        return (len(distinct[a]), plausible, counts[a])

    return max(counts, key=score), counts, distinct


def collect_refs(
    data: bytes, table: Table, ref_hash: int
) -> list[tuple[int, int, int, int]]:
    """Return (row, cell, hash, value) for cells whose hash matches."""
    out: list[tuple[int, int, int, int]] = []
    for r in range(table.nrows):
        row = table.base + r * table.stride
        for i in range(table.ncell):
            a, b = u32pair(data, row + 8 + i * 8)
            if a == ref_hash and b:
                out.append((r, i, a, b))
    return out


def order_fallback(
    data: bytes, table: Table, refs: list[tuple[int, int, int, int]]
) -> dict[int, tuple[str, str]]:
    """5.64 first-use-order fallback: i-th distinct ref -> i-th pool string."""
    if len(table.strings) != table.nstr:
        return {}
    ordered = list(table.strings.values())
    if len(ordered) != table.nstr:
        return {}
    seen: list[int] = []
    known: set[int] = set()
    for _r, _c, _a, b in refs:
        if b not in known:
            known.add(b)
            seen.append(b)
    if len(seen) != table.nstr:
        return {}
    return {b: (ordered[i], "order") for i, b in enumerate(seen)}


def rows_to_csv(
    data: bytes,
    table: Table,
    ref_hash: int,
    refs: list[tuple[int, int, int, int]],
    writer: csv.writer,
    all_occurrences: bool,
    include_raw: bool,
) -> Counter:
    stats: Counter = Counter()
    pool_rel = table.pool_rel
    strings = table.strings
    fallback = order_fallback(data, table, refs)
    emitted: set[int] = set()

    def resolve(b: int) -> tuple[str, str]:
        if b % 64 == 0:
            local = (b >> 6) - pool_rel
            if local in strings:
                return strings[local], "exact"
        if b in fallback:
            return fallback[b]
        return "", "raw"

    for r, _c, a, b in refs:
        if not all_occurrences:
            if b in emitted:
                continue
            emitted.add(b)
        text, confidence = resolve(b)
        if confidence == "raw" and not include_raw:
            continue
        stats[confidence] += 1
        writer.writerow(
            [f"0x{table.pos:x}", r, f"0x{a:08x}:0x{b:x}", text, confidence]
        )
    return stats


def describe_table_known(data: bytes, table: Table, ref_hash: int) -> None:
    """Print the report checks for the skill table."""
    refs = collect_refs(data, table, ref_hash)
    distinct = {b for _r, _c, _a, b in refs}
    first_pool = [
        table.strings[off] for off in sorted(table.strings)[:2] if off in table.strings
    ]
    print(
        f"  ref_hash=0x{ref_hash:08x} refs={len(refs)} distinct={len(distinct)} "
        f"declared_strings={table.nstr} pool_rel=0x{table.pool_rel:x} "
        f"pool_abs=0x{table.pos + table.pool_rel:x}"
    )
    print(f"  pool first strings: {first_pool!r}")
    print(
        f"  first ref 0x{min(distinct):x} -> pool_rel<<6 = 0x{table.pool_rel << 6:x}"
    )
    print("  first 20 rows (key, name cell4, desc cell6):")
    for r in range(min(20, table.nrows)):
        row = table.base + r * table.stride
        key = u32(data, row)
        name = strings_get(data, table, u32(data, row + 8 + 4 * 8 + 4)) or ""
        desc = strings_get(data, table, u32(data, row + 8 + 6 * 8 + 4)) or ""
        print(f"    row {r:4d} key {key:8d}  {name[:28]!r}  {desc[:28]!r}")
    for r in SKILL_ROW_IDS:
        if r >= table.nrows:
            continue
        row = table.base + r * table.stride
        key = u32(data, row)
        print(f"  row {r} key {key}:")
        for cell in range(table.ncell):
            b = u32(data, row + 8 + cell * 8 + 4)
            text = strings_get(data, table, b)
            if text is not None:
                print(f"    cell {cell:3d} 0x{b:x} {text[:70]!r}")


def strings_get(data: bytes, table: Table, b: int) -> str | None:
    if not b or b % 64:
        return None
    return table.strings.get((b >> 6) - table.pool_rel)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--table",
        type=lambda s: int(s, 0),
        default=None,
        help="only decode this table (dc.db offset, e.g. 0x1ce47c)",
    )
    ap.add_argument(
        "--all-occurrences",
        action="store_true",
        help="emit every cell occurrence instead of one row per distinct ref",
    )
    ap.add_argument(
        "--exclude-raw",
        action="store_true",
        help="drop unresolved refs instead of writing confidence=raw",
    )
    args = ap.parse_args()
    if args.table is not None and args.out == DEFAULT_OUT:
        # Do not clobber the global mapping with a single-table run.
        args.out = DEFAULT_OUT.with_name(
            f"agent_global_strings_{args.table:x}.csv"
        )

    data = args.db.read_bytes()
    tables = iter_tables(data)
    string_tables = [t for t in tables if t.nstr > 0]
    for t in tables:
        if t.nstr > 0:
            t.strings = parse_pool(data, t.pos + t.pool_rel, t.nstr)

    print(
        f"dc.db {args.db} size={len(data):#x} stdr_tables={len(tables)} "
        f"string_tables={len(string_tables)} no_pool={len(tables) - len(string_tables)}"
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    total: Counter = Counter()
    tables_done = 0
    hash_seen: dict[int, int] = {}
    exact_tables = 0
    formula_ok = 0
    order_mismatch = 0

    with args.out.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(["table", "row", "ref", "text", "confidence"])
        for table in string_tables:
            if args.table is not None and table.pos != args.table:
                continue
            ref_hash, _counts, _distinct = detect_ref_hash(data, table)
            if ref_hash is None:
                continue
            refs = collect_refs(data, table, ref_hash)
            if not refs:
                continue
            tables_done += 1
            hash_seen[ref_hash] = hash_seen.get(ref_hash, 0) + 1
            if table.pool_rel == 0x98 + table.stride * table.nrows:
                formula_ok += 1
            stats = rows_to_csv(
                data,
                table,
                ref_hash,
                refs,
                writer,
                args.all_occurrences,
                not args.exclude_raw,
            )
            total.update(stats)
            if stats["exact"] and not stats["raw"]:
                exact_tables += 1
            # cross-check position vs 5.64 order for exact-count tables
            distinct = {b for _r, _c, _a, b in refs}
            if len(distinct) == table.nstr:
                ordered = list(table.strings.values())
                seen: list[int] = []
                known: set[int] = set()
                for _r, _c, _a, b in refs:
                    if b not in known:
                        known.add(b)
                        seen.append(b)
                for i, b in enumerate(seen):
                    if i < len(ordered) and strings_get(data, table, b) != ordered[i]:
                        order_mismatch += 1

    print(
        f"tables_decoded={tables_done} refs exact={total['exact']} "
        f"order={total['order']} raw={total['raw']}"
    )
    print(
        f"tables fully exact={exact_tables}/{tables_done} "
        f"layout formula 0x98+stride*rows==pool_rel: {formula_ok}/{tables_done}"
    )
    print(
        f"unique string hashes={len(hash_seen)} "
        f"shared_hashes={sum(1 for v in hash_seen.values() if v > 1)}"
    )
    if order_mismatch:
        print(f"WARNING: position vs first-use-order mismatches={order_mismatch}")
    else:
        print("position encoding and 5.64 first-use order agree 100%")

    skill = next((t for t in string_tables if t.pos == SKILL_TABLE), None)
    if skill is not None and args.table in (None, SKILL_TABLE):
        print(f"\nskill table 0x{SKILL_TABLE:x}:")
        ref_hash, _c, _d = detect_ref_hash(data, skill)
        if ref_hash is not None:
            describe_table_known(data, skill, ref_hash)
            print(
                "  expected: value32=0x9b99200 -> 0x9b99200>>6=0x26e648=pool_rel; "
                "0x43cac4 is the absolute dc.db address, not the base"
            )

    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
