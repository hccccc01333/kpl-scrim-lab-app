"""前端资产引用图审计：找出真正没有被任何页面/模块引用的文件。

判定规则：
- 入口：web/studio.html、web/index.html、web/replay-review.html、web/collection-*.html
- 从入口出发，解析 <link href> / <script src> / import ... from '...' / import('...') / 字符串常量中的 /assets/ 路径
- 递归展开，得到可达集合；web/ 顶层文件里不在可达集合的即为死文件
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict, deque
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WEB = Path(__file__).resolve().parents[1] / "web"
ENTRIES = ["studio.html"]

HTML_LINK = re.compile(r'<link[^>]+href="([^"]+\.css[^"]*)"')
HTML_SCRIPT = re.compile(r'<script[^>]+src="([^"]+)"')
JS_IMPORT = re.compile(r"""(?:from|import)\s*['"]([^'"]+)['"]""")
JS_DYNAMIC = re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)""")
ASSET_STRING = re.compile(r"""['"](/assets/[^'"?]+)""")
CSS_URL = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""")


def norm(spec: str, base: Path) -> str | None:
    spec = spec.split("?")[0].split("#")[0].strip()
    if not spec:
        return None
    if spec.startswith("/assets/"):
        name = spec[len("/assets/"):]
    elif spec.startswith("./") or spec.startswith("/") or "://" not in spec:
        # 相对路径
        try:
            name = str((base.parent / spec.lstrip("./")).resolve().relative_to(WEB.resolve()))
        except Exception:
            name = spec.lstrip("./")
    else:
        return None
    name = name.replace("/", "\\")
    return name


def scan(path: Path) -> set[str]:
    out: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return out
    pats = []
    if path.suffix == ".html":
        pats = [HTML_LINK, HTML_SCRIPT]
    elif path.suffix in (".js", ".mjs"):
        pats = [JS_IMPORT, JS_DYNAMIC, ASSET_STRING]
    elif path.suffix == ".css":
        pats = [CSS_URL]
    for pat in pats:
        for m in pat.finditer(text):
            n = norm(m.group(1), path)
            if n:
                out.add(n)
    return out


def main() -> int:
    graph: dict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    q = deque(ENTRIES)
    while q:
        cur = q.popleft().replace("/", "\\")
        if cur in seen:
            continue
        seen.add(cur)
        p = WEB / cur
        if not p.exists():
            continue
        for dep in scan(p):
            graph[cur].add(dep)
            if (WEB / dep).exists() and dep not in seen:
                q.append(dep)

    top = sorted(p for p in WEB.iterdir() if p.is_file() and p.suffix in (".js", ".css", ".html", ".mjs"))
    dead = [p for p in top if p.name not in seen]
    alive = [p for p in top if p.name in seen]

    print(f"入口: {ENTRIES}")
    print(f"可达文件: {len(alive)}   顶层死文件: {len(dead)}\n")
    if dead:
        print("=== 未被引用的顶层文件 ===")
        total = 0
        for p in dead:
            total += p.stat().st_size
            print(f"  {p.stat().st_size:>9,} B  {p.name}")
        print(f"  合计 {total/1024:.0f} KB")
    print("\n=== 可达但疑似只在死链里（间接引用）===")
    for name in sorted(seen):
        if name.endswith((".png", ".jpg", ".webp", ".woff2", ".svg")):
            continue
        print("  ", name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
