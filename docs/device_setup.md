# 设备恢复与 AdvanceFrameCommands 绑定指引

目的：恢复 MuMu/ADB 环境后，沿 docs/replay_binary_format.md §5.126 已定位的调用链
绑定 `IGameLogicHelper.AdvanceFrameCommands`，打通引擎侧帧模拟（真值轨迹/血量/经济
的唯一完整路径）。本指南只覆盖环境准备与只读观测点，不包含任何游戏逻辑修改。

## 1. 环境准备（用户操作）

1. 安装 MuMu 模拟器 12（Android 12+，prior 会话为 Android 15 实例 0）。
   - ADB 端口：MuMu 12 默认 `127.0.0.1:16384`（多实例依次 +2）。
   - 验证：`adb connect 127.0.0.1:16384 && adb devices`。
2. 安装王者荣耀（`com.tencent.tmgp.sgame`），登录账号并更新到与本地样本一致的
   版本（样本资源版本 12.1.1.26，build 5247758；版本不一致时 §5.125 的协议
   selector 映射需按当前构建重跑）。
3. 校准库文件一致性（md5）：
   - `libil2cpp.so` = `43bc62bd0947e10a0ccf2ff1ac23cdd9`
   - `libGameCore.so` = `133db4411e77ed2af567a4a3bbd3dc6a`
   - 不一致则 §5.126 的 RVA 全部失效，需重跑 `tools/client_replay_system.py`。

### 2026-11-03 实机状态（只读）

- MuMu：`D:\MuMuPlayer\nx_main\MuMuNxMain.exe`，实例 0，Android 15；
- ADB：`127.0.0.1:16384`，`adb root` 后 `uid=0`；
- 游戏：`com.tencent.tmgp.sgame` App `12.1.1.1` / Res `12.1.1.26`；
  已进入**离线 5v5 对局**（隐私协议由用户授权点击，未登录账号）；
- 只读探针（96 MiB 上限，读取 66.5 MiB 主 region）：
  `data/replays/_analysis/client_probe_20261103/bind_live_20261103_ingame3/`
  - `FrameWindow.HandleFraqBootSingle` token `0x6008e07`，params=2，
    pointer `0x40002bef047c`，磁盘 raw 4096/4096；
  - `FrameWindow.HandleFraqBootInfo` token `0x6008e16`，params=2，
    pointer `0x40002bef44fc`，磁盘 raw 4096/4096；
  - `GameLogicHelper.AdvanceFrameCommands` token `0x6006bcb`，params=2，
    methodinfo `0x74cce8c4f948`，pointer `0x40002d005fa4`，
    XOR 解码页 4004/4096；
  - 未命中：FrameWindowHelper.AdvanceFrameCommands、IGameLogicHelper 接口、
    CSDT_FRAPBOOT_INFO.unpack。离线 5v5 没有 JIT touched 这些 replay 专用路径。
- 结论：设备/ADB/只读探针链路已打通，离线 5v5 的帧分发与
  `GameLogicHelper.AdvanceFrameCommands` 已定位；要补齐 replay 专用方法，
  需要进入回放上下文，或后续做同帧 seek/内存 watch。未登录、未注入。
- 2026-11-03 回放上下文补充：11/2 第一局已放进
  `Replay/` 根目录并在客户端打开；探针新增
  `CSDT_FRAPBOOT_INFO.unpack` token `0x600e874`（4/6 命中）。
  `FrameWindowHelper.AdvanceFrameCommands` 仍未加载，`IGameLogicHelper`
  接口方法也没有独立 MethodInfo；结合离线 5v5 与回放都命中
  `GameLogicHelper.AdvanceFrameCommands`，当前证据更支持
  **GameLogicHelper 是实际实现**，FrameWindowHelper 是未加载的备选。
  抓取目录：`client_probe_20261103/bind_live_20261103_replay1b/`。
- 2026-11-03 进一步：`GameLogicHelper.AdvanceFrameCommands` 是 thunk，
  真实实现在 `0x40002c84cf7c`（文件偏移 `0x664bf7c`）；`frapInfo+0xc` 是命令数、
  `+0x10` 是命令数组，命令 `+0xc` 是 1..27 类型，按 27 项跳表分派。
  详见 `docs/advance_frame_binding.md`、`docs/advance_frame_commands.md` 与
  `datasets/advance_frame_dispatch.csv`。
- 2026-11-03 live frapInfo 负结果：被动扫描未找到有效对象；`HandleFraqBootInfo`
  内 `frapInfo` 生命周期只有一次调用，帧间采样看到的是回收内存。FrameWindow
  900 槽 ring 只有空实例（current=1, nonnull=0），更像批量 FRAPBOOT 路径。
  详见 `docs/frapinfo_live.md`；在没有持久 ring/buffer 或断点级观测前，
  不要继续被动扫描 N+1。

## 2. 只读观测点（§5.126 已定位，RVA 为文件内 VA）

| 步骤 | 目标 | 位置 |
|---|---|---|
| 1 | 回放启动：`GameReplayModule.BeginReplay` → `LoadMsg` | 0x6657ac4 / 0x6657bb0 |
| 2 | 逐帧分发：`FrameWindow.HandleFraqBootSingle` | 0x5cf047c |
| 3 | 帧缓冲解包：CLASS_ID 4454（CSDT_FRAPBOOT_INFO）经共享 TDR 适配器 | 槽 0xd6f9138 → 0xa329790 |
| 4 | 引擎交接：`IGameLogicHelper.AdvanceFrameCommands(frameNo, frapInfo)` | 接口索引 53，token 0x60083ab |
| 5 | 待绑定目标：AdvanceFrameCommands 的**实际实现**（FrameWindowHelper token 0x6002afe / GameLogicHelper token 0x6006bcb 二选一） | 本轮待观测 |

观测方式沿用 prior 会话的 frida 只读捕获（MethodInfo 身份校验 + 内存读取，
不调用、不修改游戏函数；规则见 §5.101-5.126 的证据等级约定）。

## 2.5 就绪探针（设备恢复后第一步）

```powershell
python tools/advance_frame_bind_probe.py --capture-dir data/replays/_analysis/client_probe_<日期>/bind_live
```

复用 live_replay_methods 的只读捕获原语，TARGETS 扩展到两个实现候选
（FrameWindowHelper / GameLogicHelper 的 AdvanceFrameCommands，token
0x6002afe / 0x6006bcb）+ 接口 + HandleFraqBootInfo/4454 解包锚点；捕获的
代码页按 XOR 0xE3 解码并与 libil2cpp.so 磁盘副本逐字节核对（建立会话内
基址验证）。解码产物写 `decoded/`（summary.json 含每方法磁盘核对结果）。

**离线验证已通过**：用 prior 会话保存的真实 metadata
（client_probe_20261102/frame_commands_live/metadata.bin）离线运行
TARGETS 派生，6 个目标全部命中——FrameWindowHelper.AdvanceFrameCommands
token 0x6002afe、GameLogicHelper.AdvanceFrameCommands token 0x6006bcb、
接口 IGameLogicHelper token 0x60083ab（params=2）、HandleFraqBootSingle/
HandleFraqBootInfo/CSDT_FRAPBOOT_INFO.unpack。设备恢复后首次运行即可
按名扫描定位这些方法。

## 3. 绑定 AdvanceFrameCommands 的判别实验

1. 在接口调用点（0x5cf46d0 附近）hook 实参：`frameNo` 与 `frapInfo` 对象指针。
2. 对同一回放 seek 到同一帧重复播放两次，比较 `frapInfo` 内容——确定性要求。
3. 捕获 `AdvanceFrameCommands` 实际实现入口后，与 §5.126 的
   `frame_commands_live/` 下已保存的 29 条 MethodInfo 交叉核对。
4. 成功判据：给定 .abc 的帧 N，能独立预测引擎在帧 N+1 接受的命令列表
   （与 `tools/replay_frame_commands.py` 的解码输出一致）。

## 4. 产出物

- 绑定结果写入 `docs/replay_binary_format.md`（新 § 节，沿用证据等级约定）。
- 引擎侧帧模拟器原型：输入 .abc → 输出逐帧真值状态（位置/血量/经济）。
- 与 §5.132 的方向积分阴性结果对拍：引擎真值 vs 积分形状的偏差量化。

## 5. 约束

- 未登录、未注入游戏逻辑、未修改设备游戏文件的操作不做（沿用 §5.101+
  的会话约束）。
- 版本不匹配时先重跑 selector 映射与类清单，不沿用旧 RVA。
