"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '1.5.29'
RELEASE_DATE = '2026-11-10'
RELEASE_NAME = '跨局分析与选手位置按赛训组口径重排'
