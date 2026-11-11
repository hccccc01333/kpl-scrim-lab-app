"""KPL 赛训工作台 · 匿名使用统计服务（作者自部署）。

单文件 FastAPI + SQLite，**不随客户端发布包分发**（``scripts/make_release.py``
的 ``ship_files()`` 只收根目录 ``*.py``、``web/``、``resources/``、``v3/``、
``docs/`` 白名单与 ``tools/`` 白名单，``stats/`` 天然不在其中）。

启动::

    python stats/server.py --host 0.0.0.0 --port 8788 \
        --db stats/usage.db --token <一串足够长的随机字符>

接口：

* ``POST /api/ping``           客户端心跳（无需 token），按 ``installId`` upsert；
* ``GET  /api/summary``        汇总数字（Bearer token 或 ``?token=``）；
* ``GET  /``                   简易 HTML 仪表盘（同 token 校验）；
* ``GET  /api/health``         存活探针（无需 token，用于部署检查）。

只看数字：``python scripts/usage_report.py --url https://... --token <token>``。
字段与隐私边界见 ``docs/usage_stats.md``。
"""
from __future__ import annotations

import argparse
import hmac
import html
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

SCHEMA = 1
COLLECTION = 'usage_installs'
MAX_BODY_BYTES = 8 * 1024
# 客户端只会发 uuid4 hex；放宽到 1..64 位安全字符，兼容将来其它客户端。
INSTALL_ID_RE = re.compile(r'^[0-9A-Za-z._-]{1,64}$')
MAX_FIELD = 128
DAY_SECONDS = 24 * 3600

_SCHEMA_SQL = f'''
CREATE TABLE IF NOT EXISTS {COLLECTION} (
    install_id     TEXT PRIMARY KEY,
    first_seen     INTEGER NOT NULL,
    last_seen      INTEGER NOT NULL,
    first_version  TEXT NOT NULL DEFAULT '',
    version        TEXT NOT NULL DEFAULT '',
    os             TEXT NOT NULL DEFAULT '',
    os_version     TEXT NOT NULL DEFAULT '',
    arch           TEXT NOT NULL DEFAULT '',
    pings          INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_{COLLECTION}_last_seen
    ON {COLLECTION} (last_seen);
'''


def _iso(ts: float | int | None) -> str | None:
    if not ts:
        return None
    moment = datetime.fromtimestamp(float(ts), tz=timezone.utc)
    return moment.isoformat(timespec='seconds')


def _text(value, limit: int = MAX_FIELD) -> str:
    return str(value if value is not None else '').strip()[:limit]


def connect(db_path: Path | str) -> sqlite3.Connection:
    """建一条连接；WAL 模式在 ``init_db`` 里设置，这里只等锁。"""
    connection = sqlite3.connect(str(db_path), timeout=10.0)
    connection.execute('PRAGMA busy_timeout = 10000')
    return connection


@contextmanager
def _db(db_path: Path | str):
    """每请求一条连接：成功提交、失败回滚，最后一定关闭（``with`` 不会自动 close）。"""
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(db_path: Path | str) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(path)
    try:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.executescript(_SCHEMA_SQL)
        connection.commit()
    finally:
        connection.close()


def record_ping(db_path: Path | str, payload: dict) -> None:
    """按 ``installId`` 落库：首次插入，之后只更新 last_seen / version 并累加 pings。"""
    raw_install_id = payload.get('installId')
    install_id = str(raw_install_id if raw_install_id is not None else '').strip()
    # 先看原始长度再校验：不能截断后当合法 ID，否则超长串会被静默接受。
    if len(install_id) > 64 or not INSTALL_ID_RE.match(install_id):
        raise ValueError('installId 无效')
    now = int(time.time())
    version = _text(payload.get('version'), 64)
    os_name = _text(payload.get('os'), 64)
    os_version = _text(payload.get('osVersion'))
    arch = _text(payload.get('arch'), 64)
    with _db(db_path) as connection:
        updated = connection.execute(
            'UPDATE ' + COLLECTION + ' SET last_seen = ?, version = ?, os = ?, '
            'os_version = ?, arch = ?, pings = pings + 1 WHERE install_id = ?',
            (now, version, os_name, os_version, arch, install_id)).rowcount
        if not updated:
            try:
                connection.execute(
                    'INSERT INTO ' + COLLECTION + ' (install_id, first_seen, last_seen, '
                    'first_version, version, os, os_version, arch, pings) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)',
                    (install_id, now, now, version, version, os_name, os_version, arch))
            except sqlite3.IntegrityError:
                # 并发首插：另一个请求刚创建了同一 installId，补一次更新即可。
                connection.execute(
                    'UPDATE ' + COLLECTION + ' SET last_seen = ?, version = ?, '
                    'os = ?, os_version = ?, arch = ?, pings = pings + 1 '
                    'WHERE install_id = ?',
                    (now, version, os_name, os_version, arch, install_id))


def collect_summary(db_path: Path | str) -> dict:
    """``/api/summary`` 与仪表盘共用的汇总查询。"""
    now = int(time.time())
    cut_24h = now - DAY_SECONDS
    cut_7d = now - 7 * DAY_SECONDS
    cut_30d = now - 30 * DAY_SECONDS
    with _db(db_path) as connection:
        total = connection.execute(
            f'SELECT COUNT(*) FROM {COLLECTION}').fetchone()[0]
        active_24h = connection.execute(
            f'SELECT COUNT(*) FROM {COLLECTION} WHERE last_seen >= ?',
            (cut_24h,)).fetchone()[0]
        active_7d = connection.execute(
            f'SELECT COUNT(*) FROM {COLLECTION} WHERE last_seen >= ?',
            (cut_7d,)).fetchone()[0]
        active_30d = connection.execute(
            f'SELECT COUNT(*) FROM {COLLECTION} WHERE last_seen >= ?',
            (cut_30d,)).fetchone()[0]
        new_7d = connection.execute(
            f'SELECT COUNT(*) FROM {COLLECTION} WHERE first_seen >= ?',
            (cut_7d,)).fetchone()[0]
        last_ping = connection.execute(
            f'SELECT MAX(last_seen) FROM {COLLECTION}').fetchone()[0]
        rows = connection.execute(
            f'SELECT version, COUNT(*) FROM {COLLECTION} '
            'WHERE last_seen >= ? GROUP BY version '
            'ORDER BY COUNT(*) DESC, version',
            (cut_30d,)).fetchall()
    by_version = {(_text(version, 64) or '未知'): count for version, count in rows}
    return {
        'ok': True,
        'schema': SCHEMA,
        'generatedAt': _iso(now),
        'totalInstalls': total,
        'active24h': active_24h,
        'active7d': active_7d,
        'active30d': active_30d,
        'newLast7d': new_7d,
        'byVersion': by_version,
        'lastPingAt': _iso(last_ping),
    }


def _authorized(request: Request, token: str) -> bool:
    """Bearer 头或 ``?token=`` 均可用；常量时间比较，空 token 一律拒绝。"""
    if not token:
        return False
    candidates = []
    header = request.headers.get('authorization', '')
    if header.lower().startswith('bearer '):
        candidates.append(header[7:].strip())
    query = request.query_params.get('token', '')
    if query:
        candidates.append(query.strip())
    expected = token.encode('utf-8')
    for candidate in candidates:
        if hmac.compare_digest(candidate.encode('utf-8'), expected):
            return True
    return False


def _dashboard_html(summary: dict) -> str:
    def number(value) -> str:
        return f'{int(value or 0):,}'

    rows = ''.join(
        '<tr><td>{}</td><td class="num">{}</td></tr>'.format(
            html.escape(str(version)), number(count))
        for version, count in (summary.get('byVersion') or {}).items())
    if not rows:
        rows = '<tr><td colspan="2">近 30 天暂无活跃安装</td></tr>'
    last_ping = html.escape(str(summary.get('lastPingAt') or '—'))
    generated = html.escape(str(summary.get('generatedAt') or ''))
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KPL 赛训工作台 · 使用统计</title>
<style>
  body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; margin: 0;
         background: #0f1420; color: #e6e9f0; }}
  main {{ max-width: 760px; margin: 40px auto; padding: 0 20px; }}
  h1 {{ font-size: 20px; font-weight: 600; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
           gap: 12px; margin: 20px 0 28px; }}
  .card {{ background: #171e2e; border: 1px solid #263149; border-radius: 10px;
           padding: 14px 16px; }}
  .card .label {{ color: #8b97ad; font-size: 12px; }}
  .card .value {{ font-size: 26px; font-weight: 700; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; background: #171e2e;
           border: 1px solid #263149; border-radius: 10px; overflow: hidden; }}
  th, td {{ text-align: left; padding: 10px 14px; border-bottom: 1px solid #263149;
            font-size: 14px; }}
  th {{ color: #8b97ad; font-weight: 500; }}
  td.num, th.num {{ text-align: right; }}
  tr:last-child td {{ border-bottom: none; }}
  .foot {{ color: #66718a; font-size: 12px; margin-top: 18px; line-height: 1.7; }}
</style>
</head>
<body>
<main>
  <h1>KPL 赛训工作台 · 匿名使用统计</h1>
  <div class="grid">
    <div class="card"><div class="label">累计安装</div><div class="value">{number(summary.get('totalInstalls'))}</div></div>
    <div class="card"><div class="label">24 小时活跃</div><div class="value">{number(summary.get('active24h'))}</div></div>
    <div class="card"><div class="label">7 天活跃</div><div class="value">{number(summary.get('active7d'))}</div></div>
    <div class="card"><div class="label">30 天活跃</div><div class="value">{number(summary.get('active30d'))}</div></div>
    <div class="card"><div class="label">近 7 天新增</div><div class="value">{number(summary.get('newLast7d'))}</div></div>
  </div>
  <table>
    <thead><tr><th>版本（近 30 天活跃）</th><th class="num">安装数</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="foot">最近心跳：{last_ping}<br>页面生成：{generated}<br>
  数据来自客户端匿名心跳，不含主机名 / 用户名 / 路径 / 战队或对局内容。</p>
</main>
</body>
</html>'''


def create_app(db_path: Path | str, token: str) -> FastAPI:
    """构造 FastAPI 应用；``db_path`` / ``token`` 由 CLI 注入，便于本地测试。"""
    db_path = Path(db_path)
    init_db(db_path)
    app = FastAPI(title='KPL Scrim Lab Usage Stats', docs_url=None,
                  redoc_url=None, openapi_url=None)

    @app.get('/api/health')
    def health():
        return {'ok': True, 'schema': SCHEMA}

    @app.post('/api/ping')
    async def ping(request: Request):
        body = await request.body()
        if not body:
            raise HTTPException(400, '心跳内容为空')
        if len(body) > MAX_BODY_BYTES:
            raise HTTPException(413, '心跳内容过大')
        try:
            payload = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise HTTPException(400, '心跳 JSON 无效') from None
        if not isinstance(payload, dict):
            raise HTTPException(400, '心跳 JSON 无效')
        try:
            record_ping(db_path, payload)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {'ok': True}

    @app.get('/api/summary')
    def summary(request: Request):
        if not _authorized(request, token):
            raise HTTPException(401, '访问令牌无效')
        return JSONResponse(collect_summary(db_path))

    @app.get('/', response_class=HTMLResponse)
    def dashboard(request: Request):
        if not _authorized(request, token):
            return HTMLResponse(
                '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<title>需要访问令牌</title></head><body '
                'style="font-family:sans-serif;padding:40px">'
                '<h1>需要访问令牌</h1><p>在地址后加 <code>?token=你的令牌</code>，'
                '或用 <code>Authorization: Bearer</code> 头访问。</p></body></html>',
                status_code=401)
        return HTMLResponse(_dashboard_html(collect_summary(db_path)))

    return app


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='KPL 赛训工作台匿名使用统计服务（作者自部署，不随客户端发布）')
    parser.add_argument('--host', default='127.0.0.1',
                        help='监听地址；公网部署用 0.0.0.0 并配好反代 HTTPS')
    parser.add_argument('--port', type=int, default=8788, help='监听端口')
    parser.add_argument('--db', default=str(Path(__file__).resolve().parent / 'usage.db'),
                        help='SQLite 路径（默认 stats/usage.db）')
    parser.add_argument('--token', required=True,
                        help='查询接口访问令牌（必填；用足够长的随机串）')
    parser.add_argument('--access-log', action='store_true',
                        help='打印访问日志（默认关闭：不记录客户端 IP/UA，排障时再开）')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    app = create_app(Path(args.db).expanduser().resolve(), str(args.token or ''))
    import uvicorn
    # access_log 默认关闭：访问日志会带客户端 IP/UA，与「不记录 IP」的隐私口径
    # 冲突；需要排查部署问题时再显式加 --access-log。
    uvicorn.run(app, host=args.host, port=args.port,
                access_log=bool(args.access_log))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
