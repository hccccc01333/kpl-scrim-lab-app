# 王者营地回放载荷清单（数据字典）

- 版本：2026-11-10（对应平台 1.5.29）
- 扫描样本：`data/official_replays/` 下 **24 局**真实落盘回放（`camp-<gameSeq>/`）
- 生成方式：`python scripts/archive_camp_fields.py` → `data/official_replays/_fields-index.json`
  （逐局 `fields.json`、跨局 `_fields-index.json`、前端文案 `data/camp_labels.json`）
- 用途：**一页说清营地回放到底给了什么数据、精度多少、我们读了哪些、还差哪些**。
  改营地接口或改分析口径时先查这份，不要凭印象。

> 本文所有路径、覆盖率、样例值都来自上面 24 局的实际载荷，不是文档推测。
> 标「未证实」的条目表示字段顺序/量纲还没用数据验证过，不能直接进分析。

---

## 1. 数据从哪来、能留多久

| 项 | 说明 |
|---|---|
| 接口 | 营地回放分析接口（`/game/battleanalyze/old` 一系），按 `gameSvrId / relaySvrId / gameSeq` 取 |
| 落盘 | `data/official_replays/camp-<gameSeq>/`：`raw.json`（原始载荷）、`normalized.json`（平台解析后）、`positions.json`（逐秒坐标）、`meta.json`、`fields.json` |
| 保留期 | **营地只保留最近 31 天**。同步到边界后 `reachedWindow=true` 自动停；更早的局只能靠七图 + 录屏补录 |
| 同步入口 | 「采集 → 通道校对」挂营地链接；同步时自动拉回放并挂通道（v1.5.28） |
| 一局体积 | `raw.json` 约 0.6 MB（含 1 Hz 坐标时最大） |

**这条保留期直接决定分析口径**：跨局分析的时间范围默认就是"最近一个月"，不是产品选择，是数据边界。

---

## 2. 顶层结构

```text
{ result, returnCode, returnMsg, data }
data:
  playBaseInfoArr[]   十人基础 + 死亡坐标 + 高光标记
  keyEventArr[]       关键事件：资源/建筑（dragontower）、团战（battle）
  reportData          复盘叙述、逐秒位置、复活位置、野怪、技能
  camp1Gold           蓝方终局经济
  camp2Gold           红方终局经济
  camp1GoldArr[]      蓝方经济序列（约 30 秒一点）
  camp2GoldArr[]      红方经济序列（约 30 秒一点，**可能比蓝方多一个点**）
  ecoDistance[]       经济差序列 = camp1GoldArr − camp2GoldArr（已用 24 局逐点验证）
  highLightArr[]      高光数组（24 局中为空，暂不可用）
  extendEventArr[]    BUFF 击杀等扩展事件
  equipEvent[]        装备购买事件（仅 5/24 局有）
  matchInfo[]         十人终局面板（含营地自算五维）
  teamMatchInfo       队伍级信息（24 局均为 null）
  winCamp             胜方阵营："1"=蓝，"2"=红
  validNum            有效玩家数（正常 10）
  newGameReport       新复盘标记（1）
  disableSlice        禁用切片（0）
```

---

## 3. 分区块字段表

覆盖率写作 `局数/24`；「频次」是该字段在 24 局里出现的总条数（数组元素按条计）。

### 3.1 对局结论

| 路径 | 类型 | 覆盖 | 样例 | 含义 | 平台现状 |
|---|---|---|---|---|---|
| `data.winCamp` | str | 24/24 | `1` | 胜方阵营，1 蓝 2 红 | 已用 |
| `data.validNum` | num | 24/24 | `10` | 有效玩家数 | **未用**（可用作完整性校验） |
| `data.disableSlice` | num | 24/24 | `0` | 禁用切片标记 | **未用** |
| `data.newGameReport` | num | 24/24 | `1` | 新复盘格式标记 | **未用** |
| `data.teamMatchInfo` | null | 24/24 | — | 队伍级信息，样本里恒为 null | 不可用 |

### 3.2 经济序列（跨局分析的关键）

| 路径 | 类型 | 覆盖 | 频次 | 样例 | 含义 |
|---|---|---|---|---|---|
| `data.camp1Gold` | num | 24/24 | — | `39794` | 蓝方终局经济 |
| `data.camp2Gold` | num | 24/24 | — | `30550` | 红方终局经济 |
| `data.camp1GoldArr[]` | num[] | 24/24 | 656 | `2924, 4468, 5738…` | 蓝方经济序列 |
| `data.camp2GoldArr[]` | num[] | 24/24 | 657 | `2787, 4183, 5412…` | 红方经济序列 |
| `data.ecoDistance[]` | num[] | 24/24 | 656 | `137, 285, 326…` | **经济差序列 = 蓝 − 红** |

**精度与坑（必须知道）**：

- 序列长度 21–27 个点；660 秒的局约 21 点 → **间隔约 30–33 秒**，不是固定 30 秒，也不是 5 分钟。
- 两条序列**长度可能差 1**（例：21 对 22）。**逐点相减前必须先对齐长度**，不能直接 zip。
- 索引 0 是开局（总经济约 3000 = 5 人 × 初始金币），不是 0 秒采样点。
- 因此：**0–4 分钟只能插值到 ±15 秒**。写分析时必须标「约」。
- `data.camp1Gold/2Gold` 是终局值，和序列末点可能差几十金币，以序列末点为准时要说清。

**这条纠正了一个错误口径**：跨局向量曾把经济压成「每 5 分钟一个点」，那是平台自己丢的精度，**不是营地没有**。0–4 / 4–10 / 10+ 三段用插值就能算。

### 3.3 十人终局面板 `data.matchInfo[]`（10 条/局）

| 路径 | 类型 | 覆盖 | 样例 | 含义 |
|---|---|---|---|---|
| `[].playerId` | str | 24/24 | `898065045` | 营地角色 ID（跨局稳定） |
| `[].heroId` / `[].heroName` | num/str | 24/24 | `112` / `鲁班七号` | 英雄 |
| `[].heroIcon` / `[].heroPicUrl` | str | 24/24 | `https://…jpg` | 头像 |
| `[].acntcamp` | str | 24/24 | `1` | 阵营 |
| `[].killCnt` / `deadCnt` / `assistCnt` | str | 24/24 | `7` / `2` / `12` | K/D/A |
| `[].defeatAcntRatio` | str | 24/24 | `70` | 参团相关比例（营地口径，未公开分母） |
| `[].gametype` | str | 24/24 | `4` | 模式编码（4=排位） |
| `[].newGrow` | str | 24/24 | `8423` | **营地自算「成长」分** |
| `[].newBattle` | str | 24/24 | `9228` | **营地自算「团战」分** |
| `[].newSurvive` | str | 24/24 | `8640` | **营地自算「生存」分** |
| `[].newHurtHero` | str | 24/24 | `9019` | **营地自算「输出」分** |
| `[].newKDA` | str | 24/24 | `11623` | **营地自算「KDA」分** |
| `[].roleName` | str | 24/24 | 空 | 昵称，多数局为空（身份另走 `playBaseInfoArr`） |
| `[].roleId` / `[].userId` | str | 24/24 | 空 / `0` | 未填 |

> `newGrow/newBattle/newSurvive/newHurtHero/newKDA` 这五个分数**24 局全有，平台一个都没读**。
> 量纲未公开（样例在 8000–12000），只能同局同位置比较，不能跨英雄排名。

### 3.4 事件 `data.keyEventArr[]`（每局 40–60 条）

三类字段挂在同一条事件上：`eventType`、`dtData`（资源/建筑）、`battle` + `battleDetail`（团战）。

| 路径 | 类型 | 覆盖 | 频次 | 样例 | 含义 |
|---|---|---|---|---|---|
| `[].eventType` | str | 24/24 | 1472 | `dragontower` / `battle` | 事件类型 |
| `[].isKeyEvent` | num | 24/24 | 1472 | `0/1` | 是否关键事件 |
| `[].score` | num | 24/24 | 1472 | `0` | 事件权重（营地内部） |
| `[].extraFlag` | str | 24/24 | 1472 | 空 | 扩展标记 |

**资源 / 建筑（`dtData`）**

| 路径 | 类型 | 覆盖 | 频次 | 样例 | 含义 |
|---|---|---|---|---|---|
| `[].dtData.dtType` | str | 24/24 | 932 | `1` 资源 / `2` 建筑 | 事件大类 |
| `[].dtData.dtID` | str | 24/24 | 932 | `10/11/12…/8/9/17/20` | 具体资源/塔（映射见 `data/camp_labels.json`） |
| `[].dtData.dtCamp` | str | 24/24 | 932 | `2` | 资源/建筑的**所属方** |
| `[].dtData.killerCamp` | str | 24/24 | 932 | `1` | **获取方**（≠ 所属方） |
| `[].dtData.killerId` | str | 24/24 | 932 | `1073` | 获取者 objID → `playBaseInfoArr.inBattleObjID` |
| `[].dtData.killTime` | str | 24/24 | 932 | `660000` | 毫秒时间戳（局内毫秒） |
| `[].dtData.kills[].hurtTotal` | str | 24/24 | 1191 | `56058940` | 参战者伤害（量纲未证实，见 §6） |
| `[].dtData.kills[].camp/killerId/joinType` | str | 24/24 | 1191 | `1/1071/0` | 参战者与阵营 |

**团战（`battle` + `battleDetail`）**

| 路径 | 类型 | 覆盖 | 频次 | 样例 | 含义 |
|---|---|---|---|---|---|
| `[].battle.fightId` | str | 24/24 | 540 | `17` | 团战 ID |
| `[].battle.startTime/endTime` | str | 24/24 | 540 | `654000/660000` | 起止（毫秒） |
| `[].battle.camp1MemNum/camp2MemNum` | num | 24/24 | 540 | `5/2` | 双方参战人数 |
| `[].battle.firstKillerCamp` | str | 24/24 | 540 | `1` | 先手方 |
| `[].battle.joinMemInfo[]` | obj[] | 24/24 | 2767 | `objID/time/isBeginner` | 到位时间与先手标记 |
| `[].battle.killInfo[]` | obj[] | 24/24 | 868 | `killerObjID/objID/time/camp` | 击杀账本（切 C 用它） |
| `[].battleDetail[]` | obj[] | 24/24 | 2767 | 见下 | **团战级十人明细** |
| `battleDetail[].hurtTotal` | str | 24/24 | 2767 | `2583` | 团战内输出 |
| `battleDetail[].behurtTotal` | str | 24/24 | 2767 | `263` | 团战内承伤 |
| `battleDetail[].hardctrlTotal/softctrlTotal` | str | 24/24 | 2767 | `0/2112` | 硬控/软控 |
| `battleDetail[].therapicTotal` | str | 24/24 | 2767 | `0` | 治疗 |
| `battleDetail[].beginHP/endHP/lowHP` | str | 24/24 | 2767 | `5104/4312/4841` | 血量轨迹 |
| `battleDetail[].ultimateskillCnt` | str | 24/24 | 2767 | `1` | 大招次数（不是 CD） |
| `battleDetail[].killCnt/assistCnt/deadCnt` | str | 24/24 | 2767 | `0/2/0` | 团战内 KDA |

> 打团存活、团战伤害占比、先手方、人数差，全在这一块，已部分接入单局页。

### 3.5 扩展事件 `data.extendEventArr[]`（23/24 局）

| 路径 | 类型 | 覆盖 | 频次 | 样例 | 含义 |
|---|---|---|---|---|---|
| `[].eventList[].eventType` | str | 23/24 | 557 | `killbuff` | BUFF 被击杀 |
| `[].eventList[].dtData.dtType/dtID/dtCamp` | str | 23/24 | 557 | `1/11/2` | 红蓝 BUFF 归属 |
| `[].eventList[].dtData.killerCamp/killerId` | str | 23/24 | 557 | `1/3` | 击杀方 |
| `[].eventList[].dtData.killTime` | str | 23/24 | 557 | `41000` | 毫秒 |
| `[].eventTime` | num | 23/24 | 552 | `41000` | 事件毫秒 |

> **反野 / 被反 / BUFF 收野**就靠它，v1.5.23 已接入单局页，**还没进跨局**。

### 3.6 位置与死亡

| 路径 | 类型 | 覆盖 | 频次 | 样例 | 含义 |
|---|---|---|---|---|---|
| `data.playBaseInfoArr[].deathPosArr[].time` | str | 24/24 | 870 | `485` | 死亡时刻（**秒**） |
| `…deathPosArr[].coordX/coordY` | num | 24/24 | 870 | `27/-12` | 死亡坐标 |
| `data.playBaseInfoArr[].inBattleObjID` | str | 24/24 | 240 | `1071` | objID ↔ 英雄/玩家 的桥 |
| `data.playBaseInfoArr[].highlight.*` | str | 6–9/24 | 极少 | `1` | 高光标记（键是数字 ID，含义未证实） |
| `data.reportData.playerPosInfo[].posArr[][]` | num[][] | 24/24 | 400200 | `-53` | **逐秒坐标（1 Hz）**，十人约 1.6 万点/局 |
| `data.reportData.playerPosInfo[].revivePosArr[][]` | num[][] | 24/24 | 2271 | `-53` | 复活位置/时间 |
| `data.reportData.playerPosInfo[].playerID` | str | 24/24 | 240 | `898065045` | 与面板对齐用 |

> `posArr` 是跨局空间分析（路线、入侵、集结、热区）的唯一来源，**1 Hz**。
> `deathPosArr` 是 v1.5.x 之前一直没读的字段：**逐人死亡的时间+坐标，不用再从事件里反推**。

### 3.7 野怪 `data.reportData.emeryInfo[][]`（24/24 局，约 117 条/局）

样例：`["162324", 10, "1", 32, "36044", "-39242", "6"]`

前四列可读作 `objID / 野怪类型 / 阵营 / 时间(秒)`，后两列是坐标，末列含义未证实。
**24 局 24,976 条，平台一条都没读**——反野、控野区、打野路线都能从这里做。

### 3.8 复盘文案 `data.reportData.adviceList[]`（22/24 局）

| 路径 | 类型 | 覆盖 | 频次 | 样例 | 含义 |
|---|---|---|---|---|---|
| `[].time` | str | 22/24 | 397 | `654000` | 毫秒 |
| `[].fightId` | str | 22/24 | 397 | `17` | 关联团战 |
| `[].msg` | str | 22/24 | 397 | `恭喜赢得团战，主人斩获1个人头…` | **营地中文叙述** |
| `[].posX/posY` | num | 22/24 | 397 | `0/0` | 坐标（样本里恒为 0） |

> 每局约 16 条中文团战叙述，v1.5.23 已接入单局页，可直接改写成跨局的"复盘点"。

### 3.9 技能 `data.reportData.skillUsedInfo[]` / `skillConfList[]`

| 路径 | 类型 | 覆盖 | 频次 | 样例 | 含义 |
|---|---|---|---|---|---|
| `skillUsedInfo[].playerID` | str | 24/24 | 240 | `1153375288` | 玩家 |
| `skillUsedInfo[].skillUsedList[]` | list | 10/24 | 364 | `[15330, 89, 1, 0, 0]` | 技能释放记录（**多数局为空**） |
| `skillUsedList[].targetList[][]` | list | 6/24 | 2288 | `1799` | 命中目标 |
| `skillConfList[].iSkillId/szTitle` | num/str | 10/24 | 16 | `15330 / 秘技·隐匿` | 技能 ID → 中文名 |

> 覆盖只有 10/24，且 `skillUsedList` 常为空。**暂不作为分析依据**，等更大样本或换接口。

### 3.10 装备 `data.equipEvent[]`（仅 5/24 局）

| 路径 | 类型 | 覆盖 | 频次 | 样例 | 含义 |
|---|---|---|---|---|---|
| `[].eventTime` | num | 5/24 | 23 | 毫秒 | 购买时刻 |
| `[].equip[].equipId/equipName` | str | 5/24 | 23 | — | 装备 |
| `[].equip[].heros[].playerId/heroId/acntCamp/centerPos` | str | 5/24 | 23 | — | 谁买的 |

> 覆盖率太低（5/24），装备成型时间**还不能跨局用**。

---

## 4. 营地 H5 前端文案（`data/camp_labels.json`）

从营地 H5 前端包（`_h5/app.js`）抽出的 65 条中文文案，用来翻译 dtID 与事件：
「击败暴君 / 击败黑暗暴君 / 击败主宰 / 摧毁防御塔 / 摧毁水晶 / 上路 / 中路 / 下路 / 团战 / 击杀 / 死亡 / 生存 / 发育 …」。
生成命令：`python scripts/archive_camp_fields.py --labels-only`。
**改版先 diff 这份**，比等到界面上"读不出数"再查快。

---

## 5. 平台读到哪一步

| 区块 | 平台现状 |
|---|---|
| 经济序列 / 经济差 | 单局页已画；**跨局只保留 5 分钟采样 → 精度被平台丢掉** |
| 十人终局面板 | 已读（KDA、英雄、阵营） |
| 营地五维（newGrow 等） | **未读** |
| 资源 / 建筑事件 | 已读（控龙率、推塔） |
| 团战 battle / battleDetail | 已读（击杀账本、切 C、打团存活） |
| BUFF 事件 | 已读单局（反野/被反）；**未进跨局** |
| 逐秒位置 | 已读（热区、纵深、跑图） |
| 死亡坐标 deathPosArr | **未读**（现在从事件反推） |
| 野怪 emeryInfo | **未读** |
| 复盘文案 adviceList | 已读单局 |
| 技能 skillUsedInfo | **未读**（覆盖低） |
| 装备事件 | 部分读（5 局） |
| 高光 highLightArr | 空，不可用 |
| 前端文案 | 已归档 |

---

## 6. 未证实 / 待办

1. **`hurtTotal` 量纲**：同场里 800 与 2,100 万并存（`56058940`），单位未证实。
   现在只显示占比、不显示绝对值；跨局更不能用绝对值求和。
2. **`emeryInfo` 列序**：`objID / 类型 / 阵营 / 时间` 可信，末两列坐标与末列含义未验证。
3. **`newGrow…newKDA` 量纲**：8000–12000 区间，分母未公开，只做同位置比较。
4. **`defeatAcntRatio`**：营地口径，分母未知，不进评级。
5. **`skillUsedInfo` 覆盖 10/24**：要确认是"这几局没记录"还是"我们取数参数不同"。
6. **序列长度不等**（21 vs 22）：需要统一对齐规则并写进解析层，不能各页面自己 zip。
7. **`highlight.*` 的键**（1/9/11/25/122…）：未映射，可能是营地高光类型 ID。

---

## 7. 对口径的硬约束（写分析的人必须遵守）

1. **经济精度 = 约 30 秒**，任何"分钟级"结论都要标近似；不要按 5 分钟切段，
   教练的阶段是 **0–4 对线 / 4–10 发育 / 10 分钟后后期**。
2. **序列先对齐再算差**；长度不等时不补造，按较短长度截断并在页面上标覆盖。
3. **缺失不补 0**：没有该局回放就不进分母，页面写清"N 局里有 M 局可读"。
4. **营地没有的字段不硬造**：推塔/控龙能算，gank 次数、跨分路克制目前算不出。
5. 新增字段先登记到 `metrics_registry.py` 与本文件，再写页面。
