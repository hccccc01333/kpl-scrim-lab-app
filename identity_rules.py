def _roster_names(roster):
    """name → 选手 id。同名不同 id 属于数据歧义，单独标出来不猜。"""
    names = {}
    ambiguous = set()
    for person in roster or []:
        name = person.get('name')
        if not name:
            continue
        existing = names.get(name)
        if existing is not None and existing != person.get('id'):
            ambiguous.add(name)
        names.setdefault(name, person.get('id'))
    return names, ambiguous


def validate_alias_conflicts(matches, roster, aliases, previous_aliases):
    names, ambiguous = _roster_names(roster)
    for match in matches:
        own = match.get('ownCamp') or match.get('ownSide')
        seen = {}
        for player in match.get('players', []):
            camp = player.get('camp') or player.get('side')
            if own and camp and camp != own:
                continue
            label = player.get('rawLabel') or player.get('label')
            original_id = player.get('playerId') if label not in previous_aliases else None
            # 同名的两名队员无法判断指向谁；退回 playerId，不按名字猜。
            by_name = None if label in ambiguous else names.get(label)
            target = aliases.get(label) or original_id or by_name
            if not target:
                continue
            if target in seen:
                raise ValueError(f'绑定冲突：{seen[target]} 与 {label} 在同一局出场，不能合并为同一选手')
            seen[target] = label
