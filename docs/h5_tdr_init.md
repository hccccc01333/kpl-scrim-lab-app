# H5 初始化 TDR/CS 线格式复核（11/2 `.abc` + GameCore/CSProtocol）

- 日期：2026-11-03
- 范围：只读静态分析 + 既有样本；不注入、不登录、不调用游戏函数、不改游戏文件。
- 样本：`data/replays/samples/20261102_161129/20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc`
  - 482,967 B，SHA-256 `d74c2bed9dc12ec6d23118fbb87b2a372993b358f1fec542ee492d580e0e64f4`
  - App 12.1.1.1 / Res 12.1.1.26 / build 5247758
- 静态权威：
  - `data/replays/_analysis/global-metadata.dat`（本地构建，416,645 方法）
  - `data/replays/_analysis/libGameCore.so`（5069040 / 12.1.1.8；与 11/2 样本不是同一构建）
  - 公开 TDR XML 仅作交叉验证：`Moli13337/Honor-of-Kings-protocol/tdr_xml`（旧协议快照，不是 12.1.1.26 构建）

## 0. 结论摘要

1. **11/2 的 1075 包是 `SCPKG_MULTGAME_BEGINLOAD`**。外层是 replay 的 `[i32 LE 负数长度]`，
   包内是 16 B `CSPkgHead`（4 个大端字段）+ TDR body。body 起点为文件 `0x10B`。
2. **`CSDT_DESK_SVR2GAMECORE_CONFIG` 的真实 TDR 线格式已由样本字节证明**：
   `u32 BE dwArrayNum` + `dwArrayNum × {u16 BE wKey, u16 BE wValue}`。
   11/2 样本中该结构位于文件 `0x1C1..0x298`，共 **216 B**；
   53 个 key/value 与 databin 表 83（`svr2GamecoreCfg`）完全同值，仅行序不同。
3. **`Svr2GameCoreInfo` 是 databin 行类型，不是 TDR 线类型**：
   `ResData.ResSvr2GameCoreInfo {wConfType, wConfValue}` 在 databin 里是
   `{u16 LE, u16 LE}` 4 B；TDR 线类型是
   `CSDT_DESK_SVR2GAMECORE_ITEM {u16 BE wKey, u16 BE wValue}`。
4. **没有可证明的 `Ntf`/`SetupClient` 初始化 TDR 包**。
   `SGW.SetupClient` / `SGW.StartLevel` 是托管方法（4/6 参数），
   `GameBuilderClientBase.NtfCoreSetupClient` / `NtfCoreStartGame` 是 0 参数托管方法；
   metadata 中没有 `SCPKG_*SETUPCLIENT*` 类型，11/2 样本里也只有 1075/1077/1251 三个 CSPkg。
5. **`.abc` 的 1075 payload 和帧命令 payload 都不能直接推给
   `PushCsBuffer`/`CommitCsBuffer`**。GameCore slot0 的消费者 `0x46B8070`
   读的是另一种记录流：
   `u32 header = (len:16 << 16) | id:16`（bit30 为标志），后跟 `len` 字节 payload；
   `id` 索引运行时 BSS 中的 handler 表。1075 body 与
   `CSDT_FRAPBOOT_INFO` 都没有这个记录头。
6. **缺失的 wrapper 是 C# 层的 GameBuilder/SGamePInvoke 序列化映射**：
   `frapInfo bType + union → CS command id + payload`、`len|id` 记录头、
   以及开局 `StartLevel/SetupClient` 的命令顺序。该映射在现有
   样本、metadata 和本地 libGameCore 中都没有落地。
7. **因此不存在“已证明的最小 CS 初始化命令流”**。本文只给出
   已证明的 216 B TDR 配置数据和它的精确解析；不编造命令 id 或 payload。

---

## 1. 11/2 `.abc` 包图（精确偏移）

| 文件偏移 | 长度 | 内容 | 置信度 |
|---|---:|---|---|
| `0x0000..0x00F6` | 247 | replay 头：4 个版本/构建串、hero/time/map、昵称/头像、13 B 扩展头 | 高（既有 `tools/replay_opening_packet.py`） |
| `0x00F7..0x00FA` | 4 | `i32 LE = -43333` | 高 |
| `0x00FB..0x00FE` | 4 | `CSPkgHead.dwMsgID = 0x00000433 = 1075`（BE） | 高 |
| `0x00FF..0x0102` | 4 | `iVersion = 0x00002F65 = 12133` | 高（字段名按 metadata；数值为实测） |
| `0x0103..0x0106` | 4 | `dwSvrPkgSeq = 1` | 高 |
| `0x0107..0x010A` | 4 | `dwReserve = 0` | 高 |
| `0x010B..0x0AA3F` | 43,317 | `SCPKG_MULTGAME_BEGINLOAD` TDR body | 边界高；字段映射部分 |
| `0x01C1..0x0298` | **216** | `CSDT_DESK_SVR2GAMECORE_CONFIG`（53 项） | **高** |
| `0x029A..0x0454` | 443 | 初始化标量块（110 × BE u32 + 3 B 尾） | 高（5.16.8/5.34） |
| `0x0455..0x09B3A` | — | 玩家块 1；共 10 块，最后一块起于 `0x9B3B` | 高（`docs/abc_to_level_context.md`） |
| `0x0AA40..0x0AA54` | 21 | 1077 包：`-17` + `CSPkgHead` + 1 B body | 高 |
| `0x0AA55..0x75E25` | — | 帧记录流：`[i32 LE 正数长度][u32 BE seq][u16 BE size][payload]` | 高（`tools/replay_record_stream.py`） |
| `0x75E26..0x75F56` | 113 | 1251 包：`-109` + `CSPkgHead` + 93 B body | 高 |

`CSPkgHead` 16 B 实测（文件 `0x00FB`）：

```text
00 00 04 33   dwMsgID       = 1075
00 00 2F 65   iVersion      = 12133
00 00 00 01   dwSvrPkgSeq   = 1
00 00 00 00   dwReserve     = 0
```

1077 包头实测（文件 `0x0AA40`）：

```text
EF FF FF FF   i32 LE = -17
00 00 04 35   dwMsgID     = 1077
00 00 2F 65   iVersion    = 12133
00 00 00 02   dwSvrPkgSeq = 2
00 00 A9 45   dwReserve   = 43333  (等于前一包 payload 长度；语义未证)
00            body（1 B）
```

> `dwReserve` 在这里恰好等于 1075 payload 的 43,333 B。它可能只是复用字段/统计值，
> 不能据此把 `CSPkgHead` 当成“长度+ID”封装；外层长度仍是前面的 `i32 LE`。

---

## 2. 1075 body 的前 12 B 与字段线索

body 从 `0x10B` 开始。前 12 B：

```text
0x10B  33 E0 62 30   u32 BE = 870,343,216   = 文件名第 1 段
0x10F  00 01 76 7C   u32 BE = 95,868        = 文件名第 2 段
0x113  6A E8 42 47   u32 BE = 1,793,606,215 = 文件名第 3 段（服务器 Unix 时间）
0x117  03            u8     = 3             = mapType
0x118  00 00 4E 8F   u32 BE = 20,111        = mapId
```

公开 XML 的 `SCPKG_MULTGAME_BEGINLOAD` 以
`iRelaySvrEntity:int32, dwDeskId:uint32, dwDeskSeq:uint32, dwCurTime:uint32` 开头；
上述三个值与文件名三段一一对应，支持“body 从 `0x10B` 开始、字段为大端”的判断。
但**当前 build 的字段顺序不能直接套旧 XML**：例如配置块在 `0x1C1` 就出现，
而旧 XML 把 `stSvr2GameCoreDataBin` 放在玩家块之后。本文只把
`0x10B` 起的前 12 B 当作“与文件名一致的标识字段”，不强行命名。

body 中紧邻配置块之前的两个 TDR 字符串（也是标准 `u32 BE 长度 + bytes`）：

```text
0x17B  00 00 00 22   u32 BE = 34
0x17F  "udp://cn.voice.gcloudcs.com:10001\0"   (34 B)

0x1A1  00 00 00 1C   u32 BE = 28
0x1A5  "4_8703432169586817936062150\0"         (28 B)
0x1C1  ← 配置结构从这里开始
```

这证明 1075 body 是标准 TDR（长度前缀 u32 BE），不是自定义的 `u8 length`。
`docs/abc_to_level_context.md` 把 `0x1A4` 读成 `u8 len=0x1C`，实际是
`0x1A1..0x1A4` 的 `u32 BE = 28` 的低字节；配置块偏移也因此被读成 `0x1C4`。

---

## 3. `CSDT_DESK_SVR2GAMECORE_CONFIG` 的真实 TDR 线格式

### 3.1 类型定义（metadata + 公开 XML 交叉）

metadata（`global-metadata.dat`，字段名权威）：

```text
CSProtocol.CSDT_DESK_SVR2GAMECORE_CONFIG
    astGameCoreCfgItems_length
    dwArrayNum
    astGameCoreCfgItems_bytes

CSProtocol.CSDT_DESK_SVR2GAMECORE_ITEM
    wKey
    wValue
```

公开 TDR XML（旧协议，字段类型/顺序交叉验证）：

```xml
<struct name="CSDT_DESK_SVR2GAMECORE_ITEM" version="1">
  <entry name="wKey"   type="uint16"/>
  <entry name="wValue" type="uint16"/>
</struct>

<struct name="CSDT_DESK_SVR2GAMECORE_CONFIG" version="1">
  <entry name="dwArrayNum"          type="uint32"/>
  <entry name="astGameCoreCfgItems" type="uint8" count="0"/>
</struct>
```

> GameCore 没有这些 C# 类型的 pack/unpack 导出；真正的 pack/unpack 是
> `Scripts.Tdr.dll` 里的托管生成代码。本文没有把本地 libil2cpp 的
> 可疑方法标签当入口，而是以 **metadata 字段名/顺序 + 11/2 1075 body 的实际字节**
> 为主证据，公开 XML 只用于交叉确认字段宽度/端序。这样得到的结论不依赖
> 未验证的托管方法地址。

### 3.2 11/2 实测线格式

```text
offset          size              field
0x1C1           4                 dwArrayNum = 53        (u32 BE)
0x1C5..0x298    53 × 4            CSDT_DESK_SVR2GAMECORE_ITEM[]
                                 每项 { wKey:u16 BE, wValue:u16 BE }
0x299           1                 00（下一字段/对齐；不属于数组）
```

- 数组元素固定 4 B；53 项 = 212 B；加 4 B 计数 = **216 B**。
- 相对位置：TDR body `+0xB6`（`0x1C1 - 0x10B`）；1075 payload `+0xC6`
  （`0x1C1 - 0x0FB`）。
- 没有任何额外的 `_length` 字段出现在计数前或数组后；
  样本中计数前是 deskId 字符串的 NUL（`0x1C0`），数组后是 `0x29A` 的标量块。
- `astGameCoreCfgItems_length` 很可能是 C# 侧的定长 buffer 元数据，
  不在线格式里单独出现；这一点是推断，置信度中。

### 3.3 216 B 精确字节

文件 `0x1C1..0x298`，SHA-256
`84dccaa04ae223dfa3aa2de10e5df515ebaabc38230b04d6561aece760df0905`：

```text
01C1  00 00 00 35 00 01 00 32 00 02 00 01 00 03 00 19
01D1  00 04 00 01 00 05 00 01 00 06 00 05 00 07 01 2C
01E1  00 08 00 7F 00 09 06 A4 00 0A 00 01 00 0C 00 00
01F1  00 0D 00 01 00 0E 00 32 00 0F 00 00 00 10 00 01
0201  00 11 13 88 00 12 00 00 03 17 00 01 00 13 01 2C
0211  00 14 00 05 00 3F 01 F4 00 40 00 00 00 42 00 00
0221  00 43 00 01 00 44 1F 40 00 45 0A F0 00 46 07 D0
0231  00 47 0B B8 00 48 0F A0 00 49 03 E8 00 4A 03 20
0241  00 4B 02 58 00 4C 01 90 00 4D 32 C8 00 4F 03 E7
0251  00 50 01 2C 00 51 00 05 00 52 00 01 00 53 00 00
0261  00 54 00 01 00 55 01 CE 00 58 00 19 00 59 00 01
0271  00 5A 00 01 00 5B 00 02 00 5C 07 D0 00 5E 00 46
0281  00 5F 00 08 00 60 00 01 00 61 00 64 00 62 00 00
0291  00 63 01 F4 00 69 01 F4
```

逐项解析（offset 为文件偏移；`wKey`/`wValue` 均为大端 u16）：

| # | offset | wKey | wValue |
|---:|---:|---:|---:|
| 1 | 0x01C5 | 1 | 50 |
| 2 | 0x01C9 | 2 | 1 |
| 3 | 0x01CD | 3 | 25 |
| 4 | 0x01D1 | 4 | 1 |
| 5 | 0x01D5 | 5 | 1 |
| 6 | 0x01D9 | 6 | 5 |
| 7 | 0x01DD | 7 | 300 |
| 8 | 0x01E1 | 8 | 127 |
| 9 | 0x01E5 | 9 | 1700 |
| 10 | 0x01E9 | 10 | 1 |
| 11 | 0x01ED | 12 | 0 |
| 12 | 0x01F1 | 13 | 1 |
| 13 | 0x01F5 | 14 | 50 |
| 14 | 0x01F9 | 15 | 0 |
| 15 | 0x01FD | 16 | 1 |
| 16 | 0x0201 | 17 | 5000 |
| 17 | 0x0205 | 18 | 0 |
| 18 | 0x0209 | 791 | 1 |
| 19 | 0x020D | 19 | 300 |
| 20 | 0x0211 | 20 | 5 |
| 21 | 0x0215 | 63 | 500 |
| 22 | 0x0219 | 64 | 0 |
| 23 | 0x021D | 66 | 0 |
| 24 | 0x0221 | 67 | 1 |
| 25 | 0x0225 | 68 | 8000 |
| 26 | 0x0229 | 69 | 2800 |
| 27 | 0x022D | 70 | 2000 |
| 28 | 0x0231 | 71 | 3000 |
| 29 | 0x0235 | 72 | 4000 |
| 30 | 0x0239 | 73 | 1000 |
| 31 | 0x023D | 74 | 800 |
| 32 | 0x0241 | 75 | 600 |
| 33 | 0x0245 | 76 | 400 |
| 34 | 0x0249 | 77 | 13000 |
| 35 | 0x024D | 79 | 999 |
| 36 | 0x0251 | 80 | 300 |
| 37 | 0x0255 | 81 | 5 |
| 38 | 0x0259 | 82 | 1 |
| 39 | 0x025D | 83 | 0 |
| 40 | 0x0261 | 84 | 1 |
| 41 | 0x0265 | 85 | 462 |
| 42 | 0x0269 | 88 | 25 |
| 43 | 0x026D | 89 | 1 |
| 44 | 0x0271 | 90 | 1 |
| 45 | 0x0275 | 91 | 2 |
| 46 | 0x0279 | 92 | 2000 |
| 47 | 0x027D | 94 | 70 |
| 48 | 0x0281 | 95 | 8 |
| 49 | 0x0285 | 96 | 1 |
| 50 | 0x0289 | 97 | 100 |
| 51 | 0x028D | 98 | 0 |
| 52 | 0x0291 | 99 | 500 |
| 53 | 0x0295 | 105 | 500 |

### 3.4 与 databin `83_svr2GamecoreCfg` 对拍

`data/replays/_analysis/device/dtab_blocks/83_svr2GamecoreCfg.bytes.bin`
（`stdr`，`0x98` 头 + 53 行 × 4 B）逐行读作
`{u16 LE wConfType, u16 LE wConfValue}`：

- 53 个 key 集合与 53 个 value **完全一致**；
- 仅行序不同：TDR 数组把 `791` 放在第 18 项，databin 把它放在
  `80/81/82` 三项之后；`80/81/82`、`89/90/91/92` 的相对顺序也不同；
- 这不是解析偏移问题：把 TDR 项逐项与 databin 的 `key→value` 字典比较，
  53/53 全部相等。

因此：

- **数据身份**：`CSDT_DESK_SVR2GAMECORE_CONFIG` 就是
  `svr2GamecoreCfg` 表的服务器行序子集；
- **字节方向**：databin 是本地内存（LE），TDR 是网络线序（BE）；
- **行序**：以 TDR 数组的顺序为准，不能拿 databin 行序当线序。

### 3.5 对既有文档的修正

| 既有说法 | 本次实测 | 影响 |
|---|---|---|
| `0x1C4: u16 LE count=53`，`0x1C6` 起每项 `{u8 key, u16 BE value, u8 pad}` | **正确框架是 `0x1C1: u32 BE count=53`，`0x1C5` 起每项 `{u16 BE key, u16 BE value}`** | 配置块起点前移 4 B；每项解释从“key u8 + pad”改为“key u16 BE” |
| `.abc` 有 key 23=1、103=500；databin 有 791=1、105=500 | **两边的 key 集合完全相同**；本样本 TDR 第 18 项就是 791=1，最后一项 105=500；没有 key 23 | 5.16.7 的差异描述是错位读法的产物 |
| `0x1A4: u8 len=0x1C` + 28 B deskId | **`0x1A1..0x1A4: u32 BE=28` + 28 B** | 1075 body 是标准 TDR u32 长度前缀 |

---

## 4. `Svr2GameCoreInfo` 与 TDR item 的关系

| 层 | 类型 | 字段 | 字节序/宽度 | 证据 |
|---|---|---|---|---|
| databin 行 | `ResData.ResSvr2GameCoreInfo` | `wConfType`, `wConfValue` | `{u16 LE, u16 LE}` 4 B | metadata 字段名 + `83_svr2GamecoreCfg.bytes.bin` 实测 |
| TDR 线 | `CSProtocol.CSDT_DESK_SVR2GAMECORE_ITEM` | `wKey`, `wValue` | `{u16 BE, u16 BE}` 4 B | 公开 TDR XML + 11/2 配置块逐字节 |
| TDR 容器 | `CSProtocol.CSDT_DESK_SVR2GAMECORE_CONFIG` | `dwArrayNum` + item[] | `u32 BE` + N×4 B | 公开 TDR XML + 11/2 字节 |

**不要把 `Svr2GameCoreInfo` 的 databin 行字节直接当 TDR 线字节**：
两者的 key/value 相同，但每个 u16 的端序相反；且 databin 行序不是 TDR 数组行序。

---

## 5. 帧命令 payload：`SCPKG_FRAPBOOT_SINGLE` / `CSDT_FRAPBOOT_INFO`

### 5.1 外层记录

`tools/replay_record_stream.py` 已证明：正长度记录为

```text
[i32 LE 正数长度][u32 BE dwKFrapsNo][u16 BE wLen][wLen B payload]
```

长度 = `6 + wLen`。这与公开 TDR XML 的
`SCPKG_FRAPBOOT_SINGLE {dwKFrapsNo:uint32; wLen:uint16; szInfoBuff[]}` 对齐。
`i32 LE` 是 replay 容器，不属于 TDR 结构。

### 5.2 payload 结构

payload 是 `CSDT_FRAPBOOT_INFO` 的 TDR 序列化：

```text
u8 bNum
bNum × {
    u8 bType
    UN_FRAPBOOT_DT（按 bType 选择成员）
}
```

11/2 的 **第一个非空帧**（记录起于文件 `0x0AA6B`，命令 payload 起于 `0x0AA75`，
`dwKFrapsNo=3`，`wLen=169`）payload 开头：

```text
18                          bNum = 24
01 02 EE 00 02 14 02        entry 1: bType=1 (CC), wObjID=0x02EE=750,
                            CSDT_GAMING_CCSYNCINFO { wLen=2, szBuff=14 02 }
01 06 4D 00 02 14 02        entry 2: bType=1, wObjID=0x064D=1613, wLen=2, 14 02
...
```

这与公开 XML 的 `CSDT_FRAPBOOT_DETAIL {bType:u8; stDetail:UN_FRAPBOOT_DT}`、
`CSDT_FRAPBOOT_CC {wObjID:u16; stSyncInfo:{wLen:u16; szBuff[]}}` 一致。
`docs/advance_frame_commands.md` 的 27 类 `frapInfo` 命令表也是这个结构。

### 5.3 它不是 GameCore slot0 的记录流

见第 6 节。`bNum` 前缀、`bType` 字节和 union payload 都不是 slot0 消费者读取的
`u32 header + payload` 形式。

---

## 6. GameCore slot0 的真实 CS 记录格式（本地 5069040 构建）

### 6.1 消费链

```text
0x46B80E8
  x0 = [base+0x544CC40]            ; consumer/buffer object
  x1 = [base+0x52C3250]            ; slot0 ring object
  bl 0x49CBC0C                     ; ring read -> consumer buffer
  x0 = consumer buffer base
  w8 = [consumer+0xC]              ; used bytes
  x1 = base + used
  br 0x46B8070                     ; parse records
```

`0x46B8070` 的逐条记录逻辑（反汇编关键指令）：

```asm
0x46B8094  ldr  w8, [x0], #4        ; header = *(u32*)p; p += 4
0x46B8098  ldr  w10, [x20, #0x368]  ; count = *(u32*)(base+0x5272368)
0x46B80A0  and  x9, x8, #0xffff     ; id = header & 0xFFFF
0x46B80A4  cmp  w9, w10
0x46B80A8  b.hs 0x46B80D8           ; id >= count -> stop
0x46B80AC  lsl  x9, x9, #4          ; id*16
0x46B80B0  ldr  x10, [x21, #0x340]  ; table = *(u64*)(base+0x544D340)
0x46B80B4  tst  w8, #0x40000000     ; bit30 flag
0x46B80B8  lsr  w2, w8, #0x10       ; len = header >> 16
0x46B80BC  cset w1, eq              ; flag = !(header & 0x40000000)
0x46B80C4  ldr  x9, [x10, x9]       ; handler = table[id*16]
0x46B80C8  blr  x9                  ; handler(&p, flag, len)
```

因此 slot0 的一条记录是：

```text
u32 LE header = (len << 16) | id
len B payload
```

- `id` 是 16 位，索引 `*(u64*)(base+0x544D340) + id*16` 处的 handler；
- `len` 是 16 位，最大 65,535；
- bit30 清零时 `flag=1`，置位时 `flag=0`（语义未证）；
- handler 自己负责从 payload 读取并推进 `p`，循环由 `p < end` 控制。

宿主侧要使用 slot0 时，调用顺序是
`PushCsBuffer(total_len)` 取 staging 指针 → 写入 `total_len` 字节的上述记录流 →
`CommitCsBuffer()`。**Push/Commit 本身不是障碍；障碍是记录流的内容**
（id 与每类 payload 的 schema）。

### 6.2 立即包路径

`FlushCsImmediatePackBuffer`（导出 `0x460A3A0` → `0x460A364`）：

```asm
0x460A368  ldr  w8, [x0], #4        ; u32 id
0x460A36C  ldr  x9, [x9, #0x340]    ; table = *(u64*)(base+0x544D340)
0x460A370  lsl  x8, x8, #4
0x460A378  ldr  x8, [x9, x8]        ; handler = table[id]
0x460A380  mov  w1, #1
0x460A384  mov  w2, wzr
0x460A388  blr  x8                  ; handler(&p, 1, 0)
```

立即包格式是 `u32 id + payload`，没有 `len` 字段；payload 长度由 handler 自己按 id 决定。
这与 slot0 的 `len|id` 记录不同，但共用同一张 handler 表。

### 6.3 表的可见性

- `[base+0x5272368]`（count）和 `[base+0x544D340]`（table 指针）都是 **BSS，静态为 0**；
  本地 `.so` 和已捕获的 context 快照里都没有它们的运行期内容。
- `0x507E0B8` 起 41 个 RELA 项（最后一项 `0x507E1F8`）指向
  `0x544D3E0..0x544D408` 的 **41 个单字节**，形态上像“每命令一个标志位”；
  这只是候选，不能据此断言表正好 41 项。
- 没有导出可用于注册/查询 handler；表由内部初始化代码在运行期建立。

**结论**：slot0 的记录框架是确定的，但 id 空间和每个 id 的 payload schema
在静态输入里不可见。

---

## 7. 为什么 1075 payload 不能直接 Push

### 7.1 1075 payload 的开头不是记录头

1075 payload 从 `0x00FB` 开始，前 4 B 是 `00 00 04 33`（BE msgID 1075）。
如果按 slot0 记录头解释（小端 u32）：

```text
header = 0x33040000
id     = 0x0000
len    = 0x3304 = 13,060
flag   = 1（bit30=0）
```

`id=0` 指向 handler 0，payload 会从 `0x00FF`（`00 00 2F 65 ...`）开始，
而不是从 TDR body 的 `0x010B` 开始；配置块更在后面 `0x1C1`。
即使 id=0 恰好是某个合法命令，它拿到的也是 `iVersion/seq/reserve`，
不是 desk 配置。

如果从 body 起点 `0x010B` 开始推，前 4 B 是 `33 E0 62 30`：

```text
header = 0x3062E033
id     = 0xE033 = 57,395
len    = 0x3062 = 12,386
```

`id=57,395` 远大于任何合理的 41 项级表；消费者会直接 `id >= count` 返回。
无论从哪个起点，都不能把 `CSDT_DESK_SVR2GAMECORE_CONFIG` 送到 handler。

### 7.2 帧 payload 的开头也不是记录头

帧 payload 以 `bNum:u8` 开头。以记录 `0x0AA6B`、命令 payload `0x0AA75`
的帧 3 为例，前 4 B `18 01 02 EE` 按记录头读：

```text
id  = 0x0118 = 280
len = 0xEE02 = 60,930
```

同样不是 `{id, len}` 的合法组合。帧 payload 是 `CSDT_FRAPBOOT_INFO`，
必须由上层拆成 `bType` 和 union，再映射到 CS command id；这一步没有完成。

### 7.3 缺失的 wrapper（明确清单）

| 缺失项 | 现状 | 为什么不能绕过 |
|---|---|---|
| `bType/union → CS command id` 映射 | 只有客户端 27 类 `frapInfo` 类型表和 GameCore 41 项级 handler 表，二者没有对照 | id 错会把 payload 交给错误 handler |
| 每类命令的 payload TDR schema | `CSDT_FRAPBOOT_*` 是客户端结构；GameCore handler 读的是自己的字段布局 | 不能把 `CSDT_FRAPBOOT_CC` 字节原样塞进任意 id |
| `len|id` 记录头发射 | `.abc` 帧记录只有 `dwKFrapsNo/wLen/szInfoBuff`，没有 CS 记录头 | 需要 C# 序列化层逐条写 header |
| 开局 `StartLevel/SetupClient` 命令顺序 | `GameBuilder` 生命周期是托管编排；没有 wire 记录 | 1075 只是数据包，不是 GameCore 开局命令 |
| handler 表 count/id | BSS，静态 0；context 快照未包含 | 无法验证 id 合法性或 payload 长度 |

---

## 8. `Ntf` / `SetupClient` 初始化包：不存在可证明的 wire

metadata 证据：

| 符号 | token | 参数数 | 性质 |
|---|---|---:|---|
| `SGW::StartLevel` | `0x600150F` | 6 | 托管方法，非 TDR 类型 |
| `SGW::SetupClient` | `0x6001510` | 4 | 托管方法，非 TDR 类型 |
| `SGW::SetupClientImme` | `0x6001511` | 4 | 托管方法 |
| `GameBuilderClientBase::NtfCoreSetupClient` | `0x6008A9A` | 0 | 托管编排方法 |
| `GameBuilderClientBase::NtfCoreStartGame` | `0x6008A99` | 0 | 托管编排方法 |

- 对 metadata 的 **类型名**（`namespace.type`）搜索
  `SetupClient|NtfCoreSetupClient|SCPKG.*SETUP`：**0 个类型**；
  `SetupClient`/`NtfCoreSetupClient` 只是方法名，不是 TDR 结构。
- 11/2 样本的 CSPkg 只有 1075、1077、1251；没有 SetupClient/Ntf 包。
- `docs/replay_binary_format.md` 5.16.3 的
  `Initialize → BuildPlayers → AddHero → BuildCSharpPlayerHeroData →
  NtfCoreSetupClient → NtfCoreStartGame → PreBeginPlay → ...`
  是 C# 编排骨架，不是 FIFO 字节流。

因此：**`SetupClient` 的 TDR/CS 线格式没有证据，不能从 1075 或 metadata 推出。**

---

## 9. 能交给 H5 的最小真实字节

### 9.1 已证明可用作“数据”的 216 B

文件 `0x1C1..0x298` 的 216 B 是唯一已证明的初始化 TDR 结构：

```text
u32 BE 53
53 × {u16 BE wKey, u16 BE wValue}
```

它可以直接作为 `CSDT_DESK_SVR2GAMECORE_CONFIG` 的 TDR body 使用
（例如在宿主侧重新封装到 `SCPKG_MULTGAME_BEGINLOAD` 的对应字段），
前提是目标构建的 pack 仍按同一 XML 结构；11/2 样本本身已逐字节验证。
但它**不是** GameCore CS 命令，不能单独 `PushCsBuffer`。

### 9.2 不存在已证明的最小 CS 初始化命令流

严格按现有证据，最小候选命令流为 **空**。原因：

1. 没有证明任何 init command id；
2. 没有证明 `StartLevel/SetupClient/NtfCore*` 的 payload schema；
3. 没有证明 1075/frapInfo 到 CS 记录的映射；
4. handler 表在目标进程运行期才存在，静态文件无法给出 id→handler 对照。

如果后续要补，最小验证顺序应是：

1. 在真实进程里只读抓 `[base+0x544D340]`（table）和
   `[base+0x5272368]`（count），得到 id 空间；
2. 对每个 handler 的首几条指令确认它读取的 payload 长度/字段；
3. 用 `FlushCsImmediatePackBuffer` 的 `u32 id + payload` 形式做单命令试验，
   而不是直接猜 slot0 记录；
4. 只有单命令被 handler 接受后，才谈 `StartLevel` 的命令顺序。

---

## 10. 置信度表

| 结论 | 置信度 | 证据 |
|---|---|---|
| 1075 = `SCPKG_MULTGAME_BEGINLOAD`，CSPkgHead 16 B | 高 | metadata msgID 映射 + 样本字节 + 公开 XML |
| body 起点 `0x10B`，前 12 B 与文件名三段一致 | 高 | 字节逐项相等 |
| 配置块起于 `0x1C1`，`u32 BE count=53` | 高 | 前后 TDR 字符串边界 + 53 项与 databin 同值 |
| 每项 `{u16 BE wKey, u16 BE wValue}` | 高 | 216 B 逐字节 + 公开 XML |
| 53 项与 databin 同值、仅行序不同 | 高 | 逐 key 字典比较 53/53 |
| 帧 payload = `CSDT_FRAPBOOT_INFO` | 高 | 公开 XML + 27 类客户端解码器 |
| slot0 记录头 `(len<<16)|id` + handler 表 | 高（5069040 构建） | `0x46B8070`/`0x460A364` 反汇编 |
| 该记录框架同样适用于 5247758 | 中 | 结构稳定但未在 5247758 上复核 |
| 1075/frapInfo 不可直接 Push | 高 | 记录头逐字节不匹配 |
| 缺失 wrapper 是 C# 序列化层 | 中-高 | 没有其他候选；托管方法与样本均无 wire |
| handler 表规模约 41（候选） | 低-中 | 静态 41 字节标志区，非直接计数 |
| `astGameCoreCfgItems_length` 不在线格式 | 中 | 样本中计数前后都没有该字段 |

---

## 11. 复现（只读）

```bash
# 1. 1075 包边界 / 帧记录边界
python tools/replay_record_stream.py \
  data/replays/samples/20261102_161129/*.abc

# 2. 216 B 配置块解析（本文结论）
python - <<'PY'
import struct
p = r"data/replays/samples/20261102_161129/20261102_161129_870343216_95868_1793606215_2B9FAA08A7AD40D09ABDA364F9C1E804.abc"
d = open(p, "rb").read()
n = struct.unpack_from(">I", d, 0x1C1)[0]
print(n, [struct.unpack_from(">HH", d, 0x1C5 + 4*i) for i in range(n)][:5])
PY

# 3. 与 databin 表 83 对拍
python - <<'PY'
import struct
d = open(r"data/replays/_analysis/device/dtab_blocks/83_svr2GamecoreCfg.bytes.bin","rb").read()
print([struct.unpack_from("<HH", d, 0x98 + 4*i) for i in range(53)][:5])
PY

# 4. GameCore slot0 解析器 / 立即包路径
cd data/replays/_analysis/tools
python gcore_disasm.py 0x46b8070 0x100
python gcore_disasm.py 0x46b80e8 0x60
python gcore_disasm.py 0x460a364 0x40
```

---

## 12. 对现有文档的影响

- `docs/replay_binary_format.md` 5.16.4 / 5.16.7 的 KV 值清单仍然正确；
  但当前 TDR 线格式应按本文的
  `u32 BE dwArrayNum + {u16 BE wKey, u16 BE wValue}[]` 理解，
  不能把 `.abc` 的 4 B 项继续描述成 `{u8 key, u16 BE value, pad}`。
- `docs/abc_to_level_context.md` 的配置块偏移应从 `0x1C4` 修正为 `0x1C1`；
  443 B 标量块起点 `0x29A` 不变。
- `docs/simulation_plan.md` S3 的“TDR 封装未知”对 **CS 命令流** 仍然成立；
  但 **配置数据的 TDR 线格式** 已解决，可以缩小缺口范围。
- `docs/context_transplant_a1.md` 的“初始化命令 TDR 线格式仍未证明”仍然正确：
  本文证明的是配置结构，不是 GameCore 初始化命令。

## 2026-11-03 H5 实测补充

真实 `.abc` frame payload 直接 push 到 slot0 时：

- 1 字节帧（opcode 0）能被 consumer drain；
- 169 字节帧被解析成 opcode 280、handler `0x4707d64`，consumer 在
  `base+0x46bfe64` 崩溃。

因此没有“直接 push 原始 frame payload”的路线；必须有 C#/GameBuilder/TDR
包装层把 `CSDT_FRAPBOOT_INFO` 转成 native CS `len|op` 记录。当前未找到该包装层。
