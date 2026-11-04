def validate_bp(value):
    if not isinstance(value, dict):
        raise ValueError('BP 必须是对象')
    result = {'bans': {}, 'picks': {}}
    for kind, limit in [('bans', 4), ('picks', 5)]:
        group = value.get(kind, {})
        if not isinstance(group, dict):
            raise ValueError('BP 阵营格式无效')
        all_heroes = []
        for side in ['left', 'right']:
            heroes = group.get(side, [])
            if not isinstance(heroes, list) or len(heroes) > limit or any(not isinstance(h, str) or len(h) > 30 for h in heroes):
                raise ValueError(f'{kind} 每方最多 {limit} 个英雄')
            heroes = [hero.strip() for hero in heroes]
            all_heroes.extend(hero for hero in heroes if hero)
            result[kind][side] = heroes
        if len(set(all_heroes)) != len(all_heroes):
            raise ValueError('同一禁用或选用序列不能重复英雄')
    banned = {h for heroes in result['bans'].values() for h in heroes if h}
    picked = {h for heroes in result['picks'].values() for h in heroes if h}
    if banned & picked:
        raise ValueError('同一英雄不能既禁用又选用')
    first = value.get('firstPick', '')
    if first not in ['', 'left', 'right']:
        raise ValueError('一手方无效')
    notes = value.get('notes', '')
    if not isinstance(notes, str) or len(notes) > 2000:
        raise ValueError('BP 备注最多 2000 字')
    return {**result, 'firstPick': first, 'notes': notes.strip()}
