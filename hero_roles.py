"""英雄能力标签表（人工审核种子版）。

给 BP 体系识别提供可解释的英雄能力标签，不依赖外部数据源。
标签取值 0/1（是否具备该能力）；后续可扩展为 0–3 强度。

能力维度（与 README.md / 评估报告 §2.2 对齐）：
- engage:   强开/先手开团
- peel:     保护后排/反开
- burst:    爆发输出
- sustained: 持续输出
- frontline: 前排/承伤
- waveclear: 清线/转线
- roam:     游走/支援
- macro:    推塔/控龙/运营
- resilience: 容错/脱战/反打

用法：
    from hero_roles import HERO_ROLES, lineup_profile, gaps, substitutes
"""
from __future__ import annotations

CAPABILITIES = ('engage', 'peel', 'burst', 'sustained', 'frontline',
                'waveclear', 'roam', 'macro', 'resilience')

# 种子标签：仅覆盖常见英雄，未收录英雄返回空标签（不崩溃）。
# 标签为人工审核初版，后续按训练赛数据迭代。
HERO_ROLES: dict[str, dict[str, int]] = {
    '关羽': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 1,
            'waveclear': 1, 'roam': 1, 'macro': 1, 'resilience': 1},
    '马超': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0,
            'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 1},
    '吕布': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 1,
            'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '花木兰': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0,
              'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '妲己': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0,
            'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '貂蝉': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0,
            'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '沈梦溪': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0,
              'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 0},
    '西施': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0,
            'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 0},
    '张良': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0,
            'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '百里守约': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0,
                'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '公孙离': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0,
              'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 1},
    '孙尚香': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0,
              'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '马可波罗': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0,
                'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 1},
    '孙悟空': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0,
              'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 1},
    '兰陵王': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0,
              'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 1},
    '钟馗': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 1,
            'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '张飞': {'engage': 1, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 1,
            'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '牛魔': {'engage': 1, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 1,
            'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '太乙真人': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0,
                'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 1},
    '鬼谷子': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0,
              'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '盾山': {'engage': 1, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 1,
            'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '鲁班大师': {'engage': 1, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0,
                'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 0},
    '瑶': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0,
          'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 1},
    '明世隐': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0,
              'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '澜': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0,
          'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 1},
    '镜': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0,
          'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 1},
    '赵云': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0,
            'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 1},
    '裴擒虎': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0,
              'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 0},
    '橘右京': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0,
              'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 1},
    '暃': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0,
          'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 1},
    '夏洛特': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 1,
              'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
}


def role_of(hero):
    return HERO_ROLES.get(hero, {cap: 0 for cap in CAPABILITIES})


def lineup_profile(heroes):
    prof = {cap: 0 for cap in CAPABILITIES}
    for hero in heroes or []:
        r = role_of(hero)
        for cap in CAPABILITIES:
            prof[cap] += int(r.get(cap, 0))
    return prof


def gaps(heroes, *, min_cover=1):
    prof = lineup_profile(heroes)
    return [cap for cap in CAPABILITIES if prof[cap] < min_cover]


def substitutes(capability, *, exclude=None, limit=5):
    exclude = set(exclude or [])
    out = [h for h, r in HERO_ROLES.items()
           if r.get(capability) and h not in exclude]
    out.sort()
    return out[:limit]


def coverage_score(heroes):
    prof = lineup_profile(heroes)
    covered = sum(1 for cap in CAPABILITIES if prof[cap] > 0)
    return round(covered / len(CAPABILITIES), 3)


def lineup_structure(heroes):
    """返回阵容结构分析：能力覆盖、短板、替代建议。"""
    prof = lineup_profile(heroes)
    g = gaps(heroes)
    subs = {}
    for cap in g:
        subs[cap] = substitutes(cap, exclude=set(heroes or []), limit=3)
    return {
        'capabilities': prof,
        'coverageScore': coverage_score(heroes),
        'gaps': g,
        'substitutes': subs,
        'heroCount': len(heroes or []),
        'taggedCount': sum(1 for h in (heroes or []) if h in HERO_ROLES),
    }