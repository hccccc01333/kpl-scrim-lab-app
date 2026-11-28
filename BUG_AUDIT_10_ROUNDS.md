# 连续 10 轮 BUG 审计记录

目标：连续 10 轮，每轮审计不同模块，发现并修复高置信度问题，运行验证。

## 轮次计划

1. API 契约与前后端字段对齐
2. 数据接入/归一化（营地、回放、导入）
3. 缓存与失效链路
4. 规则/评级/主体映射边界
5. 前端状态、DOM、事件接线
6. 更新器/安装包/发布脚本
7. 数据库身份合并/回滚/迁移
8. 分析口径（周报、英雄、战队、选手）
9. Windows 路径/权限/异常与恢复
10. 全量回归、文档与交付核对

## 已确认并修复（进入本轮前）

- 3.5.6 已修复上一轮审计的更新器、前端、后端数据口径问题；提交 `9557ce7`。
- 全量测试 1282 passed；3.5.6 源码版本尚未打包发布。

## 轮次记录

### 第 1 轮：API 契约

- `v3/public/capture-page.js:472` 调用早已下线的 `studio/view/matches`，异常被吞掉，采集页「已采集对局」恒为 0、英雄映射为空。改为 `api('matches')`；运行时 `/api/matches` 88 局全部带 `key/heroes`。
- 其余静态 API 路径扫描未发现新的确定性问题（动态模板路径不计）。

### 第 2 轮：数据接入

- `tools/camp_sync.py:149,183` 增量同步在失败局上推进水位，失败局永久丢。水位改为只在成功写盘/命中缓存时推进，分页游标另用 `page_max`。
- `analysis_data.py` 的 `_read_jsonl` 改为 `utf-8-sig`、逐行跳过坏行并报计数；BOM 文件不再整表丢失。
- `tools/camp_client.py:131` 响应只读 8MB 后回退 raw 片段，超长响应静默丢数据；改为流式读完并设 64MB 硬上限。
- `analysis_data._bundle_date` 在 `date.text` 缺失时用文件 mtime 猜年；改为优先 `date.year/month/day`。
- `replay_timeline_build.py` 出装按 `(player, equip_id)` 全局去重导致重复购买花费低估；改为同帧同装备才算重复，花费按每次真实购买累加，最终装备按 equip_id 取最后一次。

### 第 3 轮：缓存与失效

- `workbench_api.py:24` 缓存键漏传 `data_dir`，地图定标改动不失效；已补。
- `briefing_api.py` seq→key 映射缓存不含 `matches_dir` 指纹；已加逐文件 `(name, mtime_ns, size)`。
- `analysis_data._camp_equipment_cache` 只按 seq 且 `invalidate()` 不清；改为按文件指纹索引并在 invalidate 清空。
- `analysis_period._hero_icon_map` 无参 `lru_cache` 永不重读 catalog.json；改为 mtime 指纹缓存。
- `match_facts.data_signature` 只 stat 主 DB；加入 `-wal`/`-journal`。
- `v3/serve._camp_dir_stamp` 只取最大 mtime；改为 `(count, 逐文件指纹)`。
- `AnalysisRepository.get()` 只按身份代际判新；加入输入文件指纹（1 秒 TTL），import/replay/match_meta 写入后自动重建。
- `depth_api._FACTS_CACHES` 改为有界 deque，避免多次 create_router 累积。

### 第 4 轮：规则 / 评级 / 主体映射

- `grade_rules.grade()` 传入未保存的空规则时会回退到内置默认档位参与评级；已改为 `saved=false` 或无 subjects 时返回 `None`。
- 布尔阈值（`False/True`）能通过 `_valid()` 但保存后被 `normalize()` 静默换成默认值；已在校验处排除 bool。
- `grade-rules.js` / `rule-snapshots.js` 在 `document` 派发不冒泡事件，而 `metrics-observe.js` 在 `window` 监听，规则保存后阈值缓存永不失效；监听目标改为 `document`。
- 选手详情 / `team-hero-insight` 的行数据缺少 `blade`，打野细分按英雄静态标签而非装备判定，与对局页/规则中心不一致；两处补齐 blade，`metrics-engine.rowLaneSubject` 与 `player-detail.rulesFor` 都改为 blade 优先。
- `app.js` 打野类型用全等 `坦野`，与其他模块的 `includes('坦野')` 不一致；已统一为包含判断。

### 第 5 轮：前端状态 / DOM / 事件

- `app.js` 门控页提前 return，切到未解锁页时跳过所有模块 `dispose()`，旧页监听和轮询继续挂死；提前 return 前补齐释放。
- 任意 `TypeError` 被当成断网触发自动重连；改为只有 fetch 形状错误才算断网，并给接口 `null` 结果兜底空对象。
- `cross-page` / `biggame-page` 的过期详情请求不清理 loading，导致详情页永久卡住；`ensure()` 不再因 `detailLoading` 阻止重试。
- 模块加载失败时 `cross/biggame/docs` 渲染器未加保护，空页兜底失效；已补可选调用与空页提示。
- `index.html` 的 features.js preload 版本号与 import 不一致，冷启动重复下载；已对齐。
- 筛选提交未捕获 `localStorage` 异常，隐私模式下筛选无响应；已加 try/catch。
- hashchange 不关闭筛选弹窗，跨页提交在 `data=null` 上取 `players` 被误报断网；hashchange 关闭弹窗并统一可选链访问。
- `source-health` 重试成功不恢复按钮、延迟轮询无 generation 守卫；已修复。

### 第 6 轮：更新器 / 安装包 / 发布脚本

- `scripts/make_release.py` 的清装包会把用户 `update_config.json` 覆盖成发布模板；构建清装包时过滤 `PATCH_EXCLUDE`。
- `--no-patch` 仍写 `dist/update.json`，可能把线上自动更新清单打回旧版；已停止写入。
- `installer.iss` 的 `[InstallDelete] *.json` 会删除 `camp_auth.json` / `camp_config.json` / `update_config.json`；改为只删 `update.json`。
- GitHub Actions 手动打 tag 时仍 checkout 默认分支；改为使用输入 tag。
- `updater.py` 失败回滚优先读失败的清装备份目录；`update_client.py` 检查更新补传本地 HTTP 开关。

### 第 7 轮：身份 / 合并 / 迁移

- `undo_merge` 把目标选手的全部 link 搬回来源，误伤目标原有账号；改为仅回退合并时记录的 `link_id`。
- `identity_service._fetch_team` 没查 `aliases`，`_drop_team_alias` 永远无效；已补字段。
- 选手新增 / 删除 / 对手归队写库后未失效 workspace 缓存；三处补 `invalidate_workspace_cache()`。
- 已记录但暂未改（需单独确认数据语义）：归档清理覆盖 `mergedInto`、选手/战队删除级联、大小写/全角别名去重、自由文本队名同步。

### 第 8 轮：分析口径

- `analysis_data.overview` 的 `timelineMatches` 被循环变量覆盖成数组；已保持整数计数。
- `metrics-engine.tableRow` 对 gpm/dpm/tpm/dtpm 用逐局均值，与看板 Σ/Σ 口径不一致；已改 Σ总量/Σ分钟。
- laneCompare / 选手对 / 对手交手胜率用总局数作分母；已统一为 `wins/decided`。
- `analysis_period` 周/月本期窗口延伸到未来周末/月末，与「上期同进度」长度不等；本期截止到今天。
- 已记录但暂未改（涉及指标改名和 UI 契约）：`dpm` 总伤害 vs 英雄伤害双口径、`damageShare` 双分母。

### 第 9 轮：Windows / 异常 / 恢复

- `camp_client` 只读 8MB 的截断问题在测试替身下反复读同一块造成死循环；改为一次性读完整响应并做 64MB 上限。
- 营地登录态时间改用 UTC；`server.py` 缓存解析同步支持带时区 ISO 时间。
- `updater._atomic_copy` 与 `v3/serve._merge_staging` 先删目标再 replace，中途失败会丢文件；改为优先 `os.replace`，仅在被占用时回退删除。
- `updater.read_installed_version` 吞掉所有异常并按 0.0.0 处理，文件损坏时会误判老版本；只对 FileNotFoundError 降级。
- `updater._write_json` 使用固定 `.tmp` 且未 fsync；改为唯一临时文件 + fsync。
- 构建脚本未关闭的 `open()` 已改为 `with`。
- 已记录但暂未改（面广、需逐处回归）：若干固定 `.tmp` 文件名在并发写时互相覆盖。

### 第 10 轮：回归与交付

- 新增回归测试：未保存规则不参与评级、coverage 计数类型、pending 接口存在。
- 语法检查：全部改动 Python `py_compile` 通过；改动 JS `node --check` 通过。
- 针对性测试：`74 passed`（含新增用例）。
- 全量测试：`python -m pytest -q` 结果见交付说明。

### 已知未改项（低优先级 / 需业务确认）

- 身份模块的级联删除与别名规范化策略。
- `dpm` / `damageShare` 两个口径的字段改名和 UI 文案统一。
- 并发固定临时文件名改为 `mkstemp` 的全量替换。

## 后续反馈修复（同一天）

- 选手详情「对抗路类型占比 / 战边·坦边」整块删除：非对抗路选手页不再出现无关分路统计。
- 补刀并入规则设置的特殊分钟标准：内置发育/对抗/中路 1–20 分钟标准表（来自用户附件），可加任意分钟；不足 19 分钟按 18 分钟档。发育/对抗高于/低于标准分别显示金色/红色，等于标准显示蓝色；中路补刀固定蓝色参考。
- 外部数据源缺失或过期时后台自动补爬（英雄 / KPL / 巅峰千强），带成功 6 小时、失败 30 分钟冷却；结果明确显示「爬取成功 / 爬取失败」。
- 周报标题、报告类型直接标注「一周」。

## 团队排查：多版本遗留问题（同日）

- 待命名战队根因不在缓存：`team_clusters` / `match_facts` / `analysis_profile` 读取时给未确认签名簇造「待命名战队 #N」，`bp_board` 把它当真实对手下传。统一 `workspace_store.is_placeholder_team` / `real_team_name` 口径，源头与所有接口出口一起修；旧落盘缓存按签名版本位失效。
- BP工作台下拉改 Popover top-layer + CSS Anchor Positioning（含 @supports 回退），避免被其它卡片压住；去掉内层窄滚动和省略号；Ban 斜线用同一 inset 贴 30×30 头像。
- 跨场 10 分钟金币门槛改为 ≥3,000 / ≥5,000 两档并列，命中数与分母同档；领先/落后分绿红且文案写明方向；窄屏用 flex-wrap / 断点排版。
- 总览对比单位 pp → %；英雄池筛选按钮改「总共 / 我方 / 敌方」，完整语义进 title/aria-label。
- 英雄类型此前并行两套数据源：规则中心写 `hero_tags.json`，图7等却读静态 `hero_archetypes.py`，且向量缓存不认标签变更。改为实时读标签 + mtime 失效 + 保存后清向量缓存；导入脚本模板同步保留动态逻辑。历史统计会按新标签重算，这是联动的预期结果。
- 匹配页侧栏新增「一键确认（N）」：按蓝方/红方分别批量把自动匹配改为人工复核，局部更新 DOM 以保留焦点/滚动，不跨阵营批量确认。
- 周报原先纵向堆叠、标题偏泛且把十几行对局明细直接铺进报告。改为宽画布 + A4 横向命名页，领导摘要重排成 12 栏拼版并统一「本周…」标题；对局模块改为按日聚合节奏带，逐局明细留在对局页。
- 赛后笔记独立页把 `channel-xxx` 当用户可见副标题。改成日期/对手为主标题、赛制/时间/训练组为副标题；选局下拉用「第 N 局」代替 key 尾号，链接 title 也不再暴露裸 ID。
- 周报二轮精修：补封面「本周结论」导语与页脚，避免教练先扫表；字号从 px 改 rem/clamp、标题 `text-wrap: balance`、导语 `text-wrap: pretty`；渐变显式 `in oklab` 并保留强制颜色模式回退。
- 周报视觉层原先放进 `style.css` 的 `layer(legacy)`，被后加载的未分层样式覆盖，导语文字发灰。独立 `weekly-refined.css` 最后加载并改纸感/宋体/章节编号/细铜线，截图复核后对比度与杂志感恢复。
- 组合卡被 `rl-table-wrap` 的容器查询在窄卡片里拆成块，三列变成上下堆叠，数字飘移。周报层强制恢复表格 display、固定三列并加宽卡片，截图复核后「组合 / 局数 / 胜率」横向对齐。
- 组合只有文字胜率，扫读成本高。加排名与原生 `<progress>` 胜率条，同时保留完整胜负分母文字，避免颜色/长度单独表达数据。
- 低胜率提示原先写死「控制与开团」。改成按组合英雄的分路标签推导复盘方向；节奏条补胜:负文本并同步 aria-label，避免只靠色块比例判断。
