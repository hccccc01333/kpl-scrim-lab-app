# GameCore 回放模拟方案（静态可行性分析）

- 日期：2026-10-30
- 范围：只做静态文件/已有 device 产物分析；不启动或连接游戏进程，不登录，不注入/attach，不修改游戏文件。
- 依据：`docs/replay_binary_format.md` 5.15–5.36、`docs/evidence_audit.md`、`.workbuddy/memory/MEMORY.md`、`data/replays/_analysis/_host/{gc_boot,gc_cs,gc_tables}.c`、`libGameCore.so` 的 ELF/RELA/dynsym（pyelftools + capstone）。
- 本文配套只读脚本：`tools/gc_export_map.py`。`python tools/gc_export_map.py --check` 当前输出 `CHECK OK`。
- **执行状态（2026-10-30，审计后）**：E1/E1b 已通过——宿主 `ModuleInit` 后注册假表对象，
  `DT_Count/GetByIndex` 读通表 83，并进一步注册全部 825 张表、
  205,149 行抽样校验 0 不一致（见 `docs/replay_binary_format.md` 5.30/5.31）。
  S3 初始化命令流仍未解；S3b 仅 Push 通过、Commit 崩；0x43D301C 已确认不是上下文安装器。
  **MVSS-B 建议暂停**，先按 `docs/evidence_audit.md` 的 G1–G5 门槛判断是否继续。

---

## 0. 结论摘要

1. **宿主化本身可行，且比“自己写模拟器”更接近真实数据**。libGameCore 无 il2cpp/GL 依赖、无代码加密，`ModuleInit` 可在自建 ARM64 宿主跑完（5.15.1/5.15.6，已由 `gc_boot --init` 验证）。
2. **但 `ModuleInit` 只是 native 子系统初始化，不等于“开一局”**。C# 侧还有 `SGW.GameCoreInit / SGamePInvoke.Init / SetGameCorePipe`（managed），以及战斗上下文、CoreThread、8 路缓冲池的创建；这些都不是 `ModuleInit` 的产物。宿主若只调 `ModuleInit` 就 `PushCsBuffer`，会在 FIFO 对象为空处崩溃（5.18；本次静态链复核见 §2.3）。
3. **databin 是当前最接近可交付的一环，但没有“导出级注入 API”**。`GameDataWrapper_*`/`DT_*` 都是**查询**接口；`SGameSetEnableDatabinCrcFromFile` 只写一个字节开关；真正的装载器是内部函数（`DatabinTableBase::LoadLocalData` 0x2a36308、候选顶层 loader 0x3cd9480），或走 `libQtskDB` 的 `DB_OpenTable` + `STDBTableEnv`。注意 loader **不负责建表对象**：它从 `0x5274280` 的源数组复制对象指针到 `0x52742a0` 注册表，再按表加载行；因此表对象仍需先由 C# 或宿主构造。宿主可行的两条路是：**自建表对象 + 0x52742a0 注册表**（先证契约），或**构造源表对象 + 原生 loader + dc.db**（要 QtskDB 环境）。
4. **初始化头（KV + 443B 标量 + 玩家块）是“数据”，不是可直接推给 CS FIFO 的“命令流”**。从 `.abc` 头到 `CLevelContext/deskPool` 的字段映射，以及 CSProtocol/TDR 的命令封装，仍是最大缺口（5.16.6 的 a/b/c）。没有这一步，FIFO 里没有可消费的开局命令，后面逐帧 Push 也无从谈起。
5. **帧驱动的正确组合是：`PushCsBuffer`/`CommitCsBuffer`（输入） + 0x46B7888（每帧生产者，最终调 `ctx+0x280`）**。`CommitCsBuffer` 本身不推进帧；`PushViewBuffer/CommitViewBuffer` 是 **GameCore→宿主** 的状态输出，不是帧驱动（5.22/5.23；本次静态复核 §4.3）。
6. **`DoBattleStart` 不是 native 导出，`SFNtfRunningGameCoreThreadID` 不是必需，`SGC_*` 不可用**：`DoBattleStart` 是 `SGamePInvoke` 的 managed 方法（metadata 166485），`SGC_GetPlayer*` 是 `mov w0,#11; ret` 桩，`SGC_Init/CreateGame/RunFrame` 根本不存在；`SFNtfRunningGameCoreThreadID` 只写 `0x542a8a8`，离线 5V5 实测为 0（5.23.3）。
7. **最小可行模拟应拆成两级**：
   - **MVSS-A（近期可做）**：宿主 + `ModuleInit` + 自建 databin 注册表 + `DT_*` 查询一张表（如 83 `svr2GamecoreCfg`，53 行×4 B）。不碰战斗、不碰帧。
   - **MVSS-B（真正的“模拟”）**：上下文/线程 + databin 全量 + 初始化命令流 + 逐帧 Push/Commit + tick + 读状态。其门槛不在 databin，而在 **S3 初始化命令流**；在 S3 未解前，不应承诺“跑完一局”。
8. **本地当前没有 NDK**（`ANDROID_NDK_HOME` 为空，未发现 `C:/Android` / `$LOCALAPPDATA/Android/Sdk/ndk`）。E0 静态实验不需要 NDK；第一个宿主二进制实验 E1 需要重装 NDK（r28b，见 §5.4）。

---

## 1. 目标架构与数据流

```
自建 ARM64 宿主进程（MuMu 内 root；不是游戏进程）
├─ dlopen: libpandora / libpuerts / libPixUI_Unity / libpixuiCurl
│           + libGameCore.so（可选 libQtskDB / libQtsVFS）
├─ ModuleInit()                                   ← native 子系统初始化（已验证）
├─ 战斗上下文/线程初始化（C# GameCoreInit/StartLevel 的 native 等价物）  ← 最大缺口
├─ databin 注册（825 张表块 → 0x52742a0 数组，或原生 loader + dc.db）
├─ 初始化头 → CS 命令流（KV + 443B + 玩家块 → CLevelContext/deskPool/TDR）
├─ 逐帧:
│    PushCsBuffer(len) → 写入 TDR 命令 → CommitCsBuffer()
│    0x46B7888(delta)（或 ctx+0x280）→ GameCore 走一帧
└─ 读状态:
     PushViewBuffer/CommitViewBuffer（需要 view context）
     或 DT_*（需要 0x52742a0 表注册表）
```

数据流的两条 FIFO 必须区分：

| 方向 | API | 底层对象 | 作用 |
|---|---|---|---|
| 宿主→GameCore（输入） | `PushCsBuffer(size)` / `CommitCsBuffer()` / `ResetCsBuffer()` | `0x4ff5de8 → 0x52488b8 → 0x52c3250` | CS 帧命令（原始位流，不加密） |
| GameCore→宿主（输出） | `PushViewBuffer(size)` / `CommitViewBuffer()` / `ResetViewBuffer()` | `0x4ff4520` 链 + `+0x2b0` | 每帧世界状态/视口数据 |
| 帧推进 | 0x46B7888(delta) → `ctx+0x280` | `0x4ff4520` 链 + `+0x280` | 跑一帧逻辑；CoreThread 可选 |

---

## 2. 本次静态复核（可直接复现）

### 2.1 导出桩 → 槽位 → 实现

`libGameCore.so` 的 C 导出都是 12–28 B 跳转桩：`adrp x8, page; ldr x8,[x8,#off]; br/blr x8`；槽位在 `.data`/`.data.rel.ro`，由 `RELA R_AARCH64_RELATIVE` 在加载时物化（5.15.3）。本次用 RELA 重建的表（节选，完整表见 `tools/gc_export_map.py`）：

| 导出 | 桩地址 | 槽位 | 实现 | 说明 |
|---|---:|---:|---:|---|
| `ModuleInit` | 0x46ad0e0 | 0x522e960 | 0x46ad0cc | 置 `x0=0x542f4b0`，尾调 0x40a0360 |
| `PushCsBuffer` | 0x460a3cc | 0x522a728 | 0x460a3ac | 取 `[[[base+0x4ff5de8]]]` 后尾调 0x49cbf98 |
| `CommitCsBuffer` | 0x460a400 | 0x522a730 | 0x460a3e4 | 取 `[base+0x52488b8]` 对象，虚表 +0x10 |
| `ResetCsBuffer` | 0x460a428 | 0x522a738 | 0x460a40c | 尾调 0x525a7b8 |
| `PushViewBuffer` | 0x46b7fd8 | 0x522f050 | 0x46b7f9c | `[[[base+0x4ff4520]]]+0x2b0` 后尾调 0x525a798 |
| `CommitViewBuffer` | 0x46b8024 | 0x522f058 | 0x46b7ff0 | 同上，虚表 +0x10 |
| `SGC_GetPlayerSettleData` | 0x46ad104 | 0x522e978 | 0x46ad0fc | `mov w0,#11; ret`（桩） |
| `SGC_GetPlayerReportQuitACNTData` | 0x46ad124 | 0x522e980 | 0x46ad11c | 同上 |
| `SGC_GetPlayerTLogData` | 0x46ad144 | 0x522e988 | 0x46ad13c | 同上 |
| `SGC_GetPlayerMapExInfo` | 0x46ad164 | 0x522e990 | 0x46ad15c | 同上 |
| `SGameSetEnableDatabinCrcFromFile` | 0x4606ad4 | 0x522a418 | 0x4606ac8 → 0x522a3d8 → 0x46064b4 | `strb w0,[base+0x542a804]` |
| `GameDataWrapper_GetTable` | 0x460709c | 0x522a470 | 0x4606f04 | 名字表查询；管理器 `[0x4ff57b0]` |
| `DT_Count` | 0x4606dc0 | 0x522a438 | 0x4606da0 | `*(0x5118810)→0x52742a0→array→table[index]`，虚表 +0x18 |
| `DT_GetByIndex` | 0x4606df8 | 0x522a440 | 0x4606dd8 | 同上，虚表 +0x20 |
| `DT_FindByKey` | 0x4606d88 | 0x522a430 | 0x4606d64 | 同上，虚表 +0x10 |
| `SFNtfRunningGameCoreThreadID` | 0x460a4cc | 0x522a758 | 0x460a4c0 | `str x0,[base+0x542a8a8]; ret` |
| `QTSRegisterSystem` | 0x45f3874 | 0x52296c8 | 0x45f3760 | 注册 sysName + path；不读文件 |
| `QTSOpenFile` | 0x45f3534 | 0x5229690 | 0x45f3490 | 经 QtsFileSystem::Open；失败回退 fopen |

要点：`SGC_*` 只有 4 个 `SGC_GetPlayer*` 且全是桩；`SGC_Init/SGC_CreateGame/SGC_RunFrame` **不存在**，`gc_boot.c` 里 `dlsym` 这三个名字只会得到 NULL。

### 2.2 关键全局链（静态初值，RELA 物化后）

| 槽位 | 静态值 | 含义 |
|---|---:|---|
| 0x542f4b0 | BSS | `ModuleInit` 的上下文块；`+0x48` 是“只初始化一次”标志（BSS 初值 0） |
| 0x4ff4520 | 0x51ea4d0 | 主 context 入口槽 |
| 0x51ea4d0 | 0x52717b0 | context 持有者槽 |
| 0x52717b0 | 0（BSS） | context 持有者对象；首字段指向真实 context，`+0x280`/`+0x2b0` 在真实 context 上 |
| 0x4ff5de8 | 0x52488b8 | CS FIFO 第一跳 |
| 0x52488b8 | 0x52c3250 | CS FIFO 第二跳：指向 8 路对象指针数组的基址 |
| 0x52c3250 | 0（BSS） | CS FIFO 8 路对象指针数组基址（每个 qword 在上下文安装后填对象；Push/Commit 取 array[0]） |
| 0x52742a0 | 0（BSS） | databin 表对象指针数组槽；`mem_databin.c` 的 `arrAddr`；`DT_*` 的目标注册表 |
| 0x5274280 | 0（BSS） | 原生 loader 的**源**表对象数组指针槽；loader 从 `0x5118818` 取它 |
| 0x5118810 | 0x52742a0 | `DT_*` 的注册表入口（取 `*(0x5118810)` 即 `0x52742a0`） |
| 0x5118818 | 0x5274280 | 原生 loader 的源数组入口（取 `*(0x5118818)` 即 `0x5274280`） |
| 0x4ff57b0 | 0x51187e8 | `GameDataWrapper_GetTable` 名字表入口；`0x51187e8 → 0x52c31b8`（BSS 数组，16 B/项） |
| 0x542a7b0 | 0（BSS） | 原生 databin DB 句柄（`DatabinManager` 运行时写） |
| 0x542a7f8 | 0（BSS） | databin 每表 CRC 数组指针 |
| 0x542a800 | 0（BSS） | CRC 数组长度 |
| 0x542a804 | 0（BSS） | `SGameSetEnableDatabinCrcFromFile` 的 1 字节开关 |
| 0x542a8a8 | 0（BSS） | `SFNtfRunningGameCoreThreadID` 写入的线程 ID |
| 0x544d3a8 | 0（BSS） | databin 表数量；原生 loader 读取 |
| 0x544c0b58 / +0xbd0 | 0（BSS） | CoreThread 帧 delta / 状态机（0 空闲、2 跑一帧、3 退出） |

**关键推断**：`PushCsBuffer` 的静态链 `0x4ff5de8 → 0x52488b8 → 0x52c3250` 是通的，但 `0x52c3250` 是 BSS 零；`ModuleInit` 后没有安装战斗上下文。**0x43D301C 已确认不是上下文安装器**（5.35 反汇编显示是引用计数/弱引用赋值助手，读写 +0x48/+0x50/+0xa8/+0xb0）；不要再按“调它就能装 FIFO”的假设做实验。这解释了 5.18 的 `ModuleInit` 后 `PushCsBuffer(64)` 崩溃：不是 FIFO 链不存在，而是**战斗上下文尚未由未知路径创建**。

### 2.3 初始化/帧函数的内部地址

| 地址 | 作用 | 证据 |
|---:|---|---|
| 0x40a0360 | `ModuleInit` 的一次性链：读 `ctx+0x48`，置 1，顺序调用约 30 个子系统 init（全部经指针表，x0=ctx） | 5.15.6 + 本次反汇编 |
| 0x43d301c | **不是**上下文安装器；5.35 反汇编为引用计数/弱引用赋值助手（+0x48/+0x50/+0xa8/+0xb0） | 5.35；旧“frame-sync 安装器”说法已推翻 |
| 0x46b7784 / 0x46b7848 | CoreThread 创建 / 停止（栈 0x40000） | 5.23.1 |
| 0x46b7888 | 每帧生产者：写 delta(+0xb58)，按状态 notify，最后取 `[[[0x4ff4520]]]+0x280` 并调 `[0x519ae18]` | 5.23.1 + 本次反汇编 |
| 0x4882c10 | CoreThread 主循环：状态 2 跑一帧，状态 3 退出 | 5.23.1 |
| 0x49cbf98 | `PushCsBuffer` 的最终实现：确保容量、写 `pending_len(+0x24)`、返回 `+0x18` 缓冲指针 | 本次反汇编 |
| 0x3cd9480 | **候选**原生 databin DB loader：读表数量 `0x544d3a8`、打开 DB、把句柄写 `0x542a7b0`、路径指针来自 `0x542a790` | 本次反汇编；需运行验证 |
| 0x2a36308 | `DatabinTableBase::LoadLocalData`：读 `0x542a7b0`/`0x542a7f8`/`0x542a800`/`0x542a804`，按表索引取行 | 本次反汇编；字符串 0x11cd756 |
| 0x4606f04 | `GameDataWrapper_GetTable` 实现：`[0x4ff57b0]` 名字表查询，返回 handle | 本次反汇编 |
| 0x4606da0 | `DT_Count` 实现：`*(0x5118810) → 0x52742a0 → array[index] → vtable+0x18` | 本次反汇编 |
| 0x46b7f9c | `PushViewBuffer` 实现：`[[[0x4ff4520]]]+0x2b0` 取对象后写 | 本次反汇编 |

> 注意：以上内部函数没有 dynsym 导出，只能按“基址 + 文件内偏移”调用。仅对 **5069040 / 12.1.1.8** 构建成立；5230306/5169333 变体偏移不同。

---

## 3. 分阶段方案（每阶段：已验证 / 缺失 / 验收）

### 3.0 最小可行链（MVSS）对照

| 链节 | 目标 | 当前状态 | 依据 |
|---|---|---|---|
| 宿主 → `ModuleInit` | 自建 ARM64 进程内跑通 native 引导 | ✅ 已验证（M1） | 5.15.6；`gc_boot --init` |
| 初始化上下文/线程 | `0x52717b0` context 持有者、`0x52c3250` CS FIFO 数组、CoreThread | ❌ 未解决；无导出级 create；0x43D301C 不是安装器 | 5.35；0x46b7784/0x46b7888；5.23 |
| 载入 databin | 825 张表可供 GameCore 查询 | ⚠️ 半解决：块已导出；查询 API 可用；装载需自建对象/原生 loader | 5.19–5.21；§4.1 |
| 喂 `.abc` 初始化头 | KV + 443B + 玩家块 → `CLevelContext/deskPool` → CS 命令 | ❌ 未解决：字段映射 + TDR 封装 + 命令顺序 | 5.16.4/5.16.8/5.16.6 |
| 逐帧 Push/Commit | `PushCsBuffer`/`CommitCsBuffer` + 0x46B7888 tick | ⚠️ API 语义已确认；上下文未解决 | 5.18/5.22/5.23；§4.3 |
| 读状态 | ViewBuffer 或 `DT_*` | ⚠️ `DT_*` 需注册表；ViewBuffer 需 context；`SGC_*` 是桩 | 5.22；§4.2/§4.3 |

- **MVSS-A** = 上表前 1 行 + 第 3 行（S1 + S2-A）：宿主能启动并让 `DT_*` 读到宿主提供的一张表。**这是近期可交付的最小成果，但还不是回放模拟。**
- **MVSS-B** = 全部链节（S1→S5）：必须跨过“初始化上下文/线程”和“初始化头→CS 命令”两座桥；在 S3 未解前，不应承诺“跑完一局”。

### S0 静态契约（已完成，无需 NDK/设备）

- 产物：`tools/gc_export_map.py`；`--check` 校验导出桩、实现地址、SGC 桩、FIFO/databin 全局链、CRC 开关链、`DT_Count` 取表路径。
- 已验证：上述 §2 全部静态事实。
- 缺失：运行期值（`0x52742a0` 是否真为 0、`0x542f4b0+0x48` 是否置 1）只能由宿主/活进程确认。
- 验收：`python tools/gc_export_map.py --check` → `CHECK OK`。

### S1 宿主 + ModuleInit + 全局探针

- 目标：在 MuMu 内自建 ARM64 进程中 `dlopen` 依赖 + `libGameCore.so`，调 `ModuleInit()`，打印 §2.2 的全局槽。
- 已验证：M1（5.15.6）`gc_boot --init` 可跑完 `ModuleInit`；依赖 `libpandora/libpuerts/libPixUI_Unity/libpixuiCurl` 必须预加载（`gc_boot.c`）。
- 缺失：没有“上下文/线程”创建；`0x4ff4520` 链、`0x52c3250`、`0x52742a0` 预期仍为 0/静态初值。
- 验收：`ModuleInit` 返回；`base+0x542f4b0+0x48 == 1`；`[0x4ff5de8]==0x52488b8`、`[0x52488b8]==0x52c3250`、`[0x52c3250]==0`；`[0x52742a0]==0`；`[0x4ff4520]==0x51ea4d0`、`[[0x4ff4520]]==0x52717b0`、`[[[0x4ff4520]]]==0`。
- 说明：这一步**不能**调 `PushCsBuffer`；5.18 已实测会 SIGSEGV。

### S2 databin 装载（三条路线）

#### S2.0 现有资产

- 825 张表、205,149 行、71,923,748 B，块格式 `stdr` + 0x98 头 + rows×stride；逐块校验通过（5.21）。
- `83_svr2GamecoreCfg.bytes.bin`：`stride=4, rows=53, block=364`，行首 `{u16 confType, u16 value}`；与 `.abc` KV 同构（5.16.7）。
- `dc.db` 本地副本 124,780,544 B（`data/replays/_analysis/device/dc.db`，已被 `data/` 忽略）。
- `tables_blocks.csv` 提供 index/path/rows/stride/columns/block。

#### S2-A 宿主表对象 + `0x52742a0` 注册表（推荐先做）

- 依据：`DT_*` 只依赖 `*(0x5118810)=0x52742a0` 的 1024 项数组；`DT_Count` 调 `vtable+0x18`，`DT_GetByIndex` 调 `+0x20`（本次反汇编）。`mem_databin.c` 已证明活进程就是 `0x52742a0 → arr → obj` 三层。
- 做法：
  1. 宿主把 `83_svr2GamecoreCfg.bytes.bin` 读入内存（`stdr` 块已在磁盘）。
  2. 分配一个宿主表对象，字段模仿活进程 `DatabinTableBase`：`+0x10` 路径、`+0x18` stride、`+0x30` 块头指针、`+0x88` 行目录（可后置）、`+0xA0` rows、`+0xB0` rows。
  3. 分配 `HostVtable[16]`，在 `+0x18` 放 `count(self)`、`+0x20` 放 `get_by_index(self, i)`（返回 `block+0x98+i*stride`）；`+0x10/+0x30/+0x38/+0x40/+0x48` 可先放安全桩。
  4. `reg[83]=&table`；`*(void**)(base+0x52742a0)=reg`。
  5. `DT_Count(83)` 期望 53；`DT_GetByIndex(83,0)` 期望首 4 字节 `01 00 32 00`（confType=1, value=50）。
- 已验证：API 契约（静态）；块格式（5.21）。
- 缺失：`DatabinTableBase` 完整 vtable/字段布局未逐项验证；字符串池未落地（5.21 末），只能先保证数值列；GameCore 内部消费者可能走其他虚表槽。
- 风险：宿主 vtable 与真实类 ABI 不一致会被内部代码打穿；先用 `DT_*` 验证，再逐步接 `GameDataWrapper_*`。
- 验收：`DT_Count(83)=53`、`DT_GetByIndex` 行内容与块逐字节一致。
- 与 S2-B 的关系：S2-B 的 loader 只是把 `0x5274280` 的源表对象复制到 `0x52742a0` 并加载行；S2-A 构造出的表对象可以直接挂到 `0x5274280`，复用为 S2-B 的输入。

#### S2-B 原生 loader + `dc.db`（完整但高风险）

- 依据：0x3cd9480 读表数量 `0x544d3a8`、打开 DB 并写 `0x542a7b0`；0x2a36308 `DatabinTableBase::LoadLocalData` 使用 `0x542a7b0/0x542a7f8/0x542a800/0x542a804`；`dc.db` 是活进程的 databin DB 缓存（5.19）。
- **前置条件（本次静态复核新增）**：loader 不是“从零建表”。它先从 `*(0x5118818) = 0x5274280` 取**源表对象数组**，把对象指针逐个复制到 `*(0x5118810) = 0x52742a0` 的注册表，并写对象 `+0x20 = index`（0x3cd93d8–0x3cd93fc）；随后才对每张表做 `LoadLocalData`。因此 **`dc.db` 只解决行数据，表对象仍需先存在**（C# `DatabinManager` 创建，或宿主按 S2-A 构造）。
- 做法：宿主预加载 `libQtskDB.so`，`ModuleInit` 后设 `*(char**)(base+0x542a790)=dc.db 路径`，设 `*(void**)(base+0x5274280)=源表对象数组`、`*(uint32_t*)(base+0x544d3a8)=表数量`，再调用 `0x3cd9480(0)`（带一个 0x100 B 的 sret 缓冲），最后查 `DT_Count(83)`。
- 静态确认（候选）：loader 的调用链与 QtskDB/表的全局吻合；`dc.db` 与 825 表块来自同一离线 5V5（5.19/5.20）；源/目标数组链见 §2.2。
- 缺失：`0x542a790` 路径的写入者/字符串所有权未定；loader 的入参（是否 bool=srv、是否还需要 `0x542a7a8` env）未验证；QtskDB 的 `STDBTableEnv` 回调未定。
- 风险：loader 可能依赖 `DatabinManager` 的 C# 侧初始化（表数量、CRC 数组、版本），单独调用会在空指针/断言处崩；失败不影响 S2-A。

#### S2-C QtskDB `CSharp_DB_*` 直接读 `dc.db`（只读数据，不喂 GameCore）

- 依据：`libQtskDB.so` 导出 `CSharp_DB_OpenBase/OpenTable/CreateTable`、`CSharp_new_STDBTableEnv`、`CSharp_STDBTableEnv_fn_Hash1/2_set`；`DB_OpenBase` 在宿主返回 1，`DB_OpenTable` 卡在 err=8（5.19；`qts_dbget.c` 传了 env 但未设 Hash 回调）。
- 用途：把 `dc.db` 当只读数据源，补 `.abc` 缺的表/行；不解决“GameCore 内部表对象”问题。
- 缺失：`STDBTableEnv` 的 Hash1/Hash2 函数签名与哈希算法；表名是“路径”还是块头 32 字符哈希（`stdr+0x60`）未定。
- 验收：`CSharp_DB_OpenTable(dc.db, <32字符哈希>, cfg, env)` 返回非空，`DB_GetHeadItem` 能读出 53×4 行。

**推荐顺序**：S2-A → S2-B（可选）→ S2-C（只读补表）。S2-A 能在不碰 QtskDB 的情况下证明“GameCore 的 `DT_*` 能读宿主表”。

### S3 初始化头 → CS 命令流（最大缺口）

#### S3.0 上下文/线程初始化（本阶段的前置）

- `ModuleInit` 只做 native 子系统初始化；主 context 持有者 `0x52717b0` 的首字段、CS FIFO 数组 `0x52c3250`、View FIFO 都还是 0。
- **0x43d301c 不是上下文安装器**：5.35 反汇编显示它是引用计数/弱引用赋值助手，不负责把 CS FIFO 对象挂到 `[0x52488b8]`。因此“调 0x43d301c 安装上下文”的旧路线作废；必须先找真实的 create/install 路径，或拿到非零 context 快照。
- 0x46b7784 创建 CoreThread、0x46b7848 停止；0x46b7888 是每帧生产者。宿主可以**不建 CoreThread**，同步调 0x46b7888；但仍需要 context/FIFO 先存在。
- C# 侧 `SGW.GameCoreInit`（metadata 166656）、`SGamePInvoke.Init`（166503）、`SetGameCorePipe`（166508）、`DoBattleStart`（166485）都是 managed，不是 native 导出；它们是“谁在什么时候创建 context/FIFO”的参考实现，但宿主不能直接调。
- 因此上下文初始化只有两条实际路线：**(a) 找到并调用 native create/install 入口（按偏移，需先定位）**；**(b) 通过 CS 初始化命令让 Core 自己创建（需要 S3.1–S3.3 的命令流）**。两者都不在本次静态分析的可执行范围内。

#### S3.1 已有数据

- `.abc` 5069040 变体：
  - `0x018D`：`u16 count` + count×(`u8 confType, u16 BE value, u8 pad`)；25/25 样本为 53 条（排位），42/46 条随模式；51 个 confType 恒定，仅 94={70,100}、95={8,12} 变化（5.16.4/5.16.7）。
  - KV 后 8 字节 `{u32 0, u32 modeWord}`，再 443 B = 110 个 BE u32 + 3 B 尾 `00 00 0a`；index 67 = 服务器 Unix 时间；模板 `abc_init_scalars_5v5.json`（5.16.8）。
  - `0x041E` 起 10 个玩家块：`<team><team>01<slot>0000<entity:u16BE><u32>000000<nameLen><name>`（5.13.2）。
  - `0xBFE8` 起帧记录流，seq 0x22 起（5.16.5/5.13.3）。
- databin `svr2GamecoreCfg` 53 行×4 B 是 KV 的默认值模板；`.abc` 覆盖 94/95 即可复现该局（5.16.7）。
- 443 B 的字段语义大部分未解（只知 index 1 modeWord、index 67 时间；5.16.8）。

#### S3.2 缺失

1. **CLevelContext 字段映射**：443 B/玩家块 → `CLevelContext`（type 42374，285 字段）与 `deskPool` 的 `CSDT_DESK_SVR2GAMECORE_ITEM/CONFIG` 的逐字段对应（5.16.3/5.16.4；5.16.6 的 a/b/c）。
2. **CSProtocol/TDR 封装**：`CSProtocolWrapper` 的 TDR 结构、GUID hash、命令头/长度/序号；`FRAME_CMD_INFO` 143 条只是 opcode 表（5.13.9/5.16.1）。
3. **开局命令顺序**：`GameBuilder` 生命周期（Initialize→BuildPlayers→AddHero→BuildCSharpPlayerHeroData→NtfCoreSetupClient→NtfCoreStartGame→PreBeginPlay→NtfAllBuildComplete→StartFight→PostBeginPlay）只是 C# 编排骨架（5.16.3）；每条 `Ntf*`/`SetupClient/StartLevel` 在 FIFO 里的字节形态未还原。
4. **托管方法体**：`SGW.StartLevel/PureReplayStart/StartHostReplay/SetAllKeyDatabin` 是 C# 方法（metadata 166669/166676/166994/167067），不是 native 导出；要拿命令顺序，需静态恢复其方法体或从 CS FIFO 采样（后者需要运行时，当前不做）。注意：本构建的方法槽存在“指向共享函数中部/描述符”的异常（例如 `DoBattleStart` 的槽指向 0xd2a0db8，落在 `.data.rel.ro`；`SGW.GameCoreInit` 的 0x55a7968 前还有共享代码），方法边界需先校准，不能直接把 metadata 地址当函数入口。

#### S3.3 可行切入点

- **先做“空局/最小局”而不是完整 5V5**：只构造 `CLevelContext` 的最小字段（地图/模式/人数/随机种子/时间）+ 1 个 host player + 0 个 AI，验证 Core 能否进入 `StartFight`。
- **用 `svr2GamecoreCfg` 的 KV 作为“开关”**：先只推 KV（53×4）和 8 字节前缀，观察 Core 是否创建上下文/线程；如果连这个都无反应，说明还需要玩家/desk 命令。
- **以 `GameBuilder` 顺序为模板**：按 5.16.3 的生命周期逐条补命令，每条命令先用“最小 TDR”试推，靠 Core 的日志/状态机（`ctx+0xbd0`、`0x544c0bd0`）判断是否被接受。
- **状态机探针**：在宿主里轮询 `0x544c0bd0`（0 空闲/2 跑一帧/3 退出）、`0x544c0b58`（delta）、`0x4ff4520` 链是否非 0，作为“初始化到哪一步”的唯一可靠信号（5.23）。

### S4 帧驱动

- 输入：每帧把 `.abc` payload 转成 CS 命令，`PushCsBuffer(len)` 返回缓冲指针，写入后 `CommitCsBuffer()`。CS 是原始位流、不加密（5.18）；`PushCsBuffer` 只保证容量并记录 `pending_len`，不写长度头（本次反汇编 0x49cbf98）。
- 最小命令集建议：先推**空帧/heartbeat**验证 tick；再把 `0x2D`（u16BE 角度）映射到 `PushSetSkillIndicatorDirectionCmd`、`0x2C`（type/id/x/y/seq）映射到 `PushAttackPosCmd`/`PushSetSkillIndicatorPositionCmd`（5.25）；移动类 `0x01/0x02` 的 `compressInfo_Move` 位域仍需解（5.13.9/5.25）。143 条 `FRAME_CMD_INFO` 是 opcode 表，不是线格式。
- 推进：调 `0x46B7888(delta)`（每帧生产者）或直接调 `[[[0x4ff4520]]]+0x280` 的可调用体（经 `[0x519ae18]` invoker）。`CommitCsBuffer` 不推进帧；`PushViewBuffer` 是输出，不是驱动。
- 线程：CoreThread 创建 0x46B7784、停止 0x46B7848；离线 5V5 的帧循环走 UnityMain，CoreThread 空闲（5.23.1a），所以宿主**优先同步 tick**，不要强依赖 CoreThread。`SFNtfRunningGameCoreThreadID` 只在需要指定外部线程时用；离线 5V5 实测为 0（5.23.3）。
- 风险：每帧逻辑可能主要在 TypeScript（puerts）里（5.23.2）；若宿主不加载 GameCoreTS JS 包，`ctx+0x280` 可能只跑 native 部分，状态不完整。JS 包目前在加密 QTS 内，未拿到明文（5.23.4）。
- 已验证：CS FIFO 不加密、`PushCsBuffer` 语义、0x46B7888→ctx+0x280 的 tick 路径（5.18/5.23；本次反汇编）。
- 缺失：context/FIFO（S3.0）、`.abc`→CS 的完整映射、GameCoreTS JS（若逻辑在 TS）。
- 验收：连续 100 帧无崩、帧号/输出缓冲递增；若用 CoreThread，`0x544c0bd0` 出现 2（跑一帧）；同步 tick 则以帧号/缓冲游标为准。

### S5 状态读出

- `SGC_GetPlayerSettleData/ReportQuitACNTData/TLogData/MapExInfo` 全是 `mov w0,#11; ret` 桩（本次反汇编），不可用。
- 首选 `PushViewBuffer/CommitViewBuffer`：5.22 已定位 8 路缓冲对象（`+0x18` 数据、`+0x20 {capacity,pending}`、`+0x2c/+0x30` 累计位游标；20 fps 约 348 位/帧 ≈ 43.5 B/帧）。但需要 view context（`[[[0x4ff4520]]]+0x2b0`）先存在。
- 备选 `DT_*` 直接读表：一旦 0x52742a0 注册表建立，可读任意表的行（数值列）；适合经济/属性/配置核对，不是逐帧世界状态。
- `.abc` metadata 已有 KDA/胜负（5.13.11），可作为模拟结果的 sanity check，但不能替代逐帧状态；经济不在回放里（5.13.12/5.14）。
- 已验证：`SGC_*` 是桩、ViewBuffer 对象结构、`DT_*` 注册表路径（5.22；本次反汇编）。
- 缺失：view context/FIFO、缓冲位流→玩家状态的切分、表字符串池。
- 验收：能在首帧读出 ≥1 个玩家的一个数值状态（如位置/血量/金币），并与已知数据做数量级核对。

---

## 4. 三个关键判定的直接回答

### 4.1 宿主内 databin 注入有没有可用导出 API？

**没有“装载型”导出。** 逐个核对：

- `GameDataWrapper_GetTable(out, name)`（0x4606f04）：先从 `[0x4ff57b0]`（入口 0x51187e8 → BSS 数组 0x52c31b8，16 B/项）做名字查找，再返回 handle；数组需要 C# `DatabinManager` 填表项。**只查不装**。
- `GameDataWrapper_FindByKey/FindDataByKey/GetAllKeys/GetField/GetInt/...`：都是对 handle/表的查询/字段读，不接文件。
- `DT_FindByKey/Count/GetByIndex/FindRange/FixData/IsLazyLoad/Unload/ReloadLocalData`：按 **table index** 虚分派到 `0x52742a0` 数组里的表对象；没有“从文件/内存块装载”的参数。
- `SGameSetEnableDatabinCrcFromFile(enable)`：0x46064b4 只做 `strb w0,[0x542a804]`，是 CRC 校验开关，不是 loader。
- `CSharp_DB_*`：在 `libQtskDB.so`，是 SWIG 包装的 DB 打开/游标 API；可以读 `dc.db`，但**不会把表注册进 GameCore**，且 `DB_OpenTable` 需要 `STDBTableEnv` 的 Hash1/Hash2。当前宿主 `OpenBase` 成功、`OpenTable` err=8（5.19）。
- 真正的 loader 是内部函数：`DatabinTableBase::LoadLocalData` 0x2a36308（读 `0x542a7b0` 句柄与 CRC 数组）与候选顶层 0x3cd9480（打开 DB、写 `0x542a7b0`）。它们不是 dynsym 导出，只能按偏移调用；且 0x3cd9480 先把 `0x5274280` 的源表对象复制进 `0x52742a0` 注册表，**不会从零创建表对象**。

**结论**：两条可行路线——
1. **自建表对象 + 0x52742a0 注册表**（先做；`DT_*` 立即可用）；
2. **复用原生 loader + `dc.db`**（完整但依赖 QtskDB/路径/全局状态）。
“直接调 `GameDataWrapper_*` 让它自己加载”不可行。

### 4.2 初始化是否必须调用 `DoBattleStart` / `SFNtfRunningGameCoreThreadID` / `SGC_*`？

- **`DoBattleStart`：不是 native 导出，宿主无法直接调用。** dynsym 里没有 `DoBattleStart`；它是 `SGamePInvoke` 的 managed 方法（metadata index 166485，type 31266，0 参数）。`SGamePInvoke` 32 个方法全是 FIFO/缓冲/内存/管线操作，另有 `fullCorePipe/liteCorePipe/microPipe/DLLName/inited_` 字段，说明 C# 通过 `Init`/`SetGameCorePipe` 接 native 管线；`DoBattleStart` 的效果应通过**同一套 CS 命令/管道**复现，而不是在宿主里找一个同名 C 函数。
- **`SFNtfRunningGameCoreThreadID`：不是必需。** 实现 0x460a4c0 只写 `0x542a8a8`；离线 5V5 实测该值为 0（5.23.3），说明该模式不要求外部指定逻辑线程。宿主同步 tick 时不需要它。
- **`SGC_*`：不可用，也不是初始化必需。** 4 个 `SGC_GetPlayer*` 都是返回 11 的桩；`SGC_Init/SGC_CreateGame/SGC_RunFrame` 不存在。状态读出必须走 ViewBuffer 或 `DT_*`。

### 4.3 帧驱动是 `PushCsBuffer` 还是 `PushViewBuffer/ctx+0x280`？

- **输入 → `PushCsBuffer` + `CommitCsBuffer`**。5.18 已证 CS FIFO 不加密；本次反汇编 0x49cbf98 确认 `PushCsBuffer` 只保证容量、写 `pending_len`、返回写指针，`CommitCsBuffer` 才把 pending 提交到对象（0x460a3e4 走 `[0x52488b8]` 对象虚表 +0x10）。
- **推进 → 0x46B7888（最终 `ctx+0x280`）**。0x46b7888 写 delta、按 `0x544c0bd0` 状态 notify，然后无条件取 `[[[0x4ff4520]]]+0x280` 调 `[0x519ae18]`。`CommitCsBuffer` 不推进帧。
- **`PushViewBuffer/CommitViewBuffer` 是输出**，不是帧驱动；它取 `[[[0x4ff4520]]]+0x2b0` 的对象，写的是 GameCore→宿主的视图缓冲。
- 如果宿主想完全同步、不建 CoreThread：直接每帧 `PushCsBuffer/CommitCsBuffer` 后调 `0x46B7888(delta)`；状态机保持 0 时它会走一次初始化调用再 tick（0x46b7938→0x46b7960），不会等线程。

---

## 5. 第一个可执行实验与 NDK

### 5.1 E0：静态契约实验（已可执行，不需要 NDK/设备）

```bash
python tools/gc_export_map.py --check
# 期望：CHECK OK
python tools/gc_export_map.py --globals
python tools/gc_export_map.py --symbol PushCsBuffer --symbol DT_Count
```

验收：导出/槽位/实现、SGC 桩、FIFO 链、databin 注册表链、CRC 开关链、`DT_Count` 取表路径全部一致。该实验**不加载库、不跑 GameCore**，只读 ELF。

### 5.2 E1：宿主 + ModuleInit + 一张 databin 表（第一个“碰 GameCore”的实验）

> 本任务不编译/不推送/不运行；以下为下一步执行单。

1. 准备设备目录 `/data/local/tmp/gc/sim/`，推入：
   - `libpandora.so`、`libpuerts.so`、`libPixUI_Unity.so`、`libpixuiCurl.so`、`libGameCore.so`；
   - `libQtskDB.so`（S2-B 用）、`dc.db`（S2-B 用）；
   - `83_svr2GamecoreCfg.bytes.bin`（S2-A 用；设备 `dtab_blocks/` 已有）。
2. 新写 `gc_sim0.c`（只读探针，不改 `gc_boot.c/gc_cs.c/gc_tables.c`）：
   - dlopen 依赖 + libGameCore；`ModuleInit()`；
   - `base = (char*)dlsym(h,"ModuleInit") - 0x46ad0e0`；
   - dump §2.2 全局；
   - `SGameSetEnableDatabinCrcFromFile(0)`，确认 `base+0x542a804==0`；
   - 读 block 83，分配 host 表对象 + vtable（`+0x18` count、`+0x20` get_by_index），`reg[83]=obj`，`*(void**)(base+0x52742a0)=reg`；
   - 调 `DT_Count(83)` 与 `DT_GetByIndex(83,0..52)`，与 block 逐字节比；
   - 打印 `[0x52c3250]` 并**不**调 `PushCsBuffer`。
3. 期望：`DT_Count(83)==53`，首行 `01 00 32 00`，`[0x52c3250]==0`；无 SIGSEGV。
4. 失败分支：
   - `DT_Count` 崩：检查 `0x5118810→0x52742a0` 链和 vtable 偏移；先只装 index 0 的表；
   - `ModuleInit` 崩：回到 M1，检查预加载顺序/`RTLD_GLOBAL`；
   - 表对象被内部代码打穿：只保留 `DT_*` 路径，不让 GameCore 内部消费者碰它。

### 5.3 E2：原生 databin loader（可选，高风险）

- 在 E1 基础上预加载 `libQtskDB.so`；`ModuleInit` 后设 `*(char**)(base+0x542a790)=dc.db 路径`、`*(void**)(base+0x5274280)=源表对象数组`、`*(uint32_t*)(base+0x544d3a8)=数量`，调 `0x3cd9480(0)`（sret 缓冲 ≥0x100 B），检查 `[0x542a7b0]` 是否非 0，再 `DT_Count(83)`。
- 如果崩：记录 PC/寄存器，不要反复试；回退 S2-A。此实验只验证“原生 loader 能否脱离 C# 独立跑”，不是必需路径。

### 5.4 NDK 状态与重装

- 当前本地：`ANDROID_NDK_HOME` 为空；未发现 `C:/Android`、`$LOCALAPPDATA/Android/Sdk/ndk`。**E1/E2 需要新编译 ARM64 宿主，必须先装 NDK。**
- 文档 5.17.2 的既有探针用 **NDK r28b**、`aarch64-linux-android28-clang`。建议：
  ```bash
  sdkmanager "ndk;28.0.13004108"        # r28b，按本机 SDK 实际版本号
  export ANDROID_NDK_HOME=$ANDROID_HOME/ndk/28.0.13004108
  export CC=$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/windows-x86_64/bin/aarch64-linux-android28-clang
  ```
- 编译：`-fPIE -pie -O2 -ldl -llog -landroid`；运行环境为 MuMu 内 root 的**普通进程**（非游戏进程、不登录、不注入）。若 MuMu 不可用，备选 qemu-user-aarch64 + Android bionic sysroot，但成本更高。
- 不需要重装 NDK 的部分：E0、文档、databin 块解析、`.abc` 解析。

---

## 6. 风险清单

| 风险 | 影响 | 证据/说明 | 缓解 |
|---|---|---|---|
| **初始化命令流未还原** | 无法进入战斗，后续全部阻塞 | 5.16.1/5.16.2/5.16.6；`StartLevel/PureReplayStart` 是 managed，非导出 | 静态恢复方法体；以 GameBuilder 顺序做最小局；先验证 KV 是否足以创建上下文 |
| **方法槽/函数边界异常** | 托管方法体反汇编不可靠 | `DoBattleStart` 槽→0xd2a0db8（.data.rel.ro）；`SGW.GameCoreInit` 0x55a7968 前有共享代码 | 先做方法边界校准；用字符串/调用图交叉验证，不把 metadata 地址直接当入口 |
| **TDR/CS 封装未知** | 即使有字段，也拼不出合法命令 | `FRAME_CMD_INFO` 只是 opcode 表；CSProtocolWrapper TDR 结构未逐条落地 | 用 GameCore 内 TDR pack/unpack 作为权威；先做一条最小命令（heartbeat/move） |
| **上下文/线程创建无导出** | `ModuleInit` 后 FIFO/ViewBuffer 为空 | 0x43D301C 不是安装器；`0x52c3250` BSS 0；无 create 入口 | 不做“手动造上下文”的硬编码；先找真实 C# 初始化等价物或非零 context 快照；同步 tick 代替 CoreThread |
| **databin 表对象 ABI** | `DT_*` 可过，内部消费者可能打穿 | 真实 `DatabinTableBase` vtable/字段未全解；字符串池缺失 | 先只让 `DT_*` 用；逐步补 vtable/行目录；数值列优先 |
| **QtskDB `STDBTableEnv` 回调未知** | 原生 loader/DB 直读可能失败 | `OpenTable` err=8；Hash1/Hash2 签名未定 | 先 S2-A；再反汇编 `DB_OpenTable` 找 Hash 调用约定；用块头 32 字符哈希试表名 |
| **GameCoreTS（puerts）逻辑缺失** | 逐帧逻辑可能不完整 | 5.23.2/5.23.4：`sgc_LogicTick` 由 libpuerts 定义；JS 包在加密 QTS 内 | 先读 native 出口；若要完整逻辑，解 QTS JS 包或走客户端回放 |
| **模式差异** | 5V5 与练习场的帧循环不同 | 5.23.1a：5V5 走 UnityMain，CoreThread 空闲 | 按 5V5 模式设计同步 tick，不外推练习场 |
| **构建差异** | 5230306/5169333 偏移/语法不同 | 5.16.8 变体；5.24 数据集 `old_or_unsupported` | 只锁定 5069040/12.1.1.8；先做 `check_build_match.py` |
| **资源/场景依赖** | 初始化可能需要 action/AGE/QTS 资源 | 5.17/QTS 卡点；databin 之外还有资源 | 先跑最小局观察缺什么；QTS 只作按需注入，不先攻全量 |
| **宿主稳定性** | 大库（~82 MB）+ 数 MB BSS/堆对象，MuMu 内存压力 | 5.23.4 扫描曾把对局进程拖死；宿主本身也可能 OOM | 宿主独立进程、限制扫描、不要与游戏同开；先小步 keepalive |
| **红线/合规** | 不能登录、不能注入 | MEMORY 运行时红线 | 只做静态 + 自建宿主；不 attach 游戏进程；不发布游戏二进制 |

---

## 7. 替代路线（按推荐度）

1. **客户端自带回放播放（最高保真，暂不在本任务范围）**
   - `GameReplayModule.StartHostReplay(abhPath)` + `PureReplayStart` 是 C# 托管层入口，
     **不是 GameCore 导出**；需要完整 il2cpp/Unity/资源/账号栈。GameCore 内没有
     `StartHostReplay/PureReplayStart/StartLevel` 导出（只有无关的 `visualReplayPipe` 字符串）。
   - `StartHostReplay` 的签名要 `.abh` 路径；本地 AutoSave 只有 `.abc/.ope`，没有 `.abh`。
     因此不能把“调这个入口”当成宿主捷径。
   - 代价：需要运行完整客户端（当前红线不允许登录；离线模式是否可用需单独验证），
     且状态读取要另找出口（ViewBuffer/UI/只读内存）。

2. **自有解析 + 轻量模拟器（最快交付，精度有限）**
   - 用 `replay_frames.csv`（194,652 条）、`replay_commands.csv`（1,528 条）、`replay_heading.csv`（16,315 条）、`replay_events.csv`（50,838 条）（5.24/5.25）作为输入，用 databin 数值列 + 简化的 MOBA 模型估算经济/等级/位置。
   - 优点：不依赖 GameCore 初始化；缺点：不是确定性 lockstep 结果，不能声称“真实血量/伤害”。

3. **离线 5V5 + 只读内存采样（作为校准/真值，不是模拟器）**
   - 5.19–5.22 已证明离线 5V5 可加载 databin、可只读 `/proc/<pid>/mem` 导出表/缓冲；可作为 GameCore 模拟的 ground truth 或参数校准。
   - 代价：需要游戏进程（当前任务不做），且只能采到出口缓冲，不能任意读内部状态。

4. **最小 il2cpp 宿主（复用 C# 初始化）**
   - 把 `libil2cpp.so` + `global-metadata.dat` + 必要 managed 程序集放进宿主，跑 `DatabinManager/GameBuilder/SGW` 的真实 C# 初始化，避免手工还原 CS 序列。
   - 优点：初始化逻辑与官方一致；缺点：需要 Unity/il2cpp 运行时 shim、大量 native 导入、工程量大，且 libil2cpp 有 XOR 混淆。

5. **QTS/GameCoreTS JS 提取（补齐逻辑）**
   - 5.23.2 表明逐帧逻辑可能在 TypeScript；如果 native 路径不足，必须解 QTS 包拿 GameCoreTS JS，或定向 dump V8 堆（需 NDK 探针）。
   - 这是“完整模拟”的并行前置项，不是短期可完成项。

6. **服务器/官方数据（若可得）**
   - 直接使用赛后经济/伤害面板或官方 API；不在当前静态分析范围。

---

## 8. 里程碑与验收建议

| 里程碑 | 内容 | 依赖 | 预计 | 验收 |
|---|---|---|---|---|
| M0 | 静态契约脚本 + 方案 | 无 | 已完成 | `--check` OK |
| M1 | 宿主 + ModuleInit + 全局探针 | NDK | 1–2 天 | 全局链符合 §2.2 |
| M2a | 一张 databin 表进 0x52742a0，`DT_*` 可读 | M1 | 3–5 天 | `DT_Count(83)=53`，行逐字节一致 |
| M2b | 825 张表进注册表/或原生 loader | M2a | 1–2 周 | `DT_Count` 抽查 20 张与 `tables_blocks.csv` 一致 |
| M3a | `.abc` 头解析成 `CLevelContext/deskPool` 中间结构 | 无（静态） | 1–2 周 | 25 样本 KV/玩家块 100% 解析 |
| M3b | CS 初始化命令流（最小局） | M2a + M3a | 2–4 周，高风险 | Core 创建上下文/FIFO，`0x544c0bd0` 进入 2 |
| M4 | 逐帧 Push/Commit + tick | M3b | 1–2 周 | 连续 100 帧无崩，帧号递增 |
| M5 | ViewBuffer/DT 状态读出 | M4 | 1 周 | 首帧能读到 ≥1 个玩家数值状态 |
| M6 | 与 `.abc` metadata/离线 5V5 对拍 | M5 | 1–2 周 | KDA/胜负方向一致；经济误差可解释 |

> 工期是“按现有证据的粗略估计”，M3b 的 2–4 周取决于托管方法体恢复和 TDR 封装是否顺利；若必须依赖 GameCoreTS JS，另加 2–4 周。

### 8.1 审计后的验收门槛（2026-10-30，建议写死）

详细证据分级见 `docs/evidence_audit.md`。宿主路线必须同时满足：

| # | 条件 | 当前 | 说明 |
|---|---|---|---|
| G1 | 真实 `CLevelContext/deskPool` 构造路径，不伪造字段/vtable | ❌ | 0x43D301C 不是安装器；15 个标量变量未命名 |
| G2 | 真实 CS FIFO 上下文，`CommitCsBuffer` 不崩 | ❌ | 仅 Push 通；Commit SIGSEGV（`s3b_gc_fifo0.log`） |
| G3 | 可 Push 的初始化命令流（S3），GameCore 能消费 | ❌ | KV/443B 是数据，不是 TDR 命令流 |
| G4 | 至少推进一帧并读回状态 | ❌ | 无 tick/ViewBuffer 成功记录 |
| G5 | 在真实回放/离线对局上对拍，不依赖登录 | ❌ | 离线 5V5 不产回放；context 释放；无安全账号 |

**停止规则**：下一次最小实验若仍要伪造新的 vtable/context 字段、猜 15 个变量、
或必须嵌入完整 il2cpp/Unity 才能调回放入口，就暂停 MVSS-B。不要为了
KDA/经济/血量/伤害这几个聚合指标承担完整模拟成本；这些指标优先走
录屏 OCR/CV、结算界面或服务器/战绩数据。

**本轮回放复核补充**：主样本 `.abc` 在主帧流后还有第二段 712 帧
（13096–13807），是输入续流，不是状态快照；尾部 102/106 B 是英雄/皮肤名单，
不是结算。详见 `docs/replay_binary_format.md` 5.36 与 `docs/evidence_audit.md`。

---

## 附录 A：关键地址/偏移速查（5069040 / 12.1.1.8）

```text
ModuleInit            导出 0x46ad0e0  实现 0x46ad0cc  ctx 0x542f4b0  +0x48 一次标志
PushCsBuffer          导出 0x460a3cc  实现 0x460a3ac  → 0x49cbf98
CommitCsBuffer        导出 0x460a400  实现 0x460a3e4  → [0x52488b8] vtable+0x10
PushViewBuffer        导出 0x46b7fd8  实现 0x46b7f9c  → [[[0x4ff4520]]]+0x2b0
CommitViewBuffer      导出 0x46b8024  实现 0x46b7ff0
SGC_GetPlayer*        0x46ad0fc/0x46ad11c/0x46ad13c/0x46ad15c  = mov w0,#11; ret
SGameSetEnableDatabinCrcFromFile 0x4606ac8 → 0x522a3d8 → 0x46064b4 = strb [0x542a804]
DT_Count              0x4606da0  *(0x5118810)→0x52742a0→array→vtable+0x18
DT_GetByIndex         0x4606dd8  同上 vtable+0x20
GameDataWrapper_GetTable 0x4606f04  manager [0x4ff57b0]=0x51187e8
SFNtfRunningGameCoreThreadID 0x460a4c0 = str x0,[0x542a8a8]
DatabinTableBase::LoadLocalData 0x2a36308
候选原生 databin loader 0x3cd9480（源数组 *(0x5118818)=0x5274280 → 目标 *(0x5118810)=0x52742a0；写 0x542a7b0，路径 0x542a790）
CoreThread create/stop 0x46b7784/0x46b7848；producer 0x46b7888；loop 0x4882c10
0x43d301c  引用计数/弱引用助手（不是 frame-sync context installer；5.35 已推翻旧说法）
```

## 附录 B：产物路径

- 方案：`docs/simulation_plan.md`
- 只读脚本：`tools/gc_export_map.py`
- 既有宿主探针：`data/replays/_analysis/_host/gc_boot.c`、`gc_cs.c`、`gc_tables.c`
- databin 块：`data/replays/_analysis/device/dtab_blocks/`（825 表）
- 表索引：`data/replays/_analysis/device/tables_blocks.csv`
- 初始化标量模板：`data/replays/_analysis/device/abc_init_scalars_5v5.json`
- KV 默认模板：`data/replays/_analysis/device/dtab_blocks/83_svr2GamecoreCfg.bytes.bin`
- 离线 DB 副本：`data/replays/_analysis/device/dc.db`（已被 `data/` 忽略）
- 数据集：`data/replays/_analysis/datasets/`（`replay_frames.csv` 等）
- 章节依据：`docs/replay_binary_format.md` 5.13–5.25

## 附录 C：不要重复的失败路线

- 不要再用 `frida` hook arm64 `.text`：本环境 frida 只覆盖 x86_64 翻译层（MEMORY）。
- 不要假设 `*OperatorData.Write` 是回放序列化：它是 puerts 编组层（MEMORY/5.10.2）。
- 不要在 `.abc` 里找经济/KDA：帧命令 143 条全是输入；KDA 在 metadata，经济不在（5.13.9/5.13.12/5.14）。
- 不要用 `GameDataWrapper_GetTable` 直接加载文件：它只查名字表（§4.1）。
- 不要用 `SGC_*` 读状态：全是桩（§2.1）。
- 不要在 `ModuleInit` 后直接 `PushCsBuffer`：`0x52c3250` 为 0，必崩（5.18 + §2.3）。
- 不要把 5230306/5169333 的头部/帧语法套到 5069040（5.16.8/5.24）。
