"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '3.5.1'
RELEASE_DATE = '2026-11-26'
RELEASE_NAME = '3.5.1：赛事只填起始日时分析不再漏掉后续对局'
