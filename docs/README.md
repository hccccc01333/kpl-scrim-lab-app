# 项目文档目录

## 使用与交付

- [部署指南](deploy.md)：新机器安装、环境变量、Docker、自检与开源边界。
- [使用指南](product_guide.md)：启动、导入、校对、复盘与对比的完整路径。
- 统一平台（历史，已归档）：页面、功能、数据口径和兼容路由。
- [采集要求与示例](collection_sop.md)：营地路径的营地链接与双合规路径、OCR 路径（七页截图或一段录屏即可建档）；[单局采集说明](collection_channel.md)含「补采 vs 新录入」的区别。
- [截图字段说明](screenshot_fields.md)、[表格导入](sheet_import.md)、[录屏识别](replay_video_ocr.md)、[官方营地回放](camp_replay.md)。
- [本机 OCR 引擎](ocr_engine.md)：可选模型、安装要求与识别限制。

## 开发与验证

- [设计系统](design_system.md)：布局、颜色、交互规范与数据展示要求。
- [数据字段总览](data_fields.md)：现有数据的分层、字段、覆盖与缺口（API / 关系库 / 回放 / 营地原始），改分析或建模型前先看这张表。
- [跨局分析 / 大场分析](cross_analysis.md)：两个独立模块——多场 BO 的概述/赛中/赛后/英雄和 BP，
  以及单场大场的列表/逐局分析；统一范围、BP 消耗与比分校验口径。
- [赛训分析](workbench.md)：P0 剩余分析（资源分配 / BP 等）的口径与落位（选手 / BP 模块的
  分析入口）、`/api/decision/*`；独立「决策台」已于 2026-11-13 下线，对局分析三页
  （失利关键链 / 团战执行与到位 / 优势保持与回撤）已整页删除。实现契约见 [workbench_contract.md](workbench_contract.md)。
- [赛训周期简报](period_brief.md)：默认首页（`#overview`）的信息组织：周期切换、一句战况、
  本期最值得关注的 1–3 条变化、下一场约训、数据覆盖；含 `GET /api/briefing` 契约与口径、空态规则。
- [系列赛编组与分析](series_builder.md)：V2.0 阶段 01–03：`training_series` 两张新表与关系列写回、
  编组中心（`#series-builder`）拖框编组交互、跨局分析以系列赛为单位汇总与单场大场分析、
  规则集与完赛判定口径、自动建议不落库原则。
- [分析平台](analysis_platform.md)：分析数据组织与扩展说明。
- [赛事命中口径](kpl_hit_logic.md)：本局 BP 在 KPL 赛场「命不命中」怎么判、三层结论怎么读、
  它不是什么；数据更新方式见同文。抓取与落盘契约见 [kpl_bp_pipeline.md](kpl_bp_pipeline.md)。
- `../v3/`：V3 页面、原生 JavaScript 模块与样式（`../web/` 仅保留采集规范资料与参考快照）；`../server.py`：本机 API；`../tests/`：后端测试；`../scripts/`：运行、评测和浏览器验收脚本。
- `python scripts/audit_v3_regression.py http://127.0.0.1:8766`：V3 的 25 条路由逐条渲染、JS 异常和空页检查。
- `python scripts/verify_frontend.py --no-shots`：从导航动态抓路由，跑桌面/手机视口、横向溢出和失败请求。
- `node scripts/test_workspace_home.mjs`：首页（赛训看板）静态回归：路由、挂载点与样式约束。
- `python scripts/verify_module_analyses.py`：已下线分析的删除回归：选手 / BP 十个分析的
  入口、页面与接口零残留，其他模块入口仍在。
- `node scripts/test_analysis_math.mjs`：缺失值、滚动窗口、并列分位、Wilson 区间及时间轴分段计算。
- `python -m unittest tests.test_analysis_timeline tests.test_analysis_data tests.test_studio -v`：分析统计与时间轴口径回归。
- `python scripts/verify_analysis_visuals.py`：当前本机样本的可视化交互验收；合成边界数据仅挂在测试浏览器，不写入项目数据。
- `test-results/`：截图、测试数据库、验收报告和修改前备份，已在 Git 忽略列表中。用户数据位于 `data/`，不与测试产物混用。

## 回放协议与专项研究

本目录其余 `abc`、`ope`、frame、runtime、simulation 等文档记录解析研究与实验边界；不代表界面已支持全部研究字段。先从 统一平台（历史，已归档）核对当前功能，再查阅专项说明。

- [回放解析档案与版本流水线](replay_profiles.md)：新增客户端版本时如何更新配置、重跑 selector 映射，以及“文件解码 / 引擎实测 / UI 采样 / 估算”四档置信度约定。
- 回放分析路线文档（历史，已归档）。
- [十检查点状态序列](state_series_10pt.md)：01:34–09:37 的 10 个引擎实测 gold/KDA/level 点，及其产品导入 JSONL。

本次通过增加索引整理文档，不移动或删除历史文件。启动脚本保持原名，避免破坏现有快捷方式。
