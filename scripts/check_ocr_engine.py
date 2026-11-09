"""Check the local OCR stack without touching the database.

Examples:
    python scripts/check_ocr_engine.py
    python scripts/check_ocr_engine.py --load
    python scripts/check_ocr_engine.py --image data/screenshots/samples/05-data.png --max-tokens 64
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import media_tools
import mimo_ocr


def main():
    parser = argparse.ArgumentParser(description='检查本机 Mimo / RapidOCR / ffmpeg 可用性。')
    parser.add_argument('--load', action='store_true', help='加载 Mimo 权重并报告设备/耗时')
    parser.add_argument('--image', help='可选图片；用 Mimo 读一小段文字验证推理')
    parser.add_argument('--max-tokens', type=int, default=64, help='验证推理的最大输出 token')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    args = parser.parse_args()

    status = mimo_ocr.status()
    status['rapidocr'] = _module_available('rapidocr_onnxruntime')
    status['ffmpeg'] = media_tools.ffmpeg() if media_tools.available() else None
    status['ffprobe'] = media_tools.ffprobe() if media_tools.probe_available() else None
    if args.load or args.image:
        try:
            engine = mimo_ocr.get_engine().load()
            status['loaded'] = True
            status['device'] = engine.device
            status['dtype'] = str(engine.dtype).replace('torch.', '')
            status['loadSeconds'] = engine.load_seconds
        except mimo_ocr.MimoUnavailable as error:
            status['error'] = str(error)
            _print(status, args.json)
            return 1
    if args.image:
        image_path = Path(args.image).expanduser().resolve()
        if not image_path.is_file():
            print(f'找不到图片：{image_path}', file=sys.stderr)
            return 2
        from PIL import Image
        image = Image.open(image_path).convert('RGB')
        result = mimo_ocr.get_engine().read(
            image, 'Extract the text in the image.', max_new_tokens=args.max_tokens,
            cache=False)
        status['image'] = str(image_path)
        status['text'] = result['text']
        status['elapsedMs'] = result['elapsedMs']
        status['imageSize'] = list(image.size)
    _print(status, args.json)
    return 0 if status.get('available') and status.get('rapidocr') and status.get('ffmpeg') else 1


def _module_available(name):
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def _print(status, as_json):
    if as_json:
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return
    print('OCR 引擎检查')
    print(f"  Mimo:      {'可用' if status.get('available') else '未找到'}  {status.get('path') or ''}")
    print(f"  RapidOCR:  {'可用' if status.get('rapidocr') else '未安装'}")
    print(f"  ffmpeg:    {status.get('ffmpeg') or '未找到'}")
    print(f"  ffprobe:   {status.get('ffprobe') or '未找到'}")
    print(f"  设备:      {status.get('device') or '未加载'}")
    print(f"  缓存:      {status.get('cacheDir')}（{status.get('cacheFiles')} 个结果）")
    if status.get('loaded'):
        print(f"  加载耗时:  {status.get('loadSeconds')}s   dtype={status.get('dtype')}")
    if status.get('text') is not None:
        print(f"  图片:      {status.get('image')} {status.get('imageSize')}")
        print(f"  识别耗时:  {status.get('elapsedMs')}ms")
        print(f"  输出:      {status.get('text')[:300]}")
    if status.get('error'):
        print(f"  错误:      {status['error']}")


if __name__ == '__main__':
    raise SystemExit(main())
