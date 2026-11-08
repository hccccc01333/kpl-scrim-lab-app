"""Exercise product input paths against an isolated database; retain all artifacts."""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.request import urlopen
from playwright.sync_api import sync_playwright
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests.test_analysis_data import make_db, bundle, C_BLUE, C_RED

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'test-results'/('input-details-'+uuid.uuid4().hex[:8])
OUT.mkdir(parents=True)
DB=OUT/'training.sqlite3'
make_db(DB)
MATCHES=OUT/'matches';MATCHES.mkdir()
original=bundle('example-bundle','2026-10-09',900,C_BLUE,C_RED)
original['match'].update(ownCamp='blue',winnerCamp=None)
(MATCHES/'match.json').write_text(json.dumps(original),encoding='utf-8')
BASE='http://127.0.0.1:8774'
env=dict(os.environ,TRAINING_PORT='8774',TRAINING_DB=str(DB),ANALYSIS_MATCHES=str(MATCHES),ANALYSIS_IMPORTS=str(OUT/'imports'),STUDIO_RESULTS_DB=str(OUT/'studio.sqlite3'),PYTHONIOENCODING='utf-8')
process=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
checks=[];errors=[]
def check(name,condition):
 checks.append({'name':name,'ok':bool(condition)})
 if not condition:raise AssertionError(name)
try:
 for _ in range(120):
  try:urlopen(BASE+'/api/health',timeout=.3);break
  except OSError:time.sleep(.1)
 with sync_playwright() as p:
  browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1000});dialogs=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  def dialog(d):dialogs.append(d.message);d.accept()
  page.on('dialog',dialog)
  def go(route):page.goto(BASE+'/studio#'+route,wait_until='networkidle');page.wait_for_selector('#content h1')
  go('overview')
  page.evaluate("""()=>localStorage.setItem('training-unsaved',JSON.stringify({id:'empty',status:'draft',players:Array.from({length:10},(_,i)=>({side:i<5?'left':'right',slot:i%5,hero:'',playerId:''})),scores:{left:'',right:''},bp:{bans:{left:[],right:[]},picks:{left:[],right:[]}}}))""")
  go('new');check('空白缓存不提示恢复',not dialogs)
  page.locator('[data-meta=opponent]').fill('');page.locator('[data-meta=opponent]').fill('撤销内容');page.locator('[data-meta=opponent]').fill('')
  check('清空后没有未保存缓存',page.evaluate("localStorage.getItem('training-unsaved')")==None)
  go('overview');go('new');check('再次进入空页不提示',not dialogs)
  page.locator('[data-meta=opponent]').fill('需要恢复的对手');go('overview');go('new')
  check('有内容草稿恢复成功',page.locator('[data-meta=opponent]').input_value()=='需要恢复的对手' and any('继续填写' in d for d in dialogs))
  page.locator('#duration-slider').evaluate("el=>{el.value=181;el.dispatchEvent(new Event('input',{bubbles:true}));}")
  check('时长滑杆按分秒同步',page.locator('#duration-minutes').input_value()=='3' and page.locator('#duration-seconds').input_value()=='1')
  page.locator('[data-obj-add="tyrant:left"]').click()
  page.locator('[data-obj-slider="tyrant:left:0"]').evaluate("el=>{el.value=90;el.dispatchEvent(new Event('input',{bubbles:true}));}")
  check('资源事件滑杆同步时间',page.locator('[data-obj-time="tyrant:left:0"]').input_value()=='1:30')
  page.locator('#save-draft').click();page.wait_for_function("!localStorage.getItem('training-unsaved')")
  saved_id=page.url.split('#edit/')[1];go('edit/'+saved_id)
  check('时长与事件保存后重开',page.locator('#duration-readout').inner_text()=='3:01' and page.locator('[data-obj-time="tyrant:left:0"]').input_value()=='1:30')
  prior=len(dialogs);go('new');check('已保存后新建不再恢复旧草稿',len(dialogs)==prior)
  go('roster');team_options=page.locator('#team-preset option').all_inner_texts();check('内置18支KPL队与自定义选项',len(team_options)>=19 and any('自定义战队' in item for item in team_options))
  page.locator('#team-preset').select_option(label='成都AG超玩会');page.locator('#new-player').fill('测试新增打野');page.locator('#new-player-lane').select_option(label='打野');page.locator('#add-player').click()
  page.wait_for_function("document.querySelector('#new-player').value===''")
  settings=page.request.get(BASE+'/api/state').json()['settings'];new_player=next(v for v in settings['roster'] if v['name']=='测试新增打野')
  check('战队与默认分路持久化',settings['teamName']=='成都AG超玩会' and new_player['position']=='打野')
  go('new');page.select_option('[data-meta=side]','left');page.locator('[data-player="left-0"][data-key=playerId]').select_option(new_player['id'])
  check('绑定队员后建议默认分路',page.locator('[data-player="left-0"][data-key=position]').input_value()=='打野')
  page.locator('[data-player="left-0"][data-key=position]').select_option('中路')
  check('实际分路可独立调整',page.locator('[data-player="left-0"][data-key=position]').input_value()=='中路')
  go('identity');page.locator('[data-identity-lane]').first.select_option('游走');page.locator('#identity-save').click();page.wait_for_timeout(400)
  settings2=page.request.get(BASE+'/api/state').json()['settings'];check('身份页可以直接保存分路',settings2['roster'][0]['position']=='游走')
  go('match/example-bundle');page.wait_for_selector('[data-save-bp]')
  page.locator('[data-capture-bp="bans:left:0"]').select_option('大乔');page.locator('[data-capture-bp="picks:left:1"]').select_option('关羽');page.locator('[data-capture-bp="picks:right:0"]').select_option('吕布')
  page.locator('[data-capture-first]').select_option('right');page.locator('[data-save-bp]').click();page.wait_for_selector('[data-bp-status]:has-text("已保存")')
  go('match/example-bundle');check('已有数据包BP补录后可重开',page.locator('[data-capture-bp="picks:left:1"]').input_value()=='关羽' and page.locator('[data-capture-bp="picks:left:0"]').input_value()=='')
  changed=json.loads((MATCHES/'match.json').read_text(encoding='utf-8'));changed['match'].pop('bp');check('BP补录保留所有原始证据',changed==original)
  go('bp');check('补录进入BP分析',page.locator('.bp-row').count()>=2)
  channel=page.request.post(BASE+'/api/channels',data={'match':{'opponent':'BP通道测试'}}).json()
  go('channel/'+channel['id']);page.locator('[data-capture-bp="bans:right:0"]').select_option('镜');page.locator('[data-save-bp]').click();page.wait_for_selector('[data-bp-status]:has-text("已保存")')
  go('channel/'+channel['id']);check('采集通道BP持久化',page.locator('[data-capture-bp="bans:right:0"]').input_value()=='镜')
  page.screenshot(path=str(OUT/'channel.png'),full_page=False)
  go('clean');page.wait_for_selector('[data-prepare-cell]')
  with page.expect_response('**/api/studio/clean/preview'):page.locator('#prepare-trim').uncheck()
  page.wait_for_function("!document.querySelector('#prepare-run').disabled")
  check('规则修改自动预览','已预览' in page.locator('#prepare-status').inner_text() or '检查完成' in page.locator('#prepare-status').inner_text())
  cell=page.locator('[data-prepare-cell]').first;row_id=cell.get_attribute('data-prepare-cell');cell.fill('1234')
  with page.expect_response('**/api/studio/clean/preview'):cell.press('Tab')
  page.wait_for_function("!document.querySelector('#prepare-run').disabled")
  check('清洗修订自动更新',page.locator('[data-prepare-cell]').first.input_value()=='1234')
  page.screenshot(path=str(OUT/'clean.png'),full_page=False)
  page.locator('#prepare-title').fill('可验证的清洗结果');page.locator('#prepare-publish').click();page.wait_for_url('**#datasets')
  datasets=page.request.get(BASE+'/api/studio/datasets').json()['datasets'];saved=page.request.get(BASE+'/api/studio/datasets/'+datasets[0]['id']).json()
  check('保存按钮真实生成校正数据集',any(row['_rowId']==row_id and row['gold']==1234 for row in saved['rows']))
  go('clean');page.wait_for_selector('[data-prepare-cell]');page.route('**/api/studio/clean/preview',lambda route:route.fulfill(status=503,content_type='application/json',body='{"detail":"临时检查失败，请重试"}'))
  page.locator('#prepare-run').click();page.wait_for_selector('#prepare-status.error')
  check('失败提供反馈且按钮可重试',page.locator('#prepare-run').is_enabled())
  page.unroute('**/api/studio/clean/preview');page.locator('#prepare-run').click();page.wait_for_function("!document.querySelector('#prepare-run').disabled && !document.querySelector('#prepare-status').classList.contains('error')")
  check('清洗失败后可恢复',True)
  for topic,group in [('hero_benchmark','对比'),('hero_pool','选手'),('hero_combos','BP'),('player_form','选手'),('player_pairs','选手'),('resource_efficiency','选手'),('tempo','战队'),('swing_windows','战队'),('session_summary','战队')]:
   go('topics/'+topic);check('直达功能 '+topic,page.locator('.topic-card').count()==0 and page.locator('#navigation .nav-item.active').inner_text()==group)
  go('compare/player')
  source=page.get_by_label('纳入其他来源')
  check('默认以营地为分析来源',not source.is_checked())
  source.check();page.wait_for_selector('.av-dumbbell')
  check('对比展示原始指标和两边证据入口',page.get_by_text('查看 A 的逐局记录').count()==1 and page.get_by_text('查看 B 的逐局记录').count()==1)
  page.locator('#compare-output').screenshot(path=str(OUT/'comparison.png'))
  page.goto(BASE+'/assets/collection-guide.html?section=screenshots',wait_until='networkidle');page.wait_for_function("document.querySelectorAll('.collection-seven img').length===7 && [...document.querySelectorAll('.collection-seven img')].every(i=>i.complete&&i.naturalWidth>1000)")
  check('七张真实结算图并遮罩昵称',page.locator('.collection-seven .capture-name-mask').count()==70)
  for section,count in [('video',3),('official',1)]:
   page.goto(BASE+'/assets/collection-guide.html?section='+section,wait_until='networkidle');check('真实采集示例 '+section,page.locator('.real-capture-example img').count()==count)
  go('import');check('导入前能看字段与模板','导入字段与填写要求' in page.locator('#content').inner_text() and page.locator('a[download]').count()>0)
  page.set_viewport_size({'width':390,'height':844})
  for route in ['new','roster','identity','clean','channel/'+channel['id'],'compare/player']:
   go(route);check('移动端无页面横溢 '+route,page.evaluate('document.documentElement.scrollWidth<=innerWidth+3'))
  check('无浏览器脚本错误',not errors)
  browser.close()
finally:
 process.terminate();process.wait(timeout=15)
 report={'checks':checks,'errors':errors,'artifacts':str(OUT)}
 (ROOT/'test-results/input-details-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'checks':len(checks),'passed':sum(c['ok'] for c in checks),'errors':errors,'artifacts':str(OUT)},ensure_ascii=False))
