# 赛训数据字段总览（现状快照）

> 快照日期：2026-11-15。来源：运行中的 API（`http://127.0.0.1:8766`）、`v3/serve.py`、`bp_camp.py`、`workspace_store.py`、`data/` 落盘文件。
> 当前为验证数据集：**396 局**可分析对局，其中 340 局有经济采样、396 局有回放聚合；一血/一龙/一塔等事件字段只按可读局计算。
>
> 口径：**经济差 = 我方 − 对手**，负数是落后；时间单位秒；分均 = 每分钟；金币单位。

---

## 1. 数据分层与落盘位置

| 层 | 内容 | 位置 | 规模 |
|---|---|---|---|
| 采集原始 | 营地战报详情 | `data/camp_details/*.json` | 104 |
| 采集原始 | 官方回放全景 | `data/official_replays/<id>/{raw,normalized,meta,fields}.json` | 76 |
| 采集归档 | 对局归档（主记录来源） | `data/matches/*.json` | 396 |
| 关系库 | 系列赛 / BP / 选手 / 约训 | `data/training.sqlite3` | 4 系列、12 局编组、11 条 BP |
| API | 主记录、详情、向量、系列赛 | `/api/*` | 386 向量 |

---

## 2. 对局主记录 `GET /api/matches`

`matches[]` 每项字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | string | 对局主键（`channel-…` / 归档 key） |
| `date` / `dateText` | string | 日期 `YYYY-MM-DD` |
| `startTime` | string | 开赛时钟快照，如 `11-10 22:45` |
| `duration` | number | 时长（秒） |
| `mode` | string | 模式，如 `排位赛 双排` |
| `title` | string | 来源标题（`采集通道` 等） |
| `source` / `sources` | string / array | 数据来源：`bundle` / `official` / `table` / `video` / `screenshot` |
| `opponent` / `opponentTeamId` | string | 对手名 / 对手实体 ID |
| `session` | string | 训练组 |
| `version` | string? | 版本（当前普遍为空） |
| `ownCamp` | `blue`\|`red` | 我方阵营 |
| `result` | `win`\|`loss`\|`na` | 胜负 |
| `scores` | object | `{left,right,blue,red}` 人头比分 |
| `players` | number | 十人人数（10） |
| `complete` | bool | 是否字段齐全 |
| `missing` | array | 缺失字段清单 |
| `warnings` | array | 数据质量警告 |
| `isSeed` | bool | 是否验证/种子数据 |
| `hasPov` / `hasScoreboard` / `hasTimeline` | bool | 是否有第一视角 / 结算面板 / 时间轴 |
| `heroes` / `lineup` / `own` / `enemy` | array | 双方英雄与阵容 |
| `goldDiff` | number? | 终局经济差 |

---

## 3. 单局详情 `GET /api/matches/{key}`

### 3.1 顶层

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` / `dbId` | string | 对局主键 / 库内 ID |
| `date` / `dateText` / `startTime` | string | 时间 |
| `duration` | number | 秒 |
| `mode` / `title` | string | 模式 / 标题 |
| `opponent` / `opponentTeamId` / `opponentNameSource` | string | 对手与对手名来源 |
| `ownCamp` / `ownSide` | `blue`\|`red` / `left`\|`right` | 我方阵营 / 边 |
| `result` / `winner` / `winnerCamp` | string | 胜负 |
| `scores` | object | `{blue,red,left,right}` |
| `teamTotals` | object | 双方汇总（见 3.4） |
| `players` | array | 十人面板（见 3.2） |
| `process` | object | 经济/击杀过程（见 3.3） |
| `bp` | object | 人工录入 BP（可能为空） |
| `campBp` | object | 营地解析 BP（见 5.1） |
| `draft` | object | 合并后的 BP（人工优先、营地兜底） |
| `bpFacts` | object | BP 统计事实 |
| `officialReplay` | object | 官方回放摘要（见 3.5） |
| `bundleKey` / `campBacked` / `campTilesSource` | string/bool | 数据包与营地面板来源 |
| `source` / `sources` / `status` / `warnings` | — | 来源与质量 |

### 3.2 `players[]`（十人面板）

| 字段 | 说明 |
|---|---|
| `playerId` / `label` / `rawLabel` | 选手 ID / 显示名 / 原始名 |
| `camp` / `side` / `slot` | `blue`\|`red` / `left`\|`right` / 1–10 槽位 |
| `position` / `hero` | 分路 / 英雄 |
| `kills` / `deaths` / `assists` / `kda` | 击杀 / 死亡 / 助攻 / KDA |
| `gold` / `damage` / `taken` / `healing` | 金币 / 输出 / 承伤 / 治疗 |
| `cs` / `jungleGold` / `control` / `towerDamage` | 补刀 / 野怪经济 / 控制 / 推塔伤害 |
| `participation` / `damageConversion` / `takenPerDeath` | 参团率 / 伤害转化 / 每死承伤 |
| `rating` / `result` | 评分 / 胜负 |
| `finalSource` / `partial` | 数据来源 / 是否补全 |
| `campTiles` | 营地面板指标卡（`name/key/group/raw/value/unit/note/hint/roles`） |
| `equipment` / `process` | 装备 / 个人过程（可能为空） |

### 3.3 `process`

| 字段 | 说明 |
|---|---|
| `timeline[]` | 经济序列：`{gameTime, blueGold, redGold, blueKills, redKills, goldDiff, source}`，约 30 秒一点 |
| `killEvents[]` | 击杀事件（有回放时） |
| `scoreboardSnapshots[]` | 结算快照（有回放时） |

### 3.4 `teamTotals` / `scores`

```
teamTotals = {
  blue: { players: 5, complete: true,
          totals: { kills, gold, damage, taken } },
  red:  { … }
}
```

### 3.5 `officialReplay`（API 摘要，不含完整事件）

| 字段 | 说明 |
|---|---|
| `id` / `kind` | 回放 ID / 类型（`personal` 等） |
| `winCamp` / `score` / `teamGold` | 胜方 / 比分 / 团队经济 |
| `goldPoints` | 经济点数量 |
| `events` | 事件数量 |
| `positions` | `{perSecond, pointsPerPlayer, file}` |
| `goldIntervalSecApprox` | 经济采样间隔（约 30 秒） |

完整事件与位置在 `data/official_replays/<id>/normalized.json`（见第 7 节）。

---

## 4. 跨局向量 `GET /api/cross/vectors`

一次取回全量局的轻量指标，供跨局分析（总览 / BP 与阵容 / 对线与运营 / 对手 / 系列赛）使用。
2026-11-15 起新增 `comp*` / `bans*` / `first` / `objAt10` / `fight.decided*` / `pl[].arch`，均为加法字段。

### 4.1 标识与范围

| 字段 | 说明 |
|---|---|
| `key` / `date` / `clock` / `order` | 主键 / 日期 / 开赛时钟 / 排序键 |
| `session` / `version` | 训练组 / 版本 |
| `opponent` / `opponentTeamId` | 对手 |
| `result` | `win`\|`loss`\|`na` |
| `duration` | 秒 |
| `camp` | 我方阵营 `blue`\|`red` |
| `hasReplay` | 是否有回放全景 |
| `ecoPoints` | 经济采样点数（0 = 只有面板） |

### 4.2 经济与节奏

| 字段 | 说明 |
|---|---|
| `at4` / `at10` | 4 / 10 分钟经济差（金币，缺采样为 null） |
| `finalDiff` | 终局经济差 |
| `seg` | `{early, mid, late}`：0–4 / 4–10 / 10 分钟后净增 |
| `g` | 按 5 分钟段的绝对经济差序列（长度 = `segments`） |
| `w` | 每 5 分钟净增序列 |
| `s` | 相对时长 6 点轨迹（0/20/40/60/80/100%） |
| `killsOwn` / `killsFoe` | 双方人头 |

### 4.3 资源 / 团战 / 打野

| 字段 | 说明 |
|---|---|
| `obj` | `{dragonOwn, dragonFoe, towerOwn, towerFoe}` 龙/塔 |
| `death` | `{own, foe}` 死亡数 |
| `fight` | `{n, win, decidedN, decidedWin}` 团战数 / 胜团数 / **有击杀团战数 / 胜团数**（胜率分母用后者） |
| `buff` | `{anti, stolen}` 反野 / 被反 |
| `cut` | `{n, first}` 切 C 次数 / 首杀 |
| `fk` | `{adv, even, dis, first, firstAgainst}` 各 `{n, win}` |
| `jungle` | `{crossSec, crossShare, firstCross, deepShare}` 打野过河 |
| `first` | `{bloodT, bloodSide, dragonT, dragonSide, dragonName, towerT, towerSide}` 一血/一龙/一塔；`side` 为 `own/foe/null` |
| `objAt10` | `{dragonOwn, dragonFoe, towerOwn, towerFoe}` 10 分钟前双方龙/塔数量 |

### 4.4 阵容与选手

| 字段 | 说明 |
|---|---|
| `heroes` / `heroesFoe` / `bans` | 我方 / 对方英雄 / 双方全部禁用 |
| `bansOwn` / `bansFoe` | 我方 ban / 对方 ban；`campBp.ownSide` 缺失时为 null，不猜边 |
| `compOwn` / `compFoe` | 阵容功能标签数组（双前排 / 强开团 / 保护链 / 清线转线 / 无前排）；无标签为 null |
| `lanes` | 每条路 `{gold, damage, taken}` 分均差 |
| `pl[]` | 十人：`{name, camp, pos, hero, arch, k, d, a, gpm, dpm, part}`；`arch` 为该分路打法类型 |

### 4.5 系列赛关联（2026-11-14 新增）

| 字段 | 说明 |
|---|---|
| `seriesId` / `bestOf` / `gameIndex` | 所属系列赛 / 赛制 / 局序 |
| `seriesStart` | 系列赛开赛日（按此做时间窗口，不切断 BO） |

未编组的局这些字段为 null。

---

## 5. BP 字段

### 5.1 营地 BP（`campBp` / `draft`）

| 字段 | 说明 |
|---|---|
| `bans` / `picks` | 按边 `{left, right}` 的英雄对象数组 |
| `banSlots` / `pickSlots` | **保留槽位**的数组：空 ban 为 null；按格式排程自动铺成逐手事件 |
| `banCount` | `{left, right}` ban 数 |
| `pickOrderKnown` | 名单数量与格式相符、已自动生成逐手事件后为 `true`；不足时 `false`，只做名单统计 |
| `firstPick` | 首抢方（`draft-18` / `draft-20` 固定蓝方先选） |
| `draftEvents` | 逐手事件；营地入库时按「每方名单 + 格式」自动生成，不再人工录入 |
| `heroMeta` / `lanes` | 英雄元信息 / 英雄分路 |
| `teamStats` / `winnerSide` / `ownSide` | 队伍统计 / 胜方 / 我方 |
| `gameSeq` / `mapName` / `duration` / `startTime` | 对局标识与时间 |

### 5.2 BP 三格式（`bp_formats`）

| 格式 | 用于 | Ban | Pick | 手数 |
|---|---|---|---|---|
| `draft-18` | 征召（训练赛/自定义）；KPL 2024 夏季赛及以前 | 2 + 2（第二轮红先） | 6 + 4 | 18 |
| `draft-20` | KPL 2024 年度总决赛起 | 2 + 3（第二轮红先） | 6 + 4 | 20 |
| `rank-20` | 排位 / 巅峰 | 5 + 5 同时 | 10 | 20 |

完整逐手排程、全局 BP、巅峰对决与元流之子口径见 `docs/bp_rules_v2.md`。

### 5.3 手序来源

赛后数据里每方名单就是最终手序，**不手工录入**：

1. 营地数据：`camp_sync` 入库时读取每侧 Ban/Pick 名单，按自动判定的格式
   （排位/巅峰 → `rank-20`；4 Ban → `draft-18`；5 Ban → `draft-20`）铺成
   `draftEvents`，并写 `ruleProfile=<format>`。
2. KPL 官方数据：`bp_list` 的逐手事件按记录格式保留；4 Ban 历史局按 `draft-18` 显示。
3. 名单数量与格式不符时只标 `orderPending=true`，不生成假顺序、不改写名单。
4. 旧 `bpOrder` / 手工顺序字段忽略；不再提供录入弹窗或写接口。

### 5.4 人工 BP 表（`bp`）

| 列 | 说明 |
|---|---|
| `match_key` | 对局 |
| `bans` / `picks` | 按边英雄 |
| `pick_order` | 人工录入手序（当前 11 行全空） |
| `first_pick` / `bp_coach` | 首抢 / BP 教练 |
| `comp_tags` | 阵容体系标签（当前全空） |
| `notes` | 备注 |

---

## 6. 系列赛

### 6.1 表 `training_series`

| 列 | 说明 |
|---|---|
| `id` / `best_of` | 系列赛 ID / BO3/5/7 |
| `status` | `confirmed` / `needs_review`（当前 4 组均为 needs_review） |
| `ruleset_id` | 规则集（`scrim-global-team`；KPL 固定全局 BP） |
| `opponent` / `opponent_team_id` | 对手 |
| `session` / `version` / `schedule_id` | 训练组 / 版本 / 约训 |
| `start_at` / `end_at` | 开赛 / 结束日期 |
| `completion_mode` / `completion` | `standard`\|`fixed` / `completed`\|`open`\|`interrupted`\|`incomplete` |
| `notes` / `created_at` / `updated_at` / `updated_by` | 备注与审计 |

### 6.2 表 `training_series_games`

`series_id` / `match_key` / `game_index` / `created_at`（当前 12 行）。

### 6.3 `GET /api/cross/series-summary`

```
{
  summary: {
    totals: { series, completed, seriesWins, seriesLosses, games, gameWins,
              seriesWinRate, gameWinRate },
    gameSequence: [{ gameIndex, n, wins, winRate, medianAt10, at10Samples, avgUsedUs }],
    afterLoss: { n, nextWins, nextWinRate, medianAt10Delta, deltaSamples },
    consumption: [{ gameIndex, avgUsedUs, avgUsedFoe, n }],
    attention: [{ seriesId, kind, title, detail, links, gameIndexes }]
  },
  series: [{
    id, bestOf, status, completion, completionMode, rulesetId, ruleset,
    opponent, session, version, startAt, endAt, score, notes, coverage,
    games: [{ matchKey, gameIndex, date, clock, result, at10,
              usedUsCount, usedFoeCount, changeLevel }]
  }],
  rulesets: [{ id, … }]
}
```

---

## 7. 回放全景 `normalized.json`（schema `camp-replay-v1`）

| 键 | 内容 |
|---|---|
| `schema` / `source` | 版本 / 来源（`api,eId,gameSeq,gameSvr,kind,mId,playerId,relaySvr,url`） |
| `match` | `durationSec, equipmentEvents, extendedEvents, goldIntervalSecApprox, goldPoints, keyEvents, score, teamGold, teams, winCamp` |
| `economy` | `{blue, red, diff, note}` |
| `events` | `{key[], extended[], equipment[]}` |
| `players[]` | `{playerId, camp, hero, heroId, kills, deaths, assists, ratings{grow,battle,survive,hurtHero,kda}}` |
| `battles` | `counts{fights,heroKills,fightRows,deathPoints}`、`deaths[]`、`fights[]`、`playerMap{}` |
| `positions` | `{perSecond, pointsPerPlayer, players:10, note, file}` |
| `warnings` | 覆盖与解析说明 |

事件字段：`eventType, timeSec, dtType, dtId, dtCamp, killerCamp, killerId, kills[{camp, killerId, hurtTotal}]`。

战斗字段：`deaths[{objID,camp,heroId,x,y,timeSec}]`；`fights[{fightId,startSec,endSec,firstKillerCamp,camp1,camp2,participants[{objID,camp,timeSec,beginner}]}]`；`playerMap{objID:{heroId,hero,kills,deaths,assists}}`。

位置：`positions.json` 结构为 `{schema, players[{playerId, points, posArr}]}`，`posArr = [[x, y], …]` 每秒一点（常见 600–1200 点）。

---

## 8. 营地原始详情 `data/camp_details/*.json`

```
data
├─ head: acntCamp, playerId, userId, roleId, roleName, heroId, heroName,
│        kda, killCnt, deadCnt, assistCnt, gameResult, gradeGame,
│        mapName, matchDesc, teamNum, is10v10
├─ battle: startTime, usedTime, mapName, gameType, dtEventTime
├─ blueTeam / redTeam: acntCamp, money, killCnt, deadCnt, assistCnt,
│        towerCnt, ldragon1/2, bdragon1/2/3, banCnt,
│        banHeros[], pickHeros[], gameResult, moneyTrend
└─ blueRoles / redRoles: [{
     basicInfo, battleRecords: { position, usedHero{heroId,heroName},
       posList, deathPosList, revivePosList, finalEquips, skill, skillUsed,
       highLight, inBattleObjid, teamFlag },
     battleStats, heroBehavior, recCards, dataBehavior, dataBehaviorV2 }]
```

赛后数据里每方 `banHeros` / `pickHeros` 名单就是最终手序。`camp_sync` 入库时按自动判定的格式（征召 18 / KPL 20 / 排位·巅峰 20）生成 `draftEvents`；不再使用 `bpOrder` 手工顺序。

---

## 9. 采集链路

### 9.1 `GET /api/channels`

`channels[]`：

| 字段 | 说明 |
|---|---|
| `id` / `entry` | 通道 ID / 采集入口 |
| `match` | `{date, durationSec, mode, opponent, ownSide, scores, session, version, winner}` |
| `saved` | 入库状态（`status`） |
| `review` | `{status, reviewedBy, reviewedAt, notes}` |
| `missing[]` | 缺失字段（`label/total/present` 口径） |
| `sourceStatus` | `{policyVersion, statuses{official,camp,table,video,screenshot,replay}, complete, counts}` |
| `coverage` / `changeLog` / `revision` | 覆盖、变更、修订 |
| `recordingIds` / `recordingShas` / `screenshotImageIds` | OCR 素材引用 |
| `updatedAt` | 更新时间 |

### 9.2 `GET /api/camp/sync`

`auth{authorized,nickname,userId,loginAt,expired,reason,code,invalidAt,checkedAt}`、`config.players[{nickname,campUserId}]`、`details[{gameSeq,mapName,gametime,startedAt,eventAt,battleType,winCamp,kda[],syncedAt}]`、`progress`、`result`、`running`、`error`、`backfill`、`finalize`。

---

## 10. 训练与关系表

| 表 | 关键列 | 现状 |
|---|---|---|
| `players` | `id, team_id, name, match_name, position, aliases, camp_user_id, role, revision, status, positions` | 0 行（结构已有） |
| `schedules` | `id, date, start_time, opponent_team_id, session, series_id, format, rules, version, status, notes, goals, review, review_status, attendance, competition_id` | 1 行，`goals` 空 |
| `match_records` | `match_key, date, session, series_id, game_no, mode, rules, version, own_team_id, enemy_team_id, own_side, winner, score, duration, reviewer, status, tags, notes, source, revision` | 11 行 |
| `bp` | 见 5.4 | 11 行，`pick_order`/`comp_tags` 全空 |

---

## 11. 覆盖与缺口（实测计数）

| 项 | 现状 | 影响 |
|---|---|---|
| 可分析对局 | 386 | 分析基数 |
| 有经济采样 | 330 / 386 | 过程类结论可用 |
| 有回放全景 / 位置 | 76 / 386 | 事件、分路、打野位置类只覆盖 20% |
| 官方回放目录 | 76 | 同上 |
| 版本 `version` | 0 / 386 有值 | 跨期对比暂不可用 |
| 训练组 `session` | 1 局有值 | 分训练组对比不可用 |
| 系列赛编组 | 4 组 BO3（12 局），全部 `needs_review` | S 系列结论只能标“未确认编组” |
| BP 手序 | `bp.pick_order` 0 行；`campBp.pickSlots` 有槽位 | 可按规则复原，需开关 |
| 阵容体系标签 `comp_tags` | 0 行 | 体系类分析只能靠英雄组合推断 |
| 选手档案 `players` | 0 行 | 选手身份、英雄池暂无 |
| 约训 `schedules` | 1 行，`goals` 空 | 训练目标追踪暂无数据 |

---

## 12. 命名与口径约定

- **阵营**：数据层用 `camp = blue|red`，BP/展示层用 `side = left|right`；`ownCamp`/`ownSide` 指我方。
- **经济差**：一律 `我方 − 对手`；负数 = 落后。`goldDiff` 在 timeline 里默认 `blue − red`，读取时需按 `ownCamp` 取符号。
- **时间**：`duration`、`timeSec`、`usedTime` 均为秒；`clock`/`gametime` 为 `MM-DD HH:mm` 文本。
- **at4 / at10**：只在有经济采样且时长足够（≥240 / ≥600 秒）时非 null，**不补 0**。
- **`g` / `w` / `s`**：`g` 为 5 分钟段绝对差，`w` 为段净增，`s` 为按比赛进度对齐的 6 点形状。
- **`pickOrderKnown`**：`true` 表示已按格式自动生成逐手顺序；营地名单数量与格式相符时为 `true`，不足时保持 `false` 并标 `orderPending`。
- **状态枚举**：系列赛 `status ∈ {confirmed, needs_review}`；`completion ∈ {completed, open, interrupted, incomplete}`；通道 `review.status` 为 `unreviewed` 等；`sourceStatus.statuses` 每类来源为 `completed/parsed/missing`。

---

## 13. 当前没有的字段（V4 需要，另行补齐）

| 字段 | 用途 | 状态 |
|---|---|---|
| 版本逐局标注 | 跨期 / 版本对比 | 待回填 |
| 赛前计划（主攻路、资源优先级、强势期、禁用优先级） | 执行 vs 计划 | 未建模 |
| 选手英雄池熟练度 | 英雄池瓶颈的“质量”约束 | 待 OCR/表格导入 |
| 选手身份 ID 映射 | 选手维度分析 | 表已有，数据待录 |
| 研究结果资产（发现/证据/反例/稳定性） | V4 规律库 | 未建模 |
