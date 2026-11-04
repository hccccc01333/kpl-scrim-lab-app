"""用手机视口截取一个页面，用于人工查看营地分享链在浏览器里长什么样。

    python tools/camp_page_shot.py "<url>" test-results/camp-page.png

只打开页面并截图，不登录、不点击分享按钮。
"""
import sys
from playwright.sync_api import sync_playwright

UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
      'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
      'Mobile/15E148 Safari/604.1')


def main():
    if len(sys.argv) < 2:
        raise SystemExit('用法：camp_page_shot.py <url> [out.png] [wait_ms]')
    url = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else 'test-results/camp-page.png'
    wait_ms = int(sys.argv[3]) if len(sys.argv) > 3 else 6000
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={'width': 414, 'height': 896},
            device_scale_factor=2, is_mobile=True, has_touch=True,
            user_agent=UA)
        page = context.new_page()
        notes = []
        page.on('console', lambda m: notes.append(f'console[{m.type}] {m.text[:160]}'))
        page.on('requestfailed',
                lambda r: notes.append(f'failed {r.url[:110]} :: {str(r.failure)[:80]}'))
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
        except Exception as error:
            print('goto failed:', type(error).__name__, str(error)[:200])
        page.wait_for_timeout(wait_ms)
        page.screenshot(path=out, full_page=True)
        print('final_url:', page.url[:300])
        print('title:', page.title())
        try:
            html = page.content()
        except Exception:
            html = ''
        print('html_len:', len(html), 'frames:', len(page.frames))
        try:
            text = page.inner_text('body')
        except Exception:
            text = ''
        print('body_text:', ' | '.join(line for line in text.splitlines() if line.strip())[:700])
        for note in notes[:15]:
            print('  ', note)
        print('saved:', out)
        browser.close()


if __name__ == '__main__':
    main()
