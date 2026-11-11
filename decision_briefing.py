"""赛训首页「今天先看这几个问题」。

把 P0 分析各自的聚合结果压成 3–5 条教练可以直接行动的问题卡：

- 只陈述观察到的数字与比率，不写「因为」。
- 小样本（n<10 / 每名对手 1 局）自动降级 confidence，并强制写 caveat。
- 数据不足时宁可不产生条目，也不硬凑；始终返回 skipped 说明原因。
- 每次调用都按当前数据范围重新计算候选、重新排序，结果带 scope/fingerprint，
  首页可以显示「本次评估了几类信号、为什么是这几条」。

排序：severity（high > medium > low）→ 涉及样本 n 降序 → 固定 kind 顺序。
"""
from __future__ import annotations

import hashlib
import json

SEVERITY_ORDER = {'high': 0, 'medium': 1, 'low': 2}
KIND_ORDER = {
    'comeback_leak': 0, 'loss_pattern': 1, 'slow_conversion': 2, 'fight_arrival': 3,
    'resource_mismatch': 4, 'opening_habit': 5, 'coverage_gap': 6, 'training_gap': 7,
}


def _confidence(n, *, cap='high'):
    level = 'high' if (n or 0) >= 10 else ('medium' if (n or 0) >= 5 else 'low')
    if SEVERITY_ORDER[cap] > SEVERITY_ORDER[level]:
        return cap
    return level


def _game_index(facts):
    return {seq: facts['games'][seq] for seq in facts.get('order') or []}


def _evidence_from_games(games, *, limit=4):
    out = []
    seen = set()
    for game in games:
        game_id = str(game.get('id') or game.get('game') or '')
        if not game_id or game_id in seen:
            continue
        candidates = game.get('candidates') or []
        candidate = candidates[0] if candidates else None
        out.append({
            'game': game_id,
            'label': game.get('label') or game_id,
            't': (candidate or {}).get('t'),
            'kind': (candidate or {}).get('kind') or 'game',
            'text': (candidate or {}).get('text') or (game.get('label') or game_id),
        })
        seen.add(game_id)
        if len(out) >= limit:
            return out
    return out[:limit]


def _clamp_evidence(facts, game_ids, limit=4):
    """把 game id 转成可点击证据（至少给对局入口）。"""
    games = _game_index(facts)
    out = []
    for game_id in game_ids:
        game = games.get(str(game_id))
        if not game:
            continue
        out.append({
            'game': game['id'], 'label': game['label'],
            't': None, 'kind': 'game',
            'text': f"{game['label']}（{game.get('result') or '结果未知'}）",
        })
        if len(out) >= limit:
            break
    return out


def _safe(report, skipped, name, label):
    if isinstance(report, dict) and report.get('available') is False:
        skipped.append({'analysis': name, 'reason': report.get('reason') or '数据不足'})
        return None
    if not isinstance(report, dict):
        skipped.append({'analysis': name, 'reason': f'{label}暂不可用'})
        return None
    return report


def _comeback_item(facts, advantage, skipped):
    summary = (advantage or {}).get('summary') or {}
    led = summary.get('ledGames') or 0
    comebacks = summary.get('comebacks') or 0
    if led < 3 or comebacks < 2:
        skipped.append({
            'analysis': 'advantage_retention',
            'reason': f'曾领先 ≥1000 的局只有 {led} 局、被翻盘 {comebacks} 局，不足以形成重复模式',
        })
        return None
    marked = [game for game in (advantage.get('games') or []) if game.get('comeback')]
    rate = summary.get('comebackRate')
    drawdown = summary.get('avgDrawdown')
    detail_parts = [f'{led} 局曾在任意时刻领先 ≥1000，其中 {comebacks} 局最终失利']
    if rate is not None:
        detail_parts.append(f'被翻盘率 {rate:.1f}%')
    if drawdown is not None:
        detail_parts.append(f'领先后的平均回撤 {round(drawdown):,} 金币')
    if summary.get('avgLeadAt10') is not None:
        detail_parts.append(f'这些局 10 分钟平均经济差 {round(summary["avgLeadAt10"]):,}')
    if summary.get('enough') is False:
        detail_parts.append('样本不足 10 局，只作为观察')
    return {
        'id': 'comeback-leak',
        'kind': 'comeback_leak',
        'severity': 'high' if comebacks >= 3 else 'medium',
        'title': f'曾领先 ≥1000 的 {led} 局里丢了 {comebacks} 局',
        'detail': '；'.join(detail_parts) + '。先回看最大回撤局，确认是推进断档还是被一波团战打回。',
        'n': led,
        'confidence': _confidence(led, cap='medium'),
        'caveat': '翻盘是结果描述，不是因果；回撤窗口附近的事件只作候选证据。',
        'analysis': 'advantage_retention',
        'evidence': _evidence_from_games(marked, limit=4),
        'link': '/decision?tab=review',
    }


def _loss_pattern_item(facts, loss, skipped):
    summary = (loss or {}).get('summary') or {}
    patterns = summary.get('patterns') or []
    candidates = [item for item in patterns
                  if (item.get('windows') or 0) >= 3 and (item.get('games') or 0) >= 2]
    if not candidates:
        skipped.append({'analysis': 'loss_chain',
                        'reason': '负向经济窗口还不够形成重复类别（需 ≥3 个窗口、≥2 局）'})
        return None
    best = sorted(candidates, key=lambda item: (-(item.get('windows') or 0),
                                                -(item.get('games') or 0)))[0]
    windows, games = best.get('windows') or 0, best.get('games') or 0
    cost = best.get('avgCost')
    by_phase = [item for item in (summary.get('byPhase') or []) if (item.get('windows') or 0) > 0]
    phase_text = ''
    if by_phase:
        phase = max(by_phase, key=lambda item: abs(item.get('cost') or 0))
        phase_text = f"最伤的一段在{phase.get('phase')}（累计 {round(phase.get('cost') or 0):,}）"
        if summary.get('losses') is not None:
            phase_text += '。'
    detail = f"{windows} 个窗口、涉及 {games} 局，类别为「{best.get('typeLabel') or best.get('label') or best.get('type')}」"
    if cost is not None:
        detail += f"，窗口内平均经济差变化 {round(cost):,}"
    detail += '。' + (phase_text or '先按类别回看证据窗口。')
    evidence, seen = [], set()
    for item in (best.get('evidence') or []):
        game_id = str(item.get('game') or '')
        if not game_id or game_id in seen:
            continue
        seen.add(game_id)
        evidence.append({
            'game': game_id, 'label': item.get('label') or game_id,
            't': item.get('start'), 'kind': 'swing',
            'text': item.get('text') or f"{item.get('typeLabel') or item.get('type')} · 经济差 {round(item.get('delta') or 0):,}",
        })
        if len(evidence) >= 4:
            break
    return {
        'id': f"loss-{best.get('type') or 'pattern'}",
        'kind': 'loss_pattern',
        'severity': 'high' if games >= 4 else 'medium',
        'title': f"反复出现的失利窗口：{best.get('typeLabel') or best.get('label') or best.get('type')}（{games} 局）",
        'detail': detail,
        'n': games,
        'confidence': _confidence(games, cap='medium'),
        'caveat': '这些是经济损失窗口内同时出现的候选事件，不证明因果；同一波事件会落在多个长度窗口里，'
                  '窗口数会重复计数，先按局看。',
        'analysis': 'loss_chain',
        'evidence': evidence,
        'link': '/decision?tab=review',
    }


def _slow_conversion_item(facts, advantage, skipped):
    games = [game for game in (advantage or {}).get('games') or []
             if game.get('conversionSec') is not None]
    if len(games) < 5:
        skipped.append({'analysis': 'advantage_retention',
                        'reason': f'有「领先→下一次拿资源/推塔」时间差的局只有 {len(games)} 局，需 ≥5 局'})
        return None
    slow = [game for game in games if (game.get('conversionSec') or 0) > 120]
    ratio = len(slow) / len(games) * 100
    if ratio < 50:
        skipped.append({'analysis': 'advantage_retention',
                        'reason': f'超过 120 秒才兑现的局只有 {len(slow)}/{len(games)}，未形成模式'})
        return None
    return {
        'id': 'slow-conversion',
        'kind': 'slow_conversion',
        'severity': 'medium',
        'title': f'领先后 {len(slow)}/{len(games)} 局超过 2 分钟才拿到下一个资源或塔',
        'detail': '领先之后优先看推进/控龙时间点：是不是拿到了优势但节奏停了。',
        'n': len(games),
        'confidence': _confidence(len(games), cap='medium'),
        'caveat': '兑现时间来自经济点插值事件，时间精度约 ±30 秒；只描述节奏，不评价指挥。',
        'analysis': 'advantage_retention',
        'evidence': _clamp_evidence(facts, [game.get('id') for game in slow], limit=4),
        'link': '/decision?tab=review',
    }


def _fight_arrival_item(facts, fights, skipped):
    summary = (fights or {}).get('summary') or {}
    buckets = summary.get('openingBuckets') or []
    behind = [item for item in buckets if (item.get('advStart') or 0) <= -2]
    even = [item for item in buckets if (item.get('advStart') or 0) >= 0]
    behind_n = sum(item.get('n') or 0 for item in behind)
    behind_w = sum(item.get('wins') or 0 for item in behind)
    even_n = sum(item.get('n') or 0 for item in even)
    even_w = sum(item.get('wins') or 0 for item in even)
    if behind_n < 8 or even_n < 8:
        skipped.append({'analysis': 'fight_execution',
                        'reason': f'人数落后 (-2 人及以下) {behind_n} 场 / 人数不落后 {even_n} 场，各需 ≥8 场'})
        return None
    behind_rate = behind_w / behind_n * 100
    even_rate = even_w / even_n * 100
    if even_rate - behind_rate < 20:
        skipped.append({'analysis': 'fight_execution',
                        'reason': f'开局人数差与团战胜率差只有 {even_rate - behind_rate:.1f} 个百分点，未形成模式'})
        return None
    evidence, seen = [], set()
    for item in (fights.get('rows') or []):
        game_id = str(item.get('game') or '')
        if not game_id or game_id in seen:
            continue
        seen.add(game_id)
        evidence.append({
            'game': game_id, 'label': item.get('label') or game_id,
            't': item.get('startSec'), 'kind': 'fight',
            'text': f"开局 {item.get('advStart')} 人 · 击杀差 {item.get('killDiff')}",
        })
        if len(evidence) >= 4:
            break
    return {
        'id': 'fight-arrival',
        'kind': 'fight_arrival',
        'severity': 'high',
        'title': f'团战开局就少人时胜率 {behind_rate:.0f}%，人数不落后时 {even_rate:.0f}%',
        'detail': f'人数落后 2 人及以上的 {behind_n} 场团战只赢 {behind_w} 场；'
                  f'人数持平或领先的 {even_n} 场赢 {even_w} 场。先看「等人再打」和开团沟通。',
        'n': behind_n + even_n,
        'confidence': _confidence(min(behind_n, even_n), cap='medium'),
        'caveat': '团战胜负按击杀差判定；人数差是团战开始 3 秒内的到达人数，不含随后进场的人。',
        'analysis': 'fight_execution',
        'evidence': evidence,
        'link': '/decision?tab=review',
    }


def _resource_item(facts, resource, skipped):
    anomalies = (resource or {}).get('anomalies') or []
    if len(anomalies) < 2:
        skipped.append({'analysis': 'resource_allocation',
                        'reason': f'达到复核线的资源分配条目只有 {len(anomalies)} 条'})
        return None
    top = sorted(anomalies, key=lambda item: -(item.get('gap') or 0))[:3]
    names = '、'.join(f"{item.get('name') or ''}{('（' + item.get('hero') + '）') if item.get('hero') else ''}"
                      for item in top if item.get('name'))
    return {
        'id': 'resource-mismatch',
        'kind': 'resource_mismatch',
        'severity': 'medium',
        'title': f'{len(anomalies)} 条资源分配值得复核：高经济低输出 / 发育路死亡偏多',
        'detail': (f'优先看 {names}。' if names else '') +
                  '四象限只用于发现异常，不等于选手评价；辅助请改看控制/治疗。',
        'n': len((resource or {}).get('players') or []),
        'confidence': _confidence(len(anomalies), cap='medium'),
        'caveat': '经济=营地 money，输出=totalHeroHurtCnt；两者不同口径，不直接换算。',
        'analysis': 'resource_allocation',
        'evidence': _clamp_evidence(
            facts, [item.get('seq') for item in top], limit=4),
        'link': '/decision?tab=player',
    }


def _opening_item(facts, opening, skipped, opponent):
    if opponent:
        selected = (opening or {}).get('selected') or {}
        if selected.get('enough') is False:
            skipped.append({'analysis': 'opening_routes',
                            'reason': f"该对手只有 {selected.get('games') or 0} 局回放，不能输出固定开局套路"})
            return None
        routes = (opening or {}).get('routes') or []
        habits = [route for route in routes if (route.get('count') or 0) >= 3]
        if not habits:
            skipped.append({'analysis': 'opening_routes', 'reason': '没有出现 ≥3 次的同一路线簇'})
            return None
        best = habits[0]
        return {
            'id': 'opening-habit',
            'kind': 'opening_habit',
            'severity': 'medium',
            'title': f"对手在 {best.get('lane') or '开局'} 有一类重复路线（{best.get('count')} 次）",
            'detail': f"路线经过 {' → '.join(best.get('zoneSequence') or []) or '—'}；"
                      "赛前可以针对这条路线做开局布置。",
            'n': selected.get('games') or 0,
            'confidence': _confidence(best.get('count') or 0, cap='medium'),
            'caveat': '只统计平台收录的回放，不能推断对手全部比赛习惯。',
            'analysis': 'opening_routes',
            'evidence': [],
            'link': '/decision?tab=prep',
        }
    skipped.append({
        'analysis': 'opening_routes',
        'reason': '每名对手目前只有 1 局回放（32 个对手 / 23 局），对手固定套路类结论不成立，只做单局观察',
    })
    return None


def _late_join_item(facts, fights, skipped):
    """团战迟到：有明确「开团 5 秒后才到」的人次。"""
    summary = (fights or {}).get('summary') or {}
    rate = summary.get('lateJoinRate')
    participants = summary.get('ownParticipants') or 0
    late = summary.get('lateJoins') or 0
    if rate is None or participants < 100:
        skipped.append({'analysis': 'fight_execution',
                        'reason': f'我方团战参战 {participants} 人次，需 ≥100 才评估迟到率'})
        return None
    if rate < 10 or late < 10:
        skipped.append({'analysis': 'fight_execution',
                        'reason': f'迟到率 {rate:.1f}%（{late} 人次），还没到 10% 的观察线'})
        return None
    evidence, seen = [], set()
    for row in (fights.get('rows') or []):
        if not row.get('lateJoins'):
            continue
        game_id = str(row.get('game') or '')
        if not game_id or game_id in seen:
            continue
        seen.add(game_id)
        evidence.append({
            'game': game_id, 'label': row.get('label') or game_id,
            't': row.get('startSec'), 'kind': 'fight',
            'text': f"团战 {row.get('timeLabel') or ''} · 我方 {row.get('lateJoins')} 人迟到",
        })
        if len(evidence) >= 4:
            break
    late_fights = sum(1 for row in (fights.get('rows') or []) if row.get('lateJoins'))
    return {
        'id': 'late-join',
        'kind': 'late_join',
        'severity': 'medium',
        'title': f'团战迟到率 {rate:.0f}%：{late} 人次在开团 5 秒后才到',
        'detail': f'我方共 {participants} 人次参团，{late_fights} 场团战有人迟到；先看「等队友到位再开」是不是训练点。',
        'n': late_fights or participants,
        'confidence': _confidence(participants, cap='medium'),
        'caveat': '迟到按参战记录时刻计算，不含未参团的人；开团时刻是回放团战段的开始秒。',
        'analysis': 'fight_execution',
        'evidence': evidence,
        'link': '/decision?tab=review',
    }


def _lane_concentration_item(facts, resource, skipped):
    """资源分配复核条目的分路集中度：集中在某一路时优先看那一路。"""
    anomalies = (resource or {}).get('anomalies') or []
    if len(anomalies) < 3:
        skipped.append({'analysis': 'resource_allocation',
                        'reason': f'资源分配复核条目只有 {len(anomalies)} 条，无法看集中度'})
        return None
    counts = {}
    for item in anomalies:
        lane = item.get('lane') or '未标注'
        counts[lane] = counts.get(lane, 0) + 1
    lane, count = max(counts.items(), key=lambda pair: pair[1])
    if count < 3 or count / len(anomalies) < 0.4:
        skipped.append({'analysis': 'resource_allocation',
                        'reason': f'复核条目分散在 {len(counts)} 个分路，没有单一集中分路'})
        return None
    evidence = [{
        'game': item.get('seq'), 'label': item.get('name') or item.get('seq'),
        't': None, 'kind': 'player',
        'text': item.get('text') or '',
    } for item in anomalies if (item.get('lane') or '') == lane][:4]
    return {
        'id': f'lane-resource-{lane}',
        'kind': 'resource_mismatch',
        'severity': 'medium',
        'title': f'资源分配复核有 {count} 条集中在{lane}',
        'detail': f'{len(anomalies)} 条复核里 {count} 条来自{lane}；先对比这一路的资源投入与职责产出。',
        'n': len(anomalies),
        'confidence': _confidence(len(anomalies), cap='medium'),
        'caveat': '分路来自营地面板；同局出现双同位置时按原值统计，可能轻微偏移。',
        'analysis': 'resource_allocation',
        'evidence': evidence,
        'link': '/decision?tab=player',
    }


def _coverage_item(facts):
    coverage = facts.get('coverage') or {}
    paired = coverage.get('pairedGames') or 0
    panel = coverage.get('panelGames') or 0
    errors = coverage.get('errors') or 0
    if panel and paired < panel:
        missing = panel - paired
        detail = f'{panel} 局终局面板中 {paired} 局有官方回放过程'
        if errors:
            detail += f'，{errors} 局回放缺面板或无法判定阵营'
        detail += '。缺回放的对局只能看终局数据，不能做经济转折、团战和落点复盘。'
        return {
            'id': 'coverage-gap',
            'kind': 'coverage_gap',
            'severity': 'low',
            'title': f'{missing} 局只有终局面板、没有回放过程',
            'detail': detail,
            'n': panel,
            'confidence': 'high',
            'caveat': '这是采集覆盖问题，不是比赛结论。',
            'analysis': 'catalog',
            'evidence': [],
            'link': '/collect',
        }
    return None


def briefing(facts, *, opponent=None, date_from=None, date_to=None, result=None, limit=5):
    """返回 {available, coverage, items, skipped, scope, ...}；最多 limit 条。"""
    order = facts.get('order') or []
    import decision_facts
    scoped = decision_facts.filter_games(
        facts, opponent=opponent, date_from=date_from, date_to=date_to, result=result)
    coverage = {
        'games': len(scoped),
        'panelGames': (facts.get('coverage') or {}).get('panelGames'),
        'losses': (facts.get('coverage') or {}).get('losses'),
        'calibrated': (facts.get('coverage') or {}).get('calibrated'),
    }
    if not order:
        return {
            'available': False, 'reason': '当前没有可分析的完整回放对局',
            'coverage': coverage, 'items': [], 'skipped': [],
            'note': '先在采集 → 通道校对里关联官方回放。',
        }
    if not scoped:
        return {
            'available': False,
            'reason': '当前数据范围没有可分析的对局；检查日期、对手或结果筛选。',
            'coverage': coverage, 'items': [], 'skipped': [],
            'scope': {'games': 0, 'dateFrom': date_from, 'dateTo': date_to,
                      'opponent': opponent, 'result': result},
            'note': '决策问题只基于有回放且能判定阵营的对局；放宽筛选后再看。',
        }

    date_args = {'opponent': opponent, 'date_from': date_from, 'date_to': date_to,
                 'result': result}
    skipped = []
    items = []
    try:
        import decision_loss
        advantage = _safe(decision_loss.advantage_report(facts, **date_args),
                          skipped, 'advantage_retention', '优势保持分析')
        loss = _safe(decision_loss.loss_report(facts, **date_args),
                     skipped, 'loss_chain', '失利关键链')
    except Exception as error:  # pragma: no cover - 模块未就绪或数据异常时降级
        advantage, loss = None, None
        skipped.append({'analysis': 'loss_chain', 'reason': f'分析不可用：{error}'})
    try:
        import decision_fights
        fights = _safe(decision_fights.fight_report(facts, **date_args),
                       skipped, 'fight_execution', '团战执行分析')
    except Exception as error:  # pragma: no cover
        fights = None
        skipped.append({'analysis': 'fight_execution', 'reason': f'分析不可用：{error}'})
    try:
        import decision_resource
        resource = _safe(decision_resource.resource_report(facts, **date_args),
                         skipped, 'resource_allocation', '资源分配分析')
    except Exception as error:  # pragma: no cover
        resource = None
        skipped.append({'analysis': 'resource_allocation', 'reason': f'分析不可用：{error}'})
    try:
        import decision_opening
        opening = _safe(decision_opening.opening_report(facts, opponent=opponent),
                        skipped, 'opening_routes', '对手开局分析')
    except Exception as error:  # pragma: no cover
        opening = None
        skipped.append({'analysis': 'opening_routes', 'reason': f'分析不可用：{error}'})

    builders = (
        lambda: _comeback_item(facts, advantage, skipped),
        lambda: _loss_pattern_item(facts, loss, skipped),
        lambda: _slow_conversion_item(facts, advantage, skipped),
        lambda: _fight_arrival_item(facts, fights, skipped),
        lambda: _late_join_item(facts, fights, skipped),
        lambda: _resource_item(facts, resource, skipped),
        lambda: _lane_concentration_item(facts, resource, skipped),
        lambda: _opening_item(facts, opening, skipped, opponent),
        lambda: _coverage_item(facts),
    )
    for build in builders:
        try:
            item = build()
        except Exception as error:  # pragma: no cover - 单条失败不影响其他条目
            skipped.append({'analysis': 'briefing', 'reason': f'条目生成失败：{error}'})
            continue
        if item:
            items.append(item)

    items.sort(key=lambda item: (SEVERITY_ORDER.get(item.get('severity'), 9),
                                 -(item.get('n') or 0),
                                 KIND_ORDER.get(item.get('kind'), 9)))
    picked = items[:max(1, min(5, int(limit or 5)))]
    if len(picked) < 3:
        picked = items[:5]
    skipped.append({
        'analysis': 'training_verification',
        'reason': '训练效果只做干预前后描述（复用 /api/v3/effect）；'
                  '复盘问题→训练目标→复测的自动关联尚未打通（C 级）',
    })
    scope = {
        'games': len(scoped),
        'dateFrom': date_from,
        'dateTo': date_to,
        'opponent': opponent,
        'result': result,
        'panelGames': coverage.get('panelGames'),
    }
    fingerprint = hashlib.sha1(json.dumps({
        'scope': scope,
        'items': [{'id': item.get('id'), 'n': item.get('n'), 'title': item.get('title')}
                  for item in picked],
    }, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()[:12]
    return {
        'available': True,
        'coverage': coverage,
        'items': picked,
        'skipped': skipped,
        'evaluated': len(builders),
        'triggered': len(items),
        'fingerprint': fingerprint,
        'generatedAt': facts.get('generatedAt'),
        'scope': scope,
        'selection': (f'基于当前数据范围自动计算：共评估 {len(builders)} 类信号，'
                      f'命中 {len(items)} 条，按严重度和样本量显示前 {len(picked)} 条；'
                      f'换数据范围或补充对局后会重新计算。'),
        'note': ('按「重复出现 / 涉及胜负 / 有证据可回看」排序；'
                 '小样本会自动降级并写明限制。'),
    }
