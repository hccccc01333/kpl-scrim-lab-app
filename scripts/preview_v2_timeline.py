"""Standalone preview for the V2 timeline component (no product DB writes).

Run: python scripts/preview_v2_timeline.py
Open: http://127.0.0.1:8777/preview
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import sys
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from replay_v2_api import create_v2_router  # noqa: E402

REPLAY_ID = "d74c2bed9dc12ec6d23118fbb87b2a372993b358f1fec542ee492d580e0e64f4"

app = FastAPI()
app.include_router(create_v2_router())
app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")

PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>V2 时间轴预览</title>
<style>body{font:14px/1.5 system-ui,sans-serif;margin:24px;background:#fafafa;color:#18181b}
.panel{background:#fff;border:1px solid #e4e4e7;border-radius:10px;padding:16px}
.helper{color:#71717a;font-size:12px}.tag{display:inline-block;padding:1px 6px;border-radius:5px;background:#eef2ff;color:#3730a3;font-size:12px}
.tag.amber{background:#fef3c7;color:#92400e}.tag.gray{background:#f4f4f5;color:#52525b}
.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px}
th,td{border-bottom:1px solid #f0f0f1;padding:6px 8px;text-align:left;white-space:nowrap}
.empty{color:#71717a;padding:12px}</style></head><body>
<h2>V2 时间轴预览</h2>
<div id="v2"><div class="helper">加载中…</div></div>
<script type="module">
import { renderV2Timeline } from '/assets/v2-timeline.js';
const api = async path => { const r = await fetch(path); if(!r.ok) throw new Error((await r.json()).detail || r.status); return r.json(); };
renderV2Timeline(document.getElementById('v2'), {api, replayId: '__REPLAY__'});
</script></body></html>""".replace("__REPLAY__", REPLAY_ID)


@app.get("/preview", response_class=HTMLResponse)
def preview():
    return PAGE


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8777, log_level="warning")
