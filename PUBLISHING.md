# 开源发布规则

> 这个文件回答一个问题:**哪些东西可以推到公开仓库**,以及为什么。
> 每次发版前跑一遍 `python scripts/check_publish.py`。

## 原则

公开仓库只放**跑起来、改得动这个项目所需要的东西**:源代码、测试、构建脚本、
技术文档、模板与示例数据(合成)。

**不放**:个人资料、运营与投放素材、设备派生数据、第三方素材、参考项目的副本。

## 永不上传清单

| 路径 / 类型 | 原因 |
|---|---|
| `内部资料/` | 截图与个人材料,与代码无关 |
| `marketing/` | 投放文案、封面、发布计划,含账号与运营信息 |
| `datasets/` | 设备派生的原始数据 |
| `docs/afdian/` | 赞助页素材 |
| `web/capture-guide/*.jpg`、`*.png` | 营地界面截图,可能含真实昵称/账号 |
| `web/refsite/` | 另一个项目的参考站副本(103MB),不是本项目代码 |
| `resources/icons/` | 王者荣耀英雄/装备图片,权利归原权利人,不随代码分发 |
| `_qr.json`、`_pid.txt`、`*.log` | 登录二维码、进程号、运行日志 |
| `data/`、`*.sqlite3`、`*.abc`、`*.ope` | 对局数据、数据库、回放文件 |
| `data/facts/lane_matchups.json` | 由私有 KPL 数据集生成，公开仓库不带 |
| `data/kpl/bp_games.jsonl` | 本项目爬虫从 KPL 官方公开接口抓的逐局 BP，可随时重抓，**可公开** |
| `data/facts/kpl_combos.json` | 由 `data/kpl/bp_games.jsonl` 生成，公开仓库可不带（一条命令重算） |
| `scripts/build_bp_facts.py` 的巅峰千强部分 | 依赖私有数据集，留在本地；KPL 部分已改为自抓管线 |
| `tools/agent_*.py`、`docs/agent_*.md` | 逆向研究过程脚本与笔记，不公开 |
| 用户目录绝对路径(本机用户名目录) | 暴露本机用户名与目录结构 |
| 分发渠道与安全运营细节 | 签名状态、分发方式、安装链路、内部端点等，只写在本机运维笔记里 |
| 外部项目名与路径(如其他作品集目录) | 暴露项目组织与工作方式 |

## 图片资源怎么办

需要英雄/装备图时,在本地跑:

```bash
python scripts/sync_catalog.py
```

它按官方公开地址拉取到 `resources/icons/`,只在本机使用。公开仓库不含这些图片,
克隆下来没有图也不影响平台运行(只是跳过图像匹配)。

## 发版前检查

```bash
python scripts/check_publish.py      # 检查已跟踪文件
python scripts/check_publish.py --strict   # 额外检查正文里的本机路径与邮箱
```

检查不通过就不要推送。建议同时挂到 pre-push 钩子或 CI:

```bash
# .git/hooks/pre-push
python scripts/check_publish.py --strict
```

## 历史遗留

`git rm --cached` 只影响之后的提交。**Git 历史里仍然存在**这些文件
(包括 103MB 参考站副本与 349 张英雄图)。

首次公开前必须二选一:

1. `git filter-repo --path 内部资料 --path marketing --path datasets \
   --path web/refsite --path resources/icons --invert-paths`
   —— 彻底抹掉,但会改写所有 commit hash。
2. 新建一个 squashed 的「开源首发」分支,只保留当前快照,不带历史。

## 当前状态(1.6.0)

- 已取消跟踪:**961 个文件**——内部资料 15、marketing 197、refsite 350、
  resources/icons 349、capture-guide 截图 13、datasets 2、afdian 2、
  data/facts 2、研究脚本 1、跨项目生成脚本 2、逆向研究脚本 27、研究笔记 1。
- 已清理:两份文档里的本机绝对路径。
- 已加自检:`python scripts/check_publish.py --strict` 覆盖禁止路径、
  本机用户名、外部项目名与邮箱。
- 未决:Git 历史是否重写(见上),以及 `docs/feedback-*.md`(教练反馈台账)是否随仓库公开。
