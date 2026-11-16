# 系列赛编组与系列赛分析（V2.0 阶段 01–03）

> 2026-11-14 落地；2026-11-15 跨局页改为「多场 BO 汇总 + 单场大场分析」两层。方案基线见 V2.0《跨局分析重构方案》：
> 先保证「系列赛关系正确」，再追求分析深度。本轮交付：数据层（系列赛身份）+ 编组中心交互 +
> 四项 P0 系列赛分析。长期趋势（`#cross/trends`）与教练决策闭环（阶段 05）留待下一轮。

## 1. 设计原则

1. **原始对局不变。** 系列赛是独立于单局的新关系实体；确认编组只写关系列。
2. **所有分析可追溯。** 每条结论逐局带 `matchKey`，可点进既有单局复盘 `#match/<key>`。
3. **缺数据不造假。** 缺手序 / 缺经济差 / 缺结果一律 `None` + 覆盖说明，不用 0 充数。
4. **自动建议不落库。** 编组建议只产出候选，确认后才创建；已确认编组不会被自动流程改动。

## 2. 数据层

两张新表（`data/training.sqlite3`，`workspace_store.SCHEMA`，全部 `CREATE TABLE IF NOT EXISTS`，非破坏升级）：

| 表 | 关键字段 | 约束 |
|---|---|---|
| `training_series` | `id`（`ts-YYYYMMDD-xxxx`）、`best_of`（3/5/7）、`status`（confirmed/needs_review）、`ruleset_id`、`opponent/opponent_team_id`、`session`、`schedule_id`（可选关联训练课）、`start_at/end_at`、`completion_mode`（standard/fixed）、`completion`、`notes` | — |
| `training_series_games` | `series_id`、`match_key`、`game_index`（G1..Gn） | `match_key` 全局 **UNIQUE**：一局只能属一个系列赛 |

**关系列写回（兼容层）**：确认 / 调整 / 删除时同步 `match_records` 与 `matches` 的 `series_id`、`game_no`
（这两个列早已存在但从未被写入）；删除置 NULL。操作全部记 `change_log`（entity=`series` / `match`）。

**局序规则**：不给 `gameIndex` 时按传入顺序自动编 G1..Gn；给了就必须恰好是连续 1..n——缺号意味着采集缺局，
要教练先补齐或改自动编排，不静默补号冒充完整 BO。

## 3. 规则集（`series_engine.RULESETS`）

| id | 名称 | 口径 |
|---|---|---|
| `scrim-global-team`（默认） | 全局BP · 队内不复用 | 本系列赛某队已选英雄不能再由该队选择（换边不重置，上局禁用不延续）；对手已选对我方仍可选 |
| `scrim-global-shared` | 全局BP · 双方共同不复用 | 系列赛内任一方选过的英雄双方都不能再选 |
| `per-game` | 每局独立 BP | 无跨局消耗；账本只记录，不产生「不可再选」 |

沿用 `bp_rules.py` 的赛训口径（`BO3/BO5/BO7 最大局数`、决胜目标 `ceil(B/2)`）；**绝不默认套用 KPL 赛事规则**。

## 4. 完赛判定（`series_engine.derive_completion`）

- 标准决胜：任一方到 `ceil(B/2)` 胜即完赛（BO5 的 3:0 / 3:1 / 3:2 都是完整 BO5）；打满 B 局也算完赛。
- 固定打满（`fixed`）：打满 B 局才算完赛（训练赛约定打满）。
- 其余一律 `open`，不猜。教练可 PATCH 显式标注 `interrupted`（中断）/ `incomplete`（采集不完整），教练标注优先于推导。
- 前端「打满」徽标按**实际局数**显示（局数 ≥ bestOf），不单独依赖建组时的 `completionMode`：BO3 打了 3 局、BO5 打了 5 局都显示；固定打满但只打了 3/5 局的不显示。存储的 mode 不变。

## 5. 自动编组建议（`POST /api/series/suggest`）

分组：同一对手 + 同一天 + 时间连续（间隔 ≤180min）；间隔 >90min 提示核实；跨午夜且间隔未超阈值保持同组；
缺开赛时间的同日局先归同组并要求确认局序；对手缺失退化为（日期 + 训练组）分组并提示补齐；已在其他系列赛的局进 `blocked`。

推荐赛制：3 局→BO3、5 局→BO5、7 局→BO7，2/4/6 局按最接近的赛制给候选（未完赛），**不强行确定**——三局也可能是 3:0 完赛的 BO5。
超过 7 局的候选组只提示「请拆分后再编组」，不自动切分。

## 6. API（`v3/series_api.create_series_router`）

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/series` | GET | 列表（from/to/session/opponent/bestOf/status/completion），逐局带日期/时间/胜负/10 分钟差，附比分与完赛状态；只建已入组对局的完整向量 |
| `/api/series/bootstrap` | GET | 编组页一次取全：轻量向量（时间轴 / 对手 / 胜负 / 比分 / 阵容）+ 系列赛 + 自动候选；按数据指纹整包缓存 |
| `/api/series/{id}` | GET | 单组简介 |
| `/api/series/suggest` | POST | 编组建议（不落库），返回 `suggestions` + `blocked`；只读接口，不触发快照 / 向量缓存失效 |
| `/api/series` | POST | 创建并确认。校验：bestOf∈{3,5,7}、局数≤上限、无重复 key；重复归属 → **409** 带 `occupied`。支持显式 `id`（撤销删除按原 ID 重建） |
| `/api/series/{id}` | PATCH | 改赛制 / 局序（games 全量替换 = 调序、增删、拆分、合并）/ 执行方式 / 教练标注 |
| `/api/series/{id}` | DELETE | 只删编组关系，保留对局，返回释放的 matchKey 列表 |
| `/api/series/{id}/analysis` | GET | 单组 P0 分析（下钻时才取完整详情：手序 / 禁用 / 过程覆盖） |
| `/api/cross/series-summary` | GET | 多组汇总 + 「本轮需要关注」清单（账本按向量出场阵容口径，不取详情） |
| `/api/metadata/icons` | GET | 编组页轻量图标目录 + 英雄分路标签；只读 `resources/`，不依赖分析快照 |

数据依赖经 `lookup` 注入（`repo/vectors/vectors_for/builder_vectors/detail`），隔离测试可传假实现（见 `tests/test_series_api.py`）。

**性能约定（2026-11）**：编组页只打一个 bootstrap；轻量向量按“对局包 + 队名/对局元数据”指纹缓存，
默认查询再落盘到 `data/.cache/series-vectors.json`，服务重启后首次进页直接读盘（实测 2.4s → 0.26s）。
命中缓存时连仓库快照都不建，所以确认编组 / 改赛制 / 调序实测 60–90ms（此前每次可能等 15 秒快照过期后重建，约 2–4 秒）。
头像走 `/api/metadata/icons`，热缓存约 4ms、冷启动约 90ms，不再等 metadata 的仓库快照。
系列赛列表 / 汇总只建已入组那几局的完整向量（`vectors_for`），不再为几十组重建全量 396 局。
跨局页 `/api/cross/vectors` 同样落盘到 `data/.cache/cross-vectors.json`：服务重启后首次 5.5s → 0.18s，
热缓存 33–38ms；缓存键排除系列赛关系，确认编组不会让跨局向量失效。

挂载：`v3/serve.py` 同时把路由 include 进 `app`（独立运行）与模块级 `router`（生产 `server.py._mount_v3` 只挂后者）。

## 7. P0 系列赛分析（`series_engine.analyze_series` / `summarize_series`）

| 模块 | 内容 | 数据口径 |
|---|---|---|
| 局序表现 | G1..G7 逐局胜负、10 分钟 / 终局经济差；汇总页按 G1..G7 聚合胜率（n<2 的格给 None） | 向量（`at10` 需过程数据，缺失记 None 并写分母） |
| 连续局调整 | 逐局与上一局对照：新增 / 移出英雄数、调整幅度（0=未变、1–2=小调整、≥3=大调整）、体系标签变化 | 终局名单口径；有手序（人工 BP）才谈顺序 |
| 全局 BP 英雄账本 | 逐局累计「我方曾选 / 对方曾选」，按规则集计算「本局后不可再选」；检测跨局复用并告警（说明规则集与数据不符） | 有营地名单用名单，否则退化向量出场阵容（来源标记 `camp` / `manual` / `roster`） |
| 对手回应 | 对方逐局新增 / 移出英雄、体系切换、禁用重复 | 同上；无手序时不推断针对顺序 |
| 败局后恢复 | 输局后的下一局：胜负、10 分钟差变化；汇总页给胜率与中位差 | 向量；缺过程数据的对照标记「不比较经济差」 |
| 体系延续 vs 切换 | 连续两局体系标签相同 vs 不同时的下一局胜率 | `hero_capabilities.functional_tags`；全员无能力数据不生成标签、不判切换 |

「本轮需要关注」（`series_engine.build_attention`，宁缺勿滥，样本不足不报）：
- `late-drop`：G4 起后段胜率比前段低 ≥15pp（后段 n≥2）；
- `losing-streak`：以 ≥3 连败收尾；
- `after-loss-flat`：≥2 次输局后下一局全部仍输；
- `needs-review` / `interrupted`：编组待核实 / 教练标注中断。

**防两类错误**（V2.0 方案 §六）：
1. 营地终局名单 ≠ BP 手序。`orderKnown` 只在有手序数据（人工校对 `match.bp`）时为 True；
   无手序时所有「应对 / 针对」类结论降级为「终局阵容对照」，caveats 明确标注。
2. 左右位置 ≠ 真实阵营。阵营映射只用已校验的 `ownSide` / `ownCamp`（`blue→left` 镜像），不猜。

## 7.1 大场挖掘层（`series_insight.build_insight`，2026-11-15）

`GET /api/series/{id}/analysis` 在 P0 事实之外返回 `insight`。它不再只描述「哪局赢了」，
而是把一组 BO 的几局放在一起做统计与挖掘；所有模块都带分母、样本量与可点进的证据局。

| 模块 | 内容 | 方法 / 防泄漏 |
|---|---|---|
| `flow` 大场走势 | 逐局参考胜率曲线、10 分钟领先兑现/落后翻盘、最大波动与转折点 | L2 逻辑回归（1000 经济差 × 分钟交互）；按对局分组 5 折交叉验证；训练集排除本系列赛；经济持平/0 分钟锚定 50% |
| `phase` 阶段与资源 | 0–4 / 4–10 / 10 分钟后经济差、胜负手阶段、10 分钟龙/塔/团战 | 只统计有回放事件的局；缺过程数据不补 0；n<2 不给比例 |
| 局面形态 | 6 点相对时间经济曲线聚类：全程压制 / 逆风翻盘 / 优势被翻 / 后程发力 / 后程失守 / 拉锯 | k-means（固定种子）；语义与形状几乎相同的簇自动合并 |
| `draft` BP 价值 | 英雄价值、舒适区/生疏 pick、英雄池、对手局间回应、ban 价值 | 按「选到该英雄的一方」统计胜率，Beta-Binomial 向 50% 收缩（先验 8 局）+ Wilson 区间；排除本系列赛 |
| `players` 选手状态 | GPM / DPM / 参团 / KDA / 死亡相对个人（≥4 局）或同位置（≥8 局）基线的 z-score；对位经济、趋势、波动 | 小样本向 0 收缩；不含沟通/指挥/视野；只覆盖面板数据 |
| `fight` 团战与资源 | 团战胜率、优势/均势/劣势团、10 分钟资源、领先兑现率对照历史 | 团战胜率以「有击杀的团」为分母；资源事件缺失为 None |
| `similar` 历史对照 | 相似大场（余弦）+ 逐局 kNN（k=7）参考胜率与最近邻居 | z-score 特征；排除同系列赛对局；参考胜率用 Beta(2,2) 平滑，避免 7 个邻居全胜/全负给出 100%/0% |
| `insights` 挖掘结论 | 按严重度 × 置信度排序的 6 条以内结论；每条带证据与局链接 | 只报达到阈值的信号；质量信号（重复局/阵容异常）优先于战术结论 |
| `quality` 数据质量 | 过程指纹相同的重复局、双方阵容相同/缺失、语料去重统计 | 指纹＝10 分钟差 + 终局差 + 时长 + 双方阵容；重复局保留原始记录，不静默删 |

**语料与性能**：历史语料是全部合格对局的完整向量（经济曲线 / 团战 / 资源 / 十人面板）。
`v3/serve._series_corpus` 按对局包指纹缓存；首次下钻要把 396 局回放聚合一遍（冷启动含仓库快照约 4–7 秒），
之后按指纹命中；列表 / 汇总不取这份语料。历史语料先排除目标系列赛，再按过程指纹（+胜负）去重，
避免同一局既进训练集又被重复计算；内容相同但结果相反的局作为矛盾数据保留（当前数据 396 → 110 局唯一语料，98 组重复）。

**修复**：营地 `detail.ownSide` 可能是 `red/blue`，而 `campBp` 的键是 `left/right`；
`_bp_sides` 现在统一归一，red 方的 picks 不再全部落到对手侧（此前会污染调整/账本/BP 价值）。

## 8. 前端

| 文件 | 职责 |
|---|---|
| `v3/public/series-builder.js` | 编组中心（`#series-builder`，对局区次级导航末项）。自取数模式（同首页简报）：一次 `/api/series/bootstrap` 取轻量向量 + 系列赛 + 候选，`/api/metadata/icons` 并行补齐头像。未编组对局按日折叠、一行一局（局序 / 开赛 / 对手 / 结果 / 比分 / 时长 / 终局经济差 / 双方阵容 / 复盘入口，首屏前 6 行头像 eager）；日期栏定位、搜索与对手筛选、待核实筛选胶囊（`待核实 N`）、需补数据筛选（缺对手 / 开赛时间 / 阵容 / 结果 / 时长 / 比分）；展开日期、筛选条件、系列赛管理状态与每日显示条数写入 localStorage；整行可选（点选 / Shift 首尾 / 方向键移动 / Ctrl+A 选当前页 / Esc 取消 / Ctrl+Z 撤销 / 每日「全选当前页」）；候选可单组或「全部编组 N 组」批量确认（只处理无警告、无需核实、≤7 局，二次确认，组合撤销）；底部固定操作条推荐赛制、可切 BO 与「固定打满」；选中局数超过当前赛制时自动升到能装下的最小 BO，选满 3/5/7 局时自动勾选「打满」（置灰并标「自动」），低于局数的 BO 选项禁用。系列赛默认收成一行摘要胶囊，展开后为卡片：拖拽 / 箭头调序、移出、追加（按剩余局数限流）、改赛制、标记已核实 / 中断 / 缺采、两步确认删除；写操作直接用返回的 series 乐观更新，提供 toast 撤销 |
| `v3/public/series.css` | `.sb-*` / `.sa-*` 命名空间；`.sb-*` 本地令牌放在 `:root`（toast 也共享），明暗主题自适应 |
| `v3/public/cross-page.js` | **跨局分析**（`#cross`）：多场 BO 汇总，四段 `概述 / 赛中 / 赛后 / 英雄和 BP`；取 `/api/cross/series-summary` + `/api/cross/vectors`，分区写入 `view=`；不承载单场详情 |
| `v3/public/biggame-page.js` | **大场分析**（`#biggame`，独立模块）：大场列表卡片 + `#biggame/<id>` 单场分析（挖掘结论/走势/阶段/BP 价值/选手/历史对照/调整/账本/败局恢复/方法）；取 `/api/cross/series-summary` 与 `/api/series/{id}/analysis` |
| `v3/public/biggame-insight.js` | 单场挖掘卡片渲染：结论卡、逐局参考胜率曲线（SVG）、阶段/资源表、形态路径、BP 价值表、选手状态表与 sparkline、相似大场/相似局、方法与口径；只排版，不重算口径 |
| `app.js` / `features.js` / `index.html` | 次级导航注册、自取数旁路、mount/dispose、样式挂载；编组页走 `/api/metadata/icons` 轻量图标目录，其它页仍按 `iconsOnly` 标记补完整 metadata |

导航兼容：旧 `#cross/trend` / `#cross/bp` / `#cross/lanes` / `#cross/res` / `#cross/opponents` 统一落到多场汇总 `#cross`；
`#cross/series/<id>` 自动重定向到独立模块 `#biggame/<id>`。次级导航同时挂「跨局分析」「大场分析」。`series-analytics.js` 已退役。

## 9. 测试

- `tests/test_series_store.py`：CRUD、唯一归属（`SeriesConflict`）、关系列写回 / 置空、按原 ID 重建、
  过滤（时间窗按系列赛开赛日归档，一组 BO 不被切开）、重开库关系保持。
- `tests/test_series_api.py`：隔离 TestClient + 假 lookup。固定回归样本：三种 BO、不同比分（3:0 / 3:1 / 3:2）、
  固定打满、只采两局、跨午夜、缺开赛时间、对手冲突、重复归属 409、PATCH 调序换成员、DELETE。
- `tests/test_series_analysis.py`：完赛推导矩阵、三种规则集账本、复用检测、手序降级、缺数据 None 不补 0、
  汇总聚合与关注信号；新增 `ownSide=red/blue` → `left/right` 的 BP 侧别归一测试。
- `tests/test_series_insight.py`：24 局合成语料 + 3 局目标大场。覆盖结论契约、过程指纹重复局识别、
  目标系列赛从英雄价值中排除、经济差→胜率方向、kNN 平滑不出现 100%、空语料降级、单局不给比例。

## 10. 已知边界与后续

- 真实数据当前对手 / 训练组标注率低（营地面板对手字段为空）：建议层按「日期 + 时间连续性」降级分组并提示
  「对手未标注」；补齐对手后建议质量自动提升。
- 阶段 04（部分完成，2026-11-15）：跨局页已重组为总览 / BP 与阵容 / 对线与运营 / 对手 / 系列赛；
  `GET /api/cross/trends` 长期趋势（7 天~1 年、按系列赛开赛日归档、同条件分层）仍待下一轮。
- 阶段 05（后续）：教练训练决策闭环（跨局问题 → 训练课目标 → 下轮验证）。
- 存量修复：`_cross_vector` 团战分桶曾覆盖外层 `key`（330/386 个向量 key 被写成 adv/even/dis），
  2026-11-14 改名 `bucket` 修复；跨局分析按局链接与系列赛索引依赖此修复。
- 大场挖掘首次下钻需要把 396 局回放聚合成完整向量（冷启动约 4–7 秒），之后按对局包指纹命中；
  列表 / 汇总不取语料。语料按过程指纹去重（当前 396 → 110 局唯一），重复局会在结论最前提示。
- 挖掘层是描述性统计与历史对照：经济→胜率模型、BP 价值、选手状态、相似局都不构成因果；
  目标系列赛已从训练集/基线/邻居中排除。样本不足时对应模块降级为 None 或「参考」，不补 0。
- 既有失败（与本功能无关）：`v3/tests/test_service_boundaries.py::test_malformed_json_returns_400`
  的 `/api/v3/research/reports` 子例——HEAD 上同样失败（FastAPI 方法不匹配先于 JSON 校验返回 405）。
