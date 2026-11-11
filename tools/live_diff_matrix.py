#!/usr/bin/env python3
"""Live per-field diff matrix for the ten GameCore arena unit objects.

The GameCore context is reached from the IL2CPP image base:

    libil2cpp_base + 0x159EA4D0  ->  P1
    [P1]                         ->  context (0x1E00000 arena)

Inside the arena, ten battle-stat records carry the stable header
``+0x00=16, +0x08=10000, +0x0C=f32~3.32, +0x20=1000000000+index``.
``record+0x28`` is an absolute pointer to the unit object for that player.
The unit header used here is:

    +0x08 u32 normalized HP current
    +0x10 u32 normalized HP max
    +0x28 u32 heroID
    +0x3C u32 entityID
    +0x40 u32 entityID (duplicate)

Live mode captures t0 while the replay is paused, clicks play at game-space
(402, 845), waits ``--seconds``, clicks pause, then re-scans the records and
captures t1.  The clicks use the same MuMu window mapping as
``tools/host_click.py``.

Offline mode never contacts the device.  It diffs saved
``unit_<name>_t0.bin`` / ``unit_<name>_t1.bin`` files, which is also what
``--dry-run`` does when offline inputs are supplied.

Outputs (inside ``--out``, which must be below ``data/``):

* ``unit_diff.json``   full report: context chain, ten records, per-unit
  fields, changed u32 words, and the cross-unit field matrix;
* ``unit_diff.csv``    long form: one row per unit/field;
* ``field_matrix.csv`` wide form: one row per offset, one column group per
  unit.

Live mode additionally saves the raw ``unit_*_t0.bin`` / ``unit_*_t1.bin``
captures so the run can be re-diffed offline.

Read-only.  Every device read is bounded to <= 8 MiB and uses a device-side
``timeout 10`` around ``dd``; timed-out/failed reads are followed by a
best-effort cleanup of the matching ``dd`` process.

Usage
-----
    # dry-run, no device contact, diff two saved captures
    python tools/live_diff_matrix.py --dry-run
        --offline-t0 data/replays/_analysis/live_20261104/unit_zhongkui_t0.bin
        --offline-t1 data/replays/_analysis/live_20261104/unit_zhongkui_t1.bin
        --out data/replays/_analysis/live_20261104/diff_tool_test

    # diff every unit_*_t0.bin / unit_*_t1.bin pair in a directory
    python tools/live_diff_matrix.py --dry-run
        --offline-dir data/replays/_analysis/live_20261104
        --out data/replays/_analysis/live_20261104/diff_tool_test/all_pairs

    # live capture: paused t0 -> play 3 s -> pause t1
    python tools/live_diff_matrix.py --pid 2135 --seconds 3
        --out data/replays/_analysis/live_20261104/live_diff

Exit codes: 0 = report written, 1 = tool/device error, 2 = CLI usage error.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import json
import re
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = (ROOT / "data").resolve()
TOOLS_DIR = Path(__file__).resolve().parent

ADB_DEFAULT = "D:/MuMuPlayer/nx_main/adb.exe"
SERIAL_DEFAULT = "127.0.0.1:16384"
PACKAGE_DEFAULT = "com.tencent.tmgp.sgame"

# GameCore context chain and arena geometry (docs/replay_binary_format.md
# 5.155-5.157).
CONTEXT_GLOBAL_OFFSET = 0x159EA4D0
ARENA_SIZE = 0x1E00000
UNIT_SIZE = 0x2000

# Read bounds.  4 MiB chunks keep every dd invocation well below the 8 MiB
# ceiling even after page alignment and scan overlap.
MAX_READ = 8 * 1024 * 1024
READ_CHUNK = 4 * 1024 * 1024
SCAN_OVERLAP = 0x400
DEVICE_TIMEOUT_S = 10

# Records were observed at arena+0x17c5cc0 in the 2026-11-04 G4 sessions.
DEFAULT_SCAN_START = 0x1700000
DEFAULT_SCAN_SIZE = 0x100000
DEFAULT_SECONDS = 3.0
DEFAULT_SETTLE = 0.8

PLAY_PAUSE_GAME_XY = (402, 845)
EXPECTED_RECORDS = 10
RECORD_HEADER_SIZE = 0x1E4
RECORD_INDEX_BASE = 1_000_000_000
RECORD_INDEX_SPAN = 14

# Header semantics from docs/replay_binary_format.md 5.157.  The ids are
# informational (the live unit header is authoritative); the index order is
# the one observed in the ten-record block.
HERO_BY_INDEX = {
    13: "兰陵王",
    12: "张良",
    11: "妲己",
    10: "百里守约",
    9: "钟馗",
    8: "公孙离",
    7: "孙悟空",
    6: "貂蝉",
    5: "关羽",
    4: "吕布",
}
HERO_NAME_BY_ID = {
    153: "兰陵王",
    156: "张良",
    109: "妲己",
    196: "百里守约",
    175: "钟馗",
    199: "公孙离",
    167: "孙悟空",
    141: "貂蝉",
    140: "关羽",
    123: "吕布",
}

# Named fields in the unit object.  Everything else that changes is still
# reported as a raw aligned u32 word.
NAMED_FIELDS = (
    (0x08, "hp_current", "u32"),
    (0x10, "hp_max", "u32"),
    (0x28, "hero_id", "u32"),
    (0x3C, "entity_id", "u32"),
    (0x40, "entity_id_dup", "u32"),
)
NAMED_BY_OFFSET = {off: (name, typ) for off, name, typ in NAMED_FIELDS}

PAIR_RE = re.compile(r"^unit_(?P<name>.+)_t(?P<phase>[01])\.bin$",
                     re.IGNORECASE)
UNSAFE_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')


class ToolError(RuntimeError):
    """A recoverable tool error (reported without a traceback)."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def parse_int(text: str) -> int:
    """argparse type accepting decimal or 0x-prefixed integers."""
    try:
        return int(text, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}")


def hexstr(value: int | None) -> str | None:
    return None if value is None else f"0x{value:x}"


def u32(raw: bytes, off: int) -> int:
    return struct.unpack_from("<I", raw, off)[0]


def u64(raw: bytes, off: int) -> int:
    return struct.unpack_from("<Q", raw, off)[0]


def f32(raw: bytes, off: int) -> float:
    return struct.unpack_from("<f", raw, off)[0]


def is_canonical(addr: int) -> bool:
    return 0x10000 <= addr < (1 << 48)


def is_aligned(addr: int, alignment: int = 0x1000) -> bool:
    return addr % alignment == 0


def safe_name(name: str) -> str:
    return UNSAFE_FILENAME_RE.sub("_", name)


def read_first(path: Path, size: int) -> bytes:
    try:
        with path.open("rb") as handle:
            return handle.read(size)
    except OSError as exc:
        raise ToolError(f"cannot read {path}: {exc}") from exc


# ---------------------------------------------------------------------------
# ADB, maps and bounded /proc/<pid>/mem reads
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Mapping:
    start: int
    end: int
    perms: str
    offset: int
    path: str

    @property
    def size(self) -> int:
        return self.end - self.start


def parse_maps(text: str) -> list[Mapping]:
    rows: list[Mapping] = []
    for line in text.splitlines():
        parts = line.split(maxsplit=5)
        if len(parts) < 5:
            continue
        try:
            start, end = (int(x, 16) for x in parts[0].split("-"))
            offset = int(parts[2], 16)
        except ValueError:
            continue
        rows.append(Mapping(start, end, parts[1], offset,
                            parts[5].strip() if len(parts) > 5 else ""))
    return rows


class MapIndex:
    """Fast readable-range lookup over /proc/<pid>/maps."""

    def __init__(self, maps: list[Mapping]) -> None:
        ranges = sorted((m.start, m.end) for m in maps
                        if m.perms.startswith("r"))
        self._ranges = ranges
        self._starts = [r[0] for r in ranges]

    def readable(self, addr: int, size: int = 1) -> bool:
        if addr < 0 or size <= 0:
            return False
        idx = bisect.bisect_right(self._starts, addr) - 1
        return (0 <= idx < len(self._ranges)
                and addr + size <= self._ranges[idx][1])


def find_libil2cpp_base(maps: list[Mapping]) -> int:
    rows = [m for m in maps if "libil2cpp.so" in m.path]
    if not rows:
        raise ToolError("libil2cpp.so is not mapped in this process")
    bases = sorted({m.start - m.offset for m in rows})
    bases = [b for b in bases if b > 0 and is_aligned(b)]
    if not bases:
        raise ToolError(f"no aligned libil2cpp base in candidate mappings "
                        f"{[hex(m.start) for m in rows]}")
    if len(bases) > 1:
        raise ToolError("ambiguous libil2cpp bases: "
                        + ", ".join(hex(b) for b in bases))
    return bases[0]


class Device:
    """Thin ADB wrapper; only reads /proc/<pid>/mem and process metadata."""

    def __init__(self, adb: str, serial: str, package: str,
                 pid: int | None = None) -> None:
        self.adb = adb
        self.serial = serial
        self.package = package
        self.pid = pid

    # -- process plumbing -------------------------------------------------
    def _run(self, *args: str, timeout: float = 30) -> bytes:
        try:
            proc = subprocess.run(
                [self.adb, "-s", self.serial, *args],
                capture_output=True, timeout=timeout)
        except FileNotFoundError as exc:
            raise ToolError(f"adb executable not found: {self.adb}") from exc
        except subprocess.TimeoutExpired:
            return b""
        return proc.stdout

    def shell(self, *args: str, timeout: float = 30) -> bytes:
        return self._run("shell", *args, timeout=timeout)

    def exec_out(self, command: str, timeout: float = 20) -> bytes:
        # Every interpolated value in `command` is an integer built locally.
        return self._run("exec-out", command, timeout=timeout)

    def pids(self) -> list[int]:
        raw = self.shell("pidof", self.package,
                         timeout=15).decode("ascii", "replace")
        result = []
        for token in raw.split():
            try:
                result.append(int(token))
            except ValueError:
                pass
        return result

    def read_maps(self, pid: int) -> list[Mapping]:
        text = self.shell("cat", f"/proc/{pid}/maps", timeout=30).decode(
            "utf-8", "replace")
        maps = parse_maps(text)
        if not maps:
            raise ToolError(f"empty or unreadable /proc/{pid}/maps")
        return maps

    def find_pid(self) -> int:
        pids = self.pids()
        if not pids:
            raise ToolError(
                f"package {self.package} is not running (pidof returned none)")
        if len(pids) == 1:
            return pids[0]
        for pid in pids:
            try:
                maps = self.read_maps(pid)
            except ToolError:
                continue
            if any("libil2cpp.so" in m.path for m in maps):
                return pid
        return pids[0]

    # -- bounded reads ----------------------------------------------------
    def read_mem(self, addr: int, size: int,
                 timeout: float = DEVICE_TIMEOUT_S) -> bytes:
        """Read exactly `size` bytes (<= 8 MiB) via a timed-out device dd."""
        if self.pid is None:
            raise ToolError("process id is not resolved")
        if size <= 0:
            return b""
        if size > MAX_READ:
            raise ToolError(
                f"refusing a {size}-byte read (tool ceiling {MAX_READ} bytes)")
        page = addr & ~0xFFF
        pages = (addr - page + size + 0xFFF) // 0x1000
        if pages * 0x1000 > MAX_READ + 0x1000:
            raise ToolError(
                f"refusing a {pages * 0x1000}-byte aligned read at {addr:#x}")
        command = (f"timeout {DEVICE_TIMEOUT_S} dd if=/proc/{self.pid}/mem "
                   f"bs=4096 skip={page // 0x1000} count={pages} 2>/dev/null")
        last_len = 0
        for attempt in range(2):
            raw = self.exec_out(command, timeout=timeout + 10)
            last_len = len(raw)
            if len(raw) == pages * 0x1000:
                start = addr - page
                return raw[start:start + size]
            # A timed-out dd can outlive adb exec-out; kill it before retrying.
            self.cleanup_dd()
            if attempt == 0:
                time.sleep(0.15)
        raise ToolError(
            f"short memory read at {addr:#x}: got {last_len} of "
            f"{pages * 0x1000} bytes (dd timeout is {DEVICE_TIMEOUT_S}s)")

    def cleanup_dd(self) -> None:
        """Best-effort kill of a leftover dd reading this pid's memory."""
        if self.pid is None:
            return
        pattern = f"dd if=/proc/{self.pid}/mem"
        try:
            text = self.shell("ps", "-A", "-o", "PID,ARGS",
                              timeout=8).decode("utf-8", "replace")
            if not text.strip():
                text = self.shell("ps", "-A", timeout=8).decode(
                    "utf-8", "replace")
            found = False
            for line in text.splitlines():
                if pattern not in line:
                    continue
                token = line.strip().split(None, 1)[0]
                if token.isdigit():
                    found = True
                    self.shell("kill", "-9", token, timeout=5)
            if not found:
                # Some toybox builds need pkill; it is harmless when absent.
                self.shell("pkill", "-f", pattern, timeout=5)
        except (ToolError, OSError):
            pass

    def close(self) -> None:
        self.cleanup_dd()


# ---------------------------------------------------------------------------
# Arena records
# ---------------------------------------------------------------------------
@dataclass
class Record:
    index: int
    offset: int          # relative to the context arena
    subtype: int
    gold: int
    kills: int
    deaths: int
    assists: int
    assists_alt: int
    unit_ptr: int

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "offset": hexstr(self.offset),
            "offset_int": self.offset,
            "subtype": self.subtype,
            "gold": self.gold,
            "kills": self.kills,
            "deaths": self.deaths,
            "assists": self.assists,
            "assists_alt": self.assists_alt,
            "unit_ptr": hexstr(self.unit_ptr),
        }


def _record_at(raw: bytes, local: int, absolute: int) -> Record | None:
    if u32(raw, local) != 16 or u32(raw, local + 8) != 10000:
        return None
    try:
        feature = f32(raw, local + 0x0C)
    except struct.error:
        return None
    if not 3.20 <= feature <= 3.40:
        return None
    index = u32(raw, local + 0x20)
    if not RECORD_INDEX_BASE <= index < RECORD_INDEX_BASE + RECORD_INDEX_SPAN:
        return None
    gold_at = local + 0x4C
    return Record(
        index=index,
        offset=absolute,
        subtype=u32(raw, local + 0x04),
        gold=u32(raw, gold_at),
        kills=u32(raw, gold_at + 0x158),
        deaths=u32(raw, gold_at + 0xB8),
        assists=u32(raw, gold_at + 0xBC),
        assists_alt=u32(raw, gold_at + 0xC0),
        unit_ptr=u64(raw, local + 0x28),
    )


def scan_records(device: Device, context: int, start: int,
                 size: int) -> dict[int, Record]:
    """Find the ten record headers in [context+start, context+start+size)."""
    original_start = start
    start = max(0, start & ~3)  # record headers are 4-byte aligned
    size += original_start - start
    if start < 0 or size <= 0 or start + size > ARENA_SIZE:
        raise ToolError(
            f"record scan {start:#x}+{size:#x} escapes the "
            f"{ARENA_SIZE:#x} arena")
    end = start + size
    records: dict[int, Record] = {}
    for chunk_start in range(start, end, READ_CHUNK):
        chunk_end = min(end, chunk_start + READ_CHUNK)
        read_start = max(start, chunk_start - SCAN_OVERLAP)
        read_end = min(end, chunk_end + SCAN_OVERLAP)
        raw = device.read_mem(context + read_start, read_end - read_start)
        scan_lo = chunk_start - read_start
        # Include a candidate whose header ends exactly at read_end.
        limit = min(chunk_end, read_end - RECORD_HEADER_SIZE + 4)
        scan_hi = limit - read_start
        for local in range(scan_lo, scan_hi, 4):
            record = _record_at(raw, local, read_start + local)
            if record is None or record.index in records:
                continue
            records[record.index] = record
    if len(records) != EXPECTED_RECORDS:
        found = ", ".join(str(i) for i in sorted(records, reverse=True))
        raise ToolError(
            f"expected {EXPECTED_RECORDS} records in "
            f"{start:#x}+{size:#x}, found {len(records)}"
            + (f" (indexes {found})" if found else "")
            + "; widen --record-scan-start/--record-scan-size "
              "(session-local offsets can move, e.g. arena+0x4cd0)")
    return records


def sorted_records(records: dict[int, Record]) -> list[Record]:
    return [records[i] for i in sorted(records, reverse=True)]


def read_units(device: Device, records: dict[int, Record],
               maps: MapIndex) -> dict[int, bytes]:
    blobs: dict[int, bytes] = {}
    for record in sorted_records(records):
        if not maps.readable(record.unit_ptr, UNIT_SIZE):
            raise ToolError(
                f"record {record.index} unit pointer "
                f"{record.unit_ptr:#x} is not readable for "
                f"{UNIT_SIZE:#x} bytes")
        blob = device.read_mem(record.unit_ptr, UNIT_SIZE)
        hero_id = u32(blob, 0x28)
        entity_id = u32(blob, 0x3C)
        if hero_id == 0 or entity_id == 0:
            raise ToolError(
                f"record {record.index} pointer {record.unit_ptr:#x} does "
                f"not look like a unit object (heroID={hero_id}, "
                f"entityID={entity_id}); record+0x28 layout may have "
                "changed in this session")
        blobs[record.index] = blob
    return blobs


def save_unit_captures(out: Path, phase: str,
                       blobs: dict[int, bytes]) -> dict[int, Path]:
    paths: dict[int, Path] = {}
    for index in sorted(blobs, reverse=True):
        blob = blobs[index]
        hero_id = u32(blob, 0x28)
        name = HERO_NAME_BY_ID.get(hero_id) or HERO_BY_INDEX.get(
            index, f"idx{index}")
        path = out / f"unit_{index:02d}_{safe_name(name)}_{phase}.bin"
        path.write_bytes(blob)
        paths[index] = path
    return paths


# ---------------------------------------------------------------------------
# Unit diff
# ---------------------------------------------------------------------------
@dataclass
class UnitDiff:
    name: str
    label: str
    t0: bytes
    t1: bytes
    t0_file: str
    t1_file: str
    hero_id: int
    entity_id: int
    fields: list[dict]
    changed_offsets: list[int]
    identity_stable: bool
    record_index: int | None = None
    record_t0: dict | None = None
    record_t1: dict | None = None
    warnings: list[str] = dataclass_field(default_factory=list)

    def to_json(self) -> dict:
        record_delta = None
        if self.record_t0 is not None and self.record_t1 is not None:
            record_delta = {
                key: self.record_t1[key] - self.record_t0[key]
                for key in ("gold", "kills", "deaths", "assists")
            }
        return {
            "name": self.name,
            "label": self.label,
            "hero_id": self.hero_id,
            "entity_id": self.entity_id,
            "identity_stable": self.identity_stable,
            "t0_file": self.t0_file,
            "t1_file": self.t1_file,
            "record_index": self.record_index,
            "record_t0": self.record_t0,
            "record_t1": self.record_t1,
            "record_delta": record_delta,
            "unit_size": UNIT_SIZE,
            "changed_word_count": len(self.changed_offsets),
            "changed_word_offsets": [hexstr(off) for off in
                                     self.changed_offsets],
            "fields": self.fields,
            "warnings": self.warnings,
        }


def _field(offset: int, name: str, typ: str, t0_value: int | float | None,
           t1_value: int | float | None) -> dict:
    if isinstance(t0_value, (int, float)) and isinstance(t1_value,
                                                        (int, float)):
        delta = t1_value - t0_value
        if isinstance(delta, float):
            delta = round(delta, 6)
    else:
        delta = None
    return {
        "offset": offset,
        "offset_hex": hexstr(offset),
        "field": name,
        "type": typ,
        "t0": t0_value,
        "t1": t1_value,
        "delta": delta,
        "changed": t0_value != t1_value,
    }


def diff_unit(name: str, label: str, t0: bytes, t1: bytes,
              t0_file: Path | str, t1_file: Path | str,
              record_index: int | None = None,
              record_t0: dict | None = None,
              record_t1: dict | None = None) -> UnitDiff:
    if len(t0) < UNIT_SIZE or len(t1) < UNIT_SIZE:
        raise ToolError(
            f"{label}: unit capture is shorter than {UNIT_SIZE:#x} bytes")
    hero_id = u32(t0, 0x28)
    entity_id = u32(t0, 0x3C)
    hero_id_t1 = u32(t1, 0x28)
    entity_id_t1 = u32(t1, 0x3C)
    hp_current = u32(t0, 0x08)
    hp_current_t1 = u32(t1, 0x08)
    hp_max = u32(t0, 0x10)
    hp_max_t1 = u32(t1, 0x10)

    changed_offsets = [off for off in range(0, UNIT_SIZE, 4)
                       if u32(t0, off) != u32(t1, off)]

    fields: list[dict] = []
    for offset, field_name, typ in NAMED_FIELDS:
        row = _field(offset, field_name, typ, u32(t0, offset),
                     u32(t1, offset))
        fields.append(row)
        if offset == 0x08:
            ratio_t0 = (hp_current / hp_max) if hp_max else None
            ratio_t1 = (hp_current_t1 / hp_max_t1) if hp_max_t1 else None
            fields.append(_field(
                offset, "hp_ratio", "ratio",
                round(ratio_t0, 6) if ratio_t0 is not None else None,
                round(ratio_t1, 6) if ratio_t1 is not None else None))

    for offset in changed_offsets:
        if offset in NAMED_BY_OFFSET:
            continue
        fields.append(_field(offset, f"u32@0x{offset:04x}", "u32",
                             u32(t0, offset), u32(t1, offset)))

    warnings: list[str] = []
    identity_stable = (hero_id, entity_id) == (hero_id_t1, entity_id_t1)
    if not identity_stable:
        warnings.append(
            f"identity changed between t0 and t1: hero {hero_id}->{hero_id_t1}, "
            f"entity {entity_id}->{entity_id_t1}")
    if hero_id == 0 and entity_id == 0:
        warnings.append(
            "unit identity is empty at t0; record+0x28 may not point at a "
            "unit object in this session")
    if hp_max == 0 or hp_max_t1 == 0:
        warnings.append("hp_max is zero; hp_ratio cannot be computed")
    if hp_max != hp_max_t1:
        warnings.append(f"hp_max changed {hp_max}->{hp_max_t1}")
    if hp_max and hp_current > hp_max:
        warnings.append(
            f"hp_current {hp_current} exceeds hp_max {hp_max} at t0 "
            "(shields/overheal?)")
    if hp_max_t1 and hp_current_t1 > hp_max_t1:
        warnings.append(
            f"hp_current {hp_current_t1} exceeds hp_max {hp_max_t1} at t1 "
            "(shields/overheal?)")
    if u32(t0, 0x40) != entity_id:
        warnings.append(
            f"entity_id_dup {u32(t0, 0x40)} differs from entity_id "
            f"{entity_id} at t0")
    if u32(t1, 0x40) != entity_id_t1:
        warnings.append(
            f"entity_id_dup {u32(t1, 0x40)} differs from entity_id "
            f"{entity_id_t1} at t1")

    return UnitDiff(
        name=name,
        label=label,
        t0=t0,
        t1=t1,
        t0_file=str(t0_file),
        t1_file=str(t1_file),
        hero_id=hero_id,
        entity_id=entity_id,
        fields=fields,
        changed_offsets=changed_offsets,
        identity_stable=identity_stable,
        record_index=record_index,
        record_t0=record_t0,
        record_t1=record_t1,
        warnings=warnings,
    )


def build_matrix(units: list[UnitDiff]) -> list[dict]:
    offsets: set[int] = set(NAMED_BY_OFFSET)
    for unit in units:
        offsets.update(unit.changed_offsets)
    matrix: list[dict] = []
    for offset in sorted(offsets):
        name, typ = NAMED_BY_OFFSET.get(
            offset, (f"u32@0x{offset:04x}", "u32"))
        entries = []
        for unit in units:
            t0_value = u32(unit.t0, offset)
            t1_value = u32(unit.t1, offset)
            entries.append({
                "unit": unit.label,
                "name": unit.name,
                "t0": t0_value,
                "t1": t1_value,
                "delta": t1_value - t0_value,
                "changed": t0_value != t1_value,
            })
        matrix.append({
            "offset": offset,
            "offset_hex": hexstr(offset),
            "field": name,
            "type": typ,
            "changed_count": sum(1 for entry in entries if entry["changed"]),
            "units": entries,
        })
    return matrix


# ---------------------------------------------------------------------------
# Reports and CSV
# ---------------------------------------------------------------------------
def build_report(mode: str, dry_run: bool, seconds: float | None,
                 context: dict | None, scan: dict | None,
                 records_t0: dict[int, Record] | None,
                 records_t1: dict[int, Record] | None,
                 units: list[UnitDiff], clicks: list[dict],
                 warnings: list[str]) -> dict:
    global_warnings = list(warnings)
    for unit in units:
        for warning in unit.warnings:
            global_warnings.append(f"{unit.label}: {warning}")
    return {
        "schema": "kpl-live-diff-matrix-v1",
        "tool": "tools/live_diff_matrix.py",
        "created_at": datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "mode": mode,
        "dry_run": dry_run,
        "device_contacted": mode == "live",
        "seconds": seconds,
        "unit_size": UNIT_SIZE,
        "context": context,
        "scan": scan,
        "records_t0": ([r.as_dict() for r in sorted_records(records_t0)]
                       if records_t0 else None),
        "records_t1": ([r.as_dict() for r in sorted_records(records_t1)]
                       if records_t1 else None),
        "clicks": clicks,
        "units": [unit.to_json() for unit in units],
        "matrix": build_matrix(units),
        "warnings": global_warnings,
    }


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    return value


def write_outputs(out: Path, report: dict,
                  units: list[UnitDiff]) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "unit_diff.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    long_path = out / "unit_diff.csv"
    with long_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "unit", "label", "hero_id", "entity_id", "record_index",
            "offset", "offset_hex", "field", "type", "t0", "t1", "delta",
            "changed",
        ])
        for unit in units:
            for row in unit.fields:
                writer.writerow([
                    unit.name, unit.label, unit.hero_id, unit.entity_id,
                    unit.record_index if unit.record_index is not None else "",
                    row["offset"], row["offset_hex"], row["field"],
                    row["type"], _csv_value(row["t0"]), _csv_value(row["t1"]),
                    _csv_value(row["delta"]), int(bool(row["changed"])),
                ])

    matrix_path = out / "field_matrix.csv"
    with matrix_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        header = ["offset", "offset_hex", "field", "type", "changed_count"]
        for unit in units:
            header.extend([
                f"{unit.label}_t0", f"{unit.label}_t1",
                f"{unit.label}_delta", f"{unit.label}_changed",
            ])
        header.append("changed_units")
        writer.writerow(header)
        for row in report["matrix"]:
            values = {entry["unit"]: entry for entry in row["units"]}
            line = [row["offset"], row["offset_hex"], row["field"],
                    row["type"], row["changed_count"]]
            for unit in units:
                entry = values.get(unit.label)
                if entry is None:
                    line.extend(["", "", "", ""])
                else:
                    line.extend([
                        entry["t0"], entry["t1"], entry["delta"],
                        int(bool(entry["changed"])),
                    ])
            line.append(";".join(
                entry["unit"] for entry in row["units"]
                if entry["changed"]))
            writer.writerow(line)

    return {"json": json_path, "csv": long_path, "matrix_csv": matrix_path}


def print_summary(report: dict, paths: dict[str, Path]) -> None:
    units = report["units"]
    changed_units = sum(1 for unit in units if unit["changed_word_count"])
    print(f"mode={report['mode']} units={len(units)} "
          f"units_with_changes={changed_units} "
          f"matrix_rows={len(report['matrix'])}")
    for unit in units:
        hp_current = next((row for row in unit["fields"]
                           if row["field"] == "hp_current"), None)
        hp_ratio = next((row for row in unit["fields"]
                         if row["field"] == "hp_ratio"), None)
        if hp_current is not None:
            print(f"  {unit['label']:<24} hero={unit['hero_id']:>3} "
                  f"entity={unit['entity_id']:>5} "
                  f"hp={hp_current['t0']}->{hp_current['t1']} "
                  f"ratio={hp_ratio['t0']}->{hp_ratio['t1']} "
                  f"changed_words={unit['changed_word_count']}")
    print(f"wrote {paths['json']}")
    print(f"wrote {paths['csv']}")
    print(f"wrote {paths['matrix_csv']}")
    if report["warnings"]:
        print(f"warnings: {len(report['warnings'])}")
        for warning in report["warnings"]:
            print(f"  - {warning}")


# ---------------------------------------------------------------------------
# Offline / dry-run paths
# ---------------------------------------------------------------------------
def collect_offline_pairs(args: argparse.Namespace
                          ) -> tuple[list[tuple[str, Path, Path]], list[str]]:
    if bool(args.offline_t0) != bool(args.offline_t1):
        raise ToolError("--offline-t0 and --offline-t1 must be used together")
    if args.offline_t0 and args.offline_dir:
        raise ToolError(
            "--offline-t0/--offline-t1 and --offline-dir are mutually "
            "exclusive")
    if args.offline_t0:
        t0_path = args.offline_t0.resolve()
        t1_path = args.offline_t1.resolve()
        if not t0_path.is_file():
            raise ToolError(f"missing t0 capture: {t0_path}")
        if not t1_path.is_file():
            raise ToolError(f"missing t1 capture: {t1_path}")
        match = PAIR_RE.match(t0_path.name)
        name = match.group("name") if match else t0_path.stem
        return [(name, t0_path, t1_path)], []
    if args.offline_dir:
        directory = args.offline_dir.resolve()
        if not directory.is_dir():
            raise ToolError(f"--offline-dir is not a directory: {directory}")
        pairs: list[tuple[str, Path, Path]] = []
        warnings: list[str] = []
        for t0_path in sorted(directory.glob("unit_*_t0.bin")):
            match = PAIR_RE.match(t0_path.name)
            if not match:
                continue
            name = match.group("name")
            t1_path = t0_path.with_name(f"unit_{name}_t1.bin")
            if t1_path.is_file():
                pairs.append((name, t0_path, t1_path))
            else:
                warnings.append(
                    f"{t0_path.name}: no matching {t1_path.name}")
        if not pairs:
            raise ToolError(
                f"no unit_*_t0.bin / unit_*_t1.bin pairs in {directory}")
        return pairs, warnings
    raise ToolError(
        "offline mode needs --offline-dir or --offline-t0/--offline-t1")


def run_offline(args: argparse.Namespace, out: Path) -> int:
    pairs, warnings = collect_offline_pairs(args)
    if args.pid is not None:
        warnings.append("--pid is ignored in offline mode")
    units: list[UnitDiff] = []
    for name, t0_path, t1_path in pairs:
        t0 = read_first(t0_path, UNIT_SIZE)
        t1 = read_first(t1_path, UNIT_SIZE)
        if len(t0) < UNIT_SIZE:
            raise ToolError(
                f"{t0_path}: {len(t0)} bytes, need {UNIT_SIZE:#x}")
        if len(t1) < UNIT_SIZE:
            raise ToolError(
                f"{t1_path}: {len(t1)} bytes, need {UNIT_SIZE:#x}")
        units.append(diff_unit(
            name=name, label=name, t0=t0, t1=t1,
            t0_file=t0_path, t1_file=t1_path))
    report = build_report(
        mode="offline", dry_run=bool(args.dry_run),
        seconds=None, context=None, scan=None,
        records_t0=None, records_t1=None,
        units=units, clicks=[], warnings=warnings)
    paths = write_outputs(out, report, units)
    print_summary(report, paths)
    return 0


def run_plan(args: argparse.Namespace, out: Path) -> int:
    """Dry-run without offline inputs: describe the live plan, touch nothing."""
    out.mkdir(parents=True, exist_ok=True)
    plan = {
        "schema": "kpl-live-diff-matrix-plan-v1",
        "tool": "tools/live_diff_matrix.py",
        "created_at": datetime.now().astimezone().isoformat(
            timespec="seconds"),
        "mode": "dry-run",
        "device_contacted": False,
        "pid": args.pid,
        "package": args.package,
        "seconds": args.seconds,
        "record_scan": {
            "start": hexstr(args.record_scan_start),
            "size": hexstr(args.record_scan_size),
            "expected_records": EXPECTED_RECORDS,
            "max_read_bytes": MAX_READ,
            "read_chunk_bytes": READ_CHUNK,
            "device_timeout_seconds": DEVICE_TIMEOUT_S,
        },
        "context_chain": {
            "expression": f"libil2cpp_base + {hexstr(CONTEXT_GLOBAL_OFFSET)}",
            "stage_1": "[global] -> P1",
            "stage_2": "[P1] -> context",
            "arena_size": hexstr(ARENA_SIZE),
        },
        "unit_read_size": hexstr(UNIT_SIZE),
        "clicks": {
            "game_xy": list(PLAY_PAUSE_GAME_XY),
            "mapping": "tools/host_click.py",
            "play_then_pause": True,
            "seconds": args.seconds,
            "settle_seconds": args.settle,
        },
        "outputs": ["unit_diff.json", "unit_diff.csv", "field_matrix.csv"],
        "note": "No device access and no clicks in dry-run mode.",
    }
    path = out / "dry_run_plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print("dry-run plan (device not contacted)")
    print(f"  context: libil2cpp_base + {hexstr(CONTEXT_GLOBAL_OFFSET)}")
    print(f"  scan: {hexstr(args.record_scan_start)}+"
          f"{hexstr(args.record_scan_size)} (expect {EXPECTED_RECORDS})")
    print(f"  unit read: {hexstr(UNIT_SIZE)} per unit")
    print(f"  clicks: {PLAY_PAUSE_GAME_XY} via tools/host_click.py, "
          f"play {args.seconds}s then pause")
    print(f"wrote {path}")
    print("supply --offline-t0/--offline-t1 or --offline-dir to diff "
          "saved captures without a device")
    return 0


# ---------------------------------------------------------------------------
# Live path
# ---------------------------------------------------------------------------
def _host_click_module():
    if sys.platform != "win32":
        raise ToolError("live clicks require Windows (tools/host_click.py)")
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    try:
        import host_click  # noqa: PLC0415 - optional Windows-only module
    except Exception as exc:  # pragma: no cover - depends on host setup
        raise ToolError(f"cannot load tools/host_click.py: {exc}") from exc
    return host_click


def host_click_game(game_x: int, game_y: int) -> dict:
    """Click game-space (x, y) using the host_click MuMu window mapping."""
    host = _host_click_module()
    try:
        hwnd = host.find_mumu_window()
        host.user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        left, top, _cw, _ch = host.client_rect(hwnd)
        gx, gy, gw, _gh = host.game_area(hwnd)
        scale = gw / host.GAME_W
        sx = int(left + gx + game_x * scale)
        sy = int(top + gy + game_y * scale)
        point = host.wt.POINT()
        restore = bool(host.user32.GetCursorPos(host.ctypes.byref(point)))
        try:
            host.click(sx, sy)
        finally:
            if restore:
                host.user32.SetCursorPos(point.x, point.y)
    except SystemExit as exc:  # host_click raises SystemExit on setup errors
        raise ToolError(f"host click failed: {exc}") from exc
    except Exception as exc:
        raise ToolError(f"host click failed: {exc}") from exc
    return {
        "game_xy": [game_x, game_y],
        "host_xy": [sx, sy],
        "hwnd": hexstr(hwnd),
        "scale": round(scale, 6),
        "verified": False,
    }


def run_live(args: argparse.Namespace, out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    device = Device(args.adb, args.serial, args.package, args.pid)
    clicks: list[dict] = []
    try:
        pid = args.pid if args.pid is not None else device.find_pid()
        if pid <= 0:
            raise ToolError(f"invalid pid: {pid}")
        device.pid = pid
        maps = device.read_maps(pid)
        map_index = MapIndex(maps)
        base = find_libil2cpp_base(maps)
        global_addr = base + CONTEXT_GLOBAL_OFFSET
        if not map_index.readable(global_addr, 8):
            raise ToolError(
                f"context global {global_addr:#x} is not readable")
        p1 = u64(device.read_mem(global_addr, 8), 0)
        if not is_canonical(p1):
            raise ToolError(f"context global holds a non-pointer: {p1:#x}")
        if not map_index.readable(p1, 8):
            raise ToolError(f"P1 {p1:#x} is not readable")
        context = u64(device.read_mem(p1, 8), 0)
        if not is_canonical(context):
            raise ToolError(f"P1 holds a non-pointer: {context:#x}")
        if not map_index.readable(context, 0x100):
            raise ToolError(f"context {context:#x} is not readable")
        scan_start = args.record_scan_start
        scan_size = args.record_scan_size
        if not map_index.readable(context + scan_start, scan_size):
            raise ToolError(
                f"record scan range {scan_start:#x}+{scan_size:#x} is not "
                f"mapped at context {context:#x}")
        print(f"pid={pid} base={base:#x} P1={p1:#x} context={context:#x}",
              flush=True)

        print("scanning records for t0...", flush=True)
        records_t0 = scan_records(device, context, scan_start, scan_size)
        print(f"  records_t0={len(records_t0)}", flush=True)
        units_t0 = read_units(device, records_t0, map_index)
        paths_t0 = save_unit_captures(out, "t0", units_t0)
        print(f"  captured {len(units_t0)} unit objects "
              f"({UNIT_SIZE:#x} bytes each)", flush=True)

        print(f"click play at {PLAY_PAUSE_GAME_XY}, wait {args.seconds}s...",
              flush=True)
        clicks.append(host_click_game(*PLAY_PAUSE_GAME_XY))
        time.sleep(args.seconds)
        print("click pause...", flush=True)
        clicks.append(host_click_game(*PLAY_PAUSE_GAME_XY))
        time.sleep(args.settle)

        print("scanning records for t1...", flush=True)
        records_t1 = scan_records(device, context, scan_start, scan_size)
        print(f"  records_t1={len(records_t1)}", flush=True)
        # Playback can create new heap mappings; refresh the readable set.
        map_index_t1 = MapIndex(device.read_maps(pid))
        units_t1 = read_units(device, records_t1, map_index_t1)
        paths_t1 = save_unit_captures(out, "t1", units_t1)

        units: list[UnitDiff] = []
        for index in sorted(records_t0, reverse=True):
            record0 = records_t0[index]
            record1 = records_t1.get(index)
            if record1 is None:
                raise ToolError(f"record {index} disappeared at t1")
            blob0 = units_t0[index]
            blob1 = units_t1[index]
            hero_id = u32(blob0, 0x28)
            name = HERO_NAME_BY_ID.get(hero_id) or HERO_BY_INDEX.get(
                index, f"idx{index}")
            label = f"idx{index:02d}_{name}"
            units.append(diff_unit(
                name=name, label=label,
                t0=blob0, t1=blob1,
                t0_file=paths_t0[index], t1_file=paths_t1[index],
                record_index=index,
                record_t0=record0.as_dict(),
                record_t1=record1.as_dict()))

        warnings = [
            "click success at the play/pause control is not visually verified",
            "t0 is assumed to be paused; if the replay was playing, t0 drifts",
            "only u32-aligned words are compared; sub-word changes are not "
            "resolved independently",
            "hp values are normalized; absolute HP needs the panel maximum",
            "record offsets and unit pointers are session-local",
        ]
        report = build_report(
            mode="live", dry_run=False, seconds=args.seconds,
            context={
                "libil2cpp_base": hexstr(base),
                "context_global_offset": hexstr(CONTEXT_GLOBAL_OFFSET),
                "context_global": hexstr(global_addr),
                "P1": hexstr(p1),
                "context": hexstr(context),
                "arena_size": hexstr(ARENA_SIZE),
            },
            scan={
                "start": hexstr(scan_start),
                "size": hexstr(scan_size),
                "records_expected": EXPECTED_RECORDS,
                "records_found_t0": len(records_t0),
                "records_found_t1": len(records_t1),
                "max_read_bytes": MAX_READ,
                "read_chunk_bytes": READ_CHUNK,
                "device_timeout_seconds": DEVICE_TIMEOUT_S,
            },
            records_t0=records_t0, records_t1=records_t1,
            units=units, clicks=clicks, warnings=warnings)
        paths = write_outputs(out, report, units)
        print_summary(report, paths)
        return 0
    finally:
        device.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pid", type=int,
                        help="target PID; default: pidof --package, preferring "
                             "the process with libil2cpp mapped")
    parser.add_argument("--out", type=Path, required=True,
                        help="output directory below data/")
    parser.add_argument("--seconds", type=float, default=DEFAULT_SECONDS,
                        help=f"playback duration between the two clicks "
                             f"(default {DEFAULT_SECONDS})")
    parser.add_argument("--record-scan-start", type=parse_int,
                        default=DEFAULT_SCAN_START,
                        help="record scan start offset in the arena "
                             f"(default {DEFAULT_SCAN_START:#x})")
    parser.add_argument("--record-scan-size", type=parse_int,
                        default=DEFAULT_SCAN_SIZE,
                        help="record scan length in the arena "
                             f"(default {DEFAULT_SCAN_SIZE:#x})")
    parser.add_argument("--dry-run", action="store_true",
                        help="never contact the device; diff offline captures "
                             "if supplied, otherwise print the live plan")
    parser.add_argument("--offline-dir", type=Path,
                        help="directory with unit_<name>_t0.bin / "
                             "unit_<name>_t1.bin pairs")
    parser.add_argument("--offline-t0", type=Path,
                        help="single saved t0 unit capture")
    parser.add_argument("--offline-t1", type=Path,
                        help="single saved t1 unit capture")
    parser.add_argument("--settle", type=float, default=DEFAULT_SETTLE,
                        help="seconds to wait after the pause click before "
                             f"capturing t1 (default {DEFAULT_SETTLE})")
    parser.add_argument("--adb", default=ADB_DEFAULT,
                        help=f"adb executable (default {ADB_DEFAULT})")
    parser.add_argument("--serial", default=SERIAL_DEFAULT,
                        help=f"adb serial (default {SERIAL_DEFAULT})")
    parser.add_argument("--package", default=PACKAGE_DEFAULT,
                        help=f"game package (default {PACKAGE_DEFAULT})")
    return parser


def resolve_out(path: Path) -> Path:
    out = path.resolve()
    if out == DATA_ROOT or DATA_ROOT not in out.parents:
        raise ToolError(f"--out must be below {DATA_ROOT}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        out = resolve_out(args.out)
    except ToolError as exc:
        parser.error(str(exc))
    if args.seconds < 0:
        parser.error("--seconds must be >= 0")
    if args.settle < 0:
        parser.error("--settle must be >= 0")
    if args.record_scan_start < 0:
        parser.error("--record-scan-start must be >= 0")
    if args.record_scan_size <= 0:
        parser.error("--record-scan-size must be > 0")
    if args.record_scan_start + args.record_scan_size > ARENA_SIZE:
        parser.error(
            f"--record-scan-start + --record-scan-size exceeds "
            f"the {ARENA_SIZE:#x} arena")
    offline = bool(args.offline_t0 or args.offline_t1 or args.offline_dir)
    if offline and args.offline_dir and (args.offline_t0 or args.offline_t1):
        parser.error(
            "--offline-dir cannot be combined with --offline-t0/--offline-t1")
    try:
        if offline:
            return run_offline(args, out)
        if args.dry_run:
            return run_plan(args, out)
        return run_live(args, out)
    except (ToolError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
