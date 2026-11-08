"""把官网从 website/src 模板渲染成纯静态站（website/dist）。

数据源只有一个真相：
* 版本 / 发布日期 / 发布名  -> version.py
* 更新日志                -> CHANGELOG.md（默认不渲染「未发布」段）
* 功能截图                -> docs/images/*.png（原样拷贝进 dist/assets/img）

用法：
    python scripts/build_website.py                     # 只构建
    python scripts/build_website.py --serve             # 构建并在本机预览
    python scripts/build_website.py --download-url URL  # 覆盖下载按钮指向
    python scripts/build_website.py --include-unreleased

纯标准库，无第三方依赖；GitHub Actions 直接跑这个脚本即可部署。
"""
from __future__ import annotations

import argparse
import html
import re
import shutil
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'website' / 'src'
DIST = ROOT / 'website' / 'dist'
REPO_URL = 'https://github.com/hccccc01333/kpl-scrim-lab'
DEFAULT_DOWNLOAD_URL = f'{REPO_URL}/releases/latest'


def read_version() -> tuple[str, str, str]:
    text = (ROOT / 'version.py').read_text(encoding='utf-8')

    def grab(name: str, default: str = '') -> str:
        m = re.search(rf"{name}\s*=\s*['\"]([^'\"]*)['\"]", text)
        return m.group(1) if m else default

    return grab('VERSION'), grab('RELEASE_DATE'), grab('RELEASE_NAME')


def inline_md(text: str) -> str:
    """CHANGELOG 行内标记的极简子集：**加粗** 与 `代码`。"""
    text = html.escape(text)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text


def parse_changelog() -> list[dict]:
    """解析顶层版本段 -> [{version, date, blocks:[(小节, [条目])]}]，保持文件顺序（新在上）。"""
    sections: list[dict] = []
    cur: dict | None = None
    sub: str | None = None
    for raw in (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8').splitlines():
        line = raw.rstrip()
        m = re.match(r'^##\s+\[(.+?)\]\s*(?:-\s*(\d{4}-\d{2}-\d{2}))?\s*$', line)
        if m:
            cur = {'version': m.group(1).strip(), 'date': m.group(2) or '', 'blocks': []}
            sections.append(cur)
            sub = None
            continue
        if cur is None:
            continue
        if line.startswith('### '):
            sub = line[4:].strip()
            continue
        if line.startswith('- '):
            item = inline_md(line[2:].strip())
            if cur['blocks'] and cur['blocks'][-1][0] == sub:
                cur['blocks'][-1][1].append(item)
            else:
                cur['blocks'].append([sub, [item]])
            continue
    return sections


def render_sections(sections: list[dict], version: str, release_name: str,
                    include_unreleased: bool) -> str:
    out = []
    for s in sections:
        unreleased = s['version'] == '未发布'
        if unreleased and not include_unreleased:
            continue
        ver = html.escape(s['version'])
        head = [f'<h2>v{ver}</h2>']
        if s['date']:
            head.append(f"<span class='cl-date'>{s['date']}</span>")
        if s['version'] == version and release_name:
            head.append(f"<span class='cl-tag'>{html.escape(release_name)}</span>")
        elif unreleased:
            head.append("<span class='cl-tag'>开发中</span>")
        body = [f"<section class='cl-version'><div class='cl-head'>{''.join(head)}</div>"]
        open_ul = False
        cur_sub: str | None = None
        for sub, items in s['blocks']:
            if sub != cur_sub:
                if open_ul:
                    body.append('</ul>')
                if sub:
                    body.append(f'<h3>{inline_md(sub)}</h3>')
                body.append('<ul>')
                open_ul, cur_sub = True, sub
            body.extend(f'<li>{item}</li>' for item in items)
        if open_ul:
            body.append('</ul>')
        body.append('</section>')
        out.append('\n'.join(body))
    return '\n'.join(out)


def build(download_url: str, include_unreleased: bool) -> None:
    version, release_date, release_name = read_version()
    tokens = {
        'VERSION': version,
        'RELEASE_DATE': release_date,
        'YEAR': release_date[:4] or '2026',
        'DOWNLOAD_URL': download_url,
    }
    sections = parse_changelog()
    changelog_html = render_sections(sections, version, release_name, include_unreleased)

    # 只覆盖、不清空：本机预览服务可能正占用 dist（Windows 下 rmtree 会失败），
    # 产物文件名固定，覆盖写入不会留下旧文件。
    (DIST / 'assets' / 'img').mkdir(parents=True, exist_ok=True)

    for name in ('index.html', 'changelog.html', 'guide.html'):
        page = (SRC / name).read_text(encoding='utf-8')
        for key, value in tokens.items():
            page = page.replace('{{' + key + '}}', value)
        page = page.replace('{{CHANGELOG_SECTIONS}}', changelog_html)
        (DIST / name).write_text(page, encoding='utf-8')

    shutil.copyfile(SRC / 'style.css', DIST / 'assets' / 'style.css')
    images = ROOT / 'docs' / 'images'
    if images.is_dir():
        for img in images.glob('*.png'):
            shutil.copyfile(img, DIST / 'assets' / 'img' / img.name)

    print(f'构建完成: {DIST}')
    print(f'版本: v{version} ({release_date}) · 渲染了 {len(sections)} 个版本段')


def serve(port: int) -> None:
    handler = SimpleHTTPRequestHandler
    handler.directory = str(DIST)
    url = f'http://127.0.0.1:{port}/'
    print(f'预览: {url}  (Ctrl+C 退出)')
    webbrowser.open(url)
    HTTPServer(('127.0.0.1', port), handler).serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--download-url', default=DEFAULT_DOWNLOAD_URL,
                    help=f'下载按钮指向（默认 GitHub Releases：{DEFAULT_DOWNLOAD_URL}）')
    ap.add_argument('--include-unreleased', action='store_true',
                    help='在更新日志页渲染「未发布」段落（默认隐藏）')
    ap.add_argument('--serve', nargs='?', const=8137, type=int, metavar='PORT',
                    help='构建后启动本地预览服务（默认端口 8137）')
    args = ap.parse_args()
    build(args.download_url, args.include_unreleased)
    if args.serve:
        serve(args.serve)


if __name__ == '__main__':
    main()
