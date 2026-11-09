#!/usr/bin/env python3
"""Smoke-check a fresh workbench deployment without touching real data.

Runs the FastAPI app with a temporary SQLite DB and temporary analysis dirs,
then exercises the loopback health/read endpoints through TestClient.

Usage:
  python scripts/check_deploy.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix='kpl-deploy-'))
    os.environ['TRAINING_DB'] = str(tmp / 'training.sqlite3')
    os.environ['ANALYSIS_MATCHES'] = str(tmp / 'matches')
    os.environ['ANALYSIS_IMPORTS'] = str(tmp / 'imports')
    os.environ['ANALYSIS_OFFICIAL'] = str(tmp / 'official_replays')
    os.environ['ANALYSIS_BUILDS'] = str(tmp / 'builds')
    os.environ.setdefault('TRAINING_ALLOWED_HOSTS', '127.0.0.1,localhost,::1')

    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient  # noqa: PLC0415
    import server  # noqa: PLC0415

    client = TestClient(server.app, base_url='http://127.0.0.1')
    checks = [
        ('GET', '/api/health'),
        ('GET', '/api/replays'),
        ('GET', '/api/state'),
        ('GET', '/'),
        ('GET', '/static/app.js'),
        ('GET', '/assets/capture-guide/requirements.json'),
    ]
    failures = []
    for method, path in checks:
        response = client.request(method, path)
        ok = response.status_code == 200
        print(f'{method} {path}: {response.status_code}')
        if not ok:
            failures.append((path, response.status_code, response.text[:300]))

    health = client.get('/api/health')
    if health.status_code == 200:
        payload = health.json()
        print('health:', json.dumps({k: payload.get(k) for k in
                                     ('ok', 'dbPath', 'matchesDir')},
                                    ensure_ascii=False))
        if not payload.get('ok'):
            failures.append(('health.ok', payload))

    ocr = client.get('/api/ocr/status')
    if ocr.status_code != 200:
        failures.append(('ocr.status', ocr.status_code, ocr.text[:300]))
    else:
        status = ocr.json()
        rapid_ok = bool((status.get('rapid') or {}).get('available'))
        mimo = status.get('mimo') or {}
        deps_ok = bool(mimo.get('torch')) and bool(mimo.get('transformers'))
        print('ocr:', json.dumps({
            'rapid': rapid_ok,
            'mimoDeps': deps_ok,
            'mimoModel': bool(mimo.get('available')),
            'ffmpeg': bool(status.get('ffmpeg')),
        }, ensure_ascii=False))
        if not rapid_ok:
            failures.append(('ocr.rapid', 'rapidocr-onnxruntime missing'))
        if not deps_ok:
            # Mimo refinement is an optional add-on; the core workbench runs
            # on RapidOCR alone. See requirements-mimo.txt.
            print('note: Mimo dependencies are not installed; RapidOCR still works.')
            print('      install them with: pip install -r requirements-mimo.txt')
        if not mimo.get('available'):
            print('note: Mimo model weights are not present; RapidOCR still works.')

    if failures:
        print('DEPLOY CHECK FAILED')
        for item in failures:
            print(' ', item)
        return 1
    print('DEPLOY CHECK OK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
