# GameCore CS FIFO 对象/上下文布局与宿主安装（5069040 / 12.1.1.8，只读静态复核）

日期：2026-11-03。构建：KPL 5069040 / 客户端 12.1.1.8 的
`data/replays/_analysis/libGameCore.so`（86,426,392 B）。

范围与边界：

- 只做**静态反汇编** + 既有只读快照（`host/fixtures/20261102_161129/context/context_snapshot.json`）；
  不启动游戏、不注入、不 attach、不写游戏进程、不改任何游戏文件。
- 所有地址都是 **file offset / base-relative offset**。运行期必须写成 `base + 0x...`；
  快照里的 `0x40003...`、`0x75d7...` 只作布局证据，不能当常量。
- 仅对上述构建成立。换构建先用 `python tools/gc_export_map.py --check` 复核。

结论先行：

1. `PushCsBuffer` 真正操作的是 `base+0x52c3250` 开始的**8 路指针槽位表**
   （静态地址槽直接覆盖 0-5；不是 8 个相同的 CS FIFO）。Push/Commit/Reset 只取
   **slot 0**；slot 1 是 Cpp pack 通道；slot 2/3 也被按 ring 读取；slot 4/5 由
   上下文绑定；slot 6/7 静态无地址槽，快照内容也不是 ring。完整映射见 §1.2。
2. 每个 ring 对象 0x90 B：`+0x08` 环形区、`+0x10` 环形区大小、`+0x18` 暂存区、
   `+0x20` 暂存容量、`+0x24` pending 长度、`+0x2c/30/34` 三个 32 位累计字节游标、
   `+0x3c` pthread_rwlock_t、`+0x78/80` malloc/free 回调、`+0x00` vtable。
3. `0x6C`（108 B）**不在** `PushCsBuffer` 里。它是相邻的另一个类——一个
   108 B 多态记录的 SBO vector；`0x7fff` 位域是该 vector 的 count/capacity/mode，
   不是 CS 字节流的 head/tail。快照 pending 8/76 B 也不是 108 的倍数，见 §4。
4. 宿主可以安装一个**完全真实的最小 FIFO**（真实 ctor + 真实 init + 真实 vtable +
   真实 malloc/free），但**不能手搓一个最小 context**；context 只能来自真实运行实例，
   binder `0x43d301c` 只能把真实 context 的槽位绑到全局，不能创建 context，见 §6/§7。
5. `CommitCsBuffer` 在检查 pending 之前就做 `vtable+0x10` 虚调用。即使 pending=0，
   vtable 也不能为空。`_host/gc_fifo0.c` 的 calloc 假对象在 Commit 处会踩空，见 §7。

---

## 1. 地址链、槽位表与 API 取对象方式

### 1.1 全局链

静态 RELA（`R_AARCH64_RELATIVE`）物化后的链：

```text
[base+0x4ff5de8] = base+0x52488b8        ; 第一跳（PushCsBuffer 用的根槽）
[base+0x52488b8] = base+0x52c3250        ; 第二跳：指向槽位表首地址
slot0 = *(void**)(base+0x52c3250)        ; 真正的 CS ring 对象
```

`base+0x52c3250` 是 BSS 里的指针表（按 8 路口径为 8 个 qword / 0x40 B），零初始化。
它不是堆数组，也不是对象；只是通道指针。静态地址槽只直接覆盖 slot0-5；
slot6/7 没有找到地址槽，只能按快照/表长推断。

快照里的对应值（仅证据）：

```text
0x4ff5de8 -> 0x40003bc488b8   (= base+0x52488b8)
0x52488b8 -> 0x40003bcc3250   (= base+0x52c3250)
0x52c3250 -> 0x75d7e7fe70fc   (slot0 对象)
```

### 1.2 8 路槽位表：不是 8 个 CS FIFO

静态能证明的槽位地址与绑定来源：

| slot | 槽位地址 | 地址槽（全局） | 谁写/谁读 | 说明 |
|---:|---:|---:|---|---|
| 0 | `base+0x52c3250` | `[0x4ff5de8] -> 0x52488b8 -> 0x52c3250` | Push/Commit/Reset 只读它；binder 写 `ctx+0x80` | **CS 输入** |
| 1 | `base+0x52c3258` | `[0x4ff57c8] -> 0x52488c0 -> 0x52c3258` | binder 写 `ctx+0x88`；`PopFifoCppPackBuffer` 读它 | Cpp pack 通道（同为 ring 类） |
| 2 | `base+0x52c3260` | `[0x4ff5de0] -> 0x52486a0 -> 0x52c3260` | 内部函数 `0x460a180` 按 ring 读 `+0x10` | 其他 ring 通道 |
| 3 | `base+0x52c3268` | `[0x4ff5e70] -> 0x52486a8 -> 0x52c3268` | 内部函数 `0x460a180` 按 ring 读 `+0x10` | 其他通道；快照对象不像 ring |
| 4 | `base+0x52c3270` | `[0x4ff5dc0] -> 0x52488c8 -> 0x52c3270` | binder 写 `&ctx[0x4f0]` | 上下文内嵌对象，类型未定 |
| 5 | `base+0x52c3278` | `[0x4ff5df0] -> 0x52488d0 -> 0x52c3278` | binder 写 `&ctx[0x578]` | 上下文内嵌对象，类型未定 |
| 6 | `base+0x52c3280` | 未找到静态地址槽 | 未知 | 快照对象 vtable 不同，非 ring 证据 |
| 7 | `base+0x52c3288` | 未找到静态地址槽 | 未知 | 同上 |

要点：

- **只有 slot0 是 CS 帧命令输入**。Push/Commit/Reset 的实现里阵列下标恒为 0，
  不会遍历 8 路。
- `PopFifoCppPackBuffer`（导出，`0x460a434`）走 slot1：它读
  `[0x4ff57c8]=0x52488c0 -> [0x52488c0]=0x52c3258 -> [0x52c3258]=slot1`，
  然后直接调 ring read `0x49cc1a8`。不要把它当成读 slot0。
- 8 路表是**异构通道表**，不是 8 个同构 CS FIFO。宿主只应安装 slot0；
  其余槽位保持 BSS 零或真实对象。

### 1.3 三个导出的取对象方式

| API | 桩 | 实现 | 取对象 | 调用目标 |
|---|---:|---:|---|---|
| `PushCsBuffer(size)` | 0x460a3cc | 0x460a3ac | `[0x4ff5de8] -> [0x52488b8] -> [0x52c3250]` | 尾调 `0x49cbf98(obj,w1=size)` |
| `CommitCsBuffer()` | 0x460a400 | 0x460a3e4 | `[0x52488b8] -> [0x52c3250]` | `obj->vtable+0x10`（虚调用） |
| `ResetCsBuffer()` | 0x460a428 | 0x460a40c | 同上 | 尾调 `0x49cc18c(obj)` |

关键反汇编（取对象部分）：

```asm
; PushCsBuffer impl 0x460a3ac
adrp x8, #0x4ff5000
ldr  x8, [x8, #0xde8]      ; x8 = [0x4ff5de8] = 0x52488b8
ldr  x2, [x9, #0x798]      ; x2 = 0x49cbf98
ldr  x8, [x8]              ; x8 = [0x52488b8] = 0x52c3250
ldr  x0, [x8]              ; x0 = slot0
br   x2

; CommitCsBuffer impl 0x460a3e4
adrp x8, #0x5248000
add  x8, x8, #0x8b8        ; x8 = 0x52488b8
ldr  x8, [x8]              ; x8 = 0x52c3250
ldr  x0, [x8]              ; x0 = slot0
ldr  x8, [x0]              ; x8 = vtable（obj 不可为 0）
ldr  x1, [x8, #0x10]       ; vtable+0x10
br   x1
```

---

## 2. 单个 ring 对象布局（0x90 B）

字段宽度与语义全部来自实际指令（`ldr w` = 32 位，`ldr x/str x` = 64 位，
`ldrb/strb` = 8 位）：

| 偏移 | 大小 | 类型/宽度 | 字段 | 语义 | 证据 |
|---:|---:|---|---|---|---|
| +0x00 | 8 | `void*` (64) | vtable | 类虚表；Commit 走 `+0x10` | ctor `0x49cbd88` 写 `base+0x4fd16f8`；Commit `0x460a3e4` |
| +0x08 | 8 | `void*` (64) | ring base | 环形区基址 | ctor 清 0；init `0x49cbeec` malloc；commit/read/grow 使用 |
| +0x10 | 4 | `u32` | ring size | 环形区字节数，必须是 2 的幂 | init 写；commit `(size-1)&cursor`；grow 更新 |
| +0x14 | 4 | — | padding | 未访问 | — |
| +0x18 | 8 | `void*` (64) | staging | 暂存区基址（Push 返回它） | Push `0x49cbf98` 返回 `+0x18`；Commit 从这里拷出 |
| +0x20 | 4 | `u32` | staging cap | 暂存区容量 | Push 比较/更新；init 分配 |
| +0x24 | 4 | `u32` | pending length | 本帧待提交字节数（不是累计） | Push 写入；Commit 读取；Reset 清 0 |
| +0x28 | 1 | `u8` | reset/flag | Reset 置 1；访问器 `0x49cc2f8` 读后清零 | `0x49cc18c` / `0x49cc2f8` |
| +0x29 | 3 | — | padding | — | — |
| +0x2c | 4 | `u32` | write cursor | 生产侧累计写入字节数 | Commit `+0x2c += pending` |
| +0x30 | 4 | `u32` | read cursor | 消费侧累计读出字节数 | read `0x49cc1a8` 前进 |
| +0x34 | 4 | `u32` | committed | 已提交水位（每次 Commit 后 = write） | Commit 末尾；read 用 `+0x34-+0x30` |
| +0x38 | 4 | `u32` | arg/channel | init 的第二个参数（w2），Push/Commit 不用 | init `0x49cbeec` 写 |
| +0x3c | 0x38 | `pthread_rwlock_t` | 读写锁 | 仅 grow 与 read 使用 | `pthread_rwlock_init/destroy/rdlock/wrlock/unlock` PLT |
| +0x74 | 4 | — | padding | — | bionic LP64 rwlock = int32_t[14] |
| +0x78 | 8 | `void*` (64) | alloc callback | 分配器；默认 `base+0x45f7324` -> malloc | Push realloc 路径、grow、init |
| +0x80 | 8 | `void*` (64) | free callback | 释放器；默认 `base+0x45f7334` -> free | Push realloc 路径、grow、dtor |
| +0x88 | 8 | — | 未访问/对齐 | Push/Commit/Reset/Read 均不访问；对象按 0x90 分配 | 快照对象恰为 0x90 间隔 |

### 2.1 哪些是 32 位、哪些是 64 位、哪些是计数器

- 64 位指针：`+0x00` vtable、`+0x08` ring、`+0x18` staging、`+0x78` alloc、`+0x80` free。
- 32 位：`+0x10` ring size、`+0x20` staging cap、`+0x24` pending、`+0x2c/+0x30/+0x34`
  三个游标、`+0x38` arg。
- 8 位：`+0x28` flag。
- `+0x3c` 是 **pthread_rwlock_t**，不是 mutex。bionic LP64 下为 56 B（`int32_t[14]`），
  所以 `+0x3c..+0x73`，`+0x74..+0x77` 对齐，`+0x78` 是 alloc。
- 计数器语义：
  - `+0x24` 是**本帧 pending 长度**，不累计，Commit 不清零。
  - `+0x2c/+0x30/+0x34` 是**累计字节游标**（u32，可回绕），不是缓冲内偏移；
    所以它们可以远大于 `+0x10/+0x20`。快照 slot0 的 2,694,944 和 slot1 的
    25,114,468 都大于容量，正是累计值。
  - `+0x10/+0x20` 是容量，不是计数器。

### 2.2 与 View FIFO 的互相印证

`docs/gamecore_view_buffer.md` 的 view subobject 实测：`+0x10=4096`、
`+0x20=2048`、`+0x24=pending`、`+0x18` data、`+0x2c/30/34` 游标、
`+0x78/80` alloc/free。这与本节布局逐项一致；且 `2048 = 4096/2` 正好符合
init 的 `staging_cap = max(ring_size/2, 0x20)`。说明 CS 与 View 共用同一个
ring 布局（同一类族），只是 vtable/用途不同。

### 2.3 0x90 对象尺寸与构造/初始化

- 最小真实构造/初始化：
  - `0x49cbd88(obj)`：基础 ctor。设置 vtable `base+0x4fd16f8`，清零
    `+0x08/+0x18/+0x24/+0x28/+0x2c/+0x30/+0x34`，`pthread_rwlock_init(+0x3c)`，
    清零 `+0x78/+0x80`，做一次 vtable 范围检查 `0x21b04ec`。
  - `0x49cbeec(obj, ring_size, arg, alloc, free)`：基础 init。写 `+0x38=arg`；
    若 `alloc/free` 为 0 则用默认 `0x45f7324/0x45f7334`（malloc/free）；
    ring_size 非 2 的幂时用 `0x45d0cf0` 向上取整；alloc ring -> `+0x08`，
    写 `+0x10`；`staging_cap=max(ring_size/2,0x20)`，alloc staging -> `+0x18`，
    写 `+0x20`；最后尾调 `vtable+0x18`（基础 vtable 下是 `0x49cc310: ret`）。
- 已知最后一个被访问的字段在 `+0x80..+0x87`；对象按 0x90 分配（+0x88 可能是
  未访问尾部）。快照 slot2/slot0/slot1 三个有效对象地址恰好相差 0x90，直接印证。
- 默认分配器不是 operator new：`0x45f7324` 最终走 PLT `malloc`；
  `0x45f7334` 最终走 PLT `free`。

---

## 3. Push / Commit / Reset / Read / Grow 伪代码

以下 `obj` 均指 slot0；`base` 为 `libGameCore.so` 加载基址。

### 3.1 PushCsBuffer(size)

```c
void *PushCsBuffer(uint32_t size) {
    void *obj = *(void **)(base + 0x52c3250);   /* slot0 */
    return push_impl(obj, size);
}

void *push_impl(void *obj, uint32_t size) {
    *(uint32_t *)(obj + 0x24) = size;           /* pending = size，先写 */
    uint32_t cap = *(uint32_t *)(obj + 0x20);   /* staging cap */
    if (cap < size) {
        uint32_t rounded = round_pow2(size);    /* 0x45d0cf0 */
        *(uint32_t *)(obj + 0x20) = rounded;
        void *p = ((void *(*)(uint32_t))*(void **)(obj + 0x78))(rounded); /* malloc */
        ((void (*)(void *))*(void **)(obj + 0x80))(*(void **)(obj + 0x18)); /* free */
        *(void **)(obj + 0x18) = p;
    }
    return *(void **)(obj + 0x18);              /* staging，不是 ring */
}
```

语义：

- **只保证暂存区容量并返回写指针**，不写长度头、不写 ring、不推进游标。
- `pending` 在返回前就已经等于 `size`；调用方必须在返回后写入**恰好 size 字节**。
- 若 `size <= staging cap`，不会调用任何分配器（这就是 `gc_fifo0` 只设
  `+0x18/+0x20/+0x24` 也能 Push 成功的原因）。
- 容量不足时先按 2 的幂扩容，再 `free` 旧暂存区；旧数据不保留（本来就要被新帧覆盖）。

### 3.2 CommitCsBuffer()

```c
int CommitCsBuffer(void) {
    void *obj = *(void **)(base + 0x52c3250);   /* slot0 */
    void **vt = *(void ***)obj;                 /* vtable，obj 不可为 0 */
    int (*commit)(void *) = (int (*)(void *))vt[2]; /* vtable+0x10 */
    return commit(obj);                         /* -> 0x49cbffc */
}

int commit_impl(void *obj) {
    uint32_t pending = *(uint32_t *)(obj + 0x24);
    if (pending == 0) {
        *(uint32_t *)(obj + 0x34) = *(uint32_t *)(obj + 0x2c);
        return 0;                           /* 实际 w0 未定义，不要依赖返回值 */
    }

    uint32_t ring_size = *(uint32_t *)(obj + 0x10);
    uint32_t write = *(uint32_t *)(obj + 0x2c);
    uint32_t read  = *(uint32_t *)(obj + 0x30);
    uint32_t free_space = ring_size + (read - write);   /* u32 回绕 */

    if (free_space < pending) {
        pthread_rwlock_wrlock((pthread_rwlock_t *)(obj + 0x3c));
        uint32_t needed = (ring_size - free_space) + pending;
        grow(obj, round_pow2(needed));                  /* 0x49cc320 */
        pthread_rwlock_unlock((pthread_rwlock_t *)(obj + 0x3c));
    }

    __dmb(ish);
    void *ring = *(void **)(obj + 0x08);
    void *staging = *(void **)(obj + 0x18);
    uint32_t off = write & (ring_size - 1);
    uint32_t n1 = min(pending, ring_size - off);
    memcpy((char *)ring + off, staging, n1);
    memcpy(ring, (char *)staging + n1, pending - n1);
    __dmb(ish);

    write += pending;
    *(uint32_t *)(obj + 0x2c) = write;
    *(uint32_t *)(obj + 0x34) = write;      /* committed = write */
    return 0;                               /* 实际 w0 未定义，不要依赖返回值 */
}
```

必须注意：

- **pending 不会被清零**。Commit 两次会把同一段 staging 再写一遍，产生重复数据。
  正常用法是每帧先 Push 再 Commit。
- pending=0 时虽然不拷贝，但**虚调用已经发生**；vtable 不能为空。
- 正常拷贝路径**没有加锁**；只有 grow 和 read 用 rwlock。宿主必须自己串行化
  Push/Commit/Read，不能假设内部锁保护普通提交。
- grow 后 `+0x2c/+0x30/+0x34` 会被重写为压缩后的计数，见 §3.5。

### 3.3 Read（0x49cc1a8）与 PopFifoCppPackBuffer

ring read 不是导出，但可以被宿主按偏移调用；`PopFifoCppPackBuffer` 也复用它：

```c
int ring_read(void *obj, void *dst, uint32_t max_len) {
    pthread_rwlock_rdlock((pthread_rwlock_t *)(obj + 0x3c));
    uint32_t committed = *(uint32_t *)(obj + 0x34);
    uint32_t read = *(uint32_t *)(obj + 0x30);
    uint32_t avail = committed - read;
    uint32_t n = min(max_len, avail);

    uint32_t ring_size = *(uint32_t *)(obj + 0x10);
    void *ring = *(void **)(obj + 0x08);
    uint32_t off = read & (ring_size - 1);
    uint32_t n1 = min(n, ring_size - off);
    memcpy(dst, (char *)ring + off, n1);
    memcpy((char *)dst + n1, ring, n - n1);

    *(uint32_t *)(obj + 0x30) = read + n;
    pthread_rwlock_unlock((pthread_rwlock_t *)(obj + 0x3c));
    return n;
}
```

`PopFifoCppPackBuffer(dst, len)`（0x460a434）不是读 slot0：

```text
x8 = [0x4ff57c8] = 0x52488c0
x8 = [0x52488c0] = 0x52c3258      ; slot1 地址
x8 = [0x52c3258]                  ; slot1 对象
ring_read(slot1, dst, len)
```

### 3.4 ResetCsBuffer()

```c
void reset_impl(void *obj) {            /* 0x49cc18c */
    *(uint32_t *)(obj + 0x2c) = 0;      /* write */
    *(uint32_t *)(obj + 0x30) = 0;      /* read */
    *(uint32_t *)(obj + 0x34) = 0;      /* committed */
    *(uint32_t *)(obj + 0x24) = 0;      /* pending */
    *(uint8_t  *)(obj + 0x28) = 1;      /* reset/overflow flag */
}
```

Reset 不释放 ring/staging，不重置 `+0x08/+0x10/+0x18/+0x20`。

> 返回值注意：`CommitCsBuffer` / `ResetCsBuffer` 的实现没有显式设置 `w0`，
> 所以 C 返回值不是稳定契约。判定成功要看 `+0x24/+0x2c/+0x34` 和 `+0x28`，
> 不要依赖返回值。`PushCsBuffer` 返回 `+0x18`，这个是可靠的。

### 3.5 Grow（0x49cc320）

```c
void grow(void *obj, uint32_t new_size) {   /* new_size 已是 2 的幂 */
    void *new_ring = alloc(obj, new_size);  /* +0x78 */
    uint32_t ring_size = *(uint32_t *)(obj + 0x10);
    uint32_t write = *(uint32_t *)(obj + 0x2c);
    uint32_t read  = *(uint32_t *)(obj + 0x30);
    uint32_t readable = write - read;

    void *old_ring = *(void **)(obj + 0x08);
    uint32_t off = read & (ring_size - 1);
    uint32_t n1 = min(readable, ring_size - off);
    memcpy((char *)new_ring, (char *)old_ring + off, n1);
    memcpy((char *)new_ring + n1, old_ring, readable - n1);

    *(uint32_t *)(obj + 0x2c) = readable;   /* write = 未读数 */
    *(uint32_t *)(obj + 0x30) = 0;          /* read = 0 */
    *(uint32_t *)(obj + 0x34) = readable;   /* committed = 未读数 */
    free(obj, old_ring);                    /* +0x80 */
    *(void **)(obj + 0x08) = new_ring;
    *(uint32_t *)(obj + 0x10) = new_size;
}
```

grow 只压缩 ring，不改变 `+0x18/+0x20/+0x24`。

### 3.6 关键不变量

- `+0x10` 必须是 2 的幂，否则 `(size-1)&cursor` 的环形索引错误。
- `+0x08`、`+0x18`、`+0x78`、`+0x80` 必须非空（除非永远不触发对应路径）。
- `+0x24` 是"暂存区里有多少字节待提交"，不是"ring 里有多少字节"。
- ring 排空时 `+0x2c == +0x30 == +0x34`，但 `+0x24` 仍可非零（快照正是如此）。
- `+0x24` 非零不代表数据还没提交过；Commit 不清 pending。
- 同一个对象不要并发 Commit/Read；普通路径没有 write lock。

---

## 4. 0x6C / 0x7FFF 的归属纠正

### 4.1 事实

`PushCsBuffer` 实现 `0x49cbf98` 的全部反汇编只有：

```text
ldr  w8, [x0, #0x20]     ; cap
str  w1, [x0, #0x24]     ; pending
cmp  w8, w1
... 0x45d0cf0 (round pow2) / [x0+0x78] / [x0+0x80] ...
ldr  x20,[x0, #0x18]     ; staging
```

**没有 `0x6c`，也没有 `and #0x7fff` / `ubfx #0xf,#0xf`。**

`0x6c` 与 `0x7fff` 实际出现在相邻的另一个类：

- `0x49ccd44`：按索引析构一个元素（`umaddl x0, w20, w9, x8`，其中 `w9=0x6c`）。
- `0x49ccdd8`：清空所有元素（`add x21, x21, #0x6c`）。
- `0x49cce80`：reserve/扩容（`mov w10,#0x6c`）。
- `0x49ccf68`：区间搬移（`umaddl x0, w22, w9, x8`）。
- `0x49ccffc`：emplace/copy 插入（`mov w8,#0x6c`）。

这些函数操作的是 **SBO（small-buffer-optimized）vector**，不是 CS 字节流。

### 4.2 vector 头与元素布局

容器首 4 B（`container+0`）是位域头：

| 位 | 宽度 | 含义 |
|---|---:|---|
| 0..14 | 15 | count（`& 0x7fff`） |
| 15..29 | 15 | capacity（`ubfx #0xf,#0xf`） |
| 30..31 | 2 | storage mode（`lsr #0x1e`）：0 = inline，1 = heap |

- inline 模式：元素从 `container+4` 开始；heap 模式：`container+4` 是元素数组指针。
- 本专用化的元素步长 **0x6C = 108 B**：
  - `elem+0x00`：元素 vtable（多态）。
  - `elem+0x68`：constructed 标志（copy ctor 置 1；析构器清 0）。
  - `elem+0x00` 的 vtable[0] 是元素析构器。
- 插入时若 `count == capacity`，容量字段按 **count+4** 增长（每次增加 4 个元素；
  `0x49cce80` 的 reserve 可精确设置容量），不是倍增。分配器/释放器经
  `0x51d1e08/0x51d1e18`。
- 元素 copy ctor：`0x4a17ee8`（经 `[0x5074a50]` 工厂，用源对象 vtable 构造）。

### 4.3 它索引的是什么对象

在 `0x3e70400`（协议/命令序列化函数）里：

```text
x19 = serializer/context-like object
x24 = [x19+0x28] + 0x60          ; 容器地址
...
x8  = [0x525a938] = 0x49ccffc    ; emplace
x0  = x24
x1  = sp+0x10                    ; {x19, x2, x3}
blr x8
```

即：**某个子对象 `[serializer+0x28] + 0x60` 处的 108 B 多态记录队列**，
用于协议/消息对象，不是 `base+0x52c3250` 的 CS ring，也不是 `+0x18` 的暂存字节。
它也不等于 `.abc` 的 FRAME_CMD 线格式（后者是 opcode + payload；143 条
`FRAME_CMD_INFO` 只是 opcode 表）。

### 4.4 与快照数据对拍

| 快照槽 | pending（`+0x24`） | 是否 108 的倍数 | 结论 |
|---:|---:|---|---|
| 0 | 8 | 否 | 原始字节，不是 108 B 记录 |
| 1 | 76 | 否 | 原始字节 |
| 2 | 0 | — | 空暂存 |

`+0x18` 是 Push 返回给调用方的**原始字节暂存区**；这一层没有任何记录头/步长。
因此：

- 不能用 `0x6C` 去切分 CS pending 数据；
- 不能把 `0x7FFF` 当 CS 流的 head/tail；它是另一个 vector 的 count/capacity/mode；
- `docs/gamecore_view_buffer.md` §4 把 `0x6C` 归到 `PushCsBuffer` 的说法应更正
  （本文 §4 为准）。

---

## 5. 快照对拍

快照文件：`host/fixtures/20261102_161129/context/context_snapshot.json`
（pid 2052，base `0x400036a00000`；地址只作证据）。

### 5.1 槽位 0-2：ring 对象

| slot | 对象 | vtable | `+0x20` cap | `+0x24` pending | `+0x2c` | `+0x30` | `+0x34` | 解释 |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 0 | 0x75d7e7fe70fc | 0x75db20ca8608 | 0x8000 | 8 | 0x291f20 | 0x291f20 | 0x291f20 | ring 已排空，暂存 8 B 未/已提交 |
| 1 | 0x75d7e7fe718c | 0x75db20ca8608 | 0x40000 | 76 | 0x17f3764 | 0x17f3764 | 0x17f3764 | 同上，76 B pending |
| 2 | 0x75d7e7fe706c | 0x75db20ca8608 | 0x8000 | 0 | 0 | 0 | 0 | 新建/空闲 |

- 三个对象地址相差 0x90：slot2 = X，slot0 = X+0x90，slot1 = X+0x180；
  与 0x90 对象尺寸一致。
- 游标相等且大于容量，证明 `+0x2c/30/34` 是累计字节计数，不是缓冲内偏移。
- 由 `staging_cap = ring_size/2` 可推断 slot0 的 `+0x10` 约为 0x10000，
  slot1 约为 0x80000（快照未直接读 `+0x10`，这是推断，不是实测）。
- pending 8/76 都不是 108 的倍数，直接否定"CS 缓冲按 108 B 记录组织"。

### 5.2 槽位 3-7：不是 CS ring

| slot | 对象 | vtable | 判据 |
|---:|---|---|---|
| 3 | 0x75dc98daaa70 | 0x75ddcda95ff0 | `+0x20=0x6E676953` = ASCII `"Sign"`，`+0x24=0x69466C61` = `"alFi"`；对象是字符串/其他数据，不是 ring |
| 4 | 0x75d7ea4e9ee0 | 0x75d7e8750184 | 不是 ring；与 slot5 相差 0x88，符合 binder 的 `ctx+0x4f0`/`ctx+0x578` 内嵌对象间距 |
| 5 | 0x75d7ea4e9f68 | 无 | 不是 ring；与 slot4 相差 0x88，可能是未构造的内嵌对象 |
| 6 | 0x75db890b5310 | 0x75db20c9a1f0 | cap=0、pending=48，容量 0 却有 pending，不符合 ring 不变量 |
| 7 | 0x75db890b3550 | 0x75db20c9a1f0 | 同上，pending=56 |

结论：**8 路表是异构通道表**；快照里只有 slot0/1/2 能按 ring 解释；
slot4/5 很可能是某个 context 的内嵌对象（见 §5.3），slot3/6/7 也不是 CS ring。
把 slot3-7 当 CS FIFO 会误读字符串/其他对象。

### 5.3 上下文快照 vs binder 偏移

`0x43d301c`（经 vtable `0x4f8d720[0]` / thunk `0x43d320c`）是真实的全局绑定器。
它的语义（反汇编）：

```text
owner = x0
S = [owner+0x48]                  ; 强引用对象
if [S+0xc] == [owner+0x50] ...    ; 版本/盐匹配
    S+0x8 += 1                    ; 引用计数 +1
W = [owner+0xa8]                  ; 弱引用对象
if W 有效且 [W+0xc] == [owner+0xb0]:
    ctx = W
    *[0x4ff5de8] -> [0x52488b8] -> slot0 = [ctx+0x80]   ; CS 输入
    *[0x4ff57c8] -> [0x52488c0] -> slot1 = [ctx+0x88]   ; Cpp pack
    *[0x4ff5dc0] -> [0x52488c8] -> slot4 = ctx + 0x4f0   ; 内嵌对象地址
    *[0x4ff5df0] -> [0x52488d0] -> slot5 = ctx + 0x578   ; 内嵌对象地址
else:
    slot0/slot1/slot4/slot5 = 0
```

所以 binder 需要的是一个**真实引用计数 context**，其字段：

| context 偏移 | 含义 |
|---:|---|
| +0x08 | u32 引用计数（binder 会 +1/-1，减到 0 会调 `vtable+0x10` 析构） |
| +0x0c | u32 版本/盐（与 owner 的版本字比较） |
| +0x80 | CS slot0 对象指针（取 `*(ctx+0x80)`） |
| +0x88 | Cpp pack slot1 对象指针（取 `*(ctx+0x88)`） |
| +0x4f0 | slot4 内嵌对象（binder 存 `ctx+0x4f0` 这个地址） |
| +0x578 | slot5 内嵌对象（binder 存 `ctx+0x578` 这个地址） |

快照上下文（0x75d7e86e9ff0）对拍：

| 偏移 | 值 | 与 binder 预期 |
|---:|---|---|
| +0x00 | 0x75d7e86e9ff0（自身） | 不是 vtable；说明它可能不是普通 C++ 对象头 |
| +0x08 | 0x64801e00000 | 低/高 32 位不像普通引用计数 |
| +0x18 | 0x75d7ea4e9ff0 | 另一个对象指针 |
| +0x68 | 0x75d7e7fe6ff0 | 指向 CS 对象 arena 头部（slot2 之前 0x7c） |
| +0x78 | base+0x40a0c94 | libGameCore 代码指针 |
| +0x80 | 0x75db20c99f48 | **不是** 快照 slot0（0x75d7e7fe70fc） |
| +0x88 | null | binder 期望 slot1 对象 |
| +0x2e0 | 0x75d7e7fe706c | 指向 slot2（arena 起点） |
| +0x370 | 0x75d7e7fe726c | 指向 arena 内另一对象 |
| +0x4f0 | 0x75d7ea4c7870 | 快照 context 不是 P，所以这不是 binder 的内嵌对象；不能按指针字段解释 |
| +0x578 | 0x7fffaaa8b5b38ec7 | 同上；该 qword 跨记录，不能按指针解释 |

**补充推断（数值上很强）**：快照 slot5 - slot4 = `0x88`，正好等于
`0x578 - 0x4f0`；并且

```text
slot4 - 0x4f0 = 0x75d7ea4e99f0
slot5 - 0x578 = 0x75d7ea4e99f0
```

两边相同，说明 slot4/5 很可能**确实由 binder 从 context P = 0x75d7ea4e99f0
安装**：slot4 = P+0x4f0、slot5 = P+0x578，都是 context 内嵌对象。
而快照 `context+0x18 = 0x75d7ea4e9ff0 = P+0x600`，说明快照捕获的
`0x75d7e86e9ff0` 不是 P，而是另一个层级/包装（其 +0x18 指向 P 的尾部）。
在快照的全部 context 字段里，只有 +0x18 落在 P 的地址范围内（P..P+0x800），
没有其他字段直接指向 P；这也符合"快照是包装层"的判断。

如果这个推断成立，P+0x80/P+0x88 应分别等于 slot0/slot1
（0x75d7e7fe70fc / 0x75d7e7fe718c）。这是下一步最值得做的只读验证：
dump P+0x00..0x90 和 P+0x4f0/+0x578，即可确认 binder 的真实 context 及
四个槽位来源。

当前能下的结论：**快照的 `context` 不是 binder 的 `CCoreContext`**。
它的 +0x80/+0x88 不满足 binder 语义，`+0x268` 之后还是非 8 字节对齐的记录区
（很多 qword 是两个指针/字段拼出来的）。因此：

- 可以用快照证明 ring 对象布局和 8 路表；
- **不能用快照的 context 字段当安装模板**；
- 如果宿主需要 context，必须拿真实 context（或真实 binder owner），见 §6.4。

---

## 6. 宿主安装真实 FIFO

### 6.1 前置条件

1. 同一构建、同一 ABI（ARM64 Android，bionic）。先 preload 依赖
   `libpandora.so`、`libpixuiCurl.so`、`libPixUI_Unity.so`、`libpuerts.so`，
   再 `dlopen libGameCore.so`。
2. `dlsym("ModuleInit")` 并调用；`base = ModuleInit - 0x46ad0e0`。
3. 等 `[base+0x542f4b0+0x48] == 1`（ModuleInit 只初始化一次标志）。
4. 校验链：
   - `[base+0x4ff5de8] == base+0x52488b8`
   - `[base+0x52488b8] == base+0x52c3250`
   - `[base+0x52c3250] == 0`（ModuleInit 后通常还没有战斗上下文）
5. 不要用快照里的 `0x75d7.../0x75db...` 常量；vtable 用 `base+...`。

### 6.2 推荐：用真实 ctor/init 装一个最小 slot0

```c
/* 只读/宿主进程内；不注入游戏 */
void *obj = calloc(1, 0x90);                       /* 零初始化，保活 */
((void (*)(void *))(base + 0x49cbd88))(obj);       /* 基础 ctor：vtable/rwlock/字段 */
((void (*)(void *, uint32_t, uint32_t, void *, void *))
    (base + 0x49cbeec))(obj, 0x10000, 0, 0, 0);    /* init：malloc ring/staging */

*(void **)(base + 0x52c3250) = obj;                /* 只写 slot0，保留 0x52488b8 */
```

得到：

- `obj+0x00 = base+0x4fd16f8`（真实基础 vtable；Commit 的 `+0x10` -> `0x49cbffc`）
- `obj+0x08 = malloc(0x10000)`；`obj+0x10 = 0x10000`
- `obj+0x18 = malloc(0x8000)`；`obj+0x20 = 0x8000`
- `obj+0x24 = 0`；`obj+0x2c/30/34 = 0`；`obj+0x28 = 0`
- `obj+0x38 = 0`
- `obj+0x3c` = 已初始化的 pthread_rwlock_t
- `obj+0x78 = base+0x45f7324`（malloc 包装）
- `obj+0x80 = base+0x45f7334`（free 包装）

为什么这是"真实对象"而不是 fake：

- vtable 是库自己的 `.data.rel.ro` 表（`0x4fd16f8`），不是手写函数表；
- 分配器是库默认的 malloc/free 包装；
- rwlock 用真实 `pthread_rwlock_init`；
- ring/staging 是真实 malloc 缓冲；
- 后续 Push/Commit/Reset/Read/grow 全部走真实实现。

注意：

- `0x49cbd88` 是**基础** ctor，设置基础 vtable；不要再用 `0x4fd1728`
  （那是一个带二级基类/额外虚槽的真实表，语义未完全验证）。Push/Commit/Reset
  只需要基础表。
- `0x49cbeec` 不初始化 rwlock，也不清 cursors；所以必须先 ctor，或手工全部初始化。
- 只想换 ring 大小时改第二个参数即可；必须是 2 的幂（init 会向上取整，但
  Commit 的 `(size-1)` 要求最终值是 2 的幂）。
- 对象必须**保活到进程结束**。不要 free，不要 memcpy 搬家（rwlock/指针不可搬）。
- 退出时可先 `*(void**)(base+0x52c3250)=NULL`，再调真实 dtor
  `base+0x49cbe30`（会 free ring/staging + destroy rwlock）。
- 如果 slot0 已经有真实对象（战斗中），直接复用，不要覆盖。

### 6.3 安装后的自检

| 检查 | 期望 |
|---|---|
| `[base+0x4ff5de8]` | `base+0x52488b8` |
| `[base+0x52488b8]` | `base+0x52c3250` |
| `[base+0x52c3250]` | `obj` |
| `*(void**)obj` | `base+0x4fd16f8` |
| `obj+0x08 / +0x18` | 非空 |
| `obj+0x10` | 2 的幂（如 0x10000） |
| `obj+0x20` | `max(+0x10/2, 0x20)`（如 0x8000） |
| `obj+0x24 / +0x2c / +0x30 / +0x34` | 0 |
| `obj+0x78 / +0x80` | `base+0x45f7324 / base+0x45f7334` |

### 6.4 上下文：能绑，不能造

宿主**不能**手搓一个"最小 context"来骗过 GameCore。原因：

- 帧 tick `0x46b7888` 取 `[[[base+0x4ff4520]]] + 0x280` 并调用；
- View 出口用 `context+0x2b0`；
- `PopFifoCppPackBuffer` 用 `context+0x88`（经 slot1）；
- binder 还会取 `*(context+0x80)`、`*(context+0x88)`，以及
  `&context[0x4f0]`、`&context[0x578]` 两个内嵌对象地址，并管理
  `+0x08/+0x0c` 引用计数/版本；
- `0x52717b0` 持有者、`context+0x78` 代码指针等都会被其他子系统解引用；
  binder owner 的 `+0xa8/+0xb0` 还有弱引用/版本链。任何一个假字段都会在
  tick/view/析构路径上崩。

可行做法只有两类：

1. **真实 context + 只绑定**：
   - 如果已有真实 context 指针，直接写四个槽位（等价于 binder 的尾部）：
     ```c
     *(void**)(base+0x52c3250) = *(void**)(ctx+0x80);          /* slot0 */
     *(void**)(base+0x52c3258) = *(void**)(ctx+0x88);          /* slot1 */
     *(void**)(base+0x52c3270) = (char*)ctx + 0x4f0;           /* slot4 内嵌 */
     *(void**)(base+0x52c3278) = (char*)ctx + 0x578;           /* slot5 内嵌 */
     ```
     这比调用 binder 少了引用计数副作用。
   - 或者调用 binder `base+0x43d301c`，但 owner 必须是真实 owner（`+0x48/+0x50`
     强引用、`+0xa8/+0xb0` 弱引用都真实），否则它可能把真实 context 的
     引用计数减到 0 并调用析构。
2. **不装 context，只装 FIFO**：
   - Push/Commit/Reset/read 都能工作，适合做 FIFO 语义实验；
   - 但 GameCore 不会消费命令、不会推进帧；cs 消费者路径需要真实 context/
     pack buffer/parser。

### 6.5 必须初始化 / 不能伪造清单

| 项 | 必须初始化 | 可以伪造？ | 说明 |
|---|---|---|---|
| vtable `+0x00` | 是 | **否** | 用真实 `base+0x4fd16f8`；Commit 先查 vtable+0x10 |
| ring `+0x08` / size `+0x10` | 是 | 可以真实分配，不可空/假 | size 必须 2 的幂 |
| staging `+0x18` / cap `+0x20` | 是 | 可以真实分配，不可空/假 | Push 返回它 |
| pending `+0x24` | 是 | 必须等于实际写入字节数 | Commit 用它 |
| cursors `+0x2c/30/34` | 是 | 必须自洽 | 累计计数，可回绕 |
| flag `+0x28` | 是 | 0 或 Reset 语义 | Reset 置 1 |
| rwlock `+0x3c` | 是 | **否** | 必须 `pthread_rwlock_init`，不能是 mutex/全零假设 |
| alloc/free `+0x78/80` | 是 | 可以真实 malloc/free，不可空 | 默认 `base+0x45f7324/334` |
| slot 表 `base+0x52c3250` | 只写 slot0 | 不替换 `0x52488b8` | 保留真实表 |
| context `+0x80/+0x88`（对象指针）与 `+0x4f0/+0x578`（内嵌对象） | 仅真实 context | **否** | 不能手搓；4/5 是 context 内部地址 |
| context 引用计数 `+0x08/+0x0c` | 仅 binder 需要 | **否** | 假计数会触发真实析构 |
| 8 路其他槽 | 可保持 0 | 不要伪装成 CS | slot1 是 Cpp pack，4/5 是上下文通道 |

---

## 7. 拒绝清单：不安全的 fake context 捷径

按危险程度排序。每条都给出会踩的指令/地址。

1. **calloc 一个对象、不设 vtable，直接 Commit（包括 pending=0）**
   - `CommitCsBuffer` 先 `ldr x8,[x0]`（vtable）、`ldr x1,[x8,#0x10]`；
     vtable=0 时在 `0x460a3f8/0x460a3fc` 踩 0x10。
   - `_host/gc_fifo0.c` 的 `obj=calloc` 没有写 `obj[0]`；它的
     "Commit(len=0) 会立即返回"只对 `0x49cbffc` 内部成立，虚调用之前就已经崩。
2. **手写只含 `+0x10` 的 vtable**
   - Commit 能过；但 GameCore 关闭/Reset/异常路径可能调用 `+0x00` 析构或
     `+0x08` deleting dtor，直接跳飞。用真实 vtable。
3. **在 `+0x3c` 放 pthread_mutex_t（或全零当 rwlock）**
   - grow 路径 `0x49cc03c/0x49cc0b8` 调 `pthread_rwlock_wrlock/unlock`；
     read 调 `pthread_rwlock_rdlock`。类型不对是 UB，可能死锁/崩。
   - 必须 `pthread_rwlock_init`。
4. **`+0x08` 为 NULL 但 Commit 时 pending>0**
   - `0x49cc100` 取 `ring = [obj+8]`，随后 `0x49cc12c` 计算 `ring+off`、
     `0x49cc134` 做 memcpy；空指针直接 SIGSEGV。
5. **`+0x78/+0x80` 为 NULL**
   - Push 的 `size > staging cap` 路径在 `0x49cbfcc` 调 `[obj+0x78]`；
     Commit grow 也调；空指针崩。
6. **ring size 不是 2 的幂**
   - Commit/read 用 `(size-1)&cursor`；非 2 的幂会得到错误偏移，数据错位/越界。
7. **替换 `[base+0x52488b8]` 为宿主堆数组（gc_fifo0 的做法）**
   - Push/Commit/Reset 能跑，但真实 `base+0x52c3250` 表被绕过；
     binder、`0x460a180`、任何直接读槽位的代码都看不到你的对象。
   - 正确做法：只写 `*(void**)(base+0x52c3250) = obj`。
8. **手搓 context 字段 `+0x80/+0x88` 或内嵌对象 `+0x4f0/+0x578`**
   - tick `0x46b7888`、View `context+0x2b0`、`PopFifoCppPackBuffer`、
     binder 引用计数都会解引用；假指针会在这些路径崩。slot4/5 不是外部指针，
     而是 context 内部对象地址，不能单独分配后塞进去。
9. **手搓 context 引用计数 `+0x08/+0x0c` 后调 binder**
   - binder 在 `0x43d30c0/0x43d3128` 可能调用 `vtable+0x10` 析构；
     假计数可能把真实对象提前释放，或对假对象调析构。
10. **把快照地址当常量**
    - `0x75d7.../0x75db...` 是新进程/新对局就变的运行期地址；用 `base+offset`，
      vtable 用库内真实表。
11. **把 8 路都当 CS FIFO**
    - slot1 是 Cpp pack；slot2/3 是其他 ring；4/5 是上下文通道；6/7 未绑定。
      只对 slot0 做 CS Push/Commit。
12. **把 pending 当"未提交标志"**
    - Commit 不清 pending；重复 Commit 会重复写入。每帧先 Push 再 Commit。
13. **用 0x6C 切分 pending/ring 字节**
    - 见 §4；pending 8/76 不是 108 的倍数，0x6C 属于另一个 SBO vector。
14. **并发 Commit/Read 同一对象**
    - 普通拷贝路径不加写锁；只有 grow/read 加锁。宿主需串行化。

---

## 8. 最小测试计划（宿主进程，不启动游戏）

测试对象：§6.2 构造的真实 slot0。所有调用都在宿主进程内，不注入游戏。
建议用 `gc_fifo0.c` 的框架（preload + ModuleInit + dlsym），但把 fake 对象换成
真实 ctor/init。

函数签名：

```c
void *(*PushCsBuffer)(uint32_t)          = dlsym(gc, "PushCsBuffer");
int   (*CommitCsBuffer)(void)            = dlsym(gc, "CommitCsBuffer");
int   (*ResetCsBuffer)(void)             = dlsym(gc, "ResetCsBuffer");
int   (*ring_read)(void*, void*, uint32_t) =
        (int (*)(void*, void*, uint32_t))(base + 0x49cc1a8);
```

| # | 操作 | 期望成功信号 | 失败信号/定位 |
|---:|---|---|---|
| T0 | 构造 + 装 slot0 + 自检 §6.3 | 所有字段匹配；无 SIGSEGV | `obj+0` 不是 `base+0x4fd16f8`：ctor 未跑/被覆盖 |
| T1 | `PushCsBuffer(0)` -> `CommitCsBuffer()` | 返回 `obj+0x18` 非空；pending=0；`+0x2c/30/34` 不变；Commit 不崩（返回值不可依赖） | Commit 崩在 0x460a3f8：vtable 空；Push 返回 NULL：staging 空 |
| T2 | `PushCsBuffer(8)`，写 8 B 模式，`Commit`，`ring_read(obj,dst,8)` | Push 返回 staging；Commit 后 write/committed +8；read 返回 8 且字节完全一致；read cursor +8 | 数据不一致：ring/offset/size 错；崩 0x49cc100/0x49cc12c：ring 空 |
| T3 | `PushCsBuffer(76)`，写 76 B，`Commit`，`ring_read(...,76)` | 同上；76 B 完整回读；pending 仍为 76（Commit 不清） | 76 不是 108 倍数但应正常；若按 108 解析会误判 |
| T4 | 连续 Push/Commit/Read 100 次（每次 8 B） | 100 次无崩；每次 read 8 B；游标每次 +8 | 游标不前进：pending 被清/Commit 未走；崩：锁/指针 |
| T5 | 填满 ring（不读）：`Push(0x8000)+Commit` 两次，再 `Push(1)+Commit` | 前两次后 write=0x10000、read=0；第三次 free_space=0，触发 grow 到 0x20000；无崩；read 回读 0x10001 字节且内容一致 | 未 grow：free_space 计算/条件错；崩 0x49cc0b0：alloc/free 空 |
| T6 | 空 ring 上 `Push(0x10000)+Commit`（ring=0x10000，刚好满） | 不 grow（free_space==pending）；write=0x10000；read 回读 0x10000 | 误 grow：条件写错；读长度不对：size/offset |
| T7 | `ResetCsBuffer()` | pending=0，`+0x2c/30/34=0`，`+0x28=1`；随后 read 返回 0；Commit 不再前进 | 标志/游标未清：Reset 未走 |
| T8 | 重复 Commit（Push 8 + Commit + Commit + read 16） | read 返回 16（前 8 + 重复 8）；证明 pending 不清 | 只返回 8：Commit 清了 pending（与实现不符） |
| T9（负向，可选） | 按 §7 的 fake 对象做 Commit(0)/Commit(pending>0) | 预期在 0x460a3f8 / 0x49cc100 / rwlock 处 SIGSEGV；用于验证拒绝清单 | 不崩反而危险：说明对象/布局被误改 |

T5 的 ring 大小：T0 用 0x10000；T5 先 `Push(0x8000)+Commit` 两次（不 read），
此时 write=0x10000、read=0，ring 已满；再 `Push(1)+Commit` 时 free_space=0，
pending=1，触发 grow 到 0x20000。

成功总标准：

- 无 SIGSEGV/SIGBUS/SIGABRT；
- Push 返回 `obj+0x18`；
- Commit 后 `+0x34 == +0x2c`；
- read 返回的字节与写入完全一致；
- `+0x10` 始终是 2 的幂；
- 100 帧循环后 `+0x2c/+0x30/+0x34` 单调（按 u32 回绕意义）且差值等于未读字节。

---

## 9. 证据、未决与下一步

### 9.1 已证实的静态事实

- `PushCsBuffer` 桩/实现/尾调：`0x460a3cc -> 0x460a3ac -> 0x49cbf98`；
  取 `[[[0x4ff5de8]]]` 的 slot0。
- `CommitCsBuffer`：`0x460a400 -> 0x460a3e4`，取 slot0 后 `vtable+0x10`。
- `ResetCsBuffer`：`0x460a428 -> 0x460a40c`，取 slot0 后 `0x49cc18c`。
- `0x49cbf98` 字段：`+0x20` cap、`+0x24` pending、`+0x18` 返回、`+0x78/80`
  alloc/free、`0x45d0cf0` round pow2。
- `0x49cbffc` 字段：`+0x24` pending、`+0x10` ring size、`+0x2c/30/34` 游标、
  `+0x08` ring、`+0x18` staging、`+0x3c` rwlock、grow `0x49cc320`。
- `0x49cc1a8` 是 read（`+0x34-+0x30`，`+0x30` 前进，rdlock/unlock）。
- `0x49cc18c` 是 reset（清 4 个字段并置 `+0x28=1`）。
- 基础 ctor `0x49cbd88` -> vtable `0x4fd16f8`；基础 init `0x49cbeec`；
  默认 alloc/free = malloc/free 包装 `0x45f7324/0x45f7334`。
- 槽位表静态地址槽：`0x52488b8/0x52488c0/0x52486a0/0x52486a8/0x52488c8/0x52488d0`
  分别指向 `0x52c3250/58/60/68/70/78`。
- binder `0x43d301c` 写 slot0/1/4/5：slot0/1 取 `*(ctx+0x80)`/`*(ctx+0x88)`，
  slot4/5 取 `ctx+0x4f0`/`ctx+0x578` 这两个**内嵌对象地址**。
- `0x6C`/`0x7FFF` 属于 108 B 多态记录的 SBO vector，不属于 PushCsBuffer。

### 9.2 未决

- 快照里 slot0/1/2 的具体 vtable `0x75db20ca8608` 属于哪个模块的哪份类实例；
  本文只证明字段行为与库内基础类一致，未把运行期地址映射回文件。
- 快照 context 与 binder 的 `CCoreContext` 不是同一个对象；由 slot4/5 间距可反推
  binder context 很可能是 **P = 0x75d7ea4e99f0**（slot4=P+0x4f0，slot5=P+0x578，
  P+0x600 = 快照 context+0x18）。需 dump P+0x80/+0x88 验证是否分别等于
  slot0/slot1。
- slot2/3/6/7 的通道语义（谁分配、谁消费）未定。
- CS 消费者路径 `0x46b80e8 -> 0x49cbc0c -> 0x46b8070` 需要
  `0x544c0c40` pack buffer 和 context；未验证宿主能否单独喂通。
- `+0x38` arg 的语义、`+0x28` flag 除 Reset 外的触发条件未定。
- 普通 Commit/Read 是否由游戏主线程天然串行化未定；宿主必须自己串行化。

### 9.3 下一步静态动作

1. 在活进程里只读抓 `owner`（vtable `0x4f8d720`）的 `+0x48/+0xa8`，确认真实
   context 指针、`*(ctx+0x80)`/`*(ctx+0x88)`，以及 `ctx+0x4f0`/`ctx+0x578`
   的内嵌对象类型。
2. 对 `0x52c3250` 做写入者扫描（基址计算/间接写），确认除 binder 外谁填 slot2/3/6/7。
3. 反汇编 `0x46b8070`（CS parser），确认它是否依赖 context 的其他字段。
4. 在离线 5V5 里对 slot0 的 `+0x2c/+0x30/+0x34` 做帧内差分，验证
   "push -> commit -> read" 的真实节奏（不注入，只读采样）。

## 10. 2026-11-03：consumer 拆解与 H5 探针实测

`0x46B80E8` 不是单一解析器，而是两步：

```text
0x46B80E8(consumer=[0x544CC40], slot0=[[[0x4FF5DE8]]])
  -> 0x49CBC0C(consumer, slot0)   ; drain：ring_read 到 consumer buffer
  -> 0x46B8070(buf, buf+used)     ; parse：按 32 位头分发 handler
```

parser 头（小端）：

```text
opcode = hdr & 0xffff
arg    = hdr >> 16
flag   = (hdr & 0x40000000) ? 0 : 1
if (opcode >= [base+0x5272368]) stop
handler = *(void **)(*(void **)(base+0x544D340) + opcode*16)
handler(&p, flag, arg)
```

本次新增的静态/运行期事实：

- `[base+0x544D340]` 是**表指针**（不是表本身），每 entry 16 B；
  `[base+0x5272368]` 是槽位容量。干净宿主 `ModuleInit` 后两者都是 0，
  所以真实帧即使推进 slot0，parser 也不会分发。
- live 进程（build 5247758）实测 count=857、非零 handler=792；
  表在 `base+0x53F6F40`。`host/scripts/capture_cmd_table.py` 可只读捕获
  table + thunk 引用的 BSS slot，写成 `KCMD v1` fixture。
- 全量 10,473 非空真实 `.abc` payload：push/commit/drain 10,473/10,473，
  consumer buffer 与 payload 逐字节一致；935 帧 opcode 在范围内，其中
  25 帧 handler 正常返回、910 帧在 context/battle 对象解引用处崩溃
  （PC 聚类见 `docs/h5_consumer_probe.md`）。
- 结论不变：**FIFO/drain 已通，不等于 GameCore 消费成功**；崩溃点是运行期
  context/对象状态缺口，不是 ring 布局问题。

复现：`host/scripts/run_h5_probe.sh`；详见 `docs/h5_consumer_probe.md`。

---

## 附录 A：地址/偏移速查

| 名称 | base-relative |
|---|---:|
| CS 根槽 | `0x4ff5de8` -> `0x52488b8` |
| 槽位表首 | `0x52c3250`（8 qword） |
| slot0 地址槽 | `0x52488b8` -> `0x52c3250` |
| slot1 地址槽 | `0x4ff57c8 -> 0x52488c0 -> 0x52c3258` |
| slot2 地址槽 | `0x4ff5de0 -> 0x52486a0 -> 0x52c3260` |
| slot3 地址槽 | `0x4ff5e70 -> 0x52486a8 -> 0x52c3268` |
| slot4 地址槽 | `0x4ff5dc0 -> 0x52488c8 -> 0x52c3270` |
| slot5 地址槽 | `0x4ff5df0 -> 0x52488d0 -> 0x52c3278` |
| PushCsBuffer | stub `0x460a3cc`, impl `0x460a3ac`, target `0x49cbf98` |
| CommitCsBuffer | stub `0x460a400`, impl `0x460a3e4`, target `0x49cbffc` via vtable+0x10 |
| ResetCsBuffer | stub `0x460a428`, impl `0x460a40c`, target `0x49cc18c` |
| ring read | `0x49cc1a8` |
| ring reset | `0x49cc18c` |
| ring grow | `0x49cc320` |
| ring flag accessor | `0x49cc2f8` |
| ring get size | `0x49cc2f0` |
| 基础 ctor | `0x49cbd88` |
| 基础 init | `0x49cbeec` |
| 基础 dtor | `0x49cbe30` |
| 基础 vtable | `0x4fd16f8` |
| 默认 alloc | `0x45f7324` -> malloc |
| 默认 free | `0x45f7334` -> free |
| round pow2 | `0x45d0cf0` |
| binder | `0x43d301c` (thunk `0x43d320c`, vtable `0x4f8d720`) |
| 槽位统计 helper | `0x460a180` |
| Cpp pack pop | `0x460a434` |
| CS consumer | `0x46b80e8` -> `0x49cbc0c` -> `0x46b8070` |
| 0x6C vector 函数 | `0x49ccd44 / 0x49ccdd8 / 0x49cce80 / 0x49ccf68 / 0x49ccffc` |
| 0x6C 元素 ctor | `0x4a17ee8` |

对象字段：

```text
+0x00 vtable        +0x08 ring        +0x10 ring_size(u32)
+0x18 staging       +0x20 staging_cap(u32)  +0x24 pending(u32)
+0x28 flag(u8)      +0x2c write(u32)  +0x30 read(u32)
+0x34 committed(u32)+0x38 arg(u32)    +0x3c pthread_rwlock_t
+0x78 alloc         +0x80 free         size = 0x90
```

## 附录 B：复现命令（只读）

```bash
python tools/gc_export_map.py --check
python tools/gc_export_map.py --symbol PushCsBuffer --symbol CommitCsBuffer --symbol ResetCsBuffer
python tools/gc_export_map.py --globals
```

本文所有反汇编地址都可用 `tools/gc_export_map.py` 的 `Core.dis()` 复现；
关键函数起点：`0x49cbf98`、`0x49cbffc`、`0x49cc1a8`、`0x49cc18c`、`0x49cc320`、
`0x49cbd88`、`0x49cbeec`、`0x43d301c`、`0x460a180`。

## 附录：2026-11-03 BSS 偏移修正

本文若出现 `0x544C0BD0/0x544C0C40`，应读作 `0x544CBD0/0x544CC40`；
`0x544C000` 是页基址，0xBD0/0xC40 是页内偏移。A1 宿主已用
`[0x544CC40]=0x75dc98daac10` 调用 `0x46B80E8`，返回不崩；尚未推入有效帧命令。
