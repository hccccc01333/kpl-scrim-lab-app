# KPL Grand Finals 2026 · SVG 素材包

五张参考图共拆出 **332 个独立 SVG**。其中 218 个是纯矢量，28 个叠加了附件原图，86 个内嵌附件原图。

[预览](preview.png) · [逐项索引](INDEX.md) · [JSON 清单](manifest.json)

## 快速定位

- `surfaces/` · 背景和容器，共 25 个 · [打开示例](surfaces/main-card-container.svg)
- `broadcast/` · 赛事标题、胜负、比分和战队，共 63 个 · [打开示例](broadcast/metric-tab-blank.svg)
- `bp/` · BP 槽位、竖卡和下三分之一，共 50 个 · [打开示例](bp/hero-card-plain.svg)
- `charts/` · 图表、数值和统计行，共 77 个 · [打开示例](charts/stat-row-blank.svg)
- `modules/` · 选手、装备和位置模块，共 70 个 · [打开示例](modules/equipment-cluster-blank.svg)
- `decor/` · 角饰、高光、分隔线和色板，共 47 个 · [打开示例](decor/divider-title-flourish.svg)

## 前端接入

- 每个 SVG 都有自己的 `viewBox`，可直接通过 `<img>` 引用，也可交给设计工具。固定文字已转路径，浏览器无需加载字体。
- 动态队名、比分、选手名和统计值适合叠在 `blank` 底板上。`example` 是固定样例。统计条的 `*-fill.svg` 可按真实比例裁切，雷达图和经济差曲线需要按数据生成点位。
- `vector` 可编辑路径、渐变、描边和底板。`mixed` 和 `raster` 中的插画、徽标、照片、装备和复杂纹理来自附件，它们在 SVG 内以 PNG 或 JPEG 保存，无外部图像依赖。放大时受原图分辨率限制。
- 如需把多个 SVG 内联到同一个 DOM，给每个 SVG 的 `id`、`url(#…)` 和片段引用加唯一前缀。直接用 `<img>` 时各文件独立。
- 默认保持 `viewBox` 比例。标记 `stretch-x` 的图形适合沿横轴裁切或调整。

```html
<button type="button" aria-label="查看输出伤害">
  <img src="/kpl-finals-svg/broadcast/metric-tab-output.svg" alt="" width="222" height="59">
</button>
```

颜色取自第 3 张素材板。主背景 `#F8F7F3`，主文字 `#2F281E`，品牌金 `#D7B071`，强调色 `#2AA68A`，中性灰 `#E6E6EA`。

第 4 张素材板的大雷达图示例按图上的八轴外轮廓绘制。旁边标注的五轴网格也单独收录。
