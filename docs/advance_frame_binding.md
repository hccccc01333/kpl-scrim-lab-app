# AdvanceFrameCommands 实机绑定：thunk、实现与命令跳表

日期：2026-11-03。样本：MuMu Android 15，王者 App 12.1.1.1 / Res 12.1.1.26，
11/2 第一局回放。只读 ADB root 探针，不注入、不调用游戏函数、不修改文件。

## 1. 探针命中

回放上下文（`client_probe_20261103/bind_live_20261103_replay1b/`）稳定命中：

| 方法 | token | methodinfo |
|---|---|---|
| `GameLogicHelper.AdvanceFrameCommands` | `0x6006bcb` | `0x74cce8c4f948` |
| `FrameWindow.HandleFraqBootSingle` | `0x6008e07` | `0x74ccea9cc868` |
| `FrameWindow.HandleFraqBootInfo` | `0x6008e16` | `0x74ccea9ccd90` |
| `CSDT_FRAPBOOT_INFO.unpack` | `0x600e874` | `0x74ccec13e578` |

`FrameWindowHelper.AdvanceFrameCommands` 未加载；`IGameLogicHelper` 接口方法
没有独立 MethodInfo。离线 5v5 与回放都只加载 GameLogicHelper 实现，因此当前
证据更支持 **GameLogicHelper.AdvanceFrameCommands 是实际帧推进入口**。

## 2. GameLogicHelper 是 thunk

方法指针 `0x40002d005fa4` 对应的代码页首部：

```text
adrp x8, #0x40003374b000
mov  w0, w1
mov  x1, x2
mov  x2, xzr
ldr  x3, [x8, #0xb68]
br   x3
```

它把 `(frameNo, frapInfo)` 转发到全局指针 `[0x40003374bb68]`。本次运行读到：

```text
target = 0x40002c84cf7c   (libil2cpp 文件偏移 0x664bf7c)
```

因此 `GameLogicHelper.AdvanceFrameCommands` 本身只是共享泛型/转发 thunk；
真实实现是 **0x40002c84cf7c**。

## 3. 真实实现的 frapInfo 布局

反汇编 `0x40002c84cf7c`：

```text
x20 = frapInfo (x1)
w19 = frameNo  (w0)
w24 = [x0+0x24]           ; 当前帧/序号
w8  = [frapInfo+0xc]      ; 命令数量 (u8)
x0  = [frapInfo+0x10]     ; 命令数组/list
循环 w23 = 0 .. w8-1:
  x0 = array_get(x0, w23)
  x1 = x0
  w8 = [x0+0xc]           ; 命令类型 (u8, 1..27)
  switch w8:
    1..27 -> 跳表
```

命令对象：

```text
+0x0c  u8   type (1..27)
+0x10  ptr  payload/具体命令对象
```

跳表：

```text
adr  x9, #0x40002c84d03c
ldrh w10, [x27, x8, lsl #1]   ; 27 项 u16
add  x9, x9, w10, lsl #2
br   x9
```

## 4. 27 项分派表

`data/replays/_analysis/datasets/advance_frame_dispatch.csv` 已生成：

- 类型 **1–9、11、14、16–20、22–24、27**：独立 handler；
- 类型 **10、12、13、26**：走默认分支 `0x40002c84d03c`；
- 类型 **15、21、25**：直接跳过 `0x40002c84d050`。

handler 地址从 `0x40002c84d064` 起，每个类型间隔约 0x40 字节；它们先做
metadata class/type 检查，再进入实际处理分支。字段语义尚未命名，不能把
type 号直接当 TDR selector；下一步要把每个 handler 的尾部处理函数与
`FRAME_CMD_INFO`/`CSDT_FRAPBOOT_*` 字段表对上。

## 5. 复现

```bash
python tools/advance_frame_dispatch.py
```

脚本读取本地 `libil2cpp.so` 的跳表，输出 27 类型映射；运行时 thunk 目标
需要设备只读捕获（本次地址已记录，不是跨版本常量）。

## 6. 边界与下一步

- 设备侧仍只读；没有注入、没有调用游戏函数。
- 真实实现地址与跳表是 build 5247758 的本次实例证据；换构建要重新捕获。
- 下一步：
  1. 反汇编每个 handler 的尾部，找它调用的 `FRAME_CMD_INFO` 处理函数；
  2. 用 `.abc` 的已知 TLVs（1075/1076/1077）与 `replay_frame_commands` 对拍，
     把 type 1..27 映射到具体命令；
  3. 在同一回放帧重复 seek，比较 `frapInfo` 的命令数/类型序列是否确定；
  4. 只有完成 N→N+1 命令序列预测，才把 G4/G5 视为通过。
