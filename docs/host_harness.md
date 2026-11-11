# GameCore Host Harness 骨架

本文件对应 `host/src/gchost.c` 与 `host/scripts/build_host.sh`。它是
`docs/gamecore_host.md` 中 H0/H1/H2 的产品化宿主骨架，**不是**完整的对局模拟器。

## 1. 状态边界（先读）

| 阶段 | 状态 | 说明 |
|---|---|---|
| deps | 已实现 | 预加载 4 个依赖库 + `libGameCore.so` |
| module-init | 已实现 | `dlsym(ModuleInit)`、校验构建偏移、调用 `ModuleInit` |
| fixture | 已实现 | 读取并交叉校验 `meta.json`（可选 `init/abc_header.json`） |
| databin | 已实现 | 加载 `stdr` 数据表、注册宿主表对象、用 `DT_Count/DT_GetByIndex` 校验 |
| context-init | **未实现** | 显式 stub，返回退出码 40；不构造 `CLevelContext/deskPool` |
| frame-tick | **未实现** | 显式 stub，返回退出码 40；不推送/推进任何帧 |
| state-output | **未实现** | 显式 stub，返回退出码 40；不读取玩家状态、不写 JSONL |

因此本骨架能证明的是：

- 私有 ARM64 宿主进程可以加载 GameCore 依赖并完成 `ModuleInit`；
- fixture 的 `meta.json` 与 `init/abc_header.json` 自洽（版本、回放 ID、总帧数）；
- 指定构建的 databin 表可以按 `DT_*` 契约注册并读回一致的行数据。

它**不能**证明：能跑一局、能推进帧、能拿到任何玩家状态或经济数据。H4/H5/H6
仍未完成，任何“完整状态已可用”的说法都超出本骨架。

> 独立的 H5 实验（真实 `.abc` 帧载荷 → CS slot0 → consumer）不在本骨架的
> `--tick`/`--state-out` 路径里，见 `docs/h5_consumer_probe.md`；它验证了
> push/commit/drain，但没有帧推进或玩家状态输出。

### 1.1 各阶段验证内容

| 阶段 | 通过条件 | 明确不验证 |
|---|---|---|
| deps | 4 个依赖库和 `libGameCore.so` 均可 `dlopen` | 不验证游戏版本兼容性，不证明后续调用安全 |
| module-init | `ModuleInit` 导出存在；`dladdr` 得到的 base 满足 `ModuleInit-base == 0x46ad0e0`；调用未崩溃 | `ModuleInit` 返回值不是成功码；不启动对局，不构造 context，CS 数组保持原样 |
| fixture | `meta.json` schema/必填字段/`total_frames>0`/sha 格式正确；可选 `abc_header.json` 的 replay_id、totalFrameNum、builds[-1] 与 meta 一致 | 不解析 `.abc` 内容，不重算 sha256（validator `--abc` 才会重算） |
| databin | 每个块 magic=`stdr`、`0x98+stride*rows` 与文件长度一致；注册表写入成功；`DT_Count` 等于行数；sample/full 行逐字节一致 | 不证明 CS FIFO 可用、不证明能 push/commit 帧、不读出任何玩家状态 |
| context-init | **无通过条件（未实现）** | 不构造 `CLevelContext/deskPool`，不伪造 vtable |
| frame-tick | **无通过条件（未实现）** | 不推送命令、不调用 tick、不推进帧号 |
| state-output | **无通过条件（未实现）** | 不读取玩家字段、不写 JSONL |

## 2. 构建

要求：

- Android NDK r28b（默认 API 28，可改 `API`）；
- 目标 ABI：ARM64（`aarch64-linux-android28-clang`）；
- 只编译，不接触设备/游戏。

```bash
# NDK 可从环境变量或 SDK 常见目录自动发现
NDK=/path/to/android-ndk-r28b bash host/scripts/build_host.sh

# 或：
ANDROID_NDK_HOME=/path/to/android-ndk-r28b bash host/scripts/build_host.sh
```

可覆盖的环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NDK` / `ANDROID_NDK_HOME` / `ANDROID_NDK_ROOT` | 自动探测 | NDK 根目录 |
| `API` | `28` | Android API level |
| `SRC` | `<repo>/host/src/gchost.c` | 源文件 |
| `OUT_DIR` | `<repo>/host/build` | 输出目录 |
| `OUT_BIN` | `$OUT_DIR/gchost` | 输出二进制 |

脚本固定使用 `-fPIE -pie -O2 -ldl`，并在最后用 `llvm-readelf` 打印
`Class/Machine/Type`。默认输出：

```text
host/build/gchost
```

仓库只保留源码；`host/build/` 不是源码的一部分。

## 3. 运行

宿主是独立进程，不附加游戏进程、不登录、不注入、不修改游戏文件。`.abc/.ope`
只读。

### 3.1 设备侧准备

以下路径均为例示，可用 `--lib-dir` 等参数改。`ADB`/`SER` 与
`host/scripts/run_probe.sh` 保持一致。Git Bash 下建议先：

```bash
export MSYS_NO_PATHCONV=1
```

避免 `/data/local/tmp/gc` 被转换成 Windows 路径。

```bash
ADB="${ADB:-D:/MuMuPlayer/nx_main/adb.exe}"
SER="${SER:-127.0.0.1:16384}"
DEV=/data/local/tmp/gc

"$ADB" connect "$SER"
"$ADB" -s "$SER" shell "mkdir -p $DEV/dtab_blocks $DEV/fixture"

# 依赖库 + GameCore（沿用现有探针的布局）
"$ADB" -s "$SER" push data/replays/_analysis/_host/libs/. "$DEV/"
"$ADB" -s "$SER" push data/replays/_analysis/libGameCore.so "$DEV/"
"$ADB" -s "$SER" push host/build/gchost "$DEV/"

# fixture（meta + init 头；context 快照可选）
"$ADB" -s "$SER" push host/fixtures/20261102_161129/. "$DEV/fixture/"

# databin 块（<index>_<name>.bytes.bin）
"$ADB" -s "$SER" push data/replays/_analysis/device/dtab_blocks/. "$DEV/dtab_blocks/"
```

### 3.2 仅引导（不做 fixture/databin）

```bash
"$ADB" -s "$SER" shell \
  "cd $DEV && chmod 755 gchost && ./gchost --lib-dir $DEV"
```

等价于现有 `gc_boot` 的 H0 冒烟：加载依赖、校验 `ModuleInit` 偏移并调用它。

### 3.3 fixture + databin 全量已实现阶段

```bash
"$ADB" -s "$SER" shell \
  "cd $DEV && ./gchost \
     --lib-dir $DEV \
     --fixture $DEV/fixture \
     --replay-id 20261102_161129 \
     --databin-dir $DEV/dtab_blocks \
     --verify samples"
```

默认 `--verify samples` 对每张表查 3 行（首、中、末）；`--verify full` 逐行比较；
`--verify none` 只安装不查询。成功时最后一行是
`implemented stages completed OK`。

当前 `dtab_blocks` 的基线（来自已有 `gc_sim0b` 探针，需在设备上用本骨架复核）：

```text
databin RESULT installed=825 verified=825 count_bad=0 row_bad=0 total_rows=205149
```

CS 数组槽只作为只读诊断打印，例如：

```text
CS array slot (diagnostic, not initialized by harness) = 0x...
```

它不是 context 构造结果，也不代表 CS FIFO 可用。

### 3.4 请求未实现阶段（用于确认 fail-closed）

```bash
./gchost --lib-dir "$DEV" --fixture "$DEV/fixture" --context
./gchost --lib-dir "$DEV" --fixture "$DEV/fixture" --tick 1
./gchost --lib-dir "$DEV" --fixture "$DEV/fixture" --state-out "$DEV/state.jsonl"
```

三者都会打印 `UNIMPLEMENTED (H4/H5/H6)` 并以 40 退出；`--state-out` 不会创建文件，
`--tick` 不会推进任何帧。

## 4. 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `--lib-dir DIR` | 否 | `libGameCore.so` 与 4 个依赖所在目录；默认是本可执行文件所在目录 |
| `--fixture DIR` | 否 | fixture 根目录，至少含 `meta.json`；有 `init/abc_header.json` 时交叉校验 |
| `--replay-id ID` | 否 | 要求 `meta.replay_id == ID` |
| `--databin-dir DIR` | 否 | 数据表目录；文件名为 `<index>_<name>.bytes.bin` |
| `--verify none\|samples\|full` | 否 | databin 查询强度，默认 `samples` |
| `--allow-unverified-build` | 否 | 跳过构建/偏移门禁；仅用于新构建实验，可能直接崩溃 |
| `--keep-databin-crc` | 否 | 不调用 `SGameSetEnableDatabinCrcFromFile(0)` |
| `--context` | 否 | 请求未实现的 context-init；与已实现阶段一起运行时最终退出 40 |
| `--tick N` | 否 | 请求未实现的 frame-tick N 帧；最终退出 40 |
| `--state-out FILE` | 否 | 请求未实现的 state-output 到 FILE；最终退出 40，不写文件 |
| `--keepalive SEC` | 否 | 所有阶段结束后休眠 SEC 秒，便于 `/proc` 检查，默认 0 |
| `--help` | 否 | 打印帮助 |

`--databin-dir` 必须与 `--fixture` 一起使用，以便用 `meta.build` 对照已验证构建；
没有 fixture 时必须显式给 `--allow-unverified-build`。

## 5. fixture 参数与校验范围

`--fixture DIR` 期望：

```text
DIR/
  meta.json                 # 必需
  init/abc_header.json      # 可选；存在则交叉校验
  init/players.json         # C 骨架不解析；validator 会校验
  context/context_snapshot.json  # 可选；C 骨架不解析
  frames/ state/            # 可选；骨架不读取
```

`meta.json` 的 C 侧校验：

- `schema == "kpl-gamecore-fixture-v1"`；
- `replay_id`、`build` 非空；
- `total_frames` 为大于 0 的整数；
- `abc_sha256` 为 64 位小写十六进制；
- 若提供 `--replay-id`，必须与 `meta.replay_id` 一致；
- 若 `init/abc_header.json` 存在：`schema`、`replay_id`、`header.totalFrameNum`、
  `header.builds[-1]` 必须分别与 meta 的 schema、replay_id、total_frames、build 一致。

C 骨架**不**重新计算 `.abc` 的 SHA-256（fixture 目录里通常没有 `.abc`）。
需要重算时用下面的 validator：

```bash
python host/scripts/validate_fixture.py host/fixtures/20261102_161129
python host/scripts/validate_fixture.py host/fixtures/20261102_161129 \
  --abc data/replays/<file>.abc --json
```

validator 只依赖 Python 标准库，返回：

- `0`：fixture 合法；
- `1`：存在错误；
- `2`：用法错误或 fixture 目录不存在。

它会额外检查 `init/players.json` 的字段/顺序/entity 唯一性，并与
`abc_header.json.players` 对拍；`context_snapshot.json` 只做形状检查，并明确标注
“只读抓取，不代表宿主已构造 context”。

## 6. 退出码

| 退出码 | 含义 |
|---|---|
| `0` | 所有请求的已实现阶段通过 |
| `2` | 参数/用法错误 |
| `10` | 依赖库 `dlopen` 失败（`libpandora/libpixuiCurl/libPixUI_Unity/libpuerts`） |
| `11` | `libGameCore.so` 加载失败，或缺少 `ModuleInit` 等必需导出 |
| `12` | 构建偏移 `ModuleInit - base` 与已验证 profile 不符，或注册表槽位异常 |
| `20` | fixture 缺失、JSON 非法、字段/交叉校验失败 |
| `30` | databin 目录/块文件/头校验失败，或安装注册表失败 |
| `31` | databin 查询校验失败（`DT_Count` 或行内容不一致） |
| `40` | 请求了未实现阶段（context-init / frame-tick / state-output） |
| `90 + signal` | 宿主收到致命信号，例如 SIGSEGV=101、SIGABRT=96、SIGBUS=97 |

`ModuleInit` 返回值只作为诊断打印。已验证构建上它返回非零，因此**不能**把
“返回 0”当作成功条件。真正成功与否看阶段日志和后续退出码。

## 7. 已验证构建与偏移

当前 profile：

```text
GCHOST_PROFILE       = gc-android-arm64-build-5247758-v1
GCHOST_PROFILE_BUILD = 5247758
```

实现依赖以下构建相关偏移（相对 `dladdr(ModuleInit).dli_fbase`）：

| 符号/用途 | 偏移 |
|---|---|
| `ModuleInit` | `0x46ad0e0` |
| 注册表槽（指向 holder） | `0x5118810` |
| 注册表 holder（`void*[1024]`） | `0x52742a0` |
| CS 数组（只读诊断） | `0x52c3250` |

换构建必须重新验证这些偏移；`--allow-unverified-build` 只是让骨架继续执行，
不保证安全，也不代表新构建已适配。

## 8. 失败排查

| 现象 | 优先检查 |
|---|---|
| `10` / `11` | `--lib-dir` 是否同时包含 4 个依赖和 `libGameCore.so` |
| `12` | GameCore 构建是否 5247758；fixture `meta.build` 是否一致 |
| `20` | `meta.json` 必填字段、`abc_header.json` 的 replay/build/frame 是否与 meta 一致 |
| `30` | 块文件名是否为 `<index>_<name>.bytes.bin`，magic 是否为 `stdr`，文件长度是否满足 `0x98 + stride*rows` |
| `31` | 块 dump 是否来自同一构建；`DT_Count` 与块行数是否一致 |
| `40` | 这是预期行为：context/frame/state 尚未实现 |
| `101` | `ModuleInit` 之后访问了未验证的偏移；用正确构建或不要绕过门禁 |

## 9. 相关文件

- `host/src/gchost.c`：宿主骨架
- `host/scripts/build_host.sh`：NDK 构建
- `host/scripts/validate_fixture.py`：fixture JSON 校验器
- `host/fixtures/20261102_161129/`：当前 golden fixture
- `docs/gamecore_host.md`：总体计划与 H0–H7 里程碑
- `data/replays/_analysis/_host/`：原始探针源码与二进制（保留不动）
