# 回放数据与宿主路线证据审计

- 日期：2026-10-30（2026-11-02 续：D1/D2/最终装备成本）
- 范围：只核对已有静态文件、解析代码、设备日志与数据集；不启动/连接游戏进程，不登录，不注入。
- 关联文档：`docs/replay_binary_format.md`（5.13–5.36）、`docs/agent_death_0x81.md`、`docs/packed_inputs.md`、`docs/scope_11_2.md`、`docs/simulation_plan.md`、`.workbuddy/memory/MEMORY.md`。
- 本文目的：把“实际验证成功”“仅推测可行”“已被推翻/需修正”分开，给宿主路线设验收门槛，并按数据需求选择路径。

---

## 0. 结论摘要（TL;DR）

1. **M2 全表读取的证据是硬的，但只硬到“DT_* 查询契约”这一层。**
   E1/E1b 证明宿主可以造出符合 `DT_Count/DT_GetByIndex` 调用的假表对象，并让 825 张表的计数与抽样行逐字节读回；
   它**没有**证明真实表对象 ABI、原生 loader、QtskDB、CRC、行目录或 GameCore 战斗消费者能用同一套对象；E1b 是逐表计数 + 抽样行，不是 205,149 行全量逐字节比较。
2. **CS 缓冲只通过了 Push，Commit 没有通过。**
   `PushCsBuffer` 只依赖 `+0x18/+0x20/+0x24`，假对象即可成功；
   `CommitCsBuffer` 仍 SIGSEGV，说明它还依赖真实上下文/锁/回调等未满足状态。没有完整 CS 流、没有开局命令、没有帧推进、没有状态输出。
3. **回放组成需要修正：主帧流之后还有第二段 712 帧（主样本 13096–13807），当前数据集漏掉了它。**
   第二段是**输入续流**（408 条朝向、23 条坐标命令、181 条事件），不是状态快照；其 payload 省略了主段的 count 前缀。
   尾部 102/106 B 是 **10 个槽位的 entity ID + 评分×100 表 + 本地槽位/英雄**；次值不是皮肤（5.105c/R2 已修正），也不是 KDA/经济/结算。
4. **回放文件内没有完整 KDA/经济/血量/伤害/结算 10 人快照；营地官方数据补了 KDA/团队金币/位置。**
   本地 `camp-1793606215` 有 10 人 KDA/评分、23 个团队金币点、10×693 逐秒位置，
   与面板求和 41,000/29,248 对拍为 41,021/29,266（差 21/18g），KDA 10/10 一致；
   仍没有逐人 1 秒金币、原始输出/承伤/总经济。
   5069040/11-02 的 `0x02/0x85` 都是 **BUYEQUIP**，不是金币；旧 `player_gold_events` /
   `normal5v5_gold_ledger_5069040` 的 source/amount 是 0x85 的错位读取；
   只有 5230306 变体的 `02/80` 有 5 条累计金币/经验快照（build-specific，非逐事件）。
   `COMDT_GAME_30SEC_INFO` 是客户端→服务器的 30 秒统计协议，不在回放里。
   11/2 的 `0x81`/`0x84` 已确认是 `USEDIRECTIONALSKILL`/`BASEATTACK`，不是死亡事件；
   `0x03` 是存活 beacon。旧 `0x81 mode6=死亡` 已撤回，11/2 回放内没有可确认死亡事件。
   最终 6 格装备成本与面板累计金币可做严格一致性检查（9/10 满足 `cost < panel`；
   296 `6,130 > 5,828` 是 −302g 异常，待查），但不是逐笔购买/收入账本。
5. **原生回放入口不在 GameCore。**
   `libGameCore.so` 没有 `StartHostReplay/PureReplayStart/StartLevel` 导出，只有无关的 `visualReplayPipe` 字符串；
   回放入口全在 il2cpp 托管层（`QuickReplaySystem` / `GameReplayModule` / `SGW`），依赖完整 C#/Unity/资源/账号栈。
   关键入口方法还被加密或编译成不可读桩，无法还原成“一个可复用的原生 API”。
6. **宿主路线应设门槛，当前建议暂停 MVSS-B（真正跑一局）。**
   当前 5 项验收条件没有一项完整通过，只有 Push 一个子项部分通过；下一步若仍需伪造 context 字段/vtable 或猜 15 个初始化变量，就应停止。
   近期可交付的是**基于输入的回放分析**；KDA/经济/血量/伤害应优先走录屏 OCR/CV、结算界面或服务器/战绩数据，而不是完整模拟。

---

## 1. 证据分级总表

标记：✅ 已验证（有代码/日志/文件逐字节证据）；◐ 合理推断/部分验证；❌ 已推翻或需修正。

### 1.1 M2 配置表与宿主读表

| 结论 | 级别 | 证据 | 边界 |
|---|---|---|---|
| 825 张表有行数据，205,149 行，71,923,748 B | ✅ | `dtab_blocks/` 825 个 `.bin`；`tables_manifest.csv`；`docs/replay_binary_format.md` 5.21 | 只覆盖本地构建/离线可加载表；130 张空表未证明“永远为空” |
| 每张表块满足 `0x98 + rows*stride == 文件长度`，825/825 | ✅ | 5.21；`dtab_blocks/*.meta` | 只证明块布局，不证明字段语义 |
| 宿主 `ModuleInit` 可在自建 ARM64 进程跑完 | ✅ | `device/e1_gc_sim0.log`：`ModuleInit -> -777077424`；`e1b...` 同样非零 | `ModuleInit` 不是“开一局”，CS 数组仍为 0 |
| `DT_Count/DT_GetByIndex` 走 `*(0x5118810)→0x52742a0→array[index]→vtable+0x18/+0x20` | ✅ | E1 反汇编 + 运行；`DT_Count(83)=53`，53 行逐字节一致 | 只验证查询路径；未验证真实表对象由谁构造 |
| 宿主可注册全部 825 张假表，计数全匹配、抽样行逐字节一致 | ✅ | `e1b_gc_sim0b.log`：`installed=825 verified=825 count_bad=0 row_bad=0 total_rows=205149`；每表抽样 0/mid/last 行 | 假对象 vtable 是宿主自造；只调用 count/get 两个槽；未逐行全量比较 |
| 真实原生 loader/QtskDB 可用 | ◐ | 静态候选 `DatabinTableBase::LoadLocalData 0x2a36308`、顶层 loader `0x3cd9480`；未运行 | 未证明能建表对象、CRC、行目录、字符串池 |
| 48 张表字段名/行解码正确 | ◐ | `tables_decoded/` 48 CSV；自然对齐布局 | 字段名来自 C# 声明顺序；未与真实消费者逐字段对拍 |
| 表语义（例如 `svr2GamecoreCfg` 的 confType）已全解 | ❌/◐ | KV 值与表默认值 25/25 对齐；confType 语义仍未解 | 5.16.7 明确说逐项语义未解 |

**全表读取究竟证明了什么：**

- 证明了：表块格式、注册表槽位、`DT_*` 调用契约、宿主能提供符合该契约的对象。
- 没有证明：真实表对象的构造/生命周期、原生 loader 的输入、GameCore 战斗代码会接受宿主对象、表字段语义、字符串池解析。
- 因此 E1/E1b 是 **MVSS-A 的数据契约完成**，不是“GameCore 已经能读真实配置跑战斗”。

### 1.2 M4/M5 CS 缓冲与帧循环

| 结论 | 级别 | 证据 | 边界 |
|---|---|---|---|
| `ModuleInit` 后 CS 数组 `0x52c3250 == 0` | ✅ | `e1_gc_sim0.log`、`e1b_gc_sim0b.log` | 说明上下文未安装；不是 FIFO 链不存在 |
| `PushCsBuffer` 只读 `+0x18/+0x20/+0x24`，假对象可 Push | ✅ | `s3b_gc_fifo0.log`：`PushCsBuffer(64) -> data OK, obj.len=64` | 只证明写入路径的字段契约 |
| `CommitCsBuffer` 用假对象仍 SIGSEGV | ✅ | 同上：`CommitCsBuffer() -> SIG 11 addr=0x10 pc=0x2100a3f8 x0=obj` | 未定位完整缺失字段；不能据此说 Commit 永远不可用 |
| 0x43D301C 是“上下文安装器” | ❌ | 5.35：反汇编显示是引用计数/弱引用赋值助手（+0x48/+0x50/+0xa8/+0xb0） | 5.29/`simulation_plan.md` 的旧说法需修正 |
| 已有完整初始化命令流（S3） | ❌ | 5.34/5.35：443B 中 15 个变量未命名；KV 只到 key 值；无 TDR 命令封装 | 只有 KV 模板 + 标量分类表，不是可 Push 的命令流 |
| 帧推进/状态输出已打通 | ❌ | 无成功日志；`PushViewBuffer/CommitViewBuffer` 未在宿主验证 | 5.23 只到静态调用链 |
| 离线 5V5 可产出回放 | ❌（强证据） | 两次 AutoSave 监视 8+10 分钟无新文件；进程仍在离线对局；5.33 | 不是数学证明，但足以停止等待 AutoSave |
| 离线 5V5 有隐藏表 | ❌ | `mem_databin` 955 对象，825 有行、130 空；对象 rows 与 DB 头 rows 全为 0 | 825 张是当前离线完整集 |

**CS 缓冲究竟证明了什么：**

- 证明了：`PushCsBuffer` 的缓冲对象最小字段布局，以及宿主可以骗过写入路径。
- 没有证明：`CommitCsBuffer` 可用、CS 流格式、TDR 编码、上下文/锁/回调、帧 tick、状态读回。
- 因此 S3b **未通过**；只能说“Push 通、Commit 崩”。

### 1.3 回放数据组成（本轮修正）

| 结论 | 级别 | 证据 | 边界 |
|---|---|---|---|
| 主帧流 194,652 条（27 样本） | ✅ | `replay_frames.csv`；`find_stream` 逐条 seq+1 | 只算第一段 |
| 主样本还有第二段 712 帧（13096–13807） | ✅ | `replay_tail_frames.csv`；seq 连续；`abc_tail_frames.py` | 仅主样本；其他样本无第二段 |
| 第二段是输入续流，不是状态快照 | ✅/◐ | 624 条消息：408 条 `0x2d` 朝向、23 条 `0x2c` 坐标、181 条事件；无 10 人状态字段 | “输入续流”由标签/英雄消息支持；“无状态”只对已解析标签成立 |
| 第二段 payload 省略 count 前缀 | ✅ | 主段 `count + tags`；第二段直接从 `0x12/0x01/0x02` 开始；按无 count 解析覆盖大部分帧 | 仍有 597 帧尾部 1 B 未解析（多为终止符） |
| 尾部 102/106 B 是 entity + 评分表 | ✅ | `replay_tail_roster.csv` 20 样本；`hero_skin_pairs` 实为 entity:rating×100，覆盖 roster + AI 2001–2008 | 次值是评分×100，不是皮肤；字段名是历史误称 |
| 尾部含本地槽位/英雄 | ◐ | 106 B 样本最后 4 B 为 `1`，最后 2 B 等于本地英雄 | 102 B 样本无此字段；槽位语义未用 UI 验证 |
| 尾部是结算/KDA/经济表 | ❌ | 值是 entity ID + 评分×100，不是金币/伤害/KDA | 不能把“有评分”误读成“有经济账本” |
| `.ope` MemoryData 是状态快照 | ❌ | 解码样本仅 4 条、49 B 指针/“null” | 不是 10 人快照 |
| 0x12 标量是经济/血量 | ❌ | 5–10 值/帧、随机/无单调、与经济曲线不相关 | 可能是相机/表现参数，但未命名 |
| `COMDT_GAME_30SEC_INFO` 在回放里 | ❌ | 5.14：定宽/protobuf 签名 0 命中；它是客户端→服务器协议 | 107 字段是权威定义，但不在 `.abc/.ope` |
| 击杀/死亡/助攻由 `BattleNotifyReplayTool` 录制 | ❌（修正 5.13.11） | 5.14.1：该命名空间是编辑器技能回归测试（XML 比对、repeatNum、中文 FrameDoType） | 不能当运行时回放证据 |

**数据集修正量：**

| 数据 | 原数据集 | 第二段补充 | 合计 |
|---|---:|---:|---:|
| 帧 | 194,652 | 712 | 195,364 |
| 命令（0x2c） | 1,528 | 23 | 1,551 |
| 朝向（0x2d） | 16,315 | 408 | 16,723 |
| 事件 | 50,838 | 181 | 51,019 |
| entity/评分名单 | 未建 | 20 样本 | `replay_tail_roster.csv`（历史列名 hero_skin_pairs） |

主样本自身：主段 13,062 帧 + 第二段 712 帧 = 13,774 帧；第二段相当于主段的 5.45%（占该样本全部帧的 5.17%），不是全语料的 5.45%。

### 1.4 原生回放入口

| 结论 | 级别 | 证据 | 边界 |
|---|---|---|---|
| `libGameCore.so` 有回放导出 | ❌ | dynsym 无 `Replay/StartHostReplay/PureReplayStart/StartLevel`；唯一 `Replay` 字符串是 `visualReplayPipe` | 不排除内部未导出函数，但没有可调用入口 |
| 回放入口在 C# 托管层 | ✅ | `GameReplayModule` 104 方法、`QuickReplaySystem` 25 方法、`SGW` 580 方法；metadata 5.16.2 | 方法体不全是可读代码；入口依赖完整客户端 |
| `GameReplayModule::BeginReplay` 地址/代码 | ✅ | live MethodInfo：token 0x6002b68，params=2，methodPointer 0x40002c85a23c → static 0x665a23c；真实函数序言（5.41） | 代码可读；运行仍依赖完整客户端 |
| `SGW::StartHostReplay/PureReplayStart` 地址/代码 | ✅ | live MethodInfo：StartHostReplay token 0x6001654 → static 0x53ce9d4；PureReplayStart token 0x6001516 → static 0x53b5fdc（5.41） | 地址已验证；入口仍是 managed/Unity，不是 native 可复用 API |
| 存在 C#/C++ 模拟器路径 | ◐ | metadata 有 `SGW::PureReplayWaitEndWithCs2CppSimulator`；地址未在本轮 MethodInfo 表中列出 | 只能确认方法名存在；具体实现地址未验证 |
| `StartHostReplay(abhPath)` 需要 `.abh` | ◐ | metadata 签名；`QuickReplayFileHead` 字段；设备 AutoSave 只有 `.abc/.ope`，无 `.abh` | 未证明 `.abc` 可直接走该入口 |
| 回放依赖登录/账号 | ◐ | `QuickReplaySystem` 有 `DownloadAndEnterQPlay/qReplayInfoUrl`；`GameReplayModule` 有 `HostPlayerId/SrvTime` | 静态方法名不能证明每个入口都强制登录；需运行验证，但当前无安全账号 |

**地址级结论的追加修正（2026-10-30 续）**

旧 `addr2method.json` 的生成公式已被 `tools/il2cpp_method_map_check.py --check`
否定：`.data` 的 0xd380ce0 不是“metadata 方法索引 → 代码地址”数组。具体反例：
旧表把 `System.String::get_Length` 标到 0x7491e5c，但该地址字节是
`stp x29,x30,[sp,#-0x30]!` 一类函数序言，不是 `ldr w0,[x0,#0x10]; ret`。
因此所有依赖旧地址的 SGW/GameReplayModule 反汇编结论都必须降为未验证候选；
metadata 里的方法名、字段名、参数名不受影响。

新路径的具名导出锚点（`il2cpp_class_get_method_from_name`、MethodInfo getter）
是有效的；`0x3ad3788 → 0x3ae9344 → 0xba755c0` 的静态链仍有 EH/ABI 矛盾（5.38），
但已经不再需要它：2026-10-31 用离线 5v5 的只读 `/proc/pid/mem` 直接读到了
**真实 MethodInfo**，name/token/params/methodPointer 全部对上（5.41）。

**Ground truth 已取得**：

- `SGW::StartHostReplay` → static `0x53ce9d4`；
- `SGW::PureReplayStart` → static `0x53b5fdc`；
- `GameReplayModule::BeginReplay` → static `0x665a23c`；
- `GameReplayModule::GetBeginLoadMsg` / `UpdateFrame` / `HandleMsg` 等也有真实地址（5.41 表）。

因此旧 `addr2method` 和 `.rodata` pair 表都**不能当方法地址**：pair 表候选
StartHostReplay `0xc6b4020`、BeginReplay `0xc1b68a0` 与真实地址不同；pair 表是
thunk/共享入口标签表（5.39）。独立 IL2CPP 宿主在 MuMu/houdini 上 SIGILL（5.40），
但只读 live dump 已绕过这个环境限制，且没有登录、没有注入。

**从打开回放到送帧的架构链（metadata + 可读反汇编，不是逐指令验证）：**

```
回放 UI / QuickReplaySysMediator
  → QuickReplaySystem.EnterQReplayFile / StartQReplay
  → GameReplayModule.BeginReplay / LoadMsg / AnalyseReplayFile
  → SGW.PureReplayStart / StartHostReplay(abhPath) / BeginLoad
  → GameCoreInit / SetCoreUpdateFrameMode / PushEasyInStartFightCmd
  → VisualFrameReplayManager.UpdateFrame / AdvanceOneFrame / FlushGameCoreFifoForce
  → GameCore CS FIFO (PushCsBuffer/CommitCsBuffer)
  → GameCore 帧推进 → 状态输出（View buffer/回放 UI）
```

可复用与不可复用：

- **可直接复用**：`.abc` 解析、帧/标签/名单/输入分析、`DT_*` 查询契约（在真实表对象可用时）。
- **不可直接复用**：`SGW/GameReplayModule/QuickReplaySystem` 的入口（需要完整 il2cpp/Unity/资源/账号栈）；GameCore 没有回放导出；`.abh` 入口本地没有样本。
- **因此**：把“原生回放入口”当成宿主可调用的一个函数，是没有证据的；宿主路线必须自己重建初始化/帧驱动，不能靠调用回放入口。

---

## 1.5 11/2 死亡通道、packed 输入与最终装备成本（2026-11-02 续）

| 结论 | 级别 | 证据 | 边界 |
|---|---|---|---|
| `0x02/0x81` = `USEDIRECTIONALSKILL`（129），不是死亡 | ✅ | D1：11/2 16:11 711/711、16:37 1290/1290 与 TDR 命令流逐字节相等；body `slot, degree, object_id, secondary×3, skill_seq, drag` | 旧 `mode6` 是 slot=6，不是死亡状态；`secondary_*` 语义未解 |
| `0x02/0x84` = `BASEATTACK`（132），不是金币/HP/死亡 | ✅ | D1：20261016_195137 6,688/6,688、16:37 30/30 逐字节；body `start:u8, object_id:u32` | 16:37 有 30 条负 object_id/池外，未解 |
| `0x01/0x03` 是 CC `0300` 存活 beacon，不是死亡 | ✅ | D1：16:11 4,570/4,570；16:37 7,063 vs 7,039，差 24 条在流开头未对齐 | 不能从 beacon 空档推死亡 |
| 11/2 回放内有可确认死亡事件 | ❌ | `agent_death_candidates.csv` confirmed=0；488 条 slot6 全部 `rejected_not_death` | 旧 R1 `0x81 mode6` 死亡候选全部撤回 |
| 外部面板 33 死亡与 slot6 burst 对不上 | ✅ | 11/2 第一局 21 burst vs 33 死亡；漂流 D=0 但 2 burst；5 人合计 16 死亡但 0 burst | 11/2 第二局无 KDA 真值，不能算死亡候选 |
| BUYEQUIP unique 价格和能当累计花费 | ❌ | 10/10 大于面板累计金币；集合同时含合成件+成品+重复通知 | 仍可用于购买时间线/装备集合 |
| 最终 6 格装备成本能解释面板累计金币量级 | ✅/◐ | `20261102_build_cost_vs_panel.csv`：5 名 6/6 完整识别玩家成本 6,175–9,130，全部严格小于面板；9/10 满足 `cost < panel`；翳灵崽 4 格 6,130 > 面板 5,828，**−302g 异常** | 装备 ID 来自截图人工识别（52/52 可辨认、31 高置信、0 超出购买集合）；未识别格只给下界；296 未解决前不能当校准点 |
| `PLAYER_MOVE`/`PLAYER_ATTACK` 已解出 unit/方向 | ✅ | 5.127：`wMoveInfo=[unit:5][seq:2][sign:1][mag:8]`，`bAttack=[unit:5][seq:2][flag:1]`；camp1 槽位 0–4→unit 8–12、camp2→16–20；三局 213,032 条 0 条 mag>180/非法 unit | unit 是槽位，不是 entity；per-player move/attack 已可归属；方向不是位置，`0x82 kind=2` 只有稀疏锚点 |
| 回放内可恢复逐笔购买/收入曲线 | ❌ | BUYEQUIP 是装备变化通知，不含价格/金币余额；`gold_event_total` 是错位字段；5.130 逐字节确认 0x85 是 BUYEQUIP 镜像 | 最终装备成本是一致性检查，不是账本 |

**经济口径修正**：不再说“BUYEQUIP 购买下界”，也不再加初始 300。正确的两条是：
`最终装备成本 = Σ(最终格装备 buy_price)`，以及严格一致性检查
`最终装备成本 < 面板累计金币`（10 人 9/10 通过；5 名 6/6 完整识别玩家全部通过）。
面板金币是赛后累计金币（`docs/match_data.md`），**已包含初始 300**，不是当前可用余额。
翳灵崽 `6,130 > 5,828`（−302g）是唯一异常：不是加 300 能解释的，需查装备 ID/价格/面板读数或未记录的出售；在查清前不能当校准点。

**官方营地补充（11/2 第一局，已本地化）**：`data/official_replays/camp-1793606215/`
提供团队金币 41,021/29,266、10 人 KDA/评分、10×693 逐秒位置；面板求和
41,000/29,248，差 21/18g，KDA 10/10 一致。它补团队 30 秒金币、位置和 KDA，
但仍没有逐人 1 秒金币、原始输出/承伤/总经济。产物见 `20261102_official_join.md`。

**操作量口径修正（5.127）**：`20261102_player_actions.csv` 的 per-player
`move_events`/`attack_events` 已按 unit 高 5 位映射到十人槽位，可用；
`unit_high5_camp_slot` 是归属方式。`0x82 kind=2` 是稀疏位置锚点，不能积分成逐帧轨迹（5.132 阴性）。

---

## 2. 宿主路线验收门槛

### 2.1 五项必要条件

| # | 条件 | 当前状态 | 判定依据 |
|---|---|---|---|
| G1 | 有真实 `CLevelContext`/`deskPool` 构造路径，不靠伪造字段 | ❌ | 0x43D301C 不是安装器；无构造函数/偏移；15 个标量变量未命名 |
| G2 | 有真实 CS FIFO 上下文，`CommitCsBuffer` 不崩 | ❌（仅 Push 通过） | `s3b_gc_fifo0.log` SIGSEGV |
| G3 | 有可 Push 的初始化命令流（S3），并能被 GameCore 消费 | ❌ | KV/443B 是数据，不是 TDR 命令流；无成功日志 |
| G4 | 能推进至少一帧并读回状态 | ❌ | 无帧 tick/View buffer 成功记录 |
| G5 | 全链路在真实回放/离线对局上对拍，不依赖登录 | ❌ | 离线 5V5 不产回放；context 释放；无安全账号 |

**5.126/5.150 + 2026-11-03 实机补充**：`AdvanceFrameCommands` 的接口和 6 个
MethodInfo 已用真实 metadata 离线定位；MuMu 离线 5v5 与 11/2 回放上下文
都跑过只读探针，稳定命中 4 个：`FrameWindow.HandleFraqBootSingle/Info`、
`CSDT_FRAPBOOT_INFO.unpack`、`GameLogicHelper.AdvanceFrameCommands`。
`FrameWindowHelper.AdvanceFrameCommands` 和 `IGameLogicHelper` 接口方法
未加载/无独立 MethodInfo；当前证据更支持 GameLogicHelper 是实际实现。
尚未在同一帧上完成 frapInfo 确定性比较或 N+1 命令预测，G4–G5 判定不变。

### 2.2 停止规则（建议写死）

满足以下任一情况，**暂停 MVSS-B**，不再继续堆宿主：

1. 下一次最小实验仍需要**伪造新的 vtable/context 字段**才能让 `CommitCsBuffer` 前进；
2. 无法在不登录的情况下拿到**非零 context 快照**或 `CLevelContext` 构造函数；
3. S3 的 15 个变量仍只能靠猜，且没有真实消费者对拍；
4. 需要把完整 il2cpp/Unity/资源栈嵌入宿主才能调用回放入口；
5. 为少量聚合指标（KDA/经济/血量/伤害）需要承担完整模拟成本。

### 2.3 如果还要继续，下一次最小实验

只做一件事，二选一：

- **E4a（优先）**：在离线 5V5 中，于 context holder 非 0 的窗口做一次**只读快照**，确认 `0x52c3250`/`0x52717b0` 的真实对象布局；若拿不到窗口，直接停。
- **E4b**：静态反汇编 `CLevelContext` 构造函数/`GameBuilder` 初始化，找出 443B 标量到字段的写入点；若只能得到字段声明顺序而不能对拍，停。

验收：`CommitCsBuffer` 用真实 context 返回成功，且能推进一帧；否则不进入下一步。

---

## 3. 按数据需求选择路径

| 需求 | 回放里有什么 | 推荐路径 | 不建议 |
|---|---|---|---|
| 赛后 KDA | 回放内无 KDA 字段；命令表无击杀/死亡/助攻；`0x81`/`0x84` 已确认不是死亡；本地营地 `camp-1793606215` 已给 10 人 KDA/评分（10/10 对上面板） | 营地官方数据（已有第一局）；`postgame_ocr.py` 战后截图 OCR；服务器/战绩接口；赛事数据源 | 为 KDA 跑完整模拟；从 `0x81 mode6` 数死亡 |
| 经济曲线 | **没有可靠的逐笔金币收入**；`0x02/0x85` 在 5069040/11-02 都是 BUYEQUIP，旧 gold ledger 是 0x85 错位读取；仅 5230306 的 `02/80` 有 5 条累计快照（build-specific） | 最终 6 格装备成本做严格检查（`cost < panel`，9/10 通过；296 异常）；5230306 快照可做锚点；总经济/曲线仍用 OCR/服务器 | 用 BUYEQUIP unique 价格和当花费；用 `player_gold_events`/`normal5v5_gold_ledger`/`source4/5/6/43` 当收入 |
| 连续位置 | 回放没有逐帧位置；`0x02/0x83` 是输入方向角，不是位置；`0x82 kind=2` 是英雄自身世界坐标的**稀疏锚点**（5.128）；方向积分轨迹阴性（5.132） | 稀疏锚点 + 官方营地回放每人 1 秒位置；连续轨迹用 CV/录屏；模拟（若 G1–G5 通过） | 把 0x83 当位置；把方向积分当轨迹；把 0x2c 当连续位置 |
| 血量 | 未找到 HP 字段 | 回放 UI 血条 OCR/CV；模拟 | 从 0x12 推 HP |
| 伤害 | 未找到伤害字段 | `postgame_ocr.py`（输出/承伤/对塔等总量）；服务器数据；模拟 | 从事件数推伤害 |
| 技能/出装/朝向/事件 | ✅ 已有：0x2d 朝向、0x2c 坐标、0x02 技能升级、0x03/0x23 事件；第二段补充 712 帧 | 直接用现有数据集 + 第二段补充 | 等模拟 |
| 名单/英雄/评分 | ✅ 玩家块 + 尾部 entity/评分表（含 AI 2001–2008）；皮肤从玩家块/agent_skin_ids | 直接用 `replay_players.csv` + `replay_tail_roster.csv` | 把尾部次值当皮肤 |

**近期可交付（不依赖模拟）：**

1. 输入侧回放分析：名单/英雄/皮肤、技能升级顺序、朝向、瞄准/攻击目标点、事件时间线。
2. 把第二段 712 帧合并进分析口径（当前是补充 CSV；合并时加 `segment` 字段，避免与主段 seq 混淆）。
3. 用录屏/结算 OCR 补 KDA、经济总量、伤害总量；经济曲线用回放 UI 面板录制，不做逐帧模拟。

> 项目已有 `postgame_ocr.py`（配套 `tests/test_postgame_ocr.py`），覆盖战后截图的
> 战绩/数据/输出/生存/发育/团队 tab，字段含 `kills/deaths/assists/gold/damageDealt/
> damageTaken/participation` 等；它适合补**赛后总量/占比**，但不提供逐分钟经济曲线
> 或逐帧 HP。经济曲线、连续位置、逐帧血量仍需回放 UI/视频 OCR 或 CV。

**中期只有当 G1–G5 全过才做：**

- 完整状态模拟（HP/伤害/经济/连续位置）。
- 在那之前，宿主路线只保留 M2 的 `DT_*` 数据契约，不承诺“跑完一局”。

---

## 4. 需要修正的旧结论

| 旧说法 | 修正 |
|---|---|
| “所有战绩数字都不在回放里，必须模拟” | 方向对，但表述过宽：第二段 712 帧是漏掉的数据；它仍是输入，不是战绩。应说“现有段没有战绩字段；战绩需另找来源”。 |
| “击杀/死亡/助攻是录制的”（5.13.11） | 5.14.1 已下调：`BattleNotifyReplayTool` 是编辑器测试工具，不能作为运行时回放证据。 |
| “0x43D301C 是上下文安装器” | 5.35 已推翻：它是引用计数/弱引用助手。`simulation_plan.md` 的旧表述需改。 |
| “CS 缓冲已安装，Push/Commit 可验证” | 只验证了 Push；Commit 崩。S3b 未通过。 |
| “帧数据集完整（194,652）” | 主段完整；主样本第二段 712 帧漏掉。补充后 195,364。 |
| “尾部可能是结算/统计表” | 已解析为 entity + 评分×100 + 本地槽位/英雄；不是金币/KDA 结算。 |
| “离线 5V5 有回放” | 两次监视无新 AutoSave；强证据表明不产可用回放。 |
| “原生回放可以作为一个入口复用” | GameCore 无导出；入口在托管层且被加密/依赖完整客户端。 |
| “0x81 mode6 = 死亡候选” | D1 已推翻：0x81 = USEDIRECTIONALSKILL；0x84 = BASEATTACK；0x03 = beacon。11/2 confirmed death candidates = 0。 |
| “0x84 是单位死亡/金币/HP” | D1 已推翻：0x84 = BASEATTACK，body `start:u8, object_id:u32`。 |
| “BUYEQUIP unique 价格和 = 花费下界” | 已推翻：集合含合成件+成品+重复通知，10/10 大于面板累计金币；只用最终 6 格装备成本做严格一致性检查（9/10 通过，296 异常）。 |
| “11/2 是 2 真人 + 8 AI” | 11/2 两局都是 10 真人、0 AI（`blocks.bot` 全 False）。 |
| “PLAYER_MOVE/ATTACK 可按玩家计数” | 5.127 已修正：packed 高 5 位是 unit=槽位（camp1 8–12、camp2 16–20），不是 4/5/6/8/9/10 的 actor 码；per-player move/attack 可归属。 |

---

## 5. 附：本轮新增/更新的产物

| 文件 | 内容 |
|---|---|
| `data/replays/_analysis/tools/abc_tail_frames.py` | 解析第二段帧（无 count 前缀），输出帧/消息/命令/朝向/事件 |
| `data/replays/_analysis/tools/abc_tail_roster.py` | 解析尾部 entity/评分×100 与本地槽位/英雄（列名 hero_skin_pairs 为历史误称） |
| `datasets/replay_tail_frames.csv` | 712 帧（主样本 13096–13807） |
| `datasets/replay_tail_actions.csv` | 624 条消息 |
| `datasets/replay_tail_commands.csv` | 23 条 0x2c 坐标命令 |
| `datasets/replay_tail_heading.csv` | 408 条 0x2d 朝向 |
| `datasets/replay_tail_events.csv` | 181 条事件 |
| `datasets/replay_tail_roster.csv` | 20 个样本的 10 槽英雄/皮肤 + 本地槽位/英雄 |
| `datasets/replay_tail_summary.csv` | 各样本主段末 seq/尾部字节/第二段帧数 |
| `datasets/agent_death_candidates.csv` | D1：488 条 slot6 `rejected_not_death` + 20 条外部真值；confirmed death=0 |
| `datasets/agent_0x84_values.csv` | D1：31,373 条 BASEATTACK |
| `docs/agent_death_0x81.md` | D1：0x81/0x84/0x03 语义纠正与对拍 |
| `datasets/packed_inputs_20261102.csv` | D2：213,032 条 packed MOVE/ATTACK/ATTACKWITHOBJ 解码 |
| `docs/packed_inputs.md` | D2 历史记录；5.127 已把高 5 位修正为 unit=槽位，旧 actor 码仅保留作历史 |
| `datasets/20261102_build_cost_vs_panel.csv` | 11/2 第一局最终 6 格装备成本 vs 面板累计金币 |
| `tools/build_20261102_build_cost.py` | 上述 CSV 的复现脚本 |
| `datasets/20261102_official_join.md` | 营地官方数据与面板/回放对拍：团队金币 21/18g 差、KDA 10/10、逐秒位置 |
| `datasets/20261102_official_players.csv` | 10 人官方 KDA/评分 + 面板金币/对拍标记 |
| `datasets/20261102_official_positions.csv` | 10 人 × 693 逐秒网格位置 |
| `datasets/20261102_official_team_gold.csv` | 23 个约 30 秒团队金币点 |
| `tools/build_20261102_official_join.py` | 上述三个 CSV 的复现脚本 |

**复现：**

```powershell
python data/replays/_analysis/tools/abc_tail_frames.py
python data/replays/_analysis/tools/abc_tail_roster.py
```

---

## 6. 最终建议

- **不要把“全表读取成功”当成“GameCore 可跑一局”**：前者只是查询契约，后者缺上下文、初始化命令流、帧驱动和状态输出。
- **不要为了完整 KDA/经济/血量/伤害承担完整模拟**：回放只有部分 POV/累计金币和购买流水，没有完整 10 人结果；优先录屏 OCR/结算/服务器数据。
- **宿主路线设硬门槛**：G1–G5 未过就暂停 MVSS-B；下一次实验若仍要伪造 context/vtable 或猜字段，直接停。
- **保留并完善输入侧分析**：这是当前唯一有逐字节证据、可稳定交付的数据路径；第二段和尾部名单已补上，先把这部分做成可用的赛训分析。
