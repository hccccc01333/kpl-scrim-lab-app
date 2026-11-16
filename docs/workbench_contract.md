# 赛训决策台 · 实现契约（v1.6.x）

> **2026-11-13 变更：独立的「决策台」已下线。**
> 本文件保留为分析口径与 `/api/decision/*` 接口的历史契约（第 1–3 节中未被删除的分析仍然有效），
> 但第 4 节描述的前端独立页面不再存在：
>
> - 网页工作台不再有 `#decision` 与顶部「决策」入口；保留的分析改挂到对象模块的分析入口
>   （选手：资源分配与四象限；BP：`#bp`（2026-11-15 起为九区 BP 概览）；选手该分析已于同日整页删除）。
> - **选手 / BP 十个分析已整页删除（2026-11-13）**：补刀与产出、经济投入与输出、同位置参照、
>   分路对位、蓝红阵营对照、资源分配与四象限、选手状态、选手搭档、经济与产出、禁选与资源，
>   连同 `/api/decision/resource`、五个 `/api/depth/analysis/*`、三个 `/api/v3/research/*`
>   接口与 `v3/public/analysis-pages.js` 页面文件一并移除；只保留 BP `#bp`。
> - 赛训台客户端不再有 `/decision` 页面与概览页「今天先看这几件事」问题卡；
>   保留的分析以块的形式落在战队 / 选手页面。
> - 首页不再自动生成问题清单。
> - **对局分析三页已整页删除（2026-11-13）**：网页对局分析 rail 的「失利关键链 / 团战执行与到位 /
>   优势保持与回撤」入口、客户端跨局分析三块与 `/api/decision/loss`、`/api/decision/advantage`、
>   `/api/decision/fights` 接口一并移除；`/api/decision/briefing`（问题清单）接口同样删除。
>   本文件第 2.2 / 2.3 / 2.6 节与 API 表相应行已删除，不再实现；其余涉及上述接口的 as-built
>   细节、测试与所有权清单仅作历史记录。
> - **「对手开局路线与热区」已整页删除（2026-11-13）**：网页 `#topic/opening_routes`、
>   客户端「开局与路线」块与 `/api/decision/opening` 接口一并移除；本文件第 2.4 节与
>   API 表中的该行仅作历史记录，不再实现。
> - 除上述删除项外，分析口径、字段与接口路径未改变，见 [workbench.md](workbench.md)。

本文件是「数据挖掘与教练端可视化扩展方案」的落地契约。所有模块、API、前端页面按本文件实现，
不另起口径。方案里的 P0 五项 + 赛训首页「今天先看这几个问题」是本轮交付范围
（其中对局三项与首页问题卡已于 2026-11-13 删除）；P1/P2 只保留入口或空态。

## 0. 目标与边界

> 2026-11-13 更新：本节第 1、2、4、5 项对应的分析（失利关键链 / 优势流失、团战执行、
> 对手开局路线、问题清单）已整页删除，此处仅保留当时的设计目标。

**目标**：把已有字段组合成教练真正要做的决策：

1. 为什么输（失利关键链 / 优势流失）
2. 团战为什么没打好（到位、人数差、交换）
3. 经济给对位置了吗（资源分配与发育效率）
4. 对手开局怎么打（开局路线与后续事件）
5. 今天先复盘什么（自动挑 3–5 个值得看的问题）

**边界**：
- 只读分析，不新增写接口；教练备注、训练任务关联仍走工作台（本轮不做写闭环）。
- 不引入新算法库：统计、分位、Wilson 区间、简单路线聚类（贪心/medoid）即可。
- 不宣称因果：所有「关键链」都是**候选事件**，页面必须写明。
- 小样本只展示事实与分布，不输出稳定预测/排名。
- 数据覆盖不足时**在图原位**显示原因，不画看似完整的图。

## 1. 已验证的数据资产（本机真实库）

| 层 | 位置 | 数量 | 用途 |
|---|---|---|---|
| 终局面板 | `data/camp_details/*.json` | 32 局 × 10 人 = 320 行 | 资源分配（A 级，不依赖回放） |
| 官方回放（规范化） | `data/official_replays/camp-*/normalized.json` | 24 局，其中 23 局能配到面板 | 经济/事件/团战/死亡（B 级） |
| 位置 | `data/official_replays/camp-*/positions.json` | 23 局 × 10 人 × 1 Hz | 开局路线热区（B 级） |
| 团战 | `normalized.battles.fights` | 518 场 | 单局复盘的团战（地图 / 贡献） |
| 死亡 | `normalized.battles.deaths` | 831 次 | 单局复盘的掉点与死亡 |
| 地图事件 | `normalized.events.key/extended` | 1407 条 | 资源/推塔/击杀链 |
| 地图定标 | `data/map_calibration.json` | calibrated，bounds ±53 | 位置→地图宽度比例 |
| 对战身份 | `team_clusters` / workspace | 32 个对手，每个 1 局 | 对手名（全部待命名） |
| 训练管理 | `training.sqlite3` / `/api/v3/effect` | 现有 | 训练验证（C 级，只复用） |

本机真实库的胜负分布：23 局可判胜负中 **20 胜 3 负**；日期 2026-11-02 至 2026-11-04。
因此「败局反复出现的问题」样本极少，页面必须用「全部对局 + 结果筛选」而不是只报败局；
所有结论按小样本规则降级。

**关键现实**：每个对手目前只有 1 局回放 → 不能输出「对手固定开局套路」，只能输出
「本批收录里这类路线的出现次数 + 单局路线」，并明确标注样本不足。

## 2. 后端模块

### 2.1 `decision_facts.py`（Lead 所有，先落地）

统一事实表 + 覆盖检查 + 共享工具。所有分析模块只读 facts，不自己扫目录。

```python
load_facts(replays_dir, camp_dir, data_dir=None, db_path=None, *, now=None) -> dict
```

返回结构（字段必须齐全，缺数据用 None/空列表，不用 0 假填）：

```jsonc
{
  "generatedAt": "2026-11-11T12:00:00",
  "coverage": {
    "panelGames": 32, "panelRows": 320,
    "replayGames": 24, "pairedGames": 23,
    "games": 23, "withResult": 23, "wins": 13, "losses": 10,
    "positionGames": 23, "fightGames": 23, "fights": 540, "deaths": 870, "events": 1472,
    "dateRange": ["2026-11-02", "2026-11-06"],
    "calibrated": true, "calibrationNote": "...",
    "identity": {"playersWithNickname": 320, "namedOpponents": 0},
    "errors": 1
  },
  "calibration": {"calibrated": true, "bounds": {...}, "width": 106.0} | null,
  "positionBounds": null,                   // 未定标时给相对坐标范围，供开局热区归一化
  "games": { "<seq>": Game },
  "order": ["1793595424", ...],            // 只含有回放且能判定我方阵营的对局，按时间升序
  "panels": { "<seq>": PanelMeta },        // 32 局都有
  "rows": [PanelRow, ...],                 // 320 行终局面板（own + enemy）
  "opponents": [{"id": "team-...", "name": "待命名战队 #1", "seqs": ["..."], "replayGames": 1}],
  "seqToOpponent": {"<seq>": "team-..."},
  "labels": {"<seq>": "11/02 · 对阵 待命名战队 #1"},
  "notes": ["..."]
}
```

`Game`：

```jsonc
{
  "id": "1793595424", "label": "11/02 · 对阵 待命名战队 #1",
  "date": "2026-11-02", "start": "11-02 12:59",
  "opponentId": "team-...", "opponentName": "待命名战队 #1",
  "ownCamp": "blue", "enemyCamp": "red",
  "winner": "blue", "result": "win",           // win / loss / null
  "duration": 660.0,
  "diff": [/* 原始经济差，蓝方视角，约 30 秒一点 */],
  "ownDiff": [/* 我方视角：ownCamp=red 时取反 */],
  "times": [0.0, 30.0, ...],                  // 与 diff 等长，approx
  "events": [norm.events.key...],
  "extended": [norm.events.extended...],
  "fights": [norm.battles.fights...],
  "deaths": [norm.battles.deaths...],
  "positions": {"<replayPlayerId>": [[u, v], ...]},   // 已按定标换算到 0–1；未定标用原始坐标
  "relative": false,                            // 未定标 true
  "players": [{"playerId","hero","camp","name","lane","objId"}],
  "objToPlayer": {"<objId>": "<replayPlayerId>"},
  "objToCamp": {"<objId>": "1|2"},
  "lanes": {"<replayPlayerId>": "对抗路|中路|发育路|打野|游走|"},
  "heroes": {"<replayPlayerId>": "英雄名"},
  "hasPositions": true, "hasFights": true, "hasEvents": true,
  "fightsNote": null
}
```

`PanelRow`（资源分配用，逐人逐局；own/enemy 都保留）：

```jsonc
{
  "seq": "1793595424", "date": "2026-11-02", "start": "11-02 12:59",
  "camp": "blue", "side": "own", "opponentId": "team-...", "opponentName": "...",
  "won": true, "minutes": 11.0,
  "playerId": "...", "name": "营地昵称", "lane": "对抗路", "hero": "项羽",
  "kills": 3, "deaths": 0, "assists": 6,
  "gold": 7892, "heroDamage": 29253, "damage": 153338, "taken": 52537,
  "participation": 32.1, "towerDamage": 3817, "control": 38, "heal": 30110,
  "cs": 38, "jungleGold": 270, "grade": 8.7
}
```

共享工具（其他模块与测试直接 import）：

```python
PHASES = ((0, 240, '对线期'), (240, 600, '发育期'), (600, None, '后期'))
def phase_of(seconds) -> str
def wilson(success, total) -> (low, high) | (None, None)   # 百分数 0–100
def percentile(values, q) -> float | None                  # q: 0–100
def median(values) -> float | None
def clock(seconds) -> "m:ss"
def time_at(index, count, duration) -> float
def value_at(seconds, series, duration) -> float | None     # 线性插值，端点夹住
def team_roster(panel) -> [...]                            # 营地阵容
def filter_games(facts, *, game=None, opponent=None, date_from=None, date_to=None, result=None) -> [Game]
def format_objective(event) -> {"name": ..., "kind": "resource|building|kill|fight|buff", "camp": "own|enemy|unknown"}
```

坐标口径：`positions` 在 `calibration.calibrated` 时已换算到 0–1（每单位 = 地图宽度），否则保持原值且 `Game.relative=True`。
经济时间：`times[i] = i * duration / max(1, n-1)`，页面一律显示「≈」并注明约 30 秒采样。

### 2.4 `decision_opening.py`（teammate: fight-analyst）

```python
opening_report(facts, *, opponent=None, lane=None, date_from=None, date_to=None, side='enemy') -> dict
```

1. 只取有位置的对局，0–240 秒，每 5 秒采样（positions 已 0–1 或相对单位）。
2. 按 `side`（默认 enemy）与分路分组的路线样本：每局每名该侧选手一条路线（t, x, y）。
3. 聚类：同一分路内贪心聚类，距离 = 对齐点平均欧氏距离；阈值 0.18（已定标）或 18（相对单位）。
   每条路线找 medoid（到同簇其他路线平均距离最小）；少于 3 条样本时不聚类，原样输出单局路线。
4. `zoneSequence`：把地图均分 3×3 九宫格（左上=蓝方野区、中上=上路河道…），取路线停留最久的 3 个格命名；
   命名固定表，不推断草丛/视野。
5. `nextObjective`：路线结束后 4–10 分钟内该侧获得的第一个资源/建筑事件（type/name/minutes），同簇频率。
6. `heat`：该侧 0–4 分钟位置点按 20×20 网格计数（已定标用 0–1；未定标用固定 bounds 归一化），
   返回 `cells[{x,y,n}]` 与 `max`。
7. 对手样本不足（<3 局回放）时：`selected.enough=false`，仍输出单局路线 + 热区，页面必须显示「样本不足，仅单局观察」。
8. 输出 `{"available","filters","opponents","selected","lanes","routes","heat","coverage","notes"}`。

### 2.5 `decision_resource.py`（teammate: resource-analyst）

```python
resource_report(facts, *, lane=None, player=None, opponent=None, date_from=None, date_to=None, result=None, side='own') -> dict
```

基于 320 行终局面板（默认只看 `side=own`）：
1. 每局按阵营求 5 人合计：gold/heroDamage/towerDamage/control/heal/jungleGold。
2. 逐人占比（0–100，1 位小数）：`goldShare/heroDamageShare/towerShare/controlShare/healShare/jungleShare`；
   `gpm=gold/minutes`、`participation` 保留原值、`deaths`、`quadrant`：
   x=goldShare，y=heroDamageShare；象限标签「高经济·高输出 / 高经济·低输出 / 低经济·高输出 / 低经济·低输出」
   （以各自样本中位数分界，n<10 时用 20/20 固定分界并标 `quadrantBasis="fixed"`）。
3. `quadrantFlag`：仅对 中单/发育路/对抗路/打野，且 goldShare − heroDamageShare ≥ 5pp 且 goldShare ≥ 20 时 true；
   辅助/游走不使用该规则（页面提示看控制/治疗）。
4. `byLane`：分路均值（n、goldShare、heroDamageShare、towerShare、controlShare、healShare、jungleShare、deaths、gpm）。
5. `anomalies`：只列 `quadrantFlag=true` 或「分路为发育路且死亡 ≥ 3」的条目，
   给 `text`（如「经济占比 27.1%，英雄伤害占比 19.4%（差 7.7pp）」），不排名、不评价选手。
6. `efficiency`：每分路一行「经济→输出」转化（heroDamageShare / goldShare，n），用于横向看职责差异。
7. 口径：`goldBasis=battleStats.money`、`damageBasis=battleStats.totalHeroHurtCnt`、
   `towerBasis=battleStats.buildingDamage`；`damage`/`totalHurtCnt` 与英雄伤害分开保留，不混用。
8. 无面板行/过滤后为 0：`available=false` + `reason`。

### 2.7 as-built 返回结构补充（实现后以本节为准）

> 2026-11-13 更新：以下 advantage / loss / fights / briefing 的 as-built 细节仅对应已删除接口，
> 保留作历史记录；resource / opening 相关仍然有效。

实现与前端联调后确认的细节，均不影响上面的字段语义：

- **advantage.bands** 是数组，不是按分钟分组的对象：
  `[{minute, seconds, win:{n,p25,p50,p75}, loss:{...}, all:{...}}, ...]`，n=0 时该组 p25/p50/p75 为 null。
- **loss.summary** 额外有 `byType/patterns/phases/thresholds/gamesWithWindows`；
  `patterns[]` 元素含 `{type,typeLabel,windows,games,avgCost,minCost,enough,reason,evidence[]}`；
  `rows[]` 额外有 `startClock/endClock/windowSec/opponentId`。
  `typeLabel` 最终取值：`wipe=4 人以上阵亡`、`multi_death=多人阵亡`、`teamfight_loss=团战失利`、
  `objective_lost=丢失资源/建筑`、`no_trade=未形成置换`、`unclassified=其他候选`。
- **fights** 真实回放里 `startSec` 就是最早参战时刻，故 `arrivalDiff` 恒 0、`firstSide` 恒 tie；
  先手改用：
  - 每行 `firstKillerSide: 'own'|'enemy'|null`（首个击杀方）
  - 每行 `beginnerSide: 'own'|'enemy'|'tie'|null`
  - `summary.firstKiller:{own,enemy,none}`、`summary.beginner:{own,enemy,tie,none}`、
    `summary.firstArrivalNote` 说明 tie 原因。
  - `selected.arrivalBars` 是**选中团战级别**的数组：
    `[{player,hero,lane,camp,from:0,to:arrivalLagSec}]`（成员对象本身不重复带该字段）。
- **opening.route.representative** 为 `{game,label,player,hero,name,lane,times:[...],points:[[x,y],...]}`；
  `heat.cells` 是整数网格坐标 `{x,y,n}`（x/y ∈ 0..grid-1），另有 `heat.grid/max/total/unit`；
  未指定对手时 `selected.id=null`、`selected.name="全部对手（本批）"`。
- **resource** 顶层实际键：`available/reason/filters/summary/quadrantBasis/quadrant/players/byLane/`
  `anomalies/efficiency/efficiencyNote/goldBasis/damageBasis/towerBasis/metrics/coverage/note`；
  `quadrant` 是单个对象 `{x:'goldShare',y:'heroDamageShare',xSplit,ySplit,basis,n,note}`；
  逐人行含 `goldShare/heroDamageShare/towerShare/controlShare/healShare/jungleShare/`
  `quadrant/quadrantFlag/goldDamageGap/gpm`。
- **briefing** 额外在 `skipped[]` 里放 `training_verification`（C 级：训练目标与复盘问题自动联动未打通）；
  证据按对局去重；同一波事件落在 30/60/120 秒多个窗口时会重复计数，已在 caveat 写明。

## 3. API 契约（`decision_api.py`，Lead 所有）`create_decision_router(replays_dir, camp_dir, data_dir=None, db_path=None)` → `APIRouter(prefix='/api/decision')`，
结果按数据签名缓存（camp/official 目录 mtime + db mtime），命中缓存不重复扫盘。

| 方法 | 路径 | 参数 | 返回 |
|---|---|---|---|
| GET | `/api/decision/catalog` | — | 覆盖、层、分析清单、对局列表、对手列表 |
| GET | `/api/decision/opening` | opponent,lane,from,to,side | opening_report |
| GET | `/api/decision/resource` | lane,player,opponent,from,to,result,side | resource_report |

> 2026-11-13 起 `/api/decision/briefing`、`/api/decision/loss`、`/api/decision/advantage`、
> `/api/decision/fights` 四行已删除（见顶部变更说明）；`opening` 行仅作历史记录。

- 参数非法 → 400（日期格式 `YYYY-MM-DD`，from > to）。
- 无数据 → 200 + `available=false` + `reason`，不 500。
- `server.py` 里 `app.include_router(create_decision_router(OFFICIAL_DIR, DATA_DIR / 'camp_details', DATA_DIR, DB_PATH))`
  （放在 V3 挂载之前；与现有路由不冲突）。

## 4. 前端（client 赛训台，teammate: client-ux）

> **已作废（2026-11-13）**：本节描述的 `/decision` 一级导航、概览页问题卡与四工作区页面均已下线，
> 实际落位见 [workbench.md](workbench.md) 的「分析落位」一节。保留本节只为追溯当时的实现约定。

### 4.1 路由与导航
- `AppShell.tsx`：左侧一级导航新增 `{ to: '/decision', label: '决策台', icon: 'decision' }`，放在「概览」之后；
  `pageTitles['/decision'] = '决策台'`；`Routes` 增加 `/decision`。
- 概览页 `OverviewPage.tsx` 顶部新增「今天先看这几件事」：`/api/decision/briefing` 的 3–5 张问题卡；
  失败/空态显示「暂时没有足够证据的问题」+ 入口按钮，不阻塞概览其余内容。

### 4.2 页面结构 `/decision`
- `PageHeader`：eyebrow `DECISION DESK`，标题「赛训决策台」，
  副标题「先把值得复盘的问题挑出来，再回到对局证据。」；
  右侧按钮：刷新、打开工作台（沿用现有 page actions 模式）。
- 顶部覆盖条：完整回放 23 局 · 终局面板 32 局 · 坐标已定标/未定标 · 数据范围（对手/结果/日期，来自 catalog）；
  所有数字来自 API，不硬编码。
- `Briefing` 区块：问题卡（severity 颜色、n、caveat、证据 chips→`/matches/<id>`；「查看分析」切 tab）。
- 四个 Tab（URL `?tab=review|prep|player|training`，默认 review）：
  1. **赛后复盘**：局选择器（有回放的对局）→ 经济差时间轴 + 关键链卡（候选事件、证据、类别标签）+
     优势保持 KPI（最大回撤/领先时长/兑现时间/翻盘率）+ 分位带图 + 分桶表 + 回撤排行（点进局）。
     时间轴与链卡联动：点事件标记滚动到对应链卡。
  2. **赛前备战**：对手选择器（显示回放局数；<3 局显著提示）+ 分路筛选 → 开局热区网格 + 路线卡
     （簇样本数、zone 序列、后续第一个资源/建筑、频率）+ 单局路线播放（简化为选中路线在地图网格上高亮）。
     标注「仅收录 23 局回放，不能推断对手全部习惯」。
  3. **选手研究**：分路筛选 → 经济占比 × 伤害占比四象限散点（颜色=分路，大小=推塔伤害，悬浮卡给英雄/补刀/控制/治疗/GPM/来源）+
     异常清单（可点进对局）+ 分路均值表 + 口径说明（经济=营地 money，伤害=totalHeroHurtCnt，未混用）。
  4. **训练验证**：复用 `useTrainingEffect`（`/api/v3/effect`）：干预前后对比卡 + 目标达成 + 样本量；
     显示 C 级提示「训练目标绑定与复盘问题联动尚未打通；这里只做前后描述，不宣称因果」；
     链接到 `/training/effect`。
- 空态：`BoardEmpty` 显示 API 给的 `reason`；小样本显示「样本不足，仅供观察」badge；`n` 永远可见。
- 每张图/表底部显示 `note`（来自 API）；颜色只用 `tokens.css` 变量；亮/暗主题都要可读。
- 图表组件放 `components/charts/DecisionCharts.tsx`（纯 SVG，无新依赖）：
  `EconomyTimeline`（经济差面积+事件标记）、`BandChart`（P25–P75 带+P50 线）、
  `QuadrantChart`（散点）、`OpeningHeat`（网格热区+路线折线）、`ArrivalBars`（团战到位条）。
- 数据 hook 放 `lib/decision.ts`（`useDecisionCatalog/useBriefing/useLoss/useAdvantage/useFights/useOpening/useResource`），
  用 `api<T>(baseUrl, path, { timeout })`；类型集中在同文件，不改 `types.ts` 以外必要处。
- CSS 放 `styles/decision.css` 并在 `styles/index.css` 引入；沿用 `board-page` 等现成版式。
- 概览页改动只加一块，不改原有结构；所有新增文案中文、教练话术、不用「金差」。

### 4.3 交互与口径（硬要求）
- 时间显示 `m:ss`，近似经济点标「≈」；不把 API 的 approx 数据说成精确时间。
- 点击证据 → `/matches/<key>`（单局深度页），时间点用页面内已有锚点/查询参数即可，不新增后端。
- 任何「为什么输」结论必须写「候选事件/待复核」，不写「因为」。
- 小样本（n<10）数字旁显示 `样本不足` 标签；无数据不给 0 或空图，显示原因。

## 5. 测试与验收

> 2026-11-13 更新：`test_decision_loss.py` / `test_decision_fights.py` 及 briefing 相关测试
> 已随对应接口删除，以下清单仅作历史记录。

- 后端每个模块一个 pytest 文件，使用 `tests/decision_fixtures.py` 合成数据（Lead 提供）：
  - `test_decision_loss.py`：窗口/分类/损失排序/优势回撤/翻盘率/样本不足。
  - `test_decision_fights.py`：我方视角、到位差、人数差、热力格、团灭、缺失参与者。
  - `test_decision_opening.py`：单局路线、热区计数、样本不足标记、未定标单位。
  - `test_decision_resource.py`：占比、象限、异常、辅助不套输出规则。
- `tests/test_decision_api.py`（Lead）：`TestClient` 冒烟，7 个端点 200、关键字段存在、
  非法日期 400、空目录返回 `available=false`。
- 前端：`cd client && npm run typecheck && npm run build` 通过。
- 运行时：启动 `python server.py`（真实数据），curl 7 个端点确认 200 且数据非空；
  Playwright Electron 截图 `/decision` 四个 tab + 概览页问题卡，检查无横向溢出、无控制台报错。
- 现有测试回归：`pytest tests/`（至少新模块相关 + test_app / test_analysis_* / test_studio）。

## 6. 文件所有权（避免并行冲突）

| 所有者 | 文件 |
|---|---|
| Lead | `docs/workbench_contract.md`, `decision_facts.py`, `decision_briefing.py`, `decision_api.py`, `tests/decision_fixtures.py`, `tests/test_decision_api.py`, `docs/workbench.md`, `CHANGELOG.md`, `server.py`（仅 mount 一处） |
| loss-analyst | `decision_loss.py`, `tests/test_decision_loss.py` |
| fight-analyst | `decision_fights.py`, `decision_opening.py`, `tests/test_decision_fights.py`, `tests/test_decision_opening.py` |
| resource-analyst | `decision_resource.py`, `tests/test_decision_resource.py` |
| client-ux | `client/src/renderer/src/lib/decision.ts`, `client/src/renderer/src/pages/DecisionPage.tsx`, `client/src/renderer/src/components/charts/DecisionCharts.tsx`, `client/src/renderer/src/styles/decision.css`, `client/src/renderer/src/styles/index.css`, `client/src/renderer/src/components/AppShell.tsx`, `client/src/renderer/src/components/Icon.tsx`, `client/src/renderer/src/pages/OverviewPage.tsx`, `client/src/renderer/src/lib/routes.ts`（如需） |

禁止跨所有权改文件；需要共享工具时在 `decision_facts.py` 提出，由 Lead 补。
