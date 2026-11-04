# 单局数据包（数据整理）

把赛后截图 OCR 与多路回放录屏 OCR 整理成一份 `kpl-match-data-v1` JSON。这里只做“同一局对齐、字段统一、来源保留”，不计算胜率、分均经济或伤害等分析指标；分析层再消费这份文件。

## 输入

| 输入 | 来源 | 作用 |
| --- | --- | --- |
| 录屏报告 | `scripts/replay_video_ocr.py` 生成的 `kpl-video-ocr-v1` JSON | 团队时间轴、记分板快照、POV 面板过程数据 |
| 赛后截图 | 战绩页/数据页 PNG/JPG，或 `/api/images/{id}/recognition` 返回的识别 JSON | 全场终局 KDA、经济、伤害、承伤、参团率、评分 |

一份单局数据包可以只有录屏，也可以只有赛后截图；同时有时才做同一局校验。只有录屏时，终局字段退化为“最后一张记分板快照”，并明确标为部分数据，不冒充全场终局。

## 使用

```powershell
python scripts/build_match_data.py `
  --video data/replays/video_ocr/team.json --follow - `
  --video data/replays/video_ocr/pov-ying.json --follow 影 `
  --postgame data/screenshots/score.png `
  --postgame data/screenshots/data.png `
  --out data/matches/<key>.json
```

- `--video` 可重复；第一路作为阵容基准，其余路用于团队曲线复核、记分板和 POV。
- `--follow` 与 `--video` 按出现顺序一一对应；`-` 表示这一路不指定 POV（团队/记分板视频）。
- `--postgame` 可重复：战绩页 + 数据页，或任意一张。图片会调用本机 `ocr.recognize`；也可以传识别 JSON。
- `--force`：同一局校验不通过时仍生成，并保留警告。
- `--match-id`：覆盖自动生成的单局 ID。
- `--out -` 只打印，不写文件。

默认输出 `data/matches/<key>.json`；`--json` 打印完整 JSON。

## 同一局校验

录屏侧使用标题、模式、日期（月/日，年份不显示）、总时长和十人英雄集合；赛后截图使用日期、时长和十人英雄集合。三项检查：

| 检查 | 规则 |
| --- | --- |
| 日期 | 月/日一致；赛后截图有年份时写入数据包，否则年份留空 |
| 时长 | 录屏总时长与赛后时长相差 ≤2 秒（`ocr.py` 的时长单位是分钟，这里换算成秒） |
| 英雄 | 十人英雄集合按“精确或单字差”匹配，重合 ≥8/10 |

- 三项全过：`confidence: high`。
- 只有两项可用且通过：`medium`。
- 日期或时长明确冲突、或英雄重合 <8：`low`，默认拒绝生成，需 `--force`。
- 多路录屏标题不同是允许的（可能是不同玩家的 POV），只给警告；日期/时长/阵容仍须一致。
- 左右阵营不靠固定假设：用双方英雄集合与录屏蓝/红阵容比较，取重合度高的一侧映射；无法精确匹配时标 `partial/assumed`。

## 赛后两张图的合并

战绩页和数据页的行序可能不同，**按行内英雄名匹配到录屏阵容的稳定 key**，不按截图行号合并。字段优先级：

| 字段 | 优先页 | 说明 |
| --- | --- | --- |
| 击杀/死亡/助攻 | 战绩页 | 数据页没有 KDA |
| 伤害/承伤/参团率 | 数据页 | 只有数据页有 |
| 经济、评分、英雄 | 数据页优先 | 两页都有时保留来源页 |
| 装备图标 | 视觉候选 | 只保存候选，不当作确认名称 |

数值保留 `raw`（原始文本）、`value`（解析值）、`unit`、`approx`（`k/万` 为显示精度）、`confidence` 和 `sourcePage`。缺失字段保持 `null`，不用快照或猜测补齐全场终局。

## POV 归属

- 每路视频用 `--follow` 指定被观战队员（昵称或英雄）；解析必须唯一。
- 报告里的 `pov` 是录制账号/本地玩家，不一定等于被观战目标；不要自动拿它代替 `--follow`。
- 一路视频里出现多段观战目标切换时，仍把段挂到 `--follow`，但会写警告；每段的 `level/kda/availableGold/stats/runes/equipment` 保留，身份标记 `manual`。
- 没有 `--follow` 的视频只贡献团队曲线和记分板，其选中面板放到 `unattributedPov`，不冒充某名队员。

## 团队数据合并

- 时间轴：多路报告按 `gameTime` 合并，金币取中位数、击杀取整数中位数；差值超过容差时标 `disagree` 并写警告；合并后仍强制单调，回退点丢弃。
- 记分板：只采用金币校验通过的快照，按 `(gameTime, 双方金币行)` 去重；每名队员的 KDA/累计金币形成 `players[].process.scoreboard` 序列。
- 击杀变化：从合并后的时间轴重新推导，不从单路事件直接拼接。
- 覆盖：录屏只到 01:46 / 02:57 时，`match.videoCoverage` 标出结束点和比例，并写“团队曲线不是全场”。

## 字段语义

| 字段 | 含义 | 不能混用 |
| --- | --- | --- |
| `key` | 本次数据包内的行键（阵营 + 选人序号） | 不是队员稳定 ID；正式队员身份仍需在工作台名单中确认 |
| `final` | 全场终局；优先赛后截图 | 只有录屏时是最后记分板快照，标 `partial` + `gameTime` |
| `process.scoreboard[].totalGold` | 记分板逐人累计经济快照 | 不等于底部面板的可用金币 |
| `process.pov[].availableGold` | 底部面板的当前可用金币 | 不是累计经济；买装备会下降 |
| `process.pov[].kda` | 当前观战面板的 KDA 段首/段尾 | 不是全场终局 |
| `process.series[]` | POV 逐秒过程（等级/KDA/可用金币/属性/铭文/装备） | 切换观战目标时混有不同目标，需看警告 |
| `match.scores` | 赛后比分，按阵营映射后为整数 | 只有战绩页提供 |

## 输出示例

```json
{
  "schema": "kpl-match-data-v1",
  "match": {
    "key": "20261028-177-71b998",
    "title": "茉莉花与雨",
    "mode": "峡谷—快速赛",
    "date": {"year": 2026, "month": 10, "day": 28, "text": "2026-10-28"},
    "duration": 177,
    "scores": {"blue": 20, "red": 18},
    "identity": {"confidence": "high", "checks": {"date": true, "duration": true, "heroes": 10}},
    "videoCoverage": {"start": 0, "end": 106, "ratio": 0.599}
  },
  "sources": [
    {"kind": "video", "file": "...", "sha256": "...", "followLabel": "孙膑",
     "followPlayer": {"camp": "blue", "hero": "孙膑", "nickname": "茉莉花与雨"}},
    {"kind": "postgame", "file": "score.png", "pageKind": "score"}
  ],
  "roster": {"blue": [{"key": "blue-0", "hero": "影", "nickname": "影", "slot": 0}], "red": []},
  "team": {"timeline": [], "scoreboardSnapshots": [], "killEvents": []},
  "players": [{
    "key": "blue-0", "camp": "blue", "hero": "影", "nickname": "影",
    "final": {
      "source": "postgame", "complete": true, "partial": false,
      "kills": 7, "deaths": 4, "assists": 5,
      "totalGold": 11700.0, "damage": 31200.0, "taken": 22400.0,
      "participation": 72.5, "rating": 12.8,
      "fields": {"gold": {"raw": "11.7k", "value": 11700.0, "unit": "k", "approx": true, "sourcePage": "data"}}
    },
    "process": {"pov": [], "series": [], "scoreboard": []}
  }],
  "unattributedPov": [],
  "postgameUnmatched": [],
  "coverage": {},
  "warnings": []
}
```

## 本次样本

- 只有录屏（没有同一局的赛后截图）时，生成 `data/matches/1028-177-71b998.json`：
  - 1 路视频、无赛后；终局 10 人全部取自 01:00 记分板快照，标 `partial`；
  - 团队时间轴 97 点、记分板 4 快照、POV 1 人（孙膑，5 段观战切换警告）；
  - 提示“录屏只覆盖到 01:46 / 总时长 02:57”。
- 赛后战绩页/数据页的合并、左右阵营互换、行序不同、只有单页、同一局校验失败需 `--force` 等情况由 `tests/test_match_data.py` 用合成 OCR 结果覆盖。工作区没有与这段录屏同一局的真实赛后截图，因此没有把合成数值写进正式样本。

## 边界

- 这是整理层，不计算 KDA、GPM、XPM、分均伤害、参团率或胜率；这些留给分析层，避免在整理阶段重复实现统计口径。
- 录屏终局字段天然是局内过程，不是全场终局；只有赛后截图才是全场数据。两者都不完整时，保留缺失并写警告。
- 赛后截图 OCR 的 `41.8k` 等是显示精度；`value` 是近似值，`raw` 保留原文。
- POV 身份是人工标签，不能由底部面板自动确认；多段切换时只保证“这一段属于同一面板”。
- 装备名来自图标候选，未达到阈值不提供名称；铭文只在本地面板显示且末尾可能被裁切。
- 多路视频标题可以不同（不同 POV 账号），但日期/时长/阵容必须一致；不通过校验时默认拒绝，需人工 `--force`。
- 输出只写本机 `data/`，不进入工作台数据库、不自动创建正式比赛。

## 验证

```powershell
python -m unittest tests.test_match_data -v
python -m unittest discover -s tests -v
```

测试覆盖：同一局高/低置信度与 `--force`、左右阵营互换、行序不同的两页合并、只有战绩页/只有数据页、无赛后时用记分板快照、POV 唯一/歧义/未标注、多路时间轴中位数与不一致警告、显示精度解析、单局 key 年份规则。
