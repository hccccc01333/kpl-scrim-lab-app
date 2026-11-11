#!/usr/bin/env python3
"""Validate a GameCore host fixture directory (stdlib only).

Checks:
  meta.json                 required schema/fields/types, sha256 format
  init/abc_header.json      schema, replay_id/build/frame cross-checks
  init/players.json         per-player fields, order/entity uniqueness,
                            consistency with abc_header.json
  context/*.json            optional H4 snapshot shape (read-only capture)
  init/init_cmds.index.json optional init-command index shape
  frames/, state/           optional file counts only

This validator never reads a .abc by default and never writes to the fixture.
Pass --abc to verify meta.abc_sha256 against the original replay file.

Exit codes: 0 valid, 1 invalid, 2 usage/IO (argparse or missing directory).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

META_SCHEMA = "kpl-gamecore-fixture-v1"
INIT_SCHEMA = "kpl-gamecore-fixture-init-v1"
CONTEXT_SCHEMA = "kpl-gamecore-context-snapshot-v1"

META_REQUIRED = ["schema", "replay_id", "build", "total_frames", "abc_sha256"]
META_ALLOWED = {
    "schema", "replay_id", "build", "app", "res", "game_mode", "map_id",
    "total_frames", "abc_sha256", "capture_pid", "capture_note",
}
PLAYER_REQUIRED = [
    "order", "camp", "position", "heroId", "entityId", "self", "bot",
    "nameSha256",
]
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.facts: dict[str, Any] = {}

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.match(value) is not None


def load_json(path: Path, report: Report, label: str, required: bool) -> Any | None:
    if not path.is_file():
        if required:
            report.error(f"{label}: missing file {path}")
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        report.error(f"{label}: cannot read {path}: {exc}")
    except json.JSONDecodeError as exc:
        report.error(f"{label}: invalid JSON in {path}: {exc}")
    return None


def check_meta(meta: Any, report: Report) -> dict[str, Any] | None:
    if not isinstance(meta, dict):
        report.error("meta.json: top level must be an object")
        return None
    for key in META_REQUIRED:
        if key not in meta:
            report.error(f"meta.json: missing required key '{key}'")
    unknown = sorted(set(meta) - META_ALLOWED)
    if unknown:
        report.error(f"meta.json: unexpected key(s): {', '.join(unknown)}")

    if meta.get("schema") != META_SCHEMA:
        report.error(f"meta.json: schema must be '{META_SCHEMA}'")
    for key in ("replay_id", "build"):
        value = meta.get(key)
        if not isinstance(value, str) or not value:
            report.error(f"meta.json: '{key}' must be a non-empty string")
    for key in ("app", "res", "game_mode", "capture_note"):
        if key in meta and not isinstance(meta[key], str):
            report.error(f"meta.json: '{key}' must be a string")
    if "map_id" in meta and not is_int(meta["map_id"]):
        report.error("meta.json: 'map_id' must be an integer")
    if "capture_pid" in meta and not (
        meta["capture_pid"] is None or is_int(meta["capture_pid"])
    ):
        report.error("meta.json: 'capture_pid' must be an integer or null")

    total = meta.get("total_frames")
    if not is_int(total) or total <= 0:
        report.error("meta.json: 'total_frames' must be an integer > 0")
    if not is_sha(meta.get("abc_sha256")):
        report.error("meta.json: 'abc_sha256' must be 64 lowercase hex characters")

    if report.ok:
        report.facts["replay_id"] = meta["replay_id"]
        report.facts["build"] = meta["build"]
        report.facts["total_frames"] = meta["total_frames"]
        report.facts["game_mode"] = meta.get("game_mode")
    return meta


def check_players(players: Any, report: Report, label: str) -> list[dict[str, Any]] | None:
    if not isinstance(players, list):
        report.error(f"{label}: must be a JSON array")
        return None
    parsed: list[dict[str, Any]] = []
    orders: list[int] = []
    entities: list[int] = []
    for index, player in enumerate(players):
        where = f"{label}[{index}]"
        if not isinstance(player, dict):
            report.error(f"{where}: must be an object")
            continue
        for key in PLAYER_REQUIRED:
            if key not in player:
                report.error(f"{where}: missing '{key}'")
        unknown = sorted(set(player) - set(PLAYER_REQUIRED))
        if unknown:
            report.warn(f"{where}: unknown key(s): {', '.join(unknown)}")
        order = player.get("order")
        camp = player.get("camp")
        position = player.get("position")
        hero = player.get("heroId")
        entity = player.get("entityId")
        if not is_int(order):
            report.error(f"{where}: 'order' must be an integer")
        else:
            orders.append(order)
        if not is_int(camp) or camp not in (1, 2):
            report.error(f"{where}: 'camp' must be 1 or 2")
        if not is_int(position) or position < 0:
            report.error(f"{where}: 'position' must be a non-negative integer")
        if not is_int(hero) or hero <= 0:
            report.error(f"{where}: 'heroId' must be a positive integer")
        if not is_int(entity) or entity <= 0:
            report.error(f"{where}: 'entityId' must be a positive integer")
        else:
            entities.append(entity)
        for key in ("self", "bot"):
            if not isinstance(player.get(key), bool):
                report.error(f"{where}: '{key}' must be a boolean")
        name_sha = player.get("nameSha256")
        if name_sha is not None and not is_sha(name_sha):
            report.error(f"{where}: 'nameSha256' must be null or 64 lowercase hex")
        parsed.append(player)

    if len(orders) != len(set(orders)):
        report.error(f"{label}: duplicate 'order' values")
    elif orders and sorted(orders) != list(range(len(orders))):
        report.error(f"{label}: 'order' values must be contiguous 0..{len(orders) - 1}")
    if len(entities) != len(set(entities)):
        report.error(f"{label}: duplicate 'entityId' values")
    if len(players) != 10:
        report.warn(f"{label}: {len(players)} players (ten-player target expects 10)")
    report.facts["players"] = len(players)
    return parsed


def check_header(header: Any, meta: dict[str, Any], report: Report) -> tuple[
    list[dict[str, Any]] | None, dict[str, Any] | None
]:
    if not isinstance(header, dict):
        report.error("abc_header.json: top level must be an object")
        return None, None
    if header.get("schema") != INIT_SCHEMA:
        report.error(f"abc_header.json: schema must be '{INIT_SCHEMA}'")
    if header.get("replay_id") != meta.get("replay_id"):
        report.error(
            "abc_header.json: replay_id does not match meta.json "
            f"({header.get('replay_id')!r} != {meta.get('replay_id')!r})"
        )

    inner = header.get("header")
    if not isinstance(inner, dict):
        report.error("abc_header.json: 'header' must be an object")
        inner = None
    if inner is not None:
        if "totalFrameNum" in inner:
            value = inner["totalFrameNum"]
            if not is_int(value) or value <= 0:
                report.error("abc_header.json: header.totalFrameNum must be an integer > 0")
            elif value != meta.get("total_frames"):
                report.error(
                    "abc_header.json: header.totalFrameNum != meta.total_frames "
                    f"({value} != {meta.get('total_frames')})"
                )
        else:
            report.warn("abc_header.json: header.totalFrameNum is absent")
        builds = inner.get("builds")
        if isinstance(builds, list):
            if not builds or not all(isinstance(b, str) and b for b in builds):
                report.error("abc_header.json: header.builds must be a non-empty string array")
            elif builds[-1] != meta.get("build"):
                report.error(
                    "abc_header.json: last build != meta.build "
                    f"({builds[-1]!r} != {meta.get('build')!r})"
                )
        elif builds is not None:
            report.error("abc_header.json: header.builds must be an array")
        if "versions" in inner and not (
            isinstance(inner["versions"], list)
            and all(isinstance(v, str) for v in inner["versions"])
        ):
            report.error("abc_header.json: header.versions must be a string array")
        report.facts["header_build"] = builds[-1] if isinstance(builds, list) and builds else None
        report.facts["header_total_frames"] = inner.get("totalFrameNum")

    kv = header.get("kv")
    if kv is not None:
        if not isinstance(kv, dict):
            report.error("abc_header.json: 'kv' must be an object")
        else:
            items = kv.get("items")
            count = kv.get("count")
            if not isinstance(items, list):
                report.error("abc_header.json: kv.items must be an array")
            if not is_int(count):
                report.error("abc_header.json: kv.count must be an integer")
            elif isinstance(items, list) and count != len(items):
                report.error(
                    f"abc_header.json: kv.count {count} != len(kv.items) {len(items)}"
                )
            if isinstance(items, list):
                for index, item in enumerate(items):
                    if not isinstance(item, dict):
                        report.error(f"abc_header.json: kv.items[{index}] must be an object")
                        continue
                    conf_type = item.get("confType")
                    conf_value = item.get("confValue")
                    if not is_int(conf_type) or not 0 <= conf_type <= 255:
                        report.error(
                            f"abc_header.json: kv.items[{index}].confType must be 0..255"
                        )
                    if not is_int(conf_value) or not 0 <= conf_value <= 65535:
                        report.error(
                            f"abc_header.json: kv.items[{index}].confValue must be 0..65535"
                        )
                report.facts["kv_items"] = len(items)

    scalar = header.get("scalarBlock")
    if scalar is not None:
        if not isinstance(scalar, dict):
            report.error("abc_header.json: 'scalarBlock' must be an object")
        else:
            for key in ("offset", "length"):
                value = scalar.get(key)
                if value is not None and not is_int(value):
                    report.error(f"abc_header.json: scalarBlock.{key} must be integer or null")
            if scalar.get("sha256") is not None and not is_sha(scalar.get("sha256")):
                report.error("abc_header.json: scalarBlock.sha256 must be null or 64 hex")

    header_players = None
    if "players" in header:
        header_players = check_players(header["players"], report, "abc_header.json.players")
    return header_players, inner


def compare_players(
    header_players: list[dict[str, Any]] | None,
    player_file: list[dict[str, Any]] | None,
    report: Report,
) -> None:
    if header_players is None or player_file is None:
        return
    if len(header_players) != len(player_file):
        report.error(
            "players.json: length differs from abc_header.json.players "
            f"({len(player_file)} != {len(header_players)})"
        )
        return
    keys = ("order", "camp", "position", "heroId", "entityId")
    for index, (a, b) in enumerate(zip(player_file, header_players)):
        for key in keys:
            if a.get(key) != b.get(key):
                report.error(
                    f"players.json[{index}].{key} {a.get(key)!r} != "
                    f"abc_header.json.players[{index}].{key} {b.get(key)!r}"
                )


def check_context(snapshot: Any, report: Report) -> None:
    if not isinstance(snapshot, dict):
        report.error("context_snapshot.json: top level must be an object")
        return
    if snapshot.get("schema") != CONTEXT_SCHEMA:
        report.error(f"context_snapshot.json: schema must be '{CONTEXT_SCHEMA}'")
    context = snapshot.get("context")
    if context is not None and not isinstance(context, str):
        report.error("context_snapshot.json: 'context' must be a hex string or null")
    slots = snapshot.get("csSlots")
    if isinstance(slots, list):
        if len(slots) != 8:
            report.warn(f"context_snapshot.json: csSlots has {len(slots)} entries (expected 8)")
        for index, slot in enumerate(slots):
            if not isinstance(slot, dict):
                report.error(f"context_snapshot.json: csSlots[{index}] must be an object")
            elif slot.get("slot") != index:
                report.error(f"context_snapshot.json: csSlots[{index}].slot != {index}")
        report.facts["context_cs_slots"] = len(slots)
    elif slots is not None:
        report.error("context_snapshot.json: 'csSlots' must be an array")
    report.facts["context_is_host_constructed"] = False
    report.facts["context_note"] = (
        "read-only live snapshot; this does not mean the host constructed a context"
    )


def check_init_cmd_index(index: Any, report: Report) -> None:
    if isinstance(index, list):
        report.facts["init_cmd_index_entries"] = len(index)
    elif isinstance(index, dict):
        entries = index.get("commands", index.get("entries"))
        if isinstance(entries, list):
            report.facts["init_cmd_index_entries"] = len(entries)
    else:
        report.error("init_cmds.index.json: must be an array or object")


def check_abc_sha(abc_path: Path, expected: str, report: Report) -> None:
    if not abc_path.is_file():
        report.error(f"--abc: file not found: {abc_path}")
        return
    digest = hashlib.sha256()
    try:
        with abc_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        report.error(f"--abc: cannot read {abc_path}: {exc}")
        return
    actual = digest.hexdigest()
    if actual != expected:
        report.error(f"--abc: sha256 {actual} != meta.abc_sha256 {expected}")
    else:
        report.facts["abc_sha256_verified"] = True


def count_files(directory: Path, patterns: tuple[str, ...]) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for path in directory.iterdir() if path.is_file() and path.suffix in patterns)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("fixture", type=Path, help="fixture directory (contains meta.json)")
    ap.add_argument("--abc", type=Path, help="optional .abc path to verify meta.abc_sha256")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    ap.add_argument("--json", action="store_true", help="print a machine-readable report")
    args = ap.parse_args()

    fixture = args.fixture
    if not fixture.is_dir():
        print(f"validate_fixture: not a directory: {fixture}", file=sys.stderr)
        return 2

    report = Report()
    meta = load_json(fixture / "meta.json", report, "meta.json", required=True)
    meta = check_meta(meta, report) if meta is not None else None

    if meta is not None:
        header = load_json(
            fixture / "init" / "abc_header.json", report,
            "abc_header.json", required=False,
        )
        header_players = None
        if header is not None:
            header_players, _ = check_header(header, meta, report)

        players_doc = load_json(
            fixture / "init" / "players.json", report,
            "players.json", required=False,
        )
        player_file = None
        if players_doc is not None:
            player_file = check_players(players_doc, report, "players.json")
        compare_players(header_players, player_file, report)

        context = load_json(
            fixture / "context" / "context_snapshot.json", report,
            "context_snapshot.json", required=False,
        )
        if context is not None:
            check_context(context, report)

        cmd_index = load_json(
            fixture / "init" / "init_cmds.index.json", report,
            "init_cmds.index.json", required=False,
        )
        if cmd_index is not None:
            check_init_cmd_index(cmd_index, report)

        if args.abc is not None:
            expected = meta.get("abc_sha256")
            if is_sha(expected):
                check_abc_sha(args.abc, expected, report)
            else:
                report.error("--abc: meta.json has no valid abc_sha256 to compare against")

        report.facts["frame_files"] = count_files(fixture / "frames", (".json", ".bin"))
        report.facts["state_files"] = count_files(fixture / "state", (".jsonl",))

    if args.strict:
        report.errors.extend(report.warnings)
        report.warnings = []

    result = {
        "ok": report.ok,
        "fixture": str(fixture),
        "facts": report.facts,
        "errors": report.errors,
        "warnings": report.warnings,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"fixture: {fixture}")
        for key, value in report.facts.items():
            print(f"  {key}: {value}")
        for warning in report.warnings:
            print(f"  W: {warning}")
        for error in report.errors:
            print(f"  E: {error}")
        print("OK" if report.ok else "INVALID")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
