"""Fixed post-game screenshot field contract for the current tabbed UI.

The tabbed post-game screen was added after the original two-column screenshot
contract.  This module is the single source of truth for page types and field
IDs; the OCR implementation must only emit these fields.
"""
SCHEMA = 'kpl-postgame-screenshot-v1'

# pageType -> tab shown in the bottom navigation
TABS = {
    'score': '战绩',       # older/score variant with equipment and gold
    'kda': '战绩',         # current 战绩 view: KDA counts and shares
    'data': '数据',
    'output': '输出',
    'survival': '生存',
    'farming': '发育',
    'team': '团队',
}
PAGE_ORDER = ('score', 'kda', 'data', 'output', 'survival', 'farming', 'team')

MATCH_FIELDS = ('date', 'time', 'durationSec', 'mode', 'result', 'score')
MATCH_LABELS = {
    'date': '日期', 'time': '时间', 'durationSec': '时长（秒）', 'mode': '模式',
    'result': '胜负', 'score': '比分',
}

PLAYER_FIELDS = (
    'nickname', 'hero', 'rating', 'title', 'mvp',
    'kills', 'deaths', 'assists', 'gold',
    'damageDealt', 'damageTaken', 'participation', 'takenPerDeath',
    'damageConversion', 'jungleGold', 'cs', 'control', 'healing', 'towerDamage',
)
SHARE_FIELDS = (
    'killsShare', 'deathsShare', 'assistsShare',
    'outputShare', 'takenShare', 'goldShare',
    'jungleShare', 'csShare', 'controlShare', 'healingShare', 'towerShare',
)
PLAYER_LABELS = {
    'nickname': '昵称', 'hero': '英雄', 'rating': '评分', 'title': '称号', 'mvp': 'MVP',
    'kills': '击杀', 'deaths': '死亡', 'assists': '助攻', 'gold': '总经济',
    'damageDealt': '输出伤害', 'damageTaken': '承受伤害', 'participation': '参团率',
    'takenPerDeath': '每死承伤', 'damageConversion': '伤害转化比',
    'jungleGold': '野怪经济', 'cs': '补刀数', 'control': '控制效果',
    'healing': '治疗量', 'towerDamage': '对塔伤害',
    'killsShare': '击杀占比', 'deathsShare': '死亡占比', 'assistsShare': '助攻占比',
    'outputShare': '输出占比', 'takenShare': '承伤占比', 'goldShare': '经济占比',
    'jungleShare': '野怪经济占比', 'csShare': '补刀占比',
    'controlShare': '控制占比', 'healingShare': '治疗占比', 'towerShare': '对塔占比',
}

FIELD_UNITS = {
    'rating': 'score',
    'kills': 'count', 'deaths': 'count', 'assists': 'count', 'cs': 'count',
    'control': 'count', 'gold': 'unit', 'damageDealt': 'unit',
    'damageTaken': 'unit', 'takenPerDeath': 'unit', 'jungleGold': 'unit',
    'healing': 'unit', 'towerDamage': 'unit',
    'damageConversion': 'ratio',
    'participation': 'percent',
    'killsShare': 'percent', 'deathsShare': 'percent', 'assistsShare': 'percent',
    'outputShare': 'percent', 'takenShare': 'percent', 'goldShare': 'percent',
    'jungleShare': 'percent', 'csShare': 'percent',
    'controlShare': 'percent', 'healingShare': 'percent', 'towerShare': 'percent',
}

# Complete player payload allowed on each page.  Ratings and identity are on
# every tab; the other fields are shown by that tab only.
PAGE_FIELDS = {
    'score': ('nickname', 'hero', 'rating', 'title', 'mvp',
              'kills', 'deaths', 'assists', 'gold'),
    'kda': ('nickname', 'hero', 'rating', 'title', 'mvp',
            'kills', 'deaths', 'assists',
            'killsShare', 'deathsShare', 'assistsShare'),
    'data': ('nickname', 'hero', 'rating', 'title', 'mvp',
             'damageDealt', 'damageTaken', 'gold', 'participation',
             'outputShare', 'takenShare', 'goldShare'),
    'output': ('nickname', 'hero', 'rating', 'title', 'mvp',
               'damageDealt', 'damageConversion', 'outputShare'),
    'survival': ('nickname', 'hero', 'rating', 'title', 'mvp',
                 'damageTaken', 'takenPerDeath', 'takenShare'),
    'farming': ('nickname', 'hero', 'rating', 'title', 'mvp',
                'gold', 'jungleGold', 'cs',
                'goldShare', 'jungleShare', 'csShare'),
    'team': ('nickname', 'hero', 'rating', 'title', 'mvp',
             'participation', 'control', 'healing', 'towerDamage',
             'controlShare', 'healingShare', 'towerShare'),
}

# Which page can supply match-level metadata.  All pages may show the score in
# the header; only 战绩 carries date/duration/mode/result in the calibrated UI.
MATCH_PAGE_FIELDS = {
    'score': ('date', 'time', 'durationSec', 'mode', 'result', 'score'),
    'kda': ('score',),
    'data': ('score',),
    'output': ('score',),
    'survival': ('score',),
    'farming': ('score',),
    'team': ('score',),
}

IDENTITY_FIELDS = ('side', 'slot', 'nickname', 'hero', 'rating')

# A merged bundle can fill a field from another tab of the same match, but the
# value must be tagged with the tab that supplied it.
FIELD_PAGES = {}
for _page, _fields in PAGE_FIELDS.items():
    for _field in _fields:
        FIELD_PAGES.setdefault(_field, []).append(_page)
