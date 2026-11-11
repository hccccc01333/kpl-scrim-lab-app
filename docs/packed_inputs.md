# Packed 输入位域：PLAYER_MOVE / PLAYER_ATTACK / PLAYER_ATTACKWITHOBJ

日期：2026-11-02；**2026-11-03 按 5.127 修正**。范围：`12.1.1.26` / build `5247758` 的三局 `.abc`（11/1 人机局 + 11/2 两局）。
只做离线静态分析，不启动/连接游戏、不登录、不注入；没有修改 R1 事件流、R2 web 或既有数据集。

> **5.127 修正（优先于下文旧读法）**：packed 高 5 位是 **unit=英雄槽位**
> （camp1 0–4→8–12，camp2 0–4→16–20），不是 4/5/6/8/9/10 的 4-bit actor 码。
> `wMoveInfo=[unit:5][seq:2][sign:1][mag:8]`；`bAttack=[unit:5][seq:2][flag:1]`。
> 下文 `actor_code`/`bit11 click-path`/`低3位攻击类型` 均是旧读法，保留作历史；
> 现行结论以 `docs/replay_binary_format.md` 5.127–5.129 为准。

结论先行：

- **metadata 只固定容器宽度**：`wMoveInfo:u16`、`bAttack:u8`、`wObjID:u16`。位域布局是从数据反推，不是 metadata 字段声明。
- **5.127 已定（高置信）**：`wMoveInfo=[unit:5][seq:2][sign:1][mag:8]`；`bAttack=[unit:5][seq:2][flag:1]`；`unit` 映射十人槽位；`mag` 0–180，`sign` 给有符号方向。
- **仍未定**：`seq`/`flag` 的具体语义、方向角 0° 基准的最终地图对齐（但 5.128 已给出 `(cos d, sin d)` 与 15fps 时间基准）。
- 三局共 **35,788 帧、213,032 条目标事件**（182,443 MOVE、20,247 ATTACK、10,342 ATTACKWITHOBJ），全部解码；反例检查 0 条。

## 1. 输入与产物

输入：

- `data/replays/samples/20261101_182452/20261101_182452_-1723849936_94263_1793527939_CBDD358E761B15A4DF526A179E8119E2.abc`
- `data/replays/samples/20261102_161129/20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc`
- `data/replays/samples/20261102_163751/20261102_163751_-1996438720_96420_1793607470_2B9FAA08A7AD40D09ABDA364F9C1E804.abc`
- `data/replays/_analysis/global-metadata.dat`、`libil2cpp.so`（只读）
- `data/replays/_analysis/frame_cmd_structs.json`、`frame_inputs.jsonl`、`frame_command_audit.json`

产物：

- `data/replays/_analysis/tools/decode_packed_inputs.py`
- `data/replays/_analysis/datasets/packed_inputs_20261102.csv`
- `data/replays/_analysis/datasets/packed_inputs_20261102_summary.json`
- 本文

三局覆盖：

| 局 | 帧记录 | 完整解析 | MOVE | ATTACK | ATTACKWITHOBJ | move actor 码 |
|---|---|---|---|---|---|---|
| 11/1 `20261101_182452` | 9,900 | 9,900 | 10,939 | 2,324 | 686 | 4 |
| 11/2a `20261102_161129` | 10,509 | 10,509 | 68,384 | 7,538 | 4,348 | 4,5,6,8,9,10 |
| 11/2b `20261102_163751` | 15,379 | 15,379 | 103,120 | 10,385 | 5,308 | 4,5,6,8,9,10 |
| 合计 | 35,788 | 35,788 | 182,443 | 20,247 | 10,342 | - |

复现：

```bash
python data/replays/_analysis/tools/decode_packed_inputs.py --metadata-only
python data/replays/_analysis/tools/decode_packed_inputs.py \
  <11/1.abc> <11/2a.abc> <11/2b.abc> \
  --hero-ids 1168,1613,750,538,1611,1031,296,551,1799,1760 \
  --out data/replays/_analysis/datasets/packed_inputs_20261102.csv \
  --summary-json data/replays/_analysis/datasets/packed_inputs_20261102_summary.json
python -m py_compile data/replays/_analysis/tools/decode_packed_inputs.py
```

## 2. metadata 证据

`decode_packed_inputs.py --metadata-only` 从 `global-metadata.dat` 解析 TypeDefinition/Field/DefaultValue，得到：

| TypeDef | 字段 | 类型/宽度 |
|---|---|---|
| `CSProtocol.CSDT_FRAPBOOT_PLAYER_MOVE` | `wMoveInfo` | `System.UInt16` / 2 |
| `CSProtocol.CSDT_FRAPBOOT_PLAYER_ATTACK` | `bAttack` | `System.Byte` / 1 |
| `CSProtocol.CSDT_FRAPBOOT_PLAYER_ATTACKWITHOBJ` | `bAttack` | `System.Byte` / 1 |
| `CSProtocol.CSDT_FRAPBOOT_PLAYER_ATTACKWITHOBJ` | `wObjID` | `System.UInt16` / 2 |
| `CSProtocol.FRAMEPKG_CMD_PLAYERMOVEDIRECTION` | `nDegree` | `System.Int16` / 2 |
| `CSProtocol.FRAMEPKG_CMD_PLAYERMOVEDIRECTION` | `bMoveSeq` | `System.Byte` / 1 |
| `CSProtocolWrapper.FRAMEPKG_CMD_PLAYERMOVE` | `stWorldPos` | `FRAMEDT_VECTOR3` |
| `CSProtocolWrapper.FRAMEPKG_CMD_PLAYERMOVE` | `bIsClickPathFinding` | `System.Byte` / 1 |
| `CSProtocolWrapper.FRAMEPKG_CMD_ATTACKACTOR` | `iObjectID` | `System.Int32` / 4 |
| `CSProtocolWrapper.FRAMEPKG_CMD_ATTACKPOSITION` | `stWorldPos` | `FRAMEDT_VECTOR3` |
| `CSProtocolWrapper.FRAMEPKG_CMD_PLAYCOMMONATTACKTMODE` | `bCommonAttackMode` | `System.Byte` / 1 |
| `CSProtocolWrapper.FRAMEPKG_CMD_PLAYATTACKTARGETMODE` | `chAttackTargetMode` | `System.SByte` / 1 |
| `Assets.Scripts.GameLogic.CmdCompressPlayerInfo` | `maxCampPosBitCnt` | 默认值 `3` |
| 同上 | `maxCampCnt` | 默认值 `2` |
| 同上 | `maxCampPosCnt` | 默认值 `4` |

`FRAME_CMD_INFO` 的 5 个目标字段与嵌套类型（`--metadata-only` 的
`frame_cmd_info_members`）：

| FRAME_CMD_INFO 字段 | 解析到的类型 | 嵌套字段 |
|---|---|---|
| `stCmdPlayerMove` | `CSProtocolWrapper.FRAMEPKG_CMD_PLAYERMOVE` | `stWorldPos:FRAMEDT_VECTOR3`, `bIsClickPathFinding:u8` |
| `stCmdPlayerStopMove` | `FRAMEPKG_CMD_STOPMOVE` | `chReserve:i8` |
| `stCmdPlayerAttackPosition` | `FRAMEPKG_CMD_ATTACKPOSITION` | `stWorldPos:FRAMEDT_VECTOR3` |
| `stCmdPlayerAttackPlayer` | `FRAMEPKG_CMD_ATTACKACTOR` | `iObjectID:i32` |
| `stCmdPlayCommonAttackMode` | `FRAMEPKG_CMD_PLAYCOMMONATTACKTMODE` | `bCommonAttackMode:u8` |
| `stCmdPlayerAttackTargetMode` | `FRAMEPKG_CMD_PLAYATTACKTARGETMODE` | `chAttackTargetMode:i8` |

`FRAMEDT_VECTOR3` 的嵌套字段是 `iX:i32, iY:i32, iZ:i32`（12 字节），
`FRAMEDT_VECTOR2` 是 `iX:i32, iZ:i32`（8 字节）。

**命名陷阱（重要）**：`FRAME_CMD_INFO.stCmdPlayerMove` 指向的是
`FRAMEPKG_CMD_PLAYERMOVE { stWorldPos:Vector3(12B), bIsClickPathFinding }`，
不是 `.abc` 里的 2 字节 packed 记录。`.abc` BOOT 记录用的是
`CSProtocol.CSDT_FRAPBOOT_PLAYER_MOVE { wMoveInfo:u16 }`。同理：

- `stCmdPlayerAttackPosition` 是 12 字节 Vector3 的完整攻击位置命令；
- `stCmdPlayerAttackPlayer` 是 4 字节 `iObjectID` 的完整攻击 actor 命令；
- 它们都不是 replay 的 1 字节 `bAttack`。
- `stCmdPlayCommonAttackMode` / `stCmdPlayerAttackTargetMode` 是独立命令；它们是否被折叠进
  `bAttack` 的 bit3 仍是候选，见 §4。

`BOOTFRAP_TYPEDEF` 的枚举值直接确认 selector：

| value | name |
|---|---|
| 18 | `BOOTFRAP_TYPE_PLAYER_MOVE` |
| 19 | `BOOTFRAP_TYPE_PLAYER_ATTACK` |
| 20 | `BOOTFRAP_TYPE_PLAYER_ATTACKWITHOBJ` |

因此 `BOOT_SCHEMAS` 的 18/19/20 命名与 metadata 一致；payload 宽度 `H` / `B` / `BH` 也与
`wMoveInfo:u16` / `bAttack:u8` / `bAttack+wObjID:u16` 完全一致。

## 3. `wMoveInfo` 位布局

16 bit，bit0 = LSB，按大端读入：

| bits | 字段 | 取值/说明 | 置信度 |
|---|---|---|---|
| 0-7 | `degree_mag` | 0..180，单位 1° | 高 |
| 8 | `sign` | 符号位；本文候选 `1=正、0=负` | 高（作为符号位）/ 中（极性） |
| 9-10 | `move_seq2` | 0..3，按 1 递增 mod 4 | 高 |
| 11 | `click_path` | 0=摇杆/普通方向，1=click-path/寻路方向 | 中高 |
| 12-15 | `actor_code` | 4..6（camp A）或 8..10（camp B） | 高（作为 actor 码）/ 中（语义） |

`actor_code` 解码：

| code | `camp_tag` (bits14-15) | `camp` | `camp_pos` (bits12-13) |
|---|---|---|---|
| 4 | 0b01 | 0 | 0 |
| 5 | 0b01 | 0 | 1 |
| 6 | 0b01 | 0 | 2 |
| 8 | 0b10 | 1 | 0 |
| 9 | 0b10 | 1 | 1 |
| 10 | 0b10 | 1 | 2 |

即高 2 位是 one-hot camp tag（`01`/`10`），低 2 位是 camp position。观察不到 `7`/`11`
（camp_pos=3），也观察不到 `0-3`/`12-15`。也可以等价地把它直接读成一个 4-bit
`campPos` 码（camp A = 4..6，camp B = 8..10）；位模式相同，差别只在命名。

`CmdCompressPlayerInfo` 的默认值 `maxCampCnt=2`、`maxCampPosCnt=4`、
`maxCampPosBitCnt=3` 说明本项目存在 camp/position 压缩概念；它与高 4 位的
6 个码在量级上相容，但**不是这 4 bit 的直接 schema 证明**（`maxCampPosBitCnt=3`
与本文的 2-bit `camp_pos` 并不完全一致，可能属于另一个压缩结构）。实际三局只用了
3 个 position。

### 3.1 证据

1. **角度绝对值范围精确闭合**：182,443 条 MOVE 的 `raw & 0xFF` 全部落在 `0..180`，
   181 个整数全部出现；`>180` 计数为 0。三局分别 `mag_max=180`。
2. **符号位连续**：11/1 的 `0x4274 -> 0x469b -> 0x43b4` 解为 `-116 -> -155 -> +180`
   （跨 ±180 连续）；`0x4920`（bit11=1）是另一条 +32 的 click 流。符号位不是
   two's complement 的 bit15，而是独立的 magnitude sign bit。
   开局分路也支持 `sign=1 -> 正`：camp A 的 hi5 首条 `0x592d` -> `+45°`，
   hi4 首条 `0x4d7c` -> `+124°`；camp B 的 hi8/9/10 首条
   `0x80a5/0x988c/0xa091` -> `-165/-140/-145°`。camp A 与 camp B 呈相反方向场，
   与双方基地对角分布相符。
3. **seq 计数**：11/1 的 joystick 流（bit11=0）中，`seq` 相邻事件按
   `0 -> 1 -> 2 -> 3 -> 0` 递增；三局 `4:joystick` 的“+1 mod 4”比例分别为
   64.3%、61.6%、63.0%。`5:joystick` 在 11/2a 为 64.8%，11/2b 恒 0（11/1 无 code 5）。
   `8/9/10` 的 seq 恒为 0（AI/目标同步流的反例，见 §3.2）。
4. **click-path 双流**：同一 actor 码可同时出现 bit11=0 和 bit11=1 的两条独立角度流；
   例如 11/1 frame 316 同时有 `0x4920`（click，+32）和 `0x4592`（joystick，+146）。
   `0x4920` 在连续帧重复，符合按住 click-path 目标的语义；metadata 的
   `FRAMEPKG_CMD_PLAYERMOVE.bIsClickPathFinding` 给出了字段名候选。
5. **actor 码在 MOVE 与 ATTACK 中复用**：`bAttack` 的高 4 位出现完全相同的
   `4/5/6/8/9/10` 集合；11/1 两者都只有 `4`。每条 actor 码的 MOVE 流在整局内连续
   （中位 gap 1-2 帧，最大 gap 数百帧，符合死亡/回城），说明它是稳定 actor 码，
   而不是每帧序号。
6. **AT/ATO 的 camp 偏置**：三局 `PLAYER_ATTACK` 的 actor 码 20,101 次在 camp A、
   仅 146 次在 camp B；`PLAYER_ATTACKWITHOBJ` 则有 8,954 次在 camp B、1,388 次在
   camp A。这个偏置支持“camp A = 本地/POV 输入按钮，camp B = 远端/敌方目标同步”，
   但仍不能证明真实阵营名称。

### 3.2 反例/未定

- `7`/`11`（camp_pos=3）从未出现；`0-3`/`12-15` 也从未出现。不能据此断言
  `camp_pos` 只有 2 bit 或“每 camp 只有 3 人”，只能说明这三局只记录到 3 个位置。
- 11/1 只有 actor `4`；11/2 两局都是 `4,5,6,8,9,10`。因此“10 人局应有 10 个
  actor 码”是**错误预期**：这三局只记录到 6 个输入源（每 camp 3 个）。
- seq 并非对所有流递增：`8/9/10` 恒 0，11/2b 的 `5:joystick` 也恒 0。它仍然
  是一个 2 bit 字段，但不能假定“每条 MOVE 都会 +1”。
- bit11=1 的 click 流 seq 在 11/1/11/2a 部分 actor 上恒 0；click 流不保证推进
  joystick 的 seq。
- 符号极性：`sign=1` 选为“正”是本文约定。把整列取反得到镜像方向场，位结构、
  连续性和范围检查同样成立；仅凭位流无法排除镜像。§3.1 的开局分路几何（camp A
  的车道方向、camp B 的 down-left）支持当前约定，但不是强证明。

## 4. `bAttack` 位布局

8 bit，bit0 = LSB。**`bAttack` 没有方向位**：方向只在 `PLAYER_MOVE.wMoveInfo`
的低 12 位里；`PLAYER_ATTACK` 只表达“哪个攻击按钮/什么状态/哪个 actor”，
`PLAYER_ATTACKWITHOBJ` 的目标方向由 `wObjID` 指向的目标 actor 决定，不携带角度。

| bits | 字段 | 取值/说明 | 置信度 |
|---|---|---|---|
| 0-2 | `attack_type` | `emComAtkCmdType` 0..7 | 高 |
| 3 | `flag3` | 候选：精确普攻/目标模式；不是严格的“有目标”标志 | 中 |
| 4-7 | `actor_code` | 与 `wMoveInfo` bits12-15 同一编码 | 高 |

`emComAtkCmdType`（metadata 枚举值）：

| value | name | 三局 ATTACK 计数 |
|---|---|---|
| 0 | `StopCommonAttack` | 9,994 |
| 1 | `CommonAttackButton` | 8,976 |
| 2 | `LastHitButton` | 427 |
| 3 | `AttackOrganButton` | 153 |
| 4 | `SearchAreaLockTarget` | 680 |
| 5 | `LeftJoyStickSelect` | 0 |
| 6 | `NearestButton` | 17 |
| 7 | `CommonAttackMiss` | 0 |

`PLAYER_ATTACKWITHOBJ` 的 type 分布：`CommonAttackButton` 10,260、
`SearchAreaLockTarget` 61、`CommonAttackMiss` 21。

### 4.1 证据

- 11/1 的 AT 值几乎全部在 `0x40/0x41` 间交替：`0x40` = `StopCommonAttack`，
  `0x41` = `CommonAttackButton`，正好是按下/停止的成对命令。11/1 的 ATO 恒为
  `0x49` = `CommonAttackButton` + `flag3=1`。
- 11/2 的 AT 在 `0x50/0x51`、`0x60/0x61`、`0x40/0x41` 等成对交替，低 3 位分别是
  Stop/CommonAttackButton，且高 4 位与 MOVE 的 actor 码一致。
- `flag3` 与 ATO **相关但不等价**：全部 AT 的 `flag3=1` 为 6,343/20,247（31%），
  ATO 为 6,520/10,342（63%）；11/2b 的 AT 也有一半左右 `flag3=1`。
- 因此 `flag3` 不能解释成“是否带目标 object”：ATO 中仍有 `0x81/0x91/0xA1`
  （`flag3=0`）大量出现；AT 中也有 `0x48/0x49`（`flag3=1`）。最直接的反例是
  11/1 的 `0x48`：低 3 位是 `StopCommonAttack`，bit3=1，且它只出现在没有
  `wObjID` 的 `PLAYER_ATTACK` 里（281 次）。

### 4.2 `flag3` 候选表

| 候选 | 支持 | 反证/风险 | 置信度 |
|---|---|---|---|
| `bCommonAttackMode`（精确普攻模式） | metadata 有独立的 `stCmdPlayCommonAttackMode { bCommonAttackMode:bool }`；单 bit 正好可表示 normal/precise 二态 | `emCommonAttackMode` 有 3 个值（0/1/2），单 bit 不能全覆盖；没有受控切换样本 | 中 |
| targeted/lock attack mode | ATO 的 flag3=1 比例更高（63% vs 31%）；`0x49` 是典型的带目标攻击 | ATO 仍有 37% flag3=0；AT 也有大量 flag3=1 | 中低 |
| `bStart`（按下/抬起） | 若 bit3 是 start，`0x48` 可解释为“start + Stop” | `StopCommonAttack + flag3=1` 语义矛盾；AT 的交替实际发生在低 3 位 Stop/CommonAttackButton 上，不是 bit3 | 低 |

**建议**：数据层保留 `flag3` 原值，不要把它直接命名为 `has_target`。若后续要生成
“是否精确普攻/是否锁目标”的业务字段，必须先做受控实验（§7）。

## 5. `PLAYER_ATTACKWITHOBJ.wObjID`

- 宽度：metadata `u16`；读法：大端（`>H`）。小端会把 37 读成 9472，既不在
  actor id 范围，也无法与同帧 `USEOBJECTIVESKILL.object_id`/`CC.object_id` 对齐。
- 语义：目标 actor object id，不是施法者 id。
- 三局统计：

| 局 | ATO 事件 | 唯一目标 | 目标范围 | target=0 | 命中 10 个英雄 entity id |
|---|---|---|---|---|---|
| 11/1 | 686 | 30 | 1..11484 | 0 | 0 |
| 11/2a | 4,348 | 200 | 1..11295 | 0 | 0 |
| 11/2b | 5,308 | 267 | 3..17868 | 0 | 0 |

- 11/2 的 10 个英雄 entity id（`1168,1613,750,538,1611,1031,296,551,1799,1760`）
  一次都没有成为 target。这与 `PLAYER_ATTACKWITHOBJ` 是“打小兵/野怪/塔/器官”的
  目标同步相符；**不能**把它当作英雄目标通道。
- 部分 target 同时出现在其他命令的 `object_id`：例如 11/2a 的 58、12、8282；
  11/2b 的 65、51、8996；11/1 的 37、51、24。并不是所有 target 都被其他命令引用
  （很多单位只被普攻目标一次），所以“未在其他命令出现”不构成反证。
- 目标具体类型（小兵/野怪/塔/器官）**未定**；目前只确定是“非英雄 actor object id”。
  小 id（1/3/12/24/37/51/58）与召唤物/兵线/器官候选相容，大 id（4156/8282/9106/
  17868）与野怪/防御塔候选相容，但没有逐类 ground truth。

## 6. 置信度汇总

| 项 | 结论 | 置信度 |
|---|---|---|
| 容器宽度 `u16/u8/u8+u16` | metadata 直接字段 | 高 |
| MOVE 低 8 位 = 0..180 角度绝对值 | 182,443 条全部 ≤180，181 值全出现 | 高 |
| MOVE bit8 = 符号位 | 跨 ±180 连续；0 幅值只出现 sign=1（负零） | 高 |
| MOVE bit8 极性 `1=正` | 开局分路几何支持；镜像不矛盾 | 中 |
| MOVE bits9-10 = 2 bit seq | 多条流严格 +1 mod 4；但部分流恒 0 | 高（字段）/ 中（对所有流都递增） |
| MOVE bit11 = click-path/寻路 | 同 actor 双角度流；metadata 字段名候选 | 中高 |
| MOVE 高 4 位 = actor/camp 码 | MOVE/ATTACK 复用；稳定流；6 个码 | 高 |
| camp 码 → 真实阵营 | camp A/B 与 01/10 对应；A 可能是本地/蓝方 | 中低 |
| ATTACK 低 3 位 = `emComAtkCmdType` | 8 值枚举；Stop/CommonAttackButton 成对 | 高 |
| ATTACK bit3 | 精确普攻/目标模式候选 | 中 |
| ATTACK 高 4 位 = 同一 actor 码 | 与 MOVE 完全同一集合 | 高 |
| `wObjID` = 非英雄目标 actor id | u16 BE；三局 0 个英雄 id | 高（非英雄）/ 中（具体单位类型） |
| actor 码 → 英雄 object id | 未建立 | 未定 |

## 7. 可证伪实验

1. **camp/阵营极性**：取一局已知 POV 玩家和阵营的回放，比较开局第一次 MOVE 的
   actor 码与分路方向。若 camp A 的 actor 4-6 从蓝方基地出发，则本文 `4..6=camp A`
   与 `1=正` 的约定成立；若相反，只需翻转这两个约定。
2. **5 人/4 位置**：找一局 5 个真人同队的回放。若出现 `7`/`11`（camp_pos=3）或
   `0-3`/`12-15`，说明 `camp_pos` 位宽/编码不止本文的 2 bit；若仍只有 3 个位置，
   则“输入流只记录部分玩家”成立。
3. **click-path**：构造/寻找一次明确的点击寻路（`MoveToPosCommand.isClickPathfinding`）
   输入，确认对应 MOVE 的 bit11=1，且其角度流与摇杆流分离。若 bit11 在纯摇杆局也
   频繁为 1，则 bit11 不是 click-path。
4. **bit3**：在设置中切换“精确普攻/普通普攻”，录制前后同英雄的 AT/ATO。若 bit3
   随设置切换而稳定变化，支持 `bCommonAttackMode`；若 bit3 随目标锁定状态变化，
   支持 targeted 模式。注意 `emCommonAttackMode` 有 3 个值，若观察到 2 bit 模式
   信息，说明 bit3 不是它的全部。
5. **seq**：连续改变摇杆方向，检查同一 actor 的 seq 是否 `0,1,2,3,0...`。若某些
   流恒 0，需按“人类输入流 vs AI/目标同步流”分组，不要全局假设 seq 递增。
6. **target 类型**：把 `wObjID` 与同一帧/邻近帧的 `CC.object_id`、`USEOBJECTIVESKILL.object_id`、
   已知防御塔/野怪 entity 表对拍，确定它是小兵、野怪、塔还是器官。当前只能确定
   “非英雄 actor”。

## 8. 覆盖与限制

- 三局 35,788 帧全部被现有 `replay_frame_commands` 解码（`fully_parsed_frames` 与
  `frame_records` 相等，`unresolved_frames=0`）；本工具只消费其中 18/19/20 三条
  BOOT 记录，覆盖 213,032/213,032 条目标事件。
- 11/1 的 13,949 条目标事件与现有 `frame_inputs.jsonl` 逐条一致：按
  `(kind, frame, raw, target_object_id)` 计数，两个 Counter 完全相等（13,949 =
  10,939 + 2,324 + 686）。这说明本解码器没有改变 R1 的原始 raw 读取。
- 11/2 的 CS 技能 schema 存在已知漂移（例如 `USEDIRECTIONALSKILL` 的
  `secondary_1..3` 出现 0x8000003B 之类的值），但 BOOT 18/19/20 的字节宽度和
  帧边界在三局中保持精确；本解码器不依赖 CS 技能字段。
- 本文没有证明 `.abc` 记录的 `actor_code` 对应哪个英雄；也没有证明 camp A 是
  蓝方/本地阵营。两者都需要外部 ground truth（POV、录屏、客户端设置或更多局）。
- 位域是数据反推；metadata 只给出容器宽度。不要把它当作官方协议文档。
- 没有启动/连接游戏、没有登录、没有注入；没有修改 R1/R2 或既有数据集。
