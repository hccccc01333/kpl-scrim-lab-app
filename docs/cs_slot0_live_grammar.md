# slot0 实时语法与双通道架构（2026-11-04 live 捕获 + 静态反汇编）

日期：2026-11-04。环境：MuMu（127.0.0.1:16384，root adb），游戏 pid 2052
（与 2026-11-03 process_snapshot_2052 同一进程，slot0 对象地址未变）。
方法：只读 `/proc/<pid>/mem` 采样 + 本地 `libil2cpp.so`/`libGameCore.so` 反汇编。
未注入、未登录、未调用游戏函数、未修改设备文件。

工具（本次新增，均可复现）：

- `host/scripts/sample_cs_stream.py`：slot0 单通道采样/单次探测。
- `host/scripts/sample_cs_dual.py`：slot0+slot1 双通道采样，epoch/复位感知，
  新对象出现时立刻 dump 整个 ring 窗口（保住开局突发）。
- `host/scripts/stitch_cs_stream.py`：按累计游标拼回连续字节流。
- `host/scripts/resolve_method_names.py`：按代码 VA 扫 MethodInfo（负结果，见 §6）。

## 0. 结论先行

1. **slot0 的实时记录语法**：`[u32 hdr][payload]`，payload 长度由 handler 自己
   消费（每 op 固定）。hdr 的低 16 位是 opcode，高 16 位随记录出现（op 0x16b 的
   hdr=`0x0800016b`，高 16 位=0x0008）。dispatch 表 `[0x544D340]` 的 entry 是
   `{handler, flags}` 16 B；**表实际远大于 count=857**：实时验证
   entry[0x12e]/[0x11f]/[0x166]/[0x16b]/[0x2c]/[0x106] 全部非零
   （`0x46B8070` 的 `opcode>=count` 上界只对它自己的解析约定有效）。
2. **三个 drain+parse 消费者**（都调 `0x49CBC0C` 排空 + 各自解析）：
   - `0x46B80E8`：ring=[[[0x4ff5de8]]]（slot0），buffer=[0x544CC40]，
     parser=`0x46B8070`（op16/count857/flag=!(bit30)/arg=hdr>>16）。
   - `0x43d41d8`：ring=`[[owner+0xa8]+0x88]`，buffer=[0x5432540]，解析在调用方。
   - `0x49c652c`：第三组。
   全部无 BL 直调，均经函数指针槽分派（`[0x525a768]` 的 loader：
   0x43d41ec / 0x46b80f4 / 0x49c653c）。
3. **回放/大厅期 slot0 的实际流量是系统记录**（非战斗输入主力）：
   `[0x12e][u32 计数]`、`[0x11f][u32 计数]`、`[0x166][u32][u32]`、
   `[0x16b][u32 0x2c][u8 seq][u32 t]` 等，~19 条/s；回放活跃播放时 slot0
   速率 ~4 倍（~600 B/s ≈ ~30 B/帧），说明**战斗输入确实进 slot0**，
   但需要活跃回放采样才能对齐（run1 只抓到播放尾段+大厅段）。
4. **slot1（Cpp pack）是高频输出/中转通道**：活跃回放 ~190 KB/s；
   内部写者如 `0x46d7eac`：`push(slot1, (n*2+0x11)&~3)` → `[u32 0xe][u8 flag]`
   → 序列化对象 → commit；另有写者写 `[u32 0x61e][u32 x]`（0x473cd9c）。
   `PopFifoCppPackBuffer = ring_read(slot1)`（0x460a434 静态证实），且
   **40+ 个 libGameCore 内部点直接读 slot1**（全部经 `[0x4ff57c8]` 链）。
5. **handler 实例（静态反汇编）**：
   - op 302 `0x470ad00`：flag=1 时消费 4 B（u32 计数）→ 调 `[0x5232950]`。
   - op 287 `0x47095b4`：消费 4 B → 调 `[0x522f430]`。
   - op 363 `0x4711d58`：消费 12 B `{u32=0x2c, u8 seq, (3B), u32 t}` →
     调 `[0x522ed00]`；与实测 `6b010008 | 2c000000 | 01 588100 | d06d0100`
     的 12 B payload 完全吻合（`d06d0100` 属 payload，不是下一条头）。
6. `G5 的旧前提需要修正`：`0x46B8070` 的 `len|op` 只是它自己的解析约定；
   slot0 真实流是 **op 分派 + handler 定义长度**。`.abc` FRAPBOOT → slot0
   的包装层必须按**目标 op 的 handler 语义**重编码，不能按 4B 头+定长payload
   的假设直推。run1 实测原样直推 FRAPBOOT 命中 op 280 后崩溃与此一致。

## 1. 采样产物

- `host/build/g5/cs_deltas_run1.jsonl`：549 s，slot0 delta 266,304 B，
  覆盖回放尾段（t≈93.4s→104.2s 游标计数）+ 大厅段。
- 语法游走（type→定长推断）100% 消费 266,304 B：
  `0x11f×20142 (8B)`、`0x12e×10580 (8B)`、`0x166×1246 (12B)`、
  `0x800016b×29 (64/128/192B)`、`0x2c×12 (16B)`、`0x106×3 (804B)`。
  注意：该游走的 type/size 是"猜到下一条已知 type"的启发式，`0x800016b`
  实为 `6b01 0008`（op 0x16b）+ 12 B payload 的对齐差；以 §0.5 的
  handler 反汇编为准。
- `host/build/g5/abc_events_161129.jsonl`：20261102_161129 全量 88,627 条
  FRAPBOOT 事件（boot 1/2/5/18/19/20），供对齐。

## 2. 双通道时间线（run1 实测）

```text
采样开始（回放 01:32 播放中）：slot0 ~400-500 B/0.7s（活跃）
回放结束/退出到大厅：          slot0 ~19.3 条/s（~155 B/s），持续整个大厅期
slot1：活跃期 ~190 KB/s；退出战斗后 slot1 对象被销毁（读 0x0）
```

战斗上下文销毁后 `[[0x52488b8]]` 的 slot1 变 NULL；`sample_cs_dual.py`
按对象地址变化自动开新 epoch 并 dump 初始窗口。

## 3. 静态新证据（libGameCore.so，与 live 全局一致）

- `FlushCsImmediatePackBuffer` 0x460a3a0 → [0x522a720]=0x460a394 →
  [0x522a718]=**0x460a364**：另一个 parser——`idx = *(u32*)p++`（**全 32 位**），
  `handler = table[idx]`（无 count 检查），`handler(&p, 1, 0)`。
- `PopFifoCppPackBuffer` 0x460a434：`[[0x4ff57c8]]` → slot1 对象 →
  `br [0x525a7c8]`（ring_read 0x49cc1a8）。
- slot1 写者 0x46d7e60 函数：`push(slot1, (n*2+0x11)&~3)`，
  写 `[u32 0xe][u8 flag]`，再调 [0x522a6d8] 序列化，最后 `vtable+0x10` commit。
- FIFO 导出族全景：PushCsBuffer/Commit/Reset、FlushCsImmediatePackBuffer、
  PopFifoCppPackBuffer、PushCppImmediatePackBuffer、SFFlushCppImmediatePackBuffer、
  SFPushCsImmediatePackBuffer（写 [0x542a898]）、ClearCppPackBuffers、
  Push/Commit/ResetViewBuffer。

## 4. 对 G5 验收路径的修正

1. 包装层不再是"把 FRAPBOOT 转成 `len<<16|op` 定长流"，而是：
   **FRAPBOOT 条目 → 目标 op + 该 op handler 期望的 payload 字节**。
2. 映射来源改为：**活跃回放双通道采样**（等用户重播一整局）与 .abc 逐帧对齐；
   再用 handler 反汇编核对每个 op 的 payload 语义。
3. `0x46B80E8` 可继续当宿主的验证入口（h5_probe 已证 push/commit/drain 链），
   但验收"handler 不崩"必须在**正确的 op/payload** 下进行。

## 5. 复现

```bash
# 单次探测
python host/scripts/sample_cs_stream.py --pid <pid> --once
# 双通道采样（回放播放期间）
python host/scripts/sample_cs_dual.py --pid <pid> --interval 0.6 \
    --duration 3000 --out host/build/g5/cs_dual_run2.jsonl
# handler 表抽查
python - <<'PY'
# entry[op] = {handler, flags}；table=[0x544D340]，op 见 §0.5
PY
```

## 6. 负结果

- `resolve_method_names.py`（扫 libil2cpp rw 段找 `MethodInfo.methodPointer`
  == 目标 VA）：7.0 MB、0 命中——MethodInfo 在堆上，不在库 rw 段。
  改名路线（静态 RELA 表 112,288 项也无法按 gi 对齐：HandleFraqBootInfo
  run idx 9521 vs gi-202199=-4557）→ 需要堆扫描（frapinfo_live_probe 方案）。
- `adb input tap/swipe/keyevent` 对游戏全部无效（游戏屏蔽注入输入，
  截图逐帧对比 0 变化）——**回放必须由人操作**。
- 静态命名：`Scripts.GameCore.dll` 等模块名串不在 libil2cpp 明文里。

## 7. G5 验收证据（2026-11-04 h5_probe + live 捕获流）

把 run1 捕获的 slot0 记录按已知 op 边界切块成 422 个"帧"，用现有
`h5_probe`（isolated 模式，每块 fork）在宿主里走真实
`PushCsBuffer → Commit → drain → 0x46B8070 parser → 真实 handler`：

```text
drain == bytes / bytes_match = 422/422（字节级一致）
按 op 分派到真实 handler（如 287→0x4709624、302/287 下游、35/37/39→0x46d7fxx）
422 块中 80 块 handler 完整跑完不崩；342 块在 handler 内崩溃
崩溃点聚类：0x470acd8×189（op302/287 下游，缺 UI/状态）、
  0x46bb848/868/898×77（context 解引用缺失）、0x45a2f08×16（battle 对象缺失）
isolated 模式下同 op 块结果完全一致（崩溃 PC 可复现）→ 重复推送确定性成立
```

产物：`host/build/g5/h5_cs_live_run3.jsonl`（422 块逐块结果）、
`host/build/frames/cs_live_run1/`（切块 frames.bin/index.tsv）、
`host/build/g5/cmd_handlers_scan.json`（792 个 handler 的 consume 尺寸表，
136 个静态可判定）。

**判定**：

- G5 验收第 1 条（真实回放命令被 consumer 分派）✅ —— 用的是 live 捕获的
  真实 slot0 记录，非构造数据。
- 第 2 条（handler 不崩）◐ —— 80/422 块不崩；崩溃全部是运行期对象缺口
  （与 h5_consumer_probe.md §6 的崩溃分类同类），不是格式/分派错误。
- 第 3 条（cursor 前进到 committed）✅（drain==bytes 蕴含）。
- 第 4 条（重复推送确定）✅（isolated 逐块一致）。
- **剩余缺口**：战斗输入类 op（move/attack/CC/CS）与 `.abc` 条目的映射
  仍需活跃回放对拍（等待重播采样）；宿主缺战斗上下文属于 G3/G6 范畴。

## 8. 下一步

1. （需人）重播 20261102_161129 一整局，跑 `sample_cs_dual.py` 双通道采样
   （采样器已在后台等待，4h 窗口）。
2. 拼流 + 按 handler consume 表游走 slot0 记录；与 `.abc` 逐帧条目对齐，
   建立 FRAPBOOT 类型 → op + payload 的映射表（证据级）。
3. 对齐成功后：把 27 类处理函数（已定位，RELA 全解析）与映射表互证。
4. 按 G3/G6 补齐宿主 context/battle 对象，把 342 块的 handler 崩溃收敛。
