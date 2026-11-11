# 赛训决策台：数据挖掘与教练端可视化（v1.6.x）

本文记录「从教练可以查看哪些数据，升级为教练今天该研究哪些问题」这一轮的落地内容。
设计契约见 [decision_workbench_contract.md](decision_workbench_contract.md)。

## 一句话

新增 `/api/decision/*` 分析层、赛训台客户端「决策台」与工作台网页端 `#decision` 四工作区：
先给教练 3–5 个有证据的问题，再按「赛后复盘 / 赛前备战 / 选手研究 / 训练验证」下钻到对局、
时间点和原始字段。

## 交付范围（12 项分析的进度）

| 优先级 | 分析 | 状态 |
|---|---|---|
| P0 | 1 失利关键链（Loss Breakdown） | ✅ `/api/decision/loss` |
| P0 | 2 经济优势保持与回撤 | ✅ `/api/decision/advantage` |
| P0 | 3 团战执行与人员协同 | ✅ `/api/decision/fights` |
| P0 | 4 资源分配与发育效率 | ✅ `/api/decision/resource` |
| P0 | 5 对手开局路线与热区 | ✅ `/api/decision/opening`（对手样本多为 1 局，只做单局观察） |
| P1 | 6 BP 阵容抗针对 | ✅ `/api/decision/bp` + 工作台 `#bpcounter` |
| P1 | 7 死亡代价与连锁失误 | 📋 复用 A4/掉点数据，待整合成连锁损失面板 |
| P1 | 8 资源置换与决策收益 | 📋 待做 |
| P1 | 9 选手状态与稳定性 | 🚧 已有选手状态/波动页，待加同英雄同位置条件比较与异常预警 |
| P1 | 10 阵容协同与换人影响 | 🚧 已有阵容/搭档 Lift，待加团战共同参与与换人前后对比 |
| P1 | 11 训练措施有效性 | 🚧 已有训练前后对比，待打通「复盘问题→训练目标→复测」闭环 |
| P2 | 12 出装节奏与团战表现 | ⏸ 仓库仍标未完成；先验证购买事件覆盖 |

「赛训首页问题卡」已做：`/api/decision/briefing`，顶栏/首页显示证据最强的 3 条。

## 分析归属：模块优先（2026-11-11 调整）

决策台**不是所有分析的唯一落点**。对象模块是主分析所在地，决策台只做跨对局的任务汇总与入口：

| # | 分析 | 第一落点 | 决策台角色 |
|---|---|---|---|
| 1 | 失利关键链 | 单局复盘（经济/事件时间轴） | 反复出现的失利模式汇总 + 回单局 |
| 2 | 优势流失/滚雪球 | 跨局分析（节奏/经济）+ 单局 | 回撤排行/翻盘率摘要 |
| 3 | 团战执行与协同 | 单局复盘（事件/地图）+ 跨局团战聚合 | 重复出现的团战问题 |
| 4 | 资源分配与发育效率 | 选手模块（选手档案/资源效率） | 需复核异常清单入口 |
| 5 | 对手开局战术画像 | 战队/对手模块 | 赛前备战当前对手的单局观察 |
| 6 | BP 阵容抗针对 | **BP 模块（`#bpcounter`）** | 赛前备战只放补练建议摘要 |
| 7 | 死亡连锁代价 | 单局复盘（掉点账本/地图） | 高频掉点区域/时段模式 |
| 8 | 资源置换与收益 | 单局复盘事件泳道 + 跨局聚合 | 重复让渡/交换模式 |
| 9 | 选手状态与稳定性 | 选手模块 | 优先复核名单 |
| 10 | 阵容协同与换人影响 | 战队模块（阵容/训练） | 轮换观察摘要 |
| 11 | 训练措施有效性 | 赛训模块（训练效果/训练课） | 只读摘要 + 入口 |
| 12 | 出装节奏与团战表现 | 英雄模块 / 单局复盘 | 数据稳定前不出现 |

落位原则：

- **对象是谁就放对象模块**（选手/战队/英雄/BP/单局/跨局）；
- 只有需要「跨对局找模式、排优先级、串联训练」的结论才进决策台；
- 决策台不复制完整图表，最多保留一个摘要 +「查看完整分析 →」；
- 同一个分析只维护一个主页面，客户端/网页端共享同一批后端接口。

## 数据资产与边界（本机真实库）

| 层 | 位置 | 数量 | 能支持 | 不能支持 |
|---|---|---|---|---|
| 终局面板 | `data/camp_details/*.json` | 32 局 × 10 人 = 320 行 | 资源分配、BP 禁选、发育效率 | 过程、时间点 |
| 官方回放 | `data/official_replays/camp-*/normalized.json` | 24 局，23 局配到面板 | 经济、事件、团战、死亡 | 逐秒精确经济 |
| 位置 | `.../positions.json` | 23 局 × 10 人 × 1 Hz | 开局路线、热区 | 视野、草丛、兵线控制权 |
| 团战 | `normalized.battles.fights` | 518 场 | 到位、人数差、交换 | 技能级细节 |
| 死亡 | `normalized.battles.deaths` | 831 次 | 落点、孤立度 | 归因 |
| 地图事件 | `normalized.events.key` | 1407 条 | 资源、推塔、击杀链 | 资源归属的精确经济 |
| 地图定标 | `data/map_calibration.json` | bounds ±53，23 局位置 | 相对位置比较 | 官方地图尺寸 |
| 对手身份 | `team_clusters` / workspace | 32 个对手，每个 1 局 | 单局对手观察 | 对手固定套路 |
| 训练管理 | `training.sqlite3` / `/api/v3/effect` | 现有（本机暂无干预记录） | 训练前后描述 | 因果结论 |

本机胜负分布：23 局可判胜负里 **20 胜 3 负**。所以：

- 「败局反复出现的问题」样本只有 3 局 → briefing 优先用「曾领先但被翻盘」「团战人数差」这类
  跨胜败都可观察的模式，并把 `losses=3` 写进页面；
- 每名对手目前 1 局回放 → 对手开局只做「本批单局观察」，不输出固定套路。

## P0 五项分析口径

### 1. 失利关键链（`/api/decision/loss`）

- 30/60/120 秒窗口里找 `ownDiff` 显著变化，阈值 `max(1000, P90)`，只取我方视角负向窗口。
- 关联窗口内/±60 秒：死亡（含最近队友距离、孤立标记）、团战（击杀差、开局人数差）、
  资源/建筑（`dtType=1` 资源、`dtType=2` 建筑）。
- 主类优先级：`wipe`（我方 ≥4 人阵亡，页面标「4 人以上阵亡」）→ `multi_death`（≥2 人阵亡）→
  `teamfight_loss`（团战击杀差 ≤ −2）→ `objective_lost`（敌方拿资源/建筑且我方 0）→
  `no_trade`（未形成置换）→ `unclassified`（其他候选）。
- 输出单局经济序列 + 按损失排序的关键链卡；跨局按类别、阶段汇总。
- 页面措辞：**候选事件，不证明因果**；`confidence` 一律 `candidate`。

### 2. 优势保持与回撤（`/api/decision/advantage`）

| 指标 | 定义 |
|---|---|
| 最大优势 `maxLead` | 我方视角经济差的历史峰值 |
| 最大回撤 `drawdown` | 峰值之后到终局的最低点与峰值之差（幅度，不带正负） |
| 领先时长 `leadDurationSec` | `ownDiff ≥ +500` 的累计采样时长 |
| 兑现时间 `conversionSec` | 首次 `≥ +1000` 后，到下一次我方资源/建筑事件的时间 |
| 后续增量 `postLead2mDelta` | 首次 `≥ +1000` 后 120 秒的经济差变化 |
| 被翻盘 `comeback` | `maxLead ≥ +1000` 且最终告负 |

- 10 分钟分桶：落后 <−500 / 持平 −500~500 / 小优 500~1500 / 大优 ≥1500。
- 分位带按游戏分钟给胜局/败局/全体的 P25/P50/P75；n=0 的档不画线。
- 经济点约 30 秒一个，所有时间标「≈」；样本 <10 局时 `enough=false`。

### 3. 团战执行与人员协同（`/api/decision/fights`）

- 我方视角：参战人数、每人到位延迟、先到方、`advStart`（开局 3 秒内人数差）、击杀差、
  迟到人数、先手方、成员伤害/承伤/治疗/控制/血量。
- 汇总：平均到位延迟、迟到率、`advStart` 分桶胜率、`advStart × killDiff` 热力格、团灭。
- 人数差是**团战开始 3 秒内到达**的人数差，不把随后进场算进去；0 击杀团战只看到位。

### 4. 资源分配与发育效率（`/api/decision/resource`）

- 只依赖终局面板，32 局 × 10 人（默认只看我方 5 人）。
- 逐局算五人合计与逐人占比：经济、英雄伤害、推塔伤害、控制、治疗、野怪经济。
- 四象限：X=经济占比，Y=英雄伤害占比；以样本中位分界（n<10 用 20/20 固定线）。
- 复核标记 `quadrantFlag`：仅中单/发育路/对抗路/打野，且经济占比 − 英雄伤害占比 ≥5pp 且经济占比 ≥20。
  游走/辅助不套这个规则（页面提示改看控制/治疗）。
- 口径：经济=`battleStats.money`，英雄伤害=`totalHeroHurtCnt`，推塔=`buildingDamage`；
  `damage`（总伤害）与英雄伤害分开保留，不混用、不换算。
- 象限只用于发现值得复核的资源配置，不做选手排名或能力评价。

### 5. 对手开局路线与热区（`/api/decision/opening`）

- 0–240 秒、每 5 秒采样；按分路把该侧选手轨迹做贪心聚类（medoid 代表路线）。
- 输出路线代表点、九宫格 zone 序列、路线结束后第一个资源/建筑及频率、20×20 热区。
- 每名对手 1 局时 `selected.enough=false`，只显示单局路线。

### 6. BP 阵容抗针对（`/api/decision/bp`，BP 模块 `#bpcounter`）

- 对手禁选排行（总体/指定对手）、我方分路英雄池、被对手常禁命中后的可用池深度。
- 稳定选手只保留 ≥3 局样本；本批轮换多（117 个只打 <3 局的昵称）单独计数，不混成主力。
- 输出补练建议：分路可用池偏薄、稳定选手可 Ban 英雄集中、我方常用与对手 ban 位重合。
- **不把少量比赛的胜率当英雄强度**；对手目前 1 局时只做单场观察；不推断 BP 手序。

## 赛训首页问题卡（`/api/decision/briefing`）

每次按当前数据范围重新计算 9 类候选，按严重度 × 样本量取前 3–5 条：

| kind | 触发 | 说明 |
|---|---|---|
| `comeback_leak` | 曾领先 ≥1000 的局 ≥3 且被翻盘 ≥2 | 翻盘率、平均回撤 |
| `loss_pattern` | 某类损失窗口 ≥3 且涉及 ≥2 局 | 类别、阶段、平均损失 |
| `slow_conversion` | 有兑现时间的局 ≥5 且 >120 秒占一半 | 领先后推进/控龙节奏 |
| `fight_arrival` | 人数落后/不落后各 ≥8 场且胜率差 ≥20pp | 等人再打/开团沟通 |
| `late_join` | 迟到率 ≥10% 且 ≥10 人次 | 团战迟到 |
| `resource_mismatch` | 复核标记 ≥2 条 | 资源分配待复核 |
| `lane_concentration` | 复核条目 ≥3 且 ≥40% 集中在同一分路 | 集中分路优先看 |
| `opening_habit` | 同一对手路线簇 ≥3 次 | 本机通常不产生，写入 skipped |
| `coverage_gap` | 有面板无回放的局 >0 | 采集覆盖提醒 |

每条带 severity、n、confidence、caveat、证据和链接；小样本自动降级并写入 `skipped`。

## 工作台网页端首页入口

- `#overview` 在 `pageIntro` 后新增「今天先看这几件事」，**紧凑 3 行**（不是 5 张大卡）：
  标题 + 优先级/类别/n/可信度/样本不足 +「证据 ×N」+ 决策台入口；证据行内展开，默认不撑高首页。
- **随数据变化**：按工作台当前日期筛选请求 `/api/decision/briefing`，显示当前范围、
  「共评估 9 类信号，命中 K 条，显示前 3 条」和数据版本指纹；换筛选/补对局后重算。
- 行主入口走 `#decision/<tab>?game=…`；保留「在赛训台看」深链。

## 工作台网页端决策台 `#decision`（四工作区）

顶部导航「决策」或首页入口进入；数据范围（日期/对手/结果）与覆盖条统一。

| 工作区 | 内容 |
|---|---|
| 赛后复盘 | 局选择 → 经济差时间轴（损失窗口 + 死亡/团战/资源标记）、关键链、优势指标、分桶、回撤排行、分位带 |
| 赛前备战 | 对手选择 → 开局热区/路线 + **BP 抗针对摘要**（链接 `#bpcounter`）+ 样本不足提示 |
| 选手研究 | 分路筛选 → 四象限（点可点选）+ 人次证据卡 + 经济→输出差距排行 + 复核清单 + 分路均值 + 口径说明 |
| 训练验证 | 干预前后对照；空态 + `#effect` 入口；固定显示 C 级提示 |

- URL：`#decision/review|prep|player|training`，刷新保持当前工作区，切工作区不整页刷新。
- 图表纯 SVG，无新依赖；无数据/失败只影响当前区并给重试。

## 教练端（赛训台 client）

- 左侧一级入口「决策台」`/decision`，与网页端同四工作区；概览页顶部「今天先看这几件事」。
- 深链：`kpl-client://open?tab=review|prep|player|training&game=<seq>`（主进程白名单解析）。
- 团战/表格排版：6 列压到 4 列、默认 6 场、单列布局、到位图标签「英雄 · 分路」、
  开局人数差 3 组汇总；数据表行高/字号按可读性调整。
- 字体：400/700 两个真实字重（GB2312 一级全覆盖）；默认界面缩放 115%，
  设置页可选 100–140%，`Ctrl +/-/0` 调整。

## API

| 方法 | 路径 | 参数 |
|---|---|---|
| GET | `/api/decision/catalog` | — |
| GET | `/api/decision/briefing` | from, to, opponent, result, limit |
| GET | `/api/decision/loss` | game, opponent, from, to, result, limit |
| GET | `/api/decision/advantage` | opponent, from, to, result |
| GET | `/api/decision/fights` | game, opponent, from, to, result, side, limit |
| GET | `/api/decision/opening` | opponent, lane, from, to, side |
| GET | `/api/decision/resource` | lane, player, opponent, from, to, result, side |
| GET | `/api/decision/bp` | opponent, from, to |

`server.py` 挂载；事实表按数据签名缓存；无数据 200 + `available=false + reason`；参数非法 400。

## 怎么验证

```powershell
$env:PYTHONIOENCODING='utf-8'
python -m pytest tests/test_decision_api.py tests/test_decision_loss.py `
  tests/test_decision_fights.py tests/test_decision_opening.py `
  tests/test_decision_resource.py tests/test_decision_bp.py -q
python -m pytest tests/test_app.py tests/test_release_manifest.py -q
cd client; npm run typecheck; npm run build
```

工作台：启动 `python server.py`，访问 `http://127.0.0.1:8766/#decision/review` 等；
客户端：见 `scripts/shot_client_decision.mjs`（可测深链）。

## 文件地图

| 文件 | 作用 |
|---|---|
| `decision_facts.py` | 统一事实表、覆盖检查、共享工具 |
| `decision_loss.py` | 失利关键链 + 优势保持/回撤 |
| `decision_fights.py` | 团战执行与人员协同 |
| `decision_opening.py` | 对手开局路线与热区 |
| `decision_resource.py` | 资源分配与发育效率 |
| `decision_bp.py` | BP 阵容抗针对 |
| `decision_briefing.py` | 赛训首页 3–5 个问题 |
| `decision_api.py` | `/api/decision/*` 只读路由 |
| `tests/decision_fixtures.py` | 合成数据夹具 |
| `client/src/renderer/src/pages/DecisionPage.tsx` | 客户端四工作区 |
| `client/src/renderer/src/components/charts/DecisionCharts.tsx` | 客户端图表 |
| `client/src/main/index.ts` | 深链解析 |
| `client/src/renderer/src/styles/fonts.css` + `assets/fonts/` | 中文衬线 400/700 子集 |
| `scripts/build_client_fonts.py` | 生成字体子集 |
| `v3/public/home-decision.js` | 工作台首页紧凑入口 |
| `v3/public/decision-page.js` | 工作台 `#decision` 四工作区 |
| `v3/public/bp-counter.js` | 工作台 BP 模块 `#bpcounter` |
| `scripts/shot_client_decision.mjs` | 客户端冒烟/截图 |
| `docs/decision_workbench_contract.md` | 实现契约 |

## 已知限制与下一步

1. **对手样本**：每名对手 1 局回放，无法做对手习惯画像；补齐多局后 `opening`/`bp` 的对手维度才有意义。
2. **时间精度**：经济点约 30 秒、位置 1 Hz；页面统一标近似。
3. **坐标**：定标来自本批位置分位，不是官方地图尺寸；换版本/地图需重新定标。
4. **训练闭环**：复盘问题 → 训练目标 → 复测仍属下一阶段；当前训练验证只读。
5. **P1 剩余**：死亡连锁、资源置换、状态稳定性、阵容轮换需按「模块优先」继续落到对象页；
   P2 出装节奏需先验证购买事件覆盖。
6. **写操作**：决策台只读；教练备注与训练任务回工作台完成。
