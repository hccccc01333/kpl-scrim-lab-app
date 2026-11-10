"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '1.5.31'
RELEASE_DATE = '2026-11-10'
RELEASE_NAME = '身份主数据统一与 BP 口径补全'
