# Replay event stream (R1)

`.abc` 帧 payload 的统一解码层。只读静态分析：不启动/连接游戏、不登录、不注入、不修改游戏文件。

> **2026-11-02 D1 纠正（优先于下文旧结论）**：`0x02/0x81` 是 TDR
> `CSSYNC 129 USEDIRECTIONALSKILL`，`0x02/0x84` 是 `CSSYNC 132 BASEATTACK`，
> `0x01/0x03` 是 CC `0300` 存活 beacon；三者都不是死亡/金币/HP。
> 下文 `death_candidate`、`stat_value_candidate`、`mode6=死亡` 等旧标签全部**撤回**，
> 不能用于 KDA/死亡/经济。证据见 `docs/agent_death_0x81.md`。

## 0. 交付物

| 文件 | 内容 |
|---|---|
| `data/replays/_analysis/tools/build_event_stream.py` | 可重复运行的构建器 |
| `data/replays/_analysis/datasets/replay_event_stream.jsonl.gz` | **全量**消息流（含 `0x12/0x13/0x14` 标量），1,540,385 行，26–27 MB gzip（未压缩约 700 MB） |
| `data/replays/_analysis/datasets/replay_event_stream_events.jsonl.gz` | **R2/R3 推荐入口**：去掉标量，326,096 行，~7 MB gzip |
| `data/replays/_analysis/datasets/replay_event_stream_summary.json` | 每个文件/段/标签的计数与覆盖率 |
| `data/replays/_analysis/datasets/replay_event_stream_counts.csv` | `(file, segment, tag, sub, body_len) -> count` |

复跑：

```bash
python data/replays/_analysis/tools/build_event_stream.py
python -m py_compile data/replays/_analysis/tools/build_event_stream.py
```

不修改任何现有数据集；本目录下的旧 CSV 均未改动。

## 1. 为什么需要重建解析器

旧工具（`abc_tags_full.py` 等）对 `tag=0x02` 使用：

```text
len = flag & 0x7f
```

这条规则只对 `flag=0x83/0x84/0x85/0x87` 碰巧接近，对 `0x80/0x81/0x82` 会**少读**（0x80 只读 0 B、0x81 只读 1 B、0x82 只读 2 B），随后把结构体内部字节当成新标签，造成：

- `tokenize_exact_ratio` 只有 0.2%–92%；
- 后续消息被吞掉，所有子标签计数系统性偏低；
- `0x82` 被误读成 2 B “kind+toggle”，`0x85` 被误读成 5 B “source+amount”。

本次用**固定长度表**替代 `flag&0x7f`，并用“payload 必须恰好消费完 + count 前缀必须等于消息数”验证：

```text
0x02/0x80  12 B
0x02/0x81  22 B
0x02/0x82  16 B
0x02/0x83   3 B
0x02/0x84   5 B
0x02/0x85   7 B
0x02/0x86   6 B
0x02/0x87   7 B
```

结果：主段 **204,509 / 204,518 = 99.9956%** 精确；续流 **712 / 712 = 100%**。剩余 9 条是流末尾被截断的记录（消息越界），保留为 `kind=unparsed_record`，不猜测。

> 这也是任务中给出的计数（0x39≈6703、0x02≈5 万、0x03≈4.6 万、0x01/0x01≈1881、0x8a≈2680）低于本文件计数的原因：旧解析器在 `0x02/0x80/0x82/0x85` 处脱同步后丢消息。本文件使用修正后的全量计数。

## 2. 容器语法

### 2.1 主段（main）

```text
seq:u8  00  len:u8  payload[len]  a:u8  00*5  b:u8
payload = count:u8 + tag-stream
```

`seq` 只存低 8 位，逻辑帧号由记录流递增得到；跨文件从第一条记录的 seq 起算。

### 2.2 续流（tail）

当前批次只有 `20260925_105224` 有第二段，共 712 帧（seq 13096–13807）：

```text
frame:u16BE  len:u16BE  type:u8  payload[len]
payload = tag-stream + 1 个记录级尾字节
```

尾字节不属于标签流；去掉最后 1 B 后 712/712 精确解析。`frame_index` 仍以主段首帧为 0，所以续流帧号连续（13096 → frame_index 13062）。

注：`20260925_105224` 的主段最后一条是 seq 13094，续流从 13096 开始；seq 13095 这一帧不在主段 seq 连续链里（`replay_index.csv` 记 13,062 条，本文件主段 13,061 条 + 续流 712 条）。R2 时间轴会看到一个 1 帧缺口，不补造数据。

### 2.3 顶层标签

| tag | 长度 | 含义 |
|---|---:|---|
| `0x01` | `5 + len` | 英雄消息：`hero:u16BE, flag:u8, len:u8, body`；`body[0]` 是子标签 |
| `0x02` | `4 + 固定长度` | 英雄消息：`hero:u16BE, flag:u8, body`；`flag` 是子类型 |
| `0x12` | 3 | 标量 `u16BE`（相机/视口候选） |
| `0x13` | 2 | 标量 `u8` |
| `0x14` | 4 | 标量 `u24BE` |
| `0x1a` | 33 | 稀有 opaque（5169333/5230306） |
| `0x05` | 13 | 稀有 opaque（4742900） |

`count` 前缀在全部 204,509 条成功记录中都等于消息数。

## 3. 统一 schema

JSONL 每行一个消息（或一条未解析记录）：

```json
{
  "file": "...abc",
  "segment": "main|tail",
  "seq": 13096,
  "frame_index": 13062,
  "hero_id": 1879,
  "actor_id": 44,
  "tag": 2,
  "sub": 133,
  "kind": "buy_equip",
  "action": "BUYEQUIP",
  "skill_slot": null,
  "item_id": 1511,
  "target_id": null,
  "x": null,
  "y": null,
  "direction": null,
  "raw_hex": "0207578505e70000002c00",
  "confidence": "high",
  "notes": "85/BUYEQUIP H,I,B: ...",
  "extra": {"team": 2, "slot": 3, "player": "aaa.芸",
            "equip_id": 1511, "object_id": 44, "auto_buy_raw": 0}
}
```

约定：

- `file`：basename；
- `segment`：`main` / `tail`；
- `seq`：记录流逻辑帧号（主段从首帧起递增；tail 沿用文件的 u16 frame）；
- `frame_index`：`seq - 主段首帧 seq`，main 与 tail 连续；
- `hero_id`：`0x01/0x02` 的信封英雄（u16BE）；标量/opaque 为 `null`；
- `actor_id`：已解码的战场对象 ID（0–65 的英雄对象池）；不确定时为 `null`；
- `tag`/`sub`：整数；`sub` 对 `0x01` 是 `body[0]`，对 `0x02` 是 `flag`；
- `kind`：语义大类（见下表）；
- `action`：具体动作/事件名；未知时 `flag_xx`/`sub_xx`；
- `skill_slot`：只填已确认的槽位（`0x02/0x87`、`0x80`、`0x82`）；
- `item_id`：`0x02/0x85` BUYEQUIP 填 `equip_id`；其余为 `null`（装备 ID 同时保留在 `extra.equip_id`）；
- `target_id`：`0x01/0x1e` 的 victim、`0x01/0x2c` 的 target、`0x02/0x80` 的 object_id；
- `x`/`y`：世界坐标（`0x01/0x2c`、`0x01/0x39`、`0x01/0x01`、`0x02/0x82`）；
- `direction`：角度。`0x01/0x2d` 是 1–359；`0x02/0x83` 是带符号 -180..180；
- `raw_hex`：完整消息字节（含 tag），便于回查；
- `confidence`：`high|medium|low|unknown`；
- `notes`：布局、候选语义、反例的简短说明；
- `extra`：形状专属字段（金额、槽位、对象 ID、队伍、玩家名等）。R2/R3 应优先读 `extra`，不要把未确认字段当真理。

### 3.1 kind 计数（全量）

| kind | 条数 | 来源 |
|---|---:|---|
| `scalar` | 1,214,280 | `0x12/0x13/0x14` |
| `move` | 144,052 | `0x02/0x83` MOVE |
| `beacon` | 64,554 | `0x01/0x03` + `0x01/0x87` |
| `stat_value_candidate` | 31,343 | `0x02/0x84`（旧标签；实为 BASEATTACK） |
| `heading` | 21,488 | `0x01/0x2d` |
| `action_state` | 13,212 | `0x02/0x81`（旧标签；实为 USEDIRECTIONALSKILL） |
| `use_objective_skill` | 12,292 | `0x02/0x80` |
| `state_toggle` | 11,051 | `0x01/0x23` + `0x01/0x8a` |
| `trajectory` | 8,715 | `0x01/0x39` |
| `buy_equip` | 7,396 | `0x02/0x85` |
| `use_position_skill` | 3,896 | `0x02/0x82` |
| `world_point` | 2,493 | `0x01/0x01` |
| `learn_skill` | 2,369 | `0x02/0x87` |
| `command` | 2,018 | `0x01/0x2c` |
| `status_effect` | 539 | `0x01/0x29` |
| `unit_interaction` | 314 | `0x01/0x1e` |
| `opaque_event` | 211 | `0x01/0x38` |
| `opaque` | 153 | `0x01` 其他子标签、`0x02/0x86`、`0x1a`、`0x05` |

## 4. 覆盖率

### 4.1 总量

| 指标 | 值 |
|---|---:|
| 批次文件 | 28 |
| 有帧记录流 | 21 |
| 主段记录 | 204,518 |
| 主段精确解析 | 204,509（**99.9956%**） |
| 主段未解析 | 9（流末尾截断） |
| 续流记录 | 712 |
| 续流精确解析 | 712（**100%**） |
| 消息总数 | 1,540,376 |
| 事件流（去标量）行数 | 326,096 |
| 续流行数 | 4,368 |

未进入帧流解析的 7 个文件：`20251202_191545`、`20260401_234221`、`20260401_234517`、`20260429_134758`、`20260522_165211`、`20261028_135516`、`20261028_135520`。它们要么是旧构建（帧流布局不同），要么是 TLV/非帧记录变体；不伪造数据，只在 summary 中标 `no_frame_stream`。

### 4.2 逐文件

| 文件（截断） | 主段记录 | 精确 | 消息数 | 续流 |
|---|---:|---:|---:|---:|
| 20260807_151225_1526784816_154069_1786 | 11,495 | 99.991% | 99,158 | 0 |
| 20260827_004836_171991872_144574_17877 | 11,823 | 100.000% | 88,634 | 0 |
| 20260827_010503_184599314_225994_17877 | 12,365 | 99.992% | 102,492 | 0 |
| 20260827_012122_-968875200_204768_1787 | 11,331 | 100.000% | 95,293 | 0 |
| 20260827_013634_-432004288_198861_1787 | 11,342 | 100.000% | 92,142 | 0 |
| 20260902_221251_1226875664_155848_1788 | 13,502 | 99.993% | 104,096 | 0 |
| 20260902_222816_922764049_209329_17883 | 10,799 | 100.000% | 86,584 | 0 |
| 20260924_113638_48251441_2363_17902201 | 10,514 | 100.000% | 88,970 | 0 |
| 20260925_094930_819986962_5853_1790300 | 5,159 | 100.000% | 10,367 | 0 |
| 20260925_095631_1593860880_29_17903009 | 5,538 | 100.000% | 10,990 | 0 |
| 20260925_101323_1430258451_33_17903014 | 12,256 | 100.000% | 102,912 | 0 |
| 20260925_103058_805307185_6743_1790302 | 12,785 | 99.992% | 98,883 | 0 |
| 20260925_105224_-1505729760_4933_17903 | 13,061 | 99.985% | 118,484 | 712 |
| 20261016_005102_855679761_52398_179208 | 7,527 | 99.987% | 61,838 | 0 |
| 20261016_010346_1325417280_53348_17920 | 9,492 | 99.989% | 81,729 | 0 |
| 20261016_194242_819986993_61671_179215 | 5,929 | 100.000% | 50,412 | 0 |
| 20261016_195137_48243249_47346_1792150 | 6,587 | 100.000% | 43,183 | 0 |
| 20261017_015659_792757010_63227_179217 | 10,027 | 100.000% | 82,403 | 0 |
| 20261027_231329_1323311634_83533_17931 | 7,244 | 100.000% | 61,021 | 0 |
| 20261027_232156_155222801_82079_179311 | 5,875 | 99.983% | 45,709 | 0 |
| 20261101_182452_-1723849936_94263_1793 | 9,867 | 100.000% | 15,076 | 0 |

## 5. `0x02` 子类型（重点）

`0x02` 的 `flag` 高位置 1，低 7 位是子类型，不是长度。下表是最终计数（含 tail）。

| flag | body | 条数 | 语义 | 置信度 |
|---|---:|---:|---|---|
| `0x80` | 12 | 12,292 | **USEOBJECTIVESKILL**：`slot:u8, object_id:u32BE, custom:u8, skill_seq:u16, drag:u32` | high |
| `0x81` | 22 | 13,212 | **USEDIRECTIONALSKILL**：`slot:u8, degree:i16, object_id:u32, secondary_1/2/3:i32, skill_seq:u16, drag:u8` | high（D1） |
| `0x82` | 16 | 3,896 | **USEPOSITIONSKILL**：`slot, x:i32BE, y:i32BE, skill_seq:u16, object_id:u32, drag:u8` | high (object_id 部分 medium) |
| `0x83` | 3 | 144,052 | **MOVE**：`degree:i16BE (-180..180), seq:u8` | high |
| `0x84` | 5 | 31,343 | **BASEATTACK**：`start:u8, object_id:u32BE` | high（D1；旧 build 的 0–8465 是目标池内 ID） |
| `0x85` | 7 | 7,396 | **BUYEQUIP**：`equip_id:u16BE, object_id:u32BE, auto_buy byte` | high (tail byte 未定) |
| `0x86` | 6 | 6 | 稀有 opaque | unknown |
| `0x87` | 7 | 2,369 | **LEARNSKILL**：`hero_object_id:u32BE, slot:u8, level:u8, auto byte` | high (tail byte 未定) |

这三种技能的 schema 与仓库里的 TDR 抓包表 `tools/replay_frame_commands.py`（`CS_SCHEMAS`）逐字段一致，并且长度/字段值域独立吻合：

- `0x80` = id 128 `USEOBJECTIVESKILL b i B H I`；object_id 的常见值是 8/12/24/44/58/65（本批英雄对象池）。
- `0x82` = id 130 `USEPOSITIONSKILL b i i H I B`；x/y 范围约 ±57,000 世界单位。
- `0x83` = id 131 `MOVE h B`；degree 实测 **-180..180**，seq 每英雄回绕。
- `0x85` = id 133 `BUYEQUIP H I B`；`equip_id` 与 `pvp_items_115.csv` 匹配 **7,393/7,396（102/104 个不同 ID）**。
- `0x87` = id 135 `LEARNSKILL I B B B`；`hero_object_id` 7–65，slot 1–4，level 0–5。

### 5.1 `0x02/0x83`：MOVE，不是位置

```text
83 | degree:i16BE | seq:u8
```

- 144,052 条，全部在主段；degree 最小 -180、最大 180；0 与正负各半；
- `axis=0/255` 的旧读法是把 i16 的高字节当成了“轴”；它其实是**符号字节**；
- 旧 `abc_positions.py` / `abc_positions.csv` 把 `0x83` 当“256×256 地图坐标”，这是**错的**，R2 不要使用；
- 反例：若它是位置，同一英雄的连续值应该形成慢速轨迹；实际 degree 在 ±180 内跳变，且与 `0x2c` 世界坐标无线性关系；
- 未解：degree 是移动方向还是摇杆角度；速度不在消息里，不能只靠它重建位置。

### 5.2 `0x02/0x85`：BUYEQUIP，不是金币

```text
85 | equip_id:u16BE | object_id:u32BE | auto_buy:u8
```

- `equip_id` 1,111–22,031，7,393/7,396 命中 `pvp_items_115.csv`（102/104 个不同 ID）；
- `object_id` 0–65，是购买者的战场对象 ID（与 `0x87` 的 `hero_object_id` 同一池）；
- **BUYEQUIP 计数**与 11/2 两局的 `received_20261102_players.csv` 的 `gold_events` 逐玩家一致（547/627，逐人 23/25/21…；由 coordinator 提供并复核）；
- `auto_buy` 字节在本批不是干净的 0/1（实测 0/169/55/232/248…），尾部语义未定，暂存 `extra.auto_buy_raw`；
- **它不是收入事件**：旧 `normal5v5_gold_ledger_5069040.csv`、`player_gold_events.csv`、`new_5247758_gold_events.csv` 的 `source/amount` 是错位读取。BUYEQUIP 是装备/库存变化通知，不含价格或金币余额；不要用 `gold_event_total`。
- R3 用法：`kind=buy_equip` + `extra.equip_id` + `extra.object_id` + `seq`，做购买/装备变化时间线；只有**最终 6 格装备**的买价和能与面板累计金币做严格一致性检查（`cost < panel`，9/10 通过；296 −302g 异常），不能把 unique 全集合的价当花费下界。

### 5.3 `0x02/0x87`：LEARNSKILL

```text
87 | hero_object_id:u32BE | slot:u8 | level:u8 | auto_learn:u8
```

- 2,367 条主段（tail +2），slot 1–4，level 0–5（0-based）；
- 563/563 个 `(file, hero, slot)` 组按 seq 非递减；
- `hero_object_id` 在同一 `(file, hero)` 内恒定（186/186 组无冲突）；
- 末字节 `auto_learn` 在本批不是干净 0/1（0/169/55/…），保留原始值；
- 旧 CSV 的 `actor_id`（data[3]）与本字段的低字节一致，历史数据可继续用于“技能加点顺序”，但请以新 `learn_skill` 行为准。

### 5.4 `0x02/0x82`：USEPOSITIONSKILL

```text
82 | slot:u8 | target_x:i32BE | target_y:i32BE | skill_seq:u16 | object_id:u32BE | drag:u8
```

- slot 1–4；x/y ±57,000 世界单位；drag 0/1；
- `object_id` 多数为 0，少数出现 0x00080000 级大值，字段偏移/含义仍有歧义，标 medium；
- 旧 `agent_state_semantics.md` 的“2 B kind+toggle”是解析器只消费 2 B 的假象；正确长度是 16 B。

### 5.5 `0x02/0x80`：USEOBJECTIVESKILL

```text
80 | slot:u8 | object_id:u32BE | custom:u8 | skill_seq:u16 | drag:u32
```

- slot 1–15；object_id 0–17,286，最常见的是本局英雄对象 ID；
- `skill_seq` = `u16BE`，按英雄递增 1（TDR 声明 H 得到验证；旧读法“seq 以 256 递增”是把 BE 读成 LE 的假象）；`extra.skill_seq_le` 保留反序读数；
- 不是“通用 12 B 帧命令”，而是“对某个对象释放技能”的输入事件。

### 5.6 `0x02/0x81`：USEDIRECTIONALSKILL（D1 纠正）

- 22 B body：`slot:u8, degree:i16BE, object_id:u32, secondary_1:i32, secondary_2:i32, secondary_3:i32, skill_seq:u16, drag_flag:u8`；
- 旧读法 `mode:u8, param:u16BE, 19B tail` 只是字段切分碰巧对齐：`mode` 是 `slot`，`param` 是 degree 的高 16 位的一部分；
- 所谓 `mode6` 是 **slot=6**（方向技能槽），`tail counter` 是 `skill_seq`，`tail flag` 是 `drag_flag`；
- D1 对拍：11/2 16:11 711/711、16:37 1290/1290 与 `tools/replay_frame_commands.py` 的 TDR 命令流逐字节相等；
- **不是死亡/状态/金币**。旧 R1 的 415/488 条 `death_candidate` 全部撤回；confirmed death = 0。

### 5.7 `0x02/0x84`：BASEATTACK（D1 纠正）

- `start:u8, object_id:u32BE`；
- 旧读法 `kind:u8, value:u32BE` 的字段边界正确，但语义是普通攻击命令：`kind` 是 `start`，`value` 是目标 `object_id`；
- D1 对拍：20261016_195137 `6,688/6,688`、16:37 `30/30` 逐字节相等；其余 3 个文件因 `BOOTFRAP selector 26` 不支持，只算同布局；
- `object_id` 在旧 build 的 0–8,465 是运行时目标池内 ID，不是金币/HP；16:37 的 30 条为负值/池外，未解；
- **不是死亡/金币/HP**；可按 `start`/`object_id` 做普通攻击输入，但不能当伤害或击杀。

### 5.8 `0x02/0x86`

6 条，6 B opaque；未知。

## 6. `0x01` 子标签

| sub | body | 条数 | kind/action | 语义 | 置信度 |
|---|---:|---:|---|---|---|
| `0x01` | 14 | 2,493 | `world_point/point_update` | `i32 A, u32 0, i32 B, u8 flag`；世界点；相机/瞄准锚点候选 | low |
| `0x03` | 2 | 64,339 | `beacon/alive_beacon` | 恒 `03 00`；出现/存活 beacon | medium |
| `0x1e` | 19 | 314 | `unit_interaction/hit_event_candidate` | `type, 14×00, victim:u16BE, 01` | low |
| `0x23` | 2 | 2,913 | `state_toggle/binary_state` | `23 00/01` 逐英雄 bool | low |
| `0x29` | 17 | 539 | `status_effect/status_event` | `29 000000 actor id:u32BE param:i32BE tail:u32BE` | low–medium |
| `0x2c` | 17 | 2,018 | `command/aim_point_command` | `kind flag target x y counter` | medium |
| `0x2d` | 3 | 21,488 | `heading/aim_direction` | `degree:u16BE` 1–359 | high |
| `0x38` | 29 | 211 | `opaque_event/typed_event` | `u32 value + 21×00 + u24 type` | unknown |
| `0x39` | 9 | 8,715 | `trajectory/aim_trajectory_point` | `i32 x, i32 y` 世界轨迹 | medium |
| `0x87` | 5 | 215 | `beacon/skill_panel_beacon` | 恒 `87 00000000` | unknown |
| `0x8a` | 6 | 8,138 | `state_toggle/binary_state` | `flag 000000 actor` | low |
| `0x1f` | 28 | 46 | opaque | 高光通知 | low |
| `0x20` | 20 | 12 | opaque | 高光详情 | low |
| 其他 | var | ~70 | opaque | 0x73/0x7d/0x79/… | unknown |

### 6.1 `0x39`：与 `0x2c` 目标点绑定的密集轨迹

- 布局：`39 | i32 x | i32 y`（不是 4×i16；两个 32 位大端坐标）；
- 236 个 episode（同英雄按 seq 间隔 ≤5 切分）中，**142 个首点与 ±2 帧内某个 `0x2c` 的 (x,y) 完全相等**；232/236 的 episode 在 ±3 帧内有 `0x2c`；
- 每个 episode 1–30 帧、约 4 个采样/帧，轨迹从 `0x2c` 目标点出发向外扫；
- 候选语义：技能/攻击指示器的拖动轨迹，或弹道轨迹；**不是英雄连续位置**；
- 反例：轨迹起点是目标点而不是英雄位置；只有 4 个英雄/文件有该流；
- 未解：指示器 vs 弹道；与技能槽的对应。

### 6.2 `0x03`：存活/出现 beacon

- 恒 `03 00`，每个英雄 40–633 条（每文件 42–6,486 条），事件驱动、非每帧；
- 旧文档把它与 `0x81 mode6` 关联为“死亡空档”；D1 已证明 `mode6` 是方向技能 slot，**该关联撤回**；
- beacon 空档本身仍可能反映回城/挂机/通道稀疏，但**不能当死亡真值**，也不能反推死亡时间；
- R3 用法：只可作为活动/存在性锚点，不能生成 KDA。

### 6.3 `0x01/0x01`：世界点，不是单位位置

- `i32 A, u32 0, i32 B, u8 flag`；A/B 是 ±55,000 级世界坐标；
- 仅在 16 个文件的**部分英雄**出现（每文件 1–5 人）；同队/观察队偏向明显；
- 值会在固定点停留数秒到数分钟，也会平滑移动；`(13957,16637)`、`(±38700,±38700)`、`(-18523,23303)` 等坐标跨文件重复，像地图固定点/基地；
- 候选：相机/瞄准锚点/最后已知点；不是英雄连续位置；
- 反例：`0x2c` 的 target/x/y 与该点无稳定关系；同英雄的 `0x83` 是 MOVE 方向，不能用来对照位置；
- 未解：到底属于相机、观战者、还是某个 UI 锚点。

### 6.4 `0x01/0x8a`：逐英雄二值流

- `8a | flag:0/1 | 00 00 00 | actorID:u8`；
- actor 与该英雄的 `0x87 hero_object_id` 低字节一致（186/186 组恒定）；
- flag 0/1 近乎各半；按消息看每 1–2 秒切换一次，短 run 为主；
- 候选：可见性/战斗/冷却/可操作状态；**没有足够证据命名**；
- 反例：不是 1 帧脉冲（同一状态会保持多个消息间隔）；不是死亡（死亡窗口更长）；只覆盖部分英雄/队伍；
- 未解。

### 6.5 `0x23`：0/1 状态窗口

- `23 00/01`；主样本 254 条/120 窗口，窗口 0.2–3.2 s；
- 窗口内同英雄命令/瞄准/命中/金币极少；像硬控/僵直；
- 反例：不是死亡（太短）；与 `0x03` 长空档有重叠，说明也可能只是“无活动”；与击杀/金币流水无稳定对齐；
- 置信度 low（CC 候选）。

### 6.6 `0x1e`：单位交互，不是伤害表

- `1e | type:u8 | 14×00 | victim:u16BE | 01`；
- victim 0–994，属于运行时 objectID 池，**不命中** 10 人 entityID/heroID/actorID；
- 没有 damage/skillId/单位类型字段；
- type 2/3/4/7；与击杀金/`0x1e` 无稳定时间对齐；
- 置信度 low；只能当“发生了某次单位交互”，不能当伤害/击杀真值。

### 6.7 `0x29`：状态/效果流

- `29 | 000000 | actor:u8 | id:u32BE | param:i32BE | tail:u32BE`；
- actor 与 `0x87/0x80` 的 object_id 一致（0 冲突）；
- id 900011 = 救援/打包濒死队友（medium-high）；91060 在多个不同英雄上重复出现，**不能**当小乔大招/技能名；11990 未命名；
- 重复帧状态流，不是回城/施法日志；置信度 low–medium。

### 6.8 `0x2c`：目标点命令

- `2c | kind:u8 | flag:u8 | target:u16BE | x:i32BE | y:i32BE | counter:u32BE`；
- `flag=1` ⇒ cancel（target=0xFFFF, x=y=0）；
- kind 1/2/3/4；type=`kind<<8|flag`，实测 0x0100/0x0200/0x0300/0x0400 及 cancel 变体；
- 坐标是世界单位（±52,000），是**事件目标点**，不是连续位置；
- 与 `0x39` 强绑定（142/236 首点完全相等）；
- target 1–359，**不是**英雄 ID 的富集池；不能按目标英雄解释；
- 置信度 medium；kind 语义未定。

### 6.9 `0x2d`：朝向

- `2d | degree:u16BE`，1–359；
- 只在 5 个文件、被记录/本地英雄上出现；成簇出现，是瞄准/视角方向，不是移动方向；
- 置信度 high（布局+语义）。

### 6.10 `0x38`：29 B typed event

```text
38 | value:u32BE | 21×00 | type:u24BE
```

- type = 107 或 546601/546602/546603；value = 0–5 或 ~5.4M；
- 与 `0x8a` 的英雄集合高度重合；只出现在 5 个非 5069040 文件；
- 语义未知；不是死亡/击杀日志（数量/时刻对不上）；置信度 unknown。

### 6.11 `0x01/0x87`：常量 beacon

- 恒 `87 00000000`，215 条；
- 与 `0x02/0x87` LEARNSKILL 的最近距离中位 **190 帧**，1/215 在 ±2 帧内 → **不是**学习确认/ack；
- 语义未知。

## 7. 标量与稀有 opaque

| tag | 条数 | 布局 | 说明 |
|---|---:|---|---|
| `0x12` | 992,494 | `u16BE`（首字节 2-bit 前缀 + 6-bit signed 候选） | 每帧 5–8 个；相机/视口/效果标量候选；未解 |
| `0x13` | 165,109 | `u8` | 第二标量；未解 |
| `0x14` | 56,677 | `u24BE` | 稀有标量；未解 |
| `0x1a` | 27 | 33 B opaque：`u16 0, u16 x, …` | 仅 5169333/5230306；`u16_1` 像英雄/actor ID；未解 |
| `0x05` | 8 | 13 B opaque | 仅 4742900；未解 |

标量只进全量 `.jsonl.gz`，不进 `events.jsonl.gz`；R2/R3 一般不需要。

## 8. R2（2D 查看器）可直接用的字段

推荐只读 `replay_event_stream_events.jsonl.gz`，按 `file` + `frame_index` 排序：

| 画面元素 | 过滤 | 字段 |
|---|---|---|
| 英雄移动方向箭头 | `kind=move` | `hero_id`, `direction`（-180..180，转 0..360 用 `(d+360)%360`）, `seq` |
| 朝向/瞄准 | `kind=heading` | `direction`（1–359） |
| 方向技能瞄准 | `kind=use_position_skill` | `hero_id`, `skill_slot`, `x`, `y`, `extra.skill_seq` |
| 指向对象的技能 | `kind=use_objective_skill` | `hero_id`, `skill_slot`, `target_id` |
| 目标点命令 | `kind=command` | `x`, `y`, `target_id`, `extra.kind_byte`, `extra.flag` |
| 技能拖动轨迹 | `kind=trajectory` | `x`, `y`（按 seq 连成 polyline） |
| 技能加点 | `kind=learn_skill` | `skill_slot`, `extra.level` |
| 装备购买 | `kind=buy_equip` | `extra.equip_id`, `extra.object_id` |
| 存活 beacon | `kind=beacon` | `action=alive_beacon`；**不表示死亡/复活** |
| 队伍/槽位/玩家名 | 任意 hero 行 | `extra.team`, `extra.slot`, `extra.player` |

R2 注意：

- **不要**把 `0x83` 当坐标；它只有方向。没有速度/位置，不能单独重建轨迹。
- `0x01/0x01` 的 x/y 是世界点，但不是英雄位置；只能当相机/锚点候选。
- `0x01/0x39` 的轨迹是“从 0x2c 目标点出发的拖动/弹道”，不是英雄走位。
- `0x2c`/`0x82` 的 x/y 是**事件目标点**，不是连续位置。
- tail 段的 `frame_index` 已与主段连续，可直接接在时间轴后面。
- 不要使用旧 `abc_positions.csv`；它是 0x83 的误读。

## 9. R3（死亡/经济/装备）可直接用的字段

### 9.1 死亡

- **回放内没有可确认的死亡事件**。D1 已证明：
  - `0x02/0x81` = `USEDIRECTIONALSKILL`，`slot6` 不是死亡；
  - `0x02/0x84` = `BASEATTACK`，不是死亡/金币/HP；
  - `0x01/0x03` = 存活 beacon，不能反推死亡；
- 旧 R1 的 `kind=action_state, action=death_candidate` 标签全部**撤回**；
  `agent_death_candidates.csv` 中 confirmed death candidates = 0；
- 外部面板 33 死亡与 21 个 slot6 burst 对不上（漂流 D=0 但有 2 burst；5 人合计 16 死亡但 0 burst），
  进一步否定 slot6=死亡；
- `0x1e` 的 victim 不能映射到英雄/小兵/塔；没有 killer/victim 配对，不能生成 KDA；
- KDA/死亡时间只能来自外部面板/OCR/服务器数据。

### 9.2 装备/购买

- `kind=buy_equip`（`0x02/0x85` BUYEQUIP）：7,396 条；
- 字段：`actor_id`（购买者 object_id）、`item_id` / `extra.equip_id`、`extra.object_id`、`seq`；
- `extra.equip_id` 与 `pvp_items_115.csv` 的 `item_id` 可 join（7,393/7,396 命中）；
- **不要**用 unique 全集合 × `buy_price` 当花费下界：集合同时含合成件与成品、原始通知重复，
  11/2 第一局 10/10 人的价格和都大于面板累计金币；
- 可用的是**最终 6 格装备成本**：截图识别最终装备 ID，按 `battle_item.buy_price` 求和，
  再与面板累计金币做严格检查。11/2 第一局 5 名 6/6 完整识别玩家成本 6,175–9,130，
  全部严格小于面板；9/10 满足 `cost < panel`；翳灵崽 `6,130 > 5,828` 是 −302g 异常，
  不能加 300 掩盖，需查装备 ID/价格/面板读数或出售；
- 这仍不是逐笔购买账本/收入曲线；同一装备可能合成/出售，最终格只代表最后持有物；
- `0x02/0x85` 的 `auto_buy` 字节未定，不要当布尔；
- **不要**使用旧 `gold_event_total`、`normal5v5_gold_ledger_5069040.csv`、`player_gold_events.csv`、`new_5247758_gold_events.csv` 的 amount/source 作为金币收入；它们是 0x85 的错位读取。其按玩家计数可以当 BUYEQUIP 计数（与 11/2 的 `received_20261102_players.csv` 一致）。

### 9.3 技能/加点

- `kind=learn_skill`：`skill_slot`、`extra.level`（0-based）、`extra.level_display`；
- 563/563 组单调，可直接做加点顺序/主升技能；
- 与旧 `replay_skill_levels.csv` 的 actor_id 兼容（低字节一致），但以新流为准。

### 9.4 经济（收入）

本回放帧流**没有可靠的逐笔金币收入**：

- `0x85` 是 BUYEQUIP，不是收入；unique 价格和也不是花费；
- `0x84` 是 BASEATTACK，不能当金币；
- 自然金只能按配置（3/s，40s 起）估算；
- 击杀/助攻/推塔金没有独立的全量事件；`0x1e`/`0x29` 不是金币流水。
- 可用口径：最终装备成本与面板累计金币的严格一致性检查（`cost < panel`，9/10 通过；
  296 −302g 异常）；面板含初始 300，不加 300，也不把 296 当校准；
  这不是逐笔收入，不能给单点经济曲线。

## 10. 与现有数据集/报告的冲突（重要）

| 现有产物 | 问题 | 处理 |
|---|---|---|
| `abc_positions.py` / `abc_positions.csv` | 把 `0x02/0x83` 当 256×256 位置；实际是 MOVE `degree:i16BE + seq` | **弃用**；R2 不要用 |
| `normal5v5_gold_ledger_5069040.csv`、`player_gold_events.csv`、`new_5247758_gold_events.csv` | 把 `0x02/0x85` 当金币；`source/amount` 是错位字节 | 只保留“购买计数”用途；**不是收入** |
| `agent_state_semantics.md` 的 0x82 | 2 B `kind+toggle` 是旧解析器只读 2 B 的假象 | 正确为 16 B USEPOSITIONSKILL |
| `agent_damage_skill_objective.md` 的 0x85 章节 | 同上，0x85 不是金币 | 以本文件为准 |
| `abc_tag_fields.csv` 的 0x83/0x82/0x85/0x87 行 | 偏移/长度/语义过时 | 以本文件为准 |
| `replay_frames.csv` 的 `tokenize_exact_ratio` | 旧长度表导致低覆盖率 | 本文件主段 99.9956% |
| `agent_state_semantics.md` / `agent_kda_validate.md` 的 `0x81 mode6=死亡` | D1 已推翻：0x81=USEDIRECTIONALSKILL；0x84=BASEATTACK；0x03=beacon | 以 `docs/agent_death_0x81.md` 为准；**不要用于 KDA/死亡** |
| `replay_event_stream_events.jsonl.gz` 中的 `death_candidate`/`stat_value_candidate` 标签 | 旧 schema 命名，语义已撤回 | R2 不要把它显示成死亡；按 `usedirectional`/`baseattack` 重标或忽略 |

未修改上述任何文件；它们仍在原位置，但 R2/R3 应优先使用 `replay_event_stream_events.jsonl.gz`。

## 11. 未解项

1. `0x02/0x81` 的 `secondary_1/2/3` 语义；`slot` 1–6 的具体技能槽映射。
2. `0x02/0x84` 的 `start` 枚举与 16:37 负 `object_id`；它不是死亡/金币。
3. `0x02/0x85` 的 `auto_buy` 字节；`0x02/0x87` 的 `auto_learn` 字节（本批都不是 0/1）。
4. `0x01/0x01` 的世界点属于相机、观战者还是 UI 锚点。
5. `0x01/0x38` 的 `type` 枚举与 `value` 语义。
6. `0x01/0x8a` 的 flag=什么状态。
7. `0x01/0x1e` 的 victim 运行时 objectID → 单位类型/英雄的映射。
8. `0x29` 的 91060/11990 命名空间；`0x2c` 的 kind 与 target 映射。
9. `0x12/0x13/0x14` 标量通道的语义。
10. `0x02/0x82` 的 `object_id`/`drag` 字段在大值样本上的偏移是否与 TDR 完全一致。
11. 死亡事件到底在哪个通道：0x81/0x84/0x03 已排除；CC 的 5/14/17/19/28B buffer 仍未解。

## 12. 验证口径

- 主段“精确”= 标签流恰好消费完 payload，且 `payload[0] == 消息数`；不是“看起来像”。
- 续流“精确”= 去掉 1 B 记录尾字节后恰好消费完。
- 未解析的 9 条保留 `kind=unparsed_record` 和 `raw_hex`，不补字段。
- 所有计数可由 `replay_event_stream_summary.json` / `replay_event_stream_counts.csv` 复现。
- `python -m py_compile data/replays/_analysis/tools/build_event_stream.py` 通过。
