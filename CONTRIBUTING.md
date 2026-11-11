# 贡献指南

感谢参与这个项目。这个平台服务于 KPL、次级联赛和训练队的日常赛训工作，
改动直接影响到教练组能不能用，因此我们对提交有明确要求。

## 开始之前

- 先读 [README](README.md) 了解平台解决什么问题、哪些部分处于实验状态。
- 涉及回放文件格式、OCR 识别口径、经济规则的部分，改动前请先在 Issue 里
  说明现状与你的判断，避免做重复的逆向工作。
- 不要在 Issue 或 PR 中粘贴真实对局数据、玩家昵称、账号标识或营地登录凭证。
  平台自带 `.gitignore` 会挡住 `data/` 目录，但请不要依赖它兜底。

## 环境准备

```bash
git clone https://github.com/hccccc01333/kpl-scrim-lab.git
cd kpl-scrim-lab
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
```

需要 Python 3.11 以上。OCR 精读（可选）另装：`pip install -r requirements-mimo.txt`。

启动：`python server.py`，浏览器打开 <http://127.0.0.1:8766/studio>。

## 提交前必须通过

```bash
python -m pytest tests -q          # 单元测试
python scripts/check_deploy.py     # 部署自检
python scripts/check_publish.py --strict   # 开源发布自检（禁止路径/个人信息）
python scripts/verify_frontend.py  # 前端全站巡检（需要 playwright）
```

前端改动还要跑：

```bash
python scripts/verify_ui_pages.py
```

三个脚本都会在失败时返回非零退出码，CI 也是这么跑的，本地先过一遍能省很多往返。

## 代码约定

- Python 遵循 PEP 8，行宽 100，函数与类之间留两行空行。
- 前端使用 ES module，遵循现有文件的命名与组织方式，不引入新的构建步骤。
  仓库不带打包器，改完直接刷新页面即可看到效果。
- 新增依赖前先确认它确实必要，并同步更新 `requirements.txt`，
  注明版本上下界的理由。平台要能在普通赛训组电脑上装起来。
- 业务数据一律写在 `data/` 下，该目录不进入版本库。
- 注释解释「为什么这么做」，不要复述代码本身。

## 数据来源标注

平台上的每个数字都带来源标注，这套口径是产品可信度的基础。新增分析维度时，
请明确使用下列哪一档，并保持页面与文档一致：

| 标注 | 含义 |
|---|---|
| 文件解码 | 从回放或表格文件中直接解码得到 |
| 引擎实测 | 客户端运行时读取的引擎状态 |
| UI 采样 | 从界面或小地图采样得到的位置类数据 |
| 估算 | 由已有数据推算，精度有限 |

不要把估算值呈现为实测值，也不要跨档混用同一张图。

## Pull Request

- 一个 PR 只做一件事。跨模块的大改请拆开。
- 标题用一句话说明改了什么，例如「修复 BP 录入撤销后槽位残留」。
- 描述里写清楚：问题是什么、怎么改的、怎么验证的、有什么已知限制。
- 附上截图（前后对比效果类改动）或测试输出（行为变更类改动）。
- 涉及界面的改动，确认过窄屏（375px）不横向溢出。
- 补充 `CHANGELOG.md` 的 `Unreleased` 段落。

## 协议与贡献者授权

本项目自 1.6.0 起为 **AGPL-3.0-or-later + 商业授权** 双轨（见 [LICENSING.md](LICENSING.md)）。
提交 PR 即表示你同意两件事：

1. 你的贡献以 **AGPL-3.0-or-later** 授权给本项目；
2. 同时授权维护者以**其他协议（含商业授权）**分发你的贡献——这是双轨授权能成立的前提。

提交时请带签署行（`git commit -s` 会自动加上）：

```
Signed-off-by: 你的名字 <你的邮箱>
```

这是 DCO（Developer Certificate of Origin）的轻量方式。不同意这两条请不要提交 PR，
可以改用 Issue 提建议或提供复现步骤。

## Issue

提交 Issue 前请先搜索同类问题。用 Issue 追踪：

- 识别错误（截图读错数值、英雄认错）
- 数据不一致（营地与表格对不上）
- 平台报错或卡死
- 功能建议与使用问题

报告识别错误时，请附上脱敏后的截图说明哪一项读错了，不需要附原始对局文件。

## 行为准则

参与即表示同意 [行为准则](CODE_OF_CONDUCT.md)。
