# native hero 对象字段与一个被否决的金币候选

日期：2026-11-04。数据来自只读进程快照（pid 2135），回放暂停在
**07:43.20–07:43.22 / frame 7030–7052**。没有修改游戏、没有注入、没有点击。

## 0. 结论（先看这里）

- **`hero+0x50` 不是金币。** 它的十人合计 49,888 与营地团队金币插值
  50,283 很接近，但与 `state_table/state.jsonl` 在 07:46 的权威逐人 gold
  （3,962 / 4,805 / 5,011 / 5,012 / 4,540 / 3,945 / 4,549 / 3,775 /
  4,142 / 3,642）逐人对比完全不符，已否决。
- native 的**权威 gold 字段是 arena record `+0x4C`**，不是 hero 对象
  `+0x50`；现成结果见
  `data/replays/_analysis/live_20261104/state_table/state.jsonl`。
- hero 对象的 `+0x08` / `+0x10` 是 **HP current / HP max（归一化）**：
  例如 07:46 钟馗 `996 / 1079`，与 state_table 完全一致。
- `+0x5C` 仍未定语义，不能标 HP 或 gold。

## 1. 对象链

```text
ctx = 0x730fe87fcff0
ctx+0x3D0                         battle context
battle+0x40                       10-entry entity -> compact actor table
compact actor+0xD8                hero object (0x1900 B)
hero+0x08 / +0x10                 hp_current / hp_max (normalized)
hero+0x28                         heroID
hero+0x34                         camp (1/2)
hero+0x3C / +0x40                 entityID
hero+0x50                         rejected gold candidate (semantics unknown)
hero+0x278/0x27C/0x280            spawn anchor X/Y/Z
```

## 2. 为什么曾怀疑 +0x50 是 gold

- `+0x50 / 256` 的 10 个值全部是整数；
- 十人合计 **49,888**；
- Camp 官方团队金币在 07:43.2 的插值约 **50,283**（450s 48,833，
  480s 52,129），差 0.8%；
- 逐人值 3,488–6,368，量级像经济。

## 3. 为什么否决

`state_table/state.jsonl` 在 07:46 的 gold 是经过 UI 30/30 验证的 arena
record `+0x4C`：

| hero | entity | 权威 gold (07:46) | hero+0x50/256 (07:43) |
|---|---:|---:|---:|
| 钟馗 | 1168 | 3,962 | 5,600 |
| 妲己 | 1613 | 4,805 | 3,488 |
| 孙悟空 | 750 | 5,011 | 5,344 |
| 关羽 | 538 | 5,012 | 4,480 |
| 百里守约 | 1611 | 4,540 | 6,272 |
| 公孙离 | 1031 | 3,945 | 6,368 |
| 吕布 | 296 | 4,549 | 3,936 |
| 貂蝉 | 551 | 3,775 | 4,512 |
| 兰陵王 | 1799 | 4,142 | 4,896 |
| 张良 | 1760 | 3,642 | 4,992 |

逐人相差 0.5–2.4k，且方向不一致；3 秒不可能产生这种变化。因此 `+0x50`
不是 gold（更像经验/战斗统计/其他资源，语义未定）。

## 4. 已确认字段

- `hero+0x08` = HP current（归一化）
- `hero+0x10` = HP max（归一化）
- `hero+0x28` = heroID
- `hero+0x34` = camp
- `hero+0x3C/+0x40` = entityID
- `hero+0x278/+0x27C/+0x280` = spawn anchor X/Y/Z
- 权威 gold / KDA / level：arena record `+0x4C` / `gold+0x158` /
  `gold+0xB8` / `gold+0xBC` / `+0x220`，见 state_table。

## 5. 提取器

```bash
python host/scripts/extract_context_actors.py \
    data/replays/_analysis/client_probe_20261103/process_snapshot_A_active \
    --out host/build/g5/context_actors.json
```

输出 heroID/camp/entity、HP current/max、`field_5c`、spawn anchor；
`field_50` 仍输出但标记为 rejected candidate。不读取/不输出昵称、账号或字符串。

## 6. 下一步

- 不再追 `+0x50` 的 gold 假设；G7 以 arena record `+0x4C` / state_table 为准。
- `+0x5C` 需要用第二个时间点或 UI 对拍确定；若要确认，优先用已有
  state_table 的 4 个 checkpoint 做同帧对齐，而不是单点猜测。
