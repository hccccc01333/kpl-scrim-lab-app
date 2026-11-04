# IL2CPP/C# 初始化宿主（B 路线）B0 可行性

日期：2026-11-03。只读检查；未登录、未注入、未修改游戏文件。

## 1. APK 资产

设备 `base.apk` 的 `assets/bin/Data/Managed/` 只有：

```text
Metadata/global-metadata.dat       60,322,264 B
Resources/mscorlib.dll-resources.dat
Resources/System.Data.dll-resources.dat
Resources/Newtonsoft.Json.dll-resources.dat
```

**没有** `Assembly-CSharp.dll`、`Scripts.GameCore.dll`、`Scripts.Framework.dll` 等
托管程序集。这是 IL2CPP 的正常形态：C# 代码已 AOT 编译进 `libil2cpp.so`，
B 路线需要的是 `libil2cpp.so + global-metadata.dat + libtprt.so`，不是 DLL。

本地已有：

```text
data/replays/_analysis/libil2cpp.so        227,661,664 B
data/replays/_analysis/global-metadata.dat  60,322,264 B
data/replays/_analysis/libtprt.so            1,829,288 B
data/replays/_analysis/_host/il2cpp_probe     12,328 B
```

## 2. 独立宿主实测

推送：

```text
/data/local/tmp/il2cpp/lib/libil2cpp.so
/data/local/tmp/il2cpp/lib/libtprt.so
/data/local/tmp/il2cpp/data/global-metadata.dat
/data/local/tmp/il2cpp/il2cpp_probe
```

运行：

```bash
cd /data/local/tmp/il2cpp
LD_LIBRARY_PATH=/data/local/tmp/il2cpp/lib ./il2cpp_probe /data/local/tmp/il2cpp
```

结果：

```text
loading libil2cpp (no libtprt): .../libil2cpp.so
Illegal instruction
```

`logcat`：

```text
signal 4 (SIGILL), code 0 (SI_USER)
#00 pc ... /system/lib64/libhoudini.so
```

设备：

```text
ro.product.cpu.abi      = x86_64
ro.product.cpu.abilist  = x86_64,arm64-v8a,x86
uname -m                = aarch64
```

结论：MuMu 是 x86_64 + houdini ARM 翻译层；独立 `libil2cpp` 在 houdini 下加载后
SIGILL，无法在当前环境完成 `il2cpp_init`。这不是 metadata/路径错误，是运行环境
不满足。

## 3. B 路线门槛

B 要成立，必须满足：

1. 原生 ARM64 Android 运行环境（ARM64 AVD/真机/qemu+bionic），不是 houdini 翻译；
2. `libil2cpp` 能完成 `il2cpp_init`，能打开 metadata；
3. 能通过 `il2cpp_class_get_method_from_name` 找到 `SGW`/`GameReplayModule` 的真实
   MethodInfo（现有 `il2cpp_probe` 已实现查找逻辑）；
4. 再谈 `SGW.GameCoreInit/StartLevel` 的调用与 GameCore context 初始化。

当前 B0 **未通过**，卡在第 1 条运行环境。

## 4. 下一步

- **B1**：准备原生 ARM64 Android 环境（ARM64 AVD 或真机），重跑 `il2cpp_probe`；
  通过后再做 `SGW` 调用。
- **B2**：如果不使用 Android 设备，则搭 qemu-aarch64 + Android bionic sysroot；
  工程量更大，但可脚本化。
- **C**：放弃独立宿主，回到完整客户端回放/营地/UI 数据；不满足“一劳永逸”，
  但经济/KDA 已有验证来源。

在 B0 通过前，不继续写 C# 初始化宿主代码，避免在错误运行环境上堆实现。
