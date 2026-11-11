"""Mimo refinement for replay recordings.

Per-frame HUD numbers stay on the fast OCR engine: at 1 fps a full game has
dozens of frames, and the local 0.8B VLM is too slow to replace that loop on a
CPU-only workstation.  Mimo is used where it changes the outcome: the loading
screen's five player cards per side and the scoreboard's printed names.  The
fast report remains the source of timeline and counters.
"""
import os
import re

import mimo_ocr
import video_ocr
from vision import catalog

VERSION = 'mimo-video-v1'
LOADING_CROPS = {
    'blue': (40, 248, 1560, 348),
    'red': (40, 744, 1560, 846),
}
LOADING_CROPS_20X9 = {
    'blue': (250, 140, 1250, 310),
    'red': (250, 550, 1250, 720),
}
SCOREBOARD_CROPS = {
    'blue': (160, 190, 500, 820),
    'red': (920, 190, 1260, 820),
}
TEAM_PANEL_CROPS = {
    'blue': (360, 680, 620, 900),
    'red': (980, 680, 1220, 900),
}
TEAM_PANEL_CROPS_20X9 = {
    'blue': (470, 555, 640, 720),
    'red': (980, 555, 1150, 720),
}


def refine_report(report, evidence_dir, on_stage=None, force=False):
    """Add Mimo-read lineups to a video OCR report; never replaces the timeline."""
    if not evidence_dir:
        return _skip(report, '没有保存证据帧，跳过 Mimo 精读。')
    loading_path = os.path.join(evidence_dir, '02-loading.png')
    scoreboard_path = os.path.join(evidence_dir, '04-scoreboard.png')
    if not os.path.isfile(loading_path):
        return _skip(report, '录屏中没有加载页证据帧，跳过 Mimo 阵容精读。')
    calls, warnings = 0, []
    started = None
    try:
        from PIL import Image
        import time
        started = time.time()
        entries = catalog()['entries']
        hero_names = {entry['name'] for entry in entries if entry['kind'] == 'hero'}
        long_screen = report.get('layout') == 'replay-hud-20x9-v1'
        reference = (1600, 720) if long_screen else (1600, 900)
        loading_crops = LOADING_CROPS_20X9 if long_screen else LOADING_CROPS
        team_crops = TEAM_PANEL_CROPS_20X9 if long_screen else TEAM_PANEL_CROPS
        refined = {}
        with Image.open(loading_path) as image:
            image = image.convert('RGB')
            width, height = image.size
            for camp, box in loading_crops.items():
                if on_stage:
                    on_stage(f'Mimo 读取加载页{"蓝" if camp == "blue" else "红"}方阵容…')
                crop = image.crop(_scale_box(box, width, height, reference))
                response = mimo_ocr.get_engine().read(
                    crop, _loading_prompt(camp), max_new_tokens=160,
                    cache=not force, cache_tag=f'{VERSION}:loading:{camp}')
                calls += 1
                rows = _parse_rows(response.get('text') or '', 2)
                if len(rows) != 5:
                    warnings.append(f'Mimo 加载页{"蓝" if camp == "blue" else "红"}方返回 '
                                    f'{len(rows)} 行（应为 5 行）。')
                refined[camp] = rows
                report.setdefault('mimo', {}).setdefault('loadingRaw', {})[camp] = \
                    (response.get('text') or '')[:2000]
                _merge_loading(report, camp, rows, hero_names, warnings)
        if os.path.isfile(scoreboard_path):
            with Image.open(scoreboard_path) as image:
                image = image.convert('RGB')
                width, height = image.size
                scoreboard = {}
                for camp, box in SCOREBOARD_CROPS.items():
                    if on_stage:
                        on_stage(f'Mimo 读取记分板{"蓝" if camp == "blue" else "红"}方名字…')
                    crop = image.crop(_scale_box(box, width, height, reference))
                    response = mimo_ocr.get_engine().read(
                        crop, _scoreboard_prompt(camp), max_new_tokens=180,
                        cache=not force, cache_tag=f'{VERSION}:scoreboard:{camp}')
                    calls += 1
                    scoreboard[camp] = _parse_rows(response.get('text') or '', 3)
            report.setdefault('mimo', {})['scoreboard'] = scoreboard
        panel_frames = (report.get('teamPanel') or {}).get('frames') or []
        if not panel_frames:
            single = os.path.join(evidence_dir, '06-team-panel.png')
            if os.path.isfile(single):
                panel_frames = [{'name': '06-team-panel.png', 'videoTime': None, 'gameTime': None}]
        if len(panel_frames) > 4:
            panel_frames = [panel_frames[0], panel_frames[len(panel_frames) // 3],
                            panel_frames[2 * len(panel_frames) // 3], panel_frames[-1]]
        team_readings = []
        for frame_info in panel_frames:
            path = os.path.join(evidence_dir, frame_info.get('name') or '')
            if not os.path.isfile(path):
                continue
            try:
                with Image.open(path) as image:
                    image = image.convert('RGB')
                    width, height = image.size
                    reading = {'videoTime': frame_info.get('videoTime'),
                               'gameTime': frame_info.get('gameTime')}
                    for camp, box in team_crops.items():
                        if on_stage:
                            on_stage(f'Mimo 读取团队面板{"蓝" if camp == "blue" else "红"}方…')
                        crop = image.crop(_scale_box(box, width, height, reference))
                        crop = crop.resize((crop.width * 3, crop.height * 3),
                                           Image.Resampling.LANCZOS)
                        response = mimo_ocr.get_engine().read(
                            crop, _team_panel_prompt(camp), max_new_tokens=120,
                            cache=not force,
                            cache_tag=f'{VERSION}:panel:{camp}:{frame_info.get("name")}')
                        calls += 1
                        rows = _parse_team_panel(response.get('text') or '')
                        if len(rows) == 5:
                            reading[camp] = rows
                        else:
                            reading[camp] = []
                            warnings.append(f'Mimo 团队面板{"蓝" if camp == "blue" else "红"}方'
                                            f'读出 {len(rows)} 行（应为 5 行），本样本不采用。')
                    reading['complete'] = bool(reading.get('blue')) and bool(reading.get('red'))
                    if reading.get('blue') or reading.get('red'):
                        team_readings.append(reading)
            except OSError:
                continue
        if team_readings and not any(item.get('complete') for item in team_readings):
            warnings.append('Mimo 团队面板没有读全双方 5 行的样本；逐人 KDA/金币请以同局赛后截图为准。')
        report.setdefault('mimo', {}).update({
            'engine': mimo_ocr.ENGINE,
            'version': VERSION,
            'available': True,
            'layout': report.get('layout'),
            'calls': calls,
            'elapsedMs': int((time.time() - started) * 1000),
            'loading': refined,
            'teamPanel': team_readings,
            'warnings': warnings,
        })
        report['warnings'] = _dedupe(list(report.get('warnings') or []) + warnings)
        return report
    except mimo_ocr.MimoUnavailable as error:
        return _skip(report, f'Mimo 精读不可用：{error}')
    except Exception as error:  # noqa: BLE001 - a refinement failure must not destroy the fast report
        return _skip(report, f'Mimo 精读失败（{type(error).__name__}: {error}），保留快速识别结果。')


def _skip(report, message):
    report.setdefault('mimo', {})['available'] = False
    report['mimo']['error'] = message
    report['warnings'] = _dedupe(list(report.get('warnings') or []) + [message])
    return report


def _scale_box(box, width, height, reference=(1600, 900)):
    sx, sy = width / reference[0], height / reference[1]
    return (max(0, round(box[0] * sx)), max(0, round(box[1] * sy)),
            min(width, round(box[2] * sx)), min(height, round(box[3] * sy)))


def _loading_prompt(camp):
    side = 'blue' if camp == 'blue' else 'red'
    return (
        'This is the loading screen of Honor of Kings. Read the five player cards '
        f'in this {side}-side row from left to right. Return exactly five lines, '
        'one per card, in this format: hero|nickname\n'
        'Copy the printed hero name and nickname exactly. Use - when unreadable. '
        'Do not infer a hero from the portrait. No header, numbering or commentary.'
    )


def _team_panel_prompt(camp):
    side = 'blue' if camp == 'blue' else 'red'
    return (
        'This is the Honor of Kings replay team panel. Read the five rows of the '
        f'{side}-side player list from top to bottom. Each row shows KDA '
        '(kills/deaths/assists) and cumulative gold. Return exactly five lines:\n'
        'kills/deaths/assists|gold\n'
        'Use - when a value is unreadable. No header, numbering or commentary.'
    )


def _parse_team_panel(text):
    """Parse KDA|gold or gold|KDA line order; the right panel prints gold first."""
    lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
    rows = []
    for line in lines:
        kda_first = re.search(
            r'(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})[^\d]{0,10}(\d{1,6})', line)
        gold_first = re.search(
            r'(\d{1,6})[^\d]{0,10}(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})', line)
        if kda_first:
            rows.append({'kda': [int(kda_first.group(index)) for index in (1, 2, 3)],
                         'gold': int(kda_first.group(4))})
        elif gold_first:
            rows.append({'kda': [int(gold_first.group(index)) for index in (2, 3, 4)],
                         'gold': int(gold_first.group(1))})
    if not rows:
        matches = re.findall(
            r'(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})[^\d]{0,8}(\d{1,6})',
            ' '.join(lines))
        rows = [{'kda': [int(item[0]), int(item[1]), int(item[2])], 'gold': int(item[3])}
                for item in matches]
    return rows[:5]


def _scoreboard_prompt(camp):
    side = 'blue' if camp == 'blue' else 'red'
    return (
        'This is the Honor of Kings scoreboard. Read the five rows of the '
        f'{side}-side name column from top to bottom. Return exactly five lines: '
        'row|hero|nickname\n'
        'row is 0-4 top-to-bottom. Copy printed text; use - when unreadable. '
        'Do not infer identity from position or gold. No header or commentary.'
    )


def _parse_rows(text, width):
    rows = []
    for raw in str(text or '').splitlines():
        line = raw.strip().strip('`').strip()
        if not line:
            continue
        line = re.sub(r'^\s*(?:[-*•]|\d{1,2}[.)、])\s*', '', line)
        parts = [part.strip() for part in re.split(r'\s*[|｜]\s*', line)]
        if len(parts) == 1 and '\t' in line:
            parts = [part.strip() for part in line.split('\t')]
        lowered = [part.lower() for part in parts]
        if width == 3 and lowered[:2] in (['row', 'hero'], ['序号', '英雄']):
            continue
        if width == 2 and lowered[:2] == ['hero', 'nickname']:
            continue
        if width == 2 and lowered[:2] == ['英雄', '昵称']:
            continue
        if width == 3:
            # Accept an optional leading row number.
            if parts and re.fullmatch(r'\d', parts[0]):
                parts = parts[1:]
            if len(parts) >= 3:
                parts = parts[:3]
            elif len(parts) == 2:
                parts = ['-'] + parts
            else:
                continue
            rows.append({'row': len(rows), 'hero': _clean(parts[1]),
                         'nickname': _clean(parts[2])})
        else:
            if len(parts) > 2:
                parts = parts[:2]
            if len(parts) < 2:
                parts += ['-'] * (2 - len(parts))
            rows.append({'hero': _clean(parts[0]), 'nickname': _clean(parts[1])})
    return rows


def _merge_loading(report, camp, rows, hero_names, warnings):
    lineup = (report.get('lineups') or {}).get(camp) or []
    for index, row in enumerate(rows[:5]):
        if index >= len(lineup):
            continue
        target = lineup[index]
        hero = row.get('hero')
        hero_confirmed = bool(hero and hero in hero_names)
        if hero_confirmed:
            current = target.get('hero')
            if current is None:
                target['hero'] = hero
                target['heroStatus'] = 'exact'
                target['heroSource'] = 'mimo'
            elif current == hero:
                target['heroStatus'] = 'exact'
                target['heroSource'] = 'consensus'
            elif target.get('heroStatus') in ('candidate', 'unknown', None):
                target['heroMimo'] = hero
                warnings.append(f'加载页{"蓝" if camp == "blue" else "红"}方第 {index + 1} 卡 '
                                f'英雄快速识别 {current} / Mimo {hero}')
            elif target.get('heroStatus') != 'manual':
                target['heroMimo'] = hero
                warnings.append(f'加载页{"蓝" if camp == "blue" else "红"}方第 {index + 1} 卡 '
                                f'英雄快速识别 {current} / Mimo {hero}')
        nickname = row.get('nickname')
        # A nickname without a confirmed hero is often a skin/watermark read;
        # do not attach it to a player row by position.
        if hero_confirmed and nickname and nickname != '-':
            current = target.get('nickname')
            if not current:
                target['nickname'] = nickname
                target['nicknameSource'] = 'mimo'
            elif _norm(current) != _norm(nickname):
                target['nicknameMimo'] = nickname
                warnings.append(f'加载页{"蓝" if camp == "blue" else "红"}方第 {index + 1} 卡 '
                                f'昵称快速识别 {current} / Mimo {nickname}')


def _clean(value):
    text = str(value or '').strip().strip('`').strip()
    return text if text and text != '-' else None


def _norm(value):
    return re.sub(r'\s+', '', str(value or '')).lower()


def _dedupe(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
