"""生成演示用的营地面板，用来验证「对手战队卡片」在有重复阵容时是否成立。

真实数据里 32 局是排位赛，对面每局都是不同的人，聚出来 32 支"1 局的战队"，
看不出多队对比的效果。这里造一批有重复阵容的样本：

- 7 支对手战队，T1 打了 12 局、T2 7 局、T3 5 局，其余 1–3 局；
- T3 有 2 局换了 1 个人（4/5 重合），用来验证"建议合并"；
- 我方 2 支首发阵容轮换，蓝红阵营交替；
- 英雄从真实英雄名里取，分路与英雄大体对应。

只写 data/_mock/camp_details，不碰 data/camp_details 里的真实数据。
"""
import json
import random
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / '_mock' / 'camp_details'

LANES = ['对抗路', '打野', '中路', '发育路', '游走']
# 营地 position 编码：0=对抗路 / 1=中路 / 2=发育路 / 3=打野 / 4=游走
LANE_CODE = {'对抗路': 0, '中路': 1, '发育路': 2, '打野': 3, '游走': 4}
HEROES = {
    '对抗路': ['吕布', '马超', '铠', '夏洛特', '老夫子', '杨戬', '芈月', '猪八戒'],
    '打野': ['阿轲', '兰陵王', '镜', '澜', '曜', '韩信', '裴擒虎', '娜可露露'],
    '中路': ['安琪拉', '不知火舞', '诸葛亮', '小乔', '王昭君', '貂蝉', '上官婉儿', '杨玉环'],
    '发育路': ['马可波罗', '公孙离', '狄仁杰', '黄忠', '伽罗', '虞姬', '百里守约', '莱西奥'],
    '游走': ['瑶', '钟无艳', '张飞', '孙膑', '庄周', '牛魔', '大乔', '东皇太一'],
}

TEAMS = {
    'T1': dict(name='青岚', players=['青岚·辰', '青岚·野', '青岚·中', '青岚·射', '青岚·辅'], games=12),
    'T2': dict(name='赤霄', players=['赤霄·一', '赤霄·二', '赤霄·三', '赤霄·四', '赤霄·五'], games=7),
    'T3': dict(name='苍梧', players=['苍梧·林', '苍梧·山', '苍梧·风', '苍梧·月', '苍梧·雪'], games=5),
    'T4': dict(name='', players=['白虎·刀', '白虎·枪', '白虎·剑', '白虎·弓', '白虎·盾'], games=3),
    'T5': dict(name='', players=['流云·一', '流云·二', '流云·三', '流云·四', '流云·五'], games=2),
    'T6': dict(name='', players=['惊蛰·A', '惊蛰·B', '惊蛰·C', '惊蛰·D', '惊蛰·E'], games=1),
    'T7': dict(name='', players=['逐风·1', '逐风·2', '逐风·3', '逐风·4', '逐风·5'], games=1),
}
SUB = '苍梧·替补'

# 数据包与战队档案里展示的队名（面板本身仍保留"待命名"以覆盖改名流程）。
BUNDLE_NAMES = {
    'T1': '青岚战队', 'T2': '赤霄战队', 'T3': '苍梧战队', 'T4': '白虎战队',
    'T5': '流云战队', 'T6': '惊蛰战队', 'T7': '逐风战队',
}

# 固定体系：每队一套基础阵容（按路序：对抗路/打野/中路/发育路/游走）
COMPS = {
    'T1': ['吕布', '阿轲', '不知火舞', '马可波罗', '瑶'],
    'T2': ['马超', '兰陵王', '诸葛亮', '公孙离', '张飞'],
    'T3': ['铠', '镜', '安琪拉', '狄仁杰', '钟无艳'],
    'T4': ['夏洛特', '澜', '小乔', '黄忠', '孙膑'],
    'T5': ['老夫子', '曜', '王昭君', '伽罗', '庄周'],
    'T6': ['杨戬', '韩信', '貂蝉', '虞姬', '牛魔'],
    'T7': ['芈月', '裴擒虎', '上官婉儿', '百里守约', '大乔'],
}
OWN_COMPS = {
    'blue': ['吕布', '阿轲', '安琪拉', '马可波罗', '瑶'],
    'red': ['马超', '兰陵王', '小乔', '公孙离', '张飞'],
}

OWN = {
    'blue': ['我方·边', '我方·野', '我方·中', '我方·射', '我方·辅'],
    'red': ['轮换·边', '轮换·野', '轮换·中', '轮换·射', '轮换·辅'],
}


def role(player_id, name, lane, hero, camp, stats):
    return {
        'basicInfo': {'playerId': player_id, 'roleName': name, 'acntCamp': camp},
        'battleRecords': {'usedHero': {'heroName': hero}, 'position': LANE_CODE[lane]},
        'battleStats': stats,
    }


# 每支对手的整体强度，用来让对比表出现真实差异（1.0 为基准）
STRENGTH = {'T1': 1.14, 'T2': 1.02, 'T3': 0.96, 'T4': 0.86, 'T5': 0.9, 'T6': 0.8, 'T7': 0.82}

# 分路系数：(经济占比, 输出占比, 承伤占比, 控制秒/分, 治疗/分)
LANE_SHAPE = {
    '对抗路': (0.9, 1.05, 1.25, 1.6, 0.2),
    '打野': (1.05, 1.1, 1.05, 1.4, 0.1),
    '中路': (1.0, 1.2, 0.85, 1.2, 0.3),
    '发育路': (1.15, 1.25, 0.8, 0.8, 0.1),
    '游走': (0.75, 0.55, 1.05, 2.4, 1.8),
}


def stats_for(rng, lane, minutes, strength):
    share, damage, taken, control, heal = LANE_SHAPE[lane]
    return {
        'killCnt': max(0, int(round(rng.uniform(1.5, 6.5) * damage * strength))),
        'deadCnt': max(0, int(round(rng.uniform(1.5, 5.5) / strength))),
        'assistCnt': max(0, int(round(rng.uniform(3, 10) * strength))),
        'money': int(round(minutes * rng.uniform(620, 780) * share * strength)),
        'totalHurtCnt': int(round(minutes * rng.uniform(2400, 3600) * damage * strength)),
        'totalHeroHurtCnt': int(round(minutes * rng.uniform(2100, 3300) * damage * strength)),
        'totalBehurtCnt': int(round(minutes * rng.uniform(2200, 3400) * taken / max(strength, 0.8))),
        'ctrlTime': int(round(minutes * rng.uniform(18, 34) * control)),
        'healCnt': int(round(minutes * rng.uniform(300, 700) * heal)),
        'towerCnt': int(round(rng.uniform(0, 3))),
        'joinGamePercent': round(rng.uniform(0.45, 0.82), 3),
        'gradeGame': round(rng.uniform(4.5, 12.5) * strength, 1),
    }


LANE_OF_HERO = {hero: lane for lane, heroes in HEROES.items() for hero in heroes}


def hero_entry(name):
    return {'name': name, 'id': None, 'icon': '', 'lane': LANE_OF_HERO.get(name, '')}


def compose_heroes(seq, team_key, own_camp_code):
    """训练赛有固定体系：七成局用同一套阵容，其余局换 1-2 个位置。

    面板与 matches 表共用这个函数，保证两边英雄完全一致。
    """
    rng = random.Random(f'heroes-{team_key}-{seq}')
    own_heroes = list(OWN_COMPS['blue' if own_camp_code == 1 else 'red'])
    enemy_heroes = list(COMPS[team_key])
    if rng.random() >= 0.7:
        slot = rng.randrange(5)
        enemy_heroes[slot] = rng.choice([h for h in HEROES[LANES[slot]] if h != enemy_heroes[slot]])
        if rng.random() < 0.4:
            slot = rng.randrange(5)
            own_heroes[slot] = rng.choice([h for h in HEROES[LANES[slot]] if h != own_heroes[slot]])
    return own_heroes, enemy_heroes


def panel(seq, team_key, index, start, own_camp_code, own_win, subs):
    team = TEAMS[team_key]
    names = list(team['players'])
    ids = [f'{team_key}-p{i}' for i in range(5)]
    if subs:
        names[3] = SUB
        ids[3] = f'{team_key}-sub'   # 替补必须是不同的人，否则聚不出"4/5 重合"
    rng = random.Random(f'{team_key}-{seq}')
    seconds = rng.randint(720, 1500)
    minutes = seconds / 60
    strength = STRENGTH[team_key]
    own_names = OWN['blue' if own_camp_code == 1 else 'red']
    own_heroes, enemy_heroes = compose_heroes(seq, team_key, own_camp_code)
    own_roles = [role(f'own-{i}', own_names[i], LANES[i], own_heroes[i], own_camp_code,
                      stats_for(rng, LANES[i], minutes, 1.0)) for i in range(5)]
    enemy_camp = 2 if own_camp_code == 1 else 1
    enemy_roles = [role(ids[i], names[i], LANES[i], enemy_heroes[i], enemy_camp,
                        stats_for(rng, LANES[i], minutes, strength)) for i in range(5)]
    blue, red = (own_roles, enemy_roles) if own_camp_code == 1 else (enemy_roles, own_roles)
    # BP 页读的是 blueTeam / redTeam 的终局名单；缺了它 parse_camp_bp 会直接跳过这一局。
    ban_rng = random.Random(f'bans-{team_key}-{seq}')
    pool = [hero for heroes in HEROES.values() for hero in heroes]
    used = set(own_heroes) | set(enemy_heroes)
    ban_pool = [hero for hero in pool if hero not in used]
    ban_rng.shuffle(ban_pool)
    blue_picks, red_picks = (own_heroes, enemy_heroes) if own_camp_code == 1 else (enemy_heroes, own_heroes)
    return {
        'returnCode': 0,
        'data': {
            'head': {'acntCamp': own_camp_code, 'gameResult': own_win,
                     'roleName': own_names[0], 'kda': '3.0'},
            'battle': {'startTime': start, 'usedTime': seconds,
                       'mapName': '训练赛', 'gameType': 4},
            'blueRoles': blue, 'redRoles': red,
            'blueTeam': {'pickHeros': list(blue_picks), 'banHeros': ban_pool[:4]},
            'redTeam': {'pickHeros': list(red_picks), 'banHeros': ban_pool[4:9]},
        },
    }



def write_bundles(out_dir, plan, team_name='1', names=None):
    """把同一批对局写成 kpl-match-data-v1 数据包。

    营地口径只认数据包（campBacked 来自 officialReplay.id），写 matches 表会被
    「营地口径」筛掉，所以这里生成 bundle。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob('mock-*.json'):
        old.unlink()
    written = 0
    for seq, team_key, start, own_code, own_win, own_heroes, enemy_heroes in plan:
        team = TEAMS[team_key]
        rng = random.Random(f'bundle-{team_key}-{seq}')
        seconds = rng.randint(720, 1500)
        minutes = seconds / 60
        own_camp = 'blue' if own_code == 1 else 'red'
        enemy_camp = 'red' if own_camp == 'blue' else 'blue'
        own_side = 'left' if own_camp == 'blue' else 'right'
        day = int(start.split()[0].split('-')[1])
        own_names = OWN[own_camp]
        players = []

        def add(camp, slot, pid, label, hero, lane_index, strength):
            raw = stats_for(rng, LANES[lane_index], minutes, strength)
            players.append({
                'camp': camp, 'side': camp, 'slot': slot, 'key': pid,
                'hero': hero, 'heroId': None, 'heroSource': 'mock', 'heroStatus': 'ok',
                'nickname': label, 'nicknameRaw': label, 'nicknameConfidence': 1.0,
                'panelSlot': slot, 'position': lane_index, 'process': None, 'sources': [],
                'final': {
                    'source': 'mock', 'partial': False, 'complete': True,
                    'kills': raw['killCnt'], 'deaths': raw['deadCnt'], 'assists': raw['assistCnt'],
                    'totalGold': raw['money'], 'damage': raw['totalHurtCnt'],
                    'taken': raw['totalBehurtCnt'], 'participation': round(raw['joinGamePercent'] * 100, 1),
                    'rating': raw['gradeGame'], 'control': raw['ctrlTime'],
                    'healing': raw['healCnt'], 'cs': 0, 'jungleGold': 0, 'towerDamage': 0,
                    'damageConversion': 0, 'takenPerDeath': 0,
                },
            })
        for i in range(5):
            add(own_camp, i, f'own-{i}', own_names[i], own_heroes[i], i, 1.0)
            add(enemy_camp, i, f'{team_key}-p{i}', team['players'][i], enemy_heroes[i], i, STRENGTH[team_key])

        score_own, score_enemy = rng.randint(8, 30), rng.randint(3, 20)
        left_score, right_score = (score_own, score_enemy) if own_side == 'left' else (score_enemy, score_own)
        winner_camp = own_camp if own_win else enemy_camp
        pool = [hero for heroes in HEROES.values() for hero in heroes]
        used = set(own_heroes) | set(enemy_heroes)
        ban_pool = [hero for hero in pool if hero not in used]
        rng.shuffle(ban_pool)
        left_picks = own_heroes if own_side == 'left' else enemy_heroes
        right_picks = enemy_heroes if own_side == 'left' else own_heroes
        camp_bp = {
            'source': 'mock', 'gameSeq': str(seq), 'mapName': '训练赛',
            'duration': seconds, 'startTime': start, 'ownSide': own_side,
            'winnerSide': own_side if own_win else ('right' if own_side == 'left' else 'left'),
            'pickOrderKnown': True, 'banCount': 8,
            'bans': {'left': [hero_entry(x) for x in ban_pool[:4]],
                     'right': [hero_entry(x) for x in ban_pool[4:9]]},
            'picks': {'left': [hero_entry(x) for x in left_picks],
                      'right': [hero_entry(x) for x in right_picks]},
            'firstPick': 'left' if own_side == 'left' else 'right',
            'lanes': {}, 'heroMeta': {}, 'teamStats': {},
        }
        bundle = {
            'schema': 'kpl-match-data-v1',
            'generatedAt': f'2026-11-{day:02d}T12:00:00',
            'team': {'name': team_name},
            'match': {
                'key': f'mock-{seq}',
                'date': {'year': 2026, 'month': 11, 'day': day, 'text': f'2026-11-{day:02d}'},
                'duration': seconds,
                'opponent': (names or {}).get(team_key) or team['name'],
                'session': '训练赛', 'mode': '训练赛',
                'ownCamp': own_camp, 'ownSide': own_side,
                'winner': winner_camp, 'winnerCamp': winner_camp,
                'scores': {'left': left_score, 'right': right_score,
                           'blue': left_score if own_side == 'left' else right_score,
                           'red': right_score if own_side == 'left' else left_score},
                'officialReplay': {'id': f'camp-{seq}', 'kind': 'personal'},
                # 两个版本，用日期后半段切分，供「版本对比」使用
                'version': '12.1.1.1' if day <= 3 else '12.2.0.1',
                'campBp': camp_bp, 'bp': '', 'result': {}, 'title': None, 'startTime': None,
            },
            'players': players,
            'sources': [], 'warnings': [], 'coverage': {}, 'roster': {},
        }
        (out / f'mock-{seq}.json').write_text(json.dumps(bundle, ensure_ascii=False), encoding='utf-8')
        written += 1
    print(f'写入 {written} 个数据包 -> {out}')


def generate(base: Path) -> dict:
    """把一整套演示数据写到 ``base``：面板进 camp_details，数据包进 matches。"""
    base = Path(base)
    panels = base / 'camp_details'
    panels.mkdir(parents=True, exist_ok=True)
    for old in panels.glob('*.json'):
        old.unlink()
    plan = []
    for key, team in TEAMS.items():
        plan += [key] * team['games']
    random.Random(7).shuffle(plan)
    seq = 900000
    entries = []
    for index, key in enumerate(plan):
        seq += 137
        day = 2 + index // 8
        hour = 12 + (index % 8)
        start = f'11-{day:02d} {hour:02d}:{(index * 7) % 60:02d}'
        own_code = 1 if index % 2 == 0 else 2
        # 青岚整体偏强（我方胜率约 35%），弱队我方胜率更高
        edge = {'T1': .35, 'T2': .55, 'T3': .6, 'T4': .8, 'T5': .7, 'T6': .9, 'T7': .9}[key]
        own_win = random.Random(index).random() < edge
        subs = key == 'T3' and index % 2 == 0
        payload = panel(seq, key, index, start, own_code, own_win, subs)
        (panels / f'{seq}.json').write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        own_heroes, enemy_heroes = compose_heroes(seq, key, own_code)
        entries.append((seq, key, start, own_code, own_win, own_heroes, enemy_heroes))
    write_bundles(base / 'matches', entries, names=BUNDLE_NAMES)
    return {'panels': panels, 'matches': base / 'matches',
            'games': sum(team['games'] for team in TEAMS.values())}


def main():
    import argparse

    parser = argparse.ArgumentParser(description='生成演示用营地数据')
    parser.add_argument('--data-dir', default=str(ROOT / 'data' / '_mock'),
                        help='写到哪个数据根（默认 data/_mock）')
    args = parser.parse_args()
    info = generate(Path(args.data_dir))
    print(f"写入 {info['games']} 局面板 -> {info['panels']}")
    print(f"写入数据包 -> {info['matches']}")
    for key, team in TEAMS.items():
        print(f"  {key} {team['name'] or '(待命名)':8} {team['games']:2} 局")


if __name__ == '__main__':
    main()
