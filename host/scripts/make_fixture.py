#!/usr/bin/env python3
"""Build a GameCore host golden fixture from a replay .abc (read-only).

The fixture deliberately excludes account/token/avatar/openID fields. Player
names are stored only as SHA-256; the host needs entity/hero/camp/slot, not
display names.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import replay_parser  # noqa: E402
KV_SIG = bytes.fromhex("010032000200010003001900")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_kv(data: bytes) -> dict | None:
    pos = data.find(KV_SIG)
    if pos < 2:
        return None
    count = struct.unpack_from("<H", data, pos - 2)[0]
    items = []
    off = pos
    for _ in range(count):
        if off + 4 > len(data):
            break
        conf_type = data[off]
        conf_value = struct.unpack_from(">H", data, off + 1)[0]
        items.append({"confType": conf_type, "confValue": conf_value})
        off += 4
    return {"offset": pos - 2, "count": count, "items": items, "end": off}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--abc", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    data = args.abc.read_bytes()
    header = replay_parser.parse_header(data)
    report = replay_parser.inspect_replay(data)
    blocks = report.get("blocks") or []
    kv = parse_kv(data)
    first_player = min((b["start"] for b in blocks), default=None)
    scalar_len = None
    if kv and first_player and kv["end"] <= first_player:
        scalar_len = first_player - kv["end"]

    replay_id = args.abc.stem.split("_")[0] + "_" + args.abc.stem.split("_")[1]
    out = args.out
    (out / "init").mkdir(parents=True, exist_ok=True)
    (out / "frames").mkdir(exist_ok=True)
    (out / "context").mkdir(exist_ok=True)
    (out / "state").mkdir(exist_ok=True)

    meta = {
        "schema": "kpl-gamecore-fixture-v1",
        "replay_id": replay_id,
        "build": header["builds"][-1] if header.get("builds") else None,
        "app": header["versions"][0] if header.get("versions") else None,
        "res": header["versions"][1] if header.get("versions") else None,
        "game_mode": f"mapType_{header.get('mapType')}",
        "map_id": header.get("mapId"),
        "total_frames": header.get("totalFrameNum") or report.get("frames", {}).get("records"),
        "abc_sha256": sha(data),
        "capture_pid": None,
        "capture_note": "read-only .abc fixture; no login, no game process, no account fields",
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    players = []
    for block in blocks:
        name = block.get("name") or ""
        players.append({
            "order": block.get("order"),
            "camp": block.get("camp"),
            "position": block.get("position"),
            "heroId": block.get("heroId"),
            "entityId": block.get("entityId"),
            "self": bool(block.get("self")),
            "bot": bool(block.get("bot")),
            "nameSha256": sha(name.encode("utf-8")) if name else None,
        })

    init = {
        "schema": "kpl-gamecore-fixture-init-v1",
        "replay_id": replay_id,
        "header": {
            "versions": header.get("versions"),
            "builds": header.get("builds"),
            "localHeroId": header.get("localHeroId"),
            "mapType": header.get("mapType"),
            "mapId": header.get("mapId"),
            "totalFrameNum": header.get("totalFrameNum"),
            "layoutSupported": header.get("layoutSupported"),
            "profile": header.get("profile"),
            "headerSha256": sha(data[: first_player or 0]),
        },
        "kv": kv,
        "scalarBlock": {
            "offset": kv["end"] if kv else None,
            "length": scalar_len,
            "sha256": sha(data[kv["end"]:first_player]) if kv and scalar_len else None,
        },
        "players": players,
        "frameStream": {
            "start": (report.get("frames") or {}).get("start"),
            "end": (report.get("frames") or {}).get("end"),
            "records": (report.get("frames") or {}).get("records"),
            "firstSequence": (report.get("frames") or {}).get("firstSequence"),
            "lastSequence": (report.get("frames") or {}).get("lastSequence"),
        },
    }
    (out / "init" / "abc_header.json").write_text(
        json.dumps(init, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "init" / "players.json").write_text(
        json.dumps(players, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({
        "out": str(out),
        "replay_id": replay_id,
        "build": meta["build"],
        "total_frames": meta["total_frames"],
        "players": len(players),
        "kv": kv["count"] if kv else None,
        "scalar_len": scalar_len,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
