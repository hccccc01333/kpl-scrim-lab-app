"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '3.5.6'
RELEASE_DATE = '2026-11-27'
RELEASE_NAME = '3.5.6：数据口径与缓存纠错'
