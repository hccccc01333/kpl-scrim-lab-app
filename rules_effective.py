"""规则中心「按赛事生效」的统一解析（方案文档 §2 遗留 TODO 落地）。

规则条目的 effective：{eventId, eventName, from, to}——四项全空 = 始终生效。
赛事是备战周期：eventId 直接对 competitions.id；eventName 对赛事名称；
from/to 用赛事的训练起始（date）落在窗内判定。
"""

_ENTRY_KEYS = {'counters': None, 'combos': 'combos', 'lineup_tags': 'tags', 'misc': 'entries'}


def _split_pairs(matched):
    hero = [entry for entry in matched if entry.get('sub') != 'combo']
    combo = [entry for entry in matched if entry.get('sub') == 'combo']
    return hero, combo


def filter_entries(entries, competition):
    """按赛事过滤规则条目，返回 (适用条目, 命中说明)。

    competition: 赛事 dict（id/name/date/end_date）或 None（全局口径 = 全量）。
    """
    entries = entries or []
    if not competition:
        return list(entries), {'mode': 'global', 'total': len(entries), 'matched': len(entries)}
    comp_id = str(competition.get('id') or '')
    comp_name = str(competition.get('name') or '')
    comp_date = str(competition.get('date') or '')
    matched = []
    for entry in entries:
        eff = entry.get('effective') or {}
        event_id = str(eff.get('eventId') or '').strip()
        event_name = str(eff.get('eventName') or '').strip()
        lo = str(eff.get('from') or '').strip()
        hi = str(eff.get('to') or '').strip()
        if not (event_id or event_name or lo or hi):
            matched.append(entry)  # 常年生效
        elif event_id and event_id == comp_id:
            matched.append(entry)
        elif event_name and event_name == comp_name:
            matched.append(entry)
        elif lo and comp_date and comp_date >= lo and (not hi or comp_date <= hi):
            matched.append(entry)
    return matched, {'mode': 'competition', 'competition': comp_id,
                     'total': len(entries), 'matched': len(matched),
                     'skipped': len(entries) - len(matched)}


def resolve_doc(kind, doc, competition):
    """返回按赛事裁剪后的 rules-center 文档（结构不变，条目集合被过滤）。"""
    doc = dict(doc or {})
    if kind == 'counters':
        entries = (doc.get('heroPairs') or []) + (doc.get('comboPairs') or [])
        matched, meta = filter_entries(entries, competition)
        hero, combo = _split_pairs(matched)
        doc['heroPairs'], doc['comboPairs'] = hero, combo
    else:
        key = _ENTRY_KEYS.get(kind)
        entries = doc.get(key) or [] if key else []
        matched, meta = filter_entries(entries, competition)
        if key:
            doc[key] = matched
    doc['effectiveMeta'] = meta
    return doc
