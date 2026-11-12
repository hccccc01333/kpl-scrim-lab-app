# 技能台账（file-decode + 可选引擎实测层）：每局每次施法一行

状态：**已在 11/2 两局真回放上跑通**，模块 `tools/replay_skill_ledger.py`，接口
`GET /api/replays/{id}/skill-ledger`。本页只讲**证据与口径**，不讲玩法建议。

台账本体是**文件解码**层（`.abc` 输入流）。**引擎实测**（回放暂停帧只读客户端
进程内存）是另一档来源，作为**可选**的逐次施法结果挂在同一行上；本轮只接数据
通路与契约，真实测量数据尚未在本页样例局上灌入（未采样时 `engine=null`）。

## 1. 这一层能回答什么

“某人某局放了哪些技能、各多少次、打的是自己/队友/敌人/非英雄单位”。全部来自
`.abc` 回放**输入流**，不启动游戏、不读进程内存、不碰反作弊。

| 问题 | 本层能否回答 | 说明 |
|---|---|---|
| 钟馗放了 35 次方向技能（槽位 2） | ✅ | 次数=释放尝试数 |
| 妲己 S2 打敌人 32 次、打非英雄单位 13 次 | ✅ | 目标来自 LEARNSKILL 反推的对象池 |
| 鲁班大师 S2 连线队友 | ⚠️ 可出 ally-hero 计数，但样例局里没这英雄 | 口径已就绪 |
| 钩子**命中**几次 | ❌ 文件层；⚠️ 仅当该次 cast 被引擎实测层采样（见 §7） | 输入流没有命中结果 |
| 给盾数值 / 控制时长 | ❌ 文件层；⚠️ 同上 | 只有引擎实测层能回答被采样的那几次 |
| 伤害/金币/KDA | ❌ | 见 `docs/replay_data_contract.md` 的边界 |

## 2. 两种 id 空间（关键）

| id | 例子 | 来源 |
|---|---|---|
| 名册实体 id（大随机数） | 1168 / 1613 | `.abc` 十人块 `entityId`；命令条目的外层 `wObjID` 就是它 |
| 战斗对象 id（小整数 7–65） | 12 / 25 / 33 | 由 `LEARNSKILL` 每英雄恒定一个（docs 5.3） |

0x80 `USEOBJECTIVESKILL` 的 `object_id` 是**第二套 id**（目标）。把两套对上，
才知道“打的是谁”：等于自己→`self-anchor`；同阵营英雄→`ally-hero`；敌阵营英雄→
`enemy-hero`；其余→`other-object`（小兵/野怪/召唤物，本层不再细分）。

> `self-anchor` **刻意不叫 `self`**：客户端在“没有外部单位目标”时都会写施法者
> 自己的对象 id，这既包括真正的自我增益（给自己盾），也包括以自身为中心的范围
> 技能（落点在脚下、实际打周围所有人）。文件层无法区分这两类，所以它只声明
> “对象字段指向施法者”，**从不声明命中了谁**。引擎实测层的 `hit` 也必须遵守
> 同一语义：只写引擎实际记录到的被作用对象，不把 `self-anchor` 当成“命中自己”。

11/2 16:11 那局实测：对象池 `{钟馗:12, 妲己:25, 孙悟空:65, 关羽:58, 百里守约:44,
公孙离:33, 吕布:8, 貂蝉:20, 兰陵王:37, 张良:51}`，与逐英雄技能计数一一吻合。

## 3. 字段可信度

| 字段 | 置信度 | 证据 |
|---|---|---|
| 施法者/槽位/技能类型 | decoded | 帧命令逐字节解完，10509/10509 帧 |
| `aimDeg`（方向技能角度） | decoded | 原始值 = centi-degree：2001 次方向施法全在 ±17994 内；÷100 与同英雄 0x2d 朝向样本平均差 2.1–2.4°，100% 落在 20° 内 |
| targeted 目标分类 | decoded | 妲己 S2/S3、张良 S3 全部落在敌人；关羽/公孙离自释技能全部 self-anchor，与技能性质一致 |
| `aimX/aimY`（位置技能落点） | medium | 0x82 坐标 ±5.7 万世界单位；同条目的 `object` 字段均值疑（0xD1E00000 级），未参与解析 |
| 槽位语义（1-4=英雄技能槽） | 推断 | 5/6/7/9/15 归为非英雄技能槽（装备主动/召唤师/扩展），只标注不解释 |
| 次数完整性 | per-hero | 见 §4 |

## 4. 计数完整性：`counter.complete`

`skill_seq` 是**每英雄自增的施法序号**。非 POV 英雄在两局里都是 1..N 且
条数 == 最大序号；POV（自录玩家）可能丢条目：

- `20261102_161129`：百里守约（POV）实录 78 条，序号到 174 → `complete=false`，
  该行次数只是下限；
- `20261102_163751`：十人（含 POV）全部 `complete=true`。

所以台账对每个英雄给出 `counter.{casts,maxSeq,firstSeq,monotonic,complete}`，
**不把缺失静默成 0**。

## 5. 复现

```bash
python -m tools.replay_skill_ledger data/replays/<match>.abc --summary
python -m tools.replay_skill_ledger data/replays/<match>.abc --csv ledger.csv --json ledger.json
python -m tools.replay_skill_ledger data/replays/<match>.abc \
    --engine-outcomes outcomes.json --csv ledger.csv      # 可选引擎实测层，见 §7.3
curl "http://127.0.0.1:<port>/api/replays/<id>/skill-ledger?unit=8"
```

`--catalog resources/hero_skills.csv`（`hero_id,slot,name`）可把槽位名接上；
仓库当前**没有**这份英雄技能名表，所以默认 `skillName=null` —— 宁缺毋滥。

## 6. 与营地数据的关系（不可混用）

营地 `battledetail` 的命中类/控制类字段是**客户端随机上报**的第三层，与
文件解码的“释放次数”不是同一口径：一个是输入事件，一个是结果统计。产品里
必须分列并标注来源层级，禁止相加或互相校验。

引擎实测层（§7）与营地数据同样不可混用：一个是暂停帧读客户端进程内存的离散
采样，一个是营地接口的统计上报，口径、覆盖、置信度都不同。引擎层数据只有
**官方合作**一条合规路径；本台账默认不依赖它（未采样时 `engine=null`），也
不需要 MuMu 或设备才能输出文件解码层。

## 7. 引擎实测层（可选、独立来源、fail-closed）

### 7.1 来源层级定位

产品四档来源（`README.md` 数据口径、`docs/replay_sources_matrix.md`）里，本台账涉及两档：

| 标识 | 含义 | 本台账中的位置 |
|---|---|---|
| **文件解码** | 从 `.abc` 输入流逐条解出施法指令 | 台账本体：`tier=file-decode`、逐次 cast 行 |
| **引擎实测** | 回放客户端运行时读到的引擎状态 | 可选层：每条 cast 的 `engine` 块，`tier=engine-measured` |
| UI 采样 / 估算 | 界面/小地图采样、由已有数据推算 | 本台账不使用 |

引擎实测在本项目里的采集方式是：**MuMu 里跑官方回放，在暂停帧只读
`/proc/<pid>/mem` 读客户端进程内存**，一次暂停得到一份 snapshot。它是**离散采样**：
一次 snapshot 只覆盖那一时刻附近、且我们能定位到的 cast；不是连续记录，也不保证
覆盖全队/全场。它与文件解码**不是同一口径**：文件解码回答“按了什么”，引擎实测
回答“暂停帧时刻引擎里记到了什么”。**禁止把两者相加、取平均或互相校验。**

### 7.2 每行契约（缺测就是 null）

每条 cast 固定带 `engine` 字段：

- 未采样：`"engine": null`（默认；**绝不补 0、绝不推断、绝不从文件层目标复制**）。
- 已采样：

```json
{
  "tier": "engine-measured",
  "source": "engine-memory",
  "confidence": "measured",
  "hit":     {"hit": true, "target": {"kind": "enemy-hero", "unit": 16},
              "evidence": "unit+0x1664 hit flag"},
  "shield":  null,
  "control": {"durationS": 0.8, "target": {"kind": "enemy-hero", "unit": 16}},
  "observedAt": {"frame": 4213, "clockMs": 280866, "snapshot": "snap_pause_1"},
  "notes": ["暂停帧读 unit 对象 +0x1664 命中标记"]
}
```

字段口径：

| 字段 | 允许值 | 缺测 | 说明 |
|---|---|---|---|
| `hit` | `null` 或 `{"hit": true|false|null, "target": ..., "evidence": "..."}` | `null` | `hit=false` 是**实测未命中**，与“未采样”的 `null` 不同；`target` 只写引擎实际记录的对象 |
| `shield` | `null` 或 `{"amount": number|null, "target": ...}` | `null` | `amount=0` 是实测值，不是缺失 |
| `control` | `null` 或 `{"durationS": number|null, "target": ...}` | `null` | 秒；`0` 也是实测值（有测量、时长为 0） |
| `observedAt` | 非空对象，`frame`/`clockMs`/`snapshot` 至少一项 | 必填 | 记录这次测量来自哪次暂停、哪个 snapshot；没有它就不算 engine 实测 |
| `notes` | 字符串列表 | `[]` | 写读的地址/偏移、判定方法；语义未确认必须写在这里 |

`target` 支持字符串（如 `"enemy-hero"`）、单位槽位整数，或对象
`{"kind","unit","heroId","hero","objectId"}`；只允许引擎实际观察到的对象。
**`self-anchor` 不是“命中自己”**：它只表示对象字段指向施法者，自我增益与自身
中心 AoE 无法区分（见 §2）。引擎块同理：`hit.target="self-anchor"` 或
`shield.target="self-anchor"` 只表示引擎记录到的作用对象是施法者，**不能据此
推断“命中自己”或“给了自己盾”**；真实结论必须来自引擎记录的对象/字段，并写进
`evidence`/`notes`。

### 7.3 灌入方式（本轮的 data path）

纯函数（不改文件、不读设备、可单测）：

```python
from tools.replay_skill_ledger import attach_engine_outcomes

report = skill_ledger(abc_bytes)                 # 文件解码层
report = attach_engine_outcomes(report, outcomes)  # 返回新对象，原 report 不被修改
```

`outcomes` 以 cast 的**稳定键 `frame + offset`** 索引，接受三种形状：

```json
{"casts": [{"frame": 4212, "offset": 88123, "hit": {"hit": true, "target": "enemy-hero"},
            "observedAt": {"frame": 4213, "clockMs": 280866, "snapshot": "snap_pause_1"}}]}
```

或同一批行直接作为裸列表；或直接映射：

```json
{"4212:88123": {"hit": {"hit": true, "target": "enemy-hero"},
                "observedAt": {"clockMs": 280866, "snapshot": "snap_pause_1"}}}
```

守则（全部**报错**而不是猜测）：

- 未知稳定键（该局台账没有这个 `frame+offset`）→ `EngineOutcomeError`；
- 同一 cast 重复挂载、或覆盖已有 `engine` 块 → 报错；
- `outcomes` 顶层 / outcome / 子对象含未知字段 → 报错（防 `hits`、`damge` 之类静默丢字段）；
- `tier`/`source`/`confidence` 写错（例如把营地或 OCR 数据标成引擎实测）→ 报错；
- 已采样块 `hit`/`shield`/`control` 全为 `null`、或缺 `observedAt` → 报错（缺测应保持 `engine=null`）。

**给 Lead 的灌入示例**（`outcomes.json`）：

```json
{
  "casts": [
    {
      "frame": 4212,
      "offset": 88123,
      "hit": {"hit": true, "target": {"kind": "enemy-hero", "unit": 16},
              "evidence": "unit+0x1664 hit flag; 对照 cast target enemy-hero"},
      "shield": null,
      "control": {"durationS": 0.8, "target": {"kind": "enemy-hero", "unit": 16}},
      "observedAt": {"frame": 4213, "clockMs": 280866, "snapshot": "snap_20261112_1611_pause1"},
      "notes": ["暂停帧读 unit 对象 +0x1664；控制时长语义按 XXXXX 字段，置信度待对拍"]
    }
  ]
}
```

本地导出：

```bash
python -m tools.replay_skill_ledger data/replays/<match>.abc \
    --engine-outcomes data/replays/_analysis/engine_20261112/outcomes.json \
    --csv ledger.csv --json ledger.json
```

CSV 增列（**空单元格 = 该次未实测**，不写 0）：
`engine_hit`（1/0/空）、`engine_hit_target`、`engine_shield`、`engine_shield_target`、
`engine_control_s`、`engine_control_target`、`engine_observed_frame`、
`engine_observed_clock_ms`、`engine_snapshot`。注意 `engine_hit=0` 是实测未命中，
`engine_shield=0`/`engine_control_s=0` 是实测 0，都**不是缺失**。

### 7.4 API provenance

`GET /api/replays/{id}/skill-ledger` 的 `provenance` 固定增加一档：

```json
"engine": {"tier": "engine-measured", "source": "engine-memory",
           "confidence": "measured", "castsMeasured": 0, "castsTotal": 6,
           "note": "本局未挂载引擎实测数据：…缺测=null…禁止相加或互校。"}
```

没有引擎数据时 `castsMeasured=0`、所有 cast 的 `engine` 为 `null`，筛选/404/
字段形状与之前一致（只是多了这一档说明和逐行 `engine:null`）。有数据时
`castsMeasured` 是已采样的 cast 数（`castsTotal` 仍是台账总行数）。

### 7.5 能回答 / 不能回答（别越界）

| 问题 | 引擎实测层 | 说明 |
|---|---|---|
| 被采样的那次 cast 有没有命中、打到了谁 | ✅（有 `hit` 且证据写清时） | 只限该 snapshot 覆盖到的 cast |
| 该次给盾数值、控制时长 | ✅（有 `shield`/`control` 时） | 语义未对拍的字段必须写在 `notes` 里并标置信度 |
| 全场每次 cast 的命中率 / 总控制时长 | ❌ | 采样稀疏且不完整，不能当全量；与文件解码次数不可相除/相加 |
| 未采样 cast 的命中/给盾/控制 | ❌ | 保持 `null`，不允许用文件层目标或邻行推断补齐 |
| 伤害、击杀归属、金币 | ❌ | 本层不采集这些；不要因为同一个 snapshot 里能看到就混进台账 |

**证据口径**：一条引擎结论至少要能回答“哪次暂停（snapshot 文件）、读的哪个对象/
偏移、看到了什么”。写不进 `observedAt` + `notes` 的数值，一律按未实测处理。

