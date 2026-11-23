"""使用者等级（联赛）映射表：加新等级只改这张表，不改代码（方案文档 §9）。

league 存在队伍资料（settings 表 JSON 的 league 字段）；capabilities 决定
采集入口与事实表适用性的前端呈现；thresholds 给初始化清单默认值。
覆盖薄的等级，核心资产是自建训练赛语料 + 自攒对手库——叙事由前端按等级调整。
"""

LEAGUES = ['KPL', 'K甲', '女子联赛', '青训', '高校', '大众赛']
DEFAULT_LEAGUE = 'KPL'

# formalSync：正赛数据能否从营地/官方自动同步（决定采集页能力入口）；
# factsApplies：KPL/营地外部事实表对本等级的适用性（full / reference / meta-only）。
CAPABILITIES = {
    'KPL': {'formalSync': True, 'factsApplies': 'full'},
    'K甲': {'formalSync': False, 'factsApplies': 'reference'},
    '女子联赛': {'formalSync': False, 'factsApplies': 'meta-only'},
}
DEFAULT_CAPABILITIES = {'formalSync': False, 'factsApplies': 'reference'}

THRESHOLDS = {
    'corpus': 20,              # 跨局分析语料（当前赛事已确认对局数）
    'boHabitSameFormat': 2,    # BO 习惯：同赛制同 Ban 数的历史场次数
}


def capabilities(league):
    return dict(CAPABILITIES.get(str(league or '').strip(), DEFAULT_CAPABILITIES))


def threshold_for(league, key='corpus'):
    # 阈值纪律：阈值必须与分析代码真实口径一致，各等级不放宽（宁可灰显不混数据）。
    return THRESHOLDS.get(key)
