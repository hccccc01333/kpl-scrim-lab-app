"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '3.0.0'
RELEASE_DATE = '2026-11-23'
RELEASE_NAME = '3.0.0：全新视觉体系 + 复盘细节打磨 + 跨局大场收口'
