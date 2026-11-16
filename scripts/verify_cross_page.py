"""跨局分析 / 大场分析页面回归（Playwright，不写用户数据）。

用法：
    python scripts/verify_cross_page.py --base http://127.0.0.1:8771

覆盖：
- `#cross` 多场 BO：hero、范围条、概述/赛中/赛后/英雄和 BP 四个分区、分区切换与 URL；
- `#biggame` 独立大场列表：入口卡、筛选、进入单场；
- `#biggame/<id>` 单场大场分析：逐局卡、逐局对比、返回；
- 旧 `#cross/series/<id>` 重定向到 `#biggame/<id>`；
- 桌面 1440 与移动 390 无横向溢出、无 JS 异常。
"""
import argparse
import sys
import urllib.request

from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def warm(base):
    for path in ("/api/cross/series-summary", "/api/cross/vectors?source=db%2Cbundle&validation=1"):
        try:
            with urllib.request.urlopen(base + path, timeout=120) as r:
                r.read(2048)
        except OSError:
            pass


def text(page, selector):
    node = page.query_selector(selector)
    return node.inner_text() if node else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8766")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    warm(base)
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        for name, width, height in [("desktop", 1440, 1000), ("mobile", 390, 844)]:
            page = browser.new_page(viewport={"width": width, "height": height}, locale="zh-CN")
            page.add_init_script("try{localStorage.setItem('training-tour-complete-v3','1');}catch(e){}")
            page.on("pageerror", lambda e: errors.append(f"JS 异常：{str(e)[:160]}"))

            # 跨局分析：四个分区，默认概述。
            page.goto(base + "/#cross", wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector(".xc-section-nav", timeout=30000)
                page.wait_for_timeout(800)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"#cross 未就绪：{exc}")
                continue
            if len(text(page, "#content")) < 300:
                errors.append("#cross 内容过短")
            if "跨局分析" not in text(page, ".xc-eyebrow"):
                errors.append("#cross 页头不是跨局口径")
            if len(page.query_selector_all("[data-cx-section]")) != 4:
                errors.append("#cross 不是 4 个分析分区")
            if [x.get_attribute("data-cx-section") for x in page.query_selector_all("[data-cx-section]:not([hidden])")] != ["overview"]:
                errors.append("#cross 默认没有停在概述")
            if page.query_selector('.xc-tabs') is not None:
                errors.append("#cross 仍出现旧页签条")
            if page.query_selector('a[href="#biggame"]') is None:
                errors.append("#cross 没有独立大场分析入口")
            if page.query_selector(".xc-ring") is None or page.query_selector(".xc-hero-trend") is None:
                errors.append("#cross hero 缺少胜率环/净胜走势")
            if len(page.query_selector_all(".xc-last-chip")) < 2:
                errors.append("#cross hero 缺少近 5 场比分")
            visible_sections = [x.get_attribute("data-cx-section") for x in page.query_selector_all("[data-cx-section]:not([hidden])")]
            if visible_sections == ["overview"]:
                if page.query_selector(".xc-cohort") is None:
                    errors.append("#cross 概述缺少描述性样本卡")
            elif page.query_selector("[data-cx-section]:not([hidden]) .xc-insight") is None:
                errors.append("#cross 缺少分区一眼结论")
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2"):
                errors.append(f"{name}: #cross 横向溢出")

            # 分区切换与 URL 保持。
            for section in ("ingame", "postgame", "draft"):
                page.click(f'[data-cx-section-link="{section}"]')
                page.wait_for_timeout(300)
                visible = [x.get_attribute("data-cx-section") for x in page.query_selector_all("[data-cx-section]:not([hidden])")]
                if visible != [section]:
                    errors.append(f"#cross 分区 {section} 未切换（{visible}）")
                if f"view={section}" not in page.evaluate("location.hash"):
                    errors.append(f"#cross 分区 {section} 未写进地址")
                if section in ("postgame", "draft"):
                    if page.query_selector(f'[data-cx-section="{section}"]:not([hidden]) .xv-view:not([hidden]) table') is not None:
                        errors.append(f"#cross 分区 {section} 默认视图仍是表格")
            page.reload(wait_until="domcontentloaded")
            try:
                page.wait_for_selector(".xc-section-nav", timeout=30000)
                page.wait_for_timeout(600)
            except Exception:
                pass
            visible = [x.get_attribute("data-cx-section") for x in page.query_selector_all("[data-cx-section]:not([hidden])")]
            if visible != ["draft"]:
                errors.append(f"刷新后没有保持英雄和 BP 分区（{visible}）")

            # 独立大场分析：列表 + 详情。
            page.goto(base + "/#biggame", wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector(".xc-bigcard", timeout=30000)
                page.wait_for_timeout(500)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"#biggame 未就绪：{exc}")
                continue
            if page.query_selector('.secondary-nav a[href="#biggame"]') is None:
                errors.append("大场分析没有次级导航入口")
            if page.query_selector(".xc-bigcard") is None:
                errors.append("大场列表没有卡片")
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2"):
                errors.append(f"{name}: #biggame 横向溢出")
            link = page.query_selector('.xc-bigcard[href^="#biggame/"]')
            if link is None:
                errors.append("大场卡片没有详情入口")
            else:
                href = link.get_attribute("href")
                page.goto(base + "/" + href, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector(".xc-series-detail", timeout=30000)
                    page.wait_for_timeout(500)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"大场详情未就绪：{exc}")
                else:
                    if page.query_selector(".xc-gcard") is None:
                        errors.append("大场详情缺少逐局卡片")
                    if "逐局对比" not in text(page, "#content"):
                        errors.append("大场详情缺少逐局对比")
                    if page.query_selector(".xc-back") is None:
                        errors.append("大场详情缺少返回列表")
                    if page.query_selector(".xc-game-row") is None:
                        errors.append("大场详情缺少逐局卡")
                    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2"):
                        errors.append(f"{name}: 大场详情横向溢出")

            # 旧路径重定向。
            page.goto(base + "/#cross/series/ts-test-redirect", wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            if "#biggame/ts-test-redirect" not in page.evaluate("location.hash"):
                errors.append("旧 #cross/series/<id> 没有重定向到 #biggame/<id>")
            page.close()
        browser.close()

    if errors:
        print("跨局/大场分析页面回归失败：")
        for item in errors:
            print(" -", item)
        return 1
    print("跨局/大场分析页面回归通过：四分区、独立大场入口、详情、旧路径、桌面/移动端。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
