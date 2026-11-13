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
  --bp-project "D:/Projects/KPLBPagentRL" \
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

- 最低样本 `MIN_PAIR_N = 200`，双方使用率 `MIN_PICK_RATE = 0.03`。
- 超额胜率 = 实际胜率 − Bradley-Terry 期望胜率。
- `+2` / `-2` 是**效果量提示阈值**，不是统计证据充分的判定：
  每条记录附 `excessCI`（95% 近似区间）与 `reliability`（high/medium/low）。
- CI 跨过 0 → reliability 至少降一档，且 `state` 不给方向性结论（归为 even）。
- 小样本用贝叶斯收缩（`shrunkExcess` / `shrunkWr`），先验以 expected 为中心、伪计数 40。