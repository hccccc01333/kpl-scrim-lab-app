# 客户端回放系统静态盘点（2026-11-02）

本轮按“把客户端回放系统搬出来”的路线，启动 MuMu、连 ADB、核对 native 库，
并从当前 IL2CPP metadata 生成回放系统的类/字段/方法清单。**没有注入游戏进程、
没有修改游戏文件、没有登录、没有调用游戏内部函数。**

## 1. 设备与取证

| 项 | 值 |
|---|---|
| 模拟器 | MuMu Android 15，实例 0 |
| ADB | `127.0.0.1:16384` |
| 包名 | `com.tencent.tmgp.sgame` |
| versionName / versionCode | `12.1.1.1` / `1201010103` |
| primaryCpuAbi | `arm64-v8a` |
| base.apk | `/data/app/~~_8xoTLmbblrfQ9PSEVAonw==/com.tencent.tmgp.sgame-A5YyjZqtIenxEvDTBeKtGw==/base.apk` |
| base.apk 大小 | 1,748,020,380 B |

`base.apk` **没有整包拉取**：D 盘只剩 1.1 GB，小于 APK 的 1.75 GB；而回放系统
真正执行的代码在 `libil2cpp.so` / `libGameCore.so`，这两份本地已有，且与设备
md5 完全一致：

| 库 | 本地 md5 | 设备 md5 |
|---|---|---|
| `libil2cpp.so` | `43bc62bd0947e10a0ccf2ff1ac23cdd9` | 同左 |
| `libGameCore.so` | `133db4411e77ed2af567a4a3bbd3dc6a` | 同左 |

设备 `Replay/` 已只读拉到 `data/replays/_analysis/client_extract_20261102/Replay`；
清单和 SHA-256 在 `client_extract_20261102/manifest.json`。设备上的
`Replay/AutoSave` 仍是 10-28、10-30 两份旧样本；用户提供的 11-02 两局不在
设备上，已经另外归档在 `data/replays/samples/`。

## 2. 回放系统类图

`data/replays/_analysis/client_extract_20261102/replay_system.json` 是完整清单。
关键类与职责：

| 类 | 规模 | 职责 |
|---|---|---|
| `GameReplayModule` | 52 字段 / 104 方法 | 回放主模块：录制、回放、seek、流式、恢复 |
| `ReplayFileInfo` | 12 字段 | 回放列表/头部信息：path、heroId、startTime、mapType、mapId、userName、userHead、rank、totalFrameNum |
| `BeginReplayParam` | 6 字段 | `Path`、`ViewMode`、`SelectPlayerIndex`、`SeekFrame`、`MultiThreadSeek`、`CheckVersion` |
| `stReplayHeadOutParam` | 3 字段 | `totalFrameNum`、`guideInfoPlayerMobaLevel`、`guideInfoHasRelateOpenID` |
| `ReplayMsgType` | 5 字段 | `Default` / `Streaming` / `ShareMem` / `TotalNum` |
| `ReplayControl` | 55 字段 / 69 方法 | 回放 UI：进度条、倍速、关键事件点、追帧 |
| `ReplayMemoryRecover` | 2 字段 / 16 方法 | `.csd/.dmg` 恢复：`SaveRecovery`、`PrepareReplayRecover`、`MultiPlayerReplayRecover`、`DeleteDmgFileBeyondFrameNum` |
| `CAutoReplayManager` | 28 字段 / 44 方法 | 自动回放/流式/共享内存/AI server 路径 |
| `QuickReplaySystem` | 21 字段 / 25 方法 | 快速回放/分享 |
| `CReplayKitSys` | 5 字段 / 15 方法 | 回放工具/录制套件 |

`GameReplayModule` 的关键字段：

```text
recordStream / recordWriter        录制写入流
replayStream / replayReader        回放读取流
m_replayMsgLoader                  回放消息加载器
m_getStreamingReplayData           流式回放数据入口
streamBuffer / bufferUsedSize      读取缓冲
replayAbsHeader                    回放绝对头
m_replayHeadOutParam               totalFrameNum 等输出头
m_dumpSeekNoList                   seek 点列表
endKFraqNo / m_totalFrameOffset    帧号/偏移
HostPlayerIndex / HostPlayerId     主视角玩家
streamPath                         当前回放路径
```

## 3. 录制/写入路径

方法名按职责分组：

```text
BeginMultiRecord / BeginSingleRecord   建立 recordStream/recordWriter
AutoSaveRecord / HistoryAutoSaveRecord 选择自动保存/历史保存路径
FlushRecord                            落盘
WriteStreamReplayData                  流式回放写入
GetStreamPath / GetNonAutoSaveStreamPath / GetRecordDeskIdStr / GetRecordOpenIdStr
DeleteOldRecordFile / DeleteOldFile    清理旧回放
OnFightOver                            对局结束钩子
```

这条路径解释 `.abc` 为什么是“输入记录 + 末尾 MVP 评分”：

- `recordWriter` 写的是 signed i32 长度记录：负数 CSPkg、正数帧记录；
- 1075 开局、1077 开战、帧记录来自战斗过程；
- 1251 是 `SCPKG_GAMEOVER_MVPSCORE`，在 `OnFightOver` 附近写入，用于回放列表
  展示胜方/败方 MVP 和十人评分；
- 完整结算 `SCPKG_GAME_OVER_RSP`（1082）不在 `GameReplayModule` 的
  record/ replay 字段和写方法里，属于战斗结算/网络消息路径，不进入这条
  回放记录流。

注意：这一节的 1082 判断是“文件级已确认 + 类/方法结构推断”；`AutoSaveRecord`/
`OnFightOver` 的逐指令写入顺序仍需下一轮反汇编确认。

## 4. 回放/读取路径

```text
BeginReplay(BeginReplayParam)
  -> GameReplayModule_BeginReplay
  -> CheckReplayVersion / SkipReadReplayHead
  -> GetBeginLoadMsg / RetriveBeginLoad
  -> BattleStart
  -> UpdateFrame
       -> LoadMsg / LoadDefaultMsg / SLoadDefaultMsg
       -> Handle / HandleSinglePkg
       -> HandleFrapBoot -> FrameWindow -> AdvanceFrameCommands
  -> OnFightOver
```

对应关系：

| `.abc` 部分 | 客户端侧 |
|---|---|
| 头部（版本、build、localHero、map、user、rank、totalFrameNum） | `ReplayFileInfo`、`CheckReplayVersion`、`SkipReadReplayHead`、`stReplayHeadOutParam` |
| 1075 开局包 | `GetBeginLoadMsg`、`RetriveBeginLoad`、`SLoadDefaultMsg`、`HandleSinglePkg` |
| 1077 开战包 | `Handle`、`HandleSinglePkg`、`BattleStart` |
| 帧记录流 | `LoadMsg`、`UpdateFrame`、`HandleFrapBoot`、`FrameWindow`、`AdvanceFrameCommands` |
| 1251 MVP 评分包 | `SLoadDefaultMsg`/`HandleSinglePkg` 读取；`OnFightOver`/`AutoSaveRecord` 写入 |
| 1082 完整结算 | 不在这条 record/replay 流里；是 `SCPKG_GAME_OVER_RSP` 网络消息 |
| `.ope` | 本地操作流，走 OperatorMonitor，不是 `GameReplayModule` 的记录流 |
| `.csd/.dmg` | `ReplayMemoryRecover` 的恢复快照，不是 `.abc` 统计区 |

### 4.1 记录流语法

`tools/replay_record_stream.py` 与 `SLoadDefaultMsg` 的结构一致：

```text
signed i32 LE length
  负数 -> CSPkg，长度 = abs(length)
  正数 -> 帧记录，前 6B = BE u32 序号 + BE u16 内容长度
```

这解释了两局 `.abc` 的完整消费：

```text
1075 -> 1077 -> 帧记录 1..N -> 1251
```

顶层包边界零缺口，帧记录序号连续。

### 4.2 运行时读取链路：已解到泛型共享入口（2026-11-02 第二轮）

静态文件里的关键槽位是 0，必须用运行时内存。本轮补了一份**完整**
libil2cpp 映射 dump：

```text
data/replays/_analysis/runtime_dump_full/
  memory.bin       434.3 MiB
  manifest.json    8 个映射段，含之前 --skip-text 漏掉的 151.9 MiB r--p 区
```

从运行时槽位读出的结果：

**（a）`HandleFrapBoot` 是帧命令分发器**

`0x645eb54` 读取 `[x0+0x135]` 的 24 位 flags（`ldrh + ldrb + bfi`），
按位检查后调用四个静态槽位。回放/战斗状态 dump 中这些槽位指向：

```text
FrameWindowHelper::HandleServerClientSyncCommand
FrameWindowHelper::HandleServerInGameItemUseCommand
FrameWindowHelper::HandleClientStateSyncCommand
FrameWindowHelper::HandleAssistChgSyncCommand
```

这与 `CSDT_FRAPBOOT_INFO` 的 CS/CC/ACNTSTATE/ASSISTSTATE 分支方向一致。
**注意：这些槽位是状态相关的**。登录页状态下同一地址会指向
`CTrainingHelperPnlTypeV121View`/`HonorItemView`/`EmojiItemView` 等 UI 类，
所以不能在登录页 dump 上做回放语义判断。

**（b）`LoadMsg` / `SLoadDefaultMsg` 的尾跳是泛型共享入口**

- `SLoadDefaultMsg`（0x645d3b4）前 0x54 字节是静态初始化 + `br x2`，
  `x2` 来自槽位 `0xd8d4670`。回放状态 dump 值为 `0x400032ed9d00`；
  该地址**不是函数开头**，而是泛型共享函数的中间入口：
  代码从 `ldr x23,[x24]` / `ldr x25,[x22,#0x38]` 开始，没有标准 prologue。
- `LoadMsg`（0x645d1cc）先调槽位 `0xd8d4678`（回放状态值
  `0x400032ed9dfc`），该地址是 `b 0x400032ed9d58`，同样跳进这个
  泛型共享函数。
- 该共享函数使用 `x22` 作为消息/上下文对象，读取 `[x22+0x38]`、
  `[x25+0x20]` 等字段，并调用 `0x400031ce1460` / `0x400031ce14fc`
  两个共享辅助函数。当前没有方法表名字能对上，说明它不是普通
  `MethodInfo` 入口，而是 **generic sharing / 共享桩**。

**（c）`HandleSinglePkg` 的槽位同样是状态相关**

`0x645ece4` 读取 `[0xde85240]` 后调 `[0xd53e3b8]`。回放状态 dump 中该槽位
指向 `FrameWindowHelper::HandleAIChgSyncCommand` 候选；登录页状态下
指向一个 2 指令 setter（`str w1,[x0,#8]; ret`）。因此这个槽位只能
在回放/战斗状态取。

**（d）`RetriveBeginLoad` 的 Miniz 候选**

回放状态 dump 中 `RetriveBeginLoad` 的槽位 `0xd4e4430` 解析到
`UGC.Miniz::uncompress` 候选；但两局 1075 payload 的 zlib/raw-Deflate
扫描均为 0 命中，说明：
- Miniz 调用可能作用于一个**嵌套/长度前缀的子 buffer**，不是整个 1075；
- 或者该槽位在登录页/回放状态下指向不同函数，名字不能直接外推。

**本轮结论**：读取链路已经从“方法名列表”推进到实际机器码和运行时槽位，
`HandleFrapBoot` 的分发方向、`LoadMsg`/`SLoadDefaultMsg` 的泛型共享入口
都已定位。下一道墙是 **generic sharing 桩 + 状态相关槽位**：
必须在回放/战斗状态下取槽位，并对共享函数入口做寄存器/参数跟踪，
不能再用登录页 dump 的槽位值。

## 5. 1251 与 1082

| | 1251 | 1082 |
|---|---|---|
| 类 | `SCPKG_GAMEOVER_MVPSCORE` | `SCPKG_GAME_OVER_RSP` |
| 字段 | `dwWinMvpObjID`、`stMvpScoreDetail`、`iLoseMvpObjNum`、`LoseMvpObjList` | `stResultInfo`、`stDetail`、`stAcntInfo`、`bPressExit` |
| 语义 | 胜方 MVP、十人评分、败方 MVP 列表 | 完整结算/面板 |
| 在 `.abc` 中 | 是，末尾 109 B | 否，30 份样本均无合法 1082 包 |
| 客户端职责 | 回放列表预览；`OnFightOver`/`AutoSaveRecord` | 战斗结算/网络响应；不是 `GameReplayModule` 的记录内容 |

`1251` 的 109 B 已经能按字段对齐：`dwWinMvpObjID`（胜方 MVP）、
10×8 B `stMvpScoreDetail`、`iLoseMvpObjNum=1` + `LoseMvpObjList`（败方 MVP）。
两局新样本的胜方/败方 MVP 与评分表一致，胜负可由该包反推。

`1082` 的字段表来自当前 metadata；回放文件里没有它的实例。它的存在说明
“完整面板的 schema 在哪”，不说明“回放文件写了它”。

## 5.1 公开研究对照（2026-11-02）

| 来源 | 关键证据 | 与本项目对照 |
|---|---|---|
| `Moli13337/Honor-of-Kings-protocol` | `tdr_xml/wzry_pkg.xml`：1075 `SCPKG_MULTGAME_BEGINLOAD`、1077 `SCPKG_MULTGAME_BEGINFIGHT`、1082 `SCPKG_GAME_OVER_RSP`、1251 `SCPKG_GAMEOVER_MVPSCORE`、1252 `SCPKG_WEARING_INFO_NTF` | 独立确认消息号/类名 |
| 同上 `proto/wzry_sc_response.proto` | `SCPKG_GAME_OVER_RSP { stResultInfo=1; bPressExit=2; COMDT_SETTLE_RESULT_DETAIL stDetail=3; stAllAcntDetail=4; }`；`SCPKG_GAMEOVER_MVPSCORE { dwWinMvpObjID=1; dwLoseMvpObjID=2; COMDT_MVP_SCORE_DETAIL stMvpScoreDetail=3; }` | 确认完整结算/评分包的字段家族；当前 metadata 把败方 MVP 改成 `iLoseMvpObjNum/LoseMvpObjList` |
| 同上 `proto/wzry_csdt.proto` | `CSDT_FRAPBOOT_CC/_CS/_ACNTSTATE/_ASSISTSTATE/_AISTATE/_GAMEOVERNTF(bWinCamp)/_PAUSE` | 与 `HandleFrapBoot` 的 CS/客户状态/助攻/AI 分发方向一致；`bWinCamp` 是 FRAPBOOT 里的显式胜负字段 |
| `ihaiucom/wangzhe.WangZheDllCode` 旧版 `GameReplayModule.cs` | 头部 11 字段；记录用 **signed int16** 长度，正数 `CSDT_FRAPBOOT_INFO`、负数 `CSPkg`；`CacheRecord` 只在 `dwMsgID==1075` 时 `BeginRecord`；`UpdateFrame` → `FrameWindow.HandleFraqBootInfo` / `DirectHandleMsg`；`FlushRecord` 追加 `CSDT_FRAPBOOT_INFO(dwKFrapsNo=endKFraqNo, bNum=0)` | 确认读写方向和 1075 语义；旧版是 i16，**当前 5247758 是 i32**，不能直接套宽度 |
| 同上 `COMDT_MVP_SCORE_DETAIL` / `COMDT_MVP_SCORE_INFO` | `bAcntNum` + `astMvpScoreDetail[10]`；每项 `dwObjID:u32 + iMvpScoreTTH:int` = 8 B | 精确解释 1251 里的 `0x0a` 计数和 10×8 B 表 |
| `tencent-ailab/hok_env` | 官方 README：ABS Parsing Tool（ABSTOOL）播放 GameCore 生成的 ABS，不是 `.abc` | 官方路径存在，但不能直接替代商业 `.abc` 解析 |

**对照结论**：

- 1251/1082 的消息号和字段家族**有公开协议定义独立确认**，不再只是本机
  metadata 的单一来源。
- 1251 的 `bAcntNum + 10×8 B` 与公开 `COMDT_MVP_SCORE_DETAIL` 完全吻合；
  当前 build 的败方 MVP 从旧的单个 `dwLoseMvpObjID` 演化为
  `iLoseMvpObjNum + LoseMvpObjList`。
- 旧版 `FlushRecord` 解释了帧流前那 7 B：
  `i16 length=7 + u32 dwKFrapsNo + u8 bNum`，即
  `CSDT_FRAPBOOT_INFO(dwKFrapsNo=..., bNum=0)` 关键帧。按这个口径，
  7 B 已从 residual 移除，residual 降为 **867 / 869 B**
  （头部 13 B + 1075 前缀 854/856 B）。位置和 `dwKFrapsNo` 的取值
  （0 或 7）仍待逐字节确认。
- 旧版 `GameReplayModule.cs` 是历史版本，**i16 宽度、旧字段名不能直接
  套到 2026 build**；只用于语义和记录方向的交叉验证。

## 6. `.ope` 与 `.csd/.dmg`

- `.ope`：本地操作流（OperatorMonitor），记录触控/移动/技能/UI 操作；
  与 `.abc` 的 CSPkg 记录流是两套东西。新构建在操作流偏移 0x1B 命中
  `0xEF`，当前解析器如实报墙。
- `.csd/.dmg`：`ReplayMemoryRecover` 的恢复文件。设备 files 根目录有大量
  `0000000000_0000000000_<编号>.csd/.dmg`；`.csd` 约 2–6 KB，`.dmg` 约
  6.6–6.9 MB。方法名表明这是 seek/recover 快照，不是 `.abc` 的结算统计。
  当前未解码 `.dmg` 内部格式。

## 7. 证据等级

| 判断 | 等级 |
|---|---|
| `GameReplayModule`/`ReplayFileInfo`/`ReplayMemoryRecover` 等类/字段/方法名 | ✅ 当前 metadata 直接读出 |
| `.abc` 记录流 signed i32 + CSPkg/帧记录语法 | ✅ 记录流工具 + `SLoadDefaultMsg` 结构 |
| `ReplayFileInfo` 字段与 `.abc` 头部对应 | ✅ 字段名/顺序一致 |
| 1251 在文件末尾、109 B、MVP/评分字段 | ✅ 文件对齐 + 11-01 面板真值 |
| 1082 不在 `.abc` 记录流 | ✅ 文件级；30 份样本零合法包 |
| 1082 不进入 `GameReplayModule` 写入路径 | ◐ 类/字段/方法结构推断，待逐指令确认 |
| `.csd/.dmg` 是 recovery 快照 | ◐ 方法名 + 文件形态，待格式解码 |
| `AdvanceFrameCommands` 的具体实现绑定 | ◐ 见 `replay_binary_format.md` 5.126 |

## 8. 复现

```bash
# 模拟器
D:/MuMuPlayer/nx_main/MuMuManager.exe control -v 0 launch
adb connect 127.0.0.1:16384

# 设备信息/APK/库
adb shell pm path com.tencent.tmgp.sgame
adb shell dumpsys package com.tencent.tmgp.sgame | grep -E "versionName|versionCode|primaryCpuAbi"
adb shell md5sum <lib path>
adb pull /sdcard/Android/data/com.tencent.tmgp.sgame/files/Replay <out>

# 回放系统清单
python tools/client_replay_system.py
python tools/replay_record_stream.py <abc>
python tools/peel_replay_residue.py <abc>
```

产物：

```text
data/replays/_analysis/client_extract_20261102/replay_system.json
data/replays/_analysis/client_extract_20261102/manifest.json
data/replays/_analysis/client_extract_20261102/Replay/
```

## 9. 未决

1. **状态相关槽位**：`HandleFrapBoot`/`HandleSinglePkg`/`RetriveBeginLoad`
   的静态槽位在登录页和回放/战斗状态下指向不同函数。必须在回放状态下
   取槽位，不能沿用登录页 dump。
2. **generic sharing 桩**：`SLoadDefaultMsg` 的 `br x2` 目标
   `0x400032ed9d00` 和 `LoadMsg` 的 `0x400032ed9dfc` 都是共享函数中间入口，
   没有普通 `MethodInfo` 名字。需要跟踪 `x22` 上下文和共享辅助函数
   `0x400031ce1460`/`0x400031ce14fc`。
3. `LoadMsg` 的 switch（`w8-4`，4..12）与跳表 `0x19bd000+0xfdc`：
   需要把 9 个 case 与 CSPkg/帧类型对齐。
4. `RetriveBeginLoad` 的 `Miniz::uncompress` 候选：确认它解的是哪个嵌套
   buffer；1075 整体不是 Deflate 流。
5. `AutoSaveRecord`/`OnFightOver` 的逐指令写入顺序：确认 1251 的具体写入点，
   以及是否存在任何 1082 写回放的分支。
6. `AdvanceFrameCommands` 到 `libGameCore.so` 的实际绑定。
7. `ReplayMemoryRecover` 的 `.csd/.dmg` 内部格式。
8. `CAutoReplayManager` 的 Streaming/ShareMem 路径与 `Default` 本地文件的差异。
9. 如需 APK assets/config，可在释放 D 盘空间后选择性拉取，不必整包 1.75 GB。
