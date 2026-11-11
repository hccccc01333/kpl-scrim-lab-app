"""Single source of truth for the application version.

The version is exposed through `/api/health` and rendered in the page
footer. Bump `VERSION` when releasing; `RELEASE_NOTES` feeds CHANGELOG.md.
"""
from __future__ import annotations

VERSION = '1.6.0'
RELEASE_DATE = '2026-11-11'
RELEASE_NAME = '开源协议切换（AGPL-3.0 + 商业授权）'
