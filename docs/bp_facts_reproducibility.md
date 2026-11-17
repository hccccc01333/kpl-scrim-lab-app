# BP 事实表可复现性契约（v1.6.7）

## 1. 产物

`data/facts/` 下两份事实表，由 `scripts/build_bp_facts.py` 离线生成：

- `lane_matchups.json` —— 巅峰千强大盘同分路对位（`bp_facts.py` 的「对位压制」消费）。
- `kpl_combos.json` —— KPL 赛事同队组合（`bp_facts.py` 的「赛事命中 / 联动」消费）。

两表互不合并成一个分（见 `bp_facts.py` 模块文档）。

## 2. 生成命令

```bash
# 只重建 KPL 组合（本项目自抓，可完全复现）
python scripts/crawl_kpl_bp.py --since-year 2024 --build
python scripts/build_bp_facts.py --kpl data/kpl/bp_games.jsonl

# 同时重建巅峰千强对位（依赖外部 bp-project 数据集，授权受限，不随仓库分发）
python scripts/build_bp_facts.py \
  --bp-project "<本地 bp-project 数据集目录>" \
  --kpl data/kpl/bp_games.jsonl
```

## 3. 输入契约

| 产物 | 输入 | 是否随仓库分发 |
|------|------|----------------|
| `kpl_combos.json` | `data/kpl/bp_games.jsonl`（自抓） | 是（脚本 + 数据） |
| `lane_matchups.json` | 外部 `bp-project/data/processed/91m/hero_daily.parquet` + `matchup_raw/` | 否（授权受限） |

外部数据集的授权与权利归原数据方。公开仓库只提供 KPL 部分的可复现管线；
巅峰千强部分缺失时，`build_bp_facts.py` **保留现有** `lane_matchups.json`，绝不覆盖成空表。

## 4. 校验

- `tests/test_kpl_bp.py::test_build_bp_facts_detects_local_and_legacy` 锁定 KPL 格式识别与最小产物。
- `tests/test_kpl_bp.py` 中 bp_facts 用例锁定 `for_match` 的字段与兜底行为。
- 新增字段（`excessCI` / `reliability` / `shrunkExcess` / `shrunkWr` / `draftEvents`）必须向后兼容：
  老文件缺字段时消费方按「缺失 → 不展示」处理，不报错。

## 5. 统计口径（对位）

- 收录门槛 `MIN_PAIR_N = 50`，不再按使用率过滤（`MIN_PICK_RATE = 0`）。
- **基准窗口**：英雄胜率取最近 8 周（`WIN_WINDOW_DAYS = 56`），先按周聚合、再取周中位数，
  避免单日异常/作弊局把均值拉高。
- **登场率收缩**：`wr_adj = 0.5 + (wr - 0.5) × pick / (pick + 0.02)`；期望胜率用 `wr_adj`，
  低登场率英雄不把「绝活哥拉高的胜率」带进对位期望。`pick < 1%` 的对位标 `lowPick`。
- 证据分级：`<50` 不足（不收录）；`50–199` 或 `lowPick` 初步观察（只给方向和 CI，
  不判优势/劣势）；`≥200` 且非低登场率可判；`≥3000` 且 CI 不跨 0 为 high。
- 超额胜率 = 实际胜率 − Bradley-Terry 期望胜率。
- `+2` / `-2` 是**效果量提示阈值**，不是统计证据充分的判定：
  每条记录附 `excessCI`（95% 近似区间）与 `reliability`（high/medium/preliminary/insufficient）。
- CI 跨过 0 → `state` 不给方向性结论（归为 even）；50–199 局或低登场率统一归 preliminary。
- 小样本用贝叶斯收缩（`shrunkExcess` / `shrunkWr`），先验以 expected 为中心、伪计数 40。
- **对位矩阵的口径**：91m explorer 返回的是累计 `allPickTimes`，当前对位胜率仍是累计值；
  只有英雄基准做了 8 周窗口。要窗口化对位本身，需要用相邻周快照做差（见 `peak_crawl` 分片），
  在快照覆盖不足前不要混用「周基准 + 累计对位」下强结论。
- **英雄强度窗口（2026-11-17）**：`heroes[name]` 另带 `wr7d/pick7d/wrAdj7d` 与
  `wr30d/pick30d/wrAdj30d`（日线窗口均值，同样按登场率收缩），供「对位样本凑不够」时
  看英雄本身强度；`rolePools` 存分路英雄池，`bp_facts._lane_strength` 按**本局实际分路**
  重排 T1–T4（源站主分路会把李信算进发育路，按主分路排没有意义）。
  页面上「今日巅峰千强」改为「源站累积样本，截至 X」，不再把累计值说成当日值。