"""Read-only browser acceptance for the interactive analysis components."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results'
BASE='http://127.0.0.1:8766'
checks=[]
errors=[]


def check(name,condition):
    checks.append({'name':name,'ok':bool(condition)})


with sync_playwright() as p:
    browser=p.chromium.launch()
    page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(BASE+'/studio?qa=analysis-scatter#players',wait_until='networkidle')
    page.wait_for_selector('.av-plot svg')
    check('表现散点可用',page.locator('circle[data-point]').count()>0)
    page.locator('circle[data-point]').first.focus()
    page.keyboard.press('Enter')
    check('键盘检查对象',page.locator('.av-inspector h3').inner_text()!='点选一个对象')
    page.locator('[data-axis="y"]').select_option('participation')
    check('切换坐标指标','参团率' in page.locator('.av-plot-title').inner_text())
    page.locator('[data-minimum]').select_option('10')
    check('样本筛选空态',page.locator('.av-plot .av-empty').count()==1)
    page.locator('[data-minimum]').select_option('1')
    page.locator('[data-view="matrix"]').click()
    check('矩阵显示原值',page.locator('.av-matrix tbody tr').count()>0)
    page.locator('[data-sort="kda"]').click()
    with page.expect_download() as download:
        page.locator('[data-export]').click()
    check('导出当前数据',download.value.suggested_filename.endswith('.csv'))
    page.screenshot(path=str(OUT/'analysis-matrix-desktop.png'),full_page=False)

    page.goto(BASE+'/studio?qa=analysis-compare#compare/player',wait_until='networkidle')
    page.wait_for_selector('.av-dumbbells')
    a,b=page.locator('#compare-a').input_value(),page.locator('#compare-b').input_value()
    page.locator('#compare-swap').click()
    check('交换对比对象',page.locator('#compare-a').input_value()==b and page.locator('#compare-b').input_value()==a)
    page.locator('#compare-a').select_option(a)
    check('相同对象不制造差异',page.locator('#compare-output .empty-state').count()==1)
    page.locator('#compare-a').select_option(b)
    page.screenshot(path=str(OUT/'analysis-compare-desktop.png'),full_page=True)

    page.goto(BASE+'/studio?qa=analysis-hero#heroes',wait_until='networkidle')
    page.wait_for_selector('.hero-card')
    href=page.locator('.hero-card').first.get_attribute('href')
    page.goto(BASE+'/studio?qa=analysis-profile'+href,wait_until='networkidle')
    page.wait_for_selector('.av-trend-plot svg')
    page.locator('#entity-metric').select_option('damage')
    page.set_viewport_size({'width':1100,'height':900})
    page.wait_for_timeout(100)
    check('指标切换及重排保持一致','输出' in page.locator('.av-trend-detail').inner_text())
    match_href=page.locator('.av-trend-detail a').get_attribute('href')
    page.goto(BASE+'/studio?qa=analysis-timeline'+match_href,wait_until='networkidle')
    page.wait_for_selector('.av-range-label input')
    before=page.locator('.av-timeline-readout').inner_text()
    page.locator('.av-range-label input').evaluate("el=>{el.value=0;el.dispatchEvent(new Event('input',{bubbles:true}));}")
    check('时间游标改变原值',page.locator('.av-timeline-readout').inner_text()!=before)
    page.locator('.av-range-label input').focus()
    page.keyboard.press('ArrowRight')
    check('时间游标支持方向键',page.locator('.av-range-label input').input_value()=='1')
    page.locator('[data-economy="total"]').click()
    check('双方经济可切换',page.locator('.av-timeline-plot path').count()>=2)
    page.screenshot(path=str(OUT/'analysis-timeline-desktop.png'),full_page=False)

    page.goto(BASE+'/studio?qa=analysis-team#team',wait_until='networkidle')
    page.wait_for_selector('.av-process-matrix')
    check('15分钟缺失不外推',page.locator('.av-process-matrix tbody tr').first.locator('td').last.inner_text()=='—')
    page.screenshot(path=str(OUT/'analysis-team-desktop.png'),full_page=True)
    page.locator('.page-filter>summary').click()
    page.locator('#filter-from').fill('2099-01-01')
    page.locator('#apply-filters').click()
    page.wait_for_selector('.team-summary .team-kpi b:text-is("0")')
    check('战队汇总遵守筛选',page.locator('.team-summary .team-kpi b').first.inner_text()=='0')

    # QA-only synthetic rows are mounted in this browser, never persisted to the app.
    page.evaluate("""async()=>{
      const {mountPerformanceExplorer,mountEntityTrend}=await import('/assets/analysis-visuals.js?v=2');
      document.querySelector('#content').innerHTML='<h1>QA 合成数据</h1><div id="qa-explorer"></div><div id="qa-trend"></div>';
      mountPerformanceExplorer(document.querySelector('#qa-explorer'),[
        {label:'缺失样本',matches:4,kda:null,gpm:null,dpm:10,participation:null,winRate:null},
        {label:'零值样本',matches:4,kda:0,gpm:0,dpm:0,participation:0,winRate:0,wins:0,decided:4},
        {label:'有效样本',matches:5,kda:3,gpm:500,dpm:3000,participation:60,winRate:60,wins:3,decided:5}
      ]);
      mountEntityTrend(document.querySelector('#qa-trend'),[
        {date:'2026-01-01',matchKey:'qa-1',gold:10},{date:'2026-01-02',matchKey:'qa-2',gold:null},{date:'2026-01-03',matchKey:'qa-3',gold:30}
      ],'gold');
    }""")
    page.locator('[data-view="matrix"]').click()
    check('缺失矩阵单独标记',page.locator('.av-missing').count()>=3)
    check('趋势缺失形成断线',page.locator('.av-trend-line').get_attribute('d').count('M')==2)
    check('滚动样本不补零','2 个有效值' in page.locator('.av-trend-detail').inner_text())
    for width in [320,390,768]:
        page.set_viewport_size({'width':width,'height':844})
        for route in ['players','compare/hero']:
            page.goto(BASE+'/studio?qa=analysis-mobile-'+str(width)+'-'+route+'#'+route,wait_until='networkidle')
            page.wait_for_selector('#content h1')
            check(f'{width}px {route} 无页面横向溢出',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
            if width==390:
                page.screenshot(path=str(OUT/('analysis-'+route.replace('/','-')+'-mobile.png')),full_page=True)
    check('无 JavaScript 错误',not errors)
    browser.close()

report={'checks':checks,'errors':errors}
(OUT/'analysis-visuals-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=True))
raise SystemExit(0 if all(item['ok'] for item in checks) else 1)
