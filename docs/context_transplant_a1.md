# A1：完整进程堆快照移植（设计）

日期：2026-11-03。目标：把 context + 外部对象 + 文件映射整体复制到宿主，
保持原虚拟地址关系，再重定位 libGameCore，让宿主能用真实 context 启动 H5。

## 1. 已知事实

context arena：`0x75d7e86e9ff0`，`0x1E00000` B；内部指针 181,234、libGameCore
12,779、外部堆 406,716（去重 111,674）。

从 context arena 的外部指针反查当前进程 mapping：

```text
外部唯一目标 mapping：35 个
总大小：2,029,359,104 B ≈ 1.89 GiB
最大项：dataCache.db 119 MiB、多个 scudo primary_reserve 250 MiB
```

注意：这里只统计了 context 直接指针；嵌套对象可能再指向其他 mapping，抓取后用
“可达区闭包”再补，不能假设 35 个 mapping 就是全部。

## 2. 快照格式

```text
data/replays/_analysis/client_probe_<date>/process_snapshot_<pid>/
  meta.json                 # old base/context/gc range, region count/bytes
  regions.tsv               # start end perms path file size sha256
  region_<start>_<end>.bin  # 原地址内容
```

原始快照只放 `data/` 忽略目录，不提交、不写文档正文；文档只保留地址/大小/hash。

## 3. 宿主装载

1. 先 `mmap(MAP_FIXED_NOREPLACE)` 每个 region 到原 start；失败立即报告，不做覆盖。
2. 复制 region 内容。
3. `dlopen` GameCore 依赖 + GameCore；得到新 base。
4. 扫描所有 region qword：
   - `[old_ctx, old_ctx+size)`：地址保持原样（context 在快照内原位）；
   - `[old_gc, old_gc+old_gc_size)`：加 `new_gc - old_gc`；
   - 其他 libc/libtprt/Unity 指针：先统计，不静默改。
5. 写 `base+0x52717B0 = old_ctx`，检查 `[base+0x4FF4520]` 链。
6. 安装真实 CS FIFO ctor/init 到 `base+0x52C3250` slot0；验证 Push/Commit/Reset。
7. 不接受“只映射成功”作为通过；必须验证 context 的 view/CS 指针和外部对象可读。

## 4. 验收

- 所有 region 固定映射成功，内容 hash 与 manifest 一致；
- 重定位后 context 内指针统计与快照前一致（或差异可解释）；
- `0x52717B0` 指向快照 context；
- 真实 CS FIFO slot0 可 Push/Commit/Reset；
- 若继续到 H5，必须证明 CS 消费者能读 slot0/`0x544CC40`，否则只算“装载成功”。

## 5. 风险

- 2 GB 快照含账号/token 等内存；只在本地忽略目录，不传播。
- 原进程地址与宿主自身库/堆冲突；用 `MAP_FIXED_NOREPLACE` 失败即停。
- 外部指针可能指向 stack/TLS/其他库；先统计，不假设全部可移植。
- 这是研究性快照，不是产品化采集；不能把快照文件提交或外传。

## 6. 实测结果（2026-11-03）

快照：`process_snapshot_2052`，26 个 region，282,755,072 B。

宿主 `host/src/gc_transplant.c` 实测：

```text
mapped=26 failed=0
holder_slot=0x21c717b0
published context = 0x75d7ea4e99f0
binder context P = 0x75d7ea4e99f0
slot0 = 0x75d7e7fe70fc
slot1 = 0x75d7e7fe718c
slot4 = P+0x4f0
slot5 = P+0x578
PushCsBuffer(0) 返回 staging 指针
CommitCsBuffer(0) 不崩
ResetCsBuffer 不崩
```

关键修正：之前抓的 `0x75d7e86e9ff0` 是包装层；真正的 binder context 是
**`P=0x75d7ea4e99f0`**（在 context arena 内，`P+0x600` 等于包装层 `+0x18`）。
`P+0x80/+0x88` 正好是 slot0/slot1，`P+0x4f0/+0x578` 是 binder 的内嵌槽位地址。

## 7. H5 consumer 实测（2026-11-03）

补抓 consumer 所在 region `0x75dc98d88000-0x75dc99108000`（3.5 MiB）后，宿主：

```text
mapped=27 failed=0
BSS state [0x544CBD0]=0x400000000002
consumer [0x544CC40]=0x75dc98daac10
calling CS consumer 0x46B80E8
CS consumer returned
```

这证明：

- 正确的 BSS 偏移是 `0x544C000 + 0xBD0 = 0x544CBD0`、`+0xC40 = 0x544CC40`；
- consumer 指针必须来自 live snapshot，A1 主快照本身没有包含它；
- 宿主可以调用真实 `0x46B80E8`，不崩。

**但 consumer 返回不等于推进帧/读到状态**：当前 slot0 pending 为 0，consumer 没有
消费到有效命令。H5 还需要把 `.abc` 初始化/帧命令按真实 TDR 格式推入 slot0。

### 7.1 H5 探针补测（2026-11-03）

`host/src/h5_probe.c` 已在 A1 之上补了“真实帧载荷 → slot0 → consumer”：

- 快照里 consumer buffer 的 base `0x75ddc9809ff0` 不在 27 个 region 内；
  探针用宿主 `calloc(0x40000)` 替换该 buffer（只替换数据缓冲，不替换
  consumer 对象/表），否则第一次非空 drain 会写未映射页。
- 1,000 帧 `.abc` 原始 `szInfoBuff`：`PushCsBuffer` + `CommitCsBuffer` 全部
  成功，slot0 `pending/write/committed` 等于帧长；consumer drain
  `0x49CBC0C` 使 `drained == bytes` 1,000/1,000，buffer 与 payload
  逐字节一致 1,000/1,000；全量 10,473 非空帧 `drain == bytes`
  10,473/10,473。
- 干净宿主命令表为 0；用 `host/scripts/capture_cmd_table.py` 导入 live
  命令表（857 槽/792 非零 handler/1,368 个 BSS slot）后，parser
  `0x46B8070` 全量分发 935 帧，其中 25 帧 handler 返回，910 帧在
  context/battle 对象解引用处崩溃。
- 仍未证明 payload 是原生 CS TDR，也未推进帧；详见
  `docs/h5_consumer_probe.md`。

## 8. A 路线后续结果（2026-11-04 晚）

active context `P=0x730fe87fcff0`、`ctx+0x3d0=0x730fea5db178` 的 39-region
快照已让真实 slot0 handler 路径跑通：

- 补齐 `0x4FF8000` data、`0x526F000` BSS、`0x544C000` 跳转表，并修
  `[0x4FF57C8]=base+0x52488C0`；
- `--init-slot1` 用真实 ctor 初始化 slot1，修复 `0x39` 的 null slot；
- 1–200 帧 isolated/sequential 均 200/200 ok；
- 400–440 帧 41/41 ok，`0x39/0x3a/0x3b/0x34/0x73` 计数与 fixture 完全一致；
- context 每帧 113–126 B 变化，但属于命令/协议记录，不是 DS 状态推进。

详见 `docs/h5_active_context_slot0.md`。

## 9. 仍未完成

- 外部指针未全部重定位：`other_ptrs≈1.97M`，仍可能有 libc/houdini/stack 指针。
- 已把真实 `.abc` 帧载荷推入 slot0 并调用 consumer drain/parse，但**没有推进帧**
  （无 tick、无帧号递增）；handler 的 context/battle 依赖仍未补齐。
- 初始化命令的 TDR 线格式仍未证明；不能编造命令字节。
- 原生 ARM64 环境仍未解决 B 路线的 il2cpp SIGILL。

复现：

```bash
bash host/scripts/build_host.sh  # 编译 gc_transplant 需 SRC/OUT_BIN 覆盖
MSYS_NO_PATHCONV=1 bash host/scripts/run_transplant.sh
```

## 6. 2026-11-04 晚：闭包抓取 + 4 字节对齐指针（决定性修复）

### 6.1 旧失败根因

旧快照只从 context arena 抓一层指针，`slot0+0x18` 指向的外部缓冲没有进入快照；
重定位又只扫 8 字节对齐 qword。实际 GameCore 的 binder/CS 结构是 **4 字节对齐打包**：

```text
slot0 = P+0x80 = 0x…30fc
slot0+0x00 u64 = 0x…da4608
slot0+0x08 u64 = 0x…f00f00
slot0+0x18 u64 = 0x…0664b0   ← 位于 …1114，8 字节不对齐
slot0+0x20 u32 cap=0x8000, +0x24 u32 size=8
```

因此 `PushCsBuffer(0)` 一直返回旧地址，`Commit` 写入未映射内存后 SIGSEGV。
修复：`rebase_snapshot.py` 同时扫 offset 0 和 offset 4 两套 qword；
offset-4 写入与相邻对齐 qword 冲突时跳过。重写数 9,468,541 → 10,003,610。

### 6.2 wrapper 与 binder 必须分开

`0x4FF4520` 链最终得到的是 **wrapper context**（如 `0x2000ec9ff0`），
而 CS slot0/slot1 在 **binder context P**（wrapper+0x1DFFA00，如 `0x2002cc99f0`）。
把 P 写进链会在 `wrapper+0x3b8` 取到垃圾（实测 `0x0b25168ccc66cc26`），
帧推进第一步即崩。harness 现在分别接收 `--context`（wrapper）和 `--binder`（P）。

### 6.3 闭包抓取器 `host/scripts/capture_closure_snapshot.py`

```text
种子   arena + holder/consumer/CS 全局槽 + 模块 .data/.bss
展开   arena 一层叶子；CS 对象一层；globals 根一层 + 其目标再一层
策略   只收 rw 的 scudo / Mem_ / 未命名堆；排除代码、栈、reserve、dalvik
       模块自身范围 [base, base+0x6000000) 不复制（宿主 dlopen 自己的）
输出   regions.tsv + meta.json + globals/manifest.tsv（.data + .bss）
```

### 6.4 当前状态

| 步骤 | 结果 |
|---|---|
| 137 区映射 | 137/137，0 失败（39-bit 重定位） |
| Push / Commit / Reset | 正常，返回重定位后的缓冲区 |
| CS consumer `0x46B80E8` | 正常返回 |
| 帧推进（op 0x0d） | **需要 globals**；否则 `wrapper+0x3b8` 链断 |
| 载入 globals 后 | MuMu 上前 17 帧逐帧 ok（consumer returned=1, bytes_match=1），第 18 帧遇到 globals 指向未抓堆区 |

### 6.5 结论

- ARM64 39-bit 移植链路已打通到“帧命令消费”层；剩余问题是闭包完整性。
- 47-bit 的 MuMu 实验环境跨模块指针天然有效，是当前最快的验证与取数环境；
  ARM64 上任何 libil2cpp/libunity 指针都无法复用（宿主不加载托管运行时）。
- 下一步必须是 **回放加载状态下的一次性完整抓取**（arena + CS + globals 根），
  最好在 00:00 暂停，从而从第 1 帧离线推进整局。
