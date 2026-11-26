"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '3.5.0'
RELEASE_DATE = '2026-11-26'
RELEASE_NAME = '3.5.0：修复营地采集对局在赛事分析中缺失'
