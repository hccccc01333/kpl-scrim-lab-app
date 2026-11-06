# 更新与发布

赛训组拿到的是免安装包，不是仓库源码。更新由工作台内置的更新器完成，
只替换程序文件，永远不修改 `data/`、`.env` 和 `data/camp_auth.json`。

## 发布物

`python scripts/make_release.py` 在 `dist/` 生成：

| 文件 | 内容 |
|---|---|
| `KPL赛训工具-<版本>-full.zip` | 首次安装，内置 Python 与核心依赖 |
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
5. 国内镜像可把 `patch-*.zip` 与 `update.json` 同步到 Gitee 发行版/仓库，
   客户端通过 `UPDATE_MANIFEST_URLS` 配置多个地址。

GitHub Release 的 `releases/latest/download/update.json` 是稳定地址；
清单里的相对 `patch-*.zip` 会自然解析到同一个 Release，不需要域名和服务器。
Gitee 镜像建议把 `patch-*.zip` 与 `update.json` 放在同一目录（仓库 raw 或发行版附件），
这样相对路径同样有效；如果补丁在另一个地址，构建时用 `--base-url` 生成一份
指向 Gitee 的清单，并在 `update_config.json` 里把 Gitee 地址放在第一位。

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
| `UPDATE_MANIFEST_URLS` | 更新清单地址，逗号分隔；留空时读取 `update_config.json`，再回退到内置 GitHub 地址 |
| `UPDATE_ALLOW_HTTP` | 仅本地调试时允许 http 更新源，正式使用保持 0 |
| `TRAINING_PORT` | 重启健康检查使用的端口，默认 8766 |

`update_config.json` 位于应用根目录，完整包内置一份空列表：

```json
{
  "manifestUrls": [
    "https://gitee.com/<你的账号>/kpl-scrim-lab/raw/master/update.json",
    "https://github.com/hccccc01333/kpl-scrim-lab/releases/latest/download/update.json"
  ]
}
```

交付前把 Gitee 镜像放在第一位即可。增量包不会覆盖这个文件，方便按队伍配置不同镜像。

## 源码用户

源码目录不要使用增量包。运行 `更新代码.bat`，等价于：

```bash
git pull --ff-only
python -m pip install -r requirements.txt
```

增量包只面向免安装包，文件布局和依赖安装方式不同。
