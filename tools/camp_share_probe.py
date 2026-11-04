#!/usr/bin/env python3
"""王者营地分享链接诊断：这条链接到底能不能还原成回放参数。

微信里复制出来的营地分享至少有这么几种形态：

    A  https://camp.qq.com/h5/webdist/battle-replay/index.html?gameseq=...
    B  https://servicewechat.com/wxascheme/jump_wxa?url=<编码后的小程序 path>
C  https://wxaurl.cn/xxxx  https://cu.qq.com/xxxx   短链，302 到 B 或 weixin://
D  #小程序://王者营地/xxxx                    纯文本协议链，没有参数
E  gameseq=...&gamesvrentity=...              只贴了半截 query

本工具只做还原：把 A/B/C/E 里的四个参数抠出来，拼回 A；对 D 明确说"取不到"。
不猜参数、不构造缺失值——缺哪个就报哪个。

    python tools/camp_share_probe.py "<粘贴内容>"
    python tools/camp_share_probe.py --file share.txt
    Get-Clipboard | python tools/camp_share_probe.py -

只读。不请求 kohcamp.qq.com，不写任何文件。唯一外部请求是对 wxaurl.cn
短链发一次 HEAD（不跟随跳转），只为取 Location。
"""
from __future__ import annotations

import re
import sys
import urllib.error
import urllib.parse
import urllib.request

WEB_REPLAY = 'https://camp.qq.com/h5/webdist/battle-replay/index.html'

# 规范名 -> 可能的写法（统一小写比较）
KEYS = {
    'gameseq': ('gameseq', 'game_seq', 'gamesvrseq'),
    'gamesvr': ('gamesvrentity', 'gamesvr', 'game_svr', 'gamesvrid'),
    'relaysvr': ('relaysvrentity', 'relaysvr', 'relay_svr', 'relaysvrid'),
    # userId 是营地账号 ID，比游戏 playerId 短；接口不校验它（实测两种都 code=0）
    'playerid': ('playerid', 'player_id', 'userid'),
}

LABEL = {'gameseq': 'gameseq', 'gamesvr': 'gamesvrentity',
         'relaysvr': 'relaysvrentity', 'playerid': 'playerid'}

URL_RE = re.compile(r'https?://[^\s<>"\'）)】\]]+', re.I)
MINI_TEXT_RE = re.compile(r'#小程序://\S+')
BARE_QUERY_RE = re.compile(r'(?:^|[?&])gameseq=', re.I)


def _qs(url_or_query):
    """解析 query，返回小写 key -> 值。容忍 &amp; 和重复 key。"""
    text = url_or_query.split('#', 1)[0]
    raw = text.split('?', 1)[1] if '?' in text else text
    raw = raw.replace('&amp;', '&')
    out = {}
    for key, value in urllib.parse.parse_qsl(raw, keep_blank_values=True):
        out.setdefault(key.strip().lower(), value.strip())
    return out


def _pick(qs):
    found = {}
    for canonical, aliases in KEYS.items():
        for alias in aliases:
            if qs.get(alias):
                found[canonical] = qs[alias]
                break
    return found


def _unquote_deep(value, depth=3):
    for _ in range(depth):
        nxt = urllib.parse.unquote(value)
        if nxt == value:
            break
        value = nxt
    return value


def _classify(url):
    host = urllib.parse.urlsplit(url).netloc.lower()
    if host == 'camp.qq.com' or host.endswith('.camp.qq.com'):
        return 'camp-web'
    if host.endswith('servicewechat.com'):
        return 'wechat-scheme'
    if host.endswith('wxaurl.cn') or host.endswith('w.url.cn'):
        return 'short-url'
    if host == 'cu.qq.com' or host.endswith('.cu.qq.com') or host == 'url.cn':
        return 'short-url'
    return 'other'


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _peek_location(url, timeout=8):
    """取短链的跳转目标，不跟随。返回 (location, 说明)。"""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url, method='HEAD',
        headers={'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.headers.get('Location'), f'HTTP {response.status}'
    except urllib.error.HTTPError as error:
        return error.headers.get('Location'), f'HTTP {error.code}'
    except Exception as error:  # 网络、TLS、超时都当"取不到"
        return None, f'{type(error).__name__}: {error}'


def _expand(url, notes, depth=0):
    """把一个 URL 展开成若干"还能再解析"的片段。"""
    if depth > 3:
        return []
    kind = _classify(url)

    if kind == 'short-url':
        location, detail = _peek_location(url)
        notes.append(f'短链跳转（{detail}）：{location or "没有 Location"}')
        return [location] if location else []

    if kind == 'wechat-scheme':
        qs = _qs(url)
        fragments = []
        for field in ('url', 'path', 'query', 'scheme'):
            value = qs.get(field)
            if not value:
                continue
            inner = _unquote_deep(value)
            notes.append(f'小程序参数 {field}= 解码后：{inner[:200]}')
            fragments.append(inner)
        if not fragments:
            notes.append('这是小程序跳转链，但 url/path 参数是空的。')
        return fragments

    return []


def resolve(text):
    """把一段粘贴内容还原成回放参数。

    返回 dict：params（已找到的四个参数）、missing（缺哪些）、
    kinds（识别到的链接形态）、notes（过程记录）。
    """
    text = str(text or '').strip()
    notes, kinds, params = [], [], {}

    urls = URL_RE.findall(text)
    for url in urls:
        kind = _classify(url)
        if kind not in kinds:
            kinds.append(kind)
        if kind in ('camp-web', 'other'):
            found = _pick(_qs(url))
            if found:
                notes.append(f'{kind} 直接带参数：{sorted(found)}')
            params.update({k: v for k, v in found.items() if k not in params})
        for fragment in _expand(url, notes):
            if fragment.startswith('http'):
                inner_kind = _classify(fragment)
                if inner_kind not in kinds:
                    kinds.append(inner_kind)
                found = _pick(_qs(fragment))
                params.update({k: v for k, v in found.items() if k not in params})
            elif 'gameseq=' in fragment.lower():
                found = _pick(_qs(fragment))
                if found:
                    notes.append(f'小程序 path 内嵌参数：{sorted(found)}')
                    params.update({k: v for k, v in found.items() if k not in params})

    if not params and BARE_QUERY_RE.search(text):
        found = _pick(_qs(text))
        if found:
            kinds.append('bare-query')
            notes.append('按裸 query 解析，未发现完整 URL。')
            params.update(found)

    if not urls and not params and MINI_TEXT_RE.search(text):
        kinds.append('mini-text')
        notes.append('这是 #小程序:// 纯文本协议链，参数不在文本里，'
                     '只能由微信客户端打开，本机取不到 gameseq。')

    missing = [k for k in KEYS if k not in params]
    return {'params': params, 'missing': missing, 'kinds': kinds, 'notes': notes}


def build_url(params):
    query = urllib.parse.urlencode({
        'isNavigationBarHidden': 1,
        'gameseq': params['gameseq'],
        'gamesvrentity': params['gamesvr'],
        'relaysvrentity': params['relaysvr'],
        'playerid': params['playerid'],
    })
    return f'{WEB_REPLAY}?{query}'


def report(result):
    lines = []
    lines.append('链接形态：' + ('、'.join(result['kinds']) or '未识别'))
    if result['params']:
        lines.append('已取到参数：')
        for key, value in result['params'].items():
            lines.append(f'  {LABEL[key]:16} = {value}')
    if result['missing']:
        lines.append('缺少参数：' + '、'.join(LABEL[k] for k in result['missing']))
    if not result['missing']:
        lines.append('')
        lines.append('还原出的网页回放链接：')
        lines.append(build_url(result['params']))
        lines.append('')
        lines.append('这条链接可以直接粘进工作台「王者营地链接」，不需要打开小程序。')
    elif result['kinds'] == ['mini-text']:
        lines.append('')
        lines.append('结论：这条路拿不到参数。要让选手改用页面里的「复制链接」，'
                     '或者从对局详情点「对局回顾」再分享；否则只能抓包。')
    else:
        lines.append('')
        lines.append('结论：信息不全，把完整分享内容（不要截断）再粘一次。')
    if result['notes']:
        lines.append('')
        lines.append('过程：')
        for note in result['notes']:
            lines.append('  - ' + note)
    return '\n'.join(lines)


def _read_input(argv):
    if len(argv) > 1 and argv[1] == '--file':
        if len(argv) < 3:
            raise SystemExit('用法：--file <路径>')
        with open(argv[2], 'r', encoding='utf-8') as handle:
            return handle.read()
    if len(argv) > 1 and argv[1] != '-':
        return ' '.join(argv[1:])
    return sys.stdin.read()


def main(argv):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    text = _read_input(argv)
    if not text.strip():
        raise SystemExit('没有输入。把微信里复制的分享内容作为参数传入，或用 - 从标准输入读。')
    print(report(resolve(text)))


if __name__ == '__main__':
    main(sys.argv)
