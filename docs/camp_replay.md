# 王者营地官方回放链接导入

赛训组只需提供一条 `camp.qq.com` 回放链接，工作台就能提取官方公开数据。它是当前采集流程的**唯一必采来源**，提供官方过程数据；终局十人数值由营地自动同步的 `battledetail` 面板补齐（推荐主路径）。七张结算截图与一段完整录屏只在传统兜底路径下才需要，不再按局必采。链接获取步骤、格式示例和错误示例见 [采集 SOP](collection_sop.md)。

## 支持什么链接

```text
# 标准网页回放
https://camp.qq.com/h5/webdist/battle-replay/index.html?
  isNavigationBarHidden=1&gameseq=...&relaysvrentity=...&gamesvrentity=...
  &playerid=... [&kplMatchFlag=1&eId=...&mId=...] [&betaFlag=1]

# 微信分享短链（选手转发战绩卡片得到）
https://cu.qq.com/xxxxxx    → 302 → camp.qq.com/h5/webdist/mp-redirect/index.html?
  userId=...&roleId=...&router=battleDetail&gameSeq=...
  &relaySvrId=...&battleType=16&gameSvrId=...&pvpType=5&ca_...
```

### 微信分享链（2026-11-04 实测）

选手在营地 APP 里把一局分享到微信，复制出来是 `cu.qq.com` 短链。它的 302
一跳就落到**公开的** `camp.qq.com` 页面，四个参数都在地址里：

| mp-redirect 字段 | 对应回放参数 |
| --- | --- |
| `gameSeq` | `gameSeq` |
| `gameSvrId` | `gameSvr` |
| `relaySvrId` | `relaySvr` |
| `userId` | `playerId` |

- **不需要微信客户端、不需要登录、不需要抓包**，`import_link()` 会先展开短链再解析。
- `userId`（营地账号 ID，9 位）和 `playerId`（游戏侧 ID，19 位）不同，但接口
  **不校验 playerId**：同一局用两者请求，返回都是 `code=0`、141,623 字节、内容一致。
- `battleType` / `pvpType` **只在链接上，接口返回里没有**，已随 meta 保存，
  可用于区分模式（排位样本 `battleType=16`、`pvpType=5`；训练赛取值待样本确认）。
- 只有 `servicewechat.com/wxascheme/...` 和 `#小程序://王者营地/xxx` 这两种还原不了：
  参数不在文本里，只能由微信客户端打开。
- 短链来自“逐局转发”，**不提供战绩列表**。批量枚举仍无公开接口。

## 公开接口

工作台根据链接参数选择：

| 类型 | 接口 |
| --- | --- |
| 个人回放 | `POST https://kohcamp.qq.com/game/battleanalyze/old` |
| KPL | `POST https://kohcamp.qq.com/game/kplbattleanalyze/old` |
| Beta | `POST https://kohcamp.qq.com/game/betabattleanalyze/old` |

个人回放请求体：

```json
{
  "cSystem": "unknown",
  "h5Get": 1,
  "gameSeq": "1793606215",
  "gameSvr": "95868",
  "playerId": "3686206139544504830",
  "relaySvr": "870343216"
}
```

KPL 额外带 `eId` / `mId`。请求头 `h5get: 1`、`noencrypt: 1`、`content-type: application/json`、`referer: https://camp.qq.com/`。

## 能提取什么

- 比赛：胜方、双方比分（KPL）、团队最终金币、时长。
- 经济：约 **30 秒一个点**的团队金币和经济差。
- 事件：关键事件（龙 / 塔 / 野怪 buff）、扩展事件、装备事件。
- 团战与击杀：`keyEventArr[eventType=battle]` 里的 `battle.killInfo` 是**逐次英雄击杀流水**
  （击杀者、被击杀者、双方阵营、毫秒级时刻），逐局与终局面板总击杀数一致；
  `battleDetail` 是团战窗口内逐人的输出、承伤、控制、治疗与 K/D/A；
  `playBaseInfoArr[].deathPosArr` 是逐人死亡坐标 + 秒级时间。
- 选手：英雄、K/D/A、页面评分。
- 位置：每人逐秒坐标（个人回放 693 点/人，KPL 1287 点/人）。

`battle` 事件没有 `dtData`（只有 `dragontower` 有），必须走 `battle` / `battleDetail`
分支解析；早期版本把 504 场团战压成了 `timeSec=0 / kills=[]`，现已修复。
历史回放可用 `python tools/rebuild_camp_battles.py` 从本地 `raw.json` 幂等重建
（支持 `--dry-run`，写入前备份 `normalized.json`），结果落在 `normalized.json['battles']`。

## 不能提取什么

- **1 秒金币**：接口只有约 30 秒的点。把 23 个点插值成 1 秒只是画线，不是实测。
- **逐人全局原始输出 / 承伤 / 总经济**：接口只给团队金币和页面 KDA/评分；
  `battleDetail` 只覆盖团战窗口，不能当作全局伤害，也不能与结算面板数值混算。
- 需要登录的营地数据（比赛历史、选手主页、赛季统计等）不在这里；不要绕过微信/QQ 登录，使用公开链接或赛训组自己导出的数据。

## 工作台入口

「数据 → 采集」→ 打开一局 → “王者营地链接（必需）”：粘贴链接 → **提取并关联**。

- 提取结果存放在 `data/official_replays/<camp-gameseq>/`：`raw.json`、`normalized.json`、`positions.json`、`meta.json`。
- 关联后写入本局通道的 `official` 字段，参与必采来源状态；成功提取并关联才算完成。
- 保存比赛时：
  - `team.timeline` 使用官方 30 秒金币曲线（`timelineSource = official-30s`）；
  - 原来的录屏 4 秒曲线保留在 `team.recordingTimeline`；
  - `team.officialEvents` 保存事件；
  - `team.positions` 记录逐秒位置文件；
  - `match.officialReplay` 保存胜方、团队金币、点数、位置摘要；
  - 终局 KDA/经济/伤害/承伤仍来自截图/回放。
- 再次提取同一 `gameseq` 会使用缓存；需要刷新时传 `force` 或删除对应目录。

## CLI

```powershell
python scripts/import_camp_replay.py "https://camp.qq.com/h5/webdist/battle-replay/...?gameseq=..."
python scripts/import_camp_replay.py "<link>" --force --json
```

## API

```text
POST /api/official/replay                 {"url": "...", "force": false}
GET  /api/official/replays
GET  /api/official/replays/{id}
GET  /api/official/replays/{id}/positions
POST /api/channels/{channelId}/official   {"officialId": "camp-..."}
```

## 11/2 本地样本与对拍

`data/official_replays/camp-1793606215/` 已保存 11/2 第一局（`20261102_161129`）
的营地数据，不需要重新请求链接：

- 官方团队金币 41,021 / 29,266；面板 10 人求和 41,000 / 29,248，差 21/18g；
- 官方 KDA 与面板 10/10 一致；
- `positions.json` 提供 10 人 × 693 个逐秒网格坐标（`[-57,57]`），
  用于走位/距离/区域热图，不是逐帧轨迹；
- 23 个团队金币点约为 30 秒一个，不是 1 秒，也不是逐人金币。

对拍脚本/产物：`tools/build_20261102_official_join.py`、
`datasets/20261102_official_join.md`、`20261102_official_players.csv`、
`20261102_official_positions.csv`、`20261102_official_team_gold.csv`。

## 边界

- 这是公开接口，不是登录态爬虫；接口可能改版或限流，失败时保留原数据并报错。
- 个人回放的玩家昵称、KDA、评分可作为核对；不能据此自动确定本队阵营，仍需工作台确认。
- KPL 链接数据不能混入训练赛统计；工作台会标记 `kind = kpl`。
- `official_replays` 目录是原始数据证据，不进入 SQLite/JSON 备份；需要时单独备份该目录。
