# GameCore view buffer / CS buffer live 解包（只读）

日期：2026-11-03。目标：解 `context+0x2b0` 的 view buffer 布局和
`PushViewBuffer/CommitViewBuffer` 接口，找真正的逐帧状态数组。
只读 ADB root + `/proc/<pid>/mem`；不注入、不调用游戏函数、不修改进程。

## 1. context 链

当前回放进程 pid 2052，`libGameCore.so` base `0x400036a00000`：

```text
base+0x4ff4520 -> 0x40003bbea4d0
              -> 0x40003bc717b0
              -> context 0x75d819773ff0
context+0x2b0 -> view object 0x75d8197bf5ec
```

`context+0x2b0` 的 view object 首 qword 是 vtable `0x75db20ca84e8`。

## 2. view buffer 对象布局

`PushViewBuffer` 的真实实现（file `0x46b6f9c`）：

```text
x0 = context+0x2b0
x8 = [x0]                  ; vtable
x8 = [x8+0x48]
blr x8                     ; 取/准备 subobject（x0 = view+0x90）
w1 = size
br [0x40003bc5a798]        ; 49caf98
```

`vtable+0x48` 目标 file `0x49c55c8`，实际只是：

```text
ldr x0, [x0]               ; 返回 subobject 首字段
ret
```

`CommitViewBuffer` 同样取 `view+0x90`，再调用返回对象的 `vtable+0x10`。

`view+0x90` 的 subobject 是一个 FIFO buffer 对象，实测字段：

| 偏移 | 含义 |
|---:|---|
| +0x00 | buffer vtable（`0x75db20ca6f60`） |
| +0x18 | data pointer |
| +0x20 | capacity（2048） |
| +0x24 | pending size |
| +0x2c/+0x30/+0x34 | 读/写游标 |
| +0x78/+0x80 | alloc/free 回调 |
| +0x10 | 当前块大小（本对象 4096） |

`0x49caf98`（PushViewBuffer 尾调用）：读 `+0x20` 容量，写 `+0x24=size`；
容量不足时重新分配，最后返回 `+0x18` 的数据指针。因此
`PushViewBuffer(size)` **只预留/返回缓冲区**，实际写入由调用方完成；
`CommitViewBuffer()` 提交该缓冲。

## 3. 实测内容不是战斗状态

view+0x90 的数据指针 `0x75db58d6f560`，cap=2048，pending=0。
数据前 4 B `0x264`（612），随后是若干消息字段；从约 `0xEE` 起是 UTF-8 JSON，
字段名包含 `login_token`、`access_token`、`cgToken`、`expire_ts`、
`webview_frame` 等。**这是登录/授权视图消息，不是十人逐帧战斗状态。**
（实际 token 值不写入文档，也不落盘。）

同 view object 的 `+0x80` 是另一个同类 FIFO：cap=2048、pending=8，
数据开头 `31 02 00 00 22 04 00 00` 后也带同一类 openID 字符串；仍是通用
view/消息通道。

结论：`context+0x2b0` / `PushViewBuffer` / `CommitViewBuffer` 是
**GameCore→宿主的通用 view/UI FIFO**，不能直接当作逐帧世界状态数组。
之前文档把“ViewBuffer = 每帧世界状态”当成已确认，本实测不支持这个说法。

## 4. CS 8 路缓冲池

`PushCsBuffer` 链：

```text
base+0x4ff5de8 -> 0x40003bc488b8
              -> 0x40003bcc3250
              -> 8 个对象指针
```

当前 8 槽中前 3 槽是有效 buffer 对象（vtable `0x75db20ca8608`）：

| 槽 | data | cap | pending |
|---:|---:|---:|---:|
| 0 | `0x75dcc9168a20` | 32768 | 8 |
| 1 | `0x75d8662eaff0` | 262144 | 24 |
| 2 | `0x75dcc9199680` | 32768 | 0 |

槽 0 数据开头：`1f 01 00 00 1e 00 00 00 10 58 81 00 ...`；
槽 1：`eb 04 00 00 90 04 00 00 0c 00 00 00 79 00 00 00 ff 7f 00 00 ...`。
这些是待提交的原始缓冲，不是已经映射好的十人字段。

`PushCsBuffer` 的实现（file `0x49cbf98`）**没有** `0x6c`，也没有 `0x7fff` 位域；
它只做“暂存区容量检查 + 返回 `+0x18` 写指针”。

**更正（2026-11-03）**：`0x6C`/`0x7FFF` 实际位于相邻的另一个类
（`0x49ccd44..0x49cd1a0`），是一个保存 108 B 多态记录的 SBO vector，
`0x7fff` 是它的 count/capacity/mode 位域，不是 CS 字节流的 head/tail。
CS ring/暂存区仍是原始字节流。详见 `docs/cs_fifo_context.md` §4。

## 5. 下一步

1. 对 8 路缓冲的 `+0x18/+0x20/+0x24` 做**帧内**差分（不是 UI 时间采样），
   找待提交记录的增长点；
2. 槽 0/1/2 的 pending 为 8/76/0，**不是 108 的倍数**；不要按 108 B 步长切分。
   先按原始字节/TDR 对拍 `.abc` 已知 FRAME_CMD 数量/类型，确认哪一路是帧命令、哪一路是状态；
3. 若确认某一路是逐帧状态，再按 TDR/字段表映射到 `CLevelContext/CPlayer`；
   不要把 108 B 当 CS 步长（它属于另一层的 SBO vector）；
4. view buffer 这条线保留为“通用视图通道”证据，不再当状态源。

## 6. 边界

- 只读；没有注入/调用/写进程。
- 实际登录 token/OpenID 值未写入文档或数据文件。
- 当前结论只证明 view buffer 是通用 FIFO；不证明 GameCore 没有状态出口，
  只是出口不在这里。
