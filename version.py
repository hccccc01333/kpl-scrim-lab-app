"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '1.0.0'
RELEASE_DATE = '2026-11-05'
RELEASE_NAME = '首个公开版'
