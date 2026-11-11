# 数据分析平台（实验）

本地只读分析服务：读取工作台比赛记录、单局数据包和表格导入结果，提供总览、队员、英雄、团队、比赛详情和数据源视图。不写数据库、不调用云端、只监听本机。

## 启动

```powershell
python server.py
# V3 入口：http://127.0.0.1:8766/
# 旧分析别名 /analysis 会 302 到根路径
```

分析页与录入工作台是同一个 FastAPI 服务，侧栏“数据分析平台”直接进入；录入工作台仍是 `server.py` / `启动工作台.bat`。`analysis_server.py` 只保留为独立调试入口（8767），正式使用不需要另开服务。可选环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `TRAINING_DB` | `data/training.sqlite3` | 工作台数据库（分析只读） |
| `ANALYSIS_MATCHES` | `data/matches` | 单局数据包目录 |
| `ANALYSIS_IMPORTS` | `data/imports` | 表格导入 staging 目录 |
| `ANALYSIS_PORT` | `8767` | 仅独立调试用 `analysis_server.py` 时生效 |

页面顶部“刷新数据”会清空进程缓存并重新读取；不修改任何文件。

## 数据源与同一局关联

| 来源 | 读取内容 | 默认是否计入 |
| --- | --- | --- |
| 本机比赛记录 | `matches` 表中 `status=confirmed` 的比赛；草稿只计数 | 是 |
| 单局数据包 | `kpl-match-data-v1`：终局、团队时间轴、记分板快照、POV 段 | 是 |
| 表格导入 | `kpl-sheet-import-v1` 的 `match_player` 行 | 否，需勾选“表格导入” |
| 聚合表 | 表格导入中的 `aggregate_*` 表 | 否，单独展示，禁止与单局混算 |

**数据包 ↔ 本机记录关联**：日期（月/日）一致、总时长差 ≤3 秒、十人英雄重合 ≥8/10，且只匹配到一条本机记录时自动关联。关联后：

- 终局字段优先用本机已确认记录；缺失字段才用数据包终局补，标 `mixed`。
- 团队时间轴、记分板快照、POV 段来自数据包。
- 本队阵营用双方英雄集合把左/右映射到蓝/红；结果按本机胜方计算。
- 多条候选时不做自动关联，保留为两条来源，避免静默混合。

**表格来源**默认不计入单局统计，勾选后才加入；表格可能与本机记录重复，平台不去重，只在提示里说明。聚合表始终不进入队员/英雄/团队计算。

## 指标口径

| 指标 | 口径 |
| --- | --- |
| 胜率 | 胜场 / 有胜负的场数；未知结果不计入分母 |
| KDA | `(击杀 + 助攻) / max(1, 死亡)` |
| GPM / DPM / TPM | `sum(经济/输出/承伤) / sum(有效分钟)`，不是各场比率的平均 |
| 经济/输出/承伤占比 | 仅当同队 5 人对应字段齐全时计算，再对有值场次求平均 |
| 参团率 | 优先用来源字段；缺失时用 `(击杀+助攻)/团队击杀`，团队击杀未知或为 0 不计算 |
| 团队场均 | 只统计本队五人终局字段齐全的场次；经济差要求双方团队经济都齐全 |
| 每分钟指标 | 只对完整终局计算；部分快照不按全场时长折算 |

### 部分数据

- 只有录屏、没有赛后截图时，数据包终局是最后一张记分板快照，标 `partial`。
- 默认**不把部分行计入队员/英雄/团队统计**；页面会提示“可勾选包含部分数据”。
- 勾选后可以查看过程快照，但 GPM/DPM/TPM 仍为空，行上标“部分”；不要把它当成全场终局。
- 数据包只有 01:46/02:57 时，团队曲线也标“不是全场”。

## 页面

- **总览**：比赛数、胜率、队员/英雄数、完整终局数、部分行、时间轴/记分板/POV 覆盖、Top 队员/英雄、提示。
- **队员**：场次、胜负、胜率、KDA、GPM、DPM、参团、英雄池；点击查看逐场趋势和明细。
- **英雄**：出场、胜率、KDA、GPM、DPM、使用队员；点击按该英雄过滤比赛。
- **团队**：本队胜率、场均经济、经济差、场均击杀、对手胜率条、阵营分布。
- **比赛**：比赛列表；详情含十人终局、团队经济曲线、记分板快照（折叠）、POV 段（折叠）、提示。
- **数据源**：本机/录像/表格/聚合表库存；表格行和聚合表可查看前 100 行。

## API

所有接口只读；默认来源 `db,bundle`，`includePartial=1` 才纳入部分行。

```text
GET /api/analysis/overview
GET /api/analysis/filters
GET /api/analysis/players
GET /api/analysis/players/{key}/trend
GET /api/analysis/heroes
GET /api/analysis/teams
GET /api/analysis/matches
GET /api/analysis/matches/{key}
GET /api/analysis/sources
GET /api/analysis/imports
GET /api/analysis/imports/{id}/rows?sheet=&limit=&offset=
POST /api/analysis/reload
```

过滤参数：`from`、`to`、`source=db,bundle,sheet`、`player`、`hero`、`opponent`、`session`、`version`、`result`、`camp`、`includePartial=1`。

单局全景单独走 `GET /api/review/{key}`，输入为 `data/matches/{key}.json` 数据包，可选关联 `data/official_replays/<camp-id>/` 的逐秒坐标与事件、`data/builds/<abc-sha>/builds.json` 的出装时间线。缺少官方回放或出装时仍返回终局数据，相关区块为空态。官方事件只覆盖资源/目标与建筑摧毁，不含英雄击杀，接口以 `coverage.heroKills=false` 标明，不会用资源事件补造击杀时间轴。

## 身份

- 本机记录有队员 ID，按名单关联。
- 数据包只有昵称/英雄；只在关联到本机记录时通过英雄匹配到队员 ID，否则显示“未绑定”，按昵称/阵营分组。
- 表格行同样不自动绑定队员 ID，不判断真实分路。
- 平台不把昵称当稳定 ID；后续接战队名单时可加人工映射。

## 本样本现状

工作台数据库当前 0 场确认比赛；`data/matches/1028-177-71b998.json` 只有一段 141 秒录屏、无同一局赛后截图。因此：

- 总览显示 1 场、10 人、时间轴/记分板/POV 覆盖 1；
- 完整终局 0，部分行 10；默认队员/英雄统计为空并给出提示；
- 勾选“包含部分数据”后可查看名单快照，但 GPM/DPM/TPM 为空；
- 比赛详情有十人终局快照、团队经济曲线、4 个记分板快照、5 段 POV。

这不是平台准确率或训练价值的评估，只是当前本机数据的真实覆盖。

## 验证

```powershell
python -m unittest tests.test_analysis_data -v
python scripts/verify_analysis_page.py
python -m unittest discover -s tests -v
```

`tests/test_analysis_data.py` 使用临时数据库、数据包和表格导入，覆盖：本机记录、数据包关联、左右阵营映射、终局优先/补缺、表格来源按需纳入、聚合表隔离、KDA/GPM 口径、部分数据排除、API、比赛详情。`verify_analysis_page.py` 启动本地服务并用 Chromium 走总览→部分数据→队员趋势→比赛详情→数据源，截图保存在 `test-results/analysis-*.png`。

## 边界

- 只读；不创建正式比赛、不修改数据库、不自动去重表格与本机记录。
- 数据包没有对手/赛事/版本时，这些筛选只能匹配本机记录；未知对手会单独显示。
- 聚合表只能查看，不能与单局数据相加或再平均；分析层消费时要先按 `grain` 分开。
- 平台不提供导出/分享；训练赛私有数据只在本地。
- 当前单战队、本机使用；多战队权限与云端协作未实现。
