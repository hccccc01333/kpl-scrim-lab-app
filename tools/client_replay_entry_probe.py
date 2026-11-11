"""Read-only Android checks for an installed client's external replay-file entry.

Does not launch/login to the game, change files, inject, or read process memory.
An absent ACTION_VIEW handler does not exclude internal UI/deep-link replay paths.
"""
from __future__ import annotations

import argparse
import json
import subprocess


def probe(adb: str, serial: str, timeout: float = 8) -> dict:
    prefix = [adb, "-s", serial]

    def run(*args: str) -> dict:
        try:
            result = subprocess.run(prefix + list(args), capture_output=True, timeout=timeout)
            return {"exit_code": result.returncode,
                    "text": (result.stdout + result.stderr).decode("utf-8", "replace").strip()}
        except subprocess.TimeoutExpired:
            return {"timed_out": True}

    boot = run("shell", "getprop", "sys.boot_completed")
    package = run("shell", "dumpsys", "package", "com.tencent.tmgp.sgame")
    # Keep only version fields, not the package's account/permission/provider state.
    if "text" in package:
        package["text"] = "\n".join(line.strip() for line in package["text"].splitlines()
                                    if "versionCode=" in line or "versionName=" in line)
    foreground = run("shell", "dumpsys", "activity", "activities")
    if "text" in foreground:
        foreground["text"] = "\n".join(line.strip() for line in foreground["text"].splitlines()
                                       if "topResumedActivity=" in line or "mResumedActivity=" in line)
    queries = {}
    for label, args in {
        "abc_file": ("-d", "file:///sdcard/replay_probe.abc"),
        "abc_content": ("-d", "content://local/replay.abc", "-t", "application/octet-stream"),
        "smoba_scheme": ("-d", "smoba://"),
    }.items():
        queries[label] = run("shell", "cmd", "package", "query-activities", "--brief",
                             "-a", "android.intent.action.VIEW", *args,
                             "-p", "com.tencent.tmgp.sgame")
    return {"boot": boot, "package_version": package, "foreground": foreground,
            "view_queries": queries,
            "limitations": [
                "Probe URIs test Android routing only; no replay file is opened.",
                "A registered smoba handler does not identify its supported replay parameters.",
                "Activity/process state cannot determine the in-game login or replay page.",
                "No conclusion about ABC format compatibility follows from these queries.",
            ]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="D:/MuMuPlayer/nx_main/adb.exe")
    parser.add_argument("--serial", default="127.0.0.1:16384")
    parser.add_argument("--timeout", type=float, default=8)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    print(json.dumps(probe(args.adb, args.serial, args.timeout), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
