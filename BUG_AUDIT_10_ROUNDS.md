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
