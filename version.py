"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '1.6.6'
RELEASE_DATE = '2026-11-12'
RELEASE_NAME = '修复营地同步回放为空、升级后仍是旧界面'
