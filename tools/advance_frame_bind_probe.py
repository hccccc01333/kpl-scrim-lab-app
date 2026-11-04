"""Capture the AdvanceFrameCommands implementation candidates from a live client.

Extends tools/live_replay_methods.py with the two IGameLogicHelper implementation
candidates (FrameWindowHelper / GameLogicHelper, docs 5.126) and decodes the
captured code pages with the established XOR 0xE3 page cipher (docs 5.131 area).
Decoded pages are verified against the on-disk libil2cpp.so copy when the mapped
offset is known. Read-only: no injection, no calls, no device writes; captures go
to a new directory under data/ (previous captures preserved).

Run AFTER docs/device_setup.md step 1 (MuMu installed, game logged in, replay
loaded to the point where the helpers are JIT-touched). ADB must be a root shell.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import live_replay_methods as base  # noqa: E402

XOR_KEY = 0xE3
IL2CPP_DISK = ROOT / "data" / "replays" / "_analysis" / "libil2cpp.so"

BIND_TARGETS = {
    "FrameWindowHelper": {"AdvanceFrameCommands"},
    "GameLogicHelper": {"AdvanceFrameCommands"},
    "IGameLogicHelper": {"AdvanceFrameCommands"},
    "FrameWindow": {"HandleFraqBootSingle", "HandleFraqBootInfo"},
    "CSDT_FRAPBOOT_INFO": {"unpack"},
}


def decode_pages(code: bytes) -> bytes:
    return bytes(b ^ XOR_KEY for b in code)


def verify_against_disk(raw: bytes, mapped_file_offset: int) -> dict:
    """Page encryption is page-granular (docs 5.7/5.141): report both readings
    (raw and XOR 0xE3) against the disk copy so the consumer picks the
    matching one per method."""
    if not IL2CPP_DISK.exists():
        return {"disk_check": "libil2cpp.so copy missing"}
    disk = IL2CPP_DISK.read_bytes()
    if mapped_file_offset < 0 or mapped_file_offset + len(raw) > len(disk):
        return {"disk_check": "mapped offset outside disk copy"}
    disk_slice = disk[mapped_file_offset:mapped_file_offset + len(raw)]
    xored = decode_pages(raw)
    raw_match = sum(1 for a, b in zip(raw, disk_slice) if a == b)
    xor_match = sum(1 for a, b in zip(xored, disk_slice) if a == b)
    return {"disk_check_raw": f"{raw_match}/{len(raw)}",
            "disk_check_xor": f"{xor_match}/{len(xored)}",
            "encrypted_page": xor_match > raw_match}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=base.__dict__.get("ADB_DEFAULT", "D:/MuMuPlayer/nx_main/adb.exe"))
    parser.add_argument("--serial", default="127.0.0.1:16384")
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--max-heap-mb", type=int, default=96)
    args = parser.parse_args()
    out = args.capture_dir.resolve()
    ignored_root = (ROOT / "data").resolve()
    if ignored_root not in out.parents:
        parser.error("Captures must be inside project data/")
    if out.exists():
        parser.error("Use a new capture directory; existing captures are preserved")

    # Reuse the proven capture pipeline with the binding targets.
    base.TARGETS = BIND_TARGETS
    argv = sys.argv[1:]
    rc = base.main_with(argv) if hasattr(base, "main_with") else None
    if rc is None:
        # live_replay_methods.main reads sys.argv itself; emulate by injection.
        sys.argv = [sys.argv[0]] + argv
        rc = base.main()
    if rc != 0:
        print("Capture produced no verified hits; see the output above.", file=sys.stderr)
        return rc

    # Decode the captured code pages (XOR 0xE3) and verify against the disk copy.
    hits = json.loads((out / "methods.json").read_text(encoding="utf-8"))["hits"]
    decoded_dir = out / "decoded"
    decoded_dir.mkdir(exist_ok=True)
    summary = []
    for hit in hits:
        code_file = out / hit["code_file"]
        if not code_file.exists():
            continue
        raw = code_file.read_bytes()
        decoded = decode_pages(raw)
        decoded_path = decoded_dir / hit["code_file"]
        decoded_path.write_bytes(decoded)
        row = {"owner": hit["owner"], "method": hit["method"], "token": hit["token"],
               "pointer": hit["pointer"], "mapped_file_offset": hit["mapped_file_offset"]}
        row.update(verify_against_disk(raw, int(hit["mapped_file_offset"], 16)))
        (decoded_dir / (hit["code_file"] + ".json")).write_text(
            json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append(row)
    (out / "decoded" / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"decoded": len(summary),
                      "next": "compare the two AdvanceFrameCommands implementations' "
                              "decoded code; the active one is identified by a memory "
                              "watch during playback (device session)",
                      "rows": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
