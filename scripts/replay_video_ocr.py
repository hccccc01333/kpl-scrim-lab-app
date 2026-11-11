"""Read-only OCR of a fixed-layout replay recording.

Reads only text that is visible in the video. The report is an experiment:
it is not written to the database and never enters win-rate statistics.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import video_mimo
from video_ocr import VideoOCRError, analyze_video, cross_check_abc, render_summary


def main():
    parser = argparse.ArgumentParser(description='识别固定布局回放录屏的可见 HUD（列表、阵容、经济、击杀、面板）。')
    parser.add_argument('video', help='录屏文件路径（mp4/mkv 等 ffmpeg 可读格式）')
    parser.add_argument('--fps', type=float, default=1.0, help='采样帧率，默认 1；2 更平滑但更慢')
    parser.add_argument('--out', help='报告路径；默认 data/replays/video_ocr/<sha前缀>.json；- 表示只打印')
    parser.add_argument('--evidence', help='把关键帧保存到该目录，便于人工核对')
    parser.add_argument('--abc', help='同一局的 .abc；只读核对十人英雄，可选')
    parser.add_argument('--ocr-engine', choices=['rapid', 'mimo', 'auto'], default='auto',
                        help='rapid=只跑逐帧快速 OCR；mimo=额外精读加载页/团队面板；auto=默认')
    parser.add_argument('--json', action='store_true', help='输出完整 JSON 而不是摘要')
    parser.add_argument('--quiet', action='store_true', help='不显示进度')
    args = parser.parse_args()

    path = Path(args.video).expanduser().resolve()
    if not path.is_file():
        print('找不到指定的录屏文件', file=sys.stderr)
        return 2
    progress = None if args.quiet else (
        lambda done, total: print(f'  已采样 {done} 帧 / 约 {total:.0f}s', file=sys.stderr))
    evidence = args.evidence
    if not evidence and args.ocr_engine in ('mimo', 'auto'):
        evidence = str(ROOT / 'data' / 'replays' / 'video_ocr' / 'evidence' / path.stem)
    try:
        report = analyze_video(path, fps=args.fps, progress=progress, evidence_dir=evidence)
    except ImportError:
        print('本地 OCR 组件未安装，请运行 安装依赖.bat', file=sys.stderr)
        return 2
    except VideoOCRError as error:
        print(f'识别失败: {error}', file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f'识别失败: {error}', file=sys.stderr)
        return 2
    if args.ocr_engine in ('mimo', 'auto'):
        report = video_mimo.refine_report(report, evidence)
    if args.abc:
        try:
            report['abcCheck'] = cross_check_abc(report, args.abc)
        except VideoOCRError as error:
            print(f'.abc 核对跳过: {error}', file=sys.stderr)
            report['abcCheck'] = {'status': 'error', 'note': str(error)}

    if args.out == '-':
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    out = Path(args.out) if args.out else (
        ROOT / 'data' / 'replays' / 'video_ocr' / f"{report['video']['sha256'][:16]}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_summary(report))
        print(f'报告: {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
