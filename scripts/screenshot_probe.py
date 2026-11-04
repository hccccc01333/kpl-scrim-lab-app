"""Read-only screenshot field audit using the existing local OCR.

Run on real post-game score/data screenshots to see which fixed fields are
readable, which are missing, and which visible text is not yet a field.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ocr import recognize
from screenshot_fields import flatten_recognition, render_summary


def probe(path, tokens=False):
    result = recognize(path.read_bytes())
    flat = flatten_recognition(result, path.name)
    if tokens:
        flat['tokens'] = result.get('tokens') or []
    return flat


def main():
    parser = argparse.ArgumentParser(description='审计赛后截图的固定字段覆盖（只读，不写数据库）。')
    parser.add_argument('images', nargs='+', help='赛后战绩页/数据页截图')
    parser.add_argument('--json', action='store_true', help='输出 JSON 而不是摘要')
    parser.add_argument('--out', help='同时保存 JSON 到该文件')
    parser.add_argument('--tokens', action='store_true', help='附带全部 OCR token 和坐标')
    args = parser.parse_args()

    images = []
    for value in args.images:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            print(f'找不到截图：{path}', file=sys.stderr)
            return 2
        images.append(path)

    report = {'schema': 'kpl-screenshot-probe-v1', 'images': []}
    try:
        for path in images:
            flat = probe(path, args.tokens)
            report['images'].append(flat)
            if not args.json:
                print(render_summary(flat))
                print()
    except ImportError:
        print('本地 OCR 组件未安装，请运行 安装依赖.bat', file=sys.stderr)
        return 2
    except Exception as error:
        print(f'识别失败：{type(error).__name__}: {error}', file=sys.stderr)
        return 2

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'报告：{out}')
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
