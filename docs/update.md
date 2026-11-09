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
| 升级 | 同 `AppId`，装新包直接覆盖，安装前会调 `/api/shutdown` 停旧服务 |
| 可选 | 安装时可勾选「开机后台启动」（写入 HKCU Run，不弹浏览器） |

安装包与增量更新并存：日常代码变更仍然发 `patch-*.zip`（几 MB），
只有换内置 Python、增删核心依赖或需要改快捷方式时才发新安装包。

### 没有代码签名时怎么交付

安装包目前是未签名的（`NotSigned`）。它不影响运行，Windows 只会在特定路径上拦一下：

| 分发方式 | 是否触发拦截 | 说明 |
|---|---|---|
| 微信 / QQ / 网盘客户端传 zip，解压后运行 | 一般不会 | 首选，文件不带网络标记 |
| U 盘拷贝 | 不会 | 可以 |
| 浏览器从网页/GitHub 直接下 exe | 会弹「Windows 已保护你的电脑」 | 点「更多信息 → 仍要运行」，或右键属性勾「解除锁定」 |
| 机器开启了「智能应用控制」(Smart App Control) | 直接拦，签名也未必过 | 设置 → 隐私和安全性 → Windows 安全中心 → 应用和浏览器控制，关闭后安装 |

两个容易忽略的点：

- 安装器是 `PrivilegesRequired=lowest`，**不触发 UAC**，所以不会出现「未知发布者」的
  管理员授权弹窗——大部分人对未签名程序的恐惧来自那一下 UAC，我们本来就没有。
- 拦截只发生在**第一次安装**。之后走内置增量更新（`patch-*.zip`），不经过 Windows
  安装器，也不会再触发任何信任检查。

发布时把 `.sha256` 和安装包一起发，或在群里贴哈希，收到的人本地核对即可：

```powershell
Get-FileHash .\KPL赛训工具-1.0.0-setup.exe -Algorithm SHA256
```

`make_installer.py` 每次构建都会生成 `*.exe.sha256` 并打印摘要。

以后有预算再补签名——Azure Trusted Signing 约 $9.99/月，是目前个人开发者最便宜的
真证书路径；OV 证书几百到两千一年。签名后用：

```powershell
signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 <setup.exe>
```

自签名证书（`New-SelfSignedCertificate`）不解决问题：别人机器不信任你的根证书，
仍显示未知发布者，还要每台机器装一次证书——除非你能控制全部目标机器，否则不值得做。

## 客户端行为

- 启动后延迟检查，结果缓存 6 小时；网络失败静默，不阻塞工作台。
- 发现新版本时右下角显示版本、更新说明和“立即更新 / 选择本地更新包 / 稍后”。
- 立即更新：服务端下载增量包 → 校验 SHA-256 → 暂存 → 退出 → 独立更新进程替换文件 →
  重启 → 轮询 `/api/health`。启动失败自动回滚到上一版本并重启。
- 本地更新包：离线时把 `patch-*.zip` 发给教练，在提示里选择文件即可。
- 旧代码备份在 `data/backups/code-<旧版本>-<时间>/`，默认保留最近 5 份。
- 更新日志：`logs/update.log`、`logs/update-server.log`、`data/update/last_result.json`。

## 配置

| 变量 | 说明 |
|---|---|
| `UPDATE_MANIFEST_URLS` | 更新清单地址，逗号分隔；留空时读取 `update_config.json`，再回退到内置 Gitee / GitHub 地址 |
| `UPDATE_ALLOW_HTTP` | 仅本地调试时允许 http 更新源，正式使用保持 0 |
| `TRAINING_PORT` | 重启健康检查使用的端口，默认 8766 |

`update_config.json` 位于应用根目录，完整包内置一份（Gitee 第一位，GitHub 海外备用）：

```json
{
  "manifestUrls": [
    "https://gitee.com/Rainfun42/kpl-scrim-lab-app/raw/main/update.json",
    "https://github.com/hccccc01333/kpl-scrim-lab-app/releases/latest/download/update.json"
  ]
}
```

交付前把 Gitee 镜像放在第一位即可。增量包不会覆盖这个文件，方便按队伍配置不同镜像。

> 如果 Gitee 仓库是从 GitHub 镜像自动同步的，`update.json` 也要提交到 GitHub 仓库根目录，
> 或单独建一个只放 manifest 的 Gitee 仓库，避免同步时被覆盖。

## 源码用户

源码目录不要使用增量包。运行 `更新代码.bat`，等价于：

```bash
git pull --ff-only
python -m pip install -r requirements.txt
```

增量包只面向免安装包，文件布局和依赖安装方式不同。
