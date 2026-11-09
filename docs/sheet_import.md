# 表格数据导入（数据整理）

赛训组已有的表格通常不是一种形状：有的是一行一名队员的单局数据，有的是一行一场的团队数据，有的是逐事件日志，还有的是跨局聚合（胜率、场次、场均经济/伤害）。这个导入层先识别**粒度**和**字段类型**，再按 profile 落盘，保留原始列；不会把聚合字段当成单局字段，也不会把百分比/场均重新求和。

## 本局附件与批量导入的区别

“采集通道 → 表格”是选填来源，必须使用[本项目十人模板](http://127.0.0.1:8766/assets/capture-guide/match-template.xlsx)，每局恰好十行、双方各五人，严格校验表头、日期、分路、本队阵营和数值；未知数值可空，示例编号不允许提交。完整规则和虚构示例见[采集 SOP](collection_sop.md)。机器约束定义在 `web/capture-guide/requirements.json`，服务端在写入附件前校验。

以下自动画像、聚合表与多局表说明属于“批量导入”和 CLI，不代表本局附件接受任意格式。

## 支持范围

- 格式：CSV/TSV、XLSX/XLSM。旧版 `.xls` 请先另存为 `.xlsx` 或 CSV。
- 大小：单文件 ≤64 MB、≤200,000 行；中文编码尝试 UTF-8/GB18030/UTF-16。
- 粒度：
  - `match_player`：一行一名队员的一局数据（日期/对局 ID + 选手/英雄 + KDA/经济/伤害）。
  - `match_team`：一行一支队伍的一局数据。
  - `event`：一行一个事件（时间/帧 + 事件类型 + 选手/英雄 + 坐标等）。
  - `aggregate_player` / `aggregate_team` / `aggregate_hero`：跨局聚合（场次/胜率/场均）。
  - `match_wide`：一行一局、十名队员横向展开；需要 profile 里的 `wide.players` 映射才能拆成一行一名队员。
- 依赖：`openpyxl`（XLSX）；CSV 用标准库。读取在本机完成。

## 工作流

先画像，不要直接相信自动识别：

```powershell
python scripts/import_sheet.py "赛训表.xlsx" --preview
```

会输出每个工作表的行/列数、推断粒度、键、指标、维度、未映射列和警告。确认后：

```powershell
# 1) 生成 draft profile，人工检查/修改
python scripts/import_sheet.py "赛训表.xlsx" --write-profile data/imports/table-profile.json --preview

# 2) 用 profile 落盘
python scripts/import_sheet.py "赛训表.xlsx" --profile data/imports/table-profile.json

# 只处理某个工作表
python scripts/import_sheet.py "赛训表.xlsx" --sheet "单局数据" --preview
```

快速试导入（manifest 会标 `profileSource: inferred`，不建议直接用于正式分析）：

```powershell
python scripts/import_sheet.py "赛训表.xlsx" --accept-inferred
```

默认输出 `data/imports/<文件 sha 前 16 位>/`：

```text
manifest.json          # 来源、profile、每表画像、质量、警告
profile.json           # 实际使用的映射，可复用
rows/01-单局数据.jsonl  # 规范化行：raw + keys + dimensions + metrics
```

只写本机 `data/`，不进入工作台数据库，也不会自动创建正式比赛。

## Profile

一个 profile 可以只描述一个工作表（`sheet`），也可以用 `sheets` 包多个：

```json
{
  "profileVersion": 1,
  "sheet": "单局数据",
  "grain": "match_player",
  "keys": {
    "date": "日期",
    "matchId": "对局ID",
    "player": "选手",
    "hero": "英雄"
  },
  "metrics": {
    "kills": {"column": "击杀", "kind": "total", "unit": "count"},
    "deaths": {"column": "死亡", "kind": "total", "unit": "count"},
    "assists": {"column": "助攻", "kind": "total", "unit": "count"},
    "kda": {"column": "KDA", "kind": "ratio"},
    "gold": {"column": "经济", "kind": "total", "unit": "amount"},
    "damage": {"column": "输出", "kind": "total", "unit": "amount"},
    "taken": {"column": "承伤", "kind": "total", "unit": "amount"},
    "participation": {"column": "参团率", "kind": "percentage"},
    "rating": {"column": "评分", "kind": "total", "unit": "score"}
  },
  "dimensions": {"win": "胜负"},
  "uniqueBy": ["date", "matchId", "player", "hero"]
}
```

### 跨局聚合

```json
{
  "profileVersion": 1,
  "sheet": "赛季汇总",
  "grain": "aggregate_player",
  "keys": {"period": "赛段", "player": "选手", "hero": "英雄"},
  "metrics": {
    "games": {"column": "场次", "kind": "count"},
    "wins": {"column": "胜场", "kind": "count"},
    "winRate": {"column": "胜率", "kind": "percentage"},
    "avgGold": {"column": "场均经济", "kind": "average", "unit": "amount"},
    "avgDamage": {"column": "场均伤害", "kind": "average", "unit": "amount"},
    "participation": {"column": "参团率", "kind": "percentage"}
  },
  "uniqueBy": ["period", "player", "hero"]
}
```

每一行会带 `"aggregated": true`。分析层必须按粒度分开：聚合行不能当单局行再求和；胜率/场均不能再平均（需要分母/场次时保留 `games`）。

### 事件日志

```json
{
  "profileVersion": 1,
  "sheet": "事件",
  "grain": "event",
  "keys": {
    "date": "日期",
    "matchId": "对局ID",
    "time": "时间",
    "event": "事件",
    "player": "选手",
    "hero": "英雄",
    "skill": "技能"
  },
  "metrics": {
    "x": {"column": "x", "kind": "coordinate"},
    "y": {"column": "y", "kind": "coordinate"}
  },
  "uniqueBy": []
}
```

事件表默认不做重复键删除（同一秒可有多条事件）；`uniqueBy` 留空。

### 宽表

自动画像只能检测到重复前缀（如“蓝方上单_击杀、蓝方上单_经济……”）并把粒度标成 `match_wide`，不会替你猜十名队员。需要补：

```json
{
  "profileVersion": 1,
  "sheet": "宽表",
  "grain": "match_wide",
  "keys": {"date": "日期", "matchId": "对局ID"},
  "metrics": {},
  "dimensions": {},
  "uniqueBy": [],
  "wide": {
    "players": [
      {
        "side": "blue",
        "slot": 0,
        "columns": {
          "player": "蓝方上单_选手",
          "hero": "蓝方上单_英雄",
          "kills": "蓝方上单_击杀",
          "deaths": "蓝方上单_死亡",
          "assists": "蓝方上单_助攻",
          "gold": "蓝方上单_经济"
        }
      }
    ]
  }
}
```

每行按 `players` 展开；`side/slot` 写入 keys。宽表没有 `players` 时会拒绝落盘，只给画像和警告。

## 字段语义

| 类型 | 处理 |
| --- | --- |
| 日期 | `datetime`/`YYYY-MM-DD`/`YYYY/M/D`/`M/D` 归一化；只有月日时保留 `MM-DD`，年份未知 |
| 金额 | `9.8k`→9800、`1.2万`→12000、`1.2w`→12000；保留 `raw` |
| 百分比 | 统一存 0–100；源值 `0.62` 且无 `%` 时按比例 ×100，并标 `sourceScale: ratio`；>100 标无效 |
| 胜负 | `胜/赢/W/1`→1，`负/输/L/0`→0；无法识别保留空值 |
| KDA | 支持 `K/D/A` 三段（存数组）或单个 KDA 数值 |
| 时长 | `mm:ss`→秒；纯数字保留数值并标 `unit: seconds`（若源是分钟，profile 设 `"unit": "minutes"` 转换） |
| 场次 | 聚合表按 `games`；单局表里表头恰为“场次”时按 `matchNo`，避免把场次号当胜率分母 |
| 混合表 | 单局表里出现胜率/场次/场均列时，粒度按单局，聚合列标 `aggregate: true` 并警告，不随单局累加 |
| 未识别列 | 全部保留在 `raw`，列入 `unmappedColumns`；不会丢列 |

## 行格式

```json
{
  "rowNumber": 2,
  "grain": "match_player",
  "aggregated": false,
  "raw": {"日期": "2026-10-28", "选手": "茉莉花与雨", "击杀": "1", "...": "..."},
  "keys": {"date": "2026-10-28", "matchId": "M1", "player": "茉莉花与雨", "hero": "孙膑"},
  "dimensions": {"win": 1},
  "metrics": {
    "kills": {"raw": "1", "value": 1, "kind": "total", "unit": "count", "valid": true},
    "gold": {"raw": "9.8k", "value": 9800, "kind": "total", "unit": "amount", "valid": true}
  },
  "duplicate": false
}
```

`keys` 是源表里的原始标识（昵称/英雄/对局 ID），**不是工作台的稳定队员 ID**；队员身份、实际分路和对手仍要人工确认。

## 质量检查

- 空键、重复键（不自动去重，只在 `quality.duplicates` 计数并写警告）。
- 指标越界/无法解析（保留 `raw`，`valid: false`，`note` 说明）。
- 未识别列、低置信映射、宽表缺 `players`、聚合表/混合表警告。
- 行数/文件大小上限；`.xls` 拒绝并提示转换。

## 与后续分析

- `grain` 决定行的含义；分析层不能把 `aggregate_*` 和 `match_*` 混在一起计算。
- `aggregated: true` 或指标 `spec.aggregate` 为 true 的列，不参与单局求和/再平均。
- 百分比已统一到 0–100；需要分母时用 `games`/`wins`，不要用百分比反推。
- 所有值保留 `raw` 与行号，便于回到原表核对。

## 限制

- 自动画像只是草稿：中文表头歧义（时间/场次/经济/输出）和不同俱乐部模板需要人工 profile。
- 宽表展开只有显式 `wide.players`；不做任意表头模式的自动拆分。
- 不做昵称→队员 ID 的自动绑定；不判断真实分路/对位。
- 不写工作台数据库；不自动创建正式比赛或进入胜率统计。
- 只支持 UTF-8/GB18030/UTF-16 文本和 xlsx/xlsm；公式单元格以缓存值读取，没有缓存值的公式会为空。

## 验证

```powershell
python -m unittest tests.test_sheet_import -v
python -m unittest discover -s tests -v
```

测试覆盖：GB18030 CSV、XLSX 读取、单局/聚合/事件/宽表粒度、场次歧义、混合聚合列、百分比比例与越界、金额/时长单位、重复键、缺键警告、缺列报错、manifest/JSONL 落盘。
