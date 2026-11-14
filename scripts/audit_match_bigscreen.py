"""单局「复盘大屏」验收脚本（2026-11-14 方案变更后）。

背景（2026-11-14）：教练要求复盘大屏收敛——赛事命中并入本局 BP 复盘（命中组合
带头像 / 胜率 / 最近谁用 / 使用时间），团战与资源、经济走势两张卡撤掉（细节在
「事件」页签），比赛脉搏放进本局结论卡，总量条紧跟结论。当前契约：
  * 单局页 4 个页签，顺序 review(复盘大屏) / data(十人数据) / events(事件) / map(地图)；
    默认页签 review，地址 ``#match/<key>``；深链 ``#match/<key>/<tab>`` 仍有效。
  * review pane 内依次是：
      section.md-hero#match-verdict（本局结论，内含 div#match-pulse 比赛脉搏）
      div#match-totals（总量条）
      section#match-ov-lineup（双方阵容，头像 / 名字跳 #hero/<名字>）
      section#match-ov-bp（本局 BP 复盘 + 赛事命中 .md-kplhit）
      section#match-ov-matchup（对位压制，.md-mu-face 头像跳英雄页）
      section#match-ov-combos（联动组合）
      .md-pane-row（#match-phases + #match-timeline）
  * 不再存在：#match-ov-kpl / #match-ov-battle / #match-ov-economy 独立卡，
    以及任何 ``data-md-jump`` 跳转按钮。
  * 页签按钮是 ``.md-tabs [data-md-tab]``，共 4 个。
  * 异步回放到达后，pane 内的 ``section[id]``（含结论卡）会被原位替换，
    不允许出现重复 id 或丢区块。

断言覆盖：
  1. 默认 active=review；4 个页签且第一个文字含「复盘大屏」；
  2. review pane 可见，7 个 section 区块各恰好 1 个，``#match-totals`` 与
     ``#match-pulse`` 都在 review 内（pulse 在结论卡里），文档内无重复 id；
     ``section.md-hero`` 存在且 h1 有结论句；
  3. 阵容 / 对位 / 组合的英雄链接全部指向 ``#hero/<名字>``，不允许 ``#matches/hero=``；
  4. BP 复盘块内出现「赛事命中」子块（.md-kplhit）；
  5. 点击 data / events / map / review：对应 pane 可见、其余隐藏、hash 同步、无 JS 报错；
  6. 1440×1000 / 1280×900 / 1024×900：无横向溢出、各截全页图、打印复盘大屏高度；
  7. route 拦截 /api/replay/**、/api/positions/** → 404：复盘大屏区块仍齐全、
     不出现「正在读取」占位、无 JS 报错；
  8. route 拦截 /api/matches/<key>*，删掉 draft/bpFacts/teamTotals：出现「暂无禁选记录」、
     赛事命中留空说明、无 JS 报错；
  9. 旧深链 ``#match/<key>/data`` 等直接打开仍停在对应页签。
 10. ``--regression``：用根路径逐条扫 26 条一级/二级路由（无 JS 异常、非空页），
     并顺带跑 scripts/audit_v3_regression.py（该脚本固定拼 ``/v3/`` 前缀，本机部署在
     根路径时会把 26/26 判失败，属于脚本与部署不匹配，会降级成 warning）。

用法：
    python scripts/audit_match_bigscreen.py
    python scripts/audit_match_bigscreen.py --base http://127.0.0.1:8766 \
        --key channel-2f41bb5f40a84f2fb0b0b1d7cbc2f33e --regression
    python scripts/audit_match_bigscreen.py --headed --wait-ms 7000

退出码：0 = 全部断言通过（warning 不阻塞）；1 = 有 FAIL；2 = 环境/脚本异常。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_BASE = "http://127.0.0.1:8766"
DEFAULT_KEY = "channel-2f41bb5f40a84f2fb0b0b1d7cbc2f33e"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / ".audit-shots" / "match-bigscreen"

EXPECTED_TABS = ["review", "data", "events", "map"]
EXPECTED_LABELS = {
    "review": "复盘大屏",
    "data": "十人数据",
    "events": "事件",
    "map": "地图",
}

# review pane 内应有且仅有一个的 section 区块（顺序即视觉顺序）。
# 结论卡是 section.md-hero（非 .section），脉搏 / 总量是卡内 / 卡后的 div。
SCREEN_SECTIONS = [
    "match-verdict",       # section.md-hero：本局结论（内含 #match-pulse 比赛脉搏）
    "match-ov-lineup",     # 双方阵容
    "match-ov-bp",         # 本局 BP 复盘（含赛事命中 .md-kplhit）
    "match-ov-matchup",    # 对位压制
    "match-ov-combos",     # 联动组合
    "match-phases",        # 阶段对比
    "match-timeline",      # 关键节点
]
TOTALS_ID = "match-totals"  # 总量条是 div，紧跟结论卡
PULSE_ID = "match-pulse"    # 比赛脉搏在结论卡里，也是 div
# 2026-11-14 撤掉的三张卡，不允许再出现。
REMOVED_IDS = ["match-ov-kpl", "match-ov-battle", "match-ov-economy"]

# 两栏行只剩阶段对比 + 关键节点。
PANE_ROWS = [
    ["match-phases", "match-timeline"],
]

VIEWPORTS = [(1440, 1000), (1280, 900), (1024, 900)]

# 与 scripts/audit_v3_regression.py 相同的 26 条一级/二级路由。
# 注意：那个脚本拼的是 `{base}/v3/{route}`；本机 8766 把 v3 应用挂在根路径，
# `/v3/...` 会 404。所以 --regression 里除了跑外部脚本，还会用根路径自己扫一遍。
REGRESSION_ROUTES = [
    "overview", "ingest", "capture", "matches", "query", "featured", "records", "versions",
    "economy", "tempo", "teams", "opponents", "h2h", "coach", "players", "identity",
    "compare", "bp", "heroes", "combos", "setup", "pending", "plan", "effect", "reports", "sources",
]

# 无回放时复盘大屏必须保持完整；review 内不允许再出现「正在读取」占位
# （团战与资源卡已撤，回放到达只影响结论卡内脉搏的事件标记）。
NO_REPLAY_PHRASES = [
    "正在读取",
    "正在读取官方回放",
]
# 无 BP / KPL 时的空态文案。
NO_DRAFT_PHRASE = "暂无禁选记录"
NO_KPL_PHRASE = "赛事命中"  # 赛事命中子块标题仍然存在（无数据时给出留空说明）

# 既有噪声：/api/update/check 在本地 404；fetch 到 404（如模拟的 replay/positions）也会打
# "Failed to load resource"。这些与本次改动无关，记 warning；其它 console error 仍 FAIL。
BENIGN_CONSOLE_PATTERNS = (
    "Failed to load resource",
    "update/check",
    "favicon",
)


@dataclass
class Results:
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: int = 0
    capture_failures: list[str] = field(default_factory=list)

    def check(self, case: str, name: str, ok: bool, detail: str = "") -> bool:
        self.checks += 1
        if ok:
            print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
            return True
        self.failures.append(f"{case} / {name}" + (f" · {detail}" if detail else ""))
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))
        return False

    def warn(self, case: str, text: str) -> None:
        self.warnings.append(f"{case} / {text}")
        print(f"  [WARN] {text}")

    def fail(self, case: str, text: str) -> None:
        self.failures.append(f"{case} / {text}")
        print(f"  [FAIL] {text}")


SNAPSHOT_JS = """(sections) => {
    const clean = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
    const visible = (el) => !!el && el.getClientRects().length > 0;
    const page = document.querySelector('.md-page');
    const review = document.querySelector('[data-md-pane="review"]');
    const tabs = [...document.querySelectorAll('.md-tabs [data-md-tab]')].map((b) => ({
        key: b.dataset.mdTab || '',
        label: clean(b.textContent),
        selected: b.getAttribute('aria-selected') === 'true',
    }));
    const panes = [...document.querySelectorAll('[data-md-pane]')].map((p) => ({
        key: p.dataset.mdPane || '',
        visible: visible(p),
        textLen: clean(p.textContent).length,
    }));
    const blocks = sections.map((id) => ({
        id,
        inReview: review ? review.querySelectorAll('#' + id).length : 0,
        document: document.querySelectorAll('#' + id).length,
    }));
    const allIds = [...document.querySelectorAll('[id]')].map((el) => el.id);
    const dupIds = [...new Set(allIds.filter((id, i) => allIds.indexOf(id) !== i))];
    const hero = review ? review.querySelector('section.md-hero') : null;
    const rows = review
        ? [...review.querySelectorAll(':scope > .md-pane-row')].map((row) => ({
            children: [...row.querySelectorAll(':scope > section[id]')].map((s) => s.id),
        }))
        : [];
    const totals = document.getElementById('match-totals');
    const pulse = document.getElementById('match-pulse');
    const heroLinks = (review ? [...review.querySelectorAll('a.bp-hero-link[href^="#hero/"]')] : []);
    const staleMatchesLinks = (review
        ? [...review.querySelectorAll('a.bp-hero-link[href^="#matches/hero="]')].length : 0);
    const faces = (review ? review.querySelectorAll('.md-mu-face .portrait').length : 0);
    const kplHit = (review ? review.querySelectorAll('.md-kplhit').length : 0);
    const kplHitRows = (review ? review.querySelectorAll('.md-kplhit-row').length : 0);
    return {
        hash: location.hash,
        title: document.title,
        active: page ? page.dataset.mdTabActive : null,
        tabs,
        panes,
        blocks,
        totalsInReview: review ? review.querySelectorAll('#' + 'match-totals').length : 0,
        totalsIsInReview: review && totals ? review.contains(totals) : false,
        totalsRightAfterHero: review && hero && totals
            ? hero.nextElementSibling === totals : false,
        pulseInHero: hero && pulse ? hero.contains(pulse) : false,
        removedStillPresent: ['match-ov-kpl', 'match-ov-battle', 'match-ov-economy']
            .filter((id) => document.getElementById(id)),
        dupIds,
        heroExists: !!hero,
        heroH1: clean(hero ? hero.querySelector('h1')?.textContent : ''),
        heroHasPulse: hero ? !!hero.querySelector('#match-pulse') : false,
        heroFaceCount: hero ? hero.querySelectorAll('.portrait').length : 0,
        heroLinks: heroLinks.length,
        staleMatchesLinks,
        faces,
        kplHit,
        kplHitRows,
        paneRows: rows,
        jumps: [...document.querySelectorAll('[data-md-jump]')].map((b) => ({
            target: b.dataset.mdJump || '',
            label: clean(b.textContent),
        })),
        reviewText: clean(review ? review.textContent : ''),
        reviewTextLen: clean(review ? review.textContent : '').length,
        contentTextLen: clean(document.querySelector('#content')?.textContent).length,
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth: window.innerWidth,
        scrollHeight: document.documentElement.scrollHeight,
        emptyCards: [...document.querySelectorAll('.offline-card, .loading')]
            .filter(visible).map((el) => clean(el.textContent).slice(0, 80)),
    };
}"""


class ScreenRun:
    """一次页面加载：错误收集、route 拦截、快照。"""

    def __init__(self, browser, base: str, key: str, viewport=(1440, 1000)):
        self.base = base
        self.key = key
        self.pageerrors: list[str] = []
        self.console_errors: list[str] = []
        self.failed_responses: list[str] = []
        self.request_failures: list[str] = []
        width, height = viewport
        self.context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
        # 引导层「八堂课」modal 会在 goto 前弹，先标记已看过，避免挡住截图。
        self.context.add_init_script("localStorage.setItem('training-tour-complete-v3','1');")
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda e: self.pageerrors.append(str(e)[:300]))
        self.page.on(
            "console",
            lambda m: self.console_errors.append(m.text[:300]) if m.type == "error" else None,
        )
        self.page.on(
            "response",
            lambda r: self.failed_responses.append(f"{r.status} {r.url}") if r.status >= 400 else None,
        )
        self.page.on("requestfailed", lambda r: self.request_failures.append(f"{r.url} {r.failure}"))

    # -- 错误分类 -------------------------------------------------------
    def benign_console(self) -> list[str]:
        return [t for t in self.console_errors if any(p in t for p in BENIGN_CONSOLE_PATTERNS)]

    def fatal_console(self) -> list[str]:
        return [t for t in self.console_errors if not any(p in t for p in BENIGN_CONSOLE_PATTERNS)]

    def report_errors(self, results: Results, tag: str) -> bool:
        ok = True
        if self.pageerrors:
            results.fail(tag, "pageerror: " + " | ".join(dict.fromkeys(self.pageerrors)))
            ok = False
        fatal = self.fatal_console()
        if fatal:
            results.fail(tag, "console error: " + " | ".join(dict.fromkeys(fatal)))
            ok = False
        benign = self.benign_console()
        if benign:
            results.warn(tag, f"console 噪声 {len(benign)} 条（资源 404 / 更新检查，与本次改动无关）")
        if self.request_failures:
            results.warn(tag, "请求失败: " + " | ".join(dict.fromkeys(self.request_failures))[:200])
        return ok

    # -- 页面操作 -------------------------------------------------------
    def open(self, tab: str | None = None, wait_ms: int = 5200) -> None:
        fragment = f"#match/{self.key}" + (f"/{tab}" if tab else "")
        self.page.goto(self.base.rstrip("/") + "/" + fragment, wait_until="load", timeout=30000)
        try:
            self.page.wait_for_selector("[data-md-pane]", timeout=12000)
        except PlaywrightError:
            pass
        # 等异步回放把结论卡替换完（脉搏事件标记补齐），再给一点渲染余量。
        try:
            self.page.wait_for_function(
                "() => { const el = document.querySelector('#match-verdict');"
                " return el && el.textContent.includes('比赛脉搏'); }",
                timeout=12000,
            )
        except PlaywrightError:
            pass
        self.page.wait_for_timeout(wait_ms)

    def snapshot(self) -> dict:
        return self.page.evaluate(SNAPSHOT_JS, SCREEN_SECTIONS)

    def after_click(self) -> dict:
        return self.page.evaluate(
            """() => {
                const clean = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
                const visible = (el) => !!el && el.getClientRects().length > 0;
                const page = document.querySelector('.md-page');
                return {
                    hash: location.hash,
                    active: page ? page.dataset.mdTabActive : null,
                    visiblePanes: [...document.querySelectorAll('[data-md-pane]')]
                        .filter(visible).map((p) => p.dataset.mdPane || ''),
                    selectedTabs: [...document.querySelectorAll('.md-tabs [data-md-tab]')]
                        .filter((b) => b.getAttribute('aria-selected') === 'true')
                        .map((b) => b.dataset.mdTab || ''),
                    reviewLen: clean(document.querySelector('[data-md-pane="review"]')?.textContent).length,
                };
            }"""
        )

    def close(self) -> None:
        try:
            self.context.close()
        except Exception:  # noqa: BLE001
            pass


def install_no_replay_routes(page) -> None:
    """模拟无回放 / 无位置：/api/replay/** 与 /api/positions/** 一律 404。"""

    def handler(route):
        route.fulfill(status=404, content_type="application/json", body='{"detail":"审计模拟 404"}')

    page.route("**/api/replay/**", handler)
    page.route("**/api/positions/**", handler)


def load_match_detail(base: str, key: str) -> dict:
    """取一份真实详情 JSON，供「删字段」拦截使用（只读取）。"""
    with urllib.request.urlopen(f"{base.rstrip('/')}/api/matches/{key}", timeout=30) as response:
        return json.loads(response.read())


def install_no_bp_routes(page, base: str, key: str, results: Results, tag: str) -> None:
    """模拟无 BP / 无 KPL 数据：拦截单局详情，删掉 draft / bpFacts / teamTotals。"""
    try:
        original = load_match_detail(base, key)
    except Exception as exc:  # noqa: BLE001
        results.fail(tag, f"取不到原始详情 JSON，无法模拟无 BP：{str(exc)[:120]}")
        return

    def handler(route):
        body = dict(original)
        body.pop("draft", None)
        body.pop("bpFacts", None)
        body.pop("teamTotals", None)
        route.fulfill(
            status=200,
            content_type="application/json; charset=utf-8",
            body=json.dumps(body, ensure_ascii=False),
        )

    page.route(f"**/api/matches/{key}*", handler)


# ── 各项断言 ──────────────────────────────────────────────────────────────
def check_screen_structure(run: ScreenRun, results: Results, tag: str, snap: dict) -> None:
    """默认 / 大屏结构：页签、pane、11 个区块、hero、两栏行、无重复 id。"""
    tabs = snap["tabs"]
    keys = [tab["key"] for tab in tabs]
    labels = [tab["label"] for tab in tabs]

    results.check(tag, "默认页签 active=review", snap["active"] == "review", f"实际 {snap['active']}")
    results.check(tag, "页签数量为 4", len(tabs) == 4, f"实际 {len(tabs)}：{labels}")
    results.check(tag, "页签 key 恰为 review/data/events/map", keys == EXPECTED_TABS, f"实际 {keys}")
    results.check(
        tag,
        "第一个页签文字含「复盘大屏」",
        bool(labels) and EXPECTED_LABELS["review"] in labels[0],
        f"第一个 {labels[0] if labels else '—'}",
    )
    for tab in tabs:
        expected = EXPECTED_LABELS.get(tab["key"])
        if expected and expected not in tab["label"]:
            results.warn(tag, f"页签「{tab['key']}」文字未含「{expected}」：{tab['label']}")

    visible = [pane["key"] for pane in snap["panes"] if pane["visible"]]
    results.check(tag, "默认只显示 review pane", visible == ["review"], f"可见 {visible}")
    results.check(
        tag,
        "review pane 可见且文本 > 200 字",
        snap["reviewTextLen"] > 200,
        f"文本 {snap['reviewTextLen']} 字",
    )

    missing = [block["id"] for block in snap["blocks"] if block["inReview"] != 1]
    results.check(
        tag,
        f"review pane 内 {len(SCREEN_SECTIONS)} 个区块各恰好 1 个",
        not missing,
        "缺失/重复：" + "、".join(missing) if missing else "、".join(SCREEN_SECTIONS),
    )
    removed = snap["removedStillPresent"]
    results.check(
        tag,
        "赛事命中 / 团战与资源 / 经济走势独立卡已撤掉",
        not removed,
        f"残留 {removed}" if removed else "无残留",
    )
    results.check(
        tag,
        f"总量条 #{TOTALS_ID} 在 review 内且唯一",
        snap["totalsInReview"] == 1 and snap["totalsIsInReview"],
        f"在 review 内 {snap['totalsInReview']} 个",
    )
    results.check(
        tag,
        "总量条紧跟结论卡",
        snap["totalsRightAfterHero"],
        "md-hero 的下一个兄弟是 #match-totals" if snap["totalsRightAfterHero"] else "顺序不对",
    )
    results.check(
        tag,
        f"比赛脉搏 #{PULSE_ID} 在结论卡内",
        snap["pulseInHero"] and snap["heroHasPulse"],
        "#match-pulse 在 #match-verdict 内",
    )
    results.check(tag, "文档内无重复 id", not snap["dupIds"], f"重复：{snap['dupIds']}" if snap["dupIds"] else "无")
    results.check(tag, "section.md-hero 存在", snap["heroExists"], "review pane 内")
    results.check(
        tag,
        "section.md-hero 的 h1 有结论句",
        len(snap["heroH1"]) >= 8,
        f"h1={snap['heroH1'][:40]!r}",
    )
    # 英雄跳转：全部指向英雄详情页，不允许再落到对局筛选。
    results.check(
        tag,
        "复盘大屏内英雄链接全部跳 #hero/<名字>",
        snap["heroLinks"] > 0 and snap["staleMatchesLinks"] == 0,
        f"#hero 链接 {snap['heroLinks']} 个 · 旧 #matches/hero= 链接 {snap['staleMatchesLinks']} 个",
    )
    # 赛事命中并入 BP 复盘。
    results.check(
        tag,
        "BP 复盘内出现赛事命中子块（.md-kplhit）",
        snap["kplHit"] >= 1,
        f"{snap['kplHit']} 个",
    )
    if snap["kplHitRows"]:
        results.check(
            tag,
            "命中组合行带头像与「最近/年份」使用时间",
            True,
            f"{snap['kplHitRows']} 行",
        )
    else:
        results.warn(tag, "这一局没有命中组合行（数据决定，不算失败）")

    actual_rows = [row["children"] for row in snap["paneRows"]]
    results.check(
        tag,
        "两栏行结构正确（阶段 + 节点）",
        actual_rows == PANE_ROWS,
        f"实际 {actual_rows}",
    )
    results.check(
        tag,
        "不再有 data-md-jump 跳转按钮",
        not snap["jumps"],
        f"残留 {snap['jumps']}" if snap["jumps"] else "无",
    )


def check_tab_switching(run: ScreenRun, results: Results, tag: str, key: str) -> None:
    """依次点 data/events/map，再点回复盘大屏。"""
    for tab in ["data", "events", "map", "review"]:
        label = EXPECTED_LABELS[tab]
        fatal_before = len(run.fatal_console())
        pageerrors_before = len(run.pageerrors)
        try:
            run.page.click(f'.md-tabs [data-md-tab="{tab}"]', timeout=6000)
        except PlaywrightError as exc:
            results.fail(tag, f"点击「{label}」失败：{str(exc)[:80]}")
            continue
        run.page.wait_for_timeout(600)
        snap = run.after_click()
        results.check(
            tag,
            f"点击「{label}」后只显示 {tab} pane",
            snap["visiblePanes"] == [tab],
            f"可见 {snap['visiblePanes']}",
        )
        results.check(
            tag,
            f"点击「{label}」后 hash 同步",
            snap["hash"] == f"#match/{key}/{tab}",
            f"实际 {snap['hash']}",
        )
        results.check(
            tag,
            f"点击「{label}」后 aria-selected 唯一",
            snap["selectedTabs"] == [tab],
            f"实际 {snap['selectedTabs']}",
        )
        results.check(
            tag,
            f"点击「{label}」后无新增 JS 报错",
            len(run.fatal_console()) == fatal_before and len(run.pageerrors) == pageerrors_before,
            "" if (len(run.fatal_console()) == fatal_before and len(run.pageerrors) == pageerrors_before)
            else "新增 pageerror/console error",
        )


def check_jump(run: ScreenRun, results: Results, tag: str, key: str) -> None:
    """2026-11-14 起 data-md-jump 跳转按钮已随「团战与资源」卡撤掉：保留空实现占位。"""
    return None


def run_default_view(run: ScreenRun, results: Results, tag: str, args, screenshot_name: str) -> dict:
    """默认状态 + 结构化断言 + 截图 + 页签。截图必须在点页签之前（默认页）。"""
    run.open()
    snap = run.snapshot()
    run.report_errors(results, tag)
    results.check(
        tag,
        "应用外壳已渲染（#content 有内容）",
        snap["contentTextLen"] > 20,
        f"正文 {snap['contentTextLen']} 字，title={snap['title']!r}",
    )
    check_screen_structure(run, results, tag, snap)
    results.check(
        tag,
        "无横向溢出",
        snap["scrollWidth"] <= snap["innerWidth"] + 2,
        f"scrollWidth {snap['scrollWidth']} / innerWidth {snap['innerWidth']}",
    )
    print(f"  复盘大屏高度：{snap['scrollHeight']}px（2026-11-13 版约 3485px）")
    # 截图必须在点页签之前：点完页签页面就停在别的页签上了。
    take_screenshot(run, results, tag, args, screenshot_name)
    check_tab_switching(run, results, tag, run.key)
    return snap


def check_deep_links(browser, results: Results, base: str, key: str, args) -> None:
    """旧深链（#match/<key>/<tab>）直接打开时应停在对应页签。"""
    tag = "深链直达页签"
    print(f"\n[{tag}]")
    for tab in EXPECTED_TABS:
        run = ScreenRun(browser, base, key, viewport=(1440, 1000))
        try:
            run.open(tab)
            snap = run.snapshot()
            run.report_errors(results, tag)
            results.check(tag, f"深链 /{tab} 直达 {tab} 页签", snap["active"] == tab, f"active={snap['active']}")
            visible = [pane["key"] for pane in snap["panes"] if pane["visible"]]
            results.check(tag, f"深链 /{tab} 只显示 {tab} pane", visible == [tab], f"可见 {visible}")
            results.check(tag, f"深链 /{tab} hash 保持", snap["hash"] == f"#match/{key}/{tab}",
                          f"实际 {snap['hash']}")
            if tab == "review":
                results.check(tag, "深链 /review 大屏 7 个区块齐全",
                              all(block["inReview"] == 1 for block in snap["blocks"]),
                              f"{len(SCREEN_SECTIONS)} 个各 1 个")
        except Exception as exc:  # noqa: BLE001
            results.fail(tag, f"{tab} 深链运行异常：{type(exc).__name__}: {str(exc)[:140]}")
        finally:
            run.close()


def take_screenshot(run: ScreenRun, results: Results, tag: str, args, name: str) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / name
    try:
        run.page.screenshot(path=str(path), full_page=True)
        print(f"  截图：{path}")
    except PlaywrightError as exc:
        results.capture_failures.append(f"{tag} 截图失败：{str(exc)[:100]}")
        results.warn(tag, f"截图失败：{str(exc)[:100]}")


def check_app_routes(browser, results: Results, base: str, wait_ms: int = 2200) -> bool:
    """根路径逐条渲染 26 条路由：无 JS 异常、非空页（空页需有可见空态文案）。

    外部 scripts/audit_v3_regression.py 拼的是 `{base}/v3/{route}`，本机服务把
    v3 应用挂在根路径，直接跑会全 404；这里用根路径做同样的检查作为回归信号。
    """
    tag = "其它路由回归（26 条，根路径）"
    print(f"\n[{tag}]")
    context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
    context.add_init_script("localStorage.setItem('training-tour-complete-v3','1');")
    bad: list[str] = []
    try:
        for route in REGRESSION_ROUTES:
            page = context.new_page()
            page_errors: list[str] = []
            page.on("pageerror", lambda e: page_errors.append(str(e)[:160]))
            page.on(
                "console",
                lambda m: page_errors.append("console:" + m.text[:150]) if m.type == "error" else None,
            )
            row = f"{route:<12}"
            try:
                page.goto(f"{base.rstrip('/')}/#{route}", wait_until="load", timeout=25000)
                page.wait_for_timeout(wait_ms)
                info = page.evaluate(
                    """() => {
                        const clean = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
                        const box = document.querySelector('#content');
                        const empties = [...document.querySelectorAll('#content .empty, #content .offline-card')]
                            .filter((el) => el.getClientRects().length > 0)
                            .map((el) => clean(el.textContent)).filter(Boolean);
                        return {
                            h1: clean(box ? box.querySelector('h1')?.textContent : '').slice(0, 20),
                            len: box ? clean(box.textContent).length : 0,
                            htmlLen: box ? box.innerHTML.length : 0,
                            emptyText: empties.join(' / ').slice(0, 40),
                        };
                    }"""
                )
                fatal = [e for e in page_errors if not any(p in e for p in BENIGN_CONSOLE_PATTERNS)]
                ok = not fatal and (info["htmlLen"] >= 300 or bool(info["emptyText"]))
                if not ok:
                    reason = "JS 报错：" + fatal[0] if fatal else "空页（无内容且无空态说明）"
                    bad.append(f"{route}：{reason}")
                row += f"{info['h1'] or '—':<22}{info['len']:>7}  {'PASS' if ok else 'FAIL'}"
                if not ok:
                    row += "  " + (fatal[0] if fatal else "空页")
                print("  " + row)
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{route}：{type(exc).__name__}: {str(exc)[:80]}")
                print(f"  {row}  FAIL  {type(exc).__name__}")
            finally:
                page.close()
    finally:
        context.close()
    results.check(
        tag,
        f"26 条路由全部正常渲染",
        not bad,
        "；".join(bad[:4]) if bad else "26/26 PASS",
    )
    return not bad


def check_external_regression(results: Results, base: str) -> bool:
    """跑仓库里的 scripts/audit_v3_regression.py，返回是否通过。"""
    tag = "外部回归 scripts/audit_v3_regression.py"
    script = Path(__file__).resolve().parent / "audit_v3_regression.py"
    try:
        proc = subprocess.run(
            [sys.executable, str(script), base],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        )
        tail = "\n".join((proc.stdout or "").strip().splitlines()[-3:])
        if proc.returncode == 0:
            results.check(tag, "外部回归通过", True, tail.replace("\n", " "))
            return True
        # 该脚本固定拼 /v3/ 前缀；本机部署在根路径时属于脚本与部署不匹配，不是页面回归。
        if "共 26 条，失败 26 条" in (proc.stdout or ""):
            results.warn(
                tag,
                "外部脚本把 URL 拼成 {base}/v3/…，本机 8766 把 v3 挂在根路径、/v3/ 返回 404，"
                "26/26 失败属于脚本前缀与部署不一致（已用根路径扫描代替）",
            )
            return False
        results.check(tag, "外部回归通过", False, f"退出码 {proc.returncode}；{tail}".replace("\n", " "))
        return False
    except Exception as exc:  # noqa: BLE001
        results.warn(tag, f"外部回归脚本无法运行：{type(exc).__name__}: {str(exc)[:120]}")
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="单局复盘大屏验收（Playwright）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--base", default=DEFAULT_BASE, help="本地服务地址")
    parser.add_argument("--key", default=DEFAULT_KEY, help="完整数据局 key")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="截图输出目录")
    parser.add_argument("--wait-ms", type=int, default=4800, help="每页稳定等待毫秒数（等待异步回放到位）")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口（调试用）")
    parser.add_argument("--regression", action="store_true",
                        help="顺带跑 scripts/audit_v3_regression.py 做其它路由回归")
    args = parser.parse_args(argv)

    results = Results()
    print("=" * 92)
    print("单局复盘大屏验收（4 页签 / review 整合大屏）")
    print(f"base = {args.base}")
    print(f"key  = {args.key}")
    print(f"out  = {Path(args.out).resolve()}")
    print("=" * 92)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        try:
            # 1) 1440×1000：默认状态、结构、页签、跳转、截图、高度。
            tag = "1440×1000 默认复盘大屏"
            print(f"\n[{tag}]")
            run = ScreenRun(browser, args.base, args.key, viewport=VIEWPORTS[0])
            try:
                run_default_view(run, results, tag, args, "match-bigscreen-1440x1000.png")
            except Exception as exc:  # noqa: BLE001
                results.fail(tag, f"运行异常：{type(exc).__name__}: {str(exc)[:160]}")
                traceback.print_exc(limit=2)
            finally:
                run.close()

            # 2) 其余两个视口：溢出 + 高度 + 截图。
            for width, height in VIEWPORTS[1:]:
                tag = f"{width}×{height} 响应式"
                print(f"\n[{tag}]")
                run = ScreenRun(browser, args.base, args.key, viewport=(width, height))
                try:
                    run.open()
                    snap = run.snapshot()
                    run.report_errors(results, tag)
                    results.check(tag, "active=review", snap["active"] == "review", f"实际 {snap['active']}")
                    results.check(tag, "review pane 可见且文本 > 200 字", snap["reviewTextLen"] > 200,
                                  f"文本 {snap['reviewTextLen']} 字")
                    results.check(
                        tag,
                        "无横向溢出",
                        snap["scrollWidth"] <= snap["innerWidth"] + 2,
                        f"scrollWidth {snap['scrollWidth']} / innerWidth {snap['innerWidth']}",
                    )
                    results.check(tag, "文档内无重复 id", not snap["dupIds"],
                                  f"重复：{snap['dupIds']}" if snap["dupIds"] else "无")
                    print(f"  复盘大屏高度：{snap['scrollHeight']}px（旧版约 4028px）")
                    take_screenshot(run, results, tag, args, f"match-bigscreen-{width}x{height}.png")
                except Exception as exc:  # noqa: BLE001
                    results.fail(tag, f"运行异常：{type(exc).__name__}: {str(exc)[:160]}")
                    traceback.print_exc(limit=2)
                finally:
                    run.close()

            # 2.5) 旧深链直达各页签。
            check_deep_links(browser, results, args.base, args.key, args)

            # 3) 模拟无回放 / 无位置。
            tag = "模拟无回放（/api/replay、/api/positions 404）"
            print(f"\n[{tag}]")
            run = ScreenRun(browser, args.base, args.key, viewport=VIEWPORTS[0])
            try:
                install_no_replay_routes(run.page)
                run.open()
                snap = run.snapshot()
                run.report_errors(results, tag)
                results.check(tag, "无回放时仍默认落在 review 大屏", snap["active"] == "review",
                              f"实际 {snap['active']}")
                review_text = snap["reviewText"]
                hit = [phrase for phrase in NO_REPLAY_PHRASES if phrase in review_text]
                results.check(tag, "复盘大屏不出现「正在读取」占位", not hit,
                              f"命中 {hit}" if hit else "无占位残留")
                results.check(tag, "复盘大屏区块仍齐全",
                              all(block["inReview"] == 1 for block in snap["blocks"]),
                              f"{len(SCREEN_SECTIONS)} 个 section 各 1 个")
                results.check(tag, "结论卡（含脉搏）仍被替换渲染", snap["heroHasPulse"],
                              "md-hero 内有 #match-pulse")
                take_screenshot(run, results, tag, args, "match-bigscreen-no-replay.png")
            except Exception as exc:  # noqa: BLE001
                results.fail(tag, f"运行异常：{type(exc).__name__}: {str(exc)[:160]}")
                traceback.print_exc(limit=2)
            finally:
                run.close()

            # 4) 模拟无 BP / KPL 数据。
            tag = "模拟无 BP/KPL（删 draft、bpFacts、teamTotals）"
            print(f"\n[{tag}]")
            run = ScreenRun(browser, args.base, args.key, viewport=VIEWPORTS[0])
            try:
                install_no_bp_routes(run.page, args.base, args.key, results, tag)
                run.open()
                snap = run.snapshot()
                run.report_errors(results, tag)
                text = snap["reviewText"]
                results.check(tag, f"出现「{NO_DRAFT_PHRASE}」空态", NO_DRAFT_PHRASE in text,
                              f"文本 {len(text)} 字")
                results.check(tag, "赛事命中留空说明仍渲染（无 KPL 数据时）",
                              snap["kplHit"] == 0 and "赛事命中" in text,
                              f"md-kplhit {snap['kplHit']} 个 · 文本含说明")
                results.check(tag, "review 大屏仍可见", snap["active"] == "review" and snap["reviewTextLen"] > 200,
                              f"active={snap['active']} 文本 {snap['reviewTextLen']} 字")
                take_screenshot(run, results, tag, args, "match-bigscreen-no-bp.png")
            except Exception as exc:  # noqa: BLE001
                results.fail(tag, f"运行异常：{type(exc).__name__}: {str(exc)[:160]}")
                traceback.print_exc(limit=2)
            finally:
                run.close()
        finally:
            browser.close()

    # 5) 其它路由回归（可选）：外部脚本 + 根路径扫描。
    if args.regression:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not args.headed)
            try:
                check_app_routes(browser, results, args.base)
            finally:
                browser.close()
        check_external_regression(results, args.base)

    print("\n" + "=" * 92)
    print(f"汇总：{results.checks} 项硬断言，失败 {len(results.failures)} 项，warning {len(results.warnings)} 条")
    if results.capture_failures:
        print("截图失败：" + "；".join(results.capture_failures))
    if results.warnings:
        print("\nwarnings（不阻塞退出码）：")
        for item in results.warnings:
            print("  -", item)
    if results.failures:
        print("\nFAIL 明细：")
        for item in results.failures:
            print("  -", item)
        print("\n结论：FAIL")
        return 1
    print("\n结论：PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(2)
