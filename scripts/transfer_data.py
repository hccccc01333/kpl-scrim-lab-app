"""跨机器传递赛训数据的命令行入口：`python scripts/transfer_data.py export|import`。

A 机（长期爬营地数据的那台）：
    python scripts/transfer_data.py export --out 赛训数据-20261111.zip

B 机（想在新机器上看/继续用）：
    python scripts/transfer_data.py import --bundle 赛训数据-20261111.zip
    # 先看一眼会补什么，不写入：
    python scripts/transfer_data.py import --bundle 赛训数据-20261111.zip --dry-run

加截图：`--with-screenshots`；连原始回放一起搬：`--with-replays`（几个 GB）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_transfer import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
