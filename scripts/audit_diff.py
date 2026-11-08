"""收口前后像素对比：同一路由、同一视口、同一等待时长，逐张算差异。"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = Path(__file__).resolve().parents[1] / ".audit-shots"
BEFORE = BASE / "before"
AFTER = BASE / "after"


def pixels(img: Image.Image) -> int:
    return img.width * img.height


def main() -> int:
    if not BEFORE.exists() or not AFTER.exists():
        print("缺少 before/ 或 after/ 目录")
        return 1

    print(f"{'页面':<22}{'尺寸一致':<10}{'差异像素':>12}{'占比':>10}   结论")
    print("-" * 72)
    worst = 0.0
    for p in sorted(BEFORE.glob("*.png")):
        q = AFTER / p.name
        if not q.exists():
            print(f"{p.stem:<22}{'缺文件':<10}")
            continue
        a = Image.open(p).convert("RGB")
        b = Image.open(q).convert("RGB")
        same_size = a.size == b.size
        if not same_size:
            print(f"{p.stem:<22}{'否':<10}{'-':>12}{'-':>10}   {a.size} -> {b.size}")
            continue
        diff = ImageChops.difference(a, b)
        bbox = diff.getbbox()
        if bbox is None:
            print(f"{p.stem:<22}{'是':<10}{0:>12}{'0.00%':>10}   完全一致")
            continue
        # 统计非零像素
        gray = diff.convert("L")
        hist = gray.histogram()
        nonzero = sum(hist[1:])
        total = pixels(a)
        ratio = nonzero / total
        worst = max(worst, ratio)
        verdict = "一致" if ratio == 0 else ("轻微" if ratio < 0.001 else ("明显" if ratio < 0.02 else "**回归**"))
        print(f"{p.stem:<22}{'是':<10}{nonzero:>12,}{ratio*100:>9.3f}%   {verdict}  bbox={bbox}")

    print("-" * 72)
    print(f"最大差异占比 {worst*100:.3f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
