# 运行时赛训数据（实验）

训练赛的 `.abc` 回放保存的是命令/事件输入，不是十人经济、伤害、承伤或位置的最终表。`GameCore` 在客户端播放回放时重新模拟比赛，真正的逐帧状态只在运行时产生。本页定义工作台消费这类数据的稳定格式；采集器可以替换，回放文件始终只读。

## 数据边界

已确认的运行时入口：

- `CAutoReplayManager`：本地回放入口，持有 `m_isShmReplay`、`m_isStreamReplay`、`m_shmOffset` 等状态。
- `CShmReplayConsumer`：共享内存消费者，含 `InitSyncShm`、`InitBattleShm`、`GetBattleBasicInfo`、`GetBattleAttrInfo`、`ConsumeBattleFrameWithOffset`。
- `VisualFrameReplayManager`：进程内帧缓冲，含 `cppBuffer`、`RecordFrame`、`GetCurrentFrameData`。

当前样本的 `GameModeConfig.json` 中 `IsSharedMemReplay_b=false`，`BattleDataShareMemMapFilePrefix_s` 为空。若运行时也读取到 `m_isShmReplay=false`，则不会走 `CShmReplayConsumer`，只能从进程内帧缓冲或游戏内面板取值。该判断必须在实际设备上复核，不能只凭配置文件推断。

原始帧字节不等于赛训指标：仍需把英雄、位置、血量、经济、伤害等字段映射出来，或有游戏内方法直接返回带标签的结构。没有完成映射前，工作台只接收已经带字段名的导出，不猜测原始二进制。

## JSONL 契约

一行一个 JSON 对象，UTF-8，最大 8 MB、20 万行。支持四种 `type`：

```jsonl
{"type":"meta","schema":"kpl-runtime-v1","gameVersion":"12.1.1.23","matchId":"...","source":"gamecore-shm"}
{"type":"frame","frame":120,"time":120,"players":[{"playerId":"b1","heroId":101,"camp":"blue","slot":0,"gold":1200,"kills":2,"deaths":1,"assists":3,"damageDealt":6000,"damageTaken":3000}]}
{"type":"player","frame":121,"time":121,"playerId":"b1","heroId":101,"camp":"blue","gold":1210,"kills":2,"deaths":1,"assists":3}
{"type":"event","frame":150,"time":150,"event":"dragon","camp":"blue","playerId":"b1"}
```

### 帧/队员字段

`type:"frame"` 的 `players` 为 1–10 人；`type:"player"` 是一行一名队员。两者可混用，同一帧同一 `playerId` 不能重复。

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `playerId` | 是 | 稳定队员标识，1–80 字符，不能用昵称或画面行号 |
| `heroId` | 是 | 游戏英雄 ID，1–9999 |
| `camp` | 否 | `blue`、`red` 或 `unknown`，默认 `unknown` |
| `slot` | 否 | 0–4，仅用于排序，不代表分路 |
| `hp` / `maxHp` / `mana` | 否 | 当前值，非负整数 |
| `level` | 否 | 0–100 |
| `gold` / `exp` | 否 | 累计值，非负整数 |
| `kills` / `deaths` / `assists` | 否 | 累计值，非负整数 |
| `damageDealt` / `damageTaken` | 否 | 累计值，非负整数 |
| `healing` / `towerDamage` / `visionScore` | 否 | 累计值，非负整数 |
| `x` / `y` | 否 | 世界坐标，有限数字 |
| `alive` | 否 | 布尔值 |

`frame` 必填，0–10000000；`time` 可选，单位秒。没有 `time` 时工作台按 30fps 估算时长，并在报告中标注。累计字段按最新帧取值；缺字段保持 `None`，不补零。

### 事件

`event` 必填，支持：

`kill`、`death`、`assist`、`tower`、`dragon`、`tyrant`、`overlord`、`teamfight_start`、`teamfight_end`、`skill_use`、`skill_hit`、`skill_miss`、`recall`、`revive`、`objective`。

可选字段：`playerId`、`targetId`、`camp`、`skillId`、`skillSlot`、`x`、`y`、`success`。事件不要求每帧都有；只有事件、没有帧时，队员指标不计算。

## 工作台计算

导入后生成：

- 每名队员：KDA、GPM、XPM、分均伤害、分均承伤、参团率、经济占比、伤害占比。
- 每方：5 人齐全时才计算团队击杀/经济/伤害等合计；不足 5 人保留 `partial` 与 `knownPlayers`，不把部分合计伪装成全队。
- 时间轴：只有双方各有 5 人完整金币/击杀时才生成采样点，最多 120 点。
- 事件：按类型和阵营计数；同时有 `skill_use` 与 `skill_hit` 时计算技能命中率。
- 覆盖：帧数、队员数、事件数、时长及每项指标的可用人数；缺字段写入 `warnings`。

KDA 使用 `(击杀+助攻)/max(1,死亡)`；零死亡时标记 `kdaPerfect`。参团率使用 `(击杀+助攻)/团队击杀`；团队击杀未知或为 0 时不计算。

## 导入方式

工作台接口：

```text
POST /api/replays/{replay_id}/runtime   原始 JSONL，Content-Type 不限
GET  /api/replays/{replay_id}/runtime   返回分析摘要
GET  /api/replays/{replay_id}/runtime/file  下载原始 JSONL
```

页面操作：回放实验室 → 查看结果 → 运行时赛训数据 → 选择 `.jsonl` → 导入并分析。

备份会同时保存运行时原文件和分析结果；恢复时重新校验并重算，旧备份没有 `runtimeFileId` 时保持原样。

## 采集路线

1. **共享内存（优先验证）**：在设备上读取 `CAutoReplayManager.GetIsShmReplay()`。为 `true` 时，按 `CShmReplayConsumer` 的 `mapfile`/`shm_name` 只读映射，再按已知帧结构导出字段。当前配置为 `false`，不能假设可用。
2. **进程内帧缓冲（需要注入/调试）**：对 `VisualFrameReplayManager.RecordFrame` 或 `GetCurrentFrameData` 取 `cppBuffer`，再解码帧结构。此路线需要 Frida、gdbserver 或 root 调试权限，可能触发反作弊；必须先获得明确授权，且只读、不修改进程内存。
3. **游戏内面板 / 录屏（不注入）**：用现有 OCR 路线读取可见的经济、KDA、输出、承伤、参团。覆盖不完整，但可核对，适合作为运行时数据的回退和交叉验证。

采集器只负责把字段写成上述 JSONL；不要把字段映射和统计逻辑复制进采集器，否则版本更新后两处会漂移。

设备在线且游戏进入回放后，先用只读探针确认运行时映射：

```powershell
python scripts/runtime_probe.py --json
python scripts/runtime_probe.py --dump --serial emulator-5554
```

探针会输出游戏 PID、`root` 状态、`libGameCore.so` / `ashmem` / `memfd` / `shm` 相关映射。`--dump` 需要 root，默认最多读取 4 MB，只读 `/proc/<pid>/mem`，不写游戏进程。

## 验证

```powershell
python -m unittest tests.test_runtime_data tests.test_replay_runtime_api -v
python scripts/verify_runtime_page.py
```

测试覆盖：完整两队指标、部分队伍不补零、零死亡 KDA、缺失 `time`、只有事件、非法字段、重复队员、8 MB 上限、导入/下载、重新导入保留运行时数据、备份恢复；浏览器验收覆盖页面导入、10 人指标表、时间轴、移动端无横向溢出。

## 版本与安全

- 适配样本版本为 12.1.1.x；字段偏移和运行时方法在不同构建间可能变化。
- 不修改 `.abc`、`.ope`、游戏包体或进程内存；采集器默认只读。
- 运行时数据只进入回放实验室，不自动创建正式比赛、不进入英雄胜率统计。
- 训练赛数据与公开赛事数据分开保存；导出文件可能含队员标识，按内部资料管理。
