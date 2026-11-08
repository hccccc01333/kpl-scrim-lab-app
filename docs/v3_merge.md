# V3：唯一应用

2026-11-08。V3 是唯一的产品入口；V1 工作台和 V2 独立服务已退役。

## 现在的结构

**一个 FastAPI app，一张路由表。** 不再有 V1 app 挂 V2 app：

```
server.py
 ├─ /            V3 默认界面（v3/public/index.html）
 ├─ /static      V3 前端资源
 ├─ /v3          302 → 根路径（旧链接兼容）
 ├─ /api/*       V3 路由表：采集/校对 + 只读分析
 ├─ /assets      采集规范/模板等静态资料（web/）
 └─ /studio      302 → 根路径（V1 旧入口已退役）
```

一个进程、一个端口（8766）、一份 `data/`。根路径直接返回 V3。

`server.py` 末尾的 `_mount_v3()`：

- 用 `importlib` 按路径加载 `v3/serve.py`
- 加载前把 `v3/` 加进 `sys.path`，否则 `deep_analysis` 找不到
- `app.include_router(module.router)` 把 V3 路由并进同一个 app
- `app.mount('/static', ...)` 指向 `v3/public`
- V1 的 `/api/*` 注册在前，路径重复时优先命中；V3 的 `/api/matches` 是 GET，
  V1 的同名路由是 POST，不会互相遮挡
- 加载失败只打印告警；根路径返回 503 提示前端资源缺失

## V1 / V2 退役清单

| 旧入口 | 现状 |
|---|---|
| `/studio` | 302 到 `/`，不再提供 V1 界面 |
| `启动赛训数据V2.bat` | 移到 `.archive/2026-11-08-v1v2-retire/` |
| `frontend-v2-rebuild/` | 改名为 `v3/` |
| V2 独立 `serve.py --port 8771` | 仅保留给开发和演示，不是产品入口 |
| `scripts/audit_v2.py`、`scripts/patch_v2_paths.py` | 已归档到同一目录 |

## 历史：V2 前端为什么曾改路径

V2 曾独占根路径，资源和接口都写死绝对路径。挂到 `/v3` 下会全部 404。当时的改动（脚本已归档）：

| 位置 | 改动 |
|---|---|
| `index.html` | `/static/...` → `static/...` |
| `style.css` | 字体 `url('/static/media/...')` → 相对 |
| `*.js` | `fetch('/api/...` → `fetch(API_BASE + '/api/...` |

`API_BASE` 用 `new URL('..', import.meta.url)` 推导，所以 **根路径、`/v3` 和 8771
独立运行都正常**。

## 采集链路已迁入 V3

「采集」一级导航，5 个子页签：

| 页面 | 展示 | 能做的事 |
|---|---|---|
| 截图 OCR | 按局分组的卡片：日期/时长/比分/胜负、10 位选手昵称+英雄、页数、待处理提示；展开看逐页明细和提示原文 | 多选上传 → 自动 OCR（先传 `/api/images`，再触发 `/postgame/images/{id}/ocr`）；选通道后 `{imageIds}` 挂载 |
| 录屏 | 文件名/时长/分辨率/fps/体积、识别状态与百分比、采样与计时帧数、蓝红击杀、证据帧、提示数、报告覆盖度 | 上传录屏（XHR 带进度）→ 自动排队识别；每份可重新识别；有任务时每 3 秒自动刷新 |
| 回放 | 十人指令与评分表 | **研究中，不作为采集来源**（见下） |
| 导入表格 | 表格结构、17 列字段要求（运行时读 `requirements.json`）、模板下载、常见错误 | 预览与导入 |

采集总览的每条通道行有「校对 →」入口，跳到 `#review/<channelId>`。

### 页签按采集档位收敛（2026-11-07）

采集只有 **一个** 页签「营地同步」，二级导航条因此隐藏。其余四个页面**降级为入口**，
放在营地同步页的「来源档位」块里，因为它们是兜底/补充，不是主路径：

| 来源 | 档位 | 入口 |
|---|---|---|
| 官方回放链接 | 唯一必采 | 无需单独操作（在校对页关联） |
| 营地数据自动采集 | 推荐主路径 | `#ingest` |
| 七张赛后截图 | 兜底路径 | `#shots` |
| 完整录屏 | 兜底路径 | `#videos` |
| 标准表格 | 选填·补充 | `#capture` |

**回放文件（`.abc` / `.ope` 本地解析）已从采集来源里撤下**（2026-11-07，用户判断：
解析口径还没研究透）。页面 `#replays` 保留可访问，但页头标注「回放（研究中）」并给出
不入库的提示 —— 内部还能看，产品面上不再作为采集入口。

注意别和「官方回放链接」混淆：后者是营地网页回放，属于必采；`.abc`/`.ope` 是本机文件解析，
是另一回事。

档位措辞必须与 `web/collection-guide.js:77-81` 和 `web/capture-guide/requirements.json`
保持一致，不要另造词。

**坑：`current()` 用 `Object.hasOwn(labels, name)` 判断路由合法性。** 路由名从
`featureSections` 撤下后会同时从 `labels` 消失，随即被当成未知路由**静默退回首页**。
撤页签时必须把路由名补进 `app.js` 的 `Object.assign(labels, {...})`。

### 逐项校对页（`#review/<channelId>`）

`v3/public/review-page.js`。一条通道对应一局，这一页是素材挂完之后的人工核对：

| 区块 | 内容 |
|---|---|
| 对局 | 日期、比分、胜负、阵营、时长、模式 |
| 素材来源 | 6 类来源的状态与计数，必采来源左侧加竖线，缺失标红 |
| 草稿数据 | 10 行 × 9 个可编辑字段（英雄 + 击杀/死亡/助攻/经济/输出/承伤/参团/评分），每格带来源与置信度色标 |
| 跨来源冲突 | 折叠，默认只显示冲突数量 |
| 复核与入库 | 复核备注、标记复核、保存到正式统计 |
| 变更记录 | 最近 20 条 |

写接口：

- `PATCH /api/channels/{id}/draft` `{players:[{side, slot, hero?, fields:{...}}]}`
- `POST /api/channels/{id}/review` `{reviewedBy, notes}`
- `POST /api/channels/{id}/save`

**边界（与后端一致）**：昵称不能在草稿里改 —— `channel_store.apply_draft` 只接受 `hero` 和 `fields`。
身份错请走「选手认领」。改草稿会触发 `invalidate_review`，页面会重新读取并提示需要重新复核。

这些接口都在根路径 `/api/...` 上，现在属于 V3 同一张路由表。素材页和采集页用绝对路径请求；
`v3/serve.py` 单独跑（开发/演示）时，页面会提示采集接口未挂载。

实现文件：

- `v3/public/capture-page.js` —— 采集总览（授权 / 白名单 / 拉取 / 入库）
- `v3/public/sources-page.js` —— 截图 / 录屏 / 回放三页
- `scripts/wire_capture_page.py`、`wire_capture_actions.py`、`wire_sources_pages.py` —— 把页面接进
  `features.js` 的 `endpoints / has / load / renders / click / afterRender` 契约

## 还没做

1. **回放文件导入** —— 回放解析口径未定，暂不作为采集来源
2. **首局建档 / 手工建局** —— V1 的「新建一局」入口还没搬进 V3
3. **打包** —— `make_release.py` 已纳入 V3 的 `serve.py` / `deep_analysis.py` /
   `demo_data.py` / `public/`；`v3/` 仍未纳入 git，发布补丁能带上它，
   但版本历史里看不到
4. **V1 静态资料清理** —— `web/` 仍保留采集规范、模板和旧页面脚本；`/studio` 已退役，
   但 `/assets` 还能直接访问 `studio.html`，后续可把 V1 专用文件移入归档目录

## 已完成

- **单应用**：V2 的 40 条路由已改成 `APIRouter`，并进 `server.py`；不再挂第二个 app
- **入口**：根路径即 V3；`/v3`、`/studio`、`/analysis` 都 302 到根路径
- **打包**：`make_release.py` 纳入 `v3/serve.py`、`deep_analysis.py`、`demo_data.py`、`public/`
- **缓存**：V3 路由的写操作会通过 `server.py` 中间件调用 `invalidate_snapshot()`

## 坑：async 回调不能拿来判断「是否处理了事件」

`features.js` 的点击分发原本写成：

```js
if (reviewPage.click(event)) return true;   // ✗
```

`click` 是 `async` 函数，返回值是 Promise —— **恒为真**。结果第一个模块就吞掉了所有点击，
后面的模块永远收不到事件，页面上表现为「按钮点了没反应、也不报错」。

修复方式：先用选择器同步判断，再交给异步函数执行：

```js
if (event.target.closest('[data-review-action]')) { reviewPage.click(event); return true; }
```

这个 bug 曾导致逐项校对页的三个按钮上线即失效，靠「数据库副本 + 真实点击」才发现。
**渲染正常不等于能交互**，改事件分发后必须真的点一遍。

## 验证方式

```powershell
python server.py                        # 8766
python scripts/audit_v3_regression.py http://127.0.0.1:8766   # 26 条路由逐条渲染 + 报错检查
python scripts/audit_sources_pages.py   # 三个素材页（脚本内 BASE 改到 8766）
python scripts/audit_review_visual.py   # 逐项校对页（只读，不写真实数据）
```

回归脚本会打印每条路由的 h1、内容长度、JS 异常数，失败时返回非零。

## 主数据与批量操作（2026-11-08）

- **战队名只有一个权威来源**：`workspace_store.teams`。`team_clusters` 覆盖层只做旧数据兼容；`/api/studio/teams/rename` 和 `/api/studio/workspace/teams` 都会同步两处。历史差异用 `POST /api/studio/workspace/teams/reconcile` 对账（`?dry_run=1` 只报告）。
- **旧名单迁移**：建档页的「迁移旧名单」把 `settings.roster` 写入 `players`，保留旧 id，按 id / 营地 ID / 同战队同名同位置去重，并写入 `rosterMigratedAt`。
- **批量命名**：建档页支持粘贴名单或 CSV，按待命名顺序对应；显式写 `#1=队名` 可跳过顺序。服务端 `POST /api/studio/teams/rename-batch` 单事务写工作区与覆盖层。
- **待确认批量**：`POST /api/studio/workspace/pending/confirm-batch` 单事务确认一局的所有字段，失败全回滚；前端按局「全部确认」已切到该接口。

## 踩过的坑

- **TypeScript 语法混进 JS**：`const failed: string[] = []` 让整个 V3 白屏。`node --check` 能过，
  Chromium 直接 `Missing initializer in const declaration`。提交前用浏览器实测，别只看 node。
- **`load()` 没保存数据**：采集页的写操作后重绘依赖 `state.value`，漏存会让「点了没反应」且不报错。
- **`.match-row` 的 7 列网格**：直接塞 4 个字段会撑出 76px 行高，采集页要用 `.capture-rows` 变体重排列宽。
