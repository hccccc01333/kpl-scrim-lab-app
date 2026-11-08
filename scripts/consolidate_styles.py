"""一次性样式收口：18 个串行样式表 → 3 层。

为什么安全：
  tokens.css 原本排在最后，已经用等特异性赢下了全部 75 个令牌
  （studio / redesign / polish / ui 里的 :root 共 33 条声明全部被覆盖）；
  polish.css 的 body[data-design="product"] 里 7 条令牌也被 tokens.css 的同名块覆盖。
  因此把这些死声明删掉、把令牌层提到最前，计算结果不变。

保留的只有「非令牌」规则的相对顺序：
  layout     = workbench → studio → redesign → polish
  components = archive → profile → team-archive → team → player → identity
               → ui → analysis-workspace → depth → dashboard-ext → update
               → tokens 尾部的数字规则 → design/base
  vendor/refsite.css 从此不进主页面（它只服务 .refsite 作用域，主页面已无此标记）。

用法：
    python scripts/consolidate_styles.py --check     # 只报告，不写文件
    python scripts/consolidate_styles.py --write     # 写入 web/styles/
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
OUT = WEB / "styles"
ARCHIVE = ROOT / ".archive" / "2026-11-07-frontend-cleanup" / "web-css"

LAYOUT = ["workbench.css", "studio.css", "redesign.css", "polish.css"]
COMPONENTS = [
    "archive.css", "profile.css", "team-archive.css", "team.css", "player.css",
    "identity.css", "ui.css", "analysis-workspace.css", "depth.css",
    "dashboard-ext.css", "update.css",
]

ROOT_BLOCK = re.compile(r":root\s*\{[^{}]*\}")


def strip_root(text: str, rel: str) -> tuple[str, list[str]]:
    """删除被 tokens.css 完全覆盖的 :root 块。"""
    removed: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        removed.append(rel)
        return ""

    out = ROOT_BLOCK.sub(_sub, text)
    return out, removed


def strip_polish_body_tokens(text: str) -> tuple[str, int]:
    """polish.css 的 body[data-design="product"] 里 7 条令牌已被覆盖，只留 background。"""
    m = re.search(r'(body\[data-design="product"\])\s*\{([^{}]*)\}', text)
    if not m:
        return text, 0
    body = m.group(2)
    kept: list[str] = []
    dropped = 0
    for raw in body.split(";"):
        if not raw.strip():
            continue
        if raw.strip().startswith("--"):
            dropped += 1
            continue
        kept.append(raw.strip())
    new_block = f'{m.group(1)}{{\n  ' + ";\n  ".join(kept) + ";\n}"
    return text[: m.start()] + new_block + text[m.end():], dropped


def read(rel: str) -> str:
    return (WEB / rel).read_text(encoding="utf-8", errors="replace")


def build() -> dict[str, str]:
    removed: list[str] = []

    # ---- 令牌层 ----
    tokens_src = read("tokens.css")
    # 尾部数字规则要留在 components 层末尾（保持它原本接近末尾的位置）
    m = re.search(r"(?s)(/\*\s*数字：位数对齐[^*]*\*/\s*\[data-num\].*)$", tokens_src)
    numbers_rule = ""
    tokens_body = tokens_src
    if m:
        numbers_rule = m.group(1).strip()
        tokens_body = tokens_src[: m.start()].rstrip()

    tokens_out = tokens_body.replace(
        "加载顺序：本文件必须最后加载，用等特异性覆盖 polish.css / studio.css /\n"
        "   redesign.css 里各自的 :root，避免旧声明反杀。",
        "加载顺序：本文件现在**第一个**加载。原先 studio / redesign / polish / ui 里\n"
        "   各自的 :root 已在 2026-11-07 收口时删除，它们是死声明（全部被这里覆盖）。",
    )

    # ---- 布局层 ----
    layout_parts = []
    for rel in LAYOUT:
        text = read(rel)
        if rel == "polish.css":
            text, dropped = strip_polish_body_tokens(text)
            if dropped:
                removed.append(f"polish.css body[data-design] 内 {dropped} 条令牌")
        text, r = strip_root(text, rel)
        removed.extend(r)
        layout_parts.append(f"/* ===== {rel} ===== */\n{text.strip()}")

    # ---- 组件层 ----
    comp_parts = []
    for rel in COMPONENTS:
        text = read(rel)
        text, r = strip_root(text, rel)
        removed.extend(r)
        comp_parts.append(f"/* ===== {rel} ===== */\n{text.strip()}")
    comp_parts.append(f"/* ===== tokens.css（数字排版规则，保持原位置）===== */\n{numbers_rule}")
    comp_parts.append(f"/* ===== design/base.css ===== */\n{read('design/base.css').strip()}")

    header = """/* 样式层 1/3 · 令牌
   ------------------------------------------------------------------
   唯一真相源。新增颜色 / 字号 / 间距前先改这里，不允许在下面两层写裸 hex。
   2026-11-07 收口：18 个串行样式表合并为 3 层，本层第一个加载。
*/
"""

    return {
        "tokens.css": header + "\n" + tokens_out.strip() + "\n",
        "layout.css": (
            "/* 样式层 2/3 · 骨架\n"
            "   ------------------------------------------------------------------\n"
            "   外壳、导航、页面模板、打印。来源：workbench / studio / redesign / polish。\n"
            "*/\n\n" + "\n\n".join(layout_parts) + "\n"
        ),
        "components.css": (
            "/* 样式层 3/3 · 组件与页面\n"
            "   ------------------------------------------------------------------\n"
            "   卡片、表格、图表、各页面私有块。来源：archive / profile / team-archive /\n"
            "   team / player / identity / ui / analysis-workspace / depth / dashboard-ext /\n"
            "   update / tokens 数字规则 / design-base。\n"
            "*/\n\n" + "\n\n".join(comp_parts) + "\n"
        ),
        "_removed": removed,  # type: ignore[dict-item]
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="写入 web/styles/ 并归档源文件")
    ap.add_argument("--check", action="store_true", help="只报告（默认行为）")
    args = ap.parse_args()

    result = build()
    removed = result.pop("_removed")
    print("=== 删除的死令牌块 ===")
    for r in removed:
        print("   -", r)

    total_src = sum((WEB / f).stat().st_size for f in LAYOUT + COMPONENTS + ["tokens.css", "design/base.css"])
    total_out = 0
    print("\n=== 产出 ===")
    for name, text in result.items():
        data = text.encode("utf-8")
        total_out += len(data)
        print(f"  {name:16s} {len(data):>8,} B  {text.count(chr(10)):>5} 行")
    print(f"\n  源合计 {total_src:>10,} B   产出 {total_out:>10,} B   请求数 18 → 3")

    if args.write:
        OUT.mkdir(exist_ok=True)
        ARCHIVE.mkdir(parents=True, exist_ok=True)
        for name, text in result.items():
            (OUT / name).write_text(text, encoding="utf-8")
        # 源文件归档（不直接删除）
        for rel in LAYOUT + COMPONENTS + ["tokens.css", "design/base.css"]:
            src = WEB / rel
            if src.exists():
                dst = ARCHIVE / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        print(f"\n已写入 {OUT}")
        print(f"源文件已归档到 {ARCHIVE}")
    else:
        print("\n（--check 模式，未写文件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
