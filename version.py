"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '2.0.1'
RELEASE_DATE = '2026-11-18'
RELEASE_NAME = '2.0.1：BP 三模式 + 界面细节修正'
