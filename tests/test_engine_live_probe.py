"""Offline tests for tools/engine_live_probe.py (no device required).

The synthetic arena is built from the documented live layout
(README.md 5.155/5.157/5.158): a 30 MiB-ish self-relative
arena whose context header sits at mapping base + 0xFF0, ten per-player record
headers carrying an absolute pointer at +0x28, and ten unit objects with
heroID/camp/entity/HP/clock fields.  A ``FakeAdb`` serves those bytes through
the same duck-typed interface the real probe uses, so the chain lookup, the
chunked capture and the fallback locator are all exercised end to end without
touching MuMu.
"""
from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.engine_live_probe as probe  # noqa: E402
from tools.arena_player_stats import find_records  # noqa: E402
from tools.frapinfo_live_probe import parse_maps  # noqa: E402

ARENA_BASE = 0x7830BE000000
HERO_IDS = [153, 156, 109, 196, 175, 199, 167, 141, 140, 123]
CAMPS = [2, 2, 1, 1, 1, 2, 1, 2, 1, 2]
ENTITIES = [1799, 1760, 1613, 1611, 1168, 1031, 750, 551, 538, 296]
LEVELS = [3, 2, 3, 3, 2, 3, 4, 2, 3, 2]
GOLDS = [882, 661, 890, 902, 679, 1021, 1065, 723, 1083, 658]
STALE_UNIT = 6  # idx 1000000007 = 孙悟空, documented stale clock (1337 ms)
STALE_INDEX = 1000000007
REAL_0500 = (ROOT / "data" / "replays" / "_analysis" / "live_20261104"
             / "arena_paused_0500.bin")
REAL_0500_BASE = 0x7830CE89B000

GC_BASE = 0x400036A00000
HEAP_BASE = 0x7830BF000000
CHAIN_P1 = HEAP_BASE + 0x100
CHAIN_P2 = HEAP_BASE + 0x200


# ---------------------------------------------------------------------------
# Synthetic arena builder
# ---------------------------------------------------------------------------
def _w32(raw: bytearray, off: int, value: int) -> None:
    struct.pack_into("<I", raw, off, value & 0xFFFFFFFF)


def _u32(raw: bytes, off: int) -> int:
    return struct.unpack_from("<I", raw, off)[0]


def _u64(raw: bytes, off: int) -> int:
    return struct.unpack_from("<Q", raw, off)[0]


def _w64(raw: bytearray, off: int, value: int) -> None:
    struct.pack_into("<Q", raw, off, value & 0xFFFFFFFFFFFFFFFF)


def build_arena(size: int = 0x400000, base: int = ARENA_BASE,
                ctx_offset: int = probe.CTX_PAGE_OFFSET,
                record_off: int = 0x60000, unit_off: int = 0x200000,
                unit_stride: int = 0x4000,
                clock_overrides: dict[int, tuple[int, int]] | None = None,
                hp_overrides: dict[int, dict] | None = None,
                hero_overrides: dict[int, int] | None = None,
                missing_indexes: tuple[int, ...] = (),
                extra_blocks: int = 0,
                extra_block_stride: int = 0x80000,
                extra_block_pointer: int | None = None) -> dict:
    """Build a synthetic arena; returns raw bytes plus the layout bookkeeping."""
    raw = bytearray(size)
    _w64(raw, ctx_offset, base + ctx_offset)
    _w32(raw, ctx_offset + 8, size)
    clock_overrides = clock_overrides or {}
    hp_overrides = hp_overrides or {}
    hero_overrides = hero_overrides or {}
    records = []
    for i in range(10):
        rec = record_off + i * 0x2C00
        unit = unit_off + i * unit_stride
        index = probe.REC_INDEX_MAX - i
        hero = hero_overrides.get(i, HERO_IDS[i])
        _w32(raw, rec + 0x00, 16)
        _w32(raw, rec + 0x04, (i % 4) + 1)
        _w32(raw, rec + 0x08, 10000)
        struct.pack_into("<f", raw, rec + 0x0C, 3.32)
        _w32(raw, rec + 0x20, index)
        _w64(raw, rec + 0x28, base + unit)
        _w32(raw, rec + 0x4C, GOLDS[i])
        _w32(raw, rec + 0x4C + 0x158, i % 3)
        _w32(raw, rec + 0x4C + 0xB8, i % 2)
        _w32(raw, rec + 0x4C + 0xBC, i % 4)
        _w32(raw, rec + 0x4C + 0xC0, 1)
        _w32(raw, rec + 0x218, 16)
        _w32(raw, rec + 0x21C, 8)
        _w32(raw, rec + 0x220, LEVELS[i])
        _w32(raw, rec + 0x224, i % 3)
        _w32(raw, rec + 0x228, i % 2)
        for c in range(probe.REC_COUNTERS):
            _w32(raw, rec + 0x50 + 4 * c, 1000 * c + i)
        if index in missing_indexes:
            _w32(raw, rec, 0)  # break the header signature
        hp = hp_overrides.get(i, {})
        _w32(raw, unit + 0x08, hp.get("hp_current", 800 - 10 * i))
        _w32(raw, unit + 0x10, hp.get("hp_max", 1000 + i))
        _w32(raw, unit + 0x28, hero)
        _w32(raw, unit + 0x34, hp.get("camp", CAMPS[i]))
        _w32(raw, unit + 0x3C, hp.get("entity_id", ENTITIES[i]))
        _w32(raw, unit + 0x40, hp.get("entity_id", ENTITIES[i]))
        clock_off = (probe.UNIT_CLOCK_ESCAPE_OFF
                     if hero in probe.UNIT_CLOCK_ESCAPE_HEROES
                     else probe.UNIT_CLOCK_OFF)
        if i in clock_overrides:
            frame, ms = clock_overrides[i]
        elif i == STALE_UNIT:
            frame, ms = 3587, 1337
        else:
            frame, ms = 1470 - i, 94876 - 2 * i
        _w32(raw, unit + clock_off, frame)
        _w32(raw, unit + clock_off + 4, ms)
        struct.pack_into("<iii", raw, unit + 0x278, 1000 + i, 0, -500 - i)
        struct.pack_into("<ii", raw, unit + 0x288, 0, 1000)
        records.append({"record_offset": rec, "unit_offset": unit,
                        "index": index, "hero": hero})
    for extra in range(extra_blocks):
        extra_off = record_off + extra_block_stride * (extra + 1)
        for i in range(10):
            src = record_off + i * 0x2C00
            dst = extra_off + i * 0x2C00
            raw[dst:dst + probe.REC_MIN_BYTES] = raw[src:src + probe.REC_MIN_BYTES]
            if extra_block_pointer is not None:
                _w64(raw, dst + 0x28, base + extra_block_pointer)
    return {"raw": bytes(raw), "base": base, "size": size,
            "ctx_offset": ctx_offset, "records": records,
            "record_off": record_off, "unit_off": unit_off}


def decode(built: dict, **kwargs) -> dict:
    kwargs.setdefault("capture_start_abs", built["base"])
    kwargs.setdefault("expected_ctx_abs", built["base"] + built["ctx_offset"])
    return probe.decode_arena(built["raw"], **kwargs)


def _checks_by_name(checks: list[dict]) -> dict[str, dict]:
    return {check["name"]: check for check in checks}


# ---------------------------------------------------------------------------
# Fake adb device
# ---------------------------------------------------------------------------
class FakeAdb:
    """Sparse /proc/<pid>/mem + shell stand-in for the probe's device layer."""

    def __init__(self, ranges: list[tuple[int, bytes]], maps_text: str,
                 pid: int = 4321) -> None:
        self.ranges = sorted(ranges, key=lambda item: item[0])
        self.maps_text = maps_text
        self.pid = pid
        self.exe = "fake-adb"
        self.serial = "fake:1"
        self.fail_once: dict[int, int] = {}
        self.fail_always: set[int] = set()
        self.reads: list[tuple[int, int]] = []
        self.shell_calls: list[tuple[str, ...]] = []

    # -- memory ------------------------------------------------------------
    def read_mem(self, pid: int, addr: int, size: int,
                 timeout: int = 90) -> bytes | None:
        self.reads.append((addr, size))
        if addr in self.fail_always:
            return None
        if self.fail_once.get(addr, 0) > 0:
            self.fail_once[addr] -= 1
            return None
        out = bytearray()
        cursor = addr
        end = addr + size
        while cursor < end:
            segment = None
            for start, data in self.ranges:
                if start <= cursor < start + len(data):
                    segment = (start, data)
                    break
            if segment is None:
                return None
            start, data = segment
            offset = cursor - start
            take = min(end - cursor, len(data) - offset)
            out += data[offset:offset + take]
            cursor += take
        return bytes(out)

    # -- process / shell ---------------------------------------------------
    def pids(self, package: str) -> list[int]:
        return [self.pid]

    def read_maps(self, pid: int) -> list:
        return parse_maps(self.maps_text)

    def shell(self, *args: str, timeout: int = 30) -> bytes:
        self.shell_calls.append(args)
        if args[:1] == ("cat",):
            target = args[1] if len(args) > 1 else ""
            if target.endswith("/maps"):
                return self.maps_text.encode("utf-8")
            if target.endswith("/stat"):
                return (f"{self.pid} (com.tencent.tmgp.sgame) S 1 2 3"
                        .encode("utf-8"))
        if args[:1] == ("pidof",):
            return str(self.pid).encode("ascii")
        if args[:1] == ("id",):
            return b"uid=0(root) gid=0(root) groups=0(root)"
        return b""


def fake_maps_text(arena_base: int, arena_size: int) -> str:
    return "\n".join([
        f"{arena_base:x}-{arena_base + arena_size:x} rw-p 00000000 00:00 0",
        f"{GC_BASE:x}-{GC_BASE + 0x544D478:x} r-xp 00000000 00:00 0 "
        f"/data/app/com.tencent.tmgp.sgame/lib/arm64/libGameCore.so",
        f"{HEAP_BASE:x}-{HEAP_BASE + 0x1000:x} rw-p 00000000 00:00 0 [anon:fake]",
    ])


def fake_device(arena: bytes, chain_ok: bool = True,
                arena_base: int = ARENA_BASE) -> FakeAdb:
    """Sparse memory for a working (or dead) three-hop context chain.

    ``Reader`` always reads whole 4 KiB pages, so every pointer the chain
    touches gets a full page of backing bytes.
    """
    ctx = arena_base + probe.CTX_PAGE_OFFSET
    slot = GC_BASE + probe.GC_CHAIN_OFFSET
    heap = bytearray(0x3000)
    _w64(heap, CHAIN_P1 - HEAP_BASE, CHAIN_P2)
    _w64(heap, CHAIN_P2 - HEAP_BASE, ctx)
    slot_page = slot & ~0xFFF
    slot_data = bytearray(0x1000)
    _w64(slot_data, slot - slot_page, CHAIN_P1 if chain_ok else 0)
    ranges = [(slot_page, bytes(slot_data)), (HEAP_BASE, bytes(heap))]
    ranges.append((arena_base, arena))
    maps_text = "\n".join([
        f"{arena_base:x}-{arena_base + len(arena):x} rw-p 00000000 00:00 0",
        f"{GC_BASE:x}-{GC_BASE + 0x544D478:x} r-xp 00000000 00:00 0 "
        f"/data/app/com.tencent.tmgp.sgame/lib/arm64/libGameCore.so",
        f"{HEAP_BASE:x}-{HEAP_BASE + 0x3000:x} rw-p 00000000 00:00 0 [anon:fake]",
    ])
    return FakeAdb(ranges, maps_text)


def options(out: Path | None, **overrides) -> probe.Options:
    opt = probe.Options(out=out, label="unit_test", quiet=True)
    for key, value in overrides.items():
        setattr(opt, key, value)
    return opt


# ---------------------------------------------------------------------------
# Record headers
# ---------------------------------------------------------------------------
class TestRecordHeaders(unittest.TestCase):
    def test_finds_ten_headers_matching_legacy_scanner(self):
        built = build_arena()
        headers = probe.find_record_headers(built["raw"])
        self.assertEqual(len(headers), 10)
        self.assertEqual([h["index"] for h in headers],
                         sorted((h["index"] for h in headers), reverse=True))
        legacy = find_records(built["raw"])
        self.assertEqual(sorted(legacy), sorted(h["index"] for h in headers))
        for header in headers:
            ref = legacy[header["index"]]
            self.assertEqual(header["record_offset"], ref["offset"])
            self.assertEqual(header["gold"], ref["gold"])
            self.assertEqual(header["level"], ref["level"])
            self.assertEqual(header["kills"], ref["kills"])
            self.assertEqual(header["deaths"], ref["deaths"])
            self.assertEqual(header["assists"], ref["assists"])
            expected_unit = next(r["unit_offset"] for r in built["records"]
                                 if r["index"] == header["index"])
            self.assertEqual(header["pointer"], built["base"] + expected_unit)
            self.assertEqual(len(header["counters"]), probe.REC_COUNTERS)

    def test_group_blocks_splits_on_large_gap(self):
        headers = [{"record_offset": 0x1000, "index": 1000000004},
                   {"record_offset": 0x2000, "index": 1000000005},
                   {"record_offset": 0x9000, "index": 1000000006}]
        blocks = probe.group_record_blocks(headers, gap=probe.REC_BLOCK_GAP)
        self.assertEqual(len(blocks), 1)  # 0x9000 - 0x2000 < 0x40000
        blocks = probe.group_record_blocks(
            [{"record_offset": 0x1000, "index": 1000000004},
             {"record_offset": 0x2000, "index": 1000000005},
             {"record_offset": 0x2000 + probe.REC_BLOCK_GAP + 1,
              "index": 1000000006}])
        self.assertEqual(len(blocks), 2)

    def test_duplicate_block_is_reported_and_best_block_chosen(self):
        built = build_arena(extra_blocks=1, extra_block_pointer=0x3F0000)
        decoded = decode(built)
        self.assertEqual(decoded["records"]["headers_found"], 20)
        self.assertEqual(len(decoded["records"]["blocks"]), 2)
        self.assertEqual(decoded["records"]["stale_blocks"], 1)
        self.assertEqual(decoded["structural_count"], 10)
        self.assertEqual(decoded["records"]["chosen_block_offset"],
                         built["record_off"])  # valid block beats stale garbage
        self.assertEqual([row["unit_offset"] for row in decoded["records"]["rows"]],
                         [r["unit_offset"] for r in built["records"]])
        checks = _checks_by_name(probe.evaluate_snapshot(decoded, "all"))
        self.assertEqual(checks["records"]["level"], "PASS")
        self.assertEqual(checks["records_blocks"]["level"], "WARN")

    def test_adjacent_duplicate_block_stays_separate(self):
        # Gap below REC_BLOCK_GAP: only the repeated index may split the block.
        built = build_arena(extra_blocks=1, extra_block_stride=0x30000,
                            extra_block_pointer=0x3F0000)
        blocks = probe.group_record_blocks(
            probe.find_record_headers(built["raw"]))
        self.assertEqual(len(blocks), 2)
        self.assertTrue(all(len(block) == 10 for block in blocks))
        decoded = decode(built)
        self.assertEqual(decoded["records"]["stale_blocks"], 1)
        self.assertEqual([row["unit_offset"] for row in decoded["records"]["rows"]],
                         [r["unit_offset"] for r in built["records"]])

    def test_numpy_and_python_paths_agree(self):
        built = build_arena(size=0x100000, record_off=0x10000,
                            unit_off=0x60000, unit_stride=0x1000)
        fast = probe.find_record_headers(built["raw"])
        saved = probe.np
        try:
            probe.np = None
            slow = probe.find_record_headers(built["raw"])
        finally:
            probe.np = saved
        self.assertEqual([h["record_offset"] for h in fast],
                         [h["record_offset"] for h in slow])
        self.assertEqual(len(slow), 10)


# ---------------------------------------------------------------------------
# Unit objects
# ---------------------------------------------------------------------------
class TestUnitObjects(unittest.TestCase):
    def test_structural_scan_finds_exactly_the_ten_units(self):
        built = build_arena()
        candidates = probe.scan_unit_candidates(built["raw"])
        offsets = {c["unit_offset"] for c in candidates}
        self.assertEqual(offsets, {r["unit_offset"] for r in built["records"]})
        self.assertEqual([c["hero_id"] for c in candidates],
                         [c["hero_id"] for c in candidates])  # stable order

    def test_clock_offset_escape_for_lubu_and_guanyu(self):
        built = build_arena()
        units = {row["arena_index"]: row for row in decode(built)["records"]["rows"]}
        for record in built["records"]:
            row = units[record["index"]]
            if record["hero"] in probe.UNIT_CLOCK_ESCAPE_HEROES:
                self.assertEqual(row["clock_offset"], probe.UNIT_CLOCK_ESCAPE_OFF)
            else:
                self.assertEqual(row["clock_offset"], probe.UNIT_CLOCK_OFF)
        # 关羽/吕布 clocks were written at +0x1524/+0x1528 and must be found there.
        guanyu = units[1000000005]
        self.assertEqual(guanyu["clock_ms"], 94876 - 2 * 8)

    def test_parse_unit_rejects_out_of_bounds(self):
        built = build_arena(size=0x100000, record_off=0x10000,
                            unit_off=0x60000, unit_stride=0x1000)
        self.assertIsNone(probe.parse_unit(built["raw"], 0x100000))
        self.assertIsNone(probe.parse_unit(built["raw"], -8))

    def test_numpy_and_python_unit_scan_agree(self):
        built = build_arena(size=0x100000, record_off=0x10000,
                            unit_off=0x60000, unit_stride=0x1000)
        fast = probe.scan_unit_candidates(built["raw"])
        saved = probe.np
        try:
            probe.np = None
            slow = probe.scan_unit_candidates(built["raw"])
        finally:
            probe.np = saved
        self.assertEqual([c["unit_offset"] for c in fast],
                         [c["unit_offset"] for c in slow])
        self.assertEqual(len(slow), 10)


# ---------------------------------------------------------------------------
# Decode + checks
# ---------------------------------------------------------------------------
class TestDecode(unittest.TestCase):
    def test_decode_full_snapshot(self):
        built = build_arena()
        decoded = decode(built)
        self.assertTrue(decoded["arena"]["header_found"])
        self.assertEqual(decoded["arena"]["arena_size"], built["size"])
        self.assertEqual(decoded["arena"]["base_abs"], ARENA_BASE)
        self.assertEqual(decoded["arena"]["base_delta"], 0)
        self.assertEqual(decoded["records"]["indices_complete"], True)
        self.assertEqual(len(decoded["records"]["rows"]), 10)
        self.assertEqual(decoded["structural_count"], 10)
        self.assertEqual(decoded["pointer_match"], 10)
        self.assertEqual(decoded["roster_static_matches"], 10)
        self.assertEqual(decoded["clocks"]["valid_count"], 9)
        self.assertEqual(decoded["clocks"]["stale_indexes"], [STALE_INDEX])
        self.assertAlmostEqual(decoded["clocks"]["median_s"], 94.868, places=3)
        self.assertTrue(decoded["clocks"]["ok"])
        self.assertTrue(decoded["hp"]["ok"])
        checks = _checks_by_name(probe.evaluate_snapshot(decoded, "all"))
        self.assertEqual(checks["records"]["level"], "PASS")
        self.assertEqual(checks["record_crosscheck"]["level"], "PASS")
        self.assertEqual(checks["units"]["level"], "PASS")
        self.assertEqual(checks["clock_consistency"]["level"], "WARN")
        self.assertNotIn("FAIL", {c["level"] for c in checks.values()})
        self.assertTrue(probe.checks_ok(list(checks.values())))

    def test_decode_vote_path_with_moved_ctx_header(self):
        built = build_arena(ctx_offset=0x800)
        decoded = decode(built)
        self.assertTrue(decoded["arena"]["header_found"])
        self.assertEqual(decoded["arena"]["ctx_offset"], 0x800)
        self.assertEqual(decoded["arena"]["base_abs"], ARENA_BASE)
        self.assertEqual(decoded["arena"]["base_votes"], 10)
        self.assertEqual(decoded["structural_count"], 10)
        self.assertTrue(probe.checks_ok(probe.evaluate_snapshot(decoded, "all")))

    def test_missing_record_fails_validation(self):
        built = build_arena(missing_indexes=(1000000004,))
        decoded = decode(built)
        self.assertEqual(len(decoded["records"]["rows"]), 9)
        checks = _checks_by_name(probe.evaluate_snapshot(decoded, "all"))
        self.assertEqual(checks["records"]["level"], "FAIL")
        self.assertFalse(probe.checks_ok(list(checks.values())))
        self.assertFalse(decoded["records"]["indices_complete"])

    def test_corrupt_unit_fails_resolution(self):
        built = build_arena(hero_overrides={0: 999})
        decoded = decode(built)
        self.assertEqual(decoded["structural_count"], 9)
        self.assertEqual(decoded["pointer_match"], 9)
        checks = _checks_by_name(probe.evaluate_snapshot(decoded, "all"))
        self.assertEqual(checks["units"]["level"], "FAIL")
        self.assertEqual(checks["pointer_resolution"]["level"], "FAIL")
        self.assertFalse(probe.checks_ok(list(checks.values())))

    def test_two_bad_clocks_fail_clock_check(self):
        built = build_arena(clock_overrides={0: (10, 1000), 1: (11, 2000)})
        decoded = decode(built)
        # 0, 1 and the documented stale unit are all far from the median.
        self.assertEqual(decoded["clocks"]["valid_count"], 7)
        checks = _checks_by_name(probe.evaluate_snapshot(decoded, "all"))
        self.assertEqual(checks["clock_consistency"]["level"], "FAIL")

    def test_bad_hp_pair_fails_hp_check(self):
        built = build_arena(hp_overrides={0: {"hp_max": 5, "hp_current": 5000}})
        decoded = decode(built)
        self.assertEqual(decoded["hp"]["valid_count"], 9)
        checks = _checks_by_name(probe.evaluate_snapshot(decoded, "all"))
        self.assertEqual(checks["hp_pairs"]["level"], "FAIL")

    def test_records_only_decode_skips_units(self):
        built = build_arena()
        decoded = decode(built, want_units=False)
        rows = decoded["records"]["rows"]
        self.assertEqual(len(rows), 10)
        self.assertIsNone(rows[0].get("unit_offset"))
        self.assertEqual(decoded["units"], [])
        self.assertEqual(decoded["clocks"], {})
        checks = _checks_by_name(probe.evaluate_snapshot(decoded, "records"))
        self.assertEqual(checks["records"]["level"], "PASS")
        self.assertNotIn("units", checks)
        self.assertTrue(probe.checks_ok(list(checks.values())))

    def test_arena_mode_only_checks_header(self):
        built = build_arena()
        decoded = decode(built)
        checks = probe.evaluate_snapshot(decoded, "arena")
        names = {c["name"] for c in checks}
        self.assertNotIn("records", names)
        self.assertNotIn("units", names)
        self.assertEqual(_checks_by_name(checks)["arena_header"]["level"], "PASS")

    def test_meta_payload_is_json_serializable(self):
        built = build_arena()
        decoded = decode(built)
        meta = {
            "arena": decoded["arena"],
            "records": {k: v for k, v in decoded["records"].items() if k != "rows"},
            "record_rows": decoded["records"]["rows"],
            "units": decoded["units"],
            "clocks": decoded["clocks"],
            "hp": decoded["hp"],
            "roster": decoded["roster"],
            "checks": probe.evaluate_snapshot(decoded, "all"),
        }
        text = json.dumps(meta, ensure_ascii=False)
        self.assertIn("arena_size", text)
        self.assertEqual(json.loads(text)["arena"]["base_hex"], hex(ARENA_BASE))


# ---------------------------------------------------------------------------
# Context header, capture plan, pointer scan
# ---------------------------------------------------------------------------
class TestLocateHelpers(unittest.TestCase):
    def test_find_ctx_headers_filters_wrong_size(self):
        buf = bytearray(0x1000)
        base = 0x700000000000
        _w64(buf, 0x100, base + 0x100)
        _w32(buf, 0x108, 0x1E00000)
        _w64(buf, 0x200, base + 0x200)
        _w32(buf, 0x208, 7)  # bogus size -> rejected
        found = probe.find_ctx_headers_in_buffer(bytes(buf), base)
        self.assertEqual([h["offset"] for h in found], [0x100])
        self.assertEqual(found[0]["ctx_abs"], base + 0x100)
        self.assertEqual(found[0]["size"], 0x1E00000)

    def test_plan_capture_is_page_aligned_and_mapping_clamped(self):
        maps = parse_maps(fake_maps_text(ARENA_BASE, 0x400000))
        plan = probe.plan_capture(maps, ARENA_BASE + 0xFF0, 0x400000)
        self.assertEqual(plan["capture_start"], ARENA_BASE)
        self.assertEqual(plan["ctx_offset"], 0xFF0)
        self.assertEqual(plan["length"], 0x400000)
        self.assertFalse(plan["truncated"])
        short = probe.plan_capture(maps, ARENA_BASE + 0xFF0, 0x800000)
        self.assertEqual(short["length"], 0x400000)
        self.assertTrue(short["truncated"])

    def test_plan_capture_outside_mappings_raises(self):
        maps = parse_maps(fake_maps_text(ARENA_BASE, 0x400000))
        with self.assertRaises(probe.ProbeError) as ctx:
            probe.plan_capture(maps, 0x1000, 0x400000)
        self.assertEqual(ctx.exception.code, 2)

    def test_scan_qwords_in_ranges(self):
        ranges = [(0x1000, 0x2000)]
        raw = struct.pack("<QQQQ", 0x1000, 0x1FFF, 0x2000, 0xABC)
        found = probe._scan_qwords_in_ranges(raw, 0, ranges)
        self.assertEqual(sorted(found), [0x1000, 0x1FFF])
        self.assertEqual(probe._scan_qwords_in_ranges(b"", 0, []), [])

    def test_scan_size_constant_candidates(self):
        buf = bytearray(0x40)
        _w64(buf, 0x00, 0x1234)
        _w32(buf, 0x08, probe.ARENA_SIZE_EXPECTED)
        _w64(buf, 0x10, 0x99)
        _w32(buf, 0x18, probe.ARENA_SIZE_EXPECTED)
        found = probe._scan_size_constant_candidates(bytes(buf))
        self.assertEqual(found, [(0x08, 0x1234), (0x18, 0x99)])


# ---------------------------------------------------------------------------
# Chunked capture
# ---------------------------------------------------------------------------
class TestCapture(unittest.TestCase):
    def test_chunked_read_retries_a_short_chunk(self):
        built = build_arena(size=0x100000, record_off=0x10000,
                            unit_off=0x60000, unit_stride=0x1000)
        device = fake_device(built["raw"])
        device.fail_once[ARENA_BASE] = 1
        raw, diag = probe.read_arena_chunks(
            device, device.pid, ARENA_BASE, 0x100000, chunk_bytes=0x40000,
            retries=3)
        self.assertEqual(raw, built["raw"][:0x100000])
        self.assertEqual(diag["chunks"], 4)
        self.assertEqual(diag["chunk_rows"][0]["attempts"], 2)
        self.assertEqual(diag["failures"], [])

    def test_persistent_failure_raises_exit_3(self):
        built = build_arena(size=0x100000, record_off=0x10000,
                            unit_off=0x60000, unit_stride=0x1000)
        device = fake_device(built["raw"])
        device.fail_always.add(ARENA_BASE)
        with self.assertRaises(probe.ProbeError) as ctx:
            probe.read_arena_chunks(device, device.pid, ARENA_BASE, 0x100000,
                                    chunk_bytes=0x40000, retries=2)
        self.assertEqual(ctx.exception.code, 3)
        self.assertTrue(ctx.exception.info["failures"])


# ---------------------------------------------------------------------------
# End-to-end orchestration with the fake device
# ---------------------------------------------------------------------------
class TestRunEndToEnd(unittest.TestCase):
    def test_run_writes_artifacts_and_passes(self):
        built = build_arena()
        device = fake_device(built["raw"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "snap_ok"
            result = probe.run(device, options(out))
            self.assertEqual(result["exit_code"], 0, result["meta"]["failures"])
            self.assertIn(result["meta"]["status"], ("ok", "degraded"))
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["status"], result["meta"]["status"])
            self.assertEqual(len(meta["record_rows"]), 10)
            self.assertEqual(meta["units_count"], 10)
            self.assertEqual(meta["locate"]["method"], "chain")
            self.assertEqual(meta["device"]["pid"], device.pid)
            self.assertEqual((out / "arena.bin").stat().st_size, built["size"])
            lines = (out / "units.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 10)
            self.assertTrue((out / "units" / "unit_1000000013.bin").exists())
            self.assertTrue(any(check["name"] == "freeze_stable"
                                for check in meta["checks"]))

    def test_run_locate_only_does_not_capture(self):
        built = build_arena()
        device = fake_device(built["raw"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "locate"
            result = probe.run(device, options(out, locate_only=True))
            self.assertEqual(result["exit_code"], 0)
            self.assertEqual(result["status"], "located")
            self.assertTrue((out / "meta.json").exists())
            self.assertFalse((out / "arena.bin").exists())
            reads = [r for r in device.reads if r[1] > 0x40000]
            self.assertEqual(reads, [])

    def test_run_falls_back_to_mapping_scan_when_chain_is_dead(self):
        built = build_arena()
        device = fake_device(built["raw"], chain_ok=False)
        with tempfile.TemporaryDirectory() as tmp:
            result = probe.run(device, options(Path(tmp) / "snap_fallback"))
            self.assertEqual(result["exit_code"], 0, result["meta"]["failures"])
            self.assertEqual(result["meta"]["locate"]["method"],
                             "fallback_mapping_scan")
            self.assertTrue(any("mapping header scan" in line
                                for line in result["meta"]["locate"]["diagnostics"]))

    def test_run_records_mode_skips_units_jsonl(self):
        built = build_arena()
        device = fake_device(built["raw"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "snap_records"
            result = probe.run(device, options(out, mode="records"))
            self.assertEqual(result["exit_code"], 0)
            self.assertFalse((out / "units.jsonl").exists())
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(len(meta["record_rows"]), 10)

    def test_run_units_mode_skips_clock_and_hp_checks(self):
        built = build_arena()
        device = fake_device(built["raw"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "snap_units"
            result = probe.run(device, options(out, mode="units"))
            self.assertEqual(result["exit_code"], 0)
            self.assertTrue((out / "units.jsonl").exists())
            names = {check["name"] for check in result["meta"]["checks"]}
            self.assertNotIn("clock_consistency", names)
            self.assertNotIn("hp_pairs", names)
            self.assertIn("units", names)

    def test_run_without_keeping_arena(self):
        built = build_arena()
        device = fake_device(built["raw"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "snap_no_arena"
            result = probe.run(device, options(out, keep_arena=False))
            self.assertEqual(result["exit_code"], 0)
            self.assertFalse((out / "arena.bin").exists())
            self.assertTrue((out / "units.jsonl").exists())
            self.assertTrue((out / "units" / "unit_1000000013.bin").exists())

    def test_run_validation_failure_exits_4(self):
        built = build_arena(missing_indexes=(1000000010,))
        device = fake_device(built["raw"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "snap_bad"
            result = probe.run(device, options(out))
            self.assertEqual(result["exit_code"], 4)
            self.assertEqual(result["meta"]["status"], "failed")
            self.assertTrue(result["meta"]["failures"])
            meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["status"], "failed")
            self.assertTrue(meta["failures"])


# ---------------------------------------------------------------------------
# Optional real snapshot (gitignored capture; skipped when absent)
# ---------------------------------------------------------------------------
@unittest.skipUnless(REAL_0500.exists(),
                     "real arena snapshot not present (gitignored capture)")
class TestRealArenaSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = REAL_0500.read_bytes()

    def test_real_snapshot_matches_documented_values(self):
        decoded = probe.decode_arena(
            self.raw, capture_start_abs=REAL_0500_BASE,
            expected_ctx_abs=REAL_0500_BASE + probe.CTX_PAGE_OFFSET)
        self.assertEqual(len(decoded["records"]["rows"]), 10)
        self.assertEqual(decoded["structural_count"], 10)
        self.assertEqual(decoded["pointer_match"], 10)
        self.assertEqual(decoded["arena"]["base_abs"], REAL_0500_BASE)
        rows = {row["arena_index"]: row for row in decoded["records"]["rows"]}
        # README state_table: 05:00 idx 13 = 兰陵王 2800 gold level 7.
        self.assertEqual(rows[1000000013]["gold"], 2800)
        self.assertEqual(rows[1000000013]["level"], 7)
        self.assertEqual(rows[1000000013]["hero"], "兰陵王")
        self.assertEqual(rows[1000000009]["hero"], "钟馗")
        self.assertAlmostEqual(decoded["clocks"]["median_s"], 300.184, places=3)
        self.assertEqual(decoded["clocks"]["stale_indexes"], [STALE_INDEX])
        checks = _checks_by_name(probe.evaluate_snapshot(decoded, "all"))
        self.assertNotIn("FAIL", {c["level"] for c in checks.values()})
        self.assertTrue(probe.checks_ok(list(checks.values())))


if __name__ == "__main__":
    unittest.main()
