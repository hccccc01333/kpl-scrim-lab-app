"""Scrim adaptations of KPL Research analytical views.

Reference: hccccc01333/kpl-research @ 59f776c, hero_perf_app.js,
team_bp_app.js, player_deep.js and analysis/series.py. Calculations consume
local scrim records, never the reference repository's published results.
"""
import itertools
import math
from collections import Counter, defaultdict

import numpy as np

from studio_analysis import METRICS, deduplicate, finite, rounded

TOPICS = [
    ('hero_benchmark', '选手 × 英雄参照', '同位置、同英雄，列出中位、较高、高位水平与当前分位。'),
    ('player_form', '近期状态与稳定性', '逐个选手比较近期均值、全期分布、地板与上限。'),
    ('hero_pool', '英雄池与使用集中度', '查看出场分布、头部英雄占比、英雄集中度与有效英雄数。'),
    ('resource_efficiency', '资源与产出', '对照经济占比、输出占比与伤害转化，保留每局证据。'),
    ('hero_combos', '阵容组合与 Lift', '比较完整阵容中的实际共现与独立选用基线。'),
    ('player_pairs', '双人搭档', '基于稳定选手 ID 查看同队搭档的出场与胜负。'),
    ('tempo', '前期与优势转化', '按王者三段口径（0–4 前期 / 4–10 中期 / 10+ 后期）读取段末与段内经济差。'),
    ('swing_windows', '经济转折窗口', '连续经济差变化合并为窗口，提供回看起止时间。'),
    ('session_summary', '训练组证据汇总', '按日期、训练组、对手汇总比赛与数据覆盖。'),
]


def percentile_rank(values, value):
    """The reference BP view's below / (n-1) percentile convention."""
    return min(100, sum(v < value for v in values)/(len(values)-1)*100) if len(values) > 1 else None


def research(rows, topic, metric='damage', matches=None):
    if topic not in {t[0] for t in TOPICS} or metric not in METRICS:
        raise ValueError('专题或指标无效')
    rows, folded = deduplicate(rows)
    note = ''
    if topic == 'hero_benchmark':
        pools, groups = defaultdict(list), defaultdict(list)
        for r in rows:
            if r.get('position') and r.get('hero') and finite(r.get(metric)) is not None:
                pools[(r['position'], r['hero'])].append(r)
                groups[(r['playerKey'], r['hero'], r['position'])].append(r)
        out = []
        for (_, hero, position), own in groups.items():
            reference = pools[(position, hero)]
            values = [r[metric] for r in reference]
            mean = float(np.mean([r[metric] for r in own]))
            out.append({'label': own[0]['label'], 'hero': hero, 'position': position, 'n': len(own),
                        'value': rounded(mean), 'referenceRows': len(values),
                        'referencePlayers': len({r['playerKey'] for r in reference}),
                        'percentile': rounded(percentile_rank(values, mean)) if len(values) >= 5 else None,
                        'p50': rounded(np.quantile(values, .5)), 'p75': rounded(np.quantile(values, .75)),
                        'p90': rounded(np.quantile(values, .9))})
        columns = ['label','hero','position','n','value','referenceRows','referencePlayers','percentile','p50','p75','p90']
        note = '只使用已填写的实际分路。参考池少于 5 行时不显示分位；分位定义沿用参考仓库的低于当前值数量 / (n−1)。'
    elif topic in ('player_form', 'hero_pool'):
        groups = defaultdict(list)
        for r in rows:
            groups[r['playerKey']].append(r)
        out = []
        for key, group in groups.items():
            if topic == 'hero_pool':
                counts = Counter(r['hero'] for r in group if r.get('hero'))
                total = sum(counts.values())
                if not total:
                    continue
                hhi = sum((count/total)**2 for count in counts.values())
                entropy = -sum(count/total*math.log(count/total) for count in counts.values())
                out.append({'label': group[0]['label'], 'bound': group[0].get('bound'), 'n': total,
                            'heroes': len(counts), 'topHero': counts.most_common(1)[0][0],
                            'topShare': rounded(counts.most_common(1)[0][1]/total*100),
                            'hhi': rounded(hhi), 'effectiveHeroes': rounded(1/hhi), 'entropy': rounded(entropy)})
            else:
                valid = sorted([r for r in group if finite(r.get(metric)) is not None],key=lambda r:(r.get('date') or '',r['matchKey']))
                if not valid:
                    continue
                values = np.array([r[metric] for r in valid])
                dated = [r for r in valid if r.get('date') and len(str(r['date'])) == 10]
                recent = [r[metric] for r in dated[-5:]]
                out.append({'label': group[0]['label'], 'bound': group[0].get('bound'), 'n': len(values),
                            'mean': rounded(values.mean()), 'recentMean': rounded(np.mean(recent)) if recent else None,
                            'recentN': len(recent), 'std': rounded(values.std(ddof=1)) if len(values)>1 else None,
                            'p10': rounded(np.quantile(values,.1)), 'p90': rounded(np.quantile(values,.9)),
                            'iqr': rounded(np.quantile(values,.75)-np.quantile(values,.25)),
                            'change': rounded(np.mean(recent)-values.mean()) if recent else None})
        columns = ['label','bound','n','heroes','topHero','topShare','hhi','effectiveHeroes','entropy'] if topic=='hero_pool' else ['label','bound','n','mean','recentMean','recentN','change','std','p10','p90','iqr']
        note = '有效英雄数 = 1 / 英雄集中度；集中度越高，英雄池越集中。' if topic=='hero_pool' else '近期为有完整日期的最近 5 局；低水平/高水平是分布位置，不是能力上下限。'
        note += ' 未绑定记录只按来源昵称分组，不能视为同一选手的长期档案。'
    elif topic == 'resource_efficiency':
        out = []
        for r in rows:
            if r.get('goldShare') is not None and r.get('damageShare') is not None:
                out.append({'label':r['label'],'hero':r['hero'],'position':r.get('position'),'date':r.get('date'),
                            'goldShare':r['goldShare'],'damageShare':r['damageShare'],
                            'shareGap':rounded(r['damageShare']-r['goldShare']),
                            'damageConversion':rounded(r.get('damageConversion')),'matchKey':r['matchKey']})
        columns=['label','hero','position','date','goldShare','damageShare','shareGap','damageConversion','matchKey']
        note='占比差 = 输出占比 − 经济占比。职责、英雄与局势不同，不能直接据此评价选手贡献。'
    elif topic in ('hero_combos','player_pairs'):
        teams=defaultdict(list)
        for r in rows:
            if r.get('camp') not in (None,'','unknown'):
                teams[(r['matchKey'],r['camp'])].append(r)
        units=[]
        for members in teams.values():
            if len(members)!=5:
                continue
            # 只看本队阵容：对手的五个英雄不是我们的英雄池。
            if not all(r.get('isOwn') for r in members):
                continue
            if topic=='player_pairs' and not all(r.get('bound') for r in members):
                continue
            ids={r['hero'] if topic=='hero_combos' else r['playerKey'] for r in members}
            if len(ids)!=5 or '' in ids:
                continue
            outcomes={r['result'] for r in members}
            units.append((ids, next(iter(outcomes)) if len(outcomes)==1 else 'unknown', {r['playerKey']:r['label'] for r in members}))
        singles,combos=Counter(),defaultdict(list)
        labels={}
        for ids,outcome,names in units:
            singles.update(ids);labels.update(names)
            for pair in itertools.combinations(sorted(ids),2):
                combos[pair].append(outcome)
        out=[]
        for (a,b),outcomes in combos.items():
            count=len(outcomes)
            if count<3:
                continue
            decided=sum(o in ('win','loss') for o in outcomes)
            observed=count/len(units)
            expected=singles[a]/len(units)*singles[b]/len(units)
            out.append({'a':labels.get(a,a),'b':labels.get(b,b),'n':count,
                        'cooccurrence':rounded(observed*100),'expectedRate':rounded(expected*100),
                        'lift':rounded(observed/expected),'decided':decided,
                        'winRate':rounded(outcomes.count('win')/decided*100) if decided else None})
        out.sort(key=lambda r:(-r['n'],-r['lift']))
        columns=['a','b','n','cooccurrence','expectedRate','lift','decided','winRate']
        note='只统计本队完整五人阵容，至少共现 3 次；Lift 仅描述共现，不代表协同因果或 BP 优势。双人专题要求稳定选手身份。'
    elif topic in ('tempo','swing_windows'):
        out=[]
        selected={r['matchKey'] for r in rows}
        for m in matches or []:
            if m['key'] not in selected:
                continue
            points=[]
            own=m.get('ownCamp');direction=-1 if own=='red' else 1
            for p in (m.get('process') or {}).get('timeline') or []:
                t,b,r=finite(p.get('gameTime')),finite(p.get('blueGold')),finite(p.get('redGold'))
                if None not in (t,b,r):points.append((t,(b-r)*direction))
            points=sorted(dict(points).items())
            if len(points)<2:
                continue
            def at(t):
                if t<points[0][0] or t>points[-1][0]:return None
                for i,(right,y) in enumerate(points):
                    if right==t:return y
                    if right>t and i:
                        left,x=points[i-1]
                        return x+(y-x)*(t-left)/(right-left) if right-left<=120 else None
                return None
            if topic=='tempo':
                winner = m.get('winnerCamp') or m.get('winner')
                gold4, gold10, gold_end = rounded(at(240)), rounded(at(600)), rounded(points[-1][1])
                out.append({'matchKey':m['key'],'date':m.get('date'),'perspective':'本队 − 对手' if own in ('blue','red') else '蓝方 − 红方',
                            'gold4':gold4,'gold10':gold10,'goldEnd':gold_end,
                            'earlyDelta':gold4,
                            'midDelta':rounded(gold10-gold4) if None not in (gold4,gold10) else None,
                            'lateDelta':rounded(gold_end-gold10) if None not in (gold10,gold_end) else None,
                            'observedEnd':rounded(points[-1][0]/60),
                            'result':('win' if winner==own else 'loss') if own and winner else 'unknown'})
            else:
                segments=[];current=None
                for (t0,g0),(t1,g1) in zip(points,points[1:]):
                    delta=g1-g0;sign=1 if delta>0 else -1
                    if t1-t0>120 or abs(delta)<100:
                        if current:segments.append(current);current=None
                        continue
                    if current and current['direction']==sign and current['end']==t0:
                        current.update(end=t1,to=g1)
                    else:
                        if current:segments.append(current)
                        current={'start':t0,'end':t1,'from':g0,'to':g1,'direction':sign}
                if current:segments.append(current)
                for segment in segments:
                    change=segment['to']-segment['from']
                    if segment['end']-segment['start']<60 and abs(change)<400:continue
                    out.append({'matchKey':m['key'],'startMinute':rounded(segment['start']/60),
                                'endMinute':rounded(segment['end']/60),'goldChange':rounded(change),
                                'perspective':'本队 − 对手' if own in ('blue','red') else '蓝方 − 红方',
                                'note':'经济差代理窗口；回看录像确认事件'})
        columns=['matchKey','date','perspective','gold4','gold10','goldEnd','earlyDelta','midDelta','lateDelta','observedEnd','result'] if topic=='tempo' else ['matchKey','startMinute','endMinute','goldChange','perspective','note']
        note='王者三段口径：0–4 前期 / 4–10 中期 / 10+ 后期；gold4/gold10/goldEnd 为段末经济差，earlyDelta/midDelta/lateDelta 为段内变化。只在观测区间内插值，相邻点间隔最多 120 秒；不把短片段外推到 10 分钟。经济差不转换成未经训练的胜率。'
    else:
        groups=defaultdict(dict)
        for r in rows:
            if r.get('date') and r.get('session') and r.get('opponent'):
                groups[(r['date'],r['session'],r['opponent'])].setdefault(r['matchKey'],[]).append(r)
        out=[]
        for (day,session,opponent),games in groups.items():
            outcomes=[]
            for members in games.values():
                own=[r for r in members if r.get('isOwn')]
                if own and len({r['result'] for r in own})==1:outcomes.append(own[0]['result'])
            decided=sum(o in ('win','loss') for o in outcomes)
            out.append({'date':day,'session':session,'opponent':opponent,'games':len(games),'decided':decided,
                        'wins':outcomes.count('win'),'losses':outcomes.count('loss'),
                        'winRate':rounded(outcomes.count('win')/decided*100) if decided else None})
        columns=['date','session','opponent','games','decided','wins','losses','winRate']
        note='训练组由明确填写的日期、训练组和对手组成；不把同一天的不同对局自动当成 BO 系列赛。'
    summary = None
    if topic == 'tempo':
        early = [r for r in out if r['gold4'] is not None and r['gold4']>0 and r['result'] in ('win','loss')]
        late = [r for r in out if r['gold10'] is not None and r['gold10']>0 and r['result'] in ('win','loss')]
        summary = {'前期领先且有赛果':len(early), '前期其中胜场':sum(r['result']=='win' for r in early),
                   '前期转化率（%）':rounded(sum(r['result']=='win' for r in early)/len(early)*100) if early else None,
                   '十分钟领先且有赛果':len(late), '十分钟其中胜场':sum(r['result']=='win' for r in late),
                   '十分钟转化率（%）':rounded(sum(r['result']=='win' for r in late)/len(late)*100) if late else None}
    return {'topic':topic,'metric':metric,'columns':columns,'rows':out[:500], 'summary':summary,
            'matches':len({r['matchKey'] for r in rows}),'folded':len(folded),'note':note,
            'reference':'https://github.com/hccccc01333/kpl-research','referenceCommit':'59f776c364ee03d2d298d8923ce8e6233bae234f'}
