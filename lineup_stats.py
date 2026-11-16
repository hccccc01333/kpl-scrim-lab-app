"""阵容体系统计引擎（P0-2，docs/team_dossier_p0.md §2）。

五路类型签名、双人 / 三人位置组合、战术功能标签、五人英雄阵容与红蓝方拆分
的统一统计；后端唯一实现，前端不得自行计算。

口径（§2.2，改口径先改文档再改这里）：
- 有效场次 N_eff = 五路均可定位的局（picks 齐全、无重复分路）；缺路 / 重复路的局
  记 nIncomplete，不进任何统计；
- 五路签名含「待分类」的局计入 N_eff 并进 unknownRow，不进任何具体签名行；
- 双人 / 三人组合：涉及「待分类」路的组合不计入分子分母（只剔除涉事组合，
  其余仍可识别的位置对正常累计）；
- 胜率分母 = 结果已知的局（win 非空）；结果已知 < 3 局不输出胜率与区间；
- 组合按 (match, team) 去重由调用方保证：本引擎每个 game 只计一次；
- 排序：场次降序 → 胜场降序 → 名称。

输入 games 项：{'seq': str, 'win': bool | None, 'side': 'blue' | 'red' | None,
                'picks': [{'name': str, 'lane': str, 'archetype': str}, ...]}

用法：
    from lineup_stats import team_lineups
    lineups = team_lineups([{...}, ...])
"""
from __future__ import annotations

import math
from collections import defaultdict

from hero_archetypes import LANES, OTHER as PENDING

# 五个预置双人位置对（docs/team_dossier_p0.md §2.3）
PAIR_FAMILIES: tuple[tuple[str, str, str], ...] = (
    ('边野', '对抗路', '打野'),
    ('中野', '打野', '中路'),
    ('射辅', '发育路', '游走'),
    ('中辅', '中路', '游走'),
    ('野辅', '打野', '游走'),
)

# 五个预置三人组合（§2.3）
TRIAD_FAMILIES: tuple[tuple[str, str, str, str], ...] = (
    ('中野辅', '打野', '中路', '游走'),
    ('边野辅', '对抗路', '打野', '游走'),
    ('中射辅', '中路', '发育路', '游走'),
    ('野射辅', '打野', '发育路', '游走'),
    ('边中野', '对抗路', '打野', '中路'),
)

WR_MIN_DECIDED = 3  # 结果已知局数达到 3 才输出胜率与区间（验收口径）


def wilson(wins: int, games: int, *, z: float = 1.96) -> list[float] | None:
    """Wilson 95% 区间，返回 [下界%, 上界%]（1 位小数）；n<=0 返回 None。"""
    if games <= 0:
        return None
    p = wins / games
    z2 = z * z
    denom = 1 + z2 / games
    center = (p + z2 / (2 * games)) / denom
    half = z * math.sqrt(p * (1 - p) / games + z2 / (4 * games * games)) / denom
    lo = max(0.0, center - half) * 100
    hi = min(1.0, center + half) * 100
    return [round(lo, 1), round(hi, 1)]


def signature_of(picks) -> tuple[str, ...] | None:
    """五路类型签名（对抗→打野→中路→发育→游走）；分路缺失 / 重复返回 None。

    未识别类型（None / 其他）记「待分类」；签名照常生成，由上层进 unknownRow。
    """
    slots: dict[str, str] = {}
    for pick in picks or []:
        lane = pick.get('lane')
        if not lane:
            return None
        if lane in slots:
            return None
        arch = pick.get('archetype') or PENDING
        slots[lane] = PENDING if arch == '其他' else arch
    if set(slots) != set(LANES):
        return None
    return tuple(slots[lane] for lane in LANES)


def _lane_types(picks) -> dict[str, str] | None:
    sig = signature_of(picks)
    return dict(zip(LANES, sig)) if sig else None


def _heroes_in_lane_order(picks) -> tuple[str, ...] | None:
    """按固定分路序取 5 个英雄名；缺名 / 重复返回 None。"""
    by_lane: dict[str, str] = {}
    for pick in picks or []:
        lane, name = pick.get('lane'), pick.get('name')
        if not lane or not name or lane in by_lane:
            return None
        by_lane[lane] = name
    if set(by_lane) != set(LANES):
        return None
    return tuple(by_lane[lane] for lane in LANES)


def _new_acc() -> dict:
    return {'games': 0, 'wins': 0, 'losses': 0, 'refs': []}


def _add(acc: dict, game: dict) -> None:
    acc['games'] += 1
    win = game.get('win')
    if win is True:
        acc['wins'] += 1
    elif win is False:
        acc['losses'] += 1
    seq = game.get('seq')
    if seq:
        acc['refs'].append(str(seq))


def _finish(acc: dict) -> dict:
    decided = acc['wins'] + acc['losses']
    show = decided >= WR_MIN_DECIDED
    return {
        'games': acc['games'],
        'wins': acc['wins'],
        'losses': acc['losses'],
        'wr': round(100 * acc['wins'] / decided, 1) if show else None,
        'wilson': wilson(acc['wins'], decided) if show else None,
        'gamesRef': acc['refs'],
    }


def _sorted_rows(rows: list, key_name: str) -> list:
    return sorted(rows, key=lambda r: (-r['games'], -r['wins'], r[key_name]))


def team_lineups(games) -> dict:
    """一支战队（本队视角）的阵容体系统计总表。"""
    sig_acc: dict[tuple, dict] = {}
    unknown_acc = _new_acc()
    unknown_sigs: dict[tuple, int] = defaultdict(int)
    pair_acc: dict[str, dict[tuple, dict]] = {family: defaultdict(_new_acc)
                                              for family, _l1, _l2 in PAIR_FAMILIES}
    triad_acc: dict[str, dict[tuple, dict]] = {family: defaultdict(_new_acc)
                                               for family, _l1, _l2, _l3 in TRIAD_FAMILIES}
    func_acc: dict[tuple, dict] = defaultdict(_new_acc)
    hero_acc: dict[tuple, dict] = defaultdict(_new_acc)
    side_acc: dict[str, dict] = defaultdict(lambda: {'games': 0, 'wins': 0, 'losses': 0})

    n_eff = n_incomplete = n_unknown = 0
    for game in games or []:
        picks = game.get('picks') or []
        if signature_of(picks) is None:
            n_incomplete += 1
            continue
        n_eff += 1
        sig = signature_of(picks)
        lane_types = dict(zip(LANES, sig))
        if PENDING in sig:
            n_unknown += 1
            _add(unknown_acc, game)
            unknown_sigs[sig] += 1
        else:
            acc = sig_acc.setdefault(sig, {**_new_acc(), 'heroSets': defaultdict(int)})
            _add(acc, game)
            heroes = _heroes_in_lane_order(picks)
            if heroes:
                acc['heroSets'][heroes] += 1
        # 双人 / 三人：只剔除涉事组合，其余可识别位置对正常累计
        for family, l1, l2 in PAIR_FAMILIES:
            t1, t2 = lane_types[l1], lane_types[l2]
            if PENDING in (t1, t2):
                continue
            _add(pair_acc[family][(t1, t2)], game)
        for family, l1, l2, l3 in TRIAD_FAMILIES:
            types = (lane_types[l1], lane_types[l2], lane_types[l3])
            if PENDING in types:
                continue
            _add(triad_acc[family][types], game)
        # 五人英雄阵容（下钻证据层）：只要求英雄名齐全，与类型识别无关
        heroes = _heroes_in_lane_order(picks)
        if heroes:
            _add(hero_acc[heroes], game)
        # 战术功能标签：五人能力全部收录才计算（不猜短板）
        if heroes and all(h in _known_caps() for h in heroes):
            import hero_capabilities
            tags = tuple(hero_capabilities.functional_tags(heroes))
            if tags:
                _add(func_acc[tags], game)
        side = game.get('side')
        bucket = side_acc['blue' if side == 'blue' else 'red' if side == 'red' else 'unknown']
        bucket['games'] += 1
        win = game.get('win')
        if win is True:
            bucket['wins'] += 1
        elif win is False:
            bucket['losses'] += 1

    signature_rows = []
    for sig, acc in sig_acc.items():
        row = _finish(acc)
        row.update({
            'sig': list(sig),
            'heroSets': [list(heroes) for heroes, _n in
                         sorted(acc['heroSets'].items(), key=lambda kv: (-kv[1], kv[0]))],
        })
        signature_rows.append(row)

    pair_rows = []
    for family, _l1, _l2 in PAIR_FAMILIES:
        for pair, acc in pair_acc[family].items():
            row = _finish(acc)
            row.update({'family': family, 'pair': list(pair)})
            pair_rows.append(row)
    pair_rows.sort(key=lambda r: (next(i for i, (f, _a, _b) in enumerate(PAIR_FAMILIES)
                                       if f == r['family']), -r['games'], -r['wins'], r['pair']))

    triad_rows = []
    for family, _l1, _l2, _l3 in TRIAD_FAMILIES:
        for triad, acc in triad_acc[family].items():
            row = _finish(acc)
            row.update({'family': family, 'triad': list(triad)})
            triad_rows.append(row)
    triad_rows.sort(key=lambda r: (next(i for i, (f, _a, _b, _c) in enumerate(TRIAD_FAMILIES)
                                        if f == r['family']), -r['games'], -r['wins'], r['triad']))

    function_rows = []
    for tags, acc in func_acc.items():
        row = _finish(acc)
        row.update({'tags': list(tags)})
        function_rows.append(row)
    function_rows = _sorted_rows(function_rows, 'tags')

    hero_rows = []
    for heroes, acc in hero_acc.items():
        row = _finish(acc)
        row.update({'heroes': list(heroes)})
        hero_rows.append(row)
    hero_rows = _sorted_rows(hero_rows, 'heroes')

    unknown_row = _finish(unknown_acc)
    unknown_row.update({
        'sigs': [{'sig': list(sig), 'games': n} for sig, n in
                 sorted(unknown_sigs.items(), key=lambda kv: (-kv[1], kv[0]))[:5]],
        'sigKinds': len(unknown_sigs),
    })

    return {
        'nEff': n_eff,
        'nIncomplete': n_incomplete,
        'nUnknown': n_unknown,
        'signature': signature_rows,
        'unknownRow': unknown_row,
        'pairs': pair_rows,
        'triads': triad_rows,
        'functions': function_rows,
        'fiveHero': hero_rows,
        'side': {key: side_acc[key] for key in ('blue', 'red', 'unknown')
                 if side_acc[key]['games'] or key != 'unknown'},
    }


EVIDENCE_ESTABLISHED_MIN = 10  # 证据等级「倾向性发现」的最低局数（docs/team_dossier_p0.md §3.2）


def _mean(values):
    """已知值均值（1 位小数）；全缺返回 None，不补 0。"""
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def lineup_resources(games) -> list[dict]:
    """按五路类型签名聚合的资源对照（P2，上游设计 §4.1）。

    资源只汇总十人面板可用的局：占比按已知值计算（缺谁不补 0），与
    team-deep 逐人卡口径一致；panelGames < games 时页面必须标注子集。
    含「待分类」路的体系无法归入具体签名，不计入。
    games 项需带 players / stats / oppStats（见 team_clusters._enemy_lineup_games）。
    """
    buckets: dict[tuple, dict] = {}
    for game in games or []:
        sig = signature_of(game.get('picks'))
        if sig is None or PENDING in sig:
            continue
        acc = buckets.setdefault(sig, {
            'games': 0, 'panel': 0, 'wins': 0, 'losses': 0, 'refs': [],
            'lanes': {lane: {'gold': [], 'dmg': [], 'taken': []} for lane in LANES},
            'top1': [], 'towers': [], 'dragons': [], 'goldDiff': [],
        })
        acc['games'] += 1
        win = game.get('win')
        if win is True:
            acc['wins'] += 1
        elif win is False:
            acc['losses'] += 1
        if game.get('seq'):
            acc['refs'].append(str(game['seq']))
        players = [p for p in game.get('players') or [] if p.get('lane') in acc['lanes']]
        golds = [(p['lane'], p.get('gold')) for p in players if p.get('gold') is not None]
        if golds:
            acc['panel'] += 1
            total = sum(g for _lane, g in golds)
            if total > 0:
                acc['top1'].append(max(g for _lane, g in golds) / total * 100)
            for lane, gold in golds:
                acc['lanes'][lane]['gold'].append(gold / total * 100)
        dmgs = [(p['lane'], p.get('heroDamage')) for p in players if p.get('heroDamage') is not None]
        if dmgs:
            total = sum(d for _lane, d in dmgs)
            if total > 0:
                for lane, d in dmgs:
                    acc['lanes'][lane]['dmg'].append(d / total * 100)
        tkns = [(p['lane'], p.get('taken')) for p in players if p.get('taken') is not None]
        if tkns:
            total = sum(t for _lane, t in tkns)
            if total > 0:
                for lane, t in tkns:
                    acc['lanes'][lane]['taken'].append(t / total * 100)
        stats = game.get('stats') or {}
        if stats.get('towers') is not None:
            acc['towers'].append(stats['towers'])
        if stats.get('dragons') is not None:
            acc['dragons'].append(stats['dragons'])
        opp_gold = (game.get('oppStats') or {}).get('gold')
        if stats.get('gold') is not None and opp_gold is not None:
            acc['goldDiff'].append(stats['gold'] - opp_gold)
    rows = []
    for sig, acc in buckets.items():
        if not acc['panel']:
            continue
        decided = acc['wins'] + acc['losses']
        rows.append({
            'sig': list(sig),
            'games': acc['games'],
            'panelGames': acc['panel'],
            'wr': round(100 * acc['wins'] / decided, 1) if decided >= WR_MIN_DECIDED else None,
            'lanes': {lane: {'goldShare': _mean(v['gold']),
                             'dmgShare': _mean(v['dmg']),
                             'takenShare': _mean(v['taken'])}
                      for lane, v in acc['lanes'].items()},
            'top1Share': _mean(acc['top1']),
            'towers': _mean(acc['towers']),
            'dragons': _mean(acc['dragons']),
            'goldDiff': _mean(acc['goldDiff']),
            'gamesRef': acc['refs'],
        })
    rows.sort(key=lambda r: (-r['games'], -r['panelGames'], r['sig']))
    return rows


def _evidence_level(n, wr, wilson_range, baseline):
    """三档证据等级（§3.2）：n<3 证据不足；n≥10 且区间不跨基准为倾向性发现；其余初步观察。"""
    if n < WR_MIN_DECIDED:
        return 'insufficient'
    if (n >= EVIDENCE_ESTABLISHED_MIN and wilson_range and baseline is not None
            and (wilson_range[0] > baseline or wilson_range[1] < baseline)):
        return 'established'
    return 'initial'


def matchup_matrix(games) -> dict:
    """阵容对抗矩阵（P2，上游设计 §5）：对象体系 × 对手体系的历史关联。

    只输出历史关联，不写克制因果；格内只计双方五路类型均可识别的局。
    baselineDiff = 格内胜率 − 该对象体系的整体胜率（同批对局，rowBaselines）。
    games 项需带 oppPicks（见 team_clusters._enemy_lineup_games）。
    """
    cells: dict[tuple, dict] = {}
    row_totals: dict[tuple, dict] = {}
    for game in games or []:
        row_sig = signature_of(game.get('picks'))
        col_sig = signature_of(game.get('oppPicks'))
        if row_sig is None or col_sig is None or PENDING in row_sig or PENDING in col_sig:
            continue
        win = game.get('win')
        for table, key in ((cells, (row_sig, col_sig)), (row_totals, row_sig)):
            acc = table.setdefault(key, {'games': 0, 'wins': 0, 'losses': 0, 'refs': [],
                                         'side': {'blue': [0, 0], 'red': [0, 0]}})
            acc['games'] += 1
            if win is True:
                acc['wins'] += 1
            elif win is False:
                acc['losses'] += 1
            if game.get('seq'):
                acc['refs'].append(str(game['seq']))
            side = game.get('side')
            if side in ('blue', 'red'):
                acc['side'][side][0] += 1
                if win is True:
                    acc['side'][side][1] += 1

    def _wr(acc):
        decided = acc['wins'] + acc['losses']
        if decided < WR_MIN_DECIDED:
            return None, None, decided
        return round(100 * acc['wins'] / decided, 1), wilson(acc['wins'], decided), decided

    rows = []
    for (row_sig, col_sig), acc in cells.items():
        wr, wilson_range, decided = _wr(acc)
        baseline, _bw, _bd = _wr(row_totals[row_sig])
        diff = (round(wr - baseline, 1)
                if wr is not None and baseline is not None else None)
        rows.append({
            'row': list(row_sig),
            'col': list(col_sig),
            'n': acc['games'],
            'wins': acc['wins'],
            'losses': acc['losses'],
            'wr': wr,
            'wilson': wilson_range,
            'baseline': baseline,
            'baselineDiff': diff,
            'evidenceLevel': _evidence_level(decided, wr, wilson_range, baseline),
            'side': {'blue': {'games': acc['side']['blue'][0], 'wins': acc['side']['blue'][1]},
                     'red': {'games': acc['side']['red'][0], 'wins': acc['side']['red'][1]}},
            'gamesRef': acc['refs'],
        })
    rows.sort(key=lambda r: (r['row'], -r['n'], r['col']))
    baselines = []
    for sig, acc in row_totals.items():
        wr, wilson_range, decided = _wr(acc)
        baselines.append({'sig': list(sig), 'games': acc['games'], 'wins': acc['wins'],
                          'losses': acc['losses'], 'decided': decided,
                          'wr': wr, 'wilson': wilson_range})
    baselines.sort(key=lambda b: (-b['games'], b['sig']))
    return {'cells': rows, 'rowBaselines': baselines}


def _known_caps() -> set:
    """能力矩阵收录的英雄集合（模块级缓存，避免逐局 import 开销）。"""
    global _KNOWN_CAPS_CACHE
    if _KNOWN_CAPS_CACHE is None:
        import hero_capabilities
        _KNOWN_CAPS_CACHE = set(hero_capabilities.HERO_CAPABILITIES)
    return _KNOWN_CAPS_CACHE


_KNOWN_CAPS_CACHE: set | None = None
