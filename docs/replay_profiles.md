# 回放解析档案与版本流水线

回放的容器布局和帧命令 selector 都是**按客户端构建验证的观测结果**，不是官方
契约。新版客户端可能移动偏移、增删命令类型或改字段宽度。为避免把某一构建的
偏移硬编码进代码，解析器按“档案（profile）”选择布局，并在未配置时**拒绝复用
旧偏移**。

## 1. 档案在哪里

- 配置：`resources/replay_profiles.json`（可编辑，优先于代码内置）
- 代码兜底：`replay_profiles.py` 的 `BUILTIN_PROFILES`
- 解析器：`replay_parser.py`（容器/十人块/尾部流）
- 命令解码：`tools/replay_frame_commands.py`（帧命令 selector → 字段）

当前档案：`observed-12.1.1.x-v3`

| 字段 | 值 |
|---|---|
| `versionPrefixes` | `["12.1.1."]` |
| `builds` | `4989537` / `5230306` / `5247758`（记录用） |
| `requireBuilds` | `false`（按版本前缀匹配；设为 `true` 时才强制 build 命中） |
| `blockStride` | 1517 |
| `heroOffsets` | `[771, 1415, 1445]` |
| `tlvStart` | 17652 |
| `roster*` | 十人块扫描/尾部/后置字节参数 |
| `frameScanLimit` | 393216 |

匹配规则：客户端版本或资源版本以任一 `versionPrefixes` 开头即命中；
`requireBuilds: true` 时还要求构建号在 `builds` 中。未命中时：

- `inspect_replay` 只读头部，`layoutSupported=false`，**不**用旧偏移推断十人；
- `hero_inputs` 返回 `status=unsupported-version`，附带版本/构建号和接入指引；
- 页面显示“未匹配档案”，不会把未知版本当成已支持。

## 2. 新增一个客户端版本

1. **取样**：用新构建录一局，保存 `.abc`（最好同时有 `.ope`）和对应截图。
2. **读头**：确认 `versions` / `builds`（`parse_header` 或页面“文件解析结果”）。
3. **验证容器**：先复制现有档案，只改 `id` 和 `versionPrefixes`，用
   `inspect_replay` 看十人块、TLV、帧流是否与样本一致。不要凭猜测改偏移。
4. **重跑 selector 映射**：帧命令类型表在
   `tools/replay_frame_commands.py` 的 `CS_SCHEMAS` / `BOOT_SCHEMAS`。新构建若
   命令类型变化，先离线反推 selector → 字段，更新表，再用整局验证
   “每帧消费字节数 == 声明字节数、0 unresolved”。
5. **对拍**：用 `tools/full_abc_event_catalog.py` 生成整局事件表，检查
   行数、族别计数、未知行=0；再用检查点 UI（金币/KDA/等级）核对统计。
6. **回归**：`python -m unittest tests.test_replay_parser tests.test_replay_profiles
   tests.test_replay_frame_commands`。
7. **发布**：把档案写入 `resources/replay_profiles.json`，在变更说明里记录
   样本 SHA-256、构建号、验证结果。不要删除旧档案，旧回放仍要能解析。

## 3. 置信度分层

产品展示必须区分来源，估算值不进入正式统计：

| 标签 | 含义 | 例子 |
|---|---|---|
| 文件解码 | `.abc` 容器/帧命令直接解码，可复现 | 移动方向、攻击、技能、购买、CC |
| 引擎实测 | GameCore 运行时导出或检查点内存采样 | 金币、KDA、等级、归一化血量 |
| UI 采样 | 截图/小地图/面板读数，时间点有限 | 十人小地图坐标、结算面板 |
| 估算 | 由输入方向/插值/积分推算，仅供趋势 | 逐帧位置积分、检查点间金币/血量 |

API 约定：

- `inspect_replay` 报告带 `profileId`、`profileSource`、`provenance`、`confidence`；
- `/api/replays/{id}/inputs` 带 `confidence`（moves/attacks/buys=decoded，
  positions=estimated）和 `profileId`；
- 前端“数据来源与置信度”图例按上述四档展示；缺失来源显示“未使用”，不补造。

位置积分的当前验证误差约 **17.8% 地图跨度**（目标 ≤5%），因此 V1 只作为
“位移形状/趋势”，不作为逐帧坐标；要进入正式统计，需要真实位置通道
（引擎 actor/transform 外部堆指针）或密集且身份明确的小地图锚点。
