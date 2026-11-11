# 11/2 帧命令基线（N+1 对拍用）

日期：2026-11-03。来源：11/2 两局 `.abc`，`tools/replay_frame_commands.py`
的解码结果；时间按 15 fps（`t=(frame-1)/15`）。

## 产物

- `data/replays/_analysis/datasets/20261102_frame_commands.csv`
  - 25,846 行，每行一个出现命令的帧；
  - 列：sample, frame, time_sec, total, 各命令类别计数。
- `data/replays/_analysis/datasets/20261102_frame_commands_summary.json`
- `tools/build_frame_command_predict.py`

## 两局基线

| 样本 | 有命令帧 | 命令条目 | 单帧最大 |
|---|---:|---:|---:|
| 20261102_161129 | 10,473 | 88,627 | 24 |
| 20261102_163751 | 15,373 | 136,370 | 21 |

命令总量（161129 / 163751）：

- PLAYER_MOVE 68,384 / 103,120
- PLAYER_ATTACK 7,538 / 10,385
- PLAYER_ATTACKWITHOBJ 4,348 / 5,308
- BUYEQUIP 547 / 627
- LEARNSKILL 120 / 150
- USEDIRECTIONALSKILL 711 / 1,290
- USEOBJECTIVESKILL 641 / 724
- USEPOSITIONSKILL 78 / 343
- CC 6,258 / 14,391
- BASEATTACK 0 / 30
- SELLEQUIP 0 / 2

## 怎么和 live frapInfo 对拍

已知 live 结构：

```text
frapInfo + 0x0c 命令数
frapInfo + 0x10 命令数组
command  + 0x0c 类型 (1..27)
command  + 0x10 payload
```

对一个回放时刻 `t`：

1. 从 `.abc` 的 `frame_commands.csv` 取该帧 `total` 和类别计数；
2. 从 live `frapInfo` 取 `command_count` 和命令类型序列；
3. 若 `command_count == total`，且同一时段重复 seek 的类型序列稳定，
   才把 `frapInfo` 判为当前帧的命令集合；
4. 再把 type 1..27 的 payload 偏移与 `.abc` 的字段逐项对齐。

注意：`frapInfo` 的命令数不一定等于 `.abc` 的全部 tag 数；`CC` 是
BOOTFRAP1/CC buffer，可能不进入命令数组。因此对拍时要分别试
`total`、`total - CC`、以及按类别子集（例如 move+attack+skill）三种口径。
这一步没有 ground truth 前不能强行声称相等。

## 当前 live 锚点（2026-11-03）

回放播放到 `10:41` 时截屏：

- 比分 22:5，蓝/红团队金币约 36.0k / 27.3k；
- 对应 `.abc` frame≈9,615，该帧基线为 8 条命令
  （move 4、attackwithobj 1、BUYEQUIP 2、CC 1）；
- 营地 30 秒曲线在 10:30 为 37,807 / 27,954，10:41 的 UI 值在其
  显示取整/时钟误差范围内。

记录：`data/replays/_analysis/datasets/20261102_replay_ui_anchors.csv`。

