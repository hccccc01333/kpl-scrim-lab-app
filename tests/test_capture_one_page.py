"""采集页只允许是一个页面。

营地同步 / 截图 OCR / 录屏 / 回放 / 对局审查原先各占一个路由（#ingest、#shots、
#videos、#replays、#review），教练在一个流程里要来回跳四五个页面、数据还各取一遍。
2026-11-16 起它们是同一个 #ingest 页面的五个页签：旧链接照常可用，路由把旧名字
映射回采集页，页面自己按 hash 决定显示哪一块。

这组测试守住「一页」这个结构，别又拆回散页。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'v3' / 'public'


def test_old_source_routes_map_back_to_ingest():
    app = (PUBLIC / 'app.js').read_text(encoding='utf-8')
    for name in ('shots', 'videos', 'replays', 'review'):
        assert f"{name}: 'ingest'" in app, f'#{name} 没有映射回 #ingest'


def test_capture_page_renders_one_page_tabs():
    capture = (PUBLIC / 'capture-page.js').read_text(encoding='utf-8')
    assert 'cap-tabs' in capture, '采集页没有页签导航'
    for tab in ("'camp'", "'shots'", "'videos'", "'replays'", "'review'"):
        assert tab in capture, f'采集页缺少 {tab} 页签'
    assert 'data-source-section' in capture, '素材页没有作为内嵌区块渲染'
    assert 'reviewPages()?.body' in capture, '审查明细没有内嵌到采集页'


def test_sources_and_review_expose_embedded_bodies():
    sources = (PUBLIC / 'sources-page.js').read_text(encoding='utf-8')
    review = (PUBLIC / 'review-page.js').read_text(encoding='utf-8')
    assert 'function body(name, value)' in sources, '素材页没有单独导出正文'
    assert 'function hydrate(values, hooks' in sources, '素材页没有内嵌挂载入口'
    assert 'function body(id, value, embedded = false)' in review, '审查页没有单独导出正文'
    assert 'function snapshot(id)' in review, '审查页没有把最新通道对象交给采集页'


def test_features_hands_sources_and_review_to_capture():
    features = (PUBLIC / 'features.js').read_text(encoding='utf-8')
    assert 'sources: () => sourcePages' in features, '采集页没拿到素材页'
    assert 'review: () => reviewPage' in features, '采集页没拿到审查页'
