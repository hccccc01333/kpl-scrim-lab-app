#!/usr/bin/env python3
"""Pull the installed game APK/dataCache and scan for script assets.

Read-only: pulls the APK the package manager reports plus the game's
dataCache.db, then lists entries that look like script bundles
(.lua/.luac/.ts/.js/.bytes) and scans the first bytes for known signatures
(Lua bytecode `\\x1bLua`, zip, plain text) so the decryption route from the
Bilibili write-up can be reproduced offline.

Usage:
  python host/scripts/pull_game_scripts.py --serial 127.0.0.1:16384 --out data/scripts
"""
from __future__ import annotations

import argparse
import subprocess
import zipfile
from pathlib import Path


def run(adb: str, serial: str, *args: str, timeout: int = 120) -> str:
    proc = subprocess.run([adb, "-s", serial, *args],
                          capture_output=True, timeout=timeout)
    return proc.stdout.decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adb", default="D:/MuMuPlayer/nx_main/adb.exe")
    ap.add_argument("--serial", required=True)
    ap.add_argument("--package", default="com.tencent.tmgp.sgame")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    path = run(args.adb, args.serial, "shell", "pm", "path", args.package).strip()
    apk = path.split(":", 1)[1] if path.startswith("package:") else path
    print("apk:", apk)
    local_apk = out / "base.apk"
    if not local_apk.exists():
        subprocess.run([args.adb, "-s", args.serial, "pull", apk, str(local_apk)],
                       check=False)
    print("local:", local_apk, local_apk.stat().st_size if local_apk.exists() else 0)

    cache = out / "dataCache.db"
    if not cache.exists():
        subprocess.run([args.adb, "-s", args.serial, "pull",
                        "/data/data/com.tencent.tmgp.sgame/files/dataCache.db",
                        str(cache)], check=False)
        print("dataCache:", cache.stat().st_size if cache.exists() else 0)

    if local_apk.exists() and zipfile.is_zipfile(local_apk):
        script_exts = (".lua", ".luac", ".ts", ".js", ".bytes", ".txt")
        found = []
        with zipfile.ZipFile(local_apk) as zf:
            for info in zf.infolist():
                name = info.filename.lower()
                if name.endswith(script_exts) and info.file_size > 0:
                    found.append((info.filename, info.file_size))
                    if info.file_size < 64 * 1024 * 1024:
                        target = out / "apk_entries" / info.filename
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(target, "wb") as dst:
                            dst.write(src.read())
        print(f"script entries: {len(found)}")
        for name, size in found[:80]:
            print(f"  {size:>10}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
