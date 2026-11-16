# 官网（雨乐赛训）

产品站源码。纯静态、无框架、无打包器，`python scripts/build_website.py` 直接渲染出可部署的 `dist/`。

```
website/
├── src/            # 手写模板（{{TOKEN}} 占位）
│   ├── index.html      # 首页：首屏 / 适用范围 / 能力台账 / 工作流 / 数据主权 / 开发者 / 最近更新 / 下载 CTA
│   ├── download.html   # 下载 + 版本发布卡 + 赞助
│   ├── guide.html      # 安装与升级 + 常见问题
│   ├── changelog.html  # 更新日志（渲染自 CHANGELOG.md）
│   ├── 404.html
│   ├── style.css
│   └── assets/         # 自托管字体（Manrope + Noto Serif SC 子集）、产品截图（img/）
└── dist/           # 构建产物（git 忽略）
```

## 视觉系统

官网和产品端共用青瓷色，但版面语言不同：产品是一张密集的工作台，官网是一页安静的印刷品。

- **颜色**：暖纸底 `#f3efe5`、墨 `#111a16`、青瓷 `#246b63`、珊瑚 `#c9553a`。
  珊瑚只做信号色——首屏强调字、失败 / 提示标记、页眉小方点；不用它铺大面积色块。
- **字体**：宋体（Noto Serif SC 500）只负责 h1 / h2 / 引文 / 页脚字标；正文用 Manrope +
  系统中文，16px 起，最小到 12px；数字与标签用等宽。字号与间距用 `clamp()` + rem。
- **控件**：沿用产品端的圆角体系（按钮 7px、面板 10 / 14 / 20px）、44px 触控高度、160ms 过渡。
  所有按钮 `min-height: 44px`，不写死 `height`。
- **版面**：一条 1200px 栅格、一个 `--section-y` 竖向节奏、一种章节头（编号 + 标题在左，导语在右）。
  分区之间用细线分隔，不靠阴影和色块堆叠。
- **克制**：首屏只有一个焦点（产品窗口 + 图注）；不做旋转卡片、渐变光斑、虚线印章、装饰性大标语。
- **动效**：`[data-reveal]` 进入视口时上浮 14px、600ms；`prefers-reduced-motion` 下全部取消。
- **移动端**：导航用原生 `<dialog>`（Esc、点遮罩关闭、关闭后焦点回到触发按钮），
  表格在自身区域内横向滚动，不撑宽页面。

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
| `{{SITE_NAME}}` `{{SITE_FULL_NAME}}` `{{BRAND_SUB}}` | `scripts/build_website.py` 顶部的站点名常量 |
| `{{VERSION}}` `{{RELEASE_DATE}}` | `version.py` |
| `{{LATEST_NOTES}}` `{{LATEST_VERSION}}` `{{LATEST_DATE}}` | `CHANGELOG.md` 最近一个已发布版本 |
| `{{CHANGELOG_SECTIONS}}` | `CHANGELOG.md`（默认不渲染「未发布」段） |
| 产品截图 | `website/src/assets/img/*` 原样拷进 `dist/assets/img`（构建会清掉多余的旧图） |
| `{{DOWNLOAD_URL}}` | 安装版直链，默认按版本拼 Gitee Releases；可用 `--download-url` 覆盖 |
| `{{FULL_DOWNLOAD_URL}}` | 免安装版直链，默认按版本拼 Gitee Releases；可用 `--full-download-url` 覆盖 |
| `{{GITHUB_DOWNLOAD_URL}}` | GitHub Releases 页面，海外备用 |
| `{{RELEASE_PAGE_URL}}` | Gitee 当前版本的 Release 页面（校验和 / 全部文件） |
| `{{SITE_URL}}` | 站点根地址，默认 GitHub Pages；搬 CloudBase 后用 `--site-url` 覆盖 canonical / sitemap |
| `{{ASSET_VERSION}}` | `style.css` 与 `assets/` 的内容指纹，用于绕开 Pages 的 10 分钟资源缓存 |

改版本号、写 CHANGELOG、换截图，三个动作就能发一版官网，不需要动 HTML。

## 字体

宋体只保留站点实际用到的字：`python scripts/build_website_fonts.py` 从 OFL 授权的 Noto Serif SC Medium
生成子集（约 693 字形 / 301 KB，缺字检查为 0）。**改完页面文案要重跑一次**，否则新字会回退到系统宋体。
许可证见 `assets/noto-serif-sc-OFL.txt`。

## 部署

- **国内主站**：构建后把 `website/dist/` 上传到腾讯云 CloudBase 静态网站托管。默认域名国内直连、不需要备案；免费额度和默认域名有效期以控制台为准。构建时用 `--site-url https://<环境默认域名>` 让 canonical / sitemap 指向新站。
- **海外备用**：`.github/workflows/website.yml` 仍会把 `dist/` 发到 GitHub Pages，保留海外访问。
- **下载**：安装包和补丁发在 Gitee Releases（`Rainfun42/kpl-scrim-lab-app`），官网按钮默认指向 Gitee 当前版本的直链；GitHub Releases 只作海外备用。
- 首次启用 GitHub Pages：仓库 Settings → Pages → Source 选「GitHub Actions」。

## 约定

- 首屏、下载 CTA、安装说明构成转化路径，改文案时保持「本机运行、数据不外传、不弹 UAC」这三个事实准确。
- 未签名的安装包要在下载区说明清楚，别让用户以为下载坏了。
- 截图只放真实产品画面，且必须是合成演示数据（`示例战队` / `星轨战队` / `示例选手`）；空状态、加载中、报错页和真实选手档案不要放上去。
- 首屏只有一个视觉焦点；新增分区沿用现有章节头与间距，不要另起一套卡片风格。
- 珊瑚只做信号色，不要拿它做按钮底色或大面积背景。
- CSS 与首屏截图通过 `{{ASSET_VERSION}}` 加查询串；不要去掉，否则 GitHub Pages 的 10 分钟缓存会让新 HTML 配到旧 CSS。
- 站点名在 `scripts/build_website.py` 里只写一处；换品牌只改 `SITE_NAME / SITE_FULL_NAME / BRAND_SUB`。
