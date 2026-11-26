"""跨局分析 / 大场分析页面回归（Playwright，不写用户数据）。

用法：
    python scripts/verify_cross_page.py --base http://127.0.0.1:8771

覆盖：
- `#cross` 多场 BO：白底战报台、范围条、赛中/赛后/英雄和 BP 三个分区、视角切换与 URL；
- `#biggame` 独立大场列表：入口卡、筛选、进入单场；
- `#biggame/<id>` 单场大场分析：逐局卡、逐局对比、返回；
- 旧 `#cross/series/<id>` 重定向到 `#biggame/<id>`；
- 桌面 1440 与窄屏 1024 无横向溢出、无 JS 异常。
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
        for name, width, height in [("desktop", 1440, 1000), ("narrow", 1024, 900)]:
            page = browser.new_page(viewport={"width": width, "height": height}, locale="zh-CN")
            page.add_init_script("try{localStorage.setItem('training-tour-complete-v3','1');}catch(e){}")
            page.on("pageerror", lambda e: errors.append(f"JS 异常：{str(e)[:160]}"))

            # 跨局分析：三个分区（概述已并入首屏），默认赛中。
            page.goto(base + "/#cross", wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector(".xw-tabs", timeout=30000)
                page.wait_for_timeout(800)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"#cross 未就绪：{exc}")
                continue
            if len(text(page, "#content")) < 300:
                errors.append("#cross 内容过短")
            if "跨场分析" not in text(page, ".xw-page:visible .xw-eyebrow"):
                errors.append("#cross 页头不是跨场口径")
            if len(page.query_selector_all("[data-cx-section]")) != 3:
                errors.append("#cross 不是 3 个分析分区")
            visible = [x.get_attribute("data-cx-section") for x in page.query_selector_all("[data-cx-section]:not([hidden])")]
            if visible != ["ingame"]:
                errors.append(f"#cross 默认没有停在赛中（{visible}）")
            if page.query_selector('a[href="#biggame"]') is None:
                errors.append("#cross 没有独立大场分析入口")
            if page.query_selector(".xw-rate-num") is None or page.query_selector(".xw-trend-rail") is None:
                errors.append("#cross 首屏缺少大场胜率/净胜走势")
            if len(page.query_selector_all(".xw-score")) < 2:
                errors.append("#cross 首屏缺少比分分布")
            if page.query_selector(".xw-radar") is not None or "本轮关注" in text(page, "#content"):
                errors.append("#cross 仍显示本轮关注")
            lead_small_sizes = page.evaluate("""(
              [...document.querySelectorAll('#xw-ingame-lead .xw-count-label small')]
                .map(el => parseFloat(getComputedStyle(el).fontSize))
            )""")
            if len(lead_small_sizes) < 4 or any(size < 14 for size in lead_small_sizes):
                errors.append(f"领先守成条件字号偏小或缺失（{lead_small_sizes}）")
            # 首屏与页面都不该出现深色大块（旧版黑屏）。
            dark = page.evaluate(r"""(
              [...document.querySelectorAll('.xw-mast, .xw-mod')]
                .filter(el => {
                  const bg = getComputedStyle(el).backgroundColor.match(/\d+/g) || [];
                  return bg.length >= 3 && (+bg[0] < 60 && +bg[1] < 60 && +bg[2] < 60);
                }).length
            )""")
            if dark:
                errors.append(f"#cross 仍有 {dark} 个深色块")
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2"):
                errors.append(f"{name}: #cross 横向溢出")

            # 分区切换与 URL 保持。
            for section in ("postgame", "draft"):
                page.click(f'[data-cx-section-link="{section}"]')
                page.wait_for_timeout(400)
                visible = [x.get_attribute("data-cx-section") for x in page.query_selector_all("[data-cx-section]:not([hidden])")]
                if visible != [section]:
                    errors.append(f"#cross 分区 {section} 未切换（{visible}）")
                if f"view={section}" not in page.evaluate("location.hash"):
                    errors.append(f"#cross 分区 {section} 未写进地址")
                if page.query_selector(f'[data-cx-section="{section}"]:not([hidden]) .xw-mod') is None:
                    errors.append(f"#cross 分区 {section} 没有内容")
                if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2"):
                    errors.append(f"{name}: #cross {section} 横向溢出")
                if section == "postgame":
                    verdicts = page.locator(".xw-exec-verdict").all_text_contents()
                    if any("pp" in verdict.lower() for verdict in verdicts):
                        errors.append("#cross 对位差值仍显示 pp")
                    if any("+0%" in verdict for verdict in verdicts):
                        errors.append("#cross 对位差值出现 +0% 噪声")
                    if verdicts and not any("%" in verdict for verdict in verdicts):
                        errors.append("#cross 对位差值未显示百分比")
                if section == "draft":
                    cards = page.locator(".xw-arch-card")
                    if cards.count() != 5:
                        errors.append(f"#cross 五路类型卡数量异常（{cards.count()}）")
                    if page.query_selector(".xw-arch-row") is not None:
                        errors.append("#cross 仍使用旧五路堆叠行")
                    card_text = text(page, ".xw-arch")
                    if card_text.count("%") < 5:
                        errors.append("#cross 五路类型卡缺少可读占比")
                    if page.locator('.xw-arch-bar[role="img"][aria-label]').count() != 5:
                        errors.append("#cross 五路类型条缺少无障碍说明")
                    arch_columns = page.locator(".xw-arch-grid").evaluate(
                        "el => getComputedStyle(el).gridTemplateColumns.split(' ').filter(Boolean).length"
                    )
                    if arch_columns < 2:
                        errors.append(f"#cross 五路类型卡没有形成多列布局（{arch_columns}）")

            # 视角切换：本队 / 敌方都要能出数。
            page.click('[data-xw-side="foe"]')
            page.wait_for_timeout(600)
            if "side=foe" not in page.evaluate("location.hash"):
                errors.append("#cross 视角没有写进地址")
            if page.query_selector('[data-xw-side="foe"].is-on') is None:
                errors.append("#cross 敌方视角没有生效")
            page.click('[data-xw-side="own"]')
            page.wait_for_timeout(400)

            page.reload(wait_until="domcontentloaded")
            try:
                page.wait_for_selector(".xw-tabs", timeout=30000)
                page.wait_for_timeout(600)
            except Exception:
                pass
            visible = [x.get_attribute("data-cx-section") for x in page.query_selector_all("[data-cx-section]:not([hidden])")]
            if visible != ["draft"]:
                errors.append(f"刷新后没有保持英雄和 BP 分区（{visible}）")

            # 独立大场分析：列表 + 详情。
            page.goto(base + "/#biggame", wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector(".bgx-team-card", timeout=30000)
                page.wait_for_timeout(500)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"#biggame 未就绪：{exc}")
                continue
            if page.query_selector(".bgx-list-head") is None:
                errors.append("大场分析缺少列表页头")
            if page.query_selector(".bgx-team-card") is None:
                errors.append("大场列表没有卡片")
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2"):
                errors.append(f"{name}: #biggame 横向溢出")
            link = page.query_selector('.bgx-team-card[href^="#biggame/"]')
            if link is None:
                errors.append("大场卡片没有详情入口")
            else:
                href = link.get_attribute("href")
                page.goto(base + "/" + href, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_selector(".bgx-detail", timeout=30000)
                    page.wait_for_timeout(500)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"大场详情未就绪：{exc}")
                else:
                    if page.query_selector(".bgx-hero-game") is None:
                        errors.append("大场详情缺少逐局卡片")
                    if "总览与对比" not in text(page, "#content"):
                        errors.append("大场详情缺少总览与对比")
                    if page.query_selector(".bgx-back") is None:
                        errors.append("大场详情缺少返回列表")
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
    print("跨局/大场分析页面回归通过：三分区、白底、视角切换、独立大场入口、详情、旧路径、桌面/窄屏。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

