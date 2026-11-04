#!/usr/bin/env python3
"""Read-only live GameCore context/CS snapshot (H4 fixture).

Captures qword-level layout only: addresses, field values, buffer pointers and
hashes. It does not dump raw strings, account data, tokens or player names.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.frapinfo_live_probe import Adb, Reader  # noqa: E402

GAMECORE = "libGameCore.so"


def hx(value: int | None) -> str | None:
    return f"0x{value:x}" if value else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default="D:/MuMuPlayer/nx_main/adb.exe")
    ap.add_argument("--serial", default="127.0.0.1:16384")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--freeze", action="store_true", help="SIGSTOP/SIGCONT the game process")
    args = ap.parse_args()

    adb = Adb(args.adb, args.serial)
    pids = adb.pids("com.tencent.tmgp.sgame")
    if not pids:
        print("game process not found", file=sys.stderr)
        return 2
    pid = pids[0]
    maps = adb.read_maps(pid)
    base = None
    for m in maps:
        if m.path.endswith("/" + GAMECORE) and m.offset == 0:
            base = m.start
            break
    if base is None:
        print("libGameCore base not found", file=sys.stderr)
        return 2

    stopped = False
    if args.freeze:
        subprocess.run([args.adb, "-s", args.serial, "shell", "kill", "-STOP", str(pid)],
                       check=False)
        stopped = True
        time.sleep(0.3)

    try:
        r = Reader(adb, pid, maps)
        def q(addr: int) -> int | None:
            return r.u64(addr)

        view = []
        p = base + 0x4FF4520
        for _ in range(4):
            v = q(p)
            view.append({"addr": hx(p), "value": hx(v)})
            if not v:
                break
            p = v
        context = int(view[2]["value"], 16) if len(view) >= 3 and view[2].get("value") else None

        cs = []
        p = base + 0x4FF5DE8
        for _ in range(4):
            v = q(p)
            cs.append({"addr": hx(p), "value": hx(v)})
            if not v:
                break
            p = v
        cs_array = int(cs[1]["value"], 16) if len(cs) >= 2 and cs[1].get("value") else None

        context_fields = []
        if context:
            for off in range(0, 0x1000, 8):
                context_fields.append({"offset": f"0x{off:03x}", "value": hx(q(context + off))})

        cs_slots = []
        if cs_array:
            for i in range(8):
                obj = q(cs_array + 8 * i)
                slot = {"slot": i, "object": hx(obj)}
                if obj and r.readable(obj, 0x100):
                    slot.update({
                        "vtable": hx(q(obj)),
                        "cap": q(obj + 0x20) & 0xFFFFFFFF if q(obj + 0x20) is not None else None,
                        "pending": q(obj + 0x24) & 0xFFFFFFFF if q(obj + 0x24) is not None else None,
                        "data": hx(q(obj + 0x18)),
                        "cursor2c": q(obj + 0x2C) & 0xFFFFFFFF if q(obj + 0x2C) is not None else None,
                        "cursor30": q(obj + 0x30) & 0xFFFFFFFF if q(obj + 0x30) is not None else None,
                        "cursor34": q(obj + 0x34) & 0xFFFFFFFF if q(obj + 0x34) is not None else None,
                    })
                    data = q(obj + 0x18)
                    pending = slot.get("pending") or 0
                    if data and pending:
                        raw = r.read(data, min(pending, 256))
                        slot["data_sha256"] = hashlib.sha256(raw or b"").hexdigest()
                        slot["data_bytes"] = len(raw or b"")
                cs_slots.append(slot)

        result = {
            "schema": "kpl-gamecore-context-snapshot-v1",
            "pid": pid,
            "base": hx(base),
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "frozen": stopped,
            "viewChain": view,
            "context": hx(context),
            "contextFields": context_fields,
            "csChain": cs,
            "csArray": hx(cs_array),
            "csSlots": cs_slots,
            "coreState": hx(q(base + 0x544CBD0)),
            "threadId": hx(q(base + 0x542A8A8)),
        }
    finally:
        if stopped:
            subprocess.run([args.adb, "-s", args.serial, "shell", "kill", "-CONT", str(pid)],
                           check=False)

    if not context:
        print("context not resident", file=sys.stderr)
        return 3
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(args.out), "context": hx(context), "csArray": hx(cs_array),
                      "csSlots": len(cs_slots), "frozen": stopped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
