"""查询匿名使用统计服务并打印可读报表。

用法::

    python scripts/usage_report.py --url https://stats.example.com --token <令牌>
    python scripts/usage_report.py --url http://127.0.0.1:8788 --token <令牌> --json

``--url`` 可以只写到域名/前缀（脚本会拼 ``/api/summary``），也可以直接写完整
接口地址。``--token`` 不传时读环境变量 ``STATS_TOKEN``；``--url`` 不传时读
``STATS_URL``。统计服务的部署方式见 ``stats/README.md``。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

TIMEOUT_SECONDS = 10.0
USER_AGENT = 'KPL-Scrim-Lab-UsageReport/1.0'


def summary_url(base: str) -> str:
    """把 ``https://host`` / ``https://host/api`` / 完整接口地址统一成 /api/summary。"""
    text = str(base or '').strip()
    if not text:
        raise ValueError('统计地址为空')
    parsed = urlparse(text)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError(f'统计地址必须是 http(s) 地址：{base!r}')
    text = text.rstrip('/')
    if text.endswith('/api/summary'):
        return text
    return text + '/api/summary'


def fetch_summary(url: str, token: str, timeout: float = TIMEOUT_SECONDS) -> dict:
    """GET /api/summary；失败抛 ``RuntimeError``（带可读原因）。"""
    request = Request(url, headers={
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json',
        'User-Agent': USER_AGENT,
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = ''
        try:
            detail = exc.read().decode('utf-8', 'replace').strip()[:300]
        except Exception:  # noqa: BLE001 - 只为错误提示，读不到就算了
            detail = ''
        reason = f'HTTP {exc.code}' + (f'：{detail}' if detail else '')
        if exc.code == 401:
            reason += '（令牌无效，检查 --token / STATS_TOKEN）'
        raise RuntimeError(reason) from exc
    except URLError as exc:
        raise RuntimeError(f'无法连接统计服务：{exc.reason}') from exc
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as exc:
        raise RuntimeError('统计服务返回的不是 JSON') from exc
    if not isinstance(payload, dict):
        raise RuntimeError('统计服务返回格式错误')
    if payload.get('ok') is False:
        raise RuntimeError(str(payload.get('detail') or '统计服务返回失败'))
    return payload


def _number(value) -> str:
    try:
        return f'{int(value or 0):,}'
    except (TypeError, ValueError):
        return '0'


def format_report(data: dict, url: str = '') -> str:
    by_version = data.get('byVersion') or {}
    lines = [
        'KPL 赛训工作台 · 匿名使用统计',
        '=' * 34,
        f'统计地址：{url or "—"}',
        f'生成时间：{data.get("generatedAt") or "—"}',
        f'最近心跳：{data.get("lastPingAt") or "—"}',
        '',
        f'累计安装：{_number(data.get("totalInstalls"))}',
        f'24 小时活跃：{_number(data.get("active24h"))}',
        f'7 天活跃：{_number(data.get("active7d"))}',
        f'30 天活跃：{_number(data.get("active30d"))}',
        f'近 7 天新增：{_number(data.get("newLast7d"))}',
        '',
        '版本分布（近 30 天活跃）：',
    ]
    if not by_version:
        lines.append('  暂无数据')
    else:
        items = sorted(by_version.items(), key=lambda item: (-int(item[1]), str(item[0])))
        for version, count in items:
            lines.append(f'  {version:<12}{_number(count)} 台')
    return '\n'.join(lines)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='查询 KPL 赛训工作台匿名使用统计')
    parser.add_argument('--url', default=os.environ.get('STATS_URL', ''),
                        help='统计服务地址（默认读 STATS_URL）')
    parser.add_argument('--token', default=os.environ.get('STATS_TOKEN', ''),
                        help='访问令牌（默认读 STATS_TOKEN）')
    parser.add_argument('--json', action='store_true', help='输出原始 JSON')
    parser.add_argument('--timeout', type=float, default=TIMEOUT_SECONDS,
                        help=f'请求超时秒数（默认 {TIMEOUT_SECONDS:g}）')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not str(args.url or '').strip():
        print('错误：缺少 --url（或环境变量 STATS_URL）', file=sys.stderr)
        return 1
    if not str(args.token or '').strip():
        print('错误：缺少 --token（或环境变量 STATS_TOKEN）', file=sys.stderr)
        return 1
    try:
        url = summary_url(args.url)
        data = fetch_summary(url, str(args.token).strip(), args.timeout)
    except (ValueError, RuntimeError) as exc:
        print(f'查询失败：{exc}', file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(format_report(data, url))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
