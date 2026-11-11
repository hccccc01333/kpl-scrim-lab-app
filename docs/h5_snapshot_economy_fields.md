# H5 快照经济字段：CPlayer/actor 与金币记录定位

- 日期：2026-11-03
- 快照：`data/replays/_analysis/client_probe_20261103/process_snapshot_2052/`
  （27 个 region，286,425,088 B；原始快照只在本地忽略目录，不提交、不写入正文）
- 进程：pid 2052，`com.tencent.tmgp.sgame`，build 5247758
- context（包装层）：`0x75d7e86e9ff0`；binder context P：`0x75d7ea4e99f0`
- `libGameCore.so` base：`0x400036a00000`
- fixture：`host/fixtures/20261102_161129/`
- 边界：只读本地快照 + 本地 ELF/metadata/文档；没有注入、没有登录、没有调用游戏函数、没有修改游戏文件。文中不写玩家名、账号、token、openID。

> 地址只对本次进程实例有效。下文的“ctx+偏移”是相对包装层 context
> `0x75d7e86e9ff0` 的偏移；P+偏移是相对 binder context
> `0x75d7ea4e99f0` 的偏移。两者不能互换。

## 0. 结论摘要

1. **P 已复核**：P=`0x75d7ea4e99f0` 在 context arena 内（ctx+`0x1DFFA00`）；
   `P+0x80`/`P+0x88` 分别等于 CS 槽 0/1 对象 `0x75d7e7fe70fc`/`0x75d7e7fe718c`；
   包装层 `ctx+0x18` 等于 `P+0x600`（arena 结束地址）。这确认 P 是 binder 的
   `CCoreContext`，包装层不是。
2. **CPlayer 类已静态定位，但快照里没有实例**：CPlayer 构造函数
   `base+0x4348AF8`，vtable `base+0x4F5B0A8`，对象大小 `0x168`；工厂
   `base+0x45B12E8` 用字符串 “CPlayer” 注册。快照里搜不到运行时 vtable
   `0x40003B95B0A8`，也没有 0x168 步长的十人对象数组。因此本次回放快照
   **不包含活的 CPlayer 对象**。
3. **找到三张可信的十人身份/配置表**：
   - 索引表 `ctx+0x34C198`：10×0x10，`{heroId, entityId, slotIndex, 0}`，
     10 条与 fixture 完全一致。
   - 名册表 `ctx+0x594A4`：10×0x60，`heroId@+0x00`、`camp@+0x0C`、
     `entityId@+0x14/+0x18`；容器指针在 `ctx+0x1DD8248`，计数 10 在
     `ctx+0x1DD8264`（`ctx+0x1DD8260` 是 16，另一个容量/字段）。
   - hero 配置表 `ctx+0x3B43F8`：0x20 步长，前 10 条对应十名玩家，
     `{heroId, ptr, index}`；表还包含 1690/1691 等非玩家 hero 条目。指针指向
     vtable `0x75DB20C9DC38` 的 hero 配置对象，字段与 `0x111C3C` 英雄基础
     属性 CSV 逐项一致（HP/移速/防御/攻击等是**配置值**，不是实时状态）。
4. **金币整数确实在快照里，但以 0x20 字节事件记录形式存在**：记录字段集为
   `{value, entityId, packedEvent, param, vtable, 1, sequence}`，不同 vtable
   下字段顺序不同。`value` 出现全部十个官方终局面板金币值
   （6540/8168/8352/9243/8697/6191/5828/5778/5977/5474），因此 `value` 是
   金币类总量，置信度 medium-high。**但记录没有把 value 稳定绑定到相邻
   entityId**：同一个 8168 会出现在十个不同 entityId 的记录里，说明这是
   “广播/同步”记录，不是“每人一条当前金币”的直接数组。
5. **没有找到**可直接读的 live `current gold / total earned / spent` 三元组，
   也没有找到 live `KDA` 或 `HP` 字段。发现的金币记录只能证明“金币值存在”，
   不能证明其 owner 或逐帧当前金币。名册记录里的 `+0x24` 是 1..11 的小整数，
   与终局 KDA、终局金币、英雄等级均不匹配，语义未定。

> 置信度口径：high = 结构 + 值/代码双证；medium = 结构或值单证；
> low = 仅形态推断。经济值只与官方终局数据做 sanity，不反推逐帧值。

## 1. 快照与 P 复核

### 1.1 关键地址

| 项 | 地址/值 | 证据 |
|---|---:|---|
| 包装层 context | `0x75d7e86e9ff0` | `meta.json`；`ctx+0x00` 自指针 |
| binder context P | `0x75d7ea4e99f0` | `P+0x80/P+0x88` 等于 CS slot0/1 |
| P 相对 ctx | `ctx+0x1DFFA00` | 算术 |
| `ctx+0x18` | `0x75d7ea4e9ff0` | 等于 `P+0x600`（arena 结束地址） |
| `P+0x08` | `0x0000000100000003` | 低 32 位引用计数 3，高 32 位版本 1 |
| `P+0x80` | `0x75d7e7fe70fc` | CS slot0 对象 |
| `P+0x88` | `0x75d7e7fe718c` | CS slot1 对象 |
| `P+0x600` | 内存值为 0 | 该地址即 `ctx+0x1E00000`，arena 上界 |

CS 槽对象布局与 `docs/cs_fifo_context.md` 一致：slot0 vtable
`0x75DB20CA8608`、cap `0x8000`、pending 8；slot1 cap `0x40000`、pending 76。

### 1.2 快照覆盖

- context arena region：`0x75D7E86E9000-0x75D7EA4EA000`，31,461,376 B，
  包含 ctx 全部 `0x1E00000` 容量和 P 的 `0x600` 尾部。
- `dataCache.db` 映射 124,780,544 B 未使用；libGameCore 代码映射不在快照内，
  所以 CPlayer 的 vtable 指针只能按 `base+0x4F5B0A8` 推算，不能直接在快照
  里读到代码。
- 快照时刻接近回放末尾（medium）：`0x75D7E9851800` 一带的记录里出现
  10677、10676、10675、10674 递减，并与 fixture entity 交错；10674 正好等于
  `totalFrameNum`。该区域是事件/帧记录混合区，不做 stride 断言，只用于判断
  “末帧附近”，不作为经济值。

### 1.3 CS consumer 对象

`0x75DC98DAAC10` 在已抓取的 region
`0x75DC98D88000-0x75DC99108000` 内（`region_75dc98d88000_75dc99108000.bin`）。
对象头：vtable `0x75DDC9809FF0`，`+0x10 u32=0x40000`，`+0x14 u32=8`，
呈 ring/FIFO 形状，与 `docs/context_transplant_a1.md` §7 的 consumer 指针
一致。该对象前 0x60 字节没有金币/KDA 字段；它只证明 consumer 已在快照内，
不作为经济状态来源。

## 2. CPlayer / actor 静态候选

### 2.1 CPlayer 类签名（高置信）

`base+0x45B12E8` 是 CPlayer 单例工厂，反汇编关键片段：

```text
45b1304  mov  w0, #0x168          ; 对象大小 0x168
45b1308  bl   0x4B40050           ; 分配
45b131c  adrp x1, #0x1183000
45b1320  mov  x0, x19
45b1324  add  x1, x1, #0xd4d      ; "CPlayer"
45b1330  mov  w4, #0x1348         ; 类型/参数
45b1334  blr  x8                  ; 类型注册/构造
```

其中 `x8 = [base+0x5040020]`；该 GOT/RELA 槽的 addend 是 `0x4348AF8`，
即 CPlayer 的构造函数。构造函数 `base+0x4348AF8`：

```text
4348b04  bl   0x4345E9C           ; 基类构造
4348b0c  str  xzr, [x19, #0x160]  ; +0x160 = 0
4348b10  add  x8, x8, #0xa8       ; vtable = base+0x4F5B0A8
4348b14  str  x8, [x19]
```

结论：CPlayer = `{ vtable@0x00, ..., +0x160 ptr }`，大小 `0x168`。
静态 vtable 地址 `0x4F5B0A8`；运行时应为 `0x40003B95B0A8`。

### 2.2 快照内没有 CPlayer 实例（高置信）

- 在全部 27 个 region 中搜索 qword `0x40003B95B0A8`：0 命中。
- 搜索 `0x40003B95B188`（析构 vtable 变体）：0 命中。
- 按 0x168 步长扫描 arena，要求 10 条记录同时含 hero/entity 对：0 命中。
- 结论：本次回放/观战路径没有构造 CPlayer 单例，或 CPlayer 不在已抓取的
  mapping 内。**不能把 CPlayer 的 0x168 布局当成已存在的 live 状态**。

### 2.3 CPlayerArr / CActorManager 字符串（中置信，仅存在性）

`libGameCore.so` 里存在以下字符串及唯一代码引用：

| 字符串 | 文件地址 | 代码引用 | 说明 |
|---|---:|---:|---|
| `CPlayer` | `0x1183D4D` | `0x45B131C` | CPlayer 工厂/类型注册 |
| `CPlayerArr` | `0x11D08C7` | `0x463C980` | 大段类型/字段注册函数 |
| `CPlayerArrPooledPointer` | `0x11C3D2D` | 未单独展开 | 说明存在池化指针容器 |
| `TraversePlayerArray` | `0x11C7295` | `0x2CF50C4` | 大段类型/字段注册函数 |
| `CPlayerCenter` | `0x11F131C` | `0x3F99D08` | 大段类型/字段注册函数 |
| `CActorManager` | `0x120503E` | `0x45AA148` | 大段类型/字段注册函数 |

这些引用都落在“属性/字段注册”大函数里，不是可直接读取的对象构造函数；
它们证明 native 玩家容器存在，但没有给出到 context 偏移的映射。

## 3. 十人表

### 3.1 索引表：`ctx+0x34C198`（高置信）

- 地址：`0x75D7E8A36188` = ctx+`0x34C198`
- 结构：10 × 0x10
- 字段：
  - `+0x00 u32 heroId`
  - `+0x04 u32 entityId`
  - `+0x08 u32 slotIndex`（推断；0..11，缺 7/9）
  - `+0x0C u32 0`

| heroId | entityId | slotIndex |
|---:|---:|---:|
| 123 | 296 | 3 |
| 140 | 538 | 2 |
| 141 | 551 | 0 |
| 167 | 750 | 10 |
| 199 | 1031 | 4 |
| 175 | 1168 | 8 |
| 196 | 1611 | 5 |
| 109 | 1613 | 1 |
| 156 | 1760 | 11 |
| 153 | 1799 | 6 |

证据：10 条记录的 hero/entity 与 fixture 的 `players.json` 一一对应；
slotIndex 推断为 0..11 的 12 槽编号，7/9 为空。判定：**玩家/英雄索引表**，
不是经济状态表；slotIndex 的绝对语义（座位/AI 槽/其他）未证。

### 3.2 名册表：`ctx+0x594A4`（高置信）

- 记录基址：`0x75D7E8743494` = ctx+`0x594A4`
- 结构：10 × 0x60
- 容器：`ctx+0x1DD8248` 处 qword 指向记录基址；
  `ctx+0x1DD8264` 处 u32 = 10（计数）；`ctx+0x1DD8260` 处 u32 = 16
  （容量/另一个字段，语义未定）。
- 字段：

| 偏移 | 大小 | 值/语义 | 置信度 |
|---:|---:|---|---|
| `+0x00` | u32 | heroId | high |
| `+0x04` | u32 | 0 | high |
| `+0x08` | u32 | 0 | high |
| `+0x0C` | u32 | camp（1/2） | high |
| `+0x10` | u32 | 0 | high |
| `+0x14` | u32 | entityId | high |
| `+0x18` | u32 | entityId（重复） | high |
| `+0x1C` | u32 | 0 | high |
| `+0x20` | u32 | 0 | high |
| `+0x24` | u32 | 1..11 小整数，语义未定 | low |
| `+0x28` | u32 | 0 | high |
| `+0x2C` | u32 | 1 | medium |
| `+0x30..0x4F` | — | 0 | high |
| `+0x50` | u32 | `0x3BC71701` 常量 | medium |
| `+0x54..0x5F` | — | 0 | high |

十条记录（按 entity 升序）：

| # | heroId | entityId | camp | +0x24 |
|---:|---:|---:|---:|---:|
| 0 | 123 | 296 | 2 | 5 |
| 1 | 140 | 538 | 1 | 1 |
| 2 | 141 | 551 | 2 | 10 |
| 3 | 167 | 750 | 1 | 8 |
| 4 | 199 | 1031 | 2 | 11 |
| 5 | 175 | 1168 | 1 | 4 |
| 6 | 196 | 1611 | 1 | 1 |
| 7 | 109 | 1613 | 1 | 1 |
| 8 | 156 | 1760 | 2 | 9 |
| 9 | 153 | 1799 | 2 | 9 |

判定：**十人名册/身份表**。它包含 hero、entity、camp 和槽位相关标量，
但 `+0x00..0x5F` 没有金币、HP、KDA 字段；`+0x24` 不是终局 KDA、终局金币
或英雄等级（见 §5 对照）。

### 3.3 hero 配置表：`ctx+0x3B43F8`（中高置信）

- 地址：`0x75D7E8A9E3E8` = ctx+`0x3B43F8`
- 结构：0x20 步长；前 10 条对应十名玩家，之后还有 1690/1691 等非玩家
  hero 条目（表长 >10，完整边界未定）
- 每条：`+0x00 u32 heroId`、`+0x04 qword ptr`、`+0x0C u32 index`
- ptr 指向 vtable `0x75DB20C9DC38` 的 hero 配置对象。

对象字段与 `0x111C3C` 英雄基础属性 CSV 逐项一致。以 hero 109 的对象
`0x75D7EA29B940` 为例：

| 对象偏移 | 值 | CSV 对应 |
|---:|---:|---|
| `+0x10` | 7000 | 未命名配置项（非 MaxHp） |
| `+0x14` | 3600 | MoveSpeed ×10（cell_14） |
| `+0x18` | 500 | 未命名配置项 |
| `+0x1C` | 1500000 | 未命名配置项 |
| `+0x20` | 3295 | MaxHp 最大生命（cell_10 lo） |
| `+0x24` | 2008000 | 未命名配置项 |
| `+0x28` | 46 | PhysicalDefense 物理防御（cell_11 lo） |
| `+0x2C` | 21833 | 未命名配置项 |
| `+0x50` | 172 | PhysicalAttack 物理攻击（cell_12 lo） |
| `+0x54` | 94000 | 未命名配置项 |
| `+0x60` | 150 | 未命名配置项 |
| `+0x64` | 150000 | 未命名配置项 |
| `+0x68` | 75 | 未命名配置项 |
| `+0x6C` | 110000 | 未命名配置项 |
| `+0x7C` | 8500 | 未命名配置项 |

MaxHp/MoveSpeed/PhysicalDefense/PhysicalAttack 的列名来自
`data/replays/_analysis/datasets/agent_hero_tables/_attribute_candidates.csv`
（该文件把 `0x111C3C` 的 cell 与字段名对齐）。因此 `+0x20=3295` 是
**MaxHp 配置**，不是当前 HP；`+0x10=7000` 不是 MaxHp。

判定：**hero 配置缓存，不是 live 状态**。3295/3600 等值不能当当前 HP/移速
读取；它们对所有同表对象是静态配置。

### 3.4 其他候选与排除

| 候选 | 证据 | 判定 |
|---|---|---|
| `ctx+0x2B0` view 对象 | `PushViewBuffer/CommitViewBuffer` 直接读 | view/UI 通道，不是玩家状态 |
| `ctx+0x268..0x610` 0x18 记录表 | 构造函数 fixup；39 条 | 句柄/注册表，不是十人数组 |
| `0x75D7E8B2A000+0xF30` 0x0C 紧凑表 | 前 7 条像 `{entity,hero,packed}`，之后混入其他结构 | 不是完整十人表；只作旁证 |
| `0x75D7E988E000` 0x20 对象表 | 每 0x20 一条 vtable（`0x75DB20CA0080` 等） | 事件/技能对象池，不是玩家状态 |
| `0x75D7EA29B940` 等 hero 对象 | vtable `0x75DB20C9DC38`，字段=CSV 配置 | hero 配置，不是 live HP |

## 4. 金币整数与 0x20 事件记录

### 4.1 观察到的记录形式

arena 内存在大量 **0x20 字节周期**的记录，字段集固定为：

```text
{value, entityId, packedEvent, param, vtable, 1, sequence}
```

但不同 vtable/类的字段顺序不同。实测到三种排列：

**排列 A（value 在 +0x00）**：`0x75D7E989CEC0..0x75D7E989D040`

```text
+0x00 u32 value        8169 / 8168
+0x04 u32 entityId     1613 / 750 / 1611 / 296 / 538 / 1031 / 551 / 1799 / 1760
+0x08 u32 packedEvent  0x00890083 / 0x00000003 / 0x00570083 ...
+0x0C u32 param        0 / 1 / 2 ...
+0x10 qword vtable     0x75DB20CA0118 / 0x75DB20CA0080
+0x18 u32 1
+0x1C u32 sequence    3755 / 60378 / 60377 ...
```

**排列 B（vtable 在 +0x00）**：`0x75D7E987C2A0..0x75D7E987C3A0`

```text
+0x00 qword vtable     0x75DB20CA0670 / 0x75DB20CA0080 等
+0x08 u32 1
+0x0C u32 sequence    9927 / 63272 / 63271 ...
+0x10 u32 value       8697
+0x14 u32 entityId    1611 / 538 / 1031 / 296 / 551 / 1799 / 1760 / 1168 / 1613 / 750
+0x18 u32 packedEvent
+0x1C u32 param
```

**排列 C（1 在 +0x00，vtable 在 +0x18）**：`0x75D7E990B800..0x75D7E990B920`

```text
+0x00 u32 1
+0x04 u32 sequence    49394 / 49393 / 641 / 640 ...
+0x08 u32 value       6541 / 6540
+0x0C u32 entityId    1168 / 1613 / 1611 ...
+0x10 u32 packedEvent 0x00FFD60083 / 0x00FFF883 ...
+0x14 u32 param
+0x18 qword vtable     0x75DB20CA0080 / 0x75DB20CA2A10 等
```

三种排列的 `value`/`entityId`/`sequence` 语义一致，只是类布局不同。
周期 0x20 是实测的（连续 10 条记录的 vtable 指针间隔 0x20）。

### 4.2 金币值的证据

- `value` 字段在快照中取到了全部十个**官方终局面板金币**值：
  6540、8168、8352、9243、8697、6191、5828、5778、5977、5474。
  这是用 `data/replays/_analysis/datasets/20261102_official_players.csv`
  的 `panel_gold` 做 sanity（不用于生成逐帧值）。
- 同一组金币值会在多个不同 `entityId` 的记录里重复出现（最多覆盖十个
  fixture entity）。例如 8168/8169 出现在 1613、750、1611、296、538、1031、
  551、1799、1760 等记录里；6540/6541 出现在 1168、1613、1611 等记录里。
- 因此 `value` 是**被广播/同步的金币总量**，不是“该 entityId 的当前金币”。
  记录本身没有存储 owner 字段（或 owner 编码在 `packedEvent`/其它未解字段）。
- `sequence` 是全局事件序号（同一 vtable 内连续递减/递增），不是玩家 ID。
- 结论：金币值确实存在于 live 快照，且与终局面板金币同源；但**不能**把
  “value + 相邻 entityId”直接当逐人经济表。

### 4.3 十组金币值块（仅作 sanity，不是 owner 映射）

在 arena 中可找到十组 0x20 记录块，每组的 `value` 对应一个官方终局面板金币：

| value | 记录块起始（示例） | ctx 偏移 |
|---:|---:|---:|
| 8168/8169 | `0x75D7E989CEC0` | `+0x11B2ED0` |
| 6540/6541 | `0x75D7E990B800` | `+0x1221810` |
| 8697 | `0x75D7E987C2A0` | `+0x11922B0` |
| 8352 | `0x75D7E9891290` | `+0x11A72A0` |
| 9243 | `0x75D7E9859200` | `+0x116F210` |
| 6191 | `0x75D7E9922578` | `+0x1238588` |
| 5828 | `0x75D7E99395A0` | `+0x124F5B0` |
| 5778 | `0x75D7E993C970` | `+0x1252980` |
| 5977 | `0x75D7E992F2E0` | `+0x12452F0` |
| 5474 | `0x75D7E994E410` | `+0x1264420` |

注意：这些是“值块”地址，不是“某玩家对象”地址；不要根据 value 反推
owner 后写死。上表只证明快照包含这些终局金币值。

## 5. KDA / HP / 金币字段对照（排除项）

### 5.1 名册 `+0x24` 不是 KDA

官方终局 KDA（entity -> k/d/a）：

```text
1168 3/3/9   1613 6/1/7   750 5/1/5   538 8/1/7   1611 5/0/8
1031 1/5/2   296 2/7/2    551 2/3/3   1799 1/6/2  1760 0/6/4
```

名册 `+0x24`（entity 顺序 1168/1613/750/538/1611/1031/296/551/1760/1799）：
`4,1,8,1,1,11,5,10,9,9`。
逐项与 k/d/a 均不匹配；也不是 `k+d+a` 或 `k+a`。**判为未知标量**。

### 5.2 名册 `+0x24` 不是终局金币/等级

- 终局金币 5474..9243；`+0x24` 只有 1..11，数量级不符。
- 若把它当“千金币”单位，会得到 1000..11000，且两个 1000 与终局面板金币
  5474/5778 不符；没有证据支持这种缩放。
- 若把它当英雄等级，终局（frame≈10674）不应出现 1 级；与快照的终局性质
  矛盾。**判为未知标量**。

### 5.3 HP/KDA 字段

- hero 配置对象的 3295（MaxHp）/3600（移速）/46（物防）/172（物攻）等来自
  `0x111C3C` 基础属性表，是**配置值**；同一对象里没有“当前 HP/当前 MP”字段。
- 未在 arena 中找到十人 live HP 数组；未找到 KDA 三元组。
- `libGameCore.so` 中存在 `killCnt`、`assist_cnt`、`goldCoinNum`、
  `start_gold`、`total_gold` 等字符串，但它们落在属性注册/脚本绑定函数里
  （如 `0x2A00108`、`0x44FFF04`、`0x451EC9C`），没有给出可直接读的
  CPlayer/actor 偏移。

### 5.4 初始金币 300（配置已证，live 偏移未证）

- fixture 的 `init/level_context_candidate.json` 记录 `initialGold=300`，
  并标为 `m_originalGoldCoinInBattle`；
  `data/replays/_analysis/datasets/agent_normal5v5_levels.csv` 的 level
  20011 行 `wOriginalGoldCoinInBattle=300`。这是**配置/模式字段**。
- 在 arena 中搜索 u32 300 有 514 处命中，但绝大多数是零散小整数/指针低位；
  没有找到“300 + 十人金币/KDA”同构结构，也没有找到 10 条连续的 300。
- 结论：300 只能作为初始金币配置值引用；**不能**给出它在 live context/
  CPlayer 中的偏移。

## 6. 字段表（可直接引用的偏移）

| 对象/表 | 地址 | ctx 偏移 | 字段 | 置信度 |
|---|---:|---:|---|---|
| 包装 context | `0x75D7E86E9FF0` | 0 | `+0x00 self`, `+0x18 P+0x600` | high |
| binder P | `0x75D7EA4E99F0` | `+0x1DFFA00` | `+0x08 ref/version`, `+0x80 slot0`, `+0x88 slot1` | high |
| 索引表 | `0x75D7E8A36188` | `+0x34C198` | 10×0x10 `{hero,entity,slot,0}` | high |
| 名册表 | `0x75D7E8743494` | `+0x594A4` | 10×0x60；hero@0, camp@0xC, entity@0x14/0x18 | high |
| 名册容器指针 | `0x75D7EA4C2238` | `+0x1DD8248` | qword -> 名册表 | high |
| 名册计数 | `0x75D7EA4C2254` | `+0x1DD8264` | u32=10（`+0x1DD8260`=16） | high |
| hero 配置表 | `0x75D7E8A9E3E8` | `+0x3B43F8` | 0x20 步长；前 10 条为十名玩家 | medium-high |
| hero 配置对象 | 表内 ptr | — | vtable `0x75DB20C9DC38`；+0x10 HP 配置等 | medium-high |
| 金币事件块（A） | `0x75D7E989CEC0` | `+0x11B2ED0` | 0x20 周期，value@+0, entity@+4 | medium |
| 金币事件块（B） | `0x75D7E987C2A0` | `+0x11922B0` | 0x20 周期，value@+0x10, entity@+0x14 | medium |
| 金币事件块（C） | `0x75D7E990B800` | `+0x1221810` | 0x20 周期，value@+0x08, entity@+0x0C | medium |
| CPlayer 类 | `base+0x4348AF8` | — | size 0x168, vtable `base+0x4F5B0A8` | high（静态） |
| CPlayer 实例 | 未找到 | — | 快照内 0 命中 | high（不存在） |

## 7. 明确未知

1. **live 当前金币/累计获得/已花费的存储位置未定**。快照里只有广播式金币
   事件块，没有找到“每人一条 current/total/spent”的结构。
2. **金币事件块的 owner 未定**。`value` 不随相邻 `entityId` 变化，无法仅凭
   记录判断这是谁的金币；需要静态定位写入该记录的函数（谁写 +0x00/+0x10）。
3. **名册 `+0x24` 语义未定**。排除了 KDA、终局金币、英雄等级，但没有正面
   证据说明它是什么（可能是槽位/队伍内序号/AI 参数/账号等级）。
4. **live HP/KDA 未找到**。hero 配置对象的 MaxHp/移速/防御/攻击是静态配置；
   不能当当前值。
5. **CPlayer/CPlayerArr 是否在回放路径构造未定**。静态类存在，但快照无实例；
   可能走的是另一套 actor/event 结构。
6. **`P+0x4F0`/`P+0x578` 内嵌对象类型未定**；CS 槽 4/5 指向它们，但本次
   没有展开其字段。
7. **金币事件块的 `packedEvent` 编码未解**（低 16 位像事件类型，高位像
   子类型/参数；未与 `FRAME_CMD` 或协议结构对拍）。

## 8. 复现（只读）

```bash
# 1) 复核 P 与 CS 槽
python - <<'PY'
import sys
sys.path.insert(0, r'<临时目录>\kpl_a1_econ')
from mem import Mem
m = Mem()
P = 0x75d7ea4e99f0
print(hex(m.u64(P+0x80)), hex(m.u64(P+0x88)))
print(hex(m.u64(0x75d7e86e9ff0+0x18)), hex(P+0x600))
PY

# 2) 复核索引表
python - <<'PY'
import sys, struct
sys.path.insert(0, r'<临时目录>\kpl_a1_econ')
from mem import Mem
m = Mem()
for i in range(10):
    a = 0x75d7e8a36188 + i*0x10
    print(struct.unpack('<4I', m.read(a, 0x10)))
PY

# 3) 复核名册表与容器
python - <<'PY'
import sys, struct
sys.path.insert(0, r'<临时目录>\kpl_a1_econ')
from mem import Mem
m = Mem()
print(hex(m.u64(0x75d7ea4c2238)), 'cap?', m.u32(0x75d7ea4c2250), 'count', m.u32(0x75d7ea4c2254))
for i in range(10):
    a = 0x75d7e8743494 + i*0x60
    print(struct.unpack('<8I', m.read(a, 0x20)))
PY
```

> 上述脚本和快照都在本地临时/忽略目录；不提交原始快照，不把地址写成常量，
> 不把 `value` 当逐人金币写死。

## 9. 与官方数据的关系

- 只把官方 `20261102_official_players.csv` 的 `panel_gold` 当**终局 sanity**：
  快照中出现的 6540/8168/8352/9243/8697/6191/5828/5778/5977/5474 与它
  完全一致，说明快照确实包含终局金币值。
- 官方 `official_grow`（8000/10041/8614/10191/9633/6239/6567/6389/6874/6514）
  没有在快照的同一个十人数组里成组出现；它与 panel_gold 的差（1460/1873/…）
  很可能是已花费金币，但**没有在快照中定位到 spent 字段**，不能据此写
  “spent = grow - panel_gold” 的运行时结论。
- `level_economy_fields.csv` / `0x111C3C` CSV 只用于解释初始金币 300 和
  hero 配置字段，不用于生成逐帧值。
