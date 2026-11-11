# 路线 A 评估：il2cpp 运行时宿主（2026-11-04）

目标：在私有 ARM64 进程里初始化游戏自带的 il2cpp 运行时（不启动游戏、不登录、
不注入），加载 metadata，解析 `GameLogicHelper.AdvanceFrameCommands`，为离线
复现 Dimension.DS 模拟做准备。

## 1. 静态可行性：✅ 全部具备

`data/replays/_analysis/libil2cpp.so`（227,661,664 B）是标准 il2cpp 运行时：

- 全部标准 API 导出：`il2cpp_init`、`il2cpp_set_data_dir`、
  `il2cpp_domain_get`、`il2cpp_domain_get_assemblies`、
  `il2cpp_domain_assembly_open`、`il2cpp_class_from_name`、
  `il2cpp_class_get_method_from_name`、`il2cpp_runtime_invoke`、
  `il2cpp_field_get_value/offset`、`il2cpp_object_new`、`il2cpp_string_new`、
  `il2cpp_thread_attach`、`il2cpp_gc_disable` 等。
- DT_NEEDED 仅 7 个：liblog/libandroid/libm/libdl/libc/libstdc++/**libtprt**
  （libtprt 本地已有，1.8 MB）。
- `global-metadata.dat`（60 MB，v29）本地已有；metadata 头校验通过。
- 依赖库（libpandora/libpuerts/libPixUI_Unity/libpixuiCurl/libGameCore）本地已有。

## 2. 运行期实验：❌ 被模拟器翻译层卡死

实验宿主 `host/src/il2cpp_host.c`（A1：dlopen 依赖 + libil2cpp →
`il2cpp_init` → 枚举 image → 解析 GameLogicHelper/AdvanceFrameCommands）：

```text
dlopen libtprt/libpandora/libpixuiCurl/libPixUI_Unity/libpuerts/libGameCore  OK
dlopen libil2cpp.so  → 挂起或崩溃（未进入 il2cpp_init）
```

根因（logcat 实证）：

- **MuMu 模拟器是 x86_64 + Houdini（Intel ARM-on-x86 翻译）**：
  `houdini : [pid] executing ./il2cpp_host`。游戏与宿主都在翻译层下运行。
- libil2cpp 有 **784,859 条 R_AARCH64_RELATIVE/ABS64 重定位**
  （`DT_RELASZ=0x11f6c88`）。翻译层下逐条处理 78 万重定位极慢/不稳定：
  `timeout 240/420` 均未完成；短时后台运行进程即消失。
- 游戏自身能加载 libil2cpp（冷启动 60-90 s），但那是经 UnityPlayer/
  libmain 的加载路径；独立宿主复现该加载在当前模拟器上不可行。

## 3. 结论与建议

- **路线 A 的静态前提完全成立**（标准 il2cpp API + 本地二进制齐全），
  但**当前 MuMu（Houdini 翻译）环境不适合独立 il2cpp 宿主**。
- 可行条件（任一）：
  1. **真实 ARM64 设备**（手机/平板）上跑同一宿主 —— 原生执行，无翻译层；
  2. ARM64 服务器/云手机（原生 ARM64 Android）；
  3. 在 x86 上用 QEMU 全系统 ARM64（性能更差，不推荐）。
- 在满足条件的设备上，A1 之后的步骤：
  - A2：`il2cpp_init` 成功后解析 `GameLogicHelper.AdvanceFrameCommands`、
    `HeroData`/`ActorData`/DS 类；
  - A3：构造/复用 `CSDT_FRAPBOOT_INFO` 对象，调用 AdvanceFrameCommands；
  - A4：接 `.abc` 帧流 → DS 模拟 → 读取 `DSTransferRefArray` 状态。

## 4. 产物

- `host/src/il2cpp_host.c`（A1 探针，含 SIGSEGV/dlsym 日志）
- `host/scripts/build_host.sh`（NDK r28b 构建）
- 设备侧部署：`/data/local/tmp/gc/sim/`（libil2cpp + metadata + 依赖 + 宿主）

## 5. 物理 ARM64 复测（2026-11-04 晚）

连接设备 `10CEB60NHS001DX`：`arm64-v8a`、V2352A、Android 16（非 Houdini）。
在新目录 `/data/local/tmp/gc/sim_orig` 复测，未改 B 的 `/data/local/tmp/gc/sim`。

### 5.1 DT_INIT 是 dlopen 卡死/崩溃的根因

`libil2cpp.so` 动态段：

```text
DT_INIT = 0xE56145C
```

- 原始库：dlopen 进入 DT_INIT 后挂起（等 Unity/JNI 状态）；
- 把 DT_INIT 的**值**改成 0：linker 调用 base+0，SIGSEGV；
- 正确最小修补：把动态项的 **tag** 从 `DT_INIT` 改成 `DT_NULL`，linker 完全
  忽略 init，文件大小和其他 tag 不变。

脚本：

```bash
python host/scripts/patch_libil2cpp_init_tag.py \
    data/replays/_analysis/libil2cpp.so host/build/libil2cpp_noinit_tag.so
```

复测结果：

```text
dlopen libil2cpp.so OK
il2cpp_set_data_dir(".")
il2cpp_init -> SIGSEGV
  pc = bionic/libc.so +0xb2f44   (__memset_aarch64)
  lr = libil2cpp.so +0x3bdbc64   (_Znwm / operator new, after bl malloc)
  x0=0x7fcb251760 x1=0x7fcb25175b x2=0x7fcb24fe7b x3=0x7fcb252fe0
```

`x2`/`x3` 不是合法 size/目标：memset 被以接近栈顶的地址和超大长度调用。
调用链是 `il2cpp_init -> operator new -> malloc -> memset`，不是缺 JNI 符号，
也不是单纯栈上限（`ulimit -s 65536` 重跑同点崩溃）。下一步应查：
- 跳过 DT_INIT 是否留下未初始化的 C++ new-handler/allocator 全局；
- `global-metadata.dat` 与 libil2cpp 的版本是否匹配；
- 或者用真实 Unity/JNI 入口加载 libil2cpp，而不是独立 dlopen。

### 5.2 原始 DT_INIT 是 futex 死锁，不是慢

独立目录 `/data/local/tmp/gc/sim_orig_init` 跑原始库：

```text
dlopen libil2cpp (6 deps) ...
状态: S
wchan: futex_wait_queue
/proc/<pid>/syscall: futex(0xb400007afd617a80, FUTEX_WAIT, ...)
```

单线程、无其他线程可解锁，说明 DT_INIT 的静态初始化在等游戏引擎/Unity
线程创建的锁。结论：

- **不能直接跑原始 DT_INIT**（死锁）；
- **跳过 DT_INIT 也不够**（C++ 静态全局未初始化，`il2cpp_init` 的
  operator new 用了错误 size）；
- 独立 il2cpp 宿主需要“只跑必要的静态初始化”或复用真实 Unity/JNI
  加载链，不能只靠 dlopen 一个 libil2cpp.so。

补充实验：把 `il2cpp_init+0x1C` 的 `bl setlocale` NOP 掉后，崩溃前移到
libc `+0xC87D0`（x0=0），说明后面还有其它未初始化的 C++ 静态字符串。
逐条 NOP 是 whack-a-mole，不能作为路线；必须补静态初始化或走真实引擎加载。


### 5.2 复现

```bash
adb -s 10CEB60NHS001DX shell \
  "mkdir -p /data/local/tmp/gc/sim_orig && \
   ln -sf /data/local/tmp/gc/sim/{libtprt.so,libpandora.so,libpixuiCurl.so,libPixUI_Unity.so,libpuerts.so,libGameCore.so,global-metadata.dat} \
   /data/local/tmp/gc/sim_orig/"
adb push host/build/libil2cpp_noinit_tag.so \
  /data/local/tmp/gc/sim_orig/libil2cpp.so
adb push host/build/il2cpp_host /data/local/tmp/gc/sim_orig/
adb -s 10CEB60NHS001DX shell \
  "cd /data/local/tmp/gc/sim_orig && ./il2cpp_host ."
```

## 3. 2026-11-04 晚：反作弊是唯一闸门（原生 ARM64 实测）

MuMu 的挂起与 ARM64 真机的挂起**不是同一个原因**。真机 backtrace：

```text
#02 libc  sem_wait
#03 libtprt.so +0x6c454
#04 libtprt.so +0x6c2c0
#05 libtprt.so +0x6dea0
#06 libil2cpp.so (mapping 0xd908000) +0x1518
```

- `DT_INIT` 里的 `blr x8` 调用的是 libtprt 注册进去的检查函数，它在私有进程里
  永远等一个只有真实游戏进程才会 signal 的 semaphore。
- 直接 NOP 掉调用会走到 `0xd909520`：`mov w0,#0x19; mov x8,#0x5e; svc #0`
  —— **`exit_group(25)`**。检查函数必须返回**奇数**（`tbnz w0,#0` 才跳过退出），
  返回 0/偶数即自杀。这解释了所有 `rc=25`。

当前做法（待真机复测）：

```text
libtprt.so      → 空壳：只导出 g_tprt_pfn_array/g_tprt_ori_array/
                  unwind_xx_*/JNI_OnLoad，构造函数把表填成 ret0
libil2cpp.so    → 0xd909518: blr x8 改为 mov w0,#1 ; nop
```

GameCore 本身不依赖 libtprt（DT_NEEDED 无此项），所以空壳只影响 il2cpp 的
保护层。下一步：确认 `il2cpp_init` 返回 0、枚举到 `Scripts.GameCore.dll`、
解析 `GameLogicHelper.AdvanceFrameCommands`，再把 frame-0 context 接进来。
