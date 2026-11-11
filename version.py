"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '1.6.4'
RELEASE_DATE = '2026-11-11'
RELEASE_NAME = '移除匿名统计：不再上报，只保留采集与自动更新'
