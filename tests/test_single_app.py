"""只允许一套服务：采集接口与分析接口必须在同一个 app 里。

历史问题：``v3/serve.py`` 曾经自建一个只有分析路由的 FastAPI app，
``python v3/serve.py --port 88xx`` 起出来的进程没有 ``/api/channels``、
``/api/camp/sync``，采集页只能显示「营地数据暂时读不到」——
前端是好的，后端那一半根本不在。

这组测试守住「一套」：serve.py 只导出路由、入口把端口交给 server.py，
而 server.py 的 app 里同时有采集接口、分析路由和前端静态资源。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVE = ROOT / 'v3' / 'serve.py'
SERVER = ROOT / 'server.py'


def _main_block(tree: ast.Module) -> str:
    """取 ``if __name__ == '__main__':`` 的语句体，单独检查入口行为。"""
    for node in tree.body:
        if not isinstance(node, ast.If):
            continue
        if isinstance(node.test, ast.Compare) and ast.unparse(node.test) == "__name__ == '__main__'":
            return '\n'.join(ast.unparse(statement) for statement in node.body)
    return ''


def test_v3_serve_does_not_build_its_own_app():
    source = SERVE.read_text(encoding='utf-8')
    tree = ast.parse(source)
    own_app = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'FastAPI'
    ]
    assert not own_app, 'v3/serve.py 又自建了 app：分析接口必须挂进 server.py 的同一套 app'
    assert 'uvicorn.run' not in source, 'v3/serve.py 不能再自己起服务'


def test_v3_serve_entry_hands_port_to_server():
    tree = ast.parse(SERVE.read_text(encoding='utf-8'))
    block = _main_block(tree)
    assert block, 'v3/serve.py 缺少 __main__ 入口'
    assert 'server.py' in block, 'v3/serve.py 的入口应启动 server.py（唯一的那套 app）'
    assert 'TRAINING_PORT' in block, 'v3/serve.py 的 --port 应通过 TRAINING_PORT 传给 server.py'


def test_one_app_serves_collection_analysis_and_static():
    source = SERVER.read_text(encoding='utf-8')
    # 采集接口（前端采集页的最小依赖）
    for needle in ("@app.get('/api/health')", "@app.get('/api/channels')",
                   "@app.get('/api/camp/sync')", "@app.post('/api/camp/sync')"):
        assert needle in source, f'server.py 缺少采集接口 {needle}'
    # 分析路由与前端静态资源挂进同一个 app
    assert 'app.include_router(module.router)' in source, 'V3 分析路由没有并进同一个 app'
    assert "app.mount('/static'" in source, 'V3 前端没有从同一个 app 提供'
    # 大响应压缩随 app 一起保留（以前只在旁支 app 上）
    assert 'GZipMiddleware' in source, '工作台 app 缺少 gzip，跨局明细会退化成未压缩'


def test_v3_router_actually_mounts():
    """v3 路由必须真的挂上：它一旦导入失败，采集接口还活着、分析接口全 404，
    界面看起来只是「数据读不到」，很难当场发现。"""
    import server

    assert server.V3_MODULE is not None, 'v3 路由没挂上，分析接口会全部 404'
    paths = {getattr(route, 'path', '') for route in server.app.routes}
    assert '/api/health' in paths
    # 挂载成功时 v3 的候选路由能解析到（FastAPI 把子路由包成 IncludedRouter）
    client_routes = server.V3_MODULE.router.routes
    assert any(getattr(route, 'path', '').startswith('/api/v3/')
               for route in client_routes), 'v3 路由表里没有 /api/v3/*'
