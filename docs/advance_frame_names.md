# AdvanceFrameCommands 27 类命令命名（离线静态分析）

日期：2026-11-03。样本：王者 12.1.1.1 / Res 12.1.1.26，build 5247758，
本地 `global-metadata.dat` + `libil2cpp.so`。只做静态分析；未启动/连接游戏、
未登录、未注入、未读取/修改 `.ope`。

结论先行：

> **`frapInfo` 命令对象 `+0xc` 的 1..27 不是 TDR selector，也不是
> `FRAME_CMD_INFO` 的 143 个成员索引，而是
> `CSProtocol.BOOTFRAP_TYPEDEF` 的枚举值 1..27。**
> 这 27 个值就是 `CSDT_FRAPBOOT_DETAIL.bType`（回放/boot 记录类型），
> 每一类对应一个 `CSDT_FRAPBOOT_*` 载荷结构；其中 18/19/20 分别是
> PLAYER_MOVE / PLAYER_ATTACK / PLAYER_ATTACKWITHOBJ。

直接证据来自四处，互相闭合：

1. 开关边界 `sub w8,w8,#1; cmp w8,#0x1a; b.hi skip` 只接受 1..27；
2. metadata 的 `BOOTFRAP_TYPEDEF` 恰好有 0..27 共 28 个值（`MAX=28`），名字齐全；
3. 每个 processing function 读取的 payload 偏移（payload 基址 `+0xc`）逐字段
   命中对应 `CSProtocol.CSDT_FRAPBOOT_*` 的字段偏移；
4. 对应的 `Assets.Scripts.GameLogic.*Command` 类字段名/类型与 wire 结构逐字段一致
   （如 `PlayerSCMoveDirCommand.info:u16` ↔ `CSDT_FRAPBOOT_PLAYER_MOVE.wMoveInfo:u16`）；
   并且 `.abc` 侧 BOOT tag 18/19/20 已经独立解出 `wMoveInfo` / `bAttack` /
   `bAttack+wObjID`（见 `docs/packed_inputs.md`）。

## 1. 命名表（type 1..27）

`FRAME_CMD` 列指完整客户端命令（`CSProtocol.FRAMECMD_ID_DEF` /
`CSProtocolWrapper.FRAME_CMD_INFO`）里的对应项；boot 记录是压缩/通知层，
不一定逐条等于完整命令。

| type | `BOOTFRAP_TYPEDEF` | `CSDT_FRAPBOOT_*` 载荷 | 处理 | payload 读取（`+0xc` 起） | 候选 C# 类 | 对应完整命令 | 置信度 |
|---:|---|---|---|---|---|---|---|
| 1 | `BOOTFRAP_TYPE_CC` | `CSDT_FRAPBOOT_CC` | handler | child `+0x10` (`stSyncInfo`) | (CC 帧命令批容器) | 多条 CC 命令 / `compressInfo_*` | 中 |
| 2 | `BOOTFRAP_TYPE_CS` | `CSDT_FRAPBOOT_CS` | handler | `u16 +0xc` (`wObjID`)，child `+0x10` | (CS 帧命令批容器) | 多条 CS 命令 | 中 |
| 3 | `BOOTFRAP_TYPE_ACNTSTATECHG` | `CSDT_FRAPBOOT_ACNTSTATE` | handler | 复杂路径 | `SvrRunawayCommand` / `SvrDisconnectCommand` / `SvrReconnectCommand`（`FRAME_EXTEND_QUIT` 还可能走 `SvrNtfPlayerQuitFrameExtendCommand`） | 账号状态通知（`CS_FRAPBOOT_ACNTSTATE_*`） | 高 |
| 4 | `BOOTFRAP_TYPE_ASSISTSTATECHG` | `CSDT_FRAPBOOT_ASSISTSTATE` | handler | 复杂路径 | `AssistStateChgCommand` | 辅助状态变更 | 高 |
| 5 | `BOOTFRAP_TYPE_AISTATECHG` | `CSDT_FRAPBOOT_AISTATE` | handler | `u8 +0xc` (`bType`), `u32 +0x10` (`dwPlayerObjID`) | `AutoAIChgCommand` | `FRAME_CMD_SWITCHAOUTAI` / `FRAMEPKG_CMD_SWITCH_AI` / `stCmdPlayerSwithAutoAI` | 高 |
| 6 | `BOOTFRAP_TYPE_GAMEOVERNTF` | `CSDT_FRAPBOOT_GAMEOVERNTF` | handler | `u8 +0xc` (`bWinCamp`) | `SvrNtfGameOverCommand` | 胜负通知 | 高 |
| 7 | `BOOTFRAP_TYPE_PAUSE` | `CSDT_FRAPBOOT_PAUSE` | handler | `u8 +0xc/+0xd`, ptr `+0x10` (`szCampPauseNum`) | `PauseResumeGameCommand` / `PauseResumeGameCCCommand` | `FRAME_CMD_PAUSE_RESUME_GAME` / `stCmdPauseResumeGame` | 高 |
| 8 | `BOOTFRAP_TYPE_CAMPSTATE` | `CSDT_FRAPBOOT_CAMPSTATE` | handler | `u8 +0xc` (`bCamp`), `u8 +0xd` (`bState`) | `CampStateCommand` | 阵营状态通知 | 高 |
| 9 | `BOOTFRAP_TYPE_CAMP_SURRENDER` | `CSDT_FRAPBOOT_CAMP_SURRENDER` | handler | `u8 +0xc` (`bCamp`) | `CampSurrenderCommand` | 投降通知 | 高 |
| 10 | `BOOTFRAP_TYPE_MOVETOBORN` | `CSDT_FRAPBOOT_MOVETOBORN` | default | 通用路径 | `SvrNtfTransportCmd`（候选） | 传送/回出生点通知 | 中 |
| 11 | `BOOTFRAP_TYPE_QUITBATTLENTF` | `CSDT_FRAPBOOT_QUITBATTLENTF` | handler | `u32 +0x10` (`dwObjID`), `u32 +0x14` (`dwTimes`) | `SvrNtfPlayerQuitBattleCmd` | 退出战斗通知 | 高 |
| 12 | `BOOTFRAP_TYPE_BORNFOLLOW` | `CSDT_FRAPBOOT_BORNFOLLOW` | default | 通用路径 | `SvrNtfPlayerBornFollowCmd` | 出生跟随通知 | 高 |
| 13 | `BOOTFRAP_TYPE_PVEOBJNTF` | `CSDT_FRAPBOOT_PVEOBJNTF` | default | 通用路径 | `PVEObjNtfCommand` | PVE 对象通知 | 高 |
| 14 | `BOOTFRAP_TYPE_CUSTOMROOM_EFFECT` | `CSDT_FRAPBOOT_CUSTOMROOM_EFFECT` | handler | `+0x14 len1/+0x18 str1/+0x20 len2/+0x28 str2/+0x30.. ints/+0xc effectID` | `CustomEffectCommand` | 自定义房间特效 | 高 |
| 15 | `BOOTFRAP_TYPE_AUTOCHESSBOUNTYMATCH_ADDCOIN` | `CSDT_FRAPBOOT_AUTOCHESS_BOUNTYMATCH_ADDCOIN` | skip | 不处理 | (仅自走棋模式) | 自走棋赏金加币 | 高 |
| 16 | `BOOTFRAP_TYPE_BEGIN_FRAME_EXTEND` | `CSDT_FRAPBOOT_BEGIN_FRAME_EXTEND` | handler | `u8 +0xc` (`bWinCamp`) | `SvrNtfBeginFrameExtendCommand` | 开始帧延长 | 高 |
| 17 | `BOOTFRAP_TYPE_USE_PAINT` | `CSDT_FRAPBOOT_USE_PAINT_NTF` | handler | `u32 +0xc` (`dwObjID`), `u32 +0x10` (`dwPaintID`) | `PlayPaintCommand` | `FRAME_CMD_PLAYER_SET_PAINT` / `stCmdPlayerSetPaint`（输入对侧） | 高 |
| 18 | `BOOTFRAP_TYPE_PLAYER_MOVE` | `CSDT_FRAPBOOT_PLAYER_MOVE` | handler | `u16 +0xc` (`wMoveInfo`) | `PlayerSCMoveDirCommand` | `FRAME_CMD_PLAYERMOVE` / `FRAMEPKG_CMD_PLAYERMOVE` / `stCmdPlayerMove` | 高 |
| 19 | `BOOTFRAP_TYPE_PLAYER_ATTACK` | `CSDT_FRAPBOOT_PLAYER_ATTACK` | handler | `u8 +0xc` (`bAttack`) | `PlayerSCCommonAttackCommand` | `FRAME_CMD_PLAYCOMMONATTACKTMODE` / `FRAMEPKG_CMD_PLAYCOMMONATTACKTMODE` / `stCmdPlayCommonAttackMode` | 高 |
| 20 | `BOOTFRAP_TYPE_PLAYER_ATTACKWITHOBJ` | `CSDT_FRAPBOOT_PLAYER_ATTACKWITHOBJ` | handler | `u8 +0xc` (`bAttack`), `u16 +0xe` (`wObjID`) | `PlayerSCCommonAttackCommand` | `FRAME_CMD_ATTACKACTOR` / `FRAMEPKG_CMD_ATTACKACTOR` / `stCmdPlayerAttackPlayer` | 高 |
| 21 | `BOOTFRAP_TYPE_PLAYER_SAME` | (未找到结构) | skip | 不处理 | (未解) | (无) | 未解 |
| 22 | `BOOTFRAP_TYPE_PLAYER_CHANGE` | `CSDT_FRAPBOOT_PLAYER_CHANGE` | handler | 16 字段复杂路径 | `PlayerChangeCommand` | 玩家信息变更 | 高 |
| 23 | `BOOTFRAP_TYPE_REQ_QUITBATTLE` | `CSDT_FRAPBOOT_REQ_QUITBATTLE` | handler | `u32 +0x10` (`dwObjID`), `u32 +0x14` (`dwTimes`) | `SvrNtfPlayerReqQuitBattleCmd` | 请求退出战斗通知 | 高 |
| 24 | `BOOTFRAP_TYPE_SWITCH_CONTROL_OBJ` | `CSDT_FRAPBOOT_SWITCH_CONTROL_OBJ` | handler | 复杂路径 | (未找到 GameLogic 类；wire-only) | 切换控制对象；CS 侧有 `CSPKG_SWITCH_CONTROL_OBJ_REQ` | 中 |
| 25 | `BOOTFRAP_TYPE_GAMEPLAY_GOAL_SYSTEM_GEM_EFFECT` | `CSDT_FRAPBOOT_GAMEPLAY_GOAL_SYSTEM_GEM_EFFECT` | skip | 不处理 | (玩法目标系统专用) | 宝石特效通知 | 高 |
| 26 | `BOOTFRAP_TYPE_IN_BATTLE_EFFECT_BUY` | `CSDT_FRAPBOOT_IN_BATTLE_EFFECT_BUY` | default | 通用路径 | `InBattleEffectBuyCommand` | 战斗内效果购买 | 高 |
| 27 | `BOOTFRAP_TYPE_INGAME_ITEM_USE` | `CSDT_FRAPBOOT_INGAME_ITEM_USE` | handler | `u32 +0xc` (`dwObjID`), child `+0x10` (`stItemInfo`: `u32 +0x10/+0x14`) | `InGameItemUseCommand` | 局内道具使用 | 高 |

机器可读版本：`data/replays/_analysis/datasets/advance_frame_names.csv`
（含 handler/processing 地址、`CSDT` 字段表、自动对拍的字段、证据文本）。

## 2. 证据链

### 2.1 开关只接受 1..27

实现 static VA `0x664cf7c`（runtime `0x40002c84cf7c`，thunk file `0x6e04fa4`）
在读取 `command+0xc` 的 u8 后：

```text
sub  w8, w8, #1
cmp  w8, #0x1a        ; 26
b.hi skip
adr  x9, #jump_table
ldrh w10, [x27, x8, lsl #1]
add  x9, x9, w10, lsl #2
br   x9
```

即 type 0 和 type>27 被跳过，type 1..27 进 27 项跳表。跳表 27 项在
file `0x19be5ac`，与 `BOOTFRAP_TYPEDEF` 的 `0..27`（`MAX=28`）严格对应。

### 2.2 `BOOTFRAP_TYPEDEF` 就是 boot 记录 selector

metadata `CSProtocol.BOOTFRAP_TYPEDEF`（type index 19653，30 个字段）：

```text
value__ = None
BOOTFRAP_TYPE_NULL                 = 0
BOOTFRAP_TYPE_CC                   = 1
BOOTFRAP_TYPE_CS                   = 2
BOOTFRAP_TYPE_ACNTSTATECHG         = 3
...
BOOTFRAP_TYPE_PLAYER_MOVE          = 18
BOOTFRAP_TYPE_PLAYER_ATTACK        = 19
BOOTFRAP_TYPE_PLAYER_ATTACKWITHOBJ = 20
...
BOOTFRAP_TYPE_INGAME_ITEM_USE      = 27
BOOTFRAP_TYPE_MAX                  = 28
```

`CSProtocol.CSDT_FRAPBOOT_DETAIL` 的定义是 `bType:u8 + stDetail:union`。
运行时命令对象 `command+0xc` 是 bType、`command+0x10` 是 stDetail，正好对应
`BOOTFRAP_TYPEDEF` 与 `CSDT_FRAPBOOT_*`。

### 2.3 processing function 的字段偏移逐字段命中

payload 基址固定为 `+0xc`（原生命令对象前 12 字节是头）。自动对拍结果：

| type | 观察到 | `CSDT_FRAPBOOT_*` 字段 | 结论 |
|---:|---|---|---|
| 5 | `u8 +0xc`, `u32 +0x10` | `bType`, `dwPlayerObjID` | 精确 |
| 6 | `u8 +0xc` | `bWinCamp` | 精确 |
| 7 | `u8 +0xc/+0xd`, `ptr +0x10` | `bType`, `bCamp`, `szCampPauseNum` | 精确 |
| 8 | `u8 +0xc/+0xd` | `bCamp`, `bState` | 精确 |
| 9 | `u8 +0xc` | `bCamp` | 精确 |
| 11 | `u32 +0x10/+0x14` | `dwObjID`, `dwTimes` | 精确 |
| 16 | `u8 +0xc` | `bWinCamp` | 精确 |
| 17 | `u32 +0xc/+0x10` | `dwObjID`, `dwPaintID` | 精确 |
| 18 | `u16 +0xc` | `wMoveInfo` | 精确 |
| 19 | `u8 +0xc` | `bAttack` | 精确 |
| 20 | `u8 +0xc`, `u16 +0xe` | `bAttack`, `wObjID` | 精确 |
| 23 | `u32 +0x10/+0x14` | `dwObjID`, `dwTimes` | 精确 |
| 27 | `u32 +0xc`, child `+0x10` | `dwObjID`, `stItemInfo` | 精确 |
| 14 | `len +0x14`, `str +0x18`, `len +0x20`, `str +0x28`, `ints +0x30..` | `dwStrParam1Len/szStrParam1/dwStrParam2Len/szStrParam2/iIntParam1..5` | 字段顺序一致；后段偏移受 string 布局影响，见 CSV |

类型 18/19/20 的 `+0xc` 读取与 `docs/packed_inputs.md` 的 `.abc` BOOT 记录完全一致：
`BOOTFRAP_TYPE_PLAYER_MOVE=18 → wMoveInfo:u16`，`PLAYER_ATTACK=19 → bAttack:u8`，
`PLAYER_ATTACKWITHOBJ=20 → bAttack:u8 + wObjID:u16`。这是独立于 libil2cpp 的第二条证据链。

### 2.4 C# 命令类字段对拍

`Assets.Scripts.GameLogic` 下 186 个带 `OnReceive/TransProtocol/ExecLocal`
的命令类里，以下类的字段与 wire 结构逐字段一致（metadata 字段名/类型）：

| boot 类型 | candidate C# 类 | metadata 字段 | wire 字段 |
|---|---|---|---|
| 5 AISTATECHG | `AutoAIChgCommand` | `m_autoType:u8`, `m_playerID:u32` | `bType`, `dwPlayerObjID` |
| 6 GAMEOVERNTF | `SvrNtfGameOverCommand` | `m_bWinCamp:u8` | `bWinCamp` |
| 7 PAUSE | `PauseResumeGameCommand` | `PauseCommand:u8`, `PauseByCamp:u8`, `CampPauseTimes` | `bType`, `bCamp`, `szCampPauseNum` |
| 8 CAMPSTATE | `CampStateCommand` | `camp:u8`, `state:u8` | `bCamp`, `bState` |
| 9 CAMP_SURRENDER | `CampSurrenderCommand` | `camp:u8` | `bCamp` |
| 11 QUITBATTLENTF | `SvrNtfPlayerQuitBattleCmd` | `playerId:u32`, `times:u32` | `dwObjID`, `dwTimes` |
| 12 BORNFOLLOW | `SvrNtfPlayerBornFollowCmd` | `playerId`, `followPlayerId`, `state` | `dwObjectID`, `dwFollowObjID`, `bState` |
| 13 PVEOBJNTF | `PVEObjNtfCommand` | `m_playerId`, `m_dieOrRevive`, `m_CouponsReviveCnt` | `dwObjID`, `bDieOrRevive`, `bCouponsReviveCnt` |
| 14 CUSTOMROOM_EFFECT | `CustomEffectCommand` | `m_effectID`, `m_strParam1/2`, `m_intParam1..5` | `dwEffectID`, `szStrParam1/2`, `iIntParam1..5` |
| 16 BEGIN_FRAME_EXTEND | `SvrNtfBeginFrameExtendCommand` | `m_bWinCamp` | `bWinCamp` |
| 17 USE_PAINT | `PlayPaintCommand` | `paintId`, `positionX/Y/Z` | `dwPaintID`, `iPositionX/Y/Z` |
| 18 PLAYER_MOVE | `PlayerSCMoveDirCommand` | `info:u16` | `wMoveInfo:u16` |
| 19 PLAYER_ATTACK | `PlayerSCCommonAttackCommand` | `start:u8` | `bAttack:u8` |
| 20 PLAYER_ATTACKWITHOBJ | `PlayerSCCommonAttackCommand` | `start:u8`, `objID:u16` | `bAttack:u8`, `wObjID:u16` |
| 22 PLAYER_CHANGE | `PlayerChangeCommand` | `data:struct` | `CSDT_FRAPBOOT_PLAYER_CHANGE` |
| 23 REQ_QUITBATTLE | `SvrNtfPlayerReqQuitBattleCmd` | `playerId`, `times` | `dwObjID`, `dwTimes` |
| 26 IN_BATTLE_EFFECT_BUY | `InBattleEffectBuyCommand` | `dwObjID`, `dwEffectType`, `dwEffectID`, `dwBuffID`, `dwPosIndex` | `dwObjID`, `dwEffectType`, `stBuyInfo` |
| 27 INGAME_ITEM_USE | `InGameItemUseCommand` | `dwItemType`, `dwItemId`, `iItemNum` | `stItemInfo` |

方向佐证：其中多数类带 `FrameSCSYNCCommandClassAttribute`（server→client），
与 boot 记录“服务器下发的帧内通知”一致；`PauseResumeGameCCCommand` 带
`FrameCommandClassAttribute`，是 CC 方向。`FrameCommandFactory` 的
`RegisterCommandCreator / RegisterCSSyncCommandCreator / RegisterSCSyncCommandCreator`
与 `FrameCommand.OnUse/OnReceive/ExecLocal/TransProtocol` 说明这些类确实是命令对象，
不是普通 DTO。

### 2.5 处理方法：20 个独立函数 + 4 个 default + 3 个 skip

27 项跳表与 `docs/advance_frame_commands.md` 的 20 个 processing function 表一致，
本文用静态 RELA 重新算了一遍，地址逐项相同：

- 独立 handler：1–9、11、14、16–20、22–24、27（20 个）；
- default（10、12、13、26）共用 `0x664e8fc`；
- skip（15、21、25）直接 `ret`。

因此类型 10/12/13/26 的名字来自 `BOOTFRAP_TYPEDEF`，但它们走通用
`stDetail` 虚调用路径，不能从 processing function 的字段偏移单独反推；
这正是把 `BOOTFRAP_TYPEDEF` 作为主锚点的原因。

## 3. 与 `FRAME_CMD_INFO` / `FRAMEPKG_CMD_*` 的关系

`CSProtocolWrapper.FRAME_CMD_INFO` 是 **143 个成员的 union**（`stCmdPlayerMove`、
`stCmdPlayerAttackPosition`、`stCmdPlayCommonAttackMode`…），
`CSProtocol.FRAMECMD_ID_DEF` 是 **147 条完整客户端命令 + value__** 的枚举
（`FRAME_CMD_PLAYERMOVE=1`、`FRAME_CMD_ATTACKACTOR=5`、
`FRAME_CMD_PLAYCOMMONATTACKTMODE=28`、`FRAME_CMD_PLAYER_SET_PAINT=132`…）。

这两张表是**完整输入命令层**；本文的 27 项是 **boot/回放记录层**
（`CSDT_FRAPBOOT_DETAIL.bType`）。两者只在语义上对应：

- boot 18 → 展开为 `stCmdPlayerMove` / `FRAMEPKG_CMD_PLAYERMOVE`；
- boot 19 → 展开为 `stCmdPlayCommonAttackMode` / `FRAMEPKG_CMD_PLAYCOMMONATTACKTMODE`；
- boot 20 → 展开为 `stCmdPlayerAttackPlayer` / `FRAMEPKG_CMD_ATTACKACTOR`；
- boot 17 → 对应输入侧 `stCmdPlayerSetPaint`；
- boot 5/7 → 分别对应 `stCmdPlayerSwithAutoAI` / `stCmdPauseResumeGame`；
- 其余多数是服务器通知，没有同名的 `stCmd*` 输入命令。

**不要把 `FRAME_CMD_INFO` 的成员序号或 `FRAMECMD_ID_DEF` 的 1..163 当作
runtime type**：两者数值域和语义都与 27 项 boot 开关不同。

## 4. 置信度与未解项

高（22 项）：3、4、5、6、7、8、9、11、12、13、14、15、16、17、18、19、20、22、23、25、26、27。
证据是 `BOOTFRAP_TYPEDEF` + `CSDT_FRAPBOOT_*` 字段偏移/类字段双重命中。

中（4 项）：

- **1 CC / 2 CS**：名字直接来自枚举，结构是 `wObjID + stSyncInfo` 的批容器；
  processing 只做转交，内部是多条压缩命令，不能给单一命令名。
- **10 MOVETOBORN**：结构明确（`bObjType/dwObjID/stPos`），候选类
  `SvrNtfTransportCmd` 的字段（`destPosition/playerId/playerType`）同值异序，
  但没有字段顺序级证据。
- **24 SWITCH_CONTROL_OBJ**：结构明确（`dwOriginObjID/dwCurrControlObjID/
  dwToControlObjID`），metadata 里没有找到对应 `Assets.Scripts.GameLogic` 命令类；
  CS 侧只有 `CSPKG_SWITCH_CONTROL_OBJ_REQ`。

未解（1 项）：

- **21 PLAYER_SAME**：跳表指向 skip，metadata 中没有
  `CSDT_FRAPBOOT_PLAYER_SAME`，也没有同名命令类；只能保留枚举名
  `BOOTFRAP_TYPE_PLAYER_SAME`，语义（同一玩家续帧/占位）未证。

模式专用、在 KPL 5v5 回放里不会执行：

- 15 `AUTOCHESSBOUNTYMATCH_ADDCOIN`（自走棋）；
- 25 `GAMEPLAY_GOAL_SYSTEM_GEM_EFFECT`（玩法目标系统）；
- 21 `PLAYER_SAME`（skip）。

## 5. 复现

```bash
python tools/advance_frame_names.py
python tools/advance_frame_names.py --json
```

输出：

- `data/replays/_analysis/datasets/advance_frame_names.csv`（27 行）；
- 控制台摘要（type / BOOTFRAP 名 / handler 类型 / 候选类）。

工具只读 `global-metadata.dat`、`libil2cpp.so` 和跳表/RELA，不启动游戏、
不连接设备、不注入、不调用游戏函数。

## 6. 边界

- 地址与跳表是 build 5247758 本次 `libil2cpp.so` 的静态证据；换构建需重跑。
- handler 里的类型检查通过 BSS 中的 metadata usage 槽完成，静态不可读；
  本文没有把槽值冒充成类名，类名来自字段/结构对拍与 metadata 类表。
- 类型 1/2 的批容器内部命令、类型 21 的语义、类型 24 的 C# 类仍未闭合；
  需要设备只读抓取或更多模式样本才能进一步确认。
- 本机 `libil2cpp.so` 存在明文与按 32-bit 字 XOR `0xE3` 混合的代码页；
  本文只反汇编明文区域（dispatcher、27 个 handler、20 个 processing 函数），
  没有对加密区做猜测性解码。
