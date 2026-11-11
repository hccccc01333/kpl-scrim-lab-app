# KPL Scrim Lab 字段与功能规格（详细版）

- 版本：2026-11-06
- 范围：现有功能 + 新增 12 项分析（A1–A9、B1–B3）
- 口径：**王者营地 = 权威数据**；营地没有的字段不硬补，平台人工维护或标“不可用”。

---

## 0. 术语与状态

| 术语 | 含义 |
|---|---|
| 权威字段 | 王者营地原始字段，平台不二次推算 |
| 派生字段 | 平台基于权威字段计算，必须可复算、可标公式 |
| 人工字段 | 教练/平台维护：对手、训练组、版本、BP 手序、干预标签 |
| 合成字段 | 验证数据集使用，`synthetic=1`，不进入生产报告 |
| 覆盖 | `have / total`，按局或按人统计 |
| 缺失 | `null`，不参与计算，不插值、不填 0 |
| 时间精度 | 位置 1 Hz；经济约 30 秒；事件秒级；终局面板赛后 |

---

## 1. 字段字典

### 1.1 对局级字段（营地十人面板）

| 字段 ID | 中文名 | 营地路径 | 类型 | 单位/枚举 | 示例 | 覆盖 | 说明 |
|---|---|---|---|---|---|---|---|
| `match.result` | 本人胜负 | `head.gameResult` | bool | true/false | true | 32/32 | “本人这一局是否获胜” |
| `match.own_camp` | 本人阵营 | `head.acntCamp` | int | 1=蓝, 2=红 | 1 | 32/32 | 本队阵营，不是截图左右 |
| `match.team_result_blue` | 蓝方胜负 | `blueTeam.gameResult` | bool | true/false | true | 32/32 | 蓝方是否获胜 |
| `match.team_result_red` | 红方胜负 | `redTeam.gameResult` | bool | true/false | false | 32/32 | 红方是否获胜 |
| `match.start_time` | 开赛时间 | `battle.startTime` | str | `MM-DD HH:MM` | `11-02 12:59` | 32/32 | 营地不带年份 |
| `match.duration` | 时长 | `battle.usedTime` | int | 秒 | 661 | 32/32 | 终局时长 |
| `match.map_name` | 地图/模式 | `battle.mapName` | str | 文本 | `排位赛` | 32/32 | 不是游戏地图名，是模式 |
| `match.game_type` | 模式编码 | `battle.gameType` | int | 4=排位 | 4 | 32/32 | 需版本映射 |
| `match.blue_kills` | 蓝方击杀 | `blueTeam.killCnt` | int | 次 | 28 | 32/32 | 团队击杀 |
| `match.red_kills` | 红方击杀 | `redTeam.killCnt` | int | 次 | 7 | 32/32 | 团队击杀 |
| `match.blue_deaths` | 蓝方死亡 | `blueTeam.deadCnt` | int | 次 | 7 | 32/32 | 团队死亡 |
| `match.red_deaths` | 红方死亡 | `redTeam.deadCnt` | int | 次 | 28 | 32/32 | 团队死亡 |
| `match.blue_assists` | 蓝方助攻 | `blueTeam.assistCnt` | int | 次 | 58 | 32/32 | 团队助攻 |
| `match.red_assists` | 红方助攻 | `redTeam.assistCnt` | int | 次 | 6 | 32/32 | 团队助攻 |
| `match.blue_money` | 蓝方经济 | `blueTeam.money` | int | 金币 | 39838 | 32/32 | 团队总经济 |
| `match.red_money` | 红方经济 | `redTeam.money` | int | 金币 | 30533 | 32/32 | 团队总经济 |
| `match.blue_towers` | 蓝方推塔 | `blueTeam.towerCnt` | int | 座 | 7 | 32/32 | 推塔数 |
| `match.red_towers` | 红方推塔 | `redTeam.towerCnt` | int | 座 | 1 | 32/32 | 推塔数 |
| `match.blue_dragons` | 蓝方龙计数 | `blueTeam.ldragon1/ldragon2/bdragon1/bdragon2/bdragon3` | int | 条 | 1/0/0/1/0 | 32/32 | 五种龙分别计数 |
| `match.red_dragons` | 红方龙计数 | `redTeam.ldragon1/ldragon2/bdragon1/bdragon2/bdragon3` | int | 条 | 0/1/0/0/0 | 32/32 | 五种龙分别计数 |
| `match.ban_count` | 禁用数 | `blueTeam.banCnt` / `redTeam.banCnt` | int | 个 | 3 | 32/32 | 模式不同，数量不同 |

### 1.2 单局 BP 字段

| 字段 ID | 中文名 | 营地路径 | 类型 | 说明 |
|---|---|---|---|---|
| `bp.blue_bans` | 蓝方禁用 | `blueTeam.banHeros[]` | list | 终局名单，无手序 |
| `bp.red_bans` | 红方禁用 | `redTeam.banHeros[]` | list | 终局名单，无手序 |
| `bp.blue_picks` | 蓝方选用 | `blueTeam.pickHeros[]` | list | 终局名单，无手序 |
| `bp.red_picks` | 红方选用 | `redTeam.pickHeros[]` | list | 终局名单，无手序 |
| `bp.pick_order` | 选取手序 | 无 | list | 平台人工；未填不参与手序统计 |
| `bp.first_pick` | 一手方 | 无 | enum | 平台人工；left/right |
| `bp.bp_coach` | BP 教练 | 无 | str | 平台建档 |
| `bp.comp_tags` | 体系标签 | 无 | list | 平台人工/派生：强开/消耗/四保一/分带 |
| `bp.notes` | BP 备注 | 无 | str | 平台人工 |

### 1.3 选手级字段（`blueRoles[]` / `redRoles[]`）

#### 1.3.1 基础信息

| 字段 ID | 中文名 | 营地路径 | 类型 | 说明 |
|---|---|---|---|---|
| `player.id` | 营地角色 ID | `basicInfo.playerId` | str | 跨局稳定，可用于身份绑定 |
| `player.name` | 昵称 | `basicInfo.roleName` | str | 含零宽字符，需清洗 |
| `player.camp` | 阵营 | `basicInfo.acntCamp` | int | 1=蓝, 2=红 |
| `player.user_id` | 营地用户 ID | `basicInfo.userId` | str | 换号识别辅助 |
| `player.open_id` | openId | `basicInfo.openId` | str | 不对外展示 |
| `player.area_id` | 大区 | `basicInfo.areaId` | str | 同步辅助 |
| `player.server_id` | 服务器 | `basicInfo.serverId` | str | 同步辅助 |
| `player.is_me` | 是否本人 | `basicInfo.isMe` | bool | 取数账号本人 |
| `player.role_icon` | 头像 | `basicInfo.roleIcon` | str | 展示 |
| `player.hero_id` | 英雄 ID | `battleRecords.usedHero.heroId` | int | 英雄识别 |
| `player.hero_name` | 英雄名 | `battleRecords.usedHero.heroName` | str | 英雄分析 |
| `player.position` | 分路编码 | `battleRecords.position` | int | 0=对抗路,1=中路,2=发育路,3=打野,4=游走 |
| `player.in_battle_obj` | 战斗对象 ID | `battleRecords.inBattleObjid` | str | 关联回放 `playerMap` |
| `player.summoner_skill` | 召唤师技能 | `battleRecords.skill.skillName` | str | 可选分析 |
| `player.final_equips` | 终局装备 | `battleRecords.finalEquips[]` | list | 6 格，`equipId/equipName/equipIcon` |
| `player.skin` | 皮肤 | `battleRecords.usedSkin` | obj | 展示 |
| `player.team_num` | 队伍编号 | `battleRecords.teamNum` | int | 阵营辅助 |
| `player.team_flag` | 队伍标记 | `battleRecords.teamFlag` | str | 展示 |

> 注意：`battleRecords.posList`、`revivePosList`、`deathPosList`、`skillUsed` 在当前 32 局中均为空。位置、死亡、复活以营地官方回放为准，不从面板取。

#### 1.3.2 战斗统计（`battleStats`）

| 字段 ID | 中文名 | 营地路径 | 类型 | 单位 | 说明 |
|---|---|---|---|---|---|
| `stat.kills` | 击杀 | `battleStats.killCnt` | int | 次 | 终局 |
| `stat.deaths` | 死亡 | `battleStats.deadCnt` | int | 次 | 终局 |
| `stat.assists` | 助攻 | `battleStats.assistCnt` | int | 次 | 终局 |
| `stat.kda` | KDA | `battleStats.kda` | float | 比值 | 营地原值 |
| `stat.money` | 总经济 | `battleStats.money` | int | 金币 | 面板累计金币，含初始 300 |
| `stat.exp` | 经验 | `battleStats.exp` | int | 点 | 等级辅助 |
| `stat.level` | 等级 | `battleStats.heroLevel` | int | 级 | 终局等级 |
| `stat.cs` | 补刀 | `battleStats.killSoldier` | int | 刀 | 兵线补刀 |
| `stat.jungle_gold` | 野怪经济 | `battleStats.monsterCoin` | int | 金币 | 野区经济 |
| `stat.damage` | 总输出 | `battleStats.totalHurtCnt` | int | 伤害 | 含兵线/野怪 |
| `stat.hero_damage` | 对英雄输出 | `battleStats.totalHeroHurtCnt` | int | 伤害 | 分均输出优先用这个 |
| `stat.taken` | 总承伤 | `battleStats.totalBehurtCnt` | int | 伤害 | 含兵线/野怪 |
| `stat.hero_taken` | 对英雄承伤 | `battleStats.totalBeheroHurtCnt` | int | 伤害 | 对英雄承伤 |
| `stat.damage_conversion` | 伤害转化比 | `battleStats.hurtTransRate` | float | 比值 | 营地原值 |
| `stat.taken_per_death` | 每死承伤 | `battleStats.behurtPerDeath` | float | 伤害/次 | 营地原值 |
| `stat.participation` | 参团率 | `battleStats.joinGamePercent` | float | 0–1 | 营地原值 |
| `stat.healing` | 治疗量 | `battleStats.healCnt` | int | 治疗 | 辅助/回复 |
| `stat.control` | 控制时长 | `battleStats.ctrlTime` | int | 秒/原始值 | 控制效果 |
| `stat.tower_damage` | 对塔伤害 | `battleStats.buildingDamage` | int | 伤害 | 推塔贡献 |
| `stat.tower_kills` | 推塔数 | `battleStats.towerCnt` | int | 座 | 个人推塔 |
| `stat.rating` | 赛后评分 | `battleStats.gradeGame` | float | 分 | 营地评分 |
| `stat.mvp_score` | MVP 分数 | `battleStats.mvpScoreTth` | float | 分 | 营地评分 |
| `stat.mvp` | 是否 MVP | `battleStats.mvp` | bool/int | — | 展示 |
| `stat.god_like` | 超神次数 | `battleStats.godLikeCnt` | int | 次 | 可选 |
| `stat.triple_kill` | 三杀 | `battleStats.tripleKillCnt` | int | 次 | 可选 |
| `stat.ultra_kill` | 四杀 | `battleStats.UltraKillCnt` | int | 次 | 可选 |
| `stat.rampage` | 五杀 | `battleStats.rampageCnt` | int | 次 | 可选 |
| `stat.max_kills` | 最高击杀 | `battleStats.maxKill` | int | 次 | 单局最高 |
| `stat.max_damage` | 最高输出 | `battleStats.maxHurt` | int | 伤害 | 单局最高 |
| `stat.max_taken` | 最高承伤 | `battleStats.maxBehurt` | int | 伤害 | 单局最高 |
| `stat.max_assists` | 最高助攻 | `battleStats.maxAssist` | int | 次 | 单局最高 |
| `stat.max_towers` | 最高推塔 | `battleStats.maxTower` | int | 座 | 单局最高 |
| `stat.max_participation` | 最高参团 | `battleStats.maxJoinGamePercent` | float | — | 单局最高 |
| `stat.max_hero_damage` | 最高对英雄输出 | `battleStats.maxHeroHurt` | int | 伤害 | 单局最高 |
| `stat.max_hero_taken` | 最高对英雄承伤 | `battleStats.maxBeheroHurt` | int | 伤害 | 单局最高 |
| `stat.max_money` | 最高经济 | `battleStats.maxMoney` | int | 金币 | 单局最高 |
| `stat.max_control` | 最高控制 | `battleStats.maxCtrlTime` | int | — | 单局最高 |
| `stat.max_jungle_gold` | 最高野怪经济 | `battleStats.maxMonsterCoin` | int | 金币 | 单局最高 |
| `stat.max_damage_conversion` | 最高转化 | `battleStats.maxHurtTransRate` | float | — | 单局最高 |
| `stat.max_taken_per_death` | 最高每死承伤 | `battleStats.maxBehurtPerDeath` | float | — | 单局最高 |
| `stat.max_cs` | 最高补刀 | `battleStats.maxKillSoldier` | int | 刀 | 单局最高 |
| `stat.max_healing` | 最高治疗 | `battleStats.maxHealCnt` | int | 治疗 | 单局最高 |

> `battleStats` 还有 `evaluateIcon`、`sabc*`、`fightPower`、`oldMasterMatchScore` 等展示型字段，当前分析不使用。

### 1.4 回放过程字段

| 字段 ID | 中文名 | 路径 | 类型 | 精度 | 覆盖 | 说明 |
|---|---|---|---|---|---|---|
| `replay.win_camp` | 胜方阵营 | `normalized.match.winCamp` | str | 终局 | 22/22 | "1"/"2" |
| `replay.duration` | 时长 | `normalized.match.durationSec` | float | 秒 | 22/22 | 与面板可能差 1–2 秒 |
| `replay.team_gold_blue` | 团队经济序列（蓝） | `normalized.economy.blue[]` | list[int] | 约 30s | 22/22 | 长度 20–54 不等 |
| `replay.team_gold_red` | 团队经济序列（红） | `normalized.economy.red[]` | list[int] | 约 30s | 22/22 | 与 blue 可能不等长 |
| `replay.gold_diff` | 经济差序列 | `normalized.economy.diff[]` | list[int] | 约 30s | 22/22 | 蓝−红，按数组索引对齐 |
| `replay.gold_points` | 经济点数 | `normalized.match.goldPoints` | int | — | 22/22 | 与 diff 长度对应 |
| `replay.gold_interval` | 经济间隔 | `normalized.match.goldIntervalSecApprox` | int | 秒 | 22/22 | 约 30，不保证精确 |
| `replay.positions` | 逐秒坐标 | `positions.json` → `players[].posArr` | list[[x,y]] | 1 Hz | 22/22 | 仅回放有 |
| `replay.player_list` | 回放玩家 | `normalized.players[]` | list | — | 22/22 | `playerId/camp/hero/heroId/kills/deaths/assists/ratings/defeatAcntRatio` |
| `replay.fights` | 团战 | `normalized.battles.fights[]` | list | 事件级 | 22/22 | 含起止、参战、击杀、明细 |
| `replay.fight_participants` | 参战者 | `fights[].participants[]` | list | 秒 | 22/22 | `objID/camp/timeSec/beginner` |
| `replay.fight_kills` | 团战击杀 | `fights[].kills[]` | list | 秒 | 22/22 | `timeSec/killer/victim/killerCamp/victimCamp` |
| `replay.fight_details` | 团战明细 | `fights[].details[]` | list | 团战级 | 22/22 | `hurt/taken/heal/hardCtrl/softCtrl/lowHP/beginHP/endHP/ultimates` |
| `replay.fight_counts` | 团战人数 | `fights[].camp1/camp2` | int | — | 22/22 | 双方参战人数 |
| `replay.first_killer_camp` | 先手方 | `fights[].firstKillerCamp` | str | — | 22/22 | 首次击杀方 |
| `replay.deaths` | 死亡点 | `normalized.battles.deaths[]` | list | 秒 | 22/22 | `objID/camp/heroId/x/y/timeSec` |
| `replay.revive` | 复活时间 | `raw.reportData.playerPosInfo[].revivePosArr` | list | 秒 | 22/22 | 死亡窗口用 |
| `replay.events_key` | 关键事件 | `normalized.events.key[]` | list | 秒 | 22/22 | `dragontower/battle` |
| `replay.events_extended` | 扩展事件 | `normalized.events.extended[]` | list | 秒 | 21/22 | `killbuff` |
| `replay.events_equipment` | 装备事件 | `normalized.events.equipment[]` | list | 秒 | 5/22 | 购买时序 |
| `replay.player_map` | 对象映射 | `normalized.battles.playerMap` | dict | — | 22/22 | `objID → hero/camp/kills/deaths/assists` |

### 1.5 平台建档字段

| 字段 ID | 中文名 | 归属表 | 类型 | 必填 | 说明 |
|---|---|---|---|---|---|
| `team.id` | 战队 ID | `teams` | str | 是 | 稳定主键 |
| `team.name` | 战队名 | `teams` | str | 是 | 营地不提供 |
| `team.short_name` | 简称 | `teams` | str | 否 | 展示 |
| `team.aliases` | 别名/曾用名 | `teams` | list | 否 | 聚类合并 |
| `team.league` | 赛区/层级 | `teams` | str | 否 | KPL/次级/青训 |
| `team.coach` | 教练 | `teams` | str | 否 | **对方教练名字** |
| `team.analyst` | 分析师 | `teams` | str | 否 | 报告 |
| `team.status` | 状态 | `teams` | str | 是 | active/archived |
| `team.first_seen` | 首见日期 | `teams` | str | 否 | 新对手 |
| `team.parent_team_id` | 关联战队 | `teams` | str | 否 | 青训/二队 |
| `team.roster_version` | 阵容版本 | `team_roster_versions` | obj | 否 | 换人/换号 |
| `player.id` | 选手 ID | `players` | str | 是 | 稳定主键 |
| `player.team_id` | 所属战队 | `players` | str | 是 | 外键 |
| `player.name` | 比赛 ID/昵称 | `players` | str | 是 | 展示 |
| `player.match_name` | 真名/备注名 | `players` | str | 否 | 可选 |
| `player.position` | 默认分路 | `players` | str | 否 | 录入建议 |
| `player.aliases` | 小号/别名 | `players` | list | 否 | 换号合并 |
| `player.camp_user_id` | 营地 ID | `players` | str | 否 | 同步 |
| `player.role` | 主力/替补/试训 | `players` | str | 否 | 阵容评估 |
| `player.accounts` | 账号列表 | `player_accounts` | list | 否 | 一个选手多个账号 |
| `account.account_id` | 营地账号 ID | `player_accounts.account_id` | str | 是 | 唯一；映射到选手 |
| `account.is_primary` | 主号 | `player_accounts.is_primary` | bool | 否 | 展示 |
| `account.shared` | 共享账号 | `player_accounts.shared` | bool | 否 | 冲突标记 |
| `match.match_key` | 对局主键 | `matches` | str | 是 | `camp:<gameSeq>` |
| `match.date` | 日期 | `matches` | str | 是 | 可预填 |
| `match.session` | 训练组/大场 | `matches` | str | 否 | 人工/预填 |
| `match.series_id` | 系列赛 ID | `matches` | str | 否 | BO3/BO5 |
| `match.game_no` | 局序 | `matches` | int | 否 | 第几局 |
| `match.mode` | 模式 | `matches` | str | 否 | 训练赛/排位/自定义 |
| `match.rules` | 规则 | `matches` | str | 否 | 征召/全局BP/盲选 |
| `match.version` | 版本 | `matches` | str | 否 | 人工/预填 |
| `match.own_team_id` | 我方战队 | `matches` | str | 是 | 外键 |
| `match.enemy_team_id` | 对手战队 | `matches` | str | 是 | 外键 |
| `match.own_side` | 我方阵营 | `matches` | str | 是 | blue/red |
| `match.winner` | 胜方 | `matches` | str | 否 | 可预填 |
| `match.score` | 比分 | `matches` | json | 否 | 可预填 |
| `match.duration` | 时长 | `matches` | int | 否 | 可预填 |
| `match.reviewer` | 复盘人 | `matches` | str | 否 | 审核 |
| `match.status` | 状态 | `matches` | str | 是 | draft/confirmed/archived |
| `match.tags` | 标签 | `matches` | list | 否 | 正式/测试/验证 |
| `match.notes` | 备注 | `matches` | str | 否 | 复盘 |
| `roster.match_key` | 对局 | `match_rosters` | str | 是 | 外键 |
| `roster.team_id` | 战队 | `match_rosters` | str | 是 | 外键 |
| `roster.player_id` | 选手 | `match_rosters` | str | 是 | 外键 |
| `roster.account_id` | 本局账号 | `match_rosters` | str | 否 | 换号证据 |
| `roster.side` | 阵营 | `match_rosters` | str | 是 | blue/red |
| `roster.slot` | 槽位 | `match_rosters` | int | 是 | 1–5 |
| `roster.hero` | 英雄 | `match_rosters` | str | 否 | 本局英雄 |
| `roster.is_sub` | 是否替补 | `match_rosters` | bool | 否 | 阵容 |
| `roster.is_trial` | 是否试训 | `match_rosters` | bool | 否 | 评估 |
| `training.session_id` | 训练组 ID | `training` | str | 是 | 主键 |
| `training.goal` | 训练目标 | `training` | str | 是 | B3 |
| `training.intervention` | 干预措施 | `training` | str | 是 | B3 |
| `training.start_date` | 开始日期 | `training` | str | 是 | B3 |
| `training.end_date` | 结束日期 | `training` | str | 否 | B3 |
| `training.player_ids` | 适用选手 | `training` | list | 是 | B3 |
| `training.metric` | 指标 | `training` | str | 是 | B3 |
| `training.target` | 目标值 | `training` | float | 否 | B3 |
| `training.review` | 复盘结论 | `training` | str | 否 | 闭环 |
| `provenance.source` | 来源 | `provenance` | str | 是 | camp/replay/manual/synthetic |
| `provenance.confidence` | 置信度 | `provenance` | str | 是 | high/medium/low |
| `provenance.synthetic` | 是否合成 | `provenance` | int | 是 | 0/1 |
| `provenance.confirmed_by` | 确认人 | `provenance` | str | 否 | 教练 |
| `provenance.updated_at` | 更新时间 | `provenance` | real | 是 | 审计 |

### 1.6 派生指标公式

| 指标 | 公式 | 说明 |
|---|---|---|
| KDA | `(kills + assists) / max(1, deaths)` | 死亡为 0 时按 1 计，另标 `perfect` |
| GPM | `sum(gold) / sum(minutes)` | 聚合用总经济/总分钟，不是各场均值 |
| DPM | `sum(hero_damage) / sum(minutes)` | 优先 `totalHeroHurtCnt` |
| TPM | `sum(taken) / sum(minutes)` | 总承伤 |
| 经济占比 | `player.gold / team.gold * 100` | 仅同队 5 人齐全时计算 |
| 输出占比 | `player.hero_damage / team.hero_damage * 100` | 仅 5 人齐全 |
| 承伤占比 | `player.taken / team.taken * 100` | 仅 5 人齐全 |
| 参团率 | 优先 `joinGamePercent`；缺失用 `(kills+assists)/team_kills` | 团队击杀为 0 不计算 |
| 分均补刀 | `cs / minutes` | 完整终局才计算 |
| 经济差 | `blue_gold - red_gold` | 团队级 |
| 对位经济差 | 同分路 `own_gold - enemy_gold` | 双方各 1 人同分路才计算 |
| 掉点损失 | `own_sign * (start_blue - end_blue)` | 掉点窗口内团队经济差变化 |
| 经济差插值 | 按索引线性插值，四舍五入到 10 金币 | 30 秒采样，必须标“近似” |
| 团战伤害占比 | `player.hurt / sum(camp.hurt)` | 团战窗口内 |
| 团战承伤占比 | `player.taken / sum(camp.taken)` | 团战窗口内 |
| 控制占比 | `(hardCtrl+softCtrl) / sum(camp.control)` | 团战窗口内 |
| 大招使用 | `ultimates` 原值 | 次数/统计值，不是逐技能 CD |
| 路线相似度 | 重采样后欧氏/DTW 距离归一化 | 需坐标定标 |
| 孤立度 | 最近队友距离 > R 或 R 内队友数 = 0 | R 需地图定标 |
| 经济转折 | `|diff[t+window] - diff[t]| >= 阈值` | 候选事件，不归因 |
| 领先转化率 | `P(win | lead_at_10)` | 只算已知胜负 |

---

## 2. 现有功能字段矩阵

| 现有功能 | 粒度 | 必需字段 | 派生/公式 | 缺失处理 | 现有实现 |
|---|---|---|---|---|---|
| 比赛档案 | 局 | `head.gameResult`、`head.acntCamp`、`battle.startTime/usedTime`、双方 `killCnt/deadCnt/assistCnt/money` | 比分、胜负、时长 | 缺失显示“待补” | `analysis_data.py` |
| 比赛详情 | 局 + 10 人 | 上述 + `battleStats` + `usedHero` + `finalEquips` + `events` | 十人面板、经济曲线 | 缺失不补 0 | `studio_api.py` |
| 选手表现 | 人/局 | `battleStats` 全部数值字段、`usedHero`、`position`、`gameResult` | KDA/GPM/DPM/TPM/占比 | 缺字段不计算对应指标 | `studio_analysis.py` |
| 英雄表现 | 英雄/局 | `usedHero`、`position`、`battleStats`、`gameResult` | 出场、胜率、KDA | 样本不足只展示计数 | `analysis_data.py` |
| 团队复盘 | 队/局 | 双方 `money/towerCnt/ldragon*/bdragon*/gameResult`、`economy.diff` | 经济差、资源控制 | 缺时间轴不画曲线 | `depth_api.py` |
| BP 分析 | 局/队 | `banHeros/pickHeros`、`acntCamp`、`gameResult`、`banCnt` | 禁用率、选用率、胜率 | 无手序不做手序统计 | `bp_camp.py` |
| 对位分析 | 分路/局 | `position`、`usedHero`、`money/heroDamage/taken/cs/exp/level` | 对位经济差、KDA 差 | 分路缺失不计算 | `depth_api.py` |
| 热区/占位 | 秒/人 | `positions.posArr`、`camp/hero` | 密度、停留、分路占位 | 无位置不展示 | `depth_api.py` |
| 掉点分析 | 死亡事件 | `deaths.timeSec/x/y`、`revivePosArr`、`economy.diff`、`fights.kills` | 掉点窗口、经济损失 | 坐标/复活缺失跳过 | `depth_api.py` |
| 团战贡献 | 团战/人 | `fights.details`、`camp1/camp2`、`firstKillerCamp` | 伤害/承伤/控制占比 | 明细缺失跳过 | `depth_api.py` |
| 出装分析 | 人/局 | `finalEquips`、`events.equipment` | 终局装备、购买时序 | 无事件只做终局 | `depth_api.py` |
| 资源分析 | 事件/局 | `events.key/extended`、双方 `ldragon*/bdragon*/towerCnt` | 资源控制率、事件密度 | 事件缺失跳过 | `depth_api.py` |
| 节奏分析 | 分钟/局 | `economy.diff`、`events`、`fights.kills` | 分阶段经济差、事件密度 | 无过程不展示 | `depth_api.py` |
| 专题研究 | 人/局 | `battleStats` + `economy` + `events` + `gameResult` | 转化率、波动、组合 Lift | 样本不足返回空 | `studio_research.py` |
| 统计实验 | 人/局 | 全部数值 `battleStats` + 维度 + BP | 相关、聚类、PCA、回归 | 缺失列剔除 | `studio_analysis.py` |
| 对手档案 | 队/局 | 敌方 `playerId/roleName/usedHero/position/battleStats/gameResult` | 聚类、胜率、英雄池 | 无队名显示待命名 | `team_clusters.py` |
| 身份认领 | 人 | `basicInfo.playerId/roleName/acntCamp`、`usedHero`、`aliases` | 换号合并 | 未绑定保留昵称 | `identity_auto.py` |
| 训练重点 | 人/队/局 | `battleStats` 指标、日期/训练组、身份 | 目标达成率、近期均值 | 样本不足留空 | `focus.py` |
| 回放时间轴 | 秒/人 | 检查点金币/KDA/等级、`positions`、`equipmentEvents` | 时间轴、装备线 | 缺失显示 unknown | `replay_timeline_build.py` |

---

## 3. 新增功能详细规格

### A1 开局路线模式

**目标**：识别前 4 分钟常见移动路线、路线相似度与异常路线。

**输入**：
- `positions.json`：`players[].posArr`（1 Hz）、`playerId`、`camp`。
- `normalized.players[]`：`playerId/camp/hero`。
- 面板 `battleRecords.position`、`usedHero.heroName`、`basicInfo.acntCamp`。
- `normalized.match.durationSec`。

**连接键**：`game + camp + hero/playerId`；时间 `t` 秒。

**计算步骤**：
1. 取 `0 ≤ t ≤ 240` 的位置点；按 5 秒分箱，取箱内均值。
2. 坐标定标：按固定地图边界归一化到 `[0,1]`；未定标前使用相对坐标并标 `relative=true`。
3. 对每一路/每名选手，做 5 秒重采样序列。
4. 聚类：k-medoids，k 由 silhouette 在 3–6 中选；样本 < 10 局时不做聚类，只输出单局路线。
5. 相似度：与聚类中心做 DTW 距离，归一化到 0–100。
6. 异常路线：距离 > P90 + 1.5×IQR。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `game` | str | 对局 |
| `player` | str | 选手/英雄 |
| `camp` | str | 蓝/红 |
| `lane` | str | 分路 |
| `route_id` | str | 路线 ID |
| `cluster_id` | str | 簇 ID |
| `similarity` | float | 0–100 |
| `abnormal` | bool | 异常路线 |
| `sample_points` | int | 有效点数 |
| `gap_count` | int | >5 秒缺口感 |
| `relative` | bool | 是否相对坐标 |

**门槛**：前 4 分钟位置覆盖 ≥90%；≥10 局有位置；坐标定标完成。

**异常处理**：
- 缺失位置 → `available=false`。
- 缺口 >10 秒 → `partial=true`，不参与聚类中心。
- 未定标 → 只输出相对路线，标 `relative=true`。

**验收**：22 局可运行；同一选手不同局路线可比较；异常路线可下钻到原始坐标。

---

### A2 中野辅联动

**目标**：量化中/野/辅三人的集结、交汇、击杀前后支援。

**输入**：
- 三人 `positions.posArr`；分路来自 `battleRecords.position`（1=中路，3=打野，4=游走）。
- `fights[].kills[]`：`timeSec/killer/victim/killerCamp/victimCamp`。
- `fights[].startSec`。
- `playerMap` 做 `objID → hero/camp`。

**连接键**：`game + camp + hero`；时间 `t ±1s`。

**计算步骤**：
1. 取三人在每秒的位置；缺失点不插值。
2. 定义“集结”：三人两两距离均 ≤ R，持续 ≥ T 秒。R 建议为地图对角线的 15%，T=5 秒；定标前用相对 R。
3. 集结率 = 集结秒数 / 有效秒数。
4. 交汇次数 = 连续集结窗口数。
5. 击杀支援：对每次击杀，取击杀时刻击杀者/被击杀者位置作为锚点；回看 10 秒，计算三人到锚点的距离；统计进入 R 的人数和首次进入时间。
6. 团战参与：看三人是否在 `participants` 中。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `game` | str | 对局 |
| `camp` | str | 阵营 |
| `trio` | list | 中/野/辅选手 |
| `assembly_rate` | float | 集结率 % |
| `assembly_windows` | int | 集结窗口数 |
| `avg_pair_distance` | float | 平均两两距离 |
| `kill_support_rate` | float | 击杀有支援比例 |
| `avg_support_lag` | float | 平均首次进入 R 的秒数 |
| `trio_fight_participation` | float | 团战三人参与率 |

**门槛**：三人身份明确；位置覆盖 ≥80%；≥10 局；击杀时间 ±1 秒。

**异常处理**：
- 分路缺失 → `available=false`。
- 击杀无位置 → 跳过该次支援计算，计入 `missing_kills`。
- 位置缺口 → `partial=true`。

**验收**：能输出三人集结率、支援滞后；缺分路时明确不可用。

---

### A3 团战到位与人数差

**目标**：量化团战到位时间、先到方、人数差与击杀表现。

**输入**：
- `fights[]`：`fightId/startSec/endSec/camp1/camp2/firstKillerCamp`。
- `participants[]`：`objID/camp/timeSec/beginner`。
- `details[]`：`objID/camp/beginHP/endHP/kills/deaths/assists`。
- `kills[]`：`timeSec/killer/victim/killerCamp/victimCamp`。
- `playerMap`。

**连接键**：`game + fightId + objID`。

**计算步骤**：
1. 每位参战者：`arrival_lag = timeSec - startSec`；`beginner` 标先手。
2. 先到方：两阵营最小 `timeSec` 的比较；`first_arrival_diff = min(blue) - min(red)`。
3. 开局人数：`timeSec <= startSec + 3` 的人数；`adv_start = blue_count - red_count`。
4. 结束人数：`adv_end = camp1 - camp2`（营地原值）。
5. 击杀结果：按 `kills[]` 统计双方击杀；`kill_diff`；`fight_win = kill_diff > 0`。
6. 迟到：`timeSec > startSec + 5` 的参战者数量。
7. 聚合：按 `adv_start` 分桶统计团战胜率。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `game` | str | 对局 |
| `fight_id` | str | 团战 |
| `start/end` | float | 起止秒 |
| `duration` | float | 团战时长 |
| `participants` | int | 参战人数 |
| `arrival_lags` | list | 每人到位秒数 |
| `first_side` | str | 先到方 |
| `first_arrival_diff` | float | 先到差 |
| `adv_start` | int | 开局人数差 |
| `adv_end` | int | 结束人数差 |
| `kill_diff` | int | 击杀差 |
| `late_joins` | int | 迟到人数 |
| `fight_win` | bool | 击杀多者胜 |
| `beginner_side` | str | `beginner=1` 的阵营 |

**门槛**：≥30 场团战；参战时间非空；团战时长 ≥3 秒。

**异常处理**：
- 参战时间缺失 → 排除该参战者，不推断。
- 0 击杀团战 → 保留到位分析，`kill_diff=null`。
- 短团战 → 单列 `short=true`。

**验收**：能按人数差输出团战胜率；参战时间缺失时明确排除数量。

---

### A4 掉点孤立度

**目标**：判断死亡发生时是否处于相对孤立位置，并量化孤立死亡的经济代价。

**输入**：
- `battles.deaths[]`：`objID/camp/heroId/x/y/timeSec`。
- `positions.json`：死亡时队友坐标（±1 秒）。
- `raw.reportData.playerPosInfo[].revivePosArr`：复活时间。
- `economy.diff`。
- `fights.kills[]`：击杀者/团战关联。

**连接键**：`game + objID + timeSec`。

**计算步骤**：
1. 取死亡时刻 `t` 的死亡者坐标 `(x,y)`；取同阵营其他 4 人最近位置。
2. 计算最近队友距离 `nearest_dist`、半径 R 内队友数 `near_count`、队友两两平均距离 `spread`。
3. `isolated = nearest_dist > R` 或 `near_count == 0`；两个口径都输出。
4. 掉点窗口：`t → 下次复活`；无复活则到比赛结束，`final=true`。
5. 经济损失：`own_sign * (start_blue - end_blue)`，四舍五入到 10 金币。
6. 击杀关联：±5 秒内 `fights.kills` 的击杀者/团战 ID。
7. 聚合：孤立死亡率、孤立/非孤立平均损失、按分路/时间段拆分。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `game` | str | 对局 |
| `death_id` | str | 死亡事件 |
| `t` | float | 死亡秒 |
| `x/y` | float | 死亡坐标 |
| `camp` | str | 阵营 |
| `hero/player` | str | 英雄/选手 |
| `nearest_dist` | float | 最近队友距离 |
| `near_count` | int | R 内队友数 |
| `spread` | float | 队友分散度 |
| `isolated` | bool | 是否孤立 |
| `isolation_reason` | str | distance / no_teammate |
| `window_sec` | float | 掉点窗口 |
| `final` | bool | 是否终局未复活 |
| `gold_loss` | int | 经济损失 |
| `killer` | str | 击杀者 |
| `fight` | str | 团战 ID |

**门槛**：≥30 次死亡；坐标有效；队友位置覆盖 ≥80%；时间对齐 ±1 秒。

**异常处理**：
- 坐标缺失 → 跳过，计入 `missing_coords`。
- 死亡状态停留（连续相同坐标）→ 取死亡前最后一个有效点。
- 无复活 → `final=true`，窗口到比赛结束。
- 不做“失误”判断，只输出“孤立风险”。

**验收**：能输出孤立死亡比例；坐标缺失时明确跳过数量；孤立/非孤立经济损失可对比。

---

### A5 团战击杀链

**目标**：识别团战首次阵亡后的连续减员模式。

**输入**：
- `fights[]`：`fightId/startSec/endSec/camp1/camp2`。
- `kills[]`：`timeSec/killer/victim/killerCamp/victimCamp`。

**连接键**：`game + fightId`；按 `timeSec` 排序。

**计算步骤**：
1. 按 `timeSec` 排序击杀；相同时间按数组顺序，标 `ambiguous_order=true`。
2. `first_death_time = t[0] - start`。
3. `intervals = t[i] - t[i-1]`。
4. `sequence` = 每次击杀的阵营串，例如 `1,1,2,1`。
5. `max_consecutive` = 连续同阵营最大长度。
6. `pattern` = 终局击杀数，例如 `3-0`、`4-1`；一方 5 人全死标 `wipe`。
7. `trade` = 交替击杀标记。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `game` | str | 对局 |
| `fight_id` | str | 团战 |
| `start/end` | float | 起止 |
| `kills` | int | 击杀数 |
| `sequence` | list | 阵营序列 |
| `first_death_time` | float | 首死相对时间 |
| `intervals` | list | 击杀间隔 |
| `max_consecutive` | int | 最大连续减员 |
| `pattern` | str | `3-0` / `4-1` |
| `wipe` | bool | 是否团灭 |
| `trade` | bool | 是否交替 |
| `ambiguous_order` | bool | 同秒击杀 |

**门槛**：每场 ≥2 次击杀；≥30 场团战；击杀时间非空。

**异常处理**：
- 击杀为空 → 排除。
- 同秒击杀 → 标 `ambiguous_order=true`，不推断先后。
- 缺时间 → 排除该击杀并计数。

**验收**：能输出击杀链与减员模式；同秒击杀不伪造顺序。

---

### A6 团战消耗结构

**目标**：比较同英雄/同分路在不同团战中的资源使用结构。

**输入**：
- `fights[].details[]`：`hurt/taken/heal/hardCtrl/softCtrl/lowHP/beginHP/endHP/ultimates`。
- `playerMap`、面板 `position`。

**连接键**：`game + fightId + objID`。

**计算步骤**：
1. 每场团战按阵营汇总 `hurt/taken/heal/hardCtrl+softCtrl`。
2. 每人计算占比：`damage_share`、`taken_share`、`heal_share`、`control_share`。
3. `hp_loss = beginHP - endHP`；`damage_per_hp_lost = hurt / max(1, hp_loss)`。
4. `survived = endHP > 0`；`ultimates` 记原值。
5. 按英雄/分路聚合均值、中位数、样本数。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `game/fight_id` | str | 对局/团战 |
| `hero/camp/player` | str | 对象 |
| `hurt/taken/heal` | int | 原始值 |
| `hard_ctrl/soft_ctrl` | float | 控制 |
| `ultimates` | float | 大招统计值 |
| `begin_hp/end_hp` | float | 血量 |
| `damage_share` | float | 伤害占比 |
| `taken_share` | float | 承伤占比 |
| `heal_share` | float | 治疗占比 |
| `control_share` | float | 控制占比 |
| `damage_per_hp_lost` | float | 伤害/掉血 |
| `survived` | bool | 是否存活 |

**门槛**：明细完整；≥20 场/英雄或分路。

**异常处理**：
- 明细缺失 → 排除。
- HP 缺失 → 跳过 HP 指标，保留占比。
- `ultimates` 不当技能释放次数解释。

**验收**：能输出同英雄跨团战的结构差异；HP 缺失时明确跳过。

---

### A7 资源争夺空间

**目标**：分析资源事件发生前的双方聚集、到达顺序、争/放，以及事后经济变化。

**输入**：
- `events.key/extended[]`：`eventType/timeSec/dtType/dtId/dtCamp/killerCamp/killerId/kills[].hurtTotal/fightId/killCount`。
- `positions.json`。
- `economy.diff`。
- `playerMap`。

**事件类型**：当前样本只有 `dragontower`（`dtType` 1/2）、`battle`、`killbuff`。未知类型标 `unclassified`。

**计算步骤**：
1. 事件分类：`dragontower`、`battle`、`killbuff`、`unknown`。
2. 资源锚点：`killerId → playerMap → hero → 该秒位置`；无位置则 `anchor=null`。
3. 前置窗口 30 秒：统计双方在锚点 R 内的人数、到达顺序、首次到达方。
4. `contest = 双方均 ≥1 人`；`secure = 仅一方`。
5. 事后 60 秒：`gold_delta`、下一个事件类型/时间。
6. 对 `battle` 事件：用 `fightId` 关联团战，不重复计算资源锚点。
7. 对 `dragontower`：`dtCamp` 是建筑/资源所属方，`killerCamp` 是获取方，两者都保留。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `game/event_id` | str | 对局/事件 |
| `type` | str | 事件类型 |
| `t` | float | 事件秒 |
| `dt_type/dt_id` | str | 事件子类型 |
| `dt_camp` | str | 所属方 |
| `killer_camp` | str | 获取方 |
| `anchor_x/anchor_y` | float | 锚点坐标（近似） |
| `anchor_source` | str | killer_position |
| `own_near/enemy_near` | int | 30 秒内 R 内人数 |
| `contest` | bool | 是否争夺 |
| `first_side` | str | 先到方 |
| `gold_delta_60s` | int | 事后经济差变化 |
| `next_event` | str | 下一个事件 |
| `spatial` | bool | 是否有锚点 |

**门槛**：≥20 个事件；锚点位置可用；事件类型可映射。

**异常处理**：
- 无锚点 → `spatial=false`，只输出时间/经济。
- 事件无 x/y → 必须标“击杀者位置近似”，不冒充资源坐标。
- 未知事件 → `unclassified`，不参与聚合。

**验收**：能输出争夺率、先到方、事后经济差；无锚点时明确降级。

---

### A8 经济转折事件匹配

**目标**：为重大经济转折自动列出同期候选事件与局内时间点。

**输入**：
- `economy.diff/blue/red`、`durationSec`、`goldPoints`、`goldIntervalSecApprox`。
- `fights[].kills[]`。
- `events.key/extended[]`。

**连接键**：`game + t ± 60s`。

**计算步骤**：
1. 构建时间序列：`t_i = i * duration / max(1, n-1)`；标 `approx=true`。
2. 计算 30/60/120 秒窗口的 `Δdiff`。
3. 选 `|Δdiff| >= 阈值` 的窗口；阈值 = 1000 金币或 |Δ| 的 P90。
4. 对每个窗口，找 ±60 秒内的击杀、团战、资源、建筑事件。
5. 按时间距离和事件规模排序，输出候选列表。
6. 不选“唯一原因”，只列候选。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `game/swing_id` | str | 对局/转折 |
| `start/end` | float | 窗口 |
| `delta` | int | 经济差变化 |
| `direction` | str | blue/red |
| `candidates` | list | 候选事件 |
| `candidate.type` | str | kill/fight/objective/building |
| `candidate.t` | float | 事件秒 |
| `candidate.camp` | str | 阵营 |
| `candidate.magnitude` | float | 事件规模 |
| `approx` | bool | 经济点近似 |

**门槛**：≥20 个经济点；事件时间非空；30 秒分辨率。

**异常处理**：
- 序列长度不一致 → 按最短长度对齐，标 `length_mismatch=true`。
- 无事件 → 只输出转折，`candidates=[]`。
- 不宣称因果。

**验收**：能输出转折窗口与候选事件；长度不一致时明确标注。

---

### A9 优势兑现路径

**目标**：统计领先后拿资源、推塔、赢团、最终获胜的条件转化率。

**输入**：
- `economy.diff` 在 5/10/15 分钟的值（插值）。
- `events.key/extended`。
- `match.winCamp`、`durationSec`。

**计算步骤**：
1. 10 分钟经济差：`lead = diff@600`；分桶：落后/持平/领先 0–500/500–1500/>1500。
2. 10 分钟后事件序列：资源、推塔、团战。
3. 结局：`win = (winCamp == own_camp)`。
4. 转化率：`P(win | lead)`、`P(next objective | lead)`、`P(win | lead + next objective)`。
5. 路径频次：`lead → dragon/tower → win` 等序列计数。
6. 输出 Wilson 区间与样本数。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `game` | str | 对局 |
| `lead_at_10` | int | 10 分钟经济差 |
| `lead_bucket` | str | 分桶 |
| `next_objective` | str | 下一个资源 |
| `next_event` | str | 下一个事件 |
| `won` | bool | 是否获胜 |
| `path` | list | 事件路径 |
| `conversion` | float | 转化率 |
| `n` | int | 样本数 |
| `ci_low/ci_high` | float | Wilson 区间 |

**门槛**：胜负已知；10 分钟经济点可用；≥10 局。

**异常处理**：
- 缺 10 分钟点 → 排除。
- 胜负未知 → 排除。
- 样本 <10 → 只输出观察，不给转化率。

**验收**：能输出领先转化率与路径；样本不足时明确“样本不足”。

---

### B1 对手战术习惯画像

**目标**：对同一对手多局汇总 BP 偏好、选手英雄池、节奏与资源习惯。

**输入**：
- 敌方 `playerId/roleName/usedHero/position/battleStats`。
- `gameResult`、`startTime`。
- 平台 `teams`、`match_rosters`、`bp`。

**计算步骤**：
1. 对手聚类：5 人 `playerId` 签名；≥3 局才建画像。
2. BP 偏好：按阵营/版本统计 ban/pick 频率。
3. 选手英雄池：每人英雄出场与胜率。
4. 节奏：5/10/15 分钟经济差、资源计数、推塔数。
5. 阵容稳定性：5 人重合度、换人次数。
6. 输出置信度：局数、覆盖、身份确认状态。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `team_id/name/coach` | str | 对手 |
| `games` | int | 样本局数 |
| `side_pref` | obj | 蓝/红胜率 |
| `bp_pref` | list | 禁用/选用排行 |
| `player_pool` | list | 选手英雄池 |
| `tempo` | obj | 经济差/资源 |
| `roster_stability` | float | 阵容稳定度 |
| `confidence` | str | high/medium/low |

**门槛**：同一对手 ≥3 局；阵营/身份正确；对手名/教练已确认。

**异常处理**：
- <3 局 → “样本不足”，只列单局记录。
- 未命名 → `待命名对手 #N`。
- 教练缺失 → 留空，不猜测。

**验收**：mock 7 队可输出画像；32 个单局对手明确显示“样本不足”。

---

### B2 出装时序与收益

**目标**：统计核心装备成型时刻、购买顺序，以及成装后的团战表现。

**输入**：
- `battleRecords.finalEquips[]`。
- `events.equipment[]`（时间、装备 ID）。
- `fights.details[]`（成装后团战表现）。

**计算步骤**：
1. 终局装备：直接读 6 格。
2. 购买事件：按 `player + equip_id + time` 去重；按时间排序。
3. 核心装备：前 3 件成品或指定装备；输出成型时间。
4. 成装后团战：取装备时间之后的团战，统计 `hurt/taken/heal/ultimates`。
5. 前后对比：成装前 vs 成装后（同局内）。
6. 价格表可选；无价格不计算累计花费。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `game/player/hero` | str | 对象 |
| `final_equips` | list | 终局 6 格 |
| `purchases` | list | 购买事件 |
| `core_item_time` | float | 核心装时间 |
| `item_order` | list | 购买顺序 |
| `cost` | int | 仅价格表可用时 |
| `post_item_fights` | list | 成装后团战 |
| `timing` | bool | 是否有购买时序 |

**门槛**：装备事件覆盖 ≥80%；时间关联校验通过；价格表可选。

**异常处理**：
- 无装备事件 → `timing=false`，只输出终局装备。
- 时间对不上 → 标 `unlinked=true`，不硬拼。
- 不把 `.abc` 购买指令与营地数据未经验证直接拼接。

**验收**：5 局有事件的能输出时序；其余明确“仅终局装备”。

---

### B3 训练效果追踪

**目标**：把“训练措施 → 后续比赛 → 指标变化”连起来，输出前后对比与目标达成率。

**输入**：
- `battleStats` 指标。
- 稳定选手身份、日期/训练组。
- `training` 表：目标、干预、开始/结束、适用选手、指标、目标值、复测窗口。

**计算步骤**：
1. 按干预窗口切分 pre/post 比赛。
2. 计算指标均值、差值、Cohen's d、目标达成率。
3. 样本不足时只输出观察。
4. 可选：同位置/同训练组对照。
5. 不做因果归因，只描述前后变化。

**输出字段**：

| 字段 | 类型 | 说明 |
|---|---|---|
| `intervention_id` | str | 干预 |
| `player/metric` | str | 对象/指标 |
| `pre_mean/post_mean` | float | 前后均值 |
| `delta` | float | 差值 |
| `effect_size` | float | Cohen's d |
| `target_rate` | float | 目标达成率 |
| `n_pre/n_post` | int | 样本 |
| `confidence` | str | high/medium/low |

**门槛**：稳定身份；干预前后各 ≥5 局；干预标签明确。

**异常处理**：
- 样本不足 → “样本不足”。
- 无干预标签 → `available=false`。
- 训练组缺失 → 不做效果结论。

**验收**：合成干预可跑通前后对比；样本不足时明确提示。

---

## 4. 数据模型

```sql
CREATE TABLE teams (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  short_name TEXT,
  aliases TEXT NOT NULL DEFAULT '[]',
  league TEXT,
  coach TEXT,
  analyst TEXT,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  first_seen TEXT,
  parent_team_id TEXT REFERENCES teams(id),
  revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE team_roster_versions (
  id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL REFERENCES teams(id),
  name TEXT,
  player_ids TEXT NOT NULL DEFAULT '[]',
  start_date TEXT,
  end_date TEXT,
  is_current INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_roster_versions_team ON team_roster_versions(team_id);

CREATE TABLE team_relations (
  from_team_id TEXT NOT NULL REFERENCES teams(id),
  to_team_id TEXT NOT NULL REFERENCES teams(id),
  relation TEXT NOT NULL,          -- academy / sister / former / alias
  note TEXT,
  PRIMARY KEY(from_team_id, to_team_id, relation)
);

CREATE TABLE players (
  id TEXT PRIMARY KEY,
  team_id TEXT NOT NULL REFERENCES teams(id),
  name TEXT NOT NULL,
  match_name TEXT,
  position TEXT,
  aliases TEXT NOT NULL DEFAULT '[]',
  camp_user_id TEXT,
  role TEXT NOT NULL DEFAULT 'main',
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_players_team ON players(team_id);

CREATE TABLE player_accounts (
  id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL REFERENCES players(id),
  platform TEXT NOT NULL DEFAULT 'camp',
  account_id TEXT NOT NULL,
  nickname TEXT,
  camp_user_id TEXT,
  first_seen TEXT,
  last_seen TEXT,
  is_primary INTEGER NOT NULL DEFAULT 0,
  shared INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT 'manual',
  confidence TEXT NOT NULL DEFAULT 'medium',
  created_at REAL NOT NULL,
  UNIQUE(platform, account_id)
);
CREATE INDEX idx_accounts_player ON player_accounts(player_id);
CREATE INDEX idx_accounts_account ON player_accounts(account_id);

CREATE TABLE player_team_history (
  player_id TEXT NOT NULL REFERENCES players(id),
  team_id TEXT NOT NULL REFERENCES teams(id),
  start_date TEXT,
  end_date TEXT,
  source TEXT,
  PRIMARY KEY(player_id, team_id, start_date)
);

CREATE TABLE schedules (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  start_time TEXT,
  opponent_team_id TEXT REFERENCES teams(id),
  session TEXT,
  series_id TEXT,
  format TEXT,
  rules TEXT,
  version TEXT,
  status TEXT NOT NULL DEFAULT 'planned',
  notes TEXT,
  created_by TEXT,
  created_at REAL NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_schedules_date ON schedules(date);
CREATE INDEX idx_schedules_opponent ON schedules(opponent_team_id);

CREATE TABLE matches (
  match_key TEXT PRIMARY KEY,
  date TEXT,
  session TEXT,
  series_id TEXT,
  game_no INTEGER,
  mode TEXT,
  rules TEXT,
  version TEXT,
  own_team_id TEXT REFERENCES teams(id),
  enemy_team_id TEXT REFERENCES teams(id),
  enemy_cluster_id TEXT,
  schedule_id TEXT REFERENCES schedules(id),
  own_side TEXT,
  winner TEXT,
  score TEXT,
  duration INTEGER,
  reviewer TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  tags TEXT NOT NULL DEFAULT '[]',
  notes TEXT,
  source TEXT NOT NULL DEFAULT 'camp',
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_matches_date ON matches(date);
CREATE INDEX idx_matches_enemy ON matches(enemy_team_id);
CREATE INDEX idx_matches_session ON matches(session);

CREATE TABLE match_rosters (
  match_key TEXT NOT NULL REFERENCES matches(match_key),
  team_id TEXT NOT NULL REFERENCES teams(id),
  player_id TEXT NOT NULL REFERENCES players(id),
  account_id TEXT,
  side TEXT NOT NULL,
  slot INTEGER NOT NULL,
  hero TEXT,
  is_sub INTEGER NOT NULL DEFAULT 0,
  is_trial INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(match_key, team_id, player_id)
);
CREATE INDEX idx_rosters_match ON match_rosters(match_key);

CREATE TABLE bp (
  match_key TEXT PRIMARY KEY REFERENCES matches(match_key),
  bans TEXT NOT NULL DEFAULT '{}',
  picks TEXT NOT NULL DEFAULT '{}',
  pick_order TEXT NOT NULL DEFAULT '[]',
  first_pick TEXT,
  bp_coach TEXT,
  comp_tags TEXT NOT NULL DEFAULT '[]',
  notes TEXT
);

CREATE TABLE training (
  session_id TEXT PRIMARY KEY,
  goal TEXT NOT NULL,
  intervention TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT,
  player_ids TEXT NOT NULL DEFAULT '[]',
  metric TEXT NOT NULL,
  target REAL,
  review TEXT,
  revision INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE provenance (
  match_key TEXT NOT NULL,
  field TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'medium',
  synthetic INTEGER NOT NULL DEFAULT 0,
  confirmed_by TEXT,
  updated_at REAL NOT NULL,
  PRIMARY KEY(match_key, field)
);

CREATE TABLE prefill_fields (
  match_key TEXT NOT NULL,
  field TEXT NOT NULL,
  value TEXT,
  source TEXT NOT NULL,
  confidence TEXT NOT NULL,
  rule_version TEXT NOT NULL,
  generated_at REAL NOT NULL,
  synthetic INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(match_key, field)
);
CREATE INDEX idx_prefill_synthetic ON prefill_fields(synthetic);

CREATE TABLE change_log (
  id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,          -- match / team / player / session / version / training
  entity_id TEXT NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT,
  source TEXT NOT NULL,               -- manual / prefill / import / merge / undo
  actor TEXT,
  batch_id TEXT,
  reason TEXT,
  created_at REAL NOT NULL,
  undone_at REAL,
  undo_of TEXT,
  revision INTEGER NOT NULL
);
CREATE INDEX idx_change_entity ON change_log(entity_type, entity_id, created_at);
CREATE INDEX idx_change_batch ON change_log(batch_id);
CREATE INDEX idx_change_actor ON change_log(actor, created_at);

CREATE TABLE analysis_cache (
  cache_key TEXT PRIMARY KEY,
  analysis TEXT NOT NULL,
  scope_hash TEXT NOT NULL,
  input_revision INTEGER NOT NULL,
  payload TEXT NOT NULL,
  computed_at REAL NOT NULL,
  compute_ms INTEGER
);
CREATE INDEX idx_cache_analysis ON analysis_cache(analysis, input_revision);

CREATE TABLE workspace_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL
);
```

---

## 5. API 契约

### 5.1 覆盖审计

`GET /api/studio/coverage?analysis=death_isolation&game=<key>`

```json
{
  "analysis": "death_isolation",
  "game": "1793606215",
  "available": true,
  "sample": {"games": 22, "events": 770},
  "fields": {
    "deaths": {"present": 35, "required": true},
    "positions": {"present": 6930, "required": true, "hz": 1.0},
    "economy": {"present": 21, "required": true}
  },
  "checks": {"time_sync": true, "side_match": true, "coords_valid": true},
  "warnings": []
}
```

### 5.2 分析接口

`GET /api/studio/analysis/death_isolation?from=&to=&opponent=&position=`

```json
{
  "analysis": "death_isolation",
  "synthetic": false,
  "sample": {
    "games": 22,
    "events": 770,
    "confirmed": 0,
    "provisional": 32,
    "missing": 10
  },
  "rows": [],
  "coverage": {},
  "warnings": []
}
```

### 5.3 预填

`GET /api/studio/prefill?match=<key>`

```json
{
  "match_key": "camp:1793606215",
  "fields": {
    "opponent": {"value": "待命名对手 #3", "source": "derived:cluster", "confidence": "medium", "synthetic": 1},
    "session": {"value": "验证训练组 B", "source": "derived:session", "confidence": "low", "synthetic": 1},
    "version": {"value": null, "source": "placeholder", "confidence": "low", "synthetic": 1}
  }
}
```

`POST /api/studio/prefill/confirm`

```json
{
  "match_keys": ["camp:1793606215"],
  "fields": {"opponent": "青岚", "coach": "张教练"},
  "confirmed_by": "coach"
}
```

### 5.4 对手画像

`GET /api/studio/teams/<team_id>/profile`

```json
{
  "team": {"id": "team-xxx", "name": "青岚", "coach": "张教练"},
  "sample": {"games": 12, "confirmed": 12},
  "side_pref": {"blue": {"n": 6, "winRate": 50.0}, "red": {"n": 6, "winRate": 33.3}},
  "bp_pref": [],
  "player_pool": [],
  "tempo": {},
  "confidence": "medium",
  "warnings": []
}
```

### 5.5 训练效果

`GET /api/studio/training/<session_id>/effect?metric=dpm`

```json
{
  "intervention_id": "tr-001",
  "metric": "dpm",
  "pre_mean": 4200.0,
  "post_mean": 4600.0,
  "delta": 400.0,
  "effect_size": 0.42,
  "target_rate": 60.0,
  "n_pre": 6,
  "n_post": 5,
  "confidence": "low",
  "warnings": ["样本量小，仅描述前后变化"]
}
```

---

## 6. UI 规格

### 6.1 全局

- 顶部横幅：`验证模式 · 合成标签，不代表真实对手/训练组`（仅 `synthetic` 数据存在时）。
- 每个分析页顶部：`可用 22 局 · 缺失 10 局 · 合成 0 局`。
- 缺失原因可展开：`没有字段 / 字段为空 / 时间对不上 / 阵营对不上`。

### 6.2 待确认队列

> 详细页面、交互与采集联动见 **第 8 节 教练补录设计**。

- 入口：首页/录入页。
- 分组：对手、训练组、版本、BP 手序、选手身份、训练干预。
- 每行：对局、字段、当前值、来源、置信度、操作。
- 操作：内联编辑、确认、批量确认、忽略。
- 空态：`当前没有待确认字段`。

### 6.3 对手画像页

- 头部：战队名、简称、教练、样本局数、置信度。
- 区块：BP 偏好、选手英雄池、节奏、资源、阵容稳定度。
- 样本 <3 局：显示“样本不足”，只列单局记录。
- 未命名：显示 `待命名对手 #N`，提供改名/合并。

### 6.4 训练效果页

- 选择干预、选手、指标。
- 前后均值卡、效应量、目标达成率、样本数。
- 样本不足：黄色提示，不显示高置信结论。
- 口径说明：`描述性前后对比，不宣称因果`。

### 6.5 分析详情

- 每个数字可下钻到原始对局/事件。
- 每个图表显示 `n`、时间范围、来源。
- 缺失显示 `—`，不显示 0。

---

## 7. 预填与验证数据

### 7.1 预填优先级

`confirmed > prefill > empty`

### 7.2 预填规则

> 教练如何确认、修改、批量应用见 **第 8 节**。

| 字段 | 规则 | 来源 | 置信度 |
|---|---|---|---|
| 日期/开赛时间 | `battle.startTime` | auto:camp | high |
| 时长 | `battle.usedTime` | auto:camp | high |
| 我方阵营 | `head.acntCamp` | auto:camp | high |
| 胜负 | `head.gameResult` | auto:camp | high |
| 比分 | 双方 `killCnt` | auto:camp | high |
| 对手 | 阵容签名 → `待命名对手 #N` | derived:cluster | medium |
| 训练组 | 日期 + 90 分钟间隔 | derived:session | low |
| 选手身份 | 昵称/营地 ID 匹配 | derived:identity | medium |
| BP 名单 | `banHeros/pickHeros` | auto:camp | high |
| 终局装备 | `finalEquips` | auto:camp | high |
| 版本 | 空 → 待确认 | placeholder | low |
| BP 手序 | 空 → 未记录 | placeholder | low |
| 训练干预 | 空模板 | placeholder | low |

### 7.3 验证数据集

> 验证模式下的补录仍走第 8 节同一套队列，只是值标记为 `synthetic=1`。

- 独立库：`data/validation.sqlite3`，`TRAINING_DB` 指向它。
- 本队 5 人：按分路把 32 局我方昵称映射到 5 个稳定 ID（`settings.aliases`）。
- 对手：32 个 cluster → `验证对手 #1..#32`；B1 用 mock 7 队。
- 训练组：6 个时间组 → `验证训练组 A-F`。
- 版本：按日期 → `验证版本 A/B/C`。
- BP 手序：部分合成，部分留空。
- 训练干预：2–3 条合成干预。
- 装备时序：5 局有事件，其余不可用。
- 所有合成数据 `synthetic=1`，导出默认排除。

---

## 8. 教练补录设计

### 8.1 设计原则

1. **能自动推断的绝不手填**：日期、时长、阵营、胜负、比分、BP 名单、终局装备、对手 cluster、训练组猜测、选手身份猜测全部预填。
2. **能批量绝不逐局**：同一训练组、同一对手、同一版本，一次设置，批量应用。
3. **能后补绝不阻塞采集**：采集/保存不因缺字段失败；缺字段只影响对应分析，页面明确提示。
4. **只补营地没有的**：队名、教练、训练组、版本、BP 手序、训练干预；营地已有的字段不重复问。
5. **预填不是确认**：所有预填带 `source / confidence / synthetic`；教练确认后才算 `confirmed`。
6. **不编造**：不确定就留空或选“未知”，不强行填默认值。
7. **可撤销**：批量修改、合并、绑定都支持撤销与审计。

### 8.2 教练要补的字段

| 层级 | 字段 | 必填 | 影响分析 | 补录时机 | 补录方式 |
|---|---|---|---|---|---|
| 建档 | 战队名 / 简称 / 别名 / 层级 | 是（报告/对手画像） | 报告、对手画像 | 首次使用 | 向导表单 |
| 建档 | 我方教练 / 分析师 | 否 | 报告抬头 | 首次使用 | 向导表单 |
| 建档 | 选手名单 / 位置 / 营地 ID / 别名 / 角色 | 是（选手分析） | 选手分析、换号合并 | 首次使用，后续可改 | 名单表格、粘贴导入 |
| 建档 | 对手战队名 / 教练 / 别名 | 是（B1） | 对手画像、报告 | 首次遇到该对手 | 对手卡片命名 |
| 每局 | 对手 | 是（B1/筛选） | 对手画像、筛选 | 导入后 | 预填 cluster + 教练改名 |
| 每局 | 训练组 / 大场 / 局序 | 是（B3） | 训练组汇总、训练效果 | 导入后/批量 | 预填时间组 + 批量改名 |
| 每局 | 版本 / 补丁 | 是（版本趋势） | 版本趋势、英雄优先级 | 导入后/批量 | 下拉选择 + 批量应用 |
| 每局 | 比赛规则（征召/全局BP/盲选） | 否 | BP 可比性 | 导入后/批量 | 下拉选择 |
| 每局 | BP 手序 / 一手方 | 否 | BP 手序统计 | 复盘时 | 拖拽/按序点选 |
| 每局 | 比赛标签 | 否 | 筛选、排除验证数据 | 导入后 | 标签选择 |
| 每局 | 备注 / 复盘结论 | 否 | 复盘检索 | 复盘时 | 文本 |
| 每局 | 复盘人 / 审核人 | 否 | 审核记录 | 审核时 | 选择/输入 |
| 每训练组 | 训练目标 | 是（B3） | 训练效果 | 训练计划 | 表单 |
| 每训练组 | 干预措施 | 是（B3） | 训练效果 | 训练计划 | 表单 |
| 每训练组 | 开始/结束日期、适用选手 | 是（B3） | 训练效果 | 训练计划 | 表单 |
| 每训练组 | 指标 / 目标值 / 复测窗口 | 是（B3） | 训练效果 | 训练计划 | 表单 |
| 按需 | 对手风格 / 强弱档位 | 否 | 对手画像 | 首次遇到 | 标签/下拉 |
| 按需 | 录像 / 回放链接 | 否 | 证据链 | 导入后 | 链接输入 |

### 8.3 补录时机与入口

| 时机 | 入口 | 目标 | 交互 |
|---|---|---|---|
| 首次使用 | `#setup` 建档向导 | 战队、名单、营地授权、历史导入 | 5 步向导，可跳过 |
| 每次导入后 | `#pending` 待确认队列 | 确认预填、补关键字段 | 逐项确认/批量确认 |
| 打开单局 | 比赛详情侧栏“本局信息” | 修正单局字段 | 内联编辑 |
| 同一训练组/对手 | 批量操作条 | 一次改多局 | 多选 + 统一设置 |
| 制定训练计划 | `#training` 训练档案 | 目标、干预、复测 | 表单 |
| 维护主数据 | `#setup` / `#profile` | 战队、选手、教练、别名 | 表格编辑 |
| 查看分析时 | 分析页“缺字段”提示 | 即时补齐阻塞项 | 抽屉/弹窗 |

### 8.4 完整流程

```text
营地同步 / 截图 / 表格 / 回放导入
        ↓
自动预填（日期、时长、阵营、胜负、比分、BP、装备、
          对手 cluster、训练组猜测、选手身份猜测）
        ↓
生成待确认项（只对空字段 / 低置信度字段）
        ↓
待确认队列（按影响分析排序）
        ↓
教练逐项确认 / 修改 / 忽略
        ↓
完成度检查（P0 必填是否齐全）
        ↓
分析可用（A 类立即可用；B1/B3 需 confirmed）
```

状态机：

```text
imported → prefilled → reviewing → confirmed → analysis_ready
                ↘ partial（缺非阻塞字段，分析可跑但标“待确认”）
```

### 8.5 前端页面与组件

#### 8.5.1 首次建档向导 `#setup`

5 步，顶部进度条，允许“稍后再说”：

1. **战队信息**：队名、简称、层级、教练、分析师。
2. **选手名单**：昵称、位置、营地 ID、别名、角色（主力/替补/试训）；支持从剪贴板批量粘贴。
3. **营地授权**：扫码；显示授权状态与失效时间。
4. **历史导入**：选择日期范围；预览将导入多少局、可预填多少字段。
5. **预填确认**：显示“已预填 32 局 / 3 个对手待命名 / 16 个选手待绑定”；提供“一键确认高置信度”。

```text
┌ 建档向导  2/5 ─────────────────────────┐
│ 选手名单                                │
│ ┌────────┬──────┬──────┬────────────┐  │
│ │ 昵称   │ 位置 │ 营地ID│ 别名       │  │
│ │ 辰     │ 对抗 │ 1234 │ 小辰,辰辰  │  │
│ └────────┴──────┴──────┴────────────┘  │
│ [＋ 添加] [粘贴导入]                     │
│                          [上一步] [下一步]│
└────────────────────────────────────────┘
```

#### 8.5.2 待确认队列 `#pending`

```text
┌ 待确认 12 局 ──────────────────────────────┐
│ 影响：对手画像、训练效果                    │
│ [全部] [仅 P0] [本训练组] [对手] [版本]     │
├────────────────────────────────────────────┤
│ 11-02 13:15  vs 待命名对手 #3              │
│  对手   [青岚________] 推断·中   [确认]     │
│  训练组 [11-02 下午__] 推断·低   [确认]     │
│  版本   [B ▾]         待确认     [确认]     │
├────────────────────────────────────────────┤
│ 11-02 13:32  vs 待命名对手 #4              │
│  ...                                        │
├────────────────────────────────────────────┤
│ [批量设置] [确认高置信度] [稍后处理]        │
└────────────────────────────────────────────┘
```

行为：

- 按“影响分析”排序：对手 > 训练组 > 版本 > BP 手序 > 备注。
- 每行显示当前值、来源徽章、置信度、影响的分析。
- 支持单行确认、批量确认、忽略、撤销。
- 过滤：仅 P0、仅本训练组、仅某对手、仅有缺失。
- 空态：`当前没有待确认字段`。

#### 8.5.3 单局补录

比赛详情右侧“本局信息”卡片：

```text
┌ 本局信息 ───────────────────┐
│ 日期   2026-11-02   [编辑]  │
│ 对手   青岚          [编辑]  │
│ 训练组 11-02 下午    [编辑]  │
│ 版本   B             [编辑]  │
│ 规则   全局BP        [编辑]  │
│ 复盘人 张教练        [编辑]  │
│ 影响：对手画像 ✓ / 版本趋势 ✓│
└────────────────────────────┘
```

- 内联编辑，保存后立即重算分析。
- 每个字段旁显示来源：`自动` / `推断` / `待确认` / `已确认` / `合成`。
- 修改后出现“撤销”提示，保留 10 秒。

#### 8.5.4 对手命名/合并

```text
┌ 待命名对手 #3 ─────────────────────────┐
│ 5 名选手：A / B / C / D / E            │
│ 1 局 · 11-02 13:15                      │
│ 队名 [青岚________] 教练 [张教练____]   │
│ [保存并应用到 1 局] [合并到…]           │
└────────────────────────────────────────┘
```

- 阵容签名稳定，改名/合并只写覆盖层，历史对局全量生效。
- 3–4 人重合给“建议合并”，必须人工确认。
- 合并前预览：将影响多少局、是否有冲突。
- 支持撤销合并。

#### 8.5.5 选手绑定/换号

```text
┌ 待绑定昵称（16）───────────────────────┐
│ 昵称       营地ID   场次  建议           │
│ 辰辰       1234     5     辰（对抗路）   │
│ 小辰       5678     3     辰（对抗路）   │
│ [绑定到…] [新建选手] [设为别名]          │
└────────────────────────────────────────┘
```

- 同一选手多个账号：用“设为别名”合并，不新建。
- 同局两个昵称不能绑定到同一选手（防误并）。
- 绑定后显示“已合并 5 局”，可撤销。

#### 8.5.6 训练干预

```text
┌ 新建训练干预 ──────────────────────────┐
│ 目标     [提升 10 分钟经济差________]   │
│ 干预     [每日复盘 + 对线专项________]  │
│ 开始/结束 [2026-11-01] — [2026-11-07]  │
│ 适用选手 [辰] [野] [中]                  │
│ 指标     [10 分钟经济差 ▾] 目标值 [500] │
│ 复测窗口 [7 天 ▾]                        │
│ 将对比：干预前 5 局 / 干预后 5 局        │
│                          [保存] [取消]   │
└────────────────────────────────────────┘
```

- 保存后自动匹配前后比赛；样本不足时提示“还差 N 局”。
- 不做因果结论，只做前后对比。

#### 8.5.7 分析页即时补录

分析页顶部：

```text
┌ 对手画像暂不可用 ───────────────────────┐
│ 还缺：对手名称、对手教练、3 局以上样本   │
│ [去补录] [查看已有单局记录]              │
└─────────────────────────────────────────┘
```

- 点击“去补录”打开抽屉，只显示阻塞该分析的字段。
- 补完后原地刷新，不跳页。

#### 8.5.8 完成度与来源徽章

| 徽章 | 含义 | 颜色 |
|---|---|---|
| `自动` | 营地直接取数 | 蓝 |
| `推断` | 平台推断（cluster/session/identity） | 青 |
| `待确认` | 预填但未确认 | 黄 |
| `已确认` | 教练确认 | 绿 |
| `合成` | 验证数据 | 灰紫 |
| `缺失` | 无数据 | 红 |

### 8.6 交互细节

- **一键确认高置信度**：只确认 `confidence=high` 且 `source=auto` 的字段，低置信度逐项过。
- **只改不确定项**：队列默认过滤为 `待确认`，已确认字段折叠。
- **未知选项**：每个字段提供“未知/不记录”，不强制填。
- **自动保存**：输入即存草稿，离开页面不丢。
- **批量预览**：批量修改前显示“将影响 N 局”，支持撤销。
- **键盘优先**：Tab 切换字段，Enter 确认，Esc 取消。
- **移动端**：待确认队列用底部抽屉，单列卡片，大按钮。
- **错误提示**：指出具体字段和修复方式，不弹笼统“保存失败”。

### 8.7 与数据采集的搭配

#### 8.7.0 各采集方式与补录的关系

| 采集方式 | 能自动带入的字段 | 仍需教练补的字段 | 预填触发点 |
|---|---|---|---|
| 营地同步（十人面板） | 日期、时长、阵营、胜负、比分、BP 名单、终局装备、10 人昵称/英雄/分路/统计 | 对手队名、对手教练、训练组、版本、规则、BP 手序、标签、备注 | 同步完成、通道关联营地后 |
| 营地官方回放 | 位置、经济序列、团战、死亡、资源事件、胜方 | 同上；空间分析不需要额外补录 | 回放导入/构建完成后 |
| 赛后截图 | 截图日期、比分；OCR 候选的 10 人数据 | 对手、训练组、版本、规则、选手绑定、人工核对 | 截图识别完成、保存到通道后 |
| 表格导入 | 表头能映射的日期/对手/训练组/版本/选手/统计 | 无法映射的列、身份绑定、对手确认 | 列映射确认后 |
| 录屏 OCR | 时间轴、记分板快照、部分 KDA/经济 | 对手、训练组、版本、选手绑定、终局确认 | 抽帧识别完成后 |
| 回放文件 `.abc` | 英雄、评分、版本/构建、部分购买指令 | 对手、训练组、版本、BP 手序、身份绑定 | 解析完成后（仅辅助，不作权威） |

**原则**：同一局无论从哪条路进来，元数据只问一次；后到的来源只补证据，不重复问教练。

#### 8.7.1 采集入口

- 建局只要求最小信息：日期、对手（可空）、训练组（可空）。
- 营地同步成功后，用营地字段自动回填：日期、时长、阵营、胜负、比分、BP、终局装备。
- 截图/录屏/表格/回放只补充证据，不重复问同一局的元数据。

#### 8.7.2 导入后自动预填

导入完成即触发 `auto_prefill(match_key)`：

1. 营地字段 → `source=auto:camp`。
2. 对手 → `team_clusters` 签名 → `待命名对手 #N`，`source=derived:cluster`。
3. 训练组 → 日期 + 90 分钟间隔，`source=derived:session`，`confidence=low`。
4. 选手身份 → 名单昵称/营地 ID 匹配，`source=derived:identity`。
5. 版本、BP 手序、训练干预 → `placeholder`，不猜。
6. 只对空字段生成待确认项，不覆盖已有 manual 值。

#### 8.7.3 审核/保存

- **不阻塞**：缺可选字段仍可保存草稿/确认，但页面显示“哪些分析不可用”。
- **P0 必填**：日期、我方阵营、胜负、双方选手名单；缺失时不允许标记“已确认”，可保存草稿。
- **P1 建议**：对手、训练组、版本；缺失只影响对应分析。
- 保存后刷新完成度徽章和分析可用性。

#### 8.7.4 批量导入

- 按日期/训练组/对手分组预览。
- 支持“把这一组设为 11-03 晚训 · B 版 · 全局BP”。
- 批量应用前显示影响局数；应用后可撤销。
- 表格/截图批量导入复用同一套分组逻辑，不逐局重复填。

#### 8.7.5 重新导入/更新

- 幂等：以 `match_key`/`camp gameSeq` 为准。
- 只更新 `source=auto:camp` 的字段；manual/confirmed 永远优先。
- 显示 diff：哪些字段变了、哪些被保留。
- 不因为重新导入丢失教练补录。
- 变更后的全局传播、历史与撤销见 **第 9 节**；容量与性能见 **第 10 节**。

#### 8.7.6 备份/恢复

- 备份包含 `teams / players / matches / match_rosters / bp / training / provenance / prefill_fields`。
- 恢复按 ID 去重，不覆盖本机 manual 值。
- 验证数据（`synthetic=1`）默认不进入生产备份。

#### 8.7.7 数据质量看板

```text
字段覆盖         已确认 / 总局数
对手             20 / 32
训练组           12 / 32
版本             0 / 32
BP 手序          8 / 32
选手身份         32 / 32
```

- 点字段跳到待确认队列，自动带上过滤条件。
- 每个分析显示“可用局数 / 缺失局数 / 缺失原因”。

### 8.8 状态、权限与审计

| 状态 | 含义 | 可编辑 |
|---|---|---|
| `imported` | 刚导入，未预填 | 系统 |
| `prefilled` | 已预填，待教练确认 | 教练/分析师 |
| `reviewing` | 教练正在补录 | 教练/分析师 |
| `confirmed` | P0 字段齐全并确认 | 只读（可改后重新确认） |
| `analysis_ready` | 分析可用 | 只读 |

权限：

- 教练/分析师：编辑、批量、确认。
- 复盘人：确认自己负责的局。
- 选手：只读（选手端上线后）。
- 管理员：合并、删除、恢复。

审计：

- 每次修改写 `provenance`：`field / old / new / source / confirmed_by / updated_at`。
- 批量操作记一条批次 ID，可整体撤销。
- 合并/绑定保留历史，不物理删除。
- 完整的 `change_log`、撤销/重做与冲突处理见 **9.5 / 9.6**。

### 8.9 API

```text
GET    /api/studio/setup/status
POST   /api/studio/setup/team
POST   /api/studio/setup/roster
GET    /api/studio/pending?scope=all|match|session|opponent&priority=P0
PATCH  /api/studio/pending/{match_key}
POST   /api/studio/pending/batch
POST   /api/studio/pending/confirm
POST   /api/studio/opponents/{cluster_id}/rename
POST   /api/studio/opponents/{cluster_id}/merge
POST   /api/studio/players/{player_id}/alias
GET    /api/studio/training
POST   /api/studio/training
GET    /api/studio/coverage/summary
```

`PATCH /api/studio/pending/{match_key}`：

```json
{
  "fields": {
    "opponent": "青岚",
    "session": "11-02 下午",
    "version": "B",
    "rules": "全局BP"
  },
  "confirmed_by": "coach"
}
```

`POST /api/studio/pending/batch`：

```json
{
  "match_keys": ["camp:1793606215", "camp:1793606357"],
  "fields": {"session": "11-02 下午", "version": "B"},
  "confirmed_by": "coach"
}
```

### 8.10 防错规则

1. 同一选手不能同时出现在双方阵容。
2. 同一局两个昵称绑定到同一选手时，提示“改绑/新建/取消”。
3. 对手合并要求 3 人以上重合，且必须二次确认。
4. 训练组时间重叠时提示，但不阻止保存。
5. 版本从下拉选择，允许自定义，但标记“自定义”。
6. BP 手序数量必须与 picks 数量一致；不完整可保存，标“未完成”。
7. 批量修改前显示影响局数；执行后提供撤销。
8. 已确认字段被重新导入覆盖时，保留 manual 并提示 diff。
9. 删除/合并操作需要二次确认，保留历史。
10. 合成数据不能确认成生产数据；必须显式转换并记录来源。

### 8.11 验收标准

1. 首次建档 ≤5 分钟，允许跳过；跳过后分析仍可跑 A 类。
2. 导入 32 局后，≥80% 字段自动预填；教练只处理剩余项。
3. 批量设置 10 局的训练组/版本 ≤1 分钟。
4. 对手改名后，历史所有对局同步更新。
5. 选手换号绑定后，分析合并为同一身份。
6. 缺字段时，页面明确指出“哪个分析不可用、还缺什么”。
7. 重新导入不覆盖教练修改；批量操作可撤销。
8. 验证数据默认不出现在生产报告；切换验证模式有明确横幅。

### 8.12 新对手（以前没保存过）处理流程

#### 8.12.1 两种入口

| 场景 | 入口 | 教练要做什么 |
|---|---|---|
| 赛前约到新队 | `#teams` → “新建对手”；或约训日程里新建 | 填队名、教练、赛区/层级；阵容可空，赛后自动填 |
| 赛后导入发现新队 | 导入完成 → “发现未保存对手”卡片 | 新建 / 并入已有 / 作为已有队的新阵容版本 / 稍后处理 |

原则：**赛前只建“壳”，赛后自动填“人”**。不要求教练赛前填满 5 名选手。

#### 8.12.2 赛前新建对手

表单字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| 队名 | 是 | 营地不提供，必须人工 |
| 简称 / 别名 | 否 | 用于搜索、聚类合并 |
| 赛区 / 层级 | 否 | KPL / 次级 / 青训 / 大众 |
| 教练 / 分析师 | 否 | 对手教练名字写这里 |
| 关系 | 否 | 独立 / 某队青训 / 某队二队 / 曾用名 |
| 预期阵容 | 否 | 5 名选手可空；赛后从营地自动填充 |
| 备注 | 否 | 约训来源、打法印象等 |

保存后：

- `teams` 记录创建，`status=active`，`first_seen` 为空。
- 还没有比赛，因此 B1 显示“暂无交手”。
- 导入该队第一场比赛后，系统按“队名/别名/选手 ID”匹配，自动关联；匹配不上再让教练选。
- 保存时可勾选“**同时创建约训**”，填日期/时间/赛制，直接进入 **8.12.11**；这样赛前就有“约训 + 对手壳”，赛后导入可自动挂回。

防重复：

- 保存前先搜队名、别名、教练、选手营地 ID。
- 同名不同队：提示“已有同名队”，要求加赛区/别名区分。
- 同队不同名：用别名合并。

#### 8.12.3 赛后检测到新对手

导入完成后，`team_clusters` 对敌方 5 人做阵容签名。若签名没有映射到任何 `teams`，弹出：

```text
┌ 发现未保存对手 ───────────────────────────┐
│ 5 名选手：A / B / C / D / E               │
│ 首见：11-02 13:15 · 1 局                  │
│ 与已有对手重合：青岚 3/5                  │
│ [新建对手] [合并到青岚] [作为新阵容版本]  │
│ [稍后处理]                                 │
└────────────────────────────────────────────┘
```

五个选项：

1. **新建对手**：填队名/教练；5 名选手自动挂到该队。
2. **合并到已有对手**：3–4 人重合时建议；合并后历史对局全量跟随。
3. **这是已有队伍，只是换号**：进入 **8.13 账号映射**，把新账号挂到已有选手。
4. **作为已有对手的新阵容版本**：0–2 人重合，但教练确认是同一队换人。
5. **稍后处理**：保留 `待命名对手 #N`；A1–A9 照常可用，B1 显示“样本不足”。

无论选哪个，`team_clusters` 的签名映射都会写入覆盖层；以后同签名对局自动归到该队。

#### 8.12.4 新老对手判定规则

| 重合人数 | 判断 | 建议动作 |
|---|---|---|
| 5/5 | 同一队、同一阵容 | 直接关联到已有队 |
| 3–4/5 | 同一队、换人/轮换 | 建议“新阵容版本”或合并 |
| 1–2/5 | 可能不同队 / 青训 / 二队 | 新建对手，或建“关系” |
| 0/5，但队名/教练相同 | 换号 / 大换血 | 进入 **8.13 账号映射**，确认后作为“新阵容版本” |
| 0/5，队名不同 | 新队 | 新建对手 |

#### 8.12.5 新对手首战怎么分析

| 分析 | 首战是否可用 | 页面文案 |
|---|---|---|
| A1–A9 | 可用（只看局内数据） | 正常展示 |
| B1 对手画像 | 不可用（<3 局） | “首战，暂无历史画像；已记录本局 BP/选手/节奏” |
| 对手 BP 习惯 | 不可用 | “样本不足，只展示本局 BP” |
| 赛前预测 | 不可用 | “无历史交手，不做预测” |
| 单局记录 | 可用 | 5 名选手、BP、经济节奏、资源 |

达到 3 局后自动切换为“画像可用”，不需要重新导入。

#### 8.12.6 赛前准备（约到新对手）

1. 在 `#schedule` 新建约训：选择已有对手，或“新建对手”（走 8.12.2 建壳）；填日期/时间/赛制/规则/版本。
2. 赛前预览显示：“无历史交手；建议按常规 BP 准备；赛后自动建档。”
3. 比赛导入后，系统按“日期 + 时间 ±2 小时 + 对手”匹配约训，提示关联与局序。
4. 关联成功后，5 名选手自动写入 `match_rosters` 和 `players`；对手/教练/版本/规则继承约训。
5. 教练只需补 BP 手序/备注；对手名/教练已存在。

> 约训与导入的完整衔接见 **8.12.11**。

#### 8.12.7 边界与防错

| 情况 | 处理 |
|---|---|
| 同名不同队 | 提示已有同名队；要求加赛区/别名；不自动合并 |
| 同队换号（5 人全变） | 签名不重合；教练手动选“新阵容版本” |
| 青训 / 二队 | 建独立队 + `team_relations`；不合并到主队 |
| 对手教练未知 | 留空；报告显示“教练待补” |
| 重复创建 | 保存前按队名/别名/选手 ID 搜索 |
| 误合并 | 撤销合并；历史对局恢复原队 |
| 对手解散/改名 | 归档旧队或加别名；历史记录保留 |

#### 8.12.8 前端组件

**新建对手表单**

```text
┌ 新建对手 ──────────────────────────────┐
│ 队名*   [____________________]          │
│ 简称    [________]  别名 [__________]   │
│ 赛区    [KPL ▾]                         │
│ 教练    [________]  分析师 [________]   │
│ 关系    [独立 ▾]  关联战队 [________]   │
│ 阵容    [赛后自动填充] [手动添加 5 人]  │
│ 备注    [____________________]          │
│                          [保存] [取消]   │
└─────────────────────────────────────────┘
```

**赛后新对手卡片**

```text
┌ 发现未保存对手 ────────────────────────┐
│ 5 名选手：A / B / C / D / E             │
│ 与已有对手重合：青岚 3/5                │
│ [新建对手] [合并到青岚] [新阵容版本]    │
│ [稍后处理]                               │
└─────────────────────────────────────────┘
```

**比赛详情横幅**

```text
对手未命名 · [去命名] [稍后处理]
```

**对手档案空态**

```text
首战，暂无历史画像。
已记录本局 BP、5 名选手、经济节奏与资源。
再打 2 局后自动生成画像。
```

#### 8.12.9 API

```text
GET    /api/studio/teams/search?q=&player_id=
POST   /api/studio/teams
POST   /api/studio/teams/{id}/link-cluster
POST   /api/studio/teams/{id}/roster-versions
POST   /api/studio/teams/{id}/relation
POST   /api/studio/teams/{id}/merge
POST   /api/studio/opponents/detect?match_key=
```

`POST /api/studio/teams`：

```json
{
  "name": "青岚",
  "short_name": "QL",
  "aliases": ["青岚战队"],
  "league": "KPL",
  "coach": "张教练",
  "relation": {"type": "independent"},
  "notes": "首次约训"
}
```

`POST /api/studio/opponents/detect?match_key=camp:1793606215` 返回：

```json
{
  "match_key": "camp:1793606215",
  "cluster_id": "team-abc123",
  "players": ["A", "B", "C", "D", "E"],
  "suggestions": [
    {"team_id": "team-qinglan", "name": "青岚", "overlap": 3}
  ],
  "options": ["create", "merge", "new_roster_version", "later"]
}
```

#### 8.12.10 验收

1. 赛前新建对手 ≤30 秒，允许阵容为空。
2. 赛后导入能检测到未保存对手，并给出重合建议。
3. 选择“合并/新阵容版本”后，历史对局全量跟随。
4. 首战 B1 显示“首战，暂无历史画像”，不报错、不伪造。
5. 第 3 局后自动显示画像。
6. 同名不同队不会自动合并。
7. 误合并可撤销。
8. 对手教练未知时，报告显示“教练待补”。

#### 8.12.11 与赛训日程 / 约训的衔接

**目标**：赛前“建壳”不只建对手档案，还能挂到“约训 / 待打比赛”；赛前预览历史交手，赛后导入自动关联，不重复建档。

**实体关系**：

```text
teams（对手档案）
  ← schedules（约训 / 待打比赛）
      ← matches（实际导入的对局，1 个 schedule 可挂 N 局）
```

一个 BO3 约训 = 1 条 `schedules` + 3 条 `matches`；`matches.series_id` / `game_no` 记录局序。

**赛前流程**：

1. 进入 `#schedule` → “新建约训”。
2. 选择已有对手，或直接“新建对手”（走 8.12.2，建壳）。
3. 填日期、时间、赛制（BO1/BO3/BO5）、规则、版本、训练组、备注。
4. 保存后进入约训详情，显示对手档案预览。

**赛前预览**：

| 对手历史 | 显示 |
|---|---|
| 0 局 | “无历史交手；这是首次约训。赛后自动建档。” |
| 1–2 局 | “样本不足；仅展示单局 BP / 选手 / 节奏记录。” |
| ≥3 局 | 对手画像：BP 偏好、选手英雄池、节奏、资源、阵容版本 |
| 教练缺失 | “教练待补” |
| 阵容版本 | 显示当前/历史阵容；换号标“账号变化” |

**赛后导入关联**：

1. 导入营地局后，按“日期 + 开赛时间 ±2 小时 + 对手 team/cluster”匹配 `schedules`。
2. 唯一匹配：提示“关联到 11-02 19:00 vs 青岚 BO3 第 2 局？”→ 确认。
3. 多个匹配：列出候选，教练选择。
4. 无匹配：提示“未找到约训记录”，可选“创建约训”或“仅导入比赛”。
5. 对手不一致：警告“约训记录是青岚，本局识别为赤霄”，允许改约训对手或改本局对手。
6. 关联后继承：对手、教练、训练组、版本、规则、赛制；教练只补 BP 手序/备注。
7. BO3/BO5：同一 schedule 下 `game_no` 自动递增；不重复建约训。

**状态**：

| 状态 | 含义 |
|---|---|
| `planned` | 已约，未确认 |
| `confirmed` | 约训确认 |
| `played` | 已导入至少一局 |
| `postponed` | 改期 |
| `cancelled` | 取消；已导入对局仍保留 |

**数据模型**：

```sql
CREATE TABLE schedules (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  start_time TEXT,
  opponent_team_id TEXT REFERENCES teams(id),
  session TEXT,
  series_id TEXT,
  format TEXT,              -- BO1 / BO3 / BO5
  rules TEXT,
  version TEXT,
  status TEXT NOT NULL DEFAULT 'planned',
  notes TEXT,
  created_by TEXT,
  created_at REAL NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_schedules_date ON schedules(date);
CREATE INDEX idx_schedules_opponent ON schedules(opponent_team_id);

ALTER TABLE matches ADD COLUMN schedule_id TEXT REFERENCES schedules(id);
```

**API**：

```text
GET    /api/studio/schedules?from=&to=&status=
POST   /api/studio/schedules
GET    /api/studio/schedules/{id}
PATCH  /api/studio/schedules/{id}
POST   /api/studio/schedules/{id}/cancel
POST   /api/studio/schedules/{id}/link-match
GET    /api/studio/schedules/{id}/preview
GET    /api/studio/schedules/suggest?date=&start_time=&opponent=
```

**UI**：

- `#schedule`：列表/日历视图，显示日期、对手、赛制、状态。
- 新建约训表单：对手选择/新建、日期、时间、赛制、规则、版本、训练组、备注。
- 约训详情：对手预览、历史交手、阵容版本、关联对局、状态操作。
- 导入关联弹窗：候选约训、局序、确认/改期/忽略。
- 对局详情：显示“属于 11-02 19:00 vs 青岚 BO3 第 2 局”。

**边界**：

| 情况 | 处理 |
|---|---|
| 约训对手是新建壳 | 允许；预览显示“无历史交手” |
| 约训取消后仍导入 | 对局保留；提示“约训已取消，是否恢复为已打” |
| 约训改期 | 已关联对局保留原日期；显示差异 |
| 对手临时换队 | 警告；允许改约训对手或改本局对手 |
| 一个约训多局 | 1 schedule → N matches，`game_no` 自动 |
| 没有约训直接导入 | 允许；事后可补建约训并关联 |
| 重复约训 | 同日同对手同时间提示重复 |

**验收**：

1. 赛前新建“新对手 + 约训”，预览显示“无历史交手”。
2. 赛后导入能自动匹配约训，并提示局序。
3. BO3 三局挂到同一约训，`game_no` 1/2/3。
4. 约训取消后，已导入对局仍保留。
5. 对手不一致时警告，不静默关联。
6. 无约训时可直接导入，事后补建。
7. 关联后不重复创建对手/比赛。

### 8.13 对手换号 / 一个选手多账号

#### 8.13.1 核心模型：账号 ≠ 选手

| 实体 | 说明 | 示例 |
|---|---|---|
| 战队 Team | 稳定的队伍身份 | 青岚 |
| 选手 Player | 稳定的人，分析按这个聚合 | 青岚·辰 |
| 账号 Account | 营地 `playerId` + 昵称；一个人可以有多个 | 1234、5678、9012 |
| 阵容版本 RosterVersion | 某段时间队伍用的是哪 5 个人 | 青岚 B 版：辰/野/中/射/辅 |
| 对局阵容 MatchRoster | 某局某位置具体用了哪个账号 | 3 号位：青岚·辰（账号 5678） |

规则：

- **一个账号只能属于一个选手**；一个选手可以拥有多个账号。
- **分析按选手聚合**：B1 对手画像、英雄池、BP 偏好、参团等都按 `player_id`，不按账号。
- **识别按账号匹配**：导入时先用 `playerId` 找账号，再映射到选手；找不到才让教练确认。
- **不猜**：未知账号标“未识别”，不因为昵称相似就自动合并。

#### 8.13.2 换号场景怎么进

赛后导入检测到“队伍还是原来那支，但 5 个账号都没见过”时，新对手卡片增加一个选项：

```text
┌ 发现未保存阵容 ───────────────────────────┐
│ 5 个账号：A / B / C / D / E               │
│ 与已有对手重合：青岚 0/5（账号）          │
│ [这是新队伍] [这是青岚，只是换号]         │
│ [稍后处理]                                 │
└────────────────────────────────────────────┘
```

选择“这是青岚，只是换号”后，进入账号映射：

```text
┌ 账号映射 · 青岚 ──────────────────────────┐
│ 账号 A（昵称）  [青岚·辰 ▾] [新建选手]   │
│ 账号 B（昵称）  [青岚·野 ▾] [新建选手]   │
│ 账号 C（昵称）  [青岚·中 ▾] [新建选手]   │
│ 账号 D（昵称）  [青岚·射 ▾] [新建选手]   │
│ 账号 E（昵称）  [青岚·辅 ▾] [新建选手]   │
│ [保存为青岚 · 新阵容版本] [取消]          │
└────────────────────────────────────────────┘
```

保存后：

- 5 个账号写入 `player_accounts`，分别挂到对应选手。
- 该局写入 `match_rosters.account_id` + `player_id`。
- 账号签名映射到青岚；以后同账号组合自动归队。
- 如果 5 人组合与上一版不同，生成新的 `team_roster_versions`。

#### 8.13.3 队伍识别签名

| 签名 | 计算 | 用途 |
|---|---|---|
| `account_signature` | 敌方 5 个 `playerId` 排序哈希 | 账号完全一致时精确匹配 |
| `identity_signature` | 映射后的 5 个 `player_id` 排序哈希 | 换号后仍能识别为同一队 |

规则：

- 5 个账号都能映射到选手 → 用 `identity_signature` 判定队伍。
- 有账号未映射 → 用 `account_signature` 兜底，并提示“有 N 个账号未识别”。
- 两个签名都映射到同一 `team_id` 时，合并到该队。
- 映射关系写覆盖层，不改原始比赛。

#### 8.13.4 教练操作流程

**场景 A：3–4 个账号认识，1–2 个新账号**

1. 系统自动匹配已知账号。
2. 新账号提示“可能是小号/替补”。
3. 教练选择：
   - 是同一选手的小号 → “挂到该选手”；
   - 是新替补 → “新建选手”；
   - 不认识 → “稍后处理”。
4. 保存后，新账号下次自动识别。

**场景 B：5 个账号全不认识，但教练知道是同一队**

1. 选择“这是已有队伍，只是换号”。
2. 逐个账号选择已有选手，或新建选手。
3. 保存为“新阵容版本”。
4. 系统记录账号 → 选手；下次自动。

**场景 C：同一选手多个账号**

在选手详情 → “账号”：

```text
青岚·辰
主号：1234（昵称）
小号：5678（11-02 首见）
小号：9012（11-05 首见）
[添加账号] [设为主号] [解绑]
```

- 主号只影响展示，不影响分析。
- 解绑账号后，历史对局仍保留当时的映射；新对局不再自动匹配。
- 添加账号支持输入营地 ID，或从“未识别账号”列表选择。

#### 8.13.5 分析口径

| 分析 | 换号后怎么算 |
|---|---|
| B1 对手画像 | 按 `player_id` 聚合；同一选手多个账号合并 |
| 选手英雄池 | 按 `player_id`；账号只作为证据 |
| BP 偏好 | 按队伍；账号变化不影响 |
| 阵容稳定度 | 按 `player_id` 集合，不按账号；换号不算换人 |
| 单局明细 | 显示账号 + 选手；非主号标“小号” |
| 未识别账号 | 计入队伍级统计，选手级显示“未识别账号”，不猜 |

#### 8.13.6 边界与防错

| 情况 | 处理 |
|---|---|
| 一个账号被两个选手使用 | 标 `shared=true`；按局映射；提示冲突 |
| 一个选手转会到另一队 | 写 `player_team_history`；保留历史；提示“已转会” |
| 账号改名、`playerId` 不变 | 更新昵称，不新建选手 |
| 新替补（不是小号） | 新建选手；加入新阵容版本 |
| 5 个全是新账号 | 不自动合并；教练必须确认“同一队换号” |
| 同名不同队 | 不自动合并；要求赛区/别名区分 |
| 误绑账号 | 解绑/改绑；历史映射保留；可撤销 |
| 同一账号出现在双方 | 拒绝并提示数据异常 |

#### 8.13.7 前端组件

**账号映射抽屉**：新账号列表 + 选手选择 + 新建选手 + 保存为阵容版本。

**选手账号列表**：主号/小号、首见日期、解绑、设为主号。

**对局详情**：`3 号位：青岚·辰（账号 5678 · 小号）`；未识别显示 `账号 5678 · 未识别`。

**阵容版本时间线**：

```text
青岚
v1  2026-10-01 — 2026-11-01  辰/野/中/射/辅
B 版  2026-11-02 — 至今   辰/野/中/射/辅
    账号变化：辰 5678、野 6789
```

#### 8.13.8 API

```text
GET    /api/studio/opponents/{team_id}/accounts
POST   /api/studio/opponents/{team_id}/accounts
POST   /api/studio/accounts/{account_id}/link-player
POST   /api/studio/accounts/{account_id}/unlink
POST   /api/studio/accounts/{account_id}/primary
GET    /api/studio/opponents/{team_id}/roster-versions
POST   /api/studio/opponents/{team_id}/roster-versions
POST   /api/studio/opponents/detect?match_key=
```

`POST /api/studio/opponents/{team_id}/accounts`：

```json
{
  "accounts": [
    {"account_id": "5678", "nickname": "辰辰", "player_id": "p-chen", "is_primary": false},
    {"account_id": "6789", "nickname": "野王", "player_id": "p-ye", "is_primary": true}
  ],
  "roster_version": {"name": "B", "start_date": "2026-11-02"}
}
```

#### 8.13.9 验收

1. 同一队 5 个新账号，教练映射后，下次自动归队。
2. 3 个已知 + 2 个新账号，系统给出“小号/替补”建议。
3. 同一选手 3 个账号，B1 画像合并为 1 人。
4. 换号不改变阵容稳定度（按选手算）。
5. 未知账号显示“未识别”，不自动猜。
6. 同一账号绑两个选手时提示冲突。
7. 解绑/改绑可撤销，历史对局保留原映射。
8. 5 个全换号时，不自动合并为新队，必须教练确认。

## 9. 全局一致性、修订历史与撤销

### 9.1 一致性目标

1. **单一事实来源**：所有页面读同一份 resolved 值，`confirmed > prefill > empty`，不在多处复制派生值。
2. **写后全局可见**：教练改一个字段，所有依赖它的页面、分析、报告、搜索、筛选同步更新。
3. **不重写原始数据**：改名、绑定、合并只写覆盖层；营地原始文件一个字节不改。
4. **读时解析**：显示名、对手归属、选手身份在查询时解析，避免批量回写历史对局。
5. **可追溯**：每次修改有来源、操作人、时间、批次；可撤销、可审计。

### 9.2 解析与版本

| 对象 | 版本字段 | 失效范围 |
|---|---|---|
| 全局工作区 | `workspace_meta.revision` | 所有缓存、搜索索引 |
| 对局 | `matches.revision` | 该局统计、报告、列表 |
| 战队 | `teams.revision` | 对手档案、战队对比、报告 |
| 选手 | `players.revision` | 选手档案、搭档、训练重点 |
| 训练组 | `training.revision` | 训练汇总、训练效果 |
| 分析缓存 | `analysis_cache.input_revision` | 单条分析结果 |

规则：

- 任何写操作在同一事务内：更新数据 + 写 `change_log` + 递增 `revision` + 写 outbox 事件。
- 分析缓存 key = `analysis + scope_hash + input_revision`；revision 变化即失效。
- API 返回 `revision`；前端丢弃比当前 revision 更旧的响应，防止回退。
- 前端保存成功后广播 `platform-data-changed`，当前页重取；其他标签页通过 `BroadcastChannel` 同步。

### 9.3 变更影响矩阵

| 变更 | 影响范围 | 更新方式 | 是否阻塞 |
|---|---|---|---|
| 对手改名 / 合并 | 对手档案、战队对比、BP 按对手、报告、搜索、筛选 | 读时解析 + 失效 `team:*` 缓存 | 否，<1s |
| 选手绑定 / 别名 | 选手档案、英雄池、搭档、训练重点、对比、报告、搜索 | 重算 `player:*` 聚合 | 否，<2s |
| 训练组改名 | 训练组汇总、训练效果、看板、报告 | 重算 `session:*` 聚合 | 否，<2s |
| 版本修改 | 版本趋势、英雄优先级、BP、筛选 | 重算 `version:*` 聚合 | 否，<2s |
| 日期 / 阵营 / 胜负 / 比分 | 所有统计、胜率、筛选、报告 | 重算该局 + 相关聚合 | 是，<2s |
| BP 手序 / 一手方 | BP 分析、阵容组合、报告 | 重算 `bp:*` 聚合 | 否，<1s |
| 训练干预 | B3 训练效果、训练看板 | 重算 `training:*` | 否，<2s |
| 战队 / 教练 | 报告抬头、对手档案、搜索 | 读时解析 | 否，<1s |
| 删除 / 归档 | 列表、聚合、报告、搜索 | 软删除 + 失效 | 否，<2s |

**注意**：A1–A9 的数值只依赖营地局内数据，不依赖队名/教练；改名不会改变数值，只会改变显示与筛选。B1/B3 依赖平台字段，变更会触发重算。

### 9.4 更新机制

```text
写请求
  → 事务：数据 + change_log + revision++ + outbox
  → 提交
  → 广播 data-changed {scope, ids, revision}
  → 失效缓存（按 scope）
  → 轻量聚合：同步重算
  → 重量分析：后台队列重算
  → 前端重取当前页 / 其他标签页同步
```

细节：

- **缓存失效**：按 scope 失效，不做全量清空。`team:xxx`、`player:xxx`、`session:xxx`、`version:xxx`、`match:xxx`。
- **重算队列**：可取消、可合并、可查看进度；同一 scope 多次变更只保留最后一次。
- **全局搜索**：对手/选手/比赛/功能索引随 revision 更新；改名后旧名可搜索到（别名）。
- **一致性级别**：同一事务内强一致；分析缓存最终一致，页面显示“正在更新”。
- **幂等**：重复事件不重复重算；以 revision 为准。
- **失败回滚**：重算失败保留旧缓存并标 `stale=true`，不返回半成品。

### 9.5 历史记录

`change_log` 记录所有 manual / merge / alias / undo 操作；自动预填刷新可只保留最新值，不逐次记日志。

| 字段 | 说明 |
|---|---|
| `entity_type` | match / team / player / session / version / training |
| `entity_id` | 对象 ID |
| `field` | 字段名 |
| `old_value` / `new_value` | 旧值 / 新值 |
| `source` | manual / prefill / import / merge / undo |
| `actor` | 教练/分析师/系统 |
| `batch_id` | 批量操作 ID |
| `reason` | 可选备注 |
| `created_at` | 时间 |
| `undone_at` | 被撤销时间 |
| `undo_of` | 撤销的是哪条记录 |
| `revision` | 操作后的对象版本 |

规则：

- **追加写**：不更新、不删除历史；撤销也是一条新记录。
- **批量**：一个 `batch_id` 对应一次批量操作，可整体撤销。
- **合并/绑定**：保留映射历史；撤销合并恢复原 cluster。
- **保留期**：本地默认永久；超过 1 年可归档到 `change_log_archive`，不影响查询。
- **可见性**：教练看自己/全局；选手只看自己的（选手端上线后）。

### 9.6 撤销 / 重做

| 操作 | 撤销语义 | 冲突处理 |
|---|---|---|
| 单字段修改 | 写回 `old_value` | 若字段已被再次修改，提示冲突，选择“覆盖/合并/取消” |
| 批量修改 | 按 `batch_id` 逐条写回 | 部分冲突时列出冲突项，允许跳过 |
| 对手改名 | 恢复旧名/空名 | 若已合并，先撤销合并 |
| 对手合并 | 恢复被合并 cluster | 若目标 cluster 已改名，保留目标名 |
| 选手别名绑定 | 删除别名映射 | 若该昵称已重新绑定，提示冲突 |
| 删除 / 归档 | 恢复记录 | 若记录已重建，按 ID 去重 |
| 预填确认 | 回退到 prefill 值 | prefill 已变化时提示“重新预填/保留当前” |

交互：

- 保存后 toast：`已保存 · 撤销`，保留 10 秒。
- 历史抽屉：按时间倒序，显示字段、旧值 → 新值、操作人、来源、批次。
- 批量操作：显示“本次影响 N 条”，支持整批撤销。
- 重做：可选；保留 `redo_of`，撤销后可重做一次。
- 撤销本身也写 `change_log`，可再次撤销（回到撤销前）。

### 9.7 前端联动

- 保存成功：`window.dispatchEvent(new CustomEvent('platform-data-changed', {detail:{scope, ids, revision}}))`。
- 其他标签页：`BroadcastChannel('kpl-data')` 接收后失效本地缓存并提示“数据已更新”。
- 当前页：重取 workspace + 当前分析；保留滚动位置与筛选。
- 防止旧响应覆盖：每个请求带 `revision`/token，丢弃过期响应。
- 更新中：顶部细条“正在更新分析…”，不阻塞阅读。
- 冲突：409 返回当前值 + 修改人，弹窗选择。

### 9.8 API

```text
GET    /api/studio/history?entity_type=&entity_id=&actor=&from=&to=&limit=&cursor=
POST   /api/studio/history/{id}/undo
POST   /api/studio/history/batch/{batch_id}/undo
POST   /api/studio/history/{id}/redo
GET    /api/studio/revisions?scope=match|team|player|session|version
POST   /api/studio/recompute {scope, ids}
```

`GET /api/studio/history` 返回：

```json
{
  "items": [
    {
      "id": "chg-001",
      "entity_type": "team",
      "entity_id": "team-xxx",
      "field": "name",
      "old_value": "待命名对手 #3",
      "new_value": "青岚",
      "source": "manual",
      "actor": "coach",
      "batch_id": null,
      "created_at": 1762300000.0,
      "undone_at": null,
      "revision": 2
    }
  ],
  "nextCursor": null
}
```

### 9.9 验收

1. 对手改名后，对手档案、比赛列表、报告、搜索在 1 秒内全部显示新名。
2. 选手绑定后，选手档案、搭档、训练重点在 2 秒内合并。
3. 撤销改名后，所有页面恢复旧名，历史记录保留两条。
4. 批量修改 10 局，整批撤销后全部恢复。
5. 两个标签页同时打开，一边修改，另一边自动刷新。
6. 冲突修改返回 409，不静默覆盖。
7. `change_log` 只追加，不物理删除。
8. 重算失败不返回半成品，旧缓存标 `stale`。

---

## 10. 数据库容量与性能

### 10.1 容量估算

> 以下为量级估算，实际以 `scripts/eval_scale.py` 和真实库统计为准。

| 数据 | 每局 | 32 局 | 1,000 局 | 10,000 局 |
|---|---:|---:|---:|---:|
| `matches` 行 | 1 | 32 | 1,000 | 10,000 |
| `match_rosters` 行 | 10 | 320 | 10,000 | 100,000 |
| `bp` 行 | 1 | 32 | 1,000 | 10,000 |
| `change_log` 行 | 20–100 | 640–3,200 | 2–10 万 | 20–100 万 |
| `provenance` 行 | ~50 | 1,600 | 5 万 | 50 万 |
| `prefill_fields` 行 | ~20 | 640 | 2 万 | 20 万 |
| 营地面板 JSON | **97 KB（实测均值）** | 3.0 MB | 95 MB | 0.95 GB |
| 回放 normalized JSON | **120 KB（实测均值）** | 2.6 MB | 117 MB | 1.17 GB |
| 位置 JSON | **86 KB（实测均值）** | 1.9 MB | 84 MB | 0.84 GB |
| raw.json（复活点等） | **765 KB（实测均值）** | 16.4 MB | 747 MB | 7.5 GB |
| **文件合计** | **约 1.07 MB** | **约 34 MB** | **约 1.04 GB** | **约 10.4 GB** |

结论：

- **元数据**：10,000 局也在 SQLite 舒适区（百万级行）。
- **文件存储才是主问题**：10,000 局约 10.4 GB，其中 `raw.json` 占约 72%。
- **保留策略（已确认）**：**原始 `raw.json` 永久保留，不删除**。额外生成 `revive.json` 只作为快速读取缓存，不影响 raw 的完整性。
- **优化顺序**：
  1. 生成 `revive.json` 加速常用读取，原始 raw 保留；
  2. 位置 JSON 压成二进制/`npz`，预计缩小 3–5 倍；
  3. 面板/回放 JSON 只保留用到的字段，去掉展示型冗余；raw 不动。
- **容量规划**：按 10,000 局约 10.4 GB 预留磁盘；超过 1 年的 raw 可移入 `data/archive/` 冷存储，但保留可追溯，不做删除。
- **不做**：把位置/raw 逐点写进 SQLite 行；那会让行数从百万级涨到千万级，得不偿失。
- **主要运行时瓶颈**：JSON 解析和重复计算，不是 SQLite 写入。

### 10.2 SQLite 使用方式

- 开启 WAL：`PRAGMA journal_mode=WAL`。
- `PRAGMA synchronous=NORMAL`；`PRAGMA busy_timeout=5000`。
- `PRAGMA temp_store=MEMORY`；合理设置 `mmap_size`。
- 单写者：所有写走一个队列；读用只读连接。
- 批量写：一个导入批次一个事务，避免逐行 commit。
- 不把大 JSON/BLOB 放进 `matches`；只存 `data_path`、`sha256`、`size`。
- 搜索：优先 SQLite FTS5；没有 FTS 时用内存索引，启动时构建。

### 10.3 索引与查询

必须有：

```sql
CREATE INDEX idx_matches_date ON matches(date);
CREATE INDEX idx_matches_enemy ON matches(enemy_team_id);
CREATE INDEX idx_matches_session ON matches(session);
CREATE INDEX idx_matches_version ON matches(version);
CREATE INDEX idx_matches_status ON matches(status);
CREATE INDEX idx_rosters_match ON match_rosters(match_key);
CREATE INDEX idx_rosters_player ON match_rosters(player_id);
CREATE INDEX idx_change_entity ON change_log(entity_type, entity_id, created_at);
CREATE INDEX idx_change_batch ON change_log(batch_id);
CREATE INDEX idx_prefill_synthetic ON prefill_fields(synthetic);
```

查询规则：

- 列表分页，服务端筛选；不 `SELECT *` 取大字段。
- 分析查询只取需要的列；JSON 解析结果缓存。
- 用 `EXPLAIN QUERY PLAN` 检查全表扫描；超过 500ms 记慢查询。
- 不在 HTTP 请求里做全量重算；走缓存/后台队列。

### 10.4 派生表与缓存

建议新增：

| 表 | 粒度 | 用途 | 失效 |
|---|---|---|---|
| `match_metrics` | 局 | 胜负、经济差、时长、覆盖 | `match.revision` |
| `player_match_metrics` | 人/局 | KDA/GPM/DPM/占比 | `player/match.revision` |
| `team_match_metrics` | 队/局 | 团队经济、资源、推塔 | `team/match.revision` |
| `session_summary` | 训练组 | 局数、胜负、覆盖 | `session.revision` |
| `opponent_summary` | 对手 | 交手、BP、选手池 | `team.revision` |
| `version_summary` | 版本 | 英雄优先级、胜率 | `version.revision` |
| `analysis_cache` | 分析+范围 | 分析结果缓存 | `input_revision` |

规则：

- 导入/修改后**增量重算**受影响的 scope，不清空全库。
- 重算可合并：同一 scope 多次变更只算最后一次。
- 缓存带 `input_revision`；revision 不匹配即失效。
- 重算失败保留旧缓存并标 `stale=true`，页面提示“数据可能过期”。

### 10.5 分析成本与预算

| 分析 | 复杂度 | 22 局 | 1,000 局 | 10,000 局 | 策略 |
|---|---|---|---:|---:|---:|---|
| A1 路线聚类 | O(n²) DTW | <2s | 30–60s | 10min+ | 按批次预计算，缓存 |
| A2 中野辅 | O(秒×人) | <1s | <10s | <60s | 按局并行/缓存 |
| A3 团战到位 | O(团战×人) | <0.5s | <5s | <30s | 线性，直接算 |
| A4 掉点孤立 | O(死亡×人) | <0.5s | <5s | <30s | 线性，直接算 |
| A5 击杀链 | O(击杀) | <0.2s | <2s | <10s | 线性 |
| A6 团战消耗 | O(团战×人) | <0.5s | <5s | <30s | 线性 |
| A7 资源空间 | O(事件) | <0.5s | <5s | <30s | 线性 |
| A8 经济转折 | O(经济点+事件) | <0.2s | <2s | <10s | 线性 |
| A9 优势兑现 | O(局) | <0.2s | <2s | <10s | 聚合 |
| B1 对手画像 | O(局) | <0.5s | <5s | <30s | 聚合缓存 |
| B2 出装时序 | O(事件) | <0.5s | <5s | <30s | 线性 |
| B3 训练效果 | O(局) | <0.5s | <5s | <30s | 聚合缓存 |

预算：

- 首屏/页面：<2s。
- 单分析：<2s 直接返回；>2s 转后台，返回 `jobId` + 进度。
- 10,000 局：页面只读缓存，重算后台。
- 重算队列可见、可取消、可重试。

### 10.6 写入路径

```text
导入/修改请求
  → 写队列（单写者）
  → BEGIN IMMEDIATE
  → 写业务表 + change_log + revision++
  → COMMIT
  → 异步：预填、派生表、缓存失效、搜索索引
```

要求：

- 批量导入 32 局：一个事务，避免 32 次 commit。
- 写事务尽量短；不在事务内做重计算。
- 写失败回滚，change_log 不落。
- 写队列有超时与死信；失败可重试。
- 大批量导入显示进度，不阻塞读。

### 10.7 读取路径

- workspace 缓存 + `ETag`/`If-None-Match`；未变更返回 304。
- 列表分页；筛选在 SQL 层完成。
- 分析结果优先读 `analysis_cache`；未命中再算。
- 前端按区块懒加载；不一次请求所有分析。
- 大文件（位置）按需加载、降采样；不整包塞进首屏。

### 10.8 并发

- 当前单机单用户：SQLite 足够。
- 多标签页：BroadcastChannel + revision 防旧响应。
- 多教练/多端（未来）：单服务进程 + 写队列；读可并发。
- 乐观并发：`If-Match: revision`；冲突返回 409 + 当前值。
- 多战队（未来）：所有表加 `team_scope`，查询默认过滤；再考虑 Postgres。
- 不允许多个服务进程同时写同一 SQLite 文件；用文件锁/单实例。

### 10.9 存储、备份与归档

- `data/` 体积：元数据 + 面板/回放 JSON + 位置；10,000 局约 10.4 GB，raw.json 占大头。
- **raw 保留（已确认）**：原始 `raw.json` 永久保留，不删除、不裁字段；额外生成 `revive.json` 作为快速读取缓存；保留 `sha256` 便于追溯。
- **位置压缩**：`posArr` 转二进制/`npz`，按局存储；页面按需加载、降采样。
- **去重**：面板/回放按 `sha256` 去重，同一文件只存一份。
- 备份包含：DB、`teams/players/matches/...`、原始面板/回放/raw；不包含派生缓存。
- 备份分两级：热数据（最近 3 个月）全量；冷数据（>1 年）移入 `data/archive/` 冷存储，**保留不删除**，DB 保留摘要与索引。
- 备份前 `VACUUM`/检查点，减少 WAL。
- `change_log` 超过 1 年可压缩归档；不影响撤销最近操作。
- 验证库 `data/validation.sqlite3` 独立，不进入生产备份。

### 10.10 监控

`/api/health` 增加：

```json
{
  "db": {"sizeMB": 120, "walMB": 8, "tables": {"matches": 1000, "change_log": 42000}},
  "cache": {"hitRate": 0.82, "stale": 0},
  "queue": {"recompute": 2, "pending": 0},
  "slowQueries": 3,
  "lastRecomputeAt": 1762300000
}
```

阈值：

- WAL > 100MB：触发 checkpoint。
- DB > 2GB：提示归档/迁移。
- 慢查询 > 500ms：记日志。
- 缓存命中 <50%：检查失效范围是否过大。

### 10.11 扩展决策

| 规模 | 方案 |
|---|---|
| <1,000 局 | SQLite + 文件缓存，足够 |
| 1,000–10,000 局 | SQLite + 派生表 + 压缩位置 + 后台重算 |
| >10,000 局或多战队/多用户 | Postgres/DuckDB + 对象存储 + 独立分析服务 |
| 需要实时多人协作 | 服务端 + 鉴权 + WebSocket/SSE；SQLite 不再合适 |

不要提前优化；先用 `scripts/eval_scale.py` 压测，再决定迁移。

### 10.12 验收

1. 1,000 局：workspace 命中缓存 <1s；单分析 <5s。
2. 10,000 局：缓存页面 <2s；重算后台，不阻塞请求。
3. 改名/绑定：全局更新 <2s；无旧值残留。
4. 撤销：<200ms；历史可查。
5. 无全表扫描；慢查询有日志。
6. WAL 可控；备份体积可接受。
7. 批量导入不逐行 commit；失败可回滚。
8. 多标签页不出现旧数据覆盖。

## 11. 验收测试矩阵

| # | 功能 | 用例 | 期望 |
|---|---|---|---|
| 1 | A1 | 前 4 分钟位置覆盖 <90% | `available=false`，说明缺失原因 |
| 2 | A1 | 坐标未定标 | `relative=true`，不输出绝对距离 |
| 3 | A2 | 分路缺失 | `available=false` |
| 4 | A2 | 击杀时间与位置差 >1s | 跳过该击杀，计入 `missing_kills` |
| 5 | A3 | 参战时间缺失 | 排除该参战者，计数 |
| 6 | A3 | 0 击杀团战 | 保留到位分析，`kill_diff=null` |
| 7 | A4 | 死亡坐标缺失 | 跳过，计入 `missing_coords` |
| 8 | A4 | 无复活 | `final=true`，窗口到比赛结束 |
| 9 | A4 | 连续相同坐标 | 取死亡前最后有效点 |
| 10 | A5 | 同秒击杀 | `ambiguous_order=true` |
| 11 | A5 | <2 击杀团战 | 排除 |
| 12 | A6 | HP 缺失 | 跳过 HP 指标，保留占比 |
| 13 | A6 | 明细缺失 | 排除该团战 |
| 14 | A7 | 事件无锚点 | `spatial=false` |
| 15 | A7 | 未知事件类型 | `unclassified` |
| 16 | A8 | 经济序列长度不一致 | `length_mismatch=true` |
| 17 | A8 | 无事件 | `candidates=[]` |
| 18 | A9 | 无 10 分钟点 | 排除 |
| 19 | A9 | 样本 <10 | 只输出观察 |
| 20 | B1 | 对手 <3 局 | 样本不足 |
| 21 | B1 | 未命名对手 | `待命名对手 #N` |
| 22 | B2 | 无装备事件 | `timing=false` |
| 23 | B2 | 时间对不上 | `unlinked=true` |
| 24 | B3 | 无干预标签 | `available=false` |
| 25 | B3 | 前后各 <5 局 | 样本不足 |
| 26 | 预填 | 重复执行 | 幂等，不覆盖 manual |
| 27 | 预填 | 教练修改 | confirmed 优先 |
| 28 | 验证 | 合成数据导出 | 默认排除 |
| 29 | UI | 缺失字段 | 显示 `—`，不显示 0 |
| 30 | UI | 合成数据 | 显示验证横幅 |
| 31 | 全局 | 对手改名 | 比赛列表、对手档案、报告、搜索 <1s 更新 |
| 32 | 全局 | 选手绑定/别名 | 选手档案、搭档、训练重点 <2s 合并 |
| 33 | 历史 | 撤销对手改名 | 所有页面恢复旧名，历史保留两条 |
| 34 | 历史 | 批量修改 10 局后整批撤销 | 10 局全部恢复 |
| 35 | 并发 | 两个标签页同时改同一字段 | 后者收到 409，不静默覆盖 |
| 36 | 并发 | 一个标签页修改 | 另一个标签页自动刷新 |
| 37 | 性能 | 1,000 局缓存读取 | workspace <1s，单分析 <5s |
| 38 | 性能 | 10,000 局缓存读取 | 页面 <2s，重算后台执行 |
| 39 | 性能 | 慢查询 | >500ms 记入日志 |
| 40 | 撤销 | 单字段撤销 | <200ms，历史可查 |
| 41 | 新对手 | 赛前新建对手，阵容留空 | 30 秒内保存，B1 显示“暂无交手” |
| 42 | 新对手 | 赛后导入未保存阵容 | 弹“发现未保存对手”，给出重合建议 |
| 43 | 新对手 | 与已有对手重合 3/5 | 建议“合并/新阵容版本”，不自动合并 |
| 44 | 新对手 | 0/5 但队名/教练相同 | 允许标记“新阵容版本” |
| 45 | 新对手 | 首战打开对手画像 | 显示“首战，暂无历史画像”，不报错 |
| 46 | 新对手 | 第 3 局后打开画像 | 自动切换为可用画像 |
| 47 | 新对手 | 同名不同队 | 提示重名，不自动合并 |
| 48 | 新对手 | 误合并后撤销 | 历史对局恢复原队 |
| 49 | 换号 | 同一队 5 个新账号 | 教练映射后，下次自动归队 |
| 50 | 换号 | 3 个已知 + 2 个新账号 | 给出“小号/替补”建议 |
| 51 | 换号 | 同一选手 3 个账号 | B1 画像合并为 1 人 |
| 52 | 换号 | 账号变化、选手不变 | 阵容稳定度不变（按选手算） |
| 53 | 换号 | 未知账号 | 显示“未识别”，不自动猜 |
| 54 | 换号 | 同一账号绑两个选手 | 提示冲突，不静默覆盖 |
| 55 | 换号 | 解绑/改绑账号 | 可撤销，历史对局保留原映射 |
| 56 | 换号 | 5 个全换号 | 不自动新建队伍，必须教练确认 |
| 57 | 约训 | 赛前新建“新对手 + 约训” | 预览显示“无历史交手” |
| 58 | 约训 | 赛后导入匹配到约训 | 提示关联，继承对手/教练/训练组/版本 |
| 59 | 约训 | BO3 三局导入 | 同一 schedule 下 `game_no` 1/2/3 |
| 60 | 约训 | 约训取消后仍导入 | 对局保留，提示“是否恢复为已打” |
| 61 | 约训 | 导入对手与约训不一致 | 警告，不静默关联 |
| 62 | 约训 | 无约训直接导入 | 允许导入，事后可补建约训 |
| 63 | 约训 | 约训改期 | 已关联对局保留原日期，显示差异 |

---

## 12. 实施计划

| 阶段 | 交付 |
|---|---|
| Phase 0 | 字段字典、覆盖审计、`prefill_fields`、验证库 dry-run |
| Phase 1 | A4 掉点孤立度、A3 团战到位 |
| Phase 2 | A8 经济转折、A9 优势兑现 |
| Phase 3 | A2 中野辅联动、A1 开局路线 |
| Phase 4 | A5 击杀链、A6 团战消耗、A7 资源争夺 |
| Phase 5 | B1 对手画像、B2 出装时序、B3 训练效果 |
| Phase 6 | UI 待确认队列、报告、全站验收 |

---

## 13. 风险与待确认

1. **坐标定标**：当前 `x∈[-154,59]`、`y∈[-157,58]`，需确认地图边界与距离阈值。
2. **A7 锚点**：击杀者位置是近似，不是资源坐标；是否补静态资源点表。
3. **样本门槛**：团队级 ≥10 局、事件级 ≥30 次、团战级 ≥20 场，是否确认。
4. **验证库命名**：`data/validation.sqlite3` 是否确认。
5. **B1 样本**：32 个对手各 1 局，mock 7 队只用于功能验证，不代表真实对手画像。
6. **B3 干预标签**：需要教练填写，合成数据不能替代真实效果结论。
7. **当前数据是排位赛**：A1–A9 可做技术验证，结论必须标“排位赛样本”。
