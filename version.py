"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '1.6.7'
RELEASE_DATE = '2026-11-13'
RELEASE_NAME = '分析师工作首页：每块信息直接点进对应业务页'
