#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Publish README, changelog and README screenshots to the public release repo.

The public repo (kpl-scrim-lab-app) holds releases and reader-facing docs,
while the working repo's origin is the private source repo.  Uploading through
the GitHub Contents API keeps both in sync without adding a push remote.

    python scripts/publish_public_docs.py
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = 'hccccc01333/kpl-scrim-lab-app'
FILES = [
    'README.md',
    'CHANGELOG.md',
    'update.json',
    'docs/images/readme-hero.png',
    'docs/images/02-capture.png',
    'docs/images/03-matches.png',
    'docs/images/04-players.png',
    'docs/images/05-team.png',
    'docs/images/06-heroes.png',
    'docs/images/07-topics.png',
    'docs/images/08-depth.png',
    'docs/images/09-match.png',
]


def gh(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(['gh', *args], cwd=ROOT, capture_output=True,
                          text=True, encoding='utf-8', errors='replace')


def main() -> int:
    failed = []
    only = set(sys.argv[1:])
    for rel in FILES:
        if only and not any(part in rel for part in only):
            continue
        path = ROOT / rel
        if not path.is_file():
            print(f'skip (missing locally): {rel}')
            continue
        lookup = gh('api', f'repos/{REPO}/contents/{rel}', '--jq', '.sha')
        sha = lookup.stdout.strip() if lookup.returncode == 0 else ''
        payload = {
            'message': f'docs(3.0.1): refresh {Path(rel).name}',
            'content': base64.b64encode(path.read_bytes()).decode('ascii'),
            'branch': 'main',
        }
        if sha:
            payload['sha'] = sha
        with tempfile.NamedTemporaryFile('w', encoding='utf-8',
                                         suffix='.json', delete=False) as handle:
            json.dump(payload, handle)
            payload_path = handle.name
        result = gh('api', '--method', 'PUT',
                    f'repos/{REPO}/contents/{rel}', '--input', payload_path)
        Path(payload_path).unlink(missing_ok=True)
        if result.returncode == 0:
            print(f'published {rel}')
        else:
            failed.append(rel)
            print(f'FAILED {rel}: {(result.stderr or "")[:300]}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
