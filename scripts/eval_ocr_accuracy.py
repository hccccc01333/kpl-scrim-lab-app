"""漂流网咖结算截图 OCR 准确率评测。

用法：
    python -I scripts/eval_ocr_accuracy.py --engine rapid
    python -I scripts/eval_ocr_accuracy.py --engine hybrid
    python -I scripts/eval_ocr_accuracy.py --engine both --json report.json

对 ``scripts/ocr_eval_piaoliu.json`` 里人工标注的 7 张截图逐页跑
:func:`postgame_ocr.recognize`，按字段统计数值准确率并列出全部错漏。
截图取自 ``data/training.sqlite3``（postgame_images / images 表）。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from postgame_ocr import merge_pages, recognize  # noqa: E402

DB = ROOT / 'data' / 'training.sqlite3'
GT = Path(__file__).resolve().parent / 'ocr_eval_piaoliu.json'
FIELDS = ('damageDealt', 'damageTaken', 'gold', 'participation', 'damageConversion',
          'takenPerDeath', 'jungleGold', 'cs', 'kills', 'deaths', 'assists',
          'control', 'healing', 'towerDamage')


def load_images(variant_dir: str | None = None) -> dict:
    """截图来源：默认取库内原图；给 --dir 时按文件名前 8 位映射页面。

    变体文件名形如 ``f8f32cb7__q70.jpg``（模拟微信压缩）或
    ``f8f32cb7__w2400.png``（模拟 1080p 手机截图）。
    """
    out = {}
    if variant_dir:
        for path in Path(variant_dir).iterdir():
            stem = path.stem.split('__')[0]
            if stem and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
                out[stem] = path.read_bytes()
        return out
    with sqlite3.connect(DB) as conn:
        rows = conn.execute('SELECT pi.id, i.data FROM postgame_images pi JOIN images i ON i.id=pi.id').fetchall()
    for image_id, data in rows:
        out[image_id[:8]] = data
    return out


def close(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) <= 1e-6
    except (TypeError, ValueError):
        return False


def edit_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a):
        current = [i + 1]
        for j, char_b in enumerate(b):
            current.append(min(previous[j + 1] + 1, current[j] + 1,
                               previous[j] + (char_a != char_b)))
        previous = current
    return previous[-1]


def nickname_grade(read, expected) -> str:
    """教练认领口径：exact=自动认领；offByOne=改一次名回灌存档；far=人工核对。"""
    read, expected = str(read or '').strip(), str(expected or '').strip()
    if not read:
        return 'missing'
    if read == expected:
        return 'exact'
    return 'offByOne' if edit_distance(read, expected) <= 1 else 'far'


def evaluate(engine: str, images: dict, truth: dict, on_stage=None) -> dict:
    per_field = defaultdict(lambda: [0, 0])   # field -> [correct, total]
    problems = []
    nick_grades = defaultdict(int)
    nick_examples = defaultdict(list)
    for prefix, page in truth['pages'].items():
        data = images.get(prefix)
        if not data:
            print(f'!! 找不到截图 {prefix}')
            continue
        name = f"eval-{page['page']}"
        result = recognize(data, name=name, engine=engine, on_stage=on_stage)
        players = result.get('players') or []
        by_pos = {(p.get('side'), p.get('slot')): p for p in players}
        fields = page['fields']
        for side in ('left', 'right'):
            for slot, gt in enumerate(page['players'][side]):
                values = list(gt['values'])
                if len(values) < len(fields) and gt.get('gold') is not None:
                    values.append(gt['gold'])
                player = by_pos.get((side, slot))
                if player is None:
                    problems.append({'page': prefix, 'side': side, 'slot': slot,
                                     'field': '*', 'expected': gt['values'], 'got': None, 'why': '整行缺失'})
                    for fi, field in enumerate(fields):
                        per_field[field][1] += 1
                    continue
                got_fields = player.get('fields') or {}
                for fi, field in enumerate(fields):
                    expected = values[fi] if fi < len(values) else None
                    per_field[field][1] += 1
                    entry = got_fields.get(field)
                    got = entry.get('value') if isinstance(entry, dict) else entry
                    if got is not None and close(got, expected):
                        per_field[field][0] += 1
                    else:
                        problems.append({'page': prefix, 'side': side, 'slot': slot,
                                         'field': field, 'expected': expected, 'got': got,
                                         'raw': entry.get('raw') if isinstance(entry, dict) else None})
                nick = page.get('nicknames', {}).get(side, [None] * 5)[slot]
                if nick:
                    grade = nickname_grade((player.get('nickname') or {}).get('value'), nick)
                    nick_grades[grade] += 1
                    if grade != 'exact':
                        nick_examples[grade].append(
                            f"{side}{slot} {nick} -> {(player.get('nickname') or {}).get('value')!r}")
    total = sum(v[1] for v in per_field.values())
    correct = sum(v[0] for v in per_field.values())
    return {'engine': engine, 'total': total, 'correct': correct,
            'accuracy': round(correct / max(total, 1), 4),
            'perField': {k: {'correct': v[0], 'total': v[1],
                             'acc': round(v[0] / max(v[1], 1), 4)}
                         for k, v in sorted(per_field.items())},
            'nickname': {'grades': dict(nick_grades),
                         'examples': {k: v[:6] for k, v in nick_examples.items()}},
            'problems': problems}


def evaluate_bundle(engine: str, images: dict, truth: dict, on_stage=None) -> dict:
    """捆绑级评测：7 页 merge_pages 成一局后再比对，这才是生产口径。

    合并后 gold 取战绩页的全精度真值（数据页/发育页的 8.7k 是低精度显示）。
    """
    per_field = defaultdict(lambda: [0, 0])
    problems = []
    results = []
    for prefix, page in truth['pages'].items():
        data = images.get(prefix)
        if not data:
            print(f'!! 找不到截图 {prefix}')
            continue
        results.append(recognize(data, name=f"eval-{page['page']}", engine=engine, on_stage=on_stage))
    bundles = merge_pages(results)
    if len(bundles) != 1:
        return {'engine': f'{engine}(bundle)', 'total': 0, 'correct': 0, 'accuracy': 0,
                'perField': {}, 'nickname': {'grades': {}, 'examples': {}},
                'problems': [{'page': '*', 'field': '*',
                              'expected': '1 个捆绑', 'got': f'{len(bundles)} 个捆绑'}]}
    bundle = bundles[0]
    score_gold = {}
    for page in truth['pages'].values():
        if page['page'] != 'score':
            continue
        for side in ('left', 'right'):
            for slot, gt in enumerate(page['players'][side]):
                values = list(gt['values'])
                if gt.get('gold') is not None:
                    values.append(gt['gold'])
                score_gold[(side, slot)] = dict(zip(page['fields'], values))
    by_pos = {(p.get('side'), p.get('slot')): p for p in bundle.get('players') or []}
    for prefix, page in truth['pages'].items():
        for side in ('left', 'right'):
            for slot, gt in enumerate(page['players'][side]):
                player = by_pos.get((side, slot))
                if player is None:
                    for field in page['fields']:
                        per_field[field][1] += 1
                        problems.append({'page': prefix, 'side': side, 'slot': slot,
                                         'field': field, 'expected': '*', 'got': None,
                                         'why': '捆绑中整行缺失'})
                    continue
                got_fields = player.get('fields') or {}
                for fi, field in enumerate(page['fields']):
                    values = list(gt['values'])
                    if len(values) < len(page['fields']) and gt.get('gold') is not None:
                        values.append(gt['gold'])
                    expected = values[fi] if fi < len(values) else None
                    exact = score_gold.get((side, slot))
                    if exact and exact.get(field) is not None:
                        expected = exact[field]
                    per_field[field][1] += 1
                    entry = got_fields.get(field)
                    got = entry.get('value') if isinstance(entry, dict) else entry
                    if got is not None and close(got, expected):
                        per_field[field][0] += 1
                    else:
                        problems.append({'page': prefix, 'side': side, 'slot': slot,
                                         'field': field, 'expected': expected, 'got': got,
                                         'raw': entry.get('raw') if isinstance(entry, dict) else None})
    total = sum(v[1] for v in per_field.values())
    correct = sum(v[0] for v in per_field.values())
    return {'engine': f'{engine}(bundle)', 'total': total, 'correct': correct,
            'accuracy': round(correct / max(total, 1), 4),
            'perField': {k: {'correct': v[0], 'total': v[1],
                             'acc': round(v[0] / max(v[1], 1), 4)}
                         for k, v in sorted(per_field.items())},
            'nickname': {'correct': 0, 'total': 0},
            'problems': problems}


def make_variants(out_dir: Path) -> None:
    """从库内原图生成 6 组压力变体（模拟微信压缩与低分辨率手机截图）。"""
    import io

    from PIL import Image

    with sqlite3.connect(DB) as conn:
        rows = conn.execute(
            'SELECT pi.id, i.data FROM postgame_images pi JOIN images i ON i.id=pi.id').fetchall()
    tags = ('q85', 'q70', 'q55', 'w2400', 'w1920', 'w2400q70')
    for tag in tags:
        (out_dir / tag).mkdir(parents=True, exist_ok=True)
    for image_id, data in rows:
        prefix = image_id[:8]
        image = Image.open(io.BytesIO(data)).convert('RGB')
        for quality in (85, 70, 55):
            buf = io.BytesIO()
            image.save(buf, 'JPEG', quality=quality)
            (out_dir / f'q{quality}' / f'{prefix}__q{quality}.jpg').write_bytes(buf.getvalue())
        for width in (2400, 1920):
            smaller = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
            smaller.save(out_dir / f'w{width}' / f'{prefix}__w{width}.png')
            if width == 2400:
                buf = io.BytesIO()
                smaller.save(buf, 'JPEG', quality=70)
                (out_dir / 'w2400q70' / f'{prefix}__w2400q70.jpg').write_bytes(buf.getvalue())
    print(f'变体已生成到 {out_dir}：' + '、'.join(tags))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--engine', default='rapid', choices=['rapid', 'hybrid', 'mimo', 'both'])
    parser.add_argument('--dir', help='从这个目录加载变体截图（文件名前 8 位 = 页面 id 前缀）')
    parser.add_argument('--bundle', action='store_true', help='捆绑级评测（7 页合并成一局，生产口径）')
    parser.add_argument('--make-variants', help='生成 6 组压力变体到该目录后退出')
    parser.add_argument('--json', help='把完整报告写到这个文件')
    args = parser.parse_args()
    if args.make_variants:
        make_variants(Path(args.make_variants))
        return
    images = load_images(args.dir)
    truth = json.loads(GT.read_text(encoding='utf-8'))
    engines = ['rapid', 'hybrid'] if args.engine == 'both' else [args.engine]
    reports = []
    for engine in engines:
        print(f'=== 引擎 {engine} ===')
        evaluate_fn = evaluate_bundle if args.bundle else evaluate
        report = evaluate_fn(engine, images, truth)
        reports.append(report)
        print(f"数值字段: {report['correct']}/{report['total']} = {report['accuracy']:.2%}")
        grades = report['nickname'].get('grades') or {}
        print(f"昵称认领口径: 自动认领 {grades.get('exact', 0)} / 一字之差 {grades.get('offByOne', 0)}"
              f" / 人工核对 {grades.get('far', 0)} / 漏读 {grades.get('missing', 0)}")
        for field, stats in report['perField'].items():
            flag = '' if stats['acc'] >= .99 else '  ← 低'
            print(f"  {field:<18} {stats['correct']}/{stats['total']} = {stats['acc']:.2%}{flag}")
        if report['problems']:
            print(f'错漏 {len(report["problems"])} 处:')
            for p in report['problems']:
                print(f"  [{p['page']} {p['side']}{p['slot']}] {p['field']}: 期望 {p['expected']}"
                      f" / 实得 {p.get('got')!r}" + (f" (raw={p.get('raw')!r})" if p.get('raw') else ''))
    if args.json:
        Path(args.json).write_text(json.dumps(reports, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'报告已写入 {args.json}')


if __name__ == '__main__':
    main()
