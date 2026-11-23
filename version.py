"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '3.0.1'
RELEASE_DATE = '2026-11-23'
RELEASE_NAME = '3.0.1：BP 前置手序逐手化与可读性修正'
