"""Read-only OCR for the tabbed post-game screenshots.

Usage:
    python scripts/postgame_screenshot.py "战绩.png" "数据.png" --out report.json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from postgame_ocr import OCR_VERSION, recognize, merge_pages
from screenshot_schema import PAGE_FIELDS, PLAYER_LABELS, SCHEMA, TABS


def display(field):
    if not field:
        return '—'
    value = field.get('value')
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def render_page(result):
    match = result.get('match') or {}
    score = match.get('score') or {}
    lines = [f"文件：{result.get('file') or '截图'}",
             f"页面：{result.get('pageType')} / {result.get('tab') or '—'}  OCR：{result.get('version')}",
             f"日期：{match.get('date') or '—'}  时间：{match.get('time') or '—'}  "
             f"时长：{_duration(match.get('durationSec'))}  模式：{match.get('mode') or '—'}",
             f"比分：{score.get('left') if score.get('left') is not None else '—'}"
             f" : {score.get('right') if score.get('right') is not None else '—'}  "
             f"胜负：{_result(match.get('result'))}"]
    coverage = result.get('coverage') or {}
    useful = [f'{PLAYER_LABELS[field]}={coverage.get(field, 0)}' for field in coverage
              if field in PLAYER_LABELS and coverage.get(field)]
    lines.append('字段覆盖：' + ('  '.join(useful) if useful else '无可读字段'))
    for player in result.get('players') or []:
        nickname = display(player.get('nickname'))
        hero = display(player.get('hero'))
        if not hero and player.get('heroCandidates'):
            hero = '候选:' + '/'.join(item['name'] for item in player['heroCandidates'][:2])
        title = display(player.get('title'))
        flags = ' MVP' if player.get('mvp') else ''
        lines.append(f"  {_side(player['side'])}{player['slot'] + 1}  {nickname} / {hero}"
                     f"  评分{display(player.get('rating'))}  称号{title}{flags}")
        fields = player.get('fields') or {}
        shares = player.get('shares') or {}
        if fields:
            lines.append('    ' + '  '.join(f'{PLAYER_LABELS[field]}={display(value)}'
                                             for field, value in fields.items()))
        if shares:
            lines.append('    ' + '  '.join(f'{PLAYER_LABELS[field]}={display(value)}'
                                             for field, value in shares.items()))
    for warning in result.get('warnings') or []:
        lines.append(f'注意：{warning}')
    return '\n'.join(lines)


def render_bundle(index, bundle):
    pages = bundle.get('pages') or []
    match = bundle.get('match') or {}
    score = match.get('score') or {}
    title = ' / '.join(f"{page.get('pageType')}({page.get('file') or '—'})" for page in pages)
    lines = [f"== 合并组 {index}：{len(pages)} 页  {title}",
             f"日期 {match.get('date') or '—'}  时长 {_duration(match.get('durationSec'))}  "
             f"比分 {score.get('left') if score.get('left') is not None else '—'} : "
             f"{score.get('right') if score.get('right') is not None else '—'}"]
    if score.get('left') is not None and score.get('right') is not None:
        for side in ('left', 'right'):
            kills = [player.get('fields', {}).get('kills') for player in bundle.get('players') or []
                     if player.get('side') == side]
            if all(kills):
                total = sum(item['value'] for item in kills)
                lines.append(f"  {_side(side)}击杀合计 {total} / 比分 {score[side]}"
                             f"（{'一致' if total == score[side] else '不一致'}）")
    for player in bundle.get('players') or []:
        fields = dict(player.get('fields') or {})
        fields.update(player.get('shares') or {})
        text = '  '.join(f'{PLAYER_LABELS[field]}={display(value)}'
                         for field, value in fields.items())
        nickname = display(player.get('nickname'))
        hero = display(player.get('hero'))
        if not hero and player.get('heroCandidates'):
            hero = '候选:' + '/'.join(item['name'] for item in player['heroCandidates'][:2])
        lines.append(f"  {_side(player['side'])}{player['slot'] + 1}  {nickname} / {hero}"
                     f"  评分{display(player.get('rating'))}")
        if text:
            lines.append('    ' + text)
    for warning in bundle.get('warnings') or []:
        lines.append(f'注意：{warning}')
    return '\n'.join(lines)


def _duration(seconds):
    if seconds is None:
        return '—'
    return f'{seconds // 60}:{seconds % 60:02d}'


def _side(side):
    return '左' if side == 'left' else '右'


def _result(value):
    return {'win': '胜', 'loss': '负'}.get(value, value or '—')


def main():
    parser = argparse.ArgumentParser(description='只读识别新版分页赛后截图，不写数据库。')
    parser.add_argument('images', nargs='+', help='赛后截图（建议同一局多页一起传）')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    parser.add_argument('--tokens', action='store_true', help='JSON 中附带全部 OCR token')
    parser.add_argument('--out', help='把 JSON 报告保存到该路径')
    parser.add_argument('--no-merge', action='store_true', help='不尝试合并同一局的多页')
    parser.add_argument('--ocr-engine', choices=['rapid', 'mimo'], default='rapid',
                        help='rapid=快速布局（默认）；mimo=再用本机 Mimo 精读文字列')
    parser.add_argument('--mimo-mode', choices=['columns', 'page'], default='columns',
                        help='Mimo 精读模式；columns=英雄名/昵称列（推荐），page=整页实验')
    args = parser.parse_args()

    paths = []
    for value in args.images:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            print(f'找不到截图：{path}', file=sys.stderr)
            return 2
        paths.append(path)

    try:
        results = [recognize(path.read_bytes(), name=path.name, include_tokens=args.tokens,
                              engine=args.ocr_engine, mimo_mode=args.mimo_mode)
                   for path in paths]
    except ImportError:
        print('本地 OCR 组件未安装，请运行 安装依赖.bat', file=sys.stderr)
        return 2
    except Exception as error:
        print(f'识别失败：{type(error).__name__}: {error}', file=sys.stderr)
        return 2

    bundles = [] if args.no_merge else merge_pages(results, name=paths[0].stem if len(paths) == 1 else None)
    report = {'schema': SCHEMA, 'version': OCR_VERSION, 'images': results, 'bundles': bundles}

    if not args.json:
        for result in results:
            print(render_page(result))
            print()
        if len(results) > 1 and not args.no_merge:
            print(f'合并：{len(bundles)} 个独立比赛组。不同比分/阵容不会合并。')
            for index, bundle in enumerate(bundles, 1):
                print(render_bundle(index, bundle))
                print()
    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'报告：{out}')
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
