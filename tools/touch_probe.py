"""Diagnostic: does the game's Java window receive MotionEvents at all?

Hooks Activity.dispatchTouchEvent / InputEventReceiver.dispatchInputEvent in
the running client and logs every delivered touch for --duration seconds.
Read-only observation of input delivery (no modification).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

JS = r"""
Java.perform(function () {
  try {
    var Activity = Java.use('android.app.Activity');
    Activity.dispatchTouchEvent.overload('android.view.MotionEvent')
      .implementation = function (ev) {
        send({ kind: 'touch', where: 'activity',
               action: ev.getActionMasked(),
               x: ev.getX(), y: ev.getY(),
               source: ev.getSource(), t: Date.now() });
        return this.dispatchTouchEvent(ev);
      };
    send({ kind: 'hooked', where: 'activity' });
  } catch (e) { send({ kind: 'hook-failed', where: 'activity', error: String(e) }); }
  try {
    var R = Java.use('android.view.InputEventReceiver');
    R.dispatchInputEvent.overload('int', 'android.view.InputEvent')
      .implementation = function (seq, ev) {
        var kind = 'other';
        try { kind = ev.getClass().getSimpleName().toString(); } catch (e) {}
        send({ kind: 'input', cls: kind, t: Date.now() });
        return this.dispatchInputEvent(seq, ev);
      };
    send({ kind: 'hooked', where: 'receiver' });
  } catch (e) { send({ kind: 'hook-failed', where: 'receiver', error: String(e) }); }
});
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, default=2052)
    parser.add_argument("--duration", type=float, default=20.0)
    args = parser.parse_args()
    import frida
    device = frida.get_device("127.0.0.1:16384", timeout=5)
    session = device.attach(args.pid)
    script = session.create_script(JS)
    seen = {"n": 0}

    def on_message(message, data):
        if message.get("type") == "error":
            print("script error:", message.get("description"))
            return
        payload = message.get("payload", {})
        seen["n"] += 1
        print(json.dumps(payload, ensure_ascii=False), flush=True)

    script.on("message", on_message)
    script.load()
    time.sleep(args.duration)
    script.unload()
    print(f"total events observed: {seen['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
