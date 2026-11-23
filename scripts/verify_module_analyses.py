"""分析专题整层下线回归（2026-11-13）。纯静态检查，不依赖服务/浏览器。

跑法：python scripts/verify_module_analyses.py
验收：专题入口、专题页、专题接口零残留；普通页面所需的数据端点仍在。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
failures = []
notes = []


def source(name):
    return (ROOT / name).read_text(encoding='utf-8')


# 1) 专题层的三个前端文件已物理删除
for name in ('v3/public/navigation.js', 'v3/public/depth.js',
             'v3/public/analysis-pages.js',
             'v3/public/bp-lab.js', 'v3/public/bp-lab.css'):
    if (ROOT / name).exists():
        failures.append(f'专题前端文件仍存在：{name}')
notes.append('专题导航 / 专题页 / 模块分析页 / 旧 BP 前端五个文件已删除')

# 2) 前端不再有任何专题入口、专题接口或隐藏 rail
banned_js = {
    '#topic/': '专题路由', '#study/': '专题路由', '/api/depth/': '深度专题接口',
    'depth/catalog': '专题目录接口', 'v3/research/catalog': '专题目录接口',
    '/api/decision/catalog': '决策目录接口', '/api/decision/resource': '资源专题接口',
    'analysis-rail': '专题入口导航', 'createDepth': '专题页渲染器',
    'createAnalysisPages': '模块分析页', 'analysisNavigation': '专题入口生成',
    'saveReport': '专题报告保存表单',
}
js_files = sorted((ROOT / 'v3/public').glob('*.js'))
for path in js_files:
    text = path.read_text(encoding='utf-8')
    for needle, label in banned_js.items():
        if needle in text:
            failures.append(f'{path.name} 仍有{label}：{needle}')
notes.append(f'前端 {len(js_files)} 个模块：专题入口/接口/隐藏 rail 零残留')

# 3) 后端不再暴露专题接口
banned_py = {
    'depth_api.py': ['def analyses_catalog', "@router.get('/catalog'", "@router.get('/analysis/"],
    'v3/serve.py': ['def research_result', 'def research_catalog', 'def get_research',
                    'def save_research_report', "@router.get('/api/v3/research/{topic}'"],
    'workbench_api.py': ['def _catalog', "@router.get('/catalog'", 'ANALYSES = ('],
    'studio_research.py': ["'player_form'", "'player_pairs'", "'resource_efficiency'"],
}
for name, needles in banned_py.items():
    text = source(name)
    for needle in needles:
        if needle in text:
            failures.append(f'{name} 仍有专题代码：{needle}')
notes.append('后端：分析目录 / 专题取数 / 专题保存 / 三个选手专题全部删除')

# 4) 普通页面依赖的数据端点重新构建到位
facts = source('depth_api.py')
for needle in ("prefix='/api/v3/facts'", "'lane_matchup', 'equip_matrix', 'equip_impact'",
               "return {'payload': analysis_payload("):
    if needle not in facts:
        failures.append(f'普通数据端点缺：{needle}')
app = source('v3/public/app.js')
feat = source('v3/public/features.js')
# 旧 bp-lab.js/css 已下线，BP 入口现在是 bp-studio.js（app.js 的 mods.bp.mount 指向它）。
# 这里同步盯住当前实现的数据端点，避免日后又退回专题式目录接口。
bp = source('v3/public/bp-studio.js')
if '/api/v3/facts/lane_matchup' not in app:
    failures.append('单局复盘未改用新数据端点')
if "'v3/facts/lane_matchup'" not in feat:
    failures.append('英雄详情未改用新数据端点')
if 'CATALOG_URL' in bp or "state.catalog" in bp:
    failures.append('BP 概览仍依赖分析目录接口')
if '/api/v3/bp-studio' not in bp:
    failures.append('BP 概览主数据接口丢失')
if 'bp-studio/target' not in bp:
    failures.append('BP 目标下钻接口丢失')
serve = source('v3/serve.py')
if "@router.get('/api/v3/bp-lab/diagnose')" not in serve:
    failures.append('BP 己方英雄诊断后端路由丢失')
if "@router.get('/api/v3/research/reports')" not in serve:
    failures.append('报告库读取接口丢失')
notes.append('普通页面：单局复盘 / 英雄详情 / BP 概览九区 + 英雄诊断 / 报告库数据链路仍在')

print('== 结果 ==')
for note in notes:
    print('  ·', note)
if failures:
    print('== 失败 ==')
    for item in failures:
        print('  x', item)
    print(json.dumps({'ok': False, 'failures': failures}, ensure_ascii=False))
    sys.exit(1)
print('全部通过')
