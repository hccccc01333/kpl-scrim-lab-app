# 回放数据契约（`.abc` / `.ope` → 工作台）

**定位**：截图、表格、录像 OCR、运行时 JSONL 负责**终局表现**；
回放负责**身份、名单、胜负、MVP/评分、比赛元数据和事件锚点**。
回放不覆盖 KDA/经济/输出/承伤/参团，也不把部分金币/坐标当成终局面板。

## 1. 回放能交的三类数据

### A. 可直接使用（高置信）

- 比赛元数据：版本/build、日期（文件名）、mapType/mapId、录制账号、本地英雄、
  `totalFrameNum`、帧记录数、`.abc` SHA-256。
- 十人名单：阵营、真实槽位（`position`，0–4）、文件顺序（`order`）、
  entityId、昵称、英雄 ID/名称、电脑标记。
- 终局结果：胜方阵营、胜方 MVP、败方 MVP、十人评分（1251 包）。
- 配对证据：`.abc`/`.ope` 版本一致、录制者 32 位标签匹配。

### B. 过程证据（只能当锚点/实验数据）

- `0x85` BUYEQUIP：购买/装备变化时间线；条数、逐 entity、装备 ID；**不是金币流水，不是最终总经济**。
- `0x87` 技能升级：次数/时间；不是最终出装或技能等级面板。
- `0x82 kind=2` 英雄自身世界坐标的稀疏锚点（5.128）；kind 1/3 是瞄准/指针候选；都不是十人逐帧轨迹。
- `0x84` BASEATTACK、`0x81` USEDIRECTIONALSKILL、`0x1e` 命中、`0x1f/0x20` 高光、
  `0x80` 帧命令、`0x03` 存活 beacon；可用于输入/时间轴对齐，**不是死亡/KDA**。
- `CSDT_FRAPBOOT_INFO`/关键帧、`CSDT_FRAPBOOT_GAMEOVERNTF(bWinCamp)` 候选。
- `.ope` 本地操作流：触控/移动/技能/UI 事件；只代表本地录制者，当前在
  `0xEF` 处未完全解码。
- 最终 6 格装备成本：截图装备 ID × 装备买价，做严格一致性检查
  （`成本 < 面板累计金币`，9/10 通过；296 异常），不是逐笔购买/收入账本。
- 时间基准：15 帧/秒，`t ≈ (frame−F0)/15`，±1s（5.129）。

### C. 明确拿不到（不要从回放补）

- 终局 KDA、总经济、输出/承伤/治疗、参团率。
- 终局装备列表、技能命中率全量账本。
- 十人完整位置轨迹、团队击杀/比分。
- 精确比赛时长（帧数已知，帧率/时长换算未最终确认）。

原因：`.abc` 记录流是 1075 开局 + 1077 开战 + 帧记录 + 1251 MVP 评分；
**1082 完整结算包不在回放里**。终局面板必须来自截图/录像 OCR/运行时 JSONL。

## 2. 建议的回放源 JSON

以 `20261102_161129` 为例（节选，真实解析值）：

```json
{
  "source": "replay",
  "replayId": "d74c2bed9dc12ec6d23118fbb87b2a372993b358f1fec542ee492d580e0e64f4",
  "abcFileName": "20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc",
  "opeFileName": "20261102_161129_..._2B9FAA08A7AD40D09ABDA364F9C1E804.ope",
  "match": {
    "date": "2026-11-02",
    "versions": ["12.1.1.1", "12.1.1.26"],
    "builds": ["4989537", "5247758"],
    "mapType": 3,
    "mapId": 20111,
    "recorder": "漂流网咖︎",
    "localHero": "百里守约",
    "totalFrameNum": 10674,
    "frameRecords": 10509,
    "startTimeTicks": 639292319602028870
  },
  "result": {
    "winningCamp": "blue",
    "winMvp": {"entityId": 538, "nickname": "狂傲自由魂Z.", "hero": "关羽", "rating": 13.10},
    "loseMvp": {"entityId": 1031, "nickname": "麻巫喵", "hero": "公孙离", "rating": 5.90}
  },
  "players": [
    {"camp": "blue", "slot": 0, "order": 0, "entityId": 1168, "nickname": "胡不喜#", "hero": "钟馗", "heroId": 175, "bot": false, "rating": 8.40, "mvp": null},
    {"camp": "blue", "slot": 1, "order": 1, "entityId": 1613, "nickname": "自诩一棵葱", "hero": "妲己", "heroId": 109, "bot": false, "rating": 10.40, "mvp": null},
    {"camp": "blue", "slot": 2, "order": 2, "entityId": 750, "nickname": "别吃窝线吖a", "hero": "孙悟空", "heroId": 167, "bot": false, "rating": 9.10, "mvp": null},
    {"camp": "blue", "slot": 3, "order": 3, "entityId": 538, "nickname": "狂傲自由魂Z.", "hero": "关羽", "heroId": 140, "bot": false, "rating": 13.10, "mvp": "win"},
    {"camp": "blue", "slot": 4, "order": 4, "entityId": 1611, "nickname": "漂流网咖︎", "hero": "百里守约", "heroId": 196, "bot": false, "rating": 10.60, "mvp": null},
    {"camp": "red", "slot": 0, "order": 5, "entityId": 1031, "nickname": "麻巫喵", "hero": "公孙离", "heroId": 199, "bot": false, "rating": 5.90, "mvp": "lose"},
    {"camp": "red", "slot": 1, "order": 6, "entityId": 296, "nickname": "翳灵崽", "hero": "吕布", "heroId": 123, "bot": false, "rating": 5.40, "mvp": null},
    {"camp": "red", "slot": 2, "order": 7, "entityId": 551, "nickname": "一风舞", "hero": "貂蝉", "heroId": 141, "bot": false, "rating": 5.50, "mvp": null},
    {"camp": "red", "slot": 3, "order": 8, "entityId": 1799, "nickname": "扁鹊耳垂", "hero": "兰陵王", "heroId": 153, "bot": false, "rating": 3.60, "mvp": null},
    {"camp": "red", "slot": 4, "order": 9, "entityId": 1760, "nickname": "谜语星海", "hero": "张良", "heroId": 156, "bot": false, "rating": 4.90, "mvp": null}
  ],
  "partial": {
    "buyEventsRaw": 547,
    "buyUniqueItems": 135,
    "skillUpgrades": 120,
    "positionSamples": 78
  },
  "evidence": {
    "abcSha256": "d74c2bed9dc12ec6d23118fbb87b2a372993b358f1fec542ee492d580e0e64f4",
    "pairing": "recorder-tag-matched",
    "scoreTableOffset": 482879,
    "parserVersion": "observed-12.1.1.x-v3",
    "opeStatus": "operator-stream-undecoded-at-0xEF"
  }
}
```

第二局同结构：胜方蓝、胜方 MVP 1367 漂流网咖︎/百里守约 11.00、
败方 MVP 1279 南巷丶转转儿/钟馗 12.00，帧记录 15,379。

## 3. 与采集通道字段的对应

| 工作台字段 | 回放能否提供 | 说明 |
|---|---|---|
| `hero` / `nickname` / `camp` / `slot` | ✅ 直接 | `slot` 用 `position`，不是 `order` |
| `entityId` / `bot` | ✅ 直接 | 用于跨来源身份对齐 |
| `rating` | ✅ 直接 | 1251 的十人评分；**回放唯一能补的核心表现字段** |
| `match.version` | ✅ 直接 | `12.1.1.26 / 5247758` |
| `match.date` | ✅ 文件名 | 头部 `startTimeTicks` 仅作候选，未确认时区/时钟 |
| `result` / `winMvp` / `loseMvp` | ✅ 直接 | 建议新增到 `draft.match` 或顶层 `result` |
| `kills/deaths/assists` | ❌ | 截图/表格/录像/运行时 |
| `gold`（总经济） | ❌ | 回放没有金币余额/逐笔收入；`0x85` 是 BUYEQUIP，unique 标价和也不是花费。只能用最终 6 格装备成本与外部面板做交叉校验 |
| `damage/taken` | ❌ | 截图/录像/运行时 |
| `participation` | ❌ | 截图/录像/运行时 |
| `match.scores`（团队击杀） | ❌ | 截图/录像 |
| `match.durationSec` | ◐ | 帧数已知；精确秒数未最终确认 |
| 十人位置轨迹 | ◐ | `0x82` 只是部分样本，不是连续轨迹 |

## 4. 当前接入状态

`channel_store.attach_replay` 已按本契约接入：

1. `slot` 取 `block['position']`（真实槽位），`order` 只保留为文件顺序。
2. roster 已补 `camp`、`nickname`、`entityId`、`bot`、`rating`。
3. `sources.replay.match` / `sources.replay.result` 已写入版本、
   mapType/mapId、胜方、胜/败方 MVP、`totalFrameNum`、帧记录数。
4. `_merge_replay_identity` 用 camp+slot 填昵称/英雄/entityId；
   `_merge_replay_rating` 只在截图/表格没有评分时补 `rating`，
   不覆盖已有评分。
5. `bundle` 的 `match` 已带 `result`/`replay` 摘要，player 带
   `replayEntityId`/`replayBot`。
6. `buyEventsRaw`/`buyUniqueItems`/`skillUpgrades`/`positionSamples` 仍只放
   `partial`/`evidence`，不写进 `final.totalGold` 或 `player.fields.gold`；
   `goldEventTotal` 已废弃（错位字段）。

## 5. `.ope` 的定位

`.ope` 是录制者本地的操作流（触控、移动、技能、UI），不是十人状态。
当前新构建在偏移 `0x1B` 命中类型 `0xEF`，解析未完成。它适合做：

- 本地 POV 的操作时间轴、APM、技能按钮使用习惯；
- 与 `.abc` 录制者标签/对局 ID 做同局配对；
- 过程复盘的操作事件锚点。

不适合做：十人 KDA、经济、伤害、承伤、参团、位置轨迹。

## 6. 结论

回放不是“终局面板”的来源，但它是**名单/身份/胜负/MVP/评分/元数据**的
最强来源。你们截图/录像 OCR 已经覆盖终局表现，回放正好补上：

- 十人名单从候选变成 10/10 确定；
- 胜负、胜方 MVP、败方 MVP、十人评分；
- 录制账号、本地英雄、版本、地图、帧数、同局配对；
- 过程时间轴的技能升级/金币/单位死亡/位置锚点。

这样截图/录屏负责“打得好不好”，回放负责“是谁、哪一局、谁赢、MVP 是谁”，
两者不抢字段。
