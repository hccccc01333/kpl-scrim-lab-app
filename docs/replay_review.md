# 回放 2D 审阅器（R2）：R1 gzip 与 11/2 购买/加点接入

本文记录 `web/replay-review.*` 的本地只读改造。所有操作仅读取本地数据集；不启动/连接游戏、不登录、不注入，也未修改 R1 的 `tools/` 或 `datasets/`。

## 1. 改动文件

| 文件 | 作用 |
|---|---|
| `web/replay-review.js` | 浏览器流式解压 gzip、R1 JSONL 适配、11/2 BUYEQUIP/LEARNSKILL、购买/加点页、截图对拍页、调试快照 |
| `web/replay-review.html` | 新增“加载 R1 gzip”按钮、购买/加点 tab、时间轴图例与读法说明 |
| `web/replay-review.css` | 新增 BUYEQUIP/LEARNSKILL 颜色、购买/截图表格样式、时间轴高度 |
| `web/replay-review-data.js` | 由构建脚本重新生成的快照（约 1.9 MB），不含 gzip 全量事件行 |
| `scripts/build_replay_review_bundle.py` | 增加 gzip 索引、11/2 CSV、装备价格、OCR/图标对拍、面板金币分析 |
| `docs/replay_review.md` | 本文件 |

未改动：`data/replays/_analysis/datasets/*`、`tools/*`、任何 R1 业务脚本。`data/` 在 `.gitignore` 中，gzip 与 7 MB+ 数据不会进入提交。

## 2. 如何打开

### 2.1 直接打开本地文件

打开 `web/replay-review.html`。页面会先加载内置快照；gzip 事件流需要浏览器支持 `DecompressionStream('gzip')`：

1. 点击“打开数据文件夹”，选择 `data/replays/_analysis/datasets`，会读取 CSV 和 `replay_event_stream_events.jsonl.gz`；
2. 或点击“加载 R1 gzip”，单独选择 gzip 文件，把它接到当前快照上。

`file://` 下不能 `fetch` 本地路径，但文件选择器和 gzip 解压仍可用。

### 2.2 本地静态服务器（推荐，能测试 data/ 路径）

在项目根目录：

```bash
python -m http.server 8765 --bind 127.0.0.1
```

打开：

```text
http://127.0.0.1:8765/web/replay-review.html
```

点击“尝试 data/ 路径”，会读取 `data/replays/_analysis/datasets/` 下的 CSV，并优先加载 `replay_event_stream_events.jsonl.gz`。

URL 参数：

- `?data=../data/replays/_analysis/datasets/`：自动读取该目录的 CSV + gzip；
- `?gzip=../data/replays/_analysis/datasets/replay_event_stream_events.jsonl.gz`：额外加载指定 gzip；
- `?sample=20261102_161129&t=79&entity=1760`：定位样本 / 帧 / 实体。

### 2.3 重新生成快照

```bash
python scripts/build_replay_review_bundle.py
# 省略 OCR/图标对拍以加快：
python scripts/build_replay_review_bundle.py --skip-screenshot
```

构建脚本只读 `data/replays/_analysis/datasets/` 和 `resources/`，只写 `web/replay-review-data.js`。

## 3. 支持的数据

### 3.1 原有 R2 数据

- `replay_players.csv`、`replay_commands.csv`、`replay_heading.csv`、`replay_events.csv`
- 尾部 712 帧：`replay_tail_*`
- 皮肤/评分：`agent_skin_ids.csv`
- 可选未压缩 JSONL：`replay_event_stream.jsonl`（适配层保留）

### 3.2 R1 gzip 事件流

- 文件：`data/replays/_analysis/datasets/replay_event_stream_events.jsonl.gz`
- 规模：326,096 条事件 / 21 个回放文件（构建时索引；事件行不内联进 bundle）。
- 加载方式：浏览器 `file.stream()` 或 `fetch` → `DecompressionStream('gzip')` → `TextDecoderStream` 逐行解析，不一次性读入 700 MB 级文本。
- 已实测：326,096 条全部接入，`unmatched=0`，控制台无错误。
- 文件匹配：20 个文件与 R2 快照同名，事件直接并入；`20261101_182452` 作为“仅事件流样本”新增。
- 事件分类：
  - `BUYEQUIP` → 购买（buy）
  - `LEARNSKILL` → 加点（learn）
  - 其他 → R1 事件流（stream），包括 move / beacon / state / skill 等。
- `move` 事件不会被当成地图连续位置；地图只画 `aim_point_command`、`aim_trajectory_point`、`point_update`、`use_position/objective_skill` 等点类事件，且受残影窗口和数量上限约束。

### 3.3 11/2 购买/加点数据

读取：

- `20261102_buy_events.csv`（BUYEQUIP 原始通知，含重复）
- `20261102_skill_events.csv`（LEARNSKILL）
- `20261102_player_actions.csv`（每玩家 raw/unique/标价和/加点/操作计数）
- `agent_equip_prices.csv`（`battle_item` 的 `buy_price` / `sell_price` / `price_type`）

生成两个合成样本：

- `20261102_161129_...`：BUY 547 / SKILL 120
- `20261102_163751_...`：BUY 627 / SKILL 150

合成样本没有 `replay_*.csv` 的坐标命令、朝向、队伍/分路，因此：

- 地图为空，不补造位置；
- 顶部样本元数据会提示“仅购买/加点 CSV”；
- 购买/加点页按帧显示 BUYEQUIP（equip_id、名称、`buy_price`）和 LEARNSKILL（技能槽、等级）。

### 3.4 BUYEQUIP 语义（重要）

- `0x02/0x85` = BUYEQUIP，购买/出装通知，不是金币。
- 原始通知有大量重复：161129 为 547 条原始通知，按 `(entity, equip_id)` 去重后 135 件（10 人合计）。
- 去重集合同时包含**合成件**和**成品**（例如铁剑 1111 与无尽战刃 1133、神速之靴 1411 与抵抗之靴 1422）。
- 因此把所有去重装备的 `buy_price` 相加只能叫“去重标价和”，**不能直接当累计花费**，更不能当金币收入、当前金币或余额。
- 可对拍的是**最终 6 格装备成本**：按截图人工识别的格内装备 × `battle_item` 买价求和。
  11/2 第一局 5 名 6/6 完整识别玩家成本 6,175–9,130，全部严格小于面板累计金币；
  10 人中 9 人满足 `成本 < 面板`；翳灵崽 4 格 6,130 > 面板 5,828（−302g）是异常，
  不能加 300 掩盖，需查装备 ID/价格/面板读数或出售。
  这是一致性检查，不是逐笔购买账本或收入曲线。
- 页面不读取、不展示 `gold_event_total`；仅显示截图面板金币用于对拍分析（见第 4 节）。
- 注意：`20261102_player_actions.csv` 的实际表头是 `unique_equip_price_sum_unverified`；本页按实际表头读取，并在 UI 中标为“去重标价和（不可当花费）”。

## 4. 截图对拍

截图：`data/screenshots/samples/20261102_1559/01-score-equipment.jpg`（2026-11-02 15:59，27:6，11:33，5v5 排位）。

### 4.1 同局身份核对

- 截图 OCR：页面类型 `score`，日期/时间/比分/时长与截图一致。
- 与 `20261102_161129` 的 `player_actions` 对照：
  - OCR 昵称 6/10 精确或模糊匹配（OCR 把 `狂傲自由魂Z.` 读成 `狂傲自由魂乙`、`自诩一棵葱` 读成 `自翊一棵葱`，并漏读右侧部分昵称）；
  - 英雄 9/10（OCR 漏读妲己）；
  - 评分 10/10；
  - 人工目测昵称/英雄 10/10 与 CSV 一致。
- 结论：该截图对应 `20261102_161129`，不是 163751。

面板真值（截图可见，作为外部输入；不是回放字段）：

| 选手 | KDA | 面板金币 |
|---|---:|---:|
| 漂流网咖 | 5/0/8 | 8697 |
| 狂傲自由魂Z. | 8/1/7 | 9243 |
| 自诩一棵葱 | 6/1/7 | 8168 |
| 别吃窝线吖a | 5/1/5 | 8352 |
| 胡不喜# | 3/3/9 | 6540 |
| 麻巫喵 | 1/5/2 | 6191 |
| 翳灵崽 | 2/7/2 | 5828 |
| 一风舞 | 2/3/3 | 5778 |
| 扁鹊耳垂 | 1/6/2 | 5977 |
| 谜语星海 | 0/6/4 | 5474 |

### 4.2 装备图标对拍

自动全库匹配：

- 本地 `resources/catalog.json` 的 115 件装备图标作为参考；
- 对 60 个装备区域做相似度排序，最高相似度 0.895，0/60 达到 0.94 可靠性阈值；
- 因此自动全库匹配结论为 **unverified**，不能据此认定 equip_id。

人工逐格对拍（逐格对照截图图标与各自 BUYEQUIP 候选集）：

- 截图共有 52 个可见装备图标（其余为空格）；
- 人工判读 52/52 格，其中 31 格高置信（high），其余 medium/low；
- 可辨认图标 0 个超出对应玩家的 BUYEQUIP 去重集合；
- 结论：**最终面板装备与 BUYEQUIP 去重集合不矛盾，未发现购买集合之外的最终装备；但图标没有名称/ID，部分低置信格不能逐件 100% 确认。** 低置信格保留未知，未编造 equip_id。

逐人摘要（完整清单见页面“截图对拍”折叠表）：

| 选手 | 可见格 | 可辨 | 高置信 | 超出 BUYEQUIP |
|---|---:|---:|---:|---:|
| 漂流网咖 | 6 | 6 | 4 | 0 |
| 狂傲自由魂Z. | 6 | 6 | 5 | 0 |
| 自诩一棵葱 | 6 | 6 | 3 | 0 |
| 别吃窝线吖a | 6 | 6 | 3 | 0 |
| 胡不喜# | 5 | 5 | 1 | 0 |
| 麻巫喵 | 6 | 6 | 3 | 0 |
| 翳灵崽 | 4 | 4 | 2 | 0 |
| 一风舞 | 4 | 4 | 4 | 0 |
| 扁鹊耳垂 | 4 | 4 | 4 | 0 |
| 谜语星海 | 5 | 5 | 2 | 0 |

### 4.3 面板金币 vs 最终装备成本

- 面板金币合计：70,248（单人 5,474–9,243），口径是赛后累计金币（**含初始 300**，`docs/match_data.md`），不是当前余额。
- 本地营地数据 `camp-1793606215` 交叉核对：蓝/红团队金币 41,021/29,266 vs 面板求和 41,000/29,248，差 21/18g；KDA 10/10 一致。
- BUYEQUIP 去重标价和合计：107,950（单人 8,840–14,855），10/10 大于面板；因为集合同时含合成件+成品+重复通知，不能当累计花费。
- 用截图最终 6 格装备重算（`20261102_build_cost_vs_panel.csv`）：

| 选手 | 面板累计金币 | 最终装备成本 | 面板−成本 | 成本<面板 | 6/6 |
|---|---:|---:|---:|---|---|
| 漂流网咖 | 8,697 | 8,400 | +297 | 是 | 是 |
| 狂傲自由魂Z. | 9,243 | 9,130 | +113 | 是 | 是 |
| 自诩一棵葱 | 8,168 | 7,870 | +298 | 是 | 是 |
| 别吃窝线吖a | 8,352 | 7,020 | +1,332 | 是 | 是 |
| 麻巫喵 | 6,191 | 6,175 | +16 | 是 | 是 |
| 翳灵崽 | 5,828 | 6,130 | **−302** | **否** | 4/4（仅 4 格） |
| 一风舞 | 5,778 | 5,620 | +158 | 是 | 4 格，2 未知 |
| 胡不喜# | 6,540 | 5,760 | +780 | 是 | 5 格，1 未知 |
| 扁鹊耳垂 | 5,977 | 5,740 | +237 | 是 | 4 格，2 未知 |
| 谜语星海 | 5,474 | 3,455 | +2,019 | 是 | 5 格，1 未知 |

- 5 名 6/6 完整识别玩家的最终装备成本都严格小于面板累计金币，剩余 16–1,332g。
- 翳灵崽是唯一异常：4 格全部识别、成本 6,130 > 面板 5,828，**−302g**。
  面板已含初始 300，且玩家不可能把金币花到 0、装备价是整数；加 300 只能把差额从 −302 变成 −2，仍然不合法。
  因此不能把 296 当“面板不含初始 300”的校准点；需查装备 ID/价格/面板读数或未记录的出售。
- 10 人中 9 人满足 `最终装备成本 < 面板累计金币`，5 名完整识别玩家全部通过；
  这只是一致性检查，296 未解决前不能当收入下界。
- 未识别格只累加已知装备，成本是下界；不能补造装备来凑面板金币。
- 结论：BUYEQUIP 标价和不能当累计花费；最终 6 格装备成本能解释面板量级，
  但 296 异常未解决，且它不是逐笔购买账本、金币收入或余额。页面不显示 `gold_event_total`。

## 5. 页面行为

- “购买/加点” tab：
  - 顶部统计 BUYEQUIP 原始通知、去重装备、去重标价和、LEARNSKILL；
  - 明确提示“不是金币收入/累计花费”；
  - 截图对拍：同局 OCR、面板累计金币、最终 6 格装备成本、面板−成本、人工图标判读；
  - 按选手展开：每个装备的首次帧、名称、ID、`buy_price`、通知次数；LEARNSKILL 帧/技能槽/等级；`player_actions` 汇总用于交叉核对。
- “事件” tab：
  - 新增 BUYEQUIP 购买、LEARNSKILL 加点筛选 chip；
  - BUYEQUIP 行显示 `#equip_id 名称 · buy_price 金（标价参考，不是花费/收入）` 和首次/重复标记；
  - LEARNSKILL 行显示技能槽与等级（含 0-based 原始值）。
- 时间轴：新增 buy / learn 两条 lane；R1 其他事件保留 stream lane。
- 样本元数据：显示 BUY/SKILL/流计数；合成样本提示无坐标/队伍。
- 数据源列表：显示 gzip 索引、实际加载行数、接入/未匹配数量。

## 6. 已知限制

1. **11/2 合成样本没有地图/队伍/分路**：内置快照只有购买/加点 CSV，没有坐标命令；`team=0`、`slot=null`，不推断队伍。两局都是 **10 真人、0 AI**（`blocks.bot` 全 False）。新 `/inputs` API 已按 `unit` 高 5 位（camp1 8–12、camp2 16–20）映射到十人槽位，可给 per-player move/attack；0x82 kind=2 提供稀疏位置锚点，但不是连续轨迹（5.128）。
2. **BUYEQUIP 不是金币**：原始通知含重复；去重集合含合成件+成品；卖出、合成消耗、后续金币变化未还原。标价和不是累计花费/收入。
3. **面板金币语义**：赛后累计金币（含初始 300），不是当前余额；回放用最终 6 格成本做严格检查 `cost < panel`，9/10 通过，5 名 6/6 完整识别玩家全部通过；翳灵崽 `6,130 > 5,828` 是 −302g 异常，需查装备 ID/价格/面板读数或出售，不能加 300 掩盖。仍不是逐笔收入。
4. **R1 gzip 是事件流，不是完整状态**：move/beacon 等不是连续位置；地图只画点类事件，且受窗口/数量上限约束；事件流没有完整英雄属性、经济账本或最终装备状态。
5. **gzip 依赖浏览器能力**：需要 `DecompressionStream('gzip')`（新版 Chrome/Edge）。不支持时请使用内置快照或文件夹 CSV；未提交 700 MB 级全量文本。
6. **只自动加载 events-only gzip**：优先 `replay_event_stream_events.jsonl.gz`（326,096 条）；更大的 `replay_event_stream.jsonl.gz`（1,538,203 条）只作为可选后备，不建议在低内存环境加载。
7. **截图装备无名称/ID**：OCR 读不到图标含义；自动全库匹配 0/60 达阈值；人工判读有 high/medium/low 置信，低置信格保留未知。对拍结论是“不矛盾/未发现超出集合”，不是逐件 100% 证明。
8. **时间轴 30 fps 为假设**：仅用于定位，不是官方时长。
9. **R1 `hero_id` 语义**：事件流中的 `hero_id` 是 R2 名单实体 ID（不是英雄模板 ID）；`actor_id` 是子 actor。页面按 `hero_id` 优先匹配实体，因此不会把子 actor 当成新选手。仅事件流样本可能缺少英雄名映射。

## 7. 验证记录

- `node --check web/replay-review.js`：通过
- `node --check web/replay-review-data.js`：通过
- `python -m py_compile scripts/build_replay_review_bundle.py`：通过
- `python scripts/build_replay_review_bundle.py`：生成 22 个样本；包含 20 个原 R2 样本 + 2 个 11/2 合成样本；gzip 索引 326,096 事件 / 21 文件
- 浏览器（本地 `python -m http.server`）：
  - 页面加载无 console error；
  - “尝试 data/ 路径”后 gzip `lines=326096`、`applied=326096`、`unmatched=0`；
  - 数据集 23 个样本（20 + 2 个 11/2 + 1 个仅事件流样本）；
  - 11/2 161129 样本：BUY 547 / SKILL 120 / 流 667；购买页显示 135 件去重、标价和 107,950；
  - 事件页 BUYEQUIP/LEARNSKILL 筛选和行详情正常；
  - 截图对拍区域显示 OCR 同局、面板金币、人工图标结果，无未捕获异常。

## 8. 相关路径

- 页面：`D:/Projects/KPL训练赛项目/web/replay-review.html`
- 脚本：`D:/Projects/KPL训练赛项目/web/replay-review.js`
- 样式：`D:/Projects/KPL训练赛项目/web/replay-review.css`
- 快照：`D:/Projects/KPL训练赛项目/web/replay-review-data.js`
- 构建：`D:/Projects/KPL训练赛项目/scripts/build_replay_review_bundle.py`
- gzip：`D:/Projects/KPL训练赛项目/data/replays/_analysis/datasets/replay_event_stream_events.jsonl.gz`
- 11/2：`D:/Projects/KPL训练赛项目/data/replays/_analysis/datasets/20261102_buy_events.csv`、`20261102_skill_events.csv`、`20261102_player_actions.csv`
- 价格：`D:/Projects/KPL训练赛项目/data/replays/_analysis/datasets/agent_equip_prices.csv`
- 截图：`D:/Projects/KPL训练赛项目/data/screenshots/samples/20261102_1559/01-score-equipment.jpg`
