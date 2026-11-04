# 0x02/0x81 与 0x02/0x84：死亡候选复核（D1）

> 只读静态分析。没有启动/连接游戏，没有登录，没有注入，没有修改任何回放、R1/R2 数据集或既有文档。本文所有计数可由
> `data/replays/_analysis/tools/agent_death_probe.py` 复跑。

## 0. 结论速览

1. **R1 的「0x81 mode6 = 死亡候选」结论不成立。** `0x02/0x81` 是 TDR `CSSYNC 129 USEDIRECTIONALSKILL`，不是死亡/状态消息。
   - tag 流 `02 <actor:u16> 81 <22B body>` 与 `tools/replay_frame_commands.py` 解出的 TDR 命令流逐字节相同：
     16:11 `711/711`、16:37 `1290/1290`、旧 build 20260925_105224 `1126/1126`（main+tail 计数）。
   - body 是 `slot:u8, degree:i16(x0.01°), object_id:u32, secondary_1:i32, secondary_2:i32, secondary_3:i32, skill_seq:u16, drag_flag:u8`。
   - 旧读法「mode:u8, param:u16BE, 19B tail」只是字段切分碰巧对齐；所谓 `mode6` 是 **slot byte 6**，`tail counter` 是 `skill_seq`，`tail flag` 是 `drag_flag`。
2. **0x84 也不是未知 stat/金币；它是 TDR `CSSYNC 132 BASEATTACK`。**
   - tag 流 `02 <actor:u16> 84 <5B body>` 与 `replay_frame_commands.py` 的 BASEATTACK 命令逐字节相同：20261016_195137 `6,688/6,688`、16:37 `30/30`。
   - body 是 `start:u8, object_id:u32`；`kind` 是 `start`，`value` 是 `object_id`。旧 build 的 0–8465 是运行时 objectID 池内的目标 ID，不是金币/HP；16:37 的 30 条为负值/池外，单独标未解。
3. **0x01/0x03 是 CC buffer `0300`（存活/存在 beacon），不是死亡。**
   - 16:11 CC `0300` 4,570 条与 tag 0x03 4,570 条逐 actor 一致；16:37 7,063 vs 7,039（差 24 条落在命令流开头 frame ≤37，与 `find_stream` 起点差异一致；未逐条对齐）。
4. **0x81/0x84 帧流中没有可确认的死亡事件。**
   - `confirmed death candidates = 0`。
   - 488 条 slot6 事件全部是 `USEDIRECTIONALSKILL`，在 `agent_death_candidates.csv` 中标记为 `rejected_not_death`。
   - 死亡人数只能来自外部真值：11/2 第一局 KDA 截图 33 死亡；11/1 panel CSV 47 死亡。两者都没有回放内时间戳。
5. **外部真值直接反驳 mode6=死亡：**
   - 11/2 第一局：21 个 slot6 burst vs 33 死亡；`漂流网咖` 面板 D=0 但有 2 个 slot6；5 名玩家合计 16 次死亡但 0 个 slot6。
   - 11/1：`佚名(*:`（大禹）D=1、slot6 burst=1；`快乐何必认真`（娜可露露）D=1、slot6=0；8 个 AI 合计 45 死亡、slot6=0。
6. **11/2 第二局没有 KDA 真值**（只有 16:11/15:59 的面板截图和 11/1 panel CSV）；16:37 的 35 个 slot6 burst 不能算死亡候选。

## 1. 输入、口径与复跑

### 1.1 输入

| 输入 | 用途 |
|---|---|
| `data/replays/_analysis/datasets/replay_event_stream_events.jsonl.gz` | R1 旧 build 全量事件流（不含 20261102 两局） |
| `data/replays/samples/20261102_161129/`、`...163751/` 的 `.abc` + `replay-report.json` | 11/2 两局直接解析；report 提供 roster/hero/build |
| `tools/replay_frame_commands.py` | 独立的 TDR 命令流解码器；用于 0x81/0x84/CC 对拍 |
| `data/replays/_analysis/datasets/new_5247758_panel_truth_full.csv` | 11/1（20261101_182452）外部 panel 真值，10 人 47 死亡 |
| `data/screenshots/samples/20261102_1559/01-score-equipment.jpg`、`02-score-kda.jpg` | 11/2 第一局外部真值：27:6、KDA、金币 |
| `data/replays/_analysis/datasets/received_20261102_players.csv` | 只读检查；`gold_events` 是 BUYEQUIP 计数，不是金币，未参与死亡/经济计算 |

- R1 事件流**不包含** 20261102 两局。11/2 两局由 `agent_death_probe.py` 用同一套 R1 tag 语法直接解析，并在 CSV 中标记 `source=direct_abc`。
- 11/1（20261101_182452）在 R1 里，同时有 panel 真值，用来复核旧 build 的 slot6 计数。
- 0x81 的 envelope 字段是**战场实体/actor ID**（R1 JSON 里叫 `hero_id`，但 105224 的 `1729` 是实体 ID，不是英雄表 ID 142）。真英雄 ID 通过玩家块/report 反查。

### 1.2 帧号口径

- R1 的 `frame_index = seq - 主段首帧 seq`；11/2 direct 解析用同一 `find_stream`，首条 `0x22` 记录为 0。
- `find_stream` 从第一个 `0x22` 记录起扫，**跳过前 33 条记录**（11/2 report 的 `firstSequence=1`，本工具首条是 seq 34）。因此 11/2 的 `frame` 比 report 的 `seq-1` 小 33；对 slot6/0x84 无数据损失（首条 slot6 在 seq 573 之后）。
- 16:37 的 CC `0300` 比 tag 0x03 多 24 条，落在命令流开头（frame ≤37），与 `find_stream` 起点差异一致；未逐条对齐，不补造。

### 1.3 复跑

```bash
python data/replays/_analysis/tools/agent_death_probe.py
python -m py_compile data/replays/_analysis/tools/agent_death_probe.py
```

产物：

- `data/replays/_analysis/datasets/agent_death_candidates.csv`：488 条 rejected slot6 + 20 条外部真值，共 508 行。
- `data/replays/_analysis/datasets/agent_0x84_values.csv`：31,373 条 BASEATTACK。
- 本文档。

## 2. 0x02/0x81 = USEDIRECTIONALSKILL

### 2.1 布局（TDR CSSYNC 129）

```text
02 <actor:u16BE> 81 <body:22B>
body = slot:u8
       degree:i16BE        # 实际是 0.01° 定点；除以 100 后 -178.80..178.22
       object_id:u32BE
       secondary_1:i32BE
       secondary_2:i32BE
       secondary_3:i32BE
       skill_seq:u16BE
       drag_flag:u8
```

旧 R1 文档的 `mode:u8, param:u16BE, 19B tail` 与这 22B 完全同长，但字段语义不同：

- `mode` = `slot`（1/2/3/4/6/11）；
- `param` = `degree` 原始 i16；
- `tail[0:4]` = `object_id`；`tail[4:8]/[8:12]/[12:16]` = `secondary_1/2/3`；
- `tail[16:18]` = `skill_seq`（旧称 counter）；`tail[18]` = `drag_flag`（旧称 flag）。

### 2.2 对拍证据

`tools/replay_frame_commands.py` 能完整解析 **23 个文件中的 20 个**；这 20 个文件的 tag 0x81 与 TDR USEDIRECTIONALSKILL 的**原始字节多重集完全相等**。3 个文件因 `BOOTFRAP selector 26` 不支持，只能按 tag 布局外推。

| 文件（res_build） | TDR USEDIRECTIONALSKILL | tag 0x81 | 结果 |
|---|---:|---:|---|
| 20261102_161129（5247758） | 711 | 711 | 逐字节相等 |
| 20261102_163751（5247758） | 1,290 | 1,290 | 逐字节相等 |
| 20260807（4742900） | 841 | 841 | 逐字节相等 |
| 20260827_004836 / 010503 / 012122 / 013634（4813722） | 906 / 706 / 700 / 695 | 906 / 706 / 700 / 695 | 逐字节相等 |
| 20260902_221251 / 222816（4863377） | 774 / 695 | 774 / 695 | 逐字节相等 |
| 20260924_113638（5069040） | 951 | 951 | 逐字节相等 |
| 20260925_094930 / 095631 / 101323 / 103058（5069040） | 59 / 69 / 878 / 775 | 59 / 69 / 878 / 775 | 逐字节相等 |
| 20260925_105224（5069040） | 1,126 | 1,126 | main+tail 逐字节相等 |
| 20261016_005102 / 010346（5169333） | 452 / 844 | 452 / 844 | 逐字节相等 |
| 20261016_195137（5169333） | 359 | 359 | 逐字节相等 |
| 20261017_015659（5169333） | 703 | 703 | 逐字节相等 |
| 20261101_182452（5247758） | 234 | 234 | 逐字节相等 |
| 20261016_194242 / 20261027_231329 / 20261027_232156 | 工具不支持 | 441 / 621 / 383 | 未逐字节对拍；tag 布局相同 |

覆盖：0x81 事件 **13,768/15,213（90.5%）** 有逐字节证明；slot6 事件 **454/488（93.0%）** 有逐字节证明，34 条落在 3 个工具不支持的文件里。

补充证据：

- `degree` 原始值除以 100 后落在 **-178.80..178.22**，符合方向角；直接按 i16 读会得到 12,300、17,700 这类“越界角度”，这是旧结论误判的原因之一。
- `skill_seq` 在同一 actor 内非递减（383/384 个 mode6 相邻转移；唯一例外是 5247758 的全零 tail）。
- slot 分布 1/2/3/4/6/11；1–4 是普通技能槽，6/11 超出普通槽范围，**6 不是死亡**。
- 11/2 第一局 `漂流网咖` 面板 D=0，但 slot6 有 2 条；`自诩一棵葱` D=1，slot6 有 6 条。死亡假设直接失败。

### 2.3 计数与覆盖

| 来源 | 文件 | 0x81 事件 | slot6 原始 | slot6 burst（gap ≤ 10 帧） |
|---|---:|---:|---:|---:|
| R1 旧 build | 21 | 13,212 | 418 | 310 |
| 11/2 direct | 2 | 2,001 | 70 | 56 |
| 合计 | 23 | 15,213 | 488 | 366 |

slot 分布（全部 0x81，不只 slot6）：

| slot | 1 | 2 | 3 | 4 | 6 | 11 |
|---|---:|---:|---:|---:|---:|---:|
| R1 | 6,177 | 5,415 | 954 | 225 | 418 | 23 |
| 11/2 16:11 | 293 | 301 | 86 | 9 | 22 | 0 |
| 11/2 16:37 | 541 | 577 | 124 | 0 | 48 | 0 |
| 合计 | 7,011 | 6,293 | 1,164 | 234 | 488 | 23 |

slot6 映射覆盖：**477/488（97.7%）** 能映射到 player/team/hero；11 条只到 actor：
- 20260807_151225 actor 1976（4 条）；
- 20260827_012122 actor 1879（3 条）；
- 20261027_232156 actor 258（4 条）。

这些 actor 不在可用的 8–9 人玩家块里；CSV 只写 actor ID，不猜英雄。

### 2.4 11/2 第一局：外部 KDA 对拍（重点）

外部真值来源：`01-score-equipment.jpg`（27:6 面板、金币）+ `02-score-kda.jpg`（KDA）；roster/评分与 `replay-report.json` 一致，队伍击杀/死亡合计闭合（27/6）。

| 玩家 | 英雄 | 队/位 | 面板 KDA | 面板金币 | 面板 D | slot6 原始 | slot6 burst | 首次 burst 后的下一个 0x81 slot |
|---|---|---|---:|---:|---:|---:|---:|---|
| 漂流网咖︎ | 百里守约 | 1/4 | 5/0/8 | 8,697 | **0** | 2 | 2 | 3 |
| 狂傲自由魂Z. | 关羽 | 1/3 | 8/1/7 | 9,243 | 1 | 0 | 0 | - |
| 自诩一棵葱 | 妲己 | 1/1 | 6/1/7 | 8,168 | 1 | 6 | 5 | 1 |
| 别吃窝线吖a | 孙悟空 | 1/2 | 5/1/5 | 8,352 | 1 | 0 | 0 | - |
| 胡不喜# | 钟馗 | 1/0 | 3/3/9 | 6,540 | 3 | 4 | 4 | 2 |
| 麻巫喵 | 公孙离 | 2/0 | 1/5/2 | 6,191 | 5 | 0 | 0 | - |
| 翳灵崽 | 吕布 | 2/1 | 2/7/2 | 5,828 | 7 | 5 | 5 | 1 |
| 一风舞 | 貂蝉 | 2/2 | 2/3/3 | 5,778 | 3 | 0 | 0 | - |
| 扁鹊耳垂 | 兰陵王 | 2/3 | 1/6/2 | 5,977 | 6 | 0 | 0 | - |
| 谜语星海 | 张良 | 2/4 | 0/6/4 | 5,474 | 6 | 5 | 5 | 6 |

汇总：

- 面板总死亡 **33**；slot6 burst **21**。
- 即使把 slot6 硬当死亡，逐人 `min(burst,D)` 之和也只有 14：hypothetical precision 66.7%、recall 42.4%；这不是 KDA 估计。
- **D=0 但 slot6>0：`漂流网咖`（2 条）**。
- **5 名玩家合计 16 次死亡但 0 个 slot6**：关羽、貂蝉、孙悟空、公孙离、兰陵王。
- `张良` 只有 slot6 0x81、没有其他 slot，slot6 之间相隔约 2,000 帧；这仍不能证明是死亡，只是该 actor 的 0x81 流很稀疏。
- `漂流网咖` 的 slot6 之后 8/18 帧内出现 slot3；`自诩一棵葱` 的 slot6 之后 18–74 帧内出现 slot1（多数 49–74 帧）。正常技能序列，不是“死亡后复活”。

### 2.5 11/2 第二局

第二局没有 KDA/金币截图或 panel 真值，只有 slot6 计数：

| 玩家 | 英雄 | 队/位 | slot6 原始 | slot6 burst |
|---|---|---|---:|---:|
| 南巷丶转转儿 | 钟馗 | 2/0 | 17 | 8 |
| 野心蓝图33 | 安琪拉 | 2/2 | 7 | 7 |
| 蟹谢谢礼 | 吕布 | 2/3 | 6 | 6 |
| 憨熊笨拳 | 墨子 | 1/2 | 5 | 5 |
| 漂流网咖︎ | 百里守约 | 1/4 | 9 | 5 |
| 冷静宝宝QWQ | 王昭君 | 1/3 | 4 | 4 |
| 其他 4 人 | - | - | 0 | 0 |
| 合计 | - | - | **48** | **35** |

`南巷丶转转儿` 的 slot6 有 17 条、合并为 8 个 burst（例如 4758–4767 连续 10 条合并为 1 个 burst），这是技能/装备主动的连续输入，不是死亡次数。没有外部真值，不能给这一局 KDA。

### 2.6 11/1（20261101_182452）：panel 真值

| 玩家 | 英雄 | 面板 KDA | 面板金币 | 面板 D | slot6 burst |
|---|---|---|---:|---:|---:|
| 佚名(*: | 大禹 | 9/1/12 | 6,265 | 1 | 1（3 条 raw） |
| 快乐何必认真 | 娜可露露 | 22/1/2 | 13,333 | 1 | 0 |
| 传说之刃 | 花木兰 | 0/2/5 | 5,772 | 2 | 0 |
| 绝世舞姬 | 貂蝉 | 4/2/5 | 6,207 | 2 | 0 |
| 火鹰船长 | 莱西奥 | 3/3/14 | 6,732 | 3 | 0 |
| 永恒之月 | 芈月 | 2/5/3 | 5,977 | 5 | 0 |
| 破镜之刃 | 镜 | 0/8/5 | 4,584 | 8 | 0 |
| 永夜之心 | 海月 | 0/12/0 | 4,190 | 12 | 0 |
| 暴走机关 | 刘禅 | 4/6/0 | 5,886 | 6 | 0 |
| 森之风灵 | 虞姬 | 2/7/1 | 5,576 | 7 | 0 |

汇总：panel 总死亡 **47**；slot6 burst **1**。8 个 AI 合计 45 死亡，**0 个 0x81**。旧 `agent_kda_validate.md` 的“v6=死亡”在这里只是 1804 的单个巧合；同一份 panel 里 212（D=1）和 8 个 AI（D=45）都是反例。

### 2.7 0x03 beacon 空档不是死亡证据

- `0x01/0x03` 与 `replay_frame_commands.py` 的 CC `0300` 计数一致：
  - 16:11：CC `0300` 4,570 = tag 0x03 4,570（逐 actor 相同）；
  - 16:37：CC `0300` 7,063 vs tag 0x03 7,039（差 24 条在命令流开头 frame ≤37，未逐条对齐）。
- slot6 burst 的 beacon 空档：事件级 401/488 ≥3×、21 条 2–3×、50 条 <2×、16 条无边界；窗口级 288/366 ≥3×、20 条 2–3×、48 条 <2×、10 条无边界。
- 这些空档只是“该 actor 的 CC 0300 流变稀疏”，不是死亡。`漂流网咖` D=0 的 2 个 slot6 仍落在 2.67×/18.51× 空档里；`自诩一棵葱` D=1 的 5 个 burst 都在 6.78–15.67× 空档里；`胡不喜#` D=3 的 4 个 burst 里还有 0.53×/1.60×。空档既不能提高 precision，也不能补 recall。

### 2.8 slot6 的候选语义

- slot byte 6 不在普通技能槽 1–4；最可能是**召唤师技能/装备主动/其他命令子类型**，但本仓库没有 TDR 枚举能唯一命名。
- 证据只支持“slot6 是技能类输入”，不支持“死亡”。
- 旧 R1 文档的 415 条“死亡候选”应全部撤回；`agent_kda_validate.md` 的 27 窗口表是 slot6 技能 burst，不是死亡窗口。

## 3. 0x02/0x84 = BASEATTACK

### 3.1 布局（TDR CSSYNC 132）

```text
02 <actor:u16BE> 84 <body:5B>
body = start:u8, object_id:u32BE
```

旧读法 `kind:u8, value:u32BE` 与 TDR 字段一一对应，但语义是普通攻击命令，不是 stat/金币/HP：

- `kind` = `start`（0–7）；
- `value_u32` = `object_id`（0–8465 在运行时 objectID 池 0–17,286 内）；
- `value_i32` = 同一个 32 位字段的 signed 读法；16:37 的 30 条 `start=7` 值为 0xFFFFBA4B–0xFFFFFD83（u32 4,294,949,451–4,294,966,659；i32 -17,845..-637），超出 objectID 池，字段语义未解。

对拍：`replay_frame_commands.py` 的 BASEATTACK 与 tag 0x84 在 **20261016_195137（6,688/6,688）** 和 **20261102_163751（30/30）** 上逐字节相等；16:11 两边都是 0 条。其余 3 个 0x84 文件（20261016_194242、20261027_231329、20261027_232156）因 `BOOTFRAP selector 26` 不支持，未逐字节对拍；tag 布局与已证文件相同，但这 24,655 行只能算“同布局”，不是逐字节证明。

### 3.2 分布

| start | 行数 | object_id 非零 | object_id 范围 | 说明 |
|---:|---:|---:|---|---|
| 0 | 12,123 | 41 | 0–7,292 | 多为 0 |
| 1 | 16,607 | 5,572 | 0–8,465 | 主攻击流 |
| 2 | 921 | 0 | 0 | 全 0 |
| 3 | 344 | 0 | 0 | 全 0 |
| 4 | 1,318 | 19 | 0–5,774 | 少量目标 |
| 6 | 30 | 0 | 0 | 全 0 |
| 7 | 30 | 30 | 0xFFFFBA4B–0xFFFFFD83（i32 -17,845..-637） | 仅 16:37；out-of-pool |
| 合计 | **31,373** | **5,662** | - | - |

按文件/队伍：

| 文件 | 行数 | start 0/1/2/3/4/6/7 | object_id 非零（队） |
|---|---:|---|---|
| 20261016_194242 | 6,459 | 2150/3723/222/68/294/2/0 | T2 1,864；T1 3 |
| 20261016_195137 | 6,688 | 2190/3888/203/91/307/9/0 | T2 1,901；T1 5 |
| 20261027_231329 | 7,057 | 2460/4179/79/116/209/14/0 | T2 1,845 |
| 20261027_232156 | 11,139 | 5323/4817/417/69/508/5/0 | T1 8；未知 6 |
| 20261102_163751 | 30 | 0/0/0/0/0/0/30 | T1 30（负值） |

补充：

- **4 个旧 build 文件里 0x84 行覆盖全部 10 个 actor**（20261027_232156 的 actor 258 未映射到玩家），不是只覆盖一队；但 **object_id 非零**偏向一队：
  - 20261016_194242 的本地英雄是 132 马可波罗（T1），非零目标在 T2（刘禅/曜/黄忠/廉颇/貂蝉）；
  - 20261016_195137 本地英雄 112 鲁班七号（T1），非零在 T2；
  - 20261027_231329 本地英雄 563 海诺（T1），非零在 T2；
  - 20261027_232156 本地英雄 110（阵营未由 roster 确认），非零在 T1。
  - 这说明 object_id 的零/非零是**录制侧的本地/远端目标编码差异**，不是金币或属性队伍偏好。
- 16:37 只有 30 条，全部是 actor 714（亚瑟，T1）`start=7`，object_id 为负；与旧 build 的 0–8465 目标池不同，是第二局特有的未解编码。
- 16:11 第一局 **0 条 0x84**；因此不能用 0x84 给第一局死亡/金币真值做任何校验。

逐英雄行数（每文件前 5，完整逐行见 CSV）：

| 文件 | 行数前 5 的英雄（行数） |
|---|---|
| 20261016_194242 | 心魔六耳 1239、马可波罗 1066、甄姬 975、特殊块 heroID=1 938、曜 735、刘禅 466 |
| 20261016_195137 | 鲁班七号 1564、孙悟空 1090、李信 1001、兰陵王 777、朵莉亚 548、高渐离 512 |
| 20261027_231329 | 韩信 2146、百里守约 1377、兰陵王 787、吕布 722、关羽 645、蔡文姬 612 |
| 20261027_232156 | 后羿 1811、宫本武藏 1649、李白 1488、芈月 1444、孙尚香 1307、未映射 258 1140 |
| 20261102_163751 | 亚瑟 30（唯一有 0x84 的 actor） |

- 4 个旧 build 文件里每队 5 人都有 0x84 行；但 object_id 非零集中在一队（见上表）。这不是“该队才有普攻”，而是录制侧目标编码差异。
- 16:37 只有亚瑟 30 条，且全部 `start=7`/负 object_id；不能外推到其他玩家。

### 3.3 时间/英雄/事件相关性

- 逐文件 BASEATTACK 事件对齐（±10 帧，observed / uniform-frame baseline）：
  - 20261016_194242：buy 0.99×、learn 0.92×、0x81 skill 1.21×；
  - 20261016_195137：0.95×、1.00×、1.01×；
  - 20261027_231329：0.91×、1.08×、0.75×；
  - 20261027_232156：0.95×、0.96×、1.12×；
  - 16:37：0.54×、0.21×、1.37×（只有 30 条，噪声大）。
  - 没有稳定的购买/加点/技能正相关；普通攻击本来就分布在整局，不能当经济/技能日志。
- object_id 相邻转移：increase 247、decrease 169、equal 30,821——连续攻击多数重复同一目标，不是金币/经验式单调量。
- 同一 `(file, actor, frame)` 多个 start byte：7,148 组；7,131 组 object_id 全相等，pairwise 7,316/7,350 相等；34 个不等 pair 全是 0 vs 非零。解释为同一帧多条 BASEATTACK 命令（start 不同、目标相同），不是“kind=观察者通道”。

### 3.4 反例与未知

- **不是金币/HP**：object_id 0–8465 是运行时目标池；0 与非零交替；没有单调性；与购买/加点无稳定对齐。
- **不是死亡**：16:11 0 条；16:37 30 条全在同一 actor；无 victim/killer 字段。
- **不是 BASEATTACK 的完整账本**：只有 5 个文件有 0x84；4 个旧 build + 1 个 11/2 第二局；16:11、11/1 都没有。
- **16:37 负 object_id 未解**：`start=7` + 0xFFFFxxxx 可能不是普通 objectID，可能是打包的攻击参数/偏移；不能按目标 ID 使用。
- `start` 0–7 的语义未解；不能把 0/1/4/7 命名为具体攻击类型。

## 4. 0x01/0x03 与 CC buffer

- tag `0x01/0x03` 的 body 恒 `03 00`，与 TDR command stream 的 CC buffer `0300` 对应：
  - 16:11：4,570 = 4,570（逐 actor 相同）；
  - 16:37：7,063 vs 7,039（+24 在命令流开头 frame ≤37，未逐条对齐）。
- CC 总数：16:11 6,258 条；16:37 14,391 条。除 `0300` 外还有 5/14/17/19/28B 的 buffer（例如 `010000c3e6000000000000705e7f`、`8700000000`），目前未解。
- 没有在 CC 中解出死亡/kill 事件；`0300` 只能当存活/存在 beacon。**死亡事件通道仍未找到。**

## 5. 外部真值表与可确认字段

### 5.1 11/2 第一局（20261102_161129）

- 面板比分 27:6；KDA/金币见 2.4 表。
- 总死亡 33；总击杀 27（T1）+ 6（T2），与对方死亡闭合。
- 这是唯一有 KDA+金币的 11/2 样本；`01-score-equipment.jpg` 与 `02-score-kda.jpg` 的 roster/评分与 report 一致。

### 5.2 11/1（20261101_182452）

- `new_5247758_panel_truth_full.csv`：10 人、47 死亡、KDA/金币齐全（见 2.6 表）。
- 8 个 AI 的 45 死亡在 0x81 里 0 条；两个真人的 2 死亡只有 1 个 slot6 burst 命中，另 1 个漏检。

### 5.3 可确认/不可确认

| 字段 | 状态 | 说明 |
|---|---|---|
| 0x81 消息类型 | **确认** | TDR CSSYNC 129 USEDIRECTIONALSKILL；11/2 逐字节、105224 计数 |
| 0x81 slot/degree/object_id/skill_seq/drag | 布局确认 | TDR `b h I i i i H B`；degree x0.01° |
| 0x81 secondary_1/2/3 | 未解 | 可能是打包位置/参数；无 actor/victim 字段 |
| slot6 语义 | 候选 | 召唤师/装备/其他技能类；不是死亡 |
| 0x84 消息类型 | **确认** | TDR CSSYNC 132 BASEATTACK；16:37 逐字节 |
| 0x84 start/object_id | 布局确认 | start 0–7；object_id 0–8465 在池内；16:37 负值未解 |
| 0x03/CC 0300 | **确认** | 存活/存在 beacon；不是死亡 |
| 死亡事件/时间 | **不可确认** | 0x81/0x84/0300 都没有死亡字段；CC 其他 buffer 未解 |
| 死亡人数 | 仅外部真值 | 11/2 第一局 33；11/1 47；16:37 无真值 |
| 击杀者/受害者配对 | **不可确认** | 0x81 只有 caster actor；0x84 只有 start/object_id；0x03 只有 actor |

## 6. 交付物与字段

### 6.1 `agent_death_candidates.csv`（508 行）

- `record_type=mode6_event`：488 行，`semantic=USEDIRECTIONALSKILL_CSSYNC129`，`candidate_status=rejected_not_death`，`is_death_candidate=0`，`death_count_confirmed=0`。
  - 事件级字段：`file/segment/frame/seq/actor_id/player/team/slot/hero_id/hero_name`；
  - TDR 字段：`slot_byte/degree_raw/degree_deg/skill_object_id/secondary_1/2/3/skill_seq/drag_flag`；
  - 原始字段保留：`mode/param16/tail19_hex/tail_word0..3/tail_counter/tail_flag`（兼容旧读法，语义见 2.1）；
  - 上下文：beacon 空档、上下一个 0x81 slot、`tdr_match`。
- `record_type=external_truth_player`：20 行（16:11 10 人 + 11/1 10 人），`candidate_status=external_truth_player_level`，`death_count_confirmed=D`，`external_kda/external_gold/truth_source` 齐全。
- 过滤死亡候选：`record_type=mode6_event` 且 `candidate_status=rejected_not_death`；**confirmed death candidates = 0**。

### 6.2 `agent_0x84_values.csv`（31,373 行）

- `semantic=BASEATTACK_CSSYNC132`；
- `kind/start_byte`、`value_u32/value_i32`、`object_id_u32/object_id_i32/object_id_in_pool`；
- `start`、目标 ID、run、same-frame start 组、近 buy/learn/0x81 skill；
- `tdr_match`：20261016_195137 6,688 条 + 16:37 30 条 exact；其余 24,655 条 `same_layout_no_tool_support`（3 个工具不支持的文件）。0x81 的 `tdr_match` 同样是 exact/same-layout 两档，slot6 exact 454/488。

### 6.3 覆盖率

- slot6 映射：477/488（97.7%），11 条 actor-only。
- 11/2 两局 roster：10/10（report + replay_parser）；16:11/16:37 slot6 全部映射。
- 0x84 文件覆盖：5 个文件；16:11 0 条，11/1 0 条；旧 build 4 个文件 + 16:37 30 条。逐字节证明 6,718/31,373（21.4%）；其余 24,655 行同布局但工具不支持。

## 7. 与旧结论的冲突（重要）

| 旧产物 | 旧结论 | 本次处理 |
|---|---|---|
| `docs/replay_event_stream.md` §5.6/§9.1 | 0x81 mode6=死亡候选（medium） | **撤回**；0x81=USEDIRECTIONALSKILL，slot6 不是死亡 |
| `docs/replay_event_stream.md` §5.7 | 0x84 5B stat 候选/未定 | **更新**；0x84=BASEATTACK，start+object_id |
| `agent_kda_validate.md` | v6=死亡，5069040 27 窗口 | **撤回**；旧 parser 用 `len=flag&0x7f` 只消费 1B，22B 本体被截断；27 窗口是 slot6 技能 burst |
| `agent_kda_validate.md` 105224 “27 窗口与已知表一致” | 已知表=真值 | 该表是另一个 slot6 解析结果，不是死亡真值；R1 22B 解析给出更多 slot6 事件 |
| `normal5v5_gold_ledger_5069040.csv` / `player_gold_events.csv` / `new_5247758_gold_events.csv` | 0x85 金币 source/amount | 仍按 R1：0x85=BUYEQUIP，不是金币；本文不使用 |
| `received_20261102_players.csv` 的 `gold_events/gold_event_total` | 金币 | `gold_events=547` 是 BUYEQUIP 计数；不是金币，未用于本文 |

旧 parser 的关键错误：`0x81` 的 `flag & 0x7f = 1`，只读 1B 就停，导致：
- 0x81 计数偏低（旧 970/1015 vs R1 13,212）；
- 同一 record 后续消息被吞；
- 但仍能读到 body[0]=6，于是把 slot6 误当死亡值。

R1 的 22B 固定长度是正确长度（204,509/204,518 主段精确消费）；本次进一步用 TDR 命令流证明其语义。

## 8. 未解与后续

1. **死亡事件到底在哪个通道？** 0x81/0x84/0x03 都不是。CC 的 5/14/17/19/28B buffer 未解；可能是状态/动画/目标缓存，也可能包含击杀通知，但目前没有证据。
   - 额外按人计数检查（11/2 第一局）：CC `14B/01` 为 750=55、1031=60、296=24；CC `17B/2c` 为 1168=41、1611=43；`5B/87` 为 1168=1、1613=5、750=26；2B 小消息多为每实体 1–2 条。面板死亡是 1168=3、1613=1、750=1、538=1、1611=0、1031=5、296=7、551=3、1799=6、1760=6；没有任何一种 CC 类型按人闭合，不能直接当死亡账本。该检查只否定“计数=死亡”，不排除 CC 内含需要解码的死亡字段。
2. **0x81 slot6/11 的精确语义**：普通技能槽是 1–4；6/11 可能是召唤师/装备主动/其他技能。需要 TDR 枚举或对局操作流（`.ope`）对照。
3. **0x81 secondary_1/2/3**：i32 值常出现 `0x7FFCF83B`、`0xD1E00000` 等，像打包的坐标/参数；未解。
4. **0x84 16:37 的负 object_id**：`start=7` + 0xFFFFxxxx 不符合 0–17,286 目标池；可能是打包攻击参数/偏移，不能当目标 ID。
5. **0x84 的 `start` 枚举**：0–7 的具体攻击类型未解。
6. **帧率/时长**：5069040 按 20fps、5247758 按 9,900/656=15.09fps 估算；5169333/5230306 没有确认 fps，CSV 的 `seconds_est` 留空。
7. **11/2 第二局没有 KDA 真值**；第一局只有面板总 KDA/金币，没有逐次死亡时间。无法做逐死亡时间对齐。
8. **`find_stream` 跳过前 33 条记录**：11/2 frame 比 report seq-1 小 33；16:37 CC 0300 +24 在命令流开头 frame ≤37，与起点差异一致但未逐条对齐。若需要严格从 seq 1 起算，应改用 `replay_parser.inspect_frame_stream` 的起点，本文未改 R1 口径。

## 9. 验证口径

- 0x81/0x84 的“精确”是**tag 流与 TDR 命令流的多重集逐字节相等**（11/2），或 main+tail 计数相等（105224），不是“看起来像”。
- 主段/尾段事件流来自 R1 的既有 99.9956% 精确解析；11/2 direct 解析复用同一 `parse_stream`。
- slot6 burst 只是“同一 actor 相邻 slot6 事件 gap ≤ 10 帧”的分组，不是死亡窗口。
- 外部真值只读截图/CSV，不把面板金币/KDA 写回回放，不伪造逐死亡时间。
- 所有计数可由脚本复跑；`python -m py_compile` 通过。
