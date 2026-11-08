"""验证校对页：比分、素材来源、十行草稿、复核与入库控件。"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"
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

        page.goto(f"{BASE}/#review/{CHANNEL}", wait_until="load", timeout=30000)
        page.wait_for_timeout(3500)
        try:
            b = page.get_by_role("button", name="稍后再看")
            if b.count():
                b.first.click(timeout=1500)
        except Exception:
            pass

        info = page.evaluate(
            """() => ({
                score: (document.querySelector('.ed-score strong')?.textContent || '').trim(),
                meta: (document.querySelector('.ed-meta')?.textContent || '').trim(),
                sources: document.querySelectorAll('.ed-sources li').length,
                sourcesOff: document.querySelectorAll('.ed-sources li.is-off').length,
                sourcesRequired: document.querySelectorAll('.ed-sources li.is-required').length,
                rows: document.querySelectorAll('.ed-table tbody tr').length,
                splits: document.querySelectorAll('.ed-table tbody tr.is-split').length,
                inputs: document.querySelectorAll('.ed-input').length,
                notes: !!document.querySelector('[data-review-notes]'),
                saveDraft: !!document.querySelector('[data-review-action="save-draft"]'),
                saveFormal: !!document.querySelector('[data-review-action="save-formal"]'),
                review: !!document.querySelector('[data-review-action="review"]'),
            })"""
        )
        print("比分:", info["score"], "| 副信息:", info["meta"])
        print("素材来源:", info["sources"], "类 | 缺失:", info["sourcesOff"], "| 必采:", info["sourcesRequired"])
        print("草稿行:", info["rows"], "| 左右分隔:", info["splits"], "| 输入框:", info["inputs"])
        print("复核备注:", info["notes"], "| 保存草稿:", info["saveDraft"], "| 入库:", info["saveFormal"], "| 标记复核:", info["review"])

        page.screenshot(path=str(OUT / "review-current.png"))

        problems = []
        if info["rows"] != 10:
            problems.append(f"草稿行应为 10，实际 {info['rows']}")
        if info["inputs"] < 90:
            problems.append(f"可编辑输入框应至少 90，实际 {info['inputs']}")
        if not all((info["notes"], info["saveDraft"], info["saveFormal"], info["review"])):
            problems.append("复核/保存控件缺失")
        if errors:
            problems.append("JS 异常: " + "; ".join(list(dict.fromkeys(errors))[:3]))
        print("结论:", "通过" if not problems else "失败：" + "；".join(problems))
        browser.close()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
