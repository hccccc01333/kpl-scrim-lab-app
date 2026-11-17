"""英雄能力标签表（赛训组官方口径，2026-11 版）。

数据来自赛训组《KPL赛训英雄标签及逐局模板》的能力矩阵（133 英雄 × 19 个 0/1
维度），经 scripts/rebuild_hero_roles.py 映射成本模块的 9 个能力口径后整表生成；
手工调整请改工作簿后重跑该脚本，不要直接编辑下面的字典。

能力维度（与 docs/kpl_hit_logic.md / 评估报告 §2.2 对齐）：
- engage:   强开/先手开团        ← 开团
- peel:     保护后排/反开        ← 保护
- burst:    爆发输出             ← 爆发
- sustained: 持续输出            ← 持续输出
- frontline: 前排/承伤           ← 前排、承伤
- waveclear: 清线/转线           ← 清线
- roam:     游走/支援            ← 支援、入侵
- macro:    推塔/控龙/运营       ← 推进、带线
- resilience: 容错/脱战/反打     ← 反开、续航

用法：
    from hero_roles import HERO_ROLES, lineup_profile, gaps, substitutes
"""
from __future__ import annotations

CAPABILITIES = ('engage', 'peel', 'burst', 'sustained', 'frontline',
                'waveclear', 'roam', 'macro', 'resilience')

# 赛训组能力矩阵映射后的种子表（全部 133 个英雄；0/1 表示是否具备该能力）。
HERO_ROLES: dict[str, dict[str, int]] = {
    '上官婉儿': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '不知火舞': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '东皇太一': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '云中君': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '云缨': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '亚瑟': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 1},
    '亚连': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '伽罗': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
    '元歌': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
    '元流之子(刺客)': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '元流之子(坦克)': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '元流之子(射手)': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
    '元流之子(法师)': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '元流之子(辅助)': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '公孙离': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '兰陵王': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '关羽': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 1, 'resilience': 0},
    '典韦': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '刘备': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 1},
    '刘禅': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
    '刘邦': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 1, 'macro': 1, 'resilience': 0},
    '卢雅那': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '司空震': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 1},
    '司马懿': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '后羿': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
    '吕布': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '周瑜': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 1, 'resilience': 0},
    '哪吒': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 1, 'resilience': 0},
    '墨子': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '夏侯惇': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '夏洛特': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 1},
    '大乔': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '大司命': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '大禹': {'engage': 1, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '太乙真人': {'engage': 1, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '女娲': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 0},
    '妲己': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '姜子牙': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '姬小满': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
    '娜可露露': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '嫦娥': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 1, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '嬴政': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 1, 'resilience': 0},
    '孙尚香': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '孙悟空': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '孙权': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '孙策': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '孙膑': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 1},
    '安琪拉': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '宫本武藏': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '小乔': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '少司缘': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 1},
    '干将莫邪': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 0},
    '庄周': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '廉颇': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '弈星': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '张良': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '张飞': {'engage': 1, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '影': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '心魔六耳': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '戈娅': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '扁鹊': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '敖隐': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '明世隐': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '暃': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '曜': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 1},
    '曹操': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 1},
    '朵莉亚': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '李信': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 1, 'resilience': 0},
    '李元芳': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 1, 'resilience': 0},
    '李白': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '杨戬': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '杨玉环': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '桑启': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 1},
    '梦奇': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 1},
    '橘右京': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '武则天': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 0},
    '沈梦溪': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 0},
    '海月': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '海诺': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '澜': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '牛魔': {'engage': 1, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '狂铁': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 1},
    '狄仁杰': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
    '猪八戒': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '王昭君': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '王维': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 0},
    '瑶': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '甄姬': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '白起': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '百里守约': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 1, 'resilience': 0},
    '百里玄策': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '盘古': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 1, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '盾山': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '程咬金': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 1},
    '空空儿': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '米莱狄': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 1, 'resilience': 0},
    '老夫子': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 1},
    '艾琳': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '芈月': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 1},
    '花木兰': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
    '苍': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '苏烈': {'engage': 1, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '莱西奥': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '蒙恬': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
    '蒙犽': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 1, 'resilience': 0},
    '蔡文姬': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '虞姬': {'engage': 0, 'peel': 1, 'burst': 1, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '蚩奼': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '裴擒虎': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '西施': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 1, 'macro': 0, 'resilience': 0},
    '诸葛亮': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '貂蝉': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '赵云': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '赵怀真': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '达摩': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '金蝉': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 1, 'roam': 0, 'macro': 0, 'resilience': 1},
    '钟无艳': {'engage': 1, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '钟馗': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '铠': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '镜': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '阿古朵': {'engage': 0, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 1, 'macro': 1, 'resilience': 0},
    '阿轲': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '雅典娜': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '露娜': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '韩信': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 1, 'resilience': 0},
    '项羽': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 1, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '马可波罗': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '马超': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 1, 'resilience': 0},
    '高渐离': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 1},
    '鬼谷子': {'engage': 1, 'peel': 0, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 1, 'macro': 0, 'resilience': 0},
    '鲁班七号': {'engage': 0, 'peel': 0, 'burst': 1, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
    '鲁班大师': {'engage': 1, 'peel': 1, 'burst': 0, 'sustained': 0, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 0, 'resilience': 0},
    '黄忠': {'engage': 0, 'peel': 0, 'burst': 0, 'sustained': 1, 'frontline': 0, 'waveclear': 0, 'roam': 0, 'macro': 1, 'resilience': 0},
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