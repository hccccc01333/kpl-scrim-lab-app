"""Single source of truth for the local data root.

Everything the app writes at runtime — SQLite, match bundles, camp panels,
recordings, OCR caches, update staging — lives under one directory.  By default
that is ``<project>/data``.  Setting ``KPL_DATA_DIR`` points an instance at a
different directory, which is what demo/screenshot instances and tests use so
they never touch a real coach's data.

The variable is read at import time: set it before starting the process.

    set KPL_DATA_DIR=D:\\tmp\\kpl-demo
    python server.py
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_NAME = 'KPL_DATA_DIR'


def data_root(root: Path | str | None = None) -> Path:
    """Return the data root: ``KPL_DATA_DIR`` when set, else ``<root>/data``.

    ``root`` lets callers that operate on another installation (updater,
    update client) keep their semantics while still honouring the override.
    """
    override = (os.environ.get(ENV_NAME) or '').strip()
    if override:
        return Path(override).expanduser().resolve()
    base = Path(root) if root is not None else ROOT
    return base.resolve() / 'data'


DATA_DIR = data_root()


def data_path(*parts: str) -> Path:
    """``data_path('camp_details', '123.json')`` → ``<data>/camp_details/123.json``."""
    return DATA_DIR.joinpath(*parts)
