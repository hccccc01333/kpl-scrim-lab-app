"""导入后自动预填（规格 8.7.2）。

只对**空字段**生成待确认项，不覆盖人工值：
  对手     已由迁移按阵容签名写入；为空才建待确认项
  训练组   按日期推断「YYYY-MM-DD 训练组」，置信度 low
  版本     营地没有 → placeholder，不猜
  规则     营地没有 → placeholder
  BP 手序  有 campBp 才建议 auto，否则 placeholder
"""
from __future__ import annotations


def run(workspace, *, actor=None):
    """扫描 match_records，为缺失字段写 prefill_fields，返回生成条数。"""
    records = workspace.list_matches(limit=5000)
    existing = {(row['match_key'], row['field']) for row in workspace.list_prefill()}
    created = 0

    def mark(match_key, field, value, source, confidence):
        nonlocal created
        if (match_key, field) in existing:
            return
        workspace.add_prefill(match_key, field, value, source=source, confidence=confidence)
        created += 1

    for record in records:
        key = record['match_key']
        if not record.get('enemy_team_id'):
            mark(key, 'enemy_team_id', None, 'derived:cluster', 'medium')
        if not record.get('session'):
            date = record.get('date') or ''
            mark(key, 'session', f'{date} 训练组' if date else None, 'derived:session', 'low')
        if not record.get('version'):
            mark(key, 'version', None, 'placeholder', 'low')
        if not record.get('rules'):
            mark(key, 'rules', None, 'placeholder', 'low')

    return created


def queue(workspace):
    """把预填项按对局分组，供待确认队列使用。"""
    records = {row['match_key']: row for row in workspace.list_matches(limit=5000)}
    teams = {team['id']: team['name'] for team in workspace.list_teams(include_archived=True)}
    grouped = {}
    for item in workspace.list_prefill():
        record = records.get(item['match_key'])
        if record is None:
            continue
        entry = grouped.setdefault(item['match_key'], {
            'matchKey': item['match_key'],
            'date': record.get('date'),
            'opponent': teams.get(record.get('enemy_team_id')) or '',
            'ownSide': record.get('own_side'),
            'winner': record.get('winner'),
            'fields': [],
        })
        entry['fields'].append({
            'field': item['field'],
            'value': item['value'],
            'source': item['source'],
            'confidence': item['confidence'],
        })
    rows = sorted(grouped.values(), key=lambda row: (row.get('date') or '', row['matchKey']), reverse=True)
    return {'rows': rows, 'total': len(rows),
            'fields': sum(len(row['fields']) for row in rows)}
