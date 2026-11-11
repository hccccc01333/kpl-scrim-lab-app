"""给前端改版拍对照图。

用法：
    python scripts/shot.py --out .screenshots/before --page "#depth/time_economy"
    python scripts/shot.py --out .screenshots/after --all

只读本地已启动的工作台（默认 http://127.0.0.1:8766），不改数据。
输出整页 PNG，文件名由路由生成，便于改版前后逐张对照。
"""
import argparse
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]

PAGES = {
    'home': '#home',
    'team': '#team',
    'players': '#players',
    'bp': '#bp',
    'compare': '#compare/player',
    'analysis-economy': '#depth/time_economy',
    'analysis-tempo': '#topics/tempo',
    'analysis-kill': '#depth/time_kill_rhythm',
    'datasets': '#datasets',
    'identity': '#identity',
}

READY = """() => {
  const main = document.querySelector('#content');
  const t = (main ? main.innerText : '').trim();
  if (/^(正在读取|正在打开|正在获取|加载中|正在加载|loading)/i.test(t)) return false;
  return t.length >= 40;
}"""


def shot(page, base, route, out, name, viewport):
    page.set_viewport_size(viewport)
    page.goto(base + '/' + route, wait_until='domcontentloaded')
    try:
        page.wait_for_function(READY, timeout=15000)
    except Exception:
        page.wait_for_timeout(2500)
    page.wait_for_timeout(600)  # 让字体与图表稳定
    target = out / f'{name}.png'
    page.screenshot(path=str(target), full_page=True)
    print(f'{name:24} {page.url.split("#")[-1]:28} -> {target.name}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', default='http://127.0.0.1:8766')
    ap.add_argument('--out', default='.screenshots/ui')
    ap.add_argument('--page', action='append', default=[])
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--width', type=int, default=1440)
    ap.add_argument('--height', type=int, default=900)
    args = ap.parse_args()

    out = (ROOT / args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    viewport = {'width': args.width, 'height': args.height}

    targets = []
    if args.all:
        targets = list(PAGES.items())
    for raw in args.page:
        route = raw if raw.startswith('#') else '#' + raw
        name = re.sub(r'[^a-z0-9]+', '-', route.strip('#').lower()).strip('-') or 'page'
        targets.append((name, route))

    if not targets:
        ap.error('给 --page "#route" 或 --all')

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=viewport)
        # 教程遮罩会盖住首屏，截图前先标记「已看完」，否则每张图都拍到弹窗。
        page.add_init_script(
            "try{localStorage.setItem('training-tour-complete-v3','1');}catch(e){}")
        for name, route in targets:
            try:
                shot(page, args.base, route, out, name, viewport)
            except Exception as exc:
                print(f'{name:24} 失败: {exc}')
        browser.close()


if __name__ == '__main__':
    main()
