# H5 探针：真实帧载荷 → CS slot0 → consumer

日期：2026-11-03。目标是把 `.abc` 里**逐帧原始命令缓冲**（`szInfoBuff` /
`CSDT_FRAPBOOT_INFO` 字节）通过真实 `PushCsBuffer/CommitCsBuffer` 推进
GameCore 的 CS slot0，再调用真实 CS consumer，并把“推送 / 提交 / 排空 /
解析分发”四段结果分别记录下来。

范围：私有 ARM64 宿主进程；只读进程快照；不注入游戏、不登录、不调用游戏进程内
函数、不修改游戏文件。快照和命令表都在本地忽略目录或 fixture 中，不含账号、
昵称、对局内容等玩家数据。

## 1. 结论先行

1. **推送链已打通**：对 20261102_161129 的前 1,000 帧，`PushCsBuffer(len)` +
   `CommitCsBuffer()` 全部成功；slot0 的 `+0x24` pending、`+0x2c` write、
   `+0x34` committed 都精确等于该帧载荷长度，`+0x10` ring size 保持 0x10000。
2. **consumer 排空链已打通**：`0x46B80E8` 的第一步（`0x49CBC0C`）把 slot0
   中的真实载荷全部读入 consumer 缓冲；1,000/1,000 帧满足
   `drained == bytes`，consumer 的 `+0x0` base、`+0x8` cap、`+0xc` used 都可读回。
3. **解析分发需要运行期命令表**：干净宿主 `ModuleInit` 后
   `[base+0x5272368] == 0`、`[base+0x544D340] == 0`；不导入命令表时，
   parser 在第一个 32 位头处因 `opcode >= 0` 直接返回，**不会分发**。
4. **导入真实命令表后确有 handler 执行并返回**：1,000 帧中 89 帧的
   `opcode < 857`，其中 5 帧由真实 handler 正常返回；其余 84 帧在
   handler 内的 context / battle 对象解引用处崩溃（见 §6）。
5. **这不是“CS TDR 已还原”**：payload 是 BOOTFRAP 容器，不是证明过的原生
   CS TDR 流；成功返回只证明该帧的字节被 parser 接受并执行了对应 handler，
   不证明帧推进、经济/KDA 或任何对局状态。

## 2. 消费链（静态事实 + 本次实测）

```text
PushCsBuffer(len)  -> 0x460A3AC -> slot0 staging (+0x18)
写 staging len 字节 -> 0x460A3E4 (Commit) -> ring +0x08 / cursors +0x2c,+0x30,+0x34
0x46B80E8
  ├─ 0x49CBC0C(consumer, slot0)        ; 把 slot0 可读字节读入 consumer buffer
  └─ 0x46B8070(buf, buf + used)        ; 解析命令流并分发 handler
```

parser 的 32 位头（`0x46B8070`，小端）：

```text
hdr   = *(u32 *)p; p += 4
opcode = hdr & 0xffff
arg    = hdr >> 16
flag   = (hdr & 0x40000000) ? 0 : 1
if (opcode >= [base+0x5272368]) stop
handler = *(void **)(*(void **)(base+0x544D340) + opcode*16)
handler(&p, flag, arg)
```

- `[base+0x544D340]` **是表指针**，不是表本身；每个 entry 16 B，第一 qword 是
  handler。827 个非零 entry、857 个槽位容量，表本身在宿主 BSS 的
  `base+0x53F6F40`（本次快照）。
- `0x49CBC0C` 先把 consumer `+0xc` 清零，再从 slot0 读；读满 cap 时会把
  buffer 扩到 2 倍。实测 payload 最大 169 B，cap 0x40000，不触发扩容。
- `0x46B80E8` 是“排空 + 解析”的组合；探针默认把两步分开调用，以便 parser
  崩溃时仍能报告排空结果。`--monolithic-consumer` 可恢复原组合调用。

## 3. 探针设计

### 3.1 `host/src/h5_probe.c`

- H0 引导：preload 4 个依赖 + `dlopen libGameCore.so` + `ModuleInit`。
- A1 快照：`mmap(MAP_FIXED_NOREPLACE)` 27 个 region，重定位 libGameCore 指针，
  发布 captured context（`P=0x75d7ea4e99f0`），写 `[0x544CC40]` consumer 和
  `[0x544CBD0]` core state。
- slot0：
  - 默认用真实 ctor `0x49CBD88` + 手工字段初始化（等价于 `0x49CBEF4` 的
    `+0x08/+0x10/+0x18/+0x20/+0x78/+0x80`，使用宿主 malloc/free）。
    原因：stock init 的 `vtable+0x18` 尾回调在宿主中会崩（见 §7）；
  - `--reuse-slot0` 复用快照里的真实 slot0 并先 `ResetCsBuffer`；
  - `--stock-init` 强制走真实 init，仅用于复现该崩溃。
- consumer：
  - 默认 split：先 `0x49CBC0C`，记录排空和 cursors，再 `0x46B8070`；
  - `--monolithic-consumer`：直接调 `0x46B80E8`；
  - consumer buffer 若不在快照 region（本快照缺 `0x75ddc9809ff0` 所在
    mapping），用宿主 `calloc(0x40000)` 替换并记录 `consumer_buffer_replaced=1`。
- 命令表：`--cmd-table` 读取 `KCMD v1` 二进制，安装到
  `base+0x53F6F40`，写 `[0x544D340]` / `[0x5272368]`，并只把当前为 0 的
  BSS slot 写成捕获值；非零冲突保留并计数。
- 隔离：`--mode isolated` 每帧 fork 一个 child；child 把 `struct result`
  写入 `MAP_SHARED` 内存，崩溃时父进程仍能读到 push/commit/drain 结果；
  child 的 signal handler 把 `pc/fault/lr/sp` 写入 pipe。
  `--mode sequential` 单进程连续跑，适合已经稳定的帧。

### 3.2 输入产物

`host/scripts/extract_frame_payloads.py`：

```text
host/build/frames/<replay_id>/
  frames.bin    # 逐帧 payload 原样拼接
  index.tsv     # # index sequence offset length entries parsed abc_offset
  manifest.json # 来源 sha256、版本/build、抽取统计
```

本次 20261102_161129：

| 项 | 值 |
|---|---:|
| frame records | 10,509 |
| extracted | 10,509 |
| frames.bin bytes | 334,159 |
| zero-command frames（1 B） | 36 |
| 结构解析成功 | 10,509 / 10,509 |
| 结构解析失败 | 0 |

> `run_h5_probe.sh` 默认带 `--skip-empty`，所以 36 个 1 B 零命令帧不进入
> 1,000/全量跑批。去掉该开关后它们也会被原样推入；parser 会从 1 B 之后读到
> consumer buffer 的零填充尾部（`preflight=0`），结果需单独看，不能和
> 4 B 以上的帧混在一起统计。

### 3.3 命令表捕获

`host/scripts/capture_cmd_table.py` 通过 root ADB 只读读取
`/proc/<pid>/mem`：

```text
count      = *(u32 *)(base+0x5272368)
table_ptr  = *(u64 *)(base+0x544D340)
entries    = read(table_ptr, count*16)
slots      = 反汇编每个 thunk 的 adrp+ldr，递归扫描 2 层，
             读取 writable segment 0x4ff5000..0x544d478
```

本次结果（pid 2052，build 5247758）：

| 项 | 值 |
|---|---:|
| count | 857 |
| 非零 handler | 792 |
| flags 观察值 | 0, 1, 0x100 |
| table base-relative | 0x53F6F40 |
| 捕获 slot | 1,368（5 个 zero，6 个 non-lib 跳过） |
| 扫描 target | 985 |
| binary sha256 | `af5c582e…` |

产物：`host/fixtures/20261102_161129/consumer/cmd_table.{bin,json}`。
`KCMD v1` 布局：`<4sIIQQQ>` header（36 B）+ `count×<QQ>` + `nslots×<II>`。

## 4. 运行

```bash
# 1) 编译
NDK=/d/android-ndk-r28b \
  SRC="$PWD/host/src/h5_probe.c" OUT_BIN="$PWD/host/build/h5_probe" \
  bash host/scripts/build_host.sh

# 2) 抽取真实帧载荷（一次即可）
python host/scripts/extract_frame_payloads.py \
  data/replays/samples/20261102_161129/*.abc

# 3) 捕获命令表（需要 live 游戏进程；只读，可选）
python host/scripts/capture_cmd_table.py --pid <pid>

# 4) 跑探针
MSYS_NO_PATHCONV=1 bash host/scripts/run_h5_probe.sh \
  --mode isolated --limit 200 --skip-empty

# 5) 汇总
python host/scripts/summarize_h5_probe.py \
  host/build/h5probe/run_200.jsonl
```

常用开关：

| 开关 | 作用 |
|---|---|
| `--no-consumer` | 只 push/commit，不调用 consumer |
| `--no-push` | 只排空 consumer，不推新帧 |
| `--reuse-slot0` | 用快照里的真实 slot0（先 Reset） |
| `--monolithic-consumer` | 调 `0x46B80E8` 组合入口，而非拆开的 drain+parse |
| `--stock-init` | 走真实 `0x49CBEF4`（宿主会崩，仅复现） |
| `--skip-empty` | 跳过 1 B 的零命令帧 |
| `--stride N` | 每 N 帧取一帧 |
| `--jsonl FILE` | 结果写文件 |

## 5. 输出 schema

每行一个 JSON：

```json
{"event":"frame","frame":2,"seq":3,"bytes":169,
 "preflight":2,"opcode":280,"arg":60930,"flag":0,
 "in_range":1,"handler":"0x4707d64","pending":169,
 "slot0_before":{"ring":65536,"pending":0,"write":0,"read":0,"committed":0},
 "slot0_commit":{"pending":169,"write":169,"read":0,"committed":169},
 "consumer":{"base_before":"0x...","base_after":"0x...","cap_before":262144,
             "cap_after":262144,"used_before":0,"used_after":169,
             "returned":0,"drained":169,"bytes_match":1},
 "stage":4,"status":"crash","signal":11,"exit":139,
 "crash_pc":"0x46bfe64","crash_fault":"0x0","crash_stage":4,
 "crash_opcode":280}
```

`preflight`：0 = 不足 4 B，1 = opcode 超范围，2 = 会分发。
`stage`：0 初始，1 push 完成，2 commit 完成，3 进入 consumer，
4 drain 完成 / 组合 consumer 返回，5 parse 返回。
`status`：`ok` / `crash` / `timeout` / `exit`。
`crash_pc` 是 base-relative；`crash_fault` 是 `si_addr`。

## 6. 实测结果

### 6.1 无命令表（干净宿主）

```text
cmd_count=0 table=0x0
frame 2: preflight=1 in_range=0 drained=169 returned=1 stage=5 status=ok
frame 3: preflight=1 in_range=0 drained=57  returned=1 stage=5 status=ok
frame 4: preflight=1 in_range=0 drained=8   returned=1 stage=5 status=ok
```

含义：真实载荷能完成 push/commit/drain；parser 因 count=0 不进入任何 handler。
这是“链路已通、命令表未装”的基线。

### 6.2 导入命令表（1,000 帧）

| 指标 | 值 |
|---|---:|
| frames | 1,000 |
| drain == bytes | 1,000 / 1,000 |
| consumer buffer 与 payload 逐字节一致 | 1,000 / 1,000 |
| preflight 1（opcode 超范围） | 911 |
| preflight 2（会分发） | 89 |
| handler 正常返回 | 5 |
| handler 崩溃 | 84 |

正常返回的 5 帧：

| frame | seq | bytes | opcode | arg | flag | handler |
|---:|---:|---:|---:|---:|---:|---:|
| 5 | 6 | 8 | 257 | 36868 | 1 | 0x4703bc4 |
| 64 | 65 | 11 | 258 | 19206 | 0 | 0x4703dc8 |
| 406 | 407 | 49 | 265 | 60930 | 0 | 0x4704108 |
| 408 | 409 | 49 | 265 | 60930 | 0 | 0x4704108 |
| 498 | 499 | 39 | 261 | 19206 | 0 | 0x4703f34 |

崩溃点（前 1,000 帧）：

| crash_pc | 次数 | 说明 |
|---|---:|---|
| 0x45a2f08 | 57 | handler 读 `[x0+0x40]`，x0 为缺失的 battle 对象 |
| 0x3a2ca7c | 7 | `ldr x8,[x0]; ldr x1,[x8+0x40]; br x1`，x0/vtable 链缺失 |
| 0x40a1214 | 6 | context/battle 计数对象解引用 |
| 0x46b6188 | 4 | `ldr x0,[x9+0xa8]`，context 弱引用对象缺失 |
| 0x373fb90 | 4 | `ldr w8,[x8+0x5c]`，x8=0 |
| 0x46bf3e4 | 3 | `ldr w1,[x9+0x10]`，context 字段缺失 |
| 0x46bf434 | 2 | 同上 |
| 0x46bfe64 | 1 | `[0x4ff4520]` 链 → `[x9+0x3a0]` → `+0x5c` |

这些不是 FIFO 或 payload 拷贝问题：同一次调用里 slot0 `drained == bytes` 已经
成立，且 consumer buffer 与 payload `memcmp` 一致；崩溃发生在 parser 已经取到
32 位头并进入对应 handler 之后。

### 6.4 全量非空帧（10,473 帧）

同一样本去掉 36 个 1 B 零命令帧后的全量跑批：

| 指标 | 值 |
|---|---:|
| frames | 10,473 |
| bytes pushed | 334,123（总 payload 334,159，少 36 B 空帧） |
| drain == bytes | 10,473 / 10,473 |
| preflight 0（<4 B） | 1 |
| preflight 1（opcode 超范围） | 9,537 |
| preflight 2（会分发） | 935 |
| handler 正常返回 | 25 |
| handler 崩溃 | 910 |

正常返回的站点（opcode, flag）：`(261,0)×12`、`(265,0)×8`、`(258,0)×3`、
`(257,1)×1`、`(261,1)×1`。崩溃点全量分布：

| crash_pc | 次数 | 说明 |
|---|---:|---|
| 0x45a2f08 | 389 | handler 读 `[x0+0x40]`，x0 为缺失的 battle 对象 |
| 0x3a2ca7c | 153 | `ldr x8,[x0]; ldr x1,[x8+0x40]; br x1`，vtable 链缺失 |
| 0x40a1214 | 126 | context/battle 计数对象解引用 |
| 0x46b6188 | 125 | `ldr x0,[x9+0xa8]`，context 弱引用对象缺失 |
| 0x46b61e8 | 59 | 同一 context 路径 |
| 0x46b6114 | 19 | 同一 context 路径 |
| 0x46bf3e4 | 18 | context 字段 `[x9+0x10]` 缺失 |
| 0x46b605c | 8 | 同一 context 路径 |
| 0x3740154 | 5 | `ldr w8,[x8+0x5c]` 类字段 |
| 0x373fb90 | 4 | x8=0 |
| 0x46bf434 | 3 | context 字段 |
| 0x46bfe64 | 1 | `[0x4ff4520]` 链 → `[x9+0x3a0]` → `+0x5c` |

结论：935 个“字节层面能进入 dispatcher”的帧中，只有 25 个在移植宿主里完整
返回；其余先通过 drain，再在 handler 的 context/battle 依赖处崩溃。这是
**运行期状态缺口**，不是 ring 布局或 payload 拷贝问题。

### 6.3 关键对照：同一 opcode 的两个分支

- frame 4（opcode 257，flag 0）→ `0x373fb90`，fault 0；
- frame 5（opcode 257，flag 1）→ handler 返回 ok。

handler `0x4703b48` 的第一条分支就是 `tbz w1,#0`；这说明 flag 来自 32 位头的
bit30，并真实影响 handler 路径。探针记录的是实际执行结果，不是把“未崩溃”
当成“语义正确”。

## 7. 证明与未证明

**已证明（本次实测）**

- 真实 `.abc` 帧载荷可以按字节推进真实 slot0；push/commit 的 pending、
  write、committed 与载荷长度一致。
- consumer 的 drain 步骤（`0x49CBC0C`）对每一帧都把 slot0 读空，且
  consumer `used == 帧长`；1,000 帧样本中 consumer buffer 与 payload
  `memcmp` 1,000/1,000 一致；全量 10,473 非空帧 `drain == bytes` 10,473/10,473。
- 干净宿主 `ModuleInit` 后命令表/consumer/core state 均为 0；
  导入真实命令表后 parser 会按 32 位头分发，935 帧进入 dispatcher，
  其中 25 帧由真实 handler 正常返回。
- handler 崩溃点集中在 context/battle 对象解引用，属于运行期状态缺口，
  不是 slot0/FIFO 布局错误。

**未证明**

- `.abc` payload 就是原生 CS TDR 流；它是 `CSDT_FRAPBOOT_INFO` 容器，
  32 位头能命中只是字节层面的实验结果。
- 帧推进、tick、`CLevelContext` 状态更新或任何经济/KDA/血量输出。
- 所有 857 个 opcode 的 handler 都能在移植宿主里运行；很多 handler 需要
  真实 context、pack buffer、battle 对象或更多 BSS slot。
- 命令表是某一时刻的 live 快照状态；不同 build/进程状态可能不同。

## 8. 已知限制与下一步

1. **context 依赖**：`0x46bfe64` 的 `[0x4ff4520]` 链在宿主中走到
   `[x9+0x3a0]` 为 0。需要确认 A1 发布的 `P=0x75d7ea4e99f0` 是否就是
   `[[0x4ff4520]]` 期望的 active context，或补抓 wrapper/owner 层。
2. **更多 BSS slot**：当前只导入 table thunk + 2 层代码指针；handler 内的
   数据对象仍可能为 0。下一步可按 `crash_pc` 反查缺失 slot，定向补捕。
3. **slot0 初始化**：stock init 的 `vtable+0x18` 尾回调在宿主中崩；
   默认已改为等价字段初始化。等确认该回调的运行期注册值后，可恢复 stock init。
4. **命令流格式**：如果目标是把 BOOTFRAP 命令真正转换成 parser 的
   `[opcode:16][arg:16]` 流，需要先建立 selector → opcode / payload 长度的
   映射；本探针只验证“原始字节 + 真实 consumer”的行为，不做转换。
5. **完整跑批**：1,000 帧约 50 s（isolated）；全量 10,473 非空帧本次约 9 min
   （设备状态相关）。全量汇总可用 `host/scripts/summarize_h5_probe.py` 生成。

## 9. 复现与文件

| 文件 | 作用 |
|---|---|
| `host/src/h5_probe.c` | 探针主程序 |
| `host/scripts/extract_frame_payloads.py` | `.abc` → `frames.bin` + `index.tsv` |
| `host/scripts/capture_cmd_table.py` | live 命令表/BSS slot 只读捕获 |
| `host/scripts/summarize_h5_probe.py` | JSONL 汇总 |
| `host/scripts/run_h5_probe.sh` | 编译/抽取/推送/运行一条龙 |
| `host/fixtures/20261102_161129/consumer/cmd_table.bin` | 命令表 fixture |
| `host/fixtures/20261102_161129/consumer/cmd_table.json` | 捕获 manifest |
| `tests/test_h5_frame_payloads.py` | 抽取器回归 |

相关文档：`docs/cs_fifo_context.md`、`docs/context_transplant_a1.md`、
`docs/gamecore_host.md`、`docs/replay_record_stream.md`。

## 10. active context 结果（2026-11-04 晚）

H5 的“context 依赖”已补：active context `P=0x730fe87fcff0` +
`0x4FF8000/0x526F000/0x544C000` globals + slot1。结果：

- 1–200 帧 isolated/sequential 均 200/200 ok；
- 400–440 帧 41/41 ok，`0x39/0x3a/0x3b` 等均真实分派；
- `0x3a` 的空跳转表由 `0x544C000` 窗口修复；
- `0x39` seq 484 由 slot1 修复；
- context 每帧有 113–126 B 命令记录副作用，不等于 DS 状态。

详见 `docs/h5_active_context_slot0.md`。原 §8 第 1、2 条的 context/BSS
缺口已闭合；第 4 条（命令流语义）和“不是帧推进/状态输出”的界限仍成立。
