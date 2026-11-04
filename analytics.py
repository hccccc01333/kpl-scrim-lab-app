"""Recomputable review metrics. Never turn a partial team sum into a total."""
from collections import Counter

TOTAL_METRICS = ('kills', 'deaths', 'assists', 'gold', 'damage', 'taken')


def team_totals(match, side):
    from domain import number
    players = [p for p in match['players'] if p['side'] == side]
    result = {}
    for metric in TOTAL_METRICS:
        values = [number(p.get(metric)) for p in players]
        known = [v for v in values if v is not None]
        result[metric] = {'value':sum(known) if len(players) == 5 and len(known) == 5 else None,
                          'samples':len(known), 'expected':5}
    return result


def player_measures(match, player, totals=None):
    from domain import number
    minutes = number(match.get('duration'))
    metrics = {k:number(player.get(k)) for k in (*TOTAL_METRICS, 'participation', 'rating')}
    result = dict(metrics)
    for metric in ('gold', 'damage', 'taken'):
        result[metric+'PerMinute'] = metrics[metric]/minutes if minutes and metrics[metric] is not None else None
    totals = totals or team_totals(match, player['side'])
    for metric in ('gold', 'damage', 'taken'):
        total = totals[metric]['value']
        result[metric+'Share'] = metrics[metric]/total*100 if total and metrics[metric] is not None else None
    k, d, a = (metrics[k] for k in ('kills', 'deaths', 'assists'))
    result['kda'] = (k+a)/max(1,d) if all(v is not None for v in (k,d,a)) else None
    return result


def aggregate_measures(items):
    from domain import number
    result = {}
    rows = [(m,p) for m,p,_ in items if p is not None]
    for metric in ('gold', 'damage', 'taken'):
        paired = [(number(p.get(metric)), number(m.get('duration'))) for m,p in rows]
        paired = [(v,t) for v,t in paired if v is not None and t is not None and t > 0]
        minutes = sum(t for _,t in paired)
        result[metric+'PerMinute'] = sum(v for v,_ in paired)/minutes if minutes else None
        result[metric+'PerMinuteSamples'] = len(paired)
        result[metric+'PerMinuteMinutes'] = minutes
    for metric in ('gold', 'damage', 'taken'):
        shares = [player_measures(m,p)[metric+'Share'] for m,p in rows]
        shares = [s for s in shares if s is not None]
        result[metric+'Share'] = sum(shares)/len(shares) if shares else None
        result[metric+'ShareSamples'] = len(shares)
    triples = [(number(p.get('kills')), number(p.get('deaths')), number(p.get('assists'))) for _,p in rows]
    triples = [triple for triple in triples if all(v is not None for v in triple)]
    result['kda'] = (sum(t[0]+t[2] for t in triples)/max(1,sum(t[1] for t in triples))) if triples else None
    result['kdaSamples'] = len(triples)
    result['positions'] = sorted({p['position'] for _,p in rows if p.get('position')})
    result['unknownPositionSamples'] = sum(not p.get('position') for _,p in rows)
    return result


def review_match(match, roster, team_name):
    from domain import POSITIONS, number
    names = {p['id']:p['name'] for p in roster}
    own = match.get('side')
    first = own if own in ('left','right') else 'left'
    second = 'right' if first == 'left' else 'left'
    teams = {}
    for side in ('left', 'right'):
        totals = team_totals(match, side)
        players = []
        for p in sorted((p for p in match['players'] if p['side'] == side), key=lambda p:p['slot']):
            players.append({'slot':p['slot'], 'playerId':p.get('playerId'), 'name':names.get(p.get('playerId'), ''),
                            'hero':p.get('hero',''), 'position':p.get('position',''),
                            'equipment':p.get('equipment',''), 'metrics':player_measures(match,p,totals)})
        label = team_name if side == own else (match.get('opponent') or '对手') if own in ('left','right') else ('左侧' if side == 'left' else '右侧')
        teams[side] = {'side':side,'name':label,
                       'isOwn':side == own,'totals':totals,'players':players}
    comparisons = []
    for key in ('gold', 'damage', 'taken', 'kills'):
        a,b = teams[first]['totals'][key], teams[second]['totals'][key]
        comparisons.append({'metric':key,'first':a,'second':b,
                            'difference':a['value']-b['value'] if a['value'] is not None and b['value'] is not None else None})
    # Positions are explicitly confirmed; screenshot row order is never a matchup.
    matchups = []
    for position in POSITIONS:
        a = [p for p in teams[first]['players'] if p['position'] == position]
        b = [p for p in teams[second]['players'] if p['position'] == position]
        if len(a) == len(b) == 1:
            matchups.append({'position':position, 'first':a[0], 'second':b[0],
                             'goldDifference':a[0]['metrics']['gold']-b[0]['metrics']['gold'] if a[0]['metrics']['gold'] is not None and b[0]['metrics']['gold'] is not None else None})
    duplicate_positions = []
    for side in ('left','right'):
        counts = Counter(p['position'] for p in teams[side]['players'] if p['position'])
        duplicate_positions += [f'{"左" if side == "left" else "右"}侧{position}有 {n} 人，未生成该位置对照' for position,n in counts.items() if n > 1]
    return {'id':match['id'],'revision':match.get('revision'), 'status':match['status'], 'date':match.get('date',''),
            'side':own,'winner':match.get('winner'),'session':match.get('session',''), 'version':match.get('version',''),
            'duration':number(match.get('duration')), 'scores':match.get('scores',{}), 'teams':teams,
            'order':[first,second], 'comparisons':comparisons, 'matchups':matchups, 'warnings':duplicate_positions,
            'notes':match.get('notes',''),'bp':match.get('bp',''),'imageIds':match.get('imageIds',[]),
            'method':'review-v1 · rates=sum(value)/sum(valid paired minutes); shares=require all five teammates'}
