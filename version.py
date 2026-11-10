"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '1.5.30'
RELEASE_DATE = '2026-11-10'
RELEASE_NAME = 'BP 命中：大盘对位与 KPL 赛事命中'
