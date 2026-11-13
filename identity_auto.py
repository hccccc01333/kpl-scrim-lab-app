"""对局分边与认领的自动匹配（纯计算，不写库）。

教练口径（2026-11-06）：
  * 「存档战队」= 教练手动认领过的昵称（settings.aliases / enemyAliases）
    + 教练保存过「本队在哪个阵营 + 对手是谁」的比赛（match_meta 覆盖层，
    AnalysisRepository 会打上 metaFields 标记）。原始数据包自带的分边不算存档，
    避免把未经核对的数据当成依据。
  * 一侧 5 人里「没见过」的昵称 ≤ maxDiff（默认 1）→ 自动认领；
    2 个及以上不同 → 存疑，交给教练（可能是对手开小号，也可能是约了新对手）。
  * 红蓝两侧必须一边是本队、一边是对手；同一支战队不能占两边。
  * 教练在面板里给出「本队在哪边 + 对手是谁」后，这一局整局建档；
    建档结果立刻回灌存档，同一批里相似的对局下一轮即可自动匹配。

输出的是「建议」：新身份、别名补丁、战队名录、逐局分边。落库仍走
PUT /api/settings 与 POST /api/studio/match-meta/{key}，复用既有校验。
"""

from __future__ import annotations

import copy
import hashlib

DEFAULT_MAX_DIFF = 1
MAX_DIFF = 2
MAX_ROSTER = 40
MAX_MATCHES = 60
MAX_ALIASES = 2000
PLACEHOLDERS = {'', '对手待填写', '待指定', '蓝方', '红方'}
CAMP_NAME = {'blue': '蓝方', 'red': '红方'}


class CapacityError(Exception):
    """名单已满 / 存档冲突，这一局只能交给教练。"""


def _text(value):
    return str(value or '').strip()


def canon(camp):
    """把 left/right、1/2 统一成 blue/red（match_meta 只接受 blue/red）。"""
    value = _text(camp).lower()
    if value in ('blue', 'left', 'l', '1'):
        return 'blue'
    if value in ('red', 'right', 'r', '2'):
        return 'red'
    return value


def _camp_of(player):
    return canon(player.get('camp') or player.get('side'))


def _nick(player):
    return _text(player.get('rawLabel') or player.get('label'))


def _side(match, camp):
    return [p for p in (match.get('players') or []) if _camp_of(p) == camp]


def _nicks(match, camp):
    return [nick for nick in (_nick(p) for p in _side(match, camp)) if nick]


def eligible(data, limit=MAX_MATCHES):
    """只处理标准 5v5（每边 3–6 人、蓝红齐全）且带 key 的对局。

    先过滤再截断：limit 是「最多返回多少局可用对局」，不是「只检查最近的
    limit 局」——否则前面若有一批不完整局，会把后面合格的局直接挤掉。
    """
    items = [m for m in (data.get('matches') or []) + (data.get('sheetMatches') or [])
             if m.get('key')]
    items.sort(key=lambda m: (str(m.get('date') or m.get('dateKey') or ''),
                              len(m.get('players') or [])), reverse=True)
    cap = max(1, min(limit, 200))
    out = []
    for match in items:
        if len(out) >= cap:
            break
        blue = _nicks(match, 'blue')
        red = _nicks(match, 'red')
        camps = {_camp_of(p) for p in (match.get('players') or [])}
        if camps <= {'blue', 'red'} and len(camps) == 2 and 3 <= len(blue) <= 6 and 3 <= len(red) <= 6:
            out.append(match)
    return out


def _settings_team(settings):
    return _text(settings.get('teamName')) or '我的训练队'


def build_archive(data, settings, decisions=None):
    """team -> {nick: {'playerId': ..., 'weight': ..., 'sources': [...]}}。

    同一个昵称若出现在两支战队的存档里，直接丢弃：它无法用来判断分边。
    """
    own = _settings_team(settings)
    roster = {p.get('id'): p for p in (settings.get('roster') or []) if isinstance(p, dict)}
    evidence = {}

    def add(nick, team, player_id, weight, source):
        nick, team = _text(nick), _text(team)
        if not nick or not team or team in PLACEHOLDERS:
            return
        slot = evidence.setdefault(nick, {})
        item = slot.setdefault(team, {'playerId': None, 'weight': 0, 'sources': []})
        item['weight'] += weight
        if source and source not in item['sources'] and len(item['sources']) < 8:
            item['sources'].append(source)
        member = roster.get(player_id) if player_id else None
        if member and _text(member.get('team')) == team:
            item['playerId'] = player_id

    def add_lineup(nicks_by_camp, own_camp, opponent, source, ids_by_camp=None):
        if own_camp not in ('blue', 'red') or not opponent or opponent == own or opponent in PLACEHOLDERS:
            return
        ids_by_camp = ids_by_camp or {}
        for camp in ('blue', 'red'):
            team = own if camp == own_camp else opponent
            for nick in nicks_by_camp.get(camp) or []:
                add(nick, team, None, 1, source)
                player_id = (ids_by_camp.get(camp) or {}).get(nick)
                if player_id:
                    add(nick, team, player_id, 0, source)

    def ids_of(match):
        return {camp: {_nick(p): p.get('playerId') for p in _side(match, camp) if _nick(p)}
                for camp in ('blue', 'red')}

    # 1) 教练手动认领：权重最高，且带稳定选手身份
    for table in ('aliases', 'enemyAliases'):
        for nick, player_id in (settings.get(table) or {}).items():
            member = roster.get(player_id)
            if member:
                add(nick, _text(member.get('team')) or own, player_id, 3, table)

    # 2) 教练保存过分边的对局：只要确认了「本队在哪边」，本队五人就能进存档；
    #    对手侧必须同时命名了战队，否则不知道该记到哪支队伍名下。
    all_matches = (data.get('matches') or []) + (data.get('sheetMatches') or [])
    for match in all_matches:
        fields = match.get('metaFields') or []
        if 'ownCamp' not in fields:
            continue
        own_camp = canon(match.get('ownCamp') or match.get('ownSide'))
        source = _text(match.get('key'))[:60]
        if own_camp in ('blue', 'red'):
            player_ids = ids_of(match).get(own_camp) or {}
            for nick in _nicks(match, own_camp):
                add(nick, own, None, 1, source)
                if player_ids.get(nick):
                    add(nick, own, player_ids[nick], 0, source)
        if 'opponent' not in fields:
            continue
        add_lineup({'blue': _nicks(match, 'blue'), 'red': _nicks(match, 'red')},
                   own_camp, _text(match.get('opponent')), source, ids_of(match))

    # 3) 本轮教练刚做的判断，立刻当作存档（同一批里相似对局就能跟着自动）
    for key, decision in (decisions or {}).items():
        match = next((m for m in all_matches if _text(m.get('key')) == key), None)
        if not match:
            continue
        add_lineup({'blue': _nicks(match, 'blue'), 'red': _nicks(match, 'red')},
                   decision['ownCamp'], decision['opponent'], 'decision:' + key[:40])

    archive = {}
    for nick, per_team in evidence.items():
        teams = [team for team in per_team if team not in PLACEHOLDERS]
        if len(teams) == 1:
            archive.setdefault(teams[0], {})[nick] = per_team[teams[0]]
    return archive, own


def candidate_opponents(data, settings, archive, own):
    names = []
    for team in (settings.get('teams') or []):
        if isinstance(team, dict):
            names.append(_text(team.get('name')))
    for match in (data.get('matches') or []) + (data.get('sheetMatches') or []):
        names.append(_text(match.get('opponent')))
    names.extend(archive.keys())
    return [name for name in dict.fromkeys(names)
            if name and name != own and name not in PLACEHOLDERS]


def score(nicks, team, archive):
    known = archive.get(team) or {}
    hits = [nick for nick in nicks if nick in known]
    unknown = [nick for nick in nicks if nick not in known]
    return {'team': team, 'hits': len(hits), 'diff': len(unknown),
            'hitNicks': hits, 'unknown': unknown}


def pair_options(nicks_by_camp, own, opponents, archive):
    options = []
    for own_camp in ('blue', 'red'):
        opp_camp = 'red' if own_camp == 'blue' else 'blue'
        own_score = score(nicks_by_camp[own_camp], own, archive)
        for opponent in opponents:
            opp_score = score(nicks_by_camp[opp_camp], opponent, archive)
            # 本队名单出现在对面 / 对手名单出现在本队，都说明分边或存档不干净
            cross = (score(nicks_by_camp[opp_camp], own, archive)['hits']
                     + score(nicks_by_camp[own_camp], opponent, archive)['hits'])
            options.append({
                'ownCamp': own_camp, 'opponent': opponent,
                'ownScore': own_score, 'oppScore': opp_score,
                'hits': own_score['hits'] + opp_score['hits'],
                'diff': own_score['diff'] + opp_score['diff'],
                'cross': cross,
            })
    return options


class Resolver:
    """给昵称分配稳定身份；同一 (战队, 昵称) 在整批里只建一个身份。"""

    def __init__(self, settings, own, archive):
        self.own = own
        self.archive = archive
        self.roster = {p['id']: dict(p) for p in (settings.get('roster') or [])
                       if isinstance(p, dict) and p.get('id')}
        self.aliases = dict(settings.get('aliases') or {})
        self.enemy_aliases = dict(settings.get('enemyAliases') or {})
        self.patch_aliases = {}
        self.patch_enemy = {}
        self.members = []
        self.teams = set()
        self.metas = []
        self.registry = {}
        for mapping in (self.aliases, self.enemy_aliases):
            for nick, player_id in mapping.items():
                member = self.roster.get(player_id)
                if member:
                    self.registry[(_text(member.get('team')) or own, nick)] = player_id

    def snapshot(self):
        return copy.deepcopy((self.roster, self.registry, self.members, self.patch_aliases,
                              self.patch_enemy, self.teams, self.metas))

    def restore(self, state):
        (self.roster, self.registry, self.members, self.patch_aliases,
         self.patch_enemy, self.teams, self.metas) = state

    def _id_for(self, team, nick):
        seed = hashlib.sha1(f'{team}\x1f{nick}'.encode('utf-8')).hexdigest()[:12]
        candidate = 'ac-' + seed
        suffix = 0
        while candidate in self.roster:
            suffix += 1
            candidate = f'ac-{seed}-{suffix}'
        return candidate

    def identity(self, team, nick, is_own, preferred=None, force_new=False):
        table = self.aliases if is_own else self.enemy_aliases
        patch = self.patch_aliases if is_own else self.patch_enemy
        if not force_new:
            existing = table.get(nick) or patch.get(nick)
            if existing and existing in self.roster and (_text(self.roster[existing].get('team')) or self.own) == team:
                return existing, 'existing'
            if preferred and preferred in self.roster and (_text(self.roster[preferred].get('team')) or self.own) == team:
                pid, source = preferred, 'archive'
            else:
                key = (team, nick)
                pid, source = self.registry.get(key), 'archive'
        else:
            pid = None
        if not pid:
            if len(self.roster) >= MAX_ROSTER:
                raise CapacityError(f'选手名单已满 {MAX_ROSTER} 人')
            pid = self._id_for(team, nick)
            self.roster[pid] = {'id': pid, 'name': nick[:50], 'team': team,
                                'position': '', 'tags': []}
            self.members.append(dict(self.roster[pid]))
            source = 'new'
        if nick not in table and nick not in patch and len(table) + len(patch) >= MAX_ALIASES:
            raise CapacityError(f'昵称存档已满 {MAX_ALIASES} 条')
        patch[nick] = pid
        self.registry[(team, nick)] = pid
        return pid, source

    def bind_side(self, camp, team, nicks, is_own, infer=True):
        known = self.archive.get(team) or {}
        unknown = [nick for nick in nicks if nick not in known]
        hit_count, diff_count = len(nicks) - len(unknown), len(unknown)
        binds, used = [], {}
        for nick in nicks:
            if nick in unknown:
                continue
            preferred = (known[nick] or {}).get('playerId')
            pid, source = self.identity(team, nick, is_own, preferred)
            if pid in used:
                raise CapacityError('存档里两个昵称指向同一身份，且同时出现在本局')
            used[pid] = nick
            binds.append({'nick': nick, 'playerId': pid, 'source': source})
        if len(unknown) == 1 and infer:
            # 4/5 命中同一支战队、只差一个昵称：优先当作缺的那位开了小号。
            patch = self.patch_aliases if is_own else self.patch_enemy
            candidates = set()
            for archived_nick, entry in known.items():
                if archived_nick in nicks:
                    continue
                pid = (entry or {}).get('playerId') or self.registry.get((team, archived_nick))
                if pid and pid in self.roster and pid not in used:
                    candidates.add(pid)
            if len(candidates) == 1:
                pid = candidates.pop()
                patch[unknown[0]] = pid
                self.registry[(team, unknown[0])] = pid
                binds.append({'nick': unknown[0], 'playerId': pid, 'source': 'inferred'})
                unknown = []
        for nick in unknown:
            used_ids = {b['playerId'] for b in binds}
            clash = self.registry.get((team, nick)) in used_ids
            pid, source = self.identity(team, nick, is_own, force_new=clash)
            binds.append({'nick': nick, 'playerId': pid, 'source': source})
        return {'camp': camp, 'team': team, 'hits': hit_count, 'diff': diff_count,
                'unknown': [b['nick'] for b in binds if b['source'] in ('new', 'inferred')],
                'binds': binds}

    def deltas(self):
        return {
            'members': list(self.members),
            'aliases': dict(self.patch_aliases),
            'enemyAliases': dict(self.patch_enemy),
            'teams': [name for name in sorted(self.teams) if name and name != self.own],
            'metas': list(self.metas),
        }


def _sanitize_decisions(decisions, matches, own):
    keys = {_text(m.get('key')) for m in matches}
    clean = {}
    for key, value in (decisions or {}).items():
        key = _text(key)
        if key not in keys or not isinstance(value, dict):
            continue
        camp = canon(value.get('ownCamp'))
        opponent = _text(value.get('opponent'))[:50]
        if camp not in ('blue', 'red') or not opponent or opponent == own or opponent in PLACEHOLDERS:
            continue
        clean[key] = {'ownCamp': camp, 'opponent': opponent}
    return clean


def _review(plan, reason, notes=None):
    plan['status'] = 'review'
    plan['ownCampPlan'] = None
    plan['opponent'] = None
    plan['reason'] = reason
    plan['notes'] = notes or []
    return plan


def _base(match):
    return {
        'key': _text(match.get('key')),
        'date': _text(match.get('date') or match.get('dateKey')),
        'title': _text(match.get('title') or match.get('date') or '训练赛'),
        'hintCamp': canon(match.get('ownCamp') or match.get('ownSide')),
        'currentOpponent': _text(match.get('opponent')),
        'sides': [], 'notes': [], 'status': 'review', 'reason': '',
        'ownCampPlan': None, 'opponent': None,
    }


def build_plan(data, settings, max_diff=DEFAULT_MAX_DIFF, decisions=None, limit=MAX_MATCHES):
    """返回自动认领预览；不写任何文件。"""
    try:
        max_diff = max(0, min(MAX_DIFF, int(max_diff)))
    except (TypeError, ValueError):
        max_diff = DEFAULT_MAX_DIFF
    matches = eligible(data, limit)
    own = _settings_team(settings)
    clean_decisions = _sanitize_decisions(decisions, matches, own)
    archive, own = build_archive(data, settings, clean_decisions)
    opponents = candidate_opponents(data, settings, archive, own)
    resolver = Resolver(settings, own, archive)
    plans = []

    for match in matches:
        plan = _base(match)
        key = plan['key']
        nicks = {'blue': _nicks(match, 'blue'), 'red': _nicks(match, 'red')}
        options = pair_options(nicks, own, opponents, archive)
        best_any = min(options, key=lambda o: (-o['hits'], o['diff'], o['cross'])) if options else None

        # 教练已经判断过：整局建档，不再做匹配推断。
        if key in clean_decisions:
            decision = clean_decisions[key]
            state = resolver.snapshot()
            try:
                own_camp = decision['ownCamp']
                opp_camp = 'red' if own_camp == 'blue' else 'blue'
                sides = [resolver.bind_side(own_camp, own, nicks[own_camp], True, infer=False),
                         resolver.bind_side(opp_camp, decision['opponent'], nicks[opp_camp], False, infer=False)]
                resolver.teams.add(decision['opponent'])
                resolver.metas.append({'key': key, 'ownCamp': own_camp, 'opponent': decision['opponent']})
                plan.update({
                    'status': 'decided', 'ownCampPlan': own_camp, 'opponent': decision['opponent'],
                    'sides': sides,
                    'reason': f"按教练判断建档：本队{CAMP_NAME[own_camp]}、对手「{decision['opponent']}」；"
                              f"{sum(len(s['binds']) for s in sides)} 个昵称已认领，下一次同类对局可自动匹配",
                    'notes': ['这次判断会写进存档，之后再遇到同一批昵称就能自动认领'],
                })
            except CapacityError as error:
                resolver.restore(state)
                _review(plan, str(error), ['请先到「管理与建档」整理选手名单，再回来自动认领'])
            plans.append(plan)
            continue

        if not opponents:
            _review(plan, '还没有对手战队存档',
                    ['先由教练在下面判断一局「本队在哪边 + 对手是谁」，之后同类对局就能自动匹配'])
            plans.append(plan)
            continue

        if not (archive.get(own) or {}):
            _review(plan, f'还没有「{own}」的存档名单',
                    ['先由教练判断一局，把两边十个人的昵称认领下来，系统才有比对依据'])
            plans.append(plan)
            continue

        valid = [o for o in options
                 if o['ownScore']['diff'] <= max_diff and o['oppScore']['diff'] <= max_diff
                 and o['cross'] == 0]
        if not valid and best_any:
            missing = []
            for label, camp_score in (('本队', best_any['ownScore']), ('对手', best_any['oppScore'])):
                if camp_score['diff'] > max_diff:
                    missing.append(f"{label}侧 {camp_score['diff']} 个没见过的昵称"
                                   f"（{'、'.join(camp_score['unknown'][:5])}）")
            if not missing and best_any['cross']:
                _review(plan, '同一批昵称同时出现在本队和对手的存档里，分边存疑',
                        ['多半是分边记反了或存档有串号，请教练确认本队在哪边、对手是谁'])
            else:
                detail = '；'.join(missing) or '两侧名单都对不上'
                _review(plan, detail + '，可能是开小号，也可能是约到了新对手',
                        ['这类对局交给教练：确认本队在哪边、对手是谁，判断结果会成为下一次的存档'])
            plans.append(plan)
            continue
        if not valid:
            _review(plan, '存档名单还不足以判断分边')
            plans.append(plan)
            continue

        valid.sort(key=lambda o: (-o['hits'], o['diff'], o['cross'],
                                  0 if o['ownCamp'] == plan['hintCamp'] else 1))
        best = valid[0]
        tied = [o for o in valid[1:] if o['hits'] == best['hits'] and o['diff'] == best['diff']]
        if tied:
            _review(plan, '有多支战队都能对上这局名单，无法唯一确定对手',
                    ['请教练指定对手战队；指定后这一批里的同类对局会自动跟随'])
            plans.append(plan)
            continue

        if plan['hintCamp'] in ('blue', 'red') and plan['hintCamp'] != best['ownCamp']:
            _review(plan, f"存档名单显示本队在{CAMP_NAME[best['ownCamp']]}，但本局原始记录是"
                          f"{CAMP_NAME[plan['hintCamp']]}，两边对不上",
                    ['不自动翻边；请教练确认本队在哪边，确认后会覆盖原始分边'])
            plans.append(plan)
            continue

        state = resolver.snapshot()
        try:
            own_camp = best['ownCamp']
            opp_camp = 'red' if own_camp == 'blue' else 'blue'
            sides = [resolver.bind_side(own_camp, own, nicks[own_camp], True),
                     resolver.bind_side(opp_camp, best['opponent'], nicks[opp_camp], False)]
            resolver.teams.add(best['opponent'])
            resolver.metas.append({'key': key, 'ownCamp': own_camp, 'opponent': best['opponent']})
            inferred = sum(1 for s in sides for b in s['binds'] if b['source'] == 'inferred')
            created = sum(1 for s in sides for b in s['binds'] if b['source'] == 'new')
            pieces = [f"{CAMP_NAME[s['camp']]} {s['hits']}/{len(s['binds'])} 命中「{s['team']}」" for s in sides]
            notes = []
            if inferred:
                notes.append(f'{inferred} 个新昵称按小号合并到缺的那位（可在下拉里改绑）')
            if created:
                notes.append(f'{created} 个全新昵称自动建档（如为小号，教练可改绑到原身份）')
            plan.update({
                'status': 'auto', 'ownCampPlan': own_camp, 'opponent': best['opponent'],
                'sides': sides, 'reason': '；'.join(pieces), 'notes': notes,
            })
        except CapacityError as error:
            resolver.restore(state)
            _review(plan, str(error), ['请先到「管理与建档」整理选手名单，再回来自动认领'])
        plans.append(plan)

    counts = {status: sum(1 for p in plans if p['status'] == status)
              for status in ('auto', 'decided', 'review')}
    return {
        'summary': {
            'total': len(plans), **counts, 'maxDiff': max_diff,
            'archiveTeams': {team: len(nicks) for team, nicks in sorted(archive.items())},
            'coldStart': not archive,
        },
        'options': {'teams': opponents, 'ownTeam': own, 'maxDiffChoices': [0, 1, 2]},
        'matches': plans,
        'deltas': resolver.deltas(),
    }
