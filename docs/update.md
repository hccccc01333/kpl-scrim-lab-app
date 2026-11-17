# 更新与发布

赛训组拿到的是免安装包，不是仓库源码。更新由工作台内置的更新器完成，
只替换程序文件，永远不修改 `data/`、`.env` 和 `data/camp_auth.json`。

## 发布物

`python scripts/make_release.py` 在 `dist/` 生成：

| 文件 | 内容 |
|---|---|
| `KPL-Scrim-Lab-<版本>-full.zip` | 首次安装，内置 Python 与核心依赖 |
| `patch-<版本>.zip` | 增量包，只含变更文件与 `update.json` |
| `update.json` | 更新清单，供 `/api/update/check` 读取 |

常用命令：

```bash
# 首次发布 / 重发全量补丁
python scripts/make_release.py --all

# 日常发版：对比上一个 git tag，只打包变更文件
python scripts/make_release.py

# 跳过完整包，只出增量包
python scripts/make_release.py --no-full

# 离线构建：复用本地 Python embeddable 与依赖目录
python scripts/make_release.py --python-archive D:\cache\python-3.12.10-embed-amd64.zip \
  --deps-dir D:\cache\site-packages
```

完整包构建时会在 `dist/build-*` 中用内置 Python 执行 `import server` 冒烟测试；
导入失败会中止打包，避免发出起不来的包。

如果本次更新改了 `requirements.txt`、内置 Python 版本或需要新增核心依赖，
不要只发增量包：同时提供完整包，并把 `--min-version` 设为新版本，让旧客户端
看到“需要下载完整包”的提示。增量包只替换程序文件，不安装依赖。

## 发布流程

1. 修改 `version.py`，并在 `CHANGELOG.md` 写对应版本段落（清单里的更新说明来自这里）。
2. 提交并打 tag：`git tag v1.0.1 && git push origin v1.0.1`。
3. CI（`.github/workflows/release.yml`）自动构建增量包与 `update.json`，上传到 GitHub Release。
4. 完整包在 Windows 本机构建后手动上传到同一个 Release；首次安装才需要。
5. 国内镜像把 `patch-*.zip`、`update.json`、完整包同步到 Gitee 发行版
   （`Rainfun42/kpl-scrim-lab-app`），并把 `update.json` 提交到仓库根目录，
   客户端用 `raw/main/update.json` 做稳定清单地址。

   Gitee 单附件上限 100MB：完整包 / 安装包超过时，至少传 `patch-*.zip` 与
   `update.json`，`full.url` 指向 GitHub（或另外的网盘/对象存储）。这样
   `minVersion` 以上的用户仍能增量更新；低于门槛的用户需要单独提供完整包。

### 1.6.3 的增量包基线（重要）

当前仓库里 `v1.5.29`～`v1.5.32` 这几个 tag 的树和 `main` 历史对不上
（`git tag --merged HEAD` 里没有它们，`git describe` 停在 `v1.5.15`），所以
`make_release.py` 自动选起点会退到 `v1.5.15`。1.6.3 的增量包因此是拿
`dist/KPL-Scrim-Lab-1.5.32-full.zip` **实际发布包**逐文件比对生成的（39 个文件，
`minVersion=1.5.32`）；完整包用 1.6.2 发布包的 runtime 覆盖当前程序文件生成，
并用内置 Python 做过 `import server` 冒烟与「1.6.2 安装包 → 一键更新到 1.6.3」端到端验证。

以后发版前先把 tag 打在 `main` 的发布提交上（例如 `git tag v1.6.3 && git push gitee v1.6.3`），
`make_release.py` 的自动基线就会正常；否则继续按「包对包」的方式生成增量包。

GitHub Release 的 `releases/latest/download/update.json` 是海外稳定地址；
清单里的相对 `patch-*.zip` 会自然解析到同一个 Release。
国内镜像不要在清单里用相对路径：清单在 Gitee raw、包在 Releases 时会解析到错误目录。
发版时给构建命令传 `--base-url https://gitee.com/Rainfun42/kpl-scrim-lab-app/releases/download/v<版本>/`，
让 `patch.url` / `full.url` 变成绝对地址，然后把生成的 `update.json` 提交到 Gitee `main`。

## 安装包（推荐的交付方式）

免安装包适合测试，正式交给赛训组用安装包：

```bash
python scripts/make_installer.py            # 复用 dist/ 里的 full 包
python scripts/make_installer.py --rebuild  # 依赖或内置 Python 变了才需要
```

产物：`dist/KPL-Scrim-Lab-<版本>-setup.exe`（约 58 MB）。构建流程：

1. 解包 `dist/KPL-Scrim-Lab-<版本>-full.zip`，得到内置 Python 与依赖；
2. 用当前工作树覆盖程序文件（`ship_files()`），所以改完代码不用重打完整包；
3. 调 Inno Setup 编译 `packaging/installer.iss`。

安装包的行为：

| 项目 | 说明 |
|---|---|
| 安装位置 | `%LOCALAPPDATA%\KPL赛训工具`，按用户安装，不弹 UAC |
| 快捷方式 | 桌面 + 开始菜单组（启动 / 停止 / 检查更新 / 数据目录 / 日志目录 / 使用说明） |
| 卸载 | 出现在「应用和功能」，卸载前自动优雅停止服务 |
| 数据 | `data/` 永不被卸载删除；重装或升级沿用原目录 |
| 升级 | 同 `AppId`，装新包直接覆盖，安装前会自动停掉旧服务 |
| 可选 | 安装时可勾选「开机后台启动」（写入 HKCU Run，不弹浏览器） |

安装包与增量更新并存：日常代码变更仍然发 `patch-*.zip`（几 MB），
只有换内置 Python、增删核心依赖或需要改快捷方式时才发新安装包。

## 客户端行为（1.6.3 起，2026-11-17 起增强）

- 打开工作台后自动检查：页面加载完约 1.5 秒请求 `/api/update/check`，之后每
  `autoCheckMinutes`（默认 30 分钟）复查一次；从别的标签页切回来时如果距上次检查
  超过 30 分钟，也会补查一次。定时检查会带 `force=1` 绕过服务端 6 小时清单缓存；
  离线静默，不阻塞工作台。
- 发现新版本时右下角弹出卡片：当前版本 / 新版本 / 增量包大小 / 更新摘要，按钮
  「立即更新 / 选择本地更新包 / 稍后」。
- **自动下载**：发现新版本后不等点击，先在后台请求 `/api/update/prepare`：下载增量包 →
  校验 SHA-256 → 暂存到 `data/update/staged/`。成功时卡片显示「已自动下载」，
  按钮变成「立即重启更新」；点它只需要重启服务完成安装，不再等下载。
  下载失败不打扰，仍可点「立即更新」重试；跨版本（低于 `minVersion`）不自动下载，
  按卡片引导下载完整包。用 `update_config.json` 的 `"autoDownload": false` 或环境变量
  `UPDATE_AUTO_DOWNLOAD=0` 可关闭后台下载。
- 立即更新：服务端复用已暂存的包；没有暂存包时下载增量包 → 校验 SHA-256 → 暂存 →
  服务退出 → 独立更新进程替换文件 → 重启 → 前端轮询 `/api/health`，以新版本回来后
  自动刷新页面；启动失败自动回滚到上一版本。
- 选择本地更新包：完全离线时把 `patch-<版本>.zip` 发给教练，在卡片里选文件上传，
  同样走校验 → 应用 → 重启。
- 稍后：本次会话内不再打扰（同一标签刷新也不弹），下次打开工作台再提示。
- 版本过旧（低于清单 `minVersion`）不提供增量更新，卡片引导下载完整包 / 安装包。
- 页脚「检查更新」随时可手动检查；已是最新、检查失败都会在底部给一行提示。
  检查失败时会把原因（哪个源连不上）带出来，不再「点了没反应」；只拿到旧缓存时
  会明确说「暂用上次结果」。
- 多镜像：所有清单地址并发读取，取**版本号最高**的一份，而不是「谁先返回用谁」。
  这样 Gitee 镜像还停在旧版时，不会把 GitHub 上刚发布的新版吃掉。
  `/api/update/check` 的 `mirrors` 字段会列出每个源的成功/失败、版本与错误，便于排查；
  `stale` 表示当前结果来自本地缓存（所有源都没连上），`reason` 是最后一次失败原因。
- 源码目录（根目录有 `.git`）不弹自动更新，`/api/update/stage|apply|prepare` 也会拒绝：
  请运行 `更新代码.bat`（= `git pull --ff-only` + 装依赖）。
- 旧代码备份在 `data/backups/code-<旧版本>-<时间>/`，默认保留最近 5 份。
- 更新日志：`logs/update.log`、`logs/update-server.log`、`data/update/last_result.json`。

## 配置

| 变量 | 说明 |
|---|---|
| `UPDATE_MANIFEST_URLS` | 更新清单地址，逗号分隔；留空时读取 `update_config.json`，再回退到内置 Gitee / GitHub 地址 |
| `UPDATE_ALLOW_HTTP` | 仅本地调试时允许 http 更新源，正式使用保持 0 |
| `UPDATE_AUTO_DOWNLOAD` | `0` 关闭后台自动下载；默认开启。也可在 `update_config.json` 写 `"autoDownload": false` |
| `TRAINING_PORT` | 重启健康检查使用的端口，默认 8766 |

`update_config.json` 位于应用根目录，完整包内置一份（Gitee 第一位，GitHub 海外备用）。
除 `manifestUrls` 外还支持两个可选键（不写就用默认值，旧配置文件无需改动）：

```json
{
  "manifestUrls": [
    "https://gitee.com/Rainfun42/kpl-scrim-lab-app/raw/main/update.json",
    "https://github.com/hccccc01333/kpl-scrim-lab-app/releases/latest/download/update.json"
  ],
  "autoDownload": true,
  "autoCheckMinutes": 30
}
```

`autoCheckMinutes` 会被夹在 5–1440 之间。交付前把 Gitee 镜像放在第一位即可；
增量包不会覆盖这个文件，方便按队伍配置不同镜像。

> 发版后请确认**每个镜像**的 `update.json` 版本一致。客户端会取最高版本，
> 但下载资源仍从清单里 `patch.url` 指向的地址取；首选镜像只有旧清单、新包只在
> 另一个镜像上时，用户能看到更新却下载失败。

> 如果 Gitee 仓库是从 GitHub 镜像自动同步的，`update.json` 也要提交到 GitHub 仓库根目录，
> 或单独建一个只放 manifest 的 Gitee 仓库，避免同步时被覆盖。

## 源码用户

源码目录不要使用增量包。运行 `更新代码.bat`，等价于：

```bash
git pull --ff-only
python -m pip install -r requirements.txt
```

增量包只面向免安装包，文件布局和依赖安装方式不同。源码目录里工作台不会自动提示更新
（`/api/update/check` 会返回 `sourceMode: true`），`stage` / `apply` / `prepare` 接口也会拒绝覆盖。
