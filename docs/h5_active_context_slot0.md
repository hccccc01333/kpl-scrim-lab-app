# A 路线：active native battle context + slot0 handler 实跑

日期：2026-11-04。输入是只读进程快照 + 本地宿主 `libGameCore.so`；没有注入、
没有在游戏进程里调用函数、没有修改游戏文件。快照原始字节只在 `data/` 忽略目录。

## 0. 结论

1. active context（真正的 binder context）：
   `P = 0x730fe87fcff0`，`P+0x3d0 = 0x730fea5db178`，对象可读。
   这是当前播放回放进程的上下文，不是早期抓到的 wrapper `0x75d7e86e9ff0`。
2. 在宿主里，slot0 的命令流可以由真实 parser `0x46B8070` 逐条分派到真实
   handler；已实测的非零 op：
   `0x0d` 帧标记、`0x83` move、`0x84` attack、`0x32` 位置/技能、`0x34`
   stopmove、`0x39` 目标技能、`0x3a` 方向技能、`0x3b` 位置技能、
   `0x48` learn、`0x4d` buy、`0x73` direction。
3. 结果：
   - 1–200 帧 isolated：**200/200 ok**，0 crash；
   - 1–200 帧 sequential（同一 context 连续）：**200/200 ok**；
   - 400–440 帧（含 0x39/0x3a/0x3b）：**41/41 ok**，逐 op 计数与重建
     fixture 完全一致；
   - 单个 0x39 必需 slot1 的帧（seq 484）：补 slot1 后 **ok**。
4. handler 不是 no-op：同一帧执行前后，context arena 有 **113–126 字节**
   变化，move 记录以 0x20 字节对象累积；但这仍是 **命令/协议记录写入**，
   不是已证明的 `Dimension.DS` 战斗状态推进。
5. 1000 帧 sequential 在 frame 667 崩在 `0x28719f0`（哈希/索引查找），
   说明长时间连续把网络日志当模拟输入会破坏内部状态；逐帧隔离仍可用。
   这支持原有架构结论：slot0 是网络同步日志，不是回放模拟输入。

## 1. 快照与启动条件

```text
pid           2135
old base      0x400036a00000
context P     0x730fe87fcff0
context size  0x1E00000
snapshot      39 regions mapped, 0 failed
consumer      [0x544CC40] = 0x73144c078290
slot0         fresh（真实 ctor 0x49CBD88 + 手工字段初始化）
slot1         --init-slot1 时 fresh（同一套 ctor/字段）
```

`ctx+0x80/+0x88` 是 slot0/slot1 的 BSS 指针；本快照里 `+0x88` 为 0，所以
`0x39` 的某些 payload 会走 `[0x52488C0] -> 0x52C3258 -> [slot1]`，需要
`--init-slot1`。

## 2. 必需的 globals 窗口

只拷贝完整 BSS 会在宿主启动阶段崩；当前可用的是“按需窗口 + 单 qword 修补”：

| 区间 | 大小 | 作用 |
|---|---:|---|
| `0x4FF8000-0x526F000` | 2,584,576 | libGameCore data（含 slot 数组对象 `0x52488C0`） |
| `0x526F000-0x5281000` | 73,728 | 早期 BSS 窗口 |
| `0x544C000-0x544D478` | 5,240 | `0x544CC48` 的 0x1C2 项跳转表；修掉 `0x3a` 的 `br x3=0` |

另有两个 active-context 专用修补（`--init-slot1` 时启用）：

```text
mprotect(base+0x4FF000, 0x1000, RW)
*(u64 *)(base+0x4FF57C8) = base+0x52488C0   // slot 数组地址
slot1 = make_cs_obj(ring_size)              // 真实 ctor + host alloc/free
```

`0x4FF57C8` 位于 data 段起点 `0x4FF8000` 之前的页面；整页拷贝会覆盖宿主
`.data.rel.ro`/GOT 并导致 allocator 崩，所以只改这一个 qword。

## 3. 逐 op 分派证据

### 3.1 200 帧（含 buy/learn/stopmove/direction）

```text
frames 200, ok 200
trace: op0d=200, op83=963, op84=33, op32=93,
       op34=12, op48=9, op4d=10, op3a=1
```

`host/build/g5/a_active_1_200_globals2.log`（200 isolated）和
`host/build/g5/a_seq_1_200_slot1_final.log`（200 sequential）都是 200/200 ok。

### 3.2 400–440 帧（技能 op 覆盖）

```text
frames 41, ok 41
trace: op0d=41, op83=344, op84=27,
       op39=2, op3a=1, op3b=1, op34=4, op73=5
```

`build_cs_frame.py` 的统计同样是 `cs_target=2, cs_directional=1,
cs_position=1, cc_stopmove=4, cc_direction=5`，逐项相等。
日志：`host/build/g5/a_active_400_440_trace2.log`。

### 3.3 slot1 缺口

frame seq 484 含 `0x3a + 0x39`；没有 slot1 时 `0x3f864d8` 的 `br x3` 取到 0。
补 slot1 后：

```text
frame 483 / seq 484: status=ok
trace total=10: op0d=1, op83=7, op3a=1, op39=1
```

日志：`host/build/g5/a_frame484_slot1b.log`。

## 4. context 侧写效果（frame 100）

`--diff-context` 对 context 所在 30 MiB region 做前后 FNV/逐 qword 比较：

```text
frame 100: diff 114 B, first 0x730fe87fd018
frame 101: diff 126 B
frame 102: diff 113 B
```

主要变化：

- `ctx+0x28` 指向的向下增长缓冲区每次减少 0xC0（6 条 move × 0x20）；
- 缓冲区条目含 `0x83` tag、frame 101/102/103、wMoveInfo；
- `ctx+0x...0AF00` 低 32 位每帧 +6（6 条 move）；
- 两个计数器 `+1/-1` 变化。

这说明 handler 确实有副作用，但副作用是命令队列/序列化记录，不能据此声称
`actorGoldCoin`、HP 或 `Dimension.DS` 已推进。

## 5. 仍未完成

- 长时间 sequential：1000 帧在 frame 667 崩于 `0x28719F0`（索引/哈希查找），
  需要判断是合成命令流触发内部状态破坏，还是仍缺对象；逐帧 isolated 不受影响。
- `0x39/0x3b` 的字段语义只保证分派与长度，不保证与真实客户端 payload 完全同构。
- 回放模拟真值仍应走托管 `AdvanceFrameCommands / Dimension.DS`；slot0 是网络日志。
- 未把 handler 副作用映射到经济/HP/KDA 字段；G7 仍待 DS/HeroData 验证。

### 5.1 1000 帧 isolated 全通过

`--mode isolated --limit 1000 --init-slot1` 的结果：

```text
1000/1000 ok
trace: 0x0d=1000, 0x83=6742, 0x84=1325, 0x32=100,
       0x39=39, 0x3a=36, 0x3b=6, 0x34=193,
       0x48=20, 0x4d=29, 0x73=116
```

与 `build_cs_frame.py --frames 1-1000` 的统计逐项相等。日志：
`host/build/g5/a_iso_1_1000_slot1.log`。

### 5.2 native actor 表：静态描述，不是逐帧状态

`ctx+0x3D0` 的 battle context 对象在 `+0x40` 指向一张 10 项
`entityID -> actor*` 表（entry 0x20 B：key、actor 指针、slot/order、hash）。
每个 actor 对象可读，字段示例：

```text
+0x08  camp/type          +0x14 entityID
+0x10  slot/order-ish     +0x18 候选资源/HP（语义未定）
+0x2c  camp 1/2           +0x40 / +0x64 统计/顺序
```

关键否定结果：

- 同一 replay 的两份快照（pid 2052、pid 2135）actor 字段逐字节相同；
- 连续执行 200 帧 move/attack/skill 后，10 个 actor 对象 **0 字节变化**；
- 每帧调用 `0x46B7888(delta)`（native 帧生产者）200 次，actor 仍 **0 字节变化**。

因此这些 actor 是 level/desk 初始化时建立的静态描述（身份、阵营、基础属性），
不是 `Dimension.DS` 的实时 HP/金币/等级状态。不要把 `+0x18` 直接标成 gold。

同一 context 里还有一张静态 10 人映射表（`ctx+0x241870` 附近，stride 0x10）：
`{0, heroID, entityID, slot/order}`，覆盖本局 10 人，可用于身份对拍和 DS
对象关联；但它同样不随帧变化。

### 5.3 hero 对象字段：gold 候选已被否决

compact actor 的 `+0xD8` 指向同 arena 的 0x1900 B hero 对象。该对象：

```text
+0x08/+0x10 hp current/max（归一化）
+0x28 heroID   +0x34 camp   +0x3C entityID
+0x50 曾被怀疑为 gold；已用 state_table 07:46 权威 gold 逐人否决
+0x278/+0x27C/+0x280 spawn anchor X/Y/Z
```

`+0x50/256` 的十人合计 49,888 与营地团队金币插值 50,283 很像，但与
arena record `+0x4C` 的权威逐人 gold 完全不符，不能当金币。真正的
gold/KDA/level 字段在 arena record `+0x4C` 等偏移，已有
`data/replays/_analysis/live_20261104/state_table/state.jsonl`。

详见 `docs/native_hero_fields.md`；提取器：
`host/scripts/extract_context_actors.py`。

## 6. 复现

```bash
python host/scripts/build_cs_frame.py host/build/g5/abc_events_161129.jsonl \
    --frames 1-200 --frames-dir host/build/frames/recon_1_200

SNAP="$(pwd -W)/data/replays/_analysis/client_probe_20261103/process_snapshot_A_active" \
CMDTAB="$(pwd -W)/host/fixtures/20261102_161129/consumer_active/cmd_table.bin" \
FRAMES_DIR="$(pwd -W)/host/build/frames/recon_1_200" \
CTX=0x730fe87fcff0 CONSUMER=0x73144c078290 \
PUSH_SNAPSHOT=0 MSYS_NO_PATHCONV=1 \
bash host/scripts/run_h5_probe.sh --mode sequential --limit 200 \
    --globals /data/local/tmp/gc_transplant/globals_selective \
    --trace-dispatch --init-slot1
```
