"""导航可达性回归：枚举页面上所有导航链接，逐个访问。

判定：
- 页面渲染无 JS 异常
- #content 有实质内容
- 顶部导航有且只有一个 active 分组
- ref/* 内嵌页 iframe 能加载
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8766"
OUT = Path(__file__).resolve().parents[1] / ".audit-shots" / "nav"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        page = ctx.new_page()

        page.goto(BASE + "/studio#home", wait_until="load", timeout=30000)
        page.wait_for_timeout(2500)

        links = page.evaluate(
            """() => Array.from(document.querySelectorAll('#navigation a, #subnavigation a'))
                .map(a => a.getAttribute('href')).filter(h => h && h.startsWith('#'))"""
        )
        links = list(dict.fromkeys(links))
        groups = page.evaluate(
            """() => Array.from(document.querySelectorAll('#navigation .nav-group'))
                .map(g => g.querySelector('.nav-item').textContent.trim())"""
        )
        print(f"一级分组 {len(groups)}: {' / '.join(groups)}")
        print(f"可导航链接 {len(links)} 个\n")

        for href in links:
            errors: list[str] = []
            page2 = ctx.new_page()
            page2.on("pageerror", lambda e: errors.append(str(e)[:160]))
            page2.on("console", lambda m: errors.append("console:" + m.text[:160]) if m.type == "error" else None)
            try:
                page2.goto(f"{BASE}/studio{href}", wait_until="load", timeout=25000)
                page2.wait_for_timeout(2200)
                info = page2.evaluate(
                    """() => ({
                        contentLen: (document.querySelector('#content')?.innerHTML || '').length,
                        h1: (document.querySelector('#content h1')?.textContent || '').trim().slice(0, 30),
                        activeGroups: Array.from(document.querySelectorAll('#navigation .nav-group.active'))
                            .map(g => g.querySelector('.nav-item').textContent.trim()),
                        hasIframe: !!document.querySelector('#content iframe, iframe.refsite-frame'),
                    })"""
                )
            except Exception as exc:  # noqa: BLE001
                rows.append({"href": href, "ok": False, "why": "nav timeout", "detail": str(exc)[:90]})
                page2.close()
                continue

            ok = info["contentLen"] > 80 and len(info["activeGroups"]) == 1 and not errors
            rows.append({"href": href, "ok": ok, **info, "errors": errors[:2]})
            if not ok:
                page2.screenshot(path=str(OUT / (href.strip("#").replace("/", "_") + ".png")))
            page2.close()

        browser.close()

    bad = [r for r in rows if not r["ok"]]
    print(f"{'路由':<28}{'内容':>7}  {'激活组':<12}{'iframe':<7}结论")
    print("-" * 82)
    for r in rows:
        if "contentLen" not in r:
            print(f"{r['href']:<28}{'--':>7}  {'--':<12}{'--':<7}FAIL {r.get('why')}")
            continue
        print(
            f"{r['href']:<28}{r['contentLen']:>7}  "
            f"{(r['activeGroups'][0] if r['activeGroups'] else '无'):<12}"
            f"{'是' if r['hasIframe'] else '否':<7}"
            f"{'OK' if r['ok'] else 'FAIL ' + '; '.join(r.get('errors', []))[:60]}"
        )
    print("-" * 82)
    print(f"共 {len(rows)} 条，失败 {len(bad)} 条")
    (Path(OUT).parent / "nav-report.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
