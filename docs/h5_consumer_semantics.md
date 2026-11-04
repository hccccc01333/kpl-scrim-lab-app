# H5 CS 消费者语义与验收（0x46B80E8）

- 日期：2026-11-03
- 范围：只读静态反汇编 + 既有进程快照；不注入、不登录、不调用游戏函数、不改游戏文件。
- 构建：`data/replays/_analysis/libGameCore.so`（KPL 5069040 / 客户端 12.1.1.8）。
- 相关输入：`host/src/gc_transplant.c`、`host/scripts/run_transplant.sh`、
  `data/replays/_analysis/client_probe_20261103/process_snapshot_2052/`、
  `docs/context_transplant_a1.md`、`docs/cs_fifo_context.md`、`docs/gamecore_init_chain.md`。
- 所有地址均为 **base-relative / 文件 VA**；运行期写 `base + 0x...`。

## 0. 结论先行

1. `0x46B80E8` 不是“读一条命令”的函数，而是两段式流水线：
   - `0x49CBC0C`：把 slot0 当前全部可读字节排空到 `[0x544CC40]` 指向的 **16 B buffer**；
   - `0x46B8070`：把 `[buf, buf+used)` 按 **4 B 命令头** 逐个分发给
     `[0x544D340]` 的 handler 表。
   函数 **无返回值**；成功与否只能靠调用前后的内存差分。
2. 字节级成功 = `slot0.read` 前进到 `slot0.committed`，`consumer.used = N`（本次排空字节数）；
   `slot0.write / committed / pending` 不被消费者修改。
   **`+0x24 pending` 不是 backlog**：`CommitCsBuffer` 从不清零 `+0x24`。
3. 命令级成功还要求 `[0x5272368] > 0` 且 `[0x544D340] != 0`。
   两者 BSS 初始为 0，宿主没有显式设置；在 libGameCore `.text` 的 adrp/add
   引用扫描中只找到读、未找到直接写者（不排除外部注册代码经 `.data` 地址表写入）。
   `count=0` 时 parser 读完第一个 4 B 头就返回，但 ring 字节已经被排空——
   这就是“consumer returned 但没有消费任何命令”的静默路径。
4. **当前 A1 H5 测试是空路径**：`gc_transplant` 在调用 consumer 前执行了
   `PushCsBuffer(0)` + `CommitCsBuffer()` + `ResetCsBuffer()`；`Reset` 把 slot0 的
   `+0x2c/+0x30/+0x34/+0x24` 全部清零，live 快照里的 8 B backlog 被丢弃。
   consumer 实际面对空 ring。该测试只证明“空 ring 下可调用不崩”。
5. 快照 consumer 对象 `0x75dc98daac10` 是 16 B buffer：
   `+0=0x75ddc9809ff0`、`+8 cap=0x40000`、`+0xc used=8`。
   `+0x10` 起是下一个分配/注册表项，**不是 consumer 字段**。
   它的 data 指针不在 27 个已捕 region 中；slot0 的 ring/staging 也不在。
   因此 `N>0` 的 push 会在写 staging 时踩未映射，`N>0` 的 consume 会在
   `memcpy` 处踩未映射。
6. `[0x544CBD0]` 不被 `0x46B80E8` 读取；它是 CoreThread 状态字，不是 H5 consumer
   的验收信号（详见 §7）。
7. 要证明“一帧被消费”，宿主至少要同时观测到：
   调用前 `N>0`、调用后 `slot0.read == committed`、`consumer.used == N`、
   以及 handler 调用/副作用。只看“函数返回”或只看某一个计数器都不够。

## 1. 地址与调用链

```text
0x46B80E8  cs_consumer()
  consumer = *(void**)(base + 0x544CC40)
  slot0    = *(void**)( *(void**)( *(void**)(base + 0x4FF5DE8) ) )
             // [0x4FF5DE8]=0x52488B8 -> [0x52488B8]=0x52C3250 -> [0x52C3250]=slot0
  0x49CBC0C(consumer, slot0)                            // drain ring -> consumer buffer
  0x46B8070(consumer->data, consumer->data + consumer->used)
```

静态物化值：

| 槽 | 静态值 | 说明 |
|---|---:|---|
| `[0x4FF5DE8]` | `0x52488B8` | CS 根槽 |
| `[0x52488B8]` | `0x52C3250` | 8 路槽表首地址 |
| `[0x52C3250]` | BSS 0 | slot0 对象指针 |
| `[0x525A768]` | `0x49CBC0C` | drain 函数 |
| `[0x522F068]` | `0x46B8070` | parser |
| `[0x522F070]` | `0x46B80E8` | consumer 本体（同时被 `0x46B8130` thunk 引用） |
| `[0x5272368]` | BSS 0 | parser opcode 上限/数量（u32） |
| `[0x544D340]` | BSS 0 | parser handler 表指针（qword） |
| `[0x544CC40]` | BSS 0 | consumer buffer 对象指针（qword） |
| `[0x544CBD0]` | BSS 0 | CoreThread 状态（u32），**不在本路径** |

`[0x522F068]`/`[0x522F070]`/`[0x525A768]` 都有 `R_AARCH64_RELATIVE` 重定位，
分别指向 `0x46B8070`/`0x46B80E8`/`0x49CBC0C`。

`0x522F050..0x522F0A8` 是相邻的一组 view/CS dispatch slot：
`0x522F068` parser、`0x522F070` consumer、`0x522F078/0x522F080` 两个 thunk、
`0x522F088` event sender。它们不是 8 路 FIFO 槽表（槽表是 `0x52C3250`）。

## 2. `0x46B80E8` 反汇编与语义

```asm
0x46b80e8  stp  x30, x19, [sp, #-0x10]!
0x46b80ec  adrp x8, #0x4ff5000
0x46b80f0  adrp x19,#0x544c000
0x46b80f4  adrp x9, #0x525a000
0x46b80f8  ldr  x8, [x8, #0xde8]      ; x8 = [0x4ff5de8] = 0x52488b8
0x46b80fc  ldr  x0, [x19,#0xc40]      ; x0 = [0x544cc40] = consumer
0x46b8100  ldr  x8, [x8]              ; x8 = [0x52488b8] = 0x52c3250
0x46b8104  ldr  x1, [x8]              ; x1 = slot0
0x46b8108  ldr  x8, [x9, #0x768]      ; x8 = [0x525a768] = 0x49cbc0c
0x46b810c  blr  x8                    ; 0x49cbc0c(consumer, slot0)
0x46b8110  ldr  x8, [x19,#0xc40]      ; consumer
0x46b8114  adrp x9, #0x522f000
0x46b8118  ldr  x0, [x8]              ; x0 = consumer->data (+0x00)
0x46b811c  ldr  w8, [x8, #0xc]        ; w8 = consumer->used (+0x0c)
0x46b8120  ldr  x2, [x9, #0x68]       ; x2 = [0x522f068] = 0x46b8070
0x46b8124  add  x1, x0, x8            ; x1 = data + used
0x46b8128  ldp  x30, x19, [sp], #0x10
0x46b812c  br   x2                    ; tailcall 0x46b8070(data, data+used)
```

语义：

```c
void cs_consumer(void) {                 // 0x46B80E8, no args, no return value
    Buf  *c = *(Buf**)(base + 0x544CC40);
    Ring *r = *(Ring**)( *(void**)(base + 0x4FF5DE8) );  // slot0
    buf_drain(c, r);                     // 0x49CBC0C
    cs_parse(c->data, c->data + c->used);// 0x46B8070
}
```

要点：

- 不读取 `[0x544CBD0]`。
- 不修改 `[0x544CC40]` 本身。
- 不返回状态；`x0` 在 tailcall 后由 parser/handler 决定，不可依赖。
- slot0 为空时仍然会调用 `buf_drain`（把 `used` 清 0）并调用 parser（范围为空，立即返回）。

## 3. `0x49CBC0C`：把 slot0 排空到 16 B buffer

对象布局（构造函数 `0x49CBB80` 证明对象大小 0x10）：

| 偏移 | 宽度 | 字段 | 读/写 |
|---:|---:|---|---|
| `+0x00` | 8 | data 指针 | drain 读；grow 写新指针并 free 旧指针 |
| `+0x08` | 4 | capacity | drain 读；grow 写新容量 |
| `+0x0c` | 4 | used / length | drain 入口写 0，随后累加；`0x46B80E8` 读 |

`0x49CBC0C` 伪代码：

```c
void buf_drain(Buf *c, Ring *r) {
    c->used = 0;                                  // 0x49cbc2c
    for (;;) {
        uint32_t n = ring_read(r, c->data, c->cap); // 0x49cc1a8
        c->used += n;
        if (c->used != c->cap) break;             // 0x49cbc4c
        buf_grow(c, c->cap * 2);                  // 0x49cbca4
    }
}
```

- `buf_grow`（`0x49CBCA4`）：`new(cap)` -> memcpy 旧 `used` 字节 -> free 旧指针 ->
  写 `+0x00`/`+0x08`。
- 循环终止条件不是“ring 空”，而是“buffer 未恰好填满”。由于每次 `ring_read`
  最多返回当前可读字节数 `available = committed - read`，最终会把 **全部**
  committed backlog 排空（除非扩容失败）。
- 如果 `cap == 0`，`used == cap` 永远成立，会无限 grow/read 循环；
  验收前必须保证 `cap > 0`。
- 排空后：`c->used = N = (u32)(committed - read)`（本次调用前的 backlog）。

旁证：`0x49C652C` 也是同一模式——它的 `+0` 是 ring、`+8` 是 16 B buffer，
先调 `0x49CBC0C(buf, ring)`，再用同样的 parser 循环。说明 `0x49CBC0C` 是
通用的“ring -> buffer”helper，不是某个特化命令读取器。

### 3.1 `0x49CC1A8` ring read

```c
uint32_t ring_read(Ring *r, void *dst, uint32_t req) {
    uint32_t avail = r->committed - r->read;       // +0x34 - +0x30, u32
    uint32_t n = min(avail, req);
    uint32_t off = r->read & (r->ring_size - 1);   // +0x30 & (+0x10 - 1)
    uint32_t n1 = min(n, r->ring_size - off);
    memcpy(dst, r->ring + off, n1);
    memcpy((char*)dst + n1, r->ring, n - n1);
    r->read += n;                                  // +0x30
    return n;
}
```

- `+0x24 pending` 不参与读；读只看 `+0x34 committed` 与 `+0x30 read`。
- `+0x30 read` 是累计字节游标（u32，可回绕），不是 ring 内偏移。
- 消费者不改 `+0x2c write`、`+0x34 committed`、`+0x24 pending`。

## 4. `0x46B8070`：4 B 命令头 parser

```asm
0x46b8070  sub  sp, sp, #0x30
0x46b8074  stp  x30, x21, [sp, #0x10]
0x46b8078  stp  x20, x19, [sp, #0x20]
0x46b807c  cmp  x0, x1
0x46b8080  str  x0, [sp, #8]
0x46b8084  b.hs 0x46b80d8              ; empty -> return
0x46b8088  mov  x19, x1                ; end
0x46b808c  adrp x20, #0x5272000
0x46b8090  adrp x21, #0x544d000
0x46b8094  ldr  w8, [x0], #4           ; word = *(u32*)p; p += 4
0x46b8098  ldr  w10,[x20,#0x368]       ; count = [0x5272368]
0x46b809c  str  x0, [sp, #8]
0x46b80a0  and  x9, x8, #0xffff        ; op = word & 0xffff
0x46b80a4  cmp  w9, w10
0x46b80a8  b.hs 0x46b80d8              ; op >= count -> return
0x46b80ac  lsl  x9, x9, #4             ; entry stride = 16
0x46b80b0  ldr  x10,[x21,#0x340]       ; table = [0x544d340]
0x46b80b4  tst  w8, #0x40000000        ; bit30
0x46b80b8  lsr  w2, w8, #0x10          ; payload = bits 16..31
0x46b80bc  cset w1, eq                 ; w1 = !bit30
0x46b80c0  add  x0, sp, #8             ; &cursor
0x46b80c4  ldr  x9, [x10, x9]          ; handler = table[op]
0x46b80c8  blr  x9
0x46b80cc  ldr  x0, [sp, #8]           ; p = cursor (handler may advance)
0x46b80d0  cmp  x0, x19
0x46b80d4  b.lo 0x46b8094
0x46b80d8  ... ret
```

命令头格式（本构建实测）：

```text
word (u32 LE):
  bits  0..15  opcode index
  bits 16..31  payload（完整 16 位，包含 bit30/31）
  bit   30     flag：w1 = (bit30 == 0) ? 1 : 0
handler = *(void**)(table + opcode * 16)
handler(&cursor, w1, payload)   // handler 可读/写 cursor，用于消费变长 payload
```

- table entry 大小 16 B；parser 只读 entry 的第一个 qword。
- `count` 是 `opcode < count` 的上界；不是命令条数，也不是 frame 数。
- 无返回值、无计数、无错误码；`op >= count` 时静默停止（不报错）。
- `count=0` 时：读完第一个 4 B 头就返回，**不调用任何 handler**。
- `count>0` 但 `table=0` 时：在 `ldr x9,[x10,x9]` 处踩空。

## 5. 成功消费到底改变什么

设调用前：

```text
R = slot0[+0x30]  read
W = slot0[+0x2c]  write
C = slot0[+0x34]  committed
P = slot0[+0x24]  pending
N = (u32)(C - R)  backlog
Cap = consumer[+0x08]
```

一次成功的非空调用后：

| 对象 | 字段 | 变化 | 说明 |
|---|---:|---|---|
| slot0 | `+0x30 read` | `R -> R + N`（u32） | 主证据；本次调用后 `read == committed` |
| slot0 | `+0x34 committed` | 不变 | 消费者不改生产水位 |
| slot0 | `+0x2c write` | 不变 | 同上 |
| slot0 | `+0x24 pending` | 不变 | **不要期望它变 0** |
| consumer | `+0x00 data` | 通常不变；`N > Cap` 时 grow 后可能变 | grow 会 free 旧指针 |
| consumer | `+0x08 capacity` | 通常不变；`N > Cap` 时按 2 的幂增长 | 可能大于 N |
| consumer | `+0x0c used` | 旧值 -> `N` | 本次排空字节数；空 ring 时为 0 |
| `[0x544CC40]` | qword | 不变 | 仍是同一个 buffer 对象 |
| `[0x544CBD0]` | u32 | 不变 | 不在本路径 |
| handler 状态 | — | handler 自定义 | 只能由 handler 副作用观测 |

`N=0` 时：`read` 不变、`used` 被清 0、parser 范围为空、handler 0 次调用。
“函数返回”本身不证明任何消费。

以上等式假设宿主**串行化** Push/Commit 与 consumer；若并发，`committed` 可能在
drain 过程中前进，`N` 不再是单一快照值。`docs/cs_fifo_context.md` 已要求宿主
自己串行化，验收时必须遵守。

另外，调用前必须保证 `read` 与 `committed` 是同一代游标（通常
`read <= committed`）。如果 `read > committed`（Reset 后手工写、回绕、
快照拼接），`(u32)(committed - read)` 会变成巨大值，consumer 会尝试读满
ring/buffer；这不是合法 backlog。

返回后的状态（本函数可保证的部分）：

```text
slot0[+0x30]      = 调用前 read + 本次排空字节数（通常到 committed）
consumer[+0x0c]   = 本次排空字节数（空 ring 时为 0）
slot0[+0x2c/+0x34/+0x24]、[0x544CC40]、[0x544CBD0] 均不变
其它变化只可能来自 parser handler 的副作用
```

函数本身不推进帧号、不清 pending、不写 `[0x544CC40]`、不写 CoreThread 状态。

## 6. 快照实测（process_snapshot_2052）

### 6.1 slot0 对象 `0x75D7E7FE70FC`

| 偏移 | 值 | 含义 | 是否已捕 |
|---:|---:|---|---|
| `+0x00` | `0x75DB20CA8608` | vtable | 是（`0x75db20c98000-0x75db21029000`） |
| `+0x08` | `0x75DCFBD22FE0` | ring base | **否** |
| `+0x10` | `0x00010000` | ring size = 65536 | 是（对象内） |
| `+0x18` | `0x75DCC8ECE100` | staging | **否** |
| `+0x20` | `0x00008000` | staging cap = 32768 | 是 |
| `+0x24` | `0x00000008` | pending（最后一次 Push 长度） | 是 |
| `+0x28` | `0` | reset/flag | 是 |
| `+0x2C` | `0x00124910` | write cursor | 是 |
| `+0x30` | `0x00124908` | read cursor | 是 |
| `+0x34` | `0x00124910` | committed | 是 |
| `+0x38` | `1` | arg/channel | 是 |
| `+0x78` | `0x40003AFF7324` | alloc = base+`0x45F7324` | 是 |
| `+0x80` | `0x40003AFF7334` | free = base+`0x45F7334` | 是 |

关键计算：

```text
backlog = committed - read = 0x00124910 - 0x00124908 = 8
ring index = read & (0x10000 - 1) = 0x124908 & 0xffff = 0x4908
pending 8 B address = 0x75DCFBD22FE0 + 0x4908 = 0x75DCFBD278E8
（+8 未越过 ring 末尾，不 wrap）
```

即：快照里 **确实有 8 B 未消费的 CS 字节**，位于 `0x75DCFBD278E8`；
但该 ring mapping 没有被捕获。`pending=8` 与 backlog=8 只是同一帧长度的重合，
不能把 `pending` 当 backlog 的通用判据。

### 6.2 consumer buffer 对象 `0x75DC98DAAC10`

| 偏移 | 值 | 含义 | 置信度 |
|---:|---:|---|---|
| `+0x00` | `0x000075DDC9809FF0` | data 指针 | 高（字段）；**该地址未捕** |
| `+0x08` | `0x00040000` | capacity = 262144 | 高 |
| `+0x0C` | `0x00000008` | used = 8 | 高 |
| `+0x10` | `0x142500000000D101` | 下一个分配/注册表项，**不是对象字段** | 中-高 |
| `+0x18` | `0` | 同上 | 中-高 |
| `+0x20` | ASCII `"IntMatrix4x4"` | 相邻注册表名字 | 中-高 |

对象大小 16 B 的依据：构造函数 `0x49CBB80` 明确按 0x10 字节初始化
`{data, cap, used}`，且 `0x49CBC0C` 只访问 `+0x00/+0x08/+0x0c`。
`0x75DC98DAAC10 + 0x10` 已经落在相邻的 0x20 步长注册表项上，
当前 `gc_transplant` 打印 `+0x10/+0x18` 是越界读，不是 consumer 字段。

相邻同型 buffer 描述符（同一 region）：

| 描述符 | data | cap | used |
|---|---:|---:|---:|
| `0x75DC98DAAA70` | `0x75DDCDA95FF0` | `0x40000` | 0 |
| `0x75DC98DAAEF0` | `0x75DDC9D20FF0` | `0x40000` | 0 |
| `0x75DC98DAAC10` | `0x75DDC9809FF0` | `0x40000` | 8 |

这更像一组 0x40000 B 的 buffer 描述符/注册表；`0x75DC98DAAC10` 是其中
`used=8` 的活跃项。结论：consumer 对象布局高置信；它是否仍是 live 时刻的
同一对象为中-高（consumer region 文件 mtime 22:12 晚于其他 region 21:50；
`meta.captured_at` 仍是 21:51:36，说明该 region 是后补的）。

consumer 对象本身**没有** command queue / frame counter / 命令计数器字段；
它只有 `{data, cap, used}`。相邻的 0x20 步长表是注册表/描述符表，不是
命令队列；`+0x10` 之后的任何值都不应计入 consumer 状态。

### 6.3 region 覆盖检查

| 地址 | 用途 | 是否在 27 个 region 内 |
|---|---:|---|
| `0x75DC98DAAC10` | consumer 对象 | 是（`0x75dc98d88000-0x75dc99108000`） |
| `0x75DDC9809FF0` | consumer data | **否** |
| `0x75DCFBD22FE0` | slot0 ring | **否** |
| `0x75DCFBD278E8` | 当前 8 B backlog | **否** |
| `0x75DCC8ECE100` | slot0 staging | **否** |

因此当前 A1 宿主只能安全执行 `N=0` 的路径；非空 push 会在写 staging 时踩
未映射地址，非空 consume 会在 `0x49CC1A8` 的 `memcpy`（`0x4B405C0`）处
读写未映射地址。

### 6.4 当前 A1 H5 序列为什么是空路径

`host/src/gc_transplant.c` 的顺序（行号近似）：

```c
push(0);                    // 0x49CBF98: pending = 0
commit();                   // pending=0 -> committed = write; no memcpy
reset();                    // 0x49CC18C: +0x2c=+0x30=+0x34=+0x24=0, +0x28=1
*(base+0x544CC40) = consumer;
*(base+0x544CBD0) = core_state;
consumer_0x46B80E8();       // ring 已被 Reset 清空
```

后果：

- live 快照的 8 B backlog 被 `ResetCsBuffer` 丢弃；
- `PushCsBuffer(0)` 把 `pending` 从 8 改成 0；
- consumer 看到 `read == committed == 0`，排空 0 B，`used=0`，parser 空转；
- 当前日志没有打印 consumer `+0x0c used`，所以连“used=0”都没有被观测；
- “CS consumer returned” 只证明 **空 ring 下可进入并返回**。

`docs/context_transplant_a1.md` §7 的“当前 slot0 pending 为 0”应读作
“宿主 Push(0) 之后 pending 为 0”，不是 live 快照的值。

## 7. H5 验收信号表

分级：

- **L0**：consumer 可调用、不崩（当前 A1 已达到）。
- **L1**：字节级排空（ring -> consumer buffer）。
- **L2**：命令级分发（handler 被调用）。
- **L3**：帧级语义（帧号/游戏状态推进）。

| ID | 观测点 | 通过条件 | 证明 | A1 现状 | 置信度 |
|---|---|---|---|---|---|
| P0 | `[base+0x544CC40]` | 非 0，指向已映射的 16 B 对象；`+8 cap>0` | consumer 前置条件 | PASS（`0x75dc98daac10` 已映射） | 高 |
| P1 | slot0 对象 | 非 0；`+0x10` 为 2 的幂且 >0；`+0x30/+0x34` 可读 | ring 前置条件 | PASS（对象已映射） | 高 |
| P2 | data 映射 | consumer `+0x00`、slot0 `+0x08/+0x18` 指向已映射内存 | 非空路径可执行 | **FAIL**（三处均未捕） | 高 |
| L1-1 | `slot0[+0x34] - slot0[+0x30]` | 调用前 `N > 0` | 有真实 backlog | **FAIL**（Reset 清零） | 高 |
| L1-2 | `slot0[+0x30]` | 调用后 `read == committed`（u32） | ring 已排空 | **FAIL** | 高 |
| L1-3 | `consumer[+0x0c]` | 调用后 `used == N` | 字节已拷入 buffer | **未观测**（日志未打印） | 高 |
| L1-4 | `consumer[+0x00]` | 前 N 字节等于 ring 中 backlog 字节 | 数据一致，不是仅游标前进 | **FAIL**（data 未捕） | 高 |
| L1-5 | `slot0[+0x2c/+0x34/+0x24]`、`[0x544CC40]` | 调用前后不变 | 消费者不越权修改生产侧 | N/A（N=0） | 高 |
| L2-1 | `[base+0x5272368]` | `> 0` | parser 有 opcode 上界 | **未验证**（宿主未设置；BSS 初值 0） | 中-高 |
| L2-2 | `[base+0x544D340]` | 非 0，且 `table[0..count)` 可读 | handler 表可用 | **未验证**（宿主未设置；BSS 初值 0） | 中-高 |
| L2-3 | host 包裹的 handler 计数 | 每个 4 B 头恰好 1 次回调；w1/w2 与 header 一致 | 命令级分发 | **未验证**（需 E1） | 高（需 E1） |
| L2-4 | 真实 handler 副作用 | 具体游戏状态/事件变化 | 命令语义正确 | **不可达** | 中 |
| L3-1 | 帧号/上下文状态 | 单调推进/符合 `.abc` 预期 | 帧级消费 | **不可达** | 低 |
| C1 | `[base+0x544CBD0]` u32 | 若走 CoreThread：2=跑一帧，3=退出 | CoreThread 状态 | 非本路径；consumer 前后不变 | 高（排除） |
| C2 | 输出/事件队列计数 | 本路径没有通用计数器 | — | 不存在 | 高 |

补充说明：

- **`pending` 不能作为验收信号**：`CommitCsBuffer` 不写 `+0x24`；
  快照 `pending=8`、backlog=8 只是巧合。判 backlog 必须用
  `committed - read`。
- **`[0x544CBD0]` 不能作为 consumer 验收信号**：`0x46B80E8` 的指令里没有
  该地址；读取它的只有 `0x46B7898/0x46B7B64/0x46B7C48/...`（CoreThread）
  与 `0x4882C10` 主循环。live `0x400000000002` 的低 u32 是 2；
  它只在“H5 走 CoreThread tick”时才有意义，而 5v5 并不走 CoreThread。
- **输出/事件队列**：`0x46B8070` 没有计数器；只有具体 handler 才可能调用
  `0x46B8148`/`0x406B178` 事件路径。不能把某个 context 队列当作通用验收点。

## 8. 当前 H5 判定

| 结论 | 状态 |
|---|---|
| 宿主可进入 `0x46B80E8` 并返回 | ✅ 已验证（A1） |
| 非空 ring 的字节排空 | ❌ 未验证（Reset + 未捕 data） |
| consumer `used` 变化 | ❌ 未观测 |
| parser handler 分发 | ❌ 未验证（宿主未设置 handler 表） |
| 帧推进 | ❌ 不可达 |
| `[0x544CBD0]` 参与 consumer | ❌ 静态否定 |

因此当前只能记为 **H5-L0（可调用/空路径）**，不能记为“consumer 已打通”或
“帧已消费”。`docs/context_transplant_a1.md` §7 的措辞应按此降级。

## 9. 最小下一步宿主实验（E1，合成数据）

目标：在不依赖任何未捕 mapping、不伪造真实命令语义的前提下，证明
`Push -> Commit -> 0x46B80E8 -> 0x49CBC0C -> 0x46B8070 -> handler`
整条链路。只在临时测试宿主中执行，不提交生产代码改动，不碰设备。

构建临时宿主（不要提交临时源）：

```bash
SRC=/path/to/tmp_gc_transplant.c OUT_BIN=host/build/gc_transplant \
  bash host/scripts/build_host.sh
```

### 9.1 准备

1. 按现有 A1 方式映射快照并调用 `ModuleInit`，得到 `base`（`new_base`）。
2. 不用 live slot0/consumer（它们的 data 未捕），改为宿主自建：
   - `ring_obj = malloc(0x90)`；
   - 调用真实 ctor `base+0x49CBD88(ring_obj)`；
   - 调用真实 init `base+0x49CBEEC(ring_obj, 0x1000, 0, 0, 0)`；
     init 会自己分配 ring（0x1000）和 staging（0x800）；
   - `*(void**)(base+0x52C3250) = ring_obj`。
3. `buf_obj = malloc(0x10)`；`buf_data = malloc(0x1000)`；
   `*(void**)(buf_obj+0x00) = buf_data`；
   `*(uint32_t*)(buf_obj+0x08) = 0x1000`；
   `*(uint32_t*)(buf_obj+0x0c) = 0`；
   `*(void**)(base+0x544CC40) = buf_obj`。
4. `handler_table = malloc(0x10)`；`handler_table[0]=stub`；
   `handler_table[1]=0`；
   `*(uint64_t*)(base+0x544D340)=handler_table`；
   `*(uint32_t*)(base+0x5272368)=1`。
5. `stub(uint64_t *cursor, uint32_t w1, uint32_t w2)` 只记录
   `calls++`、`last_w1=w1`、`last_w2=w2`，不修改 `*cursor`。

### 9.2 推一条合成命令

```c
uint32_t *p = PushCsBuffer(4);   // 真实导出；返回 staging
*p = 0x00000000;                 // opcode=0, payload=0, bit30=0
CommitCsBuffer();
```

`0x00000000` 是结构性测试字，不是游戏命令；它只验证 header 解析和
handler 分发，不验证任何游戏语义。

### 9.3 观测

调用前：

```text
ring_obj[+0x2c] write      = 4
ring_obj[+0x30] read       = 0
ring_obj[+0x34] committed  = 4
ring_obj[+0x24] pending    = 4
buf_obj[+0x0c] used        = 0
```

调用 `base+0x46B80E8()` 后：

| 观测点 | 期望 |
|---|---|
| `ring_obj[+0x30]` | `4` |
| `ring_obj[+0x34]` | `4`（不变） |
| `ring_obj[+0x2c]` | `4`（不变） |
| `ring_obj[+0x24]` | `4`（**不是 0**） |
| `buf_obj[+0x0c]` | `4` |
| `buf_data[0..4)` | `00 00 00 00` |
| `buf_obj[+0x00]` | 仍等于 `buf_data`（未 grow） |
| `handler_calls` | `1` |
| `last_w1` | `1`（bit30=0） |
| `last_w2` | `0` |
| `[base+0x544CC40]` | 不变 |
| `[base+0x544CBD0]` | 不变 |

通过条件：上表全部满足，且无 SIGSEGV/abort、无 malloc 失败。

### 9.4 负对照

- `count=0`：同样 push/commit，但 `[0x5272368]=0`。
  期望 `ring_obj[+0x30]=4`、`buf_obj[+0x0c]=4`、`handler_calls=0`。
  这直接证明“字节已排空但命令未分派”的静默路径。
- **不要**在 consumer 前调用 `ResetCsBuffer()`；否则 ring 清空，实验退化为 L0。
- **不要**让 `buf_obj[+8] cap=0`；会导致 `used==cap` 的死循环。
- **不要**让 `count>0` 而 table 为 0；会在 parser 里踩空。

### 9.5 E1 不能证明什么

- 不能证明 live consumer 对象/数据一致；
- 不能证明真实 `.abc`/TDR 命令格式；
- 不能证明 handler 语义或帧推进；
- 不能证明 143 条 opcode 表的真实内容。

## 10. 保真度后续（E2，只读采集）

E1 通过后，最小保真实验是补齐三处未捕 mapping 和 handler 表：

1. 用 `/proc/<pid>/maps` 找到包含以下地址的完整 region：
   - `0x75DCFBD22FE0`（slot0 ring，至少 0x10000 B）；
   - `0x75DCC8ECE100`（slot0 staging，至少 0x8000 B）；
   - `0x75DDC9809FF0`（consumer data，至少 0x40000 B）。
2. 只读读取 `0x75DCFBD278E8` 的 8 B（当前 backlog）和
   `0x75DDC9809FF0` 的 `used` 字节（consumer buffer 当前内容）。
3. 只读读取 `base+0x5272368`、`base+0x544D340`；
   若非零，dump `count * 16` B 的 handler 表并按 `new_base - old_base` 重定位
   其中的 libGameCore 代码指针。指向 il2cpp/其他库的 entry 需要额外映射，
   否则只能部分分发——这一点必须先统计，不能假设全部可调用。
4. 用 live slot0/consumer 重跑：**不 Push(0)、不 Reset**；
   直接调用 `0x46B80E8`。
   以现场读数为准；若仍接近快照值，期望：
   `read 0x124908 -> 0x124910`、`used=8`、consumer 前 8 B 等于
   ring `+0x4908` 的 8 B；若 handler 表已捕且 count>0，再观测 handler 调用。

E2 比 E1 大，且需要设备只读访问；它才是“live 8 B 帧命令被消费”的证明。
在 E2 完成前，不应声称 H5 已消费真实帧。

## 11. 置信度与未决

高置信：

- `0x46B80E8` 的两段式语义、无返回值、只读 `[0x544CC40]`；
- consumer 对象 16 B 布局 `{+0 data, +8 cap, +0xc used}`；
- `+0x24 pending` 不是 backlog，Commit/read 都不清零它；
- `[0x5272368]`/`[0x544D340]` 是 parser 分发前置条件；BSS 初值 0，宿主未设置；
- `[0x544CBD0]` 不在 consumer 路径；
- 快照 slot0 backlog=8、consumer used=8、三处 data mapping 未捕。

中-高置信：

- `0x75DC98DAAC10` 是 live consumer 对象（布局吻合、值合理；但 region 采集
  时间晚于主快照）；
- 相邻 0x20 步长表是注册表/描述符表，不是命令队列；
- `[0x5272368]` 的 live 值可能与 143 条 `FRAME_CMD_INFO` 有关，但未读取验证。

未决：

- live `[0x5272368]`、`[0x544D340]` 的真实值；
- 谁写 `[0x544CC40]`、`[0x544D340]`（libGameCore `.text` 的 adrp/add 扫描
  未见直接写者；`.data` 地址表 `0x507E018`/`0x507C7B0` 分别持有它们的地址，
  可能由外部注册代码写）；
- handler 表 entry 的第二 qword 语义；
- 4 B 头与 TDR `FRAME_CMD_INFO`/`.abc` 线格式的精确对应；
- 帧边界：slot0 是字节流，没有 frame 分隔；帧级推进只能由 handler 副作用证明。

## 附录 A：复现命令

```bash
python tools/gc_export_map.py --check
python tools/gc_export_map.py --symbol PushCsBuffer --symbol CommitCsBuffer --symbol ResetCsBuffer
```

反汇编三个目标（只读）：

```python
import sys
from pathlib import Path
sys.path.insert(0, "tools")
from gc_export_map import Core

c = Core(Path("data/replays/_analysis/libGameCore.so"))
for start, n in [(0x46B80E8, 0x48), (0x49CBC0C, 0x98), (0x46B8070, 0x78)]:
    print("==", hex(start))
    for i in c.dis(start, n):
        print(f"{i.address:#x}: {i.mnemonic} {i.op_str}")
```

## 附录 B：地址速查

| 名称 | base-relative |
|---|---:|
| CS consumer | `0x46B80E8` |
| drain ring -> buffer | `0x49CBC0C` |
| parser | `0x46B8070` |
| ring read | `0x49CC1A8` |
| buffer grow | `0x49CBCA4` |
| buffer ctor (0x10 B) | `0x49CBB80` |
| ring ctor | `0x49CBD88` |
| ring init | `0x49CBEEC` |
| ring reset | `0x49CC18C` |
| PushCsBuffer | `0x460A3AC -> 0x49CBF98` |
| CommitCsBuffer | `0x460A3E4 -> vtable+0x10 (0x49CBFFC)` |
| ResetCsBuffer | `0x460A40C -> 0x49CC18C` |
| consumer slot | `0x544CC40` |
| handler table | `0x544D340` |
| opcode count | `0x5272368` |
| CoreThread state | `0x544CBD0` |
| CS root slot | `0x4FF5DE8 -> 0x52488B8 -> 0x52C3250` |
| drain fn slot | `0x525A768` |
| parser slot | `0x522F068` |
| consumer slot (vtable) | `0x522F070` |

## 实测补充（2026-11-03，H5 E1 已通过）

真实 ring init 入口应是 **`0x49CBEEC`**；`0x49CBEEC` 是序言后 +8，调用会跳过
`stp x30` 保存并在尾调后返回 0。

H5 E1 实际结果：

```text
ring init done
ring vtable=base+0x4FD16F8 cap=2048 pending=0
pushed 4 bytes header=00000000 slot0 pending=4 cursors=4/0/4
handler called op=1 arg=0 total=1
after consumer: handler_calls=1 used=4 data=00000000
cursors=4/4/4
```

证明：

- consumer 确实把 slot0 committed 字节 drain 到 `[0x544CC40]` 的 buffer；
- `0x46B8070` 按 4B header 分派，host handler 被调用；
- read cursor 前进到 committed，未消费字节为 0。

仍未证明：真实 TDR 初始化命令的 opcode/body 映射。下一步要把 `.abc` 初始化头
包装成真实 `len|op` 记录，而不是继续用 0 header。

## 真实 `.abc` 帧探针（2026-11-03）

用 `host/build/frames/20261102_161129` + live `cmd_table.bin` 跑 3 帧：

```text
frame 0: bytes=1  opcode=0   handler=0        consumer drained=1  ok
frame 1: bytes=1  opcode=0   handler=0        consumer drained=1  ok
frame 2: bytes=169 opcode=280 arg=60930 handler=0x4707d64
         consumer exit=139  crash_pc=0x46bfe64  stage=3
```

结论：

- host 能把真实 `.abc` frame payload 推进 slot0，consumer 能 drain 1 字节帧；
- 但 `.abc` payload 是 `CSDT_FRAPBOOT_INFO` 容器，不是 native CS `len|op` 流；
- 第三帧按 low16=280 分派到真实 handler 后崩溃，证明直接 push 不可行；
- H5 仍缺 C#/GameBuilder/TDR 包装层；不能把 frame payload 当 CS 命令。
