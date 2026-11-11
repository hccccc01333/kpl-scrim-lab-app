"""HTTP endpoints for checking and staging workbench updates."""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

import updater
import update_client
from paths import data_root

MAX_UPLOAD_BYTES = updater.MAX_PATCH_BYTES
_SAFE_NAME = re.compile(r'[^0-9A-Za-z._-]+')


def _public_pending(pending: dict | None) -> dict | None:
    if not pending:
        return None
    return {
        'version': pending.get('version'),
        'notes': pending.get('notes', []),
        'fileCount': len(pending.get('files', [])),
        'remove': pending.get('remove', []),
        'createdAt': pending.get('createdAt'),
        'source': pending.get('source', ''),
    }


def _absolute_assets(result: dict) -> dict:
    source = result.get('source') or ''
    patch = result.get('patch')
    if patch:
        patch = dict(patch)
        patch['url'] = update_client.resolve_url(source, patch['url'])
    full = result.get('full')
    if full:
        full = dict(full)
        full['url'] = update_client.resolve_url(source, full['url'])
    result = dict(result)
    result['patch'] = patch
    result['full'] = full
    return result


def _schedule_exit(delay: float = 1.0) -> None:
    if os.environ.get('KPL_UPDATE_NO_EXIT', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        return

    def exit_later():
        time.sleep(delay)
        os._exit(0)

    threading.Thread(target=exit_later, name='kpl-update-exit', daemon=True).start()


def create_update_router(root: Path, current_version: str) -> APIRouter:
    root = Path(root)
    router = APIRouter()
    lock = threading.Lock()

    def source_checkout() -> bool:
        """源码目录（有 .git）不能用增量包覆盖，更新走 git pull。"""
        return (root / '.git').is_dir()

    @router.get('/api/update/check')
    def check(force: int = 0):
        result = update_client.check_for_update(
            root, current_version, force=bool(force))
        if result.get('ok'):
            result = _absolute_assets(result)
            result.pop('manifest', None)
        result['pending'] = _public_pending(updater.read_pending(root))
        result['sourceMode'] = source_checkout()
        return result

    @router.get('/api/update/status')
    def status():
        return {
            'ok': True,
            'currentVersion': current_version,
            'pending': _public_pending(updater.read_pending(root)),
            'lastResult': updater.read_last_result(root),
        }

    @router.post('/api/update/stage')
    async def stage(request: Request):
        if source_checkout():
            raise HTTPException(400, '源码模式请用「更新代码.bat」（git pull）更新')
        body = await request.body()
        if not body:
            raise HTTPException(400, '更新包为空')
        if len(body) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, '更新包超过大小限制')
        name = _SAFE_NAME.sub('_', request.headers.get('x-filename', 'patch.zip'))
        upload_dir = data_root(root) / 'update' / 'uploads'
        upload_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        target = upload_dir / f'{stamp}-{name}'
        target.write_bytes(body)
        with lock:
            try:
                pending = updater.stage_patch(target, root, source=f'local:{name}')
            except Exception as exc:  # noqa: BLE001
                target.unlink(missing_ok=True)
                raise HTTPException(400, str(exc)) from exc
        return {'ok': True, 'pending': _public_pending(pending)}

    def _download_and_stage() -> dict:
        if source_checkout():
            raise ValueError('源码模式请用「更新代码.bat」（git pull）更新')
        result = update_client.check_for_update(
            root, current_version, force=True)
        if not result.get('ok'):
            raise ValueError(result.get('reason') or '无法获取更新清单')
        if not result.get('updateAvailable'):
            raise ValueError('当前已是最新版本')
        if result.get('blocked'):
            raise ValueError(f"当前版本过旧，请下载完整包升级到 {result.get('minVersion')}")
        patch = result.get('patch')
        if not patch:
            raise ValueError('该版本未提供增量包，请下载完整包')
        url = update_client.resolve_url(result['source'], patch['url'])
        destination = (data_root(root) / 'update' / 'downloads' /
                       f"patch-{result['latestVersion']}.zip")
        update_client.download_file(
            url, destination, expected_sha256=patch.get('sha256'),
            max_bytes=MAX_UPLOAD_BYTES)
        return updater.stage_patch(destination, root, source=url)

    @router.post('/api/update/apply')
    async def apply(request: Request):
        try:
            await request.body()
        except Exception:
            pass
        with lock:
            try:
                pending = await asyncio.to_thread(_download_and_stage)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(400, str(exc)) from exc
            updater.spawn_restart(root)
        _schedule_exit()
        return {'ok': True, 'restarting': True,
                'pending': _public_pending(pending)}

    @router.post('/api/update/restart')
    def restart():
        pending = updater.read_pending(root)
        if not pending:
            raise HTTPException(409, '没有待应用的更新')
        with lock:
            updater.spawn_restart(root)
        _schedule_exit()
        return {'ok': True, 'restarting': True,
                'pending': _public_pending(pending)}

    return router
