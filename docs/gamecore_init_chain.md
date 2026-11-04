# GameCore 初始化链静态分析（宿主编排证据）

- 日期：2026-11-03
- 范围：只读静态反汇编 + 既有只读快照；不注入、不登录、不调用游戏函数、不改游戏文件。
- 输入：
  - `data/replays/_analysis/libGameCore.so`（5069040 / 12.1.1.8，86,426,392 B）
  - `data/replays/_analysis/libil2cpp.so`、`global-metadata.dat`（本地构建，方法数 416,645）
  - `data/replays/_analysis/tools/method_addr_names.json`、`kpl_i2cpp.py`、`gcore_disasm.py`
  - `host/fixtures/20261102_161129/context/context_snapshot.json`
  - 设备只读 MethodInfo 记录：`datasets/replay_method_map.csv`、`device/live2_mem/scan_stack.log`
- 所有地址都是 **base-relative / 文件 VA**；运行期必须写 `base + 0x...`。不同构建不可直接套用。

结论先行：

1. **本地 `libil2cpp.so` 的 metadata 与设备快照不是同一构建**：本地 416,645 方法，
   设备 `live2`/`client_probe_*` 为 416,815 方法。`method_addr_names.json` 的地址标签
   不能当方法入口；部分标签落在函数中间，`SGW::GameCoreInit` / `StartLevel` /
   `PureReplayStart` 均如此。
2. **GameCore 没有“创建一局 / 创建 context”的 C 导出**。`ModuleInit` 的引导链
   `0x46AD0CC -> 0x40A0360` 只做约 40 个子系统初始化，不写 context 持有者、
   8 路槽表或 CoreThread 状态。
3. **FIFO 可以宿主安装**：真实 ring ctor `0x49CBD88` + init `0x49CBEEC`，
   只写 `base+0x52C3250` 的 slot0 即可；Push/Commit/Reset 都能工作。
4. **context 不能由宿主创建**：持有者 `0x52717B0` 是 BSS 零；唯一写入路径是
   内部 context pool 的 “按索引激活/安装”函数（`0x409F178`、`0x409F2C8`、
   `0x409F0B8`），它们要求 pool 对象与真实 context 条目；pool 工厂 `0x409EBE4`
   依赖静态为零的运行期回调 `0x51D10BD0` / `0x51D10B30`。
5. **CoreThread 不能作为宿主帧驱动**：创建函数 `0x46B7784` 依赖线程工厂指针
   `0x50B40F48`（静态为 0），且 5v5 本身不走 CoreThread（`docs/replay_binary_format.md`
   5.23.1a）。
6. **第一个缺失步骤**：真实 context 对象（含其 pool/owner）。没有它，槽表不会被
   binder 发布，CS 消费者 `0x46B80E8` 也不会读取 slot0；`.abc` 初始化数据即使推入
   FIFO 也不会推进帧。

---

## 1. 构建与地址校准

### 1.1 本地 libil2cpp 与设备快照不是同一构建

| 数据 | 文件 | 大小 | metadata 版本 | 方法数 | 类型数 |
|---|---|---:|---:|---:|---:|
| 本地 | `global-metadata.dat` | 60,322,264 | 29 | **416,645** | 64,125 |
| 设备 live2 | `device/live2_mem/metadata.bin` | 60,346,368 | 29 | **416,815** | 64,138 |
| 设备 probe 11/02–11/03 | `client_probe_*/metadata.bin` | 60,346,368 | 29 | **416,815** | 64,138 |

后果：

- `method_addr_names.json` 是按本地 metadata 方法索引与本地 `.data` 槽位生成的标签；
  但该槽位表已被 `docs/replay_binary_format.md` 5.37/5.38 否定为“metadata 索引 →
  方法地址”数组。标签只能作候选，不能作入口。
- `datasets/replay_method_map.csv` 的 ground truth 来自 5069040 构建（416,815 方法），
  与本地 libil2cpp 不同构建；其 `0x53B4938`、`0x53B5798`、`0x53B5FDC` 等地址
  不能套到本地文件。下文的本地 C# 地址只做“函数边界校准”，不主张跨构建同名。

### 1.2 代码可读性

- `libGameCore.so` `.text` 可线性反汇编，RELA 已物化；`gcore_disasm.py` 可直接用。
- 本地 `libil2cpp.so` 的 `.text` 明文与单字节 XOR `0xE3` 混排；本轮的 C# 函数边界
  用 `明文 / XOR 0xE3` 两种 key 交叉判定，只有出现标准序言
  （`stp x29,x30,[sp,#-...]!`、`sub sp,sp,#...`）或 `ret` 边界才记为“真实起点”。

---

## 2. C# 初始化链：入口校准

### 2.1 目标方法候选表

“标签地址”来自 `method_addr_names.json`；“真实起点”由序言/`ret` 边界校准；
“名称可信度”指“该地址是否确实属于 metadata 中同名方法”，不是函数边界置信度。

| 目标 | 标签地址 | 标签处字节/序言 | 真实函数起点 | 函数边界 | 标签是否起点 | 名称可信度 | 证据 |
|---|---:|---|---:|---|---|---|---|
| `SGamePInvoke::Init` | `0x55A4020` | `stp x29,x30,[sp,#-0x20]!` | **`0x55A4020`** | `0x55A4020..0x55A4064`（`ret`） | **是** | 中 | 序言 + `ret`；调用 `0x3B0417C`、槽 `0xD4C7028` |
| `SGamePInvoke::SetGameCorePipe` | `0x55A41EC` | `stp x29,x30,[sp,#-0x20]!` | **`0x55A41EC`** | `0x55A41EC..0x55A4230`（`ret`） | **是** | 中 | 同上；槽 `0xD4C7050` |
| `SGW::SetAllKeyDatabin` | `0x55CF0A0` | `sub sp,sp,#0x30; stp x29,x30` | **`0x55CF0A0`** | `0x55CF0A0..0x55CF110`（`ret`） | **是** | 中 | 调用 `0xD4D0DD0`、`0xD5BC0E20`、`0xD5BC0E38` |
| `BattleLogic::DoBattleStart` | `0x694C6A8` | `stp x29,x30,[sp,#-0x30]!` | **`0x694C6A8`** | 下一序言 `0x694C87C`，上界 ≤ `0x1D4` | **是** | 中 | 读静态标志 `0xE295B50`，调用多个托管槽 |
| `SGW::GameCoreInit` | `0x55A7968` | 无；`blr x8` 序列中段 | **`0x55A77E8`** | `0x55A77E8..0x55A79DC`（`br x2`） | **否**（+0x180） | 低 | 0x55A7968 位于函数中部，无 `stp x29`；该函数使用 `w1/x2/x3/w4`，与 metadata 的 0 参数签名不符，说明标签与方法索引已错位 |
| `SGW::StartLevel` | `0x55A956C` | 无；日志/字符串调用中段 | 短函数（上界 `0x55A9584`，起点未定）；大函数 **`0x55A9588`** 起 | `0x55A9588..0x55A9810` | **否** | 低-中 | 标签处是“取 `[x0+0x128]` 并返回”的短函数；6 参数体更像 `0x55A9588` |
| `SGW::PureReplayStart` | `0x55A9EE4` | 无；`mov x1,xzr; ... blr x8` 中段 | **`0x55A9D74`** | `0x55A9D74..0x55A9F70`（`ret`） | **否**（+0x170） | 低-中 | 函数内有 7 参数使用形态，但名称不能由标签证明 |
| `OfflineGameMatchData::DoBattleStart` | `0x5E1B90C` | `str x1,[x0,#0x10]; ret` | 不是函数起点 | 微型 setter | **否** | 低 | 标签直接落在 `str; ret` 上，明显不是 DoBattleStart |

### 2.2 设备 ground truth（5069040 构建，仅作对照）

| 方法 | token | params | process methodPointer | static VA |
|---|---|---:|---:|---:|
| `SGW::GameCoreInit` | `0x6001502` | 0 | `0x40002B5B4938` | `0x53B4938` |
| `SGW::StartLevel` | `0x600150F` | 6 | `0x40002B5B5798` | `0x53B5798` |
| `SGW::PureReplayStart` | `0x6001516` | 7 | `0x40002B5B5FDC` | `0x53B5FDC` |
| `SGamePInvoke::DoBattleStart` | `0x6001457` | 0 | `0x40002B5E7118` | `0x53E7118` |
| `SGamePInvoke::FlushGameCoreFifo` | `0x6001459` | 1 | `0x40002B5E74A8` | `0x53E74A8` |
| `SGamePInvoke::SetGameCorePipe` | `0x600146E` | 1 | `0x40002B5E8D68` | `0x53E8D68` |

来源：`datasets/replay_method_map.csv` + `device/live2_mem/scan_stack.log`（按 `MethodInfo+0x18`
名称指针回 metadata 校验，`+0x52` 参数数匹配）。这组地址与本地标签完全不同，
再次说明本地 `.data` 槽位标签不能当入口。

### 2.3 对宿主计划的含义

- 这些 C# 方法全部是 **managed 方法**，不是 GameCore 可调用 API；它们的函数体里
  调用的是 il2cpp 托管 helper/槽（部分槽在静态文件里为 0，运行期才填），没有
  任何“直接调用 GameCore 导出”的静态调用点。
- 因此宿主不能“调用 `SGW::GameCoreInit`/`StartLevel`/`PureReplayStart` 来启动一局”；
  这与 `docs/replay_binary_format.md` 5.16.1 的“初始化也是数据”一致。
- `SetAllKeyDatabin`/`SetGameCorePipe`/`DoBattleStart` 即使函数边界可确认，也仍然
  依赖完整 il2cpp/Unity 对象与运行期槽；不构成 native 入口。

---

## 3. native GameCore：谁能创建/安装 context、槽表、CoreThread

### 3.1 没有导出可以做这些事

`gamecore_c_exports.txt` 的 123 个 C 导出里没有 context/FIFO/线程创建入口；
相关导出只有：

- `ModuleInit`（`0x46AD0CC`，实际实现 `0x46AD0CC`，槽 `0x522E960`）
- `PushCsBuffer` / `CommitCsBuffer` / `ResetCsBuffer`
- `PushViewBuffer` / `CommitViewBuffer` / `ResetViewBuffer`
- databin / QTS / 压缩 / 场景图等

`ModuleInit` 实现 `0x46AD0CC` 置 `x0=0x542F4B0` 后尾调 `0x40A0360`；
`0x40A0360` 的约 40 个间接调用全部是子系统初始化，**没有**写
`0x52717B0`、`0x52C3250`、`0x544CBD0` 的代码。

### 3.2 静态全局状态

| 目标 | 静态值 | 说明 |
|---|---:|---|
| `[0x4FF5DE8]` | `0x52488B8` | CS 根槽 |
| `[0x52488B8]` | `0x52C3250` | 8 路槽表地址 |
| `[0x52C3250]` | `0` | slot0 对象；BSS 零 |
| `[0x4FF4520]` | `0x51EA4D0` | view/context 根槽 |
| `[0x51EA4D0]` | `0x52717B0` | context 持有者对象 |
| `[0x52717B0]` | `0` | context 指针；BSS 零 |
| `[0x544CBD0]` | `0` | CoreThread 状态机；BSS 零 |
| `[0x50B40F48]` | `0` | CoreThread 线程工厂指针；BSS 零 |
| `[0x51D10BD0]` / `[0x51D10B30]` | `0` | context pool 工厂依赖的运行期回调；BSS 零 |

### 3.3 FIFO：可安装，但只解决“写入”

真实对象路径（与 `docs/cs_fifo_context.md` 一致）：

| 项 | 地址 | 证据 |
|---|---:|---|
| ring ctor | `0x49CBD88` | 设置基础 vtable `0x4FD16F8`、`pthread_rwlock_init`、清计数字段 |
| ring init | `0x49CBEEC` | `+0x08/+0x10` ring、`+0x18/+0x20` staging、默认 malloc/free |
| PushCsBuffer | `0x460A3AC -> 0x49CBF98` | 取 `[[[0x4FF5DE8]]]` 的 slot0 |
| CommitCsBuffer | `0x460A3E4 -> vtable+0x10 (0x49CBFFC)` | 先虚调用再检查 pending |
| ResetCsBuffer | `0x460A40C -> 0x49CC18C` | 清游标/pending |
| slot0 发布者 | `0x43D301C` | 从 `owner+0xA8` 的真实 context 读 `ctx+0x80/0x88/0x4F0/0x578` |
| CS 消费者 | `0x46B80E8 -> 0x49CBC0C -> 0x46B8070` | 读 `[0x544CC40]` 与 slot0 |

要点：

- `0x52C3250` 是 BSS 指针表；除 binder `0x43D301C` 外，没有找到任何 allocator
  或 pool 构造函数写 slot0–slot7。
- 宿主按 `docs/cs_fifo_context.md` §6.2 安装真实 slot0 后，Push/Commit/Reset
  和 ring read 都能工作；但 `0x46B80E8` 需要 `[0x544CC40]` 非零（BSS 零），
  且 parser 需要真实 context/pack 数据。**FIFO 写入 ≠ GameCore 消费**。

### 3.4 context 持有者 `0x52717B0`：能绑，不能造

`0x52717B0` 的地址本身没有代码直接引用；所有访问都经过
`[[0x51EA4D0]]`（即 `[0x52717B0]`）。定位到的写入点只有内部 pool 函数：

| 函数 | 行为 | 关键指令 |
|---|---|---|
| `0x409F178` | 取/建 pool[index]，临时安装到 holder，再清空 | `0x409F1B4 ldr x8,[0x51EA4D0]`；`0x409F1B8 str x20,[x8]`；`0x409F1CC str xzr,[x8]`；`0x409F208 str x0,[pool+0x28][index]` |
| `0x409F250` | 按索引取 pool 条目并安装到 holder，调用后清空 | `0x409F280 str x20,[x8]`；`0x409F2B4 str xzr,[x8]` |
| `0x409F2C8` | 选择 pool 条目并安装到 holder | `0x409F2FC ldr x9,[0x51EA4D0]`；`0x409F300 str x8,[x9]` |
| `0x409F0B8` | 清 pool / holder | `0x409F0E8 ldr x8,[0x51EA4D0]`；`0x409F0EC str xzr,[x8]` |

这些函数都是 **pool 语义**，不是 context 创建：

- `0x409F178` 在 pool[index] 为空时调用 `0x409EBE4` 取一个条目；该条目随后
  存入 pool 数组。`0x409EBE4` 是 pool 条目分配器，内部：
  - `0x409EC04 ldr x8,[0x51D10BD0]`，`0x409EC08 blr x8`；
  - `0x409EC98 ldr x8,[0x51D10B30]`，`0x409ECA8 blr x8`。
  两个槽在静态文件中都是 **0**，且没有找到 GameCore 代码写它们；干净宿主直接
  调用会在 `0x409EC08` 跳空。
- context 构造函数 `0x40A0CA0` 的 RELA 槽只有 `0x51D1E58`；找到的代码引用只有
  `0x409FB90` 一处（在 `0x409F6FC` 函数内），而该处的 `x0` 来自
  `[[0x51EA4D0]]`（当前活动 context）。也就是说：**构造函数被用于“已有 context
  的初始化”，不是“创建并安装 context”**。
- 没有找到任何直接写 `[0x52717B0]` 的导出/引导函数，也没有找到 context 大小的
  分配点（容量 `0x1E00000` 来自对象头部，不是 ctor 常量）。

结论：宿主可以**绑定**一个真实 context（如果已有），但不能用 native 路径
**创建**一个；手搓 context 会踩 `ctx+0x80/0x88/0x4F0/0x578`、`+0x78` 代码指针、
`+0x08/+0x0C` 引用计数等，`docs/cs_fifo_context.md` §7 的拒绝清单仍成立。

### 3.5 CoreThread 状态 `0x544CBD0`：内部创建，缺线程工厂

| 项 | 地址/偏移 | 证据 |
|---|---|---|
| 控制块 | `0x544CB58..0x544CBD4` | `+0xB58` delta、`+0xB78` mutex、`+0xB78+0x28` cond、`+0xBD0` 状态、`+0xBD4` 通知字 |
| 创建 | `0x46B7784` | 初始化 mutex/cond、`[0x5091548]=0x25CD8F8`、构造 `"CoreThread"` 字符串（`0x11DDC47`）、栈 `0x40000` |
| 线程工厂槽 | `0x50B40F48` | 创建函数 `0x46B7804/0x46B781C` 读它并 `blr`；静态值 **0** |
| 停止 | `0x46B7848` | 取 `0x544CB70` 线程句柄，虚调用 `+0x10/+0x28` |
| 帧生产者 | `0x46B7888` | 写 `+0xB58`，读 `+0xBD0`，通知两组 cond，置 `+0xBD0=2` |
| 状态写入 | `0x46B7904` / `0x46B7B98` / `0x46B7BF0` | `str w8,[x19,#0x58]`，`x19=0x544CB78` → `0x544CBD0` |
| 主循环 | `0x4882C10` | 读 `+0xBD0`；2=跑一帧，3=退出 |
| 唯一发布槽 | `0x522EF88/90/98` | 创建/停止/生产者的 RELA 槽；无导出 |

创建函数 `0x46B7784` 的调用链不是导出：`0x522EF88` 只在 `0x46BC1BC` 被读，
该包装 `0x46BC190` 发布在槽 `0x522F3D0`，再由 `0x46D683C` 等内部函数调用。
静态前置条件：

- `0x50B40F48`（运行期线程工厂）必须非零；干净宿主没有；
- `0x5091548` 已有真实实现 `0x25CD8F8`，但它只做 `+0xBD4` 通知初始化；
- 线程 callable 由 `operator new(0x10)` + 字符串构造，依赖 C++ 运行时与
  `std::string` 全局；
- 即使创建成功，5v5 也不使用 CoreThread（5.23.1a），所以它不是 5v5 帧驱动入口。

### 3.6 证据总表

| 目标 | 真实入口/实现 | 调用者/被调用 | 前置条件 | 宿主可调用 | 置信度 |
|---|---|---|---:|---|---|
| `ModuleInit` | 导出桩 `0x46AD0E0` → 实现 `0x46AD0CC` → `0x40A0360` | 约 40 个子系统 init | BSS 块 `0x542F4B0`、一次性标志 `+0x48` | **是**（已验证 H0） | 高 |
| CS slot0 ring | ctor `0x49CBD88`，init `0x49CBEEC` | Push/Commit/Reset | `0x52C3250` 可写；对象保活 | **是**（FIFO 语义） | 高 |
| CS slot0 发布 | binder `0x43D301C` | 从真实 `owner+0xA8` context 读 `+0x80/+0x88/+0x4F0/+0x578` | 真实引用计数 owner/context | **否**（需要真实 context） | 高 |
| context 持有者 `0x52717B0` | pool 安装 `0x409F178` / `0x409F250` / `0x409F2C8`；清理 `0x409F0B8` | 内部方法表 `0x51D1C20/30/40/00` | pool 对象、真实 context 条目、运行期回调 | **否**（无导出；工厂回调为 0） | 高（无导出）/ 中（具体 allocator） |
| context ctor `0x40A0CA0` | 方法表 `0x51D1E58` 唯一代码引用 `0x409FB90` | 对 `[[0x51EA4D0]]` 的已有 context 做初始化 | 已有 context | **否**（不创建、不安装） | 中-高 |
| CoreThread 创建 `0x46B7784` | 槽 `0x522EF88` | 包装 `0x46BC190`（槽 `0x522F3D0`） | 线程工厂 `0x50B40F48` 非零、pthread、C++ 字符串/callable | **否**（无导出；工厂为 0） | 高（无导出）/ 中（运行前置） |
| CoreThread 状态 `0x544CBD0` | `0x46B7888` / `0x46B7Bxx` / `0x4882C10` | 帧生产者/主循环 | 控制块初始化、线程句柄 `0x544CB70` | **否**（内部状态） | 高 |
| CS 消费者 `0x46B80E8` | `-> 0x49CBC0C -> 0x46B8070` | slot0 + `[0x544CC40]` | `[0x544CC40]` 非零、真实 context/pack | **否**（BSS 零、无导出） | 高 |
| C# `SGW::GameCoreInit` | 本地标签 `0x55A7968` 不是起点；函数 `0x55A77E8..0x55A79DC` | 托管 helper/槽 | il2cpp/Unity 运行时 | **否** | 中（边界）/ 低（名称） |
| C# `SGW::StartLevel` | 本地标签 `0x55A956C` 不是起点；候选 `0x55A9588` | 托管 helper/槽 | il2cpp/Unity 运行时 | **否** | 低-中 |
| C# `SGW::PureReplayStart` | 本地标签 `0x55A9EE4` 不是起点；候选 `0x55A9D74` | 托管 helper/槽 | il2cpp/Unity 运行时 | **否** | 低-中 |
| C# `SGamePInvoke::Init` | 标签 `0x55A4020` = 真实序言 | 托管 helper `0x3B0417C`、槽 `0xD4C7028` | il2cpp/Unity 运行时 | **否** | 中 |
| C# `SetGameCorePipe` | 标签 `0x55A41EC` = 真实序言 | 托管 helper、槽 `0xD4C7050` | il2cpp/Unity 运行时 | **否** | 中 |
| C# `SetAllKeyDatabin` | 标签 `0x55CF0A0` = 真实序言 | 槽 `0xD4D0DD0`、`0xD5BC0E20/E38` | il2cpp 运行时；部分槽静态为 0 | **否** | 中 |
| C# `BattleLogic::DoBattleStart` | 标签 `0x694C6A8` = 真实序言 | 静态标志 `0xE295B50`、多个托管槽 | il2cpp/Unity 运行时 | **否** | 中 |

---

## 4. 支持的最小宿主序列

以下序列只使用已验证的 native 路径；**不包含任何伪造 context/vtable**。

| 步骤 | 操作 | 结果/状态 |
|---:|---|---|
| 1 | preload `libpandora/libpixuiCurl/libPixUI_Unity/libpuerts`，`dlopen libGameCore.so` | H0 已验证 |
| 2 | `dlsym("ModuleInit")`，调用；校验 `[0x542F4B0+0x48]==1` | H0 已验证 |
| 3 | `QTSRegisterSystem` + databin 表对象注册，`DT_*` 查询 | H1/H2 已验证（825 表） |
| 4 | ctor `0x49CBD88` + init `0x49CBEEC` 造真实 slot0；`*(void**)(base+0x52C3250)=obj` | **可执行**；Push/Commit/Reset 可跑 |
| 5 | `PushCsBuffer` 写入 + `CommitCsBuffer` | **可执行**；只是写入 ring，GameCore 不消费 |
| 6 | 安装 context：binder `0x43D301C` 或 pool 安装 `0x409F178` | **阻塞**：没有真实 owner/context；pool 工厂回调 `0x51D10BD0/0x51D10B30` 为 0 |
| 7 | CS 消费/帧 tick：`0x46B80E8`、`0x46B7888` 或 `0x4882C10` | **阻塞**：依赖 `[0x544CC40]`、真实 context、线程工厂 |
| 8 | `.abc` 初始化头 → CS 命令流 | 数据已可解析（53 KV/10 玩家/443B 标量）；但没有步骤 6/7 不会推进 |
| 9 | 逐帧状态输出 | **不可达** |

**第一个缺失步骤（明确标记）**：

> 步骤 6：真实 context 对象及其 pool/owner。  
> 现有 native 代码只能“发布/激活已有 context”（binder 或 pool 安装），不能创建它；
> 唯一找到的 pool 条目工厂 `0x409EBE4` 在干净宿主中会因
> `0x51D10BD0` / `0x51D10B30` 为 0 而在 `0x409EC08` 跳空。  
> 因此 H4 的“宿主构造 context”仍未完成，H5（CS 初始化命令流）不能开始。

---

## 5. 置信度与未决

已证实（高）：

- 本地 metadata 416,645 / 设备 416,815，构建不同；
- `method_addr_names.json` 的部分标签不是函数起点（至少 4 例）；
- GameCore 无 context/线程/槽表创建导出；`ModuleInit` 引导链不写这三个目标；
- `0x52717B0`、`0x52C3250`、`0x544CBD0` 静态均为 0；
- slot0 真实 ring 可由 ctor/init 安装；binder 只发布真实 context 的槽；
- CoreThread 创建依赖 `0x50B40F48`（静态 0）；5v5 不走 CoreThread。

未决（中/低）：

- context pool 单例对象在哪里构造、由谁构造；
- `0x409EBE4` 的 pool 条目大小/语义（`[0x51D10BD0]` 回调返回什么）；
- 谁在真实进程里填写 `0x51D10BD0` / `0x51D10B30` / `0x50B40F48`；
- `ctx+0x68` 是否是 slot 池 owner；slot2/3/6/7 的分配者；
- 本地 libil2cpp 的精确构建号；`SGW::StartLevel/PureReplayStart` 的真实本地入口
  仍需匹配构建的 live MethodInfo 才能定名。

不再做：

- 不伪造 vtable/context/引用计数；
- 不把 `0x52717B0` 当作可直接 `calloc` 的 context；
- 不把 `0x52C3250` 替换成宿主数组（会绕过 binder 和消费者）；
- 不把 C# 标签地址当 native 入口调用。

## 9. 2026-11-03 实机修正

BSS 偏移以 `adrp #0x544C000` 为页基址：

```text
CoreThread state = 0x544C000 + 0xBD0 = 0x544CBD0
CS consumer      = 0x544C000 + 0xC40 = 0x544CC40
```

旧文中的 `0x544C0BD0/0x544C0C40` 是把页地址和页内偏移拼错；`0x5440BD0/
0x5440C40` 也不是同一字段。live 进程 `[0x544CC40]=0x75dc98daac10`、
`[0x544CBD0]=0x400000000002`。A1 宿主补抓 consumer region 后调用 `0x46B80E8`
已返回不崩；但 slot0 pending=0，尚未消费有效帧命令。
