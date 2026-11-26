# 官网（雨乐赛训）

产品站源码。纯静态、无框架、无打包器，`python scripts/build_website.py` 直接渲染出可部署的 `dist/`。

```
website/
├── github.json     # 构建时读取的 GitHub 仓库信息（scripts/sync_github.py 刷新）
├── src/            # 手写模板（{{TOKEN}} 占位）
│   ├── index.html      # 首页：封面 / 示例简报 / 往下看 / 更新 / 顾虑 / 下载 CTA
│   ├── product.html    # 产品：四步链路 + 输出
│   ├── privacy.html    # 数据主权：目录、备份与搬迁
│   ├── opensource.html # 源码：命令、GitHub、许可与参与
│   ├── download.html   # 下载 + 版本发布卡 + 赞助
│   ├── guide.html      # 安装与升级 + 常见问题
│   ├── changelog.html  # 更新日志（渲染自 CHANGELOG.md）
│   ├── 404.html
│   ├── style.css
│   └── assets/         # 自托管字体（Manrope + Noto Serif SC 子集）、产品截图（img/）
└── dist/           # 构建产物（git 忽略）
```

导航是六页：首页 / 产品 / 数据主权 / 源码 / 安装说明 / 更新日志，下载作为常驻 CTA。

## 视觉系统

V21「墨玉编排」是官网唯一的视觉语言，集中在 `src/assets/v21.css`（在 v6 / v14 之后载入，
覆盖它们过时的排版决策）。产品端仍是一张密集工作台，官网则是有明确呼吸感的编排页面。

- **颜色**：暖纸 `#f5f2ea`、深墨 `#121c18`、青玉 `#1c6c5c`；赤铜 `#b86542` 只做信号点。
  内页页眉、深色分区、收尾 CTA 与页脚统一用深墨 + 青玉光晕，形成首尾呼应的框架。
- **字体**：展示标题恢复宋体（Noto Serif SC 600）并拉开字阶；正文用系统中文黑体，
  数字与标签用 Manrope 等宽。所有字号走 `clamp()` + rem，标题 `text-wrap: balance`。
- **版面**：1200px 栅格；章节编号改为青玉胶囊标签，导语改为带竖线的引言块；
  正文规则用 2 列圆角卡片（14 / 20px）与柔和投影分组，不再靠满屏横线切分。
- **首屏**：一个统一的内页封面（深墨 + 光晕 + 宋体大标题），数据口径页右侧加一张
  「计算轨迹」装饰卡，用内容本身做视觉焦点，不放无关插画。
- **图标**：导航用 CSS mask + 内联 SVG（currentColor，装饰图标不进无障碍树）；
  移动端菜单沿用原生 `<dialog>`，关闭后焦点回到触发按钮。
- **动效**：V21b 渐进增强层——首屏错峰上浮、计算轨迹进度条填充、卡片随视口滚动上浮、
  `scroll(root block)` 驱动的细进度条、顶栏随滚动方向收起；按钮按下用 `linear()` 弹性曲线。
  默认静态，只有 `prefers-reduced-motion: no-preference` 才启动，`reduce` 下内容保持终态。
- **移动端**：`@media (max-width: 980px)` 收成单列，导航用原生 `<dialog>`（Esc、
  点遮罩关闭、关闭后焦点回到触发按钮），表格在自身区域内横向滚动，不撑宽页面。
- **约束**：任何新版式都只在 `v21.css` 里做，不再往 v6 / v14 叠加第三条覆盖链。

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
| `{{GH_USER}}` `{{GH_STARS}}` `{{GH_COUNT_TEXT}}` `{{GITHUB_META}}` | `website/github.json`（`python scripts/sync_github.py` 刷新；构建只读缓存，不联网，也不产生运行时请求） |
| `{{FAQ_JSONLD}}` | 构建时从安装页 FAQ 的 `details/summary` 自动抽取成 `FAQPage` 结构化数据 |
| `{{CHANGELOG_SERIES}}` | 由 `CHANGELOG.md` 的版本号分组（1.6 / 1.5 …），供更新日志左侧索引 |
| `{{GITEE_URL}}` | Gitee 镜像仓库 |

改版本号、写 CHANGELOG、换截图，三个动作就能发一版官网，不需要动 HTML。

构建还会额外产出 `dist/feed.xml`（更新日志 RSS，47 个已发布版本）。渲染完成后会检查是否有残留的 `{{TOKEN}}`，
漏掉占位符会直接让构建失败，而不是上线后被用户看见。

## 打印

`style.css` 末尾有一组 `@media print` 规则：打印时去掉导航、目录、悬浮按钮、跑马灯与 CTA，把深色区块转成白底描边框，
FAQ 由 `beforeprint` 自动展开，文档里的外链会补上 URL。安装说明页可以直接打印给教练组。

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
