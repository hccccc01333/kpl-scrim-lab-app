# -*- coding: utf-8 -*-
"""定位 ffmpeg / ffprobe。

优先用应用内一键安装的那一份（``tools/ffmpeg/bin``），找不到再退回系统 PATH。
这样用户不需要改环境变量，卸载重装也不会把 PATH 弄脏。
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCAL_ROOT = ROOT / 'tools' / 'ffmpeg'
LOCAL_BIN = LOCAL_ROOT / 'bin'

_SEARCH_PATHS = (LOCAL_BIN, LOCAL_ROOT)


def local_exe(name: str) -> Path | None:
    """应用内安装的 ffmpeg / ffprobe（没有就返回 None）。"""
    for folder in _SEARCH_PATHS:
        try:
            candidate = folder / f'{name}.exe'
        except OSError:
            continue
        if candidate.is_file():
            return candidate
    return None


def exe(name: str) -> str:
    """优先应用内副本，其次 PATH，最后退回裸命令名（让调用方拿到 FileNotFoundError）。"""
    found = local_exe(name)
    if found is not None:
        return str(found)
    return shutil.which(name) or name


def ffmpeg() -> str:
    return exe('ffmpeg')


def ffprobe() -> str:
    return exe('ffprobe')


def available() -> bool:
    return local_exe('ffmpeg') is not None or shutil.which('ffmpeg') is not None


def probe_available() -> bool:
    return local_exe('ffprobe') is not None or shutil.which('ffprobe') is not None


def source() -> str:
    """给前端看的来源说明：bundled / path / missing。"""
    if local_exe('ffmpeg') is not None:
        return 'bundled'
    if shutil.which('ffmpeg'):
        return 'path'
    return 'missing'
