# AdvanceFrameCommands：27 类命令的真实处理入口与 payload 读取

日期：2026-11-03。基于 11/2 回放上下文、MuMu Android 15、build 5247758。
只读 ADB 探针 + 本地 libil2cpp 反汇编；没有注入/调用游戏函数。

## 1. 调用链

```text
GameLogicHelper.AdvanceFrameCommands(thunk, file 0x6e04fa4)
  -> [0x40003374bb68] = 0x40002c84cf7c (file 0x664bf7c)
     x20 = frapInfo
     w19 = frameNo
     w8  = [frapInfo+0xc]      命令数量
     x0  = [frapInfo+0x10]     命令数组
     for i in 0..count-1:
       cmd = array_get(x0, i)
       type = [cmd+0xc]        1..27
       switch type -> 27 项跳表
         -> type handler
         -> processing function (below)
```

`frapInfo+0x24` 还保存一个序号/帧值；实现会把 `w24` 与 `frameNo` 比较。
命令对象 `cmd+0x10` 是具体 payload/命令对象。

## 2. 每个类型的处理入口

跳表之后，每个 type handler 会跳到自己的 processing function。以下是
本次运行读出的 20 个非默认/非跳过类型：

| type | processing runtime | file off | 观察到的 payload 读取 |
|---:|---|---:|---|
| 1 | `0x40002c84dc4c` | `0x664cc4c` | `cmd+0x10` 子对象；读 `u16 [+0xc]`，数据从 +0x10 |
| 2 | `0x40002c84de28` | `0x664ce28` | `cmd+0x10` 子对象；读 `u16 [+0xc]`，数据从 +0x10 |
| 3 | `0x40002c84df34` | `0x664cf34` | `cmd+0x10` 子对象；多段处理 |
| 4 | `0x40002c84dff4` | `0x664cff4` | `cmd+0x10` 子对象；多段处理 |
| 5 | `0x40002c84e0b4` | `0x664d0b4` | `cmd+0x10` 子对象；`u8 [+0xc]` |
| 6 | `0x40002c84e320` | `0x664d320` | `u8 [cmd+0xc]` |
| 7 | `0x40002c84e40c` | `0x664d40c` | `cmd+0x10` 子对象；`u32 [+0x10]`；`u8 [+0xc]`、`u8 [+0xd]` |
| 8 | `0x40002c84e66c` | `0x664d66c` | `u8 [cmd+0xc]`, `u8 [cmd+0xd]` |
| 9 | `0x40002c84e580` | `0x664d580` | `u8 [cmd+0xc]` |
| 11 | `0x40002c84f2a4` | `0x664e2a4` | `u32 [cmd+0x10]`, `u32 [cmd+0x14]` |
| 14 | `0x40002c84eac4` | `0x664dac4` | `ptr [cmd+0x18]` |
| 16 | `0x40002c84ec74` | `0x664dc74` | `u8 [cmd+0xc]` |
| 17 | `0x40002c84ed60` | `0x664dd60` | `u32 [cmd+0xc]`, `u32 [cmd+0x10]` |
| 18 | `0x40002c84ee48` | `0x664de48` | `u16 [cmd+0xc]` |
| 19 | `0x40002c84ef20` | `0x664df20` | `u8 [cmd+0xc]` |
| 20 | `0x40002c84effc` | `0x664dffc` | `u8 [cmd+0xc]`, `u16 [cmd+0xe]` |
| 22 | `0x40002c84f394` | `0x664e394` | 复杂分支 |
| 23 | `0x40002c84f1b4` | `0x664e1b4` | `u32 [cmd+0x10]`, `u32 [cmd+0x14]` |
| 24 | `0x40002c84f0dc` | `0x664e0dc` | 复杂分支 |
| 27 | `0x40002c84e9a4` | `0x664d9a4` | `cmd+0x10` 子对象：`u32 +0xc/+0x10/+0x14` |

type 10/12/13/26 走默认分支，15/21/25 直接跳过；它们的 payload 不在这里展开。

## 3. 已解析出的类型名（2026-11-03 实机）

从每个 type handler 的类指针 `[0x400034067000+offset]` 读 `Il2CppClass`，
再读 `+0x10` 类名指针（`+0x18` 是 namespace），已经确定：

| type | class |
|---:|---|
| 1 | `CSProtocol.CSDT_FRAPBOOT_CC` |
| 2 | `CSProtocol.CSDT_FRAPBOOT_CS` |
| 5 | `CSProtocol.CSDT_FRAPBOOT_AISTATE` |
| 18 | `CSProtocol.CSDT_FRAPBOOT_PLAYER_MOVE` |
| 19 | `CSProtocol.CSDT_FRAPBOOT_PLAYER_ATTACK` |
| 20 | `CSProtocol.CSDT_FRAPBOOT_PLAYER_ATTACKWITHOBJ` |

这与 `.abc` 的帧命令完全对上：type18 是 move、type19 是 attack、
type20 是 attackwithobj；type1/2/5 是 CC/CS/AISTATE 帧头。

其余 type 的全局槽目前是小型 metadata token（`0x2001df4d` 等），不是
`Il2CppClass*`，还需要通过 metadata 类型表解码；不要把它们当成未知新类型。

## 4. 这份表怎么用

- 27 个 type 是 `frapInfo` 的命令类型，不是 TDR `CSSYNC` selector；
- 每个 type 的 payload 读取偏移现在可以直接和 `.abc` 的
  `FRAME_CMD_INFO`/`CSDT_FRAPBOOT_*` 字段表对照；
- 目前字段名还没绑定到具体命令（Move/Touch/SkillUse/…），下一步是把
  processing function 里调用的子函数/字段偏移与 metadata 里的
  `FRAME_CMD_INFO` 成员对齐；
- 这张表只对 build 5247758 本次 libil2cpp 有效，换构建要重新捕获/反汇编。

## 5. 复现

```bash
python tools/advance_frame_dispatch.py
python tools/advance_frame_bind_probe.py \
  --serial 127.0.0.1:16384 \
  --capture-dir data/replays/_analysis/client_probe_20261103/bind_live_<new>
```

设备侧只读；不使用 Frida、不注入、不调用游戏函数。
