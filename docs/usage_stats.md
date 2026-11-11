# 匿名使用统计

作者想知道「大概有多少台机器在用、每天有多少活跃、大家升级到哪个版本了」，
以便决定优先修哪些问题、什么时候停止维护旧版本。为此客户端会在启动后发一条
**匿名心跳**：一个本地随机生成的安装 ID + 版本号 + 操作系统类型，**不含任何
可识别身份的信息**。

统计默认关闭：只有更新清单 `update.json` 里出现可选的 `stats` 字段时才会发。
旧客户端（≤ 1.6.2）会忽略这个字段，不受影响；1.6.3 起支持。因为地址写在清单
里，以后开启 / 更换 / 关闭统计都不需要重新发版。

## 心跳字段

`POST <stats.url>`，`Content-Type: application/json`，超时 6 秒：

| 字段 | 示例 | 说明 |
|---|---|---|
| `schema` | `1` | 心跳协议版本，字段只增不改 |
| `app` | `kpl-scrim-lab` | 应用标识，固定值 |
| `installId` | `8e9fd3a7311c4cf3893f091e6966ca93` | 本机随机 UUID4（32 位十六进制），与账号/设备无关 |
| `version` | `1.6.3` | 当前工作台版本 |
| `os` | `Windows` | `platform.system()` |
| `osVersion` | `10` | `platform.release()`（内核版本号，如 `10` / `11`） |
| `arch` | `AMD64` | `platform.machine()` |
| `startedAt` | `2026-11-11T12:00:00+00:00` | 本次启动后第一次尝试心跳的时间（ISO 8601 UTC） |
| `firstSeen` | `2026-11-01T09:30:00+00:00` | 本安装第一次心跳的时间（ISO 8601 UTC），用于算新增 |

统计服务按 `installId` 去重落库，记录 `first_seen`、`last_seen`、`first_version`、
`version`、`os`、`os_version`、`arch` 与心跳次数。服务端用自己的时钟记
`first_seen` / `last_seen`，不依赖客户端时钟。

### 不采集什么

以下内容**永远不会发送**，代码里也没有对应字段（`tests/test_telemetry.py`
里有一条用例专门断言 payload 字段集合固定）：

- 主机名、计算机名、Windows 用户名、登录账号、IP 地址；
- 文件路径、数据目录、项目 / 战队 / 选手名称；
- 对局、阵容、比分、截图、录屏、OCR 结果等任何业务数据；
- 浏览器信息、已安装软件列表、MAC / 硬盘序列号等设备指纹；
- 崩溃堆栈、日志内容。

服务端也只保存上面那张表里的字段，不记录 IP、User-Agent 或来源地域：SQLite 表
只有 `install_id / first_seen / last_seen / first_version / version / os /
os_version / arch / pings` 九列，`stats/server.py` 默认关闭 uvicorn 访问日志
（`access_log=False`，排障时才用 `--access-log` 临时打开）。云函数代码同样不打
请求内容，但 CloudBase 平台级的函数调用日志由平台默认保留，可在控制台调整。

## 停用（opt-out）

两种方式，任选其一，**立即生效**（下次启动不再联网）：

1. 环境变量：`set KPL_TELEMETRY=0`
   也接受 `false` / `off` / `no`（不区分大小写）。想恢复就删掉该变量。
2. 停用标记文件：在数据目录下新建空文件 `data\usage\optout`。

停用后不再发送任何心跳（当前进程只在启动时发一次，已经发出的无法撤回）。如果
之前已经生成过安装 ID，它会保留在本机（页脚「匿名统计」说明框里仍会显示它，
仅用于展示和换新身份）；想换一个新身份，删掉 `data\usage\install_id.txt` 即可
（重新开启统计后的下一次启动会重新生成随机 ID；关闭状态下打开说明框不会新生成）。

## 使用者可见的告知

统计不是偷偷进行的：工作台首次打开会主动弹一次说明，之后页脚「匿名统计」入口
可以随时查看状态、关闭或重新开启。前端代码在 `v3/public/telemetry-notice.js`，
启动接线在 `v3/public/app.js`（`initTelemetryNotice({ API_BASE })`），样式在
`v3/public/style.css`（`.usage-dialog`）。

### 首次打开自动提示

- 页面加载约 2 秒后弹出「匿名使用统计」说明框，**只自动弹一次**（浏览器
  `localStorage` 记 `kpl-telemetry-notice-v1`）；如果当前已关闭统计，不再自动弹。
- 说明框明确列出「会上报 / 不会上报」两份清单，展示本机匿名安装 ID（可一键复制）
  与当前状态，并提供「关闭匿名统计 / 继续使用」按钮。
- 说明框读取状态失败（后端未就绪、接口异常）时静默跳过，不阻塞工作台。

### 页脚入口与开关

- 页面页脚有「匿名统计」按钮（`data-action="usage-info"`），随时重新打开同一
  说明框，看到实时状态：是否开启、是否被环境变量关闭、安装 ID、最近一次心跳、
  上报周期。
- 点「关闭匿名统计」→ 写 `data/usage/optout`；点「重新开启」→ 删除该文件。
  关闭后本机不再发心跳（当前进程只在启动时发一次，已发出的无法撤回）。

### 对应接口

| 接口 | 方法 | 作用 |
|---|---|---|
| `/api/usage/status` | GET | 返回 `enabled`、`envDisabled`、`optout`、`installId`、`lastPingAt`、`lastError`、`periodHours` |
| `/api/usage/optout` | POST | 关闭匿名统计：写 `data/usage/optout` |
| `/api/usage/optin` | POST | 重新开启：删除 `data/usage/optout` |

这三个接口只服务本机页面（工作台默认只监听 `127.0.0.1`），实现见
`update_api.py` 的 `create_update_router`；真正的上报逻辑仍只在 `telemetry.py`。

### opt-out 优先级

从高到低：

1. **环境变量** `KPL_TELEMETRY=0`（或 `false` / `off` / `no`）：优先级最高。
   一旦设置，工作台内开关会被隐藏/禁用（`/api/usage/status` 返回
   `envDisabled=true`），必须去掉这个环境变量并重启才能恢复上报。
2. **`data/usage/optout` 标记文件**：页脚开关写/删的就是它。存在即关闭。
3. 两者都没有、且更新清单里有 `stats` 字段时才会上报。

也就是说：环境变量可以强制关闭统计（页面里改不回来）；页面开关只操作 optout
文件，不会覆盖环境变量的决定。

## 本机存了什么

统计相关的本地文件都在数据目录（默认 `<安装目录>\data\usage\`；设置
`KPL_DATA_DIR` 时跟着走）：

| 路径 | 内容 |
|---|---|
| `data\usage\install_id.txt` | 随机安装 ID（uuid4 hex）。统计开启时首次发心跳或打开页脚「匿名统计」说明框懒创建；关闭统计时不新生成；升级 / 覆盖安装不删除 |
| `data\usage\first_seen.txt` | 本安装第一次心跳时间（ISO 8601 UTC） |
| `data\usage\last_ping.json` | 节流状态：上次尝试 / 成功时间、上次错误原因。用于「成功 20 小时内不重复、失败至少隔 1 小时再试」 |
| `data\usage\optout` | 存在即停用（空文件即可，可选） |

这些文件都不含敏感信息，可以随时删除；删除 `install_id.txt` 等于放弃旧身份，
统计端会把它当成一台新安装。

## 客户端行为

- 启动时（`server.py` 的 `__main__`）调用 `telemetry.maybe_ping(ROOT, VERSION, delay=75.0)`，
  内部起 **daemon 线程**，先等约 75 秒再联网——不阻塞启动，不改变任何现有路由，
  也让工作台有机会先把「匿名统计说明」展示给使用者。
- 统计地址来自 `update_client.check_for_update()` 结果里的 `stats.url`，
  复用更新清单的 6 小时缓存，离线时不会额外请求。
- 成功心跳后 `periodHours`（默认 20）小时内不再发；失败（断网、服务没开、
  超时等）至少隔 1 小时再试。
- 任何异常都静默吞掉，只在 `last_ping.json` 记一笔，不会弹窗、不会写日志噪音、
  不会影响工作台功能。

代码位置：`telemetry.py`（心跳）、`update_client.py`（清单 `stats` 字段校验与
透传）、`server.py`（启动钩子）。

## 启用（作者侧）

1. 部署统计服务：推荐腾讯云 CloudBase 云函数（免运维），备用方案是任意
   Python 主机 / VPS。分步说明见 [`stats/README.md`](../stats/README.md)。
2. 拿到地址后发版时传入：

   ```bash
   python scripts/make_release.py --stats-url https://stats.example.com/api/ping
   ```

   生成的 `update.json`（以及补丁包内嵌的那份）会带上：

   ```json
   "stats": {
     "url": "https://stats.example.com/api/ping",
     "periodHours": 20
   }
   ```

   `periodHours` 可省略（默认 20，允许 1–168 的整数）。也可以手工编辑
   `update.json` 加这一段，效果相同。
3. 不想发版就启用/关闭/换地址：直接改清单里的 `stats` 字段。客户端最迟在
   更新清单缓存过期（6 小时）后读到新配置；**已经发出去的心跳无法撤回**。

清单校验规则（`update_client.normalize_manifest`）：

| 字段 | 规则 |
|---|---|
| `stats` | 可选；出现时必须是对象 |
| `stats.url` | 必填，`http` / `https` 绝对地址，最长 512 字符 |
| `stats.periodHours` | 可选，1–168 的整数，缺省 20 |

字段不合法会让整份更新清单校验失败（这是有意的：统计配置写错不应该悄悄
失效）。旧客户端不校验、直接忽略未知字段。

## 查看数据

```bash
# 可读报表
python scripts/usage_report.py --url https://stats.example.com --token <令牌>

# 原始 JSON（适合自己再加工）
python scripts/usage_report.py --url https://stats.example.com --token <令牌> --json
```

`--url` 写域名前缀即可（脚本自动补 `/api/summary`），`--token` / `--url` 也可
分别用环境变量 `STATS_TOKEN` / `STATS_URL` 提供。报表包含：

```
累计安装、24 小时活跃、7 天活跃、30 天活跃、近 7 天新增、
最近心跳时间、近 30 天活跃安装的版本分布
```

也可以直接用浏览器打开 `https://<统计服务域名>/?token=<令牌>` 看简易仪表盘；
或者 `GET /api/summary`（`Authorization: Bearer <令牌>` 或 `?token=<令牌>`）。

统计口径：

- **累计安装**：数据库里出现过的不同 `installId` 数；
- **活跃**：`last_seen` 落在最近 24 小时 / 7 天 / 30 天内的安装数；
- **新增**：`first_seen` 落在最近 7 天内的安装数；
- **版本分布**：最近 30 天活跃安装的 `version` 分布。

## 隐私说明

- 安装 ID 是客户端本地随机生成的 UUID4，不来自硬件、账号或网络信息，作者
  无法据此反查到具体的人或机器；
- 心跳只描述「有一台 Windows 机器在 1.6.3 上启动过一次」，不包含任何业务
  内容；
- 传输走 HTTPS（CloudBase 自带；VPS 请配证书），数据库只有作者能访问；
- 想退出：`KPL_TELEMETRY=0` 或 `data\usage\optout`（见上文）；不放心也可以
  删掉整个 `data\usage\` 目录；
- 统计服务本身不随客户端发布，赛训组拿到的 full.zip / 安装包里没有 `stats/`。

## 本地调试

不需要联网、不碰真实数据：

```bash
# 1) 临时数据库起服务（端口别用 8766，避免和已开的工作台冲突）
python stats/server.py --host 127.0.0.1 --port 8799 ^
  --db %TEMP%\kpl-usage\usage.db --token testtoken

# 2) 临时数据目录 + 手动发一条心跳
set KPL_DATA_DIR=%TEMP%\kpl-telemetry
python -c "import telemetry; print(telemetry.ping_once('.', '1.6.3', update_result={'ok': True, 'stats': {'url': 'http://127.0.0.1:8799/api/ping'}}))"

# 3) 看报表
python scripts/usage_report.py --url http://127.0.0.1:8799 --token testtoken
```

离线单测（mock 掉全部 HTTP，不联网）：

```bash
python -m pytest tests/test_telemetry.py tests/test_update.py -q
```
