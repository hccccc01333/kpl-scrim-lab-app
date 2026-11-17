"""刷新 website/github.json —— 构建只读缓存，运行时不请求 GitHub。

用法：
    python scripts/sync_github.py      # 联网拉一次仓库信息，写进缓存
    python scripts/build_website.py    # 构建时只读缓存，不联网

没有网络时会保留旧缓存；删掉缓存文件则页面自动隐藏星标，不显示假数字。
"""
from __future__ import annotations

import datetime
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'website' / 'github.json'
API = 'https://api.github.com/repos/hccccc01333/kpl-scrim-lab-app'


def main() -> int:
    req = urllib.request.Request(API, headers={'User-Agent': 'kpl-scrim-lab-site'})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as exc:  # noqa: BLE001 - 只提示，不覆盖旧缓存
        print(f'拉取失败，保留旧缓存：{exc}')
        return 1

    payload = {
        'user': data['owner']['login'],
        'repo': data['name'],
        'stars': data['stargazers_count'],
        'language': data.get('language') or '',
        'pushed': (data.get('pushed_at') or '')[:10],
        'fetched': datetime.date.today().isoformat(),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'已更新 {OUT.relative_to(ROOT)}：★ {payload["stars"]}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
