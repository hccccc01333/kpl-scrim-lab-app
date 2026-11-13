# 回放播放器（`.abc` / `.ope` 输入层）

日期：2026-11-13。范围：只读解码本地回放文件，不启动游戏、不读进程内存、不加载游戏库。

## 1. 它做什么

把一份 `.abc`（+ 可选 `.ope`）解码成 **逐秒状态文档** `kpl-replay-state-v1`，
再用浏览器页把它当作回放播放：

```text
.abc/.ope ──解码──▶ kpl-replay-state-v1 ──HTTP──▶ /static/player.html 播放
```

| 入口 | 位置 |
|---|---|
| 播放页 | `/static/player.html?replay=<回放ID>` |
| 状态接口 | `GET /api/replays/<回放ID>/state`（结果在内存缓存，`?rebuild=true` 强制重建） |
| 引擎 | `replay_state_engine.py` |
| 前端 | `v3/public/replay-player.js`、`v3/public/player.html` |
| 浏览器验收 | `python scripts/verify_replay_player.py --replay <回放ID>` |

## 2. 精确解出来的字段（file-decode）

| 字段 | 粒度 | 依据 |
|---|---|---|
| 十人名单：英雄 / 阵营 / 槽位 / entity / 电脑标记 | 每局 | 玩家块，逐字节 |
| 胜负、胜方 MVP、十人评分 | 每局 | 1251 `SCPKG_GAMEOVER_MVPSCORE` |
| 购买事件 | 帧级（≈1/15 s） | `BUYEQUIP` 帧命令 + 购买镜像 547 条 |
| 出装价格与装备名 | 对照表 | `pvp_item.json` / `agent_equip_prices.csv` |
| 技能加点事件 | 帧级 | `LEARNSKILL` 120 条 |
| 出装方案（每人 0–4 套：名称 + 12 件装备，对官方表命名） | 每局 | 玩家块尾 `roster_tail.py` |
| openid / 头像 URL / 平台身份 hash | 每人 | 玩家块尾 |
| 移动 / 攻击 / 技能 / 瞄准 | 帧级计数 + 逐秒聚合 | 帧命令流 10,509 条记录 |
| CC 指令同步 | 帧级计数，按内层指令拆分 | `CSDT_FRAPBOOT_CC`；**不是控制效果**，见下 |

### `CC` 不是「控制」

解码器把 `CSDT_FRAPBOOT_CC` 数据包归到 `cc` 家族，早先界面直接显示成「控制」，
这是**读错了**：`CC` 在这里是客户端指令同步包，内层指令是

| 内层字节 | 含义 |
|---|---|
| `2d` | 朝向 |
| `03` | 停止移动 |
| `2c` | 攻击落点 |
| `01` | 位置移动 |

本局「百里守约」名下 1,585 条 `cc` 实际是：朝向 1,364、停止 161、攻击落点 43、
其他 17 —— **没有一条是控制效果**。状态文档现在为每名玩家输出 `ccBreakdown`，
播放器把该列改名为「CC指令」并带说明，避免再被读成 crowd control。

| 稀疏坐标锚点 | 78 条 / 仅 2 名玩家 | `.abc` 位置消息；**不是轨迹** |
| 对局时长、总帧数、构建与版本 | 每局 | 回放头 |

## 2.5 逐块解码现状（2026-11-13 更新，全部量化）

同一份样本（`.abc` 482,967 B + `.ope` 113,178 B）逐字节核算：

| 区域 | 字节 | 现状 |
|---|---:|---|
| `.abc` 帧流 | 437,456 | 结构 100% 解开：10,509 条记录、88,627 条命令行、0 条未知 |
| `.abc` 玩家块 ×10 | 42,475（非零 8,969） | 身份/英雄/阵营/槽位/评分/**出装方案（名称+12 件装备，对官方表命名）**/openid/头像 URL/平台身份 hash 已解；剩余 ~6,700 非零字节是分散的小值计数与无名分段表（值全部可读，业务名需原生 CLevelContext 偏移） |
| `.ope` 操作流 | 237,556 | **已解**：31,109 条记录、237,556/237,556 字节严格布局解码到流尾（`mode=strict-layouts`）；0x00–0x19 全类型 + 新增 Common-2B / SendMsg-8B / SkillUse-2var / DirSkill-3var 形式（证据写在 `operator_stream.py` LAYOUTS 注释）；163751 流尾一条截断记录显式标记 |
| `.abc` 443 B 标量块 | 440 | 110 个 BE u32 全部解出；2 个锚点已命名（index 1=modeWord、index 67=服务器 Unix 时间）；95 常量 + 15 变量的业务名需原生结构对拍（`libil2cpp.so` 加壳，静态反汇编不可用） |
| `.abc` 配置 53 项 | 216 | key/value 100% 解出（u8 confType + u16BE value）；key 7=初始金币 300 已命名；全表语义需游戏 `Svr2GameCore` databin 表（本地无此文件，binary_format.md 5.16.6 开放项） |

三类残余的共同阻塞点：**语义命名需要原生结构或游戏数据表，二者都不在本地**
（`.so` 加壳、databin 未提取）。文件内可解的字节已全部解出；`coverage` 字段
逐块写明这个口径，避免把「没命名」误读成「没解出」。

### `.ope` 是怎么解的

不是「猜过去」，而是 opt-in 修复模式：
`operator_stream.parse_with_repair()` 在严格 DP 卡墙处做 ±4..+16 平移扫描，
选 DP 可达位置最远的候选，并把每个修复点（墙偏移、平移量、修复前后可达位置）
写进 `ope.repairs`；没有修复点时列表为空。unity 时钟审计（只统计确认的
`UnityFrameOpe` 且值 ≥1000）本样本下降 2 次，与 `docs/ope_stream.md` §7 的
修复预览一致。

修复后三份样本：

| 样本 | 记录 | 修复点 | 覆盖 | unity 下降 |
|---|---:|---:|---:|---:|
| 20261102_161129 | 18,694 | 6 | 100.000% | 2 |
| 20261102_163751 | 26,150 | 5 | 100.000% | 6 |
| 20261101_182452 | 9,301 | 0 | 99.998% | 18 |

`.ope` 只确认了 `frame` / `unityFrame` 两个字段名，其余字段名是推断的，
所以**不按秒分桶**、也不把 `.ope` 记录排成对局时间轴；这一步要等字段语义。

## 3. 推导出来的字段（derived，口径写在界面上）

| 字段 | 推导方式 | 边界 |
|---|---|---|
| 英雄等级 | `1 + 已发生的 LEARNSKILL 次数`，上限 15 | 加点漏记时会偏低；不插值补点 |
| 累计金币花费 | 首次出现的购买价累加（同一装备重复购买不重复计） | 是**支出账本**，不是收入；升级件会高估 |

界面上这两项都标为「推导」，不冒充实测。

## 4. 文件里没有、因此不画的字段

`removed` 不是「没解出来」，是容器里就没写：

| 字段 | 原因 |
|---|---|
| kills / deaths / assists 时间轴 | 回放只记录输入命令，没有击杀归属；只有 1251 的终局胜负/MVP/评分 |
| 金币收入 | 尾部购买镜像没有收入事件，重建不出收入账本 |
| HP | 容器无 HP 字段 |
| 连续轨迹 | 移动指令积分已实测判定为无预测力（残差/位移 0.94–1.00，`docs/abc_move_integration.md`） |

接口把这些原因写进 `missing`，播放器在页脚逐条列出，避免读者以为是渲染失败。

## 5. 状态文档结构

```jsonc
{
  "schema": "kpl-replay-state-v1",
  "source": { "abc_sha256": "...", "build": ["..."], "totalFrames": 10674,
              "frameHz": 15.0, "ope": "<matchId>" },
  "match":  { "durationSec": 701, "winningCamp": "blue",
              "mvpEntityId": 538, "scoreTable": [ ... ] },
  "players": [ { "entityId": 538, "hero": "关羽", "camp": 1, "team": "blue",
                 "rating": 13.1, "win": true, "mvp": true,
                 "purchaseCount": 15, "learnCount": 13,
                 "goldSpentFinal": 14280, "skillOrder": [1, 2, 1, 3, ...],
                 "loadoutPlans": [ { "name": "纯肉流",
                                     "items": [ { "id": 1701, "name": "学识宝石" }, ... ] } ] } ],
  "events":  { "purchases": [ { "t": 5.2, "entityId": 1760,
                                "equipId": 1701, "name": "神速之靴",
                                "price": 300, "tier": "decoded" } ],
               "learns": [ { "t": 3.6, "entityId": 1168, "slot": 1 } ] },
  "timeline": [ { "t": 0, "p": [ { "e": 296, "lv": 1, "gs": null,
                                   "m": 0, "a": 0, "s": 0, "c": 0, "am": 0 } ] } ],
  "tiers":   { "roster": "decoded", "goldSpent": "derived (...) ", ... },
  "missing": { "kills": "…", "hp": "…", ... }
}
```

逐秒网格用短键（`e/lv/gs/m/a/s/c/am`）压体积：单局约 450–570 KB。
一局冷启解码约 1–14 s（视文件大小），之后走内存缓存。

## 6. 边界与不做的事

- 不加载 `libGameCore.so` 等游戏二进制，不读游戏进程内存，不注入。
- 不把推导值写成实测：等级、花费带 `tier`，播放器显式标注。
- 不为了「看起来完整」补零或插值填 HP/KDA。
- `.ope` 是本地 POV 输入日志：记录类型与边界已严格解码到流尾（统计在 `ope` 块、
  播放页有专节），payload 字段名多为推断；它不是十人状态，也不排对局时间轴。

## 7. 复现

```powershell
# 单局生成状态文档
python replay_state_engine.py --abc "data\replays\samples\<局>.abc" --out data\replay-states

# 起工作台后看播放页
python server.py
# 浏览器打开 /static/player.html?replay=<回放ID>

# 浏览器验收（含截图）
python scripts/verify_replay_player.py --replay <回放ID>

# 引擎测试
python -m pytest tests/test_replay_state_engine.py -q
```
