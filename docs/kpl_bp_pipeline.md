# KPL BP 数据管线契约（冻结版 v1）

> 本文件是 `bp-crawler` 与 `bp-ui` 两条并行工作流的唯一接口约定。
> 由 Lead 冻结；两侧都不得单方面改字段名。需要新增字段时先发消息给 Lead。

## 0. 为什么有这条管线

`赛事命中` 原来吃的是 `data/facts/kpl_combos.json`，它由**外部项目**的
`prematch_games_raw.jsonl` 离线跑出来（`scripts/build_bp_facts.py --kpl ...`）。
外部数据包不会自己更新，所以改成：本项目自己从**KPL 官方赛事接口**抓 BP。

已验证可用的公开接口（无需登录、无需 Cookie）：

| 用途 | 接口 |
| --- | --- |
| 赛季列表 | `https://prod.comp.smoba.qq.com/leaguesite/leagues/open` |
| 赛季赛程 | `https://prod.comp.smoba.qq.com/leaguesite/matches/open?league_id=<id>` |
| 一场比赛的小局 | `https://prod.comp.smoba.qq.com/leaguesite/match/battles/open?match_id=<id>` |
| 单局快照（含 BP） | `https://prod.comp.smoba.qq.com/leaguesite/battle/open?battle_id=<id>` |

关键事实（已实测）：

* `leagues/open` 返回 33 个赛季（2019 起），字段 `league_id / league_name / year / status`。
* `matches/open` 每行含 `match_id / start_time / status / camp1.team_name / camp2.team_name /
  match_battle_video_list[].battle_id / match_stage_desc / bo`；`status == 2` 表示已完赛。
* `battle/open` 的 `data` 含：
  * `bp_list`：完整局 20 条（2024 赛季为 18 条，4 ban/边），
    `{camp, is_ban_or_pick, hero_id, hero_name, hero_icon, position}`，
    **`is_ban_or_pick == 1` 是选用（pick），`== 0` 是禁用（ban）**，顺序即 BP 顺序；
    ⚠️ 此处 Lead 第一版笔误写反过，已用 `battle_player_list` 逐英雄交叉校验 10/10 修正。
  * **巅峰对决（盲选）没有 BP**：系列赛打满最后一局（BO7 打到 3:3 的第 7 局）按规则盲选，
    没有 ban、也没有选人顺序，官方接口的 `bp_list` 为空或不完整——**这不是数据缺失**。
    实测 4702 个小局里 44 局属于这种情况。这类局的 5 人阵容取 `battle_player_list`，
    记 `bpMode = "blind"`、`bansKnown = false`、`pickOrderKnown = false`，
    **照常计入组合 / 整阵容统计**（教练问的就是「这套阵容 KPL 见过没有」，盲选也是选）。
  * 同理，个别老局 `bp_list` 整体缺失或条数不足（实测 2024 有 3 局），
    只要 `battle_player_list` 有 10 人，就记 `bpMode = "partial"` 取 pick，不要整局丢掉。
  * **pick 的权威来源是 `battle_player_list`**：`bp_list` 完整时用它取 ban 与选人顺序，
    并强制校验两侧 pick 集合与十人面板一致（不一致 → `mismatch`，跳过并记账）；
    `bp_list` 空/不完整时用十人面板兜底，只标记 `bansKnown = false`，不算错。
  * `win_camp`（1/2）、`game_duration`（毫秒）、`battle_seq`；
  * `camp1/camp2`：`team_id / team_name / team_abbreviation / is_win`；
  * `battle_player_list`：10 条，除 `hero_name / player_name / actual_player_name / position_desc / team_name`
    外，还含 `kill_num / death_num / assist_num / participation_rate / gold / hurt_total /
    hurt_to_hero_total / be_hurt_total / be_hurt_by_hero_total` 等终局字段。
* 单次请求 ~46 KB；同一个 `requests.Session`（keep-alive）串行约 **0.1 秒/局**。
  4600 局 ≈ 8 分钟。不要开大并发（16 并发反而更慢）。
* 请求头用 `Referer: https://pvp.qq.com/`、普通浏览器 UA 即可；`trust_env = False`（直连，绕过代理）。

## 1. 落盘：`data/kpl/bp_games.jsonl`

一行一局，schema `kpl-bp-game-v1`：

```json
{
  "schema": "kpl-bp-game-v1",
  "battleId": "1054884368_36_1790920656",
  "matchId": "2026100201",
  "leagueId": "20260004",
  "leagueName": "2026KPL年度总决赛",
  "year": 2026,
  "stage": "擂台赛",
  "startTime": "2026-10-02 14:00:00",
  "date": "2026-10-02",
  "gameSeq": 1,
  "durationMs": 840000,
  "camp1": {"teamId": "10008", "team": "深圳DYG", "abbr": "DYG"},
  "camp2": {"teamId": "10017", "team": "广州TTG", "abbr": "TTG"},
  "winCamp": 2,
  "winner": "广州TTG",
  "bpMode": "full",
  "bansKnown": true,
  "pickOrderKnown": true,
  "picks": {"1": ["敖隐", "女娲", "苏烈", "裴擒虎", "达摩"], "2": ["张飞", "海月", "赵云", "夏洛特", "百里守约"]},
  "bans":  {"1": ["沈梦溪", "钟馗", "苍", "马超", "公孙离"], "2": ["鲁班大师", "盾山", "阿古朵", "橘右京", "夏侯惇"]},
  "players": {"1": [{"hero": "苏烈", "player": "小A", "position": "游走",
    "stats": {"kills": 5, "deaths": 0, "assists": 9, "participation": 93.3333,
      "gold": 7176, "damage": 144350, "heroDamage": 68113, "taken": 37752, "heroTaken": 32422}}], "2": []},
  "fetchedAt": "2026-11-11T14:20:00"
}
```

* `picks` / `bans` 的键是 camp（`"1"` / `"2"`），值是英雄名数组，**按 BP 顺序**。
* `bpMode` 只有三种取值：
  * `"full"` —— 正常 BP，ban 与选人顺序都有；
  * `"blind"` —— 巅峰对决（盲选），无 ban、`picks` 由十人面板给出，顺序不代表选人顺序；
  * `"partial"` —— 老局 `bp_list` 缺失/不全，`picks` 同样由十人面板给出。
  三种都算有效数据、都进组合统计；`bansKnown` / `pickOrderKnown` 让下游知道别把空的
  `bans` 当成「一个 ban 都没有」。
* 只保留 BP、胜负与选手终局统计，不落整包快照。`stats` 是兼容扩展：旧局没有详细字段时省略，
  不补零；`participation` 保持官方 `0–100` 口径，`durationMs` 用于计算分均指标。
* 文件为追加式去重存储：`battleId` 已存在就不再请求。要给旧局补详细指标，运行
  `python scripts/crawl_kpl_bp.py --refresh`（会重抓并覆盖已有行）。

## 2. 落盘：`data/kpl/manifest.json`

```json
{
  "schema": "kpl-bp-manifest-v1",
  "updatedAt": "2026-11-11T14:30:00",
  "sinceYear": 2024,
  "games": 4586,
  "windowStart": "2024-01-05",
  "windowEnd": "2026-11-10",
  "full": 4654,
  "blind": 44,
  "partial": 3,
  "invalid": 0,
  "leagues": [
    {"leagueId": "20260004", "leagueName": "2026KPL年度总决赛", "year": 2026,
     "matches": 54, "games": 168, "crawledAt": "2026-11-11T14:30:00"}
  ]
}
```

* `full / blind / partial / invalid` 四类计数加起来等于本次扫描的小局数；
  **`blind` 不是错误**，是巅峰对决没有 BP；`invalid` 才是真拿不到（连十人面板都不全）。
* `errors` / `errorBattleIds` 只记网络/解析类失败，与 `invalid` 分开。

## 3. 派生：`data/facts/kpl_combos.json`（schema 保持 `bp-kpl-combos-v1`）

在原有字段上**只增不改**，`bp_facts.py` 与老消费方都能继续读：

```json
{
  "schema": "bp-kpl-combos-v1",
  "source": "kpl-official",
  "sinceYear": 2024,
  "games": 4586,
  "minGames": 3,
  "updatedAt": "2026-11-11T14:30:00",
  "windowStart": "2024-01-05",
  "windowEnd": "2026-11-10",
  "leagueCount": 9,
  "leagueNames": ["2024KPL春季赛", "..."],
  "note": "场次 = 该组合在 KPL 同队同场出现过的局数；胜率 = 这些局的胜率。不含版本换算。",
  "pairs": [
    {"heroes": ["关羽", "百里守约"], "n": 45, "wins": 20, "wr": 44.4, "year": 2026,
     "size": 2,
     "teams": [{"team": "广州TTG", "n": 6, "wins": 3}, {"team": "成都AG超玩会", "n": 5, "wins": 2}]}
  ],
  "trios": [
    {"heroes": ["关羽", "百里守约", "钟馗"], "n": 3, "wins": 3, "wr": 100.0, "year": 2026,
     "size": 3, "teams": [{"team": "北京WB", "n": 2, "wins": 2}]}
  ]
}
```

* `teams` 按 `n` 倒序，最多保留 5 支；这是「哪些队（教练）用过这套阵容」。
* 英雄名用接口返回的 `hero_name` 原文；同队同场先去重再组合。

### 3.1 整阵容（5 人）：`kpl_combos.json` 的 `lineups`

教练真正问的是「**我们这套 5 人 BP，KPL 那边有没有出现过**」。所以除了双人/三人，
还要把**整队 5 个选用英雄**作为一组统计，单独一个数组（不走 `minGames` 门槛，出现过 1 次就算）：

```json
"lineups": [
  {"heroes": ["关羽", "百里守约", "钟馗", "孙悟空", "妲己"], "n": 2, "wins": 1,
   "wr": 50.0, "year": 2026,
   "teams": [{"team": "成都AG超玩会", "n": 1, "wins": 1}, {"team": "广州TTG", "n": 1, "wins": 0}]}
]
```

* key 用 5 个英雄名**排序后**的元组（避免顺序不同算成两套）。
* 数组按 `n` 倒序；`teams` 同样最多 5 支。
* 体量预估：4500 局 × 2 队 ≈ 9000 条，约 1 MB，可接受。若超过 3 MB，只保留 `n >= 1` 不变、
  去掉 `teams` 里的单次队伍即可，仍保留 `heroes/n/wins/wr/year`。

## 4. `bp_facts.py` 输出扩展（`bpFacts.kpl`）

保留现有全部字段，新增：

| 字段 | 含义 |
| --- | --- |
| `totalTrios` | 本队 5 人里三人组合总数（C(5,3)=10） |
| `updatedAt` | 组合表生成时间（ISO） |
| `sourceLabel` | 给界面看的数据源名，固定 `"KPL 官方赛事"` |
| `windowStart` / `windowEnd` | 统计窗口 |
| `leagueCount` | 覆盖赛季数 |
| `latestYear` | 最近一个赛季年份 |
| `lineup` | **整阵容命中**：`{heroes:[5], n, wins, wr, year, teams}`；没出现过就是 `null` |
| `lineupSeen` | `bool`，整阵容是否出现过（等价于 `lineup != null`） |

`pairs` / `trios` 每行透传 `teams`；`comboIndex` 的每个值也带 `teams`。
**老文件缺这些字段时必须不报错**（用 `.get()`，缺就当没有）。

## 5. 界面（`v3/public/app.js` + `v3/public/style.css`）

两块要重做：`本局 BP 复盘`（类名 `md-bprev`）与 `赛事命中`（类名 `md-kplhit`）。

* 数据只从 `m.bpFacts` 取，不新增接口请求。
* 新字段可能不存在（老数据/老缓存），所有新字段都要有兜底文案，不能出现 `undefined`。
* 新样式类统一 `md-bprev-*` / `md-kplhit-*` 前缀，只改这两个块，不动其它 section。
* 深浅色主题都要能看（`html[data-theme]`）。

### 5.1 赛事命中（md-kplhit）的新信息层级

一眼看懂「这套阵容在 KPL 见过没有」：

1. **最上层＝整阵容结论**（`m.bpFacts.kpl.lineup` / `lineupSeen`），这是主结论，字号最大：
   * 见过：「本队 5 人整阵容 KPL 见过 N 次（M 胜）」，附最近年份；有 `teams` 就列队名；
   * 没见过：「本队 5 人整阵容 KPL 没出现过」——正常结论，不是报错态。
2. **第二层＝组合命中率**：双人 X/10、三人 Y/10，数字块 + 进度条，别只用灰字。
3. **第三层＝命中组合逐条**：头像 + 英雄名 + N 场 + 胜率 + 「哪些队用过」chips（`teams` 最多 3 支，多出写 `+N`；无 `teams` 整行不显示）。
4. **底部＝口径脚注**：`sourceLabel` + `windowStart–windowEnd` + `updatedAt`（日期即可），缺字段就不显示该片段。
5. `hitPairs + hitTrios === 0` 且 `lineup` 为空时给体面空态，不要像报错。

### 5.2 本局 BP 复盘（md-bprev）的新信息层级

* 头部：标题 + 徽章（沿用现有 badge：证据不足 / 样本偏薄 / BP 端占优 / BP 端吃亏 / 五五开）。
* 主体：一句话结论（现有 `parts.join('；')`）作为主文案，字号加大、可读；可拆成「对位 / 赛事 / 组合」三块短句，但不要变表格。
* 底部：`样本偏薄` 提示保留，改成一行轻提示。
* 配色跟徽章语义走（good / bad / thin 三态），只用现有 CSS 变量。
