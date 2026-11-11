"""把「导入表格」改造成带规格说明的页面。

字段规格不写死在页面里，运行时读 /assets/capture-guide/requirements.json ——
那份文件是前后端共用的事实源（collection-v3），避免两边漂移。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PUB = Path(__file__).resolve().parents[1] / "v3" / "public"
SOURCES = PUB / "sources-page.js"
FEATURES = PUB / "features.js"

edits: list[tuple[Path, str, str, str]] = []


def plan(path: Path, old: str, new: str, label: str) -> None:
    count = path.read_text(encoding="utf-8").count(old)
    if count != 1:
        raise SystemExit(f"✗ {label}: 锚点出现 {count} 次（需要 1 次）")
    edits.append((path, old, new, label))
    print(f"  ✓ {label}")


# ---- 1) 返回链接并入 scopeNote，三个来源页自动获得 ----
plan(SOURCES,
     """  function scopeNote() {
    return '<div class="scope-note"><span>口径</span> 本页直接读 V1 的本机素材库，'
      + '不受顶部「数据范围」影响；素材可能包含非训练赛。</div>';
  }""",
     """  function backLink() {
    return '<p class="sv-back"><a class="control" href="#ingest">← 返回营地同步</a></p>';
  }

  function scopeNote() {
    return backLink() + '<div class="scope-note"><span>口径</span> 本页直接读 V1 的本机素材库，'
      + '不受顶部「数据范围」影响；素材可能包含非训练赛。</div>';
  }""",
     "来源页加返回链接")

# ---- 2) load 增加 capture 分支 ----
plan(SOURCES,
     """    } else {
      const [replays, channels] = await Promise.all([""",
     """    } else if (name === 'capture') {
      const [spec, channels] = await Promise.all([
        fetch('/assets/capture-guide/requirements.json', { cache: 'no-store' })
          .then((r) => (r.ok ? r.json() : null)).catch(() => null),
        v1('channels', { signal }).catch(() => ({ channels: [] })),
      ]);
      value = { spec, channels };
    } else {
      const [replays, channels] = await Promise.all([""",
     "load 增加表格页")

# ---- 3) render 分发 ----
plan(SOURCES,
     "    if (name === 'shots') return shotsPage(value);",
     "    if (name === 'capture') return tablePage(value);\n    if (name === 'shots') return shotsPage(value);",
     "render 分发增加表格页")

# ---- 4) 插入表格页实现 ----
TABLE_PAGE = r'''
  // ---------------- 导入表格 ----------------

  function tablePage(value) {
    const spec = value?.spec;
    const sheet = spec?.sheet;

    const upload = `<div class="upload-area">
      <span class="upload-icon">${icon('sources')}</span>
      <h2>选择本局十人表</h2>
      <p>先选择文件，检查工作表、字段和数据粒度；预览阶段不会改动原始文件，也不会写入正式统计。</p>
      <label class="primary upload-button">选择表格<input type="file" data-import-file accept=".csv,.tsv,.xlsx,.xlsm"></label>
      <p data-import-status role="status"></p>
    </div><div data-import-preview></div>`;

    if (!sheet) {
      return withPage('导入表格', '选填 · 补充 —— 只在营地与截图都没有某个字段时才需要手填。',
        backLink()
        + noticeBox()
        + block('上传', '支持 CSV / TSV / XLSX / XLSM，单个文件不超过 20 MB。', upload)
        + `<div class="capture-notice is-error" role="status">读取不到字段规格文件 capture-guide/requirements.json，无法展示字段要求。请确认通过 server.py 启动（该文件由 /assets 提供）。</div>`, false);
    }

    const requiredCount = sheet.columns.filter((column) => column.required).length;
    const columnRows = sheet.columns.map((column) => `<tr class="${column.required ? 'is-required' : ''}">
      <td class="tbl-col-name">${esc(column.name)}</td>
      <td class="tbl-col-field"><code>${esc(column.field)}</code></td>
      <td class="tbl-col-flag">${column.required ? '<span class="result pending">必填</span>' : '<span class="tbl-optional">选填</span>'}</td>
      <td class="tbl-col-rule">${esc(column.rule)}</td>
    </tr>`).join('');

    const lanes = (sheet.positions || []).join(' / ');

    return withPage('导入表格', '选填 · 补充 —— 只在营地与截图都没有某个字段时才需要手填。表格必须按下面的列结构，否则导入后进不了平台。',
      backLink()
      + noticeBox()
      + block('上传与预览', '支持 CSV / TSV / XLSX / XLSM，单个文件不超过 20 MB。先预览识别结果，确认后再导入。', upload)
      + block('表格长什么样', '一行一个人，一局正好十行。',
        `<div class="sv-spec-grid">
          <div><b>行数</b><span>${fmt(sheet.rows)} 行（我方 5 + 对方 5）</span></div>
          <div><b>阵营</b><span>${(sheet.sides || []).map((s) => (s === 'blue' ? 'blue（蓝方）' : 'red（红方）')).join(' / ')}，每方 5 行</span></div>
          <div><b>分路</b><span>${esc(lanes)}，每方每个分路各 1 人</span></div>
          <div><b>唯一性</b><span>选手昵称十行不重复；每方英雄不重复</span></div>
        </div>
        <p class="capture-hint">多局或跨局汇总不要放进本局表格，走「批量导入」。</p>`)
      + block('字段要求', `共 ${sheet.columns.length} 列，其中 ${requiredCount} 列必填。`,
        `<div class="table-wrap sv-spec-wrap"><table class="sv-spec-table"><thead><tr>
          <th>列名</th><th>字段</th><th>要求</th><th>规则</th>
        </tr></thead><tbody>${columnRows}</tbody></table></div>`)
      + block('模板与示例', '直接用模板填，列名不要改；示例文件可以对照格式。',
        `<div class="sv-downloads">
          <a class="control" href="/assets/capture-guide/match-template.xlsx" download>${icon('sources')} 下载 XLSX 模板</a>
          <a class="control" href="/assets/capture-guide/match-template.csv" download>${icon('sources')} 下载 CSV 模板</a>
          <a class="control" href="/assets/capture-guide/match-example.csv" download>${icon('sources')} 下载示例</a>
        </div>`)
      + block('最常见的三个错', '导入失败的绝大多数都是这三种。',
        `<ul class="sv-pitfalls">
          <li><b>对局 ID 十行不一致</b> —— 同一局十行必须同一个 ID，且不能用示例里的编号。</li>
          <li><b>数值写成「1.2万」</b> —— 金币、输出、承伤都要原始整数，不要带单位或缩写。</li>
          <li><b>参团率写成 0.625</b> —— 要 0–100 的数值，直接写 62.5。</li>
        </ul>`)
      , false);
  }

'''

plan(SOURCES,
     "  // ---------------- 渲染分发 ----------------",
     TABLE_PAGE + "  // ---------------- 渲染分发 ----------------",
     "插入表格页实现")

# ---- 5) features.js：capture 走素材页加载与渲染 ----
plan(FEATURES,
     "load:(name,key,signal)=>name==='ingest'?capturePageV1.load(name,key,signal)",
     "load:(name,key,signal)=>name==='ingest'?capturePageV1.load(name,key,signal)"
     ":name==='capture'?sourcePages.load(name,key,signal)",
     "features 让 capture 走素材页加载")

plan(FEATURES,
     "const renders={ingest:v=>capturePageV1.render(v),",
     "const renders={ingest:v=>capturePageV1.render(v),capture:v=>sourcePages.render('capture',v),",
     "features 用新表格页渲染 capture")

CSS = PUB / "style.css"
CSS_ADD = """
/* ---- 导入表格规格页（2026-11-07）---- */
.sv-back { margin: 0 0 10px; }
.sv-spec-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
.sv-spec-grid > div { display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; border: 1px solid var(--line); border-radius: 8px; background: #fff; font-size: 12px; }
.sv-spec-grid b { font-size: 13px; }
.sv-spec-grid span { color: var(--muted); }
.sv-spec-wrap { overflow-x: auto; }
.sv-spec-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.sv-spec-table th { text-align: left; padding: 8px; border-bottom: 1px solid var(--line); color: var(--muted); font-weight: 600; white-space: nowrap; }
.sv-spec-table td { padding: 7px 8px; border-bottom: 1px solid var(--line-soft); vertical-align: top; }
.sv-spec-table tr.is-required td { background: rgba(23,107,105,.03); }
.sv-spec-table code { font-family: var(--mono); font-size: 11px; color: var(--accent); }
.tbl-col-name { font-weight: 600; white-space: nowrap; }
.tbl-col-flag { white-space: nowrap; }
.tbl-optional { color: var(--quiet); font-size: 11px; }
.tbl-col-rule { color: var(--muted); }
.sv-downloads { display: flex; gap: 8px; flex-wrap: wrap; }
.sv-pitfalls { margin: 0; padding-left: 18px; font-size: 12px; display: grid; gap: 6px; color: var(--muted); }
.sv-pitfalls b { color: var(--text); }
"""

if "--write" not in sys.argv:
    print("\n（--write 才落盘）")
    raise SystemExit(0)

cache: dict[Path, str] = {}
for path, old, new, _ in edits:
    text = cache.get(path) or path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"✗ 写盘阶段锚点失配: {path.name} :: {old[:60]}")
    cache[path] = text.replace(old, new, 1)

for path, text in cache.items():
    path.write_text(text, encoding="utf-8")
    print(f"  已写入 {path.name}")

css_text = CSS.read_text(encoding="utf-8")
if ".sv-spec-table" not in css_text:
    CSS.write_text(css_text + CSS_ADD, encoding="utf-8")
    print("  已写入 style.css")
print("\n完成。")
