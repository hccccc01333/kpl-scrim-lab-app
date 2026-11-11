"""HTTP endpoints for checking and staging workbench updates,
plus the anonymous-usage disclosure ("匿名使用统计") controls."""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

import telemetry
import updater
import update_client
from paths import data_root

MAX_UPLOAD_BYTES = updater.MAX_PATCH_BYTES
_SAFE_NAME = re.compile(r'[^0-9A-Za-z._-]+')
_OFF_VALUES = ('0', 'false', 'off', 'no')


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

    # -- 匿名使用统计：告知与开关（工作台首次打开会展示，页脚可随时查看） --
    def _usage_status() -> dict:
        env_value = str(os.environ.get(telemetry.ENV_NAME, '') or '').strip().lower()
        env_disabled = env_value in _OFF_VALUES
        enabled = not telemetry.is_disabled(root)
        optout_file = telemetry.optout_path(root)
        try:
            optout = optout_file.exists()
        except OSError:
            optout = False
        # 已关闭统计时不新生成安装 ID：说明框里显示已有 ID（如果有），否则显示「未生成」。
        install_id = ''
        try:
            install_id = telemetry.install_id_path(root).read_text(encoding='utf-8').strip()
        except OSError:
            install_id = ''
        if not re.fullmatch(r'[0-9a-f]{32}', install_id):
            install_id = telemetry.load_install_id(root) if enabled else ''
        state = telemetry.read_state(root)
        return {
            'ok': True,
            'enabled': enabled,
            'envDisabled': env_disabled,
            'optout': optout,
            'installId': install_id,
            'lastPingAt': state.get('lastPingAt'),
            'lastError': state.get('lastError'),
            'periodHours': telemetry.DEFAULT_PERIOD_HOURS,
        }

    @router.get('/api/usage/status')
    def usage_status():
        return _usage_status()

    @router.post('/api/usage/optout')
    def usage_optout():
        """停止匿名心跳：写 data/usage/optout 标记，下一次启动起不再上报。"""
        path = telemetry.optout_path(root)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(time.strftime('%Y-%m-%d %H:%M:%S\n'), encoding='utf-8')
        except OSError as exc:
            raise HTTPException(500, f'写入 opt-out 标记失败：{exc}') from exc
        return _usage_status()

    @router.post('/api/usage/optin')
    def usage_optin():
        """重新开启匿名心跳（环境变量 KPL_TELEMETRY=0 的优先级更高）。"""
        try:
            telemetry.optout_path(root).unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(500, f'删除 opt-out 标记失败：{exc}') from exc
        return _usage_status()

    return router
