# GameCore 离线宿主化（新计划）

目标：把 `libGameCore.so` 变成可调用的离线模拟核心，输入 `.abc/.ope`，输出十人逐帧
完整状态（经济/KDA/HP/位置/装备/伤害）。这是唯一“一劳永逸”的经济与完整状态路线；
不再做客户端堆扫描、UI 时间采样或 `.dmg` 猜测。

## 1. 现状（2026-11-03）

已验证：

- 自建 ARM64 宿主可 `dlopen` GameCore + 依赖并完成 `ModuleInit`；
- `gc_sim0` 可以把宿主表对象挂到 `0x52742a0`，让 `DT_Count/DT_GetByIndex` 读取；
- **H1 已通过**：`DT_Count(83)=53`，53 行 `svr2GamecoreCfg` 逐字节一致，CS FIFO 仍为 0；
- **H2 已通过**：825 张 databin 表全部注册，`installed=825 verified=825 count_bad=0 row_bad=0 total_rows=205149`；
- `libGameCore.so` 无 il2cpp/GL 依赖，CS FIFO 不加密；
- `PushCsBuffer/CommitCsBuffer`、`PushViewBuffer/CommitViewBuffer` 的导出桩与实现已定位；
- 客户端活进程 view buffer 是登录/UI 通道，不是逐帧战斗状态（已证伪）；
- GameCore 玩家对象是池化/瞬态，不能靠暂停后全堆扫描拿十人金币（已证伪）。

运行入口：

```bash
MSYS_NO_PATHCONV=1 bash host/scripts/run_probe.sh boot    # H0
MSYS_NO_PATHCONV=1 bash host/scripts/run_probe.sh sim0    # H1
MSYS_NO_PATHCONV=1 bash host/scripts/run_probe.sh sim0b   # H2
```

未完成：

- `CLevelContext/deskPool` 的宿主构造；
- `.abc` 初始化头 → CS 初始化命令流；
- 帧循环与状态输出；
- `CPlayer`/`CLevelContext` 的完整字段表；
- 逐帧状态到 JSONL 的导出。

## 2. 架构

```text
host/gchost (ARM64, MuMu 内独立进程)
  dlopen libpandora/libpuerts/libPixUI_Unity/libpixuiCurl + libGameCore
  ModuleInit
  QTSRegisterSystem / databin 注册（0x52742a0）
  CLevelContext + deskPool 构造（S3）
  CS FIFO: PushCsBuffer + CommitCsBuffer
  同步 tick（0x46B7888 或 context+0x280）
  状态读出：CPlayer/CLevelContext 字段 + 可选 ViewBuffer
  JSONL 输出（kpl-runtime-v1）
```

宿主进程与游戏进程隔离：不登录、不进入游戏对局、不注入客户端、不修改游戏文件。
GameCore 只是被当作本地库加载；`.abc/.ope` 只读。

## 3. 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| H0 | 宿主 + ModuleInit + 全局探针 | ✅ `gc_boot` 已验证 |
| H1 | 宿主 databin 表对象 + `DT_*` 查询 | ✅ `DT_Count(83)=53`，53 行一致 |
| H2 | 825 张 databin 表注册 | ✅ installed/verified=825，205,149 行 |
| H3 | `.abc` 头 → fixture 中间结构 | ✅ `host/scripts/make_fixture.py`；11/2 样本 53 KV、10 玩家、443B 标量、10,674 帧 |
| H4 | 真实 `CLevelContext`/CS FIFO 快照 | ▶ 已捕获 `context_snapshot.json`，尚未构造宿主 context |
| H5a | 真实帧载荷 → CS slot0 → consumer 探针 | ✅ active context + globals 下 1–200 帧 200/200 ok、400–440 帧 41/41 ok；0x39/0x3a/0x3b 等真实分派；见 `docs/h5_active_context_slot0.md` |
| H5b | CS 初始化命令流（最小局）/ 帧 tick | ▶ handler 路径已跑通，但只是网络日志处理；1000 帧 sequential 在 667 崩于 `0x28719F0`，未证明帧推进/DS 状态 |
| H6 | 状态字段表 + JSONL | 依赖 H5b |
| H7 | 批量 runner + 版本适配 + 回归校验 | 产品化 |

## 3.5 H4 真实上下文快照（只读）

`host/scripts/capture_context.py --freeze` 在回放播放时抓取：

```text
host/fixtures/20261102_161129/context/context_snapshot.json
```

本次结果：

- live context：`0x75d7e86e9ff0`；
- CS 8 路数组：`0x40003bcc3250`；
- 槽 0：vtable `0x75db20ca8608`，cap 32768，pending 8；
- 槽 1：同 vtable，cap 262144，pending 76；
- 槽 2：同 vtable，cap 32768，pending 0；
- 槽 3+ 不是有效 buffer（字段不符合 `+0x18/+0x20/+0x24` 布局）。

context 的 qword 扫到多个子对象（`+0x240/+0x2c8/+0x2b0/+0x5e0` 等），其中
`ctx+0x2c8` 的目标在 `+0x19e0` 处出现 entity 1168，`ctx+0x5e0` 出现 entity 1760/1799；
这些更像事件/缓冲记录，尚未证明是 `deskPool` 或十人 `CPlayer` 数组。

结论：H4 只完成“真实上下文快照”，**没有完成宿主 context 构造**；不做伪造 vtable/字段。

### H4 审计的硬阻塞（2026-11-03 多智能体复核）

- live context 不是 C# `CLevelContext`；它是 native 自相对 arena（容量 `0x1E00000`，
  `+0x00` 自指针、`+0x08` 容量/游标、`+0x18` 结束指针）。截获的前 `0x1000` 字节
  没有十人数组；`ctx+0x2C8`/`ctx+0x5E0` 的 entity 命中只是候选，未证明 deskPool。
- `base+0x52C3250` 是**异质 8 槽指针表**，不是 8 个相同 CS FIFO。Push/Commit/Reset
  只用 slot0；slot1 是 Cpp pack，slot2/3 是其他 ring，slot4/5 由 context 绑定。
- 之前把 `0x6C`/`0x7FFF` 当 CS 记录头是**错误归属**；它属于相邻的 108B 多态记录
  SBO vector。CS 是字节 ring，槽0 pending 8/76 不是 108 的倍数。
- 真实 FIFO 可由宿主安装：ring ctor `0x49CBD88` + init `0x49CBEEC`，写入
  `base+0x52C3250` slot0；但 **FIFO 写入不等于 GameCore 消费**。
- GameCore 没有 context/FIFO/线程创建 C 导出。context 持有者 `0x52717B0` 只能由
  内部 pool 安装函数绑定真实 context；pool 工厂依赖 `0x51D10BD0/0x51D10B30`，
  静态为 0，且 live 进程读数也为 0。context 构造函数 `0x40A0CA0` 只对已有 context
  做初始化，不创建/安装。
- C# `SGW::GameCoreInit`/`StartLevel`/`PureReplayStart` 的标签地址不是函数起点，
  且都依赖 il2cpp/Unity 运行期，不是宿主可调用入口；本地 metadata 与设备 metadata
  方法数不同（416,645 vs 416,815），旧标签不能当入口。
- CoreThread 创建依赖 `0x50B40F48` 线程工厂（静态/live 均为 0），且 5v5 不走
  CoreThread；不能作为 H5 的帧驱动捷径。

因此 H4 目前是**真实硬阻塞**：没有真实 context/pool/owner，H5 不能开始。下一步只有
两条：捕获并移植真实 context 对象图，或引入 il2cpp/C# 初始化宿主；不做伪造 context。

### H4-A 真实 context arena 移植可行性（2026-11-03）

已只读捕获完整 arena（`data/` 忽略目录，不提交）：

```text
context = 0x75d7e86e9ff0
size    = 0x1E00000 (31,457,280 B)
sha256  = db8f075defa7d4310ccb0dc4897a022dccafec38035f243df6b834492658dcda
```

对 arena 内 3,932,159 个 qword 的统计：

| 目标类别 | 数量 |
|---|---:|
| 指向 context arena 内部 | 181,234 |
| 指向 libGameCore 静态范围 | 12,779 |
| 指向外部堆（scudo/anon/file） | 406,716 |
| 其他指针 | 11,443 |

外部堆指针去重后 **111,674 个不同目标**；其中 102,813 个目标在 scudo，8,272 个指向
`dataCache.db` 映射。**context 不是自包含 arena**：只复制 30MB arena 并重定位内部指针，
会有大量外部对象悬空，不能作为可运行的 context。

结论：**纯 arena 移植不成立**。若继续 A，需要升级为“进程堆快照移植”：把 context
以及其外部堆对象/文件映射一起复制并在宿主中保持地址关系；这是一项独立的大工程，
不是单纯 copy + rebase。否则应转 B（il2cpp/C# 初始化宿主）。

### B0：il2cpp 宿主运行环境（2026-11-03）

- APK 无托管 DLL，只有 `global-metadata.dat` + resources.dat；IL2CPP 正常形态。
- 本地 `libil2cpp.so` + `libtprt.so` + metadata 已推送独立宿主。
- MuMu 是 `x86_64 + houdini`；`il2cpp_probe` 加载 `libil2cpp` 后 **SIGILL**，
  backtrace 在 `/system/lib64/libhoudini.so`，`il2cpp_init` 未完成。
- 结论：B0 **未通过**；B 需要原生 ARM64 Android 环境（ARM64 AVD/真机或
  qemu+bionic），不能在当前 houdini 翻译环境继续。详见 `docs/il2cpp_host.md`。

## 3.6 H5 真实帧载荷 → slot0 → consumer 探针（2026-11-03）

入口：`host/src/h5_probe.c`、`host/scripts/run_h5_probe.sh`；
说明：`docs/h5_consumer_probe.md`。

它把 `.abc` 的逐帧 `szInfoBuff` 原样推进真实 slot0（`PushCsBuffer` +
`CommitCsBuffer`），再调用真实 CS consumer（`0x46B80E8`，拆成
`0x49CBC0C` drain + `0x46B8070` parse）。结论：

- 1,000 帧（20261102_161129，跳过 1 B 空帧）全部 push/commit 成功，
  `drained == bytes` 1,000/1,000，consumer buffer 与 payload 逐字节一致
  1,000/1,000；全量 10,473 非空帧 `drain == bytes` 10,473/10,473；
- 干净宿主 `ModuleInit` 后 `[0x5272368]=0`、`[0x544D340]=0`，parser 不分发；
- 用 `host/scripts/capture_cmd_table.py` 只读导入 live 命令表
  （857 槽、792 个非零 handler、1,368 个 BSS slot）后，全量 935 帧进入
  dispatcher；25 帧正常返回，910 帧在 context/battle 对象缺失处崩溃；
- 崩溃点不是 FIFO/payload 拷贝问题；同 opcode 的 flag=0/1 分支可产生
  “崩溃/返回”两种结果；
- 仍未证明 `.abc` payload 是原生 CS TDR，也没有帧推进或状态输出。

## 4. 第一执行批次

1. 用 `gc_sim0` 验证一张表：`DT_Count(83)=53`，行逐字节一致；
2. 用 `gc_sim0b` 验证 825 张表注册/查询；
3. 把宿主工程从 `_host` 探针 Productize：`host/scripts`、`host/src`、`host/fixtures`；
4. 再进入 H3/H4。

## 5. 验收原则

- 不声称“能跑完整局”，直到 **H4 + H5** 连续帧无崩、帧号递增；
- 不声称“拿到完整状态”，直到 H6 能从 GameCore 内部读出至少一个玩家的一个数值状态；
- 不以 UI/营地数据替代 GameCore 状态；它们只做回归校验；
- 每阶段保留可复现命令和日志，不记录敏感账号/token。
