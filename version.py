"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '3.4.0'
RELEASE_DATE = '2026-11-26'
RELEASE_NAME = '3.4.0：保留数据、其余重装的干净升级'
