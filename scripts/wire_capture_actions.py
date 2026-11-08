"""把采集页的交互（点击/勾选/afterRender）接进 features.js，并补采集页样式。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUB = Path(__file__).resolve().parents[1] / "v3" / "public"
FEATURES = PUB / "features.js"
CSS = PUB / "style.css"

edits: list[tuple[Path, str, str, str]] = []


def plan(path: Path, old: str, new: str, label: str) -> None:
    count = path.read_text(encoding="utf-8").count(old)
    if count != 1:
        raise SystemExit(f"✗ {label}: 锚点出现 {count} 次（需要 1 次）")
    edits.append((path, old, new, label))
    print(f"  ✓ {label}")


plan(FEATURES,
     "function click(event) { const b=event.target.closest('[data-feature-action]');",
     "function click(event) { if(capturePageV1.click(event))return true; const b=event.target.closest('[data-feature-action]');",
     "features.js click 转发采集页")

plan(FEATURES,
     "function change(event) {\n",
     "function change(event) {\nif(capturePageV1.change(event))return;\n",
     "features.js change 转发采集页")

plan(FEATURES,
     "afterRender:()=>{updatePairs();updateTeamBp()}",
     "afterRender:()=>{updatePairs();updateTeamBp();capturePageV1.afterRender()}",
     "features.js afterRender 通知采集页")

CSS_ADD = """
/* ---- 采集页交互件（2026-11-07）---- */
.capture-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.capture-actions button[disabled] { opacity: .5; cursor: not-allowed; }
.capture-hint { margin: 8px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }
.capture-notice { margin: 0 0 12px; padding: 10px 14px; border-radius: 8px; background: var(--soft); color: var(--accent); font-size: 13px; }
.capture-notice.is-error { background: #fae7e3; color: #a54c46; }
.capture-auth { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; padding: 4px 0 2px; }
.capture-auth > div { display: flex; flex-direction: column; gap: 2px; }
.capture-auth b { font-size: 15px; }
.capture-auth small { color: var(--muted); font-size: 12px; }
.capture-qr { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; padding: 4px 0; }
.capture-qr img { width: 168px; height: 168px; border: 1px solid var(--line); border-radius: 10px; background: #fff; }
.capture-qr-note { margin: 0; color: var(--muted); font-size: 13px; }
.capture-qr-status { margin: 6px 0 10px; font-weight: 600; }
.capture-sub { margin-top: 22px; border-top: 1px solid var(--line); padding-top: 16px; }
.capture-sub h3 { margin: 0 0 10px; font-size: 14px; font-weight: 700; }
.capture-inline-form { display: flex; gap: 10px; align-items: flex-end; margin-bottom: 10px; flex-wrap: wrap; }
.capture-inline-form label { flex: 1 1 320px; display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: var(--muted); }
.capture-inline-form input { padding: 9px 11px; border: 1px solid var(--line); border-radius: 8px; font: inherit; color: var(--text); background: #fff; }
.capture-check-row { grid-template-columns: 24px 90px minmax(140px,1.4fr) minmax(90px,1fr) 88px !important; cursor: pointer; }
.capture-check-row input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--accent); }
"""

if "--write" not in sys.argv:
    print("  · style.css 待追加采集页样式")
    print("\n（--write 才落盘）")
    raise SystemExit(0)

cache: dict[Path, str] = {}
for path, old, new, _ in edits:
    text = cache.get(path) or path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"✗ 写盘阶段锚点失配: {path.name}")
    cache[path] = text.replace(old, new, 1)

for path, text in cache.items():
    path.write_text(text, encoding="utf-8")
    print(f"  已写入 {path.name}")

css_text = CSS.read_text(encoding="utf-8")
if ".capture-actions" not in css_text:
    CSS.write_text(css_text + CSS_ADD, encoding="utf-8")
    print("  已写入 style.css（采集页交互样式）")
print("\n完成。")
