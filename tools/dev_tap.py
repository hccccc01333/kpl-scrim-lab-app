"""Raw touchscreen tap for the MuMu guest (bypasses 王者荣耀's injected-input block).

`adb shell input tap` is ignored by the client (InputManager injection is
filtered), so this drives the emulated "Xiaomi Touchscreen" evdev node directly
with protocol-B multitouch events.  The touch panel is natively 900x1600
portrait while the game view is 1600x900 landscape; --rot cw maps landscape
(x,y) -> portrait (y, H-1-x), --rot ccw -> (W-1-y, x).

Usage: python tools/dev_tap.py X Y [--rot cw] [--serial 127.0.0.1:16384]
"""
from __future__ import annotations

import argparse
import subprocess

EVENT = "/dev/input/event4"
PORTRAIT_W = 900
PORTRAIT_H = 1600


def landscape_to_portrait(x: int, y: int, rot: str) -> tuple[int, int]:
    if rot == "cw":
        return y, PORTRAIT_H - 1 - x
    return PORTRAIT_W - 1 - y, x


def tap_events(tx: int, ty: int, tracking_id: int = 9001) -> str:
    ev = f"sendevent {EVENT}"
    return " && ".join([
        f"{ev} 3 47 0",            # ABS_MT_SLOT 0
        f"{ev} 3 57 {tracking_id}",  # ABS_MT_TRACKING_ID
        f"{ev} 3 53 {tx}",         # ABS_MT_POSITION_X
        f"{ev} 3 54 {ty}",         # ABS_MT_POSITION_Y
        f"{ev} 1 325 1",           # BTN_TOOL_FINGER down
        f"{ev} 1 330 1",           # BTN_TOUCH down
        f"{ev} 0 0 0",             # SYN_REPORT
        f"{ev} 3 57 -1",           # release
        f"{ev} 1 330 0",
        f"{ev} 1 325 0",
        f"{ev} 0 0 0",
    ])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x", type=int)
    parser.add_argument("y", type=int)
    parser.add_argument("--rot", default="cw", choices=("cw", "ccw"))
    parser.add_argument("--serial", default="127.0.0.1:16384")
    args = parser.parse_args()
    tx, ty = landscape_to_portrait(args.x, args.y, args.rot)
    shell = tap_events(tx, ty)
    result = subprocess.run(
        ["adb", "-s", args.serial, "shell", shell],
        capture_output=True, text=True, timeout=30)
    if result.returncode or result.stderr.strip():
        print(result.stdout, result.stderr, file=__import__("sys").stderr)
        return result.returncode or 1
    print(f"tap landscape=({args.x},{args.y}) -> portrait=({tx},{ty})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
