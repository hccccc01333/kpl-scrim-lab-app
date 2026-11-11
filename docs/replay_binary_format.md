# 王者荣耀回放二进制结构分析

> 文档性质：只读逆向分析记录，不是官方协议规范。
>
> 样本：`data/replays/samples/20261028_135516.abc` + `20261028_135516.ope`
>
> 游戏版本：12.1.1.1 / 12.1.1.23，构建 4989537 / 5230306
>
> 分析日期：2026-10-28
>
> 约束：不修改回放文件，不注入游戏进程，不修改包体，不记录 `param.json` 中的敏感密钥。
>
> **2026-11-02 D1 纠错（优先于全文旧结论）**：`0x02/0x81` = `USEDIRECTIONALSKILL`，
> `0x02/0x84` = `BASEATTACK`，`0x01/0x03` = 存活 beacon；它们都不是死亡/金币/HP。
> 文中所有 `0x81 mode6=死亡`、`0x84=单位死亡/stat` 的说法全部撤回；
> 11/2 confirmed death candidates = 0。以 `docs/agent_death_0x81.md` 为准。
>
> **2026-11-02 经济纠错（11-03 修正）**：`0x02/0x85` = BUYEQUIP，不是金币；unique 全集合标价和
> 也不是花费。面板累计金币已含初始 300，合法状态是 `最终装备成本 < 面板累计金币`
> （9/10 通过；翳灵崽 −302g 异常待查）；不要加 300。以 `docs/scope_11_2.md` 为准。

---

## 0. 结论摘要

1. **对局数据确实在回放文件夹里**：
   - `.abc`：回放主体，包含版本、十名玩家元信息、英雄 ID、尾部 TLV 事件流；
   - `.ope`：与 `.abc` 成对保存的客户端操作数据，包含操作事件流，不是 Oodle 压缩。

2. **数据分析框架在本地客户端，不在回放文件里**：
   - `Assets.Scripts.OperatorMonitor` 是操作分析/数据分析框架；
   - 它负责采集、序列化、分析 APM、技能槽效率、技能命中率、连招、长按、摇杆断触等；
   - 分析结果通过 `ApolloRepoertEvent` / `ReportTLog2` 上报；
   - 回放里的 `.ope` 只是这套框架的输入数据，框架代码和 UI 展现都在客户端程序集。

3. **`.ope` 的真实格式已确认是双层 raw DEFLATE**：
   - 外层 `0x01` + raw DEFLATE → 14,349 字节内层数据；
   - 内层 0x00–0x8A 是明文头，0x8B 起再次 raw DEFLATE → **39,634 字节操作事件流**；
   - 不是 Oodle，也不是 LZH。

4. **`.ope` 是录制设备本地玩家的操作数据**（强证据，尚差全流玩家 ID 穷举）：
   - 头部含设备型号 `Vivo V2546A`、对局 ID、录制时间；
   - 事件以触控、技能槽、UI、GameObject 路径、内存快照为主；
   - 目前没有发现十名英雄的坐标、血量、经济等全量状态表。

5. **十人完整过程数据不能直接从 `.ope` 读出**：
   - `.abc` 更像“回放命令流 + 事件日志”，客户端需要用它重放/模拟才能得到十人过程状态；
   - 若要离线还原十人状态，需要继续解析 `.abc` 的 TLV 和 `CmdCompressPlayerInfo`，或用客户端/GameCore 重放；
   - OCR 录屏仍是可行的兜底路线，但不是唯一路线。

---

## 1. 证据等级约定

| 标记 | 含义 |
| --- | --- |
| ✅ | 已在样本上验证，偏移/长度可重复 |
| ◐ | 强证据，但只在一个样本或有限样本上验证 |
| ○ | 假设/候选解释，尚需更多样本或代码验证 |

本文所有“字段名”除已确认的容器结构外，均指**推断语义**，不应当作官方字段名。

---

## 2. `.abc` 容器结构

### 2.1 文件级信息

| 项目 | 值 | 证据 |
| --- | --- | --- |
| 文件大小 | 68,268 字节 | ✅ |
| 头部版本字符串 | `12.1.1.1`、`12.1.1.23` | ✅ |
| 头部构建字符串 | `4989537`、`5230306` | ✅ |
| 玩家块步长 | 1,517 字节 | ✅ |
| 玩家块数量 | 10 | ✅ |
| 本地玩家块起点 | 674 | ✅ |
| 尾部 TLV 记录数 | 2,878 | ✅ |

当前探针读取头部的方式：

```text
offset 0: 4 个“1 字节长度 + UTF-8 字符串”
  - 版本 1
  - 版本 2
  - 构建号 1
  - 构建号 2
offset 35: 本地英雄 ID（4 字节小端）
```

昵称不是固定偏移，探针在头部前 512 字节内扫描“长度 4–64、可打印、至少 2 个汉字”的 UTF-8 串。

### 2.2 十人玩家块

每个玩家块 1,517 字节，英雄 ID 均为 **4 字节大端**。第 2–10 个块在以下三个位置重复出现同一 ID：

```text
+771
+1415
+1445
```

本地玩家块（起点 674，第一个块）只观察到 `+1445` 位置是有效英雄 ID（本样本为 118）；它的 `+771`、`+1415` 并不是英雄 ID。因此探针在识别本地块时使用 `+1445`。

本样本块起点：

```text
674, 2191, 3708, 5225, 6742,
8259, 9776, 11293, 12810, 14327
```

对应英雄 ID（按块顺序）：

```text
118 孙膑
196 百里守约
548 戈娅
558 影
193 铠
112 鲁班七号
144 程咬金
172 蚩奼
195 百里玄策
148 姜子牙
```

注意：

- 这个顺序只是文件中的块顺序，**不代表分路或阵营**；
- 需要加载界面截图或更多样本才能可靠判断“同队/对方”；
- 头部本地英雄 ID 应与其中一个块一致，但本地玩家块不一定是第一个块。

### 2.3 尾部 TLV 事件流

本样本从偏移 17,652 开始。按记录头连续解析得到 2,878 条记录，记录区结束于偏移 68,261；文件末尾还有 7 字节（68,261–68,267）未纳入记录，用途未知。记录头形态：

```text
3 字节 key
4 字节固定标记：29 0E 00 00
1 字节长度
payload
```

payload 前 5 字节为 0，随后：

```text
u16 BE seq
u8 type
u8 subtype
args...
```

统计结果：

| key | 次数 |
| --- | --- |
| `022301` | 1,740 |
| `000000` | 604 |
| 其余 483 个 key | 多数 2 次 |

type/subtype 分布：

| type/subtype | 次数 |
| --- | --- |
| `01/00` | 1,763 |
| `02/84` | 599 |
| `02/83` | 476 |
| `02/81` | 20 |
| `02/87` | 8 |
| `02/85` | 7 |
| `02/80` | 5 |

seq 范围 2–2,477，单调递增，样本中未观察到回退。

### 2.4 `.abc` 目前能确定/不能确定什么

可以确定：

- 容器里有十名玩家的块和英雄 ID；
- 尾部存在稳定、可顺序解析的 TLV 事件流；
- TLV 事件量相对整局过程状态来说很小，更像“命令/事件日志”，而不是逐帧十人状态快照。

尚不能确定：

- TLV 的 key/type/subtype 与游戏逻辑事件的对应关系；
- `CmdCompressPlayerInfo` 的位域编码；
- 能否仅靠 `.abc` 离线重建十人坐标、血量、经济、技能 CD 等完整过程状态；
- 是否必须依赖客户端 `GameCore` 的模拟/重放逻辑。

---

## 3. `.ope` 容器结构

### 3.1 外层

| 项目 | 值 | 证据 |
| --- | --- | --- |
| 文件大小 | 14,355 字节 | ✅ |
| 外层首字节 | `0x01` | ✅ |
| 外层压缩 | raw DEFLATE（首个块为 stored） | ✅ |
| 外层解出 | 14,349 字节 | ✅ |

外层不是 zlib 带头格式，而是 raw DEFLATE（windowBits = -15）。

### 3.2 内层明文头（0x00–0x8A）

本样本关键偏移：

| 偏移 | 内容 | 证据 |
| --- | --- | --- |
| `0x00` | `01 01 01`（前 3 字节；`0x03` 紧接版本长度 8） | ✅ |
| `0x03` | 长度 8，`12.1.1.1` | ✅ |
| `0x0C` | 长度 9，`12.1.1.23` | ✅ |
| `0x16` | 长度 7，`4989537` | ✅ |
| `0x1E` | `29 0E 00 00` + 长度 11 + `Vivo V2546A` + 约 20 字节设备信息 | ◐ |
| `0x42` | 长度 32，32 字节对局 ID | ✅ |
| `0x63` | 长度 19，`2026-10-28 13:55:16` | ✅ |
| `0x78` | `01` | ◐ |
| `0x7E` | u32 LE = 31 | ◐ |
| `0x82` | float LE = 1.0 | ◐ |
| `0x86` | u32 LE = 14,211 | ✅ |
| `0x8A` | `01` | ✅ |
| `0x8B` | 第二层 raw DEFLATE 起点 | ✅ |

关于 `0x86` 的 14,211：

```text
0x8A 起 1 字节 flag + 14,210 字节 deflate 数据 = 14,211
0x8B + 14,210 = 14,349，正好到内层末尾
```

因此该字段可以理解为“从 flag 开始的剩余长度”。

另一个值得注意的细节：内层设备信息前出现了 `29 0E 00 00`，与 `.abc` TLV 记录头中的 4 字节标记相同。两者是否存在共享的版本/类型含义，目前未知（○）。

### 3.3 第二层 raw DEFLATE

```text
输入：inner[0x8B:]
输出：39,634 字节 operator stream
```

解压后的操作流已保存为研究中间文件：

```text
data/replays/_analysis/ope_decoded.bin
```

---

## 4. Operator Stream（39,634 字节）

### 4.1 操作流总头（27 字节）

本样本前 27 字节：

```text
02 00 01 F3 DD 01 0A 7B 00 00 00 00
01 FA DD 01 17 17 00 00 00 00 00 00 00 00 00
```

按偏移拆解：

| 偏移 | 字节 | 推断 | 证据 |
| --- | --- | --- | --- |
| `0x00` | `02` | 版本/格式标记 | ○ |
| `0x01` | `00` | 保留 | ○ |
| `0x02` | `01` | 标志位 | ○ |
| `0x03–0x05` | `F3 DD 01` | varint = 28,403 | ◐ |
| `0x06` | `0A` | 10（玩家数/槽位数？） | ○ |
| `0x07–0x0A` | `7B 00 00 00` | u32 = 123 | ✅ |
| `0x0B` | `00` | 保留 | ○ |
| `0x0C` | `01` | 标志位 | ○ |
| `0x0D–0x0F` | `FA DD 01` | varint = 28,410 | ◐ |
| `0x10` | `17` | 23 | ○ |
| `0x11` | `17` | 23 | ○ |
| `0x12–0x1A` | 9 个 `00` | 保留/对齐 | ○ |

其中 `0x07–0x0A = 123` 已被第一条记录验证：

```text
0x1B: 16 B4 01 + 123 字节 payload
0x1B + 1(type) + 2(frame) + 123 = 0x99
0x99 正好是下一条 SkillSlot 记录
```

因此 123 是 **UILayout 记录的负载长度**，这一点可以确认。

`0x03` 和 `0x0D` 的 28,403 / 28,410 与后续 UnityFrame（约 28,523 起）接近，但整体事件流跨度远大于 7 帧；它们更可能是某个批次的起止标记，具体含义待定（○）。

### 4.2 记录头通则

除 `0x01` 外，本样本中大多数记录采用：

```text
type:u8
Frame:u16 LE
payload
```

`0x01` 例外：

```text
type:u8 = 0x01
UnityFrame:varint
```

所有多字节整数均为小端；varint 为无符号 LEB128。

### 4.3 已观察到的记录类型

| type | 枚举名 | 记录形态 | 证据 |
| --- | --- | --- | --- |
| `0x00` | Common | `type + Frame:u16` | ✅ |
| `0x01` | UnityFrameOpe | `type + UnityFrame:varint` | ✅ |
| `0x02` | GameCoreFrameOpe | `type + Frame:u16` [+ 可选 UnityFrame:varint] | ◐ |
| `0x03` | SkillUseOpe | `type + Frame:u16 + 多个 varint` | ◐ |
| `0x05` | TouchOpe | `type + Frame:u16 + 4/5 个 varint` | ◐ |
| `0x06` | MoveOpe | `type + Frame:u16 + 5/7 个 varint` | ◐ |
| `0x0B` | UIEventOpe | `type + EventID:varint`（本样本疑似无 Frame） | ○ |
| `0x0E` | GameObjectNameOpe | `type + Frame:u16 + InstId:varint + len:u8 + path` | ✅ |
| `0x10` | MemoryData | `type + Frame:u16 + len:varint + raw bytes` | ✅ |
| `0x13` | SkillSlotOpe | `type + Frame:u16 + SlotType:u8 + Value:u8` | ✅ |
| `0x16` | UILayout | `type + Frame:u16 + 123 字节布局数据` | ✅ |

未在样本中确认或未完整解析的类型：`0x04`、`0x07`、`0x08`、`0x09`、`0x0A`、`0x0C`、`0x0D`、`0x0F`、`0x11`、`0x12`、`0x14`、`0x15`、`0x17`、`0x18`、`0x19`。

### 4.4 分类型说明

#### `0x00` Common

```text
00 8C 01
```

- `type = 0x00`
- `Frame = 0x018C = 396`

本样本中它以固定 3 字节反复出现，像是“帧占位/心跳”记录。

#### `0x01` UnityFrameOpe

```text
01 93 E0 01
```

- `type = 0x01`
- varint `93 E0 01` = 28,691

样本中 UnityFrame 值从约 28,400 递增到 29,000 以上，是排序/对齐事件的重要锚点。

#### `0x02` GameCoreFrameOpe

已观察到两种形态：

形态 A：内联 UnityFrame

```text
02 30 01 EB DE 01
   Frame=304   UnityFrame=28,523
```

形态 B：只写 GameCoreFrame，后面跟独立的 UnityFrame 记录

```text
02 8A 01 01 D7 E0 01
   Frame=394   type=0x01 UnityFrame=28,759
```

区分方法（启发式）：

- 读取 `Frame:u16` 后，尝试把后续字节按 varint 解析为 UnityFrame；
- 若结果落在合理的 UnityFrame 范围内，按形态 A；
- 若结果异常（例如超过 100 万），按形态 B，把后续 `0x01` 当独立记录。

这个启发式在本样本的多个位置可用，但还需要更多样本验证是否是真正的“可选字段”。

#### `0x03` SkillUseOpe

样本：

```text
03 E8 00 02 86 01 01 CB E0 01
```

拆解：

```text
type = 0x03
Frame = 0x00E8 = 232
payload varints = [2, 134, 1, 28,747]
```

`SkillUseOperatorData` 的已知字段是 `SlotType`、`SkillId`、`SkillSeq`。候选解释：

- `2` = SlotType
- `134` = SkillId
- `1` = SkillSeq
- `28,747` = 另一个序列/帧值，暂未归位

#### `0x05` TouchOpe

样本 1（6 字节 payload）：

```text
05 7E 00 00 10 D3 01 C3 01
   Frame=126
   payload varints = [0, 16, 211, 195]
```

样本 2（7 字节 payload）：

```text
05 82 01 00 00 10 D3 01 C3 01
   Frame=386
   payload varints = [0, 0, 16, 211, 195]
```

样本 3（7 字节 payload）：

```text
05 84 01 00 01 10 D3 01 E2 01
   Frame=388
   payload varints = [0, 1, 16, 211, 226]
```

重要观察：

- payload 字段是**字节对齐的 varint**，不是跨字段的连续位流；
- 7 字节 payload 可以看成 6 字节 payload 在第二个字段前插入了一个 `0x00`，尾部 `211, 195` 仍然对齐；
- 因此此前“整段 bit-packed”的判断不成立，`ReadBitPacked`/`WriteBitPacked` 更可能只用于单个字段，且本样本的 Touch payload 恰好落在字节边界。

候选字段：`TouchPhase`、`TouchId`、`SlotType`、`TouchPosition.x`、`TouchPosition.y`。目前还不能确定 4/5 个 varint 的准确顺序，也不能确定坐标是否经过缩放。

#### `0x06` MoveOpe

样本：

```text
06 88 01 00 10 01 02 71
   Frame=392
   payload varints = [0, 16, 1, 2, 113]
```

```text
06 88 01 01 00 02 01 95 E0 01
   Frame=392
   payload varints = [1, 0, 2, 1, 28,693]
```

```text
06 88 01 03 58 04 02 77 01 A3 E0 01
   Frame=392
   payload varints = [3, 88, 4, 2, 119, 1, 28,707]
```

`MoveOperatorData` 字段为 `Degree`、`GameSvrPing`、`Seq`。候选解释：

- 第二或第一个 varint 可能是 `Degree`（出现 0、16、48、88、96 等角度值）；
- 中间的小整数可能是 `GameSvrPing` 或标志位；
- 末尾约 28,6xx–28,7xx 的 varint 可能是 `Seq`/UnityFrame 类序列值。

目前只能确定 payload 是 5 或 7 个 varint（对应 5/7/9/10 字节），尚不能可靠命名每个字段。

#### `0x0B` UIEventOpe

样本：

```text
0B 7D A0 09
```

候选解释：

```text
type = 0x0B
EventID = varint(7D A0 09) = 151,677
```

这条记录后面紧跟 `02 93 01` GameCoreFrame（Frame=403）。  
如果按 `type + Frame:u16 + EventID:u32` 解释，Frame 会变成 41,085，明显超出本样本 126–430 的游戏帧范围；如果按 `type + EventID:u32` 解释，记录会吞掉下一条 `02`，导致边界不成立。  
因此本样本更支持 **无 Frame + EventID:varint**，但还需要更多样本确认（○）。

#### `0x0E` GameObjectNameOpe

样本：

```text
0E A5 01 D2 B3 EB FF 0F 2A
   "Design/MainCamera/CameraOffset/Main Camera"

0E A5 01 CA FD FF FF 0F 1E
   "BootObj/CUIManager/Camera_Form"
```

拆解：

```text
type = 0x0E
Frame = 0x01A5 = 421
InstId = varint
PathLen = u8
Path = UTF-8
```

`InstId` 看起来是 **32 位有符号 GameObject 实例 ID 的无符号 64 位 varint 编码**：

```text
D2 B3 EB FF 0F  -> 0xFFFAD9D2  (作为 int32 为负数)
CA FD FF FF 0F  -> 0xFFFFFECA  (作为 int32 为负数)
```

路径以 `Design/...`、`BootObj/...` 开头，可用于还原 UI/相机对象的变化。

#### `0x10` MemoryData

样本：

```text
10 A8 01 2D 00 D2 D9 FA FF ...
   Frame = 424
   len = 0x2D = 45
   data = 45 字节
```

data 前几个字节又出现了 `D2 D9 FA FF` 这类实例 ID 模式，说明 MemoryData 可能是某个内存流的快照/片段，而不是普通文本。该类型需要结合 `OperatorMonitorModule.GetMemoryStream` 继续分析。

#### `0x13` SkillSlotOpe

固定 5 字节：

```text
13 AE 01 00 01
   type = 0x13
   Frame = 0x01AE = 430
   SlotType = 0
   Value = 1
```

样本中按槽位顺序成批出现：

```text
0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 15, 10, 11
```

`Value` 为 1 或 0，像是技能槽可用/不可用、或按钮状态切换。该类型是最稳定、最先可完全解析的操作事件。

#### `0x16` UILayout

```text
16 B4 01 + 123 字节布局数据
   Frame = 436
```

123 来自操作流总头 `0x07–0x0A`。布局数据内部包含大量小整数/varint，像是按钮、摇杆、技能槽的 RectTransform 布局参数。内部结构尚未拆解（○）。

### 4.5 分批结构示例

操作流不是简单平铺，而是“帧头 + 一批事件”的结构。一个可读的片段：

```text
0x1B  16 B4 01 + 123B            UILayout, Frame=436
0x99  13 AE 01 00 01             SkillSlot, Frame=430, slot=0, value=1
0x9E  13 AE 01 01 01             SkillSlot, slot=1, value=1
...
0x1DE 02 30 01 EB DE 01          GameCoreFrame=304, UnityFrame=28523
0x1E4 13 AE 01 00 00             SkillSlot, Frame=430, slot=0, value=0
...
0x248 01 EC DE 01                UnityFrame=28524
0x24C 13 AE 01 07 00             SkillSlot, slot=7, value=0
...
0x333 0E A5 01 ...               GameObjectName, Frame=421
0x366 0E A5 01 ...               GameObjectName, Frame=421
0x38D 10 A8 01 2D ...            MemoryData, Frame=424, len=45
0x3BE 02 70 01 92 E0 01          GameCoreFrame=368, UnityFrame=28690
0x3C4 05 7E 00 ...               Touch, Frame=126
...
```

注意：同一个批次内可能出现不同 Frame 值（例如 SkillSlot 的 430 与 GameCoreFrame 的 304/368），说明 Frame 字段是“事件所属逻辑帧”，不是记录在文件中的顺序号。

### 4.6 全流顺序解析（第二轮，2026-10-28/29）

第一轮只人工核对到偏移 0x3E0 附近。第二轮做了两件事：先枚举出记录类型的权威命名，再把操作流交给「最小不确定度动态规划」做全流顺序解析（工具：`operator_stream.py`；研究原型：`_analysis/tools/operator_stream_census.py`、`meta_enum_values.py`）。

#### 4.6.1 记录类型 = `emOperatorDataType` 枚举（✅ 权威）

`global-metadata.dat` 中的枚举 `Assets.Scripts.OperatorMonitor.emOperatorDataType` 常量按 1 字节底层类型存储，值恰为 0x00–0x1B 顺序编号，与观察到的 type 字节完全一致：

| 值 | 枚举名 | 对应类（字段来自 metadata） | 样本计数 |
| --- | --- | --- | --- |
| 0x00 | Common | 基类 `OperatorData`（只写 Frame） | 多 |
| 0x01 | UnityFrameOpe | `UnityFrameOperatorData`（0 字段） | 多 |
| 0x02 | GameCoreFrameOpe | `GamecoreFrameOperatorData`（0 字段） | 多 |
| 0x03 | SkillUseOpe | `SkillUseOperatorData`（SlotType, SkillId, SkillSeq） | 有 |
| 0x04 | SkilOpe | `SkillUIOperatorData`（TouchPosition, SlotType, TouchId） | 有 |
| 0x05 | TouchOpe | `TouchOperatorData`（TouchPosition, TouchId, TouchPhase, SlotType） | 有 |
| 0x06 | MoveOpe | `MoveOperatorData`（Degree, GameSvrPing, Seq） | 有 |
| 0x07 | CoreChangeOpe | 类未定位 | 少 |
| 0x08 | SkillBtnForceUpOpe | `SkillBtnForceUpOperatorData`（ButtonState） | 少 |
| 0x09 | RefreshSkillBtnStatusOpe | `RefreshSkillBtnStatusOperatorData`（3 字段） | 未单见 |
| 0x0A | UIntOpe | `UIntOperatorData`（Value） | 多 |
| 0x0B | UIEventOpe | `UiEventOperatorData`（EventID） | 有 |
| 0x0C | CppEventOpe | `CppEventOperatorData`（SlotType, SkillId, Value） | 有 |
| 0x0D | BtnBrokenContactOpe | `BtnBrokenContactOperatorData`（RawGameObjectInstId） | 少 |
| 0x0E | GameObjectNameOpe | `GameObjectNameOperatorData`（路径） | 少 |
| 0x0F | UIViewChangeOpe | `UIViewChangeOperatorData`（ViewType, Open） | 少 |
| 0x10 | MemoryData | `MemoryOperatorData`（Stream） | 有 |
| 0x11 | CustomLog | `CustomLogData`（Log） | 少 |
| 0x12 | SkillHitRate | `SkillHitOperatorData`（6 字段） | 少 |
| 0x13 | SkillSlotOpe | `SkillSlotOperatorData`（SlotType, Value） | 多 |
| 0x14 | SkillCancelOpe | `SkillCancelOperatorData`（4 字段） | 有 |
| 0x15 | DirSkillOpe | `DirSkillUseOperatorData`（Degree） | 少 |
| 0x16 | UILayout | `UILayoutData`（20 字段） | 2 |
| 0x17 | PredictMoveOpe | `PredictMoveData`（3 字段） | 未单见 |
| 0x18 | SendMsgToServerOpe | `SendNetworkMsgToServerData`（CSMsgID, result） | 少 |
| 0x19 | DeadOrReviveOpe | `HeroDeadOrReliveData`（hostPlayerId, curPlayerId, reviveTime, configId, isDead 等 8 字段） | 少 |

0x1A/0x1B 是 `Num`/`Max` 哨兵。**type ≥ 0x1A 不可能是记录**——此前用 ≥0x20 回退形态凑出的“97.5% 覆盖”已判定为误配路径并废弃。

#### 4.6.2 已确认形态（样本反复验证，代价 0）

- `0x00 Common`：`frame` 或 `frame + varint UnityFrame` 两种形态（与 0x02 平行）。
- `0x02 GameCoreFrameOpe`：`frame ± varint UnityFrame`（内联/独立 UnityFrame 两形态）。
- `0x05 TouchOpe`：`frame + 4 或 5 个 varint`（对应 TouchPosition/TouchId/TouchPhase/SlotType 的两种序列化）。
- `0x06 MoveOpe`：`frame + 3 个 varint`（恰好 Degree/GameSvrPing/Seq）或更多（5–7，多出部分与独立 UnityFrame 等价）。
- `0x0C CppEventOpe`：`slot u8 + 1–3 个 varint`；样本出现对称四元组 `[slot, 1, value, 8]`。
- `0x13 SkillSlotOpe`：`frame + slot (+ value)`，4/5 字节两形态。
- `0x16 UILayout`：`frame + 123 字节`（长度来自流头 u32@0x07）。
- `0x03 SkillUseOpe`、`0x04 SkilOpe`、`0x0A UIntOpe`（`frame + u32` 或 varint）、`0x0E/0x10`：形态见 `operator_stream.py` 的 LAYOUTS。

#### 4.6.3 当前状态：严格解析 + 诚实报墙

解析器只接受 0x00–0x19 的记录类型，不再伪造回退。在样本上 DP 最远推进到 **0x3556（13.5%）** 后报墙：0x3556 起为 `b9 08 01 c5 f3 01 …`，而 0x3555 的 `02`（GameCoreFrameOpe）要求前一条记录结束于 0x3555，但其尾部 `8e f9` 两个字节都带 varint 继续位、无法按 varint 收尾——说明 SkillUse/CppEvent/SkillSlot 在该区域存在**固定位宽字段（疑似 `WriteBitPacked`/`WriteUshort`）或未解码的变体**。工作台导入该样本时如实显示“操作流未解析 + 报墙位置”，不输出基于误配的计数。

已排除的解释：type ≥ 0x1A 记录（枚举否定）；`a2 5c` 按 3 字节 varint 读取（0x5c 无继续位，定死为 2 字节）。

#### 4.6.4 下一步

原计划是反汇编各 `*OperatorData.Write`/`Read` 拿字段顺序与位宽。2026-10-29 的第三轮结论修正了这条路（见 5.5）：`.so` 里没有 CodeRegistration/CodeGenModule 可解，而 `*OperatorData.Write` 实为「C# 对象 → native 结构」的字段搬运，不是位流序列化；真正的位级写入器是基类的 `WriteInt/WriteShort/WriteUshort/WriteBitPacked/WriteVector2`（`0x597774c`–`0x5978300`），这段正好被 16 KB 页级加密覆盖。

因此当前优先级：

1. 还原页级加密（4 KB 粒度，`DT_INIT = 0xe56145c`）以取出位级写入器；
2. 或在 `.text` 明文页里找同一批位写入器的其他实例（编译器可能内联复制过）；
3. **补充样本**：字节级模型已证明欠定（5.6.4，仅 19.1% 区间唯一），同一版本的第二个 `.ope` 可做差分——结构相同、数值不同，恒定字节即头/常量、变化字节即字段，无需代码也能消歧。这是当前成本最低的一步。

---

## 5. 客户端分析框架

### 5.1 metadata 定位

`global-metadata.dat`（v29）关键表：

| 表 | 偏移 | 大小 | 条目 |
| --- | --- | --- | --- |
| 字符串表 | 2,765,268 | 11,636,084 | — |
| methods | 15,361,132 | 13,332,640 | 416,645 × 32 字节 |
| fields | 43,065,624 | 5,312,832 | 442,736 × 12 字节 |
| typeDefinitions | 52,335,416 | 5,643,000 | 64,125 × 88 字节 |

类型记录布局（已验证）：

```text
16 个 int32/uint32:
  name, namespace, byval, byref, decl, parent,
  elem, flags, fieldStart(w8), methodStart(w9),
  eventStart(w10), propertyStart(w11),
  nestedStart(w12), ifaceStart(w13),
  vtableStart(w14), ifaceOffStart(w15)
8 个 uint16:
  method_count, property_count, field_count, event_count,
  nested_type_count, vtable_count, interfaces_count,
  interface_offsets_count
2 个 uint32:
  bitfield, token
```

方法记录 32 字节，字段记录 12 字节。

镜像表位于 metadata header pair 21：

```text
offset = 0x374AE30
size = 4,600 = 115 × 40
```

`Assets.Scripts.OperatorMonitor` 的类型索引约 **34280**，落在镜像：

```text
Scripts.Base.dll
typeStart = 30409
typeCount = 9045
```

本版本客户端没有 `Assembly-CSharp.dll` 镜像，脚本被拆成 `Scripts.System.dll`、`Scripts.Base.dll`、`Scripts.GameCore.dll`、`Scripts.GamePlay.dll` 等。

### 5.2 `OperatorMonitor` 主要类型

已确认存在（108 个相关类型）：

- `OperatorMonitorModule`
  - `Read`
  - `GetOperatorDataIEnumerator`
  - `Write`
  - `FlushClose`
  - `BatchPush`
  - `ReadOperatorDataListFromMemoryInToolMode`
  - `WriteOperatorDataListToMemoryInEditorMode`
  - `GetMemoryStream`
  - `GetData`
  - `CountOperatorData`
  - `GetOperatorCount`
- `OperatorAnalyzeSystem`
  - `OnFightStart`
  - `OnGameEnd`
  - `OnReceiveOperatorData`
  - `Analyze`
  - `ProcessAnalyze`
  - `AddAnalyzer`
  - `GetOperatorAnalyzer`
- `OperatorMonitorConfig`
  - `IsUploadFile`
  - `FullOpeMode`
  - `OpeUploadPerfsight`
  - `MEMORY_CAPCITY`、`FULL_OPE_MEMORY_CAPCITY` 等容量参数
- `OperatorAnalyzeResult`
  - `AddResultEntity`
  - `AddResultCurve`
  - `AddGameObject`
  - `ApolloRepoertEvent`
  - `ReportTLog2`

### 5.3 分析器覆盖范围

样本 metadata 中确认的分析器包括：

```text
AccidentalIdleAnalyzer
BrokenTouchlAnalyzer
CommonAttackAnalyzer
DownUseSkillSlowAnalyzer
GameObjectOpeAnalyzer
JoystickBrokenContactAnalyzer
MoveFixJoystickAnalyzer
PlayerOpeUnitsAnalyzer
PredictMovementAnalyzerLocal / Online
SameSlotBreakAnalyzer
SkillFixJoystickAnalyzer
SkillHitRateAnalyzer
SkilLinkAnalyzer
SkillLinkFlashAnalyzer
SkillLongPressAnalyzer
SkillSlotStatusAnalyzer
SkillUnexpectedCancelAnalyzer
SkillUnexpectedTerminationAnalyzer
SkillLimitAnalyzer
SkillCDAnalyzer
SkillUseEventAnalyzer
SpecialStatusTimerAnalyzer
TouchMissUpAnalyzer
UnexpectedPanelPopAnalyzer
```

它们覆盖：

- APM / 操作单位；
- 技能槽效率、拖拽/点击技能；
- 技能命中率、瞄准灵敏度；
- 连招、长按、同槽打断；
- 摇杆断触、移动/技能摇杆偏移；
- 技能取消、意外终止、面板弹出；
- 预测移动表现。

### 5.4 数据流推断

```text
游戏内操作
  -> OperatorDataPlayer 采集触控/技能/移动/UI 事件
  -> OperatorMonitorModule 序列化到内存/文件（.ope）
  -> 对局结束/上传时生成 .ope
  -> 客户端 OperatorAnalyzeSystem 读取 .ope
  -> 各 Analyzer 产出报表实体
  -> ApolloReportEvent / ReportTLog2 上报分析平台
```

`.abc` 则走另一条回放链路：

```text
游戏逻辑帧/命令
  -> GameReplayModule 录制 .abc
  -> ReplayControl / VisualFrameReplayManager / CShmReplayConsumer 回放
  -> 客户端重建战场、UI、数据面板
```

这两条链路是**成对保存但职责不同**的：

- `.abc`：比赛过程/命令；
- `.ope`：录制设备本机操作数据。

---

## 5.5 IL2CPP 二进制解析（2026-10-29 第三轮，反汇编路线）

### 5.5.1 先排除的疑点：不是两套构建

`.ope` 头里的 `12.1.1.1 / 4989537` 与 `12.1.1.23 / 5230306` 是**同一次客户端安装**里同时写下的两个版本对（app 版本 + 资源/src 版本），不是两个构建。真正的构建一致性用二进制特征验证：

| 检验 | 结果 | 判定 |
| --- | --- | --- |
| metadata methods 表 | 13,332,640 / 32 = **416,645** 条 | — |
| typeDefinitions 的 method_count 求和 | **416,645** | 自洽 |
| `.data`(VA `0x0d380ce0`) 起 416,645 槽 | 97.5% 有 `R_AARCH64_RELATIVE`，405,642 个唯一 `.text` 目标，**0 重复** | 与 metadata 同量级 |
| `.text` 中 `ret` 指令数 | **458,014** ≈ 416,645 方法 + 约 4.1 万运行期函数 | 吻合 |
| 40 个 `*OperatorData.Write/Read` 落点 | 全部落在 `0x5977428`–`0x597fab0` 的 **0x8700 字节**内 | 完全吻合 |

反证同样干净：每模块方法数（`Scripts.Base` 55,613 / `GameCore` 38,222 / `System` 85,197）在整个 227 MB 里**没有任何一次**以 u32 字段形式出现。**结论：`.so` 与 metadata 是同一构建。**

### 5.5.2 之前所有锚点失败的真正原因：这个 `.so` 里没有标准 il2cpp 注册结构

不是找法不对，是结构不存在：

| 标准结构 | 本二进制实测 |
| --- | --- |
| `Il2CppCodeGenModule.moduleName`（"Scripts.Base.dll" 等） | 全文件 0 次命中（`Scripts.` 也是 0） |
| `CodeGenModule` 的 `(count, methodPointers)` 组合 | `.data` / `.data.rel.ro` 全扫 **0 命中** |
| `codeGenModules` 115 指针数组 | 0 命中（连 100~130 长连续 data 指针窗都没有） |
| `CodeRegistration`(`u32 115` + 指针) | 0 命中 |
| `.data` 内容 | 725,841 个字里 714,371 个 `.text` 指针、120 个 <64K 小整数 |
| `.data.rel.ro` 内容 | 135,491 个字里只有 **415 个**小整数 |
| `DT_INIT_ARRAY` | **不存在**；`DT_INIT = 0xe56145c` 落在文件尾独立 12 KB 可执行段 |

即：**方法体还在，但注册元数据（模块名、每模块方法数、CodeGenModule 数组）被剥离或改为运行时构造**。本构建还带自定义改名（`.rodata` 里有 `((CppEventOperatorData_t2C731DF…*)CastclassClass((RuntimeObject*)L_213, PRE_TYPEINFO_2C731DF…))` 这类自描述字符串，类型名被 `<Name>_t<SHA1>` 与 `PRE_TYPEINFO_<SHA1>` 替代）。

### 5.5.3 页级代码加密

`.text` 按 **4 KB 页**加密：

- 随机 400 个 `.text` 采样点、每点线性反汇编 16 条：**75% 整段可解码，25% 整段不可解码**；
- 不可解码的页是**连续块**，不是散点。`*OperatorData` 家族正好横跨一个 16 KB 加密块：

```text
0x5970000  可解码
……
0x5975000  可解码
0x5976000  ✗ 加密
0x5977000  ✗
0x5978000  ✗
0x5979000  ✗
0x597a000  可解码
```

这个块恰好盖住 **基类 `OperatorData`（含 WriteInt/ReadInt/WriteShort/WriteUshort/WriteBitPacked/ReadBitPacked/WriteVector2）+ Move / Touch / SkillUse / SkillUI / UnityFrame / GamecoreFrame**——也就是 `.ope` 位级打包最关键的一批函数。40 个 Write/Read 里 27 个落在明文页、13 个落在加密页。

### 5.5.4 从 metadata 拿到的权威结构（本轮修正）

类型记录里 **`int[8] = fieldStart`、`uint16[18] = fieldCount`**（不是 `int[10]`，那是 `eventStart`）。据此得到的字段表语义完全自洽：

| 类型 | 字段（声明顺序） |
| --- | --- |
| `OperatorData`（基类） | `Frame`, `UnityFrame`, `OperatorType` |
| `UnityFrameOperatorData` | —（仅基类字段） |
| `GamecoreFrameOperatorData` | —（仅基类字段） |
| `SkillUseOperatorData` | `SlotType`, `SkillId`, `SkillSeq` |
| `SkillUIOperatorData` | `TouchPosition`, `SlotType`, `TouchId` |
| `TouchOperatorData` | `MAX_TOUCH_ID`, `TouchPosition`, `TouchId`, `TouchPhase`, `SlotType` |
| `MoveOperatorData` | `Degree`, `GameSvrPing`, `Seq` |
| `SkillBtnForceUpOperatorData` | `ButtonState` |
| `RefreshSkillBtnStatusOperatorData` | `ForceUseWhenLimited`, `DisableFlags`, `SlotType` |
| `UIntOperatorData` | `Value` |
| `UiEventOperatorData` | `EventID` |
| `CppEventOperatorData` | `SlotType`, `SkillId`, `Value` |
| `BtnBrokenContactOperatorData` | `RawGameObjectInstId` |
| `GameObjectNameOperatorData` | `GameObjectPath`, `GameObjectInstId` |
| `UIViewChangeOperatorData` | `ViewType`, `Open` |
| `MemoryOperatorData` | `Stream` |
| `SkillHitOperatorData` | `skillId`, `_skillData`, `skillSeq`, `defaultTargetId`, `isSkillCastSucces`, `Shape` |
| `SkillSlotOperatorData` | `SlotType`, `Value` |
| `SkillCancelOperatorData` | `SkillId`, `CancelTime`, `CancelDistance`, `OpenDebug` |
| `DirSkillUseOperatorData` | `Degree` |

枚举 `emOperatorDataType`（顺序即 .ope 里的 OperatorType 取值域）：`Common, UnityFrameOpe, GameCoreFrameOpe, SkillUseOpe, SkilOpe, TouchOpe, MoveOpe, CoreChangeOpe, SkillBtnForceUpOpe, RefreshSkillBtnStatusOpe, UIntOpe, UIEventOpe, CppEventOpe, BtnBrokenContactOpe, GameObjectNameOpe, UIViewChangeOpe, MemoryData, CustomLog, SkillHitRate, SkillSlotOpe, SkillCancelOpe, DirSkillOpe, UILayout, PredictMoveOpe, SendMsgToServerOpe, DeadOrReviveOpe, Num, Max`。

全量（含方法地址）见 `_analysis/tools/operatordata_family.json`。

### 5.5.5 关键语义修正：`*OperatorData.Write` 不是位流序列化

明文页里的 `UIntOperatorData.Write`（`0x597ae30`）实测是**字段搬运**，不是写流：

```asm
ldr  w8, [x19, #0x18]   ; this->0x18  (uint)
str  w8, [x0, #0x14]    ; dst->0x14
ldrb w8, [x19, #0x1c]   ; this->0x1c  (bool)
strb w8, [x0, #0x30]    ; dst->0x30
mov  w1, #0xe69         ; 常量（类型/事件 id）
br   x4                 ; 尾调用
```

`OperatorMonitorModule.Write`（`0x5980b64`）同样是按固定偏移 `0x18/0x1c/…/0x6d` 把结构体字段拆到一串出参里，并先做 `cmp w11, #0x54`（Operatortype 84）判断。

所以这两类 `Write` 是 **C# 对象 ⇄ native 结构的编组层**。`.ope` 的位级布局由基类 `WriteInt / WriteShort / WriteUshort / WriteBitPacked / WriteVector2` 那一组决定——而这组正好在 5.5.3 的加密块里。

### 5.5.6 仍未坐实的一点（下一轮入口）

`.data` 那 416,645 槽可以当「方法索引 → 地址」用，但**逐条对应还没坐实**：

- 只有 996 次逆序（0.25%）、0 重复 → 很像方法指针数组；
- 但 20 个 `get_OperatorDataType` 样本没有一个长成 `mov w0,#imm; ret`；
- 9,210 个空槽与 abstract（147 个）/ generic（102 个）都对不上。

更可能的身份是「按地址排序的符号表」而不是 `methodPointers`。坐实办法：用 `.ctor` 链（每类型 `.ctor` 必在块尾）或字符串常量交叉验证；或直接解 5.5.3 的加密页。

### 5.5.7 本轮工具

| 脚本 | 作用 |
| --- | --- |
| `tools/check_build_match.py` | metadata 总表统计 + 程序头/动态段 |
| `tools/probe_plaintext.py` | `.rodata`/`.text` 熵与 ASCII 密度、模式串计数 |
| `tools/materialize_relocs.py` | RELA 物化、连续槽游程、115 指针数组搜索 |
| `tools/count_fingerprint.py` | 每模块方法数在 `.so` 中的存在性检验 |
| `tools/method_order_test.py` | `.data` 单调性 → 方法指针数组定位 |
| `tools/kpl_i2cpp.py` | 最小可复用访问器（slot / 名称 / 反汇编） |
| `tools/resolve_methods.py` | 方法名 → 索引 → 地址 |
| `tools/follow_trampolines.py` | `adrp/ldr/br` 跳板链追踪 |
| `tools/dump_operator_family.py` | 家族字段表 + 方法地址 → `operatordata_family.json` |

---

## 5.6 操作流容器链与分段歧义（2026-10-29 第四轮）

### 5.6.1 容器链（已逐字节验证）

```text
.ope 文件
  = 1 字节 0x01 + raw DEFLATE 流                (14,355 -> 14,349)
inner = 头 0x8A(138) 字节 + u32 负载长度 + 负载
        u32@0x86 = 14,211 = len(inner) - 0x8A   ✅ 完全相等
        负载首字节 = 0x01（算法/版本标记）
stream = Oodle(负载) -> 39,634 字节操作流（27 字节流头 + 记录）
```

`_analysis/ope_decoded.bin` 就是最内层的 39,634 字节流。工具：`tools/ope_container.py`。

内层头可用长度前缀 ASCII 字段无损还原，已能稳定取出：

| 字段 | 样本值 |
| --- | --- |
| 客户端版本 | `12.1.1.1` |
| 资源版本 | `12.1.1.23` |
| 构建号 | `4989537` |
| 机型 | `Vivo V2546A` |
| 账号 | `2B9FAA08A7AD40D09ABDA364F9C1E804` |
| 本地时间 | `2026-10-28 13:55:16` |

### 5.6.2 流内锚点：2,000 个 `01 <varint>` 帧标记

`0x01`（UnityFrameOpe）记录是自定界的，扫描得到 **1,999 个候选 + 边界**，其 varint **严格单调** 28,523 → 35,194，中位间距 **16 字节**，最大 231 字节，覆盖流内 94.7% 的字节（其余是锚点本身）。

这是全流唯一可靠的时间轴，也是把"全流一次 DP"换成"逐段精确填满"的依据。

### 5.6.3 证伪：记录头不是 `type + Frame:u16`

4.2 节的"每条记录带 u16 帧号"模型被数据否定：

- 按该模型解出的 5,132 个帧号里 **39.5% 相对前值递减**（396→402→401→400→396），不符合时间轴；
- `0x13`（SkillSlotOpe）在 `0x0099` 起的 **65 条连续记录**里，`ae 01` 恒定不变（430），随后 13 个槽位值全为 1；下一批同样 13 槽全为 0。**帧号不可能在 65 条记录里恒定**，所以 `13 ae 01` 是常量字段而非帧。

由此得到的可信结构：**SkillSlot 快照**。

```text
13 AE 01 <slot:u8> <value:u8>      5 字节/条
槽位集合固定 13 个：0,1,2,3,4,5,6,7,8,9,15,10,11（顺序固定）
本次样本共 187 个 burst，其中 11 个是完整 13 槽
```

### 5.6.4 分段歧义：字节级语法欠定

用"锚点 + 已知 layout 精确填满"重解全流：**99.9% 字节可被覆盖、7,604 条记录、0 个失败段**。但逐段统计可行解数量：

| 每段解数 | 段数 | 占比 |
| --- | --- | --- |
| 1（唯一） | 383 | 19.1% |
| 2 | 1,115 | 55.8% |
| ≥3 | 275 | 13.8% |
| 0（该段 layout 缺失） | 227 | 11.4% |

即：**平均每段有两种同样合法的切法**（例如 `0a 00 13 ae 01 0b 00` 既可解成一条 `UIntOpe(frame=4864,value=721326)`，也可解成 `UIntOpe` + 一条 `SkillSlot(slot=11,value=0)`）。

结论：字节级模型（type + u16 + varint）**信息量不足**，任何单一选择都是猜测。这也是 4.6.3 报墙的根因——不是 DP 不够聪明，是语法本身欠定。对外发布计数前必须先消除歧义。

### 5.6.5 代码路径现状

- `DT_INIT = 0xe56145c` 处**是真代码**（不是零页）：`sub sp,#0x90` → `mrs x20,tpidr_el0` → `svc #0`（w0=0x19 / x8=0x5e）→ `bl 0xe562548`；后者遍历 `x0+0x20` 起、步长 `0x38` 的表，比对指针并做页对齐修正——是壳自己的重定位处理，不是页解密循环。
- 全 `.text` 仍是 4 KB 页级加密（随机采样 25% 页不可解码），位级写入器 `WriteInt/WriteShort/WriteUshort/WriteBitPacked` 在 `0x597774c`–`0x5978300` 整段被加密覆盖。
- `.dynstr` 显示依赖 `libtprt.so`、`libunpacker.so`（腾讯保护运行时），**这两个库不在样本里**，因此离线解密缺少密钥/算法载体。

---

## 5.7 代码混淆已破：单字节 XOR 0xE3（2026-10-29 第五轮）

### 5.7.1 现象

全 `.text`（159 MB）按 4 KB 页统计"能否线性反汇编"：**25.0% 的页完全不可解码**（38,892 页里 9,725 页），且落点是**规则的**——每 64 KB 里固定 4 页，共 2,427 个 4 页窗口。当初据此判断是"页级加密"。

### 5.7.2 破法

对不可解码页做单字节 XOR 暴力搜索，**0xE3 命中率 100%**：

| 页 | 原始 | XOR 0xE3 |
| --- | --- | --- |
| `0x5976000` | 0/1024 条可解码 | **1024/1024** |
| `0x5977000` | 0 | 1024 |
| `0x597a040` | 1024（本就明文） | 0 |

对照实验（证明不是巧合）：随机字节从任意起点线性反汇编只能得到 **0–1 条**；XOR 0xE3 后整页 4 KB 连续 1024 条全部合法，且密文占比恰为 0.249。

### 5.7.3 粒度是"函数/字"，不是"页"

同一页里会**明文函数与密文函数混排**（例如 `0x3a95a40`：raw 能解 417 条、XOR 后 0 条；`0x3a99a40`：raw 1 条、XOR 后 368 条）。所以逐页选一个 key 会失败（这正是上一轮 4,859 页"解不开"的原因）。

改用**逐 4 字节字的二状态 DP**（key ∈ {0x00, 0xE3}，按"该字是否构成合法指令"打分，切换加惩罚）：

```text
201 页采样：平均合法指令率 1.000，平均密文字占比 0.249
```

`0x5976000` 这类整页密文的 enc_share = 1.00，`0x597a040` 这类明文页 = 0.00，混合页自动切分。

### 5.7.4 影响

- 上一轮判定"位级写入器 `WriteInt/WriteShort/WriteUshort/WriteBitPacked`（`0x597774c`–`0x5978300`）不可读"**已作废**——这段现在可以完整反汇编。
- 工具：`tools/i2_word_decrypt.py`（`decrypt_page()` 返回解密字节 + 每字 key 图）、`tools/i2_decrypt.py`（按 VA 读/反汇编，自动选 key）、`tools/page_encryption_map.py`（页图统计）。
- 混淆本身很弱（单字节、单常量、无密钥派生），说明它的目的只是**打断静态反汇编**，不是真正的密码保护——这也解释了为什么保护库里没有专门算法。

### 5.7.5 仍未解决：`.data` 槽位 → 方法 的索引对应

解密后重测槽位映射：取 `Il2Cpp` 槽位表里 `183203..183410`（`OperatorData` 家族）与 120 个随机槽，检查"目标前一条是 `ret/b/br` 且目标本身像函数开头"的比例，**只有 40%，且 ±1/±2 平移完全不变**（40.4% / 40.4% / 40.4%）——说明该比例是基线，槽位并非函数起点。

另一条旁证：槽位 0 指向 `0x3ac9fdc`，只比 `.text` 起点晚 0x4F59C，属于 il2cpp 运行时区，不可能是 C# 方法。**结论：`.data` 那张表是按地址排序的符号表，不是 `methodPointers`**，不能按 metadata 索引取方法。

因此"`OperatorData.Write` 在哪"仍未定位，位宽提取还差这一步。

---

## 5.8 定位 `*OperatorData.Write` 的尝试（2026-10-29 第六轮）

### 5.8.1 新工具：ADRP+ADD 引用扫描（可用）

`tools/find_string_refs.py` 能在整个 `.text`（159 MB）里找"哪条指令引用了某个 `.rodata` 地址"——同时匹配明文与 XOR 0xE3 两种字，按 VA 对齐分页（`.text` 文件切片起点比页边界晚 0xa40，按数组下标分页会整体错位，这一点已修正）。

用已知引用 `0x17f5125`（`GameObjectNameOperatorData.Read` 里的 `adrp x0,#0x17f5000; add x0,x0,#0x125`）验证：命中 **48** 处，工具可用。

### 5.8.2 三个被证伪的锚点

| 设想 | 结果 |
| --- | --- |
| `.rodata` 的 `((CppEventOperatorData_t…*)CastclassClass(…))` 字符串是转型点，可反查 OperatorData 代码 | **否**。引用它的代码都是连续 `adrp/add; bl 0x3a84ef4`（`raise_exception`）——那是**异常消息表**，不是转型点 |
| `get_OperatorDataType` 编译成 `mov w0,#imm; ret`，可按指令模式定位 27 个类 | 模式扫描命中 400+ 且 `imm=1` 占绝对多数（假阳性），需要函数边界过滤，暂不可用 |
| 槽位表就是 `methodPointers`，索引即 metadata 方法序号 | **否**，见 5.8.3 |

### 5.8.3 槽位映射在解密后再次被否

用解密后的代码复核三个索引（此前部分证据读的是密文，这次全部是明文）：

| 索引 | 期望形态 | 实际 |
| --- | --- | --- |
| 281771 `System.String.get_Length` | `ldr w0,[x0,#0x10]; ret` | 大函数，`ldrh w20,[x2,#0x50]` 读 MethodInfo 字段 |
| 285214 `System.Object..ctor` | 空函数 `ret` | 同样是大函数，`cbz x1` 后访问 MethodInfo |
| 183207 `OperatorData.Write` | 接收 writer、写字段 | `adrp; ldr x0,[x8,#0xf80]; ret` —— 静态字段 getter |

结论不变：`.data` 起址那张 416,645 槽的表**不是按 metadata 顺序的方法指针数组**，不能按索引取方法。

### 5.8.4 结论：静态路线到此为止，该转动态

静态可做的都做了：代码已解密、结构已定性、引用扫描可用。剩下缺的是**运行期才建起来的东西**：

- `Il2CppClass` / `MethodInfo` 在 BSS 里由加载器构造（`.data` memsz 18.7 MB vs filesz 5.8 MB，12.9 MB 是零填充）；
- 页解密与注册表填充由 `libtprt.so` / `libunpacker.so` 完成，这两个库不在样本里；
- 因此"方法 → 代码地址"的权威映射只在内存里存在。

下一步只有两条：

1. **动态 dump**（推荐）：在 root 设备/模拟器上把游戏跑起来，从 `/proc/<pid>/maps` 定位 `libil2cpp.so`，dump 内存镜像——一次拿到解密后的 `.text`、构造好的 `Il2CppClass`/`MethodInfo`（`MethodInfo` 首字段就是 `methodPointer`）。代价是需要一台能跑游戏的设备。
2. **第二个 `.ope` 样本**做差分，绕开代码直接解出记录布局。

---

## 5.9 动态 dump 流程（待执行）

### 5.9.1 为什么必须动态

静态能做的已经做完（代码解密、结构定性、引用扫描）。缺的三样东西都只在运行时存在：

| 缺什么 | 为什么静态拿不到 |
| --- | --- |
| 方法 → 代码地址 | `.data` 里那张 416,645 槽的表不是 methodPointers（5.8.3），真正的映射在 `MethodInfo.methodPointer`（首字段），而 `MethodInfo` 建在 BSS |
| `Il2CppClass` / vtable | `.data` memsz 18.7 MB vs filesz 5.8 MB，12.9 MB 零填充，由加载器填 |
| 页解密/注册表填充逻辑 | 在 `libtprt.so` / `libunpacker.so`，样本里没有 |

### 5.9.2 工具

| 脚本 | 作用 |
| --- | --- |
| `tools/dump_runtime.py` | 连设备 → 提权 → 找 pid → 解析 `/proc/<pid>/maps` 里 `libil2cpp.so` 的段 → 从 `/proc/<pid>/mem` 按段 dump → 拉回本机，产出 `memory.bin` + `manifest.json` |
| `tools/analyze_dump.py` | 在 dump 里找 `*.dll` 字符串 → 回搜指针得到 `Il2CppCodeGenModule` 记录 → 找 115 条连续指针组成 `codeGenModules` → 输出每模块 `methodPointers` 地址 |

`dump_runtime.py` 支持 `--connect-mumu`（自动问 MuMuManager 要 adb 端口并连接）、`--skip-exec`（只 dump 非执行段，通常 < 40 MB，足够拿注册结构与字符串）。

### 5.9.3 操作步骤

```text
1. 手动启动 MuMu（本机 D:\MuMuPlayer\nx_main\MuMuManager.exe control -v 0 launch，
   或直接双击 MuMu 图标）——沙箱里 sc.exe 被拦，必须人工启动。
2. MuMu 设置 → 其他 → 打开「root 权限」，重启实例。
3. 启动游戏（王者荣耀），停在任意界面即可，不必进对局。
4. 回本机执行：
   python data/replays/_analysis/tools/dump_runtime.py --connect-mumu --skip-exec
5. 解析：
   python data/replays/_analysis/tools/analyze_dump.py data/replays/_analysis/runtime_dump
```

第 5 步成功的话，会直接打印 115 个模块的 `methodPointers`；之后按 `token & 0xFFFFFF - 1` 取方法地址，`OperatorData.Write` 的机器码就到手了。

### 5.9.4 预期与风险

- 预期 dump 体积：非执行段约 20–40 MB（`.rodata` 7.9 MB + `.data.rel.ro` 1 MB + `.data` 18 MB），全量约 230 MB。
- 风险一：`/proc/<pid>/mem` 在 SELinux enforcing 下可能拒读，脚本已先尝试 `adb root`、再 `su -c setenforce 0`。
- 风险二：MuMu 的 adb 端口随实例变化，`--connect-mumu` 会现查。
- 风险三：游戏 32/64 位不同会导致 `libil2cpp.so` 路径不同（`lib/arm64` vs `lib/arm`），`read_maps` 按文件名匹配，两种都能抓。

---

## 5.10 动态执行结果（2026-10-29 第八轮，含三条更正）

环境：MuMu `MuMuPlayer-15.0-0`（Android 15，x86_64 + **libhoudini** ARM 转译），`adb root` 可用，包 `com.tencent.tmgp.sgame`，`libil2cpp.so` 基址 `0x400026200000`，设备上的 `.so` 与本地样本 **md5 完全一致**（`43bc62bd0947e10a0ccf2ff1ac23cdd9`）。

### 5.10.1 运行时镜像布局（实测）

| 映射 | VA | 大小 | 说明 |
|---|---|---|---|
| `libil2cpp.so` 头段 | `0x400026200000`–`0x400029c84000` | 58.52 MB | 文件 offset 0 起，含 ELF 头与 `.rodata` |
| `.text` | `0x400029c84000`–`0x400033475000` | 151.94 MB | **内存中已解密**，`r--p`（转译层执行自己的副本） |
| `.data.rel.ro` | `0x400033475000` | 1.04 MB | |
| `.data` | `0x400033580000` | 5.54 MB | 文件 offset `0xd37d000` |
| BSS | `0x400033b0b000` | 12.32 MB | 匿名，非零 104 万词 |
| **metadata** | `0x77faabcad000` | **57.55 MB** | `_$$global-metadata$$_.dat`（tmpfs 共享映射） |

**更正 1（关键）**：`global-metadata.dat` 在运行时是**独立的匿名/共享映射**，完全不在 `libil2cpp` 的任何段里。前几轮所有“内存里也搜不到 `Scripts.Base.dll` / 方法名”的结论，都是因为只 dump 了 lib 的段。`get_OperatorDataType` 在 `0x77faac56c621`，`get_Length` 在 `0x77faabf00e40`。

**更正 2（工具 bug）**：toybox 的 `dd` **不支持** `iflag=skip_bytes,count_bytes`，写了不报错但会把 `skip`/`count` 当块数处理，导致每段起点整体错位。第一版 dump 因此是错的（`.data` 内容与 live 内存完全不同）。改用 `bs=4096` + 页对齐 `skip`/`count`，并对每段做“首 32 字节 live 重读比对”，63/63 段全部通过。

**更正 3（推翻 5.8.3）**：文件 `.data` 的槽位表 + metadata 方法索引，**映射是正确的**。用内存中解密后的代码复核 `OperatorData`：

```
idx=183203 get_OperatorDataType  0x5977320      idx=183212 WriteUshort  0x5977d44
idx=183204 get_DisplayName       0x5977358      idx=183213 ReadUshort   0x5977d48
idx=183205 get_SimpleDisplayName 0x59773d4      idx=183214 WriteBitPacked 0x5977d4c
idx=183206 Read                  0x5977428      idx=183215 ReadBitPacked  0x5977d58
idx=183207 Write                 0x5977430      idx=183216 ReadVector2  0x59782e8
idx=183208 WriteInt              0x597774c      idx=183217 WriteVector2 0x5978300
idx=183209 ReadInt               0x5977bdc      idx=183218 Send         0x59783d4
idx=183210 WriteShort            0x5977d20      idx=183222 .ctor        0x597859c
```

21 个方法地址严格递增、连续排布，`Read` 实测为 `str x1,[x0,#0x40]; ret`（把 reader 存进字段 0x40），形态自洽。5.8.3 之所以判定为“错”，是因为当时用 XOR-DP 解出来的那段代码有问题；从 live 内存直接读，结论相反。**索引映射这条路线恢复有效。**

### 5.10.2 但是：`*OperatorData.Write` 不是回放序列化（最终结论）

拿到解密代码后可以定性了。`OperatorData.Write`（0x5977430，200 条指令）与 `WriteInt`（0x597774c，288 条）里出现的是：

- 标准 il2cpp `IsAssignableFrom` 内联：`ldrb w11,[x9,#0x130]`（typeHierarchyDepth）、`ldr x9,[x9,#0xc8]`（typeHierarchy）、`ldur x9,[x9,#-8]`、`cmp`
- 大量 `adrp/ldr` 取**缓存的 Type 对象**（`[x24,#0x9f8]`、`[x26,#0xe8]`、`[x27,#0x830]`）后做类型分派
- 参数是 `s0..s3` 四个 float，内部 `scvtf / fmul / frintp / fcvtps` 做“浮点 × 系数 → 四舍五入成整数”
- `add x8, x0, #0x135; ldrb w9,[x8,#2]; ldrh w8,[x8]; bfi w8,w9,#0x10,#8` 是取 24 位元数据标记

配合进程里映射了 **`libpuerts.so`**，可以确定：这一层是 **Puerts（TypeScript/Lua 绑定）的 C# ⇄ native 编组层**，用途是把 C# 对象暴露给脚本，与 `.ope` 位流无关。

因此 4.6.4 / 5.8 里“反汇编 `*OperatorData.Write` 拿字段顺序与位宽”的整个计划**不成立**，可以永久划掉——不是找不到，是找错了对象。

### 5.10.3 frida 在本环境的能力边界

- 进程是 **x86_64 ART**，`ro.dalvik.vm.isa.arm64 = x86_64`，arm64 代码由 `libhoudini.so` 翻译执行。
- 因此 `Interceptor.attach` 打在 arm64 地址（`0x400029c84000` 起的 `.text`）**不会生效**——断点写进的是 arm64 字节，而 CPU 执行的是 houdini 生成的 x86_64 副本。
- frida 仍可用于：枚举模块/区间、高速 `Memory.scanSync`、hook x86_64 的 libc/ART。但**读内存这件事 `/proc/<pid>/mem` 已经能做，且更简单**。
- 结论：本环境里 frida 对“定位方法 / 解位流”没有增益，不必再投入。

### 5.10.4 现在的分层判断

| 层 | 位置 | 是否已拿到 |
|---|---|---|
| `.ope` 容器（deflate + 头） | App 层 C# | ✅ 逐字节确认（5.6） |
| 操作流分段（帧锚点） | — | ✅ 1,999 锚点，覆盖 99.9% |
| OperatorData 类字段表 | metadata | ✅ 20 个类型全字段名 |
| **记录语法 / 位宽** | **native 或 Lua** | ❌ 不在 `*OperatorData.Write` |
| 方法索引 → 地址映射 | `.data` 槽位 | ✅ 已恢复有效（5.10.1） |

`libGameCore.so`（41.7 MB）的 `.dynsym` 只有 2,498 个符号，且含 `puaL_openlibs / puaS_openextlibs`——**GameCore 内嵌 Lua**。回放写入若在 native 侧，最可能在 Lua 绑定或 `Il2Cpp` 之外的 C++ 模块里。

---

## 5.11 追 `libGameCore.so` 的结果：写入点其实在 C#（2026-10-29 第十轮）

### 5.11.1 一个决定性的判别实验

`.ope` 的文件名形如 `20261028_135516.ope`，即 `yyyyMMdd_HHmmss` 格式串。于是直接查这个格式串 + `.ope` 字面量落在哪个模块：

| 文件 | `yyyyMMdd` | `.ope` |
|---|---|---|
| `global-metadata.dat` | **2** | **6** |
| `libGameCore.so` | 0 | 0（全部命中都是 `Open…` 的子串） |
| `libil2cpp.so` | 0 | 0 |

**结论：`.ope` 的写入点在 C# 侧（il2cpp），不在 GameCore/Lua。** 5.10.4 里“最可能在 native/Lua”的猜测被推翻。

对照：`libGameCore.so` 的 `.rodata` 里 `Operator*` 只有 `BuffOperatorType / FilterExtraHpOperatorType / OperatorType / SGCore::BinaryOperator` 这类**战斗逻辑**枚举，没有任何回放相关符号。

### 5.11.2 已定位的 `.ope` 流水线（地址为文件内 VA）

`Assets.Scripts.ClientRecord.ClientRecordSystem`（命名空间 `Assets.Scripts.ClientRecord`）：

| 方法 | 地址 | 说明 |
|---|---|---|
| `SaveOperatorFile` | `0x59bdf0c` | 存盘入口，2 参数 |
| `GetOpeTimeStamp` | `0x59bdf70` | 生成 `yyyyMMdd_HHmmss` |
| `SaveOpeNow` | `0x59be038` | 立即存盘 |
| `GetSavePath` | `0x59be0d0` | 路径拼装 |
| `DoOpeSimulator` | `0x59be0e0` | 回放模拟 |
| `LoadFromFile` | `0x59be1dc` | **真实代码**：`ldr w8,[x2,#8]; sub w8,w8,#1; cmp w8,#8; b.hi`，对 1..8 的枚举做跳转 |
| `OnSaveRecordFile` / `AutoSaveFile` / `HistoryAutoSaveFile` | `0x59bde14` / `0x59bde78` / `0x59bdedc` | 触发器 |

`Assets.Scripts.OperatorMonitor.OperatorMonitorModule`（操作流缓冲）：

| 方法 | 地址 |
|---|---|
| `GetMemoryStream` | `0x5981094` |
| `BatchPush`（3 参数） | `0x5980e54` |
| `FlushClose` | `0x5980cbc` |
| `GetData` / `Write` | `0x5980b20` / `0x5980b64` |
| `WriteOperatorDataListToMemoryInEditorMode` | `0x5980fbc` |
| `ReadOperatorDataListFromMemoryInToolMode` | `0x5980ee4` |

另有 `Assets.Scripts.OperatorMonitor.OperatorMonitorSystem`（30 方法）、`Assets.Scripts.GameLogic.OperatorDataPlayer`（37 方法）、`Assets.Scripts.Framework.GameReplayModule`（104 方法）同属这条链。

### 5.11.3 为什么还不能立刻读出位宽

`SaveOperatorFile` / `GetOpeTimeStamp` / `SaveOpeNow` 三个方法编译出来是同一种 **8 指令桩**：

```
ldr  x20, [x0, #0x68]        ; this->m_impl
ldr  x0,  [x20]              ; klass
...  tbz w8,#0xf, <init>     ; 类初始化检查
ldr  x2,  [x0, #0x510]       ; VirtualInvokeData.methodInfo
ldr  x3,  [x0, #0x508]       ; VirtualInvokeData.methodPtr   (slot 0x40)
br   x3
```

即真实实现挂在 `this+0x68` 那个对象的**虚方法槽 0x40**上，静态层面到此为止。`BatchPush` 则是 `il2cpp_codegen_object_new` + `.ctor` 后写入 `this+8`，只是重置缓冲。

### 5.11.4 运行时定位：klass 拿到了，实例没拿到

用 `tools/find_class.py` 扫 388 个 rw 区（369 MB）：

```
pid=60114  metadata_base=0x77faac8af000
name VAs = 0x77faac99fee7 / 0x77faad174418 / 0x77faae8f5707 / 0x77faae948d93
[9/388 regions] 命中  →  klass = 0x77fc2e9bb6d0
校验：klass+0x10 -> metadata 0x77faad174418 -> "ClientRecordSystem"   ✅
       klass+0x00 -> image 0x77fbde9ab430                              ✅
```

但 `[obj]==klass` 的 44 个候选**全是 `FieldInfo` 表项**（不是对象），说明 `ClientRecordSystem` 当前**没有活实例**——它只在进入对局时才创建，而现在停在登录/大厅。

### 5.11.5 意外收获：`FieldInfo` 布局（可直接复用）

那 44 个“误报”暴露了字段表的真实布局，stride **0x20**：

| 偏移 | 内容 |
|---|---|
| `+0x00` | `parent`——所属 `Il2CppClass*`（所以它会等于 klass，造成误匹配） |
| `+0x08` | `{ u32 offset; u32 token }`，token 高字节为 `0x04`（FieldDef 表） |
| `+0x10` | `name` → metadata 字符串 |
| `+0x18` | `type` → `Il2CppType*`（指向 libil2cpp 只读区，如 `0x4000342a9d30`） |

`ClientRecordSystem` 自己声明的 5 个字段实测：

```
0x08  gameBaseDataModule      0x10  gameSettingDataModule
0x18  config                  0x20  uploadFileList
0x28  enableDebugLogCmd
```

**这条能力很关键**：以后要读任何活对象的字段，只要能定位到它的 klass，就能拿到精确的字段偏移（不必再猜）。桩里的 `+0x68` 不属于这 5 个字段，来自基类，符合预期。

### 5.11.6 下一步

1. 进一局（或回放）后再跑 `find_class.py ClientRecordSystem --field 0x68 --name-of` —— 有实例时才能解析出实现类名。
2. 用 5.11.5 的 FieldInfo 布局，对 `TouchOperatorData / MoveOperatorData / SkillHitOperatorData` 等取字段偏移，再读活对象，与 `.ope` 字节做对照——这样就能在没有代码的情况下把位宽对出来。

---

## 5.12 离线解密的两个关键修正（2026-10-29 第十三轮）

### 5.12.1 文件偏移整体错了 0x50000

> 2026-10-30 复核修正：本节的 `VA−0x51000` 仅在所列历史代码锚点的部分页上验证，
> 不能推广到整份库；历史 metadata 与当前磁盘 metadata 不相同。第五页在另一映射下
> 可原样匹配，因此 5.12.2 的“换密钥”解释未获证实。见 5.36 与
> `python tools/replay_evidence_check.py --check`。

此前所有离线反汇编都用 `off = VA − 0x1000`（按 `.text` 段 `sh_addr − sh_offset` 推得）。用两份从内存抓到的**真·解密代码**做 XOR-0xE3 签名回搜，实测：

| live 块 | 标称 VA | 文件中的实际位置 | 差 |
|---|---|---|---|
| `code_blob.bin` | `0x5976000` | `0x5925000` | **0x51000** |
| `code_5977000.bin` | `0x5977000` | `0x5926000` | **0x51000** |

两处独立 64 字节签名一致，**`off = VA − 0x51000`**。`tools/offline_annot.py` 已加 `TEXT_DELTA = 0x51000`。

**后果**：5.11 之后基于错误偏移得出的离线结论（含"20 个 Read 里只有 3 个干净起点""`OperatorData` 21 个方法 3/20"）全部作废，需重跑。

### 5.12.2 XOR 0xE3 只在 16 KB 块内成立

用正确偏移逐字比对 20 KB 的 live 块：

| 区段 | 结果 |
|---|---|
| `0x5976000`–`0x5979fff`（4 页 = 16 KB） | **4096/4096 字全部 = 文件 ⊕ 0xE3**，明文 2 字，异常 0 |
| `0x597a000`–`0x597afff`（第 5 页） | **0 字**符合 ⊕0xE3；±0x40 内任意 4 字节平移仍为 0 |

差值的字节分布也不集中（`0xebc25b93`、`0xc8dc3c66`…各出现 2 次），说明第 5 页**不是**同一种单字节异或，而是换了一套变换（可能是按 16 KB 块递进的密钥或另一种算法）。

**结论**：`XOR 0xE3` 只在部分 16 KB 块内成立；"整段 .text 都是 XOR 0xE3"的旧判断过于乐观。要离线读代码，必须先把块级密钥的规律解出来。

### 5.12.3 当前状态

- 运行时路线：无安全账号，停用。
- 离线路线：偏移已修正，但受 5.12.2 限制，只能解出**确认是 XOR-0xE3 的 16 KB 块**。
- 已知可用：`0x5976000` 起的 16 KB（含 `OperatorData` 的 `Write/WriteInt/ReadInt/WriteShort` 等），可作为验证样本。

---

## 5.13 `.abc` 结构（2026-10-29 第十四轮，新主线）

`.abc` 与 `.ope` 并列，同一场对局各一份。它比 `.ope` 友好得多：**定长字段 + 长度前缀字符串**，不需要解密。

### 5.13.1 容器布局

```
[0x0000] len=8 "12.1.1.1"     客户端版本
[0x0009] len=8 "12.1.1.8"     资源版本
[0x0012] len=7 "4989537"      构建号（与 libil2cpp.so 同构建）
[0x001a] len=7 "5069040"
[0x0022] u32 = 0xBB
[0x0026] 10 字节散列 + 00 00
[0x0033] len=9 "佚名(*:" + 头像 URL
```

整份文件分两段，边界在 `0xC000` 附近：

| 区间 | 非零率 | 内容 |
|---|---|---|
| `0x0000–0xC000` | 17–32% | **十人名单表 + 每人 4 套出装方案**，字符串集中 |
| `0xC000–0x9b106` | ~80% | **帧记录流**，13,062 条 |
| 尾部 ~26 KB | — | 第二段记录流（头部布局不同）+ 常量串 |

### 5.13.2 十人名单（已验证，9/25 样本凑满 10 人）

玩家块头，fixed 结构：

```
<team:1|2> <team:1|2> <01> <slot:0..4> <00 00> <entity:u16 BE> <u32> <00 00 00> <nameLen:u8> <name>
```

实战样例（`20260925_105224`）：

| team | slot | entity | 昵称 |
|---|---|---|---|
| 1 | 0 | 1729 | 桑忆终尘启 |
| 1 | 1 | 1965 | 碗面加香菜 |
| 1 | 2 | 1514 | 布鲁BIUBIU |
| 1 | 3 | 1021 | 含泪吃兵线呢 |
| 1 | 4 | 338 | 双枪踏浪行 |
| 2 | 0 | 442 | 李不信有归途 |
| 2 | 1 | 1966 | 酒梦灵心醉 |
| 2 | 2 | 1547 | 备水一站. |
| 2 | 3 | 1558 | 佚名(*: |
| 2 | 4 | 1833 | Vetymoment |

每块约 4.0–5.4 KB（含 4 套出装方案 + 作者信息 + 英雄半身像 URL `DimBust`）。
产物：`_analysis/abc_roster.json`、`_analysis/abc_roster.csv`（9 场 × 10 人 = 90 行）。

### 5.13.3 帧记录流

每条记录：

```
seq:u8  pad:u8(=0)  L:u8  payload[L]  a:u8  00 00 00 00 00  b:u8
```

`seq` 从 0x22 起严格 +1（u8 回绕），共 **13,062 条**，平均 35 字节。按 20 fps 约 10.9 分钟，与一局时长吻合。

`payload` 是**标签流**，首字节是 token 计数：

| 标签 | 负载 | 含义 |
|---|---|---|
| `0x12` | 2 B | 标量（全局，47,689 个） |
| `0x13` | 1 B | 标量（10,343 个） |
| `0x14` | 3 B | 标量（23 个） |
| `0x01` | `hero:u16 BE` + `flag:u8` + `len:u8` + `len` B | **按英雄的消息 A** |
| `0x02` | `hero:u16 BE` + `0x80\|len` + `len` B | **按英雄的消息 B** |

语法在全部记录上精确吃满 **82.3%**（10,747/13,062），剩余 18% 落在更细的标签族（`0x17 / 0x2c / 0x33`…），尚未补齐。

**英雄 ID 与名单 100% 对应**：流里出现且仅出现的 10 个 hero 值 = 上述 10 名玩家的 entity，
其中本地玩家（442）出现 9,990 次，其余每人 45–302 次 —— 说明**本地玩家记录粒度远高于他人**。

### 5.13.4 已识别的英雄消息

| 英雄 | 子标签 | n | 形状 | 判断 |
|---|---|---|---|---|
| 442 | `0x2d` | 9,546 | `2d <u16 BE>`，150–350 | 朝向角度（0–360），77% 连续变化 |
| 全体 | `0x03` | 94–245 | `03 <u8>` | 状态位（0/1） |
| 442/1966 | `0x2c` | 333/85 | 17 B 定长 | **疑似坐标**，见 5.13.5 |
| 全体 | `0x02` | 143–435 | 1–7 B | 技能/状态事件（`02`、`01`、`02 ff`） |

### 5.13.5 未成立的两条判断（避免重复）

1. **`0x2c` 是坐标**：结构 `2c | count | 00 00 | i24 | i32 | i32 | u16 counter`，
   偏移 11 的 i32 恒定落在 0–65535，但均值 32,889 ≈ 65536/2、分布接近均匀 →
   **是跨字段误读**，不是坐标。偏移 7 的 i32 有 74/333 为负，也不像绝对坐标。
2. **流里没有经济**：对全部 (hero, tag, subtag) 共 134 条序列做逐字段单调性扫描，
   只命中 1 条（442 的 `0x2c` 第 14 字节，1→363，333 个样本）——**那是消息计数器**，
   不是经济。没有任何字段呈"从 0 增长到 1–2 万"的经济形态，也没有 KDA 三元组。

### 5.13.6 结论与含义

`.abc` 是**按英雄索引的帧状态/事件流**（朝向、状态位、技能事件），配合十人名单与出装。
它**不含每人的经济、KDA、输出**，这与"王者是帧同步游戏、客户端本地推演经济"一致：
录像只需记录输入与少量同步量，经济由客户端重算，因此无需入库。

**若要赛中经济，只有两条路**：
1. 录屏 + 逐帧 OCR 记分板（数据权威，工程量大）；
2. 用 `.ope`/`.abc` 的输入流在客户端复现模拟（等于自己实现一局游戏，不可行）。

### 5.13.7 与第 2 节的版本差异（重要，别混用偏移）

第 2 节基于 `20261028_135516.abc`（68 KB，头部第 4 串 = **`5230306`**）。本轮这批 25 个样本
几乎全是 **`5069040`** 变体，两者布局不同：

| 项 | `5230306`（第 2 节） | `5069040`（本节） |
|---|---|---|
| 玩家块步长 | 固定 1,517 B | **4,012–5,430 B**（随出装数量变化） |
| 英雄 ID | u32 **大端**，块内 `+771/+1415/+1445` | 块头 `u16 大端`，但**不是英雄 ID**（值域 338–1966） |
| 记录流头部 | `3B key + 29 0E 00 00 + len` | `seq:u8 + 00 + L:u8` |
| seq | payload 内 `u16 BE`，2→2,477 | 头部 `u8`，0x22→回绕，13,062 条 |

**不能用第 2 节的相对偏移读本节样本**（实测 `+1445` 处全是噪声）。
本节样本块头那个 u16 是**流内 actor id**，与 `0x01/0x02` 标签里的 hero 值一一对应，
但**没有**落到 `118 孙膑 / 196 百里守约` 这类真实英雄 ID 值域 —— 真实 heroId 在本变体里的位置仍未找到。

### 5.13.8 下一步的真正靶子：`CmdCompressPlayerInfo`

第 2 节记录过 metadata 里的字段名：

```
maxCampPosBitCnt / maxCampPosCnt / compressInfo_Move / compressInfo_CommonAtk
```

这些名字说明**坐标是以位域压缩存放的**（`Move` 与 `CommonAtk` 各一套）。所以：

- 坐标确实在 `.abc` 里，但**不是定宽整数**，按字节找必然失败（本节 5.13.5 的失败原因）；
- 要拿到走位/团战站位，必须解这套位域，而不是继续扫偏移；
- 经济/KDA 没有对应的字段名证据，倾向于**不在文件里**（帧同步本地推演）。

### 5.13.9 【定论】帧命令表：回放只存输入，不存任何战绩数字

修好 `kpl_i2cpp.fields_of` 的 `firstField` 偏移（原用 `v[10]`=eventStart，应为 **`v[8]`**）后，
从 metadata 取到两张决定性的表：

**`Assets.Scripts.Framework.FrameCommand`**（命令基类，6 字段）：

```
_sendCnt / _isCSSync / _playerID / _frameNum / _cmdId / _cmdType
```

**`CSProtocolWrapper.FRAME_CMD_INFO`**（帧命令联合体，**143 个成员**，即完整 opcode 表）：

| # | 命令 | # | 命令 |
|---|---|---|---|
| 0 | stCmdPlayerMove | 14 | **stCmdPlayerAddGoldCoinInBattle** |
| 1 | stCmdPlayerStopMove | 15 | stCmdSetSkillLevel |
| 2 | stCmdPlayerAttackPosition | 17 | stCmdPlayCommonAttackMode |
| 3 | stCmdPlayerAttackPlayer | 35 | stCmdPlayerOneStepBuyEquip |
| 4 | stCmdPlayerUseCurveTrackSkill | 41 | stCmdPlayerCancelSkill |
| 10 | stCmdPlayerLearnTalent | 45 | stCmdSuicideActor |
| 12 | stCmdPlayerAttackTargetMode | 108 | stCmdOperateSkillButton |
| 13 | stCmdSvrNtfChgFrameLater | 109 | stCmdRightJoyStickMove |
| 19 | stCmdSignalBtnPosition | 122 | stCmdLeftJostickDragStateChange |
| 20 | stCmdSignalMiniMapPosition | 140 | stCmdHeartbeat |

完整 143 条见 `_analysis/frame_cmd_table.json`。

**关键判断：这 143 条里没有任何一条携带伤害、击杀、死亡、经济或评分。**

- 唯一与金币相关的是 `stCmdPlayerAddGoldCoinInBattle`（第 14 条），从命名与位置看是**作弊/调试**命令，不是经济流；
- 也没有 `CmdDamage` / `CmdKill` / `CmdDeath` / `CmdScore` 一类命令；
- 压缩容器 `CmdCompressPlayerInfo { maxCampPosBitCnt, maxCampCnt, maxCampPosCnt, m_compressPlayerList }`
  只压 `compressInfo_Move` 与 `compressInfo_CommonAtk` —— 即**移动与普攻输入**。

**结论（可当作定论，不必再试）**：

> 王者荣耀是**帧同步（lockstep）**。回放文件记录的是**输入命令**，
> 经济、击杀、死亡、输出伤害、评分这些都由客户端在本地跑**同一套确定性模拟**算出来。
> 因此它们**不存在于 `.ope` / `.abc` 中**，不是"还没找到"，而是"信息本身没被写入"。
> 游戏内回放能显示记分板，是因为客户端重算，不是因为文件里存了。

**这条定论同时解释了此前所有失败**：5.6 的分段歧义、5.13.5 的单调性扫描无果、
坐标不是定宽整数 —— 一直在拿"结果"去文件里找，而文件里只有"原因"。

### 5.13.10 仍然可做的两件事

1. **位置（部分）**：`stCmdPlayerAttackPosition`（攻击目标位置）、`stCmdSetSkillIndicatorPosition`、
   `stCmdSignalMiniMapPosition` 这三条命令**自带坐标参数**。解出位域后能拿到
   "谁在什么时刻瞄准/标记了哪里" —— 对团战站位复盘仍然有价值，但**不是连续轨迹**。
2. **连续轨迹**：只有两种来源 —— 客户端跑模拟（不可行），或录屏 + 画面追踪。

### 5.13.11 【修正 5.13.9】击杀/死亡/助攻/胜负是**录制**的，不需要算

5.13.9 的结论"战绩数字都不在文件里"**过于绝对，此处修正**。metadata 里存在一整个
**`Assets.Scripts.BattleNotifyReplayTool`** 命名空间 —— 名字就是"战斗通知回放工具"：

| 类型 | 字段 | 含义 |
|---|---|---|
| `StepNotify` | `FrameDoType, FrameNotifyInfos, DelayFrame, StepNum, IsOpen, MyCampHeroIds, MyCampHeroObjIds, EnemyCampHeroIds, EnemyCampHeroObjIds` | **一步** = 动作 + 通知数组 + 双方阵容映射 |
| `FrameNotifyInfo` | `isKillNotify, m_attackerObjID, m_victimObjID, m_assist01..05, m_assistCount, m_killNotifyType, m_heroMultiKillType, m_heroContiKillType, sourceId, primaryTargetId, majorValue, majorValueRatioFactor, killerId, highlightResId, skillId, eventStartTime, eventEndTime, notifySeq` | **击杀事件全字段** |
| `stHighlightNotifyParams` | `sourceId, primaryTargetId, majorValue, majorValueRatioFactor, majorValueDefinition, killerId, highlightResId, skillId, eventStartTime, eventEndTime, notifySeq` | **高光数值**（伤害/治疗/承伤） |
| `SvrNtfGameOverCommand` | `m_bWinCamp` | **胜负** |
| `FrameDoType` | 37 个**中文**枚举：`什么都不做 / 释放普攻 / 释放一技能 / 释放二技能 / 释放额外技能 / 释放大招 / 释放召唤师技能 / 模拟一技能按下…模拟一技能滑动 / 学习1~3技能 / 杀死自己 / 释放回城 / 释放回复技能 / 模拟十一技能…` | **每一步的动作类型** |
| `BattleNotifyReplay` | `START_STEP, curExcuteFrame, _recordFrame, passedFrame, m_repeatNum…`（41 个方法） | 通知流的回放驱动 |

**因此正确结论应为**：

> 回放**记录输入**（`FrameDoType` 动作流 + 移动/普攻位域压缩），
> 同时**额外录制了一层战斗通知**（`StepNotify`），其中包括**击杀事件（击杀者/被击杀者/最多 5 个助攻）
> 与高光数值**。
> 所以击杀、死亡、助攻、胜负、动作时序**都不需要算，只需要解**。
> 真正需要"算"的只剩**经济**与**全程血量/持续伤害** —— 那要重跑确定性战斗模拟。

### 5.13.12 为什么"算经济"不可行（回答"为什么我们不能算"）

经济不是某个字段，而是模拟的**输出**：

```
金币 = f(自然增长速率, 补刀数 × 兵种金币, 击杀/助攻赏金 × 连杀系数, 推塔, 野怪, 装备被动)
```

要算它需要：伤害公式全链（攻击→护甲/魔抗→穿透→减伤→暴击→护盾→免伤→真伤）、
120+ 英雄 × 3~4 技能 + 被动的命中与多段逻辑、几十件装备被动、58 类控制效果、
小兵/野怪刷新与金币规则，以及确定性前提（定点数、帧序、RNG 种子）。
这些全部在 `libGameCore.so`（41 MB）与 ResData 配置表里 —— **等于把游戏重写一遍**。

这也是为什么游戏内回放能显示记分板：客户端本来就在跑这套模拟，它不需要文件告诉它。

**唯一的折中**：`stCmdPlayerOneStepBuyEquip` / `stCmdPlayerChangeUsedRecommendEquipGroup`
给出**出装时序**，把每件装备价格累加即是**经济花费下限**（不含未消费金币）。
这不需要模拟，但只是下界，不能当"经济曲线"用。

### 5.14 【权威清单】经济来源的完整字段表 —— 但不在回放里

`CSProtocolWrapper.COMDT_GAME_30SEC_INFO`（**107 字段**）是**每 30 秒一档的玩家统计快照**，
把每一份金币来源都单独计数了。这是这套二进制里关于"经济"最权威的定义：

| 类别 | 字段 |
|---|---|
| **总额** | `dwCoinCnt`（累计金币）、`dwCoinIntervalCnt`（本 30 秒增量） |
| **补刀** | `dwSoliderKillCoin` / `dwSoliderKillIntervalCoin` / `dwKillSoldierCnt` / `dwSoliderKillByHit` / `SoliderKillCoinByRouteID[]` / `SoliderKillCountByRouteID[]`（按分路） |
| **击杀** | `dwHeroKillCoin` / `dwHeroKillIntervalCoin` / `dwKillHeroCopyCoin` |
| **推塔** | `dwDestroyOrganCoin` / `dwDestroyOrganIntervalCoin` / `dwDestroyTowerCnt` / `dwDestroyOuterTowerCnt` / `dwDestroyBaseTowerCnt` |
| **野怪** | `dwMonsterKillCoin` / `dwMonsterKillIntervalCoin` / `dwKillMonsterCnt` / `dwKillEnemyMonsterCnt` / `dwKiLlOurMonsterCoin` / `dwKiLlEnemyMonsterCoin` |
| **龙/河道** | `dwLittleDragonCoin` / `dwOldDragonCoin` / `dwDragonCoin` / `dwDarkDragonCoin` / `dwBaronCoin` / `dwDuikanRiverCatCoin` / `dwMidRiverCatCoin` / `dwFayuRiverCatCoin` / `dwKillDragonCnt` / `dwKillBigDragonCnt` |
| **系统/自然** | `dwSystemAddCoin` / `dwSystemAddIntervalCoin` |
| **装备被动** | `dwEquipAssistEnCiCoin` / `dwEquipAssistYouJiCoin` / `dwEquipJungleShangJinCoin` / `dwEquipJungleYouJiCoin` / `dwAidEquipCoin` / `dwPassiveTaiYiZhenRenCoin` / `dwTeamBehaviorCoin` / `wSelfBehaviorCoin` |
| **KDA** | `dwKillCnt` / `dwDeadCnt` / `dwAssistCnt` |
| **伤害** | `dwHurtToHeroAll` / `dwTakenFromHeroAll`（对英雄 输出/承伤）、`dwHurtToOrganAll`（对建筑）、`dwHurtToEnemy` / `dwTakenFromEnemy`、`dwHurtHeroCnt` / `dwBeHurtHeroCnt` |
| **位置** | `iXPos` / `iZPos`、`astKillHeroPos[]`（击杀发生位置）、`astSubdivide30SPos[]`（30 秒内细分位置） |
| **装备** | `EquipID[]` |
| **技能** | `UseHeroSkillCount[]` / `HitHeroSkillCount[]`（可算命中率） |
| **其他** | `dwRedBuffCnt` / `dwBlueBuffCnt` / `dwYellowBuffCnt` / `dwSoulNum` / `dwHighLight` / `dwFiveCampTeamScore` |

**验证结论：这份结构不在 `.ope` / `.abc` 里。**

| 检验 | 结果 |
|---|---|
| 前 10 个 `*_length` 的 `[N,N,6]` 定宽签名（u32/u16） | **0 命中** |
| protobuf 变长形式 `03 03 06` / `04 04 06` / `05 05 06` | **0 命中**（`02 02 06` 仅 6 处、分散） |
| 10 人金币数组（u32，8000–26000） | 仅 2 处，非结构 |
| 10 人金币数组（u16） | 命中饱和（小字节遍地），无意义 |

所以它是**客户端模拟完、结算时上报给服务器**的协议结构（`COM` = 通信协议前缀），
不是回放文件的内容。**回放里始终只有输入。**

### 5.14.1 一个必须澄清的误判：`BattleNotifyReplayTool` 是编辑器测试工具

5.13.11 曾据此认为"击杀事件是录制的"，**该判断应下调为"很可能不成立"**。证据：

- 同命名空间内有 `XMLWrite { SkillTestDataName, CompareName }` + `WriteXML/ReadXML/GetCachePath/GetComparePath/IsExistFile`
- `BattleNotifyReplay` 的字段是 `_testTime1 / _testTime2 / m_repeatNum / _curRepeatNum / switchComputerBegin`
- `FrameDoType` 是中文枚举（`释放一技能 / 模拟一技能按下 / 学习1技能 …`）

这是策划/QA 做**技能回归测试**用的录制比对工具（录一遍通知、跑两遍、比对 XML），
不是运行时回放格式。**不要拿它当"回放里存了击杀事件"的证据。**

### 5.16 M3 战斗初始化命令还原（2026-10-29 第十五轮）

目标：headless 宿主（5.15.4）启动一局所需的"战斗引导命令序列"。
方法：metadata 静态考古（GameReplayModule/SGW/GameBuilder/CSProtocol 类型表）+ `.abc` 头部对拍。
本轮不涉及任何运行时操作；runtime_dump 仅用于验证（.data.rel.ro 运行时才填，dump 时点太早，类型解析路线受限后放弃）。

#### 5.16.1 C# ↔ GameCore 边界（架构定论）

`SGamePInvoke` 全部 **32 个方法**（metadata type: SGamePInvoke）逐一核对，全是 FIFO/缓冲/内存操作：
`PushCsBuffer/CommitCsBuffer/ResetCsBuffer`、`SFPushCsImmediatePackBuffer`、`PushCppImmediatePackBuffer/PopFifoCppPackBuffer`、`FlushGameCoreFifo(Force)`、`ProcessGameCoreNotify/DelayNotify`、`DoBattleStart`、`CopyMemory/MoveMemory/SGameSleep`、`CompressData/DecompressData`、`WriteString/ReadString/CalcStringMemSize/AlignSize` 等。

**没有任何"创建一局/开始战斗"C 导出**（对照 libGameCore.so 的 123 个 C 导出，5.15.2）。

> **定论：初始化也是数据，不是调用。** C# 宿主把开局配置序列化后经同一套 CS 命令缓冲推给
> GameCore；`SGW.StartLevel/PureReplayStart` 是 C# 侧的组装函数，不是 P/Invoke。

#### 5.16.2 C#→GameCore 封装层 SGW（580 方法）启动接口（参数名来自 metadata，权威）

| 方法 | 签名 | 说明 |
|---|---|---|
| `GameCoreInit()` | — | 初始化 |
| `StartLevel` | `(info, gameModeType, isMultiGame, deskPool, poolSize, extraInfo)` | 开一局 |
| `PureReplayStart` | `(info, gameModeType, abxType, isMultiGame, deskPool, poolSize, extraInfo)` | 纯回放启动 |
| `SetupClient` / `SetupClientImme` | `(isWatch, isRelayCast, watchCamp, hostPlayerInfo)` | 客户端设置 |
| `BeginLoad` / `AsyncBeginLoad` | `(param)` / `(param, immediateBuffer)` | 加载 |
| `StartHostReplay` | `(abhPath)` | 回放启动（abh = AbsHeader，即 `GameReplayModule.replayAbsHeader`） |
| `SetAllKeyDatabin` | `(info)` | 配置表加载（M2 配套） |
| `GameCoreUpdate` | `(1)` | 每帧驱动 |
| `PushSvrNtfGameOverCmd` | `(frameNum, srcPlayerID, winCmp)` | 结束（`winCmp` 即 5.13.11 `SvrNtfGameOverCommand.m_bWinCamp`） |
| `NtfSynchrConfigured/Started` | `(paramPtr, paramFlat, paramMask)` | native→C# 同步握手 |

`Push*Cmd` 系列（60+）与 `FRAME_CMD_INFO` 143 条一一对应，是帧输入命令的封装；
**开局配置不在其中**，见 5.16.4。

#### 5.16.3 开局编排器：GameBuilder 家族（生命周期即初始化序列骨架）

```
GameBuilderHelper.StartGame(3) / StartSingleGame(2) / StartMultiGame(2)
  └─ GameBuilderClientBase{gameMode, LevelContex, loadMessage, deskPool}
       Initialize(3) → BuildPlayers(0) → AddHero(1) → BuildCSharpPlayerHeroData(2)
       → NtfCoreSetupClient(0)          ← SGW.SetupClient
       → NtfCoreStartGame(0)            ← SGW.StartLevel
       → PreBeginPlay(0) → NtfAllBuildComplete(0) → StartFight(0)
       → OnLoadingProgress(1) → PostBeginPlay(0)
模式特化：MultiGameBuilder / SingleGameBuilder / UGCGameBuilder（各有 NtfCoreBeginSoloGame 等）
```

`info` 的真身是 **`CLevelContext`**（type 42374，448 方法 / **285 字段**，全清单见
`_analysis/clevel_context_fields.txt`）。关键子集：

| 字段 | 含义 |
|---|---|
| `m_pvpLevelCommonInfo` | 指向 `ResData.ResDT_LevelCommonInfo`（databin 关卡配置，206 字段） |
| `m_randomSeed` | **帧同步随机种子** |
| `m_gameType / m_subGameType / m_mapType / m_subMapType / m_mapID / m_mapName` | 模式与地图 |
| `m_isMultiPlayerGame / m_pvpPlayerNum / campCount / campMaxPlayerNum` | 人数/阵营 |
| `dwDeskId / dwDeskSeq` | 桌位 ID（`.abc` 头 `4_-1505729760...` 串即其文本形态） |
| `m_timeDuration / m_loseCondition / m_baseReviveTime / m_reviveTimeMax / m_originalGoldCoinInBattle` | 规则参数 |
| `MapRandomNumber1/2/3 / gamePlayRandNum` | 附加随机数 |
| `m_selfAILevels / m_enemyAILevels / m_aiLevel` | AI 强度 |

`deskPool` 的协议元素 = **`CSProtocolWrapper.CSDT_DESK_SVR2GAMECORE_ITEM`**，见下。

#### 5.16.4 【M3 主成果】开局配置 = Svr2GameCore KV 表（.abc 头部已还原）

metadata 链条：`CSProtocolWrapper.CSDT_DESK_SVR2GAMECORE_CONFIG`
`{ astGameCoreCfgItems_length, dwArrayNum, astGameCoreCfgItems_bytes }`，
行结构 `ResData.ResSvr2GameCoreInfo { wConfType, wConfValue }`，
源表经 `svr2GamecoreCfgDatabin`（`FindByKey/Count/GetByIndex`）读 databin；
GameCore 侧消费点为行为图节点 `GetResSvr2GameCoreInfoNode`（libGameCore.so 字符串区 0x11e9c35）。

**`.abc` 头部实测（5069040 变体，25/25 样本成立）**：

```text
0x018D: u16 LE count                      （本样本 53）
0x018F: count × (u8 confType, u16 BE confValue, u8 pad=0)   4 字节/条
```

- 定位签名：`01 00 32 00 02 00 01 00 03 00 19 00`（confType=1→50 起始）；
- key 值域 1..105，大体递增、保留 databin 表序（0x17 插在 0x12 与 0x13 之间）；
- **"序列长度未知"的正解：长度 = dwArrayNum，随模式变化**——25 样本实测
  **53 条 ×20、46 条 ×4、42 条 ×1**；
- **25 样本差分：51 个 confType 值恒定**（游戏规则常量），**仅 94={70,100}、95={8,12} 随对局变化**。

主样本（20260925_105224，排位）全部 53 条：

```text
1→50 2→1 3→25 4→1 5→1 6→5 7→300 8→127 9→1700 10→1 12→0 13→1 14→50 15→0
16→1 17→5000 18→0 23→1 19→300 20→5 63→500 64→0 66→0 67→1 68→8000 69→2800
70→2000 71→3000 72→4000 73→1000 74→800 75→600 76→400 77→13000 79→999 80→300
81→5 82→1 83→0 84→1 85→462 88→25 89→1 90→1 91→2 92→2000 94→70 95→8 96→1
97→100 98→0 99→500
```

可对号的候选（与 CLevelContext 字段名对照，待 M2 读表确认）：
73/74/75/76 = 1000/800/600/400（**赏金/经济衰减链**）；68=8000（时长或初始金币）；
77=13000（**经济上限**）；9=1700/7=300（波次/保护类时长）；94/95 = 随对局变化的模式参数。

#### 5.16.5 `.abc` 头部布局（5069040 变体，本轮补充）

```text
0x0000  4×(len+str) 版本/构建（12.1.1.1 / 12.1.1.8 / 4989537 / 5069040）
0x0026  10 字节散列
0x0034  本地玩家名 + 头像 URL（len 前缀串）
0x0146  语音服务器 "udp://cn.voice.gcloudcs.com:10001"（len=0x22）
0x016D  "4_-1505729760493317903036310"  ← gameType 前缀 + dwDeskId 串（=文件名 3 段拼接）
0x018D  ★ Svr2GameCore KV 配置（5.16.4），53×4+2 字节
0x0263  其余初始化标量（若干 u32：对局时间、随机数等，待逐字段对拍）
0x041E  玩家块 1..10（5.13.2）
块尾    4 套出装方案名（"时茧法爆流"等）+ 对局 GUID 'D341CC...' + 头像 URL
0xBFE8  帧记录流（5.13.3，seq 0x22 起）
```

#### 5.16.6 与 5.15.5 里程碑的对应

- M3"战斗引导命令序列还原"**主结构已解**：初始化序列 = GameBuilder 生命周期（5.16.3）
  + Svr2GameCore KV 表（5.16.4）+ CLevelContext 规则字段（5.16.3 表）；
- 仍开放的子项：(a) confType 全表语义需 M2 databin 读表对拍；(b) 0x0263..0x41E 的其余
  标量字段；(c) deskPool 十人条目的二进制形态（玩家块内应含其展开）；(d) TDR 编码细节归 M4。

#### 5.16.7 【M3 补全】KV 表 = databin `svr2GamecoreCfg`，25 样本逐条对拍（2026-10-30）

用 M2 导出的 databin 表 `Databin/Public/Global/svr2GamecoreCfg.bytes`
（index 83，53 行 × 4 B）对 5.16.4 的 `.abc` KV 做验证：

- 表行就是 `{u16 wConfType, u16 wConfValue}`。**53 行全部是 KV**，
  行序即 databin 表序；`.abc` 头部同构，只是编码成
  `{u8 confType, u16 BE value, u8 pad}`。
- **25/25 样本、所有重叠 key 的值与表默认值完全一致**：
  - 42/46/53 条三种集合由模式决定；42/46 条样本整体缺少 94/95/96/97/98/99
    等尾部 key；
  - 唯一值差异是 key **94**（表 70；19 样本 70，1 样本 100）和
    key **95**（表 8；19 样本 8，1 样本 12）——即 5.16.4 的“随对局变化”；
  - 样本含 key **23=1** 和 **103=500**，本地 databin 表**没有这两行**；
  - 表含 key **791=1** 和 **105=500**，25 个样本**都不发送**。
  → 本地 databin 与服务器当前 KV 表版本不同；`.abc` 保存的是服务器表的
  行序/子集，而不是本地默认值的排序结果。
- key 域到 105（表内还有 791），而 C# 侧 `ResData.RES_GAMECORE_CONF_TYPE`
  只有 73 个具名成员且值域是 0,2,4…（字节），与 `wConfType` 的 1..105
  **不是同一编号域**；confType 的逐项语义仍未解（见 5.16.6 (a)）。
  候选语义只能按值猜：1→50（选人延迟）、7→300（帧延长上限）、
  9→1700（位置同步间隔）、68→8000、73..76→1000/800/600/400 等。
- 副作用：`_analysis/device/dtab_blocks/83_svr2GamecoreCfg.bytes.bin`
  可作为离线开局 KV 的**默认值模板**；`.abc` 覆盖 94/95 即可复现该局配置。

#### 5.16.8 【M3 补全】KV 之后的初始化标量块（5069040/5v5 变体，2026-10-30）

在 KV 块之后、玩家块之前还有一段固定初始化数据。2026-09～10 的 9 个标准
5v5 样本对齐后：

- **起点 = KV 块结束 + 8**（中间 8 字节固定为 `{u32 0, u32 modeWord}`）。
- 到第一个玩家块为止 **443 字节**（110 个 **大端 u32** + 3 字节尾 `00 00 0a`；
  个别样本 441 字节，差异来自 KV 对齐，不是内容不同）。
- **整段是网络字节序（BE）**，与 KV 的 `u16 BE` 一致；按 LE 读会得到
  0x2c010000 一类“乱值”。
- 110 个值里绝大多数是常量（前 40 个：
  `0, modeWord, 300, 1000, 7, 5, 2, 10, 5, 1, 66, 1000, 32, 32, 2, 15,
  0, 0, 15, 15, 4, 300, 15, 15, 100, 0, 200, 8, 300, 0, 120, 200, 300,
  120, 0, …`；第 43/55 个是 65536，第 58 个 2144，等等）。
- **语义锚点：index 67（标量块 +0x10C）= 服务器 Unix 时间秒**。
  9 个样本中 8 个与文件名最后一段 10 位数字**完全相等**，主样本
  `20260925_105224` 的文件名是 `…_1790303631`、字段是 `1790303632`（+1 s，
  抓包晚于命名）。→ 这一段确实是 CLevelContext 一类初始化数据的序列化，
  不是随机数。
- **唯一变化的字**是 index 1（`modeWord`）：9 个样本中 6 个 =
  `89,497,376 (0x05559F20)`、2 个 = `88,448,288 (0x05459D20)`，与时间/CRC
  都不相关（CRC32/MD5 实测对不上），疑似**地图/房间类型**或服务器下发的
  配置版本号；待与 `Level.bytes`（35 行×656 B）/desk 字段对拍。
- **变体边界**：4 个样本（20261016_194242、20261016_195137、20261027_231329、
  20261027_232156）的头部版本是 **12.1.1.18 / 12.1.1.23，构建 5169333 / 5230306**，
  不是 5069040/12.1.1.8 布局：KV 后没有 `300,1000,7` 模式，index 1=6176、
  index 67=0。→ 这是**另一构建变体**的初始化头，不能拿本节偏移套。
  另有 20261017_015659（仍是 5069040）的“标量区”长 4,189 字节、只有 8 个玩家块，
  属同一构建下的特殊模式/内容，需单独处理。
- 模板已落盘 `_analysis/device/abc_init_scalars_5v5.json`
  （source、kv_end、player_block0、443 字节、110 个 BE u32、尾 3 字节）。
  与 5.16.7 的 KV 模板合并，即可**逐字节重建标准 5v5 的 .abc 初始化头**。

---

### 5.17 M2 配置表：libQtsVFS 宿主内实测（2026-10-29）

目标：M1 已在自建宿主内跑通 `ModuleInit`，本节验证能否让**宿主直接驱动 libQtsVFS**，
再把 `QTSRegisterSystem` 之后的 databin 读取接通。结论：**库可加载、系统可创建、包可描述，
但空间（space）打开/内部包挂载仍缺一份有效配置**；databin 尚未读出。

#### 5.17.1 GameCore 侧 QTS 接口（metadata 权威）

`QTSFileNativeAPI` 的 P/Invoke 参数名（`global-metadata.dat`）：

```text
QTSOpenFile(filePath, length)              → handle
QTSReadFile(handle, buffer, size)
QTSFileExists(filePath, length)
QTSGetFileLength(filePath, length)
QTSRegisterSystem(sysName, sysNameLength, cachePath, cachePathLength)
QTSUnregisterSystem(sysName, sysNameLength)
```

`ResData.DatabinManager.SGameSetEnableDatabinCrcFromFile(enable)`；
`ResData.UGCCustomDataTableMgr.GameDataWrapper_GetTable(table, name)` 等。

GameCore 的 QTS 层**自己 dlopen libQtsVFS.so**（`QtsFileSystemPlugin` 初始化函数 0x286f088）：
`dlopen("libQtsVFS.so", 2)` 后 `dlsym` 了
`VFS_OpenFileByHash / VFS_Read / VFS_Seek / VFS_Tell / VFS_CloseFile / VFS_IsExistByHash /
VFS_GetFileLengthByHash / VFS_CalcHashCode64 / VFS_OpenFile / VFS_IsExist / VFS_GetFileLength /
VFS_IsDirectory / VFS_HasSystem`，并把函数指针存 0x52c3298 起的全局表。
`QtsFileSystem::Open`（0x286f3bc）先按 hash 路径查 VFS，失败则 `fopen(path,"rb")` 回退。
QTS 相对路径由“全局前缀（6 字节，0x54191f0）+ 系统名 + 路径”拼成；前缀在 BSS，
未找到写入点（推测由宿主注册时设置）。GameCore 内只有 UGC 表的字面路径，
核心表路径（`Databin/data_xls/Hero.bytes` 等）由 C#/databin 元数据提供。

#### 5.17.2 libQtsVFS 裸宿主实测（MuMu，ARM64 进程）

工具在 `_analysis/_host/`：`qts_probe.c`、`qts_mount2.c`、`qts_desc.c`、`qts_enum.c`、
`qts_cfg.c`、`qts_cfg2.c`、`qts_mkcfg.c`（NDK r28b，`aarch64-linux-android28-clang`）。

| 调用 | 结果 |
| --- | --- |
| `VFS_Initialize_Scripted()` | 1（成功） |
| `VFS_CreateSystem(name, prime, override, dataDir)` | 1，`HasSystem(name)=1`；在 dataDir 下建 `<name>/Globalindex` + `Watchdog/*.db` |
| `VFS_Scan(name, fast, maxBroken)` | 1 |
| `VFS_IsExist/OpenFile/EnumerateDirectory` | **0 / 0 / -1**，`VFS_GetLastError()=25 = QTSEC_COMMON_GET_SYS_FAILED` |
| `VFS_CreatePackageDescription(name, pkg, internal)` | 返回 **int 句柄**（首个=0） |
| `VFS_MountPackage(handle, usage, mode)` | 0（失败）；错误码见下 |

**关键错误码**（`QTSErrorCode` 385 项，来自 metadata，值按声明顺序）：

```text
4   QTSEC_COMMON_VERSION_DATA_ERROR     33 QTSEC_COMMON_OPENDB_FAILED
25  QTSEC_COMMON_GET_SYS_FAILED         40 QTSEC_BUILD_LOAD_CONFIG_FAILED
142 QTSEC_MOUNT_DONOT_HAVE_PRIME        144 QTSEC_MOUNT_LOAD_PRIME_FAILED
146 QTSEC_MOUNT_LOAD_OVERRIDE_FAILED    151 QTSEC_MOUNT_OVERRIDE_SHOULD_BE_FULL
306 QTSEC_GLOBALINDEX_MISSING           319 QTSEC_*（GenGlobalIndex 失败）
324 QTSEC_MOUNT_OVERRIDE_BEFORE_INTERNAL
```

**挂载语义**：`VFS_OpenFile` 等无 sysName 的 API 使用一个“当前 space”，只有
`VFS_OpenQtsVFSSpace[Ex]` 能设置；仅 `CreateSystem` 不够。`VFS_MountPackage` 的原生
`usage` 不是 C# 枚举的 0/1：传 0/1 分别报 142/324（0 被视为 prime、1 被视为 override），
说明内部 `QtsPackageUsage` 至少是 1-based 或另有位标志；C# 侧 `PrimePackage=0 /
OverridePackage=1` 不能直接照搬。

#### 5.17.3 `SQTSVFS_SysConfig` 结构（setter 反汇编，权威）

```text
+0x000  all_in_one (u8)
+0x004  compatibility_version (u32)
+0x008  data_version (u32)
+0x010  build_id (u64)
+0x01c  packages_count (u32)
+0x020  app_buildin_packages_count (u32)
+0x024  system_name[128]
+0x0a4  internal_package_name[128]
+0x1a4  package_names[20480][32]        （首元素即 0x1a4）
+0x2801a8 package_hashes[20480] (u64)
+0x2a81a8 app_buildin_package_names[20480][32]
```

`CSharp_new_SQTSVFS_SysConfig()` 可直接分配；`_system_name__set(ptr, const char*)` 是
`strncpy(header+0x24, src, 0x7f)`，不是 std::string。

`VFS_SaveConfigFile(path, header)` 成功写出 **JSON**（455 B 样本，`cfg/saved_cfg.txt`）：

```json
{"compatibility_version":201392384,"system_name":"builtin","internal_package_name":"9",
 "data_version":"12.1.1.26","build_id":5069040,"all_in_one":true,"upgraded_from_v1":0,
 "packages_count":1,"app_buildin_packages_count":0,"extra_export_data_package":"",
 "package_names":["9"],"app_buildin_package_names":[],"package_hashes":{"9":<u64>}}
```

`data_version` 是**点分字符串**，`compatibility_version` 是 **u32 打包**
（12.1.1.0 = 0x0C010100 = 201392384；`VFS_VersionToString` 按 major>>24 / minor>>16 /
patch>>8 / build&0xff 拆）。但 `VFS_LoadConfigFile` 读同一份文件返回 0 且
`VFS_GetLastError()=4 (VERSION_DATA_ERROR)`，且不改写 header —— **Save/Load 不对称**，
原因未定（可能 Load 是 QTS 工具/二进制格式，运行时并不走它）。

#### 5.17.4 配置表实际所在：APK 的 builtin prime 包

`base.apk` 内 `assets/bin/Data/Package/builtin/<pkg>/<pkg>.db` 共 **29 个包、1.47 GB**：

```text
pkg 9   = 9.db 10.9 MB + 9_0.db 877.5 MB   （最大，疑似主体/核心数据）
pkg 0   = 0.db 6.0 MB + 0_0.db 234.5 MB
pkg 114 = 114.db 131 KB + 114_0.db 327 KB  （最小，适合做挂载试验）
```

设备侧 `QtsVFSCache/packages/` 是**下载覆盖层**（508 个目录，13 GB）；
`packages/builtin/{Globalindex/GlobalIndexPrime.data 9.4 MB, Merge/}` 是运行时生成的全局索引。
`packages/ResourceRecords.json`（26 KB）列出包 id / hash / 版本；
`packages/<id>/record.bytes`（39 B）格式已解：

```text
u32 0x27 | u16 9 | "12.1.1.26" | u8 1 | u32 0 | u16 9 | "12.1.1.26" | u64 hash
```

包 9 的 hash = `0xf5f1616bd02e0f8b`；包 0 = `0x56e3c186426fae0f`。
`files/databin.ver`（13,464 B）不是明文清单，熵高，未解。

已用 `unzip -o base.apk 'assets/bin/Data/Package/builtin/*'` 在设备
`/data/local/tmp/gc/apkfull/` 解出 1.3 GB 完整 prime 树，并把
`Globalindex/GlobalIndexPrime.data` 复制进 `builtin/`；`/data/local/tmp/gc/prime/`
下另有包 114 的最小 prime 树。这些只用于宿主试验，不在仓库内。

#### 5.17.5 卡点与下一步

**卡点**：`VFS_OpenQtsVFSSpace[Ex]` 需要一份与运行时一致的 space 配置/头；用
`CreateSystem` 创建的空系统不会被 IsExist/OpenFile 选中（错误 25）；自己拼的 header
和 Save 出的 JSON 都不能让 OpenEx 越过错误 40。内部包/prime 包的挂载顺序也依赖这个
space（142/144/146/324）。

**下一步（按成本排序）**：
1. 从 libil2cpp 的 `CQtsvfsFileSystemManager.Init` / `CQtsvfsResourceSystem.Init` 反汇编
   出它调用 `VFS_OpenQtsVFSSpace[Ex]` 的实参（space path、openMode、header 来源），
   这是唯一能把“配置从哪来”钉死的路径；C# 侧类型 `CQtsvfsFileSystemManager` 0 方法，
   实际在 `Scripts.Plugins.Resource.CQtsvfsPackageManager` 与 `CQtsvfsResourceSystem`。
2. 或者绕过 space：按 5.14 的 QTSF 节点记录 + LZ4 页格式写离线提取器，用
   `GlobalIndexPrime.data` 把 `Databin/**.bytes` 的路径 hash 映射到包 9/0 的页；
   提取到文件系统后让 GameCore 的 `fopen` 回退直接读（`chdir` 到 `RawAssets` 根）。
3. 拿到可读 databin 后，再回到 M2 的 `QTSRegisterSystem("builtin", …)` +
   `GameDataWrapper_GetTable` / `DT_Count` 枚举；M3/M4/M5 不变。

工具与产物：`_analysis/_host/qts_*.c`、`_analysis/device/{packages_Resource.bytes,
databinver, group0_record.bytes}`；设备侧 `/data/local/tmp/gc/{apkfull,prime,cfg}`。

#### 5.17.6 配置格式已破解（同轮续，pace 更新）

5.17.5 的“配置来源未知”已解决。`VFS_LoadConfigFile` 是 rapidjson 文本解析，
**不是二进制**；`compatibility_version` 是 QTS **配置格式版本**，不是游戏版本：

- `compatibility_version >= 5` 才被接受；`5` 走 `LoadQtsSysConfig_Ver2`（要求
  单数 `package_name` 成员），`6` 走 `LoadQtsSysConfig_Ver6`（接受
  `package_names`/`package_hashes`）。传 201392384（12.1.1.0 打包）会报
  `Qts compatibility version illegal`，传 6 成功。
- `data_version` 是点分字符串 `"12.1.1.26"`；`build_id` 是整数 5069040。
- 通过 `VFS_SetPushErrorLogsNum(100)` + `VFS_GetReportEvent/GetMsg` 能拿到
  **带条件表达式与源码行号**的错误事件，这是后续排查的关键工具（qts_diag.c）。

可用的最小 JSON（`_host` 实测 Load=1, err=0）：

```json
{
  "compatibility_version": 6,
  "system_name": "builtin",
  "internal_package_name": "9",
  "data_version": "12.1.1.26",
  "build_id": 5069040,
  "all_in_one": true,
  "upgraded_from_v1": 0,
  "packages_count": 1,
  "app_buildin_packages_count": 0,
  "extra_export_data_package": "",
  "package_names": ["9"],
  "app_buildin_package_names": [],
  "package_hashes": { "9": 17722053124361686923 }
}
```

`VFS_OpenQtsVFSSpaceEx(sysName, cfgPath, primeRoot, overrideRoot, openMode, pHeader, useAssetPath)`
的 `pHeader` 是**输出**：传 NULL 时函数自己 `calloc(0x5281a8)`，然后始终用
`cfgPath` 调 `VFS_LoadConfigFile` 填充。config 路径必须是文件，不能是目录。

打开 space 后，挂载路径已推进到：

1. `internal_package_name="builtin"`：它会找 `<overrideRoot>/builtin/builtin.db`，
   该文件必须是 **QTSF 包**（头字符串 `QTSF_PACKAGE`），不是 QtskDB；随后才开
   node storage 的 QtskDB 表 `builtin`。
2. `internal_package_name="9"`：`VFS_GenerateGlobalIndexWholeSystem(primeRoot, "9")`
   返回 **1**，并把全局索引写进 `9/9.db`（10,928,128 → 11,698,176 字节）；
   之后失败在 `qts-remaindir-node-index` 节点缺失（错误 6）。
3. `GlobalIndexPrime.data` 的魔数是 **`INGQ`**（+0x00，版本 u32=2），不是 QTSF；
   9.4 MB 的这份是设备上 `packages/builtin/Globalindex` 的实际内容。
4. 错误 152 的枚举名是 `QTSEC_MOUNT_PRIME_NOT_PREBUILD`（日志文案是
   “prime do not have GlobalIndex”），说明 prime 包还缺 **prebuild** 标记/节点。

**当前唯一卡点**：prime/internal 包的 QTSF 包内要有 `qts-remaindir-node-index`
节点（或等价 prebuild 标记）。下一步二选一：
(a) 用 `QtsfTool`/`VFS_*` 的建包 API 往 9.db 注入该节点；
(b) 从 `QtsfPackage::LoadRemainDirHashesFromPackage`（0x252xxx 附近）反推节点
格式，手工构造。之后 `VFS_IsExist/OpenFile` 就能读到 `Databin/*.bytes`，
再接 GameCore 的 `QTSRegisterSystem` + `GameDataWrapper_GetTable`。

副作用清理：调试时在游戏缓存 `QtsVFSCache/packages/builtin/` 下生成过
`PackageStats/`、`Watchdog/`，已删除；原 `Globalindex/`、`Merge/` 未改动。

#### 5.17.7 space 已能打开；当前卡在 remaindir 节点（同轮再续）

配置格式解决后，`VFS_OpenQtsVFSSpaceEx` 已能返回 **1 / err=0**：

- 最小可用配置：`internal_package_name="builtin"`、`packages_count=0`、空的
  `package_names`；primeRoot 为空目录，overrideRoot 放
  `builtin/builtin.db`（由 `VFS_GenerateGlobalIndexWholeSystem` 生成过全局索引的
  9.db）+ `builtin/builtin_0.db`（指向 9_0.db）。
- 打开后 `VFS_HasSystem("builtin")=1`。
- `VFS_IsExist` 默认报 **25 = GET_SYS_FAILED**，因为它按**路径前缀**查系统。
  `VFS_SetPathCustomPrefix("qtsvfs://")` 后，`qtsvfs://builtin/...` 能被识别，
  错误从 25 变成 0（文件不存在）或 261（查目录失败）。前缀全局在
  `libQtsVFS base+0x3d1800`：`+0x18` 长度、`+0x20` data。
- 一旦 `package_names` 非空，挂载会走 prime 包检查并报 **6**：
  `/(qts-remaindir-node-index).data not exists!`（`LoadRemainDirHashesFromPackage`,
  QtsfSystem.cpp:1991）。该节点在 **原始 9.db 和 gen 后的 9.db 里都不存在**
  （用 5 种路径写法算 hash 回搜，均 0 命中），说明它由 **建包/合并工具**生成，
  不在 APK 包内。
- `VFS_GenerateGlobalIndexWholeSystem(root, "9")` 返回 1，并把全局索引写进
  9.db（10,928,128 → 11,698,176 B），但**不生成 remaindir**。

`GlobalIndexPrime.data` 的 INGQ 结构（本轮定量）：

```text
0x00  "INGQ"          0x04 u32 version=2
0x18  u64 校验/包哈希  0x20 u32 低 32 位（=0x729dc80f）
0x24  u32 1800        0x28 u32 1,576,751  ← 条目数
0x2c  u32 562         0x30 u32 3
0x38  6 字节/条目 × 1,576,751 = 9,460,506；56 + 9,460,506 = 文件大小 9,460,562
```

条目不是简单的 `(u64 hash,u16 pkg)`，未解；13 种路径写法（正/反斜杠、构建根
`:/System/Project/Assets/../Raw`、`qtsvfs://`、`RawAssets/` 等）算出的
`VFS_CalcHashCode64` 都无法在 INGQ 中命中。包 9 的 `9_0.db` 里能看到构建路径
`:/System/Project/Assets/../Raw\Databin\Public\Item.bytes`；包 0 的 `0_0.db` 里
有 `heroDatabin` 内容，说明 databin 数据确实在包 0/9，但节点名是 hash。

**下一步**：用 QTS 的 fullfill/merge 建包流程生成 remaindir 节点（或在
`QtsfPackageMounter` 里找到它的写入点），再按路径 hash 读 `Databin/*.bytes`；
备选是离线解析 0/9 包的页与 INGQ 6 字节条目。

---

## 6. 十人全量数据可行性


### 6.1 `.ope` 的边界

支持“本地玩家操作数据”的证据：

- 头部有设备型号 `Vivo V2546A`；
- 事件是触控、技能槽、UI、GameObject 路径；
- 目前没有发现十名英雄的坐标、血量、经济、装备等字段；
- `OperatorMonitorModule` 的采集入口在 `OperatorDataPlayer`，天然是本地玩家视角。

尚未完成的验证：

- 对全流做玩家 ID/英雄 ID 穷举，确认没有其他玩家的事件；
- 检查 `MemoryData` 是否可能包含服务器下发的十人状态快照。

结论：**`.ope` 不像是十人全量状态表，更像本地操作日志**（◐）。

### 6.2 `.abc` 的潜力

`.abc` 已确认包含：

- 十人玩家块；
- 英雄 ID；
- 尾部 TLV 事件流；
- 版本与构建信息。

`.abc` 可能包含：

- 移动/普攻命令的位域压缩数据（`CmdCompressPlayerInfo` 相关字段：`maxCampPosBitCnt`、`maxCampPosCnt`、`compressInfo_Move`、`compressInfo_CommonAtk`）；
- 逻辑帧事件；
- 技能释放、击杀、经济等事件。

但“有数据”不等于“能直接读出十人状态”：

- TLV 事件量很小；
- 玩家块主要是元信息；
- 真正的过程状态可能需要客户端用 `.abc` 重放，由 GameCore 模拟产生。

### 6.3 三条路线对比

| 路线 | 能得到什么 | 成本 | 风险 |
| --- | --- | --- | --- |
| 解析 `.ope` | 本机操作数据：触控、技能槽、UI、APM 等 | 低-中 | 只有本地玩家，不是十人全量 |
| 解析 `.abc` + 客户端重放 | 十人过程状态、坐标、血量、技能等 | 高 | 需要理解命令流/模拟器，版本兼容性差 |
| 录屏 + OCR | 面板可见数据、指定玩家时间轴 | 中 | 需要多视角录制，覆盖不完整 |

当前建议：

1. 先把 `.ope` 解析完整，作为“操作分析”的高价值数据源；
2. 同时继续啃 `.abc` 的 TLV 和 `CmdCompressPlayerInfo`，判断能否离线重建十人过程；
3. OCR 保留为校验和兜底，不作为唯一路线。

---

## 7. 已排除的路线

### 7.1 Oodle / LZH

结论：`.ope` 与 Oodle 无关。

证据：

- `libsgameoodle.so` 是 AArch64 完整 Oodle 2.x，但**不含 legacy LZH 解码器**；
- `OodleLZ_Decompress` 对 `.ope` 报：
  `data is either corrupted, not a valid Oodle stream, or was compressed with an unsupported legacy compressor!`
- `OodleLZDecoder_Create` 对 legacy 压缩器报：
  `Legacy LZ VTable not installed`
- `g_OodleLZLegacyVTable` 在 BSS 中为 0；
- `OodleLZLegacyVTable_InstallToCore` 在 `.so` 内没有调用者；
- `OodleLZ_GetFirstChunkCompressor` 对随机数据也会返回 0–6，是假阳性，不能作为“LZH”证据；
- `decompress_from_memory` 检查 `"ODL"` magic，是归档/索引解包器，不是通用 Oodle 解压器。

### 7.2 其他误判

- `SyncNoCompressNoEncryt` 属于 `GCloud.ALogMode`，不是回放压缩/加密模式；
- `.abc` TLV 中的英雄 ID 假阳性：某些 seq 值恰好等于英雄 ID（112、118、144 等），不能当作英雄引用；
- `.ope` 的 `0x8A` 曾被误判为 deflate 起点，实际 `0x8A` 是 flag，`0x8B` 才是数据起点。

---

## 8. 未解问题与优先级

| 优先级 | 问题 | 状态 |
| --- | --- | --- |
| 已解决 | 记录类型命名 | 2026-10-29：`emOperatorDataType` 枚举提取，0x00–0x19 权威命名，见 4.6.1 |
| 已解决 | Touch/Move/GameCoreFrame/SkillSlot 变长记录边界（部分） | 最小不确定度 DP + confirmed/tentative 分档；Common/Move/CppEvent 新形态确认 |
| 已解决 | IL2CPP 注册结构是否可解析 | 2026-10-29：**不可**。本 `.so` 无 CodeGenModule/moduleName/codegenModules 数组，注册元数据被剥离；`.data` 为单一大指针表，见 5.5.2 |
| 已解决 | `.so` 与 metadata 是否同一构建 | 2026-10-29：**是**。416,645 槽 / 405,642 唯一目标 / ret 458,014 / 40 个 Write 全落 0x8700 字节内，见 5.5.1 |
| P0 | 0x3556 报墙区域的序列化变体（疑似 WriteBitPacked/WriteUshort 固定位宽字段） | 未解；位级写入器 `WriteInt/WriteBitPacked/WriteUshort` 在 `0x597774c`–`0x5978300`，**整段被 16 KB 页加密覆盖**，见 5.5.3 |
| P0 | 页级代码加密（4 KB 粒度，约 25% 页） | **已解**：实为按字粒度的 XOR 0xE3 混淆，逐字二状态 DP 可 100% 还原，见 5.7 |
| P1 | `*OperatorData.Write` 是否就是 .ope 序列化 | **已证伪（定论）**：内存中解密代码显示为 Puerts 绑定编组（IsAssignableFrom 内联 + 缓存 Type 分派 + 4 个 float 参数），见 5.10.2 |
| P0 | `.ope` 容器链 | **已解**：`0x01 + raw DEFLATE` → 内层头(0x8A) + `u32 长度` + Oodle 负载 → 39,634 字节流；版本/机型/账号/时间可稳定取出，见 5.6.1 |
| P0 | 记录头的字段模型 | **已证伪**：`type + Frame:u16` 不成立（39.5% 帧递减；`ae 01` 在 65 条连续记录里恒定），见 5.6.3 |
| P0 | 字节级分段是否唯一 | **否**：仅 19.1% 区间唯一，55.8% 有两解 → 语法欠定，不能据此发布计数，见 5.6.4 |
| P1 | 全流时间轴 | **已解**：1,999 个 `01 <varint>` 锚点严格单调 28,523→35,194，中位间距 16 字节，见 5.6.2 |
| P1 | slot 与 metadata 方法索引逐条对应 | **已坐实**：live 解密代码复核，`OperatorData` 21 个方法地址 0x5977320–0x597859c 严格递增且形态自洽，见 5.10.1 |
| P1 | 各类型字段表（声明顺序） | **已解**：`int[8]=fieldStart`、`u16[18]=fieldCount`，20 个类型字段名全部语义自洽，见 5.5.4 |
| P1 | Touch/Move/0x04/0x14 的 varint 字段语义（顺序、坐标缩放） | 未解；同样依赖 Write 反汇编 |
| P1 | `.abc` 记录流语法 | **部分解**：`seq:u8 + 00 + L:u8 + payload + 7B`，13,062 条；payload 标签流 `0x12/0x13/0x14/0x01/0x02` 精确消费 82.3%，见 5.13.3 |
| P1 | **M3 战斗初始化命令序列** | **主结构已解（2026-10-29）**：C#↔GameCore 无开局 C 函数、初始化走 CS 命令流（5.16.1）；GameBuilder 生命周期 + SGW 签名（5.16.2/5.16.3）；`.abc` 头部 Svr2GameCore KV 表 53/46/42 条已还原（5.16.4） |
| P1 | Svr2GameCore confType 全表语义 | 未解：51 个 confType 值恒定、94/95 随对局变（5.16.4）；语义需 M2 databin 读表对拍（表 `Svr2GameCore`，GameCore 侧节点 `GetResSvr2GameCoreInfoNode`） |
| P1 | `.abc` 头 0x0263..0x41E 其余初始化标量 | 未解（5.16.5 布局已列）；含对局时间/随机数等 u32 |
| P1 | deskPool 十人条目的二进制形态 | 未解；协议类型 `CSProtocolWrapper.CSDT_DESK_SVR2GAMECORE_ITEM`（5.16.3），玩家块内应含其展开 |
| P1 | `.abc` 十人名单 | **已解**：`team/slot/actorId/name`，9/25 样本凑满 10 人，见 5.13.2 |
| P1 | `CmdCompressPlayerInfo` 位域编码 | 未解；**坐标就在这里**（位域压缩，非定宽），见 5.13.8 |
| P1 | `.ope` 是否严格只含本地玩家 | 未解 |
| P2 | UILayout 123 字节内部结构 | 未解 |
| P2 | MemoryData 是否含嵌套记录流 | 未解；观察到疑似嵌套序列 |
| P2 | 更多对局样本的形态交叉验证 | 进行中 |

---

## 9. 复现与工具

### 9.1 只读探针

```powershell
python scripts/replay_probe.py data/replays/samples/20261028_135516.abc --json
```

当前项目探针能读取：

- `.abc` 头部、十人块、英雄 ID；
- `.ope` 外层 deflate、版本、设备、对局 ID、时间；
- `.ope` 第二层 raw DEFLATE 与操作流记录类型（`emOperatorDataType` 枚举命名，见 4.6.1）；
- 操作流结构解析在确认形态能覆盖全流时输出事件计数，遇到未解码变体时如实报墙（当前样本推进到 0x3556）；
- 工作台「回放实验室」导入后展示解析状态与报墙位置。

### 9.2 研究脚本

位于 `data/replays/_analysis/tools/`：

| 文件 | 用途 |
| --- | --- |
| `ope_records.py` | operator stream 顺序解析（研究中，Touch 变长记录尚未完全解决） |
| `probe_scan.py` | `.ope` 内层熵/偏移扫描 |
| `probe_decoder.py` | Oodle 解码器探测（已排除） |
| `oodle_emu.py` | AArch64 Oodle 的 Unicorn harness |
| `test_roundtrip.py` | Kraken 编解码往返验证 |
| `meta_browse.py` | metadata 类型/方法/字段检索 |
| `meta_method_grep.py` | 按方法名精确检索 metadata |
| `meta_literals.py` | string literal 表解析 |
| `scan_bl.py` | 全 `.text` BL 调用点扫描（numpy，明文+XOR 0xE3 双通道） |
| `rtdump.py` | runtime_dump 历史镜像的 VA 读取器（只读历史文件） |
| `abc_init_region.py` | `.abc` 头部区域解剖（块定位/字符串/帧流起点） |
| `abc_svr2gamecore_conf.py` | Svr2GameCore KV 配置解析 → `_analysis/svr2gamecore_conf.json` |
| `ope_offsets.py` | `.ope` 偏移探测 |

### 9.3 中间产物

| 文件 | 内容 |
| --- | --- |
| `data/replays/_analysis/ope_decoded.bin` | 39,634 字节 operator stream |
| `data/replays/_analysis/tools/operator_monitor_types.txt` | 108 个 `OperatorMonitor` 类型清单 |
| `data/replays/_analysis/global-metadata.dat` | 客户端 metadata |
| `data/replays/_analysis/libil2cpp.so` | 客户端 IL2CPP 二进制 |

### 9.4 只读与安全说明

- 所有分析均只读原文件；
- 未修改 `.abc` / `.ope`；
- 未注入游戏进程、未修改包体、未修改内存；
- `param.json` 含敏感字段，本文不记录其值；
- 结论仅用于赛训数据研究，不用于绕过游戏安全机制。

---

### 5.14 QTSF 容器与 libQtsVFS（第二轮破解，2026-10-29）

样本：`_analysis/apk_data/9_9.db`（组 9 索引，1,114,112 B）、`0_0.db`（组 0 索引，29,409,280 B）、
`libQtsVFS.so`（3.99 MB，自 APK `lib/arm64-v8a/` 提取）。

#### 5.14.1 .db 文件布局（9_9.db 实测）

```
+0x00  magic 01 00 00 02 01 02 03 04
+0x08  u32 有效负载长度        +0x0c  u32 文件总长
+0x10  u32 数据区起点 = 0x5000 +0x14  u32 = 0x1000
+0x24  u32 = 5144（首段长度；0x1000+5144 = 0x2418 与实测吻合）

0x1000..0x2418   有序 u32 数组（升序，跨页连续；0x2000 起点是 0x1000 页的超集
                 ——多级索引/B+ 树形态）
0x2418..0x5000   更多有序数组（0x3000/0x4000 页各自成段）
0x5000..0x1a630  LZ4 压缩内容块（Unity 序列化资源，见 5.14.3）
0x1a630..0x83234 节点记录链（9_9.db 主链 4,651 条，全文件 9,554 条）
之后             记录链与哈希数组交替；0xad320 有 5144B 名字池段
```

#### 5.14.2 节点记录格式（已全解）

链式结构，`next = A + len`，全文件可精确遍历：

```
[u32 self=A][u32 parent=-1][u32 len][data(len-12)]
```

92B 文件节点（9_9.db 有 9,524 条）：

```
+0x00 u64 hash_A        每条唯一（9,524/9,524）
+0x08 u32 =8            常量
+0x0c u32 =56           常量
+0x10 u32 1/0           标志（638 条为 0）
+0x14 u32 0 或小值      少数记录非零
+0x18 u64 hash_B        每条唯一（内容 hash）
+0x20 u64 size          3,368 个唯一值
+0x28 16B               摘要
+0x38 u32 count=1       +0x3c u32=0
+0x40 描述符×count      8B/个：{u32 packed, u32 raw_size}
+0x48 hash_B 重复
```

**描述符统计（9,524 条）**：`packed` 9,441 条 = `0x00050004`（低字节 block=4、次字节 page=5）、
81 条 = `0x00050001`；`raw_size` 9,496 条 = `0x4B000`（307,200）。即：**绝大多数内容集中在一个
307,200 字节的页里**。272B 记录（大文件）的描述符为 12B/个 `{packed, raw_size, offset}`，offset
升序（0x34688、0x67158…）——**多 extent 文件带显式偏移，单页文件不带**（偏移在页内目录中）。

104B 记录（26 条）= 2 extent：如 `{block1,page5,raw 0x4000,off 0x4e350} + {block9,page9,raw 0x4000}`。

#### 5.14.3 压缩内容块（LZ4）

- 压缩器确认为 **LZ4**（libQtsVFS 字符串 `CompressFunc_LZ4HC`、`create lz4 stream read ctx:`）。
- 实测压缩比 ≈ 1.07：**内容基本不可压，LZ4 以纯字面量方式存储**，解压输出 ≈ 原字节。
- 已解出块（起点 0x4ff4）输出 1,056B：含 Unity 序列化内容——`animationCurve` 后跟关键帧浮点
  （`ab aa aa 3e` = 0.3333）、`avatar_bodyL`（骨骼名）、`S_MOVE9`、`broadcast (1)`、
  `Res/666_DLC/PartForm/DLCMini`、`rJianTou`。
- 块起点失败模式：match 引用超出已有输出（'neg'）→ 块间窗口关系未定（真流起点更早，或按页
  独立成块带页头）。重同步扫描（0x53d0..0x5440）无 ≥400B 的干净解。

#### 5.14.4 libQtsVFS 读路径（反汇编权威结论）

```
VFS_Read (0x1b0c74, 600B)          = 日志壳，实际调用 0x1ee8a8
0x1ee8a8 QtsfFile::Read:
  file+0x10 = storage 对象          file+0x20 = curPos (u32)
  storage+0x1c = 文件大小           storage+0x38/+0x40 = 页表基址/条数
  页表 = 12B/条 {u32 key, u32 packed, u32 X}，按 key 升序，二分查找：
      page = (curPos - key) / X ; rem = (curPos - key) % X
  页缓冲上限 = 常量 0x4B000（307,200，与记录描述符 raw_size 一致！）
  解压缓冲 = 2×页大小；页缓存挂在 storage+0x438
0x1487e4 = 页缓存查找:
  packed 低字节 = block，次字节 = page（与记录描述符 packed 直接对应）
  在缓存树中比对 [obj+0x20]==block、[obj+0x24]==page，命中后虚调用取页数据
```

#### 5.14.5 哈希函数（VFS_CalcHashCode64Raw @ 0x1ae184）

双向 DJB2（乘数 33）：

```python
def hash64(b):                      # b = 路径字节
    fwd = 0x5BD1E995                # 顺序逐字节: h = (h + h<<5) ^ c
    bwd = 0xAB9423A7                # 逆序逐字节: 同上
    ...
    return fwd | (bwd << 32)        # len<1 时返回 0xAB9423A75BD1E995
```

**注意**：`hash64("QTSF_PACKAGE") = 0xf7c7d69240e43940` ≠ 根记录 hash `0xd14b28c0acc40d11`
→ 节点 hash 的输入不是裸路径字节（可能含前缀、大小写归一或 UTF-16），输入格式待定。

#### 5.14.6 定位与下一步

| 事项 | 状态 |
| --- | --- |
| .db 头、节点记录、描述符 | ✅ 全解 |
| 页表机制 / 0x4B000 语义 | ✅ 从代码读出 |
| 压缩器 = LZ4 | ✅ 确认 |
| 页内目录 + 页载荷 framing | ❌ 需要一个存储卷（X_N.db）样本 |
| hash64 输入格式 | ❌ 用已知路径对拍 |
| 路径名来源 | ❌ 前端编码名出现在压缩内容里，独立名字表未定位 |

下一步：(a) 反汇编页对象 vtable+0x30 的实现（读卷 + LZ4 调用点）；(b) 重启模拟器 dd 拉取任一
存储卷（如组 0 的 0_0.db 107MB）头 2MB，对照页表定位 (block=4,page=5) 的页并解压；(c) 用
COMDT/配置字段名（GoldCoin 等）在卷内容字面量中定位配置表。

---

### 5.15 GameCore 宿主化审计（headless 模拟路线，2026-10-29）

目标：不写自己的模拟器，**把客户端自带的战斗模拟核心在自建宿主里跑起来**，
喂 `.ope/.abc` 输入，逐帧读出经济/KDA/伤害/位置全套状态。

#### 5.15.1 审计结论（libGameCore.so，82MB）

| 审计项 | 结果 |
| --- | --- |
| 代码加密 | **无**：`.text` 41.7MB，60/60 采样点 100% 可解码（对比 il2cpp 的 25% XOR 混淆+块重排）|
| il2cpp 依赖 | **0 个** `il2cpp_*` 导入 |
| Unity/GPU 依赖 | **0 个** GL/GLES/egl 导入 |
| 实际导入 | 373 个：libc/pthread（主力）+ Lua 69 个（外部 pua_*）+ android 10 个 |
| C 风格导出 | 123 个（完整清单见 `_analysis/gamecore_c_exports.txt`）|
| 符号表 | 无 .symtab；2,125 个 dynsym 定义（1,969 个 C++ mangled，多为 Escher/Prism/std）|

**结论：GameCore 是可宿主的独立模拟核心**（帧同步设计，无渲染依赖——大概率与服务器同核）。
C# 层只是它的一个宿主，我们写自己的宿主即可。

#### 5.15.2 C API 分组（按地址序）

| 组 | 函数 | 作用 |
| --- | --- | --- |
| 启动 | `ModuleInit`, `UnityPluginLoad/Unload`, `JNI_OnLoad` | 引导 |
| 文件 | `QTSOpenFile/QTSReadFile/QTSSeekFile/QTSRegisterSystem…` | 配置/资源经注册的 QTS 文件系统读取 |
| **配置表** | `SGameSetEnableDatabinCrcFromFile`, `DT_FindByKey/DT_Count/DT_GetByIndex`, `GameDataWrapper_GetTable/GetInt/GetFloat/GetString/GetStruct/*` | **databin 加载 + 表查询 C API** |
| **命令通道** | `PushCsBuffer/CommitCsBuffer/ResetCsBuffer/SFPushCsImmediatePackBuffer/FlushCsImmediatePackBuffer`, `PopFifoCppPackBuffer/PushCppImmediatePackBuffer` | C#宿主→GameCore 推帧命令（CS=CSProtocol，即 FRAME_CMD_INFO）|
| **状态读出** | `SGC_GetPlayerSettleData/SGC_GetPlayerMapExInfo/SGC_GetPlayerTLogData`, `PushViewBuffer/CommitViewBuffer` | 结算数据 / 每帧世界状态 |
| 场景 | `SL_StartLoadScene/SL_GetNode/SL_GetAttribute…` | GameCore 自带场景图 |
| 其它 | `CompressData/DecompressData`, `sgame_crypto_aead_lock`, `Escher*`（热更框架）, `Prism*`, `Android_Log*` | 工具/可桩替 |

#### 5.15.3 间接跳转与真实地址（已全部可离线解析）

所有 C 导出是 12–28B 跳转桩：`adrp+ldr [函数指针表]` + `br/blr`。
表区 `0x5229000–0x5235000`，**由 RELA 静态填充**（674,713 条 RELATIVE 已物化验证）：

```
ModuleInit               槽 0x522e960 → 实现 0x46ad0cc  ✅ .text
PushCsBuffer             槽 0x522a728 → 实现 0x460a3ac  ✅
SGC_GetPlayerSettleData  槽 0x522e978 → 实现 0x46ad0fc  ✅
GameDataWrapper_GetTable 槽 0x522a470 → 实现 0x4606f04  ✅
QTSRegisterSystem        槽 0x52296c8 → 实现 0x45f3760  ✅
UnityPluginLoad          槽 0x52358d8 → 实现 0x474b448  ✅
PushViewBuffer/CommitCsBuffer 等 8/8 全部解析成功
```

#### 5.15.4 headless 架构方案

```
宿主进程（ARM64）
├─ dlopen: libGameCore.so + libQtsVFS.so + lua 库 + libc++
├─ QTSRegisterSystem(自建文件提供者 或 libQtsVFS 挂载 QtsVFSCache 包)
├─ ModuleInit()                                   ← 引导（环境回调待逆向）
├─ databin 加载 → GameDataWrapper_* 可查询全部配置表   ← M2（顺带完成原 B 目标）
├─ 战斗引导命令序列（C# 端序，待从 metadata/回放初始化还原）
├─ 逐帧: PushCsBuffer(命令) + CommitCsBuffer → GameCore 步进
└─ 逐帧: SGC_GetPlayer* / ViewBuffer → 经济/KDA/伤害/位置全套状态
```

运行环境二选一：PC 上 qemu-user-aarch64（纯计算，无 GPU 需求），或 Android 模拟器里的
**自建常驻进程**（不启动游戏、不登录——无封号风险，houdini 已验证能跑这些库）。

#### 5.15.5 里程碑与风险

| 里程碑 | 内容 | 风险 |
| --- | --- | --- |
| M1 | 宿主进程 + ModuleInit + QTS 注册，GameCore 起来 | ModuleInit 的环境回调要求未知（Escher 层）|
| M2 | databin 加载成功，GameDataWrapper 导出全部配置表 | databin 卷布局（QTSF 页载荷 framing，见 5.14）——**但宿主内可让 libQtsVFS 自己挂载，可能绕过破解** |
| M3 | 战斗引导命令序列还原 | 序列可能很长；C# 侧参考在 metadata（GameReplayModule 104 方法）|
| M4 | `.ope/.abc` → CS 命令流 | 序列化是 TDR（`GameCoreInfo_TDRGUIDHash`）；GameCore 内有干净的 pack/unpack 代码可作权威参考；需确认命令缓冲是否经 `sgame_crypto_aead_lock` 加密 |
| M5 | 帧循环 + 状态读出 → 全套数据 | 线程模型（`SFNtfRunningGameCoreThreadID`）|

工程量：**周级**。M1+M2 即兑现原 B 目标（全部配置表），M5 兑现"每帧全套数据"。

#### 5.15.6 M1 引导链实测（2026-10-29）

**启动路径**：`ModuleInit`(导出) → 槽 0x522e960 → `0x46ad0cc`：置 `x0 = 0x542f4b0`（BSS 上下文块，
30MB BSS 区 `_edata=0x526eb98 .. _end=0x544d478`）→ 尾调 `0x40a0360`。

**`0x40a0360`**：读 `[ctx+0x48]` 一次性标志（BSS 零初始化→首次通过）→ 置 1 → **线性调用约 17 个
子系统初始化函数**（全部经指针表，x0=ctx 传入）。分诊 17 个 callee 前 96 条指令：**无 Java/JNI、
无 Android 日志依赖**；多数自身又是指针表跳转。

**JNI_OnLoad**（Android 生产路径）：GetEnv/AttachCurrentThread，存 JavaVM@`0x544d460`、
JNIEnv@`0x544d470`，日志 tag `"Escher-GameCore"`——自建宿主可绕过或桩替。

**桩与真身**：
- 静态即真：`PushCsBuffer→0x460a3ac`、`GameDataWrapper_GetTable→0x4606f04`、
  `QTSRegisterSystem→0x45f3760` —— **配置/命令通道开箱即用**
- 静态为桩：`SGC_GetPlayerSettleData→mov w0,#11; ret`（4 个 SGC_Get* 同型）、部分引导 callee
  为空 `ret` —— Escher 分节加载体系，**表在运行时装填**；状态读出走 ViewBuffer 或运行时表

**M1 执行计划**：模拟器内自建 ARM64 常驻进程（root 推送，非游戏进程）→ dlopen GameCore →
调 ModuleInit 导出 → 观察引导链实际走到哪/缺什么回调。配置 API 先行验证：注册 QTS 后调
`GameDataWrapper_GetTable`，不等战斗即可枚举配置表。

---

## 附录 A：偏移速查

### `.abc`

```text
0x0000  4 个长度前缀字符串（版本/构建）
0x0023  本地英雄 ID（4 字节小端）
0x02A2  本地玩家块起点 674
0x44F4  尾部 TLV 起点 17,652（本样本）
         TLV 记录区结束于 68,261；文件末尾 7 字节未纳入记录
```

### `.ope`

```text
0x0000  外层 0x01
0x0001  外层 raw DEFLATE
        解压后内层的 0x008B 是第二层 raw DEFLATE 起点
```

### operator stream

```text
0x00–0x1A  27 字节总头
0x1B       第一条记录：0x16 UILayout, Frame=436, 123 字节
0x99        SkillSlot 批次起点
0x1DE       GameCoreFrame 304 / UnityFrame 28,523
0x333       GameObjectName（Main Camera）
0x366       GameObjectName（Camera_Form）
0x38D       MemoryData, Frame=424, len=45
0x3BE       GameCoreFrame 368 / UnityFrame 28,690
0x3C4       Touch 记录开始
```

---

## 附录 B：术语

| 术语 | 含义 |
| --- | --- |
| TLV | Type-Length-Value，本样本中为 3 字节 key + 标记 + 1 字节长度 + payload |
| raw DEFLATE | 不带 zlib/gzip 头的 DEFLATE 流，windowBits = -15 |
| LEB128 | 小端变长整数编码，每字节低 7 位有效，最高位为继续标志 |
| OperatorMonitor | 客户端操作数据采集/分析框架 |
| `.ope` | OperatorMonitor 生成的操作数据文件 |
| UnityFrame | Unity 渲染帧号 |
| GameCoreFrame | 游戏逻辑帧号 |
| InstId | Unity GameObject 实例 ID，本样本中以 32 位有符号值的 64 位 varint 形式出现 |

#### 5.17.8 override-only 挂载与 hash 读取（同轮收尾）

把包 9 放到 **override 层**、internal=builtin、`packages_count=1`、
`app_buildin_packages_count=0`，`VFS_OpenQtsVFSSpaceEx` 返回 **1 / err=0**，
不再触发 remaindir 错误（说明 remaindir 只对 prime 包强制）。

但 `VFS_IsExistByHash("builtin", hash)` 对以下路径仍全部 0：

```text
:/System/Project/Assets/../Raw\Databin\Public\Item.bytes
Databin\Public\Item.bytes
/Databin/Public/Item.bytes
Databin/data_xls/UGCHero.bytes
```

`VFS_IsExistByHash` 的 sysName 必须是 `"builtin"`（传 `"9"` 报 25 GET_SYS_FAILED）。
说明包 9 的节点索引里没有按这些 hash 暴露该文件，或路径归一化/hash 输入格式
仍不对（`9_0.db` 里的 `...\Databin\Public\Item.bytes` 很可能只是某个索引文件
的**内容字符串**，不是节点名）。这是下一轮要解决的点。

另：MuMu 卡在 `stopping` 时，`MuMuManager control shutdown/launch` 无效；
需 `taskkill /PID <MuMuNxDevice.exe> /F` 后 `MuMuManager control --vmindex 0 launch`，
约 90 秒恢复。

#### 5.17.9 按 hash_B 读取任意 QTS 文件；databin 不在 QTS 文件层（同轮收尾）

**节点记录与 hash 语义**（包 9 原始 `9.db`，4,485 条；dev9 4,650 条）：

- 节点链起点：`9.db` 为 `0x1a000`，dev9/9_9 为 `0x1a630`（首条是 156B 的
  `QTSF_PACKAGE` 头，需跳过）。
- 92B 文件节点：`+0x00 hash_A`（唯一）、`+0x18 hash_B`、`+0x20 size`、
  `+0x38 count`、`+0x40 描述符`。`hash_B` 才是 `VFS_OpenFileByHash` 的 key。
- 实测 `VFS_OpenFileByHash("builtin", hash_B, 0)` 可打开并 `VFS_Read` 出
  与 `size` 相同长度的内容；`hash_A` 会报 5（FILE_NOT_EXISTS）。

**挂载**：

- 28 个 APK prime 包全部放 override 层、primeRoot 为空目录、
  `package_hashes` 全 0、`data_version=12.1.1.1`、`build_id=4989537` →
  `OpenEx=1/err=0`，28 个包全部可用。
- 设备下载包（`QtsVFSCache/packages/9`，12.1.1.26）不能直接 override
  （err 45 DIFF_OPEN_PACKAGE）；把它 copy 后用
  `VFS_GenerateGlobalIndexWholeSystem(root,"9")`（1/err=0）生成全局索引，
  再作为 **internal**（`packages_count=0`）可 `OpenEx=1/err=0`，
  4,650 个节点均可按 hash_B 读。

**扫描结果**（16,001 个 APK 节点 + 4,650 个设备 9 节点）：

- 包 0 有 180 个节点含 `*Databin` 字符串，但都是 **JS/TDR schema**
  （如 `TDR ResHeroCfgInfo.Skill ResDT_SkillInfo[MAX_HERO_SKILLNUM=6]`、
  `var __decorate`），不是表数据。
- 包 9/9900/3002/114/305000000145 对 `Databin`/`TdrData`/`ResHeroCfgInfo`
  **0 命中**。
- 按路径 `VFS_OpenFile("qtsvfs://builtin/Databin/data_xls/Hero.bytes")` 等 7 种
  写法全部 0/err5；databin 表不作为松散 QTS 文件暴露。
- GameCore 宿主里 `0x52742a0` 注册表在 `ModuleInit` 后仍是 **0**；
  它由 C# `DatabinManager` 填充，不在 native 初始化里。

**结论**：databin 表很可能在 **Unity AssetBundle/TextAsset** 里（包 0/9），
或由 C# 侧从服务器/`dataCache.db` 装载；单靠 QTS 文件层枚举不到。
下一步二选一：
(a) 用 UnityPy 解析包 0/9 的 AssetBundle，找 `TextAsset` 形式的 `*Databin`；
(b) 在最小 il2cpp 宿主里跑 `DatabinManager.LoadLocalDatabin`（需要 C# 运行时）。

#### 5.17.10 AssetBundle 假设排除（同轮收尾）

对 16,001 个 APK 节点 + 4,650（设备 9）+ 369（设备 0）+ 5,064（设备 1）
个节点做了 32 字节魔数扫描：

- `UnityFS`：APK 全库仅 **1 个**（包 0，300,921 B，加载界面 spine，TextAsset
  `horseloading_spine.atlas/.skel`）；设备 9/0/1 **0 个**。
- `AKPKD`：APK **336 个**，头部后是 `BKHD/DIDX/DATA` → **Wwise 音频 bank**，不是资源包。
- `UnityWeb/CAB-/PK/TDR/TdrData/INGQ`：0 个。
- 设备 1（5,064 节点、1.27 GB 数据）按内容搜 `Databin/TdrData/ResHeroCfgInfo`
  **0 命中**。

→ databin 不是 Unity AssetBundle/TextAsset；APK/下载包里的资源是**匿名 QTS 节点**
（hash_B 可读、无路径名），核心表很可能是无名字的 TDR 二进制。
下一步只剩两条：
1. 从 C# metadata 提取 databin 表名/路径列表（`ResData.Databin` 枚举、
   `DatabinManager` 的路径拼接常量），再解决 QTS 路径 hash 归一化；
2. 用 GameCore 的 `TdrData` schema（包 0 的 JS 里有 `TDR ResHeroCfgInfo...`
   描述）反推表结构，直接在匿名二进制里按结构识别表。

UnityPy 已安装（1.25.4），但当前样本里没有可用的 databin bundle。

#### 5.17.11 定论：databin 是登录后下载的独立包，当前设备没有

metadata literal 67327：

```text
jar:file://{0}!/assets/databin/{1}
```

说明 databin 是从一个 **jar/zip 的 `assets/databin/` 目录**按表名读取的，不是 QTS 包、
不是 UnityFS。另有 **1,558 个** `*Databin` 表名字面量（`AIHeroCfgDatabin`、
`BattleEventsCfgDatabin`、`BattlePassExchangeDatabin` …），这就是表名清单。

实测当前环境：

- `base.apk`（1,572 条目）里 **0 个** `assets/databin`；
- 无 split APK、无 OBB、外部存储和 `files/` 下无 databin zip/目录；
- 只有 `files/databin.ver`（13,464 B，疑似版本清单/加密）；
- QTS 的 30,200 个节点（APK 28 包 + 设备 0/1/9）里没有 databin 表文件。

→ **databin 是客户端登录后下载的独立资源包，本机从未完整拉取**。这也解释了
GameCore 的 databin 路径为何在 QTS 里全部 0 命中。

**阻塞点（需要用户提供）**：一份正常登录后客户端下载的
`assets/databin/` 目录或其 zip（以及配套 `databin.ver`）。拿到后：
1. 按 literal 里的 1,558 个表名 + `.bytes` 直接读文件；
2. 用包 0 的 TDR schema（`TDR ResHeroCfgInfo...`）解析行数据；
3. M2 的 `GameDataWrapper_*` 对拍即可完成。

在此之前，M1（宿主）、QTS 文件层、M3（初始化命令）、M4（命令流）都可继续，不受影响。

### 5.18 M4 静态结论：CS FIFO 不加密；离线 5V5 是 databin 的运行时入口（2026-10-30）

- `sgame_crypto_aead_lock`（导出 0x45f21b8 → 0x45f21ac → 0x45f2074）在
  libGameCore **内部 0 个调用者**，只有导出跳转表引用；CS FIFO 的写入
  （`PushCsBuffer` → `sub_49cbf98` / `sub_49cc1a8`）是纯 `memcpy` 环形缓冲。
  → **CS 命令缓冲不经过该加密函数**，是原始 TDR 字节。
- 宿主实测：`ModuleInit` 后 FIFO 对象（`*0x50b6e70`）仍全 0，`PushCsBuffer(64)`
  直接 SIGSEGV；FIFO 要等战斗初始化/GameCore 线程创建后才可用。
- `.abc` 帧流里 `0x01` 外层 token（hero+flag+len+data）的 data 子标签：
  `0x2d` + u16BE（9,546 次，疑似移动/朝向）、`0x2c` + 17B（333 次，含坐标与
  递增序号）、`0x03`/`0x23`、`0x87`。这是 M4 输入→命令的静态入口。
- **离线 5V5 可启动但不登录**：客户端会在本机加载 databin（`LocalAISystem.
  StartGameBattleSimulation5V5AI`、`COffline5V5SelectHeroFormLogic`）。
  因此可以在离线对局运行时用只读 `/proc/<pid>/mem` 扫描 databin 表，
  工具 `_host/mem_scan.c`（按 pid + needle 扫描可读映射）。

### 5.19 【突破】离线 5V5 内存里的 databin 注册表（2026-10-30）

离线 5V5 不需要登录，客户端会在本机加载 databin。对局进程内：

- `libGameCore.so` 基址 + `0x52742a0` 是一个 **1,024 项的指针数组**，每项指向
  一个 `DatabinTable` 对象（本次样本对象步长 0xB8，但对象优先从指针数组取，
  不能按连续 0xB8 硬推）。
- 对象字段：`+0x10` **databin 路径 C 字符串**（`Databin/Public/Level/Level.bytes`）、
  `+0x18` 长度/容量、`+0x20` `{u32 index, u32 kind}`、`+0x38` `{u32 size, u32 flags}`、
  `+0xB0` 行数。前 43 项已解出，含
  `Databin/Public/Skill/skillIndicator.bytes`（181 行）、
  `Databin/Client/Actor/normalMonster.bytes`（2,625 行，1,601,604 B）、
  `Databin/Public/Battle/RecommendEquipInBattle.bytes`（342 行）等。
- 表数据在 `files/dataCache.db`（119 MB，`EnableLastCachedDatabinDB=1` 的 databin
  DB 缓存）；对象内的行目录指向该 DB 的映射页。QtskDB 在宿主里 `OpenBase` 返回 1，
  但 `OpenTable` 需要正确的 `STDBTableEnv` 哈希回调，当前只能到 err=8（表名/回调未定）。
- 进程退出后注册表消失（新 pid 不加载 GameCore），所以必须在**离线对局进行中**
  抓取。工具：`_host/mem_databin.c`（自动定位 base/registry，输出 1,024 张表）、
  `mem_tables2.c`、`mem_scan.c`、`mem_dump.c`。

### 5.20 【完成】离线 5V5 的 databin 全量行数据已导出（2026-10-30）

在离线 5V5 对局进程内，按表对象导出全部已加载表：

- 注册表：`libGameCore` base + `0x52742a0` → 1,024 项指针数组；实际有路径的表 **955 张**，
  其中 **825 张有行数据**。
- 表对象：`+0x10` 路径、`+0x18` 行步长（低 32 位）、`+0x38` 数据字节数、
  `+0x98` 行目录、`+0xB0` 行数。行目录条目 `{u64 rowId, u64 ptr}`，`ptr` 指向
  `dataCache.db` 映射页中的行记录；每行固定 `stride` 字节。
- 导出总量 **71,879,836 B ≈ 68.5 MB**（825 张表），落盘
  `_analysis/device/dtab_all/<index>_<name>.bytes.row` + `.meta`。
- 核心表实例：`Project8Hero` 259 行×688 B、`Item` 27,663 行×576 B（15.9 MB）、
  `Equip` 270 行×216 B、`RandomRewardStore` 14,286 行×1,232 B、`task` 12,129 行×840 B。
  行首即主键（Hero 1000/1001/1051…，Equip 1111/1112…，Item 6600…）。
- 行数据是 TDR 二进制；下一步用 `ResHeroCfgInfo`（161 字段）、`ResEquipInBattle`（84 字段）
  等 metadata 字段表解析，或把行块喂给 GameCore 的 `DatabinTableBase`。
- 限制：只覆盖**离线 5V5 当前加载**的表；未加载的 130 张（路径存在、rows=0）需在
  对应玩法/界面触发后再抓。经典 5V5 的 `ResHeroCfgInfo` 表若不在该模式加载，
  仍需从完整 databin 包里补。

工具：`_host/mem_databin.c`（枚举 1,024 表）、`mem_dump_tables.c`（按行目录导出
`rows×stride`，支持 `all`）。采集必须在离线对局进行中；进程退出注册表即消失。

### 5.21 【完成】825 张表的完整二进制块（头 + 行）与行格式（2026-10-30）

在 5.20 的行数据之外，按表对象 `+0x30` 的 DB 表头导出**整块**（0x98 头 + 行），
落盘 `_analysis/device/dtab_blocks/<index>_<name>.bytes.bin` + `.meta`：

- **825 张表、205,149 行、71,923,748 B（71.9 MB）/ 1,650 文件**。
  逐块校验：magic `stdr`、`+0x14` stride、`+0x18` rows、
  `+0x90` block size == 文件长度 == `0x98 + rows*stride`，**825/825 全部一致**。
- 表头 0x98 字节：`stdr`、`+0x08 u32`（450—452 左右，未定）、`MSES`、`+0x10=8`、
  `+0x14 stride`、`+0x18 rows`、`+0x1c` 起 28 字节 `'a'` 填充、`+0x3c "UTF-8"`、
  `+0x60` 32 字符 ASCII 哈希、`+0x90 u64 block size`。该 32 字符哈希
  **不是** 行/整块的 MD5（实测对不上），不能当内容校验用。
- 表对象补充：`+0x00` 指向类型 vtable 数组、`+0x28` 64 位表哈希、
  `+0x30` DB 表头指针、`+0x88` 行目录指针、`+0xA0` `{rows, rows}`、
  `+0xB8` 依赖表路径数组（`+0xC0` 依赖数）。`+0xB8` 的字符串是**依赖表路径**，
  `+0xA8` 是指向 GameCore `.text` 的代码指针数组，均不是字段名表。
- **行格式（已用 `ResHeroDataConf` 逐字段验证）**：
  - `+0x00 u32` 主键（rowId），随后按 TDR 类型的**自然对齐**排布；
  - **字符串字段** = 8 字节句柄 `{u32 表标记, u32 池偏移}`，同一张表内低 32 位
    标记恒定（Project8Hero=`0x818C158C`，ResHeroDataConf=`0xB27C20AE`），
    高 32 位为池内偏移（同表内随字符串长度递增，粒度 0x100）；
  - **整数** = 4 字节（`i*`/`dw*`/`w*`），**bool** 更小；因此
    `stride` 不一定是 8 的倍数：825 张中 717 张 `stride%8==0`，108 张不是，
    15 张 `stride<8`（纯标量行，如 `svr2GamecoreCfg` 53×4、`SettleConditionCfg` 42×4）。
  - `ResHeroDataConf` 实测：`dwID@0`，11 个字符串 @8..95，`iViability@96`，
    字符串 @104，`iOutputIntensity@112`，字符串 @120，`iStartedDifficulty@128`，
    字符串 @136，总长 **144**，与 C# 18 字段（1 键 + 14 字符串 + 3 整数）完全吻合；
    三行 ID=1/2/3 的三个整数字段也分别等于 1/2/3。
- **表→C# schema 映射**：按“表名 == ResData 类型名 / 去掉 Res 前缀”+ 列模式
  （字符串列和数值列顺序）比对，得到 **54 张高置信映射**，写入
  `_analysis/device/dtab_schema_map.csv`（例：`ResHeroDataConf`、
  `ResCommonSettle`、`ResRobotName`、`ResEquipVoice`、`ResTeamInfo`、
  `ResChannelID` 等，score=1.00）。完整列表见该 CSV。
- **原生专用表**：`Project8Hero`(86 列)、`Equip`(27 列) 等没有同名列数的 C# 类型，
  C# 侧是跨表合并视图（`ResHeroCfgInfo` 161 字段、`ResEquipInBattle` 84 字段），
  行内列名/列义只能从 GameCore 原生 schema 拿；当前未解。
- **字符串池未落地**：句柄高 32 位的偏移不在 `dataCache.db` 的原始文件偏移上
  （例：Project8Hero 首行 `strIdName` 句柄偏移 `0xAE2A00`，该处为全零；
  英雄名 UTF-8 实际在 `dc.db` 的 `0xB27D2` 等位置）。推测字符串在单独的
  databin 文本包/QTS 包中，句柄低 32 位是该包的标记。数值列不受影响。
- 已落地产物：`_analysis/device/tables_blocks.csv`（825 行：index/path/rows/
  stride/columns/block/id_first/id_last）、`dtab_schema_map.csv`、
  `dtab_schema_report.txt`、`dc.db`（124,780,544 B，本地副本，已被 `.gitignore`
  的 `data/` 规则忽略，不提交）。
- 工具：`tools/dtab_index.py`（重建索引）、`tools/dtab_schema.py`（schema 匹配、
  单表解码示例）、`tools/dtab_inspect.py`（列扫描）、`_host/mem_dump_blocks.c`
  （按表对象头整块导出）。采集链路：离线 5V5 → `/proc/<pid>/mem` 只读 →
  拉回本地校验。

### 5.22 离线 5V5 活进程里的 CS/缓冲对象（2026-10-30，只读快照）

在重新进入的离线 5V5（pid 1990，`libGameCore` base `0x400036a00000`）里，
按 `PushCsBuffer` 的静态实现（0x460a3ac → 槽 `0x525a798` → 0x49cbf98）追到
它真正操作的对象链：

- `PushCsBuffer` 的第 1 个参数 **不是** `*0x50b6e70`，而是
  `x0 = [[[base+0x4ff5de8]]]`：`0x4ff5de8` → `0x40003bc488b8`（`.data`）
  → `0x40003bcc3250`（`.data`）→ **8 个堆对象指针的数组**。
- 这 8 个对象结构一致（本次样本）：`+0x00` 共享类型/vtable 指针、
  `+0x08` 第二指针、`+0x10` `{total, 0}`、`+0x18` 数据缓冲指针、
  `+0x20` `{capacity, pending_len}`、`+0x2c/+0x30/+0x34` 三个游标。
  实测一个对象 `+0x18` 的缓冲里是 UTF-16 资源路径
  （`haracters/Prefab_Hero/503_KuangTie/skill/RunFast…`）+ 二进制头，
  另一个对象的缓冲里是 `1.0f/1000/900` 一类**状态数据**，都不是直接的
  FRAME_CMD TDR 记录。→ 该数组是 **GameCore 的多路缓冲池**（资源/状态/
  其他通道），CS 帧命令走其中哪一路仍未定。
- 游标确实随对局推进：100 ms 采样 `+0x2c` 前进 488–784，20 fps 下约
  **348/帧**；按“位”解释约 43.5 B/帧，和十人帧命令量级吻合。缓冲容量
  字段 0x8000/0x20000，但游标值远超容量（本次 0x98d1c…0xaac04），
  说明游标是**全流累计位偏移**，环形/分块映射在别处。
- 结论：CS 通道**确实在跑、且是原始位流**（与 5.18 的“不加密”一致），
  但要拿到逐帧 FRAME_CMD 记录，需要：
  1. 用能编译 ARM64 探针的工具链，在 `PushCsBuffer` 返回后读回指针与
     `CommitCsBuffer` 的长度（或直接按游标增量切片）；或
  2. 在宿主内复现 GameCore 的缓冲池初始化，再调用 0x49cbf98/0x49cbffc。
- 本次未把任何活进程数据发布：快照仅用于确认结构，未提交；进程已在分析后
  关闭。`_host/mem_dump.c` 可直接复用，采样脚本见 5.22 的命令记录。

### 5.23 【M5】帧循环与线程模型（2026-10-30）

#### 5.23.1 帧循环不是 C# 直调，而是 CoreThread + 条件变量

GameCore 在开局时创建一个独立线程 **`CoreThread`**（栈 0x40000 = 256 KB），
由每帧生产者唤醒；线程内跑一帧逻辑，然后回到条件变量等待。

- **创建**：0x46B7784。先 `operator new(0x10)` 建 callable，构造
  `std::string("CoreThread")`，再经运行期线程工厂
  （槽 `0x50B40F48`，本次样本填入 0x3F0F424）以
  `(target, name, stack=0x40000, flags=0, callable)` 创建；线程句柄存
  `0x544CB70`。
- **停止**：0x46B7848。取句柄，调 vtable `+0x10`（请求停）与 `+0x28`（join），
  清空句柄。
- **控制块**（0x544CB58..0x544CBD4）：
  - `+0xB58` float **帧 delta time**；
  - `+0xB78` mutex + `+0xB78+0x28` condition variable；
  - `+0xBD0` u32 **状态机**：0=空闲/未启动，2=跑一帧，3=退出；
  - `+0xBD4` u32 信号/通知字。
- **每帧生产者**：0x46B7888（float delta，经槽 `0x522EF98` 调用）。
  写 `+0xB58` → 若状态==1，notify 两组条件（`0x542A8B8/8C0`、
  `0x542A8C8/8D0`）并置状态=2 + `pthread_cond_broadcast`；
  若状态==0，先做一次初始化调用；最后取 context 并调用 `ctx+0x280`
  （主 context 更新）。
- **CoreThread 主循环**：0x4882C10。每轮读 `+0xBD0`：
  - ==2：跑一帧（0x4882CC8）：若干子系统 update（含 `[context+0x3A0]`
    的回调、两次全局 callback、`0x5091568(0x544CBD4, ret)` 通知），
    结束后检查退出标志 `[callable+8]`；
  - ==3：关停（0x4882D70）：notify、mutex、状态清 0、notify，然后退出；
  - 其他：写 `+0xBD4=-1` 后进入等待。
- **帧节奏**：在**英雄练习场**对局中实测 `CoreThread` 持续 R/S 交替，
  按帧被唤醒；同一局里 `AILocalThread` 也很热。**但这个结论不能外推到
  5v5**，见 5.23.1a。

#### 5.23.1a 【重要修正】帧循环是模式相关的

2026-10-30 在**离线 5V5**（非练习场，进程 pid 31232，base 0x400036a00000）
实测：

- `CoreThread` 线程**存在**（tid 31740）但**完全空闲**：
  `/proc/.../schedstat` 1 秒内 runtime/timeslices 不变；
  控制块 `0x544CBD0`（运行期 `0x40003BE4CBD0`）与 `+0xB50/+0xB58/
  +0xB70/+0xB78/+0xBD4` **全部为 0**；该局已进行 20 分钟以上，不是“还没启动”。
- 该局热线程：`UnityMain`(31454，最忙)、`UnityGfxDeviceW`(31706)、
  `NativeThread`(33216，约 5% CPU，`futex_wait`、~100 次调度/秒，
  是 worker 不是 20fps 循环)；`V8 DefaultWorker` ×3 存在；
  **没有 `AILocalThread`**。
- 对照英雄练习场（pid 8971）：`CoreThread`(9475) 与 `AILocalThread`(17216)
  同时高热。

**结论**：`CoreThread` + 条件变量是 **英雄练习场/TS 逻辑** 的帧驱动路径；
离线 5V5 不用它，帧更新走 **UnityMain（主线程内 C++/GameCore tick）**。
“每帧逻辑在 TS 里”也只对练习场路径有直接证据；5V5 是否调用
`GameCoreTS.Runtime.LogicTick` 尚未确认。后续读帧数据必须按模式分别处理。


#### 5.23.2 逻辑在 TypeScript（puerts）里，不在 C++ 里

- GameCore 的导出 `sgc_LogicTick` / `sgc_InspectorTick` 是 **libpuerts 定义**的
  （libGameCore 里是 `SHN_UNDEF` 导入）。GameCore 内唯一调用点：
  - `sgc_LogicTick` 0x245E668，调用前日志字符串
    **`GameCoreTS.Runtime.LogicTick`**（长度 0x1C，VA 0x11DE874）；
  - `sgc_InspectorTick` 0x245E72C。
- 该调用点属于一个 tick 适配函数（0x245E634）：判空 → 日志
  "GameCoreTS.Runtime.LogicTick" → `sgc_LogicTick(tsRuntime)` → 调
  `[0x4FF52F0]` 链与 `[0x50890840]`（回调/状态收尾）。
- puerts 两个导出实现很短：`sgc_LogicTick` 取 `[x0]` 后调 0xAEE4C4；
  `sgc_InspectorTick` 取 `[x0]` 后尾调 0xAEC058。
- **结论**：M5 的“每帧逻辑”主要是一份 **TypeScript 脚本**（GameCoreTS 运行时），
  原生层只负责调度和缓冲；要改/读逻辑，应优先找 puerts 的 JS 包，而不是继续
  反汇编 GameCore C++。JS 包不在 APK assets、也不在 `/data/data/.../files`
  顶层（应在 QTS 加密包内，下一步找 QTS 包）。
- GameCore 侧另有 `ModelPredictManager` 异步预测线程：两个 `std::thread`
  入口（0x26431DC / 0x274B7C0，callable 0x26430DC / 0x274B6C0），
  日志 "ModelPredictManager"、"[PredictAsync_1] thread sleep"，
  创建点分别 0x263E4D0 / 0x2745AD0。

#### 5.23.3 实测线程表（离线 5V5，pid 8971，对局中）

152 个线程；按相对 CPU 排序前 12（窗口非精确 2 s，仅作排序）：

| tid | name | 说明 |
|---:|---|---|
| 9194 | UnityMain | Unity 渲染/主循环，最忙 |
| 9475 | **CoreThread** | **GameCore 帧逻辑线程**（对局中 R，0x4882C10 循环） |
| 17216 | **AILocalThread** | 离线 5V5 本地 AI，0x46B2050 创建 |
| 9409 | UnityGfxDeviceW | Unity 图形 worker |
| 9390/9389 | Job.worker 1/0 | Unity Job System |
| 10367 | NativeThread | 对局期新建（Wwise/SDK 侧），非 CoreThread |
| 17218 | GameDumpThread | 对局期新建 |
| 10398 | AudioTrack | Wwise 音频 |
| 10600-10602 | V8 DefaultWorke ×3 | **puerts V8 worker**，开局期创建 |
| 10703 | Thread-170 | 开局期 std::thread（疑似 ModelPredict worker） |

- `CoreThread` 创建于开局加载期（进程启动后约 20 s），对局中占用很高；
  `AILocalThread` 在真正开战后创建（约 400 s），两者是离线 5V5 的主要
  非 Unity 计算线程。
- `SFNtfRunningGameCoreThreadID` 导出（0x460A4CC）写全局 `0x542A8A8`；
  本次对局该值为 **0**，说明该模式不使用“外部指定逻辑线程”的路径，
  帧逻辑由 CoreThread 自己跑。
- 产物：`_analysis/device/m5_threads.csv`（tid/name/state/age/cpu 窗口）、
  `th1..th4.txt` 原始 `/proc` 快照。
- 方法：只读 `/proc/<pid>/task/*/{comm,schedstat,stat,wchan}`，未 attach、
  未注入；对局结束后已 force-stop。

#### 5.23.4 GameCoreTS JS 包定位结果（2026-10-30，未拿到明文）

已确认“逻辑在 TS 里”，但 JS 包不在任何明文位置：

- `libpuerts` 里没有 `GameCoreTS` 字符串；metadata 里的两处 `GameCoreTS` 只是
  `USGMobileUGCLogBridge.GameCoreTSLog` 的日志名，不是模块/路径。
- APK 解包树 `apkfull/assets`（1.3 GB）按**内容**搜 `GameCoreTS`/`LogicTick`
  均 0 命中；`/data/local/tmp/gc` 下 allpkgs/ospace* 也 0 命中。
- 主资源在 `files/QtsVFSCache/packages/`：**848 个包目录、2,496 个文件、15.2 GB**，
  每包 `id/id_0.db`（数据）+ `id.db`（索引）+ `record.bytes`。
  `record.bytes` 实测 39 字节：`{u32 len, "12.1.1.26", u32 1, u32 len,
  "12.1.1.26", u32 hash}`；`117.db` 索引里是随机字符（加密/混淆），
  `117_0.db` 头 `01 00 00 02 01 02 03 04 ...`（QTS 容器），无明文路径。
- 对 <20 MB 的 699 个数据包、全部索引 `.db` 做 grep：**0 个 GameCoreTS**。
  → JS 包在 QTS 加密/压缩容器内，靠 grep 拿不到。
- 活进程 V8 堆扫描：`mem_scan` 只命中 libGameCore `.rodata` 的
  `GameCoreTS.Runtime.LogicTick`（30 次），没有 JS 堆明文；扫描期间模拟器
  因内存压力把对局进程杀掉，堆扫描结论不完整但**没有发现明文 JS**。

**结论**：要拿 GameCoreTS 源码，只有两条路：
1. 解 QTS 包（需要 QTS 的密钥/索引；5.14 的 remaindir 问题仍未解）；
2. 重装 NDK，写一个只扫 **匿名 rw/V8 堆映射** 的定向探针（不要像 `mem_scan`
   那样扫 15 GB 文件映射，正是它把进程拖死），再在离线对局里 dump V8 heap。
在此之前，M5 的“每帧数据”应从原生出口
`PushViewBuffer/CommitViewBuffer` 切入，而不是等 JS 源。

#### 5.23.5 M5 下一步

1. 用 `CoreThread` 控制块（0x544CBD0 状态 + 0x544CB58 delta）做
   **只读帧计数**：采样状态跳变即可测真实帧率，不需要 hook。
2. 每帧数据出口仍是 `PushViewBuffer/CommitViewBuffer` 的缓冲实例
   （5.22 已定位通用类与字段）；下一步在离线对局里对 8 路缓冲做
   **逐帧差分**，先找每帧变化的区段，再按玩家块切分。
3. 若必须读 TS 逻辑：重装 NDK → 定向 V8 堆探针，或解 QTS 包。

### 5.24 【交付】训练数据集 v0（2026-10-30）

由 `tools/build_dataset.py` 从 databin 块 + 25 个 `.abc` 生成，
落盘 `data/replays/_analysis/datasets/`（21 MB，`data/` 已 gitignore）：

- **静态表**：`tables_manifest.csv` 825 张；其中 **48 张**按“自然对齐布局”
  解出字段并导出 `tables_decoded/<index>_<name>.csv`（行数与 manifest 全一致）。
  布局模型：`u32 主键 + 声明顺序自然对齐`；字符串 8 字节句柄
  `{tag:offset}`，`i/dw/f=4`、`w=2`、`b=1`（个别表 bool=4，见 `layout` 列）。
  字符串句柄尚未解析成文本；777 张原生表保留原始块。
- **回放**：`replay_index.csv` 25 行、`replay_players.csv` 172 名玩家、
  `replay_kv.csv` 1,286 条 Svr2GameCore KV、
  `replay_frames.csv` **194,652 条帧记录**（seq/frame_index/offset/length/
  type_byte/tokenize_exact）。
- 回放状态：`ok` 9 个（检出 10 人）、`partial_players` 11 个（<10 人，
  可能漏检）、`old_or_unsupported` 5 个（build 3529557–4322850，旧布局）。
  5169333/5230306 构建的帧 payload 语法与 5069040 不同，
  `tokenize_exact_ratio` 可直接看出。
- **限制**：不含逐帧坐标/血量/经济/伤害；配置表字符串未解析；
  玩家块可能漏检。详见 `datasets/README.md`。
- 重建：`python data/replays/_analysis/tools/build_dataset.py`。

下一阶段（逐帧坐标/操作）在此数据集上继续：先对 `replay_frames.csv`
按 `type_byte`/标签语法分组，再解 `0x01/0x02` 的 actor+len 数据与
`compressInfo_Move` 位域。

### 5.25 逐帧动作数据 v1：0x2C 坐标命令与 0x2D 朝向（2026-10-30）

在 5069040 变体的帧 payload 里，`0x01` 英雄消息的两种子类型已解：

- **`0x01 0x2D` → 朝向/瞄准角度**：`u16 BE degree`，实测值域 **1–359**。
  - 仅本地/被记录视角 hero 发送；主样本 8,690 条，出现在 **12.5% 的帧**，
    每簇 1–10 个样本（如 238→160→158→157…），是**技能指示器方向拖动**，
    对应 C# `SetSkillIndicatorDirectionCommand { degree }`，不是移动方向。
  - 全 25 文件共 16,315 条，只在 5 个文件里出现。
- **`0x01 0x2C` → 坐标命令**：
  `subtag 0x2C + u16 type + u16 id + i32 x + i32 y + u32 seq`
  - `type` 实测：`0x0200`(812)、`0x0100`(507)、`0x0201`(61)、
    `0x0300`(58)、`0x0400`(45)、`0x0101`(28)、`0x0301`(16)、`0x0401`(1)；
    `x01` 结尾是取消（id=0xFFFF、x=y=0）。
  - 候选语义：`0x0200` 攻击位置、`0x0100` 技能指示器位置、
    `0x0400` 信号/小地图；`0x0300` 未知。
  - `id` 在 `0x0200` 里常见 8–351，包含敌方 hero id（如 338），
    像**目标 actor id**；`0x0100/0x0400` 的 id 更像技能/信号 id。
  - `seq` 每 hero 单调递增（个别跨类型乱序）。
  - 坐标范围 x∈[-54,682,55,757]、y∈[-52,761,57,659]；
    相邻命令中位跳 **7,000–20,000** 地图单位 → 这是**事件目标位置**，
    **不是**玩家连续轨迹。
- 其他事件：`0x01/0x03` 恒 `0300`（46,756 条，状态 beacon）；
  `0x01/0x23` 为 0/1 布尔（2,290 条）；`0x02/0x00` 7 字节原始（1,792 条）。
- `0x12` 2 字节标量每帧 5–6 个（66,095 条），值域 0x4040–0xA7xx，
  更像相机/视口状态而非摇杆输入，暂未纳入。

**结论**：`.abc` 只存输入/事件，**不存玩家连续位置**。因此“逐帧坐标轨迹”
不能靠解析回放得到，必须走 GameCore lockstep 模拟或服务器数据；
当前能稳定交付的是 **阵容、时间轴、瞄准方向、事件坐标、状态事件**。

产物（`datasets/`，由 `tools/build_actions.py` 生成）：
`replay_commands.csv`（1,528 条）、`replay_heading.csv`（16,315 条）、
`replay_events.csv`（50,838 条）。

汇总与图（`tools/analyze_actions.py`）：
- `actions_summary.csv`：20 个有动作数据的文件，命令/朝向/事件计数；
- `command_type_summary.csv`：54 组文件+type，坐标包围盒/唯一 id/本地占比；
- `heading_episodes.csv`：**500 个瞄准片段**（seq 间隔 >10 帧切分），
  含圆周均值、min/max 角度；
- `plots/commands_biggest.svg|png`：主样本事件坐标；
  红 0x200 攻击位置沿兵线/团战区聚集，蓝 0x100 更分散，绿 0x400 稀疏；
- `plots/heading_biggest.svg|png`：瞄准方向时间轴，短时簇发、簇内快速扫角。

玩家/aim 关联（`tools/report_actions.py`）：
- `player_actions.csv`：175 个文件+hero 画像；主样本本地玩家 442
  （李不信有归途）299 条命令、199 个瞄准片段、8,690 个朝向样本，命令 34.5 条/分。
- `aim_command_links.csv`：500 个瞄准片段中 **427 个（85.4%）**在 ±10 帧内
  找到同英雄坐标命令，**413 个同帧（96.7%）**；关联类型 `0x0200`=304、
  `0x0100`=103、`0x0400`=19。
- **id 语义修正**：命令 id 与名单英雄 id 的重合率仅 0–7%，不应解释为
  “目标英雄”；更像技能/非英雄单位 id，待进一步确认。

### 5.26 事件语义：0x02 = 技能升级（已确认）（2026-10-30）

`0x02/0x00` 的 7 字节结构：

```text
tag 0x02 | hero:u16 | flag=0x87 | len=7
data: u16 0 | actorID:u8 | slot:u8(1..4) | level:u8(0-based) | u8 0
```

全 25 文件验证：

- **1,792 条**，541 个 `(file,hero,slot)` 组；组内 level 按 seq **100% 非递减**；
- slot1/slot2 最高 level=5（6 级），slot3 最高 2（3 级），slot4 仅 16 条；
- 每英雄 14–15 条，正好对应 **6+6+3=15 个技能点**；
- `actorID` 每英雄每局恒定，不是技能 id；slot 即技能槽。

产物（`tools/build_skill_levels.py`）：

- `datasets/replay_skill_levels.csv`：1,792 条升级事件
  （file,seq,hero_id,actor_id,slot,level,level_display）；
- `datasets/skill_builds.csv`：184 个 file+hero 的最终加点；
- `datasets/skill_order.csv`：升级顺序串/first_slot/prefix3；
  首升 slot2 94 次、slot1 88 次；前三手 `121` 43、`212` 38、`211` 28、
  `123` 16、`213` 15、`122` 13。

其他事件（`datasets/event_semantics_report.md`）：

- `0x23`：0/1 布尔状态，2,290 条；与同帧坐标命令关联率 0%，语义未定；
- `0x12`：每帧 5–6 个 u16 标量（主样本 66,095 条，值 0x4000–0xA7xx），
  相邻帧差值大，不像平滑相机，语义未定；
- `0x03`：恒 `0300`，像每帧 beacon，只计数。

可视化：`datasets/plots/skill_order_442.png` 是主样本 442 的技能等级时间线
（slot1–4 分色），可直接看“先升 2、再补 1、几级学大招”的节奏。

结论：技能加点/升级顺序现在可直接从回放还原；这补上了 `datasets` 里
之前缺失的“成长过程”维度。0x23/0x12 仍保留原始数据，不做强行命名。

### 5.27 技能加点分布与队伍/区域事件压力（2026-10-30）

**技能加点**（`tools/analyze_skill_patterns.py`，`datasets/skill_patterns_report.md`）：

- 178 个 hero、184 个 file+hero 样本；绝大多数 hero 只出现 1 局，
  所以 `skill_patterns_by_hero.csv` 是“单局样本”，不是稳定习惯；
- 全局首升槽：slot2=94、slot1=88、slot4=1、slot3=1；
- 前三手：`121`=43、`212`=38、`211`=28、`123`=16、`213`=15、`122`=13；
- 跨局重复玩家仅“酒梦灵心醉”（8 局，英雄每局不同）和“丁真掏锐克”（2 局）。

**队伍/区域事件压力**（`tools/team_pressure.py`，`datasets/team_pressure_report.md`）：

- 1,422 条位置事件；unknown 163（11.5%）；team1 241、team2 1,018；
- team2 事件量是 team1 的 4.2 倍，但 team2 本地视角占 56.4%、team1 仅 11.2%
  → 不能读成压制力；
- 0x0100 偏西北（53.1%），0x0200 最分散（NW 30.0%/SE 32.6%），
  0x0400 全属 team2（45 条，NW 68.9%）；
- **队伍标签跨文件不可对齐**：146 个唯一玩家名中 143 个只出现在 1 个文件，
  2 个名字在两个 team 标签下都出现过；热图只是“文件内 team 字段聚合”，
  不是固定战队/地图侧画像。

### 5.28 选手-对局主表（2026-10-30）

`tools/build_player_profiles.py` 把名单、动作画像、技能加点合并为
`datasets/player_profiles.csv`：

- **175 行**（名单 172 + 动作-only 3），每行一个 file+hero；
- 字段：team/slot/name/is_local、commands + 分类型/取消/唯一 id、
  aim_episodes/aim_samples、events、skill_upgrades、slot1–4 最终等级、
  first_slot/prefix3；
- 覆盖：有坐标命令 23 行；有技能升级 172 行；本地/视角 7 行；
  本地行命令均值 88.3 条，非本地有命令行均值 56.9 条（样本小，仅参考）。

限制：`is_local` 是“同文件有朝向样本”的推断，不等于真实玩家/人机；
名单可能漏检；命令坐标是事件目标；命令 id 不能当目标英雄。

### 5.29 GameCore 回放模拟可行性（2026-10-30，静态方案）

完整方案见 `docs/simulation_plan.md`（450 行），配套只读自检
`tools/gc_export_map.py --check`（当前 `CHECK OK`）。核心结论：

- **宿主化可行，但 `ModuleInit` ≠ 开一局**：它只初始化 native 子系统；
  C# 侧 `GameCoreInit/StartLevel/SetGameCorePipe`、战斗上下文、CoreThread、
  8 路缓冲池都不是它的产物。只 `ModuleInit` 就 `PushCsBuffer` 会在
  空的 FIFO 对象处崩溃。
- **databin 没有导出级注入 API**：`GameDataWrapper_*`/`DT_*` 都是查询；
  `SGameSetEnableDatabinCrcFromFile` 只写 CRC 开关。原生 loader
  （0x3cd9480 / `DatabinTableBase::LoadLocalData` 0x2a36308）只把
  `0x5274280` 的源表对象复制到 `0x52742a0` 注册表再加载行，
  **不负责建表对象**。宿主路线：先自建表对象 + `0x52742a0` + `DT_*`
  验证一张表（MVSS-A），或构造源对象 + 原生 loader + `dc.db`。
- **初始化头是数据、不是命令流**：KV/443B/玩家块到 `CLevelContext/deskPool`
  的字段映射与 CSProtocol/TDR 封装仍是最大缺口（5.16.6 a/b/c）。
- **帧驱动**：输入 `PushCsBuffer/CommitCsBuffer`；推进 0x46B7888(delta)
  → `ctx+0x280`；`CommitCsBuffer` 本身不推进帧；`PushViewBuffer/
  CommitViewBuffer` 是输出状态，不是帧驱动。
- **不可用/非必需**：`DoBattleStart` 是 managed 方法（metadata 166485），
  非 native 导出；`SGC_GetPlayer*` 是 `mov w0,#11; ret` 桩；
  `SGC_Init/CreateGame/RunFrame` 不存在；`SFNtfRunningGameCoreThreadID`
  只写 0x542A8A8，离线 5V5 实测为 0，不是必需。
- **两级目标**：MVSS-A（宿主 + ModuleInit + 一张表的 `DT_*` 查询，
  需 NDK 编 E1 探针）；MVSS-B（真正逐帧模拟）被 S3 初始化命令流阻塞，
  在 S3 未解前不承诺“跑完一局”。
- 本地当前无 NDK；E0 静态自检不需要 NDK，E1/E2 需重装 r28b。

### 5.30 【E1 通过】宿主内安装假表对象并走 DT_* 读表（2026-10-30）

按 5.29 的 E1 执行单，用 NDK r28b 编了 `_host/gc_sim0.c`（只读探针，
不碰游戏进程），在 MuMu root 普通进程里跑通：

```text
base=0x1ca00000  ModuleInit -> -777077424（非零）
crc flag @base+0x542a804 = 0
registry slot @base+0x5118810 = base+0x52742a0, holder=0
installed reg[83]=fake table, vtable[+0x18]=count, [+0x20]=get
DT_Count(83) = 53
rows compared: 53, mismatches=0, row0 = 01 00 32 00
CS array @base+0x52c3250 = 0（未初始化，符合预期）
EXIT=0
```

结论：

- `DT_Count`/`DT_GetByIndex` 的契约是
  `*(0x5118810) → reg 数组 → reg[index] → table->vtable[+0x18/+0x20]`；
  宿主可以**自建表对象**并让 GameCore 的 `DT_*` 正常调用，不需要先装 QtskDB。
- 表 83（`svr2GamecoreCfg`，53 行 × 4 B）53 行与设备块逐字节一致；
  说明块文件、注册表、vtable 偏移都对。
- `ModuleInit` 后 CS 数组仍为 0，再次确认“ModuleInit ≠ 开一局”；
  本实验故意不调 `PushCsBuffer`。
- 产物：`_host/gc_sim0.c`、设备二进制 `/data/local/tmp/gc/gc_sim0`、
  日志 `device/e1_gc_sim0.log`。

下一步 E1b：把 825 张表的块全部注册成假表对象，逐表 `DT_Count` +
抽样 `DT_GetByIndex` 校验，验证“宿主可读全量 databin”的契约。

### 5.31 【E1b 通过】宿主内注册并校验全部 825 张 databin 表（2026-10-30）

`_host/gc_sim0b.c` 在 `ModuleInit` 后扫描 `dtab_blocks/`，为每个
`<index>_<name>.bytes.bin` 建宿主假表对象（vtable 共享，
`+0x18`=count、`+0x20`=get_by_index），安装到 `reg[index]`，
再逐表调用 GameCore 的 `DT_Count`/`DT_GetByIndex`：

```text
installed=825 skipped=0 dup=0
RESULT installed=825 verified=825 count_bad=0 row_bad=0 total_rows=205149
DT_Count(0)=35   (41)=259  (83)=53  (108)=27663
DT_Count(134)=270 (256)=14286 (754)=9999
CS array @base+0x52c3250 = 0x0
EXIT=0
```

- 每张表校验 `count == block.rows`，并抽样第 0、mid、last 行与块内
  `0x98 + i*stride` 逐字节比较，**825/825 全部通过，0 mismatch**。
- 覆盖 205,149 行（与 M2 导出的总行数一致），核心表计数与 manifest 一致。
- 这说明“宿主把 825 张表注册进 GameCore 的 `DT_*` 路径”已成立；
  **MVSS-A 的数据契约完成**。仍不是“开一局”：CS 数组/战斗上下文仍为 0，
  S3 初始化命令流（KV/443B/玩家块 → CLevelContext/TDR）尚未打通。
- 产物：`_host/gc_sim0b.c`、设备二进制 `/data/local/tmp/gc/gc_sim0b`、
  日志 `device/e1b_gc_sim0b.log`。

E1b 的意义：不必先解决 QtskDB/`STDBTableEnv`，宿主已能把全量 databin
交给 GameCore 的查询层；下一步若要真实模拟，焦点回到 S3（初始化命令流），
而不是 databin 装载本身。

### 5.32 语料扩充：27 个 `.abc` + 41 个 `.ope` 索引（2026-10-30）

- 把本地多出的 2 个 `.abc`（`20261028_135516`、`20261028_135520`）纳入批量，
  `replay_index` 从 25 → **27**；两者都是 68 KB 旧构建，玩家块/帧流解析器
  不适用，因此动作/技能数据不变：帧记录仍 **194,652**，KV 从 1,286 → **1,392**，
  玩家 172。状态：9 ok、11 partial_players、7 old_or_unsupported。
- 新增 `datasets/ope_index.csv`：**41 个 `.ope`** 的容器/头部元数据，
  全部可解且 `localTime` 齐全；客户端版本 23×12.1.1.1、11×11.4.1.1、
  7×11.4.1.36。账号只保留首尾 4 位（脱敏）。旧格式 40/41 的
  `lengthMatches=0`（0x86 处是 `0x80000000` 哨兵），不代表解包失败。
- 新增 `datasets/replay_meta.csv`：按文件名时间戳把 **21/27** 个 `.abc`
  与 `.ope` 关联，补上设备/账号/本地时间/构建；设备 20×Xiaomi 25053RT47C、
  1×Vivo V2546A。6 个 `.abc` 无对应 `.ope`。
- 尝试再抓“未加载的 130 张表”：重启游戏并点离线入口时，隐私协议弹窗
  重新出现，同意後登录页不再显示“离线5V5”入口（缓存登录态被重置）；
  未尝试登录。因此本次没有新增 databin 表，**825 张仍是离线可拿到的完整集**。
- `.ope` 内层操作流仍有 LZ 压缩层（主样本 blob 头 `3f 05 fd…`，
  不是可直接 anchor 的 27 字节流头），所以没有批量解出 41 个 `.ope` 的
  事件流；`ope_decoded.bin` 只是旧样本的单文件产物。

### 5.33 离线 5V5 活进程复核：无隐藏表，缓冲已初始化但未解（2026-10-30）

用户进入离线 5V5 后（pid 9457，base 0x400036a00000）只读复核：

- `mem_databin`：955 个有路径对象，**825 张 rows>0，130 张 rows=0**；
  与既有 `dtab_blocks` 完全一致，无新表、无行数变化。
- 新写 `_host/mem_hdr.c` 逐表比较“对象 rows”与“DB 头 rows”：
  **130 张空表的对象 rows 和 DB 头 rows 全部为 0**，没有“表头有行但对象没加载”
  的隐藏数据。→ 825 张就是离线模式能拿到的完整集。
- 8 路缓冲数组本次已初始化（`0x40003bcc3250`）：
  - array[0] 同时是 view manager（`ctx+0x2b0`），cap 0x8000；
  - array[1] cap 0x20000；array[2] 空闲；3–7 是其他结构。
  - 两次快照（间隔 1 s）差异只集中在头部（obj0 8 B、obj1 38 B），
    不是滚动状态流；按游标定位的 obj0 区域是一张 `01 01 02 03…2d…`
    正弦查表，obj1 区域为 0。→ 缓冲已活，但帧格式未解，不能发布为状态数据。
- 产物：`device/live_5v5_20261030/`（注册表/表头/8 对象/两套缓冲快照 + README）。
- 另启动 8 分钟后台监视：若这局结束生成新的 AutoSave `.abc/.ope`，会自动
  拉到 `samples/live_20261030/`；当前 AutoSave 仍只有 20261028 的旧文件。
- 两次监视（8 分钟 + 10 分钟）均未出现新文件，游戏进程仍在离线对局中；
  结合 68 KB 旧样本只有 1 个本地玩家名、无完整 10 人块，**判断离线 5V5
  不产出可用回放**，不要再等 AutoSave。

### 5.34 S3a：初始化标量块逐字段表（2026-10-30）

把 12 个可解析样本的 443 B 区域按 modeWord 拆组，输出
`datasets/init_header_fields_5v5.csv` / `_alt.csv` + `init_header_report.md`：

- **5v5 组**：8 个标准样本、110 个 BE u32；**95 个常量、15 个变量**。
  - 变量 index：1（modeWord，两值 89,497,376/88,448,288）、67（Unix 时间，
    8 个样本各不同）、58/83/85/86/87/97/98/99/100/106/107/108/109
    （多为位域/模式参数，未命名）。
  - 常量锚点：0, 300, 1000, 7, 5, 2, 10, 66, 32, 32, 2, 15, 0, 0, 15, 15,
    4, 300, 15, 15, 100, 0, 200, 8, 300, 0, 120, 200, 300, 120…（未命名）。
- **alt 组**：4 个样本、109 个 u32，105 常量/4 变量；index2=0、modeWord=6176，
  不能与 5v5 混用。
- 字段名映射的难点：`CLevelContext`/`ResDT_LevelCommonInfo` 的 C# 声明顺序
  与块内顺序不一致，不能按字段表直接套；下一步需要原生 context 偏移或
  字段默认值对拍。活进程 context 指针在本次检查时已被释放（holder=0），
  无法现场 dump。

### 5.35 S3a/S3b 执行记录：命名受阻，Push 通、Commit 崩（2026-10-30）

**S3a 续（字段命名）**：三条路都没给出可靠名字：

- metadata `fieldDefaultValues`：CLevelContext 只有 2 个非零默认值，且读出的
  u32 明显不是字段值（指向共享 blob），不能用于对拍；
- `Level.bytes` 行：656 B 行内是 600/1/4 等值，没有 443 B 块的
  300/1000/7/5 组合，说明块不是 Level 行；
- 活进程匿名堆扫描：`_host/mem_seq.c` 在 pid 9457 的匿名可读映射里搜
  300,1000,7,5 / 66,1000,32,32 等序列，**0 命中**；context 指针已释放。
- 因此 `init_header_fields_5v5.csv` 仍是“常量/变量分类表”，15 个变量
  只能判定为位域/模式参数，不能命名。

**S3b（宿主 CS 缓冲）**：`_host/gc_fifo0.c` 直接把宿主假缓冲装进
`[0x4ff5de8] → [0x52488b8] → array[0]`：

```text
PushCsBuffer(64) -> 宿主 data 指针，obj.len=64   ← 成功
CommitCsBuffer()  -> SIGSEGV                      ← 仍崩
```

- Push 成功说明 `PushCsBuffer` 只读 `+0x18`(data)/`+0x20`(cap)/`+0x24`(len)，
  宿主对象契约可满足；
- Commit 崩说明它还需要别的字段/对象状态；另外 0x43D301C 反汇编显示它是
  **引用计数/弱引用赋值助手**（读写 +0x48/+0x50/+0xa8/+0xb0），不是
  5.29 里假设的“上下文安装器”。S3b 不能靠直接调它完成。
- 日志：`device/s3b_gc_fifo0.log`。

**下一步**：先在宿主里打印 `CommitCsBuffer` 的真实槽目标与对象字段
（或从 `PushCsBuffer` 成功路径反推 Commit 需要的 +0x3c/锁/回调），再决定
是否需要真实 context；S3a 需要下一次离线对局时第一时间 dump context
（holder 非 0 的窗口）或反汇编 CLevelContext 构造函数。

**S3b 二轮（2026-10-30）**：已按上述做，结果：

- 打印运行期：Commit 跳板槽 = 0x460A3E4，内部目标 = 0x49CC18C；
  Push 后 holder/arr[0]/obj 均正确；
- 补了 `+0x10=0x1000` 和 `+0x3C` pthread mutex 后，直接调用
  `0x49CC18C(obj)` 成功；
- 但走 `CommitCsBuffer` 仍 **SIGSEGV**：`si_addr=0x10`、pc=0x460A3F8，
  寄存器显示 `x0=obj, x8=0`。故障形态像“把 x0 当对象、读空 vtable/首字段
  后 +0x10”，说明 Commit 跳板/对象契约仍不对，或该槽目标不是最终 Commit
  实现。日志：`device/s3b_gc_fifo0.log`。
- 结论：Push 契约已成立；Commit 需要继续定位真实实现（不是简单补
  +0x3C 锁），下一步应把 0x460A3E4 的跳板链和 0x49CC18C 的调用约定逐条
  对清，或从 `PushCsBuffer` 成功路径反推同族对象的完整 vtable。

### 5.36 原生回放路线复核：先隔离不一致的证据（2026-10-30）

本轮只读取现有文件，不加载游戏库，不连接设备。新增可重复检查：
`python tools/replay_evidence_check.py --check`。当前退出码为 1，表示历史快照
不能用于验证当前 metadata 的方法索引，不代表回放文件损坏。

**直接观测**：

- 当前 `global-metadata.dat` 有 416,645 个方法、64,125 个类型；
  `runtime_dump/metadata_mem.bin` 有 416,815 个方法，metadata 表头也不同。
  即使允许快照末尾有页填充，两者有效内容仍不相同。仅凭这些差异不能确定
  各文件的具体游戏构建，但不能将两套方法索引混用。
- ELF 可执行 PT_LOAD 声明 `p_vaddr=0x3a84a40`、`p_offset=0x3a83a40`，
  差为 0x1000。这是文件段映射，不等于已证明运行时所有代码页均遵循它。
- 按历史标签 `VA=0x5976000` 比较 `code_blob.bin`：前四页在
  `VA−0x51000` 位置均可用 XOR 0xE3 匹配，每页 1024/1024 个字；
  第五页却在 `VA−0x1000` 位置原样匹配 1024/1024 个字。
  因此不能把 0x51000 用作全局偏移，也不能把第五页不符合该映射直接归因于换密钥。
- `code_5977000.bin` 两页在 `VA−0x51000` 加 XOR 0xE3 下同样完全匹配。
  两个历史代码块有重叠，不能视为两份独立采集的构建身份验证。

**当前 metadata 确认的追踪线索（不附未经验证的方法地址）**：

- `GameReplayModule.BeginReplay(path, checkVersion)`，方法索引 228003；
- `GetBeginLoadMsg(isAbc, checkVersion, br)` / `(abxFullPath)`，228009/228010；
- `RetriveBeginLoad(replayFilePath)` / 含 startPos、length、csPkg 的重载，228037/228038；
- `SGW.StartHostReplay(abhPath)`，166994；`PureReplayStart(...)`，166676。

这些名称支持优先追踪现有文件读取/开局恢复入口，但不证明调用顺序、协议格式、
`.abh` 是否必需、或是否有账号校验。方法数量和单调地址也不能单独证明
全局方法索引与代码槽的一一对应。所有恢复出的调用边必须在相同来源和已校准映射下验证，
不能以 ARM64 可解码率代替方法身份验证。

**路线决定**：先校准当前样本的读取器入口与代码身份，再追 BeginLoad 的实际消费链。
本轮未还原 BeginLoad 的方法体、未构造 context、未推进任何战斗帧；原生回放复用仍是
待验证路线，不能宣称已打通。现有 ELF/metadata/历史代码快照均保留，不修改任何样本。

### 5.36 回放组成复核：第二段 712 帧与尾部 entity/评分表（2026-10-30）

> 后续修正（5.105c/R2）：尾部次值是 **本局评分×100**，不是皮肤 ID；
> 本节保留历史过程，`hero_skin_pairs` 列名是历史误称。

本轮按“不能只凭文件像命令流就断定全是输入”的要求，重新逐段核对 `.abc`。
发现两处此前数据集未覆盖的结构；结论不是“有结算数据”，而是**主帧流之后
还有一段输入续流 + 一张英雄/皮肤名单**。

**（a）第二段帧流（仅主样本 20260925_105224）**

- 主帧流结束于 seq 13094、文件偏移 0x9B0F0；其后 26,178 B 不是纯尾部。
- 在 tail+277 找到第二段帧头，seq **13096–13807，共 712 帧**，逐帧 seq 连续。
- 帧头语法与主段相同：`frame:u16BE, len:u16BE, type:u8, payload[len], 5B trailer`。
- 但 payload **没有主段的 count 前缀**，直接从 `0x12/0x13/0x14/0x01/0x02` 标签开始；
  按无 count 语法解析出 **624 条英雄消息**：
  - `0x01/0x2d` 朝向 408 条；
  - `0x01/0x2c` 坐标命令 23 条；
  - `0x01/0x03`、`0x01/0x23`、`0x02` 等事件 181 条；
  - 其余为 `0x12`（2,619 个）与 `0x13`（640 个）标量。
- 没有 10 人血量/经济/伤害/位置状态；它是**输入续流**，不是状态快照。
- 该样本主段 13,062 帧 + 第二段 712 帧 = **13,774 帧**；第二段相当于主段的 5.45%（占该样本全部帧的 5.17%）。
- 其他 19 个可解析样本尾部只有 102/106 B，没有第二段；旧格式样本的
  大尾部不参与该判定（已排除 seq 55 的误检）。

**（b）尾部英雄/皮肤名单（102/106 B，20 个样本）**

> **已修正（见 5.90）**：每对首值是 entityID（块 `+0x06`），
> 不是 heroID；次值是每局变化的未解编码，不是 skinID。尾部
> 名单不是 heroID:skinID 交替表。

布局（按 4 B 步长读 u16BE + 0 pad）：

```text
+0x00  16 B 头（8 个 u16BE；首值随对局变化）
+0x10   4 B 额外值（u16BE + 0 pad）
+0x14  10 槽 × 2 个 4 B 值：heroID, skinID 交替
+0x64   4 B 本地槽位（106 B 样本为 1）
+0x68   2 B 本地英雄 ID（106 B 样本）
```

- 20 个样本的 `heroID:skinID` 对完整覆盖玩家块名单；玩家块只解出 2/8/9 人的样本，
  尾部还能补出 **AI 英雄 2001–2008**。
- 例：`20260807` = `1367:970 1976:730 455:810 814:820 1879:1060 2228:820
  573:710 2288:500 1578:990 1198:540`，本地 `1:814`。
- 102 B 样本没有本地槽位字段，最后 2 B 为 0；106 B 样本有 `local_slot=1`。
- 这些值是英雄/皮肤 ID，不是金币、伤害、KDA 或结算；**不能当战绩表**。
- 主样本尾部同样结构；其帧流末尾多出的 1 字节 `0x04` 属于末帧类型/尾包，
  去掉后正好是 106 B 名单（`replay_tail_roster.csv` 已按此对齐）。

**（c）数据集修正**

| 数据 | 原数据集 | 第二段补充 | 合计 |
|---|---:|---:|---:|
| 帧 | 194,652 | 712 | 195,364 |
| 命令（0x2c） | 1,528 | 23 | 1,551 |
| 朝向（0x2d） | 16,315 | 408 | 16,723 |
| 事件 | 50,838 | 181 | 51,019 |
| 英雄/皮肤名单 | 未建 | 20 样本 | `replay_tail_roster.csv` |

- 新工具：`tools/abc_tail_frames.py`、`tools/abc_tail_roster.py`；
- 新数据：`datasets/replay_tail_frames.csv`、`replay_tail_actions.csv`、
  `replay_tail_commands.csv`、`replay_tail_heading.csv`、
  `replay_tail_events.csv`、`replay_tail_roster.csv`、`replay_tail_summary.csv`；
- 完整证据分级与宿主验收门槛见 `docs/evidence_audit.md`。

**（d）对旧结论的修正**

- 5.13.9/5.14 的“回放只有输入、没有战绩”方向仍成立；但不能说“所有数据都必须
  靠模拟产生”——第二段和尾部名单是不需要模拟的**输入/名单数据**，只是此前漏了。
- 5.13.11 的“击杀事件是录制的”已在 5.14.1 下调；本轮再次确认：
  `BattleNotifyReplayTool` 不能作为运行时回放证据。
- 5.35 的“0x43D301C 是上下文安装器”已被推翻，宿主路线不能按旧假设继续。

### 5.37 方法绑定复核：旧全局表公式被否定，改从导出追真实解析器（2026-10-30）

只读复现：`python tools/il2cpp_method_map_check.py --check`，当前返回 1，
表示旧映射公式被拒绝；`python tools/il2cpp_runtime_layout.py` 当前返回 0。

**旧公式的直接反例**：

- 假设起点 0xd380ce0，按 metadata 方法索引逐个取 8 B；先保留原始值，再物化
  ELF 的 R_AARCH64_RELATIVE。前 35 槽中有 20 个非零值不属于可执行 PT_LOAD。
- index 7/11/15 分别是 0x100000000/0x200000000/0x300000000；
  index 17/18 是 0xd275570/0xd2a0db8，均不是当前 ELF 可执行段中的函数入口。
  旧 resolve_methods.py 将未重定位槽直接视为 0，会把原始整数隐藏成“空方法”。
- metadata 的 9,853 个 abstract 方法中，有 9,706 个对应槽非零；早期接口方法
  对应槽甚至是 0x8000800080008000 等整数。这些值不能作为直接代码地址。
- 在 index 416645 之后再检查 1,000 槽，999 个值仍指向可执行段。
  所谓“恰好 416,645 槽”并不是独立测得的数组边界，而是旧工具取 metadata
  方法数作为读取上限。指针区继续延伸单独不能否定子数组，但前面的无效槽已构成反例。

因此，旧 `kpl_i2cpp.addr`、`addr2method.json` 以及由它派生的 SGW/GameReplayModule
方法地址和调用注释均降为未验证候选；不能因代码可解码或地址单调就恢复其可信度。
这不否定已有按导出名定位的 libGameCore 实验，也没有否定 metadata 中的方法名/参数名。

**从当前 ELF 具名导出得到的新锚点**：

- `il2cpp_class_get_methods` 0x3aa3ee8 的直接 BL 指向 0x3ad109c；
  它通过 class+0x98 取方法数组、class+0x120 的 u16 取数量。
- `il2cpp_class_get_method_from_name` 0x3aa3ef8 → 0x3ad1248 → 0x3ad125c；
  匹配代码读取 MethodInfo+0x18 的名称、+0x52 的参数数量。
- 具名 getter 的完整 load+ret 独立确认：MethodInfo.name +0x18、declaring_class +0x20、
  token +0x48、parameter_count +0x52；Il2CppClass.image +0、name +0x10、namespace +0x18。
  自动检查要求导出只有一个直接 BL，且目标确实为取字段再返回，不使用旧符号缓存。
- 沿方法数组初始化调用链追到 0x3ad3788：该函数通过 0x3ae9344 的结果填写
  MethodInfo 首字段；调用参数来自所属 class 的 image 和方法描述的 token。
  0x3ae9344 的代码映射尚未核准，本轮没有给它强行命名，也未获得最终方法入口。

**边界**：旧快照没有因此变成当前库的匹配快照；用当前布局对旧 dump 做带范围约束的
候选扫描未得到可确认记录，不能推出运行时不存在对象。原生 `.abc` BeginLoad 读取器
仍未还原；下一步应沿具名导出可追到的真实方法指针解析路径继续校准，停止使用旧全局索引公式。

### 5.38 方法指针链的闭环边界：EH frame/ABI 出现矛盾（2026-10-30 续）

继续沿 `0x3ad3788 → 0x3ae9344 → 0xba755c0` 追 `methodPointer`，出现一个
不能忽略的矛盾；本轮**不**把这条链认定为已闭环的解析器。

**（a）旧映射的独立反例**

- `addr2method.json` 把 `System.String::get_Length` 标到 0x7491e5c；
  该地址字节是 `fd 7b bd a9…`（`stp x29,x30,[sp,#-0x30]!` 一类序言），
  不是 `ldr w0,[x0,#0x10]; ret`。旧映射连这个基础 getter 都不对。
- 这再次确认：旧 `.data` 表不能按 metadata 索引取方法；旧地址派生的
  SGW/GameReplayModule 结论只能当未验证候选。

**（b）新锚点本身是有效的**

- `0x3ad3788` 是 EH FDE 起点（range 0x158），代码形态符合 MethodInfo 构造：
  `+0x18` name、`+0x20` declaring_class、`+0x30` 参数数组、`+0x48` token、
  `+0x52` param_count；它调用 `0x3ae9344` 的结果写入 MethodInfo+0。
- `0x3ae9344` 在 EH frame 里是独立 FDE 起点（range 0x24），有 3 个 BL 调用点：
  0x3ad37b4、0x3adeca4、0x503b1d0。
- 0x503b1d0 的形态很像“取方法指针”：`x0 = [[MethodInfo+0x20]]`（class→image）、
  `w1 = [MethodInfo+0x48]`（token）、`bl 0x3ae9344`，结果非零则用结果，
  否则回退到 `[MethodInfo]`。这说明 0x3ae9344 **很可能**是方法指针解析片段。

**（c）但静态 ABI 对不上**

- 0x3ae9344 的前 9 条指令使用 `x8/x19/x20/x21`，**完全不读 x0/x1**；
  它把 x8 掩码后乘以 0x18，`x21 = x8*0x18 + 0x18`，再以
  `x0=x19, w1=0, x2=x21` 调 `0xba755c0`。这更像 memset/vector 片段，
  而不是“image+token → code pointer”。
- `0xba755c0` 在 EH frame 中位于更大的 FDE 0xba75588 内；它的代码使用
  `x21` 作为指针（`ldr x25,[x21,#0x28]!`），而 0x3ae9344 传给它的 x21 是
  一个大小值。按正常 ARM64 ABI，这个调用不可能成立。
- 可能原因只有三类：编译器自定义内部 ABI/函数切分；静态文件被运行时
  解密/补丁，当前字节不是最终代码；或 XOR-DP 解码在该页选错了 key。
  无论哪一类，都不能把 0x3ae9344 的静态字节当成可信的 resolver 实现。

**（d）下一步的硬要求**

在拿到 **ground truth** 之前，停止用这条链给 SGW/GameReplayModule 定地址。
Ground truth 至少要有一种：

1. 已知方法的实际代码地址（例如从已知 getter 代码模式反查），并用它验证
   `MethodInfo.methodPointer` 的结果；
2. 运行时 `MethodInfo` 对象（只读、合规环境）读出 +0x18/+0x20/+0x48/+0x52，
   与 metadata 对拍；
3. 找到真正的 code registration/method pointer 表，而不是旧 `.data` 表。

如果三者都拿不到，就应停在这条分支：继续静态猜 resolver 只会产生
“看起来像方法入口”的第二个错误映射。

### 5.39 `.rodata` 的 `(code_address, method_index)` 表：候选 thunk 表（2026-10-30 续）

继续扫描 `.rodata/.data` 的 8 B 对齐对，找到一组**比旧 `.data` 表更可信、但仍不是最终方法体**的表：

- 结构是 `{u32 code_address, u32 method_index}`；地址落在 `.text`，索引在 metadata
  方法范围内，同一块内索引连续、地址递增。
- 全量扫描：**296,684 对，覆盖 295,183 个方法索引（70.8% / 416,645）**，
  1,501 个重复索引；有 983 段连续 run，常见 6,144 项一块（0x3000 B）。
- 类聚簇很明显：
  - `SGW` 166,627–167,206：555/580 命中，地址从 `0xc6b3270` 到 `0xc6b4fd8`；
  - `GameReplayModule` 227,947–228,050：72/104 命中，地址从 `0xc1b6470` 到 `0xc1b6c10`。
- 已知点：
  - `SGW::StartHostReplay` 166,994 → `0xc6b4020`（在 FDE `0xc6b3ee8` 内）；
  - `GameReplayModule::BeginReplay` 228,003 → `0xc1b68a0`（在 FDE `0xc1b6874` 内）；
  - `System.String::get_Length` 281,771 → `0xc217aa8`，但该地址是复杂字符串函数，
    **不是** `ldr w0,[x0,#0x10]; ret`。

**解释**：这更像**方法索引 → thunk/内部标签**表（或符号化表），不是直接方法体表。
SGW/GameReplay 的地址聚簇说明它确实与这些类相关，但 `String.get_Length` 的反例
说明不能把每个条目都当方法入口。条目可能指向共享 thunk、metadata 初始化桩或
代码范围标签；需要 ground truth 才能升级为“方法入口表”。

FDE 统计进一步支持这一点：SGW 的 555 个命中方法只落在 **42 个 FDE**，
GameReplayModule 的 72 个命中只落在 **9 个 FDE**；不是“一方法一函数”，
而是多个方法共享函数/入口标签。把已知 getter 字节模式与 pair 表地址求交集，
632 个 getter 命中里只有 5 个正好是表项，也不足以证明“表项=方法体”。

另外，直接读这些地址的 u64（含 RELA）得到的是加密代码字节，不是代码指针；
所以它们不是“指向方法指针的槽”，而是代码区里的标签/桩。

**跟 thunk 的候选结果**：

- `StartHostReplay` thunk `0xc6b4020` 读全局 `0xd861098`（RELA → `0xc2074f4`）；
  `0xc2074f4` 是一个真实函数序言，写 `[this+0x58]`，并以 path 形参调用
  `[0xd861050]`；**候选**是 StartHostReplay 的真实 wrapper，但未用运行时验证。
- `BeginReplay` thunk `0xc1b68a0` 所在函数 `0xc1b6874` 写 `[this+0x98]`、
  `[this+0x80]`、`[this+0x28]`、`[this+0x78]`，并调用 getter；**候选**是
  BeginReplay 的真实函数，但同样未验证。

**结论**：这是目前最接近“真实方法表”的静态线索，但还不是 ground truth。
下一步应拿一个已知方法（如 getter 的实际代码模式）验证该表条目到底指向
方法体、thunk 还是代码范围；在验证前，不用它给 SGW/GameReplay 下结论。
复现：`python tools/il2cpp_pair_table_probe.py`。

### 5.40 独立 IL2CPP 宿主取 MethodInfo：MuMu/houdini 不可用（2026-10-31）

为了拿 ground truth，试了“不注入游戏、独立进程加载 libil2cpp”的路线：

- `libil2cpp.so` 的 `DT_NEEDED` 只有 `liblog/libandroid/libm/libdl/libc/libstdc++/libtprt`；
  未定义符号里只有 `g_tprt_pfn_array`、`g_tprt_ori_array` 来自 libtprt。
- 导出包含 `il2cpp_init`、`il2cpp_domain_get`、`il2cpp_domain_assembly_open`、
  `il2cpp_class_from_name`、`il2cpp_class_get_method_from_name`、
  `il2cpp_method_get_name/token/class`。
- 已写 `_host/il2cpp_probe.c`，设置 `il2cpp_set_data_dir` 后调用 `il2cpp_init`，
  枚举 Assembly-CSharp，找 SGW/GameReplayModule，读 `MethodInfo+0/+0x18/+0x20/+0x48/+0x52`。
- 设备：MuMu Android 15 x86_64 + libhoudini；metadata 放在
  `/data/local/tmp/il2cpp/data/bin/Data/Managed/Metadata/global-metadata.dat`。

结果：

| 方式 | 结果 |
|---|---|
| 先 dlopen libtprt，再 dlopen libil2cpp | `dlopen libil2cpp` 卡住（>30 s），adb shell 被拖死 |
| 不加载 libtprt，提供 `g_tprt_*` 空桩/ret 桩，`RTLD_LAZY` | `dlopen libil2cpp` 约 2 s 后 **SIGILL**，EXIT=132 |
| logcat | `Fatal signal 4 (SIGILL) ... /system/lib64/libhoudini.so`；进程由 `houdini64` 执行 |

结论：**当前 MuMu 的 x86_64 + houdini 不能作为独立 IL2CPP 宿主**。
SIGILL 发生在 houdini 翻译层，不是方法映射结论；libil2cpp 在游戏进程里能跑，
是因为 Unity/游戏启动链和 houdini 的集成不同，不代表独立 dlopen 可用。

**获取 ground truth 的可行路径（按推荐度）**：

1. **ARM64 原生 Android 设备/环境**（真机或 ARM64 系统镜像）跑同一个
   `il2cpp_probe`：加载 libil2cpp + metadata，直接读 `MethodInfo.methodPointer`；
   不需要登录，不需要注入游戏。
2. **合规的运行时 MethodInfo dump**：在授权环境里对同一构建做只读 dump，
   读 `MethodInfo+0/+0x18/+0x20/+0x48/+0x52`；当前无安全账号，不做。
3. **官方/调试符号**：检查 APK/符号包里的 `LineNumberMappings.json`、`.sym.so`、
   `symbols.zip`；当前 APK 未发现。
4. **静态 code registration**：继续找真正的 method pointer 表；pair 表目前只是
   thunk/标签候选，不能当 ground truth。

产物：`_host/il2cpp_probe.c`、`_host/il2cpp_probe`、设备
`/data/local/tmp/il2cpp/`（libil2cpp、libtprt、metadata、probe.log）。
复现前需先确认设备是 ARM64 原生，不要在 MuMu/houdini 上重复 SIGILL。

### 5.41 【突破】离线 5v5 只读内存拿到真实 MethodInfo / methodPointer（2026-10-31）

没有登录、没有注入、没有调用游戏函数；只在离线 5v5 的活进程上用 root
`/proc/<pid>/mem` 做只读 dump，然后按 token/name 找 `MethodInfo`。

**方法**：

1. 进入离线 5v5（英雄练习场即可），pid=7797；root adb 读
   `/proc/7797/maps`，确认 libil2cpp 与 metadata 映射；
2. `mem_dump` 只读 dump metadata + libil2cpp 的 4 个 rw 区；
3. `mem_scan_method` 遍历所有 `rw-p` 区域，按 method token 找
   `MethodInfo+0x48`，再按 `+0x18` name 指针回 metadata 解名字、核对 `+0x52` 参数数；
4. 用 `MethodInfo+0` 取 methodPointer；用进程 maps 把指针换成
   libil2cpp 文件偏移（code 段 `static VA = file offset + 0x1000`）。

> 注意：`mem_dump` 用 `atol` 解析长度，`0x10b000` 会被当成 0；
> 必须传十进制长度，否则会写出 0 字节。

**已确认的 ground truth（当前构建 5069040/12.1.1.8）**：

| 方法 | token | params | process methodPointer | static VA |
|---|---|---:|---:|---:|
| `SGW::GameCoreInit` | 0x6001502 | 0 | 0x40002b5b4938 | 0x53b4938 |
| `SGW::StartLevel` | 0x600150f | 6 | 0x40002b5b5798 | 0x53b5798 |
| `SGW::SetupClient` | 0x6001510 | 4 | 0x40002b5b5960 | 0x53b5960 |
| `SGW::BeginLoad` | 0x6001513 | 1 | 0x40002b5b5d28 | 0x53b5d28 |
| `SGW::AsyncBeginLoad` | 0x6001514 | 2 | 0x40002b5b5e5c | 0x53b5e5c |
| `SGW::PureReplayStart` | 0x6001516 | 7 | 0x40002b5b5fdc | 0x53b5fdc |
| `SGW::StartHostReplay` | 0x6001654 | 1 | 0x40002b5ce9d4 | 0x53ce9d4 |
| `GameReplayModule::PureReplayLogic` | 0x6002b60 | 3 | 0x40002c856d8c | 0x6656d8c |
| `GameReplayModule::BeginReplay` | 0x6002b68 | 2 | 0x40002c85a23c | 0x665a23c |
| `GameReplayModule::CheckReplayVersion` | 0x6002b6b | 2 | 0x40002c85a950 | 0x665a950 |
| `GameReplayModule::SkipReadReplayHead` | 0x6002b6c | 4 | 0x40002c85aa14 | 0x665aa14 |
| `GameReplayModule::SkipReadReplayHead` | 0x6002b6d | 3 | 0x40002c85afe0 | 0x665afe0 |
| `GameReplayModule::GetBeginLoadMsg` | 0x6002b6e | 3 | 0x40002c85b07c | 0x665b07c |
| `GameReplayModule::GetBeginLoadMsg` | 0x6002b6f | 1 | 0x40002c85b42c | 0x665b42c |
| `GameReplayModule::UpdateFrame` | 0x6002b70 | 0 | 0x40002c85b4c0 | 0x665b4c0 |
| `GameReplayModule::SendReplayFinish` | 0x6002b7a | 0 | 0x40002c85c50c | 0x665c50c |
| `GameReplayModule::DirectHandleMsg` | 0x6002b86 | 1 | 0x40002c85d8e4 | 0x665d8e4 |
| `GameReplayModule::HandleMsg` | 0x6002b87 | 1 | 0x40002c85da78 | 0x665da78 |
| `GameReplayModule::BattleStart` | 0x6002b88 | 0 | 0x40002c85dd00 | 0x665dd00 |
| `GameReplayModule::RetriveBeginLoad` | 0x6002b8a | 1 | 0x40002c85e164 | 0x665e164 |
| `GameReplayModule::RetriveBeginLoad` | 0x6002b8b | 4 | 0x40002c85e1f0 | 0x665e1f0 |

每条记录的 name 指针都能回 metadata 解出对应方法名，参数数与 metadata 完全一致；
因此这不是旧 `addr2method` 或 pair 表推测，而是 **MethodInfo+0 的直接读数**。

**直接反汇编确认**：

- `StartHostReplay` static `0x53ce9d4`：真实函数序言，参数 `x0=this, x1=abhPath`；
  检查 GameReplayModule 状态，取 path 长度，构造 `0x14c` 消息并调用
  GameReplayModule 相关槽；是真正的回放入口。
- `BeginReplay` static `0x665a23c`：真实函数序言，参数 `x0=this, x1=path, w2=checkVersion`；
  先做 path 存在性检查，设置 `[this+0x18] = !checkVersion`，用两个全局字符串
  检查扩展名并写 `[this+0x12]/[this+0x13]`（对应 `.abc`/`.abf` 标记），
  把 path 存到 `[this+0xb8]`，再打开 `[this+0x78]/[this+0x80]` 流。
- 旧 pair 表候选（StartHostReplay 0xc6b4020、BeginReplay 0xc1b68a0）
  **不是 methodPointer**；pair 表是 thunk/共享入口标签表，已确认不能当方法地址。

**产物**：

- `device/live2_maps.txt`（pid 7797 maps）
- `device/live2_mem/metadata.bin`、`bss1..4.bin`
- `device/live2_mem/scan_tokens.log`、`scan_replay.log`
- `_host/mem_scan_method.c`、`_host/mem_dump`（只读）
- `datasets/replay_method_map.csv`（27 条真实方法地址，含 DoBattleStart/FlushGameCoreFifo/GameCoreUpdate）

下一步：沿 `StartHostReplay → BeginReplay → GetBeginLoadMsg/UpdateFrame` 的真实代码，
定位 `.abc` 的打开、版本检查、BeginLoad 消息和送帧路径；这不再需要猜方法地址。

### 5.42 `.abc` 打开/版本/BeginLoad/送帧链（真实代码，2026-10-31）

以下全部基于 5.41 的 ground-truth methodPointer；地址为 libil2cpp 静态 VA。
**已验证**：函数边界、调用目标、字段写入；**推断**：部分字段名和消息 ID 语义。

**（a）`BeginReplay`：文件打开**

`GameReplayModule::BeginReplay` static `0x665a23c`，签名 `(this, path, checkVersion)`：

1. `File.Exists(path)`：槽 `0xd860400` → helper `0xc1ed4c8`；失败走错误日志。
2. 扩展名检查：`String.EndsWith` helper `0xc0e1250`，对比两个全局字符串
   （`0xdf5a6a8` / `+8`，首次调用时才惰性初始化；未调用前静态值为 0）。
   - `.abc` → `[this+0x12] = 1`
   - `.abf` → `[this+0x13] = 1`
3. 打开文件流：`FileStream` helper `0xc21d98c`，参数 `(path, FileMode=3, FileAccess=1, ...)`；
   `BinaryReader` helper `0xc218e6c`，参数 `(stream, 0)`。
   - `[this+0x78] = reader`
   - `[this+0x80] = second reader/stream`
4. 调 `SkipReadReplayHead(isAbc, checkVersion, reader, &this+0x58)`：
   - `.abc` 走 `0x665aa14`，`isAbc=1`；
   - 非 abc 走 `0x665ad24` 分支。
5. 调 helper `0x665a82c`（`GameReplayModule_BeginReplay`）：
   - `[this+0x11] = 1`，`[this+0xc0] = -1`，`[this+0xc8] = 0`，`[this+0xd0] = 0`；
   - `[this+0xd4]` 作为一次性 guard；
   - 通过 `0x6dc5b5c` 发送 `0x7c` 消息（参数含 path 字符串）。

**（b）`SkipReadReplayHead`：版本检查 + replay head**

- `0x665aa14`（4 参数）处理 `.abc`：
  - 从 `BinaryReader` 读两个字符串（vtable 槽 `+0x298/+0x2a0` 等），传给
    `CheckReplayVersion` `0x665a950`；
  - 版本不通过 → 错误返回；
  - 继续从 reader 读 replay head 字段，写入 `this+0x58`：
    观察到 `+0`、`+4`、`+8` 三个写入；对应 `QuickReplayFileHead` 的
    `lastFrameNoHashCode / lastFrameNo / ...` 仍需逐字段对拍，不能只凭顺序命名。
- `0x665afe0`（3 参数）是另一个入口，`GetBeginLoadMsg` 会调用它。
- `CheckReplayVersion` `0x665a950`：
  - 若 `[GameReplayModule+0xb8+0x18]`（`forceSkipVersionCheck`）非零 → 直接返回 1；
  - 否则 tail-call `0x7351f14`：
    - `0xc0e9e5c` 检查空字符串；
    - `0xc0e1ab4` 比较版本字符串，参考值来自 `[module+0xb8]+0x78`；
    - 返回 bool。

**（c）`GetBeginLoadMsg`：BeginLoad 消息**

- `GetBeginLoadMsg` static `0x665b07c`（3 参数）：
  1. 调 `SkipReadReplayHead` `0x665afe0`；
  2. 通过 `BinaryReader` 的 vtable `+0x2b8/+0x2c0` 读**长度前缀**，分配消息对象
     （分配器 `0xa32c26c`）；
  3. 调 `0x9f7d0c0` 读取消息体；
  4. 检查消息类型：`0x1f42` 或 `0x433` 才接受；
  5. 返回消息对象（`[obj+0x18]`）。
- `GetBeginLoadMsg` static `0x665b42c`（1 参数）是简化入口：检查 path/stream 后
  tail-call 到读取逻辑。
- 这说明 `.abc` 的 BeginLoad 消息是**长度前缀 + 消息 ID**，不是直接裸 TDR；
  具体 ID 的协议名仍需对 metadata/CSProtocol 表确认。

**（d）`UpdateFrame`：送帧泵**

- `UpdateFrame` static `0x665b4c0`：
  - 先看 `[this+0x10]`；为 1 时直接返回（暂停/未开始）；
  - 调 `GetLoadMsgCountOnUpdateFrame` `0x665c058`；
  - 调三个 `Handle` 重载：`0x665bcb8`、`0x665bd94`、`0x665bf60`；
  - 结束时调 `SendReplayFinish` `0x665c50c`；
  - 尾调 `0x665d544`（结束/清理路径）。
- `Handle` → `HandleMsg` `0x665da78` → `DirectHandleMsg` `0x665d8e4`；
  这是**消息泵/分发层**，不是直接的 GameCore CS 写入。
- 原生 `PushCsBuffer/CommitCsBuffer` 的调用不在这一层；下一步要沿 `Handle`
  的下游对象（`m_replayMsgLoader`/`SGamePInvoke`）继续找。

**结论**：

- `.abc` 打开是纯客户端托管链：`File.Exists → 扩展名 → FileStream/BinaryReader →
  SkipReadReplayHead → CheckReplayVersion → BeginReplay helper → BeginLoad/UpdateFrame`。
- 版本检查是字符串比较，可用 `forceSkipVersionCheck` 绕过（客户端自身逻辑）。
- BeginLoad 消息有长度前缀和消息 ID（`0x1f42/0x433`），不是直接 TDR 命令。
- 送帧是 `UpdateFrame → Handle → HandleMsg → DirectHandleMsg` 的消息泵；GameCore
  CS 写入在更下游，需要继续沿对象字段找。
- 这套链可以作为宿主/S3 的**行为规范**，但仍依赖完整客户端对象与 GameCore；
  不改变 G1–G5 门槛。

### 5.43 送帧最后一段：Handle 下游与 FIFO 桥（2026-10-31 续）

**已确认的托管送帧链**：

- `UpdateFrame` `0x665b4c0`：
  - `[this+0x10]` 为 1 时直接返回；
  - 调 `GetLoadMsgCountOnUpdateFrame` `0x665c058`；
  - 调三个 `Handle`：`0x665bcb8`、`0x665bd94`、`0x665bf60`；
  - 结束调 `SendReplayFinish` `0x665c50c`。
- `Handle` `0x665bd94` 尾调 `HandleMsg` `0x665da78`；
  `HandleMsg` 再尾调 `DirectHandleMsg` `0x665d8e4`。
- 这一层是**消息泵/分发**，没有直接调用 `PushCsBuffer/CommitCsBuffer`；
  CS 写入在更下游对象（`m_replayMsgLoader`/`SGamePInvoke`/`SGFifoBufferCpp`）。

**SGamePInvoke 侧的真实地址**：

| 方法 | static VA | 说明 |
|---|---:|---|
| `SGamePInvoke::DoBattleStart` | `0x53e7118` | 0x90 B，custom-ABI 片段 |
| `SGamePInvoke::FlushGameCoreFifo` | `0x53e74a8` | 0x88 B，读 `[x8+0xd48]` 后 tail-call GameReplayModule 槽 `[x0+0x188]` |
| `SGamePInvoke::GameCoreUpdate` | `0x53da280` | 0x9c B |
| `SGW::SetCoreUpdateFrameMode` | `0x53c59cc` | 0x130 B |
| `SGW::PushEasyInStartFightCmd` | `0x53c6c5c` | 0x130 B |

`FlushGameCoreFifo` 的真实入口不是普通 prologue，而是共享/custom-ABI 片段；
它本身不是 `PushCsBuffer`，但确认了“UpdateFrame/Handle 之后进入
`SGamePInvoke` 的 FIFO 刷新层”。

**真正的 FIFO 方法**：

- `SGFifoBufferCpp::PushCsBuffer` token `0x6001493` params 1；
- `SGFifoBufferCpp::CommitCsBuffer` token `0x6001494` params 0；
- `SGFifoBufferCpp::ResetCsBuffer` token `0x6001495` params 0；
- `SGFifoBufferLerp::PushViewBuffer/CommitViewBuffer` token `0x600149d/0x600149e`。

这些类在**英雄选择页未初始化**，token 扫描只命中 metadata 定义，没有真实 MethodInfo。
进入离线 5v5 对局后 GameCore/FIFO 已启动，但 MuMu 在大内存扫描时 adb shell
超时（ANR），本轮没有拿到它们的 methodPointer。这是**环境阻塞**，不是地址未知。

**下一步最小实验**：

1. 进入离线 5v5 对局，等 GameCore 跑起来；
2. 用 `TOKENS_ONLY=1 mem_scan_method <pid> <metadata_base> <size>
   0x6001493 0x6001494 0x6001495` 只扫 token，不扫 name 指针；
3. 解析 name/params，拿 `SGFifoBufferCpp` 三个真实 methodPointer；
4. 反查 `FlushGameCoreFifo`/`Handle` 的全局槽，接到原生 `PushCsBuffer/CommitCsBuffer`。

原生 GameCore 的 `PushCsBuffer/CommitCsBuffer` 导出/偏移已在 5.18/5.29 记录；
现在缺的是**托管 wrapper 的真实 methodPointer**，拿到后最后一段就能闭合。

**离线 5v5 实测（2026-10-31 14:06）**：

- 进入离线 5v5 后 pid=22213，metadata 映射 `0x7be36767e000+0x398d000`；
- 用 `TOKENS_ONLY=1 mem_scan_method` 只扫
  `0x6001493/0x6001494/0x6001495`，扫描完成，**没有 `HIT token`**；
- 扫描器 `rw regions=2048` 达到硬上限，所以不能只凭这次否定“类已初始化”；
  但结合英雄选择页同样 0 命中，**更可能 `SGFifoBufferCpp` 在普通 5v5 里未初始化/未使用**，
  只在回放/QuickReplay 路径才创建；
- 另一个可能：普通 5v5 的 CS FIFO 由 native GameCore 直接消费，
  托管层只到 `SGamePInvoke.FlushGameCoreFifo`/GameReplayModule，不再经过
  `SGFifoBufferCpp`。

因此最后一段现在有两个明确分支：

1. **回放模式**：`SGFifoBufferCpp` 初始化后，用同一 token 扫描拿 methodPointer；
   但离线 5v5 不产回放，登录又不可用，当前环境无法进入回放；
2. **普通 5v5**：托管泵到 `SGamePInvoke.FlushGameCoreFifo` 就交给 native GameCore，
   最后一段是 native `PushCsBuffer/CommitCsBuffer`，不是托管 wrapper。

要区分两者，需要：进入回放模式做一次 token 扫描，或把扫描器上限提高/只扫大块 rw
后重跑普通 5v5。当前 D: 盘空间不足，NDK 已删除，暂不能重编扫描器；这是环境限制。

### 5.44 稀有 actor 消息逐类定性：没有击杀/死亡归属（2026-10-31）

目标：回答“回放里有没有死亡事件 + 击杀者/助攻，能否事件驱动还原经济”。

#### 5.44.1 全量稀有形状（27 个 `.abc`，8 个可完整解析的 5v5）

按 `(tag, sub, flag, len)` 统计，死亡量级（每局几十条）的候选如下：

| 形状 | 全局条数 | 出现文件数 | 结构 | 判定 |
|---|---:|---:|---|---|
| `0x01/0x39` | 6,703 | 4 | `39 + 4×i16`，值域含负数，坐标/速度类 | 位置/朝向类，不是死亡 |
| `0x01/0x8a` | 2,680 | 6 | `8a + flag:u8 + 00 00 00 + actorID:u8` | 可见/状态开关，flag 在 5 帧内翻转 |
| `0x01/0x29` | 447 | 8 | `29 + u16 type=0 + u8 actorID + u8 0 + i32 + i32 + u32` | 技能/回城类；`actorID` 与技能升级里的同一值 |
| `0x01/0x1e` | 255 | 8 | `1e + u8 type(2..4) + 14×00 + u16(0..994) + 01` | 伤害/高光值；尾值每事件唯一，不是稳定英雄 id |
| `0x01/0x87` | 166 | 6 | `87 00 00 00 00` 恒定 | 状态/心跳 |
| `0x01/0x38` | 123 | 3 | 29 B，尾部 `08 57 2a/2b` 递增 | 与位置流中断不相关，不是死亡 |
| `0x01/0x1f` | 40 | 5 | `1f + u8 type + i32 + …` | 极稀有高光，不是常规死亡 |

关键反证：

- `0x29` 的 `data[4]` 对同一英雄恒定（442→44、1547→51、338→8…），与
  `0x02 flag=0x87` 技能升级消息里的 `actorID` 完全一致；它不是“击杀者/受害者”字段。
- `0x1e` 的尾部 u16 在 255 条里几乎全部唯一（最大重复 2 次），且 72/255 小于
  英雄 actor id 下界 338；它更像伤害/高光数值，不是可复用的英雄 id。
- `0x38` 事件发生时该英雄的位置流仍在连续更新（间隔 1–10 条记录），没有“停更+回泉水”。

#### 5.44.2 【已修正】`0x02 len=3` 是 MOVE 方向，不是位置

R1 全量事件流（2026-11-02）确认：`0x02/0x83` 的长度是 3，
结构是 **`degree:i16BE + seq:u8`**（degree -180..180），不是 256×256 地图坐标。
旧 `abc_positions.py/.csv` 把两个字节当 x/y 网格是**错的**，已弃用。

- 这条流能还原“移动方向/输入序列”，**不能**还原英雄连续位置；
- 技能/目标点看 `0x02/0x82`（USEPOSITIONSKILL，x/y 世界单位）和
  `0x01/0x2c`（目标点命令）；
- `0x01/0x39` 是与 `0x2c` 目标点绑定的技能轨迹/拖动，不是英雄走位；
- 因此“回放不存连续位置”仍成立，新版也没有 256×256 位置流。

#### 5.44.3 新发现二：`0x02 flag=0x80` 是 12 字节帧命令，不是统计快照

`0x02 <hero:u16> 80` 后固定 12 字节：

```text
cmdType:u16 | value:u16 | actorID:u16 | seq:u32 | flag:u16
```

`cmdType` 实测 1–15（单局 44–840 条，类型分布随对局变化），`seq` 以 256
为步长递增（低 8 位恒 0），`flag` 偶发 `0x0100`。这是帧命令流，
不是 `COMDT_GAME_30SEC_INFO` 那种 30 秒统计，也不是金币数组。

#### 5.44.4 死亡能否从位置流反推

能“看到”但不可靠：

- 位置流里存在 3–21 秒的**单英雄**空档（如 20261027 的 hero 1652 有 22 个），
  但同文件里也存在大量全体同时断流（录制分段/POV 可见性丢失）；
- 空档后的坐标不总回到固定泉水点，无法把“死亡”与“离开视野/录制丢帧”分开；
- 即使判定为死亡，也只能得到**受害者**，没有击杀者/助攻字段可读。

#### 5.44.5 结论（对“死亡→金币”规则的直接回答）

1. **规则链成立，但回放缺归属字段**：`0x01/0x02` 的 actor 消息里没有
   `(killer, victim, assist[])` 三元组，也没有兵种/野怪类型字段；
2. **不能事件驱动还原经济**：即使解出死亡时刻，也无法从文件内确定金币给谁、
   给多少；金币仍只能来自录屏 OCR、结算/服务器数据，或完整 lockstep 模拟；
3. **可保留的折中**仍是 `stCmdPlayerOneStepBuyEquip` 的出装时序，以及最终 6 格装备成本的交叉校验（不是花费下界/收入），
   以及新版位置流带来的走位/团战站位（不是经济）；
4. **下一步不应继续在高频输入消息里找金币数字**；若要继续，应转向
   “死亡时刻 + 最后伤害来源”的启发式归属，并明确标注为推断而非回放事实。

### 5.45 【修正】5230306 变体有累计金币/经验快照（2026-10-31，用户对拍）

用户提供 `茉莉花与雨`（`20261028_135516.abc`，5230306 变体）的录屏经济：
前 30 秒累计金币恒为 300；00:37 累计 500；击杀小兵 120；自然增长 10；
开局买了辅助宝石。按这组数字回查，5.44 的“回放里没有金币”需要**按变体修正**。

#### 5.45.1 证据：`02/80` 是累计金币/经验快照

5230306 的尾部 TLV 流里有 5 条 `02/80`，结构为
`5×00 + seq:u16BE + 02 80 + a:u16LE + 0000 + 0800 + value:u16LE + 00`：

| 时间 | a | value | 判定 |
|---:|---:|---:|---|
| 64.7s | 2 | 1024 | 累计金币 |
| 79.0s | 2 | 2304 | 累计金币 |
| 83.2s | 5 | 2560 | 累计经验 |
| 142.9s | 2 | 5376 | 累计金币 |
| 172.7s | 5 | 6400 | 累计经验 |

`a=2` 是金币、`a=5` 是经验（79 秒录屏英雄 5 级，经验 2304/2560 量级吻合）。
金币值按 **256 量化**（1024=4×256、2304=9×256、5376=21×256），
实际值在 ±128 内。

#### 5.45.2 与用户数字/录屏 OCR 的拟合

用户补充：00:37 累计 500；01:07 累计 1124；01:09 小兵 +126；
01:14 小兵 +105、累计 1520。录屏 OCR 对应点的当前金币：

| 时间 | 录屏当前金币 | 相邻跳变 | 解释 |
|---:|---:|---:|---|
| 67s | 1114 | — | 与用户 1124 差 1s |
| 68s | 1124 | +10 | 自然增长 |
| 69s | 1134 | +10 | 自然增长 |
| 70s | 1270 | **+136** | 126 小兵 + 10 自然 |
| 74s | 1310 | — | — |
| 75s | 1530 | **+220** | 105+105 两只小兵 + 10 自然 |

回放快照（累计金币）与录屏（当前金币）的对照：

| 时间 | 回放累计 | 录屏当前 | 差值（已花费） |
|---:|---:|---:|---:|
| 64.7s | 1024 | ~1000 | ~24 |
| 79.0s | 2304 | 1629 | 675 |

所以 `02/80 a=2` 是**累计金币**，录屏底部是**当前金币**；差值就是买装备花掉的钱。
用户给的 126/105 与录屏跳变精确吻合（126+10、105+105+10），
说明“小兵金币”不是固定 120，而是按兵种/时间变化（120 只是早先的近似）。

#### 5.45.3 初始 300 与辅助宝石

- 初始金币 300 在玩家块与 TLV 之间的 **Svr2GameCore KV** 里：
  `0x41d2` 起 `value:u16BE, key:u16BE` 的 `(300, 8)`、`(300, 20)`、`(300, 81)`。
  KV 还含 `(500, 64)`、`(500, 105)`、`(13000, 79)`、`(999, 80)` 等；
  顺序是 **value 在前、key 在后**（与 5.16 的 `{confType, value}` 相反，
  需按样本复核）。
- 辅助宝石：第一条 `02/85` 在 **13.9s**，args `06 a5 00 00`
  （type=6，item=0xA5=165），与“开局买辅助宝石”一致；后续
  `02/85` 在 80.9/86.7/129.2/144.9/146.5/171.4s，是其余出装时序。
- `02/87`（8 条，`00 00 00 08`）更像技能/装备被动等级，不是金币。

#### 5.45.4 边界

- 这是 **5230306 的 TLV 流**；5069040 批次的 `0x02 flag=0x80` 是 12 字节
  帧命令（5.44.3），不是同一结构。不能把 5.45 的金币结论套到 5069040 上。
- `02/80` 只有 5 条快照，**没有逐事件金币**；120/小兵、10/s 仍是配置/推导值，
  不是每个小兵一条记录。要逐事件账本，仍需 OCR 或完整模拟。
- 但“累计金币在回放里”已成立；5.44.5 的“不能事件驱动还原经济”应改为
  “不能逐事件还原，但可用快照 + 配置校验/插值累计曲线”。

#### 5.45.5 字段清单（按用户要求：不拟合，只列字段）

| 字段 | 位置/证据 | 值 | 状态 |
|---|---|---|---|
| **模式** | `svr2gamecoreCfg` 第 1 项（`.abc` KV 首项） | 正常 5v5 = **50**；快速赛 = **53** | ✅ 27 个正常样本全 50，快速赛 53 |
| **初始金币** | `CLevelContext.m_originalGoldCoinInBattle`；init scalar index 2；KV key 7/19/80 | **300** | ✅ |
| **累计金币** | TLV `02/80` 的 `a=2`（u16 LE，256 量化） | 64.7s=1024、79.0s=2304、142.9s=5376 | ✅ |
| **累计经验** | TLV `02/80` 的 `a=5` | 83.2s=2560、172.7s=6400 | ◐（按 79s 录屏 5 级推断） |
| **出装/辅助宝石** | TLV `02/85`（type, item） | 13.9s item=165（辅助宝石）；80.9/86.7/129.2/144.9/146.5/171.4s 其余出装 | ✅ |
| **小兵金币（候选）** | 5v5 init scalar index 30/33（未命名） | **120** | ◐ 未与模式行对拍 |
| **自然金币（3/30s）** | 未找到 | — | ❌ 不在 `.abc`/KV/C# databin；`ResDT_LevelCommonInfo` 只有 `bDisableCoin`/`bDisableExp`，没有速率 |
| **快速赛小兵/自然加成** | 未找到 | 126/105、10/s（录屏） | ❌ 不在 `.abc`；应是 GameCore 原生模式配置 |

**结论**：回放里能直接读到的是**模式字段（50/53）**、**初始金币 300**、**累计金币/经验快照**、
**出装时序**；小兵金币的 120 是 init scalar 候选，快速赛的 126/105 和自然增长 3/10
不是逐事件字段，而是 **GameCore 原生模式配置**。`RewardMatchLevel` / `RewardMatchTime`
的 80003/80004 两行是普通/快速的**结算奖励**，不是局内经济，不能当小兵/自然金币字段。

**“累计金币快照就是经济”**：`02/80 a=2` 的 1024/2304/5376 是孙膑的累计金币，
可以直接回答“某时刻经济多少/经济差/曲线形状”。限制是**分辨率**（5 个锚点、
256 量化），不是“没有经济”；逐事件归属（哪只小兵/哪次击杀给谁）仍缺。
`a=5` 是同结构的累计经验。

**边界（不要把“解原生表”当成已通的路）**：

- 825 张 C# databin 表已落盘并逐块校验；但 777 张原生表的**列名/列义未解**
  （5.21/5.24），`normalMonster` 不在 825 张里。
- 离线 5v5 活进程 dump 里 `Project8NormalMonster` / `legacyNormalMonster`
  是 **rows=0**（`live_5v5_20261030/hdr2.txt` 94/95 行），所以没有行数据可读。
- `databin_tables.csv` 的 `normalMonster` 2,625 行只是**表头**，行块未落盘；
  `dc.db` 是 QTS 包，hash→offset 与原生 schema 未解。
- 自然金币 3/30s 可能是 **GameCore 代码规则**，不一定是表字段；`normalMonster`
  是怪物/小兵配置，不必然含自然金币。

因此“下一步直接解 GameCore 原生表”**不是一步可完成的事**；可行路径只有：
(a) 在**快速赛活进程**里 dump 该表（离线 5v5 是 0 行，快速赛是否加载未知）；
(b) 解 QTS 索引 + 原生 schema。两条都未验证，不应作为已承诺的下一步。

### 5.46 表格字段覆盖率（2026-10-31，field map）

工具：`data/replays/_analysis/tools/table_field_map.py`，产物
`datasets/table_field_map.csv`。匹配方式分 exact / `Res` 前缀 / `ResDT_` /
fallback，fallback 会命中 UI 类型（如 `Equip.bytes` → `enPVEEquipFormWidget`），
必须单列。

| 指标 | 数量 |
|---|---:|
| 825 张表块已校验 | 825 |
| 已解成 CSV（值） | 48 张 / 131 cell / 6,633 行 |
| 可靠字段名（exact+Res+ResDT） | **533 张 / 10,363 字段** |
| cell 模型布局已验证（第二版） | **65 张 / 740 cell** |
| 打包宽度布局已验证（v3） | **9 张 / 78 字段** |
| 布局已验证并集 | **78 张** |
| 字段名有、布局待解 | ~451 张（数组/结构体/布尔打包） |
| 无 C# 行类（原生/未知） | ~300 张 |

结论：**字段名覆盖已到 533/825（64.6%）、10,363 个字段**；布局验证到
78 张。剩余约 451 张的字段数≠cell 数，原因是 C# 行类含 `_length`/`_bytes`
数组、`st` 结构体、`b` 布尔打包，不能再用“8 字节 cell 数 == 字段数”判断；
需要**数组/结构体/布尔感知**的布局解算器。约 300 张无 C# 行类的是原生/
未知表，C# metadata 不够，必须走原生 schema。

**经济字段搜索（metadata 全类型）**：`ResData` 配置类型里没有
`gold/coin/income` 字段；带经济字段的是 `CSProtocolWrapper` 协议结构
（如 `COMDT_HERO_STATISTIC_INFO.ullInGameCoin`、`COMDT_GAME_30SEC_INFO`
的 `dwCoinCnt` 等），它们是**上报协议**，不是表。原生表的金币字段仍需
GameCore schema；`normalMonster`/`Level` 的 C# 行类不在 metadata 里。

下一步（按优先级）：
1. 写宽度感知布局解算器：按字段名前缀（`dw/i/w/f`=4、`w`=2、`b`=1、
   `strId`=8、`ast*_length`+`ast*_bytes`=数组）把 511 张的列位解出来，
   用已解的 48 张 CSV 做回归校验；
2. 对 283 张无行类的表，先按 `databin_tables.csv` 的 43 张原生表分类，
   再决定是否值得走 QTS/原生 schema；
3. `normalMonster` 的行块仍缺，不能靠 field map 补。

### 5.47 `RewardMatchLevel` 经济结构体映射（2026-10-31，突破）

`Databin/Public/Level/RewardMatchLevel.bytes`（2 行，1,280 B/行）的行类是
`ResData.ResRewardMatchLevelInfo`（22 字段），其中 `stLevelGamePlayInfo`
是 `ResData.ResDT_LevelGamePlayInfo`（74 字段）的**内联结构体**。
两行 key = **80003（普通 5v5）/ 80004（快速赛）**。

实测对齐（row0/row1 相同偏移）：

| 偏移 | 字段（按声明顺序） | row0/row1 | 说明 |
|---:|---|---|---|
| 0x34c | `astExpCompensateDetail_length` | 80 | 经验补偿条目数 |
| 0x350 | `astCoinCompensateDetail_length` | 0 | 金币补偿条目数（两模式都是 0） |
| **0x358** | **`wOriginalGoldCoinInBattle`** | **300** | **初始金币，确认** |
| 0x35a | `bIsOpenExpCompensate` | 1 |  |
| 0x35b | `bIsOpenCoinCompensate` | 1 |  |
| 0x360 | `iHeroBornAgeDelayTime` | 1900 |  |
| 0x368/0x36c | `strIdMapPath` | str handle |  |
| 0x378/0x37c | `strIdMirrorMapPath` | str handle |  |
| 0x388/0x38c | `strIdBigMapPath` | str handle |  |
| 0x390/0x394 | `strIdMirrorBigMapPath` | str handle |  |
| 0x39c 起 | `astExpCompensateDetail` | (3,4000)(4,6000)(5,8000)(6,10000) | **等级→经验补偿**，不是金币 |
| 0x4c8 | `bJungleEquipLevelNotShareIncome`/`bAidEquipLevelNotShareIncome` + 计数 | `01 01 04 0a` vs `01 01 02 0a` | 打野/辅助装备分金限制 |
| 0x4cc/0x4d0 | `iSoldierActivateCountDelay1/2` | 10036/10035 vs 10040/10039 | 小兵激活延迟（ms） |
| **0x4fc** | **`dwAidNotShareIncomeLastTime`** | **60 vs 0** | **辅助装备分金时间：普通 60s，快速 0（不限）** |

**结论**：

- 初始金币 300 的字段确认：`ResDT_LevelGamePlayInfo.wOriginalGoldCoinInBattle`
  @ `RewardMatchLevel` 行内 0x358。
- 普通/快速确实有两套 `stLevelGamePlayInfo`；差异里**辅助装备分金时间
  60 vs 0** 是已确认的**模式经济规则**，对应“快速赛辅助宝石收益更高”。
- 但 `astCoinCompensateDetail_length = 0`，两行的**金币补偿表都是空**；
  “小兵 120/126/105、自然 3/10”不在这两行里，仍需在
  `normalMonster`/`Level`/GameCore 代码里找。
- `ResDT_LevelGamePlayInfo` 的字段名已经拿到（74 个），后续可按偏移
  继续解 `Level.bytes`/其他引用它的表。
- 数组后字段（近似偏移）：`0x3e8=90003`（`dwCompensateExpBuffID`）、
  `0x3ec=90005`（`dwCompensateGoldBuffID`）。这两个是**原生 buff ID**：
  C# 的 `BurningBuff`（650010..650160）、`ResSvrBuff`（1,2）、
  `NominateBuffConf`（2..20）都不含 90005，说明 90005 是 GameCore
  原生 buff，配置不在 825 张 C# 表里。
- 因此“自然金币 3/10”若由 90005 提供，仍需原生 buff 表/GameCore 代码；
  与 `normalMonster` 同一个 blocker。`RewardMatchLevel` 能确认的只是
  起始 300、辅助装备分金 60/0、小兵激活延迟 10036/10040 这些**规则**。

#### 5.47.1 buff 90005 的原生行（`dc.db` 0x4614）

`dc.db` 0x4614 起是 buff 90005 的完整行（未压缩）：

```text
0x4614  95 5f 01 00        rowID = 90005
0x4624  00 00 00 00 00 01 01 00
0x4644  0c 00 00 00        = 12
0x4654  6b 89 db c1 00 9e 17 00   str handle
0x465c  6b 89 db c1 00 16 17 00   str handle
0x4664  6b 89 db c1 00 a4 17 00   str handle
0x4674  04 00 00 00        = 4 个效果
0x4684  61 02 00 00 62 02 00 00 63 02 00 00 00 00 00 00
        effect IDs 609, 610, 611, 0
0x469c  5a 02 00 00 5b 02 00 00 5c 02 00 00
        effect IDs 602, 603, 604
0x4714  58 02 00 00 ×4     effect ID 600
```

行里**没有直接的 3/10/120/126/105 字段**；只有效果 ID 列表。
`dc.db` 里没有 `609,610,611,612` 的连续明文序列，效果表应在
QTS 压缩页或原生 effect 配置里。`TeamExtraCoinByBuffEventParam`
（`totalCoinsByBuff`/`buffID`）说明金币是**运行时按 buff 计算**，
不一定落在表字段。下一步是 effect 609/610/611 的配置行或
GameCore 的 buff 金币计算代码。

### 5.48 【突破】`Level.bytes` 小兵金币字段是明文（2026-10-31）

`Databin/Public/Level/Level.bytes`（35 行，656 B/行）的 row0/row1
（行 id 1/2）就是**普通 5v5 / 快速赛**两套：

| 偏移 | row0（普通 5v5） | row1（快速赛） | 说明 |
|---:|---:|---:|---|
| 0x128 | 81 | 165 | 兵种/奖励组 1 |
| **0x12c** | **80** | **120** | **小兵金币，确认** |
| 0x130 | 81 | 165 | 组 2 |
| 0x134 | 80 | 120 | 组 2 金币 |
| 0x138 | 81 | 145 | 组 3 |
| 0x13c | 80 | 65 | 组 3 金币 |
| 0x144 | **3** | 0 | 自然金币（普通 3） |
| 0x178 | 17000 | 20000 | 金币/经验上限候选 |

**结论**：

- **小兵金币是明文**：`Level.bytes` 0x12c，普通 5v5 = **80**，快速赛 = **120**。
  这直接验证“120 是快速赛、正常 5v5 不一样”；105/126 是其他兵种/时间变体。
- **但 0x128–0x13c 是六个数、三组**，不是一个小兵值：
  - 普通：`(81,80) (81,80) (81,80)`；
  - 快速：`(165,120) (165,120) (145,65)`。
  这三组更可能是**三个兵种/三条兵线**（近战/远程/炮车，或上/中/下），
  `0x12c=80/120` 只是其中一组的第二个值。105/126 是实际到手值，
  可能对应另一组/时间缩放后的结果。
- 自然金币普通 = **3**（0x144），与“30s 开始 3 块”一致；快速赛 row1
  的 0x144 是 0，10 不在这里，可能在 `dwCompensateGoldBuffID=90005`
  或另一个字段。
- `Level` 是**原生表**，字段名不在 C# metadata 里；但行/偏移/值都是
  明文的，可直接用。三组的兵种/兵线归属仍需 `normalMonster` 表
  （2,625 行，行块缺失）或 `Level` 原生 schema 才能钉死。

#### 5.48.1 `02/84` 是全图单位死亡，和兵线刷新对齐（修正 5.44/5.45）

之前把 `02/84` 的每区间条数和“本地玩家反推补刀数”比较（76/70/9/343/95
vs 2.1/9.5/1.8/18.5/6.1），得出“不是补刀”的结论。这个比较口径错了：
`02/84` 是**全图单位事件**，不是本地玩家一个人的补刀。

按 5 秒桶看 `02/84`（5230306 样本，599 条）：

```text
35-40s 34   40-45s 12   45-50s 24
60-65s 12   65-70s 34   70-75s 19   75-80s 26
85-90s 40   90-95s 33   95-100s 49  100-105s 63  105-110s 39  110-115s 16
130-135s 51 135-140s 34 140-145s 26
160-165s 21 165-170s 66
```

兵线在 30/60/90/120/150s 刷新，`02/84` 的簇正好出现在每次刷新后的
5–20 秒；空档在刷新之间。**时间结构支持 `02/84` = 小兵/单位死亡**。
args 分布 `00 00` 241、`01 00` 122、`02 00` 117、`04 00` 118，
四个类别，可能是队/兵种/兵线分组。

**这对“人为计算”的意义**：

- **队伍经济**：如果 `02/84` 的 args/key 能给出“哪一队/哪一路/哪个兵种”，
  就可以用 `Level` 的小兵金币（普通 80、快速 120/165/145/65）+
  自然金币（普通 3、快速 10）+ 英雄击杀，手工累加队伍经济。
- **本地玩家经济**：`02/80` 的 1024/2304/5376 是本地玩家的累计金币锚点，
  可以直接校验手工累加的结果。
- **十人各自经济**：`02/84` 是**全局**单位事件，envelope hero=0，
  **没有击杀者英雄**；只能到“队伍/兵种/兵线”这一层，不能直接分到
  某个玩家。逐玩家需要最后一击归属（录屏或位置/攻击启发式）。

### 5.49 【修正】个人金币与逐玩家事件：`0x02 len=5` 和 `0x1e`（5069040）

之前说“个人经济算不了”过于绝对。5069040 的两个消息已经给出个人层：

**（a）`0x02 flag=0x85 len=5` = 本地/POV 玩家的金币账本**

- 每个文件**只有一个英雄**有这种消息，即本地/POV 玩家：
  - 主样本 `20260925_105224`：hero **1514**，**28 条**，合计 **2,820**；
  - 其他样本：814(6/764)、316(17/3294)、602(4/446)、1217(1/87)、356(1/253)、906(2/241)、186(1/31)。
- 数据形态：`sourceType:u8 + amount:u32LE`；主样本 sourceType
  `4`=23 条、`5`=3 条、`43`=2 条；amount 31–203。
- 这是**本地玩家的逐笔金币收入**（小兵/助攻/击杀/目标），加上自然金币
  就能还原 POV 玩家的个人经济。`sourceType` 4/5/43 的语义待定，
  但“本地玩家个人经济可算”已成立。

**（b）`0x1e len=19` = 全 10 人的单位/英雄交互事件**

- envelope hero = **攻击者**（全 10 人都出现，不是本地专属）；
  尾部 u16 = **受害者单位 ID**（0–994，基本唯一，最大重复 2）。
- 每个玩家 1–24 条：例如主样本 1021 有 5 条（193/325/457/947/369）、
  338 有 3 条；20260807 的 573 有 24 条。
- 这不是“稳定英雄 id”（之前据此判为伤害值），而是**逐玩家的
  攻击者→受害者单位**事件；受害者 ID 的兵种/英雄归属需要按
  `Level`/`normalMonster` 的单位 ID 段映射。

**结论（修正）**：

- **POV 玩家个人经济**：`0x02 len=5` + 自然金币，**可算**。
- **其他 9 人**：`0x1e` 给出英雄交互，但小兵最后一击不全；
  完整个人经济仍缺，但不再是“完全算不了”。
- **队伍经济**：`02/84` 单位死亡 + `Level` 小兵金币 + 自然金币，**可算**。

#### 5.49.1 `0x1e` 共享受害者与 `0x1f`/`0x20` 稀有形状（继续破解）

`0x1e` 的尾部 u16 不只是“每事件唯一”。按文件分组后，出现**同一值被
两个不同攻击者打**的情况：

| 文件 | 受害者值 | 攻击者 |
|---|---:|---|
| 20260827 | 342 | 1208, 1242 |
| 20260827 | 503 | 226, 907 |
| 20260807 | 699 | 1578, 1879 |
| 20260807 | 977 | 455, 573 |

这说明尾部 u16 是**受害者 ID**：能被两个玩家同时打的是**英雄/目标**，
只被一个玩家打的是**小兵/单体**。所以 `0x1e` 是
**攻击者 actorID → 受害者 ID** 的逐玩家事件，不是纯伤害值。

`0x1f`（28 B，40 条，约 1.5/局）和 `0x20`（20 B，6 条）也带多个 ID：

```text
1f 05 ff ff ff e7 ... 03 1e 01 00 04 0f 1a   ; IDs 798 / 1039
1f 01 00 00 00 1f ... 02 51 01 00 00 00 00   ; ID 593
20 15 08 00 00 08 17 ... 01 89 01 00 19 54 89 ; ID 393 / 6484
```

`0x1f` 的 `03 1e`=798、`04 0f`=1039 落在英雄/单位 ID 值域，且带
`01 00` 计数和负 i32；候选是**击杀/助攻通知**（稀有，可能只记特殊击杀）。
`0x20` 的 393/6484 候选是**目标/MVP**。两者都还不能定论，但说明
**击杀/助攻归属不一定完全缺失**，`0x1e` + `0x1f`/`0x20` 值得继续解。

**最后一击验证（主样本 `20260925_105224`）**：

- 把 `0x1e` 按受害者分组、取最大 seq 作为最后一击：
  17 个受害者、0 个共享；最后一击攻击者
  **1021=5、338=3、1729=3、1547=2、1558=2、1514=1、442=1**。
- 本地玩家 1514 在 `0x1e` 里只有 **1 次**最后一击（seq 11811，victim 145）。
- 但 `0x02 len=5` 里 1514 有 **28 条**金币（type 4=23、5=3、43=2）。

→ `0x1e` **不是**本地玩家的小兵最后一击表；它更像**英雄/目标**
（共享受害者、17 条）。本地的小兵/助攻金币在 `0x02 len=5` 里。
其他 9 人的小兵最后一击仍不在已解消息里，继续找。

**`0x02 len=5` 的 sourceType 拆分（主样本 1514，28 条）**：

| sourceType | 条数 | 金额 | 判定 |
|---|---:|---|---|
| 4 | 23 | 87–134 | 小兵/助攻（本地主要金币来源） |
| 5 | 3 | 31/131/145 | 助攻/野怪 |
| 43 | 2 | 203/102 | 击杀/目标 |

23 条 type 4 正好对上“本地小兵/助攻金币”；`0x1e` 里 1514 只有 1 次，
两类事件不同。type 4 合计 **2,208**，金额分布
80×13、90×4、100×3、130×2、110×1；时间 21–627s；
基础小兵 80 + 辅助加成 7–54。

**`0x1f` 的候选字段形态（28 B，40 条）**：

```text
1f 05 ff ff ff e7 ... 03 1e 01 00 04 0f 1a
   type=05  i32=-25      798   1   1039  26
候选：type:u8 | i32 | ... | victim:u16 | assistCnt:u16 | assist:u16 | flag:u8
```

envelope hero = 击杀者，798/1039 = 受害者/助攻。40 条约 1.5/局，
偏少，可能只记特殊击杀/高光，但**击杀/助攻归属的字段形态已有**。
`0x20`（20 B，6 条）同形态：393/6484，候选目标/MVP。

**Project8Hero 映射与 `0x1f` 修正（主样本）**：

- `Project8Hero`（`41_Project8Hero.bytes.bin`，259 行 × 688 B）：
  行 ID 1000+（actor 级）；**英雄 ID 在 offset 22/14（u16）**，
  **皮肤 ID 在 338/640/157/100/392/484**。
- `Project8Hero` 的英雄 ID 集合是 **174-193（20 个）**；`0x1e` victim 193
  在 22/14（英雄），其余 16 个 victim（626/595/980/…）不在英雄集合 →
  **单位**。按受害者取最大 seq = 最后一击：**英雄击杀 1**（1021→193），
  **单位最后一击 16**（1021=4、338=3、1729=3、1547=2、1558=2、1514=1、442=1）。
  所以 `0x1e` 是**英雄/单位伤害表**，不是纯英雄击杀。
- 本地 1514 在 `0x1e` 只有 1 次单位最后一击（145），但 `0x02 len=5`
  type 4 有 23 条 → 本地完整小兵/助攻在 `0x02 len=5`；`0x1e` 的
  单位最后一击是**特殊单位**（16），不是完整补刀。其他 9 人同理：
  `0x1e` 给 15 次特殊单位最后一击，完整小兵补刀仍不在本文件。
- 16 个单位 victim：626/595/980/325/457/362/461/861/467/429/145/
  947/64/492/464/369；英雄 victim 只有 193（1021→193）。
- `0x1f` 的 **798/42/268/458 不在 Project8Hero**；**1039 是皮肤 ID**
  （offset 338，行 1061/1062/…，英雄 174-178）。→ `0x1f` **不是**
  victim/assist 击杀通知，更像 **highlight**（source/target/skill，
  对应 metadata 的 `stHighlightNotifyParams`）。
- `0x20` 393/6484 不在 Project8Hero，候选目标/单位。主样本 1 条
  （2136，106.8s），批量 6 条；与 `0x1f`（2188，109.4s）成对，
  候选 highlight/目标。
- 分工修正：`0x1e` = 英雄击杀；`0x1f` = highlight；`0x02 len=5` =
  本地金币账本；`02/81` = 击杀位置（5230306）。其他 9 人的小兵
  最后一击仍缺。

**Project8Hero 行块（`41_Project8Hero.bytes.bin`）**：

- 259 行 × 688 B，行 ID 1000+（actor 级），不是英雄 ID；
- 英雄/皮肤 ID 是行内 **u16 字段**：193 在 offset 22/14（12 行），
  1039 在 offset 338（24 行），540/900/560 在 392/484/100；
- → `0x1e` victim 193/145 是**英雄 ID**；`0x1f` victim 1039 也在表内
  （offset 338，偏皮肤/英雄字段）；`0x20` 的 393/6484 不在表内，
  候选目标/单位 ID。
- 这确认 `0x1e` 是**英雄伤害/击杀**，不是小兵；其他 9 人的小兵最后一击
  仍不在 `0x1e`/`0x1f`/`0x02` 里。

**`02/84` args/key（修正：成对刷新/死亡）**：args `00/01/02/04/06` =
241/122/117/118/1；`00`/`01` 成对（35–40 17/17、40–45 6/6、45–50
12/12、60–65 6/6、65–70 17/17），`02`/`04` 成对（70–75 3/3、85–90
12/12、95–100 16/16、100–105 21/21、130–135 17/17、165–170 22/22）。
→ `00`/`02`=刷新，`01`/`04`=死亡；`00/01`=team 1（红，早），
`02/04`=team 2（蓝，晚）。录屏红杀 55（早）、蓝杀 82/104（晚）一致。
64s 对拍：蓝队金币来自红队死亡 `01` 41×120=**4,920** vs 录屏 **4,300**
（接近）；红队金币来自蓝队死亡 `04` **0** + 自然/目标 vs 录屏 **5,600**
（部分）。killer 仍缺，但 team/type + 刷新/死亡已分开。

### 5.50 大形状收尾：`0x39` / `0x8a` / `0x01 len14`（2026-10-31）

- **`0x39`（6,703）**：20260827 样本 4,458 条**只属于 hero 881**（POV）；
  4×i16，`a=-1/0`、`c=0/-1`、`b/e` 平滑坐标 → **POV 英雄的连续位置/速度**，
  不是小兵/其他 9 人。
- **`0x8a`（2,680）**：每文件只有少数英雄；`flag:u8 + 00 00 00 + actorID:u8`，
  actorID 是英雄自己的 in-stream ID（8/12/33/36/37/56/64），flag 0/1 各半
  → **逐英雄状态开关**（可见/存活类），不是小兵/其他 9 人。
- **`0x01 len14`（1,881）**：7×i16，col1/col5 是 x/y 坐标，col0/col4 是 -1/0
  标志，col2/3/6 恒 0；envelope 覆盖多个英雄（602/1445/701/133/1597/720/670）
  → **逐英雄位置**，是**其他 9 人的位置**（`0x39` 是 POV，`0x01 len14` 是多人），
  不是小兵。

**这补上了“其他 9 人的位置”**：`0x39`=POV 轨迹，`0x01 len14`=其他英雄轨迹，
`0x02 len=3`=MOVE 方向（degree:i16BE+seq，不是位置），`0x2c`=攻击/指示器目标位置。
`0x8a`=逐英雄状态，不是位置。

- **`0x23`（2,290）**：主样本 228 条、7 英雄；`flag:u8` 0/1 各半
  （1965 24/27、1514 25/25、1547 26/22、338 19/18…）→ **逐英雄 bool 状态**，
  不是位置。剩余大形状：`0x29`（447，技能/回城）、`0x38`（123，buff/目标）、
  `0x02 flag 0x83`（476，common）。
- **`0x29`（447）**：`x=skillID<<8`（91060 常见、900011、11991），
  `y=param<<8`（25/1348/33），tail=seq；**技能/回城**，per-hero，不是小兵。
- **`0x38`（123）**：29 B，尾部 `08 57 2b/2a`；**buff/目标**，per-hero，
  不是小兵。
- **`0x01/0x00`（191）**：全局批量包，29 条主样本；长度 12/23；
  `00 00 <seq> 00 00 00 00 <nested tags>`；嵌套 0x12/0x13/0x14/0x01/0x02，
  内含 per-hero 消息（如 `0x060b=1547` 的 `03 00`）。→ 是**批量容器**，
  不是独立语义。**消息层形状到此全部解完。**

### 5.51 `ResWarmBattleHero` 布局验证：行键是皮肤 ID（2026-10-31）

- 表 328，stride 96，132 行；offset 0 是 **皮肤 ID**（105–585），不是
  `SkinID_length`；`SkinID_length` 在 offset 8（值 1）。
- 行0：`105, 0x0001020f, 1, 80115×3（字符串句柄）, bools...`
- C# 行类字段顺序 **不匹配** 行布局；v3 打包解算器失败的原因是
  **行键/保留字段/字符串句柄/填充**，不是字段宽度。
- → 451 张布局需要 **行键感知 + 字段顺序 + 句柄/填充** 的解算器；
  单纯按 C# 字段顺序加宽度不够。

### 5.52 【突破】原生金币配置表 `dc.db @0x106464`（2026-10-31）

> **已修正（见 5.75）**：`@0x106464` 是 **ResCommonSettle**；
> 120/126 是经验、40/45 是金币，不是小兵金币档位。

> **已修正（见 5.74）**：`0x4614` 不是 buff 行，是 PVE 关卡表
> `0x364c` 的 row5 尾部 + row6 本体；609/610/611、602/603/604 是
> `0x5902c` 的王者小店主播 ID，不是 buff effect。真正的 buff 表是
> `0x8268ac`（13,558 行）。

早期把 `@0x106464` row 611 当作 buff 90005 的 effect 611；现在看，
`@0x106464` 是一张独立的金币/经验档位表：

- **row 611** = `[611, 1, 6011, 84, 420, 0, 0, 20, 100, 10, …]`；
  第 4 字段 84/120/146/268 是金币，第 5 字段 420/600/730/1340 是经验；
  第 10 字段 10 的语义未定（曾猜自然金币，未与 buff 表对上）；
- 全表扫描：300（初始）29 行、10（自然候选）35 行、
  120（小兵）2 行、105 1 行、126 3 行；
- `0xc4ab4`/`0x5902c` 的 609/610/611 行是主播/字符串行，不是金币行；
- → 609/610/611 的“商店+治疗+金币”对应关系**作废**；快速赛自然 10
  的来源仍未确认（不在 buff 表，也不在 Level）。
- `@0x106464` 的 120/126 行：
  - 432/621：120 / 600 / 40-41 / 200-206 / 10-32；
  - 334/531/524：126 / 630 / 45 / 225 / 10-28；
  → 120/126=小兵金币，600/630=经验，10=自然金币。
- **`normalMonster` 表找到了**：`dc.db @0x679118`，stride 584，
  rows 2,625；首行 rowID=41，值 17/5000/4000/140/140/2500；
  这是单位配置表（小兵/野怪类型）。

**`02/81` = 英雄击杀位置通知（5230306）**：

- 20 条，35.8–169.5s；args 19B：
  `type:u8(01/03) + u16 坐标(0xEE3B/0xFF3C/…) + 0x0c/0x0995 + zeros`；
- key：常见 `022301`，rare `0000b9`/`ff98c9`/`ffd7e3`；
- 与录屏击杀 55/82/104s 对齐：`02/81` 出现在 **62.4/84.8/105.9s**
  （延迟 7.4/2.8/1.9s）。
- → 这是**击杀位置通知**，不是纯位置流；killer/victim 不在 args，
  key 可能是 actor hash。它补上了“击杀发生时间/位置”这一层，
  但归属仍要 `0x1f`/`0x1e` 或 key 的进一步解码。

## 5.53 normalMonster 行/字段破解 + `@0x106464` 四档金币表

> **已修正（见 5.75）**：`@0x106464` 是 ResCommonSettle；
> 120/126=经验、40/45=金币；“四档金币表”作废。

**表头（`stdr`）**：`+0x08`=字符串池条数，`+0x14`=stride，`+0x18`=rows，
`+0x90`=数据结束/池起点（相对表头）。`normalMonster`：
`dc.db @0x679118`，stride 584，rows 2,625，1,192 条字符串，池
`0x7EF5F8`；下一张表 `0x80017C`。

**行布局（584B）**：

| 偏移 | 字段 | 说明 |
|---:|---|---|
| +0x00 | rowID:u32 | 单位 ID（41/410/6000/6002/6003/6011/6014/…） |
| +0x04 | 1:u32 | 版本/计数 |
| +0x08 | hash:u32 | 字符串表哈希 `0x632C9867`（同表所有行相同） |
| +0x0C | ref1:u32 | 名称字符串 ID |
| +0x10 | hash:u32 | `0x632C9867` |
| +0x14 | ref2:u32 | 变体/prefab 字符串 ID |
| +0x18 | actorType:u32 | 17（普通单位） |
| +0x1C | hp:u32 | 最大生命 |
| +0x24 | hp2:u32 | 第二血量/显示血量 |
| +0x2C | gold:u32 | 金币（+0x30 同值） |
| +0x34 | exp1:u32 | 经验（小，180/360/400） |
| +0x38 | exp2:u32 | 经验（第二档，400） |
| +0x3C | exp3:u32 | 经验（大，2500/2750/3850） |
| +0x40 | flags:u32 | 标志位 |
| +0x44 | actorTypeID:u32 | 单位类型 ID（10010/10012/10020/10016/20660/20662/20674） |
| +0x6C | field108:u32 | 50020/50103 等（待定） |

**字符串池**：`(hash64 + UTF-8 + 4 字节对齐)` 记录，共 1,192 条。`ref1`
的**首次出现顺序**与池中“含 CJK 且不含路径字符”的名称串顺序一一对应
（468/470；最后两个是非 CJK 名）。因此 rowID → 名称可还原；`ref2`
指向同组的 prefab/actorinfo 变体。

**小兵/野怪行（normalMonster 值）**：

| rowID | 名称 | HP | gold(+0x2C) | exp3(+0x3C) | actorTypeID |
|---:|---|---:|---:|---:|---:|
| 6000 | 蓝方战士 | 7000 | 60 | 3850 | 10010 |
| 6003 | 红方战士 | 7000 | 60 | 3850 | 10010 |
| 6001/6004 | 蓝/红方法师 | 8500 | 90 | 3850 | 10012 |
| 60012 | 蓝方法师（变体） | 8500 | 117 | 2750 | 100121 |
| 6002/6005 | 蓝/红方弩车 | 8500 | 192 | 3850 | 10020 |
| 6014/6015 | 蓝/红方机关战士 | 7000 | 576 | 3850 | 10016 |
| 6010 | 蔚蓝石像 | 7000 | 190 | 3000 | 20660 |
| 6011 | 腥红石像 | 7000 | 190 | 3000 | 20662 |
| 6023/6028 | 主宰/小主宰先锋 | 10000 | 200 | 3850 | 20674 |

→ `actorTypeID` 直接编码兵种：`10010=战士`、`10012=法师`、
`10020=弩车`、`10016=机关战士`、`20660=蔚蓝石像`、`20662=腥红石像`、
`20674=主宰先锋`。这是比名称更硬的类型键。

**`@0x106464` 金币/经验表**：`stdr`，stride 120，rows 388；
行布局 `[cfgID, 1, unitID, gold, exp, 0, 0, f7, f8, f9, …]`。
`cfgID = 族(3/4/5/6) + 档位(1-4) + 分路(1-4)`；
`unitID = 族(3/4/5/6) + 0 + 分路(1-4) + 1`。四族 × 四分路 × 四档：

| 族 | 类型（按 normalMonster 名称/actorType） | 一档 gold | 二档 | 三档 | 四档 |
|---|---|---:|---:|---:|---:|
| 3xxx | 近战兵（战士，actor 10010） | 60-72 | 84-102 | 102-126 | 188-232 |
| 4xxx | 远程兵（法师，actor 10012） | 66-82 | 94-116 | 116-142 | 212-258 |
| 5xxx | 炮车/弩车（actor 10020） | 72-90 | 102-126 | 126-154 | 232-284 |
| 6xxx | 超级兵/机关战士（actor 10016） | 84-102 | 120-146 | 146-180 | 268-328 |

**120/126 的真实归属**（不是唯一兵种，而是“族×分路×档位”的组合值）：

- `120/600`：`cfg 432 / uid 4021` = **远程兵（4xxx）分路 2、三档**；
  `cfg 621 / uid 6011` = **超级兵（6xxx）分路 1、二档**。
- `126/630`：`cfg 334 / uid 3041` = **近战兵（3xxx）分路 4、三档**；
  `cfg 531 / uid 5011` = **炮车（5xxx）分路 1、三档**；
  `cfg 524 / uid 5041` = **炮车（5xxx）分路 4、二档**。

因此“120=近战、126=远程”之类的单值映射不成立：同一 120/126 会在
不同族/分路/档位重复出现。**快速赛**的 120 金币来自
`Level.bytes` row1（`+0x12C=120`、自然 `+0x144=10`），与
`@0x106464` 的 120/126 是两套东西：前者是模式基数，后者是普通模式
随时间/分路/兵种变化的档位值。

**产物**：

- `data/replays/_analysis/tools/decode_normal_monster.py`
- `data/replays/_analysis/datasets/normalMonster_rows.csv`（2,625 行）
- `data/replays/_analysis/datasets/normalMonster_types.csv`（按名称聚合）
- `data/replays/_analysis/datasets/gold_config_106464.csv`（388 行）

## 5.54 `0x02 len=5` 是十人金币流水（不是只本地）

**结论**：主样本 `20260925_105224…abc` 的 `0x02 flag=0x85 len=5`
共 **286 条，覆盖全部 10 个英雄实体**（envelope hero 就是玩家实体，
不是 POV 专属；含 0x80 命令体修正）。数据
`sourceType:u8 + amount:u32LE`。

| sourceType | 观测金额 | 语义（证据） |
|---:|---|---|
| 4 | 87-135 / 187-219 | **小兵/攻城车结算**；金额是档位结算额（不是逐次补刀，见 5.96） |
| 6 | 165-201 | **野怪击杀全额金**；由辅助/游走拿边野（见 5.97） |
| 43 | 102 / 202-203 | **击杀/助攻金币**；203≈击杀 200，102≈助攻 100 |
| 5 | 31-73 / 131-254 | 小额辅助装/被动；230–254=打野刀 +20% 野怪金；131–146 混合 |
| 44/47/51 | 47 / 179 / 254 | 其他奖励（助攻/一血/推塔候选） |

**十人流水（主样本）**：

| 玩家 | 队/位 | source4 次数 | source4 金币 | source6 次数 | source43 次数/金额 | 合计 |
|---|---|---:|---:|---:|---:|---:|
| Vetymoment | 2/4 | 21 | 4,070 | 1 | 1 / 102 | 4,951 |
| 桑忆终尘启 | 1/0 | 19 | 3,667 | 0 | 1 / 102 | 4,044 |
| 双枪踏浪行 | 1/4 | 20 | 2,314 | 0 | 1 / 203 | 3,875 |
| 李不信有归途 | 2/0 | 19 | 2,192 | 0 | 0 | 3,375 |
| 备水一站. | 2/2 | 12 | 1,438 | 0 | 0 | 3,242 |
| 布鲁BIUBIU | 1/2 | 24 | 2,339 | 0 | 2 / 305 | 2,951 |
| 酒梦灵心醉 | 2/1 | 21 | 2,041 | 0 | 3 / 508 | 2,887 |
| 碗面加香菜 | 1/1 | 20 | 1,960 | 0 | 2 / 405 | 2,527 |
| 佚名(*: | 2/3 | 4 | 781 | 3 | 0 | 2,399 |
| 含泪吃兵线呢 | 1/3 | 2 | 382 | 4 | 0 | 2,119 |

**击杀/助攻归属**（source 43 拆 203=击杀、102=助攻）：

- 击杀：双枪踏浪行 1、布鲁BIUBIU 1、碗面加香菜 2、酒梦灵心醉 2
  → 团队 1 **4 杀**、团队 2 **2 杀**；
- 助攻：Vetymoment 1、桑忆终尘启 1、布鲁BIUBIU 1、酒梦灵心醉 1
  → 2:2。
- 这与“`02/81`/`02/84` 不带 killer/victim”互补：**killer/assist 不在
  TLV args 里，但在 `0x02 len=5` 的 source 43 里**。

**`02/81`/`02/84` 的边界**（5230306 快速赛样本）：

- `02/81` 20 条：args 19B `type(01/03) + u16 坐标 + 0x0c/0x0995 + zeros`；
  key 多为 `022301`（本地观察者/actor），rare `0000b9`/`ff98c9`/`ffd7e3`；
  **无 killer/victim ID**，只能给“击杀发生位置/时间”。
- `02/84` 599 条：args 2B `0100`/`0200`/`0400`/`0000`，key 多为
  `000000`/`022301`，rare key 为单位 actor；**无 killer**，只能给
  “单位生成/死亡”。
- 与 `02/81` 同 seq 附近没有 `02/84` 记录（两套独立流），不能靠对齐补归属。

**产物**：

- `data/replays/_analysis/tools/player_gold_ledger.py`
- `data/replays/_analysis/datasets/player_gold_events.csv`（281 行）
- `data/replays/_analysis/datasets/player_gold_summary.csv`

**口径提醒**：source4 的“次数”是**补刀金币事件数**，不是显式
last-hit 标记；金额会受金币分享/模式/辅助装影响。source 43 的
203/102 也应按“候选”理解，最好再用结算 KDA 对拍一次。

## 5.55 原生表目录（1,443 张 `stdr`）

`tools/native_table_catalog.py` 扫描 `dc.db` 全部 `stdr` 表，解析：
表偏移、stride、rows、声明/实际字符串数、CJK 名称数、行内
`(hash, offset)` 引用槽位、名称还原覆盖率、首行 rowID/首名称。

结果（`datasets/native_table_catalog.csv`）：

- **1,443** 张表进入目录（stride 8–4,096，rows 1–100,000）；
- **1,078** 张检测到行内字符串引用槽；
- **460** 张可把引用顺序对到 CJK 名称（名称覆盖率 >0）。

高价值候选（按覆盖行数）：

| 表偏移 | stride | rows | 名称数 | 引用槽 | 覆盖 | 首名称 |
|---:|---:|---:|---:|---:|---|---|
| `0x3a47220` | 256 | 3,819 | 15,299 | +0 | 3,819/3,819 | 北京市 |
| `0x74ac508` | 112 | 3,432 | 1,325 | +0 | 1,320/1,320 | 双抗+10 |
| `0x6225340` | 72 | 393 | 266 | +36 | 266/393 | 廉颇 |
| `0x3c4da00` | 88 | 669 | 1,040 | +0 | 262/262 | 双星英雄 |
| `0x3d1a9b0` | 1,144 | 1,947 | 6,459 | +0 | 239/239 | 廉颇 |
| `0x59f0ad0` | 200 | 688 | 969 | +60 | 235/235 | 峡谷新秀 |
| `0x111c3c` | 896 | 201 | 671 | +88 | 148/148 | 廉颇 |

注意：目录只证明“名称/字符串引用可还原”，不证明每个数值字段的
语义；字段布局仍需按表逐张用已知值（金币/血量/等级）对拍。

**产物**：`tools/native_table_catalog.py`、
`datasets/native_table_catalog.csv`。

## 5.56 30 秒统计 schema 与模式经济字段

> **已修正（见 5.69）**：`Level` 的 `+0x12C/+0x134=80/120` 是
> `iMapHeight/iSmallMapHeight`，`+0x144=3/0` 是 `iPassDialogId`，
> 不是小兵金币/自然金；`RewardMatchLevel` 的 `+0x358` 是 u16=300
> 加两个布尔字节，不是 65,836。

**30 秒统计有 schema、无数据流**：`comdt_game_30sec.json` 是
`COMDT_GAME_30SEC_INFO` 的 107 个字段名，包含：

- `dwKillSoldierCnt`、`dwSoliderKillCoin`、`SoliderKillCoinByRouteID`、
  `SoliderKillCountByRouteID`（按分路的小兵击杀数/金币）；
- `dwKillMonsterCnt`、`dwKillDragonCnt`、`dwKillCnt`、`dwCoinCnt`、
  `dwRedBuffCnt`/`dwBlueBuffCnt`/`dwYellowBuffCnt`、
  `dwDestroyTowerCnt`、`dwHeroKillIntervalCoin` 等。

但主样本 `.abc` 帧流里没有这份结构：稀有 `0x01` len=65/23/12 的消息
都是 hero=0 的全局 `0x12` 标量批（`12 xx yy`），不是 30 秒统计；
`.ope`/operator 流是操作记录（Touch/Move/SkillUse/GameFrame），
也没有 comdt。**结论：30 秒精确补刀数/金币字段在 schema 层存在，
但当前回放容器没有落盘；十人经济仍以 `0x02 len=5` 流水为准。**

**模式经济字段差分**（`Level` row0 普通 vs row1 快速，
`RewardMatchLevel` row0 80003 vs row1 80004）：

| 表 | 偏移 | 普通 | 快速 | 语义 |
|---|---:|---:|---:|---|
| Level | +0x12C | 80 | 120 | **小兵金币（确认）** |
| Level | +0x134 | 80 | 120 | 小兵金币（同值） |
| Level | +0x144 | 3 | 0 | **自然金币**；快速用 buff 90005/611=10 |
| Level | +0x128 | 81 | 165 | 小兵属性候选 |
| Level | +0x130 | 81 | 165 | 小兵属性候选 |
| Level | +0x138 | 81 | 145 | 小兵属性候选 |
| Level | +0x13C | 80 | 65 | 小兵属性候选 |
| RewardMatchLevel | +0x000 | 80003 | 80004 | 行键 |
| RewardMatchLevel | +0x004 | 0 | 6 | 模式标志 |
| RewardMatchLevel | +0x00C | 173568 | 198400 | 时长/经济上限候选 |
| RewardMatchLevel | +0x4CC | 10036 | 10040 | 小兵激活延迟 |
| RewardMatchLevel | +0x4D0 | 10035 | 10039 | 小兵激活延迟 |
| RewardMatchLevel | +0x4FC | 60 | 0 | **辅助装不分摊时长** |

**修正**：`RewardMatchLevel` 的 dtab 块 `+0x358` 读到 **65,836**，
不是 300；起始金币 300 应以 `Svr2GameCore` 配置（key1=50/53）为准，
不能引用这个偏移。

**产物**：`tools/decode_level_economy.py`、
`datasets/level_economy_fields.csv`。

## 5.57 十人补刀类型拆分 + 全局 `0x12` 标量

> **已修正（见 5.91）**：下面的金额簇是**金额带**，不是单位类型。
> `0x02` 是金币变化聚合，187–219 可以是 2 个普通兵合计，也可以是
> 1 个攻城车；`player_minion_types.csv` 只能当金额分档，不能当
> “补刀类型”。逐单位归属仍缺。

**按 source4 金额簇拆兵种**（金额是实际到手金币，含分享/模式缩放；
簇边界是候选，不是表内硬编码）：

| 簇 | 金额 | 对应（候选） |
|---|---:|---|
| melee | 80-95 | 近战兵/战士（base 60 缩放） |
| ranged | 96-120 | 远程兵/法师（base 90） |
| elite | 121-159 | 法师变体/河道之灵（base 117/140） |
| siege | 180-196 | 弩车（base 192） |
| cannon | 197+ | 炮车/超级兵（base 200+） |

十人（事件数/金币）：

| 玩家 | melee | ranged | elite | siege | cannon |
|---|---:|---:|---:|---:|---:|
| Vetymoment | 0/0 | 0/0 | 0/0 | 14/2,639 | 7/1,431 |
| 桑忆终尘启 | 0/0 | 0/0 | 0/0 | 11/2,064 | 8/1,603 |
| 布鲁BIUBIU | 16/1,417 | 5/527 | 3/395 | 0/0 | 0/0 |
| 双枪踏浪行 | 9/787 | 6/616 | 1/135 | 4/776 | 0/0 |
| 李不信有归途 | 8/696 | 7/720 | 0/0 | 4/776 | 0/0 |
| 酒梦灵心醉 | 12/1,055 | 7/722 | 2/264 | 0/0 | 0/0 |
| 碗面加香菜 | 13/1,143 | 6/623 | 0/0 | 1/194 | 0/0 |
| 备水一站. | 4/348 | 5/508 | 0/0 | 3/582 | 0/0 |
| 佚名(*: | 0/0 | 0/0 | 0/0 | 3/562 | 1/219 |
| 含泪吃兵线呢 | 0/0 | 0/0 | 0/0 | 2/382 | 0/0 |

→ 金额带的分布只能说明“谁的事件偏大额/偏小额”，**不能推出**
“两个只吃弩车/炮车的是边路”；Vetymoment/桑忆全落在 187–219
更可能是 AoE 一次收多个兵或攻城车，而不是“只吃弩车”。

**全局 `0x12` 标量**：帧流 hero=0 的 `0x01` len=12/23/65 消息里，
`0x12` 标量约 **34,690–38,324**，与十人 source4+source43+source6
总和 34,370 接近，但上下波动（不是单调累计）。候选语义：
**全局当前金币/经济总量**（购买装备会回落），不是逐人快照；
逐人仍以 `0x02 len=5` 为准。

**产物**：`datasets/player_minion_types.csv`。

## 5.58 十人经济总表 + source5 边界

**十人经济合成**（列和 = total；system = 4/6/43 之外的其余来源）：

| 玩家 | 小兵 | 野怪 | 击杀/助攻 | system | 合计 |
|---|---:|---:|---:|---:|---:|
| Vetymoment | 21/4,070 | 1/191 | 1/102 | 7/588 | 4,951 |
| 桑忆终尘启 | 19/3,667 | 0/0 | 1/102 | 2/275 | 4,044 |
| 双枪踏浪行 | 20/2,314 | 0/0 | 1/203 | 11/1,358 | 3,875 |
| 李不信有归途 | 19/2,192 | 0/0 | 0/0 | 14/1,183 | 3,375 |
| 备水一站. | 12/1,438 | 0/0 | 0/0 | 18/1,804 | 3,242 |
| 布鲁BIUBIU | 24/2,339 | 0/0 | 2/305 | 3/307 | 2,951 |
| 酒梦灵心醉 | 21/2,041 | 0/0 | 3/508 | 4/338 | 2,887 |
| 碗面加香菜 | 20/1,960 | 0/0 | 2/405 | 2/162 | 2,527 |
| 佚名(*: | 4/781 | 3/541 | 0/0 | 21/1,077 | 2,399 |
| 含泪吃兵线呢 | 2/382 | 4/720 | 0/0 | 19/1,017 | 2,119 |

**source5 边界**：小额 31–73 不是固定 30 秒 tick——相邻间隔从 44 到
4,000+ 帧不等，更像“系统/其他金币”混合（自然金、辅助装、附近击杀分成、
目标奖励）。大额 131–146/231–254 是低频事件，候选为推塔/龙/一血类
奖励，但**没有结算 KDA/经济面板对拍，不能逐项定名**。

**玩家块**：`.abc` 头部十人块（1,517B/人）是位打包结构，玩家名在
块 +0x10，heroID 在 +771/+1415/+1445；周边字段不是对齐 u32，
**最终 KDA/金币不在简单偏移里**，需要位级 schema 才能解。

**产物**：`datasets/player_economy_report.csv`。

## 5.59 十人技能升级时间线 + soldierWave 边界

**技能升级**：`0x02 flag=0x87 len=7`，135 条，覆盖全部 10 人；
数据 `00 00 00 actorID:u8 slot:u8 level:u8 00`。每人的最终技能等级：

| 玩家 | slot1 | slot2 | slot3 | slot4 |
|---|---:|---:|---:|---:|
| 双枪踏浪行 | 5 | 5 | 2 | — |
| 李不信有归途 | 5 | 5 | 2 | 1 |
| 含泪吃兵线呢 | 5 | 4 | 1 | — |
| 布鲁BIUBIU | 5 | 5 | 1 | — |
| 备水一站. | 5 | 5 | 2 | — |
| 佚名(*: | 5 | 4 | 2 | — |
| 桑忆终尘启 | 5 | 3 | 2 | — |
| Vetymoment | 5 | 4 | 2 | — |
| 碗面加香菜 | 5 | 4 | 2 | — |
| 酒梦灵心醉 | 4 | 5 | 2 | — |

actorID 是单位 actor（8/44/65/19/51/12/30/58/23/37），不是 hero 实体。
产物：`datasets/player_skill_upgrades.csv`。

**soldierWave 边界**：metadata 有 `ResSoldierWaveInfo` 字段
（`dwSoldierWaveID`、`dwNextSoldierWaveID`、`dwRepeatNum`、
`dwRepeatTimeTick`、`dwStartWatiTick`、`dwIntervalTick`、
`iSpawnInterval`、`astNormalSoldierInfo`、`astBranchWaves`），但
**825 张 C# databin 和 `dtab_all` 里都没有这张表**；`Level` 行内
+0x74 只存 `3041/3042/3043`、`4021/4022/4023` 这些 waveID。
因此 3xxx/4xxx/5xxx 的**名称**仍不能从当前 dump 表内确认；
“3=近战、4=远程、5=炮车、6=超级”是按金币递增和 Level 分组推断。

**产物**：`datasets/player_skill_upgrades.csv`。

## 5.60 `02/80` 与录屏对拍：仍不能定名

快速赛样本 `20261028_135516` 的 `02/80`：
`a=2` 值 1024/2304/5376（seq 905/1105/1998），`a=5` 值 2560/6400
（seq 1163/2415）；原始 args[7]=4/9/21/10/25，×256 得上述值。

录屏 OCR（`video_ocr/2a7206b09ea8cc35.json`）给出的对照：

| 时间 | 蓝队金币 | 红队金币 | 孙膑当前金币 |
|---:|---:|---:|---:|
| 30s | 1,600 | 1,600 | — |
| 50s | 3,200 | 3,800 | — |
| 68s | 4,600 | 6,300 | 340 |
| 74s | 5,100 | 6,700 | — |
| 90s | 6,700 | 7,500 | 800 |

- `02/80` 的 1,024/2,304/5,376 **不等于**团队金币，也不等于孙膑
  当前金币；
- 录屏 `selection` 的孙膑“金币”是 300→1,629（36–115s），与
  `02/80` 也不一致；
- 因此 `02/80` 的 `a=2/a=5` 语义仍是**候选**（金币/经验或某种
  累计/差分），不能拿“累计金币”下定论。主样本的十人经济仍以
  `0x02 len=5` 流水为准。

**结论**：快速赛的 `02/80` 需要更多样本/时间对齐才能定名；当前
可确认的是原始值 = `args[7] × 256`，以及它随 seq 递增。

## 5.61 C# 表行布局模型：+0 行键、+8 字段、stride=N×8+8

**模型**（54 张已验证表全部满足）：

```
row:  +0x00 rowKey:u32 | +0x04 reserved:u32 | +0x08 field[0] | +0x10 field[1] | …
      stride = N*8 + 8   （N = C# 字段数，不含行键）
```

`ResHeroDataConf`（stride 144、17 字段）实证：+0=1、+4=0、
+8=0xb27c20ae/0x41600（str1）、+16=0xb27c20ae/0x41c00（str2）……
`ResSkinKolTips`（stride 16、1 字段）：+8=0xbaf2acd0/0x272e00。
`ResMasterMatchSettleRankNoShow`（stride 40、4 字段）：+8/+16/+24 为 0，
+32=0x8854f4cf/0x3a00（str4）。

**v4 校验**（`tools/table_field_map4.py`，对 `table_field_map.csv`
的 10,453 个单元按 +8+i×8 重新分类）：

- **2,243 个单元 ok**；
- **169 张表全字段 ok**（代表：WealStep 18/18、ResHeroDataConf 17/17、
  HeroEventDialog 17/17、HeroPracticeLobbyCfg 15/15、
  IntimacyRelationCfg 11/11、MatchBadge 10/10、TaskTriggerInfo 7/7）；
- 1,159 个单元类型不符（str/int/float 分类边界，需按字段名再核）；
- **7,051 个单元 out_of_range**：`cell_index` 超出 8 字节单元数，
  对应数组/内联结构体，是 451 张布局剩下的主要部分。

**产物**：`tools/table_field_map4.py`、`datasets/table_field_map4.csv`。

**v5 尝试（失败，保留作反例）**：按字段名前缀（`str/sz`→str、
`dw/i/b`→int、`f`→float、`_length`→int）重判类型，结果只有
1,322 个 ok、8,877 bad、0 张全通过表。原因是映射表里的字段名/
`cell_index` 本身不总与原生行对齐；**v4 的 2,243 ok / 169 张全通过
仍是当前最佳**。

**48 张已解码 CSV 的逐字段校验（强验证）**：`tools/csv_field_offsets.py`
按 `offset = 8 + i*8` 逐字段比对，**48 张表、131 个字段全部 100%
通过**。关键修正：**整数也占 8 字节单元**（低 u32 是值，高 u32 为 0），
不是 4 字节；例如 `ResHeroDataConf` 的 `iViability` 在 +0x60，
下一个字符串字段在 +0x68。此前“整数 4 字节”的变宽假设作废。
产物：`datasets/csv_field_offsets.csv`。

**内联数组样本**（`RewardMatchLevel`，行 0/1 相同）：

- `+0x394 = 4`（length）；
- `+0x398 = 2`（起始等级/类型候选）；
- `+0x39C` 起 4 个 8 字节元素：`(4000,3)`、`(6000,4)`、
  `(8000,5)`、`(10000,6)`；
- `+0x3BC = 10000` 是数组后的下一个字段，不是第 5 个元素。

→ 内联数组规则：`_length:u32` 后紧跟 `length × 8` 字节元素；
元素可以是 `(int,int)` 对，也可以是 `(hash,offset)` 字符串 ref。
`RewardMatchLevel` 的嵌套 `ResDT_LevelGamePlayInfo` 在 +0x34C
使用的是 **4 字节字段**（如 +0x4FC=60/0），不是 8 字节单元模型，
这是 7,051 个 out_of_range 单元的主要来源，也是下一层要解的
嵌套结构体布局。

## 5.62 `ResDT_LevelGamePlayInfo` 部分字段表

> **已修正（见 5.69）**：0x394=`dwSoulAllocID`、0x3E8/0x3EC=
> `iExtraSkillId/iExtraSkill2Id`、0x4CC/0x4D0=外层消耗物品 ID、
> 0x4FC=`dwRankType`；0x358 的 u16 才是 300。

`RewardMatchLevel` 行 80003（普通）/80004（快速），嵌套结构从
+0x34C 起；已确认/候选字段：

| 偏移 | 普通 | 快速 | 字段 | 置信 |
|---:|---:|---:|---|---|
| +0x34C | 80 | 80 | 未知 | 低 |
| +0x358 | 65,836 | 65,836 | 未知 | 低 |
| +0x394 | 4 | 4 | `astExpCompensateDetail_length` | 高 |
| +0x398 | 2 | 2 | 未知 | 低 |
| +0x39C | 3→4000;4→6000;5→8000;6→10000 | 同 | `astExpCompensateDetail` | 高 |
| +0x3BC | 10,000 | 10,000 | 数组后字段 | 低 |
| +0x3E8 | 90,003 | 90,003 | `dwCompensateExpBuffID` | 高 |
| +0x3EC | 90,005 | 90,005 | `dwCompensateGoldBuffID` | 高 |
| +0x4C8 | 168,034,561 | 167,903,489 | 字符串 ref/hash | 低 |
| +0x4CC | 10,036 | 10,040 | 小兵激活延迟 | 中 |
| +0x4D0 | 10,035 | 10,039 | 小兵激活延迟 | 中 |
| +0x4FC | 60 | 0 | `dwAidNotShareIncomeLastTime` | 高 |

**注意**：`wOriginalGoldCoinInBattle`（期望 300）在本行**没有找到**；
300 仍以 `Svr2GameCore` 配置为准。该结构混用 4 字节字段、字符串 ref
和内联数组，原生偏移不连续，剩余 74 字段需按字段名逐段对位。

**产物**：`tools/decode_level_play_info.py`、
`datasets/level_play_info_fields.csv`。

## 5.63 原生表 rowID→名称（20 张、49,202 条）

`tools/native_table_names.py` 对目录中名称覆盖最高的 20 张原生表，
按“ref 首次出现顺序 = 池中 CJK 名称顺序”生成 rowID→名称映射。
产物：`datasets/native_table_names.csv`（49,202 条）。

表用途识别（首名称）：

| 表偏移 | stride | rows | 首名称 | 推断用途 |
|---:|---:|---:|---|---|
| `0x3A47220` | 256 | 3,819 | 北京市 | 地区/地址 |
| `0x74AC508` | 112 | 3,432 | 双抗+10 | 天赋/属性 |
| `0x6CCAC30` | 40 | 439 | 默认 | 通用配置 |
| `0x560BAF4` | 184 | 3,166 | 1月6日0点上架 | 商店/上架计划 |
| `0x6225340` | 72 | 393 | 廉颇 | 英雄 |
| `0x3C4DA00` | 88 | 669 | 双星英雄 | 英雄/皮肤标签 |
| `0x3D1A9B0` | 1,144 | 1,947 | 廉颇 | 英雄（大行） |
| `0x59F0AD0` | 200 | 688 | 峡谷新秀 | 称号/成就 |
| `0x5994654` | 32 | 197 | 默认 | 通用配置 |
| `0x695F084` | 208 | 205 | 关键群控 | 高光/统计标签 |
| `0x76458BC` | 168 | 195 | 新功能-小屋装修 | 功能引导 |
| `0x6F72F30` | 64 | 371 | 基础首包资源 | 资源包 |
| `0x61388A8` | 168 | 243 | 彭云飞 | 选手/职业 |
| `0x56E5140` | 472 | 1,652 | 廉颇 | 英雄 |
| `0x17DB720` | 576 | 27,663 | 碎银 | 货币/道具 |
| `0x111C3C` | 896 | 201 | 廉颇 | 英雄 |
| `0x532D5CC` | 184 | 3,120 | 庞统 | 英雄 |
| `0x6DD4714` | 160 | 2,207 | 一技能释放… | 技能提示 |
| `0x6EFF350` | 64 | 299 | 完成连招训练… | 训练/熟练度 |
| `0x720AD38` | 16 | 682 | 上路小帅宝 | AI/机器人名 |

→ 这些表已经能“按 rowID 查到名称”，但数值字段仍需按 v4 的
`+8+i×8` 模型或嵌套结构逐表对位；英雄表（廉颇/庞统）和天赋表
（双抗+10）是最值得下一步做字段映射的。

## 5.64 C# 表字符串解析：ref 首次顺序 = 本地池字符串顺序

> **已被 5.79 取代/补全**：位置法（`value32 >> 6`）对 919 张表
> 全部精确；首次顺序法只在约 300 张表正确，后续以 5.79 为准。

C# 表的字符串 ref 是 `(hash, global_offset)`，global_offset 不在
本地池；但**本地池里的字符串顺序与 ref 的首次出现顺序一致**，
和 normalMonster 同一套方法。实证：

- `ResSkinKolTips`：2,469 个 ref ↔ 2,469 条池字符串，前 10 条
  （扁鹊·无尽旅途、廉颇 寅虎·御盾、孙膑 寅虎·展翼…）逐条对齐；
- `ResHeroDataConf`：17 个字段解出“游戏职业 / 法师 / 先锋坦克 /
  传送 / 前期…”；
- `heroLabelInfo`：解出“团战控制器 / 团战发动机…”及各级解锁描述。

`tools/decode_decoded_csvs.py` 对 48 张已解码 CSV 按
`offset=8+i×8` 读字段、按首次顺序解析字符串，输出
`datasets/decoded_text/` 下 **46 张可读 CSV**（2 张因首行全零
无法唯一匹配 dc.db 表，暂跳过）。

→ 至此 C# 表不仅能“按 rowID 查名称”，还能把字符串字段读成
**实际中文文本**；数值字段按 v4 的 8 字节单元直接读。下一步
可以把同一套解析套到英雄表/天赋表/装备表。

## 5.65 C# 表批量解码：436 张可读 CSV

`tools/decode_csharp_all.py` 对 `table_field_map4.csv` 里所有含 ok
单元的表批量解码：

- 440 张表有 ok 单元，**436 张成功输出**到
  `datasets/decoded_csharp_all/`；
- 48 张有 `tables_decoded` CSV 的表使用**真实字段名**表头；
- 其余表使用 `cell_N` 通用列名（映射表的字段名含行键、整体错位，
  避免误标）；
- 字符串 ref 按首次出现顺序解析成本地池文本，整数按 8 字节单元
  低 u32 读取。

示例：

- `492_ResHeroDataConf.bytes.csv`：`游戏职业/法师/先锋坦克/传送/前期…`；
- `342_MatchBadge.bytes.csv`：`成都AG超玩会/2023年KPL夏季赛…`。

→ 这是目前最大的一次表数据解锁：从 46 张可读表扩到 **436 张**；
剩余主要是数组/嵌套结构体列（`cell_N` 里空/越界的部分）。

## 5.66 `0x1f` = 高光通知，type = 高光标签 ID

高光标签表 `0x695F084`（205 行，名称 189/189 覆盖）给出标签名；
跨 12 个样本统计 `0x1f` 的 type 字节：

| type | 次数 | 标签 |
|---:|---:|---|
| 1 | 31 | 关键群控 |
| 2 | 8 | 关键群控 |
| 5 | 1 | 团战中使用技能控制敌方多名英雄并造成击败 |
| 93 | 1 | 【逆转乾坤】杨戬短时间内刷新多次技能后击败敌方英雄 |
| 94 | 2 | 杨戬短时间内刷新多次技能后击败敌方英雄 |
| 244 | 1 | 表外（未知） |

→ `0x1f` 是**高光标签通知**，不是击杀/助攻通知；type 直接是
标签表 rowID。此前“0x1f 是 highlight”的推断现在有了标签名。
`0x1f` 的 args 还带 `i32` 数值和若干 ID，具体字段仍待拆。

**产物**：标签名在 `datasets/native_table_names.csv`（表
110,489,732 = `0x695F084`）。

## 5.67 原生英雄表：`0x111C3C` 是基础属性表

5 张原生表的性质（智能体 A 解码）：

| 表 | 行数 | 单元 | 性质 |
|---|---:|---:|---|
| `0x6225340` | 393 | 8 | OPE 问题/主播代言（每英雄 3 行） |
| `0x111C3C` | 201 | 111 | **英雄基础属性/配置** |
| `0x3D1A9B0` | 1,947 | 142 | 英雄皮肤（皮肤 ID → 英雄 ID/皮肤名） |
| `0x56E5140` | 1,652 | 58 | 皮肤上架/售卖（日期、价格、描述） |
| `0x532D5CC` | 3,120 | 22 | 英雄语音事件 |

`0x111C3C` 候选属性列（134 个正常英雄行）：

| 列 | 字节偏移 | 字段 | 范围 | 示例 |
|---|---|---:|---|---|
| `cell_10` 高 u32 | +0x5C | **MaxHp 最大生命** | 2,793–3,725 | 廉颇 3,675；小乔 3,200；赵云 3,468 |
| `cell_12` 低 u32 | +0x68 | **PhysicalAttack 物理攻击** | 140–207 | 廉颇 198；小乔 163；盾山 207 |
| `cell_11` 低 u32 | +0x60 | **PhysicalDefense 物理防御** | 23–88 | 廉颇 78；小乔 44；牛魔 88 |
| `cell_14` 高 u32 | +0x7C | **MoveSpeed 移速×10** | 3,600–3,900 | 廉颇 3,750；小乔 3,650；赵云 3,850 |

**名称映射修正**：原 `native_table_names.csv` 只过滤 CJK 字符串，导致
部分表名称错位（如 `0x111C3C` 的 106 行被标成“正义爆轰”，实际是
“小乔”）。智能体 A 改为**全部池字符串首次出现顺序**重建，5 张表的
ref 数与池字符串数精确相等（631/1748/10251/3626/3694），名称全部
解析；旧 CSV 的一致率仅 3/267、1/201、6/1947、6/1652、1084/3120。
→ 对“池里全是文本”的表用全字符串顺序；对 normalMonster 这种
池里混路径的表仍用 CJK 过滤。

**产物**：`tools/agent_hero_tables.py`、
`datasets/agent_hero_tables/`（5 张表 CSV + `_attribute_candidates.csv`）。

## 5.68 `0x1f` 28 字节高光通知的字段

44 条 `0x1f` 样本（12 个文件）统一为 28 字节：

```
1f | tag:u8 | a:u32BE | b:u32BE | c:i32BE | d:u32BE | e:u32BE |
   actor:u16BE | tail
```

- `tag` = 高光标签 ID（表 `0x695F084`；1/2=关键群控、
  93/94=杨戬逆转乾坤、5=团战控制描述、244=表外）；
- `a` 观测 1–42，`c` 观测 -45..+45，`d` 观测 0/4/5/10/12；
  候选为分数/时长/经济差，未定名；
- `actor` 观测 0x0068–0x03C9（104–969），与 `0x1e` 的 victim ID
  同量级，**候选为高光归属的英雄单位 actor ID**；
- `tail` 多数是 `0100000000`，个别（如 seq 2188）是
  `0100040f1a`，结构仍待拆。

示例（主样本）：

- seq 2188 hero 338：`tag=5, a=12, c=-25, d=10, actor=0x031e(798)`；
- seq 7209 hero 1558：`tag=244, a=42, c=-45, d=12, actor=0x00ca(202)`；
- seq 11173 hero 1729：`tag=2, a=19, c=-18, d=4, actor=0x00ca(202)`。

→ `0x1f` 是**高光通知**，不是击杀/助攻；tag 已闭环，a/c/d/actor
的语义仍待更多样本对拍。

## 5.69 重要修正：Level 80/120 不是小兵金币；0x358 的 u16 才是 300

**1. `RewardMatchLevel` +0x358**（原始字节复核）：

- `u16 @0x358 = 300` → `wOriginalGoldCoinInBattle`；
- `byte @0x35A = 1` → `bIsOpenExpCompensate`；
- `byte @0x35B = 0` → `bIsOpenCoinCompensate`；
- 之前读到的 `u32 @0x358 = 65,836` 是 `0x0001012C`，即
  **300 + 两个布尔字节**合在一起，不是独立字段。
- 80003/80004 的池名是 **金币大奖赛 / 点卷大奖赛**，不是普通/快速。

**2. `Level.bytes` 行 0/1 不是普通/快速**：行类是
`ResLevelCfgInfo`，行 0/1 是 level id 1/2（基础教学 / 3v3入门教学）：

| 偏移 | 行0 | 行1 | 字段 |
|---:|---:|---:|---|
| +0x128 | 81 | 165 | `iMapWidth` |
| +0x12C | 80 | 120 | **`iMapHeight`（不是小兵金币）** |
| +0x130 | 81 | 165 | `iSmallMapWidth` |
| +0x134 | 80 | 120 | **`iSmallMapHeight`（不是小兵金币）** |
| +0x138 | 81 | 145 | `iBigMapWidth` |
| +0x13C | 80 | 65 | `iBigMapHeight` |
| +0x144 | 3 | 0 | **`iPassDialogId`（不是自然金币）** |
| +0x178 | 17,000 | 20,000 | `dwReviveTime` |

→ 之前 5.56 的“`+0x12C/0x134=80/120` 小兵金币、
`+0x144=3/0` 自然金币”是**误读**；80/120 只是地图高度，
3/0 只是过关对话 ID。真实的小兵 80/120、自然 3/10 来源仍未定位
（不在 Level，也不在 `@0x106464` 的 120/126 里），需要另找表/GameCore。

**3. `ResDT_LevelGamePlayInfo` 真实布局**（智能体 B，交叉 8 张
level 表 stride 验证）：

- 行：prologue 0x10 → common 0x348 → **gameplay 基址 0x358，
  长 0x170** → 0x4C8 外层尾段 → 行尾 0x500；
- 不是“每字段 8 字节”单元模型，而是 **C# 顺序布局 + 自然对齐**：
  byte 1 / w 2 / i,dw,f 4 / str,ull 8；`_length` 不序列化；
  `_bytes` 是内联固定 buffer；
- high：0x358 u16=300、0x368/0x370/0x378/0x380 四个地图字符串、
  0x38C/0x390 `fMapFowScale`/`fBigMapFowScale`=0.92、
  0x398..0x3BC 5×`{dwLevelDiff,dwExtraRate}`=(2,4000)…(6,10000)、
  0x3E8/0x3EC=`iExtraSkillId`/`iExtraSkill2Id`=90003/90005、
  0x440/0x448 音乐/银行字符串、0x4CC/0x4D0 外层消耗物品
  10036/10035；
- medium：0x34C=80（`dwMinCreditValueRequirements`）、
  0x394=4（`dwSoulAllocID`）、0x424/0x428=5500/10000
  （`iSoldierActivateCountDelay2`/`iSoldierActivateDelay`）、
  0x438/0x43C=917010/917011（补偿 buff）、0x4FC=60/0（`dwRankType`）。

**4. 对 5.62 的修正**：

- 0x394 不是数组长度，是 `dwSoulAllocID=4`；
- 0x3E8/0x3EC 不是补偿 buff，是额外技能 ID 90003/90005；
- 0x4CC/0x4D0 不是小兵延迟，是外层消耗物品 ID；
- 0x4FC 不是 `dwAidNotShareIncomeLastTime`（该字段在 0x4AC=0），
  是 `dwRankType`。

**产物**：`tools/agent_level_play_info.py`、
`datasets/agent_level_play_info.csv`（109 行：high 23 / medium 72 /
low 14 / unknown 3）。

## 5.70 `0x29` / `0x38` / `0x23` / `0x20` 稀有消息

跨全部 batch 样本统计：

- **`0x29`（len=17，473 条）**：`slot:u32 + skillID:u32 + level/param:u32
  + 0`（全大端）。观测：
  - skillID=91060（最多，= 小乔 **铸魂·星华缭乱**）、
    900011（= **打包濒死队友**）、11991（**不是本表 skillID**；
    回放里是 event seq/actor_id；若为 91991 = 公孙离 铸魂·孤鹜断霞）；
  - slot 8/11/12/18/22/24/25/33/57/65；
  - 第三字段 15/16/24/32/1513/2340/7113/-1，候选等级/冷却/参数；
  - 另有 85 条 `(slot,0,0,0)`，可能是取消/召回类无技能事件。
- **`0x38`（len=29，177 条）**：`timestamp:u32 + count:u32 + 0×4
  + type:u32`（全大端）。type=**546601/546602/546603**，正好是
  `0x085729/0x08572A/0x08572B`，与旧记录的“尾部 08 57 2a/2b”
  一致；timestamp 如 5,417,630，count 0/1/2。候选为
  目标/野怪/先锋类事件。
- **`0x23`（len=2，2,617 条）**：`23 01`，是**高频** per-hero
  bool/状态，不是稀有击杀事件。
- **`0x20`（len=20，7 条）**：`20 + 5e + u32×? + actor + tail`；
  样本 `20 5e 03000000 18000000 00000000 000000b7 01000000 89`，
  与 `0x1f` 高光成对出现，字段仍待拆。

## 5.71 真实 80/120 来源：`normalMonster` 的模式变体行

> **已修正（见 5.75）**：80/120 是 normalMonster 模式变体；
> `@0x106464` 的 120/126 是结算经验，不是小兵金币。

`normalMonster` 不是“每兵种一行”，而是**按模式/玩法分行的变体**。
按 gold=80/120 过滤后可直接对上用户观测的普通 5v5 与快速赛：

**普通 5v5，gold=80（蓝/红方战士）**：

| rowID | 名称 | HP | exp1/2/3 | actor | ref2 |
|---:|---|---:|---|---:|---|
| 1660002/1660032 | 蓝/红方战士 | 7000/1860 | 180/60/4150 | 10010 | 0x6056600/0x605b100 |
| 4012001/4012007 | 蓝/红方战士 | 7000/1860 | 180/60/4150 | 10010 | 同上 |
| 4010001/4010007 | 蓝/红方战士 | 7000/1860 | 180/60/4150 | 10010 | 同上 |
| 1010301/1010307 | 蓝/红方战士 | 7000/1860 | 180/60/4150 | 10010 | 同上 |
| 2/5 | 蓝/红方法师 | 5500/1600 | 0/0/3000 | 10002 | 0x5e2df00/0x5e31a00 |

**快速赛，gold=120（蓝/红方战士）**：

| rowID | 名称 | HP | exp1/2/3 | actor | ref2 |
|---:|---|---:|---|---:|---|
| 1301/1304 | 蓝/红方战士 | 5000/2647 | 210/90/3000 | 10000 | 0x5e2cd00/0x5e30800 |
| 21010/21020 | 蓝/红方战士 | 5000/2480 | 0/0/3000 | 10000 | 同上 |

**快速赛，gold=120（法师）**：6501/6504、65012/65041、7201/7204、
17/20、1710/2010（HP 8500、actor 10012/10002/100121、exp 3000–4200）。

→ **80/120 不是 Level 的地图字段，而是 normalMonster 的模式变体行**：
普通 5v5 用 actor 10010/ref2 0x6056600 的 80 金币行；快速赛用
actor 10000/ref2 0x5e2cd00 的 120 金币行。`@0x106464` 的 120/126
是另一层“族×分路×档位”表，不是这里的模式基数。
自然金币：快速 10 已由 buff 90005/611 提供；普通 3 仍待找
（可能是另一个 buff 行或 GameCore 规则）。

**产物**：`datasets/minion_mode_map.csv`（52 行，`gold_bucket`=80/120；
`5262xxx` 标注 10v10，教学/召唤行有 `note`）。注意 `gold_bucket`
只是按金币分桶，不等于确认的游戏模式；实际模式要结合 rowID 家族/
ref2/actor 判断。

## 5.72 十人帧命令画像

`abc_frame_cmds.csv` 跨 25 个文件共 **10,714 条** 12 字节命令；
主样本 10 人（按 file+hero 对 roster）：

| 玩家 | 命令数 | 主要类型 |
|---|---:|---|
| 佚名(*: | 172 | StopMove 142、AttackPlayer 15、AutoAI 9 |
| 双枪踏浪行 | 109 | AttackPlayer 91、SwitchCaptain 12、AutoAI 6 |
| 碗面加香菜 | 99 | StopMove 82、AttackPlayer 11、AutoAI 6 |
| 含泪吃兵线呢 | 98 | StopMove 66、AttackPlayer 19、SwitchCaptain 6 |
| 酒梦灵心醉 | 74 | AttackPosition 53、AttackPlayer 13、AutoAI 7 |
| 布鲁BIUBIU | 46 | AttackPlayer 20、AttackPosition 19、AutoAI 7 |
| Vetymoment | 34 | AttackPlayer 25、AutoAI 9 |
| 备水一站. | 27 | SwitchCaptain 18、AutoAI 7 |
| 李不信有归途 | 25 | AutoAI 11、AttackPlayer 7 |
| 桑忆终尘启 | 19 | AttackPlayer 10、AutoAI 9 |

命令类型：StopMove / AttackPosition / AttackPlayer / UseCurveTrackSkill /
SwitchAutoAI / SwitchCaptain / SwitchSuperKiller / SwitchGodMode /
SwitchAllGodMode / TestCommandDelay。`actor_id` 是单位 actor，
`cmd_seq` 以 256 为步长。

**产物**：`datasets/player_command_stats.csv`（677 行）。

## 5.73 `0x20` 20 字节高光详情

7 条 `0x20` 样本统一为 20 字节：

```
20 | type:u8 | a:u32BE | b:u32BE | c:u32BE | d:u32BE | actor:u16BE
```

- `type` = 高光标签 ID（与 `0x1f` 同一张表）：94/93=杨戬逆转乾坤、
  18=完美开团、3=关键群控、2=关键群控、21=关键团战输出；
- `actor` = 目标 actor：137/109/21616/1690/1697/132/21641
  （>10000 的可能是英雄实体，百级的是单位）；
- `a` 观测 0x01000000/0x03000000/0x08000007/0x08000008，
  高字节 1/3/8 候选计数/等级；
- `b` 观测 0x17/0x18/0x20/0x26/0x27/0x3A/0x4B 高位字节
  （23/24/32/38/39/58/75），低于英雄 ID 段，候选技能/单位 ID；
- `c`=0/1/3；
- **`d` 的高字节是英雄 ID**（已对上：183=雅典娜、112=鲁班七号、
  116=阿轲、135=项羽、137=司马懿；5/7 命中；35/222 例外）；
- `actor` 是目标 actor（137/109/21616/1690/1697/132/21641）。

→ `0x20` 的 `d` 高字节可当英雄 ID 用；tag 里的英雄和 `d` 英雄
可能不同（高光归属 vs 受害者/助攻者），仍需更多样本确认。

→ `0x1f` 是高光通知、`0x20` 是高光详情/目标；两者 type 同表。

## 5.74 重要纠正：0x4614 不是 buff 行；真正 buff 表是 0x8268ac

**1. `0x4614` 是 PVE 关卡表 `0x364c` 的 row5 尾部**

`0x364c` 是 `stdr`，stride 656、rows 35、data `0x36e4`、池 `0x9094`：

- `0x4614 = row5(0x43b4) + 0x260`，读的是 row5 尾部的 buff 引用对；
- `0x4610 = row5 + 0x25C = 90000`，`0x4614 = 90005`；
- row6 从 `0x4644` 开始（key=12），所以从 `0x4614` 读会跨 row5 尾部
  + row6 本体，形成“假 90005 buff 行”；
- 609/610/611、602/603/604 是 `0x5902c` 表的**王者小店主播 ID**
  （心态/失眠芳/船长、昧昧/小强/斗鱼Sao易），不是 buff effect；
- 真正的 buff 引用对在 PVE 行尾 `+0x25C/+0x260`：
  `90000/90005`、`90003/90007`、`90000/0`。

**2. 真正的主 buff 表 `0x8268ac`**

- `stdr`，stride **1080**，rows **13,558**，strings **16,994**，ref 1:1；
- 行：`+0x00 buffID`、`+0x14/+0x3C 链接 ID 候选`、`+0x78 名称 ref`、
  `+0x80 描述 ref`、`+0x90 prefab ref`、`+0xB8 范围候选`、
  `+0xD0 类型候选`、`+0xD4/+0xD8/+0xDC 参数`、
  `+0x188/+0x240/+0x2F8 三个内联 effect slot`（`id:p1:p2:p3`，
  65535=空）、`+0x3B8/+0x3C0 字符串 ref`；
- effect slot 分布：12,435 行无、896 行 1 个、172 行 2 个、55 行 3 个。

**3. Buff effect 子表 `0x3ba41a8`**

- `stdr`，stride **184**，rows **1,309**，strings **2,322**，ref 1:1；
- 行：`+0x00 buffID`、`+0x10/+0x18/+0x20 名称/描述/prefab ref`、
  `+0x28 count/type 候选`、`+0x2C.. 数值参数`、`+0xB0 子 buff ID`。

**4. 90005/90003 的真实身份（按表命名空间）**

| 表 | 90005 | 90003 |
|---|---|---|
| `0x8268ac` | 守护者加速部分（离开基地加速并衰减） | 瞬时治疗 |
| `0x3ba41a8` | 回复法力值 | 暴君被动 |
| `0x1ce47c` | 回城 | 恢复 |

→ 等级表的 `dwCompensateGoldBuffID=90005`/`ExpBuffID=90003` 在原生
buff 表里**不是金币/经验名称**；真正的补偿行是 `9998968/9998969`、
`917010/917011`。ID 是表内命名空间，不能跨表解释。

**5. 金币/经验/辅助装相关 buff（节选）**

- 金币：`600005 增加金钱经验`、`909089 人机挑战-增加金币`、
  `922105 增加金币效果`、`9998969 少人方金币补偿`、
  `917011 学识宝石-辅助装备金币补偿`、`917012/917013 学识宝石金币补偿`、
  `917019/917020 学识宝石-兵线金币掉地（上限 450/600）`、
  `3917010/2917010 快速赛/无限乱斗学识宝石加钱`、
  `60092 边境突围神符`、`186900 太乙加钱`、`229070 10V10神兵金币`、
  `16606112 金币物资`、`6009201–6009226 掉落金钱`、
  `20260395 天黑金币`、`577376 增加金钱`。
- 经验：`60013 5V5先知主宰BUFF`、`9998968 少人方经验补偿`、
  `922103 众生和鸣`、`917010/917014 学识宝石经验`、
  `3917014/2917014 快速赛学识宝石分钱`、`4012300 辅助装备经验补偿`、
  `16606113 经验物资`、`148810 神职者`、`3ba41a8/50014 死了给全队经验`、
  `16606211 天元空间经验`。
- 辅助装：`917010/917011/917014 学识宝石`、
  `917019/917020 兵线经济50%掉地`、`917736/917741 游走装`、
  `4012300/4012301 辅助装备经验/金币补偿`、
  `101017010/101017012/101017013 学识宝石变体`、
  `3ba41a8/91815 辅助装解放`、`91816/91817 补偿`、
  `10101816 快速模式补偿`、`91747 分经济`。
- 打野/分享：`3ba41a8/91562 龙鳞利剑游击`、`91563 浴火之怒共赢`、
  `91564/91572–91575 游击`、`915340 黄刀`、`1660571 收益植物`、
  `8268ac/915731/915734/915735 游击`、`5150905/5150909 兵线强化/收入提升`、
  `1000047 金币经验区`、`60007 小龙BUFF`、`734000–734008 自然之力`。

**6. 补刀/自然金币**

- 两张 buff 表里**没有补刀/分享**的独立行；只在教学文本表出现；
- **自然金币也没有独立 buff 行**；“自然”只命中 PVE 天赋“自然之力”；
  自然金币仍更像 `Level`/GameCore 代码规则（3/10），不是 buff 字段。

**产物**：`tools/agent_native_buffs.py`、
`datasets/agent_native_buffs.csv`（14,914 行 × 19 列；14,867 条 buff，
1,123 行有内联 effect；关键词命中 129 行：gold 51、exp 23、support 27、
compensate 19、economy 27、lane 20、natural 13、income 9）。

## 5.75 重要纠正：`@0x106464` 是 ResCommonSettle，120/126 是经验不是金币

> **已修正（见 5.87）**：settle_by_id 3/4/5/6 不是兵种，是
> 玩法/章节族；5xxx=PVE 第五章（2026-11-01 纠偏），1xxx/2xxx/3xxx/4xxx=教学/PVE。

**1. 表身份**：`dc.db @0x106464` 与
`dtab_blocks/36_CommonSettle.bytes.bin` 首行字节完全一致
（stride 120、rows 388），即 **ResCommonSettle**，不是
“四族×分路×档位金币表”。

**2. 行布局（10 字段）**：

```
dwSettleID | bIsRandomAtBegin | dwSettleByID | dwAddAcntExp |
dwAddAcntExp1stTime | dwFailAddAcntExp | dwAddHeroExp | dwAddCoin |
dwAddCoin1stTime | dwGameOverCheckTime
```

（`table_field_map.csv` 的 `CommonSettle` 字段名逐一对上：field4–13 =
`dwSettleID, bIsRandomAtBegin, dwSettleByID, dwAddAcntExp,
dwAddAcntExp1stTime, dwFailAddAcntExp, dwAddHeroExp, dwAddCoin,
dwAddCoin1stTime, dwGameOverCheckTime`。）

**3. 关键行**：

| row | settleID | settleByID | addExp | addExpFirst | addCoin | addCoinFirst |
|---:|---:|---:|---:|---:|---:|---:|
| 101 | 611 | 6011 | 84 | 420 | 20 | 100 |
| 102 | 621 | 6011 | 120 | 600 | 40 | 200 |
| 67 | 334 | 3041 | 126 | 630 | 45 | 225 |
| 87 | 531 | 5011 | 126 | 630 | 45 | 225 |
| 98 | 524 | 5041 | 126 | 630 | 45 | 225 |

→ **120/126 是经验，600/630 是首次经验，40/45 是金币，
200/225 是首次金币**。之前“120/126=小兵金币”把 `addExp` 当成了
gold；真正的金币是 40/45。

**4. 结论修正**：

- “`@0x106464` 是四族×分路×档位金币表”**作废**；
- “120/126 对到具体兵种”**作废**：它们是结算经验奖励，
  `settleByID` 3041/5011/5041/6011 是结算对象 ID，不是兵种；
- 真实小兵 80/120 是 normalMonster 模式变体（见 5.71）。

**5. 数组布局规则（智能体 C）**：

- `_length` **不序列化**，不是 u32 头；
- `_bytes` 是内联固定 buffer，容量来自
  `FixedBufferAttribute(Type, N)`，字节数 = `N × sizeof(T)`；
- 元素宽度实测 **2/4/8/12**（ushort 2、int/uint 4、字符串 ref/2×u32 8、
  3×u32 12）；
- `_bytes` 起点 = 前一字段自然对齐；byte 缓冲 4 对齐、ushort 2、int 4；
- 真正数组长度由 `iParamNum/bNum/bHeroNum/dwNextNum` 等计数字段决定，
  否则零终止；
- 185 张含 `_length/_bytes` 表中 **140 张（75.7%）**可用该规则复现
  stride；9 张成功展开（23 个数组、7,724 行），4 张因未知嵌套 `st*`
  失败。

**产物**：`tools/decode_common_settle.py`、
`datasets/common_settle_106464.csv`；`tools/agent_array_expander.py`、
`datasets/agent_arrays/`（9 张表 CSV + `_layouts.csv`/`_summary.csv`/
`_model_check.csv`）。

## 5.76 source6 野怪事件 → normalMonster 类型

`0x02 len=5` 的 source6 共 8 条（两个打野 + Vetymoment 一次），
金额与 normalMonster 野怪行对上：

| 玩家 | seq | 金额 | 候选野怪 |
|---|---:|---:|---|
| 佚名(*: | 111 | 165 | 红隼/赤甲（160）、熊猫（165） |
| 含泪吃兵线呢 | 127 | 165 | 红隼/赤甲（160） |
| 佚名(*: | 2,782 | 175 | 炎狱暴君（180）、森林熊（174）、山豪小（171） |
| 含泪吃兵线呢 | 3,652 | 178 | 炎狱暴君（180）、山豪中（178） |
| 佚名(*: | 4,922 | 201 | 主宰先锋/小主宰先锋/风暴先锋（200） |
| 含泪吃兵线呢 | 5,758 | 189 | 蔚蓝/腥红石像（190） |
| Vetymoment | 7,537 | 191 | 蔚蓝/腥红石像（190） |
| 含泪吃兵线呢 | 9,073 | 188 | 蔚蓝/腥红石像（190） |

→ **source6 = 野怪击杀金币**；两个打野的路径是：
早期红隼/赤甲（165）→ 中期森林熊/山豪小/炎狱暴君（174–180）→
后期主宰先锋（200）/石像（190）。Vetymoment 的 190 石像事件是
线上玩家拿 buff（偷/协助），不是打野位。

**产物**：`datasets/jungle_event_map.csv`。

## 5.77 CommonSettle 的 settle_by_id 分组：3/4/5/6 = 单位组

> **已修正（见 5.87）**：3/4/5/6 不是近战/远程/炮车/野怪，是
> 玩法/章节族；334=第三章第4关难度4，不是炮车。

`common_settle_106464.csv` 的 `settle_by_id` 按首位分组：

| 组 | 行数 | 例子 | 推断 |
|---|---:|---|---|
| 0 | 19 | 41001、2001 | 全局/系统 |
| 1 | 50 | 1011、1021、1051 | 关卡/模式 |
| 2 | 35 | 2011、2021 | 关卡/模式 |
| 3 | 56 | 3011、3021、3031、3041 | **近战/单位组** |
| 4 | 28 | 4011、4021、4031、4041 | **远程/单位组** |
| 5 | 148 | 5011、5021、5031、5041 | **炮车/单位组** |
| 6 | 28 | 6011、6021、6031、6041 | **野怪/单位组** |
| 7 | 12 | 7011..7051 | 0 exp / 300 coin |
| 8 | 12 | 8011..8051 | 0 exp / 350 coin |

- 6xxx 能对 normalMonster 名字：`6011=腥红石像`、`6031=红方弩兵`、
  `6051=赤甲`；`6021/6041/6061` 未在 normalMonster 表内。
- 3xxx/4xxx/5xxx 是**缺失的兵种 ID**（近战/远程/炮车），名称仍缺；
- 每组的 4 个变体 × 4 个档位：`3011` 的 settle 311/321/331/341
  = 60/10、84/20、102/30、188/0（exp/coin）；`3041` 的 314/324/334/344
  = 72/15、102/30、126/45、232/0。
- → `@0x106464` 的“族×分路×档位”在**分组**上是对的（3/4/5/6），
  但语义是**结算奖励**（exp/coin），不是小兵金币；`settle_by_id`
  是单位/结算对象，不是分路。

**产物**：`datasets/settle_by_unit_group.csv`（68 行：settle_by_id、
group、normalMonster_name、settles）。

## 5.78 十人金币累计时间线

`datasets/player_gold_timeline.csv`（281 行）：按玩家/seq 排序，
列 `player, team, slot, hero_id, seq, source, amount, cum_total,
cum_source`；`cum_total` 是该玩家累计金币，`cum_source` 是该来源
累计。

示例（Vetymoment）：

| seq | source | amount | cum_total | cum_source |
|---:|---:|---:|---:|---:|
| 99 | 5 | 131 | 131 | 131 |
| 792 | 4 | 188 | 319 | 188 |
| 1,114 | 5 | 144 | 463 | 275 |
| 1,649 | 43 | 102 | 565 | 102 |
| 2,166 | 4 | 187 | 752 | 375 |
| 4,552 | 47 | 179 | 1,702 | 179 |

→ 可直接按 seq 画累计金币曲线，或按 source 拆小兵/野怪/击杀/系统
四条线。注意 seq 不是秒，需另找帧率映射。

## 5.79 字符串编码最终解法：`value32 = 文件内偏移 << 6`

技能表 `0x1ce47c` 的 ref 是 `(hash32, value32)`：

- `hash32` = **每表唯一的字符串池命名空间 ID**（本表全部
  `0xfc680a5d`；全库 919 个 hash 两两不同）；
- `value32` = **源资产文件内字符串记录偏移 << 6**；低 6 位是标志
  （本表全 0，4 字节对齐）；
- **字符串位置 = 表起点 + (value32 >> 6) + 8**（+8 跳过池记录的
  hash64）；
- 池记录 = `hash64 + UTF-8 + NUL + 4 字节对齐`；表布局 =
  `0x98 头 + nrows×stride 行 + 字符串池`；
- **919/919 张有池表**满足 `0x98 + stride×rows == pool_rel`；
  **783,075/783,075 个 ref 精确**，去重 **367,895** 个；
- 不存在单一全局池：`0xc4ab4`/`0x5902c` 都是表起点
  （ResSkinKolTips/王者小店锚点名），各自池 `0xce76c`/`0xaf4c4`；
- 旧“首次出现顺序”法在 300 张表上正确，但位置法对 919 张全部精确，
  后续以位置法为准。

**关键 skillID 名称**：

- **91060**（row1936）= **小乔 铸魂·星华缭乱**；
- **900011**（row2527）= **打包濒死队友**；相邻 900010=复活濒死队友、
  900012=放下濒死队友；
- **11991 不是本表 skillID**：回放里它是 event seq / frame actor_id；
  若原意是 **91991**，则是公孙离 **铸魂·孤鹜断霞**；
- 诸葛亮铸魂=91909 铸魂·东风破袭，廉颇=91055/91059 铸魂·爆裂冲撞；
  旧结果“91060=诸葛亮/廉颇”是错位；
- 91060 在 buff 表 `0x3ba41a8` row391 另有含义（峡谷裂口传送中断
  被动）；ID 必须带表命名空间。

**产物**：`tools/agent_global_strings.py`、
`datasets/agent_global_strings.csv`（32 MB；列
`table,row,ref,text,confidence`；全部 exact）。

## 5.80 嵌套 `st*` 结构体闭合（智能体 E）

- 解出 16 个直接 `st*` sizeof + 8 个固定 buffer 元素 sizeof =
  **24 个结构体**（22 高置信、2 中）；
- 25 张未知嵌套表：**24 张 stride 精确闭合**，1 张 pad4；
  加上原有 140 张，累计 **164/185 精确**；
- **4 张原失败表全部闭合**：
  - `ResTrial` stride 264：`stReward@76=ResDT_RewardItem(12)`；
    energy 8B×3；warning 4B×2；scoreSale 8B×bSaleNum；
    stage 20B×bStageNum；
  - `ResLuckyDrawPrice` stride 224：`stDrawPoolInfo@116=
    ResDT_LuckyDrawPool(12)`；period 32B×bPeriodCnt；egg 24B
    （8B×3 候选，中置信）；
  - `ResWealStampInfo` stride 1184：`stCommon@136=ResDT_WealCommon(248)`、
    `stFinalReward@388=ResDT_WealStamp_RewardInfo(12)`；
    reward 12B×bX/bY；XStamp 120B×bX；
  - `ResNewHeroPracticeTargetInfo` stride 240：
    `stPerfectPassAward@12=ResDT_RewardItem(12)`；target 40B×2；
    friendly/enemy 12B。

**sizeof 表**：`ResDT_RewardItem 12`、`ResDT_RefreshInfo_List 28`、
`ResDT_CreditValueRewardItem 24`、`ResDT_WealCommon 248`、
`ResDT_WealStamp_RewardInfo 12`、`ResDT_Item_Info 12`、
`ResDT_WealConMask 20`、`ResDT_LuckyDrawPool 12`、
`ResNewLuckyDrawPrice 48`、`ResLuckyDrawProbailityAdjust 16`、
`ResDT_RegisterSale_Info 48`、`RedEnvelopeValSelectParam 20`、
`ResCompetitionRewardItem 12`、`ResDT_BattlePassLevelAwardEntry 16`、
`ResDT_JumpForm 56`、`ResDT_BadgeComInfo 76→80`；
固定 buffer 元素：`ResDT_TrialScoreSale 8`、`ResDT_TrialStage 20`、
`ResEggInfo 8*`、`ResDT_LuckyDrawPeriod 32`、
`Rest_WealStamp_XStampInfo 120`、`ResDT_NewHeroTarget 40`、
`ResDT_PracticeHeroInfo 12`、`ResDT_WealStamp_CellInfo 24`。

**关键规则**：字段 metadata 存的是 **Il2CppType 索引**，不是 TypeDef；
`TypeDefinition.byvalTypeIndex + 1` = 字段类型（`stCommon` 为 +2）；
`_length` 不序列化；`_bytes` 按 `FixedBufferAttribute` 内联，自然对齐。
剩余 20 张是映射漂移（不含嵌套 `st*`）。

**产物**：`tools/agent_nested_structs.py`、
`datasets/agent_nested_structs/`（`_summary.csv`、`_st_sizes.csv`、
`_st_fields.csv`、`_tables.csv`、`_failed4.csv`、`_layouts.csv` +
4 张解码 CSV）。

## 5.81 436 张 C# 表位置法重解 + 0x29 技能名

- 用 `agent_global_strings.csv` 的 `(table,ref)→text` 精确表重解
  **436 张表**，输出到 `datasets/decoded_csharp_all/`；
- 非字符串单元不再误当 ref（MatchBadge 的 cell4 保留
  `0x64d65b00:0x6524237f`，不再出现 `5b74c>` 片段）；
- `0x29` 事件 473 条，4 个 skillID：
  - **91060 = 小乔 铸魂·星华缭乱**（161 条）；
  - **900011 = 打包濒死队友**（19 条）；
  - **0 = 289 条**（level=0，取消/无技能候选）；
  - **11990 = 4 条**（不在技能表；slot 58/64、level=-1，
    特殊/召回候选）。

**产物**：`datasets/skill_id_names.csv`、
`datasets/skill_events_named.csv`。

## 5.82 自然金币最终定位：battleDynamicProperty @0x2afa49c

- 原生表 `dc.db @0x2afa49c`（`stdr`，stride **76**，rows **7,603**，
  无字符串），即 C# `battleDynamicProperty`；关卡行的
  `dwDynamicPropertyCfg` 指向它。
- 行：`+0x00 cfgID`、`+0x04 bVarType`、`+0x08 生效时间(ms)`、
  `+0x0C 间隔(ms)`、`+0x28 随时间增长值`、**`+0x3E u16 = 每间隔金币**。
- **cfg 1**（5v5 王者峡谷族：20011、20086–20089、21000 等 63 个关卡）：
  `bVarType=2` 行 start 30/40/60/90/…s，interval 1000ms，
  **rate=3**（30s 行 0，40s 起 3）→ **3 金币/秒**。
- **cfg 1010001**（快速/娱乐族：1010/1011/1012/20040）：
  同结构，**rate=10** → **10 金币/秒**。
- 其他 cfg：5、40、77、4034、5262（不同模式 2–18/s）。
- 关卡→cfg：`AcntBattleLevel @0x14660`（stride 1240，99 行）
  行内 `+0x42C`（gameplay 基址 +0x350）。
- GameCore 消费：`libGameCore.so @0x4660b10` 把属性 **0x4000**
  映射到 `GoldCoinInBattleIncreaseRate`，**0x8000** 到
  `GoldCoinInBattleAutoIncreaseValue`；相邻 0x100 AtkSpdAdd、
  0x200 SoulExp、0x400 ReviveTime、0x2000 Damage、0x10000 MoveSpeed。
- 回放侧：`0x02 len=5` source=5 共 2,161 条；小额 31/32/33…73
  （≈3×10s 的 10 秒推送；金额随模式 4–8/s 升到 73），没有字面 3/10；
  大额 131–254 是太乙/辅助装等被动金币。
- 30 秒只是统计口径（`COMDT_GAME_30SEC_INFO.dwSystemAddIntervalCoin`
  等），不是加金节拍。
- 排除：Level `+0x144=3` 是 `iPassDialogId`；`@0x106464` 是
  CommonSettle；buff 表无自然金币行；client databin 不打包该表；
  `.ope` 无经济。

**产物**：`natural_gold_candidates.csv`、
`battle_dynamic_property_rates.csv`、`level_dynamic_property_map.csv`、
`natural_gold_tick_events.csv`、`natural_gold_tick_summary.csv`。

## 5.83 普通 5v5 模式规格（优先口径）

> **已修正（见 5.87）**：3xxx/4xxx/5xxx 不是兵种组；
> 5xxx=PVE 第五章（不是普通 5v5），1xxx/2xxx/3xxx/4xxx=教学/PVE。

**模式**：`confType1=50`（Svr2GameCore KV item1；`abc_batch` 25 个
可解析样本全是 50）；主样本 `20260925_105224` 是普通 5v5。
**注意 50 是常量，不是普通/快速的判别位**：OCR 的
`20261028_135516` 也是 50，但它是“峡谷—快速赛”。
**普通 5v5 样本基数**：6 个 res_build 5069040 样本中，3 个完整
10/10、1 个 9/10（截断）、2 个 2/10（1v1/3v3 或严重截断，
不计入普通 5v5）。
**初始金**：300（KV item7）。

| 项 | 普通 5v5 取值 | 来源 |
|---|---|---|
| 自然金 | **3 金币/秒**，40s 起、1000ms | `battleDynamicProperty` cfg1 @0x2afa49c |
| 小兵（战士） | 早期波 166000/1660002 等：gold 60/80/90、HP7000/1860、exp 4150、actor 10010；`normalMonster` 共 2,625 行 | normalMonster |
| 小兵（法师） | 早期经验法师 1660014/1660043：gold **140**、HP8500/1700、exp 4150；普通法师 166001/166004：gold **90**；另有 2/5 行 gold 80 的变体 | normalMonster |
| 兵线 | `soldierWave @0x1791ad8`：162320（战士+2 经验法师，10s/33s，repeat 8）→162321（战士+法师+弩车，repeat 11）→1623211（战士+法师+炮车）；弩车 192、炮车 300、机关战士 576、主宰先锋 300 | soldierWave |
| 野怪 | 红隼/赤甲160、森林熊174、山豪小171、炎狱暴君180、主宰先锋200、石像190 | normalMonster |
| 结算 | ResCommonSettle @0x106464；**5xxx=PVE 第五章（+0x50 `astFirstCompleteReward`→RandomRewardStore 行名 20511=501难度1；不是 level_id 字段）；普通 5v5 settle 未定位**；6xxx=10v10/排位候选；3xxx/4xxx=PVE 星级条件（另一张表） | CommonSettle + EvaluateCond |
| 对局配置 | 32 个普通 5v5 对局配置（12 普通匹配+20 征召；63 个 cfg1 总数含 AI/练习/测试/OB/娱乐） | normal_5v5_match_configs.csv |

**排除（不属于普通 5v5）**：

- 快速赛：`cfg1010001` rate=10、小兵 120 行
  `1301/1304/21010/21020`；`20261028_135516` 经 OCR 确认是
  **“峡谷—快速赛”**（POV 孙膑/茉莉花与雨），虽然它
  `conf_type1=50`、source4=194、十人阵容——**这些都不能排除快速赛**；
- 10v10：`5262xxx` 行；
- 教学/新手/召唤/选敌行。

**产物**：`datasets/mode_normal_5v5.csv`（25 条规格）、
`datasets/normal_5v5_match_configs.csv`（32 个普通 5v5 对局配置）。

## 5.84 普通 5v5 主样本：localHeroId 修正与英雄标注 blocker

> **已修正（见 5.90）**：英雄 ID 在块内 `s+0x48` u16BE；录制者是
> 1558 佚名（东皇太一 187），442 是李信 507；`off+0x08` 不是
> recordLen。下面保留原始推导过程。

- 主样本 `20260925_105224` 的头部：4 个前缀串
  （`12.1.1.1`/`12.1.1.8`/`4989537`/`5069040`）总长 34；
  **offset 34 LE = 187 = 东皇太一**（本地玩家英雄）。
- `replay_parser` 读 offset 35 BE=136 是错的；该 build 的
  `localHeroId` 在 **offset 34 LE**。
- 十人玩家块不匹配 `replay_parser` 的 stride 1517 / hero offsets
  771/1415/1445；`abc_roster` 的 `off` 窗口互相重叠，英雄名搜索
  （百里玄策/影）是跨块误命中。
- **玩家块头部**（`abc_roster` 的 `off` 即块起点）：

  | 偏移 | 内容 | 例（442） | 例（1729） |
  |---:|---|---|---|
  | +0 | 3 字节 team/slot/flag | `02 02 01` | `01 01 01` |
  | +6 | **entityID u16BE** | `01 ba`=442 | `06 c1`=1729 |
  | +8 | record length u32BE | 30 | 30 |
  | +12 | name length u32BE | 19 | 19 |
  | +16 | name UTF-8 | 李不信有归途 | 桑忆终尘启 |

- **名字后结构**：`post = off+16+nameLen`；
  `post+8` 是 4 字节哈希（442=`0x4D770A6C`、1729=`0x67002718`、
  1965=`0x9E9B7061`…）；`post+12` 是 u32BE 皮肤/配置 ID
  （442=1460、1729=3350、1965=3199、1514=1226…）；`post+16`=30；
  `post+20` 是 u16（442=18362、1729=6656…）。
- 这些 u32 **不在**英雄表 `0x111C3C`、皮肤表 `0x3D1A9B0`/
  `0x56E5140` 的行 ID/字段里（3350 在英雄表命中是 HP 类字段的
  巧合）；英雄角色 ID 仍未解。
- 英雄角色 ID **不是块头/名字附近的简单 u32**（本地英雄 187 在块内
  未命中）；其他 9 人的英雄角色 ID 仍未解。
- → 主样本除本地英雄 **187 东皇太一** 外，其他 9 人的英雄角色 ID
  仍未解；per-player 经济仍用玩家名/实体 ID 标注。
- 下一步：找 5069040 build 的玩家块布局（block stride/hero offset），
  或用录屏/结算面板补英雄。

## 5.85 普通 5v5 十人经济对账（智能体 J）

> **注意（见 5.96）**：33,040 是 `0x02` 可观测子集（25–35% 收入），
> 不是全量事件金；下面的“事件金”只能当下限。自然金基准也应按
> 回放 +21.5s 偏移改为 1,908.6/人（见 5.92），不是 1,844.1。

主样本 `20260925_105224`：**286 条 / 33,040 金币**；录制 654.7s，
对局约 676.2s（+21.5s，见 5.92）；自然金基准 **1,908.6/人**
（3/s × 635s）；流水不含初始 300。
团队：1 队 **16,002**，2 队 **17,038**。

| 玩家 | 小兵 | 野怪 | 击杀/助攻 | 自然小额 | 被动131-146 | 打野刀230-254+51 | 其他 | 流水 | 残差 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 桑忆终尘启 | 20/3,855 | - | -/1/102 | - | 2/275 | - | - | 4,232 | 275 |
| 碗面加香菜 | 20/1,960 | - | 2/405/- | 1/31 | 1/131 | - | - | 2,527 | 131 |
| 布鲁BIUBIU | 24/2,339 | - | 1/203/1/102 | 1/31 | 2/276 | - | - | 2,951 | 276 |
| 含泪吃兵线呢 | 2/382 | 4/720 | -/- | 17/655 | 3/417 | - | - | 2,174 | 417 |
| 双枪踏浪行 | 20/2,314 | - | 1/203/- | 5/204 | 3/416 | 4/981 | - | 4,118 | 1,397 |
| 李不信有归途 | 20/2,289 | - | -/- | 8/332 | 4/550 | 1/254 | 1/47 | 3,472 | 851 |
| 酒梦灵心醉 | 21/2,041 | - | 2/406/1/102 | 2/62 | 2/276 | - | - | 2,887 | 276 |
| 备水一站. | 13/1,525 | - | -/- | 11/407 | 3/416 | 4/981 | - | 3,329 | 1,397 |
| 佚名(*: | 4/781 | 3/541 | -/- | 18/656 | 3/421 | - | - | 2,399 | 421 |
| Vetymoment | 21/4,070 | 1/191 | -/1/102 | 4/134 | 2/275 | - | 1/179 | 4,951 | 454 |
| **合计** | **165/21,556** | **8/1,452** | **6/1,217 / 4/408** | **67/2,512** | **25/3,453** | **9/2,216** | **2/226** | **33,040** | **5,895** |

**自然金**：小额 67 条 / 2,512；3/s×636.2s 理论值 **1,908.6/人**、
团队 19,050；覆盖率 **13.2%**。source5 全部 7,673，为理论值的 40.3%。
→ **source5 小额是稀疏样本，自然金只能给下界**；桑忆 0 条不能
解读为无自然金。

**残差 5,895（17.8%）**：

- 被动/团队金 131–146：3,453（58.6%），25 条、10 人全有，
  130/140 底额 + 1–6 尾数；候选太乙/辅助装/团队行为金；
- **打野刀 +20% 野怪金 230–254：1,708（29.0%）**，7 条：
  备水（赵云）4/981、双枪（马超）3/727；金额 = 野怪底额×1.2
  + 1–3 尾数（190→231、200→241/242/243、210→251–254）。
  见 5.97：source6 是辅助/游走拿边野的**全额击杀金**，
  这条 230–254 才是打野刀持有人的 +20% 通道；
- **source51 254：508（8.6%）**，2 条（双枪、李不信），
  仍是目标/推塔候选；
- source47/44：226（3.8%），179（Vetymoment）像暴君/主宰/目标，
  47（李不信）像助攻/一血，低置信。

→ 残差里 1,708 已归到打野刀 +20%，508 仍是 source51 目标候选；
source5 131–146 仍是辅助装/被动/团队金混合。

**产物**：`datasets/normal5v5_reconciliation.csv`（286 条修正版；
旧 `agent_normal5v5_reconciliation.csv` 是 281 条历史版）、
`agent_normal5v5_reconciliation.md`、`tools/agent_normal5v5_reconcile.py`。

## 5.86 完整金币模型：流水=可观测事件金子集，自然金隐式累加

> **修正（见 5.96）**：`0x02` 只覆盖 25–35% 收入，所以“流水=事件金”
> 应读作“流水=可观测事件金子集”；总金模型只能给下限，支出/未知
> 收入仍缺。

**关键纠正**：`0x02 len=5` 是**事件金**（小兵/野怪/击杀/助攻/
辅助装/目标），**不是总金币**。自然金
（`battleDynamicProperty` cfg1，3/s、40s 起、1000ms，GameCore
属性 0x4000）是**隐式累加**，不在 source5 流水里。

**source5 小额不是自然金**：

- 10 人 source5 小额计数：佚名 18、含泪 17、备水 11、李不信 8、
  双枪 5、Vetymoment 4、酒梦 2、碗面 1、布鲁 1、桑忆 0；
- 自然金应 10 人相同（3/s × 636.2s ≈ 1,908.6/人），计数 0–18 不等
  直接排除“source5 小额=自然金”；
- source5 小额与**队友小兵击杀**（source4）在 ±50 seq 内的时序
  重合率：佚名 56%、含泪 50%、Vetymoment 50%、备水 45%、
  双枪 40%、李不信 25%；更像**辅助装/分享/助攻金**。

**完整金币公式**：

```
某玩家总金币 ≥ 可观测事件金（0x02 子集）+ 自然金（3/s × 有效时长）
             + 初始 300 - 支出（装备/道具）
```

- 可观测事件金合计 33,040（十人）；自然金约 1,908.6/人（普通 5v5）；
- **0x02 只覆盖 25–35% 收入**，所以公式是下限，不是精确总金；
- 之前“自然金覆盖率 13.3%”是把事件金当总金的误读；自然金
  本来就不在流水里，不能用 source5 覆盖率衡量。

**已补（见 5.97）**：source5 230–254 = 打野刀 +20% 野怪金；
131–146 仍是辅助装/被动/团队金混合；source43 203=击杀/102=助攻
仍是候选；英雄角色 ID 已解（5.90）。

## 5.87 纠偏：CommonSettle `settle_by_id` 是玩法/章节族，不是兵种

`agent_normal5v5_settles.csv`（388 行 × 26 列）把 settle 族钉死：

| 族 | 行数 | 性质 | 证据 |
|---|---:|---|---|
| 0 | 19 | 训练 | TrainingLevel 2001–2012、4003–4008、41001/41002 |
| 1xxx | 50 | **教学/基础训练** | `Level.bytes` cfg1 基础教学、cfg2 3v3入门等 |
| 2xxx/3xxx/4xxx | 110 | **PVE 剧情章节** | `Level.bytes` `SettleIDDetail`：cfg101→[111,121,131,141]、cfg304→[314,324,334,344] |
| **5xxx** | **148** | **PVE 第五章（不是普通 5v5）** | CommonSettle `+0x50 astFirstCompleteReward`：511/521/531/541→20511/20521/20531/20541 = RandomRewardStore 行名“501难度1-4”（奖励 ID 与关卡号同号）；501–506→1051–1056=关卡5-1首通…；**+0x50 不是 level_id**，20511 是首通奖励 ID/奖励行名；与普通 5v5 关卡交集 0 |
| 6xxx | 28 | 10v10/排位候选 | low |
| 7xxx/8xxx | 12/12 | 1v1/3v3/自定义候选 | low |

→ **之前 5.75/5.77/5.83 的“3=近战/4=远程/5=炮车/6=野怪”
作废**：`334` 实际是“第三章第4关难度4”，不是炮车；`524` 也不是
“炮车分路1三档”。**小兵基础金币/经验只在 `normalMonster`；
`AcntBattleLevel` 只有金币/经验补偿与兵线激活参数**。

**63 个 cfg1 对局配置**：**32 个普通 5v5 对局配置**
（12 普通匹配 + 20 征召），
其余 31 个是 AI 4、练习/修炼 3、测试 4、OB 1、调试 1、娱乐/活动 16、
其它 2；CSV 的 `is_normal5v5_core`/`exclusion_reason` 可过滤。
核心地图：`pvp_9_detail` 多数，`pvp_5_detail`/`pvp_31_detail` 少数。

**普通 5v5 对局配置字段**：初始 300、自然 3/s（40s/1000ms）、
`dwCompensateExpBuffID/GoldBuffID=917010/917011`、
`iSoldierActivateCountDelay1/2/Delay=0/5500/10000`、
经验补偿 `2:4000;3:6000;4:8000;5:10000;6:10000`。

**普通 5v5 结算**：**未定位**。5xxx 已证明是 **PVE 第五章**
（`dc.db @0x4015C7C` 是 **RandomRewardStore**，stride 1232、
rows 14286；行名是 PVE 关卡名，`+0x50` 存的是首通奖励 ID，
不是 `level_id` 字段）；6xxx 是 10v10/排位候选；普通 5v5
自己的 settle 行仍缺。

**5xxx 内部再分（PVE 第五章）**：

| 子类 | settle_id | 含义 | 证据 |
|---|---|---|---|
| 对局结果奖励 | 511/521/531/541（by 5011/5021/5031/5041） | 4 变体 × 4 tier；`add_acnt_exp`/`add_coin` 随变体递增，首胜 5× | add_exp_1st=5×add_exp |
| 失败行 | 501/504 | `fail_add_acnt_exp=1`、`add_hero_exp=100`、`add_coin=250` | 与结果行同组 |
| 账号等级段奖励 | 901–906、1001–1006 … 1801–1806、10501、10901–11806 | `add_coin` 400–1700、`add_hero_exp` 100/200，**不是对局结算** | 按等级段递增，first_complete_reward 为空 |
| 其它 | 5051/5061 各 2 行 | 低置信 | — |

→ 5xxx 不是普通 5v5；之前 5.87/5.91 的“普通 5v5 主族”作废。
普通 5v5 的 settle 行仍未定位。

**产物**：`agent_normal5v5_levels.csv`（63×44）、
`agent_normal5v5_settles.csv`（388×26）、
`normal5v5_settle_5xxx.csv`（148 行，按结果/失败/等级段拆分）、
`normal_5v5_match_configs.csv`（32 个对局配置）、
`mode_normal_5v5.csv`（已更新）。

**录屏末帧校验**（`video_ocr/evidence/05-hud-last.png`，01:46）：

- 团队比分：蓝 **2 杀 / 9.1k**，红 **1 杀 / 8.6k**；
- POV 孙膑：KDA **0/0/1**，金币 **1,783**，等级 5；
- `06-team-panel.png`（00:32）：十人全 0/0/0，金币 330–340。

这与 `samples.selected` 的末段（0/0/1、1,783）一致，说明 OCR 的
最后一条是可信的；但它只覆盖到 1:46，**不能用来验证主样本
source43 的 6:4**。主样本的 203=击杀、102=助攻仍是候选。

**快速赛标签（用户确认 + OCR 证据）**：`20261028_135516.abc`
对应视频 OCR 的 **“峡谷—快速赛”**（`match.mode.confidence=0.866`），
POV 孙膑，玩家 **茉莉花与雨**；所以它是快速赛，不是普通 5v5。
`conf_type1=50`、唯一 source4=**194**（攻城车）**不能排除快速赛**——
50 是常量，快速赛的攻城车也可以是 194；1:46 是视频片段长度，不是
模式证据。快速/普通的判别不能只看 `conf_type1` 或小兵金额，需用
OCR/UI 模式标签或 `dwDynamicPropertyCfg` 等更强证据。




















## 5.88 金币来源枚举与自然金投递路径（智能体 M）

**结论先行**

1. **C#/IL2CPP 侧没有金币来源枚举**。`eGoldSource`、`GoldSourceType`、
   `CoinSource`、`CoinSourceType`、`SystemAddCoin`、`IntervalCoin`、
   `GoldChannel` 等 18 个候选名在 `global-metadata.dat` 类型表 **全部 0 命中**。
2. **权威枚举在协议字段层**（不是 C# `enum`）：
   `COMDT_GAME_30SEC_INFO` 100 字段里 **35 个金币字段**、
   `COMDT_HERO_BATTLE_STATISTIC_INFO` 358 字段里 **42 个**、
   结算 `stReportPlayerData` 是 **6 路**分类。
3. **原生侧只有类型名、没有成员名**：`KDAStat::GET_COIN_CHANNEL_TYPE`
   @`0x11dab25`、`stHeroGoldCoinInBattleChangeParam` @`0x11efe25`、
   `goldSource` @`0x11b117f`、`stGoldCoinSourceKillParam` @`0x1209c82`；
   成员名/数值不在字符串名池，**离线不可枚举**。
4. 回放 `0x02 flag=0x85 len=5` 的 `sourceType` 是**原生金币通道号**
   （u8），不是 C# 枚举：CSProtocol/ResData/CoreDef 共 3,155 个枚举，
   **2,929 个纯步长 2**（0,2,4,…），其余是位掩码/非连续特例；
   观测值 `4/5/6/43/44/47/51` 混排，落在任何 C# 枚举的取值集之外。
5. **自然金不在 0x02 流水里**，由 GameCore 属性 `0x4000`
   （`GoldCoinInBattleIncreaseRate`）按 1000ms **隐式累加**；
   `13.3%` 是拿"事件金的一个金额档"除"全队自然金理论值"，**无经济含义**。

### 5.88.1 回放 source 映射（20 个可解析样本 / 5,758 条）

| source | 条数 | 金额 | 映射 | 置信度 | 关键证据 |
|---:|---:|---|---|---|---|
| 4 | 3,180 | 87–220 | 小兵击杀金 `dwSoliderKillCoin` / `iCoinFromKillSolider` | **high** | 三簇 87–114 / 130–135 / 187–220 = `normalMonster` 80/90/100/130/190/200/210 底额 + 加成；10 人全覆盖、人均 16–24 条，与补刀同量级 |
| 5 | 2,161 | 31–254 | 系统金/辅助装通道 `dwSystemAddCoin`、`dwAidEquipCoin`、`dwEquipAssistEnCi/YouJiCoin` | medium | 三档 31–73 / 131–146 / 231–254（底额 30 / 130,140 / 230,240,250 + 1–4 尾数）；10 人 0–18 条、合计 0–656，CV 0.94 |
| 6 | 110 | 165–211 | 野怪击杀金 `dwMonsterKillCoin` / `iCoinFromKillMonster` | **high** | 165/175–192/201–211 对 `normalMonster` 160/175/190/200/210；每局仅 2–3 人（打野/反野），5–8 条 |
| 43 | 252 | 102/202/203 | 英雄击杀/助攻 `dwHeroKillCoin` / `iCoinFromKillHero` | medium-high | 只有 100/200 两个底额 +2–3；主样本 10 条 = 6 杀 + 4 助攻，与 6:4 一致 |
| 44 | 10 | 47 | 河道之灵/小型中立（45 底额） | medium-low | 金额恒 45+2，全样本 10 条 |
| 47 | 27 | 179 | 175 底额目标/特殊野怪 | low | 金额恒 175+4，集中少数玩家 |
| 51 | 13 | 155/254 | 150/250 底额目标金（推塔/主宰） | low | 只有 150+5、250+4；无建筑死亡逐条事件可对 |
| 86 | 3 | 13–15 | 小额系统/赏金 | low | 无重复模式，可能是补偿金或伪命中 |

（`source=28` 的 2 条 amount 2,359,296 级是解析伪命中，已排除。）

### 5.88.2 协议层金币来源枚举（最有价值的部分）

**30 秒统计 `COMDT_GAME_30SEC_INFO`（100 字段，35 个金币字段）**：

- 总额：`dwCoinCnt`(7)、`dwCoinIntervalCnt`(8=本 30 秒增量)；
- 补刀：`dwSoliderKillCoin`(19)、`SoliderKillCoinByRouteID`(20)；
- 野怪：`dwMonsterKillCoin`(22)、`dwKiLlOurMonsterCoin`(37)、`dwKiLlEnemyMonsterCoin`(38)；
- 龙/河道：`dwDuikanRiverCatCoin`(23)、`dwMidRiverCatCoin`(24)、
  `dwFayuRiverCatCoin`(25)、`dwLittleDragonCoin`(26)、`dwOldDragonCoin`(27)、
  `dwDragonCoin`(28)、`dwDarkDragonCoin`(29)、`dwBaronCoin`(30)；
- **增量族**：`dwSoliderKillIntervalCoin`(31)、`dwDestroyOrganIntervalCoin`(33)、
  `dwHeroKillIntervalCoin`(34)、**`dwSystemAddIntervalCoin`(35)**、
  `dwMonsterKillIntervalCoin`(36)；
- 装备/团队：`dwEquipAssistEnCiCoin`(39)、`dwEquipAssistYouJiCoin`(40)、
  `dwEquipJungleShangJinCoin`(41)、`dwEquipJungleYouJiCoin`(42)、
  `dwPassiveTaiYiZhenRenCoin`(43)、`dwAidEquipCoin`(83)、
  `wSelfBehaviorCoin`(55)、`dwTeamBehaviorCoin`(56)；
- 累计：`dwDestroyOrganCoin`(85)、`dwHeroKillCoin`(86)、**`dwSystemAddCoin`(87)**、
  `dwKillHeroCopyCoin`(49)、`dwPickupSoldierCoinNum/Value`(91/92)。

**结算 `stReportPlayerData` 的 6 路分类**（C# 侧唯一的"来源枚举"）：

`totalCoin`(11)、`iCoinFromKillSolider`(13)、`iCoinFromKillMonster`(14)、
`iCoinFromKillTower`(15)、`iCoinFromKillDragon`(16)、`iCoinFromKillHero`(17)、
`iCoinFromSystem`(18)。

**协议/配置里真实存在的 C# 枚举**（本 build 取值步长 2）：

| 枚举 | 成员（值） |
|---|---|
| `CoreDef.CoinChangeCustomType` | NULL=0, CallVanguardKill=2, MonsterKillSpecialIncome=4, VanguardKillShareIncome=6, GodShadowShareIncome=8 |
| `ResData.RES_INCOME_KILL_TYPE` | ORGAN=2, SOLDIER=4, HERO=6, MONSTER=8, BOSS=10, EYE=12, RUNAWAYCAT=14, CALLACTOR=16, PVE_MONSTER=18, ACTIVECALLMONSTER=20, ANYINGVANGUARDBORNKILL=22, HEALTH_SEGMENT_BREAK=24, MONSTER_SPECIAL=26, MAX=28 |
| `ResData.RES_INCOME_ITEM_TYPE` | SOUL_EXP=2, BATTLE_GOLD=4 |
| `ResData.RES_INCOME_DIVIDE_TYPE` | EQUAL=2, COPY=4, NONREDUCE_COPY=6, CONTRIBUTION=8 |
| `ResData.RES_INCOME_ATTACKER_TYPE` | ALL=2, ORGAN=4, SOLDIER=6, HERO=8, MONSTER=10 |
| `ResData.RES_ASSIST_INCOME_ALLOC_TYPE` | HURT=0, CONTROL=2, BEHURT=4, HEAL=6, HIGHLIGHT=8, MAX=10 |
| `CoreDef.enFloatTextType` | 只有 `ReceiveGoldCoinInBattle=16`、`ReceiveLastHitGoldCoinInBattle=18` 两档跳字 |

> 元数据坑：`global-metadata.dat` v29 的 fieldDefaultValues **不是裸 int**，
> 而是 **MSB-first base-128 变长编码**（0x80 续位）。小枚举逐字节读出即
> 真实值，`COM_COIN_TYPE` 用 `MAX=80`/`MIXPAY=84` 自证（0..84 步长 2）。
> 旧工具按 int32 读会把 `Common` 读成 50,462,976。

### 5.88.3 自然金是"隐式累加"，13.3% 是口径错配

自然金 = `battleDynamicProperty` cfg1（3/s、40s 起、1000ms）→
GameCore 属性 `0x4000`，**按帧累加，不产生逐笔金币事件**。
证伪"source5 小额=自然金"的四条独立证据：

| 检验 | 结果 | 自然金应有 |
|---|---|---|
| 自然金 rate=0 区间（t<40s）出现 source5 小额 | **12 条**（4.2s/5.8s/7.9s/8.8s…，金额 31/32/33/65） | 0 条 |
| 主样本 10 人 source5 小额合计 | 0 / 31 / 31 / 62 / 134 / 204 / 332 / 407 / 655 / 656，**CV=0.94** | 10 人完全相同 1,908.6 |
| 金额形态 | 31 在单样本里重复 **76 次**（固定底额 30+尾数） | 3/s 连续累加不产生固定值 |
| 与队友 source4 小兵金的比例（主样本） | 0.1–0.7 全散开，覆盖仅 43% | 若为分成应有固定比例 |

**13.2% 的算式**：`2,512 / 19,050 = 13.2%`
（分子 = source5 31–80 档事件金；分母 = 3/s × 635s × 10 人）。
分子是"事件金里落在 31–80 档的那部分"，分母是"完全不产生事件的自然金"，
**两者不是同一类，比值没有经济含义**；`7,673/19,050 = 40.3%` 同理。

**正确模型**：

```
某玩家总金币 = 初始 300 + Σ(0x02 事件金) + 3/s × (时长-40s) - 支出
```

主样本：可观测事件金 33,040（十人，0x02 子集）+ 自然金 19,050 + 初始金 3,000 = 55,090（含初始），
人均 5,512（对局约 676s，11:16），是**下限**（0x02 只覆盖 25–35% 收入）。

**要真正校验自然金，只有两条路**：
`COMDT_GAME_30SEC_INFO.dwSystemAddIntervalCoin`（应 **90/30s**）或
结算面板 `iCoinFromSystem`；**这两者都不在回放容器里**（5.14/5.56 已证
签名 0 命中）。因此回放侧只能按 3/s 隐式加，不能从流水反推。

### 5.88.4 source5 到底是什么

- 三档金额（30 / 130,140 / 230,240,250）+ 1–4 尾数 → 一字节通道里唯一的
  "系统加金"聚合通道，对应 `dwSystemAddCoin`/`dwAidEquipCoin`/
  `dwEquipAssistEnCiCoin`/`dwEquipAssistYouJiCoin` 这一族；
- 小额段不是自然金（见上），也与队友小兵金无固定比例，**更像辅助装
  恩赐/游击的周期性固定额 + 团队行为金**（辅助/游走位计数最多：
  佚名 18、含泪 16、备水 11；单线 桑忆 0）；
- 大额段 **231–254 = 打野刀 +20% 野怪金**（190→231、
  200→241/242/243、210→251–254；见 5.97）；131–146 仍是
  辅助装/被动/团队金混合，未完全拆开。

**产物**：`datasets/agent_gold_source_enum.csv`（59 行：kind/source/
enum_name/protocol_field/evidence/confidence/观测值）、
`tools/agent_gold_source_enum.py`（只读，可复跑：
`python tools/agent_gold_source_enum.py`）。

## 5.89 soldierWave 表与普通 5v5 兵线（智能体 H）

`dc.db @0x1791ad8` 是 **ResSoldierWave**（stdr，stride **312**，957 行，
无字符串池）。它才是“第几波、什么兵、几秒一波”的权威表；
`normalMonster` 只给单兵种的金币/经验/血量。

**行布局**（`72 + 15×16 = 312`）：

| 偏移 | 字段 | 说明 |
|---:|---|---|
| +0x00 | waveID u32 | 波次 ID |
| +0x04 | bRouteType / bCamp / bType / bSpecifyBornPos | 4×u8 |
| +0x08 | astBranchWaves[5] | 5×8B 分支波次 |
| +0x30 | nextWaveID u32 | 下一波 |
| +0x34 | repeat u32 | 重复次数 |
| +0x3C | startMs u32 | 首波延迟 |
| +0x40 | intervalMs u32 | 波间隔 |
| +0x48 | astNormalSoldierInfo[15] | 15×16B ResSoldierTypeInfo |

`ResSoldierTypeInfo` 里的金币/经验/血量是**按 unitID 回查
`normalMonster` 行**得到的（战士 80/4150/7000·1860、法师
90/4150/8500·1700、弩车 192、炮车 300、机关战士 576、
主宰先锋 300），不是 312B 行内直接存三份数。

**普通 5v5 兵线链**（`series=5v5_1660`，蓝方 route 1）：

| 波次 | 组成 | repeat | start | interval |
|---|---|---:|---:|---:|
| 162320 | 战士×1 + 经验法师×2 | 8 | 10,000ms | 33,000ms |
| 162321 | 战士×1 + 法师×1 + **弩车**×1 | 11 | 0 | 33,000ms |
| 1623211 | 战士×1 + 法师×1 + **炮车**×1 | — | 0 | 33,000ms |

- 前 8 波是“经验法师”波（两个法师都带 4150 经验），第 9 波起
  转弩车，再转炮车；与 `AcntBattleLevel` 的
  `iSoldierActivateCountDelay1/2/Delay=0/5500/10000` 对齐。
- 超级兵 162340–162345：机关战士（576 金）+ 战士 + 法师；
- 主宰/风暴先锋 162346–162351：主宰先锋 300 金、repeat=2；
- `bSoldierType`：**1=MELEE、2=REMOTE、3=SUPER、16=DOMINATE_VANGUARD**；
- 另有 6000/4010/4012/10103 链（4010/4012 间隔 30s/29s），
  是不同地图/模式的波次族；普通 5v5 主样本以 1660 链为准。

**命名空间纠偏（重要）**：同一个数字在不同表里含义不同，必须带表名：

| 数字 | 所在表 | 含义 | 置信 |
|---|---|---|---|
| 5011/5041 | `CommonSettle.dwSettleByID` | 普通 5v5 主结算族 | medium（无直接关卡引用） |
| 5011/5041 | `EvaluateCond` | PVE 星级条件（击败怪医扁鹊/传送机关师孙膑） | high |
| 3041/4021 | `Level.bytes +0x74` 三元组 | PVE 星级条件 | high |
| 4021 | `soldierWave` | 红方波次 ID | high |
| 6xxx | `CommonSettle` | 结算族（10v10/排位候选） | low |
| 6xxx | `normalMonster` | 腥红石像等野怪名 | high（与 settle 族**无关**） |

→ 5xxx 已纠偏为 **PVE 第五章**；普通 5v5 settle 未定位；
`EvaluateCond` 的 5xxx 是另一张表的 PVE 条件，两者不矛盾，但
**不能互相引用**。6xxx 的 normalMonster 名称也不能拿来命名
CommonSettle 的 6xxx 族。5.83 注记里的“3xxx/4xxx/5xxx 缺失兵种”
应读作“缺失的 settle 族名”，不是兵种。

**产物**：`datasets/agent_normal5v5_soldiers.csv`（508 行，含
wave_slot 446 / evaluate_cond 72）、
`agent_normal5v5_soldiers_levels.csv`（99 行）、
`tools/agent_normal5v5_soldiers.py`。

## 5.90 玩家块完整布局与十人英雄 ID（智能体 N）

**5.84 的三处修正**：

1. **英雄 ID 就在块内**：`s+0x48` 的 **u16BE** 是英雄表
   `0x111C3C` 的 row_id（`s = off+0x10+nameLen+30`）；
   `s+0x6F` 是副本。5.84 的“块内无英雄 ID”不成立。
2. **本地玩家是 1558 佚名(\*:，不是 442**：录制者锚点是文件名
   后缀 `CBDD358E761B15A4DF526A179E8119E2`，它出现在 1558 的
   块里；13/13 个样本“含该 tag 的块”的 `s+0x48` 都等于头部
   `localHeroId`。442 是李信 507，1558 才是东皇太一 187。
3. **`off+0x08` 不是 recordLen**：它是账号等级类常量（7–30），
   并在 `post+0x10` 重复；名字后的 post 记录对所有人都恒为
   30 字节（`post+30+0x28` 的 hash 副本 172/172 命中）。

**块字段表**（主样本 442，块起点 0x60BC）：

| 相对偏移 | 类型 | 字段 | 442 值 |
|---|---|---|---|
| off+0x00 | u8 | team | 2 |
| off+0x01 | u8 | teamEcho（恒=team） | 2 |
| off+0x02 | u8 | 常量 0x01 | 1 |
| off+0x03 | u8 | slot | 0 |
| off+0x04 | u16BE | 保留 0 | 0 |
| off+0x06 | u16BE | entityID（战场单位 ID） | 442 |
| off+0x08 | u32BE | 账号等级类（7–30） | 30 |
| off+0x0C | u32BE | nameLen（含 NUL） | 19 |
| off+0x10 | utf8 | name | 李不信有归途 |
| post+0x00 | u32BE | flagA（2 或 hash 副本） | 2 |
| post+0x08 | u32LE | 账号 hash（s+0x28 重复） | 0x4D770A6C |
| post+0x0C | u32BE | 账号常量值（s+0x2C 重复） | 1460 |
| post+0x10 | u32BE | 等级副本 | 30 |
| post+0x14/0x18 | u32BE | 账号常量值 | 18362 / 5 |
| s+0x00 | u16BE | 账号常量值 | 423 |
| s+0x02…0x27 | — | 38B 零填充 | 0 |
| s+0x28/0x2C | u32 | hash / 常量副本 | 同 post |
| s+0x30…0x40 | u32BE | 账号常量值 | 1/2/6/0/0 |
| **s+0x48** | **u16BE** | **heroID** | **507 李信** |
| s+0x4A/0x4C/0x4E | u16BE | 0 或 2 / 3 / 1 | 2/3/1 |
| s+0x50, s+0x60 | bytes | 固定模式（16B/15B） | 全样本恒定 |
| s+0x6F | u16BE | heroID 副本 | 507 |
| s+0x71/0x75/0x76/0x7A | u32/u8 | 未知英雄相关值 | 994/8/14/517 |
| s+0xB8… | u8 | 英雄标签（1\|2, 4, …） | 2/4 |
| s+0xC8…块尾-19 | bytes | 不透明档案区（openid/头像/海报 URL、最近玩家 hash） | 5146B |
| 块尾-19 | bytes | 块脚（末 11B 恒定） | — |

不变量（172 块/20 样本全部命中）：`teamEcho==team`、
`off+0x02==1`、`off+0x08==post+0x10`、`post+0x0C==s+0x2C`、
`post+0x08==s+0x28`。

**主样本十人英雄映射**：

| 队 | 槽 | entityID | 玩家 | heroID | 英雄 |
|---|---:|---:|---|---:|---|
| 1 | 0 | 1729 | 桑忆终尘启 | 142 | 安琪拉 |
| 1 | 1 | 1965 | 碗面加香菜 | 558 | 影 |
| 1 | 2 | 1514 | 布鲁BIUBIU | 174 | 虞姬 |
| 1 | 3 | 1021 | 含泪吃兵线呢 | 159 | 朵莉亚 |
| 1 | 4 | 338 | 双枪踏浪行 | 518 | 马超 |
| 2 | 0 | 442 | 李不信有归途 | 507 | 李信 |
| 2 | 1 | 1966 | 酒梦灵心醉 | 151 | 孙权 |
| 2 | 2 | 1547 | 备水一站. | 107 | 赵云 |
| 2 | 3 | 1558 | 佚名(\*:（录制者） | 187 | 东皇太一 |
| 2 | 4 | 1833 | Vetymoment | 119 | 扁鹊 |

验证：录制者块 `s+0x48` == 头部 `localHeroId` 13/13；
20 样本 170/172 块落在英雄表内（2 个值为 1，应为表外新单位）；
主样本 10 人全表内且互不重复。

**6 个 5069040 样本的通用性**（`normal5v5_player_heroes_5069040.csv`）：
3 个 `ok` 样本各 10/10 块；3 个 `partial_players` 样本分别 9/2/2 块
（回放截断，不是布局失败）；43 行中 42 行 high，唯一 low 是
`entityID 1710 → heroID 1`（表外新单位）。录制者锚点
`CBDD358E…` 在每个样本里都落在“佚名(*:”玩家块。

**皮肤仍缺**：块内没有皮肤表引用（`heroID*100+idx` 区间 u32
全无命中）；`post+0x0C`/`s+0x2C` 是账号常量（同一玩家换英雄、
换局都不变）。唯一候选是尾部名单次值（每局变、10 的倍数），
但其归属表未解，不硬猜。

**5.36(b) 尾部名单修正**：每对首值 = 块 `+0x06` 的 entityID，
也等于帧流单位 ID（`abc_positions.csv` 里 1110/353/188… 一致）；
次值（300–1560、10 的倍数）不是 skinID/heroID，是每局变化的
未解编码。**尾部名单不是 heroID:skinID 交替表**。

**产物**：`tools/agent_player_block_schema.py`（`--verify-all`
复跑 13/13 锚点，`--abc` 可跑其它样本；5230306 build 同样适用）、
`datasets/agent_player_block_schema.csv`（474 行）、
`datasets/agent_normal5v5_player_heroes.csv`。

## 5.91 普通 5v5 完整度记分卡（2026-11-01）

产物 `datasets/normal5v5_coverage_scorecard.csv`：**30 项 = 16 decoded /
10 partial / 2 unknown / 2 blocked**。口径是“普通 5v5 主链”，不含
快速/10v10/PVE。

**已解（可直接用）**：

| 域 | 内容 | 证据 |
|---|---|---|
| 模式 | `confType1=50` | 25 样本一致 |
| 配置 | 32 个普通 5v5 配置（12 匹配+20 征召） | `AcntBattleLevel` 63 cfg1 过滤 |
| 初始金 | 300 | KV item7 + 32 配置 |
| 自然金表 | 3/s、40s 起、1000ms | `battleDynamicProperty` cfg1 |
| 小兵表 | 2,625 行 normalMonster | @0x679118 |
| 小兵数值 | 战士/法师/经验法师/弩车/炮车/机关战士/主宰先锋 | gold 50–576、exp 4150 |
| 兵线表 | 957 行 soldierWave | @0x1791ad8 |
| 首波时间轴 | 官方 S45：0:10/0:25/0:33，33s；回放 seq 0≈0:21.5 | 官方 + 6/6 首条 source4 4.0–5.1s→0:25.5–0:26.6（首击延迟 0.5–1.6s） |
| 兵线绑定 | 1660 H3：repeat=阶段波位数；弩车 4:01、炮车 10:04 | 与官方 S45 精确对上（medium-high；引擎确认待补） |
| 时间轴 | 5069040 offset=21.5±0.5s、20fps；主对局 11:16.2、续流 11:51.85 | 6 样本首条 source4 + 官方兵线表拟合；5247758 约 15.09fps |
| 金币流水 | 286 条 / 33,040 金 | `0x02 len=5`（含 0x80 命令体修正） |
| 野怪金币 | source6 96/96 金额=normalMonster 野怪底额±5；打野刀+20% 在 source5 230–254 | 5.97 |
| 十人名单 | 10/10 玩家 + heroID | 玩家块 `s+0x48` |
| 皮肤 | 玩家块 `s+0x7C`；10/10 命中皮肤表；1558=18700 经典 | 5.104 |
| 容器 | 5069040 帧流 / 5230306 TLV | 帧记录语法 |
| 操作流 | 坐标/朝向/命令 | 0x2c/0x2d/0x23/0x80（0x39 只在 5230306） |

**部分解（有表/有流，但缺一层证据）**：

- **逐单位补刀**：`0x02` 是金币变化聚合，没有单位 ID；187–219 有
  5–6 种自洽分解，**不能从金额反推单位类型**（5.96）。
- **当前/总金币**：`0x02` 只覆盖 25–35% 收入；1558 支出
  6,030–7,180、当前金币 0–5,800（low，见 5.103）。
- **击杀/助攻**：source43 6 杀/4 助；0x1e victim=unit object ID
  （0–994）；1558 K=0/A=0/D 不可得（5.101b/5.102）。
- **伤害/技能/目标**：0x1e 22 条只有 attacker/type/victim objectID、无 damage；0x29 10 条是混合状态（91060/11990/900011），不是技能释放日志；source44/47/51 只有 4 条固定底额目标奖励，不能定名。
- **表布局/原生表**：5.114 已闭合 CommonSettle 4 数组、Level 4 个
  byte buffer、AcntBattleLevel common 840B/gameplay 0x170B、Equip
  568B/17 属性/3 数组、buff 3 个 184B 效果槽；仍缺 normalMonster
  攻/防/成长/刷新、hero 成长曲线、buff param 公式、Equip 数组
  `p6/p7`。

**未解/阻塞**：

| 缺口 | 原因 |
|---|---|
| 普通 5v5 settle | 5xxx 已纠偏为 PVE 第五章（`+0x50` 首通奖励→RandomRewardStore 行名，不是 level_id）；普通 5v5 自己的 settle 行仍未定位 |
| 装备购买流水/当前金币 | 战斗表 `0x522bde8` 已解、方案/名称/价格已解；`0x87` 是技能升级，不是购买；无购买事件/金币快照 |
| 最终面板/KDA | 容器不含（29 .abc + 41 .ope 0 命中）；1558 K=0/A=0/D 不可得 |
| 运行时单位 ID | 0x1e victim 0–994 池 110/110 不可映射、0x2c target 1–359 池无英雄富集；缺 StepNotify/spawn 头（5.115） |
| 野怪刷新时间 | RefreshInfo 是商店；回放上界 BUFF≤0:23.8、边野≤0:25.9；配置不可读 |
| 星元/部件皮肤 | `s+0x7C` 只给基础皮肤；8 位星元/`stSkinPartWearing` 不在 |

**一句话**：普通 5v5 的“经济/兵线/名单/时间轴/基础皮肤”主链已经打通；
剩下的是 **普通 5v5 settle、购买流水/当前金币、逐单位归属、最终面板、
运行时单位 ID、野怪刷新、星元皮肤** 七类硬缺口，以及若干 medium
证据。

## 5.92 时间轴与首波：官方 S45 兵线表 + 回放 +21.5s 偏移

用户提供的 **S45 兵线时间表**（前 25 分钟）给出权威节奏：

- 首波 **0:10** 出生，**中路 0:25** 交汇，**边路 0:33** 交汇；
- 间隔 **33s**（±1s）；第 2 波 0:43/0:58/1:06，第 3 波 1:16/1:31/1:39；
- 第 8 波（4:01）起含弩车；10 分钟后炮车线；20:00 风暴龙王，
  击杀后接下来 2 波替换为风暴先锋；前 3 分钟防御塔减伤。

**回放侧**：6 个 5069040 样本的首条 source4 都在录制时间
4.0–5.1s，金额 88/187（小兵/攻城车）：

| 样本 | 首条 source4（录制秒） | 金额 |
|---|---:|---:|
| 20260924_113638 | 4.3 | 88 |
| 20260925_094930 | 4.5 | 88 |
| 20260925_095631 | 4.0 | 88 |
| 20260925_101323 | 4.0 | 187 |
| 20260925_103058 | 5.1 | 88 |
| 20260925_105224 | 4.7 | 88 |

如果 `game_time = recording + 21.5s`，首条补刀 = 25.5–26.6s，
落在官方 **中路 0:25** 后 0.5–1.6s（首击延迟）；第 2 条
6.7s→28.2s、第 3 条 11.6s→33.1s（边路 0:33）也吻合。
**所以回放 seq 0 ≈ 对局 0:21.5**，录制从开局约 21.5s 后才开始。之前 A（首波 0s）/B（首波 10s+10s
预录）/C（0/5.5/10s）都是基于“seq 0=0s”的假设，现全部作废。

**`soldierWave.start=10000` 就是首波 0:10**；`AcntBattleLevel` 的
`iSoldierActivateCountDelay1/2/Delay=0/5500/10000` **不是**前三波
出生时间（更像士兵激活/计数延迟），不要再用它覆盖官方节奏。

**1660 链对照（H3）**：`repeat` = 阶段波位数，末波直接用
`next` waveID。162320 repeat=8 覆盖 w1–w8（10…241s），
w8=241s=4:01 直接换成 162321（弩车）；162321 repeat=11 覆盖
w9–w19（274…604s），w19=604s=10:04 换成 1623211（炮车）。
与官方“第 8 波 4:01 弩车、10:00 炮车线”精确对上（弩车 0s、
炮车 +4s）。置信度 medium-high；仍需引擎侧
`SoldierWaveNextRepeatEventNode` 确认。

**不能用 source4 校验炮车**：主样本第 3 条 source4 在录制 11.6s
（对局 0:31.9）就是 194，而官方第一波炮车在 4:01；所以 194
**不是攻城车**，而是档位结算（见 5.96）。炮车波次只能靠
`soldierWave` 的 `repeat` 语义，不能用金额簇反推。

**自然金修正**：如果 seq 0 = 对局 21.5s，主样本对局时长 =
654.7+21.5 = 676.2s；自然金 = 3/s×(676.2−40) = **1,908.6/人**，
不是之前的 1,844.1。`player_economy_report_named.csv` 的
“支出前总金”需整体 +64 左右（扁鹊 7,159、安琪拉 6,440…）。

**产物**：`normal5v5_wave_timing_check.csv`（旧的 A/B 残差，
已被本节取代）、`normal5v5_player_timing_5069040.csv`（录制时间；
game_time = 录制+21.5s）。

## 5.93 双 build 事件字典：5069040 vs 5230306

主样本（5069040，普通 5v5）和快速样本（5230306）的**事件层不同**，
不能混用子类型。产物 `datasets/event_subtypes_by_build.csv`。

**5069040 `0x01` 子类型**（按 `data[0]`）：

| 子类型 | 长度 | 条数 | 首条 seq | 语义 |
|---|---:|---:|---:|---|
| 0x2d | 3 | 9,545 | 1,603 | 朝向 |
| 0x03 | 2 | 1,323 | 44 | ready/队伍状态 |
| 0x2c | 17 | 418 | 919 | 坐标/命令 |
| 0x23 | 2 | 249 | 74 | 逐英雄 bool |
| 0x00 | 12/23/65 | 120/20/4 | 119/680/4735 | 全局标量/位置 |
| 0x87 | 5 | 44 | 266 | 未知（候选技能/经验） |
| 0x1e | 19 | 21 | 1,064 | 伤害表 |
| 0x29 | 17 | 10 | 1,580 | 技能/回城 |
| 0x1f | 28 | 3 | 2,188 | 高光通知 |
| 0x20 | 20 | 1 | 2,136 | 高光详情 |
| 0x48 | 9 | 1 | 2,144 | 未知 |

**5069040 `0x02` flag**：

| flag | 长度 | 条数 | 语义 |
|---|---:|---:|---|
| 0x81 | 1 | 970 | USEDIRECTIONALSKILL（旧 1B 读法已推翻） |
| 0x80 | 12B 体 | 687* | 帧命令（专用解析器 703 条） |
| 0x82 | 2 | 436 | 瞄准/攻击（`02ff`） |
| 0x85 | 5 | 281 | **BUYEQUIP**（旧“金币流水”读法已推翻） |
| 0x87 | 7 | 135 | 未知（候选经验/技能） |
| 0x00 | 0 | 78 | 空 |
| 0x86 | 6 | 1 | 稀有 |

\* `abc_tags_full.parse_payload` 对 flag 0x80 只按 len=0 处理，不消费
12B 体，条数与后续对齐会偏；命令数以 `abc_frame_cmds.py` 的 703 为准。

**5230306 TLV 类型**：`01/00` 1,763、`02/80` 5、`02/81` 20（击杀位置
通知）、`02/83` 476、`02/84` 599、`02/85` 7、`02/87` 8。

**结论**：`0x39` POV 位置、`0x38` 目标/buff、`0x8a` 逐英雄状态、
`02/84` 击杀通知**只在 5230306/快速样本**；普通 5v5 主样本没有这些，
不能用它们补普通 5v5 的击杀/状态。普通 5v5 的击杀归属仍只能靠
source43（203/102）+ `0x1f`/`0x20`。

**3 个完整 5069040 样本的事件稳定性**（`event_subtypes_5069040_full.csv`）：
`0x2c` 137/34/418、`0x23` 106/51/249、`0x1e` 37/42/21、
`0x02/0x85` 608/474/281、`0x02/0x81` 810/706/970、
`0x02/0x82` 135/56/436 都出现；**`0x2d` 只在主样本出现（9,545），
另外两个为 0**——印证 `0x2d` 是本地/POV 玩家专属，不能拿它做
全样本统计。

## 5.94 operator 流第二层：能解压，但记录布局仍多解

> **已修正（见 5.98）**：没有 27B 流头；首记录在 offset 0，是
> GameCoreFrameOpe(frame=256, unityFrame=61255)；UIEventOpe 是
> `0B 7D <ULEB128 EventID>`。5.94 的 0x5cb/0xc6 是错误头导致的
> 错位，不是真实类型。

主样本 `.ope`（196,031 B）的链路本轮推进到：

1. 外层 `0x01 + raw DEFLATE` → inner **195,988 B**；
2. `inner[0x90:]` 再 raw DEFLATE → **436,738 B** 操作流；
3. 首字节 `02 00 01 c7 de 03 05 7e 00 00 10 da…`，呈
   `GameCoreFrame/Touch/UnityFrame` 循环，确认是操作记录，不是经济。

**卡点不是解压，而是记录边界**：

- 27B 头候选 `inner[0x75:0x90]`（`30 3a 35 32 3a 32 34 00 …`）
  拼上后，`operator_stream.py` 在 `0x5cb` 遇到 `type=0xc6`；该值
  不在 `emOperatorDataType` 的 0–26 内，是**前一条记录长度选错**
  造成的错位，不是新类型。
- 暴力扫起点 0–40 × UILayout 长度 0–4096、试 1-based 枚举、
  用 `operator_wire_table.json` 的实测长度过滤，**都没有推进到结尾**；
  最远约 `0x58d`。
- 典型歧义：`MoveOpe` 同一位置可用 5 个或 7 个 varint 布局，
  7-varint 版本能多推进一段但最终落入 `0xc6`；5-varint 版本在
  `0x589` 处能接上另一个 `0x06`，说明**需要更强的字段级约束**
  （C# `Write` 顺序或逐类型长度直方图），不能只靠 DP 的最远推进。

**结论**：operator 流是客户端输入（Touch/Move/Skill/UI），即使完全
解通也**不保证含购买/装备金额**；支出/装备仍按 5.91 的 blocked 处理。
不要把它当作金币来源，也不要用它反推当前金币。

**产物**：`operator_stream.py`（只读解析器）、
`data/replays/_analysis/tools/operator_wire_table.json`（类型/长度
直方图）、`tests/test_operator_stream.py`。

## 5.95 十人经济表（含英雄名，2026-11-01）

把 5.85 的事件金和 5.90 的 entityID→heroID 合并，得到可直接用的
`datasets/player_economy_report_named.csv`。自然金基准
3/s×(654.7+21.5−40)=**1,908.6/人**（回放 seq 0 ≈ 对局 0:21.5，
见 5.92）；表里的 ±1 是偏移 ±0.5s 的误差余量。支出未知，所以
“总金”是**支出前**区间。**视频只有快速赛录制，不能用于普通 5v5
验证**；本表只依赖回放 + 官方普通 5v5 兵线表。

| 玩家 | 英雄 | 职业 | 事件金 | 支出前总金（下限–上限） |
|---|---|---|---:|---:|
| Vetymoment | 扁鹊 | 阵地法师 | 4,951 | 7,159–7,161 |
| 桑忆终尘启 | 安琪拉 | 炮台法师 | 4,232 | 6,440–6,442 |
| 双枪踏浪行 | 马超 | 刺杀战士 | 4,118 | 6,326–6,328 |
| 李不信有归途 | 李信 | 狂战士 | 3,472 | 5,680–5,682 |
| 备水一站. | 赵云 | 刺杀战士 | 3,329 | 5,537–5,539 |
| 布鲁BIUBIU | 虞姬 | 连珠射手 | 2,951 | 5,159–5,161 |
| 酒梦灵心醉 | 孙权 | 灵巧射手 | 2,887 | 5,095–5,097 |
| 碗面加香菜 | 影 | 冲锋战士 | 2,527 | 4,735–4,737 |
| 佚名(\*: | 东皇太一 | 进攻辅助 | 2,399 | 4,607–4,609 |
| 含泪吃兵线呢 | 朵莉亚 | 增益辅助 | 2,174 | 4,382–4,384 |

**注意**：事件金是 `0x02` 可观测子集（25–35% 收入，见 5.96），
不是全量事件金；不含初始 300/自然金/支出。“支出前总金”是**下限**，
只用于量级对拍，不是游戏内当前金币。**实际打野刀持有人**
（source5 230–254）是马超 727、赵云 981；source6 是辅助/游走拿
边野的全额击杀金，不是分享金（见 5.97）。影没有野怪通道，可能
不是本局实际打野；“职业”列是英雄职业，不是分路。

**六样本流水汇总**（`normal5v5_gold_ledger_5069040.csv` /
`normal5v5_gold_summary_5069040.csv`，工具
`tools/normal5v5_gold_ledger_5069040.py`）：

| 样本 | 事件数 | 事件金 | 玩家块 | 是否普通 5v5 |
|---|---:|---:|---|---|
| 20260924_113638 | 229 | 27,720 | 9/10（partial） | 是（缺 1 块） |
| 20260925_094930 | 28 | 3,700 | 2/10（partial） | **否**（1v1/3v3 或严重截断） |
| 20260925_095631 | 36 | 4,912 | 2/10（partial） | **否**（同上） |
| 20260925_101323 | 626 | 68,149 | 10/10 | 是 |
| 20260925_103058 | 492 | 45,745 | 10/10 | 是 |
| 20260925_105224 | 286 | 33,040 | 10/10 | 是 |
| **普通 5v5 小计** | **1,633** | **174,654** | — | 3 完整 + 1 缺 1 块 |

两个 2 人样本的事件数/金币不能当普通 5v5 统计；它们的玩家块仍
可用来验证 `s+0x48` 布局，但模式不是 5v5。三个 `ok` 样本的
玩家/英雄映射完整。

**首条 source4 时间（`normal5v5_player_timing_5069040.csv`）**：
三个完整样本里最早的一批是 **4.0–5.1s**（妲己 4.0、鲁班 4.6、
影 4.65、酒梦 4.85、马可 5.1），加上回放 +21.5s 偏移后是
**对局 0:25.5–0:26.6**，落在官方普通 5v5 **中路 0:25 交汇**后 0.5–1.6s；
随后是 6.65–11.55s（对局 0:27–0:32，边路 0:33），21.05s 的虞姬，
100s+ 的多是辅助/打野（不补刀）。这张表只用于节奏/角色参考，
不硬判分路。

## 5.96 逐单位补刀归属：阴性结论 + `0x02` 覆盖率修正（智能体）

**结论：在 build 5069040 上，逐单位补刀/击杀归属不可得（high）**。
三条独立证据：

1. **位宽不够**：`0x02/0x85` payload 恰好 5 字节 =
   `source:u8 + amount:u32LE`，没有单位 ID 的位置；
2. **零锚点**：全量 13,061 条记录的 u16 位置扫描，10 人 entityID
   无富集（唯一的“富集”是朝向值 338 撞 entityID 338，已排除）；
3. **零对齐**：21 条 `0x1e` 与金币同英雄 ±40 帧只有 2/21、
   同 seq 0/21；`0x81` 对 `0x85 source4` 的 lift=0.30（负相关）。

**最强的可确认字段**：

| 字段 | 含义 | 置信度 |
|---|---|---|
| `0x02/0x87 data[3]` | **actorID**，与 envelope entityID 双射（1547→51、338→8…），跨样本按槽位稳定 | high |
| `0x02/0x85 data[0], data[1:5]` | source / u32LE 金额 | high |
| `0x01/0x1e data[1], data[16:18]` | type∈{2,3,4} / victim u16BE | layout high、语义 low |
| `0x02/0x81 data[0]` | 值域 {1,2,3,4,6}，与朝向 lift=3.21、与金币 lift=0.30 → 动作类，非结算 | medium |
| `0x01/0x2c data[16]` | 逐英雄 u8 回绕计数器，非 actorID | high |

**187–219 的拆解歧义**：在兵种金币集 `{60,80,90,117,120,192}` 内、
尾数 ≤20 时，每个金额仍有 5–6 种自洽分解（1×攻城车 192+尾数 /
2×法师兵 180+尾数 / 3×战士兵 180+尾数…），回放里没有可读字段
能区分。source 互斥（击杀/助攻走 43 的 202/203/102、野怪走 6 的
165–201）只能把方向压到“兵”，不能给单位类型。

**source4 不是逐次补刀，而是同档位的一次结算**：单玩家 source4
均值分层明显（1514/1965/1966 ≈ 97–98；338/442/1547 ≈ 115–120；
1729/1833/1558 ≈ 193–195）。这解释了 87/187 两簇：它们是
**档位结算额**，不是“一刀 80/192”。

**`0x02` 覆盖率只有 25–35%**：全 source 合计 33,040、人均 3,304，
而 11 分钟单人收入量级 8,000–15,000。所以：

- `0x02` 流水是**可观测事件金的子集**，不是全量事件金；
- 5.85/5.86/5.95 的“事件金/支出前总金”只能当**下限**；
- “当前金币”仍不能由 0x02 + 自然金闭合，支出/未知收入都缺。

**数据集降级**：`player_minion_types.csv` 的 melee/ranged/elite/
siege/cannon 已改名为 `amount_80_95/96_120/121_159/180_196/
197plus`，并加 `confidence=low (amount band, not unit type)`；
`agent_normal5v5_reconciliation.csv` 里的 siege/cannon 也只是
金额簇候选，不能当兵种。

**产物**：`tools/agent_last_hit_units.py`、
`datasets/agent_last_hit_units.csv`（571 行、15 个 record_type）、
`datasets/agent_last_hit_units.md`。

## 5.97 source6 = 野怪击杀全额金；打野刀 +20% 在 source5 230–254（智能体）

**结论：source6 不是助攻/分享金，也不是辅助装周期金，而是
野怪击杀金（基础全额）**。证据（high）：

- 20 个可解析样本 source6 原始 110 条 / 19,588 金；去重后
  96 条 / 17,138 金（14 条重复全部是 20260925_101323 的
  15×175 通知簇）。
- **96/96 条金额落在 normalMonster 野怪底额 ±5 内**，50/96 在 ±2，
  中位偏差 2.0：160→165、174→175、178→178、180→185、
  190→188/189/191、200→201、210→211。
- 按 25% 或 50% 分成反推，底额中位误差 490 金、**0/96 命中**；
  与 source4 的比例 0.05–2.79（中位 0.39），不是固定分成。
- 同帧同队 source4/5/43 事件 0 条，后面也没有稳定的击杀/助攻组合。

**领取者**：辅助/游走 81/96（84.4%）、中/法 7、边/坦 5、未知 3、
**打野 0、射手 0**；5069040 去重后辅助 20/26（76.9%），
把低补刀的夏侯惇按游走计则 23/26（88.5%）。18 个有 source6 的样本，
首个 source6 全部是 165，17/18 为辅助/游走。→ 辅助装“游击/分享”
解释了**为什么是辅助拿**，但金额本身是 100% 底额。

**打野金在 source5 230–254**：94/94 条满足
`金额 ≈ 野怪底额 × 1.20 + 1–3 尾数`：

| 野怪底额 | source5 金额 |
|---:|---|
| 190（石像） | 231 |
| 200（主宰/先锋） | 241/242/243 |
| 210 | 251/252/253/254 |

这是打野刀/惩击“自己击杀或 500 范围内友方击杀野怪，额外获得
20% 金币”的通道（字段候选 `dwEquipJungleShangJinCoin`，金额公式
high、字段名 medium）。**主样本**：备水（赵云）4/981
（231+243+253+254）、双枪（马超）2/484（231+253）；影 0 条。
source6 与 source5 230–254 的领取者在 17/18 个样本中完全不相交。

**开局**：31 个“同队两条通道都有”的队对中，26 对的首个 source6
与首个 source5 230–254 时间差在 ±10s 内，中位 2.4s；全部是
source6=165、source5=231。→ 打野拿 BUFF（190 底额×1.2=231）、
辅助拿边野（160+5=165）的并行开局，不是辅助抢 BUFF。

**角色修正**：按 source5 230–254，主样本 team1 的早期打野刀
持有人是**马超**（231@4.1s、253@461.9s），team2 是**赵云**
（231@3.5s、243@52.7s、253@332.9s、254@425.6s）。**影没有
230–254，也没有 source6，事件金 2,527 为主样本最低**；背景把
影标成打野与黄金通道不一致（可能是角色互换、马超带打野刀/偷野，
或影的打野刀等级不同）。所以 5.95 的“职业”列是**英雄职业**，
不是本局实际分路；实际打野刀持有人以 source5 230–254 为准。

**对旧结论的修正**：

- 5.85 的“目标/推塔 231–254 + source51 = 1,973”应拆成
  **打野刀 1,465**（备水 981 + 双枪 484）+ **source51 508**
  （双枪/李不信各 254）；
- 5.88.4 的“231–254 是目标/团队金候选”作废，改判打野刀 +20%；
- 5.95 的“两个打野事件金偏低”应改为“赵云/马超的 230–254 是
  打野刀 +20%；影没有野怪通道，可能不是实际打野”。

**仍缺**：回放没有逐单位野怪 ID/击杀者，无法把每条 source6 对到
具体野怪实体，也无法证明辅助每次是单人 100% 还是与队友同范围
25–50%；购买/装备仍被 operator 阻塞。

**产物**：`tools/agent_source6_attribution.py`、
`datasets/agent_source6_attribution.csv`、
`datasets/agent_source6_attribution.md`。

## 5.98 支出/装备：5069040 回放侧不可得（智能体）

> **已修正（见 5.100）**：`0x02/0x87` 是装备购买/升级时序
> （actorID/tier/slot），玩家块有 4 套出装方案 item ID。支出不再
> 是“不可得”，而是“购买时序已得、价格映射部分”。

**结论：build 5069040 的支出/装备无法从现有回放得到（high，覆盖
6 个 5069040 样本 + 30 个去重 `.ope`；不证明“永远不写”）**。

**operator 流格式修正（推翻 5.94 的 27B 头）**：

- 主 `.ope`：196,031 B → 外层 raw DEFLATE 195,988 B →
  `inner[0x90:]` raw DEFLATE 436,738 B；**没有 27B 流头**，
  首记录就是 `02 00 01 c7 de 03` = GameCoreFrameOpe
  (frame=256, unityFrame=61255)。之前把前 4 条记录误读成头。
- **UIEventOpe = `0B 7D <ULEB128 EventID>`**，不是普通
  `0B <varint>`。主样本 1,981 条、30 个不同 ID；Top：
  1105/1106 各 700、1139/1141 各 136、1009/1011 各 62、1144 14。
- 高置信记录：SkillSlotOpe 11,953 条（`13 AE 01 slot value`，5B）、
  UILayout 129B、GameObjectNameOpe 3 条（只有相机路径）。

**operator 流没有商店/购买/装备证据**：

- 30 个去重 `.ope` 全扫：`1194 Battle_EquipBoughtEffectPlayEnd`、
  `1206 Battle_PickDropItem`、`1248–1276 Purchase_*` **全部 0 命中**；
- 唯一命中的商店/掉落类 ID 是 `1144 Battle_OnCloseDropItemDetail`
  （855 次），只是“关闭掉落物详情”，无 item/price；
- 可读 ASCII 只有 3 条相机路径，`Shop/Store/Buy/Equip/Mall/Coin`
  关键词 0 命中；`UiEventOperatorData` metadata 只有 `EventID` 字段，
  即使命中商店按钮也没有金额字段。

**5069040 `.abc` 只有收入，没有支出/装备**：

- `02/85` 286 条（修正 0x80 命令体后），payload =
  `source:u8 + amount:u32LE`，金额 31–254，**零额 0、负额 0**；
- `02/87 len7` 548 条：`00 00 00 <id:u8> <level:u8> 00 00`，
  id 7–65、level 1–4；不是 Equip 表 row_id（1111–5536）；
- `02/80` 帧命令 3,269 条，cmd_type 只有 1–9、15；
  **没有 22 InOutEquipShop、23 ChangeUsedRecommendEquipGroup、
  35 OneStepBuyEquip**；
- Equip 表 270 个 row_id 当结构化字段扫描：**0 命中**。

**5230306 对照**：`20261028_135516.abc` 的 `02/85` 是
`type:u8 + item:u16`，7 条装备 item（type6:165、type5:146、
type6:175、type5:41、type6:185、type4:194、type5:44）；首条
13.9s、item 165（辅助宝石）。**同一 flag 在 5069040 是金币流水，
在 5230306 是装备 item，不能混用**；且它仍无价格/金额，不能补
5069040 的支出。

**支出能否从回放侧得到**：5069040 **不能**。回放只能给收入侧
（`02/85` + 自然金区间），没有当前金币/累计金币快照，也没有
装备 item/price；支出 = 累计金币 − 当前金币，第二项不在容器里。

**下一步最小验证**：

1. 录一段 5069040 对局 + 屏幕金币，在已知购买时刻检查 `.ope`
   是否出现新的 UIEventID（尤其 1194/1206/1248–1276）；
2. 找 5069040 上出现 `02 85 <type> <item>` 的样本（5230306 型）；
3. 用录屏 OCR 当前金币，与 `300 + 02/85 收入 + 3/s×(t−40)`
   做差，差值即支出（当前不依赖模拟的唯一闭环）。

**产物**：`tools/agent_operator_spending.py`、
`datasets/agent_operator_spending.csv`（479 行逐文件逐签名证据）、
`datasets/agent_operator_spending.md`。

## 5.99 普通 5v5 当前结论总表（2026-11-01）

| 项 | 结论 | 置信 |
|---|---|---|
| 模式 | `confType1=50` 是常量，不是普通/快速判别；普通 5v5 用 `dwDynamicPropertyCfg=1` + 官方兵线表 | high |
| 样本 | 5069040 共 6 个：3 个完整 10/10、1 个 9/10、2 个 2/10（1v1/3v3/截断，不计入） | high |
| 时间轴 | 官方 S45：首波 0:10、中 0:25、边 0:33、33s；回放 seq 0≈对局 0:21.5（+21.5s） | high |
| 时长 | 主对局 11:16.2（13,061 帧/20fps=10:53 录制）；第二段续流到 11:51.85 | high（主）/medium（续流） |
| 兵线 | 1660 H3：repeat=阶段波位数；弩车 4:01、炮车 10:04，与官方精确对上 | medium-high |
| 初始金 | 300 | high |
| 自然金 | 3/s、40s 起、1000ms；主样本约 1,908.6/人（对局 676.2s） | high（表）/medium（时长） |
| 0x02 流水 | 286 条 / 33,040 金；只覆盖 25–35% 收入，是下限 | high（计数）/medium（覆盖率） |
| source4 | 小兵/攻城车**档位结算额**，不是逐次补刀；187–219 有 5–6 种分解 | high（阴性） |
| source6 | 野怪击杀**全额金**；领取者辅助/游走 81/96；不是分享金 | high |
| 打野刀 | source5 230–254 = 野怪底额×1.2+尾数；主样本 马超 727、赵云 981；影 0 | high（金额）/medium（字段名） |
| source5 131–146 | 辅助装/被动/团队金混合，未拆开 | medium |
| 结算 5xxx | **PVE 第五章**（`+0x50 astFirstCompleteReward`→RandomRewardStore 行名）；普通 5v5 settle 未定位 | high（PVE）/unknown（普通5v5） |
| 十人 | 10/10 entityID/heroID/职业；实际打野刀持有人 马超/赵云，影无野怪通道 | high（英雄）/medium（分路） |
| 支出/装备 | 战斗表 `0x522bde8` + 玩家块 4 套方案 + 官方名称/价格已解；`0x87` 是技能升级，不是购买；购买流水/当前金币不在容器 | medium（方案）/low（当前金币） |
| 皮肤 | 玩家块 `s+0x7C`；10/10 命中皮肤表；1558=18700 经典；星元/部件 partial | high（基础）/partial（星元） |
| 最终面板 | 容器不含；录屏只有快速赛，不能用于普通 5v5 | blocked |
| 逐单位补刀 | 0x02 无单位 ID；0x1e/0x81 零对齐 | high（阴性） |
| 野怪刷新 | RefreshInfo 是商店；回放上界 BUFF≤0:23.8、边野≤0:25.9；配置不可读 | unknown（配置）/medium（上界） |

**一句话**：普通 5v5 的时间轴、兵线、单位表、十人名单、野怪/打野刀
通道、基础皮肤、战斗装备表/方案已经闭环；普通 5v5 settle、购买
流水/当前金币、逐单位补刀、最终面板仍是硬缺口。

## 5.100 装备购买时序：`0x02/0x87` = actorID/tier/slot（2026-11-01）

> **已修正（见 5.102）**：`0x87` 是**技能升级**（actorID/skill/
> levelIdx），不是装备购买；5.100 的 6 槽出装映射作废。装备只有
> 玩家块的 4 套赛前方案（官方 item.json 名称/价格），购买时序/
> 扣金不在容器。

**（以下 5.100 正文是历史错误推导，保留作对照；正确结论见 5.102/5.103。）**

**这推翻了 5.98 的“装备不可得”**：回放里确实有购买/升级时序，
只是之前把 `0x87` 当成了技能/未知事件。

**格式**：`0x02 flag=0x87 len=7` =
`00 00 00 <actorID:u8> <tier:u8> <slot:u8> 00 00`。
- 主样本 **139 条**，10 人各 12–15 条；
- `actorID` 每人恒定（1558→12、1547→51、338→8、442→44…）；
- `tier` 1–4 = 装备档位；`slot` 0–5 = 6 个装备槽。

**本地玩家 1558 佚名(\*:（东皇太一）的购买/升级时序**：

| 对局时间 | 录制 seq | tier | slot | 说明 |
|---:|---:|---:|---:|---|
| 0:25 | 102 | 1 | 0 | 第一件（鞋/辅助装） |
| 0:57 | 742 | 2 | 0 | slot0 升 2 档 |
| 1:28 | 1348 | 1 | 1 | slot1 第一件 |
| 2:30 | 2601 | 3 | 0 | slot0 升 3 档 |
| 2:59 | 3165 | 1 | 2 | slot2 第一件 |
| 4:26 | 4915 | 1 | 3 | slot3 第一件 |
| 5:10 | 5786 | 3 | 1 | slot1 升 3 档 |
| 5:54 | 6680 | 1 | 4 | slot4 第一件 |
| 6:11 | 7423 | 2 | 2 | slot2 升 2 档 |
| 7:28 | 8554 | 1 | 5 | slot5 第一件 |
| 7:43 | 9252 | 3 | 2 | slot2 升 3 档 |
| 8:54 | 10669 | 2 | 3 | slot3 升 2 档 |
| 9:59 | 11977 | 2 | 4 | slot4 升 2 档 |

**玩家块出装方案**：每个玩家块有 **4 套方案 × 12 个 item ID**
（`normal5v5_equipment_plans_5069040.csv`，372 行，32 套去重）。
本地玩家 1558 的 4 套：

| 方案 | 装备（官方 item.json，括号成品总价） |
|---|---|
| 热门套装 | 1701 学识宝石(300)、1422 抵抗之靴(700)、1714 近卫(850)、1332 霸者重装(2450)、1753 近卫·奔狼(2080)、1325 守护者之铠(800)、1333 不祥征兆(2020)、1347 永夜守护(2020)、1337 贤者的庇护(2280) |
| 原辅助坦克 | 1753 近卫·奔狼(2080)、1423 冷静之靴(700)、1332 霸者重装(2450)、1325 守护者之铠(800)、1335 魔女斗篷(2020)、1328 血魔之怒(2180)、1337 贤者的庇护(2280) |
| 坦克开团流 | 1701 学识宝石(300)、1422 抵抗之靴(700)、1714 近卫(850)、1332 霸者重装(2450)、1724 近卫·救赎(2080)、1723 极影·奔狼(2080)、1347 永夜守护(2020)、1333 不祥征兆(2020) |
| 天龙灭世流 | 1411 神速之靴(250)、1423 冷静之靴(700)、1233 回响之杖(2050)、1232 博学者之怒(2140)、1235 痛苦面具(2080)、1231 虚无法杖(2040)、1239 辉月(2080)、1337 贤者的庇护(2280)、1242 难知·月神(3340) |

**名称/价格来源**：`https://pvp.qq.com/web201605/js/item.json`
（115 件，`item_id/item_name/price/total_price`）。之前用
`122340616` 的“磐如山/超新星轰炸…”是**错的**，已全部替换。
`134_Equip` 只是 270 行子集；官方 JSON 才是完整 115 件。所以：

- **购买时序**：已解（0x87）；
- **出装方案/item ID/名称/成品价**：已解（玩家块 + 官方 item.json）；
- **实际扣金**：按 `tier` 增量/合成费算，仍 partial；前 6 件方案标价合计 7,180。
  `slot/tier` 也可能是同一槽位升级链（slot0 t1/t2/t3 = 学识宝石→近卫→近卫·奔狼），
  精确映射待合成树/更多样本。

**产物**：`normal5v5_equipment_upgrades_5069040.csv`（139 行）、
`normal5v5_equipment_plans_5069040.csv`（372 行，官方 item.json 名称/价格）、
`pvp_item.json` / `pvp_items_115.csv`（官方 115 件装备）、
`player_economy_report_named.csv`（可叠加购买时序）。

**本地玩家 1558 单局报告**：`datasets/player_1558_normal5v5_report.md`
（金币 2,399、4 套方案、13 条购买时序、source6 3/541、无打野刀通道）。

---

## 5.101 三条未解项复核（2026-11-01，普通 5v5）

> 范围：普通 5v5。`20261028_135516`（孙膑、茉莉花与雨）是快速赛，
> 只用于格式对照，不并入普通 5v5 的布局真值。

### 5.101.1 页加密与反汇编偏移

- 用 live dump `runtime_dump/code_5977000.bin` 复核：`VA − 0x51000` +
  逐字 XOR 0xE3，`0x5977000` / `0x5978000` 两页各 **1024/1024 字逐字节一致**。
  这一段可以完全离线反汇编。
- `0x5980xxx` 段用 `VA − 0x1000` 反汇编得到干净函数；同一段用
  `VA − 0x51000` 是错位代码。偏移要按块/段判断，不能全局统一（与 5.12/5.36 一致）。
- `OperatorMonitorModule.Write`（0x5980b64）实测：先
  `cmp [x0+0x10], #0x54`，再把 `[x0+0x18]..[x0+0x6d]` 的字段搬到
  x1..x7/栈参数——这是**字段编组**，不是 `.ope` 位流写入。
  `*OperatorData.Write`（0x5977430）同理。两条“从 Write 拿位宽”的路线排除。

### 5.101.2 `.ope` 记录布局

- 样本分组：普通 5v5 `20260925_105224`（12.1.1.8，196,031 B，流 436,738 B）、
  新普通 5v5 `20261101_182452`（12.1.1.26/build 5247758，confType1=50，
  53 条 KV，10 人含 AI；`.abc` 201,314 B，`.ope` 16,248 B，流 46,900 B）
  与快速赛 `20261028_135516`（12.1.1.23，14,355 B，流 39,634 B）。
  资源版本不同，记录布局不能混用。
- `.ope` 内层是 **raw DEFLATE**，不是 Oodle；payload 起点随版本变化：
  快速赛 0x8B、旧普通 5v5 0x90、新普通 5v5 0x91。
- 同局 `.abc` 的本地 1804（大禹）有 12 条技能事件（`skill` 1/2/3 +
  `levelIndex` 0..5，是**技能升级**，不是释放）、19 条金币事件、
  156 个位置样本；在 `.ope` 里按这些帧号搜 03/04/05/06/0C 记录，
  **0 命中**（只有一条 GameCoreFrame 9136 命中），说明 `.abc`
  技能升级事件不能直接锚定 `.ope` 的 SkillUse；下一锚点应用
  位置/金币事件或 SkillSlot 升级状态。
- 新普通 5v5 流用现有布局可以拼到流尾（0xb733/46,900，9,383 条记录，
  509 条 tentative、1,098 处歧义），但字段语义门禁失败
  （`SkillUseOpe.slotType` 到 33,554,431、`unityFrame` 出现 0xFFFFFFFF），
  这是**假完整解析**，不能当已破解；`tools/ope_parse.py` /
  `tools/ope_status.py` 已加 `semanticOk` 门禁，审计里标记
  `boundary parsed=1, semantic=0`。
- 快速赛流在 0x1b 处是 126 B 的 UILayout（type 0x16，payload 123），
  0x99 起是 `13 AE 01 <slot> <value>`；现有解析器
  （`operator_stream.py`）推进到 **0x3556** 报墙（本样本 39,634 B 的
  34.5%；5.94 的 13.5% 是旧分母）。
- 普通 5v5 流从 0 开始（首条 `02 00 01 c7 de 03` = GameCoreFrameOpe
  frame=256, unityFrame=61255），**没有 27 B 头**；用 123 作 UILayout
  长度只能推进到 **0x58d（1,421 B）**，type 0x89 报墙。把 SkillSlot
  限制为 5 B 只到 0x22f，限制为 4 B 仍是 0x58d——歧义是真实的，
  不是单个偏移造成的。
- 结论：`operator_stream.py` 的全局 `HEADER_BYTES=27` 和
  `stream[7:11]` 取 UILayout 长度只适用于快速赛样本；普通 5v5 需要
  按样本检测头/长度，并且缺记录布局。当前未解。
- 继续往下挖到的真实序列化链（2026-11-01）：
  `ClientRecordSystem.SaveOperatorFile` → `ClientRecordModule.WriteToFile/
  WriteToBytes`（0x59bd0b4/0x59bd0f4）→ `ClientRecordModuleUtility.
  WriteString/WriteMemeoryStream`（0x59bda5c/0x59bda90）→
  `UnityService.LevelManagement.Serialization.BinaryFileWriter`
  （`WriteByteArray/WriteByte/WriteInt/WriteUInt/WriteFloat/WriteString/
  WriteVector4`，0x8d4bf9c–0x8d4c198）。`OperatorMonitorModule` 自身
  有 `memoryStream` / `binaryWriter` / `batchStream` / `batchWriter`
  四个字段，`BatchPush` 新建 MemoryStream 后写到 `this+8`。
- 因此 `.ope` 的字段顺序不在 `OperatorData.Write`（0x5977430 一类
  是字段编组/虚调用桩），而在实现 `IClientRecordEntity.Write` 的
  实体（候选 `OperatorDataPlayer`/`ClientRecordModule`）里对
  `BinaryFileWriter` 的调用顺序。下一步是反这个实体的 `Write`，
  再用同一资源版本的第二个普通 5v5 `.ope` 做差分；快速赛样本不能
  作为普通 5v5 的布局真值。

### 5.101.3 连续轨迹

- `.abc` 已解的是**输入/事件**：`0x2c` 1,528 条离散目标点
  （攻击/技能指示器/信号）、`0x2d` 16,315 个朝向样本；不是逐帧位置。
- `CmdCompressPlayerInfo`（Assets.Scripts.GameLogic）4 字段：
  `maxCampPosBitCnt`、`maxCampCnt`、`maxCampPosCnt`、`m_compressPlayerList`；
  方法 `GetPlayerByCompressInfo` / `AddCompressPlayerInfo` / `Clear` /
  `GetPlayerCampInfo` 是容器辅助，不是状态解码器。它压缩的是
  Move/CommonAtk **输入**，不是状态快照。
- 因此“解出 `CmdCompressPlayerInfo` 位域”能得到**压缩后的输入位置**，
  不能得到连续轨迹；连续轨迹只能来自 GameCore lockstep 模拟
  （G1–G5 目前 0/5）或服务器数据。这条应作为定论，不再在 `.abc`
  里找连续坐标。

### 5.101.4 静态表

- 825 张 C# databin 表已落盘并逐块校验；字段名 533/825（64.6%），
  布局验证 78 张；约 451 张布局待解（数组/结构体/布尔打包），
  约 300 张原生/未知表没有 C# 行类；原生目录 1,443 张/49,202 名称，
  约 300 张数值字段未对位。
- 已解核心表包括英雄、装备、小兵（normalMonster 2,625 行）、
  兵线（soldierWave 957 行）、部分 buff（14,914 行）；数组/嵌套结构
  已有模型：`ResTaskDyncValue` 5×int32@12、`ResAlbum` 15×uint32@32、
  `ResDT_RewardItem` 12 B 等（`datasets/agent_arrays/`、
  `datasets/agent_nested_structs/`）。
- 剩余 451 张主要是 UI/活动/长尾表；需要数组/结构体/布尔感知的
  布局解算器，不是逐表手解。优先级应按分析需求（英雄/装备/技能/
  野怪）而不是按表数量。

### 5.101.5 复现

```powershell
python tools/ope_status.py
```

输出 `data/replays/_analysis/datasets/ope_status.csv`：逐 `.ope` 的
客户端/资源/构建版本、缓存流、解析结果与报墙位置；`20261028_135516`
标记为快速赛。该脚本只读，不修改回放，不启动游戏进程。


## 5.101b `0x1e/0x1f/0x20` 归属：victim 是 unit object ID（智能体）

**0x1e 结构**：`1e | type:u8 | 14×00 | victim:u16BE | 01`，主样本
21 条。envelope hero 是**攻击者 entityID**（338/1729/1021/1558…），
这一点闭合。victim 最可能是**运行时单位 object ID（0–994）**：
- 10 人 entityID 0/21、heroID 0/21、actorID 0/21；
- normalMonster id 1/21（victim 193 命中“忠诚守卫”配置 id，按巧合）；
- soldierWave waveID 3/21（325/368/369 三位数重合），兵种 unit id 0/21；
- 不是伤害值：12 文件 Pearson(t, victim) 中位 +0.038，无随时间增长。

**0x1e 不是击杀/补刀表**：与同英雄 source4 金币 ±40 帧仅 2/21，
与 source43 击杀金币 ±40 帧 **0/174**，与 source6 野怪 0/55；
重复 victim 8 例（同一攻击者 15.9s 内 type2→type4 两次），
1021/1558 有 AoE 多单位命中。更像**技能/动作命中单位**（medium）。

**0x1f/0x20**：0x1f 28B 是高光标签通知（tag 5/2/244；跨样本 93/94），
能稳定读出的只有 tag 和候选 id；0x20 20B 主样本 1 条（tag=21，
id14_le=393）。主样本 0x1f id 与 0x1e victim 零交集；跨样本
同文件 0x1f id **0/43**、0x20 id **0/7** 命中 0x1e victim，说明不是
同一 ID 空间，**不能当 killer/victim**。

**0x81/0x82**：0x81（970 条）值域 1/2/3/4/6，逐英雄强偏置；
与 source4 同帧 0、±2 帧 2/970；不是死亡/补刀。0x82（436 条）
实际是 `kind=1/2/3 + toggle=0/255`，kind 逐英雄恒定（338→2、
1547→3、1558→2、1729/1833/1966→1），像瞄准/攻击开关，无单位 ID。

**KDA**：source43 是**击杀/助攻金的子集**（主样本 6 杀 + 4 助攻），
不是全量 KDA；killer = envelope + source43 收款人，victim 不可得。
0x81 value6 的死亡窗口（team1 10 / team2 17）反推实际击杀
**17/10**，source43 只覆盖 **24%/20%**。1558：source43 0 条 →
K=0、A=0；0x81 v6 5 个窗口 → **D=5（候选）**；0x1e 作为 attacker
3 条（519.15s victim467、519.30s victim640、571.40s victim429），
0x1f 1 条（tag244,id12）。

**仍缺**：unit object ID → 英雄/兵种映射（需要战斗初始化或
StepNotify 头的 MyCampHeroObjIds/EnemyCampHeroObjIds）；victim
死亡/单位类型；0x1f/0x20 位级 schema；source43 覆盖（0x85 只是
25–35% 流水）。新线索：`0x02/0x80 cmdType=6` 的非英雄 actor 与
0x1e victim 有 6/217 个值重叠，可能共用目标单位 object ID 空间，
主样本为 0，语义未定。

**产物**：`tools/agent_kill_attribution.py`、
`datasets/agent_kill_attribution.csv`（1929 行）、
`datasets/agent_kill_attribution.md`。

## 5.102 最终面板/0x87 技能升级/1558 KDA（智能体，2026-11-01）

**`0x87` 是技能升级，不是装备购买**：格式
`00 00 00 <actorID> <skill:1-4> <levelIdx:0-5> 00 00`。
- 按 `(skill, levelIdx)` 聚合 10 人 **110 个相邻对 0 违例**；
- 按 `(tier, slot)` 聚合 81 个相邻对 **27 违例**（如 338 的
  slot0 出现 2→1→3）；
- 只有 442 李信有 skill4，与 5.26 一致；
- 1558：14 次升级，skill1 0→5、skill2 0→5、skill3 0→2，
  英雄等级约 14–15（low）。

→ **5.100 的“装备购买时序/6 槽出装”作废**。装备只有玩家块的
4 套**赛前方案**（官方 `item.json` 名称/价格）；容器里没有购买
事件、价格→扣金、当前金币。`0x80` 帧命令类型只有
{1,2,3,5,6,7,9}，没有 22/23/35 购买命令。

**最终面板不在容器**（高置信）：
- 37 个 30s/结算/KDA/伤害字段名，35/37 在 `global-metadata.dat`
  存在（KDAStat、stHeroGoldCoinInBattleChangeParam 不存在）；
- 29 条 `.abc`（27 个唯一文件）原始字节全扫 **0 命中**；
- 41 个 `.ope` 外层 + 第二层 + operator 层全扫 **0 命中**；
- 主段 13,061 帧里单帧从未同时覆盖 10 个 entity；帧流 256B
  窗口最多 7 个不同 entity；10 人同窗只在 106B 尾部名单；
- 尾部 `0x04` + 106B 名单后 **0 字节**；第二段 712 帧无结算块。

**1558 KDA/经济**：
- K=0、A=0（source43 无 1558 事件）；**D 不可得**；团队 **4:2**，
  team2 死亡 4 次（个人死亡数不可得）。
- 0x1e 作为 attacker 3 条：519.15s victim467、519.30s victim640、
  571.40s victim429，type=3；victim 是 unit object ID，不是 entityID。
- 0x02 可观测金币 **29 条 / 2,618**（主段 28/2,399 + 续流 1/219）；
  收入模型 **2,918（下限）– 4,930（中值）– 6,048（含辅助装被动
  推测上限）**；支出/当前金币不可得。

**第二段 712 帧不是纯输入**：含 8 条 0x85 金币（+968）、2 条 0x87
技能升级（含 1558 的 skill2 lv5）、5 条 0x20 高光（全是 1833）；
它把 1558 曲线延长到约 710.6s。

**口径修正**（旧口径把 0x80 当 len=0）：0x81 970→1015、0x1e
21→22、0x85 281/32,370→286/33,040、0x87 135→139。

**外部补数据最小集**：
- KDA：`entity_id, hero_id, team, kills, deaths, assists`（10 行）；
- 经济：`entity_id, total_gold_earned, gold_spent, current_gold`（10 行）；
- 完整面板再加 `damage_dealt, damage_taken, level, items[6],
  tower_damage, healing, mvp`。

**产物**：`tools/agent_final_panel2.py`、
`datasets/agent_final_panel2.csv`（162 行）、
`datasets/agent_final_panel2.md`、
`datasets/normal5v5_0x87_skill_upgrades_5069040.csv`（139 行）；
`player_1558_build_candidate_DEPRECATED.csv` 是作废的 6 槽映射。

## 5.103 战斗装备表 @0x522bde8 + 1558 支出（智能体，2026-11-01）

**战斗装备表在 `dc.db @0x522bde8`**（stdr，stride 568，533 行；
正常 4–5 位 itemID 共 **504 件**；1731 条字符串，池 0x49f30）：

| 偏移 | 字段 |
|---:|---|
| +0x08 | name |
| +0x10 | group |
| +0x16 | 价格页签 |
| +0x28 | **购买价 = total_price** |
| +0x4C | **出售价 = 60% 购买价** |
| +0x1D0 | 属性文本 |

**官方对拍（high）**：`pvp_item.json` 115 件，按 itemID 与
0x522bde8 对拍 **113/115 的 total_price/price 完全相等**。仅 2 个
例外：1133 无尽战刃（出售价 1224 vs 1236）、1711 极影（官方 1900
vs 商店表 850，版本差异，1558 未用）。→ dc.db 战斗表就是官方商店
表的原生副本。

**两个错误命名空间**：
- `134_Equip`（0x3602400）是 **PVE/训练营装备表**，不是本局商店表：
  1112 在这张表叫“木杖”，战斗表 1112 叫“匕首”；1701/1753/1411
  在 134 表里永远查不到。
- `122340616`（0x74ac508）是**装备被动/属性表**（首行“双抗+10”，
  能解出磐如山/叛逆反击等被动名），不是装备名/价格。

**0x87 再次确认是技能加点**（`stCmdSetSkillLevel`）：
- 每个 skillID 的 level 严格单调 0,1,2…（10/10 玩家无下降）；
- 大招（skillID=3）首次集中在回放 58.7–130.1s = 英雄 4 级窗口；
- skillID=4 只出现在 442 李信（唯一四技能英雄）；
- 按“tier=价格档、slot=槽位”读，5/10 名玩家 slot0 是 2→1→3。

**1558 支出（可复核口径）**：热门套装前 6 件
学识宝石 300 + 抵抗之靴 700 + 近卫 850 + 霸者重装 2450 +
近卫·奔狼 2080 + 守护者之铠 800 = **标价 7,180**。
- 1701→1714→1753 是同一条合成链，升级按原价抵扣，只实付
  300 + 550 + 1,230 = 2,080；
- **合成抵扣后实付 = 6,030**（700 + 2,450 + 2,080 + 800）；
- 若 1325 再升 1333：+1,220 → 7,250；
- 所以这 6 件实际扣金区间 **6,030–7,180**，最合理单值 **6,030**；
- 满 6 格成品（四套方案）总价：热门 11,550 / 原辅助 12,510 /
  坦克开团 11,350 / 天龙灭世 14,630。

**当前金币**：0x02 实测收入 2,399；300 + 1,908.6 + 2,399 = 4,607.6
是**收入下限，不是当前金币**。本样本 `0x01` 长度只有
0/2/3/5/9/17/19/20/28，没有 12/23/65，未找到金币快照。
估算（low）：6 件口径当前金币约 **1,900–5,800**；满 6 格口径
0–2,500；综合 **0–5,800，中位≈2,000–3,000**。

**购买流水仍不在 5069040**：286 条 `0x02/0x85` 金额全为正
（31–254，无负数扣款）；修正 0x80 后逐条扫所有每英雄消息的
2/4 字节，没有字段命中 504 件装备 ID；`stCmdPlayerBuyEquip`/
`OneStepBuyEquip` 在 metadata 里有定义，但 build 5069040 没下发。
`.ope` UIEventOpe 1194 的 payload 是 Oodle blob，本地无解码器。
要闭合到单值需要：服务端装备快照、Oodle 解码后的 `.ope`、或
录屏 OCR 装备面板。

**产物**：`tools/agent_equip_prices.py`、
`datasets/agent_equip_prices.csv`（1,077 行：battle_item 504、
pve_134 270、official_item 115、plan_1558 33、chain_cost 10、
0x87 事件 139、scenario/gold 汇总）、
`datasets/agent_equip_prices.md`。

## 5.104 皮肤 ID：玩家块 `s+0x7C`（智能体，2026-11-01）

**基础皮肤 ID 可得**：字段在玩家块英雄区 **`s+0x7C`**
（u32BE `s+0x7A` 的 bits 8–15），值是该英雄的皮肤序号；低字节
`0x05` 是常量标签。映射用皮肤表 `cell_0`（英雄名）+ `cell_1`
（序号）+ `cell_4`（模型族）对英雄表 `cell_5`，不是 heroID×100
盲算：170 个真实英雄块 **170/170** 合法，零假设期望仅 142.5/170，
log10P≈-16.0；主样本 10 人全部命中真实表行，且 10/10 同时存在于
上架表 `0x56E5140`。

| 玩家 | entity | 英雄 | 皮肤 ID | 皮肤名 |
|---|---:|---|---:|---|
| 桑忆终尘启 | 1729 | 安琪拉 142 | 14207 | 乘龙·聚宝船 |
| 碗面加香菜 | 1965 | 影 558 | 55800 | 经典 |
| 布鲁BIUBIU | 1514 | 虞姬 174 | 17401 | 加勒比小姐 |
| 含泪吃兵线呢 | 1021 | 朵莉亚 159 | 15901 | 金色潮汐 |
| 双枪踏浪行 | 338 | 马超 518 | 51805 | 琥珀纪元 |
| 李不信有归途 | 442 | 李信 507 | 50702 | 一念神魔 |
| 酒梦灵心醉 | 1966 | 孙权 151 | 15101 | 径山谋武 |
| 备水一站. | 1547 | 赵云 107 | 10703 | 皇家上将 |
| 佚名(*: | 1558 | 东皇太一 187 | 18700 | 经典 |
| Vetymoment | 1833 | 扁鹊 119 | 11900 | 经典 |

**1558**：东皇太一 187，`s+0x7A=0x00000005`，`s+0x7C=0` →
**18700 经典**（模型 3018700）；头部 `localHeroId=187`，块内含
文件名后缀 tag `CBDD358E…`，确认 1558 是录制者。

**尾表次值不是皮肤，是本局评分×100**：200 个次值范围 200–1560，
183/200 为 10 的倍数；命中皮肤行 ID 0/200、上架表 0/200、模型 ID
0/200；同一玩家+同一英雄跨局评分稳定 0/5 组，皮肤序号稳定 5/5 组。
MVP 字段 = 高均分队伍最高分实体 **9/9**，SVP **6/6**；主样本 1558
次值 **1140**，全队最高，MVP。

**仍缺**：8 位星元/部件皮肤 ID（如 15404101）和 `stSkinPartWearing`
不在该字段；AI 实体 2001–2008 没有玩家块，只有评分，AI 皮肤不可得；
`.ope` 除头部外是高熵载荷，明文层 0 命中。

**产物**：`tools/agent_skin_ids2.py`、
`datasets/agent_skin_ids2.csv`、
`datasets/agent_skin_ids2.md`。

## 5.105 新赛季构建 5247758：变长十人块 + 帧流（2026-11-01）

**样本**：`20261101_182452_-1723849936_94263_1793527939_CBDD358E761B15A4DF526A179E8119E2.abc`
+ 同名 `.ope`，2026-11-01 18:24:52 录制。头部版本
`12.1.1.1` / `12.1.1.26`，构建 `4989537` / `5247758`；`localHeroId=188`
（大禹），录制昵称 `佚名(*:`。这是普通 5v5，但**十人中有 8 名电脑玩家**，
不是十名真人的训练赛阵容（✅ 本样本）。

### 5.105.1 `.abc` 玩家块

旧 1,517 字节块（5230306）和 5069040 的变长块规则都不再直接适用。
本构建仍是十个连续块，但分为两类：

| 类型 | 块内标记 | 块长 | 名称后的 post | 收尾 |
|---|---|---|---|---|
| 真人 | `+0x02 = 01` | 变长（本样本 5,394 / 4,051 B） | 30 B | 19 B footer，末 11 B 恒为 `000000000004b000000000` |
| 电脑 | `+0x02 = 02` | 固定 2,782 B | 5 B | 无该 footer |

块头格式与 5069040 一致：

```text
+0x00 team        u8   1|2
+0x01 teamEcho    u8   恒等于 team
+0x02 kind        u8   1=真人 2=电脑
+0x03 slot        u8   0..4
+0x04 reserved    u16BE 0
+0x06 entityID    u16BE 100..9999
+0x08 accountLv   u32BE 电脑为 0
+0x0C nameLen     u32BE 含 NUL
+0x10 name        utf8
```

英雄 ID 仍是 5069040 的 `s+0x48`（u16BE），其中
`s = blockStart + 0x10 + nameLen + post`（真人 post=30，电脑 post=5）；
`s+0x6F` 为同一英雄的副本。块间首尾相接，电脑块长度固定，
真人块由 footer 定位，因此可按“下一块起点 == 当前块终点”串成十块链。
**不能把 `+0x02` 当常量 01**，否则会在第二块后停止（本样本 2/10）。

本样本十人（文件顺序）：

| 块 | 队 | 槽 | entity | 昵称 | 英雄 | 电脑 |
|---:|---:|---:|---:|---|---|---|
| 1 | 1 | 0 | 212 | 快乐何必认真 | 娜可露露 162 | 否 |
| 2 | 1 | 1 | 1804 | 佚名(*:（录制者） | 大禹 188 | 否 |
| 3 | 1 | 2 | 2001 | 传说之刃 | 花木兰 154 | 是 |
| 4 | 1 | 3 | 2002 | 绝世舞姬 | 貂蝉 141 | 是 |
| 5 | 1 | 4 | 2003 | 火鹰船长 | 莱西奥 545 | 是 |
| 6 | 2 | 0 | 2004 | 永恒之月 | 芈月 121 | 是 |
| 7 | 2 | 1 | 2005 | 破镜之刃 | 镜 531 | 是 |
| 8 | 2 | 2 | 2006 | 永夜之心 | 海月 521 | 是 |
| 9 | 2 | 3 | 2007 | 暴走机关 | 刘禅 114 | 是 |
| 10 | 2 | 4 | 2008 | 森之风灵 | 虞姬 174 | 是 |

电脑昵称来自英雄称号（“传说之刃”“绝世舞姬”等），entityID 为连续
2001–2008；真人昵称和头像 URL 在块内。八名电脑玩家的英雄互不重复，
且与 block 内 `s+0x48` 一一对应（✅ 本样本 8/8）。

### 5.105.2 `.abc` 帧流

本构建**没有**旧样本的尾部 TLV（`29 0E 00 00` 只在帧 payload 内偶然出现，
不能当 TLV 起点）。玩家块结束后是帧记录流：

```text
seq:u8   pad:u8(=0)   L:u8   payload[L]   a:u8   5 B   b:u8
```

记录总长 `10+L`，`seq` 逐条 +1（u8 回绕）。本样本：

| 项 | 值 |
|---|---|
| 帧流起点 | 32,783 |
| 首/末 seq | 1 / 172（回绕后） |
| 记录数 | 9,900 |
| 帧流结束 | 201,208 |
| 尾部剩余 | 106 B（第二段流/常量区） |

重要差异：`a` 后的 5 字节**不保证全 0**。最后一条记录为
`… 93 ff ff ff 00 00 04`，若强制要求 `00×5` 会丢掉该记录。解析器
只校验 `pad==0`、长度和 `seq` 连续。payload 语义仍未解码（○），
不能据此得到坐标、经济、击杀或技能时间轴。

### 5.105.3 `.ope` 第二层偏移

`.abc` 与 `.ope` 版本一致，仍为双层 raw DEFLATE：

| 项 | 5230306 旧样本 | 5247758 本样本 |
|---|---:|---:|
| 外层解压后 | 14,349 B | 16,242 B |
| u32 声明剩余长度位置 | 0x86 | 0x8C |
| 第二层标记 `01` | 0x8A | 0x90 |
| 第二层压缩流起点 | 0x8B | 0x91 |
| 声明剩余 / 操作流 | 14,211 → 39,634 B | 16,098 → 46,900 B |

头部字符串仍是 `01 01 01 + 三个长度前缀串`；其后设备信息/对局 ID/
时间戳仍在明文区，但多了 6 字节，因此**不能使用固定 0x8B**。
解析器改为在前 0x200 字节内搜索“`u32LE == len(inner)-position` 且
position+1 起可完整 raw inflate”的标记，旧样本与 5247758 均命中唯一候选。

本样本操作流在偏移 `0x1B` 出现未适配类型 `0x84`
（`84 0d 94 01 d6 0a 7c c5 0b bb 02 83 0d aa 03 83`），
`operator_stream.summarize` 在此中止；`.ope` 仍只按“结构已解、语义未解”
处理，不输出猜测定型的操作计数（✅ 本样本报墙位置）。

### 5.105.4 解析器与产物

`replay_parser.py` 已升级为 `observed-12.1.1.x-v3`：

- 玩家块：先尝试旧 1,517 B 布局，失败后尝试 5247758 变长十人块；
  报告新增 `blocksLayout`、`name`、`entityId`、`camp`、`position`、`bot`；
- 帧流：TLV 不匹配时搜索最长 `seq/pad/L` 链，报告新增 `frames`；
- `.ope`：动态定位第二层标记，报告新增 `secondLayerMarkerOffset`；
- 头部：补读 u16BE 昵称（两种布局均适用）。

测试：`tests/test_replay_parser.py` 新增本样本用例（10 人英雄、
8 名电脑、帧流 9,900 条、`.ope` 第二层 0x90/46,900 B）。样本原文件
位于 `data/replays/samples/abc_batch/`（`.abc`/`.ope` 被 `.gitignore`
忽略，不入库）。

**置信度**：十人块与帧流容器结构在本样本上 ✅；对其它 5247758 样本的
普适性尚待第二批样本验证（◐）；操作流 0x84 语义为 ○。

## 5.105b 新回放 20261101_182452：build 5247758 / 人机模式（2026-11-01）

- 样本：`20261101_182452_…CBDD358E….abc`（201,314 B）+ `.ope`（16,248 B）。
- build：**5247758**（12.1.1.26）；KV confType1=50、item7=300、
  item68=8000 → **普通 5v5 规则**，但实际是 **人机模式**（截图 10:56，38:8）。
- 阵容：**2 真人 + 8 AI**。本地 **佚名(*: 大禹 188 / entity 1804**；
  另一真人 快乐何必认真 娜可露露 162 / entity 212；AI 2001–2008。
- 帧流：32,783–201,208，**9,900 条**，尾部 106B；9,900/656s ≈ **15.09fps**
  （不是 5069040 的 20fps）。payload 仍是 0x12/0x13/0x14/0x01/0x02
  语法，0x80 仍需专用跳过。
- **只有 2 个真人写入 0x85/0x87**：45 条金币 / 4,598（212 2,970、
  1804 1,628）；26 条技能升级；8 个 AI 没有经济/技能流水。
- **source43 = 0**：没有 kill/assist 账本；截图 KDA（1804 9/1/12、
  212 22/1/2）是外部面板真值。
- **最终金币/KDA 数组不在回放**：6265/13333/… 单独命中都是帧序号头
  巧合（`0x00001879`=6265 = seq 0x79 前带 0x18）；u16/u32/LE/BE/
  stride 2/4/8 都没有 10 值连续数组。
- **尾部 106B 已用面板评分解码**：21B 头 + **10 槽 × 8B** + 5B 尾；
  每槽 `entityID:u16BE + 2B pad + rating×100:u16BE + 2B pad`。
  面板反查：1804=790(7.9)、2001=410(4.1)、2002=580(5.8)、
  2003=630(6.3)、2005=410(4.1)、2006=240(2.4)；212=1355(13.6→1360,
  -5)、2004=575(5.8→580,-5)、2007=608(6.1→610,-2)、
  2008=598(6.0→600,-2)。尾表是**内部评分×100**，不是金币/皮肤。
- 对账：1804 300+1,628+自然 1,848=3,776，**面板实际记录 6,265**（差 2,489）；
  212 300+2,970+1,848=5,118，**面板实际记录 13,333**（差 8,215）；
  0x85 覆盖率 **26.0% / 22.3%**，比 5069040 的 25–35% 略低。
  212 的 KDA 22/1/2，仅 source43 203/102 估算击杀/助攻金约 4,670；
  差额还包括未记录的兵线/野怪/目标金与支出，不是面板值错误。
- 赛前方案（真实装备名）：1804 控制流/均衡流/纯肉流/控制流；
  212 输出流/魔女爆发流/法师噩梦流/瞬间爆炸/打野爆发流。
  截图 4 个装备图标与“大禹辅助/坦克、娜可露露打野爆发”方向一致，
  但图标分辨率不足，不能逐件唯一对名。

**结论**：5247758 是更晚的 build + 人机模式，**不能当 10 人普通
5v5 的完整样本**；它适合验证玩家块/装备名/技能升级，但最终面板/
KDA/当前金币仍只能来自外部截图/服务端。5069040 的 10 人样本仍是
普通 5v5 主口径。

**产物**：`new_5247758_gold_events.csv`（45 条）、
`new_5247758_skill_events.csv`（26 条）、`new_5247758_report.md`。

## 5.105c 新赛季正常 5V5：十真人块变体（2026-11-02）

**样本**：两局同一录制账号的正常 5V5 回放，均为
`12.1.1.1` / `12.1.1.26`、构建 `4989537` / `5247758`。本地英雄均为
百里守约 196，蓝方槽位 4 的录制者名为“漂流网咖︎”；`.abc` 与 `.ope`
均为 `recorder-tag-matched`。

| 文件 | `.abc` | `.ope` | 帧流 | 尾部评分表 |
|---|---:|---:|---|---:|
| `20261102_161129_870343216_95868_…2B9FAA08….abc` | 482,967 B | 113,178 B | 10,509 条，seq 1–13，43,612–482,861 | 482,879 |
| `20261102_163751_-1996438720_96420_…2B9FAA08….abc` | 741,935 B | 172,908 B | 15,379 条，seq 1–19，43,501–741,829 | 741,847 |

两局尾部均剩 106 B；`.ope` 第二层标记/压缩流均在本样本回到
0x8A / 0x8B（同构建的人机样本是 0x90 / 0x91，不能固定偏移）。

### 5.105c.1 阵容与评分

第一局（`20261102_161129`，`.abc` 482,967 B）：

| 块 | 队 | 槽 | entity | 昵称 | 英雄 | 评分 |
|---:|---:|---:|---:|---|---|---:|
| 1 | 1 | 0 | 1168 | 胡不喜# | 钟馗 175 | 8.40 |
| 2 | 1 | 1 | 1613 | 自诩一棵葱 | 妲己 109 | 10.40 |
| 3 | 1 | 2 | 750 | 别吃窝线吖a | 孙悟空 167 | 9.10 |
| 4 | 1 | 3 | 538 | 狂傲自由魂Z. | 关羽 140 | 13.10 |
| 5 | 1 | 4 | 1611 | 漂流网咖︎（录制者） | 百里守约 196 | 10.60 |
| 6 | 2 | 0 | 1031 | 麻巫喵 | 公孙离 199 | 5.90 |
| 7 | 2 | 1 | 296 | 翳灵崽 | 吕布 123 | 5.40 |
| 8 | 2 | 2 | 551 | 一风舞 | 貂蝉 141 | 5.50 |
| 9 | 2 | 3 | 1799 | 扁鹊耳垂 | 兰陵王 153 | 3.60 |
| 10 | 2 | 4 | 1760 | 谜语星海 | 张良 156 | 4.90 |

第二局（`20261102_163751`，`.abc` 741,935 B）：

| 块 | 队 | 槽 | entity | 昵称 | 英雄 | 评分 |
|---:|---:|---:|---:|---|---|---:|
| 1 | 1 | 0 | 714 | `信则\u2060\u2061有\u2062` | 亚瑟 166 | 10.90 |
| 2 | 1 | 1 | 679 | 深藏功与名⢐ | 云缨 538 | 6.30 |
| 3 | 1 | 2 | 1729 | 憨熊笨拳 | 墨子 108 | 8.00 |
| 4 | 1 | 3 | 1554 | 冷静宝宝QWQ | 王昭君 152 | 9.20 |
| 5 | 1 | 4 | 1367 | 漂流网咖︎（录制者） | 百里守约 196 | 11.00 |
| 6 | 2 | 0 | 1279 | 南巷丶转转儿 | 钟馗 175 | 12.00 |
| 7 | 2 | 1 | 640 | 西行感怀录 | 赵云 107 | 6.20 |
| 8 | 2 | 2 | 351 | 野心蓝图33 | 安琪拉 142 | 9.10 |
| 9 | 2 | 3 | 1198 | 蟹谢谢礼 | 吕布 123 | 6.20 |
| 10 | 2 | 4 | 1990 | 别再浪⥳ | 马可波罗 132 | 6.30 |

评分表按 `entityID` 对齐；两局表内实体顺序都是红方五人在前、蓝方五人在后，
不能按行号直接套阵营。胜负仍未解码。

### 5.105c.2 块布局差异

- 十个块全部 `+0x02=01`（真人），5 蓝 + 5 红，没有电脑块。
- 蓝方真人块仍以 19 B footer 结束，末 11 B 恒为
  `000000000004b000000000`，footer 终点等于下一块起点。
- **红方真人块没有该 footer**，块尾是 0；必须用“下一候选块起点”收尾。
  若继续在整段文件中搜索 footer，会在后续红方块内误命中：第二局曾把
  3,481 B 的块算成 6,985 B，十块链随之断开。
- 第二局蓝方槽位 0 的昵称是 `信则` + U+2060/U+2061 + `有` + U+2062，
  18 B UTF-8 后补 1 B NUL，`nameLen=19`。旧校验要求整串
  `str.isprintable()`，会丢弃这块并只剩 9 块；解析器改为容忍 Unicode
  Cf/组合字符、去掉尾部 NUL，仍拒绝控制/未分配码点。
- `+0x08` 在本样本十人恒为 30（账号等级），不是块长；块终点仍由 footer
  或下一块起点决定。

### 5.105c.3 解析结果与边界

- 两局均读出 **10/10** 阵营、槽位、昵称、英雄和 entityID；
  `blocksLayout=roster-5247758`，`bots` 全为 false。
- 尾部评分表十人齐全，按 entityID 对到块；两局 offset 分别为
  482,879 / 741,847。
- 0x85/0x87/0x82 原始事件：第一局金币 547 条 / 64,066、技能升级 120、
  坐标 78；第二局 627 条 / 60,038、技能升级 150、坐标 343。
  仍只覆盖部分真人收入，不能替代最终面板金币。
- `.ope` 操作流在偏移 0x1B 命中类型 `0xEF`
  （`ef 09 5d b1 08 4e f6 08 c5 01 ed 09 8a 02 ed 09`）后中止；
  与 11-01 人机样本的 `0x84` 不同，解析器如实报墙，不输出猜测定型计数。
  - **2026-11-03 修正（子智能体，优先）**：0x1B/0xEF 是 `HEADER_BYTES=27`
    旧起点造成的假墙；11/2 首记录在 offset 0。UILayout(0x16) 不是
    `s[7:11]` 长度，而是 **u16 tag + 75 个 ULEB varint**（44/44 流一致）。
    旧墙 0xE79/0xCDC 是 MoveOpe 对齐错误；加入 4-var MoveOpe 后重分段为
    普通 MoveOpe/Common/UnityFrame/Touch/SendMsg/GameCoreFrame，
    `0x82/0x88` 只是上一条 varint 的尾字节。MemoryData 的 lenvar 是
    payload 字节长度，payload 是内存快照，不是续块。11/1 同 build 流已到 EOF
    （9,307 记录）；11/2 新墙 **0x1991E type=0x24 / 0x38D26 type=0x91**，
    都在大 MemoryData 之后，下一步做边界平移扫描。详见 `docs/ope_stream.md`。
- 帧流结束后不是一张无名的“评分表”，而是 **消息号 1251 的
  `SCPKG_GAMEOVER_MVPSCORE` 包**（payload 109 B）。两局记录流均严格
  消费到 EOF，只有 1075 开局、1077 开战、1251 MVP 评分三个 CSPkg；
  没有 1082 `SCPKG_GAME_OVER_RSP` 完整结算包。
- 1251 的 109 B 可对齐为：`dwWinMvpObjID`（胜方 MVP entity；本两局
  538 / 1367）、10 × 8 B `stMvpScoreDetail`（entity + 评分×100）、
  `iLoseMvpObjNum=1` + `LoseMvpObjList`（败方 MVP entity；本两局
  1031 / 1279）。由此可反推胜负：两局均为蓝方胜。字段名来自 5.125；
  其余头部字节（如 `0x2F65`、630,928）仍未解。
- 协议号相邻不等于语义相邻：**1252 是 `SCPKG_WEARING_INFO_NTF`**
  （皮肤/装扮通知，字段 `bObjCamp/dwObjId/dwHeroID/wSkinID/
  stSkinPartWearing/...`），不是结算包；完整结算仍是 1082
  `SCPKG_GAME_OVER_RSP`。1249/1250 是 ban/pick 通知，1254 是道具使用，
  1251 只是恰好注册在它们中间。
- 这解释了“有评分表、部分金币/技能/坐标，却没有完整 KDA/经济/伤害”：
  1251 是回放列表用的 MVP 评分缓存，0x85/0x87/0x82 是帧流里的输入/
  同步/通知事件，不是结算账本。完整面板字段在 1082 的
  `COMDT_HERO_BATTLE_STATISTIC_INFO` 里；本构建回放没有写入该包。
  30 份样本的 1082 扫描为零候选，但 1251 body 只解到上述结构，
  不能把“本构建没写”外推成所有版本/所有封装都没有。
- 帧流前的 7 B 间隔已按公开旧版 `GameReplayModule.FlushRecord` 对齐：
  `07 00 | 00 00 00 00 00` = i16 length 7 + `CSDT_FRAPBOOT_INFO`
  (`dwKFrapsNo=0`, `bNum=0`)；它是关键帧记录，不属于 residual。
  按此口径两局 residual 降为 **867 / 869 B**（头部 13 B + 1075 前缀
  854/856 B）。它的位置（帧流前而非文件尾）与 `dwKFrapsNo` 取值仍为 ◐。
- 公开协议仓库 `Moli13337/Honor-of-Kings-protocol` 独立确认
  1075/1077/1082/1251/1252 的消息号和 `SCPKG_GAME_OVER_RSP` /
  `SCPKG_GAMEOVER_MVPSCORE` / `CSDT_FRAPBOOT_*` 字段；旧版
  `GameReplayModule.cs` 用 i16 记录长度，当前 build 用 i32，不能混用宽度。
- 两局只进入回放实验室，不进入正式比赛和英雄胜率统计。

**置信度**：十真人块（含红方无 footer、零宽昵称）在两局上 ✅；1251/
1082 消息号与字段家族由本机 metadata + 公开协议仓库双重确认 ✅；
1251 MVP 评分包及胜负反推在两局 + 11-01 样本上 ✅（1251 其余头部字段 ◐）；
7 B 关键帧的形态与旧版 `FlushRecord` 一致（位置/取值 ◐）；`.ope` `0xEF`
语义为 ○；该变体对其它 5247758 正常 5V5 的普适性为 ◐。
测试见 `tests/test_replay_parser.py` 的
`test_new_season_normal_5v5_ten_humans` 和
`test_normal_5v5_hidden_name_and_red_blocks_without_footer`。

## 5.106 伤害/技能/目标语义：能读到什么、读不到什么（智能体）

**计数修正**（0x80 命令体）：0x1e 21→**22**、0x23 249→**254**、
0x2c 418→**425**、0x87 135→**139**、0x85 281→**286**。

**0x1e**：`1e | type:u8 | 14×00 | victimObjID:u16BE | 01`。
- envelope hero = 攻击者 entityID；victim = **运行时单位 objectID**
  （0–994），不是 entityID/heroID/actorID；主样本 22 条对 10 人
  entityID/heroID/actorID 命中 0。
- **没有 damage/skillId**：`data[2:16]` 在 5069040 110 条恒为 0；
  不是伤害表。type 只看到 2/3/4，语义 low；与金币账本对齐接近随机。
- 1558 有 3 条（519.15s victim467、519.30s victim640、571.40s
  victim429，type=3），只能证明“命中 3 个运行时单位”，**伤害值不可得**。

**0x29**：`29 | 00 00 00 | actorID:u8 | id:u32BE | param:i32BE |
tail:u32BE`。
- actorID 与 0x87/0x80 一致（6 样本 45 条 0 冲突）。
- id 在 5069040 只有 0/91060/900011/11990；91060 在技能表/
  buff_effect/击败特效三处同号，**不能命名**；900011 = “打包濒死
  队友”（medium-high）；11990 未命名。
- **不是回城**：45 条全量没有 90005/90007/90025/90035 或
  90003/90000/90006；**不是技能释放日志**：91060 单帧离散，
  900011/id=0 有连续帧；是混合的“状态/效果通知”。
- 1558 0x29 **0 条**；没有技能释放日志。

**0x1f/0x20**：0x1f 28B 有 tag/actorObjID，0x20 20B 有 tag/4×u32/
actorObjID；**没有显式 killer/victim/skillId**。0x1f tag 可闭环
（1/2/5 关键/完美群控，244 表外）；0x20 主样本 1 条 tag21。
doc 5.73 的“u32_d 高字节=heroID”被反证（0x89010019 高字节 137，
本局没有 137）。

**0x23/0x2c**：0x23 是逐英雄 bool，窗口 0.2–44.2s，语义 low；
0x2c 精确布局（2026-11-02）：
`2c | kind:u8 | flag:u8 | target:u16BE | x:i32BE | y:i32BE |
counter:u32BE`，flag=1 是取消（22/22 target=0xFFFF、x=y=0），
target 是 objectID，坐标是目标/瞄准点不是连续轨迹；**不是推塔
命令**。之前“i24/3B pad/u8 counter”作废；413 条主样本全部自洽，
对应公开 `CSDT_CMD_USEPOSITIONSKILL`（chSlotType+Vector2，TDR 大端）。

**source44/47/51**：只是 `0x02/0x85` 的 source+amount；底额
44→45、47→175、51→250，属“目标类固定底额奖励”；具体推塔/一血/
镀层/暴君**不能从回放确定**（low）。1558 这三类 0 条。

**0x38**：只在非 5069040 帧流样本（5230306/5169333/4742900）
出现；结构有 type 546601/2/3 或 107，dc.db 1245 张 stdr 表里
都不是行键，不能命名。

**结论**：这两个文件能读到“谁命中了哪个运行时单位”“哪些高光/
状态通知”“哪些固定底额奖励”，但**读不到伤害值、技能名/释放
日志、killer/victim、目标类型**。这些必须靠 objectID→单位表、
服务端结算或录屏面板补。

**产物**：`tools/agent_damage_skill_objective.py`、
`datasets/agent_damage_skill_objective.csv`（2,420 行）、
`datasets/agent_damage_skill_objective.md`。

## 5.107.1 5247758 原始事件接入解析器：0x85 金币 / 0x87 技能 / 0x82 坐标（2026-11-01）

**结论先行**：之前“5247758 只有名单和帧骨架”的说法不成立。逐条遍历
每个 payload 的**全部**顶层消息（而不是只看第一条 0x02）后，可稳定解出：

| 事件 | 子类型 | 体长 | 语法 | 本样本 |
|---|---|---:|---|---|
| 金币增量 | `0x85` | 7 B | `source:u8, amount:u16LE, 4B` | 47 条记录 / 46 条去重 / **4,792** |
| 技能升级 | `0x87` | 7 B | `2B, actorID:u16BE, skill:u8, level:u8, 1B` | **27** 条 |
| 位置候选 | `0x82` | 16 B | `kind:u8, x:i32BE, y:i32BE, 7B` | **195** 条 |

分人：

| 实体 | 玩家 | 金币事件 | 金币合计 | 技能升级 | 坐标样本 |
|---|---:|---:|---:|---:|---:|
| 212 | 快乐何必认真（娜可露露） | 27 | 3,164 | 15 | 39 |
| 1804 | 佚名(*:（大禹，录制者） | 19 | 1,628 | 12 | 156 |
| 2001–2008 | 8 名 AI | 0 | 0 | 0 | 0 |

来源分布（金币）：source4 21 条/2,409、source5 21 条/1,811、
source6 3 条/525、source44 1 条/47。

**与旧 CSV 的差异**：`new_5247758_gold_events.csv` 是 45 条/4,598，
技能 26 条。全量消息遍历后多出两条：

- frame 2259：`212 source4 amount=194`（payload 内有两个 0x02，
  旧脚本只取了第一个）；
- frame 5576：`212 actor8 skill=3 level=2`（同样是第二个 0x02）。

另外 frame 305 的 `1804 source6 165` 在同一 payload 重复出现一次，
按 `(frame, entity, source, amount)` 去重后保留 1 条。
所以当前口径是 **46 条/4,792**，不是 45 条/4,598。这个差异本身
说明“先按单条消息扫描”的结论会漏事件，不能过早封口。

**0x82 坐标**：`kind=1` 多为录制者 1804（140 条），相邻帧有
`(250,138)`、`(213,191)`、`(-186,-158)` 这类平滑小步长，范围约
`±50,000`，高度疑似地图坐标；`kind=3` 出现于 212（39 条）和
1804（16 条），数值跳变明显，暂时不能当连续轨迹。坐标原点/缩放
比例未校准，不能直接换算成米或地图格。

**尾部评分表**：帧流结束（201,208）后还有 106 B，其中有用例
`(entity:u32BE, score×100:u32BE)` 的十人表，偏移 201,226：

| 实体 | 212 | 1804 | 2001 | 2002 | 2003 | 2004 | 2005 | 2006 | 2007 | 2008 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 评分 | 13.55 | 7.90 | 4.10 | 5.80 | 6.30 | 5.75 | 4.10 | 2.40 | 6.08 | 5.98 |

若沿用 5.104 的 MVP/SVP 规则，MVP 为 212、SVP 为 2007；胜负仍未在
文件中显式出现。**这直接修正了 5.13.9/5.99 的“评分不在文件里”的旧
结论**：至少 5247758 的尾部有赛后评分表。旧结论只适用于 5069040/
5230306 样本，不能外推到所有构建。

**边界**：金币事件只覆盖最终金币的一部分（本样本远低于 50%），
0x85/0x87 只对两个真人存在；AI 没有经济/技能流水；KDA、最终面板、
伤害/承伤仍不在当前可解字段中。解析器现已输出 `playerEvents`、
`scoreTable`，并在玩家块上带 `goldTotal`/`skillEvents`/`positionSamples`/`score`。

**产物**：`replay_parser.py` 的 `inspect_player_events` /
`inspect_score_table`；测试 `tests/test_replay_parser.py` 覆盖 46 条
金币、27 条技能、195 条坐标、十人评分表。

## 5.107 普通 5v5 表字段确认版（智能体，2026-11-01）

`agent_table_fields_5v5.csv`（381 行）状态：**confirmed 65 /
candidate 216 / drift 20 / unresolved 70 / not_serialized 10**。
5.114 把 0x348/0x34C 两个误标为 `astExpCompensateDetail_length`/
`astCoinCompensateDetail_length` 的 confirmed 行降为 candidate（实际是
`stLevelCommonInfo.bIsOpenGamePlayRelic/dwGamePlayRelicID`）。
确认字段落成 `normal5v5_table_fields_confirmed.csv`（65 行）。

**行布局修正**：5.61 的“+0 行键、+8 起每字段 8 字节”只是特例。
实际是 `+0 主键(4B)` → 其余字段按声明顺序**自然对齐**打包
（u8=1 / u16=2 / u32=4 / u64=8 / 字符串句柄 8 且 8 对齐；
`*_length` 不落盘；`*_bytes` 内联）。主键字段总是提到 +0。

**关键修正**：

- **局内装备真表 = 原生表 `0x522bde8`**（533 行、stride 568）：
  +0x08 名称、+0x28 `dwBuyPrice`、+0x4C `dwSalePrice`（=买价×60%）、
  +0x50 `strIdPreEquipID` 合成材料、+0x1D0 属性文本。
- **`Equip.bytes`（0x3602400，270 行）是客户端旧版/PVE 装备表**，
  不是局内商店表；1112 在这张表叫“木杖”，局内表叫“匕首”。
- **`AcntBattleLevel` 的 `stLevelGamePlayInfo` 基址是 `0x350`**（不是
  0x348；0x348/0x34C 是 `stLevelCommonInfo` 末尾的
  `bIsOpenGamePlayRelic`/`dwGamePlayRelicID`，common 840B 从 +8 到
  +0x350）：+0x350 u16=300 初始金币；
  +0x352=1 经验补偿 bool、+0x353=0 金币补偿 bool；+0x358=1900
  出生延迟。注意 5.47 的 `RewardMatchLevel` 是另一张表，gameplay
  基址 0x358，不要混用。
- **soldierWave**：+0x30 下一波、+0x34 repeat 8、+0x3C 首波 10000ms、
  +0x40 间隔 33000ms、+0x48/+0x58/+0x68 三个 {soldierID,count} 槽。
- **normalMonster**：+0x2C HP、+0x24 HP2、+0x2C→gold 60/140、
  +0x3C exp 3850（与 source5/6 流水一致）。
- **hero**：+0x5C HP、+0x60 防、+0x68 攻（廉颇 3675 > 赵云 3468 >
  小乔 3200）。
- **skin/shop**：+0 skinID、+4 heroID、+8 英雄名、+24 皮肤名；
  shop +68 = 888 点券。
- **buff 0x8268ac**：+0 id、+0x78 名、+0x80 描述、+0x90 prefab。
- **skill 0x1ce47c**：+0 skillID、+0x28 名、+0x38 描述。

**5.114 已闭合**：CommonSettle 行尾 4 个内联数组、Level 4 个
byte buffer、AcntBattleLevel 的 `stLevelCommonInfo`(840B)/
`stLevelGamePlayInfo`(0x170B)、Equip 568B/17 属性/3 数组容量、
buff 3 个 184B 效果槽与 parent/child。**仍缺**：normalMonster
攻/防/成长/刷新、hero 移速/攻速/成长曲线、buff 每个 param 的
精确公式、Equip 数组内部 `p6/p7`、`RelationActivityMapID` 用途。

**产物**：`data/replays/_analysis/tools/agent_table_fields_5v5.py`、
`datasets/agent_table_fields_5v5.csv`、
`datasets/normal5v5_table_fields_confirmed.csv`。

## 5.108 帧流通道全表：现有数据到底有什么（2026-11-01）

`normal5v5_frame_channels.csv`（20 行）把主样本所有帧通道列清。
**计数修正**：0x12 **76,059**、0x13 **16,187**、0x14 45（之前
doc 的 66,095/2,260 是旧统计）。

| 通道 | 格式 | 主样本条数 | 语义 | 状态 |
|---|---|---:|---|---|
| 0x12 | u16BE | 76,059 | 相机/视口/位置候选 | partial |
| 0x13 | u8 | 16,187 | 相机角度/单位类型候选 | partial |
| 0x14 | u24 | 45 | 未知稀有 | unknown |
| 0x01/0x2d | u16BE | 9,941 | 朝向/瞄准角度 | decoded |
| 0x01/0x03 | 2B | 1,387 | ready/队伍状态 | partial |
| 0x01/0x2c | 17B | 425 | 坐标命令 | partial |
| 0x01/0x23 | 2B | 254 | 逐英雄 bool | partial |
| 0x01/0x87 | 5B | 50 | 未知（非 0x02/0x87） | unknown |
| 0x01/0x1e | 19B | 22 | 命中事件 | partial |
| 0x01/0x29 | 17B | 10 | 状态/效果通知 | partial |
| 0x01/0x1f | 28B | 3 | 高光标签 | partial |
| 0x01/0x20 | 20B | 1 | 高光详情 | partial |
| 0x01/0x48 | 9B | 1 | 未知稀有 | unknown |
| 0x02/0x81 | 1B | 1,015 | USEDIRECTIONALSKILL（旧 1B 读法已推翻） | partial |
| 0x02/0x80 | 12B | 703 | 帧命令 | partial |
| 0x02/0x82 | 2B | 449 | kind+toggle | partial |
| 0x02/0x85 | 5B | 286 | BUYEQUIP（旧“金币流水”已推翻） | decoded |
| 0x02/0x87 | 7B | 139 | 技能升级 | decoded |
| 0x02/0x00 | 0B | 8 | 空 | decoded |
| 0x02/0x86 | 6B | 1 | 未知稀有 | unknown |

**0x12/0x13 的判断**：0x12 每帧 4–8 个、值 9,728–64,512；
0x13 有 **55 个唯一值**（72–161），与 0x12 **不 1:1 配对**。
两者更像**相机/视口状态**（0x12 位置/距离，0x13 角度/类型），
不是十人玩家数据；没有和 0x2c 的 x/y 直接对齐。状态标 partial，
但可以确定它们**不是**逐人金币/KDA/伤害。

**结论**：现有帧流的通道已经全部列清；真正还没定语义的只剩
0x12/0x13（相机/视口）、0x81/0x82/0x23/0x2c（英雄状态/命令）、
0x1e/0x29/0x1f/0x20（命中/状态/高光）和几个稀有未知。
这些是“有数据但语义 partial”，不是“没有数据”。

**产物**：`datasets/normal5v5_frame_channels.csv`。

## 5.109 玩家块 opaque 档案区：账号/URL/hash/方案/最近玩家（2026-11-01）

`player_block_strings_5069040.csv`（116 行）+
`player_block_strings_5247758.csv`（25 行）→
`player_profiles_strings.csv`（12 人）。档案区可读字段：

| 字段 | 例（1558 佚名） | 说明 |
|---|---|---|
| account_tag | `CBDD358E761B15A4DF526A179E8119E2` | 32 hex，录制者账号 |
| avatar_url | `https://download.nature.qq.com/.../avt3_1763638567524.png` | 头像 |
| poster_url | `https://download.nature.qq.com/.../prt3_1763638567524.png` | 海报 |
| hash1/hash2 | `FB8089A7...`、`3988B6AE...` | 账号/设备/最近玩家 hash |
| recent_name | `沐风云野` | 最近玩家/队友名 |
| plans | 热门套装/原辅助坦克/坦克开团流/天龙灭世流/半肉法坦流 | 赛前方案名 |

**关键修正**：`D341CC16808B49F7BA71AB1CFB7F5771` 是 **Vetymoment
的账号 tag**，不是“对局 GUID”（5.16.5 旧说法作废）。同一账号
1558/1804 在 5069040 与 5247758 两个 build 里都是 `CBDD358E…`，
avatar/poster/hash 一致；212 的账号是 `0F8ADE3C…`。

**方案名/最近玩家名**：5069040 的 10 人方案名已列出（热门套装/
原辅助坦克/坦克开团流/天龙灭世流/半肉法坦流、输出流/均衡流/
纯肉流、暗信/光信…）；5247758 的 1804 是控制流/均衡流/纯肉流/
控制流，212 是输出流/魔女爆发流/法师噩梦流/瞬间爆炸/打野爆发流。
这些是玩家自定义文本，不是装备/英雄 ID。

**产物**：`player_block_strings_5069040.csv`、
`player_block_strings_5247758.csv`、`player_profiles_strings.csv`。

### 5.106.1 补充：0x1f/0x20 tag 名、0x2c 目标、0x29 id（2026-11-01）

**0x1f/0x20 tag 名**（0x1f 表 110489732；**0x20 不能直接套这张表**）：

| tag | 0x1f 名称 |
|---:|---|
| 1 | 关键群控 |
| 2 | 完美群控 |
| 5 | 关键群控 |
| 21 | 群体解控（庄周） |
| 93/94 | 瞬闪控制 |
| 244 | 表外；当前 dc.db 只到 205 行，缺 5069040 build 的 tag 表 |

**修正**：之前把 tag21 写成“关键团战输出”是 `native_table_names`
按首次出现顺序的误读；按 pool 精确 cell 解码是**群体解控（庄周）**。
主样本 0x20 tag21 是马超，语义与庄周不符，说明 **0x20 有独立的
tag 命名空间**，不能套 0x1f 表。0x1f/0x20 仍是高光标签，不是
killer/victim 表。

**0x2c**：425 条，target 命中英雄 actorID 仅 **6/425**，绝大多数是
非英雄 objectID；kind 2=221 / 1=159 / 4=45，flag=1 取消 23 条；
与 0x80 命令同英雄 ±5 帧只有 4/425。→ **技能/攻击目标位置**，
target 是单位 objectID，不是命令日志，也不是推塔命令。

**0x29 id**：900011=“打包濒死队友”（high，skill row2527 +
buff_main row9036 同义）；91060 最合理归 **buff_effect row391
“峡谷裂口传送中断被动”**（medium；165/165 tail=0、26 个英雄组合、
无小乔、约 75s 重复；skill 小乔/kill_effect 吕布均排除）；11990
**未命名**（high），4/4 事件都是扁鹊(119)对友方，`11990=119*100+90`，
更像扁鹊专属友方效果（low-medium），不是技能表 ID。

**0x23 = 无法行动/硬控窗口（0.55）**：254 条、120 个窗口；
107 个 ≤3.2s，13 个长窗口；窗口内同英雄 0x80 仅 1 条、
0x82/0x2c/0x2d/0x29/0x1e 全 0、0x85 仅 1 条；窗口后 2s 内施法
1/107。时长以 0.2–0.6s 为主，排除死亡（10–20s）和回城，
更像**眩晕/击飞/压制等硬控/僵直**，不支持“蓄力后释放”。

**0x81 value6 = 可观测死亡通知（medium，约 0.6，不是全量账本）——已推翻**：
D1 已证明 `0x81` 是 `USEDIRECTIONALSKILL`，`value6` 是 slot=6，不是死亡。
以下关于 v6 死亡窗口/漏检的段落只保留为历史分析，不能用于 KDA/死亡。
新回放 1804 的 v6 只有 1 个窗口（seq 7461–7463，约 494s），面板
死亡正好 1；v6 后 0x81/0x82/0x80/0x85 分别静默
46.2/66.1/66.7/40.2s。212 面板死亡 1 但 v6=0：它的 0x81 98 条
全是 value2，最大空洞 621 帧≈41.1s（像一次死亡+复活），0x23
只有 2 条且不在空洞内，所以不是 0x23 替代；v6 只出现在 1804
的密集本地流里，212 是稀疏远端流。

5069040 的 27 个 v6 窗口：442=8、1558=5、1514=4、1965=4、
1833=3、1729=2、1966=1；team1=10、team2=17。但：
- **3/27 窗口在 ≤0.5s、8/27 在 ≤1s 内就出现非 6 状态**（1514/
  1833/442）→ v6 更像**一次性死亡通知/状态位**，不是持续死亡态；
- 442 李信 8 个 v6 多数后 0.55–3s 出现形态值 1/4，存在形态切换
  歧义；若 442 的 v6 不是死亡，team2 死亡 17→9；
- “team1 死亡=team2 击杀”是定义恒等，不是独立证据；5247758
  面板 team2 击杀 8 ≠ team1 死亡 9（±1）。
- source43 覆盖率：主样本 team1 4/17=23.5%、team2 2/10=20.0%、
  合计 6/27=22.2%；跨样本池化上界只有 10–14%。source43 是
  **K/A 下界**，不是稳定全量击杀日志（击杀与 v6 时间差多数 6–35s）。
- 1547/338/1021 活跃但 0 v6，既不能确认漏检也不能确认 D=0；
  8 个 AI 完全没有 0x81（面板 45 次死亡全漏）。

**0x81 状态模型（已推翻）**：D1 证明 `0x81` = `USEDIRECTIONALSKILL`；
`slot=6` 不是死亡，`slot 1/2/4` 是方向技能槽，不再按“状态位”解释。
旧 5069040 的 v6 死亡窗口全部撤回；以 `docs/agent_death_0x81.md` 为准。

**0x82（medium-low，约 0.5）**：5069040 是 2B
`kind:u8 + toggle:0/255`；kind 逐英雄恒定（1/2/3），toggle 不是
干净的按下/抬起，更像周期采样的二值 UI/瞄准状态；kind 是该英雄
**手动瞄准技能槽的候选**（16 个 hero,kind 组合中 15 个 kind K
首次出现在技能 K 解锁后）。5247758 的 0x82 已改成 **16B
`kind + x:i32BE + y:i32BE + 7B` 位置候选**，不能与 5069040 混用。

**0x1e type = 攻击/技能槽（medium）**：type 2/3/4 更像
**技能槽/普攻**，不是单位类型：
- type 2：赵云 1 条（技能2 候选）；
- type 3：1729 安琪拉（大招）、338 马超、1558 东皇（3 条）、
  1514 虞姬、1021 朵莉亚、442 李信；
- type 4：338 马超、1514 虞姬、1021 朵莉亚（3 连）、1547 赵云
  ——更像**普攻/强化普攻**。
victim 仍是运行时单位 objectID，**没有 damage**。所以 0x1e 是
“某次普攻/技能命中了哪个单位”，不是击杀/补刀表。5.115 进一步
证明 victim 的 0–994 池**无法映射**到英雄/小兵/野怪/塔，不能
按 actorID 或静态表命名。

## 5.110 0x12 不是相机 u16，是 x:u8 + y:u8 屏幕坐标（2026-11-01）

**0x12 的 2 字节不是一个大端 u16，而是两个 u8：`x = byte0, y = byte1`。**
主样本 76,059 个值，每帧 4–8 个：

- x 范围 **64–167**、y 范围 **0–180**；
- 同索引逐帧中位跳变：x **5–20**、y **15–34**，平滑；
- 例 seq 919：`(156,63) (145,99) (134,60) (68,122) (143,112)`。

这更像**可见单位的屏幕位置**（5–8 个/帧），不是相机 u16。
之前 5.25/5.108 的“0x12=相机/视口”应改成 **0x12=屏幕坐标
(x:u8,y:u8)**（medium-high）。0x13 仍是 55 个值（72–161），
与 0x12 不 1:1 配对，暂记“相机角度/单位类型候选”。

**产物**：`datasets/frame_screen_positions_5069040.csv`（76,059 行：
seq/time_s/index/x/y）。

**索引不是单位身份**：idx0–7 的 x 中位数是
**161/151/135/98/87/90/96/98**，基本按 x 降序；y 中位 76–99。
每帧 4–8 个值，是**可见单位的屏幕位置列表，按 x 排序**，
不是固定玩家槽位，也不是相机。要按玩家跟踪，必须结合
0x2d/0x2c/0x1e 或单位 objectID 重新关联，不能直接用 index。

**0x13 的量化（partial）**：16,187 个值、55 个唯一值（72–161）；
连续中位跳变 **9**、p90 **64**，连续重复段中位长度 **1**（最长 3）；
与 0x12 的 4–8 个位置**不 1:1**（0x13 多为 0–2 个/帧）。
既不像平滑相机，也不像 0x12 的单位类型列表；更像**相机角度/
单位朝向/类型候选**。要定名需要引擎侧相机/单位表，暂不硬猜。

**0x12/0x13 智能体修正（2026-11-01）**：

- **x 不是普通 u8**：是 **2 位前缀 + 有符号 6 位**：
  `0x80+v → +v`（0…+39）、`0x40+v → -(v+1)`（-1…-40），
  v∈0..39；x 原始 64–167，**104–127 永不出现**；真实域
  **[-40,39]**。y 仍是 0–180。数据集已加 `x_signed` 列
  （`x_raw/x_signed/y`）。
- 每帧 **4–10 个点**（均值 6.17），同帧 x 100% 互不重复；列表按
  x 降序（相邻对 86.8% 降序，严格 43.9%；新进单位追加到表尾）。
- **不是身份槽位**：在 (x_signed,y) 上做匈牙利跟踪，1,390 条轨迹
  （≥3 点）、216 条 ≥100 点、5 条 ≥300 点、最长 537 帧≈38.2s；
  中位寿命 **2.9s**，没有 4–8 条（更没有 10 条）贯穿全场的平滑
  英雄轨迹；单位出屏就断，再进屏按新 x 顺序落到别处。
- **关联玩家 0/10**：0x2d 朝向与轨迹位移方向 R=0.0062（不显著）；
  0x2c 是世界坐标 i32 定点/16（±3290），与 0x12 不同域，目标点到
  最近 0x12 点 L1 中位 2502 vs 打乱基线 2589；0x1e victim 无位置；
  0x81 v6 死亡窗口 ±20 帧轨迹终止 lift 1.16（不可用）。
- **0x13 三个候选都不成立**：类型 ID（medium-high，最长重复 4
  token、45% 帧缺失）；相机角度（medium-high，R=0.25 但把 0x2d
  错位 1/100/1000 帧仍 0.246/0.235/0.249，只是边际分布）；单位
  朝向（medium，≤20° 命中 45.5% vs 随机 47.0%）。更像与 0x12 x
  共用 `0x40/0x80 + 6 位` 编码的**第二个标量/次要坐标**，
  low-medium，未定名。

**产物更新**：`frame_screen_positions_5069040.csv` 列为
`seq/time_s/index/x_raw/x_signed/y`；`agent_screen_positions.csv`
含 position/track/x13/event/stat 五个 section。

## 5.111 0x02/0x80 帧命令：hero-specific action，不是全局 move/attack/skill

主样本 703 条 12B 命令（`abc_frame_cmds.csv`）：

| cmdType | 条数 | 主要 actor | value |
|---:|---:|---|---|
| 1 | 291 | 12(1558) 142、23(1965) 82、65(1021) 66、44(442) 1 | 全 0 |
| 2 | 72 | 37(1966) 53、19(1514) 19 | 全 0 |
| 3 | 211 | 8(338) 97、58(1833) 27、65(1021) 25、23(1965) 16 | 全 0 |
| 5 | 73 | 44/30/12/58/37… | 全 0 |
| 6 | 36 | 65/8/51/37/222… | 0/2304/5632/3840/4608 |
| 7 | 6 | 44/12/37 | 全 0 |
| 9 | 14 | 12/44/65/51/19 | 全 0 |

**结论**：cmdType 1/2/3 按 actor 强偏置（1558/1965/1021 用 1，
1966/1514 用 2，338/1833 用 3），不是全局“移动/攻击/技能”枚举；
更像**hero-specific action ID**。cmdType 6 是唯一带非零 value 的，
候选“技能/施法参数”。actorID 与 0x87/0x29 的 actorID 一致。

## 5.112 source5 131–146：两段式 per-player 奖励（2026-11-01）

主样本 25 条 / 3,453 金，**10 人全有**，呈两段：

- 第一段 **131**（130+1）：每玩家 1 次，时间 4.8–187.5s；
- 第二段 **142–146**（140+2–6）：每玩家 1 次，时间 55.7–451.6s。

例：李不信 4.8s/131 → 43.45s/131 → 57.7s/143 → 362.55s/145；
1558 52.6s/131 → 112.9s/144 → 114.55s/146。

**排除**：不是自然金（首条 4.8s < 40s）；不是辅助专属（10 人全有）；
不是 source43 击杀/助攻金（203/102 另一通道）。候选：
**团队/助攻/目标的两段固定额奖励**（130/140 底额 + 尾数），
具体触发条件仍缺独立事件源；置信 medium-low。

**产物**：`datasets/source5_131_146.csv`（25 行：player/team/slot/
hero_id/seq/time_s/amount/stage）。

**5247758 皮肤（partial）**：块内没有 `18800/16200` 这类皮肤行
ID；heroID 出现在 1804 的 block+128/167/1188、212 的
+137/176/1812；附近有 `00 00 00 03`（1804）/`00 02 00 03`
（212），皮肤 index 候选，但未用面板/皮肤名验证，暂不硬定。

## 5.113 经济来源全表：兵线/野怪/中立/装备/技能/塔/击杀/系统（2026-11-01）

`economy_source_taxonomy.csv`（12 类）把“王者有哪些经济来源”与
回放 source 码对齐：

| 类别 | 回放 source | 金额形态 | 状态 |
|---|---|---|---|
| 兵线 | source4 | 87–135 / 187–219（档位结算） | decoded high |
| 野怪 | source6 | 165–201（全额） | decoded high |
| 野怪刀 +20% | source5 230–254 | 底额×1.2+尾数 | decoded high（金额） |
| 中立资源 | source44/47/51 (+6) | 45/175/150–254 | partial low-medium |
| 装备效果 | source5 31–73 / 131–146 / 230–254 | 31–73、131/142–146、230–254 | partial medium |
| 英雄技能效果 | source5 / 47 / 86 | 131–146、175、13–15 | partial low-medium |
| 塔 | source51/44 | 150/250+尾数 | partial low |
| 击杀/助攻 | source43 | 203/202、102 | partial high（金额） |
| 系统/自然金 | **不在 0x85** | 3/s、40s 起、1000ms；初始 300 | decoded（表） |
| 赏金/一血/连杀 | source44/47/86 | 47/175/13–15 | partial low |
| AI/人机奖励 | source5/44 | 5247758 1,628/2,970 | unknown |
| 当前金币/支出 | 不在 0x85 | — | blocked |

**关键点**：
- source5 是**混合通道**，必须拆成 31–73（小额）、131–146
  （两段式）、230–254（打野刀 +20%）；
- 野怪不是只有一个来源：source6 是全额击杀，source5 230–254
  是打野刀 +20%；
- 中立资源/塔/赏金仍只有 source44/47/51 的固定底额，不能唯一
  定名；
- 自然金/初始金/当前金币/支出**不在 0x85**，只能从表/面板补。

**产物**：`datasets/economy_source_taxonomy.csv`。

## 5.114 CommonSettle/Level/Equip/buff 内联数组与长字段收口（2026-11-01）

只读 `device/dc.db` + `global-metadata.dat`；产物
`datasets/agent_table_arrays.csv`（1,573 行）与
`datasets/agent_table_arrays.md`，脚本 `tools/agent_table_arrays.py`。
这一轮把“行尾内联数组容量未定”的四个表全部按 FixedBuffer 容量 +
自然对齐复现到 stride，不再靠猜测字段。**构建口径**：本机 `dc.db`
的 `databinver=5247758`，主样本是 5069040；下面的行布局/字段名
用 5247758 表验证，5069040 专属行/名称仍需 5069040 的 databin
（与 5.105b、0x29 的 build 缺口一致）。

**CommonSettle（120B）**：前 10 个标量后是 4 个 20B 固定 buffer，
每槽 u32、容量 5；388 行全部只用 slot0：

| offset | 字段 | 语义 | 观测 |
|---:|---|---|---|
| +0x28 | `AntiCheatDetail` | 反作弊参数 | 仅 settle 101 slot0=1 |
| +0x3C | `astRandomRewardDetail` | 随机奖励明细 | 全 0；元素宽度按兄弟数组推 u32（medium） |
| +0x50 | `astFirstCompleteReward` | 首通奖励 | 236 行非零，236/236 命中 RandomRewardStore |
| +0x64 | `astRaidsReward` | 扫荡奖励 | 216 行非零，216/216 命中 RandomRewardStore |

511/521/531/541 只填 first（20511/20521/20531/20541），501/504
同时填 first（1051/1054）与 raids（30201）；RandomRewardStore 行
24B=6×u32，前三项 type/id/num，条数由 `bRewardNum` 给出。

**Level（`ResLevelCfgInfo`，656B）**：10 个数组全部闭合。除
`SelfCampAIHeroID 0x40`、`AIHeroID 0x58`、`RecommendLevel 0xC8`、
`RecommendPower 0xD8`、`ServerCheckPower 0xE8`、
`SettleIDDetail 0x15C` 外，4 个 byte buffer 为：

| offset | 数组 | 字节/元素 | 语义 |
|---:|---|---|---|
| 0x74 | `astStarDetail` | 12B=3×u32 | 3 星条件；67 个非零 100% 命中 EvaluateCond |
| 0x8C | `astRewardShowDetail` | 60B=5×12B | {type,id,num} 奖励预览 |
| 0x1A0 | `astMapBuffs` | 32B=4×8B | {buffID,camp,heroType,dmgType,atkType}；Level 35 行全 0 |
| 0x1C8 | `astReviveInfo` | 144B=4×36B | 复活花费+复活 buff；653010/653020/653030 未回连 |

`SettleIDDetail` 的 83 个非零值 100% 命中 `CommonSettle.dwSettleID`；
`astStarDetail` 的 67 个非零值 100% 命中 `EvaluateCond`。这两条
是“Level→结算/星级”的硬回连，说明 5xxx 是 PVE 第 5 章而不是
普通 5v5 主结算。

**AcntBattleLevel（1,240B）**：`prologue 8B + stLevelCommonInfo
840B + stLevelGamePlayInfo 0x170B + 行尾 24B`。关键锚点：
+0x350 u16=300=`wOriginalGoldCoinInBattle`、+0x358=1900
`iHeroBornAgeDelayTime`、+0x41 `bMaxAcntNum=10`、+0x60
`bMaxCamp=2`、+0x88 `bHeroNum=1`、+0x344 `dwMinCredit=80`、
+0x3E0/0x3E4 `iExtraSkillId/2=90003/90005`、+0x430/0x434
`dwCompensateExpBuffID/GoldBuffID=917010/917011`。普通 5v5
配置 31 行；`stLevelCommonInfo` 里 `bLimitAcntNum` 在本构建
**没有序列化槽**（去掉后 840B 正好对齐 0x2C0/0x344/0x264/0x268）。
**0x348/0x34C 不是数组长度**，而是 common 末尾的
`bIsOpenGamePlayRelic`/`dwGamePlayRelicID`；两个补偿数组实际在
gameplay+0x40/+0x68（0x390/0x3B8），各 40B=5×{dwLevelDiff,
dwExtraRate}，其 `_length` 不落盘。

**Equip（`ResEquipInBattle`，568B）**：84 个声明字段完整对齐，
17 个属性标量全部定位：

| offset | 字段 | 例 |
|---:|---|---|
| 0x68 | `dwPhyAttack` | 铁剑 20、无尽 120 |
| 0x6C | `dwAttackSpeed` | 匕首 1000(=10%)、急速战靴 2000 |
| 0x70 | `dwCriticalHit` | 雷鸣刃 1200、无尽 2000 |
| 0x74 | `dwHealthSteal` | 吸血之镰 800、泣血 2500 |
| 0x78 | `dwMgcHemophagia` | 噬神之书 2400 |
| 0x7C | `dwMagicAttack` | 虚无法杖 210、回响 220 |
| 0x80 | `dwCDReduce` | 冷静之靴 1500、暗影战斧 1000 |
| 0x84 | `dwMagicPoint` | 秘法之靴 400、冰痕 500 |
| 0x88 | `dwMagicRecover` | 炼金护符 10、破碎圣杯 15 |
| 0x8C | `dwPhyDefence` | 反伤刺甲 300、抵抗之靴 50 |
| 0x90 | `dwMagicDefence` | 魔女 300、抵抗之靴 100 |
| 0x94 | `dwHealthPoint` | 无尽 500、不祥 1200、魔女 1100 |
| 0x98 | `dwHealthRecover` | 提神水晶 30、沐光 60 |
| 0x9C | `dwMoveSpeed` | 碎星锤 750、回响 750 |
| 0xA0 | `dwAttackIntensity` | 533 行全 0（仅元数据名） |
| 0xA4 | `dwMagicRecoverRate` | 533 行全 0（仅元数据名） |
| 0xA8 | `dwMainPropertyValue` | 雌雄·双股 80、传国·碧玺 65（candidate） |

百分比/固定值放大 1000：匕首 +10% 攻速=`1000`、雷鸣刃 +12%
暴击=`1200`、噬神之书 +24% 法吸=`2400`、冷静之靴 15% CDR=`1500`。
4 个文本字段是 `strIdDesc 0x1D0`、`strIdDesc2 0x1D8`、
`strIdAdditionDesc 0x1E0`、`strIdDescLabel 0x1E8`。三个数组：
`astPassiveSkill 0xB0` 5×32B、`astEffectCombine 0x150` 4×16B、
`astActiveSkill 0x190` 2×32B；容量/步长 confirmed，元素内
`fxID/srcID/p6/p7` 仍是 candidate。

**buff（0x8268ac，13,558 行）**：新增 +0x14 `dwParentBuffID`
（917010↔917014）、+0x3C `dwChildBuffID`；3 个效果槽
+0x188/+0x240/+0x2F8 各 184B，+0 类型（0xFFFF=空）、+8 效果 ID。
5v5 补偿链已确认：917010/917014 经验补偿（type=204，
+0xD8/+0xDC=10000/10000 与 12000/12000，+0x128/+0x12C=
250/250 与 300/300）、917011 金币补偿（type=107，
+0xD4/+0xD8=3000/1）、917012 第五名金币（type=86，slot0
fx=91770“宝石叠恩赐”）、917013 第四名金币（type=50，slot0
+0x24=264）。917012/917013 与 AcntBattleLevel 的
`dwCompensateExpBuffID/GoldBuffID` 对得上，但每个 param 的
业务公式仍是 candidate。

**对覆盖表的影响**：表布局/原生表从“部分”推进到“布局 high、
语义 candidate”；普通 5v5 结算仍未定位（5xxx 是 PVE 第 5 章），
购买流水/当前金币/最终面板仍 blocked。**剩余未解**：buff 每个
param 的精确公式、Equip 数组剩余参数、Level `astMapBuffs` 的
实际取值（Level 全零）、`RelationActivityMapID` 用途。

## 5.115 运行时 objectID 映射审计：0x1e victim / 0x2c target 不可映射（2026-11-01）

只读 6 个 build 5069040 样本（主样本 + 20260924_113638 /
20260925_094930/095631/101323/103058），产物
`datasets/agent_objectid_map.csv/.md`、`tools/agent_objectid_map.py`。
这一轮不是“再找一张表”，而是把“能不能映射”做成可证伪的统计审计。

**0x1e victim 是 0–994 的运行时池，不是静态行键**：110 条、104 个
不同值；0–994 均匀池模拟的不同值均值 104.14（p=0.534）、跨文件
重复 5 次（期望 3.93，p=0.355）。其中只有 **2/110** 与同局 actorID
数值相同（期望 1.09，p=0.294，碰撞级）；剩下 108 条**不等于
actorID 不能推出“非英雄”**，因为 actor-slot 是另一个 1–359 池。

**0x2c target 也没有英雄富集**：main+tail 901 条，有效 target 835
条、310 个不同值、范围 1–359，明显偏 250–359；命中同局 actorID
**14/835**（bootstrap 期望 20.5，p=0.914，甚至低于期望）。target
逐英雄不同值极高（442 李信 kind1 有 139 个/165 条，远多于 3–4 个
技能槽），所以 target 不是技能 ID；同 target 的 x/y 跨度可达 10^5，
也不是单位位置。0x2c 的 target 语义仍未定，不能当英雄 actorID。

**没有 objectID→单位静态表**：`normalMonster` 2,625 行里 222 个键
≤994，victim 命中 **17/110**（期望 24.5，p=0.974，低于随机）；
`soldierWave` 25/110（p=0.385）；`Project8Hero` 行键 1000–21930，
结构上不可能；塔/器官表 22/110（p=0.578）；野怪图鉴 3/110
（p=0.351）；`0x7384068` 虽覆盖 1–994，但 20,755 行/stride 56
只有技能/效果列，没有单位名列；decoded C# 436 张、native catalog
1,443 张也没有。**不是缺一张表，而是缺运行时 spawn/StepNotify
头**：`MyCampHeroObjIds/EnemyCampHeroObjIds` 才能把 0–994 全局
objectID 对到英雄，逐单位 spawn 日志才能对到小兵/野怪/塔；0x1e
payload 只有 type+victim，没有 unitType/team。

**唯一稳定映射是 actor-slot**：0x02/0x80 的 actor 与 0x87 的
data[3] 是**每局分配**的 1–359 actorID；主样本十人
8/12/19/23/30/37/44/51/58/65。同一个 44 在 105224 是李信、在
101323 是鬼谷子、在 113638 是上官婉儿，所以任何静态表都不可能
按 actorID 直接命名；6 个样本共 44 条英雄 actor 映射。

**时间对齐全部阴性**：0x1e vs source4 小兵金 ±1s 1/110（随机
3.4%）、source6 野怪金 0、source43 击杀金 0、0x2c target 0、
cmdType6 0、0x81 v6 死亡窗口 4/110（随机 6.6%）。0x1e 不是
补刀/击杀账本，也不是 0x2c 的命中结果；0x1f actor 9 条虽都在
0–994 但与 victim 同文件 0 交集，0x20 actor 有 21641>994，明确
不是同一池；0x01/0x48 的 37120、0x02/0x86 的 4690 也都不在两池。

**结论**：0x1e victim 110/110 具体类别未知，0x2c target 0 条高置信；
这两项应标 **blocked（缺运行时头）**，不再用“不等于 actorID”
推断兵种。产物 `agent_objectid_map.csv/.md`。

## 5.116 本地 QTSF/QtskDB 回放系统文件扫描（2026-11-02）

范围：`data/replays/_analysis/device/` 的 6 个主容器
（`dev0/dev1/dev9/orig0/gen9/orig9.db`）+ 28 个 `pkgidx/*.db` +
`dc.db`；只读静态解析，未启动模拟器、未登录、未注入、未读
`param.json`、未用 `runtime_dump`。产物
`datasets/agent_qts_replay_files.md/.csv/.json`，脚本
`data/replays/_analysis/tools/agent_qts_replay_scan.py`。

**QTSF 解析**：6 个主容器都有 `QTSF_PACKAGE` 根记录（156B），
根 `hash_A` 六文件一致 `0xd14b28c0acc40d11`。节点数：
`dev0` 643、`dev1` 195,040、`dev9` 9,554、`orig0` 15,389、
`gen9` 96,129、`orig9` 96,128。92B/104B/272B 记录逐字节验证；
多 extent 描述符区是 **`12*count - 4`**（前 count−1 个 12B 带
offset，最后一个 8B 省略 offset），修正 5.14.2 的“12B/个”。

**扫描结果**：

| 目标 | 判定 | 证据 |
|---|---|---|
| GameReplayModule/QuickReplaySystem/ClientRecordSystem 实现 | **NOT FOUND** | 34 个 QTSF 包 × 21 个精确字面量 0 命中；节点名几乎全是 hash/数字 ID，唯一可读名 `Play_ui_ingame_biaoqing_014`；实现在容器外 `global-metadata.dat`/libil2cpp |
| 回放缓存 ReplayCache | **NOT FOUND** | QTS 0 命中；`ReplayCache` 只在 metadata `m_AceReplayCacheData`(0x45d0b1)；`dc.db` 只有“本地回放已保存/删除回放文件”UI 文案 |
| `.abh`/`.abc`/`.ope` | **NOT FOUND** | 34 个包大小写敏感路径扫描 0 命中；`dev1` 0xdccaaf 的 `.ABc` 是 92B 节点摘要里的随机 4B，不是路径 |
| 结算/战绩**数据** | **NOT FOUND** | QTS 0 命中；`dc.db` 的 956 `Settle`、248 `Result`、49 `BattleResult`、396“结算”、103“战绩”全是 UI key/文案 |
| 回放 UI/配置 | **FOUND（仅 dc.db）** | 64 次 ASCII 回放串（61 个不同值；ReplayKit 12、ACE_REPLAY 10、PvpHistoryReplay 6、其它 36）+ 44 条中文“回放”+ 5 次 battle-replay H5 URL |

关键文案：`Form_PvpNewSettlement_BeginReplay`→“查看回放”；
`PvpHistoryReplay_SaveSuccess`→“已保存至本地回放，请前往观战系统
观看回放。”；`replaySaveFailed`→“回放保存失败，存储空间不足…”。
注意 `ReplayKit` 是 iOS 录屏 SDK 字符串，**不是**王者回放系统。

**`3200011801` 的性质**：它是 dev0 索引区 ID 清单的记录键：
`[u32 长度=10][ASCII 数字][2B pad][u64 value]`，三份拷贝 value
均 `0x2b632ccbbed144e8`。全部 QTSF 包共 1,752 个不同键，22 个与
`allpkg_cfg.txt` 包 ID 完全一致（如 320112、305000000065），689 个
以 `320001` 开头；与节点 hash、`dc.db` u64、hash64/FNV/MD5 变体
0 交集 → **LIKELY 资源 ID/清单键**，不是 databin 表键、不是文件
偏移；ID→u64 的生成方式仍 **blocked**。

**LZ4 边界**：`lz4.block` 在 0x4ff4/0x5000/0x5004/0x4ff0/0x4ff8
全部失败；手工 token 解码 dev9 0x4ff4 无种子 8 token/1,056B 后
`match_off=0x165c` 越窗，加 64KB 原始种子 198 token/3,016B 后
0x7000 越窗。解出片段含 `S_MOVE9`、`animationCurve`、
`avatar_bodyL`，**回放关键词 0 命中**。卡点是页封装/64KB 历史窗口
未知、本地无数据卷 `X_0.db`；dev0/dev1/orig0/gen9/orig9 的压缩
内容内部只能标 **blocked**，不能 100% 排除。但明文部分（含 dev9
已知资源名标记）已全量扫描，0 命中。

**结论**：本地 QTSF/QtskDB 容器里**没有**回放系统实现文件、
回放缓存、`.abh/.abc/.ope`、结算/战绩行数据；只有 `dc.db` 的
回放/结算 UI 文案、配置键和 H5 URL。回放数据侧仍是 `.abc/.ope`；
实现侧在容器外 `global-metadata.dat`/libil2cpp 与加密 GameCoreTS/
QTS 资源里，目前没有找到可直接读的实现文件。这个结论只覆盖
“可见/明文节点 + 已解出的 LZ4 片段”，不覆盖未解开的压缩页。

## 5.117 回放 UI 入口：OnClickBeginReplay 等符号（2026-11-02）

“查看回放”不是没有跳转。metadata 里有完整的 UI 入口符号：

- `CPlayerPvpHistoryController::OnClickBeginReplay`
- `CPlayerPvpHistoryController::OnClickSaveReplay` /
  `OnClickSaveReplayImpl`
- `CPlayerPvpHistoryController::GetReplayFilePathByGameId`
- `CPlayerPvpHistoryController::RefreshHistoryReplayBtns`
- `CPlayerPvpHistoryController::OnOpenYingdiReplay`
- 同族 UI 方法：`OnClickReplay`、`OnEnterReplayFile`、
  `OnOpenQuickReplayForm`、`OnCloseQuickReplayForm`、
  `OnOpenAceReplay`、`OnGetAceReplayList` 等。

`dc.db` 侧对应：

- 文案 key `Form_PvpNewSettlement_BeginReplay` → “查看回放”；
- prefab `UGUI/SystemRes/026_PlayerInfo/Form/Form_History_Detail_Info.prefab`
  的 widget `Center\FuncContainer\ButtonBeginReplay`；
- `PvpHistoryReplay_SaveSuccess` → “已保存至本地回放，请前往观战
  系统观看回放。”；`replaySaveFailed` → “回放保存失败，存储空间
  不足…”。

因此合理链路是：结算/历史详情按钮 → `OnClickBeginReplay` →
`GetReplayFilePathByGameId` 找本地 `.abc/.ope` → `QuickReplaySystem`
/`GameReplayModule.BeginReplay` → `SGW.PureReplayStart`。这也解释
了“点查看回放没反应”的一种常见原因：先按 gameId 查本地文件，
文件不存在/已被清理就不会跳。

**未闭合**：`addr2method.json` 把 `OnClickBeginReplay` 标到
0x4620578，但离线反汇编出来的是一段通用集合/迭代器代码，不是该
方法体；方法槽/地址映射有偏差（与 5.41 的“方法槽指向共享函数
中部”一致）。所以现在只能确认“有 handler、有按钮、有文件查找
方法”，不能确认它直接跳 `BeginReplay` 还是先开观战/历史详情页，
也不能确认传参。要继续，必须先校准 `OnClickBeginReplay` /
`GetReplayFilePathByGameId` 的真实 method pointer，再反方法体。

**2026-11-02 指针校准**：metadata 全局方法索引/ token / relocated
pointer 为：

| 方法 | index | token | ptr |
|---|---:|---|---:|
| `OnClickSaveReplay` | 54240 | 0x600d3e1 | 0x4620568 |
| `OnClickBeginReplay` | 54241 | 0x600d3e2 | 0x4620578 |
| `GetReplayFilePathByGameId` | 54255 | 0x600d3f0 | 0x462092c |

但 0x4620578 反汇编是 `str x1,[x0]; str wzr,[x0,#8]; ldr w8,[x1,#0x14];
str w8,[x0,#0xc]; ret`，即 List/集合枚举器构造（list/index/version），
不是点击处理；0x462092c 同型。相邻 `OnClickReport`(0x46202a8)、
`get_MvpScoreOffset`(0x461f668) 是单条 `ret`，`OnClickDetailInfo`
(0x461fe80) 也是枚举器构造。**结论：该类的 UI 方法指针不是直接
方法体**（方法槽指向共享/泛型代码或 stub），不能靠这个地址反跳转；
需要从 UI 事件绑定表、prefab 的 `onClick` 序列化数据或 `.ope` 的
`UiEventOperatorData` 入手。

**2026-11-02 调用者扫描**：在 `0x4400000–0x4700000`（3 MB UI
代码区）线性反汇编 786,432 条指令，扫所有 `BL/B` 目标
`0x665a23c`(BeginReplay live)、`0x64629cc`(OnOpenQuickReplayForm)、
`0x6462c50`(OnEnterReplayFile)、`0x645dba0`(.data BeginReplay)、
`0x4620578`(OnClickBeginReplay ptr)、`0x462092c`(GetReplayFilePath
ptr)，**全部 0 命中**。UI 事件是间接调用（delegate/UnityEvent），
静态 `BL` 找不到调用者。live 侧 `live2_mem/metadata.bin` 只有
metadata 方法表（token 0x600d3e2 在 0x105028c/0x12ea5ac/0x153ccec
三处，均为 32B MethodDef 记录），没有 UI MethodInfo 对象；
`runtime_dump/memory.bin` 也没有该 token。**所以 UI handler 真实
方法体仍缺**：要么拿带“查看回放”点击的 `.ope`（UiEventOperatorData），
要么解 prefab 的 `onClick` 序列化，要么拿 live MethodInfo 快照；
继续硬反 `0x4620578` 不会得到 handler。

**BeginReplay 实机地址（2026-11-02）**：`GameReplayModule.BeginReplay`
的 live MethodInfo static 地址是 **0x665a23c**（docs 5.41），反汇编
是完整真实函数（`sub sp,sp,#0x60`，读写 `this+0x70/0x78/0x80/0xb8`
等字段），不是 `.data` 里的 0x645dba0。它多次 `blr` 间接函数指针
（0xd54bf00、0xd54bf18、0xd860400、0xd90cde0、0xd945928 等）；
用 RELA 读这些指针得到 0x665a82c/0x665aa14/0xc1ed4c8/…，但
`addr2method.json` 对非虚方法的名字不可靠（0xd54bf00 被标成
`PerfSight::.ctor`），所以不能据此确认 BeginReplay 内部调用链。
可以确定的是：**回放启动侧是真实托管代码 + 间接函数指针**，不是
纯 stub；UI 到 BeginReplay 的连接仍未实锤。

## 5.118 公开研究：王者荣耀 C# DLL 反编译仓库（2026-11-02）

公开可检索范围内，**确实有人研究过**，而且不是只研究文件位置：

- `ihaiucom/wangzhe.WangZheDllCode`（GitHub，2021，约 110 MB）是
  **王者荣耀 C# DLL 反编译代码**，包含
  `Assets.Scripts.Framework/GameReplayModule.cs`、
  `Assets.Scripts.GameSystem/FrameSync/WatchController.cs`、
  `CPlayerPvpHistoryController.cs`、`ReplayControl.cs`、`COBSystem.cs`
  等。`moto2002/joework` 和 `houshuo/wzry` 也有同源/复制代码。
- 它不是 `.abc/.ope` 字段解析器，但直接给出了回放系统实现：
  `GameReplayModule` 的 11 字段头、`BeginReplay(path)`、
  `ListReplayFiles()`、`LoadMsg()`、`UpdateFrame()`、
  `DirectHandleMsg()`、`WatchController.StartReplay(path)`。
- 公开代码的 `.abc` 头字段顺序（2021 build）：
  `appVersion:string, resourceVersion:string, revision:string,
  heroID:uint32, startTime:int64, mapType:uint8, mapId:uint32,
  userName:string, userHead:string, rankGrade:uint8,
  rankClass:uint32`。
  2026 主样本在 `revision` 后多一个 `build` 字符串（5069040），
  其余逐字段对上：heroID=187、mapType=3、mapId=20111、
  userName=`佚名(*:`、rankGrade=19、rankClass=0。
- 公开代码的 `.abc` 记录格式是 `short length` + TDR-packed
  `CSDT_FRAPBOOT_INFO`（正长度）或 `CSPkg`（负长度）；
  `GameReplayModule.LoadMsg()` 按这个规则读。2026 样本的
  `seq/pad/L` 帧流是同一文件的另一层/新 build 变化，不能直接把
  2021 的 `short length` 套到所有 tag 上。
- 公开代码还给出 `ReplayFileInfo`：path/heroId/startTime/mapType/
  mapId/userName/userHead/userRankGrade/userRankClass/isExpired；
  `WatchController.StartReplay` 失败提示 `Can not play file: path`。
- 相邻公开项目：`Moli13337/Honor-of-Kings-protocol`（协议）、
  `tien0246/Dump-Honor-of-Kings-iOS`（dump）、
  `dsgaming-mrd/Il2CppDumper-GUI-HoK`（IL2CPP dump）。
  这些不是 `.abc/.ope` 字段解析器，但可作为类/协议参考。
- **没有找到公开的 `.ope` 位流解析器**。`.ope` 的类型枚举和部分
  记录字段仍是我们这边推进得更多；公开代码主要覆盖 `.abc` 回放
  头/消息和 UI 流程。
- UI 侧补充：`EN_ButtonBeginReplay` 在
  `enUIComponentWidgets_Form_History_Detail_Info` 里值 **13**；
  `Player_Info_PveHistory_ClickBeginReplay` 的 UIEventID 解为
  **30537**（`ClickSaveReplay`=30536、`QuickReplay_OpenSelectForm`=
  116400）。43 个 `.ope` 里 52,387 条 `UIEventOpe`、80 个不同
  EventID，但 30536/30537/30520/9993/9994/10029/116400-116402
  全部 0 次——**没有“查看回放”点击样本**；prefab 的 `onClick`
  序列化在 QTSF 压缩页里，仍 blocked。

**结论**：公开研究存在，且直接覆盖 `.abc` 回放系统实现和 UI 流程；
它帮我们修正了 `.abc` 头字段（本文件 5.90/字段字典已更新），但
没有公开的 `.abc` tag 全字段解析器，也没有公开的 `.ope` 位流解析器。
我们的 `.abc` tag 字段和 `.ope` 类型/部分字段仍是独立推进。

## 5.119 公开协议类对照：FrapBoot / CMD / Settle（2026-11-02）

公开仓库的 `Assembly-CSharp-firstpass/CSProtocol` 给出了回放消息和
结算的完整类定义。它不是 2026 build 的直接解析器，但把字段语义
补齐了：

**FrapBoot**

- `CSDT_FRAPBOOT_INFO`：`dwKFrapsNo:u32`、`bNum:u8`、
  `astBootInfo[40]:CSDT_FRAPBOOT_DETAIL`。
- `CSDT_FRAPBOOT_DETAIL`：`bType:u8` + `UN_FRAPBOOT_DT`。
- `UN_FRAPBOOT_DT` 的 selector 1–7：
  1=`CSDT_FRAPBOOT_CC`、2=`CSDT_FRAPBOOT_CS`、
  3=`CSDT_FRAPBOOT_ACNTSTATE`、4=`CSDT_FRAPBOOT_ASSISTSTATE`、
  5=`CSDT_FRAPBOOT_AISTATE`、6=`CSDT_FRAPBOOT_GAMEOVERNTF`、
  7=`CSDT_FRAPBOOT_PAUSE`。
- `CSDT_FRAPBOOT_GAMEOVERNTF` 只有 `bWinCamp:u8`——胜负字段。
- `CSDT_FRAPBOOT_CS`：`dwObjID:u32` + `CSDT_GAMING_CSSYNCINFO`。
- `CSDT_GAMING_CSSYNCINFO`：`bSyncType:u8` + union；
  selector 128–132 = 指向技能/方向技能/位置技能/移动/普攻。
- `CSDT_GAMING_CCSYNCINFO`：`wLen:u16` + `szBuff[64]`，是不透明
  CC 同步缓冲，和 0x23 硬控窗口的“无字段”表现一致。

**CMD 类字段**（TDR 整数是 **大端**；`.abc` 头是 BinaryWriter
小端，两者不要混）：

| 类 | 字段 |
|---|---|
| `CSDT_CMD_MOVE` | `nDegree:i16`, `bSeq:u8` |
| `CSDT_CMD_USEDIRECTIONALSKILL` | `chSlotType:i8`, `nDegree:i16`, `dwObjectID:u32` |
| `CSDT_CMD_USEPOSITIONSKILL` | `chSlotType:i8`, `stPosition:CSDT_VECTOR2` |
| `CSDT_VECTOR2` | `X:i32`, `Z:i32`（大端） |
| `CSDT_CMD_BASEATTACK` | `bStart:u8`, `dwObjectID:u32` |
| `CSDT_CMD_USEOBJECTIVESKILL` | `chSlotType:i8`, `iObjectID:i32` |

这给 0x2d/0x2c/0x1e/0x29/0x23 提供了强语义标签：0x2d=移动/方向角，
0x2c=位置/方向技能，0x1e=普攻目标，0x29=指向技能目标，0x23=CC
同步缓冲。2026 tag 的 framing 仍不同，不能直接套 2021 的 TDR 偏移。

**Settle/KDA 类**

- `CSCMD_ID_DEF.SCID_MULTGAME_SETTLEGAIN = 1082`；
  `SCPKG_MULTIGAME_SETTLEGAIN` = `iErrCode:i32` +
  `COMDT_SETTLE_RESULT_DETAIL`。
- `COMDT_SETTLE_HERO_INFO` 里有 `stHeroBattleInfo:
  COMDT_HERO_BATTLE_STATISTIC_INFO`。
- `COMDT_HERO_BATTLE_STATISTIC_INFO` 直接有：
  `dwKillCnt/dwDeadCnt/dwAssistCnt`、`dwTotalHurtCnt`、
  `dwTotalBeHurtCnt`、`dwTotalHealCnt`、`dwSoliderKillCoin/
  dwMonsterKillCoin/dwTowerKillCoin/dwDragonKillCoin/dwHeroKillCoin/
  dwSystemAddCoin`、`bDestroyTowerCnt`、`wKillSoldierCnt`、
  `wKillMonsterCnt`、`dwTotalInGameCoin/dwMaxInGameCoin`（在
  `COMDT_SETTLE_GAME_GENERAL_INFO`）等。
- 这就是最终面板/KDA/输出/承伤/经济分解的精确 schema。

**但回放里没有结算包**：用 `CSPkgHead.dwMsgID=1082` + 负 short
长度/版本/seq 合法性扫了 30 个 `.abc`，**0 个结算包候选**。
`CSPkgHead` 是 `dwMsgID:i32`、`iVersion:i32`、`dwSvrPkgSeq:u32`、
`dwReserve:u32`，均为大端；主样本里没有合法的 1082 头。说明
2026 回放没有把 `SCPKG_MULTIGAME_SETTLEGAIN` 写进 `.abc`，或者
framing 已变。**最终面板/KDA 仍不能直接从本样本回放提取**；但
现在有了精确字段表，可以用来校验面板 OCR/录屏真值。

**结论**：公开代码是“语义/字段字典”的突破，不是“2026 回放
直接解析器”。能用它修正 `.abc` 头、给 tag 定名、给最终面板
KDA/伤害/经济 schema；不能用它跳过 2026 framing 和结算包缺失。

## 5.120 5247758 完整面板与 settle schema 对拍（2026-11-02）

六张结算面板截图（数据/输出/生存/团队/战绩/发育）已整理为
`datasets/new_5247758_panel_truth_full.csv`（10 人 × 25 列）：
K/D/A、总经济、野怪经济、补刀、输出/承伤/治疗/控制/对塔伤害及
团队占比、伤害转化比、评分。和公开
`COMDT_HERO_BATTLE_STATISTIC_INFO` 的映射写在
`datasets/settle_schema_map_5247758.csv`。

**已用面板反推/验证的公式**：

- 参团率 = `(kills + assists) / 队伍总击杀`：
  大禹 (9+12)/38=55%、娜可 (22+2)/38=63%、莱西奥 (3+14)/38=44%；
  队 2 总击杀 8：镜 5/8=62%、芈月 5/8=62%、虞姬 3/8=37%。
- 每死承伤 = `承受伤害 / 死亡数`：花木兰 29.1k/2=14.55k→14.5k、
  虞姬 48.7k/7=6.96k→7.0k、海月 59.5k/12=4.96k→5.0k。
- 输出/承伤/治疗/对塔/野怪/补刀百分比 = 队内份额：
  队 1 输出 266.3k，48.5/266.3=18%；治疗 91.2k，44.9/91.2=49%；
  野怪 3.86k，3.5/3.86=91%；补刀 99，42/99=42%。
- 伤害转化比不是 output/gold 的简单比值（48.5k/6.3k≈7.7，
  面板是 1.1），公式仍未定。

**跨队对拍（强）**：队 1 输出 266.3k ≈ 队 2 承伤 266.3k；
队 2 输出 125.4k ≈ 队 1 承伤 125.5k → 输出/承伤是同一伤害
账本的两端。队 1 击杀 38 = 队 2 死亡 38；队 2 击杀 8，但队 1
死亡合计 9，差 1（可能有未记入击杀的死亡/处决），和之前
“source43/0x81 不是全量 KDA 账本”的结论一致。

**settle 字段候选**：`dwKillCnt/dwDeadCnt/dwAssistCnt`（高）、
`dwTotalHurtCnt`/`dwTotalHurtHeroCnt`（输出，medium）、
`dwTotalBeHurtCnt`/`dwTotalBeHeroHurtCnt`（承伤，medium）、
`dwTotalHealCnt`（治疗，medium）、`dwTotalHurtOrganCnt`
（对塔，medium-high）、`dwMonsterKillCoin`（野怪，medium-high）、
`wKillSoldierCnt`（补刀，medium-high）、
`COMDT_SETTLE_GAME_GENERAL_INFO.dwTotalInGameCoin`（总经济，
medium）。评分和伤害转化比不在 `COMDT_HERO_BATTLE_STATISTIC_INFO`
里，评分需另找 settle rank/score 字段。

**边界**：这仍是“面板真值 ↔ settle schema”的对拍，不是从
`.abc` 直接读结算包；30 个 `.abc` 里没有 1082 结算包。它的价值是：
如果以后拿到带结算包的回放/服务端快照，可以直接按这张表填；
如果只有面板，也能用这张表做 OCR 校验和字段命名。

**版本纠正（2026-11-02）**：1082 和
`SCPKG_MULTIGAME_SETTLEGAIN`/`SCID_MULTGAME_SETTLEGAIN` 是 2021
公开代码的旧协议名。当前 5247758 metadata **没有这两个符号**，
只有 `COMDT_SETTLE_HERO_INFO`、`COMDT_HERO_BATTLE_STATISTIC_INFO`、
`COMDT_SETTLE_GAME_GENERAL_INFO` 等字段类，以及新的
`SCPKG_TOKEN_GAME_SETTLE_RESULT_NTF`、`SETTLE_RESULT_NTF` 等
包名。**不能再用 1082 当 2026 的结算包 ID**；下一步要按新包名
在当前 metadata/代码里找新的 msgID，再扫 5069040 最新赛季普通
5v5 样本。另：5247758 面板是**人机模式**，不是普通 5v5；它适合
验证 KDA/伤害/参团率公式，但不能直接当普通 5v5 的真值。

> 更正（5.125）：以下数值与 sentinel 判断来自错误的固定宽度默认值解码，
> 不再作为当前结论。当前代码注册表和压缩默认值交叉验证：开局1075、开战1077、
> GAME_OVER_RSP1082、道具购买1126、MVP评分1251、token game结算21704。
> 旧的1140扫描不能代替1082扫描；新扫描和适用范围见5.125。

**数值 msgID 的历史结果（2026-11-02，已由5.125修正）**：用
`tools/agent_gold_source_enum.Metadata` 读当前 `CSCMD_ID_DEF`
（4,350 个成员）：

- `SCID_FRAPBOOT_SINGLE = 1044`、`SCID_FRAPBOOTINFO = 1046`、
  `SCID_MULTGAME_BEGINLOAD = 1126`（默认表可靠）。
- `SCID_TOKEN_GAME_SETTLE_RESULT_NTF` 在成员 idx 2759，默认表读出的
  值是 **8192**；同一块成员大量都是 8192/8193（`SCID_UGC_SMALL_SETTLE_RSP`、
  `SCID_SETTLE_BACKTO_TEAM_RSP` 等），这是 **sentinel/默认表不可靠**，
  不能当可信 msgID。
- 因此**还不能用新 ID 扫 5069040**。要拿真实值，得反
  `CSPkgBody.select(selector)` 的分支常量或 `CSCMD_ID_DEF` 的
  静态初始化/枚举值表，而不是继续读 metadata 默认值。

**所以当前结论**：1082 确认过时；settle 字段 schema 仍有效；
新包名存在但数值 msgID 未解析；5069040 的结算包扫描暂时 blocked，
不是“没找”。如果拿到新 msgID，再按
`COMDT_SETTLE_HERO_INFO`/`COMDT_HERO_BATTLE_STATISTIC_INFO` 解
KDA/伤害/经济。

**正确包名/ID（2026-11-02）**：当前 metadata 的
`COMDT_SETTLE_RESULT_DETAIL` 挂在 **`SCPKG_GAME_OVER_RSP`** 上
（同一字段串里还有 `stGameInfo`、`stHeroList`、
`astTeamFriendInfo`、`stMultipleDetail` 等），对应
`CSCMD_ID_DEF.SCID_GAME_OVER_RSP = 1140`。
`SCPKG_TOKEN_GAME_SETTLE_RESULT_NTF` 是 token game（字段只有
stJoinInfo/bGameResult/dwWinNum/…），不是普通 5v5 settle；旧
1082/`SCPKG_MULTIGAME_SETTLEGAIN` 也不再存在。**普通 5v5 的
目标包应是 `SCPKG_GAME_OVER_RSP` / 1140**，不是 token game。

**1140 扫描结果**：30 个 `.abc` 里没有“CSPkgHead 1140 + 合法
version/seq/reserve”的候选；raw 1140 在样本里确实出现（主样本
0x1627b），但上下文是 `00 00 04 74 00 36 0c 13 a1 12 9a 17…`，
是 tag 流里的值/长度，不是 CSPkgHead。也就是说：**当前 `.abc`
没有可识别的 1140 结算包**，要么回放结束前没写 settle，要么
2026 framing 不把 `CSPkg` 头放在这里。settle schema 仍可用于
面板真值校验。

## 5.121 原客户端启动与设备本地文件检查（2026-11-02）

本轮实际启动已安装的 MuMu 与王者客户端，不登录、不注入、不调用游戏内部函数，
不修改/删除设备游戏文件。用户确认停在登录页，随后由用户进入离线模式。
Android 原生截图确认离线选英雄页；点击取消后回到英雄练习场菜单，
画面仅显示离线训练及其他“离线不支持”的模式。本轮未启动新对局，未播放 ABC。

**启动与外部入口实测**：

- MuMu Android 15 实例 0 已启动，ADB 127.0.0.1:16384；客户端包名
  `com.tencent.tmgp.sgame`，versionName=12.1.1.1、versionCode=1201010103。
  这是 APK 版本，不代表资源 build 已与任何 ABC 匹配。
- 正常 MAIN/LAUNCHER 入口为 `.SGameActivity`；启动等待曾超时，之后检测到
  进程 2297，前台 Activity 也是 `.SGameActivity`。不能仅凭进程存在判断登录/回放状态。
- Android 查询 `.abc` 的 file:// VIEW 和 application/octet-stream 的 content:// VIEW
  均为 No activities found；向探针 URI 发送 ACTION_VIEW 也明确报 unable to resolve Intent。
  探针只测试系统路由，**没有打开真实 ABC，也没有验证其格式兼容性**。
- `smoba://` 注册了 `.SGameActivity`，但回放参数/分发条件未解；不能据此证明不存在
  内部回放入口。新增只读复现脚本 `tools/client_replay_entry_probe.py`。
- Windows UI 捕获反复超时，并出现 nvspcap64.dll 损坏映像 0xc000012f；已关闭错误提示，
  未改驱动/系统设置。后来以 Android screencap 成功观察，故窗口捕获问题不再当作回放阻塞。

**直接检查设备目录**：

- `/sdcard/Android/data/com.tencent.tmgp.sgame/files/Replay/AutoSave/` 有两组文件：
  - `20261030_215535.abc` 18,744 B、`.ope` 552 B；头为
    12.1.1.1/12.1.1.26、4989537/5247758；localHeroId=106、mapType=1、mapId=20047。
  - `20261028_135516.abc` 68,268 B、`.ope` 14,355 B；头为
    12.1.1.1/12.1.1.23、4989537/5230306；localHeroId=118、mapType=1、mapId=1010。
  文件存在不等于可完整重放；尤其不能仅凭 18 KB 的头就认定为普通 5v5 完整样本。
- `AceReplay`、`FriendReplay` 目录当前无文件；在外部 files 根目录下最多 4 层搜索
  没有 `.abh`，这不证明所有 APK/内部/虚拟资源中都没有该类文件。
- 当前 adb 为 shell 用户；访问 `/data/user/0/com.tencent.tmgp.sgame/files` 返回 Permission denied。
  本轮未提升权限，不把外部目录的观察外推到内部私有目录。
- 外部 files 根目录另有多组成对的 `0000000000_0000000000_<编号>.csd/.dmg`。
  所取样编号 10274：CSD 6,406 B，首字节 `72 65 63 00`（rec + NUL）；
  DMG 6,948,474 B，首 4 B `af af af af`。文件内容用途尚未解码。
- 当前磁盘 metadata 有 `ReplayMemoryRecover.SaveRecovery/PrepareReplayRecover/
  MultiPlayerReplayRecover/DeleteDmgFileBeyondFrameNum`；字符串常量含
  `{0:D10}_{1:D10}_{2:D10}.dmg` 和对应 CSD/DMG 格式串，与设备文件名形状一致。
  这是“回放恢复/跳转相关文件”的研究线索，**不是已经确认可加载的战斗快照**；
  还需要解析读写逻辑、版本和与 ABC 的配对关系，不能直接调用恢复或覆盖原文件。

两组回放与一组 CSD/DMG 的副本保存在 git 忽略的
`data/replays/_analysis/client_probe_20261102/`，manifest.json 记录大小与 SHA-256。
6 个文件的本地副本与设备端 sha256sum 全部一致。设备原文件保持不变，副本不提交/传播。

**下一步**：优先沿已存在的 Recovery 文件格式和真实读取链检查是否可复用状态恢复，
并继续确认本地回放入口；不能宣称本轮已把任意 `.abc/.ope` 喂进原客户端播放。

## 5.122 公开研究再检索：官方 ABS 工具与客户端 ABC 回放自动化（2026-11-02）

本轮搜索 `.abc/.ope` 解析、独立运行器和 `.csd/.dmg`/ReplayMemoryRecover。
以下结论均核对项目实际 README/源码；未下载或执行第三方工具，未申请账号/授权。

- 腾讯官方 `tencent-ailab/hok_env` README 明确提供 GameCore 配套的
  **ABSTOOL.exe**：将 GameCore 生成的 `.abs` 放入 `Replays` 后可视化播放。
  同一 README 描述 GameCore 申请与 license.dat，并提供 1v1/3v3 环境。
  这是“独立回放运行器确实存在”的直接证据，但没有证明它能导入当前商业客户端的
  5v5 `.abc/.ope`，不能将扩展名改为 ABS 就当作兼容。
  来源：https://github.com/tencent-ailab/hok_env/blob/master/README.md
- ARM 官方 `ARM-software/workload-automation` 的 honorofkings workload，
  实际代码把 `replay.abc` 推到应用外部目录的 `files/Replay`，再通过既有
  客户端自动化播放。明确要求已经登录且资源下载完成，requires_network=True；
  同时列出国服和国际服包名。这是 ABC 文件喂回原客户端的可参考工程实现，
  不是独立解析器，也不能直接解决当前无登录条件。
  来源：https://github.com/ARM-software/workload-automation/blob/master/wa/workloads/honorofkings/__init__.py
- 再次直接读取 `ihaiucom/wangzhe.WangZheDllCode` 的旧版
  `GameReplayModule.cs`：确认有 BeginReplay、LoadMsg、ListReplayFiles 和文件头读写。
  ListReplayFiles 只在 ReplayFolder 顶层枚举 `*.ab?`，而本机现有文件都位于
  Replay/AutoSave 子目录。结合 ARM 的导入目录，这给出一个具体待验证假设：
  当前版本是否也区分“自动缓存目录”和“可在列表播放的根目录”。
  **当前版本尚未对拍，不代表移动/复制文件就一定能播放**，本轮没有移动原文件。
  此源码属于旧版本参考，不能把其偏移/协议直接套到 2026 build。
  来源：https://github.com/ihaiucom/wangzhe.WangZheDllCode/blob/master/Asssembly-CSharp/Assets.Scripts.Framework/GameReplayModule.cs

公开代码搜索 ReplayMemoryRecover 无相关结果；PrepareReplayRecover 命中的
其他项目与王者无关。网页搜索亦未找到有源码和样本验证的当前版本
`.csd/.dmg` 恢复器或 `.ope` 完整解析器。检索范围内未找到不等于不存在。

路线价值排序：先核对官方 ABSTOOL 的输入契约/可获得版本；对原客户端路线，
参考 ARM 的 Replay 根目录导入方式并验证当前文件发现逻辑；Recovery 文件继续做
本地证据研究。不要采用没有源代码或样本验证的“ABC 一键转 MP4”网页结论。

## 5.123 ABSTOOL 获取/兼容性核查与当前客户端目录扫描签名（2026-11-02）

本轮只做公开资料及本地文件读取；没有申请授权、登录、发送消息、运行新软件或写设备目录。

**官方工具的证据边界**：

- 腾讯官方 README 明确承诺随 GameCore 提供 ABSTOOL，输入为该 GameCore 生成的
  ABS 文件，放入 `Replays`。官方页面目前跳转到
  https://tencentarena.com/aiarena/en/open-gamecore ，说明研究者提交承诺书/申请授权、
  审批后可下载 Windows Gamecore Server。这里只读取网页，未提交任何申请。
- 直接查询官方仓库 Releases，早期版本没有上传的二进制附件；更早版本
  附件是 3v3-level-0..6 训练 checkpoint，没有 ABSTOOL。自动生成的源码压缩包
  不等于工具运行包。本地 data/resources 中也未找到 ABSTOOL 或 ABS 样本。
- 官方仓库 Issue 52 有缺少 SGame_Data 而无法启动工具的实际报告，后续回复要求
  获取更新的完整 GameCore 包并把生成的 ABS 放入 Replays。它支持“不能只拿 EXE
  当完整播放器”的判断，但没有给出支持 2026 商业客户端 ABC/OPE 的证据。
- 官方仓库内搜索 ABSTOOL 命中 README，搜索 `.abc` 未找到相关代码；没有取得 ABS
  格式规范、样本或工具运行包，故**没有执行 ABC→ABS 字节对比或加载兼容性实测**。
  结论是兼容性未知，不是已经证明不兼容。SDK 发布号不等于客户端资源 build。

主要来源：
- https://github.com/tencent-ailab/hok_env/blob/master/README.md
- https://github.com/tencent-ailab/hok_env/releases
- https://github.com/tencent-ailab/hok_env/issues/52
- https://tencentarena.com/aiarena/en/open-gamecore

**当前客户端扫描接口与旧源码存在实质差异**：

独立读取当前磁盘 metadata 的方法/参数表，得到：

- `ListReplayFiles(removeObsolete, folderName, fileNameRegex)`，token 0x6002b64；
- `ScanReplayFiles(scanFolder, removeObsolete, retLst, fileNameRegex)`，token 0x6002b65；
- `GetReplayInfoByFilePath(path)`，token 0x6002b66。

同样方法名/token/参数数量也在历史 live2 metadata 中出现，但这不授权混用它们的
全局索引/地址。当前磁盘 metadata 的参数名说明调用方可以提供文件夹和文件名规则；
**不能只依据旧源码顶层扫描就认定当前 AutoSave 不被扫描**，也未证明递归行为或默认值。
`tools/replay_evidence_check.py` 已纳入这三个签名，并检查实际解出的参数名。

旧源码 ListReplayFiles 只有 removeObsolete 参数，且该分支会调用 File.Delete；
这不是可直接对当前客户端执行的导入脚本。本轮未把原件或副本放进游戏扫描目录，
未触发枚举/删除行为。ARM workload 也只是把 ABC 推入 files/Replay 后运行既有客户端，
明确要求已登录及资源齐全，不能据此宣称当前离线入口可播放。

旧代码与 ARM 来源：
- https://github.com/ihaiucom/wangzhe.WangZheDllCode/blob/master/Asssembly-CSharp/Assets.Scripts.Framework/GameReplayModule.cs
- https://github.com/ARM-software/workload-automation/blob/master/wa/workloads/honorofkings/__init__.py

**当前路线选择**：ABSTOOL 保留为配套 GameCore/ABS 的验证支线，取得完整包和样本前
不投入未经定义的 ABC→ABS 转换。原客户端方向先追这三个扫描方法的真实调用方，
核对 folderName/fileNameRegex/版本检查与回放 UI 的条件；Recovery 文件继续作为独立线索。
本轮没有成功播放回放，也没有把“官方有播放器”误记为“可播放本项目 ABC”。

## 5.124 当前离线客户端：七个真实方法、版本引用与开局首包（2026-11-02）

本轮继续执行原客户端路线。通过模拟器支持的 `adb root` 取得本地读取权限，
游戏 pid=2297；没有登录、注入、调用游戏内部函数、修改设备游戏文件或删除文件。
ADB daemon 此后保持 root 模式。只读取当前 metadata 和一个 36.8 MiB scudo primary
区域，未全内存扫描、未保存该堆；仅保存 metadata、目标代码和方法身份信息到 git 忽略的
`data/replays/_analysis/client_probe_20261102/replay_methods_live/`。

新增 `tools/live_replay_methods.py`：候选必须同时满足当前 metadata 的名称指针、
token、参数数目、所属类名称指针及 libil2cpp 代码映射。捕获到的真实运行入口
（下列地址均为 process pointer 减本次 libil2cpp base=0x400026200000）：

- ListReplayFiles(3): 0x6659200；ScanReplayFiles(4): 0x6659318；
- GetReplayInfoByFilePath(1): 0x6659504；BeginReplay(2): 0x665a23c；
- CheckReplayVersion(2): 0x665a950；GetBeginLoadMsg(3)/(1): 0x665b07c/0x665b42c。

Scan 的函数指针槽 0xd54bee0、单文件读取槽 0xd54bee8 实际指向上述捕获的函数，
从而独立验证 List→Scan→GetReplayInfo 的间接调用边。Scan 接收调用方的目录与
文件名规则，目录枚举的第三参数固定传 0；函数本身未发现递归调用。removeObsolete
为真时还会进入额外的文件操作 helper，因此本轮只读其代码，不触发枚举/清理。

**实时版本和目录引用**：沿真实代码中的类型/静态字段槽读取，当前 app 比较引用为
`12.1.1`，资源版本引用为 `12.1.1.26`；缓存 Replay 目录为
`/storage/emulated/0/Android/data/com.tencent.tmgp.sgame/files/Replay/`，格式串为
`{0}/Replay/`。这次读取来自同一活动进程，不从 APK versionName 或历史快照推测。
版本 helper 对资源字符串做相等比较，并从 app 版本截取前缀后比较；未启用版本跳过。

**首包读取的实质修正**：

- 当前 metadata 中 System.IO.BinaryReader 的 ReadInt32 虚槽为 15、ReadString 为 22，
  在真实代码中的 vtable 偏移分别为 0x228、0x298，差值同为 7×16。
  GetBeginLoadMsg 的首长度调用使用 0x228，因此是**signed i32 LE**，不是旧公开代码的 i16。
- ABC 常规头（四字符串、英雄/时间/地图、昵称/头像、段位）后还读 13 B：
  `u32 extra`、`i32 guide_level`、`bool guide_related`、`u32 totalFrameNum`；
  extra 的语义暂不命名。随后是负的 i32 长度与 CSPkg 首包；消息 ID 在包头按 BE 读取。
- 原生 GetBeginLoadMsg 对解包对象的 ID 接受 1075(0x433)/8002(0x1f42)。
  这只属于该开局提取路径，不代表其他回放入口都不能处理 ID1051。
- 新增只读 `tools/replay_opening_packet.py`。30 份实际 ABC 均可切出完整首包，
  其中存在长度 65,818 B 的包；由此进一步排除 2 B 长度。截断输入会拒绝。
  22 份首包 ID1075，8 份 ID1051。没有声称其 CSPkg body 或后续帧流已解码。

**候选文件的实际差别**：

- 设备 AutoSave 中的 20261030_215535：版本匹配 .26，但首包 ID1051，
  length offset=84，body=18,656 B，恰好到 18,744 B 文件末尾，没有后续独立帧记录。
  不适合作为完整比赛加载的首选；不能仅由文件大小推断其中全部内容/可播放性。
- 已有 20261101_182452 样本：build5247758/.26，length offset=192，
  body=32,559 B、ID1075，首包到 32,755 B，后面另有 168,559 B。
  它同时符合当前版本引用与开局 ID 条件，是更好的加载链验证候选；它是人机模式，
  不冒充普通 5v5 真值。header totalFrameNum=10063 不作为帧流已验证条数。

首包审计保存在捕获目录 opening_packet_audit.json，未复制样本到游戏扫描目录。
目前完成的是“真实入口绑定 + 目录/版本引用 + 首包边界和 ID 检查”，没有在客户端执行
CSPkg.unpack/BeginReplay，没有启动回放或推进战斗帧。下一步沿正确候选的开局消息
与真实启动调用继续，不能把 Python 的首包检查写成原客户端已经加载成功。

## 5.125 协议默认值解码修正与完整帧记录索引（2026-11-02）

**本节的代码注册表交叉验证优先于5.120及更早的数值msgID结论。**
继续读取同一离线客户端，捕获集 opening_unpack_live 有18条真实方法，
frame_reader_live 扩充至25条，MethodInfo 增加 namespace 指针身份验证。
未登录、未注入、未调用内部函数、未修改设备游戏文件、未删除文件。
SCPKG_MULTGAME_BEGINLOAD 的 unpack/.ctor 未在该单个primary区域命中，
不能把“未命中”解释为函数不存在，也未强制初始化该类型。

### 压缩整数才是本次metadata默认值的正确读取方法

新增 `tools/protocol_selector_map.py`：从真实 CSPkgBody .cctor 完整代码
（起始RVA0xa2562ac，保存0x15000字节）提取 selector2TypeClassId 字典的
w1消息号/w2类号注册对，再与 CSProtocol.CLASS_ID 默认值交叉验证。
默认值使用压缩整数与zigzag符号编码，例如 CLASS_ID3481 的字节是
`9b 32`（压缩无符号6962，再解符号得到3481）。旧的固定4字节读取产生错误
编号及8192/8193等假象，不能归咎于“默认表sentinel不可靠”。

3261条注册的msgID均唯一，3261个CLASS_ID均唯一匹配协议类型：

- 1051 → CLASS_ID3523 → SCPKG_STARTSINGLEGAMERSP。
- 1075 → 3481 → SCPKG_MULTGAME_BEGINLOAD。
- 1077 → SCPKG_MULTGAME_BEGINFIGHT。
- 1082 → 3561 → SCPKG_GAME_OVER_RSP。
- 1126 → 3832 → SCPKG_CMD_ITEMBUY，并非多人开局。
- 1251 → SCPKG_GAMEOVER_MVPSCORE。
- 8002 → 3309 → SCPKG_UGC_BEGINLOAD。
- 21704 → 6687 → SCPKG_TOKEN_GAME_SETTLE_RESULT_NTF。

CSCMD_ID_DEF 按同样方式解码，与当前开局/游戏结束/token结算编号一致。
1082在**当前构建仍对应游戏结束响应**；不能继续沿用“当前编号1140”或
“1082已失效”的说法。token game结算仍不等于普通5v5详细结算。
重新对30份ABC做负i32包边界/BE消息号/版本范围扫描，1082和21704均零候选。
这仅排除该扫描定义下的包，不排除其他构建、嵌套数据或不同封装；样本中当前
.26版本匹配的两份实际上是同一场人机回放的副本，不是两个独立验证局。
原始审计：opening_unpack_live/selector_envelope_audit.json。

### ID1075路径可完整索引帧记录，不能等同战斗模拟成功

当前原生 `LoadMsg` RVA0x6657ac4 构造读取委托，其后 `SLoadDefaultMsg`
位于0x6657bb0：0x6657cfc读取BinaryReader.ReadInt32虚槽0x228；
其身份另从MethodInfo0x73cdaa993888以name/token0x6002b62/12参数/已验证class指针
核实，保存为frame_reader_live/SLoadDefaultMsg_identity.json，并非仅按代码邻接猜名。
0x6657d14比较长度符号并取绝对值；0x6657da0读取对应字节；
0x6657dc4对正/非正长度分支。正长度的非light分支0x665870c将
CLASS_ID0x1167（4455）交给工厂，metadata对应 SCPKG_FRAPBOOT_SINGLE，
其字段为 dwKFrapsNo/wLen/szInfoBuff，与样本结构一致。
负长度分支进入CSPkg解包。UpdateFrame 已捕获真实入口0x665b4c0，
但本轮只读代码，没有让客户端执行回放。

新增 `tools/replay_record_stream.py`，在首包ID1075路径严格解析：

- 每条记录以signed i32 LE长度开头，负数是CSPkg，正数是帧记录。
- 帧记录前6字节为BE u32连续编号和BE u16内容长度；内容长度必须等于
  外层长度减6。编号从1开始逐条递增，任何越界/截断/长度不符/跳号直接报错。
- 当前只支持已实测的1075路径。1051单局路径明确拒绝，不能把其不同封装
  当损坏文件；8002也尚未验证，不宣称支持。

对全部30份样本执行：22份1075文件完整到EOF，包含21个不同SHA256，
每份编号均连续、内部长度均匹配；另外8份1051明确报告路径不支持。
22文件总计215824条帧记录（含重复样本，不作为独立帧总量统计）。
所有成功文件均只有三个负长度包：1075开局、1077开战、1251评分。
跨版本样本中的消息号名称是按本次客户端映射标注，未逐版本验证其body类型。
审计：frame_reader_live/record_stream_audit.json。

版本匹配的20261101_182452人机样本：首包32559字节；开战包17字节；
帧编号1..9900，共9900条；末尾1251包109字节；完整消费201314字节。
header totalFrameNum=10063，与记录数差163，差异语义未解，不强行解释成
缺帧或模拟结果。1251当前类型字段是dwWinMvpObjID/stMvpScoreDetail/
iLoseMvpObjNum/LoseMvpObjList，其body尚未解码，不能宣称已取得MVP分或KDA。

**验证与剩余缺口**：8项定向单元测试通过，覆盖压缩整数各宽度/符号/截断、
消息边界伪阳性、混合记录、截断、帧长度及编号异常、1051路径拒绝。
已解决的是记录容器和顺序索引；帧内szInfoBuff的命令语义、开局嵌套字段、
确定性战斗推进和位置/血量/经济读出仍未解决。下一步应沿这些已定位的真实
unpack与启动链继续，避免回到假缓冲Commit崩溃的盲试。

## 5.126 帧内命令结构解析与真实引擎交接接口（2026-11-02）

本轮新增 `tools/replay_frame_commands.py`，从5.125的完整记录索引继续进入
szInfoBuff。**“结构解析完成”只指条目数量、选择器、已知字段和字节边界；
不等于所有压缩字段已经解义，更不等于战斗状态已经重算。**

### 当前原生调用链的证据

frame_commands_live 捕获29条真实MethodInfo，新增FrameWindow的方法：
onFrapBootInfoSingleNtf RVA0x5ceed48、HandleFraqBootSingle0x5cf047c、
HandleFraqBootInfo0x5cf44fc。原生HandleFraqBootSingle中的槽0xd50bbb8实读
指向0x5cf44fc，与MethodInfo身份一致。它先按帧号管理环形缓冲，再逐帧处理。

HandleFraqBootInfo 从帧对象+0x10取wLen、+0x18取szInfoBuff；非空缓冲时
通过槽0xd6f9138（目标RVA0xa329790）创建CLASS_ID0x1166=4454对象，
当前压缩默认值表唯一匹配 **CSDT_FRAPBOOT_INFO**，字段bNum/astBootInfo。
缓冲经槽0xd6c6788解包；该槽目标0x9f7d0c0实际是**共享TDR缓冲适配器**，
最终调用对象class+0x1a8的虚unpack，不能把此槽命名为CSPkg专属函数。

在0x5cf46d0取接口方法并调用：接口类型来自实读slot0xde73198，即
Assets.Scripts.GameLogic.IGameLogicHelper；接口索引0x35=53，在当前metadata
精确对应 **AdvanceFrameCommands(frameNo, frapInfo)**，token0x60083ab。
metadata还有FrameWindowHelper同名实现token0x6002afe和GameLogicHelper同名
实现token0x6006bcb。当前实例具体落到哪个实现、实现怎样进入GameCore仍待验证。
这已给出真实帧交接接口，但尚未调用它。

### 命令布局与解析结果

szInfoBuff按当前CSDT_FRAPBOOT_INFO解析：u8条目数，逐条u8 BOOTFRAP选择器
与对应body。所有多字节字段按TDR大端；每帧必须恰好读完指定条目数和全部字节。
无法识别的选择器直接拒绝整帧，其已读部分也不计入成功事件，禁止猜长度重同步。
当前实现的主要结构：

- BOOTFRAP1：CC，u16 wObjID + u16 wLen + 原始buffer；buffer内层未解。
- BOOTFRAP2：CS，u16 wObjID + u8 CSSYNC_TYPE_DEF + 对应结构字段。
  当前样本实际出现128目标技能、129方向技能、130位置技能、133买装备、135学技能。
- BOOTFRAP5：AI状态切换；18移动的u16 wMoveInfo；19普攻的u8 bAttack；
  20带目标普攻的u8 bAttack + u16 wObjID。
- CSSYNC位置技能字段为i8槽位、Vector2两个i32、u16技能序号、u32对象ID、
  u8拖动标志；目标技能/方向技能/买装备/学技能等按当前metadata字段次序读取。
  当前观察到的完整条目边界支持这些布局，但未逐个原生unpack交叉执行。

对版本匹配的20261101_182452人机候选：**9900/9900帧结构完整解析**，
无未知选择器、无截断/剩余字节；其中1024帧条目数为零。输出15094条输入事件：
移动10939、普攻2324、带目标普攻686、CC419、目标技能222、方向技能234、
位置技能195、买装备47、学技能27、AI状态切换1。
这些是**输入条目计数**，不是成功施法/购买/升级或伤害次数。

例如frame111的买装备条目含外层wObjID212、wEquipID1511、内层dwObjectID8；
frame977的位置技能含外层wObjID1804、slot1、目标(46500,-32500)。
不把外层对象号猜成英雄ID；不把目标坐标当英雄当前位置，不猜单位、角度缩放或
压缩玩家位域。没有把帧号换算成秒，时间基准仍待验证。

可逐条复核的导出保存在ignored目录：
`data/replays/_analysis/client_probe_20261102/frame_commands_live/frame_inputs.jsonl`，
15094行、2190194字节。每条保留frame、原文件file_offset、条目offset/bytes、
协议类型、解析字段或原始buffer。CLI的`--events-out`仅接受单文件，先完整验证，
再以新建方式写出，已有导出不会覆盖。

跨样本结构验证：22份1075文件中19份命令结构全部到末尾，另3份共有27帧遇到
BOOTFRAP26（当前枚举IN_BATTLE_EFFECT_BUY），明确标记未支持；其余帧均完整。
这些文件含重复且跨版本，结构相容不代表所有构建的字段语义已验证。
8份1051仍由记录索引器明确拒绝，不假装支持。全部审计在
frame_command_audit.json及all_frame_command_audit.json。

### 验证范围与设备状态

15项定向测试通过：新增命令黄金字节、混合条目、带符号目标/方向/对象值、
数量/截断/尾部异常、未知选择器拒绝；包含此前记录流及压缩默认值测试。
移动/普攻的压缩字段与CC buffer仍原样保留；未取得连续位置、血量、经济或KDA。

本轮后半段ADB设备变为offline，重连127.0.0.1:16384被拒绝；原因未确认，
后续解析使用已保存代码，没有宣称继续读取到活动进程。离线库中局部搜索找到
New代码锚点：运行RVA0xa329790对应文件offset0xa348790异或E3，前2160字节
与实捕代码完全一致，到页边界首次失配。因此只确认该局部锚点，绝不外推全局
地址修正；同页preNew磁盘代码仅留作候选，不记为原生实捕unpack。
调用槽、接口与局部锚点证据保存为call_chain.json。

下一处核心工作：绑定AdvanceFrameCommands的实际实现、还原启动上下文；
以及解码移动/普攻压缩位域与CC内层。当前输入时间轴已可导出，原生回放启动和
战斗帧模拟仍未完成。无文件删除、登录、注入或设备游戏文件修改。

### 5.107 【纠错·仅 11/2 5247758】`0x02/0x85` 是 BUYEQUIP，不是金币（2026-11-02）

11/2 两局新回放（build 5247758）跑 `tools/replay_frame_commands.py` 后出现决定性反例：

- 20261102_161129：BUYEQUIP **547** 条；
- 20261102_163751：BUYEQUIP **627** 条；
- 与 `received_20261102_players.csv` 里的 `gold_events` **547/627**、逐玩家计数
  （551=214、1031=99、1799=60、538=31…）**完全一致**。

所以在这两个 11/2 样本里，`0x02/0x85`（sync_type=133）是 **BUYEQUIP**，
不是金币收入；`gold_events/gold_event_total` 是误读字段。`gold_event_total`
很可能是把装备/对象字段按错误布局求和，不能当经济。

同样只在这两个样本里确认：

- `0x02/0x87`（sync_type=135）是 **LEARNSKILL**，不是金币/购买；
- `0x02/0x80` 是 12 字节帧命令，不是 30 秒统计；
- `BUYEQUIP` 的可靠字段是 `equip_id`、`object_id` 和每玩家购买计数；
  `auto_buy` 尾部字节仍可能是布局错位，不能单独依赖；
- `SELLEQUIP`、`PLAYER_MOVE`、`PLAYER_ATTACK`、`USEDIRECTIONALSKILL`、
  `USEPOSITIONSKILL`、`USEOBJECTIVESKILL` 等已能解析。

**影响范围（仅 11/2 5247758）**：

- `received_20261102_players.csv` 的 `gold_events/gold_event_total` 应改名为
  `buy_events` 和“购买字段和”，不能当金币；
- `new_5247758_gold_events.csv` / `new_5247758_report.md` 的 0x85 经济部分
  是购买流水，不是收入；
- 其它 5069040/5230306 报告不能直接套这条纠错：它们有各自 build 的金币通道
  （5069040 的 `0x02 len=5` POV 账本、5230306 的 `02/80` 累计快照），
  必须按 build 分别验证。

**仍然成立**：

- 11/2 回放有**装备购买时序**（BUYEQUIP/SELLEQUIP）和**技能加点**（LEARNSKILL）；
- 用 `pvp_item` 价格表只能算**最终 6 格装备成本**并做严格检查（9/10 满足 `cost < panel`；296 −302g 异常），不是逐笔花费/收入；
- 最终金币/KDA/伤害不在回放；尾部 `scoreTable` 是评分×100，不是金币；
- 11/2 两局都是 **10 真人、0 AI**；5.127 证明 packed move/attack 的高 5 位是 unit=槽位（camp1 8–12、camp2 16–20），不是 4/5/6/8/9/10 的 actor 码。

### 5.108 【R3 纠错】5069040 的“POV 金币账本”也是 BUYEQUIP（2026-11-02）

R1 事件流对主样本 `20260925_105224` 解出 **303 条 BUYEQUIP**；
旧 `player_gold_events.csv` 只有 **286 条**，逐玩家计数一一接近但更少
（442=35/34、338=34/33、1547=33/31…）。这与 R1 的结论一致：
旧解析器把 `0x02/0x85` 当 5 B `sourceType+amount`，实际是 7 B
`equip_id:u16BE + object_id:u32BE + auto byte`，所以少读、错位、漏条。

因此：

- 5069040 的 `player_gold_events.csv`、`player_gold_summary.csv`、
  `player_gold_timeline.csv`、`normal5v5_gold_ledger_5069040.*`、
  `agent_normal5v5_reconciliation.*`、`agent_source6_attribution.*`
  的 source/amount/合计 **不能当金币收入**；
- 其“按玩家事件数”最多只能当 BUYEQUIP 购买计数；
- `0x02/0x85` 在 5069040 和 11/2 都是 BUYEQUIP；5230306 的 `02/80`
  是另一个 build-specific 的累计金币/经验快照（仅 5 条），不是逐事件账本；
- R3 经济结论应改为：**没有可靠的逐笔金币收入**；面板累计金币已含初始 300，
  只能对最终 6 格装备成本做严格检查（`成本 < 面板`，9/10 通过；296 异常），
  或用 OCR/服务器/完整模拟。

这进一步确认：死亡→金币规则成立，但回放没有 killer/victim/金额三元组；
`0x1e` victim 也不是英雄，不能拼出 KDA 或经济。

## 5.127 破解 packed 移动/普攻位域：unit + 有符号方向（2026-11-03）

5.126 留下的"移动/普攻压缩位域"本轮已破解。全部结论由三份样本的 213,032 条
PLAYER_MOVE / PLAYER_ATTACK / PLAYER_ATTACKWITHOBJ 条目交叉验证：
20261101_182452（人机，13,949 条）、20261102_161129（80,270 条）、
20261102_163751（118,813 条）。

### 位布局（TDR 大端，✅ 三样本全量验证）

```text
BOOTFRAP 18 PLAYER_MOVE        u16 wMoveInfo = [unit:5][seq:2][sign:1][mag:8]
BOOTFRAP 19 PLAYER_ATTACK      u8  bAttack   = [unit:5][seq:2][flag:1]
BOOTFRAP 20 PLAYER_ATTACKWITHOBJ  u8 bAttack + u16 wObjID（目标不变）
```

- `mag`（低 8 位）∈ [0, 180]，213,032 条无一越界；>180 视为该样本布局
  不成立，解析器整帧拒绝（`decode_move_info` 抛 ValueError）。
- `sign=1` 时方向 = `-mag`，`sign=0` 时方向 = `+mag`，即有符号输入方向角
  [-180, +180]。约定证据见下。
- `unit`（高 5 位）= 英雄槽位：**unit = 8 + (camp-1)*8 + slot**，
  camp1 → 8..12，camp2 → 16..20。unit 0-7、13-15、21+ 未在任何样本
  出现，归属未解。

### 方向为有符号角的证据（人机 20261101_182452，unit 8 开局段）

帧 78-92 方向连续递减：60, 27, 19, 14, 12, 10, 10, 8, 2，随后帧 89 起
sign 翻转、幅值递增：-4, -9, -14, -16, -18, -20, -20, -20, -22, ...
即 8, 2, **-4, -9, -14** —— 一个连续穿过 0° 的匀速顺时针转身。若解释为
"180+mag"（半圆偏移），序列会在 2 → 184 处跳变；只有 ±mag（符号幅值）
给出连续曲线。

### unit = 英雄槽位的证据链

1. **计数闭合**：两份 5v5 恰好 10 个 unit（8-12、16-20）承担全部移动；
   人机局恰好 2 个 unit（8、9）。
2. **AI 静默**：人机局的 8 个 AI 英雄（entityId 2001-2008）移动/普攻/
   购买/技能全部为 0 条——AI 由引擎确定性模拟，不发输入命令；只有
   2 名真人（娜可露露 entityId 212、大禹 1804，与 CC wObjID 一致）。
3. **同一编码贯穿普攻**：PLAYER_ATTACK/ATTACKWITHOBJ 的 bAttack>>3
   与移动的 unit 集合完全相同（5v5 两局均恰好 {8-12, 16-20}）。
4. **行为画像自洽**：关羽（538，机制依赖持续移动）移动 8,030 次为
   camp1 最高；张良（42）/貂蝉（82）普攻最少；公孙离（227）技能最多。
5. **external 对拍**：received_20261102_players.csv 的 (team, slot,
   entity, hero) 与 unit 映射一一对应。

### 对旧结论的修正

- 5.111/D2 的"actor 码只有 4/5/6/8/9/10"是**高半字节混淆**：
  unit 8-12 的字节落在 0x40-0x67（高半字节 4/5/6），unit 16-20 落在
  0x80-0xA1（高半字节 8/9/10/…）。真正的 actor 字段是高 5 位。
- 此前按 `v>>8` 统计出的"45 个 actor 字节"实为 10 个 unit ×
  seq(0-3) × sign(0/1) 的组合。
- `packed_inputs_20261102.csv` 把 0x403C 读成 "actor_code=4, degree=-60"
  的拆法同样混淆了高半字节；本节布局取代之。

### 仍未解

- `seq`（2 位）语义：部分 unit 的 seq 随条目 +1 循环（0-3），另一些
  unit 恒为 0（如人机 unit 9、5v5 的关羽与 camp2 全部）；触发条件未知，
  仅随事件保留。攻击的 `flag` 位语义同未解。
- 方向角的 0° 基准轴与正方向（顺/逆时针）尚未与地图几何对齐；需要与
  0x82 坐标通道或已知分路走向对拍后才能换算世界方位。
- 仍没有英雄世界坐标：方向角是**输入方向**，不是位置；不能推导轨迹、
  距离或速度。

### 本轮产物

- `tools/replay_frame_commands.py`：`decode_move_info` /
  `decode_attack_byte` / `unit_roster_slot`；PLAYER_MOVE/PLAYER_ATTACK/
  PLAYER_ATTACKWITHOBJ 行内新增 unit/seq/sign/mag/dir_deg（或 flag）
  结构化字段，raw 字段保留；mag>180 整帧拒绝。
- `tools/replay_input_timeline.py`（新）：接 `.abc` 十人块，导出
  unit→entity→英雄 的逐帧输入时间轴 JSON（moves/attacks/buys/
  learnSkill/skills/cc），帧号不换算秒，只读本机导出。
- 导出：`data/replays/_analysis/client_probe_20261102/
  input_timeline_20261101_182452.json`、`input_timeline_20261102_161129.json`、
  `input_timeline_20261102_163751.json`。
- 测试：`tests/test_replay_frame_commands.py` 新增 6 项（方向 golden、
  mag 上限拒绝、unit 映射、混合条目结构化字段）；全套 234 项通过。

### 5.127.1 工作台接入（2026-11-03 同日）

- 服务端 `GET /api/replays/<id>/inputs`（可选 `?unit=N`）：从已存 .abc 按需解码，
  返回十人输入概览（unit/阵营/槽位/英雄名 + 移动/普攻/技能/购买计数 + 活跃帧区间）
  和单英雄事件数组；>4000 点自动按步长采样。不落库、不改导入流程。
- 回放实验室详情页新增「英雄输入时间轴」面板：十人概览表 + 按英雄的方向时间轴
  SVG（蓝线=方向角采样、橙刻度=普攻、蓝块=购买），并注明"输入方向角 · 非世界坐标"。
- 测试：`tests/test_replay_inputs_api.py`（8 项，含合成 1075 记录流夹具
  `inputs_5v5_fixture`）；浏览器验收 `scripts/verify_replay_inputs_page.py`。

### 5.127.2 BOOTFRAP26 观察补充（旧构建，仍未解）

BOOTFRAP26 只出现在旧构建样本（5069040 / 5230306：20261016_194242、
20261027_231329 等 3 份，共 54 帧）。条目为长结构，开头模式固定：
`1a [u16 变化：0x00bc–0x06a5] [u32 2] [u16 0] [u32 0x155a] [u32 0×4] [u32 1] [u32 0] [u16 0]`，
之后常跟多条 CSSYNC（0x02，subtype 0x83=MOVE 等）。0x155a 在两份不同
对局中恒定，更像配置/效果常量而非对象号；u16 分量随时间变化但非单调。
当前枚举名 IN_BATTLE_EFFECT_BUY 来自 5247758 metadata，旧构建的 26 号
是否同名未验证。解析器保持整帧拒绝并如实报墙，不基于猜测形态输出计数。

## 5.128 dir_deg 角度系标定：与方向技能同帧，世界向量 = (cos d, sin d)（2026-11-03）

5.127 遗留的"0° 基准与正方向未与地图对齐"本轮拆掉大半。三条独立证据链
（样本：20261102_161129、20261102_163751）：

### 证据 1 ✅ dir_deg 与 USEDIRECTIONALSKILL.degree 是同一角度系

USEDIRECTIONALSKILL（CSSYNC 129）的 `degree` 字段取值 −17700..17920，
为**百分度**（±177.00°..±179.20°），与 dir_deg 的 ±180 有符号范围同构。
对每条方向技能施放，取同一英雄 ±2 帧内的 PLAYER_MOVE 方向做配对差
Δ = degree/100 − dir_deg：两局 18 名英雄、400+ 配对的 Δ 中位数全部落在
**0 ± 6°**（个别小样本英雄 ±19°，符合"边退边放"的真实操作）。
结论：**输入方向角与客户端方向技能的瞄准角共用同一 0° 与正方向**。
技能瞄准角是屏幕/世界系角度，因此 dir_deg 不再是"未知基准的输入码"，
而是客户端世界角度系的一员。

### 证据 2 ✅ 尾部帧流 0x82 kind=2 = 英雄自身世界坐标

0x82 消息此前只按容器解析（body[0]=kind, x/y=i32BE）。本轮把 kind=2
样本的**相邻位移方向**与该英雄在对应帧区间内的移动航向（按 mag 加权的
circular mean）配对：

- 20261102_163751 entity 1554（camp1，unit 11）：kind 2 → n=43，
  meanΔ = +8.4°，resultant **0.58**；kind 1 → r=0.37；kind 3 → r=0.45(n=15)。
- 20261102_161129 entity 1760（camp2，unit 20）：kind 2 → n=45，
  meanΔ = **−6.2°**，resultant **0.50**；kind 1 → r=0.24。
- 反例：entity 296 kind 3（n=7）r=0.12，样本过少不计数。

位移方向与航向在 **Δ≈0** 下锁定（r≈0.5-0.58 对稀疏采样而言是强信号，
英雄在采样间隔内不会走直线，相关被天然稀释）。因此 **0x82 kind=2 是
英雄自身坐标**；kind 1/3（相机/指针类候选）相关弱于 kind 2。这同时
把 5.115 "0x82 坐标标尺未校准"推进为：kind=2 坐标与输入角度系在同一
世界系中自洽。

### 证据 3 ✅ 位移方向在 (cos d, sin d) 读法下对齐 → 世界 y 轴向下

把 0x82 位移的方位按两种读法与航向对比：y-up 读法 atan2(dy,dx) 的
meanΔ ≈ −101°..−157°（系统性错位），**y-down 读法 atan2(−dy,dx) 的
meanΔ ≈ 0**。即 native 世界轴与屏幕一致：+x 向东，+y 向南（y 向下），
北 = −y。于是：

```text
世界方向向量（native 轴） = (cos dir°, sin dir°)
罗盘方位（0=北，顺时针）   = (90° + dir_deg) mod 360
```

代码落地：`tools/replay_frame_commands.py` 新增 `world_vector()` /
`compass_bearing()`；时间轴导出新增 `positions`（0x82 kind=2 稀疏锚点）。

### 证据 4 ◐ 阵营行走弧与分路结构（支持性）

两局 5V5 开局阶段（≤2400 帧）的移动方向角：camp1 全部落在
[−96°, 0°]，camp2 全部落在 [+92°, +178°]，两弧互为对映（槽位配对的
弧心差 114°–175°，因分路不按槽位对齐而不必等于 180°）。按罗盘换算：
蓝方行走弧 [354°..90°]（北→东），红方 [182°..268°]（南→西），与
"蓝方左下、红方右上"的标准地图及三条分路走向一致；role 对齐
（百里守约 ADC→分路偏东、关羽→偏北、貂蝉 mid≈225°）为支持性证据，
不单独作为证明。

### 仍开放

- `mag`（幅值）与方向的关系在长窗口内呈全周分布、低幅值条目聚在走向
  附近——mag 是"摇杆推角"还是"强度/时长"未定；输出方向时间轴时建议
  同时保留 mag 原值。
- 0x82 kind=1/3 的语义（相机/指针候选）未定；0x82 采样稀疏（每实体
  数十点），**不构成逐帧轨迹**，只作位置锚点。
- 帧号→秒的时间基准仍未验证。

## 5.129 帧号→秒时间基准标定：15 帧/秒（2026-11-03）

5.127/5.128 遗留的"帧号未换算秒"本轮标定完成。

### 同局认定 ✅（十人评分逐一相等）

对 11/2 七页赛后截图样本（`data/screenshots/samples/20261102_1559/`）跑本机
OCR（`scripts/postgame_screenshot.py`），战绩页给出：日期 2026-11-02、
时长 **11:33 = 693s**、比分 27:6、十人评分与英雄：

left 百里守约 10.6 / 关羽 13.1 / 妲己 10.4 / 孙悟空 9.1 / 钟馗 8.4；
right 公孙离 5.9 / 吕布 5.4 / 貂蝉 5.5 / 兰陵王 3.6 / 张良 4.9。

回放 20261102_161129 的 1251 评分表与英雄**完全一致**（1168=8.4 钟馗、
538=13.1 关羽、1613=10.4 妲己、750=9.1 孙悟空、1611=10.6 百里守约；
1031=5.9 公孙离、296=5.4 吕布、551=5.5 貂蝉、1799=3.6 兰陵王、1760=4.9
张良）——截图与回放确证同一局，693s 为对局时长真值（页面时钟取整到秒）。

### 帧率 = 15 帧/秒 ✅

- **主证据**：693 × 15 = **10395**，恰好落在回放流的行为区间内——首次输入
  帧 40（2.7s），最后一条手动购买（flag∈{0,1}）帧 **10409** = 693.9s。对局
  0:00 帧 F0 ∈ [0..14] 时，(10409 − F0)/15 = 692.9..693.9s ✓ 与显示 693 完
  全吻合；胜利后输入锁定，其后帧（10409→10509 = 7s）为胜利动画，流里
  仍有移动/系统购买 tick（flag=210 的 6 帧周期推荐购买，entity 551 全场
  每 6 帧重复 1243，是系统行为非手动）。
- **旁证**：公开技术资料中王者荣耀对局逻辑帧率为 15 帧/秒；三份 5247758
  样本的 header totalFrameNum − 记录流帧数 恒为 163-165（≈11s 入场装载，
  独立于对局时长）；163751 估算时长 (15261−7)/15 ≈ 1016.9s ≈ 16:57（无
  外部真值，待验）；人机 9900 帧 = 660.0s = 11:00.0 整。

### 换算与实现

```text
对局秒 t(frame) ≈ (frame − F0) / 15，F0 ∈ [0..14]，绝对误差 ≤ ±1s
```

- `tools/replay_frame_commands.py`：`FRAME_RATE = 15`、`battle_time()`。
- `tools/replay_input_timeline.py`：导出新增 `timeBase`（fps、battleStart
  区间、首末输入帧、最后手动购买帧、estimatedBattleSeconds ±1s）。
- `GET /api/replays/<id>/inputs`：payload 新增同一 `timeBase`；工作台方向
  时间轴横轴改用对局时间（m:ss，±1s）标注。

### 仍开放

- F0 的逐帧值（0..14 内）未知——需要一场有秒级事件的录像对拍才能锁死；
  对 11:33 这类整秒显示而言 ±1s 已是显示精度极限。
- flag ∈ {0,1,24,90,210} 的购买来源语义未定（210 = 6 帧周期系统 tick，
  entity 551 贯穿全场；24 集中于 163751）。

### 2026-11-10 待办：引擎实测 15.1515 fps 与本节的 15 fps 尚未对上

本节用「最后一条手动购买帧 10409 ≈ 693.9s」把帧率钉在 15，前提是「最后一次
手动购买恰好发生在对局结束」。这个前提没有独立证据，而引擎侧的测量给出的是
另一个数：

**引擎 (帧号, 毫秒) 对（`+0x1664/+0x1668`）**：暂停的 unit dump 上
`unit_钟馗_t0/t1.bin`、`unit_张良_t0/t1.bin` 逐字节读出

```text
frame 6838 @ 449,228 ms  →  frame 6895 @ 452,990 ms
57 帧 / 3,762 ms = 15.1515 fps      （2026-11-10 复现）
```

同一次 dump 拟合 F0 = 31.4（帧 6838 ↔ 449.228 s，449 s = 07:29）。

**尚未验证的一环**：上面测的是**引擎的**帧计数器。回放记录流里的 `sequence`
是否就是同一个计数器，本仓库还没有在同一局上做过对比（§5.133 断言「条目 seq =
帧号」，但没有对拍证据）。如果两者是同一个计数器，本节 15 fps 就偏晚 1%
（700 s 处约 7 s），`tools/reconstruct_trajectories.py` 记的「event_windows
的 15 fps / F0=0 在靠后的检查点上早 45–110 帧」正好是这个量级。

**结论：暂不改产品口径。** 常量统一在 `replay_time.py`：产品用 `FPS = 15`
（本节口径，行为不变），引擎实测值留作 `FPS_ENGINE = 15.1515`，只给原本就用
它的研究工具（`replay_codec/`、`interpolate_state`、`reconstruct_trajectories`）。
`tests/test_replay_time_base.py` 禁止再出现第三份常量。

要结掉这一环，只需一个最小实验：在同一局上取一条回放记录流的 `sequence`，
与引擎 `+0x1664` 在同一时刻的读数对齐，看差 1% 还是相等。在拿到这个对拍之前，
本节保持原样。
- 时长真值仅覆盖 161129 一局；163751 与人机样本为估算。

## 5.130 尾部流 0x85 = BUYEQUIP 镜像；收入账本不存在（2026-11-03）

"0x85 金币事件（source/amount）"这一长期误读本轮被逐字节证伪并修正。

### 字节级证据 ✅

0x85 的 7 字节体重新解析为：

```text
[equip_id:u16BE][pad:u8 ×3][objectId:u8][flag:u8]
```

- 与 BUYEQUIP 帧命令**一一对应**：20261102_161129 的 547 条 0x85 事件与
  547 条 CSSYNC 133 命令帧帧重合（163751 亦 627/627）。
- 旧读法 source:u8 + amount:u32LE 实为 equip_id 的高低字节被拆开：
  `06 A5` = 1701（学识宝石）、`04 57` = 1111（铁剑）、`05 83` = 1411、
  `05 E7` = 1511；"amount 165/87/131" 只是装备 ID 低字节。
- 尾两字节与命令的 object_id / auto 字段逐一相等（(79,1760): obj 51 +
  flag 210，与命令 (1701, 51, 210) 完全一致）。

因此**尾部流没有金币收入事件**：5.97/5.113 的"经济来源全表"（source 4/5/6
= 兵线/野怪/系统）是对装备 ID 高字节的误读；5.107/5.108 的怀疑在本构建
被字节级坐实。"首个兵线收入事件帧号对拍官方兵线时间以锁死 F0"的路线
随之不可用——F0 仍为 [0..14]（±1s，见 5.129）。

### 对面板真值金的交叉核对（开放问题）

用战斗装备表价格（504 件，`agent_equip_prices.csv`，覆盖样本全部购买
547/547）聚合支出与面板总经济对拍**不闭合**：部分英雄 flag∈{0,1} 的
"购买"支出超过面板总经济（如 1168 支出 13785 vs 面板 6540），且全样本
无 SELLEQUIP（0 条）。flag ∈ {0,1,24,90,210} 的语义、装备合成对组件
的扣减、以及面板"总经济"的准确口径未解——从购买流水重建收入账本仍
不可行，5.108 的"只能给区间"结论维持。

### 实现修正

- `replay_parser.py`：`playerEvents.gold` → `playerEvents.buyEcho`
  （equipId/objectId/flag），byEntity 只计次数；blocks 的 goldEvents/
  goldTotal → buyEvents；warning 文案同步。
- `tools/replay_input_timeline.py`：`load_prices()` + `annotate_buys()`
  —购买行扩展为 `[frame, equip_id, object_id, flag, price]`（547/547
  价格覆盖），**不合计支出**；`/inputs` 端点同步。
- 工作台回放详情："回放金币" → "购买 N 次"；指标卡"金币条" → "购买镜像"。
- 测试：`test_replay_parser` 改断言 buyEcho 结构；`test_replay_inputs_api`
  购买行含价格 275。

## 5.131 尾部流 0x01 包装的嵌套 TLV：0x2d 角度采样；0x1e/0x1f 与 KDA 阴性（2026-11-03）

尾部流除了 0x02 包装（0x85/0x87/0x82）外还有 **0x01 包装**：
`01 [entity:u16BE] [00] [len:u8] [body]`。按 len 全量走查
（20261102_161129 + 20261102_163751）：

### 0x2d（3B）＝角度采样 ✅ 结构 / ◐ 语义

body = `2d [b1] [b2]`，u16BE = (b1<<8)|b2 的值域**恰好 0–359**（三个实体
的 b1=1 子列最大值都是 103 → 359）。按变化触发、成簇出现；实体覆盖为
**子集**：161129 仅录制者（1611）；163751 为 云缨(679, 4784 条) + 录制者
(1367, 1583) + 钟馗(1279, 52)，窗口大量重叠（非互斥的观战镜头窗口）。

与 PLAYER_MOVE 方向角配对（±1 帧，mag>30）：

- 云缨：Δ = angle − dir 的圆均值 **≈182–189°，r 随时间升到 0.86**，
  各时间桶稳定 → **angle ≈ (dir_deg + 180) mod 360**。
- 录制者两位（1611/1367）：Δ ≈ 188–215°，r 0.22–0.68，直方图仍以 180
  为峰并带 135° 肩。
- 910+ 个样本出现在无移动输入的时刻 → 是"含站立瞄准的摇杆角度"超集。

精确语义（英雄朝向 / 瞄准角 / 反向摇杆）未定；与 §5.128 的标定一致使用
`(angle − 180) % 360 − 90` 类换算前需逐实体验证。落地：
`extract_wrapper_tlvs()` 把 0x2d 作为 `angleSamples: [frame, deg]` 接入
时间轴导出与 `/inputs` 端点。

### 0x1e/0x1f ＝ 与 KDA 阴性 ✅（否定）

0x1e（19B，`1e [victim小id] [zero×13] [a][b][c]`）与 0x1f（28B）按实体
计数与面板 kills/deaths/assists **均不对应**（孙悟空 0x1e=3 vs K5/D1；
妲己 2 vs K6/D1；其余全 0）。5.115 的"victim 小 id 不可映射到英雄"结论
维持，事件语义仍未解。原始字节按 `stateTlv: [frame, len, hex]` 留档。

### 其他包装内容（结构观察，未定）

- len=17：`2c [02] …`，i16 对落在世界坐标量级（如 31488/30545/21454，
  末尾 u32 序号递增）——疑似带坐标的目标事件（5.106.1 的 0x2c "目标"）。
- len=14：`01 [x:i32BE] [0] [y:i16BE] [7f]`，坐标量级 ±50000，每实体
  24-60 条——疑似相机/位置关键帧。
- len=2：`03 00` / `14 02` / `25 01` 等 2 字节 mini-TLV——与 BOOTFRAP1
  (CC) 的 buffer 内容同构，CC 之谜部分解开：CC 缓冲就是这些控制 TLV。

落地：`tools/replay_input_timeline.py` 的 `stateTlv`/`angleSamples`；
测试 `test_replay_inputs_api` 断言 fixture（无 0x01 包装）返回空。

## 5.132 方向积分轨迹实验：阴性结果 + 工作台估算图层（2026-11-03）

确定性战斗重算前的粗粒度尝试：把 PLAYER_MOVE 方向角按已标定的世界向量
(cos d, sin d) 积分成位移形状。

### 阴性结果 ✅（有数据支撑的否定）

把积分路径与 0x82 kind=2 真实位置锚点做**平移拟合**（最乐观的情形，
只允许一个整体偏移）：

- 20261102_163751 unit 11（王昭君，11897 条移动，56 个锚点）：
  单位步进残差 mean ≈ 21,953 / median 16,917 / max 55,480（地图 ±50,000）。
- 20261102_161129 unit 20（张良，6014 条移动，47 个锚点）：
  mean ≈ 29,292 / max 64,885。
- 用 mag 作为步长（mag、mag/2）残差**更差**（68k-247k）→ mag 不是位移
  步长。

原因：移速未知且随装备/增益/英雄变化；死亡、被控、攻击硬直与移动在
输入流里不可分；方向标定的 ±几度误差随积分累积。**方向积分不能产生
位置**——任何把该路径当作轨迹展示的做法都是误导。

### 工作台估算图层（诚实标注）

仍按验收方向交付了图层，但以"形状"而非"轨迹"呈现：

- `tools/replay_input_timeline.py`：`integrate_path()`（单位步进，≤4000
  点采样）→ 导出 `pathEstimate` + `pathSchema` 明示"仅示意转向历史，
  绝非位置"。
- `GET /api/replays/<id>/inputs?unit=N`：`hero.pathEstimate` + 
  `pathNote` + `positionAnchors`（该英雄 0x82 kind=2 真实坐标锚点）。
- 工作台「位移形状（估算）」双面板：左=方向积分形状（蓝线+起点），
  右=真实锚点折线（绿，0x82 世界坐标稀疏点）——两者坐标空间独立，
  并排对照而非叠加。
- 引擎侧真值轨迹的唯一路径仍是绑定 AdvanceFrameCommands 做帧模拟
  （需设备/反汇编，本轮未推进）。

## 5.133 ID1051 单局路线容器解码（2026-11-03）

设备路线（MuMu/ADB）本轮不可用：本机无 MuMu 安装、连接 127.0.0.1:16384
被拒绝，AdvanceFrameCommands 绑定仍需设备/反汇编，留待设备恢复。按计划
转 1051 单局路径，**8 份唯一样本全部容器级走通 EOF**。

### 封装结构 ✅（8/8 样本，13 份含副本）

1051 开包 = 与 1075 同构的 CSPkg（msg 1051 = SCPKG_STARTSINGLEGAMERSP，
body 16.7k-18.6k）。其后的记录：

```text
[i32 len][u32 seq/frame][payload = len 字节]
```

- **seq = 对局帧号**：帧内多条目时 seq 重复；各样本 max(seq) 与头部
  totalFrameNum 吻合（20260522: 5075/5075、20251202: 1761/1761、
  20260429: 488/488）或略小（20261028: 2477/2695 —— 录制早于对局结束）。
- 负 len 仅出现在开包；20261030_215535 开包后 **0 条记录**（有帧数头、
  无条目，未录制完整内容）。
- 条目长度分布以 9 字节为主（8/9/11/12/13/18/22/28/36）；条目内容
  `01 00 | 02 TT VV | <4 字节构建常量>`（4867/3625 随构建不同），TT/VV
  与 1075 流的 CC 缓冲 TLV 同族（23 01 / 14 02 / 25 01 / 1c 00 / 85 01…）
  ——1051 条目与 1075 帧命令是同一事件层的两种封装。
- 20261028 两份（build 4989537）与 2026 版样本同构；本轮未再按构建分叉。

### 实现

- `tools/replay_record_stream.py`：`iter_records` 支持 ID1051（route 判别、
  开包 CS + entry 记录、seq 单调校验）；`audit()` 新增 route/entry_records/
  last_sequence 与"容器索引、旧构建条目语义未解码"限制声明。
- `tools/replay_frame_commands.py`：`hero_inputs` 对 1051 返回
  `unsupported-route`（防误读为空数据）；`audit_commands` 带 route。
- 工作台：`/inputs` 与回放页对 1051 如实提示"容器已索引、命令语义未解码"。
- 测试：`single_game_1051_fixture` + 4 项新测试（EOF 索引/seq 单调/截断
  拒绝/路线防误读）。

### 仍开放

- 1051 条目级语义（旧构建 BOOTFRAP/CSSYNC 选择器字典，见 5.93 双 build
  字典）未解码——容器覆盖已达成，命令层留待后续。
- AdvanceFrameCommands 绑定需设备恢复（MuMu 不在本机）。

## 5.134 ID1051 条目级解码：0x02 通道事件族 + CC 缓冲（2026-11-03）

13 份单局样本（8 份唯一，build 3292376/3529557、4026096/4079362-4322850、
4989537/5230306-5247758）的 40,522 条条目**全量解码到已知形状，零未知**。

### 条目结构 ✅

```text
payload = [message][const:u32BE]     ← const 为每文件/每构建恒定值
message = 01 00 <cc-buffer>          ← CC/TLV 族（obj 0x0100，与 1075 BOOTFRAP1 同构）
        | 02 <subtype> <data>        ← 0x02 通道事件（docs 5.93 字典同族）
```

### 0x02 通道子类型（与 5.93 字典精确同族）✅

| subtype | 语义（5.93） | 本层 len | 全语料条数 |
|---|---|---:|---:|
| 0x80 | 帧命令（12B 体） | 14 | 112 |
| 0x81 | USEDIRECTIONALSKILL | 24 | 230 |
| 0x82 | 瞄准/攻击 | 18 | 12 |
| 0x83 | 未解（最大量） | 5 | 17,182 |
| 0x84 | 击杀通知 | 7 | 4,372 |
| 0x85 | BUYEQUIP | 9 | 58 |
| 0x86 | 稀有 | 4 | 4 |
| 0x87 | 候选经验/技能 | 9 | 76 |

0x80 的 12B 体与 5.93 "0x80 12B 体" 精确一致；0x84 体 = `[victim:u8] +
00×4`（victim 为小 unit id，与 5.101b 一致）；0x83 体 = `[id:u8]`+
`00 00`，id 值域与英雄/单位数同量级，语义未解。

### tag 01/00 CC 缓冲 ✅

len 5/8/9/29/32/33 五档：`01 00 <buffer>`，buffer 为 1-29 字节 TLV 链，
值域与 1075 流 CC 缓冲同族（23 01 ×8,986、03 00 ×105、85 01、14 02、
25 01、1c 00、2b 00、73 02、78 01、8c 01…）。5.131 的"CC = 控制 TLV"
结论在旧构建同样成立。

### 实现

- `tools/replay_record_stream.py`：`EVENT_SUBTYPES` 字典 + 
  `decode_1051_entry()`（tag 分派、const 剥离、未知形状如实报 unknown）；
  `iter_records` 的 entry 记录携带 `decoded`；`audit()` 新增 
  `entry_types` 直方图与"entry-shape indexing"限制声明。
- 测试：fixture 覆盖 cc/kill_notice/state_sample 三形状 + 类型直方图断言。

### 仍开放

- 02/83（17,182 条，最大量）与 CC buffer 各 TLV 的逐字段语义未解。
- 02/84 的 victim 小 id 到英雄实体的映射仍按 5.115 不可用处理。
- 事件层时间戳：条目 seq = 帧号（§5.133），对局秒按 5.129 换算。

## 5.135 ID1051 两大语义块解码：02/83 = 朝向角；CC = 键值状态广播（2026-11-03）

### 02/83 = POV 英雄朝向角采样 ✅

体（剥掉每文件常量后）= `02 83 [angle:i16BE 有符号] [index:u8]`：

- **全语料 17,182 条的 angle 值域恰好 [−180, +180]**（20260522: −23/162/
  −25/42…；20260401: −152,−150,−147,−149,−151,−155）——有符号角度解释
  唯一自洽；HP/经验等候选不满足"逐样本 ±2 连续变化"的形态
  （20260429: 124, −51, −53, −55, −57, −59 = 匀速转身 2°/样本）。
- `index` = 采样滚动计数（mod 256；20260401 从 0 起；20260429 有跳段）。
- 与 §5.93 的 0x2d（3B 朝向，POV 专属）同族：单局回放只有一名本地玩家，
  与"0x2d 只在主样本出现"的行为一致。换算对局秒用 §5.129（seq 即帧号）。

### CC buffer = 逐帧键值状态广播 ✅（结构）/ ○（键语义）

`01 00` 后的缓冲按 `02 [key:u8] [val:u8]` 链解码（20260522 全部 3,103 条
可解析）：

- 帧 1-2：**初始态突发**——8+ 个键一次广播（14=02、25=01、1c=00、
  85=01、2b=00、73=02、8c=01、78=01，两代构建一致）。
- 帧 3 起：每帧常量 (23, 01)（15,953 条）——一个整场恒真的逐英雄 bool
  （§5.93 的 0x23"逐英雄 bool"同族）；(03, value) 165 条对应 §5.93 的
  0x03"ready/队伍状态"。
- len-31 大缓冲（538 条 @ 同帧）：`1e 27 …` = 0x1e 伤害表族的批量广播。

落地：`decode_1051_entry` 输出 `states`（键值广播）与 02/83 的
`angle_deg`/`index`；EVENT_SUBTYPES 0x83 更名 `facing_angle`。

### 仍开放

- 各状态键（14/25/1c/85/2b/73/8c/78）的具体含义仅有 §5.93 的家族名提示。
- 朝向角的实体归属（单局 = 本地玩家）与 5247758 的 0x2d 通道未做跨构建
  对拍（两路线无同局样本）。

## 5.136 ID1051 事件族逐字段解码：技能加点 / 购买镜像 / 瞄准坐标（2026-11-03）

在 §5.134 的结构分派上补齐三个子类型的逐字段语义，并给出一个阴性结论。

### 02/87 = 技能加点时间轴 ✅

data = `[00 00][actor:u16BE][skill:u8][levelIndex:u8][00]`。20260522 的
actor 8（POV 英雄）15 条加点序列**严格单调自洽**：

```text
seq 103: skill4 L0 → 108: skill2 L0 → 113: skill1 L0 → 116: skill1 L1
seq 1648: skill2 L1 → 2717: skill4 L1 → 2761: skill4 L2 → 2767: skill2 L2
seq 2770: skill2 L3 → 2772: skill2 L4 → 2775: skill1 L2 → 2777: skill1 L3
seq 2780: skill2 L5 → 2785: skill1 L4 → 2788: skill1 L5
```

（skill 4 = 召唤师/初始技能在开局即 L0；对局 5:38 内 skill1/2 到 L5。）
actor 7 另有 4 条（第二实体）。字段布局与 5247758 尾部流 0x87 的
actorId/skill/levelIndex 一致——跨路线同构。

### 02/85 = 购买镜像 ✅（与 §5.130 逐字节同构）

data = `[equip_id:u16BE][pad:u8×2][object_id:u8][flag:u8]`：`06 a5 00 00
08 00` = equip 1701（学识宝石）/ obj 8 / flag 0。全语料 58 条、21 件装备。
与 5247758 尾部流 0x85 的修正读法完全相同。

### 02/82 = 瞄准/攻击位置（含世界坐标）✅ 结构 / ◐ 语义

data（16B）= `03 00 00 [x:i16BE][mid:i16BE][y:i16BE][counter:u16BE]
[00 00 00 00][01]`：12/12 条的 (x, y) 都在 ±55,000 世界坐标量级
（如 −16676/−29830 → 7671/8152），counter 递增（7,9,11,16,18,22,4,8,…
——多消息共享计数）。5.93 的"瞄准/攻击"语义 + 世界坐标 = 攻击/瞄准
目标位置候选；mid 字段（−1/0）语义未定。

### 02/84 = 双阵营成对通知 ✅（结构）/ victim→英雄映射阴性 ✅

四份样本的 victim 字节都只有 {0,1,2,3,4}：0:1 计数比 1.04–1.17（近对
称），且**每帧严格成对**（先 1 后 0，64 组同帧对）——"victim 小 id →
英雄实体"映射被否定（英雄应有 ~10 个稳定 id 且不成对）；阵营字节假设
（0=蓝 1=红 2/3/4=野区）为 ○ 假设。5.115 的不可映射结论延伸到本层。

### 朝向缺口的阴性补充

02/83 朝向序列的 >150 帧缺口（2 处）内部**无击杀通知**，且 index 在缺
口两侧连续计数——缺口 = 朝向未变的直线行走/静止，不是死亡窗口；死亡
时刻无法从朝向通道定位。

### 实现

- `decode_1051_entry`：0x87 输出 actor/skill/level_index；0x85 输出
  equip_id/object_id/flag；0x82 输出 x/y/counter。EVENT_SUBTYPES 更名
  exp_skill → skill_levelup、aim_attack → aim_position。
- 测试：fixture 覆盖 skill_levelup/buy_equip 字段断言。

## 5.137 02/80 帧命令体 + ID1051 工作台时间轴接入（2026-11-03）

### 02/80 的 12B 体 ✅（与 §5.111 hero-specific action 同构）

data（12B）= `[cmdType:u16LE][value:u16LE][actor:u16LE][cmdSeq:u32LE][flag:u16LE]`。
全语料 112 条：cmdType ∈ {1:70, 2:20, 3:4, 5:17, 7:1}（§5.111 的
hero-specific 集合 {1,2,3,5,6,7,9} 之内）；actor ∈ {7, 8, 9, 12}（8 为
POV，与 02/87 的 actor 一致）；cmdSeq>>8 为稀疏递增计数（1–91）。
cmdType 的逐类型语义维持 §5.111 的"hero-specific action id，非全局枚举"。

### ID1051 工作台时间轴接入 ✅

- `tools/replay_input_timeline.py`：新增 `single_game_timeline()`——
  1051 文件导出 `skillLevelups`（[帧, actor, skill, levelIndex]）、
  `buys`（[帧, equip, rest, price]，价格按战斗装备表）、`facingAngles`
  （[帧, 角度, index]）、`killNotices`（[帧, 阵营?]）、`frameCommands`、
  `timeBase`（15fps ±1s）；`timeline()` 对 1051 自动改走此路线。
- `GET /api/replays/<id>/inputs`：1051 记录在 `singleGame` 键下返回同结构。
- 工作台回放详情：1051 记录渲染「单局时间轴（ID1051）」——技能加点表 +
  购买流水表（对局时间 m:ss，±1s），并标注 actor→英雄映射未解。

### 02/85 字段的构建差异（诚实降级）

rest（equip 之后的 5 字节）内 POV object 字节（0x08）的位置随构建在
rest[2]/rest[3] 之间变化——`decode_1051_entry` 只保留 equip_id + rest
原始十六进制，不再声称 object_id/flag 的固定位置。

## 5.138 动作计数器共享 + cmdType 亲和性阴性 + 0x2c 字段墙（2026-11-03）

### 计数器 = POV 客户端动作/状态包序号（mod 256）✅

02/80（cmdSeq>>8）、02/82（counter）、02/83（index）的递增计数在每份
样本内**零碰撞**（8 份全查；每样本恰一个 cmd/aim actor）：20260401_234221
的合并计数流中 cmd1 占 {1,3,8,…}、aim 占 {7,9,11,…}、facing 采样覆盖
0–255 全域并按 mod 256 循环（同一 index 值在 374/561/1787 三轮复现）。
结论：三者共享"POV 客户端动作/状态包序号"；facing 在角度变化时随包
发出，cmd/aim 占据互不冲突的序号位。跨样本每样本恰一个 cmd/aim actor
（8/12/9/7），与单局本地玩家一致。

### cmdType 亲和性阴性 ✅

20260522 的 34 条 02/80（cmdType 1×31 / 5×2 / 7×1，全 actor 8）与
±5 帧内的最近事件对拍：cmd1 → kill 6 / facing 突变 3 / 无 22；cmd5/7
无亲和。cmdSeq 计数有跳段（3,6,7,10,11,…）——计数推进多于已记录条目，
即存在未被 02/80 记录的动作。cmdType 逐类型语义维持 §5.111 的
"hero-specific action id"结论，本轮无新的正向证据。

### 0x2c（17B）字段边界墙 ✅（诚实记录）

20261102_161129 尾流的 84 条 0x2c（`2c 02 + 15B`）包含落在世界坐标
量级的 i32BE 窗口（31488/30545/−44082 等），但**任何 4 字节对齐都不能
同时闭合**：i32BE@stride4 的第 2/3 字段越界；i24BE@stride4 给出
(123, 119, −44082, 1) 混合量纲。精确字段边界未定——对 0x2c 的坐标/
目标语义（5.106.1）保持"结构观察、字段未解"。

### 实现

无代码变更（计数器字段此前已在 decoded 中暴露：cmd_seq/counter/index）；
本轮为证据链与阴性结论记录。

## 5.139 CC 状态键语义 + aim→cmd 交错 + 朝向图接入（2026-11-03）

### CC 初始态突发 = 构建配置指纹 ✅

帧 2 的初始态突发（7 份样本）只有 **3 种取值集合**，且差异与构建对应：

- key **14** 跟随 app 构建：4989537 → 3，4026096 → 2；
- key **73** 跟随资源构建：4079362 → 0，4223651/4322850/5230306 → 2；
- 其余键（1c=0、25=1、2b=0、78=1、85=1、8c=1）跨样本恒定。

即初始突发 = **游戏/模式静态配置广播**，可作构建指纹；不是对局内状态。

### key 03 与 key 23 ✅（行为）

- key **23**：帧 3 起每帧常量 01（15,953 条）——整场恒真的逐英雄 bool。
- key **03**：事件驱动、值恒 0（20260522 的 31 条散布在帧 1140-1937+，
  20260429 仅 1 条 @134）——触发条件未解（候选：死亡/回城/中立事件）。

### 02/80 cmdType 与 aim 交错 ◐（单样本）

20260401_234221（唯一含 02/82 的样本）的合并计数流：**aim → cmd1 计数
紧邻**（(7,8)、(16,17)、(18,19) 三对，counter 相邻而帧差 165-218）——
counter = 英雄请求 id（移动请求消耗计数但不产生 02/82/02/80 记录），
aim（02/82 目标位置）→ cmd1（执行确认）为候选施法/攻击模式。单样本
证据，标注 ◐。cmdType 逐类型语义仍开放。

### 朝向图接入工作台 ✅

单局时间轴（ID1051）面板新增 POV 英雄朝向角时间轴 SVG（±180° 全程
曲线，对局时间轴 ±1s）。

### 仍开放

- 状态键 14/25/1c/2b/78/8c/73 的逐键含义（仅构建指纹与家族名提示）。
- key 03 的触发条件；cmdType 逐类型语义；0x2c 字段边界（5.138）。

## 5.140 CC 状态键收敛 + 0x1e/0x1f 字节结构（2026-11-03）

### CC 逐英雄键值动态（20261102_161129，5247758 尾流）✅

CC（BOOTFRAP1，obj = 英雄实体）的逐英雄键值时间线：

- **raw03**（`03 00`，每英雄每帧）：全部 10 英雄、值恒 0、零变化、
  覆盖各自全程——逐帧状态心跳。
- **初始突发键**（14/1c/25/2b/73/78/85/8c）：每英雄恰一次（帧 3-4），
  值恒定——per-hero 配置推送（与 §5.139 的构建指纹一致）。
- **raw23**（`23 VV`，2 字节）：**只有 camp1 英雄出现**——161129 的
  翻转者 = 钟馗(1168, 16 条/15 翻转)、百里守约(1611, 2 条)、妲己
  (1613, 2 条)；163751 的翻转者 = 云缨(40)、亚瑟(56)、百里守约(14)、
  王昭君(6)——**8/8 全部为 camp1（录制者己方队伍）**。值 ∈ {0,1}，
  短 ON 窗口（妲己 3 帧、守约 8 帧、王昭君 3 段 1.4-5.7s）与高频翻转
  （亚瑟 55 次）并存。客户端只为自己队伍的英雄广播该 bool；语义候选
  （瞄准/语音/标记…）均未验证，○ 级。

### 0x1e（19B）字节结构 ✅ / 语义未解

`[1e][unit:u8][zero×13][A:u8][B:u8][C:u8][D:u8]`：[1] ∈ {2,3,4}（小
unit id）；[2..14] 全零；[15]=0、[18]=1 恒定；B ∈ {0,1,3}；C ∈ 68-249。
6 条样本中 2 对相隔 2 帧的同 unit 事件（C 不同：106/249、119/68）。
语义（候选：伤害表行/装备主动/特殊状态）未解。

### 0x1f（28B）字节结构 ✅ / 语义未解

`[1f][sub:u8][obj:u32BE][0][负数:i32BE][0][0][0][b:u8][0×6]`：
20261102_161129 两条——sub=1/obj=8/−1 与 sub=243/obj=22/−5（[21] = 
0/1）。sub、obj、负数 ic 的语义未解；条数稀疏（全语料个位数）。

### 共现矩阵收敛 ✅

CC 状态键的共现结构：初始键只在帧 2-4 突发时共同出现；03 为全程独立
通道；23 为 camp1 专属独立通道；二者不与初始键共现。键之间无额外
共现模式可挖——逐键语义需要外部真值（面板/录屏 OCR）或客户端反汇编。

### 实现

无代码变更；CC 动态与 0x1e/0x1f 字节图留档于本节。

## 5.141 0x2c 字段边界阴性 + 设备恢复指引（2026-11-03）

### 0x2c 对齐检验退化 ✅（诚实记墙）

84 条 0x2c（17B）的系统化对齐检验：对全部 (x_off, y_off) 组合按
(i16BE 有符号/无符号) 读法打分——地图界约束（±55,000）下 67/66 候选
全部通过（i16 值域天然在界内），移动速度过滤在稀疏消息（同实体相邻
消息间隔数百帧）下无判别力。**84 条消息不足以唯一确定字段边界**；
0x2c 的坐标/目标语义（5.106.1）维持"结构观察、字段未解"，需要设备侧
真值或更多同构样本。

### 设备恢复指引 ✅

`docs/device_setup.md`（新增）：MuMu 12 安装、ADB 连接校验、库文件
md5 校准（不一致则 §5.126 RVA 失效需重跑类清单）、只读观测点表
（LoadMsg 0x6657bb0 / HandleFraqBootSingle 0x5cf047c / 共享 TDR 适配器
0xa329790 / AdvanceFrameCommands 接口索引 53）、绑定判别实验（同帧
seek 重播的 frapInfo 确定性比较）与成功判据（帧 N 输入可独立预测帧
N+1 命令列表，与 replay_frame_commands 解码对拍）。安装与登录为
用户侧操作；恢复后沿 §5.126 调用链继续。

## 5.142 CC 初始态逐英雄解码：打野签名 + 构建指纹结论修正（2026-11-03）

把帧 ≤10 的 per-hero CC 初始推送接入 `timeline()` 导出
（`initialStates`），随后发现 §5.139 的"构建指纹"结论需要修正。

### 打野签名 ✅（两局 2/2 经购买对拍验证）

1075 流的 per-hero 初始推送只出现在**己方（camp1）英雄**上（camp2 全
无；163751 的墨子缺失为个别异常）。其中：

- **8c = 2 且 85 = 1 ⟺ 打野英雄**：161129 的孙悟空（8c=2/85=1/2b=1/
  73=0）与 163751 的云缨（8c=2/85=1/73=2）都以**狩猎宽刃（1511）为首购**
  ——两局独立对拍 2/2；非打野者（钟馗/妲己/百里守约/亚瑟/王昭君）全部
  8c=1/85=0。8c 候选 = 召唤师技能类别（2 = 惩击，1 = 其他如闪现），
  85 = 打野相关标记。
- 其余键（14/2b/73）逐英雄变化、语义未解。

### §5.139 构建指纹结论修正 ✅（自我纠错）

§5.139 曾依据跨样本比较把 key 14/73 的差异归为"构建指纹"。163751 的
**同局内** per-hero 数据显示 14 ∈ {0,1,2}、73 ∈ {0,1,2} 按英雄变化
（亚瑟 14=0/73=1，云缨 14=1/73=2，王昭君 14=2/73=0，守约 14=2/73=1）
——构建间差异被同局英雄间差异混杂，"构建指纹"解释**撤回**；14/73 为
per-hero 配置（候选：分路/铭文/召唤师相关），语义开放。

### 其他观察

- camp2 英雄偶有单条 `03 00` 心跳推送（163751 的赵云/安琪拉），无初始
  突发——己方队伍广播规则在个别英雄上不完整（墨子/关羽缺突发，未解）。
- `timeline()` 导出的 `initialStates` 按 hero 附带（1075 路线）；
  `single_game_timeline` 的 `initialStates` 按帧留存（1051 路线）。

### 仍开放

- 8c 的精确取值表（是否为召唤师技能 id 全表）；14/2b/73/1c/25/78 逐键
  语义；关羽/墨子缺突发原因；确定性战斗重算（设备路线仍待用户恢复）。

## 5.143 cmdType 对拍阴性 + 购买口径 + 14/2b/73 角色对拍阴性（2026-11-03）

### 02/80 cmdType ≠ 技能加点/施法 ✅（阴性）

20260522 的 34 条 02/80 与 15 条 02/87 加点帧对拍：±15 帧内 **0/34**、
±45 帧 4/34、±150 帧 6/34——cmdType 与加点无亲和（加点为客户端本地
分配，本就不走英雄命令通道，符合预期）。02/80 的 cmdSeq>>8 全部落在
§5.138 的共享动作计数器空间（3,6,7,10,11,…,91），且 cmd1 呈 **2-3 帧
成对/簇状**（2046/2048/2051/2053 四连、2824/2827/2830 三连等）——
候选"多段命令"（施法序列/取消+重发），逐类型语义仍开放。

### 购买口径 ✅（既有数据集复核）

`20261102_build_cost_vs_panel.csv`（此前已生成）的持有成本 vs 面板
累计经济：关羽/貂蝉/孙悟空的 panel−held = +113/+158/+1332（收入覆盖
持有成本 ✓），吕布 −302（面板 5828 < 持有 6130，其 4 格中 3 格为图标
候选中置信——误识别候选）。结论：flag ∈ {0,1} 的购买口径在持有成本
层面大致闭合（个别英雄受识别误差影响）；flag ∈ {24,90,210} 的周期性
条目（如貂蝉 1243 云灵木 6 帧周期）不是真实购买——**从购买流水重建
收入账本仍不可行**（§5.130 结论维持），但"flag∈{0,1} ≈ 手动购买、
其余 = 系统 tick"的口径可用于过滤。

### 14/2b/73 角色对拍阴性 ✅

163751 逐英雄初始键（亚瑟 14=0/2b=1/73=1；云缨 14=1/2b=0/73=2；
王昭君 14=2/2b=0/73=0；守约 14=2/2b=0/73=1）与 161129（孙悟空
14=2/2b=1/73=0；钟馗/妲己/守约 14=2/2b=0/73=1）对拍：打野者两局
73 ∈ {2,0} 不一致、14 ∈ {1,2} 不一致；2b=1 仅孙悟空/亚瑟（两战士）
为弱信号。**14/2b/73 与分路/角色无可收敛映射**，语义仍开放。

### 实现

无代码变更（字段此前已暴露）；本轮为对拍证据与阴性结论记录。

## 5.144 flag 语义定案 + key 03 触发阴性（2026-11-03）

### BUYEQUIP flag（auto 字节）语义 ✅

20261102_161129 的 547 条 BUYEQUIP 按flag 分层：

| flag | 条数 | 买家 | 装备 | 间隔形态 | 结论 |
|---|---:|---|---|---|---|
| 0 | 100 | 8 人（23/25/26/21/1/2/1/1） | 1111/1311/1211/1411 组件散件 | 不规则 | **手动购买账本** |
| 1 | 0 | — | — | — | （人机局 AI 自动购买，样本内未现） |
| 90 | 1 | 1799 | 1311 | 单发 | 未解 |
| 210 | 446 | 6 人 | 1243/1211/1311/1317（随时间变化） | **237 个恰好 6 帧** | **周期系统流（推荐/tick），非购买** |

- flag-0 的人均 ~10 次、全组件散件、不规则间隔 = 典型手动购买行为 ✓；
  人均购买账本（钟馗 23 / 妲己 25 / 守约 26 / 孙悟空 21 …）取代 §5.130
  时代被 tick 污染的 per-player 计数（551=214 等为 tick）。
- flag-210 的 6 帧精确周期 + 装备随推荐路径变化 + 多买家 = 客户端推荐/
  系统 tick 流；**从购买流水重建收入账本不可行的根因**即此类 tick 混入。
- 20260401（1051）的 02/85 rest 尾字节同样分层（0 与周期形态）。

### key 03 触发阴性 ✅

20260522 的 31 条 key 03（值恒 0）：±10 帧内有击杀通知的 6 条（基率
~9，无亲和）；落在朝向静默窗（>60 帧，9 个）内的 9 条（覆盖不足）。
触发条件仍开放，需设备侧真值。

### 实现

无代码变更；`single_game_timeline`/timeline 导出的购买行建议消费方按
flag 过滤（1075 路线 flag∈{0,1}，1051 路线按 rest 尾字节分层）。

## 5.145 02/82 瞄准坐标修正：x/y 为 i32BE（2026-11-03）

字节级复核发现 §5.136 的 02/82 坐标读法有符号损坏：data 实为
`[03][x:i32BE][y:i32BE][counter:u16BE]…`——此前读作"mid"的 i16 字段
（ffff/0000）就是 **y 的高 16 位符号扩展**（6/6 与 y 符号一致）。

修正后 20260401_234221 的 6 条瞄准位置：
(48860, −29830)、(46996, −17816)、(39845, −15761)、(5922, 5665)、
(7671, 8152)、(132, −14697)——全部在 ±55,000 世界坐标内，且前三点
沿 x 递减（从红方区域向中路移动的轨迹形态）。

`decode_1051_entry` 已改为 x = i32BE(data[1:5])、y = i32BE(data[5:9])；
此前基于 i16 低半段的坐标值作废。0x2c（17B）的字段边界墙（§5.141）
不受影响（其窗口检验已含 i32 读法）。

## 5.146 cmdType vs 购买帧阴性；离线对拍收敛完成（2026-11-03）

20260522 的 34 条 02/80 与 15 条 02/85 购买帧对拍：±10 帧 **0/34**、
±30 帧 0/34、±90 帧 2/34（分 cmdType 全为 0）——**cmdType 与购买无亲
和**（购买有自己的 02/85 通道，符合预期）。至此 02/80 的 cmdType 对三
类已知事件（加点/击杀/购买）的亲和性对拍全部阴性，其"hero-specific
action id"语义需要设备侧真值。

另：20260522 的 15 条 flag-0 手动购买聚在帧 1221-1245（9 条/24 帧 =
一次连续采购）与 1159/1444/3178/4269/4648——手动购买的时间形态与
flag-210 的 6 帧周期 tick 截然不同，进一步支持 §5.144 的分层。

### 离线对拍收敛声明

ID1051/ID1075 的全部可离线对拍已完成系统化收敛：每个子类型/状态键/
flag 值要么有验证语义（朝向角/技能加点/购买镜像/瞄准坐标/打野签名/
flag 分层/构建配置），要么有数据支撑的阴性或字段墙（cmdType/14/2b/73/
key 03/0x2c/02/84 victim/flag=90）。后续逐键与逐类型语义需要设备侧
真值（docs/device_setup.md 待用户执行）或客户端反汇编。

## 5.147 录屏 OCR 对拍尝试：02/84 不含英雄击杀的可分离信号（2026-11-03）

用 20261028_135516 的同局回放录屏 OCR 报告（timeMapping：videoTime 36.0 =
对局 0:00，rate 1.0；killEvents：gameTime 55/82/104 三次英雄击杀）与
.abc 的 02/84 流对拍，尝试锁死 1051 路线的 F0：

- 02/84 首个成对死亡 @帧 510 = 34s（首波兵线交锋时点，量级合理 ✓）。
- 但 02/84 的"camp"字节无法与英雄击杀闭合：video 的 3 次英雄击杀中仅
  gameTime 82 附近有成簇的未配对通知（1224-1254，10 条 camp 0——数量与
  间隔均为小兵死亡形态）；gameTime 55/104 附近无未配对通知。**02/84 的
  victim 字节不是英雄 id，英雄死亡要么走未发现的通道、要么不入流**。
- 02/84 成对死亡首现 @510（34s）与 15fps 相容，但首波交锋时秒级不精确，
  F0 无法由此锁定。

结论：1051 路线的 F0 与英雄击杀归属仍需设备侧真值（录屏的时钟采样
1fps + OCR 误差不足以锚定单帧）；**15fps 在旧构建的相容性再次确认**
（全部时间形态与 15fps 线性映射无矛盾）。

## 5.148 0x1e/0x1f/0x2c 逐字段结构精化（2026-11-03，163751 大样本补充）

用 20261102_163751 尾流（487 条 0x2c、6 条 0x1f、5 条 0x1e）与 161129
合并做逐索引字节统计。

### 0x1f（28B）= 两组拆分 i32 + 尾部计数 ✅ 结构

```text
[1f][sub:u8][s1:3B符号扩展+1B值][0×4][s2:3B符号扩展+1B值][f14:u8][0×6][f21:u8][f22:u8][=1][0×4]
```

- sub ∈ {1, 2}（161129 两条 sub=1/243；163751 六条 sub=1/2）。
- s1/s2 = 符号扩展字节（000000 或 ffffff）+ 低字节（值域 ±250 内）：
  **TDR 逐字节写出的拆分 i32**（非打包 i32）。
- s1 样本：8、22、28…−16；s2 样本：−1、−5、…（小有符号量）。
- [14] ∈ {0, 4}；[21] ∈ {0,1,3}；[22] ∈ 67–218；[23] = 1 恒定；[24..27] = 0。

### 0x2c（17B）= 多 i16 字段 + 子类型 ✅ 结构 / 语义未解

- [1]（2c 后的子类型）∈ **{0, 1, 2}**（163751：0×41/1×68/2×378）——
  0x2c 有三个子类型，5.106.1 的"目标"只是其中之一。
- 宽值字节（坐标/计数量级）在 [4][7][8][11][12][16]；符号扩展字节
  （{0,255}）在 [5][6][9][10]；[13] ∈ {0, 222(0xDE), 248}；[14][15] = 0。
- 按 i16BE 切分 ≈ 七字段（±宽值、两个常 0/−1 槽、尾部计数），与
  i32BE 对齐**互斥地部分吻合**——字段边界仍未唯一确定（§5.141 维持）。

### 0x1e（19B）✅ 结构确认

`[1e][unit:u8∈{2,3,4}][0×14][A:u8∈{0,1,2,3}][B:u8∈68–249][C:u8=1][0]`
——两局 11 条一致；A/B/C 语义未解。

### 结论

三个 TLV 的**字段边界与拆分表示**已结构化（符号扩展字节模式、宽值
位置、子类型分裂、恒定尾字节），逐字段**语义**仍需设备侧真值。

## 5.149 剩余对拍收尾 + 解码状态总表（2026-11-03）

### cmdType 5/7 vs 购买帧 ✅（阴性）

cmdType 7（帧 2107）最近购买 663 帧外；cmdType 5 两连（3502/3505）最近
购买 324 帧外——与 §5.143 的 cmd1 阴性一致，**02/80 与购买无关联**。

### 02/82 瞄准点间距 ✅（攻击目标语义佐证）

六点间距：12,158 → 7,440 → **40,123** → 3,040 → 24,061 单位。第三→第
四点的 40,123 单位跳变（地图对角量级）= 目标切换到地图另一侧——与
"攻击/瞄准目标位置"语义一致（目标随战局切换），与"自身轨迹点"矛盾
（自身不会瞬移 4 万单位）。02/82 = 瞄准/攻击目标位置的置信提升。

### 解码状态总表（截至本轮）

| 通道/字段 | 状态 |
|---|---|
| 1075 容器/帧命令/购买/加点/技能 | ✅ 语义级 |
| 1075 尾流：0x85 购买镜像 / 0x87 加点 / 0x82 kind=2 位置锚点 | ✅ 语义级 |
| 1075 0x01 包装：0x2d 朝向 / 0x1e / 0x1f / 0x2c | 结构级（0x2d 语义✓） |
| 1075 CC（BOOTFRAP1）键值 | ✅ 行为级（23=每帧 bool、03=心跳、8c=2+85=1 打野签名、初始=配置推送） |
| 1051 容器/条目族 | ✅ 语义级（帧号/朝向/加点/购买/瞄准/帧命令/动作计数器/flag 分层） |
| ID1051 02/84 victim、02/80 cmdType、key 03/14/2b/73、0x2c 边界、flag=90 | ❌ 阴性或字段墙（需设备真值） |
| 时间基准 | ✅ 15fps ±1s（1075 确证；1051 相容） |
| 确定性战斗重算 | ❌ 待设备（device_setup.md + bind_probe 就绪） |

## 5.150 绑定探针就绪验证（2026-11-03）

`tools/advance_frame_bind_probe.py` 的离线验证通过：用 prior 会话保存的
真实 metadata（metadata.bin）运行 TARGETS 派生，**6 个目标全部命中**——
FrameWindowHelper.AdvanceFrameCommands（0x6002afe）、
GameLogicHelper.AdvanceFrameCommands（0x6006bcb）、接口
IGameLogicHelper.AdvanceFrameCommands（0x60083ab，params=2）、
HandleFraqBootSingle/HandleFraqBootInfo/CSDT_FRAPBOOT_INFO.unpack。
params 由 metadata 自动派生（无硬编码风险）。设备恢复后按
docs/device_setup.md 步骤 2.5 运行即可直接定位这些方法并捕获代码页
（XOR 0xE3 双读法磁盘核对）。

本轮另完成：cmdType 5/7 与购买帧阴性；02/82 瞄准点间距 40,123 单位
跳变 = 攻击目标语义佐证（§5.149）。

## 5.151 AdvanceFrameCommands 实现全量反汇编：命令消费环完整地图（2026-11-03）

设备会话（client_probe_20261103）的运行时基址（0x400026201000，由 thunk
映射推得）使真实实现（0x40002c84cf7c）的代码可从本地 libil2cpp.so 磁盘
副本**直接按文件偏移读取**（该区域未加密，无需 XOR；capstone 反汇编验证：
默认分支的 ADRP/LDR/MOV W0,W19/MOV X2,XZR/BLR 序列与 advance_frame_binding.md
的记录一致）。

### 命令消费环（完整）✅

```text
循环头 0x40002c84cffc:
  x0 = [frapInfo+0x10]            ; 命令容器
  x0 = array_get([x26+0x6d0], w23, x22)   ; 取第 index 条命令
  w8 = [x0+0xc]                   ; 命令类型 (1..27)
  sub w8, #1; cmp #0x1a; b.hi → 默认/跳过
  dispatch: br x9 = 0x40002c84d03c + [x27 + (type-1)*2]*4
默认分支 0x40002c84d03c:
  调 [0x40003374b000+0xbc0]（全局函数指针），参数 (frameNo, x1=0, 0)
  → ldrb w8, [frapInfo+0xc]; w23++; 循环/退出
```

### 27 个 handler 的统一结构 ✅

每个 handler（0x40 字节一档，0x40002c84d064 起）：

```text
x28 = [command+0x10]             ; payload 对象指针
cbz x28 → 空检查退出
adrp x8, 0x400034473000（type 1/2/11）或 0x400034491000（其余）
…  per-type 内联逻辑（无 BL，含 [obj+0x130] 容量比较等）
→ 解析子目标后调用全局函数指针 [0x40003374b000+off] 并 b 0x40002c84d044（继续循环）
```

共享尾部（0x40002c84d578 起）即一系列"解析 + 调全局指针 + 回循环"的
模式（+0xb70/0xb78/0xb80…每个 handler 一档）。

### 类型 ↔ BOOTFRAP 选择器一致性 ✅

分派表与 .abc 命令流交叉验证：**skip 类型（15/21/25）在两局 .abc 命令流
中零出现**；高频类型（1 CC ×20,649、2 CSSYNC ×5,263、18 PLAYER_MOVE
×171,504、19 ×17,923、20 ×9,656）全部有专属 handler——
**frapInfo 命令类型 = .abc BOOTFRAP 选择器**成立（零不一致）。

### 下一步（设备会话）

- 补采全局函数指针表所在页（0x40003374b000 附近，process_snapshot 未覆盖），
  解析 27 类的处理函数地址；
- 对 frapInfo 环（2×900 槽）在回放播放中做间隔采样（前次捕获时环为空）；
- 用 engine 命令流对拍 `replay_frame_commands` 的 .abc 解码（同帧确定性）。

## 5.152 活体环直连捕获：FrameWindow 包环 820+ 对象（2026-11-03）

回放暂停状态下（用户确认），经 FrameWindow klass 静态字段直连定位实例
（0x75d84abff960，klass 0x75db8938d4d0 验证），其 +0x08 = 900 槽包环数组
（0x75d81d9ac000）。新工具 `tools/ring_direct_poller.py`（绕过堆扫描的
直连轮询）捕获：

- **820 个非空槽**：slot 0 = 开局包（frame 0，plen 20,336 ≈
  SCPKG_FRAPBOOT_SINGLE 体），大包 plen 41,043 / 62,336 / 35,581 / 7,307 /
  6,329 分布于 slot 1024+；快照 400 个包对象存
  `ring_snapshot_2052/ring_manifest.json`（含每包 head 64B 与大包的
  payload 指针数组）。
- 包对象布局与探针期望一致：[frame@0x0C][plen@0x10][payload@0x18]。
- payload = **混合对象引用**（首字节为 "UnityEngine" 字符串对象指针等）
  ——包体是托管对象容器，逐字段解码需按 klass 从 metadata 解字段布局
  （metadata.bin 已存本地，可离线做）。
- 环状态：base=0、current=1、max_seen=0（重进回放后重置；slot 内容保留
  上次播放的包）。

### 下一步

1. 用 klass 指针 + metadata.bin 解包对象的字段布局（离线可做）；
2. 回放恢复播放后用 ring_direct_poller 轮询增量包（工具已就绪）；
3. 包对象内的命令列表与 `replay_frame_commands` 解码对拍（绑定验证）。

## 5.153 活体客户端路径确认：回放不走 AdvanceFrameCommands（2026-11-04）

设备实机关键发现（MuMu 运行中，回放已加载并尝试播放）：

### 回放在播放但 AdvanceFrameCommands 变量不变 ✅（否定）

- 屏幕截图确认回放**在播放**（游戏时钟 00:10 → 00:13 → 00:13）；
- 但 enable flag [0x4000344916a4] = 0（不变）；
- current frame [singleton+0x24] = 0xFFFFFFFF（不变）；
- GameCore rw-p 数据区 3 秒窗口内零变化；
- 函数指针 [0x400033ad46c0] = 0（未设置）。

**结论：标准回放 playback 不走 AdvanceFrameCommands 路径。** 该函数
可能用于特定场景（AI 回放 / 流式回放 / 特定阶段），正常回放走的是
`UpdateFrame → GetLoadMsgCount → Handle ×3 → HandleMsg → DirectHandleMsg`
消息泵路径（§5.43 已记录）。

### CS 命令 FIFO 活体确认 ✅

singleton (0x75db2ade4178) 指向 CS 命令 FIFO 内部——每 ~0x28 字节一条
命令（递增 ID 0x02004049→4A→4B…，会话 ID 0x000c98ec，时间戳递增）。
这就是 G2 的"真实 CS FIFO 上下文"——它在活体客户端中存在且有数据。
G2 的 CommitCsBuffer 崩溃问题在活体客户端中不存在（客户端自身正常
使用该 FIFO）。

### 回放画面推进证据 ✅

两张截图（间隔 8 秒）显示游戏时钟 **00:10 → 00:13 → 00:13**：
- 00:10 → 00:13 = 回放在播放（G4 帧推进的视觉证据）；
- 00:13 → 00:13 = 回放再次暂停或遇到停止点。
英雄位置、状态栏、金币面板在截图中正确渲染——引擎在消费命令流并
更新游戏状态。

### G 门槛重评（活体客户端路线）

| 门槛 | 原方案 | 活体客户端路线 | 状态 |
|---|---|---|---|
| G1 | 构造 CLevelContext | **在活体内存中定位已构造的 CLevelContext** | 结构未定位 |
| G2 | CS FIFO 不崩 | **活体 CS FIFO 已找到**，客户端自身正常使用 | ✅（活体绕过） |
| G3 | 命令流可消费 | **命令流已 100% 解码**，活体 FIFO 含录制数据 | ✅（解码层面） |
| G4 | 推帧+读回 | **回放确实在推进**（时钟递增），游戏状态在 GameCore 堆上 | ⏳ 需定位状态地址 |
| G5 | 真实回放对拍 | .abc 对拍基础设施就绪，回放加载的就是同一 .abc（SHA 一致） | ⏳ 需状态读取 |

### 下一步（优先级排序）

1. **G4 关键路径**：在回放播放中扫描进程堆，定位英雄坐标/血量/金币
   的内存地址（用 team_stats CSV 已知值过滤）；
2. **G1**：从命令 handler 的全局引用链追溯 CLevelContext；
3. **G5**：对拍回放渲染状态与 .abc 命令解码（截图 + 解码对照）。

## 5.154 处理函数架构确认：监听器分发而非直接状态写入（2026-11-04）

反汇编 AdvanceFrameCommands 消费链的处理函数（0x400030955f94 等）：

```asm
ldr x8, [x0]              ; 命令对象的 klass/data 指针
ldrb w9, [x19, #0x130]    ; 监听器期望大小
ldrb w10, [x8, #0x130]    ; 命令对象大小
cmp w10, w9               ; 容量匹配检查
b.lo → skip
ldr x8, [x8, #0xc8]       ; 命令数据数组
add x8, x8, x9, lsl #3    ; 索引×8
ldur x8, [x8, #-8]        ; 取数组条目
cmp x8, x19               ; 与监听器比较
b.ne → not_found
ret                        ; 匹配 → 返回（监听器处理）
```

**结论：全局函数指针表（0x40003374b000）不是游戏状态写入函数，是
监听器分发/匹配函数。** 命令对象通过容量匹配路由到注册的监听器，
监听器内部的回调才是实际的游戏状态更新。找到这些回调需要追跡
监听器的注册过程（运行时行为）或反汇编更多 libGameCore 代码。

这解释了为什么 AdvanceFrameCommands 的 enable flag / frame counter
与回放播放状态不对应——该函数做的是**通知分发**而非帧推进。

### G 门槛最终评估（本轮）

| 门槛 | 状态 | 说明 |
|---|---|---|
| G1 | ❌→⏳ | CLevelContext 存在于 GameCore 堆但未定位（需要 frida 或更深入反汇编） |
| G2 | **✅ 活体确认** | CS FIFO 在活体客户端中正常工作（含录制命令数据） |
| G3 | **✅ 解码完成** | 命令流 100% 解码（27 类型、40,522 条零未知、字段级语义） |
| G4 | ❌ | 回放推进通过 UpdateFrame 消息泵，非 AdvanceFrameCommands；游戏状态在引擎内部未定位 |
| G5 | ❌ | .abc 对拍基础设施就绪但无法读取活体游戏状态 |

**G3 = 通过（解码层面）。G2 = 活体绕过通过。G1/G4/G5 需要设备侧动态分析。**

## 5.154 GameCore 全局状态地图（2026-11-04，活体捕获）

通过 DirectHandleMsg (0x665d8e4) 的 ADRP 引用链，在活体客户端中定位并
读取了 GameCore 引擎的核心状态结构：

### CS 命令 FIFO ✅

singleton (0x75db2ade4178) 指向 CS 命令 FIFO 内部。每 ~0x28B 一条命令，
包含：递增命令 ID（0x02004049→4A→4B…）、会话 ID（0x000c98ec）、
时间戳、命令参数。当前帧号 = 0xFFFFFFFF（暂停未消费）。G2 的"真实
CS FIFO 上下文"已确认。

### 全局状态管理器 ✅

页 0x400034067000 包含 256 个堆指针——**每个命令类型的状态对象表**。
命令 handler 通过 `adrp x9, 0x400034067000; ldr x9, [x9, #offset]`
访问不同偏移的状态对象（0x900/0x910/0x940/0x948/0x998/0x9a0/0x9a8/
0x9b0/0x9b8…）。

### 命令执行日志 ✅

对象 0x75db2accd2e8 包含命令执行日志（每 ~0x28B 一条）：
- 递增 TDR 命令 ID（0x02000d8a→d8b→d8c…）
- 递增计数器（0x00042c0d→c18→c23…）
- 常量对象引用（0x00292c9b）
- 时间戳/参数

### 处理函数架构 ✅

27 个 handler 统一结构：payload 指针 → 容量检查（+0x130 对比）→
调用全局函数指针 → 监听器分发。游戏状态更新在监听器回调的更深层次。

### CLevelContext

CLevelContext 不在已扫描的区域中。它由 GameCore 引擎在更深层的对象
图中维护，通过监听器回调间接更新。定位需要：
1. frida hook 监听器回调的参数
2. 或从 GameCore 二进制逆向类层次
3. 或从 metadata 中查找 GameCore 类的字段布局

## 5.155 新进程布局复现、context 生命周期与结算真值（2026-11-04）

设备：MuMu 实例 0，游戏 PID **10833**（上一会话为 2052）。关键结论：
**模块装载布局在重启后完全确定，堆对象则每次重新分配。**

### 确定性布局（新进程逐项复读）

| 位置 | 值 |
|---|---|
| `libil2cpp.so` base | `0x400026200000`（与旧会话一致） |
| `libGameCore.so` base | `0x400036a00000` |
| `[base_gc+0x4ff4520]` | `0x40003bbea4d0` → `0x40003bc717b0` → context |
| `[base_gc+0x4ff5de8]` | `0x40003bc488b8` |
| AdvanceFrameCommands 转发槽 `[0x40003374b000+0xb68]` | `0x40002c84cf7c`（impl 未变） |

新进程 context = `0x7b2b70ffeff0`，头部仍是自指针 + `0x1E00000`（30 MiB）
自相对 arena，`+0x18` 为 arena 末端。**旧文档的模块内地址/RVA 可跨进程
复用；旧文档里的堆绝对地址（0x75d…/0x75db…）不可复用。**

### 回放播放中的活体信号

- 回放播放时 AdvanceFrameCommands enable flag `[0x4000344916a4] = 1`
  （§5.153 记录为 0；该 flag 至少表示 helper 已就绪，不能单独证明逐帧
  调用，仍需 hook 入口确认）；
- 30 MiB arena 连续抓三帧（间隔约 3.6 s）：出现 57 个等步长 32 位计数器，
  例如 `arena+0x1240c78` 每帧 +200（70533→70733→70933）、
  `arena+0x1dcab70` 每帧 +3168；另有大量每次 +1 的计数器。说明 arena
  在播放中持续更新，是活体模拟状态，不是静态快照；
- 但这批计数器尚未映射到游戏时钟/经济，不能作为 G4 通过证据。

### context 生命周期（重要）

回放播放到 11:33 结束后客户端进入结算页，随后：
- `[0x40003bc717b0]` 变为 `0`（context 指针被清空）；
- 30 MiB arena（`0x7b2b70ff…`）从 `/proc/<pid>/maps` 消失。

**GameCore context 与 arena 只在回放会话存活；G4/G5 的所有状态读取必须
在回放播放/暂停期间完成。** 结算后再读只能拿到已被回收的地址。

### 结算页十人真值（2026-11-04 该局）

| 阵营 | 玩家 | 英雄 | KDA | 结算金币 |
|---|---|---|---|---:|
| 蓝 | 狂傲自由魂Z. | 关羽 | 8/1/7 | 9243 |
| 蓝 | 自诩一棵葱 | 妲己 | 6/1/7 | 8168 |
| 蓝 | 漂流网咖 | 百里守约 | 5/0/8 | 8697 |
| 蓝 | 别吃窝线吖a | 孙悟空 | 5/1/5 | 8352 |
| 蓝 | 胡不喜# | 钟馗 | 3/3/9 | 6552 |
| 红 | 翳灵崽 | 吕布 | 2/7/2 | 5828 |
| 红 | 一帆舞 | 貂蝉 | 2/3/3 | 5778 |
| 红 | 谜语星海 | 张良 | 0/6/4 | 5486 |
| 红 | 麻巫喵 | 公孙离 | 1/5/2 | 6191 |
| 红 | 翩鹊耳垂 | 兰陵王 | 1/6/2 | 5977 |

口径提醒：结算金币是**整局累计获得**（蓝队合计 41,012，红队 29,260），
与对局中顶部/团队面板的“当前可用金币”（08:15 时蓝 25.8k、红 21.4k）
不是同一口径，G5 对拍时必须先对齐口径。

结算页的十个金币值在进程内可搜到（18 MiB scudo 区内 60 个命中），但
分布稀疏、无 10 项规则表结构，**仅凭数值命中不能认定结算统计对象**；
下一步应在回放会话内做结构定位，而不是在结算页猜。

### 本轮对 G4 的推进

- 已确认新进程可复用全部模块内地址、context 链可一键重解析；
- 已确认 arena 在播放中活跃更新、结束后销毁；
- 尚未把任何 arena 字段绑定到可核对的对局值（经济/血量/坐标）。

下一步（需回放重新打开）：暂停在固定时刻，先截屏取 UI 精确值，再抓
arena，搜索“同一结构内同时出现十人金币/KDA/英雄 ID”的候选；用暂停
态复核稳定性，再恢复播放看字段变化。

## 5.156 十人英雄/实体注册表定位（2026-11-04，PID 44505，暂停 03:48）

回放重新打开并在 03:48 暂停（两次截屏时钟一致），新 context =
`0x7b2b73650ff0`，仍是 `0x1E00000` arena。UI 精确锚点：蓝 5 杀/11.0k、
红 1 杀/9.3k；POV 胡不喜#（钟馗）0/0/1、4 级、金币 1595；十人等级蓝
[4,5,7,6,5]、红 [5,5,5,6,5]。

### arena+0x40cb0：10 项 × 16B 英雄/实体注册表 ✅

```text
+0x00 heroID(u32) | +0x04 entityID(u32) | +0x08 seatTag(u32) | +0x0c unknown
```

| heroID | 英雄 | entityID | seatTag 低16位 |
|---:|---|---:|---:|
| 123 | 吕布 | 296 | 3 |
| 140 | 关羽 | 538 | 2 |
| 141 | 貂蝉 | 551 | 0 |
| 167 | 孙悟空 | 750 | 10 |
| 199 | 公孙离 | 1031 | 4 |
| 175 | 钟馗 | 1168 | 8 |
| 196 | 百里守约 | 1611 | 5 |
| 109 | 妲己 | 1613 | 1 |
| 156 | 张良 | 1760 | 11 |
| 153 | 兰陵王 | 1799 | 6 |

- 旧文档反复出现的 entity 1168 正是钟馗（POV），1760/1799 是张良/兰陵王，
  与 §5.154/H4 的线索闭合；
- 表项按 **entityID 升序**排列，seatTag 高 16 位恒为 `0x7FFF`。

### arena+0x577dc：10 项 × u32 玩家顺序实体表 ✅

`1168, 1613, 750, 538, 1611, 1031, 296, 551, 1799, 1760`
（钟馗、妲己、孙悟空、关羽、百里守约、公孙离、吕布、貂蝉、兰陵王、张良）
——正好是“蓝方 5 人 + 红方 5 人”的玩家顺序，与 §5.156 注册表互为印证。

### 本轮排除的诱饵（负面证据）

- `arena+0x311970` 等“十英雄 ID 聚簇”是**字节流/命令流**，把字节按 u32
  读出的巧合；不是字段表；
- `arena+0x582ee4` 的 1595 与 1594/1596 连续出现，是递增计数器，不是金币；
- 十人等级序列 `[4,5,7,6,5,5,5,5,6,5]` 在 arena 任何测试步长（u8/u32，
  1..0x200）都没有连续存储；
- 6 个最大堆区（144/96/65/44/35/18 MiB）里没有出现 `0x7FFF0008` 座位标签，
  也没有同时含 (1595, 175, 1168) 的对象窗口。玩家逐人状态不在这些显眼位置。

### 下一步

十人注册表已经给出 entityID ↔ heroID ↔ seat 的权威映射；缺的是
**逐人可变状态**（金币/等级/KDA/血量/坐标）。最短路径：
1. 让用户打开“团队”页签，拿到暂停时刻十人**精确**金币/KDA（不是顶部
   四舍五入的 k 值），用 5+5 个数值做组合签名；
2. 或沿注册表条目里的 +0x0c 字段（0x7523C648 / 0xAADC39B7 两种基值）
   追它指向的对象；
3. 恢复播放 2–5 秒再暂停，差分两个暂停态，筛出随模拟变化且与十人
   数量相符的字段。

## 5.157 G4：逐人金币/KDA 状态记录已定位并与 UI 对上（2026-11-04）

设备/会话：PID 54128，回放暂停在 **05:00**，context =
`0x7830ce89bff0`（30 MiB arena）。UI 精确锚点（团队面板）：

| 玩家 | 英雄 | KDA | 金币 |
|---|---|---|---:|
| 胡不喜# | 钟馗 | 0/0/3 | 2297 |
| 自诩一棵葱 | 妲己 | 2/0/1 | 3169 |
| 别吃窝线吖a | 孙悟空 | 3/1/3 | 3383 |
| 狂傲自由魂Z. | 关羽 | 3/1/1 | 3138 |
| 漂流网咖 | 百里守约 | 1/0/1 | 3461 |
| 麻巫喵 | 公孙离 | 0/2/0 | 2698 |
| 翳灵崽 | 吕布 | 1/3/1 | 2785 |
| 一帆舞 | 貂蝉 | 0/1/1 | 2405 |
| 翩鹊耳垂 | 兰陵王 | 1/2/1 | 2800 |
| 谜语星海 | 张良 | 0/1/1 | 1891 |

十人等级：蓝 [6,7,8,7,7]，红 [6,7,6,7,6]（钟馗/妲己/孙悟空/关羽/百里守约；
公孙离/吕布/貂蝉/兰陵王/张良）。

### 记录布局

arena 内（本会话）出现 **10 条逐人战斗状态记录**，起始偏移
`0x17c5cc0 + k*0x2C00` 附近（因变长子记录有 ±0xD8 抖动）：

```text
+0x00  u32 16            ; 记录类型
+0x04  u32 1/2/3/4       ; 子类型（不同记录长度）
+0x08  u32 10000
+0x0C  f32 3.32          ; 识别特征
+0x20  u32 1000000000+idx ; idx = 13..4，按降序排列
+0x4C  u32 gold           ; 当前金币
gold+0x50..  u32 对       ; 分技能伤害/治疗统计
gold+0x158 u32 kills      ; 击杀（另一份在 gold+0x1D8）
gold+0xB8  u32 deaths     ; 死亡（另两份在 gold+0x138 / +0x1DC）
gold+0xBC  u32 assists    ; 助攻
```

记录顺序（idx 13→4）：兰陵王、张良、妲己、百里守约、钟馗、公孙离、
孙悟空、貂蝉、关羽、吕布。

### 对拍结果（engine vs UI，05:00 暂停帧）

- **金币 10/10**：engine 值与 UI 完全一致；关羽差 3（3135 vs 3138），
  来自“UI 截图 → arena 快照”之间约 1–2 秒的被动金币增长，属采集时序差；
- **击杀 10/10、死亡 10/10**；
- **助攻 9/10**：妲己 engine 在 `gold+0xBC` 读到 0，UI 为 1；她的助攻
  实际落在 `gold+0xC0`。说明变长子记录会让 KDA 块整体平移 4 字节，
  读取时要按记录头/长度校正，不能硬编码单一偏移。
- 关羽面板实际是 3/1/1（早期人工读成 3/1/2，已用放大截图更正）。

### 结论

G4 的“引擎侧读回”在**金币 + KDA** 维度成立：同一暂停帧内，arena 逐人
记录的数值与 UI 面板逐人一致，且记录里同时带分技能伤害统计。剩余工作：

1. **时间维验证**（本轮被模拟器重启打断）：恢复播放 5 秒再暂停，确认
   同一记录的金币/KDA 随 UI 同步变化；
2. 定位血量/坐标字段（记录里尚未识别）；
3. 把“扫描记录头 `16,*,10000,3.32` + `+0x20` 的 10000000xx 索引”
   固化成工具，避免跨会话硬编码偏移。

产物：`data/replays/_analysis/live_20261104/arena_paused_0500.bin`
（30 MiB 快照）、`scoreboard_0500.png`（十人面板）。

### 5.157.1 时间维验证通过（2026-11-04，PID 12743）

同一回放会话内取两个**真正暂停**的帧（时钟静止）：

| 帧 | 钟馗 | 妲己 | 孙悟空 | 关羽 | 百里守约 | 公孙离 | 吕布 | 貂蝉 | 兰陵王 | 张良 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 01:34 金币 | 679 | 890 | 1065 | 1083 | 902 | 1021 | 658 | 723 | 882 | 661 |
| 02:45 金币 | 1235 | 1521 | 1786 | 2048 | 1746 | 1630 | 977 | 1299 | 1380 | 992 |

- 01:34：engine 金币与 KDA **10/10 精确一致**；
- 02:45：engine 金币 10/10（关羽 2048 vs 面板 2046，差 2 为面板截图与
  arena 抓取之间的被动增长）、KDA **10/10 精确一致**；
- 帧间 KDA 变化同步：关羽击杀 2→3、孙悟空 0/0/1→1/0/2、钟馗
  0/0/0→0/0/1、吕布死亡 2→3、兰陵王死亡 0→1；
- 记录偏移在会话内保持不变（0x17c5cc0…），但**跨进程会变**：
  本次重启后 libil2cpp/libGameCore 基址整体 +0x600000
  （`0x400026800000` / `0x400037000000`），context 链全局也随之
  +0x600000（`0x40003c1ea4d0`）。读取时必须按当前 maps 的模块基址
  重算，或直接用 `tools/arena_player_stats.py` 按记录头扫描。

**G4 判定：金币 + KDA 维度通过（静态 10/10、时间维 10/10）。**
剩余：血量/坐标/等级字段（等级可从 UI 侧栏读，engine 字段尚未绑定）。

快照：`arena_t0_0134.bin`、`arena_t2_0245.bin`；面板：
`t0_ui.png`、`t2_ui.png`。

### 5.157.2 血量/坐标/等级的定位边界（2026-11-04）

对两个暂停帧的记录做逐字段差分后确认：

- `rel 0x50..0x78` 是**累计伤害/治疗**类统计（单调增，71 秒内近似翻倍），
  不是血量；
- `rel 0xC4/0xC8/0xCC` 是小计数（补刀/参团类），不是血量；
- `rel 0x150/0x15C/0x160` 十人全变、且 `0x150` 与 `0x160` 的变化量
  等大反号，量级约 Q16.16 的 4.8e4/5.7e4——更像**朝向/旋转量**，
  不是地图坐标（十人值过于接近，真实位置不会这样聚在一起）；
- 在记录 ±0x2C0 内**没有** HP/maxHP 相邻对（要求 max 帧间不变、
  current≤max），也没有 100–30000 量级的 float。

**结论：统计记录只承载金币/KDA/分技能伤害；血量/坐标/等级在堆上的
unit 对象里。** 记录头 `+0x28` 是一个绝对堆指针（示例
`0x7830BFDAEE18`，高 16 位与当前堆基址一致），指向的对象才是候选
unit。下一会话应走“轻量跟随”路线：

1. 只解析 context 链，读 arena 中记录区（约 `0x17c0000..0x17e4000`，
   144 KiB），不做 30 MiB 全抓；
2. 从一条记录的 `+0x28` 取指针，跟随并 dump 目标对象的前 0x200；
3. 在目标对象里找 10 份 unit（或按 entityID 索引的表），核对
   HP/坐标/等级；
4. 只在确认对象布局后再扩大读取，避免再次触发 ANR/重启。

本轮设备在多次全量 arena 抓取后回到 MuMu 桌面（进程重启），
unit 指针跟随未完成。

### 5.157.3 unit 对象与归一化血量（2026-11-04，PID 2135，07:26–07:29）

轻量路线跑通：只读记录区 144 KiB 即可拿到十人记录，`+0x28` 指向
**arena 内部**的 unit 对象（本会话记录区在 `arena+0x4cd0`，unit 对象在
`arena+0x1b2f00` 附近；偏移跨会话会变）。

unit 对象头部（十人一致）：

```text
+0x28  u32 heroID
+0x3C  u32 entityID
+0x40  u32 entityID (dup)
+0x08  u32 HP current (归一化)
+0x10  u32 HP max     (归一化, 约 1000)
```

**重要更正**：属性面板“生命”列是**最大血量**（钟馗 10054），不是
`+0x10`。`+0x08/+0x10` 是归一化对：

| 玩家 | +0x08/+0x10 | 比例 | 面板最大血量 | 推算当前血量 |
|---|---|---:|---:|---:|
| 钟馗 | 1013/1079 | 93.9% | 10054 | ≈9441 |
| 关羽 | 836/1064 | 78.6% | 8356 | ≈6568 |

- 3 秒播放差分中 `+0x08` 从 1041→1013（掉血），`+0x10` 不变，确认是
  **当前/最大**这一对；
- 绝对最大血量（10054 等）**不在** unit 对象，也不在其周围 384 KiB
  arena 里（按 u32/u16/f32 精确值都搜不到）；它是基础属性+等级+装备
  的派生值，只在属性面板/派生模型里；
- 因此引擎侧可直接读**血量比例**，绝对血量 = 面板最大血量 × 比例；
- 坐标候选：同一次 3 秒差分里 `+0x1664`（6798→6838）与 `+0x1668`
  （446588→449228）同步变化，疑似位置分量，待用移动中的英雄复核。

### 5.157.4 位置字段、回放时钟与命令流坐标（2026-11-04，离线智能体）

**单元对象位置三元组（出生/锚点，不是实时位置）**

```text
+0x0278 i32 X     +0x027C i32 Y (高度)     +0x0280 i32 Z
```

十人按阵营分符号：蓝方 X/Z 为负、红方为正，范围约 ±53k…±57k；
Y 全 0（地面）。因此这组是**出生/锚点**，不是逐帧实时位置。
`+0x0288/+0x0290` 是朝向单位向量，十人 |v|=1000。

**回放时钟**

`+0x1664/+0x1668` = (帧号, 毫秒)，全局共享，帧率 15.1515 fps；
关羽/吕布的布局整体 −0x140，所以同样的时钟落到 `+0x1524/+0x1528`。
`+0x16B0` 是哈希/动画相位，不是坐标。

**命令流坐标**

`.abc`（`20261102_161129_…abc`，SHA-256 `d74c2bed…`）已完整解码：
10,509 帧、88,627 条命令、0 未解析。`USEPOSITIONSKILL` 的
`target_x/target_y` 是地图内部坐标（±30k），与引擎 X/Z 同一套系统；
`PLAYER_MOVE` 68,384 条是方向+摇杆幅度（`world_vector`、`mag`），
不是绝对坐标。地图范围约 ±60k，出生点在四角 ±55k。

**结论**：实时位置可由“出生锚点 + 每帧移动向量积分 + 瞄准点校正”
重建，无需再逆 actor 对象；小地图位置用于验证。等级/装备不在
unit 对象内联，仍在增量项。智能体产物：
`unit_fields/`、`abc_timeline/`、`minimap_positions/`、
`tools/live_diff_matrix.py`；后续 `trajectories/`、`state_table/`、
`actor_hunt/`、`levels_equipment/`。

### 5.157.5 吕布跳跃的 .abc 帧锚点（2026-11-04）

用户指认 07:43 吕布是唯一在高空的单位。`.abc` 窗口 07:43±4 s 给出：

- frame **6949**（07:43.2）：`USEDIRECTIONALSKILL` slot 1，69.0°，
  skill_seq 96/97；
- frame **6999**（07:46.5）：`USEOBJECTIVESKILL` slot 9，skill_seq 98
  （更像大招/跳跃类技能）。

高度验证的取帧锚点用 6949 或 6999。当前引擎 unit 对象的
`+0x027C` 在 07:45 暂停帧仍为 0（吕布已落地）；需要在起跳帧
重新读 `+0x027C`，或在 actor/transform 对象里找实时 Y。

### 5.157.6 等级字段（2026-11-04，离线智能体 + 复验）

逐人记录里有一段稳定的战斗状态块：

```text
record+0x218 u32 16
record+0x21C u32 8
record+0x220 u32 hero level   (= gold_offset + 0x1D4)
record+0x224 u32 kills         (= gold_offset + 0x1D8)
record+0x228 u32 deaths        (= gold_offset + 0x1DC)
```

`levels_equipment/levels.csv` 覆盖 10 人 × 5 个时间点；01:34 / 02:45 /
05:00 / 07:46 的 engine 等级与侧栏/计分板 **10/10** 一致。
`tools/arena_player_stats.py` 已增加 `level` 输出，05:00 复验通过
（钟馗6、妲己7、孙悟空8、关羽7、百里守约7；公孙离6、吕布7、貂蝉6、
兰陵王7、张良6）。unit 对象 0x0..0x1888 内没有等级/经验字段；
装备只有视觉读数（52 件，未绑定内存字段）。

### 5.157.7 五路智能体收口：数据分级与产品边界（2026-11-04）

| 数据 | 结论 | 用途 |
|---|---|---|
| 全量事件表 | 88,627 行、0 unknown（移动 68,384/攻击 11,886/CC 6,258/技能 1,472/购买 547/瞄准 78/AI 2） | 事件级复盘，权威 |
| 统一状态表 | 3,043 行；金币 30/30、KDA 30/30、等级 40/40 对拍；28 PASS/5 WARN/0 FAIL | 检查点状态，引擎实测 |
| 金币/KDA 插值 | 全帧覆盖、锚点精确、单调；09:01 独立 UI 校验最大误差 1,012 金币 / 3.68 KDA | 用 supplementary 系列，标注“插值” |
| HP | 仅 21 个实测样本（0.59% 帧），其余未知 | 不插值冒充；补 UI 血条采样 |
| 逐帧位置 | 输入方向积分 17.8% 地图跨度（目标 ≤5%） | **不作为坐标发布**，仅趋势 |
| 引擎实时 transform | 不在 30 MiB arena；在 hero 对象外部堆指针 `0x7311…` | 后续活体抓取 |

产品口径（V1）：

- 可发布：事件时间线、操作统计、出装/加点、检查点金币/KDA/等级、插值曲线（标“插值”）、
  小地图采样位置（标“UI 采样”）；
- 不承诺：逐帧引擎坐标、逐帧血量、击杀归属；
- 页面必须显示四档来源（文件解码/引擎实测/UI 采样/估算），缺失显示“未使用”。

版本与置信度工程化：`resources/replay_profiles.json` + `replay_profiles.py`
（版本前缀匹配、未命中失败关闭）、`docs/replay_profiles.md`（新版本 7 步流水线）、
解析报告与 `/api/replays/{id}/inputs` 带 `provenance/confidence`、回放详情页
“数据来源与置信度”图例。

## 5.158 逐人累计统计块：偏移修正与输出/承伤候选（2026-11-04）

### 偏移修正

5.157 写的“`gold+0x50` 起是分技能伤害/治疗统计”有误：按 `gold+0x50` 读出
全 0。正确的块在 **`record+0x50`**（gold 在 `record+0x4C`，差 0x4C）。
同一记录里 `record+0x74/0x78` 与 `+0x50/+0x58` 数值重复，说明是定长数组
的两份副本，不是“分技能”。

### 结构

`record+0x50` 起 11 个 u32 累计计数器（c0…c10），三个时间点单调增：

| 时间 | 十人 c1 合计 | 十人 c3 合计 | c3/c1 |
|---|---:|---:|---:|
| 01:34 | 142,537 | 165,010 | 1.158 |
| 02:19 | 213,667 | 248,460 | 1.163 |
| 02:45 | 266,225 | 312,474 | 1.174 |
| 05:00 | 623,060 | 737,332 | 1.183 |
| 07:46 | 1,034,571 | 1,258,022 | 1.216 |

c0 = c2、c1 = c5 恒等（副本）。c3/c1 的比值跨 6 分钟稳定在 1.16–1.22，
说明两者来自同一本账（一端是输出、一端是承伤/有效承伤）。

### c3 行为像“输出”

- 角色分布：05:00 孙悟空 183,728 > 兰陵王 104,795 > 百里守约 81,012 >
  关羽 74,574 > 妲己 71,093；张良 40,076、钟馗 43,524 垫底；
- 增量对得上表现：01:34→02:45 的 71 秒里，孙悟空 +35,005（≈493 DPS）、
  兰陵王 +21,591、关羽 +19,001；吕布只 +2,024（≈28 DPS），期间正好阵亡一次；
- 五点序列的 DPS 量级（300–770）与满级前英雄的普攻+技能输出吻合。

### c1 尚不能定名

吕布在 01:34→02:45 区间阵亡一次，c1 只增 1,596（十人最低）；若 c1 是
承伤，这个数偏低。因此 c1 可能是“有效承伤”“对英雄承伤”或其他口径，
在拿到面板“数据”页之前不下结论。

### 工具与产物

- `tools/state_series.py`：多快照 → 逐检查点序列（gold/KDA/等级/11 计数器 +
  区间增量与速率），只读、离线；
- `data/replays/_analysis/live_20261104/state_series_161129.csv`（50 行，
  5 个检查点）、`roster_161129.json`（记录序号→选手/英雄）。

### 快照文件名的时间不可信

`arena_t1_0146.bin` 按金币总量插值实际约 **02:19**，不是文件名暗示的 01:46
（01:46 时十人金币应约 9.6k，实测 12.4k）。以后用金币/等级锚定快照时刻，
不要相信文件名。

### 待做

用面板“数据”页（输出/承伤/治疗）锚定 c3 与 c1 的语义；锚定后把 c3 写进
逐帧数据契约，按 10–30 Hz 只读 `record+0x50` 与 unit 对象 HP 两个字段。

### 旁证：c3 增量与操作事件数相关

用 `.abc` 全量事件目录按同一区间统计每人 attack+skill 次数，与本区间 c3 增量
做 Spearman：

| 区间 | 与 attack+skill | 与 attack |
|---|---:|---:|
| 02:19→02:45 | 0.726 | 0.766 |
| 02:45→05:00 | 0.858 | 0.845 |

相关不为 1 是好事：张良在 26 秒里只有 1 次普攻、0 次技能，c3 仍增 3,558，
说明 c3 不是“攻击次数”，而是带独立来源（持续伤害/召唤物/兵线）的伤害量。
这是旁证，不是定名。

### 锚定工具

`tools/panel_anchor.py`：输入一张快照 + 一份面板 CSV
（`player,damage_dealt,damage_taken,healing`）+ roster，输出 11 个计数器与
三列面板值的对照表、每列的 Spearman、以及 cN/damage_dealt 的中位比值，
并给出“最佳匹配”。已用合成面板自测：能把 c3 判给 damage_dealt、c1/c5 判给
damage_taken、c8 判给 healing，工具逻辑无误（自测为循环验证，不作证据）。

采集要求：同一局、同一暂停帧、面板“数据”页可见十人输出/承伤/治疗；
截图 OCR 或人工录入成上述 CSV。一次有效锚定即可定名，第二局做复核。

### 计数器图谱（10 人横截面，05:00）

`datasets/record_counters_atlas.csv`。11 个槽位里有 3 组完全重复：
c0=c9、c1=c5、c2=c10，实际只有 7 个独立计数器。

| 计数器 | 十人合计 | ρ(击杀+助攻) | ρ(金币) | ρ(死亡) |
|---|---:|---:|---:|---:|
| c0=c9 | 122,969 | 0.533 | 0.479 | -0.407 |
| c1=c5 | 623,060 | 0.464 | 0.830 | 0.032 |
| c2=c10 | 122,969 | -0.489 | -0.527 | 0.750 |
| c3 | 737,332 | 0.627 | 0.855 | 0.025 |
| c4 | 207,053 | -0.063 | -0.139 | **0.915** |
| c6 | 159,417 | -0.157 | -0.212 | **0.915** |
| c7 | 156,518 | 0.376 | 0.406 | -0.216 |
| c8 | 156,518 | -0.408 | -0.455 | 0.839 |

读法：c3 与金币/参战同向，最像“输出”；c4/c6 与死亡强相关，最像“死亡代价”
（读秒/损失）；c2 与死亡相关但与金币反向，最像“承伤/被压制”。

**阴性：c2 不是死亡计数。** 02:19→02:45 区间吕布零死亡，c2 仍增 767；
05:00→07:46 吕布零死亡，c2 仍增 13,703。它是连续累积量，只是死得多的人
累积得快。

注意：ρ 是 10 个样本的秩相关，只用于生成假设，不能定名。定名仍靠面板锚定。

### 精确对偶：两组“输出/承受”账本（2026-11-04）

不看面板也能定方向：如果某两个计数器是一笔伤害的两端，那么
**蓝方 c_i 的队内合计 必须等于 红方 c_j 的队内合计**，反之亦然，而且是
逐单位精确相等，不是近似相关。

实测（t0 / 02:45 / 05:00 三个时间点全部成立）：

| 对偶 | 蓝方合计 | 红方合计 | 误差 |
|---|---:|---:|---:|
| c0 (蓝) = c2 (红) | 77,402 | 77,402 | 0 |
| c2 (蓝) = c0 (红) | 45,567 | 45,567 | 0 |
| c7 (蓝) = c8 (红) | 100,411 | 100,411 | 0 |
| c8 (蓝) = c7 (红) | 56,107 | 56,107 | 0 |

所以 **(c0, c2) 与 (c7, c8) 是两组独立的“造成/承受”账本**，不是同一个量的
副本。方向由角色分布判：吕布 c0=10,956 / c2=19,646（坦克，造成少、承受多），
孙悟空 c0=20,157 / c2=7,755（刺客，造成多、承受少）→ **c0/c7 为“造成”，
c2/c8 为“承受”**。

两组账本的规模相差 1.2–1.6 倍，且打野的 c7/c0 明显更高（兰陵王 1.60、
公孙离 1.42、关羽 1.44；张良 1.07），说明其中一组口径更宽（含野怪/召唤物，
或为未减伤原始伤害）。**哪组是“对英雄”、哪组是“含野怪”，仍需面板或
召唤物实验区分。**

### 对 c3 的修正

5.158 前文把 c3 当“总输出”是**未经验证的推断，现降级**。理由：

1. 若 c3 是输出、c1 是承伤，两队之间应满足“蓝输出≈红承伤”，实测
   蓝 c3=453,931 vs 红 c1=242,706，差 87%，不成立；
2. 真正满足队际守恒的是 c0/c2 与 c7/c8，c3 不参与任何精确对偶；
3. c1/c3 的比值随打野占比升高（打野 1.22、法师 1.08），更像**对非英雄单位
   的伤害**（小兵/野怪），而不是对英雄输出。

c1/c3 的新候选：**c1 = 对小兵伤害、c3 = 对小兵+野怪伤害**（比值 = 1 + 野区
占比，与打野/射手更高一致）。这仍是候选，需要用补刀数或野怪击杀数做锚定。
前文“c3 像输出”的相关性证据（ρ(金币)=0.855、ρ(参战)=0.627）对 PvE 伤害
同样成立——刷得快的人经济好、参战也多，不能区分两者。

### 两组账本的口径：候选与一条阴性

(c7/c0) 与 (c8/c2) 的团队级比值在四个时间点完全同步：

| 时间 | c7/c0 | c8/c2 | c3/c1 |
|---|---:|---:|---:|
| 01:34 | 1.180 | 1.180 | 1.158 |
| 02:45 | 1.230 | 1.230 | 1.174 |
| 05:00 | 1.273 | 1.273 | 1.183 |
| 07:46 | 1.351 | 1.346 | 1.216 |

比值随时间单调上升。**“减伤率”假设已被基础护甲检验削弱**：用英雄表
`cell_11` 的基础物防与 c8/c2 做秩相关，ρ 只有 **0.389**；反例是钟馗
（物防 79，十人最高，比值 1.20）和吕布（物防 54，比值 1.53 最高）。
混合伤害类型、等级成长、装备都会稀释单看物防的解释力，但 0.39 不足以
支撑“减伤率”作为主解释。

**当前更合理的候选：c7/c8 = 含护盾吸收与溢出的总伤害，c0/c2 = 实际掉血。**
理由：

1. 比值随时间上涨，符合护盾/装备随等级增长；
2. 吕布（坦，出护盾与血量装）承受比值 1.53 最高；
3. 不需要“护甲”这一中介，能解释为什么和基础物防只有 0.39。

“溢出伤害”单独解释不了 01:34 的 1.18：当时全队只有 2 个人头。

**面板“输出/承伤”应对应 c7/c8（总伤害），不是 c0/c2。** 锚定时先比这一对；
若面板值落在 c0/c2 上，说明面板显示的是“实际掉血”口径。

c1/c3 是同一对的 PvE 版本（c1 有效、c3 原始），比值 1.16–1.22、低于英雄
那一对，符合小兵护盾更少。
