# 0x1e victim ID 映射（R3 主会话，2026-11-02）

- 输入：`replay_event_stream_events.jsonl.gz` 的 `kind=unit_interaction`
- 输出：`datasets/victim_id_events.csv`、`datasets/victim_id_summary.csv`
- 工具：`tools/analyze_victim_ids.py`

## 结论

1. **victim 不是英雄 object ID**：314 条 `0x1e` 里只有 **2 条**命中已知 hero object ID；
   victim 值域 0–994，远大于英雄 object ID 的 7–65 池。
2. 同一 victim 会被多个攻击者命中（如 699、977、604、342、503），更像
   **小兵/野怪/建筑等单位 runtime ID**，不是“攻击者→英雄”的击杀对。
3. `0x1e` 没有 damage/skillId/unitType/killer 字段，只有
   `type:u8 + 14×00 + victim:u16BE + 01`；不能用于 KDA、伤害或经济。
4. 11/2 两局没有进入这份 0x1e 事件集（该流主要来自旧 build）；新 build 的单位交互
   需要另找 frame command 或 CS 消息。

## 数据

- 16 个文件，314 条事件；
- hero object 命中 2/314（仅 `20260925_101323`）；
- 其余 victim 全部是 0–994 的 runtime ID 候选；
- 最高重复 victim 也只有 2 次，说明不是稳定的 10 人英雄表。

## 边界

- 没有单位 ID 表（`normalMonster`/`Level` 的单位 ID 段）可把 victim 映射到
  具体兵种/野怪/建筑；
- 不能用“victim 在 0–65 就是英雄”的假设，因为命中率只有 2/314；
- 不能用 0x1e 反推击杀者/助攻；
- 不要把它当伤害表或 KDA 事件。

## 下一步

- `0x02/0x84` 已确认是 BASEATTACK，**不是单位死亡候选**；不能用来做兵线经济。
- `0x02/0x81 mode6` 已确认是 USEDIRECTIONALSKILL，**不是死亡**；不能做英雄击杀归属。
- 若要做单位击杀/兵线经济，需要另找单位死亡通道，或用外部结算/OCR/模拟；
- 若要英雄击杀归属，只能用外部面板/OCR/服务器数据；回放内 confirmed death=0；
- `0x1e` 只保留为“某英雄与某单位发生交互”的低置信事件。
