# -*- coding: utf-8 -*-
"""生成宣传封面：小红书（3:4）、B站（16:9）、抖音（9:16）。

用法：python marketing/make_covers.py
产物：marketing/covers/*.png

设计原则：真实产品截图当主视觉，文案克制，不用夸张配色。
改文案直接改下面 TEXTS 里对应字段，重跑即可。
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "images"
OUT = Path(__file__).resolve().parent / "covers"
OUT.mkdir(parents=True, exist_ok=True)

FONT_DIR = Path(r"C:\Windows\Fonts")
BOLD = FONT_DIR / "HarmonyOS_Sans_SC_Bold.ttf"
REG = FONT_DIR / "HarmonyOS_Sans_SC_Regular.ttf"

INK = (22, 33, 30)
DEEP = (18, 63, 56)
MINT = (127, 211, 182)
MINT_SOFT = (185, 227, 210)
PAPER = (247, 248, 246)
MUTED = (91, 107, 102)
WHITE = (255, 255, 255)

TEXTS = {
    "xhs": {
        "eyebrow": "KPL 赛训 · 本机工具",
        "line1": "训练赛打完，",
        "line2_before": "数据还在",
        "line2_mark": "截图",
        "line2_after": "里",
        "sub": "截图 / 录屏 / 营地链接，进同一条本机链路",
        "chips": ["OCR 出候选值，确认才入库", "每个数字标明来源", "数据不出本机"],
        "strip": "sources",
        "strip_label": "每个数字的来源",
        "strip_items": ["文件解码", "引擎实测", "UI 采样", "估算"],
        "shot": "01-overview.png",
        "card_y": 540,
        "out": "xhs-cover-01.png",
        "footer": "KPL 赛训工具 · v1.3.0",
        "footer_right": "Windows 10 / 11 · 装完就用",
    },
    "xhs2": {
        "eyebrow": "赛训数据 · 方法",
        "line1": "训练赛数据，",
        "line2_before": "先别看",
        "line2_mark": "胜率",
        "line2_after": "",
        "sub": "样本、口径、来源，三件事问清楚再下结论",
        "chips": ["样本数写在页面上", "同一口径才比得了", "插值不装成实测"],
        "strip": "note",
        "strip_label": "先告诉你样本长什么样，再给结论",
        "shot": "04-players.png",
        "card_y": 540,
        "out": "xhs-cover-02.png",
        "footer": "KPL 赛训工具 · v1.3.0",
        "footer_right": "六条硬规则，都写在页面上",
    },
    "xhs3": {
        "eyebrow": "Windows · 免环境",
        "line1": "截图丢进去，",
        "line2_before": "",
        "line2_mark": "复盘",
        "line2_after": "拿出来",
        "sub": "本机识别 · 人工确认 · 时间线与选手趋势",
        "chips": ["不用装 Python", "不要管理员权限", "数据不上云"],
        "strip": "note",
        "strip_label": "个人 / 教学 / 非营利免费 · 商业使用需授权",
        "shot": "03-matches.png",
        "card_y": 540,
        "out": "xhs-cover-03.png",
        "footer": "KPL 赛训工具 · v1.3.0",
        "footer_right": "Windows 10 / 11 · 装完就用",
    },
    "rules": {
        "eyebrow": "数据口径",
        "line1": "六条硬规则",
        "sub": "赛训数据，怎么才敢拿去改 BP",
        "rows": [
            ("候选不写库", "OCR 只产出候选值，确认后才成为记录"),
            ("冲突不合并", "多来源不一致就并列保留，不取平均、不静默覆盖"),
            ("缺失不补零", "缺的字段留空，不按 0 参与任何统计"),
            ("部分不冒充终局", "快照行标 partial，默认不进选手与团队统计"),
            ("变更有审计", "复核人、审核时间、before / after 都留在通道里"),
            ("口径先于图表", "分母、样本量、计算条件写在每个指标下面"),
        ],
        "out": "xhs-card-rules.png",
    },
    "story": {
        "eyebrow": "一场训练赛的复盘会",
        "title": "五个人，五个说法",
        "sub": "20 分钟那波团，0 换 3，赛后没人说得清",
        "rows": [
            ("打野", "我没到场。"),
            ("中单", "我到了，没人跟。"),
            ("射手", "我被切了，没人管。"),
            ("辅助", "我在保上路。"),
        ],
        "reveal": ["回放慢放三遍才看清：辅助 4 分 12 秒", "交了闪现去救上路，那波团他没有闪。"],
        "point": ["这件事数据里有。", "只是没人记下来。"],
        "out": "xhs-card-story.png",
    },
    "tradeoff": {
        "eyebrow": "设计取舍",
        "title": "我砍掉的三件事",
        "sub": "做赛训工具时，我放弃了三个「更好用」的设计",
        "rows": [
            ("自动入库", "识别完直接写库，教练会爽三天，然后某天发现一个错数，从此不信任何统计。所以识别只出候选值，你确认了才入库。"),
            ("缺失补零", "看起来更整齐，实际会把平均值带偏。缺的字段就留空，宁可图表少一个点。"),
            ("云端同步", "训练赛数据是俱乐部的资产，没人愿意把它放到别人的服务器上。所以它只跑在 127.0.0.1。"),
        ],
        "outro": ["代价是它没那么聪明，", "好处是没人会在复盘会上说「这个数好像不对」。"],
        "out": "xhs-card-tradeoffs.png",
    },
    "bili": {
        "eyebrow": "V3 · 本机赛训工作台",
        "line1": "训练赛复盘",
        "line2_before": "不该是",
        "line2_mark": "手抄表格",
        "sub": "截图 / 录屏 OCR · 本机跑 · 每个数字标来源",
        "bullets": [
            "营地拉十人面板，或七页截图走本机 OCR，确认后入库",
            "时间线、经济曲线、掉点，一局一页",
            "数据只写本机，不连云、不用管理员权限",
        ],
        "cta": "下载：GitHub Releases",
        "footer": "kpl-scrim-lab-app · PolyForm NC 1.0.0",
    },
    "douyin": {
        "line1": "训练赛数据",
        "line2": "别再手抄了",
        "sub": "截图进去，曲线出来",
        "bullets": [
            "OCR 出候选值，你确认了才算数",
            "每个数字标明来源，不混口径",
            "全在本机跑，不连云",
        ],
        "footer": "KPL 赛训工具 · v1.3.0",
        "pill": "Windows 10 / 11 · 数据不出本机",
    },
}


def font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def text_w(draw, text, f):
    box = draw.textbbox((0, 0), text, font=f)
    return box[2] - box[0]


def vgrad(size, top, bottom):
    w, h = size
    base = Image.new("RGB", (1, h))
    d = ImageDraw.Draw(base)
    for y in range(h):
        t = y / max(1, h - 1)
        d.point((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return base.resize((w, h))


def glow(size, center, radius, color, alpha=70):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = center
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(radius * 0.55))


def shadow_mask(size, radius, blur, alpha=90):
    w, h = size
    pad = blur * 3
    layer = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle([pad, pad, pad + w, pad + h], radius=radius, fill=(10, 20, 18, alpha))
    return layer.filter(ImageFilter.GaussianBlur(blur)), pad


def screenshot(path, crop_h, target_w, radius):
    """裁出页面顶部区域，做圆角卡。"""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    ch = min(crop_h, h)
    img = img.crop((0, 0, w, ch))
    tw = target_w
    th = int(ch * tw / w)
    img = img.resize((tw, th), Image.LANCZOS)
    mask = Image.new("L", (tw, th), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, tw, th], radius=radius, fill=255)
    card = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    card.paste(img, (0, 0), mask)
    return card


def paste_card(base, card, xy, radius=18, blur=26, alpha=95, border=True):
    sh, pad = shadow_mask(card.size, radius, blur, alpha)
    x, y = xy
    base.alpha_composite(sh, (x - pad, y - pad + int(blur * 0.7)))
    base.alpha_composite(card, (x, y))
    if border:
        d = ImageDraw.Draw(base)
        d.rounded_rectangle(
            [x, y, x + card.size[0], y + card.size[1]],
            radius=radius, outline=(0, 0, 0, 26), width=2,
        )


def pill(draw, xy, text, f, fg, bg, padx=22, pady=11, radius=None):
    x, y = xy
    tw = text_w(draw, text, f)
    h = f.size + pady * 2
    w = tw + padx * 2
    r = radius if radius is not None else h // 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=bg)
    draw.text((x + padx, y + pady - f.size * 0.12), text, font=f, fill=fg)
    return w, h


def mark_line(draw, x, y, before, mark, after, f, mark_bg, mark_fg, ink):
    """一行文字中间带高亮块。"""
    wb = text_w(draw, before, f)
    wm = text_w(draw, mark, f)
    wa = text_w(draw, after, f)
    if before:
        draw.text((x, y), before, font=f, fill=ink)
    mx = x + wb
    pad = f.size * 0.12
    draw.rounded_rectangle(
        [mx - pad * 0.6, y - pad * 0.15, mx + wm + pad * 0.6, y + f.size * 1.16],
        radius=f.size * 0.18, fill=mark_bg,
    )
    draw.text((mx, y), mark, font=f, fill=mark_fg)
    if after:
        draw.text((mx + wm, y), after, font=f, fill=ink)
    return wb + wm + wa


def bullet_line(draw, x, y, text, f, dot=(88, 168, 142), color=(58, 74, 69), gap=34):
    draw.ellipse([x, y + f.size * 0.42, x + 10, y + f.size * 0.42 + 10], fill=dot)
    draw.text((x + gap, y), text, font=f, fill=color)


# ---------------------------------------------------------------- 小红书 3:4
def make_xhs(key="xhs"):
    W, H = 1242, 1656
    t = TEXTS[key]
    base = vgrad((W, H), (238, 245, 241), PAPER).convert("RGBA")
    base.alpha_composite(glow((W, H), (170, 120), 620, (150, 214, 190), 60))
    base.alpha_composite(glow((W, H), (1120, 1500), 520, (222, 232, 226), 55))
    d = ImageDraw.Draw(base)

    M = 84
    pill(d, (M, 92), t["eyebrow"], font(BOLD, 28), DEEP, (223, 240, 233))

    f_h = font(BOLD, 92)
    y = 190
    d.text((M, y), t["line1"], font=f_h, fill=INK)
    mark_line(d, M, y + 120, t["line2_before"], t["line2_mark"], t["line2_after"],
              f_h, MINT_SOFT, DEEP, INK)
    d.text((M, y + 250), t["sub"], font=font(REG, 31), fill=MUTED)

    card = screenshot(SHOTS / t["shot"], 1740, W - M * 2, 20)
    card_y = t.get("card_y", 540)
    paste_card(base, card, (M, card_y), radius=20, blur=30, alpha=90)

    f_chip = font(BOLD, 24)
    cx, cy = M, card_y + card.size[1] + 46
    for i, label in enumerate(t["chips"]):
        tw = text_w(d, label, f_chip)
        cw = tw + 40
        if i:
            cx += 14
        d.rounded_rectangle([cx, cy, cx + cw, cy + 56], radius=28,
                            fill=(255, 255, 255, 235), outline=(0, 0, 0, 22), width=2)
        d.ellipse([cx + 16, cy + 23, cx + 26, cy + 33], fill=(88, 168, 142))
        d.text((cx + 36, cy + 14), label, font=f_chip, fill=(38, 52, 48))
        cx += cw

    by = cy + 92
    if t["strip"] == "sources":
        d.rounded_rectangle([M, by, W - M, by + 104], radius=16,
                            fill=(255, 255, 255, 200), outline=(0, 0, 0, 18), width=2)
        f_lbl = font(BOLD, 22)
        f_src = font(REG, 23)
        d.text((M + 26, by + 40), t["strip_label"], font=f_lbl, fill=MUTED)
        sx = M + 26 + text_w(d, t["strip_label"], f_lbl) + 30
        for i, s in enumerate(t["strip_items"]):
            tw = text_w(d, s, f_src)
            d.rounded_rectangle([sx, by + 30, sx + tw + 28, by + 74], radius=22,
                                fill=(232, 243, 238) if i < 3 else (250, 240, 226))
            d.text((sx + 14, by + 40), s, font=f_src,
                   fill=(30, 74, 64) if i < 3 else (150, 100, 34))
            sx += tw + 38
    else:
        f_note = font(BOLD, 25)
        d.rounded_rectangle([M, by, W - M, by + 98], radius=16,
                            fill=(255, 255, 255, 205), outline=(0, 0, 0, 18), width=2)
        d.rounded_rectangle([M + 22, by + 26, M + 28, by + 72], radius=3, fill=(88, 168, 142))
        d.text((M + 46, by + 33), t["strip_label"], font=f_note, fill=(44, 62, 57))

    d.line([M, H - 110, W - M, H - 110], fill=(0, 0, 0, 24), width=2)
    f_foot = font(REG, 25)
    d.text((M, H - 84), t["footer"], font=f_foot, fill=MUTED)
    d.text((W - M - text_w(d, t["footer_right"], f_foot), H - 84),
           t["footer_right"], font=f_foot, fill=MUTED)

    out = OUT / t["out"]
    base.convert("RGB").save(out, quality=95)
    print("saved", out)


# ------------------------------------------------------------- B站 16:9
def make_bili():
    W, H = 1920, 1080
    t = TEXTS["bili"]
    base = vgrad((W, H), (13, 38, 34), (23, 62, 55)).convert("RGBA")
    base.alpha_composite(glow((W, H), (1520, 200), 720, (60, 190, 155), 44))
    base.alpha_composite(glow((W, H), (200, 1000), 620, (30, 110, 95), 70))
    d = ImageDraw.Draw(base)

    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 48):
        gd.line([x, 0, x, H], fill=(255, 255, 255, 9))
    for y in range(0, H, 48):
        gd.line([0, y, W, y], fill=(255, 255, 255, 9))
    base.alpha_composite(grid)

    M = 96
    f_eye = font(BOLD, 30)
    tw = text_w(d, t["eyebrow"], f_eye)
    blend(base, lambda dd: dd.rounded_rectangle(
        [M, 92, M + tw + 44, 150], radius=29, fill=(255, 255, 255, 20)))
    d.text((M + 22, 103), t["eyebrow"], font=f_eye, fill=MINT)

    f_h = font(BOLD, 104)
    d.text((M, 186), t["line1"], font=f_h, fill=WHITE)
    mark_line(d, M, 186 + 136, t["line2_before"], t["line2_mark"], "",
              f_h, MINT, (8, 40, 34), WHITE)
    d.text((M, 186 + 288), t["sub"], font=font(REG, 34), fill=(178, 203, 195))

    f_b = font(REG, 29)
    by = 186 + 372
    for i, line in enumerate(t["bullets"]):
        bullet_line(d, M, by + i * 58, line, f_b, dot=MINT, color=(214, 231, 225))

    f_cta = font(BOLD, 34)
    cpad = 30
    ctw = text_w(d, t["cta"], f_cta)
    d.rounded_rectangle([M, 782, M + ctw + cpad * 2, 782 + 68], radius=34, fill=MINT)
    d.text((M + cpad, 782 + 13), t["cta"], font=f_cta, fill=(8, 40, 34))

    d.text((M, H - 92), t["footer"], font=font(REG, 26), fill=(132, 164, 156))

    card = screenshot(SHOTS / "01-overview.png", 1560, 900, 22)
    paste_card(base, card, (930, 236), radius=22, blur=42, alpha=125, border=False)
    d.rounded_rectangle([930, 236, 930 + card.size[0], 236 + card.size[1]],
                        radius=22, outline=(255, 255, 255, 58), width=3)

    out = OUT / "bilibili-cover-01.png"
    base.convert("RGB").save(out, quality=95)
    print("saved", out)


# ------------------------------------------------------------ 抖音 9:16
def make_douyin():
    W, H = 1080, 1920
    t = TEXTS["douyin"]
    base = vgrad((W, H), (12, 36, 32), (20, 55, 49)).convert("RGBA")
    base.alpha_composite(glow((W, H), (880, 320), 640, (56, 186, 152), 50))
    d = ImageDraw.Draw(base)

    M = 76
    f_h = font(BOLD, 104)
    d.text((M, 236), t["line1"], font=f_h, fill=WHITE)
    d.text((M, 236 + 132), t["line2"], font=f_h, fill=MINT)
    d.text((M, 236 + 288), t["sub"], font=font(REG, 34), fill=(176, 200, 192))

    card = screenshot(SHOTS / "01-overview.png", 1620, W - M * 2, 20)
    paste_card(base, card, (M, 636), radius=20, blur=38, alpha=115, border=False)
    d.rounded_rectangle([M, 636, M + card.size[0], 636 + card.size[1]],
                        radius=20, outline=(255, 255, 255, 46), width=2)

    f_b = font(REG, 32)
    by = 1282
    for i, line in enumerate(t["bullets"]):
        bullet_line(d, M, by + i * 66, line, f_b, dot=MINT, color=(214, 231, 225))

    d.text((M, 1546), t["footer"], font=font(REG, 28), fill=(132, 164, 156))
    pill(d, (M, 1616), t["pill"], font(BOLD, 28), (8, 40, 34), MINT)

    out = OUT / "douyin-cover-01.png"
    base.convert("RGB").save(out, quality=95)
    print("saved", out)


# ----------------------------------------------------- 小红书图文卡：六条规则
def make_rules_card():
    W, H = 1242, 1656
    t = TEXTS["rules"]
    base = vgrad((W, H), (16, 40, 35), (11, 28, 25)).convert("RGBA")
    base.alpha_composite(glow((W, H), (1100, 170), 620, (56, 186, 152), 42))
    d = ImageDraw.Draw(base)

    M = 84
    f_eye = font(BOLD, 26)
    tw = text_w(d, t["eyebrow"], f_eye)
    blend(base, lambda dd: dd.rounded_rectangle(
        [M, 96, M + tw + 44, 150], radius=27, fill=(255, 255, 255, 22)))
    d.text((M + 22, 108), t["eyebrow"], font=f_eye, fill=MINT)

    d.text((M, 190), t["line1"], font=font(BOLD, 88), fill=WHITE)
    d.text((M, 302), t["sub"], font=font(REG, 31), fill=(150, 178, 170))

    f_no = font(BOLD, 30)
    f_ti = font(BOLD, 40)
    f_de = font(REG, 25)
    y0, step = 408, 190
    for i, (title, desc) in enumerate(t["rows"]):
        y = y0 + i * step
        d.ellipse([M, y + 4, M + 58, y + 62], outline=(127, 211, 182, 130), width=2)
        n = str(i + 1)
        d.text((M + 29 - text_w(d, n, f_no) / 2, y + 14), n, font=f_no, fill=MINT)
        d.text((M + 86, y), title, font=f_ti, fill=WHITE)
        d.text((M + 86, y + 58), desc, font=f_de, fill=(158, 182, 175))
        if i < len(t["rows"]) - 1:
            d.line([M, y + 166, W - M, y + 166], fill=(255, 255, 255, 16), width=1)

    f_foot = font(REG, 25)
    d.text((M, H - 96), "KPL 赛训工具 · v1.3.0", font=f_foot, fill=(120, 148, 140))
    right = "口径先于图表"
    d.text((W - M - text_w(d, right, f_foot), H - 96), right, font=f_foot, fill=(120, 148, 140))

    out = OUT / t["out"]
    base.convert("RGB").save(out, quality=95)
    print("saved", out)


def blend(base, fn):
    """在独立图层上画，再 alpha 合成；直接往 RGBA 画布写带 alpha 的填充会变成实心色块。"""
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    fn(ImageDraw.Draw(layer))
    base.alpha_composite(layer)


def wrap(draw, text, f, max_w):
    """按字符折行（中文没有空格可断）。"""
    lines, cur = [], ""
    for ch in text:
        if text_w(draw, cur + ch, f) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


# --------------------------------------------- 小红书叙事卡：五个说法
def make_story_card():
    W, H = 1242, 1656
    t = TEXTS["story"]
    base = vgrad((W, H), (243, 247, 244), PAPER).convert("RGBA")
    base.alpha_composite(glow((W, H), (1080, 220), 600, (206, 232, 220), 60))
    d = ImageDraw.Draw(base)

    M = 84
    pill(d, (M, 96), t["eyebrow"], font(BOLD, 26), DEEP, (223, 240, 233))
    d.text((M, 190), t["title"], font=font(BOLD, 86), fill=INK)
    d.text((M, 300), t["sub"], font=font(REG, 30), fill=MUTED)

    f_role = font(BOLD, 25)
    f_quote = font(BOLD, 42)
    y0, step = 396, 126
    for i, (role, quote) in enumerate(t["rows"]):
        y = y0 + i * step
        d.rounded_rectangle([M, y, M + 118, y + 48], radius=14, fill=(232, 241, 236))
        d.text((M + 20, y + 9), role, font=f_role, fill=(46, 92, 80))
        d.text((M + 148, y - 4), quote, font=f_quote, fill=INK)

    d.line([M, 936, W - M, 936], fill=(0, 0, 0, 26), width=2)

    f_rv = font(REG, 34)
    for i, line in enumerate(t["reveal"]):
        d.text((M, 976 + i * 52), line, font=f_rv, fill=(58, 74, 69))

    by = 1184
    d.rounded_rectangle([M, by, W - M, by + 168], radius=18,
                        fill=(255, 255, 255, 225), outline=(0, 0, 0, 18), width=2)
    d.rounded_rectangle([M + 26, by + 30, M + 34, by + 138], radius=4, fill=(88, 168, 142))
    f_big = font(BOLD, 40)
    for i, line in enumerate(t["point"]):
        d.text((M + 60, by + 32 + i * 56), line, font=f_big, fill=DEEP)

    f_foot = font(REG, 25)
    d.text((M, H - 92), "KPL 赛训工具 · v1.3.0", font=f_foot, fill=MUTED)
    right = "复盘不该靠记忆"
    d.text((W - M - text_w(d, right, f_foot), H - 92), right, font=f_foot, fill=MUTED)

    out = OUT / t["out"]
    base.convert("RGB").save(out, quality=95)
    print("saved", out)


# ------------------------------------------- 小红书叙事卡：砍掉的三件事
def make_tradeoff_card():
    W, H = 1242, 1656
    t = TEXTS["tradeoff"]
    base = vgrad((W, H), (15, 42, 37), (12, 30, 27)).convert("RGBA")
    base.alpha_composite(glow((W, H), (1080, 240), 620, (56, 186, 152), 40))
    d = ImageDraw.Draw(base)

    M = 84
    f_eye = font(BOLD, 26)
    tw = text_w(d, t["eyebrow"], f_eye)
    d.rounded_rectangle([M, 96, M + tw + 44, 150], radius=27, fill=(255, 255, 255, 22))
    d.text((M + 22, 108), t["eyebrow"], font=f_eye, fill=MINT)

    d.text((M, 190), t["title"], font=font(BOLD, 86), fill=WHITE)
    d.text((M, 300), t["sub"], font=font(REG, 29), fill=(150, 178, 170))

    f_tag = font(BOLD, 22)
    f_name = font(BOLD, 44)
    f_desc = font(REG, 27)
    y0, step = 400, 300
    for i, (name, desc) in enumerate(t["rows"]):
        y = y0 + i * step
        blend(base, lambda dd, gy=y: dd.rounded_rectangle(
            [M, gy, M + 96, gy + 42], radius=12, fill=(255, 255, 255, 20)))
        d.text((M + 18, y + 8), "砍掉", font=f_tag, fill=(240, 160, 120))
        d.text((M, y + 62), name, font=f_name, fill=WHITE)
        for j, line in enumerate(wrap(d, desc, f_desc, W - M * 2)):
            d.text((M, y + 130 + j * 40), line, font=f_desc, fill=(158, 182, 175))
        if i < len(t["rows"]) - 1:
            d.line([M, y + 258, W - M, y + 258], fill=(255, 255, 255, 16), width=1)

    f_end = font(BOLD, 32)
    for j, line in enumerate(t["outro"]):
        d.text((M, 1408 + j * 46), line, font=f_end, fill=MINT)

    f_foot = font(REG, 25)
    d.text((M, H - 92), "KPL 赛训工具 · v1.3.0", font=f_foot, fill=(120, 148, 140))
    right = "不做一键出结论"
    d.text((W - M - text_w(d, right, f_foot), H - 92), right, font=f_foot, fill=(120, 148, 140))

    out = OUT / t["out"]
    base.convert("RGB").save(out, quality=95)
    print("saved", out)


# ============================================================ 功能卡系列
# 采集只是入口，分析才是主体。每张卡：模块名 + 它回答什么问题 + 三个要点 + 来源。
# 截图文件名是历史遗留，标注以这里为准（07-topics 实为 BP 概览，08-depth 实为训练纪录）。
FEATURES = [
    {
        "name": "单局复盘",
        "q": "这一局发生了什么，转折点在哪？",
        "shot": "09-match.png",
        "crop": 1800,
        "points": [
            "先给一句结论，再往下给证据",
            "阶段经济、资源与建筑、逐局金差走势",
            "口径写在卡片底部，不藏在图表里",
        ],
        "tag": "来源：营地面板 + 可选回放",
    },
    {
        "name": "训练纪录",
        "q": "这批局的极值在哪一场，离均值差多少？",
        "shot": "08-depth.png",
        "crop": 1800,
        "points": [
            "最长 / 最短对局，标注与均值的偏离百分比",
            "最大 / 最小终局金差，直接指名第几局对谁",
            "经济最反复、最高分均经济，一屏看完",
        ],
        "tag": "来源：营地面板",
    },
    {
        "name": "跨局分析",
        "q": "换一套阵容，赢率真的会变吗？",
        "shot": "11-cross.png",
        "crop": 1800,
        "points": [
            "一局一块、一块一行，点开任意一局进复盘",
            "按同分路、同口径聚合重算，不跨口径混算",
            "比较只在当前筛选范围内成立，会写明范围",
        ],
        "tag": "来源：营地面板",
    },
    {
        "name": "战队档案",
        "q": "这个对手到底强在哪，弱在哪？",
        "shot": "05-team.png",
        "crop": 1800,
        "points": [
            "对手按 0–100 分排名，经济 / 对抗 / 输出 / 推进拆开",
            "样本不足 3 局只作参考，不判断真实强弱",
            "待命名的对手单独标记，不会被塞进某个战队",
        ],
        "tag": "来源：营地面板 + 人工确认对手归属",
    },
    {
        "name": "名单与状态",
        "q": "本期谁在打，谁有可比样本？",
        "shot": "04-players.png",
        "crop": 1800,
        "points": [
            "本队侧出场按营地昵称去重统计",
            "跨 2 局以上的人数单独列出，1 局的人不算趋势",
            "样本不足直接说，不给「看起来还行」的结论",
        ],
        "tag": "来源：营地面板",
    },
    {
        "name": "英雄榜",
        "q": "池子多深，版本答案是什么？",
        "shot": "06-heroes.png",
        "crop": 1800,
        "points": [
            "英雄池深度按选用集中度折算，不是一个出场数",
            "按胜率分 S / C 档，每档都标样本局数",
            "点进英雄再看它在每个位置上的表现",
        ],
        "tag": "来源：营地选用 + 结算面板",
    },
    {
        "name": "BP 概览",
        "q": "我们的 BP 是不是被对手读透了？",
        "shot": "07-topics.png",
        "crop": 1800,
        "points": [
            "本队禁用、本队选用、对手禁用分别统计",
            "最爱选谁、最常被 ban 谁，直接点名到次数",
            "换对手或换训练日，结论实时重算",
        ],
        "tag": "来源：营地面板 BP（手序需人工补录）",
    },
    {
        "name": "采集与入库",
        "q": "七页截图、一段录屏、一条营地链接，怎么变成数据？",
        "shot": "02-capture.png",
        "crop": 1800,
        "points": [
            "营地扫码后按选手增量拉取十人面板，不经过 OCR",
            "七页结算截图 + 整局录屏走本机 OCR，兜底用",
            "识别结果只是候选值，你确认了才成为记录",
        ],
        "tag": "来源：营地面板 / 截图 OCR",
    },
]

FMAP = {
    "eyebrow": "功能全景",
    "title": "采集只是入口",
    "title2": "分析才是主体",
    "sub": "一套东西，从七页截图走到能改 BP 的结论",
    "groups": [
        ("采集与入库", "营地增量拉取 · 七页截图 OCR · 录屏抽帧 · 表格导入", False),
        ("核对与留痕", "一局一通道 · 冲突并列 · 身份三态 · 审核日志", False),
        ("分析", "单局复盘 · 训练纪录 · 跨局对照 · 战队档案 · 选手状态 · 英雄池 · BP", True),
        ("赛训与交付", "训练计划 · 目标判定 · 周报 · 报告导出 · 增量更新", False),
    ],
    "out": "xhs-series-01.png",
}


def feature_card(f, idx, total, out_name):
    W, H = 1242, 1656
    base = vgrad((W, H), (15, 42, 37), (12, 30, 27)).convert("RGBA")
    base.alpha_composite(glow((W, H), (1090, 190), 600, (56, 186, 152), 40))
    d = ImageDraw.Draw(base)

    M = 84
    # 右侧序号水印
    f_wm = font(BOLD, 190)
    wm = f"{idx:02d}"
    blend(base, lambda dd: dd.text((W - M - text_w(dd, wm, f_wm), 96), wm,
                                  font=f_wm, fill=(255, 255, 255, 13)))

    d.text((M, 104), f"{idx:02d} / {total:02d}", font=font(BOLD, 24), fill=(120, 148, 140))
    d.text((M, 150), f["name"], font=font(BOLD, 68), fill=WHITE)
    d.text((M, 250), f["q"], font=font(REG, 29), fill=MINT)
    d.rounded_rectangle([M, 306, M + 88, 310], radius=2, fill=MINT)

    card = screenshot(SHOTS / f["shot"], f["crop"], W - M * 2, 18)
    cy = 340
    paste_card(base, card, (M, cy), radius=18, blur=36, alpha=120, border=False)
    d.rounded_rectangle([M, cy, M + card.size[0], cy + card.size[1]],
                        radius=18, outline=(255, 255, 255, 46), width=2)

    py = cy + card.size[1] + 64
    f_p = font(REG, 33)
    for i, p in enumerate(f["points"]):
        bullet_line(d, M, py + i * 78, p, f_p, dot=MINT, color=(216, 233, 227))

    ty = py + len(f["points"]) * 78 + 34
    f_tag = font(REG, 24)
    tw = text_w(d, f["tag"], f_tag)
    blend(base, lambda dd: dd.rounded_rectangle(
        [M, ty, M + tw + 44, ty + 50], radius=25,
        fill=(255, 255, 255, 16), outline=(255, 255, 255, 36), width=1))
    d.text((M + 22, ty + 12), f["tag"], font=f_tag, fill=(166, 194, 186))

    f_foot = font(REG, 24)
    d.text((M, H - 92), "KPL 赛训工具 · v1.3.0", font=f_foot, fill=(118, 146, 138))
    right = "数据不出本机"
    d.text((W - M - text_w(d, right, f_foot), H - 92), right, font=f_foot, fill=(118, 146, 138))

    base.convert("RGB").save(OUT / out_name, quality=95)
    print("saved", OUT / out_name)


def make_feature_series():
    total = len(FEATURES) + 2  # 封面 + 8 个模块 + 结尾
    for i, f in enumerate(FEATURES, start=2):
        feature_card(f, i, total, f"xhs-series-{i:02d}.png")


def make_feature_map():
    W, H = 1242, 1656
    t = FMAP
    base = vgrad((W, H), (15, 42, 37), (11, 28, 25)).convert("RGBA")
    base.alpha_composite(glow((W, H), (1050, 260), 660, (56, 186, 152), 44))
    d = ImageDraw.Draw(base)

    M = 84
    pill(d, (M, 100), t["eyebrow"], font(BOLD, 26), MINT, (8, 40, 34))
    d.text((M, 196), t["title"], font=font(BOLD, 86), fill=WHITE)
    d.text((M, 306), t["title2"], font=font(BOLD, 86), fill=MINT)
    d.text((M, 442), t["sub"], font=font(REG, 29), fill=(158, 184, 176))

    y = 536
    for name, items, hot in t["groups"]:
        block_h = 198
        if hot:
            blend(base, lambda dd, gy=y, gh=block_h: dd.rounded_rectangle(
                [M - 18, gy - 18, W - M + 18, gy + gh - 40], radius=18,
                fill=(127, 211, 182, 30), outline=(127, 211, 182, 95), width=2))
        d.text((M, y), name, font=font(BOLD, 40), fill=(MINT if hot else WHITE))
        if hot:
            cw = text_w(d, "主体", font(BOLD, 22))
            d.rounded_rectangle([M + text_w(d, name, font(BOLD, 40)) + 18, y + 8,
                                 M + text_w(d, name, font(BOLD, 40)) + 18 + cw + 28, y + 44],
                                radius=18, fill=MINT)
            d.text((M + text_w(d, name, font(BOLD, 40)) + 32, y + 14), "主体",
                   font=font(BOLD, 22), fill=(8, 40, 34))
        f_items = font(REG, 27)
        for j, line in enumerate(wrap(d, items, f_items, W - M * 2 - 20)):
            d.text((M, y + 62 + j * 42), line, font=f_items,
                   fill=(200, 226, 217) if hot else (150, 176, 168))
        if name != t["groups"][-1][0] and not hot:
            d.line([M, y + block_h - 44, W - M, y + block_h - 44],
                   fill=(60, 92, 82), width=1)
        y += block_h

    f_end = font(BOLD, 30)
    d.text((M, 1368), "26 个页面，采集只占 4 个", font=f_end, fill=MINT)
    f_note = font(REG, 25)
    d.text((M, 1420), "剩下的是对局、战队、选手、英雄、BP、赛训——都是只读分析。", font=f_note,
           fill=(150, 176, 168))

    f_foot = font(REG, 24)
    d.text((M, H - 92), "KPL 赛训工具 · v1.3.0", font=f_foot, fill=(118, 146, 138))
    right = "Windows 10 / 11"
    d.text((W - M - text_w(d, right, f_foot), H - 92), right, font=f_foot, fill=(118, 146, 138))

    base.convert("RGB").save(OUT / t["out"], quality=95)
    print("saved", OUT / t["out"])


def make_feature_outro():
    W, H = 1242, 1656
    base = vgrad((W, H), (15, 42, 37), (11, 28, 25)).convert("RGBA")
    base.alpha_composite(glow((W, H), (1060, 300), 640, (56, 186, 152), 44))
    d = ImageDraw.Draw(base)

    M = 84
    pill(d, (M, 100), "一句话总结", font(BOLD, 26), MINT, (8, 40, 34))
    d.text((M, 196), "它替你省掉三件事", font=font(BOLD, 84), fill=WHITE)
    d.text((M, 318), "七页截图进得去，一条结论出得来", font=font(REG, 29), fill=(158, 184, 176))

    rows = [
        ("手抄那 50 个数",
         "七页截图丢进去，本机 OCR 读出候选值，你确认一下就成了记录。"),
        ("核对哪份数据才对",
         "每个数字标着来源：文件解码、引擎实测、UI 采样、估算。冲突并列摆出来，不取平均。"),
        ("把训练赛数据传出去",
         "只跑在 127.0.0.1。整个 data 目录拷走，就是一次完整备份。"),
    ]
    f_h = font(BOLD, 40)
    f_b = font(REG, 26)
    y = 432
    for i, (title, body) in enumerate(rows):
        d.ellipse([M, y + 14, M + 12, y + 26], fill=MINT)
        d.text((M + 34, y), title, font=f_h, fill=WHITE)
        for j, line in enumerate(wrap(d, body, f_b, W - M * 2 - 40)):
            d.text((M + 34, y + 58 + j * 40), line, font=f_b, fill=(160, 186, 178))
        y += 200
        if i < len(rows) - 1:
            d.line([M + 34, y - 40, W - M, y - 40], fill=(60, 92, 82), width=1)

    d.line([M, 1064, W - M, 1064], fill=(60, 92, 82), width=1)
    d.text((M, 1100), "采集是入口，分析才是主体。", font=font(BOLD, 44), fill=MINT)
    d.text((M, 1166), "26 个页面，剩下全是给你复盘用的。", font=font(REG, 28), fill=(196, 220, 212))

    f_s = font(REG, 26)
    d.text((M, 1288), "Windows 10 / 11 · 装完双击就能用 · 不用装 Python", font=f_s, fill=(196, 220, 212))
    d.text((M, 1336), "个人 / 教学 / 非营利免费 · 商业使用需单独授权", font=f_s, fill=(150, 176, 168))

    f_foot = font(REG, 24)
    d.text((M, H - 92), "KPL 赛训工具 · v1.3.0", font=f_foot, fill=(118, 146, 138))
    right = "装法在主页"
    d.text((W - M - text_w(d, right, f_foot), H - 92), right, font=f_foot, fill=MINT)

    out = OUT / "xhs-series-10.png"
    base.convert("RGB").save(out, quality=95)
    print("saved", out)


if __name__ == "__main__":
    make_xhs("xhs")
    make_xhs("xhs2")
    make_xhs("xhs3")
    make_rules_card()
    make_story_card()
    make_tradeoff_card()
    make_feature_map()
    make_feature_series()
    make_feature_outro()
    make_bili()
    make_douyin()
