# G5 映射表：FRAPBOOT → native CS 记录（2026-11-04 live 对拍）

日期：2026-11-04。证据：活进程 pid 10833（20261102_161129 回放播放期间）
slot0 双通道采样 `host/build/g5/cs_dual_play.jsonl` + `.abc` 严格解码
`host/build/g5/abc_events_161129.jsonl`。全部只读（`/proc/<pid>/mem`）。

## 0. 结论

**slot0 的 native 记录 = `[u32 op][payload]`，payload 长度与字段由该 op 的
handler 决定**（不是 `len<<16|op` 定长头）。整局 10,509 帧命令流在回放开始时
被客户端**一次性预推送**进 slot0（1.36 MB），逐帧对齐后得到以下映射：

| `.abc` FRAPBOOT | native 记录 | 计数验证 |
|---|---|---|
| 帧边界（隐含） | `[u32 0x0d][u32 frameNo]` | 10,511 条，1..10,509 连续 |
| **18 PLAYER_MOVE** | `[u32 0x83][u32 frameNo+1][u16 wMoveInfo][u16 0]` | **68,384 = 68,384 精确** |
| **19 PLAYER_ATTACK** | `[u32 0x84][u32 frameNo+1][u16 0][u8 bAttack][u8 0]` | 与 20 合计 **11,886 = 7,538+4,348 精确** |
| **20 PLAYER_ATTACKWITHOBJ** | `[u32 0x84][u32 frameNo+1][u16 wObjID][u8 bAttack][u8 0]` | 同上 |
| 1 CC / 2 CS | 展开为 `0x32`（24B 技能/位置）、`0x34`、`0x4d`、`0x3a` 等 | 部分（见 §3） |

## 1. 逐字节证据

### 1.1 帧 100：6 move ↔ 6× op 0x83

```text
.abc f100: u12 0x600a, u9 0x4d25, u8 0x4312, u20 0xa1ac, u19 0x9898, u18 0x9089
native f100 block:
  0x0d {100}
  0x12e ×5 {205..209}   0x11f {23}
  0x83 {101, 0x6208}    unit=12  ✓
  0x83 {101, 0x4925}    unit=9   ✓
  0x83 {101, 0xa19d}    unit=20  ✓
  0x83 {101, 0x9898}    unit=19  ✓ 值完全相等
  0x83 {101, 0x9089}    unit=18  ✓ 值完全相等
  0x32 ×2 ...
  0x83 {101, 0x4510}    unit=8   ✓
```

`wMoveInfo` 的 unit 位段（bits15..11）逐条对上（12/9/20/19/18/8）；
数值差异仅为 ±1 帧的摇杆变化。payload 的 u32 = 目标帧号（= 标记帧 +1）。

### 1.2 帧 50/51：攻击

```text
native f50: 0x84 {51, 0, 0x61}, 0x84 {51, 0, 0x60}
.abc  f51: type19 packed_attack=97(0x61), 96(0x60)   ✓ 完全相等
```

### 1.3 帧 100 的 CC → op 0x32

```text
.abc f100 type1 CC: object_id=1031, buffer=010000 c3e60000 00000000 705e7f
native f100: 0x32 {101, 0x407, 0xc3e6, 0, 0x705e, 0x6200 01}  ← c3e6/705e 来自 CC buffer
             0x32 {101, 0x21a, 0xffff43f4(-48140), 0, 0xffff9646(-27066), ...}
```

op 0x32 payload = 24 B：`{u32 src/frame, u32 kind, i32 x, i32 y, u32 ?, u16 ?, u8 ?, u8 ?}`
（handler `0x46d8cfc`：`w0,w1=[x8]`；`x2=x8+8`（两个 i32 坐标）；`w3=[x8+0x14]`）。

## 2. 系统 op（客户端自产，非 `.abc` 条目）

同帧块内还出现（整局计数）：

| op | 计数 | 说明 |
|---|---|---|
| 0x12e (302) | 7,617 | 每帧 0~5 条，u32 连续计数；handler 消费 4B |
| 0x11f (287) | 12,492 | 每帧 1~2 条，u32 计数（帧 100 = 23）；消费 4B |
| 0x166 (358) | 850 | 2×u32 |
| 0x16b (363) | 104 | 12B `{u32 0x2c, u8 seq, u32 t}`（handler 0x4711d58 实证） |
| 0x34 (52) | 4,570 | 2×u32 |
| 0x73 (115) | 1,364 | 16B |
| 0x3a (58) | 711 | 24B |
| 0x39 (57) | 641 | 16B |
| 0x4d (77) | 547 | 16B |
| 0x21 (33) | — | 4B（待补 consume） |

这些 op 由客户端按帧生成；宿主包装层需要按同样规则复现（或从模板回放）。

## 3. 未完成

- CC(1)/CS(2) 的逐 sync_type 展开规则（LEARNSKILL 135 / BUYEQUIP 133 /
  目标技能 128 / 方向技能 129 / 位置技能 130 等）尚未逐条证明；
  op 0x32 的坐标字段已对上位置技能，但 op 选择与字段顺序仍需更多帧对拍。
- 系统 op 的生成条件（0x12e/0x11f 的计数语义）未完全解。
- 初始窗口（回放加载期，cursor 0..0x784）的命令序列尚未逐条解析。

## 4. 宿主验收（G5 四条）

用 `host/scripts/build_cs_frame.py` 从 `.abc` 重建帧 70–80（`0x0d/0x83/0x84`），
经 `h5_probe` 推入真实 slot0 + 真实 consumer：

```text
drain == bytes / bytes_match = 11/11
op 13 → handler 0x46d69ec（帧标记 handler，正确）
op 83 → handler 0x46deea0 / op 84 → 0x46deeac（正确）
handler 执行在 0x3cfeca8 崩溃（fault=0）→ 缺战斗上下文（G3/G6 缺口）
```

- 第 1 条（真实回放命令被分派）✅
- 第 2 条（handler 不崩）◐ —— 分派正确，执行需真实 context
- 第 3 条（cursor 前进）✅
- 第 4 条（重复推送确定）✅

### 4.1 active context 复测（2026-11-04 晚，A 路线）

补入 active context `P=0x730fe87fcff0`、`ctx+0x3d0` 及以下 globals 后，
上述“缺战斗上下文”缺口已闭合：

```text
data   0x4FF8000-0x526F000
BSS    0x526F000-0x5281000
table  0x544C000-0x544D478
patch  [base+0x4FF57C8] = base+0x52488C0
slot1  --init-slot1 用真实 ctor/字段初始化
```

结果：

- 1–200 帧 isolated **200/200 ok**，sequential 也 **200/200 ok**；
- 400–440 帧 **41/41 ok**；逐 op 为 `0x39=2, 0x3a=1, 0x3b=1,
  0x34=4, 0x73=5`，与 `.abc` 重建统计完全相等；
- `0x3a` 曾崩在 `0x3F864D8` 的空跳转表，补 `0x544C000` 窗口后修复；
- `0x39` 的 seq 484 需要 slot1，补 slot1 后 ok；
- handler 有副作用（context arena 每帧 113–126 B 变化、6 条 move 的 0x20
  对象累积），但仍是命令/协议记录，不是已证明的 DS 战斗状态。

详见 `docs/h5_active_context_slot0.md`。因此“handler 不崩”从 ◐ 变为 ✅
（限上述 op 与 fixture）；架构结论（slot0 是网络日志、不是模拟输入）不变。

## 5. 关键架构结论（2026-11-04 决定性证据）

**回放时 slot0 的 CS handler 不会执行**：

1. 命令 handler 的下游都经 `[[0x4ff4520]]` → `[0x52717b0]` → `+0x3d0` 取上下文
   （op 0x83 下游 `0x46d29b0`：`ldr x21,[0x4ff4520]; ldr x21,[x21]; ldr x8,[x21];
   ldr x0,[x8,#0x3d0]`）。
2. 回放播放期间实测 `[0x52717b0] == 0`（帧 handler `0x46bc800` 同样检查后
   `ret`，即 no-op）。若 parser 真的把 0x83/0x84 分派出去，游戏会立即崩溃；
   实际不崩 → **0x46B80E8 在回放时不分派 slot0**（consumer `used=0` 佐证），
   slot0 由网络/管线线程排空。
3. 因此：**slot0 的命令流是网络协议日志（客户端发给服务器的同步记录）**，
   回放时的战斗模拟输入走托管 `GameLogicHelper.AdvanceFrameCommands` 链
   （27 类处理函数 → 命令对象 → 管理器 → 原生引擎调用），不是 slot0。
4. 宿主侧历史验证：最初 `--no-publish-context` 时**帧标记 op 0x0d 单独执行
   status=ok**；move/attack/stopmove/posmove 崩在 `0x40a1200`（serializer
   上下文 x0=NULL）。2026-11-04 晚补入 active context + globals 后，这些
   handler 已可执行（§4.1），但执行的是网络日志处理，不是回放模拟。

**对 G5/G6 的含义**：G5 的"包装层"在字节级已完全还原（§0 表），但它重放的是
网络日志；要让 GameCore 真正推进帧，宿主需要复现托管链的原生调用序列
（下一步），或用真实 context 安装 `[0x52717b0]` 使 handler 路径可用。

### 5.1 回放模拟状态在托管对象里（2026-11-04 元数据证据）

`Scripts.GameCore.dll`（type 39454..43519，含 `GameLogicHelper` 与
`AdvanceFrameCommands` 链）中：

```text
HeroData  字段: skillData, actorExp, actorMaxExp, actorGoldCoin,
                actorIncomingGoldCoin, playerId, actorSoulLevel
ActorData 字段: ObjID, cfgID, actorHp, actorHpTotal, coin, camp
```

这些字段与 G7 目标字段一一对应（current_gold / total_gold_earned /
hp / level）。结合 §5 的结论（回放时 native handler 不执行、无 CPlayer
实例），**回放的经济/HP/等级状态由托管层持有**；native `libGameCore`
在回放中主要承担协议缓冲（slot0/1）与渲染状态输出。

因此：
- G7 的字段表应优先在托管 `HeroData/ActorData` 上找（类指针 + 字段偏移），
  而不是 native `CPlayer`。
- G6 的"帧推进"若要离线复现，需要运行托管 `Scripts.GameCore.dll` 的
  `AdvanceFrameCommands` 链（il2cpp 运行时）——或继续找 native context
  的构造入口。这是与"宿主只跑 native GameCore"不同的架构前提，必须写清。
- 活进程侧可用 `host/scripts/find_managed_objects.py` 扫 `HeroData/ActorData`
  实例验证字段偏移（只读堆扫描）。

### 5.2 确定性模拟框架 Dimension.DS（2026-11-04 元数据证据）

回放的战斗模拟是 C# 确定性锁步框架 `Assets.Scripts.GameLogic.Dimension.DS`
（41 个类型）。逐帧状态传输结构：

```text
Dimension.DS.Network.DSTransferArray<T>
  totalPhyAtkPt, totalMgcAtkPt, totalPhyDefPt, totalMgcDefPt,
  actorDic, heroDic, monsterDic, soldierDic          ← 全部 actor 状态字典

Dimension.DS.Network.DSTransferRefArray<T>
  actorMaxExp, actorGoldCoin, actorIncomingGoldCoin,
  playerId, actorSoulLevel, curUseSkill, skillSlotArray, slotType

Dimension.DS.Network.DSVarBaseField
  ParamInt1/2, ParamUint1/2, VarName, VarValue, ParamObj, ... (27 字段)
```

`actorGoldCoin` / `actorIncomingGoldCoin` / `actorSoulLevel` 与 G7 的
current_gold / total_gold_earned / level 一一对应；`actorDic/heroDic`
承载 HP/位置/装备等 actor 状态。**G7 的正确目标 = DS 传输对象**，
G6 的帧推进 = DS 锁步模拟本身。

实测补充（2026-11-04，44505 进程，回放暂停于 03:48）：
`HeroData` 类指针可解析（0x7b2fc67d8e08），但 scudo 与匿名区扫描均
**0 实例** —— 回放状态不在 `HeroData`，而在 DS 传输对象
（`DSTransferRefArray<T>` 的泛型实例，类名指针指向同一泛型名字符串，
需要按"全部名字命中"收集类指针再扫实例）。

### 5.3 G7 字段表（元数据推导，待活体验证）

`DSTransferRefArray<T>`/`DSTransferArray<T>` 实为**序列化缓冲**
（refArray/array/Length/DSVarDirtyFlagList/tempData），状态载体是
`HeroData`/`ActorData`。字段类型（元数据）：

```text
HeroData : skillData(ref), actorExp:i32, actorMaxExp:i32,
           actorGoldCoin:i32, actorIncomingGoldCoin:i32,
           playerId:u32, actorSoulLevel:i32
ActorData: ObjID:u32, cfgID:i32, actorHp:i32, actorHpTotal:i32,
           coin:i32, camp:u32          (父类 System.Object，无基类字段)
```

按 il2cpp 顺序布局（对象头 0x10）推导的偏移：

```text
ActorData: ObjID@0x10 cfgID@0x14 actorHp@0x18 actorHpTotal@0x1c
           coin@0x20 camp@0x24                     (size 0x28)
HeroData : skillData@0x10 actorExp@0x18 actorMaxExp@0x1c
           actorGoldCoin@0x20 actorIncomingGoldCoin@0x24
           playerId@0x28 actorSoulLevel@0x2c        (size 0x30)
```

**这些是推导值，不是实测值** —— 需要活实例或 Il2CppClass.FieldInfo 验证
后才能写入正式字段表。终局真值已存档
（`host/build/g5/truth/final_scoreboard_161129.png`：关羽 8/1/7 9243 等），
可用于验证 coin/hp 字段。

### 5.4 活体实验状态（2026-11-04 晚）

- MuMu 重启后构建偏移完全一致（`[0x4ff5de8]→base+0x52488b8→base+0x52c3250`），
  DS 类指针可解析（`host/build/g5/ds_classes3.json`）。
- 但模拟器在回放加载/播放高负载下**反复崩溃**（游戏进程被冻结/回桌面），
  `HeroData` 类解析在部分进程返回 None（il2cpp 惰性类初始化）。
- 结论：活体字段验证需要更稳定的设备会话；离线字段表可先用 §5.3 推导值，
  正式值待验证。

## 6. 产物

| 文件 | 内容 |
|---|---|
| `host/build/g5/cs_dual_play.jsonl` | 双通道原始采样（slot0 1.65 MB / slot1 32 MB） |
| `host/build/g5/analysis3/slot0_epoch0_records.jsonl` | 逐记录解析（120k+ 条，仅 3 未知头） |
| `host/build/g5/abc_events_161129.jsonl` | `.abc` 全量条目（88,627） |
| `host/build/frames/recon_70_80/` | 重建帧（h5_probe 输入） |
| `host/scripts/build_cs_frame.py` | G5 包装器原型（0x0d/0x83/0x84） |
| `host/scripts/analyze_playback_capture.py` | 捕获流解析/对拍 |
| `host/scripts/scan_cmd_handlers.py` | 705/792 handler consume 尺寸表 |
