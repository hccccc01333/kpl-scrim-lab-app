# `.ope` operator stream：11/2 卡点（2026-11-03 更新）

本文取代上一版“大 MemoryData 是真实大块快照”的结论。结论先行：

1. **UILayout 不是长度前缀的原始负载，而是 u16 tag + 恰好 75 个 ULEB varint。**
   本地 44 个去重流（46 个文件路径，含副本；构建
   4442288/4750749/4989537/5230306）全部满足，
   第 75 个值结束后正好接上 `13 ae 01 …` SkillSlotOpe 串。
   `s[7:11]`（11/2 读出 85）不是 UILayout 长度；`HEADER_BYTES=27` 只是旧样本的
   历史起点，11/2 的记录从 offset 0 开始。解析器同时探测 0 和 27，取能
   消费到 EOF、否则推进更远的起点。
2. **旧墙 0xE79 / 0xCDC 是 MoveOpe 对齐错误，不是 MemoryData 边界问题**：
   给 MoveOpe 增加 4-varint 布局后，这两处直接由普通的
   Move / Common / UnityFrame / SendMsg 记录覆盖；`0x82/0x88` 是上一条
   MoveOpe 没读完的 varint 尾字节，不是续块前缀。旧结论中的
   “MemoryData(frame=2507,len=544)”是对齐错误的产物。
3. **MemoryData 有两种完全不同的形态，只有一种带 payload**（见第 3 节）：
   - payload 形态：`frame + lenvar(data)`，11/1 的 424 帧小快照（45 B 重复块，
     含 ASCII `null`）和 11/2 的 500 系帧（如 0x3670B 的 frame=520、9,750 B）；
   - frame 256..267 的 `10 <frame> <unity>` **不是记录**：它是前一条
     Move/Skil 记录被少读一个 varint 后剩下的尾巴，第三个字段是 unity 时钟，
     不是长度。18,748 / 24,946 / **30,116 B** 的“payload”都是 DP 跳板，
     不是真实记录。
4. **0x1991E / 0x38D26 的墙字节是 varint 片段，不是类型**：
   `0x24` 补完 `ed 24`（Move 第 5 个 varint，11/2a +1 字节），
   `0x91` 开始 `91 27`（Move 第 7 个 varint，11/2b +2 字节）。
   两局适用同一条规则：**payload 结束处切开的那条记录，把它的剩余 varint
   补完后再继续**；两处的 unity 时钟都单调（34,863→34,865、5,006→5,017）。
5. 同 build 的 **11/1 人机样本（46,900 B）仍可完整消费到 EOF**
   （9,301 条记录，447 条 tentative / 2,073 B，1,089 个歧义点）。
   11/2 的严格线性解析仍有两处真墙（第 5 节），但在工具中把
   “payload 切开记录”作为**显式标记的修复预览**后，11/2a 可到 EOF，
   11/2b 可到倒数第 1 字节（第 6 节）。

复跑：

```bash
python tools/ope_11_2_walls.py        # 本次新增：墙字节/平移扫描/快照审计/修复预览
python tools/ope_11_2_diff.py         # 旧墙 0xE79/0xCDC 的重新分段
python tools/ope_11_2_probe.py        # UILayout 与当前墙的轻量报告
python -m pytest -q tests/test_operator_stream.py tests/test_replay_parser.py
```

## 1. UILayout：u16 tag + 75 个 varint（高置信）

对每个样本做同一件事：找到 `16 b4 01`，把 tag 之后的字节按 ULEB128 解析，
直到第一个 `13 ae 01 00 01` SkillSlot 串。结果：

| 样本 | 流大小 | payload 字节 | varint 数 | 末尾连续 0 varint | SkillSlot 起点 |
|---|---:|---:|---:|---:|---:|
| 20261102_161129 | 237,556 | 118 | 75 | 10 | 0x89 |
| 20261102_163751 | 358,966 | 118 | 75 | 10 | 0x89 |
| 20261101_182452 | 46,900 | 126 | 75 | 10 | 0x91 |
| 20261027_231329 | 242,707 | 126 | 75 | 10 | 0x91 |
| 20261028_135516 | 39,634 | 123 | 75 | 10 | 0x99 |

全语料命中 **同一个 varint 计数 75**（去重后 44/44，含副本 46/46），
且末 10 个 varint 恒为 0。75 个值中大量成对重复（`f0 01 f0 01`、
`8a 02 ed 09 8a 02`、`55 4f 55 4f 55 4f`），更像固定字段表的序列化，
而不是“长度 + 原始结构体”。因此 `s[7:11]=85` 与 118/126 无关，
27 字节头不是 11/2 的流头，首记录在 offset 0。

## 2. 旧墙 0xE79/0xCDC 的真相：MoveOpe 4-varint

11/2 的 MoveOpe 在干净区段（例如 11/2a 0x233..0x37E）有一串 9 字节记录：

```text
06 88 01 65 99 0a 01 c7 7d
   frame=392, m1=101, m2=1305, m3=1, unity=16071
```

它们与 `06 88 01` 逐条对齐，最后一条 varint 是单调的 unity 时钟。
加入 4-var MoveOpe 后，11/2b 的 0x0C50..0x0D04 重新分段为普通
Move / SendMsg / Common / UnityFrame 记录，原来的
“MemoryData(frame=723,len=112)”完全消失；`0x0CDC` 落在
`06 88 01 6d d0 05 …` 的 varint 内部。11/2a 的 0xE79 同理：
`0xE6E..0xE7B` 是一条 MoveOpe（unity=16670），墙处的 `82 01`
是这条记录最后一个 varint 的两字节，`0xE7B` 起才是下一条 `06 88 01`。
`tools/ope_11_2_diff.py` 的 `oldWall.segmentation` 会打印这条路径。

## 3. MemoryData：payload 形态 vs 256..267 的“假头”

### 3.1 payload 形态（真实长度）

- 11/1 的 12 条 MemoryData 帧为 424/4618/46849/28437，payload 为
  45/63/98/2 B；45 B 块在 8 条记录里逐字节重复：

  ```text
  00 34 c5 fb ff 01 02 54 55 59 00 df 7f e8 7e 00 00 00 04 6e 75 6c 6c
  ca fe ff ff 00 03 13 1e 2f 00 20 00 10 00 00 00 00 04 6e 75 6c 6c
  ```

  其中可见 ASCII `"null"`、`"TUY"`，符合内存快照语义；`lenvar` 是
  payload 字节长度。11/2a 严格路径上的 51 条 payload 形态记录全部
  结束于合法类型（`tools/ope_11_2_diff.py` 的 `memoryProbe`）。
- 11/2 也有真正的 payload 形态，帧集中在 500 系（512/513/514/518/519/
  520/523），长度 1.2–9.7 KB。**0x3670B 的 9,750 B 记录是真实的**：
  `10 08 02 96 4c` → frame=520，第三字段 9750 等于 payload 字节数，
  而当时的 unity 只有 3,193（不是时间戳）。它的 payload 结束于
  0x38D26，切开了一条 Move；补完 `91 27` 后（+2）继续，见第 4 节。

### 3.2 frame 256..267：不是 payload，是前一条记录的尾巴

11/2 有一批 `10 <frame 256..267> <varint>` 切片，旧解析把它们当作
18,748 / 24,946 / 30,116 B 的大快照。证据表明它们是**对齐错误**：

- 9 个旧“大快照”的第三字段都等于局部 unity 时钟（前一条记录 +1..4，
  后一条 UnityFrame −1..3），而不是 payload 长度：

  | 样本 | 偏移 | frame | 第三字段 | 前一 unity | 后一 unity |
  |---|---|---:|---:|---:|---:|
  | 11/2a | 0x02EF4 | 259 | 18,748 | 18,744 | 18,750 |
  | 11/2a | 0x0A9C2 | 264 | 24,946 | 24,944 | 24,947 |
  | 11/2a | 0x12374 | 258 | 30,116 | 30,114 | 30,117 |
  | 11/2b | 0x01A6B | 259 | 13,409 | 13,407 | 13,411 |
  | 11/2b | 0x0A7A5 | 260 | 22,708 | 22,706 | 22,709 |
  | 11/2b | 0x1024F | 257 | 27,699 | 27,698 | 27,700 |
  | 11/2b | 0x186D5 | 267 | 37,851 | 37,849 | 37,853 |
  | 11/2b | 0x236C1 | 259 | 49,121 | 49,118 | 49,122 |
  | 11/2b | 0x30CDC | 257 | 63,599 | 63,597 | 63,601 |

- 直接看 11/2a 0x2EF4 的原始字节：

  ```text
  06 88 01 61 10 03 01 bc 92 01
     Move frame=392, varints 97, 16, 3, 1, 18748
  ```

  `10 03 01 bc 92 01`（旧解析的“frame=259, len=18748”）只是这条
  Move 的后四个 varint；`18748` 是 unity。旧 DP 在 0x2ED9 处选了
  8-var 的 tentative Move，把 0x2EF4 切成了“MD 头”，再用 30 KB 的
  lenvar 跳过一大段。`tools/ope_11_2_walls.py` 的 `artifact_scan` 在
  两个样本各报告 64 个同型候选（工具默认上限），第三字段与后一 unity
  的差都在 −1..−5。

因此解析器现在把 `0x10` 的 payload 形态限制为 **frame ∉ [256, 267]**；
`frame_in / frame_not_in` 是 `_consume` 的显式字段门控。这样 30,116 /
24,946 / 18,748 B 的假跳板不再产生，11/2a 的“墙”从 0x1991E 回落到
真实的 0xECDA。

## 4. 0x1991E / 0x38D26：墙字节是 varint 片段（高置信）

两处墙都是**假 MD 跳板的终点**，墙字节不是类型：

| 样本 | 墙 | 上下文 | 0x24/0x91 的解释 | 首次有效平移 | unity |
|---|---|---|---|---|---|
| 11/2a | 0x1991E | `24 01 b1 90 02 …` | 补完 `ed 24`（Move 第 5 个 varint=4,717），记录在 0x1991F 结束 | +1 → 0x1991F（UnityFrame 34,865） | 34,863→34,865 |
| 11/2b | 0x38D26 | `91 27 06 88 01 …` | 补完 `91 27`（Move 第 7 个 varint=5,009），记录在 0x38D28 结束 | +2 → 0x38D28（Move） | 5,006→5,017 |

`tools/ope_11_2_walls.py` 对两处做 ±4..+8 平移扫描：

- 11/2a 只有 +1（列在 scan 的 +1）能让两侧同时合法；−1 的 `ed`、
  +2 的 `b1`、+3 的 `90` 都不是类型，不能作为起点。
- 11/2b 只有 +2 是合法的 Move 起点；−1 的 `01 91 27` 虽然能读成
  UnityFrame 5,009，但它把 `91 27` 当成独立记录，和 0x38D28 的
  `06 88 01` 冲突；+2 与后续 `06 88 01` 串连续。

两局的规则相同：**payload 结束处切开的那条记录，把它的剩余 varint 补完
后再继续**；平移量不同（+1/+2）只是因为被切开的 varint 长度不同。
这不是“新增类型 0x24/0x91”。旧文档中“0x24 可能是新类型”的猜测可以撤销。

## 5. 新增布局（均标注证据层次）

| 类型 | 布局 | 证据 | 级别 |
|---|---|---|---|
| `0x10 MemoryData` | `frame + lenvar(data)`，**仅 frame ∉ [256,267]** | 11/1 424 帧 45 B 重复块；11/2 500 系帧长度=第三字段；256..267 的第三字段=unity | CONFIRMED |
| `0x0A UIntOpe` | `frame + u24`（6 字节） | 两局都有 `0a 12 00 00 00 00 18 b6 01 6d 9d…`：6 字节 UInt 正好在 SendMsg `18 b6 01` 前结束；4 字节 varint 布局会把 `18` 吞进 Common | TENTATIVE |
| `0x15 DirSkillOpe` | `frame + skillId + seq + param1 + param2 + extra`（5 varint） | 11/2b 0x7EF3 `15 6f 02 a4 99 01 08 37 e9 02 e2 0c` 后接 `0c 04 02 00 08`，CppEvent 的 extra 重复 seq=8 | TENTATIVE |
| `0x06 MoveOpe` | 4/5/6/7-var，另保留 8-var tentative bridge | 0x233..0x37E 连续 9 字节记录 | 见旧表 |
| `0x0B UIEventOpe` | `u8 tag(0x7d) + varint eventId` | 11/2/11/1 中恒为 `0b 7d <varint>` | CONFIRMED |

加入 UInt 6 字节和 DirSkill 5-var 后，11/2b 的第一个真墙从 0x7EFD
推进到 0x13FF3；11/2a 从 0x6F2D 推进到 0xECDA。11/1 仍到 EOF
（9,301 条；比旧计数少 6 条，原因是新的 UInt 6 字节布局合并了
一些 4 字节 UInt + Common 的边界；tentative 从 453 降到 447）。

## 6. 当前真墙（严格解析，无修复）

| 样本 | 结果 | 真墙/上下文 |
|---|---|---|
| 20261102_161129 | 未到 EOF | 0xECDA type=0x6D，`6d 9d 00 00 01 01 ea da 01 …`；前一条是 Common(frame=6163, unity=182)，墙字节是下一条 SendMsg 的字段 |
| 20261102_163751 | 未到 EOF | 0x13FF3 type=0x88，`88 01 5e a0 00 02 d8 1c …`；0x13E78 的 374 B payload 形态 MemoryData 在 0x13FF3 切开一条 Move，−1 回到 0x13FF2 后可到 59.0% |
| 20261101_182452 | **EOF** | 9,301 条；447 tentative / 2,073 B；1,089 歧义 |
| 20261016_005102 | 未到 EOF | 0x1CF25 type=0x2e（未受本次修改影响） |
| 20261027_231329 | 未到 EOF | 0x254D type=0xfb（未受本次修改影响） |
| 20261028_135516 | 未到 EOF | 0x3556 type=0xb9（未受本次修改影响） |

注意：0xECDA 的墙不是 MemoryData 终点，而是 **Common/SendMsg 边界**：
`… 01 e8 da 01 | 00 13 18 b6 01 | 6d 9d …`。Common(frame=6163, unity=182)
把 `18` 当成 frame 高字节；真实记录很可能是 SendMsg `18 b6 01 6d 9d …`，
但要让 SendMsg 从 0xECD7 开始，前一条记录必须在 0xECD7 结束，而
0xECD5..0xECD6 只有 `00 13`（不足一个 Common）。这是下一步的首要实验。

## 7. 修复预览：把“切开记录”当显式修复

`tools/ope_11_2_walls.py` 的 `resyncPreview` 不是解析器输出，而是把
第 4 节的规则显式记账后的预览：在墙处按 ±4..+16 扫描，选“首个合法类型
且推进最远”的平移，重复到 EOF 或无法推进。结果：

| 样本 | 修复点 | 结果 |
|---|---|---|
| 11/2a | 0xECDA +2 → 0x1434F +1 → 0x181B8 −1（MD 0x170EB）→ 0x1AC94 +1 → 0x236EA +1 → 0x267B5 +1（MD 0x24B4A/0x265CF） | **EOF 0x39FF4** |
| 11/2b | 0x13FF3 −1（MD 0x13E78）→ 0x33B04 +1（MD 0x317EF）→ 0x38D26 −1（MD 0x3670B，真实 9,750 B）→ 0x4E2BA +1（MD 0x4E1C1）→ 0x57A33 +2 | **0x57A35**（流末 0x57A36，剩 1 字节） |

修复后的 unity 审计（只统计 UnityFrameOpe 且值 ≥1000）：
11/2a 1,366 个观测、**2 次下降**；11/2b 2,025 个观测、**6 次下降**。
所以这是**结构消费**，还不是语义确认；下降点集中在 0xECDA 附近的
Common/SendMsg 误读和几个 generic 修复点。下一步应把这些修复点
换成真实布局，而不是把 resync 直接塞进默认解析器。

## 8. 下一步实验

1. **0xECDA 的 Common/SendMsg 边界**：检查 `00 13 18 b6 01 6d 9d`
   是否有一条 `SendMsgToServerOpe` 的 6/7 字节变体，或 Common 是否
   还有第三个 varint。目标：让 11/2a 的第一个真墙从 0xECDA 后退。
2. **0x13FF3 的 374 B 快照**：0x13E78 的 payload 是真实内存快照还是
   DP 跳板？它的 payload 结尾切开 Move `06 88 01 5e a0 00 02 d8 1c
   01 be fc 01`；如果它是真实快照，就跑第 4 节的 split-tail 规则；
   如果是跳板，就找 0x13E78 之前少读的 varint。
3. **可选的显式修复模式**：在 `operator_stream.py` 增加 opt-in
   `repair=`（默认关闭），把每个修复点、跳过的字节数、unity 前后值
   记账；只有第 1/2 项的真实布局补齐后才考虑默认开启。
4. **unity 单调约束的 beam search**：当前 DP 只按 tentative 字节数选路，
   会接受 `Common(frame=6163, unity=182)` 这类语义不合理的分支；用
   UnityFrameOpe 时钟做全局约束，可以避免 0xECDA 这类“最近但错误”的
   边界。
5. **对拍**：用 `.abc` 帧流和截图校验 touch/move/skill/UI/APM；`.ope`
   仍是本地 POV 操作日志，不是十人状态。

## 9. 边界

`.ope` 是本地 POV 操作日志，不是十人状态；能补 touch/move/skill/UI/APM，
不能补十人坐标、血量、经济。完整状态仍走设备 `AdvanceFrameCommands`。
本次只做离线静态分析：未启动/连接游戏、未登录、未注入、未修改任何
回放或运行时数据；11/1 的 EOF 结果作为回归基线保留。
