"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '1.6.2'
RELEASE_DATE = '2026-11-11'
RELEASE_NAME = '截图 / 录屏新录入：营地一个月窗口外的老局也能建档'
