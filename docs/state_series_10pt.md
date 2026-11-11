# G7 十检查点状态序列（2026-11-04）

在原有 `state_series_161129.csv` 的 5 个点上，补入 03:49、07:26、07:43、08:49、09:37，
生成统一的 **10 checkpoint × 10 人 = 100 行**引擎实测状态序列。

## 0. 文件

```text
data/replays/_analysis/live_20261104/state_series_161129_10pt.csv
```

列：

```text
clock, second, index, player, hero, camp,
gold, d_gold, gold_rate,
kills, deaths, assists, level,
c0..c10, d_c3, c3_rate, source
```

- `gold` / KDA / `level`：arena record `+0x4C` / `+0x158` / `+0xB8` /
  `+0xBC` / `+0x220`；
- `c0..c10`：record `+0x50` 起的 11 个累计计数；`c3` 仍标
  `engine-measured, semantics unconfirmed`，但本序列给出了强旁证；
- 所有行都是引擎实测，没有插值。

## 1. 十点总量

| clock | gold total | c1 total | c3 total | c3/c1 |
|---|---:|---:|---:|---:|
| 01:34 | 8,564 | 142,537 | 165,010 | 1.158 |
| 02:18 | 12,424 | 213,667 | 248,460 | 1.163 |
| 02:45 | 14,614 | 266,225 | 312,474 | 1.174 |
| 03:49 | 20,310 | 430,520 | 510,167 | 1.185 |
| 05:00 | 28,024 | 623,060 | 737,332 | 1.183 |
| 07:26 | 41,410 | 979,186 | 1,188,823 | 1.214 |
| 07:43 | 43,135 | 1,023,310 | 1,243,940 | 1.216 |
| 07:46 | 43,383 | 1,034,571 | 1,258,022 | 1.216 |
| 08:49 | 50,481 | 1,243,905 | 1,509,932 | 1.214 |
| 09:37 | 55,325 | 1,426,977 | 1,740,289 | 1.220 |

gold 严格单调；c3/c1 从 1.158 缓慢升到 1.216，没有跳变，支持 `c3` 是
“造成的总伤害”类累计量，而不是金币/承伤。

逐人校验：100 行的 `gold/kills/deaths/assists/level` 在 8 个时间点之间
**0 个负增量**（10 人 × 9 个区间）。

## 2. 快照来源

| clock | file |
|---|---|
| 01:34 | `arena_t0_0134.bin` |
| 02:18 | `arena_t1_0146.bin`（文件名 01:46 不可信，unit clock 02:17.8） |
| 02:45 | `arena_t2_0245.bin` |
| 03:49 | `arena_paused_0348.bin` |
| 05:00 | `arena_paused_0500.bin` |
| 07:26 | `arena_light_0726_records.bin`（144 KiB record area） |
| 07:43 | `arena_jump_lubu.bin` |
| 07:46 | `arena_0746_full.bin` |
| 08:49 | `arena_0632.bin`（文件名不可信，真实 08:49） |
| 09:37 | `arena_sync1.bin`（真实 09:37） |

## 2.1 真实时钟（从 unit +0x1664/+0x1668 读取）

- `arena_t1_0146.bin` = **02:17.8**（文件名 01:46 不可信）
- `arena_paused_0348.bin` = **03:48.99**
- `arena_0632.bin` = **08:49.49**（不是 06:32）
- `arena_sync1.bin` = **09:37.40**
- 07:26 来自 `arena_light_0726_records.bin`（record area，无 unit clock）

## 3. 复现

```bash
python tools/state_series.py \
 --snapshot data/replays/_analysis/live_20261104/arena_t0_0134.bin@01:34 \
 --snapshot data/replays/_analysis/live_20261104/arena_t1_0146.bin@02:18 \
 --snapshot data/replays/_analysis/live_20261104/arena_t2_0245.bin@02:45 \
 --snapshot data/replays/_analysis/live_20261104/arena_paused_0348.bin@03:49 \
 --snapshot data/replays/_analysis/live_20261104/arena_paused_0500.bin@05:00 \
 --snapshot data/replays/_analysis/live_20261104/arena_light_0726_records.bin@07:26 \
 --snapshot data/replays/_analysis/live_20261104/arena_jump_lubu.bin@07:43 \
 --snapshot data/replays/_analysis/live_20261104/arena_0746_full.bin@07:46 \
 --snapshot data/replays/_analysis/live_20261104/arena_0632.bin@08:49 \
 --snapshot data/replays/_analysis/live_20261104/arena_sync1.bin@09:37 \
 --roster data/replays/_analysis/live_20261104/roster_161129.json \
 --out data/replays/_analysis/live_20261104/state_series_161129_10pt.csv
```

## 3.1 导入工作台

工作台检查点 API 接受 JSONL。转换器会把 CSV 映射成产品字段，并校验逐人单调性：

```bash
python tools/state_series_to_checkpoints.py \
  data/replays/_analysis/live_20261104/state_series_161129_10pt.csv \
  --out data/replays/_analysis/live_20261104/checkpoints_161129_10pt.jsonl \
  --manifest data/replays/_analysis/live_20261104/checkpoints_161129_10pt.manifest.json \
  --fail-on-nonmonotonic
```

然后在工作台打开对应回放，使用“导入检查点 JSONL”，或：

```bash
curl -X POST "http://127.0.0.1:8766/api/replays/<replay-id>/checkpoints?name=checkpoints_161129_10pt.jsonl" \
  -H "Content-Type: application/x-ndjson" \
  --data-binary @data/replays/_analysis/live_20261104/checkpoints_161129_10pt.jsonl
```

转换器只输出有语义的字段（gold/KDA/level/c1..c10），`sources=arena_stats`，
不插值、不补造 HP/位置。

## 4. 边界

- 这是 10 个离散 checkpoint，不是逐帧；插值仍不写入本表。
- `arena_light_0726_records.bin` 只有 record area，没有同帧 unit HP。
- 03:49 / 07:26 / 08:49 / 09:37 的 HP 尚未补；07:43 的 HP 见
  `docs/state_0743_checkpoint.md`。
- `c3` 的语义仍是候选，需要面板“数据”页锚定后才能写入正式契约。
