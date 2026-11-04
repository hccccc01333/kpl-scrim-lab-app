"""Run the local server in a restart loop for daily use.

Ctrl+C stops both the child server and this watchdog. Unexpected exits are
restarted after a short delay; logs remain in the child process output.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / 'data' / 'watchdog.pid'


def main():
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding='ascii')
    try:
        while True:
            try:
                code = subprocess.call([sys.executable, str(ROOT / 'server.py')], cwd=str(ROOT))
            except KeyboardInterrupt:
                return 0
            if code == 0:
                return 0
            print(f'服务异常退出（{code}），2 秒后重启…', flush=True)
            time.sleep(2)
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == '__main__':
    raise SystemExit(main())
