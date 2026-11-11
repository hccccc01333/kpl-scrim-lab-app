"""Build one per-match data bundle from video OCR reports and post-game screenshots.

This step aligns sources, normalizes field names and keeps provenance. It does
not compute win rates or per-minute metrics; those belong to the analysis layer.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from match_data import (MatchDataError, build_match_data, load_postgame,
                        load_video_report, render_summary)


def main():
    parser = argparse.ArgumentParser(description='把多路录屏 OCR 与赛后截图整理成一份单局数据包。')
    parser.add_argument('--video', action='append', required=True,
                        help='kpl-video-ocr-v1 报告；可重复。第一路作为阵容基准')
    parser.add_argument('--follow', action='append', default=[],
                        help='与 --video 按顺序对应的 POV 队员昵称/英雄；用 - 表示不标注')
    parser.add_argument('--postgame', action='append', default=[],
                        help='赛后截图（PNG/JPG）或截图识别 JSON；可重复（战绩页 + 数据页）')
    parser.add_argument('--match-id', help='覆盖自动生成的单局 ID')
    parser.add_argument('--force', action='store_true', help='同一局校验不通过时仍生成，并保留警告')
    parser.add_argument('--out', help='输出路径；默认 data/matches/<key>.json；- 只打印')
    parser.add_argument('--json', action='store_true', help='打印完整 JSON 而不是摘要')
    args = parser.parse_args()

    if len(args.follow) > len(args.video):
        print('--follow 不能多于 --video', file=sys.stderr)
        return 2
    follows = [None if value in ('-', '') else value for value in args.follow]
    follows += [None] * (len(args.video) - len(follows))
    try:
        videos = [load_video_report(path) for path in args.video]
        postgames = [load_postgame(path) for path in args.postgame]
        bundle = build_match_data(videos, follows, postgames, args.match_id, args.force)
    except MatchDataError as error:
        print(f'整理失败: {error}', file=sys.stderr)
        return 2
    except ImportError:
        print('读取赛后截图需要本地 OCR 组件，请运行 安装依赖.bat', file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f'整理失败: {error}', file=sys.stderr)
        return 2

    if args.out == '-':
        print(json.dumps(bundle, ensure_ascii=False, indent=2))
        return 0
    out = Path(args.out) if args.out else (
        ROOT / 'data' / 'matches' / f"{bundle['match']['key']}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.json:
        print(json.dumps(bundle, ensure_ascii=False, indent=2))
    else:
        print(render_summary(bundle))
        print(f'数据包: {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
