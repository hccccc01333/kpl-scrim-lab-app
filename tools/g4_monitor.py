"""Monitor the replay frame counter and capture state on change (G4).

Polls the enable flag and current frame counter from the live client.
When the frame advances, captures a wide memory snapshot around the
game context for offline diff. Read-only via ADB root shell.
"""
import subprocess, struct, time, json, sys
from pathlib import Path

ADB = ["adb", "-s", "127.0.0.1:16384"]
PID = 2052
ENABLE_FLAG = 0x4000344916A4
SINGLETON_PTR = 0x4000340D2D20
OUT = Path("data/replays/_analysis/client_probe_20261103/g4_monitor")

def mem(addr, size):
    page = addr & ~4095
    count = (addr - page + size + 4095) // 4096
    raw = subprocess.run(ADB + ["exec-out", f"dd if=/proc/{PID}/mem bs=4096 skip={page//4096} count={count} 2>/dev/null"],
                         capture_output=True, timeout=30).stdout
    if len(raw) < (addr - page) + size:
        raise ValueError(f"short read at {addr:#x}")
    return raw[addr - page: addr - page + size]

def u32(addr): return int.from_bytes(mem(addr, 4), "little")
def u64(addr): return int.from_bytes(mem(addr, 8), "little")

def snapshot(tag, singleton):
    OUT.mkdir(parents=True, exist_ok=True)
    data = mem(singleton - 0x1000, 0x8000)
    f = OUT / f"snap_{tag}_{int(time.time())}.bin"
    f.write_bytes(data)
    return {"tag": tag, "file": str(f), "frame": int.from_bytes(data[0x1000+0x24:0x1000+0x28], "little"),
            "size": len(data), "sha256": __import__("hashlib").sha256(data).hexdigest()[:16]}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    print("monitoring frame counter and enable flag...", flush=True)
    prev_frame = -1
    prev_enable = -1
    snaps = []
    for i in range(600):  # 10 min at 1s intervals
        try:
            enable = u32(ENABLE_FLAG)
            singleton = u64(SINGLETON_PTR)
            if singleton < 0x10000:
                time.sleep(1); continue
            frame = int.from_bytes(mem(singleton + 0x24, 4), "little")
            if i % 30 == 0:
                print(f"  [{i}] enable={enable} frame={frame} singleton={singleton:#x}", flush=True)
            if frame != prev_frame and frame != 0xFFFFFFFF and frame >= 0:
                print(f"  FRAME CHANGED: {prev_frame} -> {frame}!", flush=True)
                tag = f"frame_{frame}"
                snaps.append(snapshot(tag, singleton))
                # also capture a wider region on first change
                if len(snaps) == 1:
                    wide = mem(singleton - 0x10000, 0x20000)
                    wf = OUT / f"wide_first_{int(time.time())}.bin"
                    wf.write_bytes(wide)
                    print(f"  wide snapshot saved: {wf}", flush=True)
            prev_frame = frame if frame != 0xFFFFFFFF else prev_frame
            prev_enable = enable
        except (ValueError, subprocess.TimeoutExpired) as e:
            print(f"  [{i}] read error: {e}", flush=True)
        time.sleep(1.0)
    (OUT / "monitor_result.json").write_text(
        json.dumps({"snapshots": snaps, "samples": i + 1}, ensure_ascii=False))
    print(f"done: {len(snaps)} snapshots", flush=True)

if __name__ == "__main__":
    main()
