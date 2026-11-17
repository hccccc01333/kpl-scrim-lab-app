---
name: 赛训数据 · 青瓷
description: 温润的青瓷浮雕与可追溯的赛训记录
colors:
  primary: "#246b63"
  primary-hover: "#19574f"
  porcelain: "#fafbf9"
  paper: "#ffffff"
  ink: "#292f2d"
  secondary-text: "#5c6963"
  quiet-text: "#68766f"
  celadon-wash: "#e0eeea"
  border: "#dfe6e0"
typography:
  display:
    fontFamily: "Celadon Serif, Noto Serif SC, Source Han Serif SC, Songti SC, serif"
    fontSize: "4.75rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.045em"
  headline:
    fontFamily: "Celadon Serif, Noto Serif SC, serif"
    fontSize: "2.25rem"
    fontWeight: 700
    lineHeight: 1.35
  body:
    fontFamily: "Manrope, Noto Sans SC, Microsoft YaHei UI, PingFang SC, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.6
rounded:
  sm: "7px"
  md: "10px"
  lg: "12px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  desktop-gutter: "40px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.paper}"
    rounded: "{rounded.sm}"
    height: "40px"
    padding: "8px 14px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-cover:
    height: "48px"
    padding: "12px 24px"
---

# Design System: 赛训数据 · 青瓷

## Overview

**Creative North Star: "青瓷赛训图谱"**

用户明确选择了青瓷浮雕视觉稿。首页像一件青瓷作品旁的赛训简报：大标题、真实战绩、立体峡谷与经济图表同处一张温润的白色画布。图像承担主视觉，控件安静而清楚。

分析页面使用同一套青白色、展示字体与数据字体。让战队、英雄、分路和真实对局内容构成页面，不把每个段落都拆成装饰卡片。

**Key Characteristics:**

- 一幅有实物质感的青瓷浮雕。
- 展示标题使用中文衬线，控件与密集数据使用无衬线。
- 战绩、时间轴与对局记录仍可操作、可追溯。
- 网页与客户端共享颜色、字体、素材和基础控件。

## Colors

青白底色与低饱和青绿构成主要画面。`v3/public/ui-tokens.css` 是实现的变量来源。

- 青绿用于主要操作、选中状态与本队曲线。
- 墨色用于标题与正文；次级文字保持可读。
- 胜负、异常和告警保留文字标记，不能只靠色彩区分。
- 深色主题使用独立的背景、文字与边界变量，浮雕保留原有釉色。

## Typography

`Celadon Serif` 是基于现有 Noto Serif SC 许可字体构建的本地子集。首页标题 4.75rem，常规页面标题 2.25rem，首页分区标题 1.625rem。手机首页标题为 3rem，常规标题为 1.75rem。

中文正文使用 Noto Sans SC，英文与数字优先 Manrope。战绩大数字使用 Georgia，表格与指标启用等宽数字。图表与辅助信息跟随可用空间调整，不能把正文文字烘焙进图片。

## Layout

顶部导航高 72px，手机为 60px。网页主内容最大宽 1560px，首页为 1640px；桌面边距 40px，手机为 20px。

网页版首页以用户提供的“赛训周期简报”截图为结构基准：标题与青瓷浮雕、周期工具栏、战况与约训/覆盖、8 项指标、重点发现、复盘卡片。保留原统计口径和操作，不增加经济走势或最近对局模块。760px 以下标题与浮雕单栏排列。

青瓷封面为新增展示层。网页原有周期、视角、对比范围、战况、下一场约训、数据覆盖、指标、发现与复盘操作完整保留；客户端保留原有首页区块及其 ID、顺序、统计口径、打印和布局模式。

对局档案按训练日分组，每局显示结果、比分、时长、阵容与编辑入口。窄屏收起阵容列。复杂数据表在自身区域滚动，不撑宽整个页面。

选手名册（`#playerarchive`，`v3/public/player-archive.css`）横向上限 1640px，与顶部导航同宽，不再把内容缩在 1560 的中间。结构是一条横向工作台：报头两栏（左边一句结论 + 四个事实，右边认领进度面板）→ 四个「最高」→ 吸顶工具条 → 按战队分框的卡片墙（本队一框、每支对手一框，框内全部游戏名都是卡片，一队先铺 18 张、其余就地展开）。窄屏依次降到两栏、一栏；工具条在 1180px 以下不再吸顶。

桌面客户端保留原生窗口操作区域；宽度不足时将主导航放到第二行。所有一级功能可经导航或命令搜索访问。

## Elevation & Depth

浮雕本身的光影构成主要立体层次，使用低对比的落地阴影。普通数据表面以留白与边界区分，弹窗使用更明显的柔和阴影。没有全站毛玻璃和装饰发光。

选手名册的卡是这套里唯一允许「厚度」的表面：釉面渐变（青瓷底 + 纸白高光）、内高光、两层落地阴影。悬停抬升 3px 并换成青绿描边，勾选对比时描 2px 青绿边、底色换成釉色，右下角勾选填实。工具条吸顶时用 96% 纸白 + 背景模糊，避免和下面的卡糊在一起。

## Shapes

控件、面板、浮层分别引用 7px、10px、12px 的基础圆角。对局和指标账本使用共享分隔线。浮雕的有机轮廓来自带透明通道的 WebP，不用 CSS 多边形模拟。

选手名册把圆角提到 16–18px（卡、看点、认领面板、工具条），控件保持 10–12px，这样「大面 16、小件 10」在同一页里分得开，不会所有东西都圆成一片。

## Components

按钮和表单统一使用 40px 基础高度，首页主要操作为 48px。控件具备悬停、按下、禁用与键盘焦点状态；主操作使用青绿实底。

搜索和移动导航使用原生 `dialog.showModal()`，由浏览器处理焦点约束与 Escape。搜索支持 Ctrl/Cmd K、上下选择、Enter 打开、无结果和清空。

加载状态保留结构。次要图表接口失败时仅替换对应区域，并保留重试入口；晚到的数据不重建正在编辑的简报控件。客户端按页面加载代码，页面错误保留导航与恢复操作。

浮雕素材位于 `v3/public/media/celadon-valley.webp`。图库式展示只用于首页开场，分析区域继续以实际数据和内容为中心。

## 官网

营销站是独立版面，不复用工作台的卡片与图表组件：暖纸底 + 宋体展示标题 + 青瓷主色，珊瑚只做信号色。
页面结构、token 与字体子集见 `website/README.md`；改站点文案后需重跑
`python scripts/build_website_fonts.py`，否则新字会回退到系统宋体。

## Do's and Don'ts

- Do 以已选定的青瓷视觉稿校对首页构图与材质。
- Do 共享变量、组件与素材，并在浏览器验证桌面、平板和手机。
- Do 标注图表样本数；没有回放时解释缺失原因。
- Don't 用页面截图替代真实文字、图表或控件。
- Don't 把装饰浮雕当作本局实际地图或比赛证据。
- Don't 给每个分析区重复放置浮雕或装饰性大标题。
