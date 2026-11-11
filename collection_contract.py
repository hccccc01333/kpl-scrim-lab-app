"""Shared collection requirements and strict single-match table validation."""
import json
import math
from collections import Counter
from datetime import date, datetime
from pathlib import Path

CONTRACT = json.loads((Path(__file__).resolve().parent / 'web/capture-guide/requirements.json').read_text(encoding='utf-8'))
PAGE_TYPES = tuple(item['type'] for item in CONTRACT['screenshotPages'])
PAGE_NAMES = {item['type']: item['label'] for item in CONTRACT['screenshotPages']}
TEMPLATE_COLUMNS = tuple(column['name'] for column in CONTRACT['sheet']['columns'])


def is_example_match(value):
    text = str(value or '').strip()
    return text.upper().startswith('EXAMPLE') or text.startswith('示例')


def reject_example_table(sheet):
    """识别「原样上传示例表」：18 列模板，且所有对局 ID 还是示例编号。

    批量导入端点不做严格十人校验，示例表会带着虚构数据直接进分析数据集；
    这里只拦「整张表都是示例编号」的情况，混入真实记录的表不受影响。
    """
    header = sheet.get('header') or []
    if len(header) != len(TEMPLATE_COLUMNS) or set(header) != set(TEMPLATE_COLUMNS):
        return
    index = header.index('对局ID')
    ids = [str(row[index] or '').strip() for row in sheet.get('rows') or [] if index < len(row)]
    ids = [value for value in ids if value]
    if ids and all(is_example_match(value) for value in ids):
        raise ValueError('表格里还是示例编号：请把「对局ID」替换成真实记录，再核对日期和十人数据；示例文件只用于对照格式。')



def _require_template_columns(header):
    expected = [col['name'] for col in CONTRACT['sheet']['columns']]
    if set(header) != set(expected) or len(header) != len(expected):
        missing = [key for key in expected if key not in header]
        extra = [key for key in header if key not in expected]
        raise ValueError('请使用本项目单局模板；' + ('缺少列：' + '、'.join(missing) + '；' if missing else '') + ('多余或重复列：' + '、'.join(extra) if extra else '表头数量不符'))


def validate_sheet(sheet, match=None, existing_match_ids=()):
    """Validate and normalize a single 10-player sheet before inferred mapping."""
    columns = CONTRACT['sheet']['columns']
    header = sheet['header']
    _require_template_columns(header)
    if len(sheet['rows']) != 10:
        raise ValueError(f"单局表必须恰好 10 行（双方各 5 人），当前 {len(sheet['rows'])} 行；多局表请使用批量导入")
    rows = [dict(zip(header, values)) for values in sheet['rows']]
    integer_fields = ['击杀','死亡','助攻','经济','输出','承伤','时长']
    for index, row in enumerate(rows, 2):
        for col in columns:
            value = row.get(col['name'])
            if col['required'] and (value is None or str(value).strip() == ''):
                raise ValueError(f"第 {index} 行缺少 {col['name']}")
        for key in ['对局ID','阵营','分路','选手','英雄','胜负']:
            row[key] = str(row.get(key) or '').strip()
        if row['对局ID'].upper().startswith('EXAMPLE') or row['对局ID'].startswith('示例'):
            raise ValueError('示例数据不能直接用于本局；请用真实对局ID和真实十人数据替换示例')
        value = row['日期']
        if isinstance(value, (date, datetime)):
            row['日期'] = value.strftime('%Y-%m-%d')
        else:
            try:
                text = str(value).strip()
                row['日期'] = date.fromisoformat(text).isoformat()
            except ValueError:
                raise ValueError(f'第 {index} 行日期请使用 YYYY-MM-DD') from None
        if row['阵营'] not in ('blue','red'):
            raise ValueError(f'第 {index} 行阵营只能是 blue 或 red')
        row['本队阵营'] = str(row.get('本队阵营') or '').strip().lower()
        if row['本队阵营'] not in ('blue','red'):
            raise ValueError(f'第 {index} 行本队阵营只能是 blue 或 red')
        if row['分路'] not in CONTRACT['sheet']['positions']:
            raise ValueError(f'第 {index} 行分路必须是对抗路、打野、中路、发育路或游走')
        if row['胜负'] not in ('','胜','负','未知'):
            raise ValueError(f'第 {index} 行胜负只能是胜、负或未知')
        for key in integer_fields + ['参团率','评分']:
            value = row.get(key)
            if value is None or str(value).strip() == '':
                row[key] = None
                continue
            text = str(value).strip()
            if key == '参团率' and text.endswith('%'):
                text = text[:-1]
            try:
                number = float(text)
            except (TypeError, ValueError):
                raise ValueError(f'第 {index} 行 {key} 必须是原始数值，不能带万、k等单位') from None
            if not math.isfinite(number) or number < 0 or (key in integer_fields and not number.is_integer()):
                raise ValueError(f'第 {index} 行 {key} 数值无效；计数和总量必须是非负整数')
            if key in ('参团率','评分') and number > 100:
                raise ValueError(f'第 {index} 行 {key} 必须在 0–100 之间')
            if key == '时长' and not 0 < number <= 7200:
                raise ValueError(f'第 {index} 行时长必须是 1–7200 秒')
            row[key] = int(number) if key in integer_fields else number
    for key in ['对局ID','日期','对手','时长']:
        values = {str(row.get(key) or '').strip() for row in rows}
        if len(values) > 1:
            raise ValueError(f'单局十行的 {key} 必须一致，不能混入另一局')
    if existing_match_ids and set(existing_match_ids) != {rows[0]['对局ID']}:
        raise ValueError('表格对局ID与本局已关联表格不同，不能混入另一局')
    if match and match.get('date') and rows[0]['日期'] != match['date']:
        raise ValueError('表格日期与当前采集比赛日期不同，请核对是否同一局')
    if Counter(row['阵营'] for row in rows) != {'blue':5,'red':5}:
        raise ValueError('阵营必须 blue 五人、red 五人')
    own_sides = {row['本队阵营'] for row in rows}
    if len(own_sides) != 1:
        raise ValueError('本队阵营十行必须一致')
    sheet['ownSide'] = own_sides.pop()
    if len({row['选手'] for row in rows}) != 10:
        raise ValueError('选手昵称不能重复；同名需补充可区分的真实游戏昵称')
    for side in ('blue','red'):
        members = [row for row in rows if row['阵营'] == side]
        if len({row['分路'] for row in members}) != 5 or len({row['英雄'] for row in members}) != 5:
            raise ValueError(f'{side} 方的五个分路和英雄不能重复')
        if len({row['胜负'] for row in members}) > 1:
            raise ValueError(f'{side} 方的胜负必须一致')
    outcomes = {side:next(row['胜负'] for row in rows if row['阵营']==side) for side in ('blue','red')}
    if outcomes['blue'] in ('胜','负') and outcomes['red'] in ('胜','负') and outcomes['blue']==outcomes['red']:
        raise ValueError('双方不能同时获胜或同时失败')
    if all(row[key] is not None for row in rows for key in ('击杀','死亡')):
        for side, opposite in [('blue','red'),('red','blue')]:
            if sum(row['击杀'] for row in rows if row['阵营']==side) != sum(row['死亡'] for row in rows if row['阵营']==opposite):
                raise ValueError('双方击杀与对方死亡合计不一致，请核对结算图')
    sheet['rows'] = [[row.get(key) for key in header] for row in rows]
    return sheet


def validate_table(sheet):
    """按「对局ID」把多局表拆成每局十行，再逐局套用单局校验。

    表格入口只收这一种形状：同一局十行、双方各五人；多局就往下追加，
    每块对局ID不同。返回 {对局ID: 行数}，方便调用方核对。
    """
    header = sheet.get('header') or []
    _require_template_columns(header)
    if '对局ID' not in header:
        raise ValueError('缺少「对局ID」列')
    index = header.index('对局ID')
    blocks = {}
    for row in sheet.get('rows') or []:
        key = str(row[index] if index < len(row) else '').strip()
        if not key:
            raise ValueError('有数据行缺少对局ID')
        blocks.setdefault(key, []).append(row)
    if not blocks:
        raise ValueError('表格没有数据行')
    for key, rows in blocks.items():
        if len(rows) != 10:
            raise ValueError(f'对局 {key} 有 {len(rows)} 行；每局必须恰好 10 行（双方各 5 人）')
        validate_sheet({'name': sheet.get('name'), 'header': list(header), 'rows': rows})
    return {key: len(rows) for key, rows in blocks.items()}
