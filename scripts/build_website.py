"""把官网从 website/src 模板渲染成纯静态站（website/dist）。

数据源只有一个真相：
* 版本 / 发布日期 / 发布名  -> version.py
* 更新日志                -> CHANGELOG.md（默认不渲染「未发布」段）
* 功能截图                -> docs/images/*.png（原样拷贝进 dist/assets/img）
* 自托管字体等静态资源     -> website/src/assets/*（拷贝进 dist/assets）

用法：
    python scripts/build_website.py                     # 只构建
    python scripts/build_website.py --serve             # 构建并在本机预览
    python scripts/build_website.py --site-url URL      # 站点根地址（canonical / sitemap）
    python scripts/build_website.py --download-url URL  # 覆盖安装版下载直链
    python scripts/build_website.py --full-download-url URL  # 覆盖免安装版下载直链
    python scripts/build_website.py --include-unreleased

默认下载走 Gitee Releases（国内直连），GitHub 作为海外备用。

纯标准库，无第三方依赖；GitHub Actions 直接跑这个脚本即可部署。
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import shutil
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'website' / 'src'
DIST = ROOT / 'website' / 'dist'
REPO_URL = 'https://github.com/hccccc01333/kpl-scrim-lab-app'
GITEE_REPO_URL = 'https://gitee.com/Rainfun42/kpl-scrim-lab-app'
DEFAULT_SITE_URL = 'https://hccccc01333.github.io/kpl-scrim-lab-site'
SPONSOR_URL = 'https://afdian.com/a/kplscrim'
PAGES = ('index.html', 'download.html', 'changelog.html', 'guide.html', '404.html')


def read_version() -> tuple[str, str, str]:
    text = (ROOT / 'version.py').read_text(encoding='utf-8')

    def grab(name: str, default: str = '') -> str:
        m = re.search(rf"{name}\s*=\s*['\"]([^'\"]*)['\"]", text)
        return m.group(1) if m else default

    return grab('VERSION'), grab('RELEASE_DATE'), grab('RELEASE_NAME')


def asset_version() -> str:
    """资源和样式的内容指纹：改 CSS / 换截图都会换 URL，绕开 Pages 缓存。"""
    digest = hashlib.sha1()
    files = [SRC / 'style.css']
    assets = SRC / 'assets'
    if assets.is_dir():
        files.extend(sorted(p for p in assets.rglob('*') if p.is_file()))
    for path in files:
        digest.update(str(path.relative_to(SRC)).encode('utf-8'))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


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


def render_latest_notes(sections: list[dict], version: str,
                        release_name: str, limit: int = 4) -> str:
    """首页的「最新更新」卡片：取最近一个已发布版本的前几条。"""
    for section in sections:
        if section['version'] == '未发布':
            continue
        items = [item for _, group in section['blocks'] for item in group]
        if not items:
            continue
        bullets = ''.join(f'<li>{item}</li>' for item in items[:limit])
        meta = []
        if section['version'] == version and release_name:
            meta.append(f'<span class="tag">{html.escape(release_name)}</span>')
        if section['date']:
            meta.append(f'<span class="date">{section["date"]}</span>')
        return ('<div class="cl-item"><div class="cl-top">'
                f'<span class="ver">v{html.escape(section["version"])}</span>'
                f'{"".join(meta)}</div><ul>{bullets}</ul></div>')
    return '<div class="cl-item"><p>暂无更新记录。</p></div>'


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


def release_asset_url(version: str, filename: str) -> str:
    return f'{GITEE_REPO_URL}/releases/download/v{version}/{filename}'


def build(download_url: str | None, full_download_url: str | None,
          site_url: str, include_unreleased: bool) -> None:
    version, release_date, release_name = read_version()
    sections = parse_changelog()
    site_url = site_url.rstrip('/')
    setup_url = download_url or release_asset_url(
        version, f'KPL-Scrim-Lab-{version}-setup.exe')
    portable_url = full_download_url or release_asset_url(
        version, f'KPL-Scrim-Lab-{version}-full.zip')
    tokens = {
        'VERSION': version,
        'RELEASE_DATE': release_date,
        'YEAR': release_date[:4] or '2026',
        'DOWNLOAD_URL': setup_url,
        'FULL_DOWNLOAD_URL': portable_url,
        'GITHUB_DOWNLOAD_URL': f'{REPO_URL}/releases/latest',
        'RELEASE_PAGE_URL': f'{GITEE_REPO_URL}/releases/tag/v{version}',
        'SITE_URL': site_url,
        'REPO_URL': REPO_URL,
        'LICENSE_URL': f'{REPO_URL}/blob/main/LICENSE',
        'LATEST_NOTES': render_latest_notes(sections, version, release_name),
        'ASSET_VERSION': asset_version(),
        'SPONSOR_URL': SPONSOR_URL,
    }
    changelog_html = render_sections(sections, version, release_name, include_unreleased)

    # 只覆盖、不清空：本机预览服务可能正占用 dist（Windows 下 rmtree 会失败），
    # 产物文件名固定，覆盖写入不会留下旧文件。
    (DIST / 'assets' / 'img').mkdir(parents=True, exist_ok=True)

    for name in PAGES:
        page = (SRC / name).read_text(encoding='utf-8')
        for key, value in tokens.items():
            page = page.replace('{{' + key + '}}', value)
        page = page.replace('{{CHANGELOG_SECTIONS}}', changelog_html)
        (DIST / name).write_text(page, encoding='utf-8')

    shutil.copyfile(SRC / 'style.css', DIST / 'assets' / 'style.css')
    # SEO 文件（robots / sitemap）放在站点根目录，域名同样走 {{SITE_URL}}
    for name in ('robots.txt', 'sitemap.xml'):
        f = SRC / name
        if f.is_file():
            text = f.read_text(encoding='utf-8')
            for key, value in tokens.items():
                text = text.replace('{{' + key + '}}', value)
            (DIST / name).write_text(text, encoding='utf-8')
    # 自托管字体等静态资源（manrope.woff2 及其许可证），无外部请求
    src_assets = SRC / 'assets'
    if src_assets.is_dir():
        for f in src_assets.iterdir():
            if f.is_file():
                shutil.copyfile(f, DIST / 'assets' / f.name)
    # 官网截图只从 website/src/assets/img 发布（均为合成演示数据）；
    # 不再拷贝 docs/images，避免未脱敏截图或未使用资产进入线上。
    img_src = src_assets / 'img'
    img_dst = DIST / 'assets' / 'img'
    img_dst.mkdir(parents=True, exist_ok=True)
    if img_src.is_dir():
        wanted = {f.name for f in img_src.iterdir() if f.is_file()}
        for name in wanted:
            shutil.copyfile(img_src / name, img_dst / name)
        for old in img_dst.iterdir():
            if old.is_file() and old.name not in wanted:
                old.unlink()

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
    ap.add_argument('--download-url', default=None,
                    help='安装版下载直链（默认按版本拼 Gitee Releases）')
    ap.add_argument('--full-download-url', default=None,
                    help='免安装版下载直链（默认按版本拼 Gitee Releases）')
    ap.add_argument('--site-url', default=DEFAULT_SITE_URL,
                    help=f'站点根地址，用于 canonical / sitemap（默认 {DEFAULT_SITE_URL}）')
    ap.add_argument('--include-unreleased', action='store_true',
                    help='在更新日志页渲染「未发布」段落（默认隐藏）')
    ap.add_argument('--serve', nargs='?', const=8137, type=int, metavar='PORT',
                    help='构建后启动本地预览服务（默认端口 8137）')
    args = ap.parse_args()
    build(args.download_url, args.full_download_url, args.site_url,
          args.include_unreleased)
    if args.serve:
        serve(args.serve)


if __name__ == '__main__':
    main()
