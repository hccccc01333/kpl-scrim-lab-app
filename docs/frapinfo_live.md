# frapInfo live 只读探测：工具、扫描范围与负结果

日期：2026-11-03。环境：MuMu Android 15，王者 build 5247758
（App 12.1.1.1 / Res 12.1.1.26）。只读 ADB root + `/proc/<pid>/mem`：
不注入、不调用游戏函数、不写设备文件、不修改 `.ope` 或游戏文件。

## 0. 结论摘要

- **在两次实际回放会话（pid 2785 早期、pid 20884 约 00:44）中，都没有在
  live 堆里找到处于 `count = 1..27` 的 `CSDT_FRAPBOOT_INFO` 实例
  （0 个）。** 两次扫描分别覆盖约 **2.32 GiB** 和 **768 MiB + 1.73 GiB**
  可写堆；CSDT 类指针命中分别 19 处和 17 处，全部是类对象、
  MethodInfo/类型表或元数据描述符，不是命令结构。
- 原因不是扫描器漏读，而是对象生命周期：`FrameWindow.HandleFraqBootInfo`
  内完成 `new → TDR unpack → AdvanceFrameCommands → OnRelease → release`，
  `frapInfo` 只在这一次调用期间存在；帧间快照看到的是已释放内存，
  观测中类指针没有保留下来（与释放后对象头被 free-list 覆盖/复用一致）。
- 探测期间游戏进程多次重启（pid **2785 → 20884 → 43985 → 无进程**），
  `libil2cpp.so` / `global-metadata` 反复卸载，回放结束。因此：
  **没有拿到当前回放帧附近的 live 命令类型序列，也没有完成 .abc 对拍。**
- 已新增只读工具 `tools/frapinfo_live_probe.py`，可自定位类指针、
  扫描 scudo/匿名堆、打分候选、并采样 `FrameWindow` 的 900 槽包环形缓冲；
  回放恢复后可直接重跑。

## 1. 工具

`tools/frapinfo_live_probe.py`

### 1.1 模式

| 模式 | 行为 |
|---|---|
| `auto`（默认） | 解析类 → 堆扫描（类锚点 + 结构签名）→ ring 采样 |
| `resolve` | 只解析 `CSDT_FRAPBOOT_INFO` / `FrameWindow` 的 live `Il2CppClass*` |
| `heap` | 类锚点扫描 + 类无关结构签名扫描 |
| `ring` | 解析并采样 `FrameWindow` 的包环形缓冲 |
| `signature` | 不做类解析，只做结构签名扫描（类解析失败时用） |

关键参数：

```bash
python tools/frapinfo_live_probe.py \
  --serial 127.0.0.1:16384 \
  --out data/replays/_analysis/client_probe_<date>/frapinfo_live_<tag> \
  --max-scan-mb 1024 --resolve-scan-mb 512 \
  --chunk-kb 4096 --workers 3 \
  --samples 3 --sample-interval 0.8 --abc <file>.abc
```

- `--max-scan-mb 0` 表示不设预算；`--workers 1..8` 限制并发 ADB 读取。
- 读取统一 4 KiB 分页、4 MiB 分块、窗口化线程池（最多 `workers*2`
  个在途读取），不一次性拉完整堆。
- 输出只写 `--out/summary.json`（地址/计数/类型序列/拒绝原因），
  不写堆字节、不写 ring 原始缓冲区。
- 退出码：`0` 探测已执行（结果可为负）；`2` 游戏/IL2CPP/metadata 不可用；
  `3` 扫描或 metadata 读取失败。

### 1.2 只读边界

- 只执行 `adb shell cat /proc/<pid>/maps` 和
  `adb exec-out dd if=/proc/<pid>/mem ...`。
- 不调用任何游戏函数、不 attach、不写 `/proc/<pid>/mem`、不写设备文件。
- 扫描是机会式快照；不会让进程暂停。

### 1.3 类指针自定位（不依赖旧捕获地址）

工具从 live metadata 映射解析：

1. 读 `/proc/<pid>/maps` 中 `_$$global-metadata$$_` 映射，校验
   `0xFAB11BAF` / version 29；
2. 读 string table 与 type definition table，按
   `(nameIndex, namespaceIndex)` 找 `CSDT_FRAPBOOT_INFO`（`CSProtocol`）
   和 `FrameWindow`（`Assets.Scripts.Framework`）；
3. 计算运行时字符串地址 `metadata_base + stringOffset + index`；
4. 在 scudo primary 扫描该地址的 8 字节引用，取 `ref - 0x10` 为候选
   `Il2CppClass*`，并校验 `[class+0x10] == name_ptr`、
   `[class+0x18] == namespace_ptr`、`class` 位于 scudo primary。

离线自测（用本仓库 12:04 的 `metadata.bin` 与旧 maps，不访问设备）：

```text
metadata_base = 0x74cb1723b000
stringOffset  = 2,766,456
CSDT nameIndex= 3,928,857
name_addr     = 0x74cb1789d991
```

该地址与 `bind_live_20261103_playing/methods.json` 中
`CSDT_FRAPBOOT_INFO.unpack` 的 `class_name_pointer` 完全一致；
同名/同命名空间的解析索引为 `(3928857, 2698395)`。
`FrameWindow` 的 name 地址自测为 `0x74cb17be6356`。

同一进程（pid 2785）当时由 captures 给出的类指针：

| 类 | Il2CppClass* |
|---|---:|
| `CSProtocol.CSDT_FRAPBOOT_INFO` | `0x74ccd889b2d0` |
| `Assets.Scripts.Framework.FrameWindow` | `0x74cd1866f390` |
| `Assets.Scripts.GameLogic.GameLogicHelper` | `0x74cc1812c280` |

## 2. frapInfo 生命周期：为什么帧间堆扫描看不到

以下地址来自本次 build 的 libil2cpp 与 pid 2785 的 live 读取。
`HandleFraqBootInfo`（runtime `0x40002bef44fc`，file `0x5cf34fc`）：

```text
0x40002bef4600  adrp x8, #0x4000338f9000
0x40002bef4608  ldr  x8, [x8, #0x138]        ; factory = 0x400030529790
0x40002bef460c  blr  x8                      ; x21 = new object
0x40002bef4618  ldrh w2, [x19, #0x10]        ; packet payload length (u16)
0x40002bef461c  add  x1, x19, #0x18          ; packet payload data
0x40002bef462c  ldr  x8, [x8, #0x788]        ; TDR fill = 0x40003017d0c0
0x40002bef4638  blr  x8                      ; fill x21 from payload
...
0x40002bef46d0  ldp  x8, x3, [x0]            ; virtual slot 0x35
0x40002bef46d8  mov  w1, w23                 ; frameNo
0x40002bef46dc  mov  x2, x21                 ; frapInfo
0x40002bef46e0  blr  x8                      ; AdvanceFrameCommands call site
...
0x40002bef46ec  ldr  x8, [x20, #0x7c0]       ; release = 0x40003017d414
0x40002bef46f8  blr  x8                      ; release/reclaim frapInfo (x21)
0x40002bef4708  blr  x8                      ; release/reclaim packet (x19)
```

factory `0x400030529790` 通过全局 `0x400034067970` 取类指针；该全局在
pid 2785 中保存 `0x74ccd889b2d0`，即 `CSDT_FRAPBOOT_INFO` 的类指针，
并在新对象上写入 `[obj+0xc] = 0`（命令数清零）。

`CSDT_FRAPBOOT_INFO.unpack`（runtime `0x400030529694`，file
`0xa328694`；该页在设备上是 XOR 0xE3 编码）确认了字段：

```text
x22 = this + 0xc          ; 命令数 u8
x0  = [this + 0x10]       ; 命令数组/容器
x0  = [x22]               ; stream 读出的 count
array_fill(array, count, stream, len, ...)
```

release 路径 `0x40003017d414`：

```text
x0 = [obj]                ; klass
ldp x8, x1, [x0, #0x1d8]  ; OnRelease 虚函数
blr x8
; 然后尾调用一个 release/回收函数（0x4000338c5dc8；未逐字节验证实现）
```

`OnRelease`（token `0x600e876`，MethodInfo 指针 `0x40003052981c`）只有：

```text
strb wzr, [x0, #0xc]      ; count = 0
ret
```

因此对象在 `AdvanceFrameCommands` 返回后立即进入 OnRelease/release
路径；本次 2.19 GiB 类指针扫描没有发现帧间稳定存在的带类指针实例
（不能排除对象池复用，但复用的对象头没有保留可识别的 CSDT 类指针）。release 函数具体如何改写
对象内存尚未逐字节验证；上述“free-list 覆盖”只是与观测一致的解释，
不是本报告的直接测量结论。

类解析不是失败点：12:04 captures 给出的 CSDT 类指针
`0x74ccd889b2d0` 与本次读数一致，扫描也用该指针找到了类对象和
类型表引用，只是没有有效实例。

## 3. 实机扫描范围与结果（pid 2785，回放播放中）

所有读取均为 `/proc/2785/mem` 的只读快照；堆字节未落盘。

| 扫描 | 范围 | 读取 | 命中 | 有效 frapInfo |
|---|---|---:|---:|---:|
| CSDT 类指针 8 字节 needle | 全部 untagged `rw-p` 匿名堆 + 全部 scudo primary/secondary | 2,191.9 MiB / 1,996 chunks | 19 处 | 0 |
| `FrameWindow` 类指针 | 前 8 大 GC 匿名区（479.8 MiB 选择） | 479.8 MiB | 1 个实例 | — |
| `FRAME_CMD_PKG/INFO` 类指针 | 前 14 大匿名区 + scudo secondary（930.4 MiB 选择） | 863.0 MiB | 2 处（相邻） | 0 |
| 类指针（CSDT/PKG/INFO） | `[anon:Mem_*]` Unity 分配器 | 160.3 MiB | 0 | 0 |
| 类指针（CSDT/PKG/INFO） | partition_alloc / libc_malloc / bionic / `.bss` / thread signal stack | 22.5 MiB | 0 | 0 |
| 结构签名 | 单个 144 MiB GC 区 `0x74c9c0000000-0x74c9c9000000` | 144.0 MiB | 144,010 个预筛 | 2 个未证实 |

唯一覆盖约 **2.32 GiB（2,374.7 MiB）**（2,191.9 + 160.3 + 22.5 MiB），
基本覆盖当时所有与 IL2CPP 相关的可写堆；未扫描 Dalvik/Java 堆（与
IL2CPP 对象无关）。

### 3.1 CSDT 类指针的 19 处命中和反例

19 处包括类对象自身、类相关结构、MethodInfo/类型表和元数据描述符。
计数字段为 203/204/240～244 或 0，数组布局不成立。代表性反例：

| 地址 | 证据 | 拒绝原因 |
|---|---|---|
| `0x74c7ecee0e60` | `[+0]=0x74ccd889b2d0`, `[+0x8]=0x1166`, `[+0xc]=0`, `[+0x10]=0x74c7ecee0e40`；目标 `+0x10` 的 length = 0 | 元数据类型描述符，不是实例 |
| `0x74cceae8b868` | count=240，array=`0x74cb1789d9a4` | array 指向 `global-metadata` 只读映射 |
| `0x74cceae8b888` | count=241，array=`0x74cb177728d9` | 同上 |
| `0x74cceae8b8a8` | count=242，array=`0x74cb177728e5` | 同上 |
| `0x74cceae8b8c8` | count=243，array=`0x74cb177728f1` | 同上 |
| `0x74cceae8b8e8` | count=244，array=`0x74cd1805ea50` | array length 检查失败 |
| `0x74ccea4d37f0` | count=204，array=`0x74ccd86df770` | array length 检查失败 |
| `0x74ccec13e578` | `CSDT_FRAPBOOT_INFO.unpack` 的 MethodInfo | 类指针出现在 MethodInfo 的 declaring type 字段 |
| `0x400034067970` | 全局类指针槽 | 类指针引用，不是对象 |

`FRAME_CMD_PKG` / `FRAME_CMD_INFO` 类指针只命中
`0x74caed08ec50` / `0x74caed08ec58` 两个相邻槽；该内存是一个
类指针表（每项 16 字节，连续排列多个类指针），不是命令对象实例。
这说明连命令对象的类指针也没有以“独立实例”的形式留在堆里。

### 3.2 结构签名的两个未证实候选

在 `0x74c9c0000000` 的 144 MiB 区，预筛条件为：
`count 2..27`、`[+0x10]` 数组指针落在同一 chunk、8 字节对齐。
共 144,010 个预筛候选，其中 2 个通过“同一 chunk 内整数布局”的宽松链：

```text
0x74c9c2c56f20  count=2  layout=+0x10/+0x18  length=85
                stride=40  types=[2,2]
                payloads=[0x74c9c2c572b0, 0x74c9c2c56fd8]
0x74c9c7dfaba0  count=2  layout=+0x10/+0x18  length=85
                stride=16  types=[6,10]
                payloads=[0x74c9c7dfaf40, 0x74c9c7dfb0f0]
```

两者 length 都不等于 count，payload 指向自身附近，且没有验证
array 类名/CSDT 类名；按当前规则判为假阳性，不作为 frapInfo 结果。
这也是工具里“length 一致、payload 可读、类名匹配、类别 1..27 全部成立”
多项打分而不是单一签名判定的原因。

### 3.3 第二次 live 会话（pid 20884，回放约 00:44）

协调者确认回放正在播放后，工具用 `pidof` 重新取 PID（20884）并重读
maps；metadata base 变为 `0x74ca86154000`（version 29），重新解析出：

| 类 | Il2CppClass* |
|---|---:|
| `CSProtocol.CSDT_FRAPBOOT_INFO` | `0x74ccd84a1ad0` |
| `Assets.Scripts.Framework.FrameWindow` | `0x74cd1866d090` |

这与 pid 2785 的 `0x74ccd889b2d0` / `0x74cd1866f390` 不同，说明跨进程
常量不可复用；工具每次重解析是必要的。

`auto` 模式、`--max-scan-mb 768` 的结果：

- 实际读取 **805,306,368 字节（768 MiB）**，248 chunks，50.0 s；
- `CSDT_FRAPBOOT_INFO` 类指针命中 **17 处**，`class_anchored.validated`
  **0 个**；其中 `u8(+0xc)==0` 的命中在数组类检查中不满足
  `FRAME_CMD_INFO[]` 条件，未计为已释放实例；
- 结构签名预筛 **23,470 个**，验证 1,024 个（上限），**0 个通过**；
  拒绝原因：`array_klass_outside_scudo` 578、`array_klass_unreadable` 70、
  `command_chain_invalid` 376；其余 22,446 个超过本轮验证上限未验证；
- `FrameWindow` 类指针命中 184 处（大多数是类型表/类指针引用）。

对同一进程补做全堆 FrameWindow 扫描（scudo + 匿名 + `Mem_*`，
1,730.1 MiB，6 workers）：199 处类指针引用，只有 1 个真正的 900 槽
ring 实例：

```text
0x74c941b95640  ring=0x74c9423db000  length=900
current=1  base=0  max_seen=0  nonnull=0
```

两次采样均无 packet：`ring.instance_found=true` 但 `ring.found=false`。
另补扫 31.6 MiB 的小匿名区/`.bss`/libil2cpp rw 区，FrameWindow/CSDT
类指针 0 命中。该次回放的路径没有填充 `HandleFraqBootSingle` 的单包
ring（更可能走批量 FRAPBOOT 路径），所以 ring 锚点也没有给出 live
命令序列。

注：`frapinfo_live_20884_a/summary.json` 是工具修正前的中间版本，
其中 `ring.found` 仍为 true、`released_count_zero` 仍列出 8 个未通过
`FRAME_CMD_INFO[]` 数组类检查的地址；以本节文字和修正后的工具为准。

### 3.4 第三次进程（pid 43985）：扫描中退出

再次重启后 pid 43985 短暂出现，IL2CPP/metadata 已加载。工具解析到
`FrameWindow` class `0x74cd18687490`，但 `CSDT_FRAPBOOT_INFO` 未在
scudo primary/secondary 中命中；随后进程退出（429/429 chunks 读取失败，
heap scan 0 字节），前台回到桌面。该次结果只作为“进程在扫描中退出”的
证据，不作为 frapInfo 结论。

## 4. FrameWindow 包环形缓冲：可用的持久锚点（未完成）

`FrameWindow.HandleFraqBootSingle`（runtime `0x40002bef047c`）在同一路径上
保存了每个 FRAPBOOT 包：

```text
packet + 0x0c  u32 frameNo
packet + 0x10  u16 payload length
packet + 0x18  payload bytes
FrameWindow + 0x08  ring array pointer
ring + 0x10         ring length (900 observed)
ring + 0x18         packet pointers
FrameWindow + 0x10  base counter
FrameWindow + 0x14  current counter (increments per packet)
FrameWindow + 0x18  max frame seen
```

它是同一代码路径留下的、帧间仍然存在的证据。扫描 479.8 MiB 找到一个
`FrameWindow` 实例 `0x74c8723ab640`：

```text
ring=0x74c7edb8d000 length=900
FrameWindow+0x10 base=0
FrameWindow+0x14 current=1
FrameWindow+0x18 max=0
ring[0..2] 抽样均为 0（只抽了前 3 槽）
```

该实例不是当时回放的活跃 ring（或当时 ring 尚未填充），因此没有从中
取得回放帧号/命令序列。

pid 20884（回放约 00:44）的全堆补扫也只找到 1 个 ring 实例
`0x74c941b95640`（ring `0x74c9423db000`，length 900、nonnull=0）。
两次会话的 ring 都为空，说明这批回放的命令进入路径更可能是批量
FRAPBOOT，而不是会写这个 900 槽 ring 的 `HandleFraqBootSingle`。
工具现在把 `ring.instance_found`（找到 ring 实例）与 `ring.found`
（采样到 packet）分开报告，避免把空 ring 误报成活跃回放。

## 5. 与 .abc 对拍的状态

**未完成。** 没有 live frapInfo，也没有回放 ring 的帧数据，因此不能
诚实地给出“帧 N 的命令类型序列 == .abc 帧 N 的 selector/类别序列”。
工具已预留 `--abc <file>`：

- 用 `tools.replay_record_stream.py` 的 record 流和
  `tools.replay_frame_commands.py` 的严格 TDR 解码器加载已知帧；
- 只在 live ring 包解码成功时，对同一 frameNo 比较命令数与类别序列；
- 严格解码器对未知 selector 会整帧拒绝，输出中会保留错误/首字节，
  不把不完整解码当成匹配。

## 6. 复现

回放播放时：

```bash
python tools/frapinfo_live_probe.py \
  --serial 127.0.0.1:16384 \
  --out data/replays/_analysis/client_probe_20261103/frapinfo_live_<tag> \
  --max-scan-mb 1024 --samples 3 --abc data/replays/samples/<match>/<file>.abc
```

当前（所有 sgame 进程已退出，前台为桌面）运行工具会得到
`pidof` 空结果并退出 2；此前一次后台 stub 状态（pid 20884、
无 libil2cpp 映射）的输出为 `il2cpp-not-mapped`：

```bash
python tools/frapinfo_live_probe.py --out data/replays/_analysis/client_probe_20261103/frapinfo_current_noreplay
# exit 2, status: il2cpp-not-mapped
# pid 20884, libil2cpp_mapped=false, metadata_mappings=[]
```

产物：

- `data/replays/_analysis/client_probe_20261103/frapinfo_current_noreplay/summary.json`
  （后台 stub，无 IL2CPP）；
- `data/replays/_analysis/client_probe_20261103/frapinfo_live_20884_a/summary.json`
  （pid 20884 回放约 00:44：类解析成功、0 个 resident、0 个签名通过）；
- `data/replays/_analysis/client_probe_20261103/frapinfo_live_43985_ring/summary.json`
  （pid 43985：扫描中进程退出，429/429 chunks 失败）；
- 以上目录均不含堆转储，只含地址/计数/类型序列/拒绝原因。

离线自测（不访问设备）：

- 用 12:04 的 `metadata.bin` 复算 CSDT name 地址，得到
  `0x74cb1789d991`，与 captured `class_name_pointer` 一致；
- 构造 count=3、类型 `[1,5,18]`、inline stride 0x18 的合成结构，
  `validate_candidate` 正确接受并识别
  `klass_name=CSDT_FRAPBOOT_INFO`、`array_klass_name=FRAME_CMD_INFO[]`。

## 6.5 2026-11-03 回放 2052：FrameWindow 队列否定与 Recovery 文件（补充）

回放恢复后重新解析（pid 2052，11/2 161129）：

| 对象 | live 地址 | 结果 |
|---|---:|---|
| `FrameWindow` 类 | `0x75db8938d4d0` | 字段偏移与上一进程一致 |
| `FrameWindow` 实例 | `0x75d84abff960` | 由类指针堆扫描命中，`_receiveWindow` 是 900 槽数组 |
| `_receiveWindow` | `0x75d84ac07000` | 类名 `SCPKG_FRAPBOOT_SINGLE[]`，`length=900`，首元素 0 |
| `_offlineReceiveWindow` | `null` | 本局没有走离线包队列 |
| `_basFrqNo/_begFrqNo/_maxFrqNo` | — | 0 / 1 / 0 |
| `_offlineNowFrqNo/_offlineMaxFrqNo/m_lastOfflinePkgFrameNum` | — | 全 0 |

结论：`HandleFraqBootSingle` 的 900 槽数组在本局回放为空；`_offlineReceiveWindow`
也没有被分配。**这局回放没有留下可读的持久 FRAPBOOT 包队列。** 该结论不证明
调用期间的瞬时 `frapInfo` 不存在，只证明帧间/暂停快照没有可用的持久副本。

同进程还定位了 `VisualFrameReplayManager`（`Assets.Scripts.GameSystem`）：

- 类 `0x75db89372f10`，继承 `Singleton<VisualFrameReplayManager>`；
- 实例 `0x75db1f598120`，由 `Singleton.s_instance` 取得；
- `replayFilmDict` / `replayFrameList` 已分配但列表为空；
- `currentReplayFramePtr`、`currentFrameRecord` 为 null；
- 静态 `cppBuffer`（`class+0xB8` 静态区 +8）地址 `0x75db30981ff0`，大小 `0x40000`，
  内容是带指针的显示/录制缓冲，不是逐帧战斗状态。

这说明 `VisualFrameReplayManager` 在这局回放里没有保存逐帧战斗状态；它是显示帧/
录制路径，不是经济/HP 的持久真值。

### Recovery 文件（`.csd/.dmg`）

设备 `files/` 根目录的 `0000095868_1793606215_*.csd/.dmg` 与这局回放对应；
已只读拉取 frame 2738/3473 两组。初步格式：

- `.csd` 首 4 B `72 65 63 00`（`rec\0`），版本 2；与 `RecoverDataManager.MagicHeader`
  的 metadata 默认值 `c0 63 65 72`（字符串 `rec` 的序列化）一致；
- `.dmg` 首 4 B `af af af af`，高熵、含 Unity 资源路径和十名选手昵称/OpenID；
- `RecoverDataManager` 的 `RootRecoverData` 含 `gameData` + `_actorDatas`；
  `ActorRecoverData` 的 runtime 字段是 `animatorData/animationData/actorID`，
  即演员动画/显示恢复；不应把这组文件直接当作 HP/金币/伤害账本。

`.dmg` 中的选手昵称/OpenID 说明它至少包含回放头部/字符串池；它是否还包含
战斗逻辑状态尚未解码，不能据此宣称“完整状态已拿到”。

## 7. 边界与下一步

- 本报告是**负结果**：没有找到 live frapInfo 实例。它不证明对象在
  `AdvanceFrameCommands` 执行期间不存在；只证明帧间/释放后的堆快照
  不保留可识别的实例。
- 本次观测期间进程至少经历 `2785 → 20884 → 43985 → 无进程`；
  每个 pid 的类指针、metadata 基址和扫描结果都是该次快照，不可拼接成
  一个连续会话。pid 20884 的回放约 00:44 时确实在播放，但 ring 为空。
- 地址、布局、类指针均为 build 5247758 本次进程证据；换构建/换进程
  必须由工具重新解析，不能把 `0x74cc...` 当常量。
- 没有注入、没有调用游戏函数、没有写设备文件；`docs/advance_frame_commands.md`
  和 `.ope`/游戏文件未改动。
- 下一步：
  1. 回放恢复后重跑 `--mode auto`，优先看 `class_anchored.validated`
     是否非空；
  2. 若仍为空，使用 `--mode ring` 采样回放 ring，先确认 frame 与
     `.abc` 的对应，再考虑命令类别序列对拍；
  3. 若必须抓取调用期间的瞬时 frapInfo，需要另行批准采样方案；
     不要在未批准情况下注入或暂停进程。
