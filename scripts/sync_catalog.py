"""Download public official names and icon references; never uploads screenshots."""
import concurrent.futures
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import urllib.request
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'resources'
ICONS = CATALOG / 'icons'


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'TrainingRoom/0.2'})
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read()


def main():
    ICONS.mkdir(parents=True, exist_ok=True)
    heroes_url = 'https://pvp.qq.com/web201605/js/herolist.json'
    equipment_url = 'https://pvp.qq.com/web201605/js/item.json'
    heroes, equipment = json.loads(get(heroes_url)), json.loads(get(equipment_url))
    entries = []
    for h in heroes:
        entries.append({'id': f'hero-{h["ename"]}', 'kind': 'hero', 'name': h['cname'],
                        'url': f'https://game.gtimg.cn/images/yxzj/img201606/heroimg/{h["ename"]}/{h["ename"]}.jpg'})
    for e in equipment:
        entries.append({'id': f'equipment-{e["item_id"]}', 'kind': 'equipment', 'name': e['item_name'],
                        'url': f'https://game.gtimg.cn/images/yxzj/img201606/itemimg/{e["item_id"]}.jpg'})

    def download(entry):
        path = ICONS / f'{entry["id"]}.png'
        try:
            if not path.exists():
                im = Image.open(io.BytesIO(get(entry['url']))).convert('RGB')
                im.save(path, format='PNG')
            entry['icon'] = '/catalog/icons/' + path.name
            entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
            if entry['kind'] == 'equipment':
                variant_path = ICONS / f'{entry["id"]}-esports.png'
                variant_url = f'https://res.edata.qq.com/sgame/static/images/equipment/{entry["id"].split("-")[1]}.jpg'
                try:
                    if not variant_path.exists():
                        Image.open(io.BytesIO(get(variant_url))).convert('RGB').save(variant_path, format='PNG')
                    entry['variants'] = [entry['icon'], '/catalog/icons/'+variant_path.name]
                    entry['variantSources'] = [variant_url]
                except Exception:
                    pass
        except Exception as error:
            entry['icon'] = None
            entry['error'] = type(error).__name__
        return entry

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        entries = list(pool.map(download, entries))
    result = {'updatedAt': datetime.now(timezone.utc).isoformat(), 'sources': [heroes_url, equipment_url],
              'notice': '英雄与装备名称、图标来自王者荣耀官方公开资源，权利归原权利人；仅作为本地识别参照。默认头像不覆盖所有皮肤。',
              'entries': entries}
    (CATALOG / 'catalog.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'entries': len(entries), 'icons': sum(bool(e['icon']) for e in entries),
                      'failed': [e['id'] for e in entries if not e['icon']]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
