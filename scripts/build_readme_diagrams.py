#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the visual assets used by README.md.

    python scripts/build_readme_diagrams.py              # 全部重建
    python scripts/build_readme_diagrams.py architecture # 只重建一张

三类产物，都写到 ``docs/images/``，已随仓库入库——读者看 README 不需要任何工具：

1. **结构图**：源码是 ``docs/diagrams/architecture.html``，用 Chromium 截
   ``.stage`` 元素（2 倍像素）。改字改色只改 HTML。
2. **流程图**：源码是 ``docs/diagrams/*.mmd``（Mermaid），用 Chromium 加载
   mermaid 10 渲染后截图，再补圆角与描边。渲染需要联网拉一次 mermaid。
3. **首屏截图**：把 ``website/src/assets/img/v3-hero.webp`` 做成圆角 + 投影的
   透明 PNG，深浅主题下都不突兀。

只有改了源文件才需要重跑。依赖：``pip install -r requirements-dev.txt``，
``python -m playwright install chromium``。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'docs' / 'diagrams'
OUT = ROOT / 'docs' / 'images'
SHOTS = ROOT / 'website' / 'src' / 'assets' / 'img'
MERMAID_CDN = 'https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js'

# HTML 结构图：名字 → (产物名, 截图选择器, 逻辑宽度)
FIGURES = {
    'architecture': ('architecture.png', '.stage', 1100),
}

# Mermaid 流程图：名字 → (源文件, 产物名)
DIAGRAMS = {
    'pipeline': ('pipeline.mmd', 'pipeline.png'),
    'channel-states': ('channel-states.mmd', 'channel-states.png'),
    'capture-sequence': ('capture-sequence.mmd', 'capture-sequence.png'),
}

# 截图成片：名字 → (源图, 产物名, 逻辑宽度)
FRAMES = {
    'hero': (SHOTS / 'v3-hero.webp', 'readme-hero.png', 1500),
}

PAGE = """<!doctype html><html><head><meta charset="utf-8">
<style>html,body{{margin:0;background:#fff}}
#out{{display:inline-block;padding:10px}}
#out svg{{display:block;max-width:none!important}}</style>
<script src="{cdn}"></script>
<script>
mermaid.initialize({{startOnLoad:false,securityLevel:'loose'}});
window.renderOne=function(code,id){{
  return mermaid.render(id,code).then(function(res){{
    var out=document.getElementById('out');
    out.innerHTML=res.svg;
    var el=out.querySelector('svg'), vb=el.viewBox&&el.viewBox.baseVal;
    if(vb&&vb.width&&vb.height){{
      el.setAttribute('width',vb.width); el.setAttribute('height',vb.height);
      el.style.width=vb.width+'px'; el.style.height=vb.height+'px';
    }}
    return true;
  }});
}};
</script></head><body><div id="out"></div></body></html>"""


def round_corners(path: Path, radius: int = 14, border: tuple[int, int, int] = (219, 231, 226)) -> None:
    """给白底图补圆角与 1px 描边，避免在浅色页面里糊成一片。"""
    image = Image.open(path).convert('RGBA')
    w, h = image.size
    scale = 2  # 2 倍渲染，半径按屏像素给
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, w - 1, h - 1], radius=radius * scale, fill=255)
    image.putalpha(mask)
    ImageDraw.Draw(image).rounded_rectangle(
        [1, 1, w - 2, h - 2], radius=radius * scale,
        outline=border + (255,), width=2)
    image.save(path, optimize=True)


def frame_image(source: Path, target: Path, width: int,
                radius: int = 18, pad: int = 34) -> None:
    """圆角 + 细描边 + 投影，输出带透明边距的 PNG。"""
    shot = Image.open(source).convert('RGB')
    shot = shot.resize((width, round(shot.height * width / shot.width)), Image.LANCZOS)
    w, h = shot.size
    canvas = Image.new('RGBA', (w + pad * 2, h + pad * 2), (0, 0, 0, 0))

    shadow = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [pad, pad + 12, pad + w, pad + h + 12], radius=radius, fill=(9, 30, 26, 82))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(16)))

    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    canvas.paste(shot, (pad, pad), mask)

    ImageDraw.Draw(canvas).rounded_rectangle(
        [pad, pad, pad + w - 1, pad + h - 1], radius=radius,
        outline=(9, 30, 26, 54), width=2)
    canvas.save(target, optimize=True)


def report(path: Path) -> None:
    print(f'{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB')


def main(argv: list[str]) -> int:
    names = argv[1:]
    known = {*FIGURES, *DIAGRAMS, *FRAMES}
    unknown = [n for n in names if n not in known]
    if unknown:
        print(f'未知项：{", ".join(unknown)}（可选：{", ".join(sorted(known))}）')
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    picked = names or sorted(known)

    with sync_playwright() as p:
        browser = p.chromium.launch()

        for name in [n for n in picked if n in FIGURES]:
            target_name, selector, width = FIGURES[name]
            source = SRC / f'{name}.html'
            if not source.is_file():
                print(f'跳过 {name}：{source} 不存在')
                continue
            page = browser.new_page(viewport={'width': width + 80, 'height': 1200},
                                    device_scale_factor=2)
            page.goto(source.as_uri(), wait_until='load')
            page.wait_for_timeout(250)
            path = OUT / target_name
            page.locator(selector).screenshot(path=str(path))
            page.close()
            report(path)

        pending = [n for n in picked if n in DIAGRAMS]
        if pending:
            page = browser.new_page(viewport={'width': 2000, 'height': 1600},
                                    device_scale_factor=2)
            holder = ROOT / '.cache' / 'mermaid-render.html'
            holder.parent.mkdir(parents=True, exist_ok=True)
            holder.write_text(PAGE.format(cdn=MERMAID_CDN), encoding='utf-8')
            page.goto(holder.as_uri(), wait_until='load')
            page.wait_for_function('window.renderOne !== undefined', timeout=30000)
            for index, name in enumerate(pending):
                source_name, target_name = DIAGRAMS[name]
                source = SRC / source_name
                if not source.is_file():
                    print(f'跳过 {name}：{source} 不存在')
                    continue
                path = OUT / target_name
                page.evaluate('([c, id]) => window.renderOne(c, id)',
                              [source.read_text(encoding='utf-8'), f'fig{index}'])
                page.wait_for_timeout(150)
                page.locator('#out').screenshot(path=str(path))
                round_corners(path)
                report(path)
            page.close()

        browser.close()

    for name in [n for n in picked if n in FRAMES]:
        source, target_name, width = FRAMES[name]
        if not source.is_file():
            print(f'跳过 {name}：{source} 不存在')
            continue
        path = OUT / target_name
        frame_image(source, path, width)
        report(path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
