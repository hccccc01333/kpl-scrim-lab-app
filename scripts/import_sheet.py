"""Import an existing training spreadsheet: preview, draft a profile, stage rows.

The importer preserves raw columns and separates per-match, event and aggregate
grains. It never re-aggregates averaged/percentage fields.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sheet_import import (SCHEMA, SheetImportError, infer_profile, load_profiles,
                          read_workbook, render_preview, write_staging)


def selected_sheets(workbook, names):
    if not names:
        return workbook['sheets']
    by_name = {sheet['name']: sheet for sheet in workbook['sheets']}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise SheetImportError(f'找不到工作表：{", ".join(missing)}')
    return [by_name[name] for name in names]


def main():
    parser = argparse.ArgumentParser(description='预览并导入赛训组已有的 CSV/Excel 表格。')
    parser.add_argument('file', help='CSV/TSV/XLSX/XLSM 文件')
    parser.add_argument('--sheet', action='append', default=[], help='只处理指定工作表；可重复')
    parser.add_argument('--profile', action='append', default=[], help='映射 profile JSON；可重复')
    parser.add_argument('--preview', action='store_true', help='只打印画像，不落盘')
    parser.add_argument('--list-sheets', action='store_true', help='只列出工作表')
    parser.add_argument('--write-profile', help='把推断的 profile 写到该 JSON，便于人工修改')
    parser.add_argument('--accept-inferred', action='store_true',
                        help='直接使用推断 profile 落盘；manifest 会标记 inferred')
    parser.add_argument('--out', help='输出目录；默认 data/imports/<sha16>')
    parser.add_argument('--json', action='store_true', help='打印 manifest JSON')
    args = parser.parse_args()

    try:
        workbook = read_workbook(args.file)
        if args.list_sheets:
            for sheet in workbook['sheets']:
                print(f"{sheet['name']}  {len(sheet['rows'])} 行 × {len(sheet['header'])} 列")
            return 0
        sheets = selected_sheets(workbook, args.sheet)
        filtered = {'source': workbook['source'], 'sheets': sheets}
        inferred = {sheet['name']: infer_profile(sheet) for sheet in sheets}

        if args.write_profile:
            payload = {'profileVersion': 1, 'sheets': inferred}
            Path(args.write_profile).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                                encoding='utf-8')
            print(f'profile: {args.write_profile}')

        if args.preview or (not args.profile and not args.accept_inferred):
            print(render_preview(filtered))
            if not args.profile and not args.accept_inferred:
                if not args.preview:
                    print('\n未落盘。确认画像后：用 --profile 指定映射，或加 --accept-inferred。')
            return 0

        profiles = {}
        if args.profile:
            for path in args.profile:
                profiles.update(load_profiles(path, sheets))
            source_kind = 'provided'
        else:
            profiles = inferred
            source_kind = 'inferred'
        missing = [sheet['name'] for sheet in sheets if sheet['name'] not in profiles]
        if missing:
            raise SheetImportError(f'缺少工作表的 profile：{", ".join(missing)}')

        out = Path(args.out) if args.out else (
            ROOT / 'data' / 'imports' / workbook['source']['sha256'][:16])
        manifest = write_staging(workbook['source'], sheets, profiles, out, source_kind)
    except SheetImportError as error:
        print(f'导入失败: {error}', file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f'导入失败: {error}', file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(f"表格：{manifest['source']['name']}  sha256 {manifest['source']['sha256'][:16]}")
        for sheet in manifest['sheets']:
            print(f"  [{sheet['name']}] {sheet['grain']}  {sheet['rowCount']} 行  "
                  f"{'聚合' if sheet['aggregated'] else '单局/事件'}")
            print(f"    键：{sheet['keys']}")
            print(f"    指标：{sheet['metrics']}")
            if sheet['unmappedColumns']:
                print(f"    未映射：{', '.join(sheet['unmappedColumns'][:8])}")
        quality = manifest['quality']
        print(f"质量：{quality['rows']} 行，空键 {quality['missingKeys']}，重复键 {quality['duplicates']}，"
              f"越界指标 {quality['invalidMetrics']}")
        for warning in manifest['warnings']:
            print(f'注意：{warning}')
        print(f'输出：{out}')
        print(f'profile：{Path(out) / "profile.json"}；manifest：{Path(out) / "manifest.json"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
