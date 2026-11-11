"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '1.6.3'
RELEASE_DATE = '2026-11-11'
RELEASE_NAME = '工作台内自动更新：打开就提示，一键升级到最新版'
