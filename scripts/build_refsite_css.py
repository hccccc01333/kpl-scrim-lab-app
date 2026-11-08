"""把参考项目的 CSS 原样搬过来，只做一件事：加 .refsite 作用域。

不重写任何属性值、不改字号间距，保证组件和原站一致。
处理：
  :root                      -> .refsite
  html.v55.light-site / html.v55 / html.dark-site / html.light-site -> .refsite
  body                       -> .refsite
  其它选择器                  -> .refsite <selector>
@keyframes / @font-face 原样保留；@media / @supports 递归处理。
"""
import re
import sys
from pathlib import Path

SRC = Path(r'D:\AI数据分析\项目作品集\02-KPL实时胜率预测系统\kpl_insight\frontend\assets')
OUT = Path(r'D:\Projects\KPL训练赛项目\web\vendor\refsite.css')
FILES = ['style.css', 'pages.css', 'v55.css', 'light.css']
SCOPE = '.refsite'


def strip_comments(css: str) -> str:
    return re.sub(r'/\*.*?\*/', '', css, flags=re.S)


def transform_selector(sel: str) -> str:
    sel = sel.strip()
    if not sel:
        return sel
    if sel.startswith('@'):
        return sel
    original = sel
    for token in ('html.v55.light-site', 'html.v55', 'html.dark-site', 'html.light-site', 'html'):
        if token in sel:
            sel = sel.replace(token, SCOPE)
    if sel.strip() == 'body' or sel.strip().startswith('body'):
        sel = sel.replace('body', SCOPE, 1)
    elif sel.strip() in (':root', 'html', '*'):
        sel = SCOPE if sel.strip() != '*' else f'{SCOPE} *'
    elif not sel.strip().startswith(SCOPE):
        sel = f'{SCOPE} {sel.strip()}'
    return sel


def split_rules(css: str):
    """按顶层块切分，返回 [(prelude, body), ...]；没有 body 的尾部原样返回。"""
    blocks, buf, depth, i = [], '', 0, 0
    while i < len(css):
        ch = css[i]
        if ch == '{':
            depth += 1
            if depth == 1:
                buf += ch
                i += 1
                start = i
                level = 1
                while i < len(css) and level:
                    if css[i] == '{':
                        level += 1
                    elif css[i] == '}':
                        level -= 1
                    i += 1
                body = css[start:i - 1]
                blocks.append((buf[:-1], body))
                buf = ''
                depth = 0
                continue
        buf += ch
        i += 1
    tail = buf.strip()
    return blocks, tail


def transform(css: str) -> str:
    out = []
    blocks, tail = split_rules(css)
    for prelude, body in blocks:
        prelude = prelude.strip()
        if prelude.startswith('@media') or prelude.startswith('@supports'):
            out.append(f'{prelude}{{{transform(body)}}}')
        elif prelude.startswith('@'):
            out.append(f'{prelude}{{{body}}}')
        else:
            sels = ','.join(transform_selector(part) for part in prelude.split(','))
            out.append(f'{sels}{{{body}}}')
    if tail:
        out.append(tail)
    return '\n'.join(out)


def main():
    chunks = []
    for name in FILES:
        css = strip_comments((SRC / name).read_text(encoding='utf-8'))
        chunks.append(f'/* ==== {name} ==== */\n' + transform(css))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    header = ('/* 由 scripts/build_refsite_css.py 生成：参考项目 CSS 原样搬入，'
              '仅加 .refsite 作用域。请勿手改。 */\n')
    OUT.write_text(header + '\n'.join(chunks), encoding='utf-8')
    print(f'wrote {OUT} ({len(OUT.read_text(encoding="utf-8"))} chars)')


if __name__ == '__main__':
    main()
