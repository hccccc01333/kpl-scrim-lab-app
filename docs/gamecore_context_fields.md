# GameCore live context 字段图（H4 快照）

- 日期：2026-11-03
- 快照：`host/fixtures/20261102_161129/context/context_snapshot.json`
- 进程：pid 2052（`com.tencent.tmgp.sgame`，build 5247758，App 12.1.1.1 / Res 12.1.1.26）
- `libGameCore.so` base：`0x400036a00000`
- live context：`0x75d7e86e9ff0`
- 抓取时间：`2026-11-03T19:06:35`，抓取时冻结（`frozen=true`）
- 边界：只读 `/proc/<pid>/mem` 的已落盘快照 + 本地 ELF/metadata/文档；本次没有注入、没有登录、没有调用游戏函数、没有修改游戏文件。

> 地址只属于本次进程/本次 context 实例。同一 pid 2052 在另一份采样中曾出现
> `context=0x75d819773ff0`（见 `docs/gamecore_view_buffer.md`）；两个实例的
> **相对布局**一致，但地址不可互换。

## 0. 结论摘要

1. 快照里的 “context” 是 `[[[base+0x4FF4520]]]` 指向的 native 对象；**没有证据**
   证明它就是 C# 的 `CLevelContext`。`CLevelContext` 是 il2cpp 类型（type 42374，
   285 字段），`libGameCore.so` 里没有 `CLevelContext` 字符串。
2. 该对象是一个 **自相对（self-relative）大容量容器**，不是普通字段平铺结构：
   `+0x00` 自指针，`+0x08` 低 32 位是容量偏移 `0x1E00000`、高 32 位是已用/计数
   游标 `0x648`，`+0x10` 基址（0）、`+0x18` 结束指针（ctx+0x1E00000）、`+0x20`
   记录表游标（ctx+0x648）。构造函数/方法表已静态定位：
   构造函数 `base+0x40A0CA0`，方法表 `base+0x51D1E58`。
   **注意**：构造函数 `0x40A0CA0` 的 fixup 循环上界是 `容量-0x18`（0x1E00000-0x18），
   不是 0x648；因此 `0x648` 之后仍可能是有效 arena 数据，本次只抓了前 0x1000。
3. 只有少数 context 字段有**代码级语义**：
   - `ctx+0x280`：帧生产路径把它作为地址传给 `0x3D01F58`，后者读 `+0x30`
     （即 `ctx+0x2B0`）并调用 vtable `+0xB8`。
   - `ctx+0x2B0`：view/UI FIFO 对象指针。`PushViewBuffer/CommitViewBuffer`
     直接读取它并调用其 vtable `+0x48`/`+0x10`；帧生产路径
     `0x46B7888 → 0x3D01F58` 通过 `[ctx+0x280+0x30]`（即 `ctx+0x2B0`）
     调用 vtable `+0xB8`。
   - `ctx+0x78`：类/类型 thunk 指针。它等于运行时
     `[base+0x4FFC268]`（RELA addend `0x40A0C94`）；构造函数把该全局写进
     `[this+0x78]`。这是本 context 与构造函数 0x40A0CA0 对应的强证据。
4. `ctx+0x268..0x610` 是 **24 字节（0x18）记录表**：每条以对象指针开头，后面是
   编码过的控制/链接字；构造函数的 fixup 循环 `0x40A0F40` 正是按 0x18 字节
   窗口扫描它。它不是十人数组：共约 39 条、没有 hero/entity 连续表。
5. CS 8 路数组在 `base+0x52C3250`；只有槽 0/1/2 属于同一 buffer 类
   （vtable `0x75db20ca8608`），槽 0 是 `PushCsBuffer/CommitCsBuffer` 实际使用
   的那一路。槽 3–7 不是这一类（槽 6/7 是另一类，槽 3–5 字段不符合 buffer 布局）。
6. 在已捕获的 0x0–0xFF8（头部 + 记录表到 0x648）里没有十人数组、没有 deskPool：
   逐 16/32 位 lane 扫描本回放 10 个 hero/entity ID，只命中一个巧合值
   （`0x810` 低 32 位 `0x9c`=156，属于编码 handle 字，不是英雄表）。
   容量 0x1E00000 的其余部分（约 30 MiB）本次未抓取。
7. 十人/entity 只在**两个 handle 目标**里被早前同进程观测到：
   `ctx+0x2C8` 目标 `+0x19E0` 出现 entity 1168；`ctx+0x5E0` 目标出现
   1760/1799。1168/1760/1799 正是本 fixture 的 entity（camp1 第 1 人、
   camp2 第 9/10 人），因此这两个 handle 是下一步最值得 dump 的候选；
   但目前没有落盘子对象字节，不能证明“十人数组”。
8. `deskPool` 是 C# 侧概念：`SGW.StartLevel(..., deskPool, poolSize, ...)`，
   `GameBuilderClientBase.inDeskPool`；协议元素
   `CSDT_DESK_SVR2GAMECORE_CONFIG { astGameCoreCfgItems_length, dwArrayNum,
   astGameCoreCfgItems_bytes }`，元素 `CSDT_DESK_SVR2GAMECORE_ITEM { wKey,
   wValue }`，即 53 条 Svr2GameCore KV。它不是十人数组；native 侧有
   `SGameDesk/GameDesk.cpp` 字符串，但没有证据把它接到本 context 的某个偏移。

## 1. 快照与链

### 1.1 快照头

```text
schema      kpl-gamecore-context-snapshot-v1
pid         2052
base        0x400036a00000
context     0x75d7e86e9ff0
frozen      true
coreState   null（base+0x544CBD0 == 0）
threadId    null（base+0x542A8A8 == 0）
```

`coreState=0`、`threadId=0` 与 5.23 的“状态机 0=空闲”一致：context 存在，但本
采样点没有 CoreThread 帧推进状态；不能用它判断帧循环是否在跑。

### 1.2 view 链（`0x4FF4520`）

| 步骤 | 地址 | 值 |
|---|---|---:|
| 1 | `0x40003b9f4520` = base+0x4FF4520 | `0x40003bbea4d0` = base+0x51EA4D0 |
| 2 | `0x40003bbea4d0` = base+0x51EA4D0 | `0x40003bc717b0` = base+0x52717B0 |
| 3 | `0x40003bc717b0` = base+0x52717B0 | `0x75d7e86e9ff0`（context） |
| 4 | `0x75d7e86e9ff0` | `0x75d7e86e9ff0`（context 的 +0 自指针） |

### 1.3 CS 链（`0x4FF5DE8`）

| 步骤 | 地址 | 值 |
|---|---|---:|
| 1 | `0x40003b9f5de8` = base+0x4FF5DE8 | `0x40003bc488b8` = base+0x52488B8 |
| 2 | `0x40003bc488b8` = base+0x52488B8 | `0x40003bcc3250` = base+0x52C3250（8 槽数组） |
| 3 | `0x40003bcc3250` | `0x75d7e7fe70fc`（槽 0 对象） |
| 4 | `0x75d7e7fe70fc` | `0x75db20ca8608`（槽 0 vtable） |

静态复核：`PushCsBuffer` 实现 `0x460A3AC` 取
`[[base+0x4FF5DE8]] → [base+0x52488B8] → [槽0]`；`CommitCsBuffer` 实现
`0x460A3E4` 取同一槽 0 后走 `vtable+0x10`。所以 **槽 0 才是 CS 命令通道**。

## 2. Context 对象模型（静态证据）

### 2.1 构造函数与方法表

| 静态锚点 | 地址 | 证据 |
|---|---:|---|
| context 构造函数 | base+`0x40A0CA0` | 写 `+0x9C`(u16)、`+0x9E`(bool)、`+0x78/+0x80`、`+0x240`、`+0x248`、`+0x250`、`+0x258`、`+0x260`；初始化 `+0x268` 起始的 0x18 字节记录区 |
| 方法表 | base+`0x51D1E58` 起 | `.data` 中连续函数指针槽；`0x51D1E58` 的 RELA addend 为 `0x40A0CA0` |
| 类 ID/工厂 thunk | base+`0x40A0C94` | RELA 全局 `base+0x4FFC268` 的 addend；thunk 跳到 getter `base+0x40A18AC`，getter 返回 `[base+0x4FFC268]` |
| 类对象 getter | base+`0x40A18B8` | 构造函数调用它并把返回值写入 `+0x80` |
| 记录 fixup 循环 | base+`0x40A0F40` | 以 4 字节步进扫描 `[base+0x268, capacity-0x18]`，检查 0x18 字节窗口内的编码指针 |

构造函数关键行为（反汇编）：

```text
ldr w8, [x19]              ; self 低 32 位
ldr w9, [x19, #8]          ; 容量/结束偏移低 32 位 = 0x1E00000
sub w20, w23, w8           ; +0x268 的相对偏移
sub w21, w9, #0x18
cmp w21, w20
b.hs  fixup_loop           ; 0x40A0F40
...
ldp x9, x10, [x19, #0x10]  ; 基址 = 0，结束 = ctx+0x1E00000
...
str x0, [x19, #0x78]       ; 类 ID（[base+0x4FFC268]）
str x0, [x19, #0x80]       ; 类对象 getter 返回值
new(0x68) -> [x19, #0x240]
new(0x20) -> [x19, #0x248]
str xzr, [x19, #0x250]
new(0x18) -> [x19, #0x258]（自引用 sentinel）
new(0x18) -> [x19, #0x260]（自引用 sentinel）
```

### 2.2 头部布局（本次快照实测）

| offset | 值 | 解释 | 置信度 |
|---:|---:|---|---|
| `+0x000` | `0x75d7e86e9ff0` | self 指针；构造函数读它做相对偏移 | high |
| `+0x008` | `0x0000064801e00000` | `{low32=0x1E00000 容量偏移, high32=0x648 已用偏移}` | high |
| `+0x010` | `0` | 基址偏移（=self） | high |
| `+0x018` | `ctx+0x1E00000` | 结束/上界指针 | high |
| `+0x020` | `ctx+0x648` | 记录表已用/计数游标（精确值/关系高，语义标签未证） | medium |
| `+0x028` | `ctx+0xF166E0` | 另一个 self-relative 指针；`+0x38` 打包同一偏移 | medium |
| `+0x078` | `base+0x40A0C94` | 类 ID/工厂 thunk；等于 `[base+0x4FFC268]` | high |
| `+0x080` | `0x75db20c99f48` | 构造函数写入的类对象/getter 返回值；角色未证 | medium |
| `+0x240` | `0x75dd290779a0` | 构造函数 `new(0x68)` | high（分配事实） |
| `+0x248` | `0x75dc696d20b0` | 构造函数 `new(0x20)` | high（分配事实） |
| `+0x250` | `0x75dd2908cf10` | 构造时写 0，live 后被改写；角色未证 | medium |
| `+0x258` | `0` | 构造函数建 sentinel，live 为 0 | medium |
| `+0x260` | `0` | 构造函数建 sentinel，live 为 0 | medium |

结论：`0x0..0x267` 是头部，`+0x268..` 起是记录/arena 数据。`+0x20` 的
`ctx+0x648` 是记录表已用/计数游标；但构造函数的 fixup 循环上界是
`容量-0x18`（`0x1E00000-0x18`），会对整个 30 MiB（0x1E00000 字节）容量扫描编码指针。
因此 **不能把 0x648 之后当作未用区**；本次快照只抓了 0x1000，容量
0x1E00000 的绝大部分（包括 `ctx+0x38A54`、`ctx+0x4B5FC`、`ctx+0x1DC9D50`
等 handle 目标）不在快照内。

### 2.3 24 字节记录表（ctx+0x268..0x610）

- 记录从 `0x268` 开始、按 0x18 步进；本次捕获到约 39 个以 canonical 指针开头的
  记录（详见附录 A）。
- 每条记录：
  - `+0x00` 对象指针（canonical，指向 ctx 内 arena 或 CS pool）；
  - `+0x08`、`+0x10` 是编码控制/链接字，不是普通 canonical 指针；其高 32 位与
    对象指针低 32 位只差 0x40000–0x50500 量级，符合 **self-relative 链接/句柄**
    的形态。
- 构造函数 `0x40A0F40` 用 `and/bic` mask + `+0x0C`/`+0x10` 检查这些 0x18 字节
  窗口，证明该区域是**引擎自己的可重定位句柄/记录表**，不是十人玩家数组。
- 第一条记录 `0x268 → ctx+0x64C`（正好在 0x648 游标之后 4 字节），符合
  “记录表/头部之后紧接 arena 第一个对象”的布局。
- `+0x310` 是 `0x100000001`，不是 canonical 指针，说明 0x18 记录区不是纯指针表；
  `+0x648` 之后仍按 0x20 步长出现 `0x60000000` / `0xNNNNNNNN70000000` 模式，
  属于 arena 编码数据（语义未解），不是可忽略的陈旧尾。

## 3. 主字段表

> 完整逐字段 CSV：`data/replays/_analysis/datasets/gamecore_context_field_map.csv`。
> 下表的 “host” 列含义：
> - `static`：base 相对静态槽，宿主 `ModuleInit` 后可按同一偏移读取/设置；
> - `layout`：ctx 相对固定布局，只有真实构造同一 context 才可复现；
> - `transient`：live 堆对象指针，不能照抄地址，必须构造；
> - `encoded`：编码值/未知语义，不可直接复现；
> - `unused`：捕获为零或当前未用。
>
> CSV 的 `host_action` 取值：`static_read_ok`（base 静态槽，ModuleInit 后可读）、
> `layout_only`（ctx 相对布局，只有构造同一 context 才可复现）、
> `must_construct`（必须构造的瞬态对象）、`transient_do_not_copy`（live 地址，
> 不可照抄）、`unknown`、`ignore`。

| ctx offset | live 值/目标 | 语义与证据 | confidence | host |
|---:|---|---|---|---|
| `0x000` | `ctx` | self；构造函数 `ldr w8,[x19]` 做相对偏移 | high | layout |
| `0x008` | `{0x1E00000, 0x648}` | 容量/已用偏移；构造函数 `ldr w9,[x19,#8]` | high | layout |
| `0x010` | `0` | arena 基址偏移 | high | layout |
| `0x018` | `ctx+0x1E00000` | arena 结束指针；构造函数范围检查上界 | high | layout |
| `0x020` | `ctx+0x648` | 记录表已用/计数游标（精确值/关系高，语义标签未证）；不是 fixup 上界（上界为容量-0x18） | medium | layout |
| `0x028` | `ctx+0xF166E0` | self-relative 指针；`+0x38` 打包同偏移 | medium | layout |
| `0x030` | `0x75dc697d66f0` | 未分类堆指针 | low | transient |
| `0x038` | `{0xF166E0, 0x20}` | 与 `+0x28` 关联的打包描述 | medium | encoded |
| `0x040` | `0x0070000000010001` | 打包值（0x70, 0x10001） | low | encoded |
| `0x060` | `0x0000000100000000` | 两个 u32（1,0） | low | encoded |
| `0x068` | `0x75d7e7fe6ff0` | CS 通道块基址候选：比 CS 槽 2 对象早 0x7C，前 3 槽都在 +0x19C 内 | medium | transient |
| `0x078` | `base+0x40A0C94` | 类 ID/工厂 thunk；等于 `[base+0x4FFC268]`；构造函数写入 | high | static |
| `0x080` | `0x75db20c99f48` | 构造函数写入的类对象/getter 返回；与 CS/view vtable 同堆簇 | medium | transient |
| `0x098` | `0x010000000000000B` | 打包值 | low | encoded |
| `0x0A0` | `0x75db20aba000` | 0x140000 字节块 A | high（算术） | transient |
| `0x0A8` | `0x140000` | 块大小 | high | static |
| `0x0B0` | 块 A | 同上 | high（算术） | transient |
| `0x0B8` | `0x75db20bfa000` | 块 B = A+0x140000 | high（算术） | transient |
| `0x0C8` | `0x75db2097a000` | 块 C = A-0x140000 | high（算术） | transient |
| `0x0D0` | `0x140000` | 块大小 | high | static |
| `0x0D8` | 块 C | 同上 | high（算术） | transient |
| `0x0E0` | 块 A | 同上 | high（算术） | transient |
| `0x0E8-0x22F` | 0 | 全零 | high | unused |
| `0x230` | `2` | 小整数/flag | low | encoded |
| `0x240` | `0x75dd290779a0` | 构造函数 `new(0x68)` | high（分配事实） | transient |
| `0x248` | `0x75dc696d20b0` | 构造函数 `new(0x20)` | high（分配事实） | transient |
| `0x250` | `0x75dd2908cf10` | 构造时写 0，live 被改写 | medium | transient |
| `0x258` | `0` | sentinel；构造时分配，live 清零 | medium | unused |
| `0x260` | `0` | sentinel；构造时分配，live 清零 | medium | unused |
| `0x268..0x610` | 39 个记录 | 0x18 字节句柄/记录表；见附录 A | high（结构） | layout/transient |
| `0x280` | `0x75d7ea4c5d28` | 帧生产路径把它作为 **地址** 传给 `0x3D01F58`；后者读 `+0x30` 调 vtable+0xB8 | high | layout |
| `0x2B0` | `ctx+0x4B5FC` | view/UI FIFO 对象指针；`PushViewBuffer/CommitViewBuffer` 读它 | high | layout |
| `0x2C8` | `ctx+0x38A54` | handle；早前同进程观测到目标+0x19E0 有 entity 1168 | medium | layout |
| `0x2E0` | `0x75d7e7fe706c` | **等于 CS 数组槽 2 对象** | high | transient |
| `0x2F8` | `0x75d7e7ffd930` | CS pool 邻接对象 | medium | transient |
| `0x370` | `0x75d7e7fe726c` | CS pool 邻接对象 | medium | transient |
| `0x5E0` | `ctx+0x1DC9D50` | handle；早前同进程观测到目标有 entity 1760/1799 | medium | layout |
| `0x648..0xFF8` | 非 canonical 模式值 | 0x648 游标之后，但仍在 0x1E00000 容量内；构造函数 fixup 会扫描全容量，不能当陈旧区 | medium | encoded |
| `0x1000+` | 未抓取 | `capture_context.py` 只抓 0x1000；容量 0x1E00000 的其余部分未 dump | high | unknown |

说明：
- `ctx+0x0A0..0x0E0` 的三个 0x140000 块按地址 C、A、B 连续排列（C+0x140000=A，
  A+0x140000=B），是本次快照中唯一能严格对上的三个连续 0x140000 块；不具备“三缓冲”语义证据，用途未证。
- `ctx+0x280` 与 `ctx+0x2B0` 相距 0x30；代码把 `ctx+0x280` 作为地址传入，
  再从 `+0x30` 取 view 对象，所以 `+0x2B0` 可以理解为 `+0x280` 子结构的成员。
  但这不影响“`[ctx+0x2B0]` 是 view 对象指针”的结论。
- `ctx+0x268..0x610` 的记录数约 39；`+0x310` 处的值是 `0x100000001`，不是
  canonical 指针，说明该表不是纯指针数组。

## 4. CS 8 槽数组

数组基址 `base+0x52C3250`（`.bss`）；槽对象在堆上。

| 槽 | 对象 | vtable | cap | pending | data | 判定 |
|---:|---:|---:|---:|---:|---:|---|
| 0 | `0x75d7e7fe70fc` | `0x75db20ca8608` | 32768 | 8 | `0x75dcc8d80c70` | 有效 buffer；`PushCsBuffer/CommitCsBuffer` 使用这一路 |
| 1 | `0x75d7e7fe718c` | `0x75db20ca8608` | 262144 | 76 | `0x75d848639ff0` | 有效 buffer，同类 |
| 2 | `0x75d7e7fe706c` | `0x75db20ca8608` | 32768 | 0 | `0x75dcc8ead8c0` | 有效 buffer，同类；ctx+0x2E0 指向它 |
| 3 | `0x75dc98daaa70` | `0x75ddcda95ff0` | 1852270931 | 1766222945 | - | 字段不符合 buffer 布局，拒绝 |
| 4 | `0x75d7ea4e9ee0` | `0x75d7e8750184` | 3907776748 | 30167 | `0x400000010` | 字段不符合 buffer 布局，拒绝 |
| 5 | `0x75d7ea4e9f68` | - | - | - | - | 无法读出 0x100 字节对象头，拒绝 |
| 6 | `0x75db890b5310` | `0x75db20c9a1f0` | 0 | 48 | `0x623701c035a` | 另一类对象，不是 CS buffer |
| 7 | `0x75db890b3550` | `0x75db20c9a1f0` | 0 | 56 | `0x48048d291f` | 另一类对象，不是 CS buffer |

CS buffer 类字段（由 `0x49CBF98`/`0x49CBFFC` 反汇编确认）：

```text
+0x10 u32   total/块大小相关
+0x18 ptr   数据缓冲
+0x20 u32   capacity
+0x24 u32   pending
+0x2C/+0x30/+0x34 u32 读/写游标
+0x3C       mutex（commit 路径）
+0x78 ptr   realloc 回调
+0x80 ptr   free 回调
```

`PushCsBuffer` 只做“确保容量、写 pending、返回 data 指针”，`CommitCsBuffer` 才
走 `vtable+0x10` 提交；这与 5.22/5.23 的结论一致。槽 0 的 cap=32768 但游标
2,694,944 远大于 cap，说明快照里的 `+0x2C/+0x30` 是**全流累计写位置**，不是
0..cap 内的下标；底层仍按 capacity 做环形回绕（`0x49CC0F0` 起的复制路径）。

补充：`0x43D301C` 的反汇编显示它会把 `[x19+0xA8]` 的 `+0x80/+0x88/+0x4F0/+0x578`
发布到 `base+0x4FF5DE8`、`base+0x4FF57C8`、`base+0x4FF5DC0`、`base+0x4FF5DF0`
四个全局槽（或在空指针时清零）。因此它是**智能指针/全局指针发布器**，不是对象
创建器；旧文档“0x43D301C 不是上下文安装器”的结论（它不创建 context）仍成立，
但“它完全无关 CS 链”不成立：它确实能发布 CS 链槽。若 `[x19+0xA8]+0x80` 等于
live 的 `0x52C3250`，则被安装对象基址为 `0x52C31D0`（数组前 0x80），这与
静态池对象的推断一致，但仍属推断（medium-low）。

`ctx+0x68` 与槽对象的关系：`0x75d7e7fe6ff0` 到槽 2 对象 `0x75d7e7fe706c` 差
0x7C；到槽 0 `0x75d7e7fe70fc` 差 0x10C；到槽 1 `0x75d7e7fe718c` 差 0x19C。
三个同类对象都落在这个候选块内，因此把它列为 **CS 通道块基址候选**（medium），
但还没有静态代码证明 `ctx+0x68` 就是该池的 owner。

## 5. 跨实例不变量

同一 pid 2052 的另一份采样（`docs/gamecore_view_buffer.md`）给出另一个 context：

| 项 | 早期实例 | 本次实例 | 关系 |
|---|---:|---:|---|
| context | `0x75d819773ff0` | `0x75d7e86e9ff0` | 不同实例 |
| `ctx+0x2B0` view 对象 | `0x75d8197bf5ec` | `0x75d7e87355ec` | 都是 **ctx+0x4B5FC** |
| view 对象 vtable | `0x75db20ca84e8` | 未抓取 | 早期实例实测；与 CS vtable 同簇 |
| CS 槽 0/1/2 cap | 32768/262144/32768 | 32768/262144/32768 | 完全一致 |
| CS 槽 0/1/2 pending | 8/24/0 | 8/76/0 | 随局内时刻变化 |

结论：**`ctx+0x4B5FC` 是可复现的相对布局**；地址、pending、vtable 的具体值不可
跨实例照抄。早期文档中的 `context+0x2b0 -> view object` 与本次完全一致，只是
实例地址不同。

## 6. 十人数组 / deskPool 搜索

### 6.1 扫描方法

1. 用快照的 512 个 qword 重建 context 的 0x0–0xFF8 原始字节；
2. 对每个 8 字节窗口、每个 16/32 位 lane，搜索 fixture 的 10 个 hero ID
   （175/109/167/140/196/199/123/141/153/156）和 10 个 entity ID
   （1168/1613/750/538/1611/1031/296/551/1799/1760）；
3. 对非 8 字节对齐的窗口重扫，防止漏掉 4 字节相位的指针；
4. 再把结果与 static 字符串/metadata、以及同进程早前的 entity 观测交叉核对。

### 6.2 结果

- 0x0–0xFF8 内**没有** 10 条 hero/entity 记录、没有 10 个连续指针的候选表。
- 16/32 位 lane 只有一处命中：`0x810` 低 32 位 = `0x9C` = 156（camp2 第 5 人
  英雄 156）。它落在编码 handle 的控制字里，前后没有同 stride 的 10 条记录，
  判为巧合，不是英雄表。
- `ctx+0x268..0x610` 的记录表约 39 条，数量不是 10；首条指向 arena 起点
  （ctx+0x64C），后续指向 arena 中散落的记录；性质是句柄/注册表，不是玩家表。

### 6.3 早前同进程的 entity 观测（未落盘复核）

`docs/gamecore_host.md` §3.5 与 `.workbuddy/memory/MEMORY.md` 记录（同一 pid
2052、同一 context `0x75d7e86e9ff0`）：

- `ctx+0x2C8` 的目标（本次快照 = `ctx+0x38A54`）在 `+0x19E0` 处出现
  **entity 1168**；
- `ctx+0x5E0` 的目标（本次快照 = `ctx+0x1DC9D50`）出现 **entity 1760/1799**。

本 fixture 的玩家块正是：

```text
camp1: 1168, 1613, 750, 538, 1611
camp2: 1031, 296, 551, 1799, 1760
```

其中 1168 是 camp1 order0，1799/1760 是 camp2 order3/order4。entity 命中与
fixture 完全对得上，因此这两个 handle 是 **十人/actor 数组的最强候选**。但：
- 观测只在文本里，没有保存子对象字节；
- 不知道 target+0x19E0 是单条记录、数组元素还是字符串/事件字段；
- 没有在该 target 里验证 10 条连续记录或 hero ID。

因此结论是：**候选成立但未证实**；不能写成“已找到十人数组”。

### 6.4 候选判定表

| 候选 | 证据 | 判定 |
|---|---|---|
| `ctx+0x2B0` | `PushViewBuffer/CommitViewBuffer` 直接读取；早期实例证实是 view/UI FIFO | 否决为“战斗状态十人数组”；它是 view/UI 通道 |
| `ctx+0x280` | 帧生产路径作为地址传给 `0x3D01F58`，后者读 `+0x30` | 否决为玩家表；是 tick 子结构 |
| `ctx+0x268..0x610` | 0x18 字节记录表；39 条；构造函数 fixup | 否决为十人数组；是句柄/注册表 |
| `ctx+0x2C8` | 目标+0x19E0 出现 fixture entity 1168 | **保留**：最强候选，需子对象 dump |
| `ctx+0x5E0` | 目标出现 fixture entity 1760/1799 | **保留**：第二候选，需子对象 dump |
| `base+0x52C3250` 八槽 | 槽 0/1/2 是 CS buffer，槽 3–7 不是 | 否决为十人数组；是 CS/view 通道池 |
| `deskPool` | C# `StartLevel` 参数；协议元素是 KV item（wKey/wValue） | 不是十人数组；是 53 条 Svr2GameCore KV |
| native `CPlayerCenter/CActorManager/CPlayerArr` | libGameCore 字符串存在（`TraversePlayerArray`、`CPlayerArrPooledPointer` 等） | 说明 native 玩家容器存在，但**没有**到 context 偏移的映射 |

### 6.5 deskPool 的定义

metadata 字符串（`data/replays/_analysis/global-metadata.dat`）：

```text
GameBuilderClientBase: inGameMode, inGameContext, inMessage, inDeskPool,
                       InitialPlayers, BuildPlayers, serverHeroInfo,
                       BuildCSharpPlayerHeroData, ...
SGW:                   gameModeType, deskPool, poolSize, StartLevel, ...
CSDT_DESK_SVR2GAMECORE_CONFIG:
    astGameCoreCfgItems_length, dwArrayNum, astGameCoreCfgItems_bytes
CSDT_DESK_SVR2GAMECORE_ITEM:
    wKey, wValue
```

结合 5.16.4/5.16.7：`deskPool` 的元素就是 `{wKey,wValue}`，与 `.abc` 头部的
53 条 Svr2GameCore KV 同构。**因此 deskPool 不是十人座位/玩家数组**，不能把
“十人 desk 条目”当作已证事实。native 侧虽存在 `GameDesk.cpp`、`GameDeskFilter`、
`PooledHandle constructor failed: SGameDesk is null` 等字符串，但没有证据表明
`SGameDesk` 池挂在 context 的哪个偏移。

## 7. 构造宿主 CLevelContext/deskPool 还缺什么

1. **对象身份**：live context 的类名未定。构造函数和方法表已按地址定位，但没有
   RTTI/字符串把它命名为 `CLevelContext`；不能把“context”直接等同于
   `CLevelContext`。
2. **构造函数签名/参数语义**：`0x40A0CA0` 至少使用 `w1, x2, w3, x4, w5, x6, w7`
   和栈参数（`w26=[sp+0x68]`），且调用多个全局回调；参数含义未解，不能安全调用。
3. **固定布局的完整字段表**：目前只证明了头部（0x00–0x28）、类 ID（0x78）、
   view 对象（0x2B0）、tick 子结构（0x280）、记录表（0x268–0x610）和若干分配；
   其余 0x30–0x23F 的字段没有语义。
4. **记录表目标内容**：`ctx+0x2C8` / `ctx+0x5E0` 目标没有落盘；十人数组是否存在、
   在 target 的哪个偏移、stride 多少，都未解。
5. **CS 通道类**：槽 0/1/2 的 vtable 是堆上的 `0x75db20ca8608`，没有静态 vtable/
   构造函数；`CommitCsBuffer` 需要的 `vtable+0x10` 实现只在 live 堆里。
   `ctx+0x68` 只是候选块基址，未证明是 owner。
6. **deskPool 的 native 形态**：C# 侧已清楚（KV item），native 侧 `SGameDesk` 与
   context 的链接无证据。
7. **S3 初始化命令流**：即使 context 能构造，`KV/443B/玩家块 → CS/TDR 命令流`
   仍是最大缺口（5.16.6、simulation_plan §3 S3）。

## 8. 最小下一步实验（只读）

**目标**：在不注入、不登录、不修改游戏文件的前提下，回答“十人数组在不在
`ctx+0x2C8`/`ctx+0x5E0` 的目标里”，并确认 context 类身份。

**做法**（扩展现有 `host/scripts/capture_context.py`，不改游戏/生产代码）：

1. 仍用 `--freeze`，在回放播放时抓同一 pid、同一 context；
2. 新增只读参数：
   - `--dump <addr>:<len>`：按绝对地址只读 dump（仅落盘 qword/hex，不写原始
     token/字符串）；
   - 至少 dump：
     - `ctx+0x1000 .. ctx+0x2000`（补齐 context 逻辑区外的相邻内容，若需要）；
     - `ctx+0x2C8` 目标 `ctx+0x38A54` 的 `0x2000..0x4000` 字节；
     - `ctx+0x5E0` 目标 `ctx+0x1DC9D50` 的 `0x2000..0x4000` 字节；
     - `ctx+0x2B0` 目标 `ctx+0x4B5FC` 的前 0x200 字节（验证 vtable 与
       `ctx+0x4B5FC` 不变量）。
3. 同时读静态槽（不依赖子对象）：
   - `base+0x4FFC268`（应等于 `base+0x40A0C94`）；
   - `base+0x4FFC270`、`base+0x51D1E58`（类方法表/工厂表锚点）；
   - `base+0x4FF5DE8`、`base+0x52488B8`、`base+0x52C3250`（CS 链）。
4. 在子对象 dump 上：
   - 搜索 10 个 fixture entity ID / hero ID；
   - 对命中点尝试 0x18/0x20/0x24/0x40/0x90 等 stride，找 10 条连续记录；
   - 记录每条记录的 offset、stride、ID 序列，区分“连续 10 条”与“散落引用”。

**验收**：
- 若在某个 target 找到 **10 条连续记录**，且 entity/hero 序列与 fixture 一致，
  则标记为十人数组候选，并给出 offset/stride/字段宽度；
- 若只找到散落 entity，则明确写“不是持久十人数组，是事件/actor 记录”；
- 若 `base+0x4FFC268 == base+0x40A0C94` 且 `ctx+0x78` 相同，则类身份假设成立；
- 若 view 对象仍在 `ctx+0x4B5FC` 且 vtable 与早期实例同簇，则跨实例不变量成立。

**不做**：
- 不伪造 vtable/上下文；
- 不把早期实例地址（`0x75d8197...`）套到本次 context；
- 不把 view buffer 当战斗状态；
- 不因为 `deskPool` 名字就假设十人数组。

## 附录 A：ctx+0x268..0x610 记录表（本次快照）

| ctx offset | q1 target | target 类型 | 备注 |
|---:|---:|---|---|
| 0x268 | 0x75d7e86ea63c | ctx+0x64c | 记录表后第一个 arena 对象 |
| 0x280 | 0x75d7ea4c5d28 | ctx+0x1ddbd38 | tick 子结构地址；+0x30 -> view 对象 |
| 0x298 | 0x75d7ea4c4000 | ctx+0x1dda010 |  |
| 0x2b0 | 0x75d7e87355ec | ctx+0x4b5fc | view/UI FIFO 对象 |
| 0x2c8 | 0x75d7e8722a44 | ctx+0x38a54 | 早前观测 entity 1168 @ target+0x19e0 |
| 0x2e0 | 0x75d7e7fe706c | external | CS 数组槽 2 对象 |
| 0x2f8 | 0x75d7e7ffd930 | external | CS pool 邻接 |
| 0x310 | 0x100000001 | non-pointer | 非 canonical，表中断点 |
| 0x328 | 0x75d7ea4d3da8 | ctx+0x1de9db8 |  |
| 0x340 | 0x75d7ea4d3d68 | ctx+0x1de9d78 |  |
| 0x358 | 0x75d7ea4de840 | ctx+0x1df4850 |  |
| 0x370 | 0x75d7e7fe726c | external | CS pool 邻接 |
| 0x388 | 0x75d7ea4d01b0 | ctx+0x1de61c0 |  |
| 0x3a0 | 0x75d7ea4d3140 | ctx+0x1de9150 |  |
| 0x3b8 | 0x75d7ea4cfbe8 | ctx+0x1de5bf8 |  |
| 0x3d0 | 0x75d7ea4c8178 | ctx+0x1dde188 |  |
| 0x3e8 | 0x75d7ea4d3e18 | ctx+0x1de9e28 |  |
| 0x400 | 0x75d7ea4d3210 | ctx+0x1de9220 |  |
| 0x418 | 0x75d7ea4c8100 | ctx+0x1dde110 |  |
| 0x430 | 0x75d7ea4c80b8 | ctx+0x1dde0c8 |  |
| 0x448 | 0x75d7ea4d3dc0 | ctx+0x1de9dd0 |  |
| 0x460 | 0x75d7ea4c7ca0 | ctx+0x1dddcb0 |  |
| 0x478 | 0x75d7ea4c7bc8 | ctx+0x1dddbd8 |  |
| 0x490 | 0x75d7ea4c7b48 | ctx+0x1dddb58 |  |
| 0x4a8 | 0x75d7ea4c7b18 | ctx+0x1dddb28 |  |
| 0x4c0 | 0x75d7ea4c7a18 | ctx+0x1ddda28 |  |
| 0x4d8 | 0x75d7ea4c78a0 | ctx+0x1ddd8b0 |  |
| 0x4f0 | 0x75d7ea4c7870 | ctx+0x1ddd880 |  |
| 0x508 | 0x75d7ea4c75d8 | ctx+0x1ddd5e8 |  |
| 0x520 | 0x75d7ea4c63d8 | ctx+0x1ddc3e8 |  |
| 0x538 | 0x75d7ea4c75a8 | ctx+0x1ddd5b8 |  |
| 0x550 | 0x75d7ea4c73a0 | ctx+0x1ddd3b0 |  |
| 0x568 | 0x75d7ea4c7138 | ctx+0x1ddd148 |  |
| 0x580 | 0x75d7ea4c6fb8 | ctx+0x1ddcfc8 |  |
| 0x598 | 0x75d7ea4c6f18 | ctx+0x1ddcf28 |  |
| 0x5b0 | 0x75d7ea4c77c0 | ctx+0x1ddd7d0 |  |
| 0x5c8 | 0x75d7ea4c7760 | ctx+0x1ddd770 |  |
| 0x5e0 | 0x75d7ea4b3d40 | ctx+0x1dc9d50 | 早前观测 entity 1760/1799 |
| 0x5f8 | 0x75d7ea4c6238 | ctx+0x1ddc248 |  |
| 0x610 | 0x75d7ea4b3c50 | ctx+0x1dc9c60 |  |

## 附录 B：依据

- `docs/replay_binary_format.md` 5.15–5.23（GameCore 宿主化/CS FIFO/帧循环）、
  5.36（回放只有输入，不含状态快照）；
- `docs/gamecore_host.md` §3.5（H4 快照与 entity 观测）；
- `docs/simulation_plan.md` §2/§3（链、S3 缺口、停止规则）；
- `docs/gamecore_view_buffer.md`（早期 context 实例的 view 对象与 CS 槽）；
- `docs/frapinfo_live.md` §6.5（pid 2052 FrameWindow 解析）；
- `docs/advance_frame_binding.md`（`GameLogicHelper.AdvanceFrameCommands` 入口与 1..27 类型分派；不改变本文字段结论）；
- `data/replays/_analysis/libGameCore.so` 静态反汇编（capstone）：
  `0x40A0CA0`、`0x40A0F40`、`0x46B7888`、`0x3D01F58`、`0x46B7F9C`、
  `0x46B7FF0`、`0x460A3AC`、`0x460A3E4`、`0x49CBF98`、`0x49CBFFC`、
  `0x43D301C`；
- `data/replays/_analysis/global-metadata.dat` 字符串：
  `deskPool`、`inDeskPool`、`CSDT_DESK_SVR2GAMECORE_CONFIG`、
  `CSDT_DESK_SVR2GAMECORE_ITEM`、`wKey`、`wValue`；
- `data/replays/_analysis/libGameCore.so` 字符串：
  `CPlayerCenter`、`CActorManager`、`CPlayerArr`、`CPlayerArrPooledPointer`、
  `TraversePlayerArray`、`SGameDesk`、`GameDesk.cpp`、`GameDeskFilter`；
- `data/replays/_analysis/datasets/gamecore_context_field_map.csv`（逐字段表）。
