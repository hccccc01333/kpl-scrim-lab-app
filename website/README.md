# 官网

产品站源码。纯静态、无框架、无打包器，`python scripts/build_website.py` 直接渲染出可部署的 `dist/`。

```
website/
├── src/            # 手写模板（{{TOKEN}} 占位）
│   ├── index.html      # 首页：首屏 / 2×2 能力卡片 / 开发者体验 / 下载 CTA / 页脚
│   ├── guide.html      # 安装与升级 + 常见问题
│   ├── changelog.html  # 更新日志（渲染自 CHANGELOG.md）
│   ├── 404.html
│   ├── style.css
│   └── assets/         # 自托管字体（Manrope + Noto Serif SC 子集）、产品截图（img/）
└── dist/           # 构建产物（git 忽略）
```

## 构建与预览

```bash
python scripts/build_website.py                 # 只构建
python scripts/build_website.py --serve         # 构建 + 本地预览 8137
python scripts/build_website.py --site-url https://<官网域名>
python scripts/build_website.py --download-url URL       # 覆盖安装版直链
python scripts/build_website.py --full-download-url URL  # 覆盖免安装版直链
python scripts/build_website.py --include-unreleased
```

## 数据来源

模板里不写死版本号和更新内容，全部来自仓库的单一真相：

| 占位符 | 来源 |
|---|---|
| `{{VERSION}}` `{{RELEASE_DATE}}` | `version.py` |
| `{{LATEST_NOTES}}` `{{CHANGELOG_SECTIONS}}` | `CHANGELOG.md`（默认不渲染「未发布」段） |
| 产品截图 | `website/src/assets/img/*` 原样拷进 `dist/assets/img`（构建会清掉多余的旧图） |
| `{{DOWNLOAD_URL}}` | 安装版直链，默认按版本拼 Gitee Releases；可用 `--download-url` 覆盖 |
| `{{FULL_DOWNLOAD_URL}}` | 免安装版直链，默认按版本拼 Gitee Releases；可用 `--full-download-url` 覆盖 |
| `{{GITHUB_DOWNLOAD_URL}}` | GitHub Releases 页面，海外备用 |
| `{{RELEASE_PAGE_URL}}` | Gitee 当前版本的 Release 页面（校验和 / 全部文件） |
| `{{SITE_URL}}` | 站点根地址，默认 GitHub Pages；搬 CloudBase 后用 `--site-url` 覆盖 canonical / sitemap |
| `{{ASSET_VERSION}}` | `style.css` 与 `assets/` 的内容指纹，用于绕开 Pages 的 10 分钟资源缓存 |

改版本号、写 CHANGELOG、换截图，三个动作就能发一版官网，不需要动 HTML。

## 部署

- **国内主站**：构建后把 `website/dist/` 上传到腾讯云 CloudBase 静态网站托管。默认域名国内直连、不需要备案；免费额度和默认域名有效期以控制台为准。构建时用 `--site-url https://<环境默认域名>` 让 canonical / sitemap 指向新站。
- **海外备用**：`.github/workflows/website.yml` 仍会把 `dist/` 发到 GitHub Pages，保留海外访问。
- **下载**：安装包和补丁发在 Gitee Releases（`Rainfun42/kpl-scrim-lab-app`），官网按钮默认指向 Gitee 当前版本的直链；GitHub Releases 只作海外备用。
- 首次启用 GitHub Pages：仓库 Settings → Pages → Source 选「GitHub Actions」。

## 约定

- 首屏、下载 CTA、安装说明构成转化路径，改文案时保持「本机运行、数据不外传、不弹 UAC」这三个事实准确。
- 未签名的安装包要在下载区说明清楚，别让用户以为下载坏了。
- 截图只放真实产品画面，且必须是合成演示数据（`示例战队` / `星轨战队` / `示例选手`）；空状态、加载中、报错页和真实选手档案不要放上去。
- 亮色编辑风：暖纸底（`#f5f1e9`）、宋体大标题（Noto Serif SC 子集）、松绿 `#0f655b` 与珊瑚 `#dd6141`，产品截图用深色窗口压在纸上形成对比。
- 首屏是 CSS 渐变 + 细点阵 + 纸张噪点，无 WebGL / 外部脚本；卡片内的比分、趋势、选手档案用 HTML/SVG 重绘，数据与 V3 口径一致。
- CSS 与首屏截图通过 `{{ASSET_VERSION}}` 加查询串；不要去掉，否则 GitHub Pages 的 10 分钟缓存会让新 HTML 配到旧 CSS。
- Noto Serif SC 只保留页面标题用字的 145 字子集（56 KB），许可见 `assets/noto-serif-sc-OFL.txt`；改标题后需重新生成子集。
