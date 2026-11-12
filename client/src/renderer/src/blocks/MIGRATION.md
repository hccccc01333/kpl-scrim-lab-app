# 上帝模式 · 页面接入规范（MIGRATION）

目标：每个有分析块的页面，把分析块交给 `<BlockBoard>` 管理。接入后该页自动获得：

- 块显隐（隐藏的块仍保留在布局里）
- 拖拽排序
- 恢复默认
- 布局分享（分享码 + 密钥，AES-GCM，本地加解密）
- 新块上线自动出现在页面（只按默认顺序追加）

改造只动 JSX 包装，**不改数据、hooks、计算、文案和样式**。

## 标准写法

参考样板：[`pages/BpPage.tsx`](../pages/BpPage.tsx)。

```tsx
import { Block, BlockBoard } from '../blocks/BlockBoard'

// 页面里原本连续排列的分析区块：
<div className="page board-page">
  <PageHeader ... />
  <StatGrid ... />         {/* 非分析块，留在外面 */}
  <div className="board-toolbar">...</div>  {/* 筛选条，留在外面 */}

  <BlockBoard page="bp">
    <Block id="bp-profile" title="条件 BP 画像">
      <AnalysisSection id="bp-profile" title="条件 BP 画像" ...>
        ...
      </AnalysisSection>
    </Block>

    <Block id="bp-picks-bans" title="选用榜 / 禁用资源">
      <div className="board-grid-2" id="bp-picks">   {/* 成对区块：整组一个 Block，保住双列布局 */}
        <AnalysisSection ...>...</AnalysisSection>
        <AnalysisSection ...>...</AnalysisSection>
      </div>
    </Block>
  </BlockBoard>

  <div className="board-foot">...</div>
</div>
```

## 五条硬规则

1. **一个页面只放一个 `<BlockBoard>`**，page 用稳定的英文 slug（如 `bp`、`heroes`、`hero-detail`、`team-bp`），改了就丢已保存的布局。
2. **每个分析块用 `<Block id title>` 包住**，`id` 页内唯一、以后不能随意改；`title` 是抽屉/编辑条上的短名（≤6 个字最好）。
3. **成对区块整组当一个 Block**：原本在 `.board-grid-2`（或其它并列容器）里的两个 section，把整个容器包进同一个 Block，容器留在 Block 里面。这样视觉不变，只是这一组作为一个块排序。
4. **Block 必须是 BlockBoard 的直接子元素**（`Fragment`、`{cond && <Block/>}` 可以；**不要**再套 `<div>` 包住多个 Block，否则识别不到）。
5. **不动其它东西**：PageHeader、StatGrid、筛选条、JumpNav、banner、footer 留在 BlockBoard 外面原位置；不要改数据请求、计算和文案，不要加 CSS。

## 块级筛选（可选）

块可以自己声明支持哪些筛选，页面把筛选值接进数据：

```tsx
<BlockBoard page="bp" filterOptions={{ opponents, players, heroes }}>
  <Block id="bp-games" title="逐局名单" filters={['range', 'opponent', 'player', 'hero', 'side', 'result']}>
    {(f) => <GameList games={games.filter((g) => dateInBlockRange(g.start, f) && ...)} />}
  </Block>
</BlockBoard>
```

- `filters` 可选：`range` / `opponent` / `player` / `hero` / `side` / `result`；
- 子节点写成函数时，BlockBoard 传入该块的筛选值（类型 `BlockFilterValues`）；
- 只影响这个块，页面级筛选照样先生效；
- 工具函数在 [`blocks/filters.ts`](./filters.ts)。

## 三套模式

- 大众 / 专业 / 自定义各存一套布局，互不覆盖；
- 标题栏模式芯片循环切换，设置页也能切；
- 编辑模式保存、恢复默认只作用于当前模式；
- 布局分享包含三套模式 + 当前模式。

## 注册块（分析库 / 我的看板）

页面内联块只能在本页用。要「所有分析都能放到任意页」，就把分析写成**注册块**（自治块）：

```ts
// blocks/builtin/index.tsx
export const BUILTIN_BLOCKS: RegisteredBlock[] = [{
  id: 'bp.own-combos',        // 全局唯一，别改
  domain: 'bp',               // bp / match / hero / player / team / training
  title: '本队双人组合',
  question: '本队最常一起拿的双人组是什么？胜率多少？',
  filters: ['range', 'opponent', 'player', 'hero'],
  Component: BpComboBlock     // 组件内部自己 useConnection + hooks 取数
}]
```

- 注册块通过 `BlockBoard` 的「分析库」加到当前页，存在当前模式的 `layout.extras`（`lib:<id>`），可排序/隐藏/移除；
- 注册块内不要依赖页面 state，数据和口径自己负责；筛选值用 `useBlockFilter()`；
- 新页只要 `<BlockBoard page="xxx" />`；空白页用 `<BlockBoard page="studio" allowEmpty />`（例：`pages/StudioPage.tsx`）；
- 迁移路线：把各页内联 `AnalysisSection` 逐个抽成注册块，页面只保留 `BlockBoard`。抽完一个域，这个域的所有分析就能加到任意页/我的看板。

## 检查

- `cd client && npm run typecheck` 必须 0 错误；
- 页面正常渲染时与改造前布局一致（成对区块仍是双列）；
- 「自定义布局」按钮出现在分析区上方；编辑模式下能拖动、隐藏、恢复；
- 改动只涉及分配给你的页面文件；框架文件（`blocks/`、`Icon.tsx`、`index.css`、`styles/blocks.css`）不要动。
