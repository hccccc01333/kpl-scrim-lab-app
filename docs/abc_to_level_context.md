# `.abc` 初始化头 → `CLevelContext`/`deskPool` 中间结构

日期：2026-11-03。样本：11/2 第一局（`replayId=20261102_161129`）。
产物：`host/fixtures/20261102_161129/init/level_context_candidate.json`。

本文只描述**能从 `.abc` 头部直接读出的字段**，以及它们到 GameCore
`CLevelContext`/`deskPool` 的候选映射。未知字段一律置 `null`，不按字段表猜值。
本轮没有注入、没有登录、没有改游戏文件，也没有读取账号/token/avatar。

## 1. 结论摘要

- 11/2 样本是 **12.1.1.1 / 12.1.1.26，build 5247758**，布局与 5069040 旧样本不同：
  KV 在 `0x1C4`，443B 标量块在 `0x29A`，第一个玩家块在 `0x455`，
  帧流在 `0xAA5C`。**不能套 5.16.5 的 `0x018D/0x0263/0x041E/0xBFE8` 偏移。**
- 53 条 KV、443B 标量块、10 个玩家块、10,509 条帧记录均独立解析成功，
  与 `host/fixtures/20261102_161129/init/abc_header.json`、`players.json` 交叉一致。
- 可直接落到中间结构的已知字段：
  - 版本/构建 4 串、`localHeroId=196`、`mapType=3`、`mapId=20111`、
    `startTimeTicks=639292319602028870`、`totalFrameNum=10674`；
  - KV 53 条；其中 `confType=1 → 50`（模式）、`7/19/80 → 300`（初始金币）；
  - 标量块 `index 1 → 89,497,376`（modeWord）、`index 2 → 300`（初始金币）、
    `index 67 → 1,793,606,215`（服务器 Unix 时间）；
  - 十人 `camp/slot/entityId/heroId/nameSha256`，以及每个玩家块的精确偏移。
- 仍然不能直接构造 `CLevelContext/deskPool`：CLevelContext 的 285 个字段没有
  字节偏移表，443B 的字段顺序也不等于 C# 声明顺序；KV/443B/玩家块是**数据**，
  不是可 Push 的 CS/TDR **命令流**。详见第 9 节。

## 2. 输入与校验

| 项 | 值 |
|---|---|
| 回放 ID | `20261102_161129` |
| `.abc` 大小 | 482,967 B |
| `.abc` SHA-256 | `d74c2bed9dc12ec6d23118fbb87b2a372993b358f1fec542ee492d580e0e64f4` |
| 头部（0..1109）SHA-256 | `d68ec1205ce2c56dc5d91ae09fb962ffffe148acf01e9cc25951e128b55e2ac9` |
| KV（452..666）SHA-256 | `2314a8a091a3613990eef750413c9e11089f9b2be66868deea6fc52ebda67e2e` |
| 443B 标量块 SHA-256 | `bd3b9e7f6508bf6e651dddd1100670339ad8cff6281cca19d5cf2c07a7b9bd99` |
| 帧流 | 43,612（`0xAA5C`）..482,861（`0x75E2D`），10,509 条，尾部 106 B |

解析方法：在本任务里用独立字节解析器按 `len+UTF-8`、`u32LE/u16BE`、玩家块
`camp/slot/entity/nameLen/name/s+0x48` 逐段读取；`replay_parser.parse_header`
和 `host/scripts/make_fixture.py` 只用于交叉核对，不作为输入。玩家名只保留
SHA-256，原始昵称、头像 URL、账号字段不进入产物。

## 3. 容器总览（本构建实测偏移）

```text
0x0000  appVersion        "12.1.1.1"        7-bit len=8
0x0009  resourceVersion   "12.1.1.26"       7-bit len=9
0x0013  revision          "4989537"         7-bit len=7
0x001b  build             "5247758"         7-bit len=7
0x0023  localHeroId       u32LE = 196
0x0027  startTime         i64LE = 639292319602028870  (.NET DateTime ticks)
0x002f  mapType           u8 = 3
0x0030  mapId             u32LE = 20111
0x0034  userName          7-bit len=15 + UTF-8   (redacted)
0x0044  userHead          7-bit len=159 + URL    (redacted)
0x00e5  rankGrade         u8 = 14                (omitted)
0x00e6  rankClass         u32LE = 0              (omitted)
0x00ea  tail13            [u32LE=4][5B zero][u32LE totalFrameNum=10674 @0x00f3]
0x00f7  pre-KV residual   205 B                 (timestamps/voice/deskId/unknown)
0x01c4  KV                u16LE count=53 + 53×4 B, end 0x029a
0x029a  443B scalar       110×u32BE + 3B tail 00 00 0a, end 0x0455
0x0455  player block 0    ... 10 blocks, last starts 0x9b3b
0xaa5c  first frame stream 10,509 records, end 0x75e2d
tail    106 B               (roster/score tail; not decoded here)
```

`startTime` 是 .NET DateTime ticks（`docs/abc_ope_field_dictionary.md`），
但时区/时钟未确认，因此 JSON 里只保留 `startTimeTicks`，`startTimeIso` 为
`null`。`totalFrameNum` 在 `0x00f3`（13B tail 的最后 4B），不是 `0x00ea` 的
第一个 u32。

### 3.1 头部残余区（0x00F7..0x01C3，205 B）

这一段不是 KV，也不是玩家块。已知锚点：

| 偏移 | 形状 | 值/说明 | 处理 |
|---:|---|---|---|
| 0x0113 | u32BE | 1,793,606,215 | 与标量块 index 67、文件名 10 位段一致；字段名未定，置 null |
| 0x011e | u32BE | 1,793,606,361 | 比前一值大 146 s；字段名未定，置 null |
| 0x017e | u8 len=34 + URL | 语音服务器 URL | 与初始化无关，不复制 |
| 0x01a4 | u8 len=28 + UTF-8 | `4_8703432169586817936062150\0` | `deskIdText`，放入 `deskPool` |

其余字节没有字段名，`unknown.headerResidual.preKvRegion.fieldMapping=null`。
账号/身份字段（userName、userHead、rankGrade、rankClass）只记录“已省略”，
不写原始值。

## 4. KV 块（Svr2GameCore 配置）

### 4.1 布局

```text
0x01c4  u16LE count = 53
0x01c6  count × {u8 confType, u16BE confValue, u8 trailingByte}   4 B/条
0x029a  end
```

### 4.2 53 条清单（`confType → confValue`）

```text
1→50  2→1  3→25  4→1  5→1  6→5  7→300  8→127  9→1700  10→1
12→0  13→1 14→50 15→0 16→1 17→5000 18→0 23→1 19→300 20→5
63→500 64→0 66→0 67→1 68→8000 69→2800 70→2000 71→3000 72→4000
73→1000 74→800 75→600 76→400 77→13000 79→999 80→300 81→5
82→1 83→0 84→1 85→462 88→25 89→1 90→1 91→2 92→2000 94→70
95→8 96→1 97→100 98→0 99→500 105→500
```

### 4.3 已知语义（只列有文档依据的）

| confType | 值 | 映射 | 证据 |
|---:|---:|---|---|
| 1 | 50 | `gameMode` / 候选 `m_gameType` | 5.45.5：正常 5v5 = 50 |
| 7 | 300 | `initialGold` | 5.55：KV key 7/19/80 |
| 19 | 300 | `initialGold` | 同上 |
| 80 | 300 | `initialGold` | 同上 |

其余 49 个 key 的语义为 `null`。`94/95` 已知随对局变化
（5.16.7：94={70,100}、95={8,12}），但**没有字段名**，JSON 只记录
`matchVaryingConfTypes=[94,95]`，不赋值。

### 4.4 与 databin `svr2GamecoreCfg`（index 83）对拍

本地表：`data/replays/_analysis/device/dtab_blocks/83_svr2GamecoreCfg.bytes.bin`，
53 行 × 4 B，行数据从 `+152` 开始，表路径
`Databin/Public/Global/svr2GamecoreCfg.bytes`。

| 项 | 结果 |
|---|---|
| 共同 key | 52 |
| 值不一致 | 0 |
| `.abc` 独有 | `23` |
| 本地表独有 | `791` |
| 行序 | 不完全相同（`77` 之后出现差异） |
| 第 4 字节异常 | 仅 `confType=18` 为 `3`，其余 52 行为 `0` |

结论：`.abc` 保存的是服务器表的一个**行序子集**；本地 databin 表可以作为
默认值模板，但要按 `.abc` 的 key 集合覆盖，不能直接按行号套。`105=500`
在本 11/2 样本里发送；5.16.7 的旧 25 样本没有发送 105，这是构建/样本差异。

## 5. 443B 初始化标量块

### 5.1 布局

```text
0x029a..0x0454   443 B
  0x029a + i*4    i=0..109: u32BE
  0x0452          00 00 0a  (最后 3 B)
```

110 个大端 u32 与 5.16.8 的标准 5v5 结构一致；整段 SHA-256 =
`bd3b9e7f6508bf6e651dddd1100670339ad8cff6281cca19d5cf2c07a7b9bd99`。

### 5.2 已知锚点

| index | 块内偏移 | 值 | 映射 | 证据 |
|---:|---:|---:|---|---|
| 1 | `0x004` | 89,497,376 (`0x05559F20`) | `modeWord`（文档标签） | 5.16.8；语义未定，不映射 CLevelContext 字段 |
| 2 | `0x008` | 300 | `initialGold` / `m_originalGoldCoinInBattle` | 5.55；KV 7/19/80 同为 300 |
| 67 | `0x10c` | 1,793,606,215 | `serverTimeUnixSeconds` | 5.16.8；与文件名 10 位段、0x113 BE32 一致 |

其余 **107 个索引**的语义为 `null`。JSON 保留
`rawWordsBigEndianForDifferentialTesting` 仅用于离线差分/对拍，不进入宿主
字段注入。特别不要把 5.34 的“常量 300/1000/7/5…”直接命名为规则字段：
那只是旧 5069040 样本的分类结果，且 443B 顺序不等于 CLevelContext 声明顺序。

## 6. 玩家块与 `deskPool`

### 6.1 单块布局（本构建）

```text
+0x00  u8      camp            1|2
+0x01  u8      teamEcho        恒 == camp
+0x02  u8      0x01
+0x03  u8      slot            0..4
+0x04  u16BE   reserved        0
+0x06  u16BE   entityId
+0x08  u32BE   accountLevel    (omitted)
+0x0c  u32BE   nameLen
+0x10  bytes   name            (raw omitted; only SHA-256 kept)
s = block + 0x10 + nameLen + 30
s+0x48 u16BE   heroId
s+0x6f u16BE   heroId 副本
...            profile/social blob（未解，账号/身份字段不复制）
```

### 6.2 十个块（精确偏移）

| order | camp | slot | block | nameLen@ | name@ | s | heroId@ | heroIdDup@ | entity | hero | self |
|---:|---:|---:|---|---|---|---|---|---|---:|---:|---|
| 0 | 1 | 0 | 0x0455 | 0x0461 | 0x0465 | 0x048e | 0x04d6 | 0x04fd | 1168 | 175 | false |
| 1 | 1 | 1 | 0x146a | 0x1476 | 0x147a | 0x14a8 | 0x14f0 | 0x1517 | 1613 | 109 | false |
| 2 | 1 | 2 | 0x2615 | 0x2621 | 0x2625 | 0x2654 | 0x269c | 0x26c3 | 750 | 167 | false |
| 3 | 1 | 3 | 0x399a | 0x39a6 | 0x39aa | 0x39da | 0x3a22 | 0x3a49 | 538 | 140 | false |
| 4 | 1 | 4 | 0x4a4f | 0x4a5b | 0x4a5f | 0x4a8d | 0x4ad5 | 0x4afc | 1611 | 196 | **true** |
| 5 | 2 | 0 | 0x5d82 | 0x5d8e | 0x5d92 | 0x5dba | 0x5e02 | 0x5e29 | 1031 | 199 | false |
| 6 | 2 | 1 | 0x6d33 | 0x6d3f | 0x6d43 | 0x6d6b | 0x6db3 | 0x6dda | 296 | 123 | false |
| 7 | 2 | 2 | 0x7c7c | 0x7c88 | 0x7c8c | 0x7cb4 | 0x7cfc | 0x7d23 | 551 | 141 | false |
| 8 | 2 | 3 | 0x8c30 | 0x8c3c | 0x8c40 | 0x8c6b | 0x8cb3 | 0x8cda | 1799 | 153 | false |
| 9 | 2 | 4 | 0x9b3b | 0x9b47 | 0x9b4b | 0x9b76 | 0x9bbe | 0x9be5 | 1760 | 156 | false |

- `s` 公式：`s = block + 0x10 + nameLen + 30`；`heroId` 在 `s+0x48`，
  副本在 `s+0x6f`，本轮 10/10 块两者相同。
- `self` 由 `heroId == localHeroId(196)` 判定，只有 order 4 为 true。
- `bot` 没有从块内独立解码，JSON 保持 `null`。`scope_11_2.md` 说两局都是
  10 真人 0 机器人，但该结论不当作块字段。
- 玩家名只保留 `nameSha256`；原始昵称、账号等级、hash1、accountValue1..8、
  openID、头像/社交 URL 都不进入 fixture。

### 6.3 `deskPool` 候选

JSON 的 `deskPool` 目前只有“十人已知元组”：

```json
{
  "count": 10,
  "campIdsObserved": [1, 2],
  "entryOrder": "camp 1 slot 0..4，随后 camp 2 slot 0..4",
  "protocol": {
    "itemType": "CSProtocolWrapper.CSDT_DESK_SVR2GAMECORE_ITEM",
    "configType": "CSProtocolWrapper.CSDT_DESK_SVR2GAMECORE_CONFIG"
  },
  "deskIdText": "4_8703432169586817936062150",
  "entries": [
    {"order": 0, "camp": 1, "slot": 0, "entityId": 1168, "heroId": 175,
     "deskEntryIndex": null, "playerDeskSlot": null, "aiLevel": null,
     "rawItemBytes": null}
  ]
}
```

> 上面只展示第 1 条；实际 `entries` 有 10 条，order 0..9。

`deskEntryIndex`、`playerDeskSlot`、`aiLevel`、`rawItemBytes` 全部为 `null`：
块顺序没有证明等于 `deskPool` 下标，`CSDT_DESK_SVR2GAMECORE_ITEM` 的二进制
形态也没有还原。`deskIdText` 来自 0x1A4 的 28 B 串（去掉 NUL），按 5.16.5
是 `dwDeskId/dwDeskSeq` 的文本形态；它不是账号。

## 7. 第一段帧流

```text
0xaa5c  seq:u8 = 1
record  seq:u8, pad:u8(=0), len:u8, payload[len],
        trailerA:u8, trailer5:5B, trailerB:u8     total = 10 + len
0x75e2d end
```

| 项 | 值 |
|---|---|
| records | 10,509 |
| seq | 1 → 13（u8 回绕，不是旧样本的 0x22 起） |
| payload 长度 | 1..169 B，均值约 31.8 B |
| trailer5 | 10,508 条为 `00 00 00 00 00`；最后一条（record 10508，`0x75e02`）为 `ff ff ff 00 00` |
| 尾部 | 106 B（roster/score tail，本任务不解） |
| 帧率 | 15 fps（5.129 对 5247758 的标定） |
| `totalFrameNum` | 10,674（比记录数多 165，约 11 s 入场/装载） |

最后一条的 trailer5 例外不破坏 seq/pad/len 容器链，但 trailerA/B 与 exception
的语义仍未命名；JSON 里记录为 `trailer5.exception`，不猜测含义。

`payload` 是按英雄索引的输入/状态标签流（5.13.3/5.36），不是初始化字段，
也不含经济/KDA。本候选只记录容器范围；`payloadSemantics=null`。

## 8. 候选 JSON 结构

文件：`host/fixtures/20261102_161129/init/level_context_candidate.json`
（schema `kpl-gamecore-level-context-candidate-v1`）。

| 组 | 内容 | 未知处理 |
|---|---|---|
| `source` | 回放 ID、大小、SHA-256、只读标记、脱敏策略 | — |
| `level` | 版本/构建、localHeroId、mapType/mapId、startTimeTicks、totalFrameNum、frameStream、字段映射 | CLevelContext 未映射字段放 `unresolved`，值 null |
| `rules` | gameMode=50、initialGold=300、modeWord、serverTimeUnixSeconds、玩家观测 | 随机种子/时长/复活/AI 等 `unresolved`，值 null |
| `players` | 十人 camp/slot/entity/hero/self/nameSha256 + 每个字段偏移 | `bot=null`；原始身份字段不写入 |
| `deskPool` | 十人条目、协议类型名、deskIdText | 二进制/TDR/下标映射全部 null |
| `kv` | 53 条原始 KV、已知语义、databin 83 对拍 | 未命名 key 语义 null |
| `unknown` | 标量块、头部残余区、CLevelContext/deskPool/玩家块/帧 payload 的缺口 | 全部映射值 null，保留必要原始证据 |

`unknown.scalarBlock.rawWordsBigEndianForDifferentialTesting` 只是证据数组，
不是宿主字段；`unknown.scalarBlock.unmappedSemantics=null`，并且
`unknown.scalarBlock.mappedWordValues=null`。

## 9. 距离真正 `CLevelContext`/`deskPool` 还差什么

| # | 缺口 | 当前证据 | 影响 |
|---:|---|---|---|
| G1 | `CLevelContext` 字段偏移表 | type 42374、285 字段；无 native offset；443B 顺序 ≠ 声明顺序（5.34/5.35） | 443B 只能做差分，不能按字段名写入 |
| G2 | `deskPool` 条目二进制 | 只有 `CSDT_DESK_SVR2GAMECORE_ITEM/CONFIG` 类型名（5.16.3/5.16.6） | 十人元组还不能变成可 Push 的 desk 命令 |
| G3 | CSProtocol/TDR 封装 | KV/443B/玩家块是数据，不是命令流；`FRAME_CMD_INFO` 143 条只是 opcode 表 | `StartLevel` 的命令顺序/字节形态未知 |
| G4 | context/FIFO 创建 | `0x43D301C` 不是安装器；`CommitCsBuffer` SIGSEGV；仅 Push 通过（5.35） | 宿主还不能稳定进入帧循环 |
| G5 | 规则/AI/随机种子 | `m_randomSeed`、`m_timeDuration`、`m_loseCondition`、`m_baseReviveTime`、`m_reviveTimeMax`、`m_aiLevel` 等均未映射 | 不能保证 Core 进入 `StartFight` 后行为正确 |
| G6 | 活 context 对拍 | `context_snapshot.json` 只有 qword/缓冲布局；未证明 `ctx+0x2c8/0x5e0` 是 deskPool 或十人 `CPlayer` 数组（gamecore_host.md 3.5） | 不能拿快照当字段真值 |
| G7 | 帧 payload 语义 | 只有容器/标签统计；经济/KDA 不在帧流（5.13.3/5.36） | 初始化映射不应依赖帧 payload |

另外两个容易误判的点：

1. **`startTimeTicks` 不是 Unix 秒。** 它是 .NET DateTime ticks；时区/时钟
   未确认，所以 JSON 只给原始 ticks，`startTimeIso=null`。
2. **`serverTimeUnixSeconds`（标量 index 67）不是 `startTime`。** 它等于
   文件名里的 10 位段（本样本 `1,793,606,215`），与 0x113 的 BE32 一致，
   更像桌面/服务器时间锚点；不要拿它填 CLevelContext 的开局时间。

## 10. 下一步（保持 null，不伪造字段）

1. **先做最小 context**：只喂已知字段（mapType/mapId、人数/阵营观测、KV、
   initialGold、serverTime、十人元组），观察 Core 是否创建 context/线程；
   443B 只作为不透明 blob 保留，不按旧样本字段名拆。
2. **KV 作为开关**：用 databin 83 的 53 行做默认模板，按 `.abc` 的 key 集合
   覆盖；单独验证 KV + 8B 前缀是否触发上下文创建，再加入玩家块。
3. **状态机探针**：轮询 `0x544c0bd0`（0 空闲/2 跑一帧/3 退出）、
   `0x544c0b58`、`0x4ff4520` 链，作为“初始化到哪一步”的唯一可靠信号。
4. **静态补字段**：反汇编 `CLevelContext` 构造函数 / `GameBuilder`
   `Initialize→BuildPlayers→AddHero→...→StartFight`，找 443B 和玩家块的写入点；
   只有拿到偏移才把 `unresolved` 里的 null 替换成真实字段。
5. **deskPool 二进制**：从 `CSDT_DESK_SVR2GAMECORE_ITEM/CONFIG` 的
   TDR 读写函数反推条目布局；在此之前保持 `rawItemBytes=null`。
6. **回归**：任何新字段都要能解释 `.abc` 偏移、与 databin/营地/录屏对拍，
   否则继续留 null。

## 11. 脱敏与可复现校验

- 产物不含原始昵称、头像 URL、语音 URL、openID、账号等级、hash1、
  accountValue1..8 或录制者 32-hex 标签；玩家名只保留 SHA-256。
- 头部 `userName`/`userHead`/`rankGrade`/`rankClass` 在 JSON 里显式为
  `null`，只记录“已省略”。
- 复核哈希：`.abc` `d74c2be…`；头部 `d68ec12…`；443B `bd3b9e7…`；
  KV 与 `83_svr2GamecoreCfg.bytes.bin` 的 52 个共同 key 值全等。
- 独立解析使用的关键锚点：
  - 4 串结束 `0x23`；`localHeroId` `0x23`；`startTime` `0x27`；
  - KV 签名 `01 00 32 00 02 00 01 00 03 00 19 00`（`confType=1→50`），
    count 在签名前 2 B；
  - 玩家块签名 `camp|teamEcho|01|slot|00 00|entity:u16BE|…|nameLen`；
  - 帧流 `seq,00,len` 连续链，首个长链起点 `0xAA5C`。
- 复现命令（只读）：

```bash
python - <<'PY'
from pathlib import Path
abc = next(Path("data/replays/samples/20261102_161129").glob("*.abc"))
d = abc.read_bytes()
print(len(d), d[0x23:0x27], d[0x1c4:0x1c6])
PY
```

## 12. 相关文件

- `host/fixtures/20261102_161129/init/level_context_candidate.json`（本产物）
- `host/fixtures/20261102_161129/init/abc_header.json`（旧 fixture，交叉核对）
- `host/fixtures/20261102_161129/init/players.json`（旧 fixture，交叉核对）
- `host/fixtures/20261102_161129/context/context_snapshot.json`（H4 快照）
- `docs/gamecore_host.md`、`docs/simulation_plan.md` S3、
  `docs/replay_binary_format.md` 5.13–5.16、5.36
- `data/replays/_analysis/device/dtab_blocks/83_svr2GamecoreCfg.bytes.bin`
- `data/replays/_analysis/device/tables_blocks.csv`
