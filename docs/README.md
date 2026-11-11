# 项目文档目录

## 使用与交付

- [部署指南](deploy.md)：新机器安装、环境变量、Docker、自检与开源边界。
- [使用指南](product_guide.md)：启动、导入、校对、复盘与对比的完整路径。
- [采集要求与示例](collection_sop.md)：唯一必采的营地链接、审核双合规路径（营地面板 / 七图+录屏兜底）与选填表格；[单局采集说明](collection_channel.md)。
- [截图字段说明](screenshot_fields.md)、[表格导入](sheet_import.md)、[官方营地回放](camp_replay.md)、[营地回放载荷清单](camp_replay_payload.md)。
- [本机 OCR 引擎](ocr_engine.md)：可选模型、安装要求与识别限制。
- [更新与版本](update.md)：增量更新、版本说明与数据保留范围。
- [指标口径](metric_registry.md)、[经济规则](economy_rules.md)：页面上的数字怎么算、边界在哪。

## 开发与验证

- [设计系统](design_system.md)：布局、颜色、交互规范与数据展示要求。
- [分析平台](analysis_platform.md)：分析数据组织与扩展说明。
- [分析字段矩阵](analysis_fields_matrix.md)：字段、粒度与派生公式。
- [设备与运行环境](device_setup.md)：本机运行所需的环境准备。
- `../v3/`：V3 页面、原生 JavaScript 模块与样式；`../web/` 仅保留采集规范资料；`../server.py`：本机 API；`../tests/`：后端测试；`../scripts/`：运行与验收脚本。
- `python scripts/verify_frontend.py --no-shots`：从导航动态抓路由，跑桌面/手机视口、横向溢出和失败请求。
- `node scripts/test_analysis_math.mjs`：缺失值、滚动窗口、并列分位、Wilson 区间及时间轴分段计算。
- `python -m unittest tests.test_analysis_timeline tests.test_analysis_data tests.test_studio -v`：分析统计与时间轴口径回归。
- `test-results/`：截图、测试数据库与验收报告，已在 Git 忽略列表中。用户数据位于 `data/`，不与测试产物混用。

## 专项说明

- [打野位置口径](jungle_position_spec.md)：过河与深入的坐标定义、阈值与已知限制。
- [回放解析档案与版本流水线](replay_profiles.md)：新增客户端版本时如何更新配置、重跑映射，以及四档置信度约定。

回放二进制格式、引擎内部结构、H5 前端探针等研究笔记不在公开仓库内。
