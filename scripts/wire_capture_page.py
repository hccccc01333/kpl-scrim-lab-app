"""把采集页接进 V2 前端：注册路由、加导航、加状态样式。

改动点（每处都断言，失败就整体不动）：
  features.js  1 引入 createCapture   2 实例化   3 renders 注册 ingests
               4 has() 认 ingest      5 load() 走采集加载器
               6 featureSections 把「导入表格」从 对局 挪到 采集
  app.js       7 一级导航插入「采集」
  style.css    8 新增 .result.pending 状态色
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUB = Path(__file__).resolve().parents[1] / "v3" / "public"
FEATURES = PUB / "features.js"
APP = PUB / "app.js"
CSS = PUB / "style.css"

edits: list[tuple[Path, str, str]] = []


def plan(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"✗ {label}: 锚点在 {path.name} 里出现 {count} 次（需要 1 次），已中止")
    edits.append((path, old, new))
    print(f"  ✓ {label}")


f = FEATURES.read_text(encoding="utf-8")
a = APP.read_text(encoding="utf-8")
c = CSS.read_text(encoding="utf-8")

# ---- features.js ----
plan(FEATURES, "import { createDepth } from './depth.js';",
     "import { createDepth } from './depth.js';\nimport { createCapture } from './capture-page.js';",
     "features.js 引入 createCapture")

plan(FEATURES, "const capture = (items, limit=12) => items.slice(0,limit);",
     "const capture = (items, limit=12) => items.slice(0,limit);\n"
     "  /* 采集页：读 V1 根接口，见 capture-page.js */\n"
     "  const capturePageV1 = createCapture({esc, fmt, block, stats, empty, withPage, icon});",
     "features.js 实例化采集页")

plan(FEATURES, "const renders={identity:",
     "const renders={ingest:v=>capturePageV1.render(v),identity:",
     "features.js 注册 ingest 渲染器")

plan(FEATURES, "has:name=>Object.hasOwn(endpoints,name),",
     "has:name=>Object.hasOwn(endpoints,name)||name==='ingest',",
     "features.js has() 认 ingest")

plan(FEATURES, "load:(name,key,signal)=>Promise.all(",
     "load:(name,key,signal)=>name==='ingest'?capturePageV1.load(name,key,signal):Promise.all(",
     "features.js load() 走采集加载器")

# ---- featureSections：把 导入表格 从 对局 挪到 采集 ----
m = re.search(r"^(  matches: \[.*)$", f, re.M)
if not m:
    raise SystemExit("✗ 找不到 featureSections.matches 行")
matches_line = m.group(1)
moved = re.sub(r",\s*\['capture',\s*'[^']*'\](\s*\])", r"\1", matches_line)
if moved == matches_line:
    raise SystemExit("✗ matches 行里没找到 capture 子页签")
new_sections = (
    "  ingest: [['ingest','采集总览'], ['capture','导入表格']],\n"
    + moved
)
edits.append((FEATURES, matches_line, new_sections))
print("  ✓ features.js 采集分组（导入表格 从 对局 迁到 采集）")

# ---- app.js 一级导航 ----
m = re.search(r"(\['overview',\s*'[^']*'\],)(\s*)", a)
if not m:
    raise SystemExit("✗ app.js nav 里找不到 overview 项")
edits.append((APP, m.group(1), m.group(1) + " ['ingest', '采集'],"))
print("  ✓ app.js 一级导航插入「采集」")

# ---- style.css 待审核状态色 ----
m = re.search(r"\.result\.loss\s*\{[^}]*\}", c)
if not m:
    raise SystemExit("✗ style.css 里找不到 .result.loss")
edits.append((CSS, m.group(0),
              m.group(0) + "\n.result.pending { color: #8a6d3b; background: #fbf3e4; }"))
print("  ✓ style.css 新增 .result.pending")

if "--write" not in sys.argv:
    print("\n（--write 才落盘）")
    raise SystemExit(0)

cache: dict[Path, str] = {}
for path, old, new in edits:
    text = cache.get(path) or path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"✗ 写盘阶段锚点失配: {path.name}")
    cache[path] = text.replace(old, new, 1)

for path, text in cache.items():
    path.write_text(text, encoding="utf-8")
    print(f"  已写入 {path.name}")
print("\n完成。")
