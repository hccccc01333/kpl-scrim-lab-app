"""Host-side click into the MuMu window (Windows SendInput).

The guest ignores injected Android input (adb input / sendevent), so this
drives the MuMuNxMain window with real Win32 mouse events, exactly like a user
clicking.  Coordinates are given in the game's 1600x900 landscape space and
scaled to the window client area.

Usage: python tools/host_click.py X Y [--dry] [--restore-cursor]
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import sys
import time

GAME_W, GAME_H = 1600, 900

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PM_REMOVE = 1


def find_mumu_window() -> int:
    """Return the main visible top-level window of MuMuNxMain / MuMuNxDevice."""
    candidates: list[tuple[int, int, str]] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def enum_proc(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if not title:
            return True
        # any process whose executable lives under the MuMu install dir
        hprocess = kernel32.OpenProcess(0x0400, False, pid.value)
        exe = ctypes.create_unicode_buffer(512)
        if hprocess:
            size = wt.DWORD(512)
            try:
                # psapi GetModuleFileNameExW via kernel32 fallback
                psapi = ctypes.windll.psapi
                psapi.GetModuleFileNameExW(hprocess, None, exe,
                                           ctypes.byref(size))
            finally:
                kernel32.CloseHandle(hprocess)
        path = exe.value.lower()
        if "mumu" in path or "mumu" in title.lower():
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                time.sleep(0.05)
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            if w > 400 and h > 300:
                device = 1 if ("nxddevice" in path or "安卓设备" in title) else 0
                candidates.append((hwnd, device, w * h, title))
        return True

    user32.EnumWindows(enum_proc, 0)
    if not candidates:
        raise SystemExit("no MuMu window found; is the emulator visible?")
    candidates.sort(key=lambda c: (-c[1], -c[2]))
    return candidates[0][0]


def client_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wt.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    pt = wt.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y, rect.right, rect.bottom


def click(sx: int, sy: int) -> None:
    user32.SetCursorPos(sx, sy)
    time.sleep(0.05)
    user32.SetCursorPos(sx, sy)
    user32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
    time.sleep(0.06)
    user32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP


def game_area(hwnd: int) -> tuple[int, int, int, int]:
    """Locate the landscape game view inside the MuMu window: find contiguous
    non-black row bands (the custom title bar is a short band; the game view is
    the tall one) and return the tallest band's rect."""
    from PIL import ImageGrab
    left, top, cw, ch = client_rect(hwnd)
    img = ImageGrab.grab(bbox=(left, top, left + cw, top + ch)).convert("L")
    px = img.load()
    w, h = img.size
    row_content = []
    for y in range(h):
        bright = 0
        for x in range(0, w, 8):
            if px[x, y] > 16:
                bright += 1
                if bright >= 8:
                    break
        row_content.append(bright >= 8)
    bands = []
    y = 0
    while y < h:
        if row_content[y]:
            start = y
            gap = 0
            end = y
            while y < h and gap <= 8:
                if row_content[y]:
                    end = y
                    gap = 0
                else:
                    gap += 1
                y += 1
            bands.append((start, end - start + 1))
        else:
            y += 1
    tall = [b for b in bands if b[1] >= 300]
    if not tall:
        raise SystemExit(f"could not locate the game view; bands={bands}")
    top_band, band_h = max(tall, key=lambda b: b[1])
    # The game renders 16:9.  MuMu letterboxes it inside the client area, but
    # the letterbox rows are not always black (window chrome), so the band scan
    # can span the whole client and put every click ~20px too high.  Fit a
    # centered 16:9 viewport inside the detected band instead.
    scale = min(w / GAME_W, band_h / GAME_H)
    view_w = int(round(GAME_W * scale))
    view_h = int(round(GAME_H * scale))
    return (w - view_w) // 2, top_band + (band_h - view_h) // 2, view_w, view_h


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("x", type=int, help="game-space x (0..1599)")
    parser.add_argument("y", type=int, help="game-space y (0..899)")
    parser.add_argument("--dry", action="store_true",
                        help="print the computed host point and exit")
    args = parser.parse_args()

    hwnd = find_mumu_window()
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    left, top, cw, ch = client_rect(hwnd)
    gx, gy, gw, gh = game_area(hwnd)
    scale = gw / GAME_W
    sx = int(left + gx + args.x * scale)
    sy = int(top + gy + args.y * scale)
    print(f"hwnd={hwnd:#x} client=({left},{top},{cw}x{ch}) "
          f"game_area=({gx},{gy},{gw}x{gh}) scale={scale:.4f} "
          f"-> host=({sx},{sy})", flush=True)
    if args.dry:
        return 0
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    click(sx, sy)
    user32.SetCursorPos(pt.x, pt.y)
    print("clicked", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
