"""Read-only frida hook: capture AdvanceFrameCommands(frameNo, frapInfo) per frame.

Attaches to the running client through the ADB frida integration.  The real
implementation of GameLogicHelper.AdvanceFrameCommands is mode-dependent and
its code pages are lazily decrypted (docs/advance_frame_binding.md §2), so the
agent polls the forwarding slot [0x40003374b000+0xb68] and the static thunk
0x40002d005fa4 every 2s and installs Interceptor hooks on whichever addresses
have executable code at that moment.  Events are tagged with the entry they
fired on: 'thunk' sees (this, frameNo, frapInfo) in args[0..2]; a slot target
('impl') sees (frameNo, frapInfo) in args[0..1].

Interceptor only reads arguments; nothing is called, injected or modified.
Run:  python tools/advance_frame_hook.py --out data/replays/_analysis/frida_capture_<date>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Live-verified addresses for this client instance (build 5247758,
# docs/advance_frame_binding.md §2).  Runtime addresses, not constants.
THUNK = 0x40002D005FA4
POINTER_TABLE = 0x40003374B000
POINTER_SLOT = 0xB68
IMPL_1103 = 0x40002C84CF7C
BOOT_SINGLE = 0x40002BEF047C
BOOT_INFO = 0x40002BEF44FC
# docs §5.153: replay playback advances via the message pump, not
# AdvanceFrameCommands.  DirectHandleMsg consumes each recorded command
# message (file VA 0x665d8e4 + deterministic lib base 0x400026201000).
DIRECT_HANDLE_MSG = 0x40002C85E8E4

JS = r"""
const THUNK = ptr('__THUNK__');
const DIRECT_HANDLE_MSG = ptr('__DHM__');
const POINTER_TABLE = ptr('__PTABLE__');
const POINTER_SLOT = __PSLOT__;
const BOOT_SINGLE = ptr('__BOOTSINGLE__');
const BOOT_INFO = ptr('__BOOTINFO__');

const attached = {};   // address string -> entry tag
const failed = {};     // address string -> last error

function hex(buf) {
  if (buf === null) return null;
  return Array.prototype.map.call(new Uint8Array(buf),
      function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
}
function safe(ptr, size) {
  try { return hex(ptr.readByteArray(size)); } catch (e) { return null; }
}

function decodeCommands(frap) {
  const rec = { frap: frap.toString(), klass: null, count: null,
                count_u32: null, array: null, array_raw: null,
                array_len: null, commands: [] };
  try {
    rec.klass = frap.readPointer().toString();
    rec.count = frap.add(0xc).readU8();
    rec.count_u32 = frap.add(0xc).readU32();
    const arr = frap.add(0x10).readPointer();
    rec.array = arr.toString();
    if (arr.isNull()) return rec;
    rec.array_raw = safe(arr, 0x30);
    // il2cpp Array: klass 0x0, monitor 0x8, bounds 0x10, max_length 0x18,
    // data 0x20.  A List<T> carries its array at 0x10 and size at 0x18.
    rec.array_len = arr.add(0x18).readU32();
    let data = arr.add(0x20);
    if (rec.array_len === 0 || rec.array_len >= 4096) {
      const items = arr.add(0x10).readPointer();
      if (!items.isNull()) {
        const itemsLen = items.add(0x18).readU32();
        if (itemsLen > 0 && itemsLen < 4096) {
          data = items.add(0x20);
          rec.array_len = itemsLen;
          rec.list_size = arr.add(0x18).readU32();
        }
      }
    }
    const n = Math.min(rec.count, rec.array_len, 64);
    for (let i = 0; i < n; i++) {
      const p = data.add(i * 8).readPointer();
      const cmd = { index: i, ptr: p.toString() };
      try {
        if (!p.isNull()) {
          cmd.klass = p.readPointer().toString();
          cmd.type = p.add(0xc).readU8();
          cmd.raw = safe(p, 0x18);
          const payload = p.add(0x10).readPointer();
          if (!payload.isNull()) {
            cmd.payload = payload.toString();
            cmd.payload_raw = safe(payload, 0x28);
          }
        } else { cmd.null = true; }
      } catch (e) { cmd.error = String(e); }
      rec.commands.push(cmd);
    }
  } catch (e) { rec.error = String(e); }
  return rec;
}

function onAdvance(tag) {
  // thunk entry: (this, frameNo, frapInfo) -- impl entry: (frameNo, frapInfo)
  return function (args) {
    advanceCount += 1;
    const frameNo = (tag === 'thunk' ? args[1] : args[0]).toInt32() >>> 0;
    const frap = tag === 'thunk' ? args[2] : args[1];
    const rec = { kind: 'advance', entry: tag, t: Date.now(), frameNo: frameNo };
    if (!frap.isNull()) {
      rec.commands = decodeCommands(frap);
    } else { rec.frap_null = true; }
    send(rec);
  };
}

function tryAttach(addr, tag) {
  const key = addr.toString();
  if (attached[key]) return;
  const prev = failed[key];
  // Encrypted pages decrypt lazily on first execution; retry transient
  // "cannot intercept/decode" failures every few ticks instead of giving up.
  if (prev) {
    if (prev.tries >= 40) return;
    if (!/decode|intercept|bug/i.test(prev.error)) return;
    if (ticks - prev.tick < 8) return;
  }
  try {
    Interceptor.attach(addr, onAdvance(tag));
    attached[key] = tag;
    delete failed[key];
    send({ kind: 'attached', entry: tag, address: key, t: Date.now() });
  } catch (e) {
    if (!prev) {
      failed[key] = { error: String(e), tries: 1, tick: ticks, tag: tag };
      send({ kind: 'attach-failed', entry: tag, address: key,
             error: String(e), t: Date.now() });
    } else {
      prev.tries += 1;
      prev.tick = ticks;
    }
  }
}

function tryAttachBoot(addr, name) {
  const key = addr.toString();
  if (attached[key]) return;
  const prev = failed[key];
  if (prev) {
    if (prev.tries >= 40 || !/decode|intercept|bug/i.test(prev.error)) return;
    if (ticks - prev.tick < 8) return;
  }
  try {
    Interceptor.attach(addr, function (args) {
      const obj = args[1];
      const rec = { kind: 'boot', hook: name, t: Date.now(),
                    self: args[0].toString(), obj: obj.toString() };
      try {
        if (!obj.isNull()) {
          rec.klass = obj.readPointer().toString();
          rec.raw = safe(obj, 0x80);
        }
      } catch (e) { rec.error = String(e); }
      send(rec);
    });
    attached[key] = 'boot-' + name;
    delete failed[key];
    send({ kind: 'attached', entry: 'boot-' + name, address: key, t: Date.now() });
  } catch (e) {
    if (!prev) {
      failed[key] = { error: String(e), tries: 1, tick: ticks };
      send({ kind: 'attach-failed', entry: 'boot-' + name, address: key,
             error: String(e), t: Date.now() });
    } else {
      prev.tries += 1;
      prev.tick = ticks;
    }
  }
}

function slots() {
  const targets = [
    [THUNK, 'thunk'],
    [POINTER_TABLE.add(POINTER_SLOT).readPointer(), 'impl'],
  ];
  return targets;
}

let ticks = 0;
function tryAttachDhm() {
  const key = DIRECT_HANDLE_MSG.toString();
  if (attached[key]) return;
  const prev = failed[key];
  if (prev) {
    if (prev.tries >= 40 || !/decode|intercept|bug/i.test(prev.error)) return;
    if (ticks - prev.tick < 8) return;
  }
  try {
    Interceptor.attach(DIRECT_HANDLE_MSG, function (args) {
      dhmCount += 1;
      // DirectHandleMsg(this, msg...) -- dump the receiver and first two
      // pointer args raw; field semantics decode offline.
      const rec = { kind: 'dhm', t: Date.now(), n: dhmCount,
                    a0: args[0].toString(), a1: args[1].toString(),
                    a2: args[2].toString() };
      try {
        rec.a0_klass = args[0].readPointer().toString();
        rec.a0_raw = safe(args[0], 0x30);
        if (!args[1].isNull()) {
          rec.a1_klass = args[1].readPointer().toString();
          rec.a1_raw = safe(args[1], 0x40);
        }
      } catch (e) { rec.error = String(e); }
      // keep the stream light: full dump for the first 200, then 1/8 sample
      if (dhmCount > 200 && (dhmCount % 8)) return;
      send(rec);
    });
    attached[key] = 'dhm';
    delete failed[key];
    send({ kind: 'attached', entry: 'dhm', address: key, t: Date.now() });
  } catch (e) {
    if (!prev) {
      failed[key] = { error: String(e), tries: 1, tick: ticks };
      send({ kind: 'attach-failed', entry: 'dhm', address: key,
             error: String(e), t: Date.now() });
    } else {
      prev.tries += 1;
      prev.tick = ticks;
    }
  }
}

function poll() {
  ticks += 1;
  let current = null;
  try { current = POINTER_TABLE.add(POINTER_SLOT).readPointer().toString(); }
  catch (e) { current = null; }
  const targets = slots();
  for (let i = 0; i < targets.length; i++) {
    if (targets[i][0].isNull()) continue;
    tryAttach(targets[i][0], targets[i][1]);
  }
  tryAttachBoot(BOOT_SINGLE, 'single');
  tryAttachBoot(BOOT_INFO, 'info');
  tryAttachDhm();
  if (ticks % 15 === 0) {
    send({ kind: 'status', t: Date.now(), ticks: ticks, slot_target: current,
           attached: Object.keys(attached).length, advance_sent: advanceCount });
  }
}

let advanceCount = 0;
let dhmCount = 0;

poll();
setInterval(poll, 2000);
"""


def attach(serial: str, pid: int):
    import frida
    manager = frida.get_device_manager()
    try:
        device = manager.get_device(serial, timeout=5)
    except Exception:
        device = frida.get_device(serial, timeout=5)
    return device.attach(pid)


def resolve_pid(serial: str, pid: int) -> int:
    if pid > 0:
        return pid
    out = subprocess.run(["adb", "-s", serial, "shell", "pidof",
                          "com.tencent.tmgp.sgame"],
                         capture_output=True, text=True, timeout=15).stdout.split()
    if not out:
        raise SystemExit("game process not found; is the client running?")
    return int(out[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="127.0.0.1:16384")
    parser.add_argument("--pid", type=int, default=0,
                        help="target pid (0 = auto-discover the client)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--duration", type=float, default=900.0,
                        help="seconds to keep the hook installed (0 = until interrupted)")
    args = parser.parse_args()
    out = args.out.resolve()
    data_root = (ROOT / "data").resolve()
    if data_root not in out.parents:
        parser.error("--out must stay inside project data/")
    out.mkdir(parents=True, exist_ok=True)
    jsonl = (out / "advance_frames.jsonl").open("a", encoding="utf-8")

    source = (JS.replace("__THUNK__", hex(THUNK))
                .replace("__DHM__", hex(DIRECT_HANDLE_MSG))
                .replace("__PTABLE__", hex(POINTER_TABLE))
                .replace("__PSLOT__", str(POINTER_SLOT))
                .replace("__BOOTSINGLE__", hex(BOOT_SINGLE))
                .replace("__BOOTINFO__", hex(BOOT_INFO)))

    pid = resolve_pid(args.serial, args.pid)
    args.pid = pid
    session = attach(args.serial, args.pid)
    print(f"attached pid {args.pid}", flush=True)
    script = session.create_script(source)

    state = {"advance": 0, "boot": 0, "attached": 0}
    done = {"flag": False}

    def on_message(message, data):
        if message.get("type") == "error":
            print(f"script error: {message.get('description')}", flush=True)
            return
        payload = message.get("payload")
        if not isinstance(payload, dict):
            return
        kind = payload.get("kind")
        if kind == "attached":
            state["attached"] += 1
            print(f"hooked {payload.get('entry')} @ {payload.get('address')}",
                  flush=True)
        elif kind == "attach-failed":
            print(f"attach failed {payload.get('entry')} @ "
                  f"{payload.get('address')}: {payload.get('error')}", flush=True)
        elif kind == "advance":
            state["advance"] += 1
            if state["advance"] % 200 == 0:
                cmds = payload.get("commands") or {}
                print(f"frame {payload.get('frameNo')} ({payload.get('entry')}): "
                      f"total={state['advance']} count={cmds.get('count')}",
                      flush=True)
        elif kind == "boot":
            state["boot"] += 1
            print(f"boot packet #{state['boot']} ({payload.get('hook')})",
                  flush=True)
        elif kind == "status":
            print(f"status: attached={payload.get('attached')} "
                  f"slot={payload.get('slot_target')}", flush=True)
        jsonl.write(json.dumps(payload, ensure_ascii=False) + "\n")
        jsonl.flush()

    script.on("message", on_message)
    script.load()
    deadline = time.time() + args.duration if args.duration > 0 else None
    try:
        while not done["flag"]:
            if deadline is not None and time.time() >= deadline:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            script.unload()
        except Exception:
            pass
        summary = {"advance_events": state["advance"], "boot_events": state["boot"],
                   "hooked_entries": state["attached"], "out": jsonl.name,
                   "pid": args.pid, "duration_s": args.duration}
        (out / "hook_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print("done: " + json.dumps(summary, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
