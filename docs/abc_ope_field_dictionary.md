# `.abc` / `.ope` 字段字典（2026-11-02）

> **2026-11-02 纠错（优先）**：本文件以下旧字段定义中，
> `0x02/0x85 = 金币流水`、`0x02/0x81 = 死亡/状态`、`0x02/0x84 = 死亡/stat`
> 均已推翻。现行结论：
> - `0x02/0x85` = BUYEQUIP（`equip_id:u16, object_id:u32, auto_buy:u8`）；
> - `0x02/0x81` = USEDIRECTIONALSKILL（22B，`slot/degree/object_id/secondary×3/skill_seq/drag`）；
> - `0x02/0x84` = BASEATTACK（`start:u8, object_id:u32`）；
> - `0x01/0x03` = 存活 beacon，不是死亡。
>
> 以 `docs/replay_event_stream.md`、`docs/agent_death_0x81.md` 和
> `docs/packed_inputs.md` 为准；本文件只在旧 build 的偏移/容器层面保留参考。

本文是字段级清单，不是结论摘要。范围是普通 5v5 的 build 5069040
主样本，以及 5247758 的差异字段；所有偏移都相对所在记录/结构起点。
状态口径：

- **decoded**：offset/width/语义都有直接证据；
- **partial**：offset/width 有证据，语义只到候选；
- **unknown**：知道字段存在，但语义未定；
- **blocked**：位流/压缩层未解，无法给稳定 offset。

证据主文档是 `docs/replay_binary_format.md`；工具是
`replay_parser.py`、`operator_stream.py` 和 `data/replays/_analysis/tools/`。

---

## 1. `.abc` 文件头

`.abc` 头部是 4 个长度前缀字符串，然后本地英雄、昵称：

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| 0x00 | 1+n | 7-bit len + UTF-8 | appVersion | `12.1.1.1` 类 app 版本 | decoded |
| 0x00+ | 1+n | 7-bit len + UTF-8 | resourceVersion | `12.1.1.8` 类资源版本 | decoded |
| 0x00+ | 1+n | 7-bit len + UTF-8 | revision | `4989537` 类 revision | decoded |
| 0x00+ | 1+n | 7-bit len + UTF-8 | build | `5069040`；2026 样本比 2021 公开代码多这一项 | decoded |
| hdr | 4 | u32LE | heroID | 录制者英雄 ID；主样本 187=东皇太一 | decoded |
| hdr+4 | 8 | i64LE | startTime | .NET DateTime ticks | decoded |
| hdr+12 | 1 | u8 | mapType | 主样本 3 | decoded |
| hdr+13 | 4 | u32LE | mapId | 主样本 20111（普通 5v5 地图） | decoded |
| hdr+17 | 1+n | 7-bit len + UTF-8 | userName | 主样本 `佚名(*:` | decoded |
| hdr+ | 1+n | 7-bit len + UTF-8 | userHead | 头像 URL | decoded |
| hdr+ | 1 | u8 | rankGrade | 主样本 19 | decoded |
| hdr+ | 4 | u32LE | rankClass | 主样本 0 | decoded |

`hdr` 是 4 个字符串后的当前位置。字符串长度是 .NET
`BinaryReader.ReadString()` 的 7-bit encoded length（短字符串看起来
就是 1B），不是裸 u8。这个 11 字段顺序来自公开反编译代码
`ihaiucom/wangzhe.WangZheDllCode` 的 `GameReplayModule.cs`；
2021 代码只写 3 个字符串，2026 主样本有第 4 个 `build`，其余顺序
逐字段对上。旧 `parse_header()` 的“12B 未知 + nickname”应作废。

---

## 2. `.abc` 帧记录

每条记录固定头 10 字节 + payload：

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0x00 | 1 | u8 | seq | 记录序号，u8 回绕；主样本从 0x22 起 +1 | decoded |
| +0x01 | 1 | u8 | pad | 恒 0 | decoded |
| +0x02 | 1 | u8 | len | payload 长度；等价于 `len:u16BE` 的高字节 0 | decoded |
| +0x03 | len | bytes | payload | 标签流 | partial |
| +0x03+len | 1 | u8 | trailerA | 语义未定；可能 flag/类型 | unknown |
| +0x04+len | 5 | bytes | trailer5 | 恒 `00 00 00 00 00` | decoded（常量） |
| +0x09+len | 1 | u8 | trailerB | 语义未定；可能校验/结束位 | unknown |

记录总长 = `10 + len`。5247758 的帧率约 15.09 fps；5069040 约
20 fps。payload 的标签流由 `tag:u8` 开始；`0x12/0x13/0x14` 是
内联定长，`0x01/0x02` 是带 entity 的消息。

---

## 3. `.abc` payload 顶层 tag

| tag | payload 形状 | 字段 | 状态 |
|---|---|---|---|
| `0x12` | 重复 2B | `x_raw:u8, y:u8` | decoded/partial |
| `0x13` | 重复 1B | `value:u8` | partial |
| `0x14` | 3B | `value:u24` | unknown |
| `0x01` | `entity:u16BE + sub:u8 + len:u8 + body[len]` | 英雄消息 A | partial |
| `0x02` | `entity:u16BE + sub:u8 + body` | 英雄消息 B；body 长度由 sub 决定 | partial |

### 3.1 `0x12` 可见单位屏幕位置

payload 是 2B 点列表，每点：

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | x_raw | 2 位前缀 + 有符号 6 位；0x80+v→+v，0x40+v→−(v+1) | decoded |
| +1 | 1 | u8 | y | 0–180 | decoded |

`x_raw` 有效域 64–167，104–127 永不出现；解出 `x_signed ∈ [-40,39]`。
每帧 4–10 点，按 x 降序；是可见单位列表，不是玩家槽位，也不能
直接关联玩家。索引不是身份。

### 3.2 `0x13` 第二标量

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | value | 16,187 个、55 个唯一值（72–161）；与 0x12 x 共用 6 位编码候选 | partial |

类型 ID、相机角度、单位朝向三候选均被否证；更像“同坐标码的
第二个标量/次要坐标”，未定名。

### 3.3 `0x14` 稀有 3B

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 3 | u24 | value | 主样本 45 条；值远大于 0–994，不是单位 ID | unknown |

### 3.4 `0x01` 英雄消息 A（容器）

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x01 | 容器 | decoded |
| +1 | 2 | u16BE | entity | 英雄/单位 entityID | decoded |
| +3 | 1 | u8 | flag | 主样本恒 0；**不是子 tag** | decoded |
| +4 | 1 | u8 | len | body 长度 | decoded |
| +5 | len | bytes | body | `body[0]` 才是子 tag（0x2d/0x03/0x23/0x2c/0x1e/0x29/0x1f/0x20/0x48/0x87） | decoded |

主样本 0x01 body 长度分布：2B 1,645、3B 9,407、5B 43、
17B 423、19B 21、20B 1、28B 3。`0x01` 本身不是叶子消息，
必须先取 `body[0]` 再按子 tag 解析。

#### `0x01/0x2d` 移动/朝向

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x2d | 移动/朝向 | decoded |
| +1 | 2 | u16BE | angle | 0–360 角度；77% 连续变化 | decoded |

对应公开 `CSDT_CMD_MOVE.nDegree:i16`；`bSeq` 可能由外层帧序号
承担，2026 body 只有 2B 角度。

#### `0x01/0x03` 状态位

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x03 | 状态位 | decoded |
| +1 | 1 | u8 | state | 0/1；ready/队伍状态候选 | partial |

#### `0x01/0x2c` 目标/瞄准命令

17B 定长；主样本 413 条按新布局全部自洽。**精确定位（2026-11-02）**：
`2c | kind:u8 | flag:u8 | target:u16BE | x:i32BE | y:i32BE |
counter:u32BE`。之前“i24 / 3B pad / u8 counter”的切分作废；99 条
“pad 非零”正是 counter 超过 255，尾部 4B 是大端计数器。

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x2c | 目标/瞄准命令 | decoded |
| +1 | 1 | u8 | kind | 1/2/4；技能/攻击目标类型 | decoded（域） |
| +2 | 1 | u8 | flag | flag=1 取消（22/22 target=0xFFFF、x=y=0） | decoded |
| +3 | 2 | u16BE | target | 单位 objectID/目标；1–65535 | partial（映射） |
| +5 | 4 | i32BE | x | 世界坐标定点/16，±52000 量级 | partial |
| +9 | 4 | i32BE | y | 世界坐标定点/16，±53000 量级 | partial |
| +13 | 4 | u32BE | counter | 逐英雄/逐目标递增计数器；不是 actorID | decoded |

对应公开 `CSDT_CMD_USEPOSITIONSKILL`（`chSlotType + CSDT_VECTOR2 X/Z`，
TDR 大端），target/flag/counter 是 2026 侧新增字段。`target` 的
1–359 英雄富集仍不成立（14/835），单位类型仍 blocked。

`0x2c` 是技能/攻击目标位置，不是推塔命令，也不是连续轨迹。
`target` 的 1–359 池没有英雄富集（14/835，期望 20.5）。

#### `0x01/0x23` 硬控/无法行动窗口

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x23 | 硬控/无法行动 | decoded |
| +1 | 1 | u8 | value | 0/1；窗口开始/结束候选 | partial |

254 条、120 个窗口；107 个 ≤3.2s；窗口内 0x80/0x82/0x2c/0x2d/
0x29/0x1e 几乎全 0。更像眩晕/击飞/压制等硬控/僵直，不是死亡。

#### `0x01/0x1e` 命中事件

19B 定长；主样本 22 条：

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x1e | 命中事件 | decoded |
| +1 | 1 | u8 | type | 2/3/4；技能槽/普攻候选 | partial |
| +2 | 14 | bytes | zeros | 恒 0 | decoded（常量） |
| +16 | 2 | u16BE | victim | 0–994 运行时单位池；110/110 不能映射单位 | decoded（ID）/blocked（单位） |
| +18 | 1 | u8 | tail | 恒 01 | decoded（常量） |

没有 damage、skillId、team、unitType。不是击杀/补刀表。

#### `0x01/0x29` 状态/效果通知

17B 定长；主样本 10 条：

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x29 | 状态/效果通知 | decoded |
| +1 | 3 | bytes | zeros | 恒 000000 | decoded（常量） |
| +4 | 1 | u8 | actorID | 与 0x87 的 actorID 一致 | decoded |
| +5 | 4 | u32BE | id | 900011/91060/11990 等混合命名空间 | partial |
| +9 | 4 | i32BE | param | 事件参数；含义随 id 变 | partial |
| +13 | 4 | u32BE | tail | 尾部；900011 时为 actorID | partial |

`900011`=打包濒死队友（high）；`91060`=buff_effect“峡谷裂口
传送中断被动”（medium）；`11990` 未命名（扁鹊友方效果候选）。
不是技能释放日志，是混合状态/效果通知。

#### `0x01/0x1f` 高光标签通知

**27B/28B 两种 body 长度，字段对齐有 1B 漂移**；下表是按 28B
样本的候选，不能当固定 offset 结论。27B 样本（seq2188，tag5）
里 `c=-25` 在 +2、`a=12` 在 +10、`d=10` 在 +14、actor=798 在
+20、tail 5B 在 +22；28B 样本的 actor 可能落在 +21 或 +22。
0x1f 仍未定死，状态保持 partial。

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x1f | 高光通知 | decoded |
| +1 | 1 | u8 | highlightTag | 1/2/5/21/93/94/244；表 `0x695F084` | partial |
| +2 | 4 | i32BE | c（候选） | −45..+45；经济差/时间差候选 | partial |
| +6 | 4 | u32BE | b（候选） | 语义未定 | unknown |
| +10 | 4 | u32BE | a（候选） | 1–42；分数/时长候选 | partial |
| +14 | 4 | u32BE | d（候选） | 0/4/5/10/12；语义未定 | unknown |
| +18 | 4 | bytes | e（候选） | 语义未定；27B 样本这里已进入 actor | unknown |
| +20/21/22 | 2 | u16BE | actor（候选） | 0x68–0x3C9；高光归属单位候选 | partial |
| tail | 4/5/6 | bytes | tail | 多数 `01 00 00 00 00`，个别 `01 00 04 0f 1a` | unknown |

tag 1/2/5=关键/完美群控；21=群体解控（庄周）；93/94=瞬闪控制；
244 在可用表外。不是 killer/victim 表。

#### `0x01/0x20` 高光详情

20B；主样本 1 条：

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x20 | 高光详情 | decoded |
| +1 | 1 | u8 | highlightTag | 主样本 tag=21；独立命名空间，不能套 0x1f 表 | partial |
| +2 | 16 | 4×u32 | a/b/c/d | 4 个 u32；语义未定 | unknown |
| +18 | 2 | u16BE | actor | 单位 objectID 候选 | partial |

#### `0x01/0x48` 稀有 9B

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x48 | 稀有消息 | decoded |
| +1 | 8 | bytes | body | `48 00 50 43 40 53 52 52 52`（主样本） | unknown |

envelope hero=37120，不在 0–994/1–359 池；不是本局单位 ID。

#### `0x01/0x87` 5B 常量

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x87 | 常量消息 | decoded |
| +1 | 4 | bytes | zeros | 恒 00 00 00 00 | decoded（常量） |

不是 0x02/0x87 的技能升级。

#### 稀有 `0x01/0x39`、`0x01/0x8a`、`0x01/0x38`

- `0x39`：`39 + 4×i16`，9B；坐标/速度类，不是死亡。
- `0x8a`：`8a + flag:u8 + 00 00 00 + actorID:u8`；可见/状态开关。
- `0x38`：29B，尾部 `08 57 2a/2b` 递增；只在非 5069040 帧流，
  不是死亡。

### 3.5 `0x02` 英雄消息 B

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | tag=0x02 | 消息 B | decoded |
| +1 | 2 | u16BE | entity | 英雄/单位 entityID | decoded |
| +3 | 1 | u8 | sub | 子 tag；决定 body 长度 | decoded |
| +4 | n | bytes | body | 子 tag 负载 | partial |

#### `0x02/0x80` 帧命令（12B）

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 2 | u16LE | cmdType | 1/2/3/5/6/7/9；hero-specific action | partial |
| +2 | 2 | u16LE | value | 多为 0；cmdType6 为 256 的倍数（2304/5632/…） | unknown |
| +4 | 2 | u16LE | actor | 1–359 actor-slot；cmdType6 可指其他英雄/非英雄 | decoded（池）/partial（语义） |
| +6 | 4 | u32LE | cmdSeq | 命令序号/位域，非单调 | partial |
| +10 | 2 | u16LE | flag | 0/256 等 | partial |

cmdType 1/2/3 按 actor 强偏置，不是全局 move/attack/skill；更像
hero-specific action ID。cmdType6 的 value 语义未定。

**2026-11-02 复核**：703 条按上表解码，`actor` 与发令英雄的
actorID 对齐（1558→12、1021→65、442→44），确认是 12B 旧命令体；
**不能**按当前 `CSDT_CMD_USEOBJECTIVESKILL` 的 TDR 布局解（那会把
cmdType/actor 读成 16777216 一类垃圾值）。0x80 仍是
cmdType/value/actor/cmdSeq/flag，不是 objective skill 结构。

#### `0x02/0x81` 逐英雄状态位（1B）——已推翻，实为 USEDIRECTIONALSKILL

> 这里的 1B `value` 是旧 build 只读 1 B 的假象；完整 body 22B。
> `value6` 不是死亡，是 slot=6。详见顶部纠错与 `docs/agent_death_0x81.md`。

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | value | 1/2/3/4/6 | partial |

value6=可观测死亡通知（medium，约 0.6，非全量）；value1/2/4=
技能槽使用（medium）；value3=技能3/英雄专属候选。8 个 AI 完全
没有 0x81，212 有死亡但无 v6。

#### `0x02/0x82` 手动瞄准/UI 状态

5069040（2B）：

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | kind | 逐英雄恒定 1/2/3；手动瞄准技能槽候选 | partial |
| +1 | 1 | u8 | toggle | 0/255；不是干净按下/抬起 | partial |

5247758（16B）：`kind:u8 + x:i32BE + y:i32BE + 7B`，位置候选；
不能与 5069040 混用。

#### `0x02/0x85` 金币流水（7B）——已推翻，实为 BUYEQUIP

> 不是金币流水，`source/amount` 是装备 ID/对象 ID 的错位读取。
> 现行字段：`equip_id:u16BE, object_id:u32BE, auto_buy:u8`。详见顶部纠错。

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 1 | u8 | source | 4/5/6/43/44/47/51/86 等 | decoded |
| +1 | 4 | u32LE | amount | 金额；主样本 31–254 | decoded |
| +5 | 2 | u16 | tail | 尾字段；不是单位 ID；主样本多为 33 00/08 00 类 | partial |

`0x85` 实际是 **7B**，不是 5B：`source + amount:u32LE + tail:u16`。
之前只读 `body[1:3]` 是漏了高字节/tail；新回放 `06 a5 00 00 00 33 d2`
= source6, amount165, tail0x33d2。仍然没有单位 ID，逐单位归属
不可得。

`source4` 兵线档位结算、`source6` 野怪全额、`source5` 混合
（31–73/131–146/230–254）、`source43` 击杀/助攻子集、`source44/47/51`
目标类固定底额。不是当前金币，也不是支出。

#### `0x02/0x87` 技能升级（7B）

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| +0 | 2 | bytes | zeros | 恒 00 00 | decoded（常量） |
| +2 | 2 | u16BE | actorID | 与 entityID 双射；每局分配 1–359 | decoded |
| +4 | 1 | u8 | skill | 1–4 技能槽 | decoded |
| +5 | 1 | u8 | levelIndex | 0–5；升级档位 | decoded |
| +6 | 1 | u8 | zero | 恒 0 | decoded（常量） |

不是装备购买；110 个相邻对 0 违反“skill 连续升级”。

#### `0x02/0x00`、`0x02/0x86`

- `0x00`：空 body（0B），心跳/占位。
- `0x86`：6B，主样本 1 条，`00 00 12 52 03 12`；`0x1252=4690`
  不在 0–994/1–359 池，未知稀有。

---

## 4. `.abc` 玩家块

旧 5069040 布局：10 个连续块；`s = off+0x10+nameLen+30`。
5247758 是变长十人块；`+0x02` 是 `kind`（1=真人、2=电脑），不是常量。
正常 5V5 十真人样本中，蓝方真人块带 19 B footer，红方真人块不带，
需用“下一块起点”收尾。

| 相对偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| off+0x00 | 1 | u8 | team | 1/2 | decoded |
| off+0x01 | 1 | u8 | teamEcho | 恒=team | decoded |
| off+0x02 | 1 | u8 | kind | 1=真人、2=电脑 | decoded |
| off+0x03 | 1 | u8 | slot | 0–4 | decoded |
| off+0x04 | 2 | u16BE | reserved | 0 | decoded（常量） |
| off+0x06 | 2 | u16BE | entityID | 战场单位 ID | decoded |
| off+0x08 | 4 | u32BE | accountLevel | 7–30；不是 recordLen | decoded |
| off+0x0C | 4 | u32BE | nameLen | 含 NUL | decoded |
| off+0x10 | n | UTF-8 | name | 玩家名 | decoded |
| post+0x00 | 4 | u32BE | flagA | 2/hash 副本 | partial |
| post+0x08 | 4 | u32LE | accountHash | 账号 hash | decoded |
| post+0x0C | 4 | u32BE | accountConst | 与 s+0x2C 重复 | partial |
| post+0x10 | 4 | u32BE | levelCopy | 等级副本 | decoded |
| post+0x14/0x18 | 4+4 | u32BE | consts | 18362/5 类 | partial |
| s+0x28/0x2C | 4+4 | u32 | hash/const | 同 post | partial |
| s+0x30..0x40 | 4×? | u32BE | consts | 1/2/6/0/0 | partial |
| s+0x48 | 2 | u16BE | heroID | 英雄表 row_id | decoded |
| s+0x4A/0x4C/0x4E | 2 each | u16BE | heroFlags | 0/2、3、1 | partial |
| s+0x6F | 2 | u16BE | heroIDCopy | 英雄 ID 副本 | decoded |
| s+0x7C | 4 | u32BE | skinID | 基础皮肤 ID；1558=18700 | decoded（基础）/partial（星元） |
| s+0xC8..块尾-19 | n | bytes | profile | openid/头像/海报 URL/hash/方案/最近玩家 | partial |
| 块尾-19 | 19 | bytes | footer | 末 11B 恒定 | partial |

主样本 10 人 entity/hero 映射见 5.90。录制者块 `s+0x48` 等于
头部 `localHeroId` 13/13；`s+0x7C` 只给基础皮肤，星元/部件不在。

---

## 5. `.ope` 外层/内层头

`.ope` 外层是 `0x01 + raw DEFLATE`（windowBits=-15），内层是
明文头 + 第二层 raw DEFLATE。

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| 0x00 | 1 | u8 | outerFlag | 0x01 | decoded |
| 0x01.. | n | raw DEFLATE | outerDeflate | 解出内层 14,349B | decoded |
| inner+0x00 | 3 | bytes | magic | `01 01 01` | decoded（常量） |
| inner+0x03 | 1+n | u8+UTF-8 | appVersion | `12.1.1.1` | decoded |
| inner+0x0C | 1+n | u8+UTF-8 | resVersion | `12.1.1.23` | decoded |
| inner+0x16 | 1+n | u8+UTF-8 | build | `4989537` | decoded |
| inner+0x1E | 4+? | bytes | deviceBlock | `29 0E 00 00` + len + `Vivo V2546A` + 设备信息 | partial |
| inner+0x42 | 1+32 | u8+hex | matchId | 32B 对局 ID | decoded |
| inner+0x63 | 1+19 | u8+text | localTime | `2026-10-28 13:55:16` | decoded |
| inner+0x78 | 1 | u8 | flag78 | 01 | unknown |
| inner+0x7E | 4 | u32LE | value7E | 31 | unknown |
| inner+0x82 | 4 | floatLE | value82 | 1.0 | unknown |
| inner+0x86 | 4 | u32LE | tailLen | 14,211；flag+deflate 剩余长度 | decoded |
| inner+0x8A | 1 | u8 | innerFlag | 01 | decoded |
| inner+0x8B.. | n | raw DEFLATE | operatorDeflate | 解出 39,634B operator stream | decoded |

---

## 6. `.ope` operator stream

### 6.1 流头（27B）

| 偏移 | 宽度 | 类型 | 字段 | 说明 | 状态 |
|---:|---:|---|---|---|---|
| 0x00 | 1 | u8 | version | 02 | partial |
| 0x01 | 1 | u8 | reserved | 00 | unknown |
| 0x02 | 1 | u8 | flag | 01 | unknown |
| 0x03 | 3 | varint | startA | 28,403 | partial |
| 0x06 | 1 | u8 | playerCount | 10 候选 | unknown |
| 0x07 | 4 | u32LE | uiLayoutLen | 123，已验证 | decoded |
| 0x0B | 1 | u8 | reserved | 00 | unknown |
| 0x0C | 1 | u8 | flag | 01 | unknown |
| 0x0D | 3 | varint | startB | 28,410 | partial |
| 0x10 | 1 | u8 | value10 | 23 | unknown |
| 0x11 | 1 | u8 | value11 | 23 | unknown |
| 0x12 | 9 | bytes | reserved | 9×00 | unknown |

### 6.2 记录头通则

除 `0x01` 外：`type:u8 + frame:u16LE + payload`；`0x01` 是
`type:u8 + UnityFrame:varint`。所有多字节整数小端，varint 为
无符号 LEB128。

### 6.3 operator 类型枚举与字段

`emOperatorDataType` 顺序固定 0x00–0x19；`0x1A/0x1B` 是
`Num/Max` 哨兵。字段来自 metadata 类声明，位级布局是否全部
可解见“状态”。

| type | 枚举 | 类/字段 | 状态 |
|---:|---|---|---|
| 0x00 | Common | `OperatorData`：frame | decoded |
| 0x01 | UnityFrameOpe | `UnityFrameOperatorData`：UnityFrame | decoded |
| 0x02 | GameCoreFrameOpe | `GamecoreFrameOperatorData`：frame ± UnityFrame | partial |
| 0x03 | SkillUseOpe | `SkillUseOperatorData`：SlotType, SkillId, SkillSeq | partial |
| 0x04 | SkilOpe | `SkillUIOperatorData`：TouchPosition, SlotType, TouchId | partial |
| 0x05 | TouchOpe | `TouchOperatorData`：TouchPosition, TouchId, TouchPhase, SlotType | partial |
| 0x06 | MoveOpe | `MoveOperatorData`：Degree, GameSvrPing, Seq | partial |
| 0x07 | CoreChangeOpe | 类未定位 | blocked |
| 0x08 | SkillBtnForceUpOpe | `SkillBtnForceUpOperatorData`：ButtonState | partial |
| 0x09 | RefreshSkillBtnStatusOpe | 3 字段 | blocked |
| 0x0A | UIntOpe | `UIntOperatorData`：Value | partial |
| 0x0B | UIEventOpe | `UiEventOperatorData`：EventID | decoded |
| 0x0C | CppEventOpe | `CppEventOperatorData`：SlotType, SkillId, Value | partial |
| 0x0D | BtnBrokenContactOpe | `BtnBrokenContactOperatorData`：RawGameObjectInstId | partial |
| 0x0E | GameObjectNameOpe | `GameObjectNameOperatorData`：path | decoded |
| 0x0F | UIViewChangeOpe | `UIViewChangeOperatorData`：ViewType, Open | partial |
| 0x10 | MemoryData | `MemoryOperatorData`：Stream | decoded |
| 0x11 | CustomLog | `CustomLogData`：Log | partial |
| 0x12 | SkillHitRate | `SkillHitOperatorData`：6 字段 | partial |
| 0x13 | SkillSlotOpe | `SkillSlotOperatorData`：SlotType, Value | decoded |
| 0x14 | SkillCancelOpe | `SkillCancelOperatorData`：4 字段 | partial |
| 0x15 | DirSkillOpe | `DirSkillUseOperatorData`：Degree | partial |
| 0x16 | UILayout | `UILayoutData`：20 字段/123B | partial |
| 0x17 | PredictMoveOpe | `PredictMoveData`：3 字段 | blocked |
| 0x18 | SendMsgToServerOpe | `SendNetworkMsgToServerData`：CSMsgID, result | partial |
| 0x19 | DeadOrReviveOpe | `HeroDeadOrReliveData`：hostPlayerId, curPlayerId, reviveTime, configId, isDead 等 8 字段 | partial |

已确认的具体记录：

- `0x0B UIEventOpe`：`type + EventID:varint`；样本 `0B 7D A0 09`→151,677。
- `0x0E GameObjectNameOpe`：`type + frame:u16 + InstId:varint + len:u8 + path`。
- `0x10 MemoryData`：`type + frame:u16 + len:varint + raw`。
- `0x13 SkillSlotOpe`：`type + frame:u16 + SlotType:u8 + Value:u8`。
- `0x16 UILayout`：`type + frame:u16 + 123B`；长度来自流头 `u32@0x07`。

### 6.4 `.ope` 当前报墙

严格解析器只接受 0x00–0x19，样本在 **0x3556（13.5%）** 报墙：
`0x3556` 起为 `b9 08 01 c5 f3 01 …`，前一条 `0x02` 的尾部
`8e f9` 带 varint 继续位，无法收尾。说明 `SkillUse/CppEvent/
SkillSlot` 在该区域有固定位宽字段（疑似 `WriteBitPacked`/
`WriteUshort`）或未解码变体。**因此 `.ope` 的记录 payload 目前
只到“类型+部分字段”，不能声称每个字段都已解。**

**2026-11-02 报墙细化**：0x3540 的 `02 b8 08` 是 GameCoreFrame，
`01` 后 `c3 f3 01` 是 varint；0x3547 的 `03` 是 SkillUseOpe；
其 varint 链在 0x3553 的 `8e f9 02` 是 **3 字节 varint**（不是
2 字节），所以实际有第 9 个 varint `b9 08`，到 0x3558 才结束。
把 0x03 的布局从 7 个 varint 扩到 **9 个**后，39,634B 流可以
完整解析成 **5,087 条记录**（amb 323），但 frame 序列有 1,850
次回退，说明“能到结尾”不等于“布局正确”；9 varint 可能只是
局部特例，仍需字段约束或 writer 代码确认。0x02 的
`frame + operatorType + unityFrame` 变体也能全解，但同样出现
不合理 operatorType（235/178/…），不能直接采用。

**主普通 5v5 `.ope` 与快速赛 `.ope` 不同（2026-11-02）**：
主样本 `20260925_105224` 的 `.ope` 解出 **436,738B** operator
stream；开头不是 39,634B 快速赛样本的 `02 00 01 … 0A 7B 00 00 00`
27B 头，`stream[7:11]` 也不是 123。用现有 `operator_stream`
布局从 0 开始只推进到 **0x58d（约 0.3%）**，UILayout 长度
123/64/128/256/512/1024 都救不回来。**系统搜索** header 起点
0–32 + UILayout 长度 32–2048，最高只到 **0x9b0（0.57%）**。
说明主普通 5v5 的 operator 流是**另一套 header/framing**，
不能把快速赛 39,634B 的 0x3556/9-varint 结论直接套上去；
需要重新定位主 `.ope` 的流头和记录边界。

---

## 7. 字段状态汇总

| 结构 | 已解字段 | 未解/阻塞 |
|---|---|---|
| `.abc` 头 | 4 字符串、localHeroId、昵称 | hdr+4..hdr+16 的 12B |
| `.abc` 帧记录 | seq/pad/len/payload/trailer 常量 | trailerA/trailerB |
| `0x12` | x_raw/x_signed/y、排序、轨迹 | 玩家关联/坐标系 |
| `0x13` | value 域/编码候选 | 语义（三候选否证） |
| `0x14` | 3B 值 | 语义 |
| `0x01/0x2d` | angle | 朝向 vs 瞄准 |
| `0x01/0x2c` | kind/flag/target/x/y/counter | i24、target 语义 |
| `0x01/0x1e` | type/victim/tail | victim 单位映射、damage |
| `0x01/0x29` | actorID/id/param/tail | 11990 命名 |
| `0x01/0x1f` | tag/a/c/actor | b/d/e/tail |
| `0x01/0x20` | tag/actor | 4×u32 语义 |
| `0x02/0x80` | cmdType/actor/seq/flag | value/cmdType6 |
| `0x02/0x81` | slot/degree/object_id/skill_seq/drag（22B） | USEDIRECTIONALSKILL；secondary×3 语义 |
| `0x02/0x82` | slot/x/y/skill_seq/object_id/drag（16B） | object_id 大值/偏移 |
| `0x02/0x84` | start/object_id（5B） | BASEATTACK；不是死亡 |
| `0x02/0x85` | equip_id/object_id/auto_buy | BUYEQUIP；不是金币 |
| `0x02/0x87` | actorID/skill/level | 无（技能升级已解） |
| 玩家块 | team/slot/entity/name/hero/skin/profile | 星元/部分常量 |
| `.ope` 容器 | 外层/内层头、版本/设备/对局/时间 | 0x78/0x7E/0x82 |
| `.ope` operator | 类型枚举、0x0B/0x0E/0x10/0x13/0x16 | 0x3556 后位流/多数 payload 字段 |

---

## 8. 复跑

```bash
python replay_parser.py --help
python operator_stream.py --help
python tools/abc_nested_fields.py
python data/replays/_analysis/tools/agent_objectid_map.py
python data/replays/_analysis/tools/agent_screen_positions.py
python data/replays/_analysis/tools/agent_qts_replay_scan.py
```

`tools/abc_nested_fields.py` 已产出
`data/replays/_analysis/datasets/abc_nested_events_5069040.csv`
（11,453 行）：0x2d 9,407、0x2c 413、0x1e 21、0x29 10、0x1f 3、
0x20 1、0x03 1,308、0x23 247、0x87 43，每行带 frame/offset/
entity/subtag/字段值/raw_hex。

本字典是字段清单；不是“所有字段都已命名”。未知字段保留为
unknown/blocked，避免把候选当定论。
