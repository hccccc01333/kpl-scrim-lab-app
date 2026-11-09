# packaging —— Windows 安装包资源

这里是「把平台做成一个能双击安装的软件」的那一层。业务代码不在这里，
本目录只放构建输入。

| 文件 | 作用 |
|---|---|
| `installer.iss` | Inno Setup 6 脚本：安装位置、快捷方式、卸载项、升级前停服 |
| `app.ico` | 应用图标（多尺寸 16–256），由 `make_icon.py` 从 V3 品牌标记生成 |
| `app-256.png` | 图标预览，用于文档与商店页 |
| `ChineseSimplified.isl` | Inno Setup 官方仓库的简体中文语言包（Inno 不内置中文） |
| `make_icon.py` | 重画图标：`python packaging/make_icon.py` |
| `launcher_exe.py` | 安装版的 EXE 启动器薄壳：定位 `runtime\pythonw.exe` 并转给 `launcher.py` |
| `make_launcher.py` | 用 PyInstaller 构建 `KPLScrimLab.exe`（onedir，含版本信息与图标） |

## 构建

```bash
python scripts/make_installer.py            # 复用 dist/ 里的 full 包
python scripts/make_installer.py --rebuild  # 依赖或内置 Python 变了才需要
```

产物 `dist/KPL-Scrim-Lab-<版本>-setup.exe`。

流程是「full 包 + 覆盖」：解包 `dist/KPL-Scrim-Lab-<版本>-full.zip`（内置 Python、
依赖、data 骨架），再用当前工作树的 `ship_files()` 覆盖程序文件，最后交给
ISCC 编译。所以改完代码直接跑一次即可，不需要重打 64 MB 的运行时。

依赖 ISCC.exe；没装时：

```bash
winget install -e --id JRSoftware.InnoSetup
```

## 设计约束

- **安装到用户目录**（`%LOCALAPPDATA%`），`PrivilegesRequired=lowest`，不弹 UAC。
- **卸载保留 `data/`**：卸载器只删程序文件、日志和更新缓存；比赛数据、授权、
  备份留给用户，重装后自动沿用。
- **升级前先停服**：`[Code]` 里调 `http://127.0.0.1:8766/api/shutdown`，
  等进程退出，15 秒内没退再 `taskkill` 兜底，避免文件被占用。
- **不要打成单文件 exe**：Python 代码必须保持散文件，否则 `patch-*.zip`
  增量更新会失效，每次改一行都要全量重下。

## 已知缺口

- 没有代码签名证书，安装时 Windows 会提示「未知发布者」。拿到证书后：
  `signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 <setup.exe>`。
- 启动入口是 `KPLScrimLab.exe`（PyInstaller onedir 薄壳），双击后它再调
  `runtime\pythonw.exe launcher.py`；任务管理器里常驻的是 pythonw。
  要做托盘图标 / 常驻窗口时，再把这个薄壳换成带消息循环的原生启动器。
- 没有开机自启以外的系统集成（文件关联、右键菜单）——目前用不上。
