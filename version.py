"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '2.0.2'
RELEASE_DATE = '2026-11-18'
RELEASE_NAME = '2.0.2：BP 页空库空态 + 首页文案修正'
