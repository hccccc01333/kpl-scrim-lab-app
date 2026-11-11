def validate_alias_conflicts(matches, roster, aliases, previous_aliases):
    names = {p['name']: p['id'] for p in roster}
    for match in matches:
        own = match.get('ownCamp') or match.get('ownSide')
        seen = {}
        for player in match.get('players', []):
            camp = player.get('camp') or player.get('side')
            if own and camp and camp != own:
                continue
            label = player.get('rawLabel') or player.get('label')
            original_id = player.get('playerId') if label not in previous_aliases else None
            target = aliases.get(label) or original_id or names.get(label)
            if not target:
                continue
            if target in seen:
                raise ValueError(f'绑定冲突：{seen[target]} 与 {label} 在同一局出场，不能合并为同一选手')
            seen[target] = label
