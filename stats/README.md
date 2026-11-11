# 匿名使用统计服务（作者自部署）

给作者自己看的「有多少台机器在用、每天有多少活跃」统计后端。客户端只发一条
不含任何身份信息的心跳（字段见 [docs/usage_stats.md](../docs/usage_stats.md)），
本目录是接收端。

**不会随客户端发布**：`scripts/make_release.py` 的 `ship_files()` 只收集根目录
`*.py`、`web/`、`resources/`、`v3/`、`docs/` 白名单和 `tools/` 白名单，`stats/`
不在其中；增量包同样只含变更的发布文件。所以这里可以放心写部署细节。

```
stats/
├─ server.py           单文件 FastAPI + SQLite 服务（VPS / 任意 Python 主机）
├─ cloudbase/          腾讯云 CloudBase 云函数（推荐，免运维）
│  ├─ index.js
│  └─ package.json
└─ README.md           本文件
```

两条部署路径的接口完全一致，客户端不关心后端是哪种：

| 接口 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/ping` | POST | 无 | 客户端心跳，按 `installId` upsert |
| `/api/summary` | GET | Bearer token 或 `?token=` | 汇总数字，JSON |
| `/` | GET | 同上 | 简易 HTML 仪表盘 |
| `/api/health` | GET | 无 | 存活探针，部署自检用 |

`/api/summary` 返回：

```json
{
  "ok": true,
  "schema": 1,
  "generatedAt": "2026-11-11T12:00:00+00:00",
  "totalInstalls": 42,
  "active24h": 12,
  "active7d": 20,
  "active30d": 31,
  "newLast7d": 4,
  "byVersion": {"1.6.3": 18, "1.6.2": 9},
  "lastPingAt": "2026-11-11T11:58:12+00:00"
}
```

## 方案 A：腾讯云 CloudBase 云函数（推荐）

免运维、有免费额度，适合只有几十到几千台安装的规模。前提：一个腾讯云账号和
一个云开发（CloudBase）环境。

1. **建集合**：云开发控制台 → 数据库 → 新建集合 `usage_installs`。
   权限选「所有用户不可读写」即可——云函数用的是管理端 SDK，不受该权限限制。
   建议给 `last_seen`、`first_seen` 建索引（集合 → 索引管理），数据量大时汇总更快。
2. **部署云函数**：云开发控制台 → 云函数 → 新建云函数，名称如 `kpl-stats`，
   运行环境 Node.js 16/18。把 `stats/cloudbase/` 下的 `index.js`、`package.json`
   上传，选择「云端安装依赖」（`@cloudbase/node-sdk` 由云端 npm 安装）。
3. **配环境变量**：云函数 → 配置 → 环境变量：
   - `STATS_TOKEN`：查询令牌，必填，用 32 位以上随机串（例如
     `python -c "import secrets;print(secrets.token_urlsafe(32))"`）；
   - `STATS_COLLECTION`：可选，默认 `usage_installs`。
4. **开 HTTP 访问服务**：云开发控制台 → 环境 → HTTP 访问服务 → 添加路径。
   把下面三条路径都指向 `kpl-stats` 云函数（同一函数即可）：
   - `/api/ping`
   - `/api/summary`
   - `/`
   开启后会得到一个 `https://<环境ID>.service.tcloudbase.com` 形式的域名。
5. **验证**（把域名和令牌换成自己的）：

   ```bash
   # 存活
   curl -s https://xxx.service.tcloudbase.com/api/health

   # 模拟一次心跳
   curl -s -X POST https://xxx.service.tcloudbase.com/api/ping \
     -H "Content-Type: application/json" \
     -d '{"schema":1,"app":"kpl-scrim-lab","installId":"0123456789abcdef0123456789abcdef","version":"1.6.3","os":"Windows","osVersion":"10","arch":"AMD64","startedAt":"2026-11-11T12:00:00+00:00","firstSeen":"2026-11-11T12:00:00+00:00"}'

   # 汇总
   curl -s "https://xxx.service.tcloudbase.com/api/summary?token=<STATS_TOKEN>"
   ```

   浏览器打开 `https://xxx.service.tcloudbase.com/?token=<STATS_TOKEN>` 看仪表盘。

> 说明：CloudBase 的 HTTP 访问服务在不同控制台版本里路径配置方式略有差异
> （有的叫「路径」，有的叫「触发路径」）。如果 `/api/ping` 访问 404，检查
> 路径是否指向了 `kpl-stats` 函数；函数内部对 `/api/ping` 和 `/ping` 两种
> 形式都做了兼容。

## 方案 B：任意 Python 主机 / VPS

一台能跑 Python 3.11+ 的机器即可，SQLite 单文件，无需额外数据库。

```bash
# 1) 装依赖（只用于服务端，客户端不需要）
python -m pip install "fastapi>=0.115,<1" "uvicorn>=0.30,<1"

# 2) 启动（token 换成自己的随机串）
python stats/server.py --host 127.0.0.1 --port 8788 \
  --db stats/usage.db --token <STATS_TOKEN>
```

公网使用请放在反向代理后面并配 HTTPS（客户端清单里的 `stats.url` 也建议用
HTTPS）。Caddy 示例（自动证书）：

```caddyfile
stats.example.com {
    reverse_proxy 127.0.0.1:8788
}
```

Nginx 示例：

```nginx
server {
    listen 443 ssl;
    server_name stats.example.com;
    # ssl_certificate / ssl_certificate_key 省略

    location / {
        proxy_pass http://127.0.0.1:8788;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
    }
}
```

systemd 常驻（可选）：

```ini
# /etc/systemd/system/kpl-stats.service
[Unit]
Description=KPL Scrim Lab usage stats
After=network.target

[Service]
WorkingDirectory=/opt/kpl-scrim-lab
ExecStart=/usr/bin/python3 stats/server.py --host 127.0.0.1 --port 8788 \
  --db /opt/kpl-scrim-lab/stats/usage.db --token <STATS_TOKEN>
Restart=always

[Install]
WantedBy=multi-user.target
```

> 服务本身只监听 `127.0.0.1` 时，必须靠反代对外；直接 `--host 0.0.0.0`
> 也可以，但记得用云安全组/防火墙只放行 80/443，别把 8788 裸露公网。
> SQLite 备份：停服务后拷走 `usage.db` 即可；WAL 模式运行中备份请用
> `sqlite3 usage.db ".backup usage-backup.db"`。
>
> 仓库 `.gitignore` 已忽略 `*.db`，但 WAL 模式还会生成 `usage.db-wal` /
> `usage.db-shm`；这两个文件是运行时数据，不要提交，也别拷进发布包。

## 启用客户端统计

统计地址写在更新清单 `update.json` 的可选顶层字段里，客户端从清单读取，
**以后开启/更换/关闭统计都不需要重新发版**（客户端复用 6 小时更新清单缓存）。

发版时带上地址即可（补丁内嵌清单与外层清单一致）：

```bash
python scripts/make_release.py --stats-url https://stats.example.com/api/ping
```

等价的手工方式：编辑生成的 `update.json`，加一段：

```json
"stats": {
  "url": "https://stats.example.com/api/ping",
  "periodHours": 20
}
```

- `url`：心跳接收地址，必须是 `http(s)`；建议直接给到 `/api/ping`（也可以给
  域名前缀，客户端会按原样 POST，所以最好写全路径）。
- `periodHours`：可选，1–168 的整数，默认 20。客户端成功心跳后这段时间内
  不再发；失败后至少隔 1 小时再试。

清单校验在 `update_client.normalize_manifest`：字段不合法会让更新清单整体
校验失败（旧客户端忽略该字段，不受影响）。客户端 ≥ 1.6.3 才会发心跳；
1.6.2 及更早版本只会忽略。

关闭统计：从 `update.json` 删掉 `stats` 即可。已部署的客户端在清单缓存过期
（6 小时）后停止发送；已经发出去的心跳无法撤回。

## 查看数据

```bash
# 可读报表（推荐）
python scripts/usage_report.py --url https://stats.example.com --token <STATS_TOKEN>

# 原始 JSON
python scripts/usage_report.py --url https://stats.example.com --token <STATS_TOKEN> --json

# 浏览器仪表盘
# https://stats.example.com/?token=<STATS_TOKEN>
```

`--url` 只写到域名即可，脚本会补 `/api/summary`；也支持直接写完整接口地址。
`--token` / `--url` 不传时分别读环境变量 `STATS_TOKEN` / `STATS_URL`。

## 安全与隐私

- `/api/ping` 必须公开（客户端不带凭据），因此**无法防止伪造心跳**；它只用于
  看趋势，不要当作计费/审计依据。
- `/api/summary` 与仪表盘只认 `STATS_TOKEN`，请用长随机串，不要写进前端或
  客户端包。
- 服务端数据库只存 `install_id / first_seen / last_seen / first_version /
  version / os / os_version / arch / pings` 九列，不存 IP、User-Agent、请求头
  或请求日志；`stats/server.py` 启动时默认 `access_log=False`（uvicorn 访问日志
  会带客户端 IP，排障时才加 `--access-log` 临时打开）。云函数代码里也没有
  `console.log` 请求内容，但平台级的函数调用日志由 CloudBase 默认保留，可在
  控制台调整保留时间。
- 数据库里只有随机 `installId` 和系统/版本字段，删掉某行即删除该安装的全部
  统计；`installId` 与账号、设备序列号无关联。
- 传输建议全程 HTTPS（CloudBase 自带；VPS 用 Caddy/Nginx 配证书）。

## 本地验证（不联网、不碰真实数据）

```bash
# 1) 用临时数据库起服务（端口别用 8766）
python stats/server.py --host 127.0.0.1 --port 8799 \
  --db %TEMP%\kpl-usage\usage.db --token testtoken

# 2) 用临时数据目录让客户端发一条心跳
set KPL_DATA_DIR=%TEMP%\kpl-telemetry
python -c "import telemetry; print(telemetry.ping_once('.', '1.6.3', update_result={'ok': True, 'stats': {'url': 'http://127.0.0.1:8799/api/ping'}}))"

# 3) 看报表
python scripts/usage_report.py --url http://127.0.0.1:8799 --token testtoken
```

停用验证：`set KPL_TELEMETRY=0` 后重跑第 2 步，应返回
`{'ok': False, 'reason': 'disabled'}`，且 `data/usage/` 下不会创建安装 ID。
