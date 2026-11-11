"""Create an isolated, clearly labelled demonstration dataset for the workbench.

The demo runs the same single-app server as the real workbench. All records are
synthetic; no real match, settings, or replay files are read or modified.
Generation only writes into a new directory supplied by the caller.
"""
import json
import math
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from scripts import make_mock_camps as mock
import team_clusters
import workspace_store


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, separators=(',', ':'))


def create(root):
    root = Path(root)
    if root.exists():
        raise ValueError('演示目录已存在，不会覆盖已有数据。')
    root.mkdir(parents=True)
    data = root / 'data'; data.mkdir()
    matches, camp, replays = (data / name for name in ('matches', 'camp_details', 'official_replays'))
    for folder in (matches, camp, replays, data / 'imports', data / 'builds'):
        folder.mkdir()
    db = data / 'training.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.execute('CREATE TABLE settings(id INTEGER PRIMARY KEY, body TEXT)')
        conn.execute('CREATE TABLE matches(id TEXT PRIMARY KEY, body TEXT)')
        roster = [{'id': f'demo-own-{i}', 'name': name, 'label': name, 'position': lane,
                   'team': '星澜', 'archived': False}
                  for i, (name, lane) in enumerate(zip(['星澜·牧川', '星澜·逐风', '星澜·知夏', '星澜·远舟', '星澜·小满'], mock.LANES))]
        conn.execute('INSERT INTO settings VALUES(1,?)', (json.dumps({'teamName':'星澜', 'coach':'林教练',
                     'season':'演示赛季', 'roster':roster, 'teams':[], 'aliases':{member['name']:member['id'] for member in roster}}, ensure_ascii=False),))
    ws = workspace_store.Workspace(db).ensure_schema()
    own_id = ws.upsert_team('demo-own', name='星澜', coach='林教练')
    for i, member in enumerate(roster):
        ws.upsert_player(member['id'], team_id=own_id, name=member['name'], position=member['position'], camp_user_id=f'own-{i}')
    rng = random.Random(6123)
    plan = [key for key, team in mock.TEAMS.items() for _ in range(team['games'])]
    rng.shuffle(plan)
    opponent_names = {'T1':'青岚','T2':'赤霄','T3':'苍梧','T4':'云起','T5':'白虎','T6':'山海','T7':'辰星'}
    for index, key in enumerate(plan):
        seq = str(9100000 + index)
        dt = date(2026, 9, 1) + timedelta(days=index * 2)
        start = dt.isoformat() + ' 19:30'
        own_code = 1 if index % 2 == 0 else 2
        won = rng.random() < {'T1':.38,'T2':.55,'T3':.62,'T4':.68,'T5':.7,'T6':.75,'T7':.8}[key]
        panel = mock.panel(seq, key, index, start, own_code, won, False)
        content = panel['data']; own = 'blue' if own_code == 1 else 'red'; enemy = 'red' if own=='blue' else 'blue'
        own_roles, enemy_roles = content[own+'Roles'], content[enemy+'Roles']
        for i, role in enumerate(own_roles): role['basicInfo']['roleName'] = roster[i]['name']
        duration = int(content['battle']['usedTime']); content['battle']['startTime'] = start
        own_heroes=[r['battleRecords']['usedHero']['heroName'] for r in own_roles]
        enemy_heroes=[r['battleRecords']['usedHero']['heroName'] for r in enemy_roles]
        pool=[hero for hs in mock.HEROES.values() for hero in hs if hero not in own_heroes+enemy_heroes]
        rng.shuffle(pool)
        for side, roles in [('blue',content['blueRoles']),('red',content['redRoles'])]:
            content[side+'Team']={'pickHeros':[{'heroName':r['battleRecords']['usedHero']['heroName']} for r in roles],
                                  'banHeros':[{'heroName':x} for x in (pool[:4] if side=='blue' else pool[4:8])]}
        write_json(camp / f'{seq}.json', panel)
        teamscore = (rng.randint(15,27), rng.randint(4,14))
        bs = sum(role['battleStats']['killCnt'] for role in content['blueRoles'])
        rs = sum(role['battleStats']['killCnt'] for role in content['redRoles'])
        records=[]; replay_players=[]; player_map={}; position_players=[]
        for side, code in [('blue','1'),('red','2')]:
            for slot, role in enumerate(content[side+'Roles']):
                basic, st = role['basicInfo'], role['battleStats']; hero=role['battleRecords']['usedHero']['heroName']; pid=basic['playerId']; obj=code+str(slot)
                replay_players.append({'camp':code,'playerId':pid,'heroId':int(obj),'hero':hero})
                player_map[obj]={'camp':code,'heroId':int(obj)}
                records.append({'key':f'{side}-{slot}','camp':side,'slot':slot,'hero':hero,'nickname':basic['roleName'],'position':mock.LANES[slot],
                                'replayEntityId':int(obj),'final':{'source':'演示','complete':True,'partial':False,
                                'kills':st['killCnt'],'deaths':st['deadCnt'],'assists':st['assistCnt'],'totalGold':st['money'],
                                'damage':st['totalHeroHurtCnt'],'taken':st['totalBehurtCnt'],'participation':round(st['joinGamePercent']*100,1)}})
                sign = 1 if side=='blue' else -1
                path=[]
                for second in range(duration+1):
                    wave=math.sin(second/110+slot*.75+index*.11); orbit=math.cos(second/150+slot*.9)
                    x=max(-52,min(52,sign*(-39+second/duration*45)+wave*12+(slot-2)*9))
                    y=max(-52,min(52,sign*(-39+second/duration*45)+orbit*13-(slot-2)*9))
                    path.append([round(x,2),round(y,2)])
                position_players.append({'playerId':pid,'posArr':path})
        sample_n=max(3,duration//30+1); blue_gold=[]; red_gold=[]; timeline=[]
        blue_final=sum(r['battleStats']['money'] for r in content['blueRoles']);red_final=sum(r['battleStats']['money'] for r in content['redRoles'])
        amplitude=rng.randint(800,2000); phase=rng.uniform(0,math.pi*2)
        for i in range(sample_n):
            ratio=i/(sample_n-1);t=round(duration*ratio)
            wave=amplitude*math.sin(math.pi*ratio)*math.sin(phase+ratio*math.pi*3)
            bg=round(2500+(blue_final-2500)*ratio+wave)
            rg=round(2500+(red_final-2500)*ratio-wave*.75)
            if blue_gold: bg=max(blue_gold[-1],bg); rg=max(red_gold[-1],rg)
            blue_gold.append(bg);red_gold.append(rg);timeline.append({'gameTime':t,'blueGold':bg,'redGold':rg})
        events=[];fights=[];deaths=[]
        for j in range(5, max(6,duration//100)):
            t=min(duration-1,j*100); actor='1'+str(j%5); victim='2'+str((j+1)%5)
            events.append({'eventType':'dragontower','dtType':'1' if j%3 else '2','dtId':str(j),'timeSec':t,'killerCamp':'1','killerId':actor})
            picked=rng.sample(range(10),rng.randint(6,10))
            parts=[{'camp':str(1+i//5),'timeSec':t+rng.randint(0,8),'objID':str(1+i//5)+str(i%5)} for i in picked]
            kills=[]
            for k in range(rng.randint(1,4)):
                killcamp=rng.choice(['1','2']); victimcamp='2' if killcamp=='1' else '1';victimslot=rng.randrange(5)
                victimobj=victimcamp+str(victimslot); kt=t+3+k*3
                kills.append({'killerCamp':killcamp,'timeSec':kt,'objID':victimobj})
                pos=position_players[(0 if victimcamp=='1' else 5)+victimslot]['posArr'][kt]
                deaths.append({'timeSec':kt,'camp':victimcamp,'objID':victimobj,'x':pos[0],'y':pos[1]})
            details=[{'objID':str(1+i//5)+str(i%5),'hurt':rng.randint(1000,8000),'taken':rng.randint(1000,8000),
                      'heal':rng.randint(0,1000),'hardCtrl':rng.randint(0,8),'softCtrl':rng.randint(0,5),'beginHP':8000,'endHP':rng.randint(0,7000)} for i in picked]
            fights.append({'fightId':str(j),'startSec':t,'endSec':t+15,'participants':parts,'kills':kills,'details':details})
            events.append({'eventType':'battle','timeSec':t,'endSec':t+15,'fightId':str(j),'kills':[]})
        normalized={'schema':'camp-replay-v1','source':{'kind':'demo','gameSeq':seq},
                    'match':{'durationSec':duration,'winCamp':str(own_code if won else 3-own_code)},
                    'economy':{'blue':blue_gold,'red':red_gold,'diff':[a-b for a,b in zip(blue_gold,red_gold)],'note':'模拟经济曲线'},
                    'players':replay_players,'battles':{'playerMap':player_map,'fights':fights,'deaths':deaths},'events':{'key':events}}
        folder=replays/f'camp-{seq}';folder.mkdir();write_json(folder/'normalized.json',normalized);write_json(folder/'positions.json',{'players':position_players})
        from bp_camp import parse_camp_bp
        bp=parse_camp_bp(panel,seq)
        match_key='demo-'+seq
        bundle={'schema':'kpl-match-data-v1','generatedAt':start,'match':{'key':match_key,'title':'演示训练赛',
                'date':{'text':dt.isoformat()},'duration':duration,'opponent':opponent_names[key], 'session':'晚间训练',
                'mode':'训练赛','ownCamp':own,'winnerCamp':own if won else enemy,'scores':{'left':bs,'right':rs,'blue':bs,'red':rs},
                'officialReplay':{'id':f'camp-{seq}','kind':'demo'},'campBp':bp},
                'team':{'name':'星澜','timeline':timeline},'players':records,'sources':[],'warnings':['这是生成的演示数据，并非真实对局。']}
        write_json(matches/f'{match_key}.json',bundle)
        ws.upsert_match(match_key,date=dt.isoformat(),session='晚间训练',mode='训练赛',version='演示版本 A' if index<16 else '演示版本 B',
                        own_team_id=own_id,own_side=own,winner=own if won else enemy,score={'blue':bs,'red':rs},duration=duration,status='draft',source='demo')
        if bp: ws.upsert_bp(match_key,bans=bp['bans'],picks=bp['picks'])
    # Give clustered opponents explicit fictional names in the isolated database.
    clustered=team_clusters.list_teams(camp,db)
    for team in clustered['teams']:
        ids=[p['id'] for p in team['players']]
        team_key=next((key for key in opponent_names if any(str(pid).startswith(key+'-') for pid in ids)),None)
        if team_key: team_clusters.rename_team(db,team['id'],opponent_names[team_key],None)
    ws.save_training(goal='提升参团效率',intervention='联动专项与赛后复盘',start_date='2026-10-10',end_date='2026-10-20',metric='participation',target=65)
    write_json(root/'DEMO.json',{'type':'synthetic-v3','matches':len(plan),'notice':'全部为虚构演示数据'})
    return root
