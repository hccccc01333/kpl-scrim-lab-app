"""验证校对页重做：比分卡、字段来源开关、低置信度标记、左右分组。"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8766"
OUT = Path(__file__).resolve().parents[1] / ".audit-shots"
CHANNEL = "2f41bb5f40a84f2fb0b0b1d7cbc2f33e"


def main() -> int:
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1479, "height": 945}, locale="zh-CN").new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)[:180]))
        page.on("console", lambda m: errors.append("console:" + m.text[:130]) if m.type == "error" else None)

        page.goto(f"{BASE}/v3/#review/{CHANNEL}", wait_until="load", timeout=30000)
        page.wait_for_timeout(3500)
        try:
            b = page.get_by_role("button", name="稍后再看")
            if b.count():
                b.first.click(timeout=1500)
        except Exception:
            pass

        info = page.evaluate(
            """() => ({
                score: (document.querySelector('.rev-score strong')?.textContent || '').trim(),
                when: (document.querySelector('.rev-when')?.textContent || '').trim(),
                facts: Array.from(document.querySelectorAll('.rev-facts span')).map(s => s.textContent.replace(/\\s+/g,' ').trim()),
                srcMarks: document.querySelectorAll('.sv-src').length,
                lowMarks: document.querySelectorAll('.sv-low').length,
                inputs: document.querySelectorAll('.sv-input').length,
                split: document.querySelectorAll('.sv-split').length,
                toggle: !!document.querySelector('[data-review-action="toggle-sources"]'),
            })"""
        )
        print("比分:", info["score"], "| 副信息:", info["when"])
        print("事实:", info["facts"])
        print("默认来源徽标:", info["srcMarks"], "| 低置信度点:", info["lowMarks"])
        print("输入框:", info["inputs"], "| 左右分隔行:", info["split"], "| 开关:", info["toggle"])

        page.screenshot(path=str(OUT / "review-default.png"))

        # 打开来源徽标
        page.click('[data-review-action="toggle-sources"]')
        page.wait_for_timeout(1200)
        after = page.evaluate("() => document.querySelectorAll('.sv-src').length")
        print("打开开关后来源徽标:", after)
        page.screenshot(path=str(OUT / "review-sources.png"))

        print("JS 异常:", list(dict.fromkeys(errors))[:3] or "无")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
