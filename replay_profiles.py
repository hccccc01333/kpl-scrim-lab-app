"""Versioned replay layout profiles.

The `.abc` container layout is a research profile, not an official contract.
Every offset/stride lives here (or in ``resources/replay_profiles.json``) so a
new client build can be supported by adding a profile entry instead of editing
parser code.

Matching is by client/resource version prefix.  ``builds`` is recorded for
traceability and for profiles that opt into strict build matching with
``requireBuilds: true``.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "resources" / "replay_profiles.json"

# Fallback profile for the 2026-11 12.1.1.x samples.  Kept in code only as a
# bootstrap so the app still starts when the config file is missing.
BUILTIN_PROFILES = [
    {
        "id": "observed-12.1.1.x-v3",
        "label": "2026-11 12.1.1.x 观测档案",
        "versionPrefixes": ["12.1.1."],
        "builds": ["4989537", "5230306", "5247758"],
        "requireBuilds": False,
        "layout": {
            "blockStride": 1517,
            "heroOffsets": [771, 1415, 1445],
            "tlvStart": 17652,
            "secondDeflateStart": 139,
            "rosterScanLimit": 131072,
            "rosterHeroOffset": 72,
            "rosterBotBlockBytes": 2782,
            "rosterFooterTail": "000000000004b000000000",
            "rosterHumanPostBytes": 30,
            "rosterBotPostBytes": 5,
            "rosterMaxHumanBlockBytes": 8192,
            "frameScanLimit": 393216,
        },
    }
]

LAYOUT_TYPES = {
    "blockStride": int,
    "heroOffsets": tuple,
    "tlvStart": int,
    "secondDeflateStart": int,
    "rosterScanLimit": int,
    "rosterHeroOffset": int,
    "rosterBotBlockBytes": int,
    "rosterFooterTail": bytes,
    "rosterHumanPostBytes": int,
    "rosterBotPostBytes": int,
    "rosterMaxHumanBlockBytes": int,
    "frameScanLimit": int,
}


def _coerce_layout(layout: dict) -> dict:
    result = {}
    for key, value in layout.items():
        expected = LAYOUT_TYPES.get(key)
        if expected is bytes:
            result[key] = value if isinstance(value, (bytes, bytearray)) else bytes.fromhex(str(value))
        elif expected is tuple:
            result[key] = value if isinstance(value, tuple) else tuple(int(item) for item in value)
        elif expected is int:
            result[key] = int(value)
        else:
            result[key] = value
    return result


def load_registry(path: Path | None = None) -> dict:
    """Load the profile registry, with config entries overriding built-ins."""
    config_path = Path(path) if path is not None else CONFIG_PATH
    profiles = [dict(item) for item in BUILTIN_PROFILES]
    source = "builtin"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        payload = None
    if isinstance(payload, dict) and isinstance(payload.get("profiles"), list):
        source = str(config_path)
        by_id = {item["id"]: item for item in profiles if item.get("id")}
        for item in payload["profiles"]:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            merged = dict(by_id.get(item["id"], {}))
            merged.update(item)
            merged["layout"] = _coerce_layout(
                dict(by_id.get(item["id"], {}).get("layout", {}))
                | dict(item.get("layout", {}))
            )
            by_id[item["id"]] = merged
        profiles = list(by_id.values())
    for item in profiles:
        item["layout"] = _coerce_layout(dict(item.get("layout", {})))
    return {
        "schemaVersion": 1,
        "source": source,
        "profiles": profiles,
    }


def resolve_profile(versions, builds, registry: dict | None = None) -> dict | None:
    """Return the first profile whose version prefix and (optional) builds match."""
    if registry is None:
        registry = load_registry()
    version_list = [str(value) for value in (versions or [])]
    build_list = [str(value) for value in (builds or [])]
    for profile in registry.get("profiles", []):
        prefixes = [str(value) for value in profile.get("versionPrefixes", [])]
        if not prefixes or not any(
            version.startswith(prefix) for version in version_list for prefix in prefixes
        ):
            continue
        if profile.get("requireBuilds") and profile.get("builds"):
            if not any(build in build_list for build in profile["builds"]):
                continue
        return profile
    return None


def profile_layout(profile: dict | None) -> dict:
    if not profile:
        return {}
    return _coerce_layout(dict(profile.get("layout", {})))
