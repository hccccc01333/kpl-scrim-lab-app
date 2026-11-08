"""把截图/录屏/回放三页接进 features.js 与采集分组。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUB = Path(__file__).resolve().parents[1] / "v3" / "public"
FEATURES = PUB / "features.js"

edits: list[tuple[str, str, str]] = []


def plan(old: str, new: str, label: str) -> None:
    count = FEATURES.read_text(encoding="utf-8").count(old)
    if count != 1:
        raise SystemExit(f"✗ {label}: 锚点出现 {count} 次（需要 1 次）")
    edits.append((old, new, label))
    print(f"  ✓ {label}")


plan("import { createCapture } from './capture-page.js';",
     "import { createCapture } from './capture-page.js';\nimport { createSources } from './sources-page.js';",
     "引入 sources-page")

plan("const capturePageV1 = createCapture({esc, fmt, table, block, stats, empty, withPage, icon});",
     "const capturePageV1 = createCapture({esc, fmt, table, block, stats, empty, withPage, icon});\n"
     "  /* 截图 / 录屏 / 回放三个素材页，见 sources-page.js */\n"
     "  const sourcePages = createSources({esc, fmt, block, stats, empty, withPage, icon, table});",
     "实例化素材页")

plan("has:name=>Object.hasOwn(endpoints,name)||name==='ingest',",
     "has:name=>Object.hasOwn(endpoints,name)||['ingest','shots','videos','replays'].includes(name),",
     "has() 认三个素材页")

plan("load:(name,key,signal)=>name==='ingest'?capturePageV1.load(name,key,signal):Promise.all(",
     "load:(name,key,signal)=>name==='ingest'?capturePageV1.load(name,key,signal)"
     ":['shots','videos','replays'].includes(name)?sourcePages.load(name,key,signal):Promise.all(",
     "load() 走素材页加载器")

plan("const renders={ingest:v=>capturePageV1.render(v),identity:",
     "const renders={ingest:v=>capturePageV1.render(v),"
     "shots:v=>sourcePages.render('shots',v),videos:v=>sourcePages.render('videos',v),"
     "replays:v=>sourcePages.render('replays',v),identity:",
     "注册三个渲染器")

plan("function click(event) { if(capturePageV1.click(event))return true;",
     "function click(event) { if(sourcePages.click(event))return true; if(capturePageV1.click(event))return true;",
     "click 转发素材页")

plan("afterRender:()=>{updatePairs();updateTeamBp();capturePageV1.afterRender()}",
     "afterRender:()=>{updatePairs();updateTeamBp();capturePageV1.afterRender();sourcePages.afterRender()}",
     "afterRender 通知素材页")

plan("  ingest: [['ingest','采集总览'], ['capture','导入表格']],",
     "  ingest: [['ingest','采集总览'], ['shots','截图 OCR'], ['videos','录屏'], ['replays','回放'], ['capture','导入表格']],",
     "采集分组增加三个子页签")

if "--write" not in sys.argv:
    print("\n（--write 才落盘）")
    raise SystemExit(0)

text = FEATURES.read_text(encoding="utf-8")
for old, new, _ in edits:
    if text.count(old) != 1:
        raise SystemExit("✗ 写盘阶段锚点失配")
    text = text.replace(old, new, 1)
FEATURES.write_text(text, encoding="utf-8")
print("\n已写入 features.js")
