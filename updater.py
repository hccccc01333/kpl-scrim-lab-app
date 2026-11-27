"""Apply a code patch to the workbench without touching user data.

Typical use:

  python updater.py --check
  python updater.py --apply patch-1.0.1.zip
  python updater.py --apply-pending --restart --port 8766

A patch is a zip containing ``update.json`` plus ``payload/<relative path>``
entries.  Every payload file is checked against the SHA-256 in the manifest
before it is copied.  The current code is backed up under
``data/backups/code-<version>-<time>/`` so a failed restart can be rolled back.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from paths import data_root
from update_client import (
    UpdateError,
    check_for_update,
    compare_versions,
    download_file,
    normalize_rel_path,
    parse_version,
    resolve_url,
    sha256_file,
    normalize_manifest,
)

MAX_PATCH_BYTES = 120 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024
MAX_MEMBER_BYTES = 50 * 1024 * 1024
MAX_MEMBERS = 5000
# 自动更新改成「保留数据、重装程序」后，补丁内嵌的完整程序清单会超过
# 256 KB；清单本身只在本地读取，放宽到 2 MB 足够容纳全量文件校验值。
MAX_MANIFEST_BYTES_LOCAL = 2 * 1024 * 1024
CLEAN_BUNDLE = 'clean_bundle.zip'
CLEAN_REQUEST = 'clean_request.json'
# 只清程序目录；data/ 与 .env 不动，runtime/ 与 _internal/ 属于安装包运行时，
# 增量补丁不含它们，也不能删。
PROGRAM_DIRS = ('v3', 'tools', 'scripts', 'resources', 'docs', 'web')
PROGRAM_ROOT_SUFFIXES = ('.py', '.pyc', '.bat', '.txt', '.json', '.md',
                         '.exe', '.ico', '.example')
STAGED_ROOT = 'data/update/staged'
PENDING_FILE = 'data/update/pending.json'
LAST_RESULT_FILE = 'data/update/last_result.json'
_VERSION_RE = re.compile(r'^VERSION\s*=\s*[\'"]([^\'"]+)[\'"]', re.MULTILINE)


def _root(value=None) -> Path:
    return Path(value).resolve() if value else Path(__file__).resolve().parent


def read_installed_version(target: Path) -> str:
    path = Path(target) / 'version.py'
    try:
        match = _VERSION_RE.search(path.read_text(encoding='utf-8'))
        if match:
            parse_version(match.group(1))
            return match.group(1)
    except FileNotFoundError:
        return '0.0.0'
    except (OSError, UnicodeError, ValueError) as exc:
        # 文件被占用/损坏时静默降级成 0.0.0 会让更新器误判老版本并覆盖健康安装。
        logging.warning('读取已安装版本失败：%s', exc)
        raise
    return '0.0.0'


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent),
                                     prefix=f'.{path.name}.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return None


def pending_path(target: Path) -> Path:
    return Path(target) / PENDING_FILE


def read_pending(target: Path) -> dict | None:
    payload = _read_json(pending_path(target))
    if not isinstance(payload, dict):
        return None
    try:
        version = str(payload['version'])
        parse_version(version)
        staged = Path(str(payload['stagedDir']))
        if staged.is_absolute():
            return None
        staged_root = (Path(target) / STAGED_ROOT).resolve()
        staged_path = (Path(target) / staged).resolve()
        if staged_root not in staged_path.parents and staged_path != staged_root:
            return None
        files = []
        for item in payload.get('files', []):
            files.append({
                'path': normalize_rel_path(item['path']),
                'sha256': str(item.get('sha256', '')).lower(),
                'size': int(item.get('size', 0) or 0),
            })
        remove = [normalize_rel_path(item) for item in payload.get('remove', [])]
        return {
            'version': version,
            'stagedDir': str(staged),
            'files': files,
            'remove': remove,
            'notes': [str(item) for item in payload.get('notes', [])],
            'createdAt': payload.get('createdAt'),
            'source': payload.get('source', ''),
        }
    except Exception:
        return None


def clear_pending(target: Path) -> None:
    pending_path(target).unlink(missing_ok=True)


def read_last_result(target: Path) -> dict | None:
    payload = _read_json(Path(target) / LAST_RESULT_FILE)
    return payload if isinstance(payload, dict) else None


def _write_result(target: Path, ok: bool, message: str, **extra) -> dict:
    payload = {'ok': ok, 'message': message, 'at': time.strftime('%Y-%m-%d %H:%M:%S'),
               **extra}
    _write_json(Path(target) / LAST_RESULT_FILE, payload)
    return payload


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(destination.parent),
                                      prefix='.update-', suffix='.tmp')
    os.close(fd)
    try:
        shutil.copyfile(source, temp_name)
        try:
            # os.replace 在 Windows 上原子覆盖，先删目标会留下文件消失的窗口。
            os.replace(temp_name, destination)
        except PermissionError:
            _force_unlink(destination)
            os.replace(temp_name, destination)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _safe_member(name: str) -> str:
    normalized = str(name or '').replace('\\', '/')
    if not normalized or normalized.startswith('/') or re.match(r'^[A-Za-z]:', normalized):
        raise ValueError(f'更新包包含非法路径：{name!r}')
    parts = [part for part in normalized.split('/') if part not in ('', '.')]
    if not parts or any(part == '..' for part in parts):
        raise ValueError(f'更新包包含非法路径：{name!r}')
    return '/'.join(parts)


def _prune_staged(target: Path, keep: Path | None = None) -> None:
    root = Path(target) / STAGED_ROOT
    if not root.is_dir():
        return
    entries = sorted((item for item in root.iterdir() if item.is_dir()),
                     key=lambda item: item.stat().st_mtime, reverse=True)
    for item in entries[4:]:
        if keep and item.resolve() == keep.resolve():
            continue
        shutil.rmtree(item, ignore_errors=True)


def stage_patch(zip_path: Path, target: Path | None = None,
                source: str = '', force: bool = False) -> dict:
    """Validate a patch zip and write ``data/update/pending.json``."""
    target = _root(target)
    zip_path = Path(zip_path)
    if not zip_path.is_file():
        raise ValueError('更新包不存在')
    if zip_path.stat().st_size > MAX_PATCH_BYTES:
        raise ValueError('更新包超过大小限制')

    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ValueError('更新包文件数量异常')
        total = 0
        for info in infos:
            total += max(0, info.file_size)
            if info.file_size > MAX_MEMBER_BYTES:
                raise ValueError(f'更新包内文件过大：{info.filename}')
        if total > MAX_UNCOMPRESSED_BYTES:
            raise ValueError('更新包解压后超过大小限制')

        try:
            info = archive.getinfo('update.json')
        except KeyError as exc:
            raise ValueError('更新包缺少 update.json') from exc
        if info.file_size > MAX_MANIFEST_BYTES_LOCAL:
            raise ValueError('update.json 超过大小限制')
        manifest_raw = archive.read(info)
        manifest = normalize_manifest(json.loads(manifest_raw.decode('utf-8')))

    current = read_installed_version(target)
    if not force and compare_versions(manifest['version'], current) <= 0:
        raise ValueError(f"更新包版本 {manifest['version']} 不高于当前版本 {current}")
    min_version = manifest.get('minVersion')
    if min_version and compare_versions(current, min_version) < 0:
        # 增量包只包含基线版本之后的差分：装到更老的版本上会得到
        # 「版本号新、内容缺」的混合安装。这里兜底拦截（含手动上传）。
        raise ValueError(f'当前版本 {current} 低于补丁最低要求 {min_version}，请下载完整包升级')

    patch = manifest.get('patch')
    if not patch:
        raise ValueError('更新包缺少 patch 清单')
    files = patch['files']
    paths = {item['path'] for item in files}
    digests = {item['path']: item['sha256'] for item in files}
    if 'version.py' not in paths:
        raise ValueError('更新包缺少 version.py，无法确认版本')
    if 'version.py' in patch.get('remove', []):
        raise ValueError('更新包不能删除 version.py')

    stamp = time.strftime('%Y%m%d-%H%M%S')
    safe_version = re.sub(r'[^0-9A-Za-z._-]+', '_', manifest['version'])
    staging = (Path(target) / STAGED_ROOT /
               f'{safe_version}-{stamp}-{os.getpid()}')
    if staging.exists():
        shutil.rmtree(staging)
    payload_root = staging / 'payload'

    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = {_safe_member(info.filename): info for info in archive.infolist()
                     if not info.is_dir() and not info.filename.startswith('__MACOSX/')}
            for path in paths:
                member = f'payload/{path}'
                info = names.get(member)
                if info is None:
                    raise ValueError(f'更新包缺少文件：{path}')
                if info.file_size > MAX_MEMBER_BYTES:
                    raise ValueError(f'更新包内文件过大：{path}')
                destination = payload_root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as reader, open(destination, 'wb') as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
                digest = sha256_file(destination)
                if digest != digests[path]:
                    raise ValueError(f'更新包文件校验失败：{path}')
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    pending = {
        'version': manifest['version'],
        'stagedDir': _display_path(target, staging),
        'files': files,
        'remove': patch.get('remove', []),
        'notes': manifest.get('notes', []),
        'createdAt': time.strftime('%Y-%m-%d %H:%M:%S'),
        'source': source,
    }
    _write_json(pending_path(target), pending)
    _prune_staged(target, keep=staging)
    return pending


def item_digest(files: list[dict], path: str) -> str:
    for item in files:
        if item['path'] == path:
            return str(item['sha256']).lower()
    raise KeyError(path)


def _display_path(target: Path, path: Path) -> str:
    """尽量显示相对应用根目录的路径；``KPL_DATA_DIR`` 指到应用外时退回绝对路径。

    更新器的数据目录可以被环境变量指到应用目录之外（多实例 / 演示实例）。
    这种时候 ``path.relative_to(target)`` 会抛 ``ValueError``；旧实现会让已替换
    完文件的更新在写结果时崩掉、服务不再重启，所以这里必须容错。
    """
    try:
        return str(Path(path).relative_to(Path(target))).replace('\\', '/')
    except ValueError:
        return str(Path(path))


def _backup_files(target: Path, paths, current_version: str) -> Path:
    stamp = time.strftime('%Y%m%d-%H%M%S')
    safe_version = re.sub(r'[^0-9A-Za-z._-]+', '_', current_version)
    backup = data_root(target) / 'backups' / f'code-{safe_version}-{stamp}'
    records = []
    for path in sorted(set(paths)):
        destination = Path(target) / path
        record = {'path': path, 'existed': destination.is_file()}
        if record['existed']:
            saved = backup / 'files' / path
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, saved)
        records.append(record)
    _write_json(backup / 'backup.json', {
        'version': current_version,
        'createdAt': time.strftime('%Y-%m-%d %H:%M:%S'),
        'files': records,
    })
    return backup


def restore_backup(backup: Path, target: Path | None = None) -> None:
    target = _root(target)
    payload = _read_json(Path(backup) / 'backup.json')
    if not isinstance(payload, dict):
        raise ValueError('备份清单缺失，无法回滚')
    for record in payload.get('files', []):
        path = normalize_rel_path(record['path'])
        destination = Path(target) / path
        if record.get('existed'):
            saved = Path(backup) / 'files' / path
            if not saved.is_file():
                raise ValueError(f'备份文件缺失：{path}')
            _atomic_copy(saved, destination)
        else:
            destination.unlink(missing_ok=True)


def _prune_backups(target: Path) -> None:
    root = data_root(target) / 'backups'
    if not root.is_dir():
        return
    entries = sorted((item for item in root.iterdir()
                      if item.is_dir() and item.name.startswith('code-')),
                     key=lambda item: item.stat().st_mtime, reverse=True)
    for item in entries[5:]:
        shutil.rmtree(item, ignore_errors=True)


def _clear_bytecode_cache(target: Path) -> int:
    """清掉运行期生成的旧字节码。

    发布包刻意不带 *.pyc，所以补丁的 remove 列表里永远没有它们；旧 pyc 一旦
    被 Python 复用，升级后跑的还是旧版后端逻辑。只清项目自己的代码目录，
    不碰 runtime/ 下的第三方库缓存（数量大且与本产品代码无关）。
    """
    root = Path(target)
    cleared = 0
    for sub in ('', 'v3', 'tools', 'scripts'):
        base = root / sub if sub else root
        if not base.is_dir():
            continue
        for cache in base.rglob('__pycache__'):
            shutil.rmtree(cache, ignore_errors=True)
            cleared += 1
        for pyc in base.rglob('*.pyc'):
            pyc.unlink(missing_ok=True)
            cleared += 1
    return cleared


def _program_delete_paths(target: Path, bundle_paths: set[str] | None = None
                          ) -> tuple[list[str], list[str]]:
    """返回需要清掉的程序目录与根目录程序文件。

    data/（比赛数据、授权、备份）、.env、runtime/、_internal/、logs/ 一律不动。
    根目录只清**随包发布**的文件和旧版 .py/.pyc；安装包生成的 EXE、快捷方式
    BAT、图标、说明文档，以及用户的 update_config.json 必须保留。
    """
    root = Path(target)
    directories = [name for name in PROGRAM_DIRS if (root / name).is_dir()]
    files = []
    for name in directories:
        for item in (root / name).rglob('*'):
            if item.is_file():
                files.append(item.relative_to(root).as_posix())
    preserve = {'update_config.json', '.env', 'camp_auth.json', 'camp_config.json'}
    for item in root.iterdir():
        if not item.is_file() or item.name in preserve:
            continue
        if bundle_paths is not None:
            if item.name in bundle_paths or item.suffix.lower() in ('.py', '.pyc'):
                files.append(item.name)
        elif item.suffix.lower() in PROGRAM_ROOT_SUFFIXES:
            files.append(item.name)
    return directories, sorted(set(files))


def _force_unlink(path: Path) -> None:
    if not path.exists():
        return
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass
    path.unlink()


def _force_rmtree(path: Path) -> None:
    if not path.exists():
        return
    for root, dirs, names in os.walk(path):
        for name in names + dirs:
            try:
                os.chmod(Path(root) / name, stat.S_IWRITE)
            except OSError:
                pass
    shutil.rmtree(path)


def _merge_bootstrap_backup(backup: Path, target: Path) -> str:
    """把引导阶段留下的真正旧版文件覆盖到清装备份里。

    引导补丁会先把 updater/server/version 等几个文件写到新版本，清装启动时
    ``current`` 已是新版本号。restart_flow 在引导阶段记录的 ``previousVersion``
    才是真正的升级前版本，同名文件要从那一份备份取回，回滚才不会混版。
    """
    current = read_installed_version(target)
    last = read_last_result(target) or {}
    previous = str(last.get('previousVersion') or '')
    if not previous or compare_versions(previous, current) >= 0:
        return current
    safe = re.sub(r'[^0-9A-Za-z._-]+', '_', previous)
    root = data_root(target) / 'backups'
    candidates = sorted((item for item in root.glob(f'code-{safe}-*') if item.is_dir()),
                        key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        # 没有真正升级前的备份时不能声称回滚到旧版：清装备份里的 version.py
        # 已经是新版本，返回旧号会让 wait_health 永远等不到服务。
        return current
    source = candidates[0]
    payload = _read_json(source / 'backup.json') or {}
    for record in payload.get('files', []):
        if not record.get('existed'):
            continue
        relative = record.get('path') or ''
        saved = source / 'files' / relative
        if not saved.is_file() or not relative:
            continue
        destination = backup / 'files' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(saved, destination)
    return previous


def _remove_extracted_not_in_backup(backup: Path, target: Path,
                                    extracted: list[str]) -> None:
    """回滚时删掉失败清装已经写入、旧备份里不存在的新文件。"""
    payload = _read_json(backup / 'backup.json') or {}
    backed = {record.get('path') for record in payload.get('files', [])
              if record.get('existed')}
    for relative in extracted:
        if relative in backed:
            continue
        _force_unlink(Path(target) / relative)


def _extract_from_zip(archive: zipfile.ZipFile, info: zipfile.ZipInfo,
                      destination: Path, digest: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(destination.parent),
                                     prefix='.clean-', suffix='.tmp')
    os.close(fd)
    temp = Path(temp_name)
    try:
        with archive.open(info) as reader, open(temp, 'wb') as writer:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
        if sha256_file(temp) != str(digest).lower():
            raise ValueError(f'清装包文件校验失败：{destination.name}')
        last_error = None
        for attempt in range(4):
            try:
                if destination.exists():
                    _force_unlink(destination)
                os.replace(temp, destination)
                return
            except PermissionError as exc:
                last_error = exc
                try:
                    os.chmod(destination.parent, stat.S_IWRITE)
                except OSError:
                    pass
                time.sleep(0.15 * (attempt + 1))
        if last_error:
            raise last_error
    finally:
        temp.unlink(missing_ok=True)


def _sweep_clean_artifacts(target: Path) -> None:
    """清掉没有标记的单据碎片，避免半途退出后留下几十 MB 孤儿文件。"""
    root = Path(target)
    for item in root.glob('clean_bundle.part*'):
        if item.is_file():
            item.unlink(missing_ok=True)
    bundle = root / CLEAN_BUNDLE
    if bundle.is_file():
        bundle.unlink(missing_ok=True)


def apply_clean_bundle_if_requested(target: Path | None = None) -> dict:
    """重启后完成「保留数据、重装程序」的第二阶段。

    增量补丁先把新 updater/server 和内嵌的完整程序包分片写到应用根目录；
    重启时这里校验整包、备份旧程序、清空程序目录后整包装回。
    """
    target = _root(target)
    marker = Path(target) / CLEAN_REQUEST
    if not marker.is_file():
        _sweep_clean_artifacts(target)
        return {'ok': True, 'skipped': True, 'message': '没有待清装的更新'}

    current = read_installed_version(target)
    request = _read_json(marker) or {}
    version = str(request.get('version') or current)
    if compare_versions(version, current) < 0:
        # 残留的旧更新标记不能把已装好的新版降级回去。
        marker.unlink(missing_ok=True)
        _sweep_clean_artifacts(target)
        return {'ok': True, 'skipped': True,
                'message': f'忽略过期清装标记：{version} < {current}'}
    result_written = False
    try:
        bundle_rel = normalize_rel_path(request.get('bundle') or CLEAN_BUNDLE)
    except Exception as exc:  # noqa: BLE001
        message = str(exc) if str(exc).startswith('清装失败') else f'清装失败：{exc}'
        _write_result(target, False, message, version=current)
        raise ValueError(message) from exc
    bundle = Path(target) / bundle_rel
    expected = str(request.get('sha256') or '').lower()
    parts = request.get('parts') or []
    try:
        if parts:
            # 老更新器单次搬运的文件上限 50 MB，清装包按 40 MB 切片下发；
            # 这里逐片校验后拼回完整 zip。
            with open(bundle, 'wb') as writer:
                for item in parts:
                    part = Path(target) / normalize_rel_path(item['path'])
                    if not part.is_file():
                        raise ValueError('清装分包缺失，请重新下载更新包')
                    if sha256_file(part) != str(item['sha256']).lower():
                        raise ValueError('清装分包校验失败，请重新下载更新包')
                    with open(part, 'rb') as reader:
                        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        elif not bundle.is_file():
            raise ValueError('清装包缺失，请重新下载更新包')
        if expected and sha256_file(bundle) != expected:
            raise ValueError('清装包校验失败，请重新下载更新包')
    except Exception as exc:
        bundle.unlink(missing_ok=True)
        message = str(exc) if str(exc).startswith('清装失败') else f'清装失败：{exc}'
        _write_result(target, False, message, version=current)
        raise ValueError(message) from exc
    try:
        with zipfile.ZipFile(bundle) as archive:
            try:
                entries = json.loads(archive.read('manifest.json').decode('utf-8'))
            except (KeyError, ValueError) as exc:
                raise ValueError('清装包缺少有效清单') from exc
            if not isinstance(entries, list) or not entries:
                raise ValueError('清装包清单为空')
            members = {}
            for info in archive.infolist():
                if not info.is_dir() and not info.filename.startswith('__MACOSX/'):
                    members[_safe_member(info.filename)] = info
            paths = []
            for item in entries:
                path = normalize_rel_path(item['path'])
                digest = str(item['sha256']).lower()
                info = members.get(f'payload/{path}')
                if info is None:
                    raise ValueError(f'清装包缺少文件：{path}')
                if sha256_file_from_zip(archive, info) != digest:
                    raise ValueError(f'清装包文件校验失败：{path}')
                paths.append((path, info, digest))
            if 'version.py' not in {path for path, _, _ in paths}:
                raise ValueError('清装包缺少 version.py')

            bundle_paths = {path for path, _, _ in paths}
            directories, existing = _program_delete_paths(target, bundle_paths)
            backup = _backup_files(target, existing, current)
            previous = _merge_bootstrap_backup(backup, target)
            extracted = []
            try:
                for name in directories:
                    _force_rmtree(Path(target) / name)
                for name in existing:
                    _force_unlink(Path(target) / name)
                for path, info, digest in paths:
                    _extract_from_zip(archive, info, Path(target) / path, digest)
                    extracted.append(path)
                installed = read_installed_version(target)
                if compare_versions(installed, version) != 0:
                    raise ValueError(f'清装后版本号不一致（{installed} != {version}）')
            except Exception as exc:
                try:
                    _remove_extracted_not_in_backup(backup, target, extracted)
                    restore_backup(backup, target)
                    message = f'清装失败，已回滚到 {previous}：{exc}'
                except Exception as rollback_error:  # noqa: BLE001
                    message = f'清装失败且回滚失败：{exc}；{rollback_error}'
                _write_result(target, False, message, version=previous,
                              backupDir=_display_path(target, backup))
                result_written = True
                raise ValueError(message) from exc
    except Exception as exc:  # noqa: BLE001
        message = str(exc) if str(exc).startswith('清装失败') else f'清装失败：{exc}'
        if not result_written:
            _write_result(target, False, message, version=current)
        raise ValueError(message) from exc

    # 先清大文件、最后删标记：中途失败仍可凭标记重试。
    for item in parts:
        (Path(target) / normalize_rel_path(item['path'])).unlink(missing_ok=True)
    bundle.unlink(missing_ok=True)
    marker.unlink(missing_ok=True)
    cleared = _clear_bytecode_cache(target)
    _prune_backups(target)
    _write_result(target, True, f'已清装到 {version}', version=version,
                  previousVersion=previous, files=len(paths),
                  removedDirs=directories,
                  backupDir=_display_path(target, backup),
                  clearedCaches=cleared)
    return {'ok': True, 'skipped': False, 'version': version,
            'previousVersion': previous, 'files': len(paths)}


def sha256_file_from_zip(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(info) as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def apply_pending(target: Path | None = None) -> dict:
    target = _root(target)
    pending = read_pending(target)
    if not pending:
        return {'ok': True, 'skipped': True, 'message': '没有待应用的更新'}

    current = read_installed_version(target)
    if compare_versions(pending['version'], current) <= 0:
        clear_pending(target)
        return {'ok': True, 'skipped': True,
                'message': f"当前已是 {current}，无需重复更新"}

    staged = Path(target) / pending['stagedDir']
    if not staged.is_dir():
        clear_pending(target)
        raise ValueError('暂存的更新包已丢失，请重新下载')

    for item in pending['files']:
        source = staged / 'payload' / item['path']
        if not source.is_file():
            clear_pending(target)
            raise ValueError(f"暂存文件缺失：{item['path']}")
        if sha256_file(source) != item['sha256']:
            clear_pending(target)
            raise ValueError(f"暂存文件校验失败：{item['path']}")

    paths = [item['path'] for item in pending['files']] + pending['remove']
    paths.append('version.py')
    backup = _backup_files(target, paths, current)
    try:
        for item in pending['files']:
            _atomic_copy(staged / 'payload' / item['path'],
                         Path(target) / item['path'])
        for path in pending['remove']:
            (Path(target) / path).unlink(missing_ok=True)
        installed = read_installed_version(target)
        if compare_versions(installed, pending['version']) != 0:
            raise ValueError(f'更新后版本号不一致（{installed} != {pending["version"]}）')
    except Exception as exc:
        try:
            restore_backup(backup, target)
            message = f'更新失败，已回滚：{exc}'
        except Exception as rollback_error:  # noqa: BLE001
            message = f'更新失败且回滚失败：{exc}；{rollback_error}'
        clear_pending(target)
        _write_result(target, False, message,
                      version=current, backupDir=_display_path(target, backup))
        raise ValueError(message) from exc

    clear_pending(target)
    cleared_caches = _clear_bytecode_cache(target)
    shutil.rmtree(staged, ignore_errors=True)
    _prune_backups(target)
    result = _write_result(
        target, True, f"已更新到 {pending['version']}",
        version=pending['version'], previousVersion=current,
        backupDir=_display_path(target, backup),
        files=len(pending['files']), removed=len(pending['remove']),
        clearedCaches=cleared_caches)
    return {'ok': True, 'skipped': False, 'version': pending['version'],
            'previousVersion': current, 'backupDir': str(backup),
            'files': len(pending['files']), 'removed': len(pending['remove']),
            'clearedCaches': cleared_caches, 'result': result}


def _port_free(port: int, host: str = '127.0.0.1') -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) != 0


def wait_port_free(port: int, timeout: float = 30.0, host: str = '127.0.0.1') -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_free(port, host):
            return True
        time.sleep(0.5)
    return False


def _server_python(target: Path) -> Path:
    runtime = Path(target) / 'runtime' / ('python.exe' if os.name == 'nt' else 'python')
    return runtime if runtime.is_file() else Path(sys.executable)


def start_server(target: Path, port: int) -> subprocess.Popen:
    log = Path(target) / 'logs' / 'update-server.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['TRAINING_PORT'] = str(port)
    env.setdefault('PYTHONUTF8', '1')
    handle = open(log, 'ab')
    kwargs = {
        'cwd': str(target),
        'env': env,
        'stdin': subprocess.DEVNULL,
        'stdout': handle,
        'stderr': subprocess.STDOUT,
        'close_fds': True,
    }
    if os.name == 'nt':
        kwargs['creationflags'] = (subprocess.DETACHED_PROCESS |
                                   subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs['start_new_session'] = True
    try:
        return subprocess.Popen([str(_server_python(target)),
                                 str(Path(target) / 'server.py')], **kwargs)
    finally:
        handle.close()


def wait_health(port: int, expected_version: str, timeout: float = 90.0) -> bool:
    deadline = time.time() + timeout
    url = f'http://127.0.0.1:{port}/api/health'
    while time.time() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                payload = json.loads(response.read().decode('utf-8'))
            version = str(payload.get('version', ''))
            if expected_version and compare_versions(version, expected_version) == 0:
                return True
            if not expected_version and payload.get('ok'):
                return True
        except (URLError, OSError, ValueError, json.JSONDecodeError):
            pass
        time.sleep(1)
    return False


def _terminate(process: subprocess.Popen) -> None:
    try:
        process.terminate()
        process.wait(timeout=8)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def spawn_restart(target: Path | None = None, port: int | None = None) -> None:
    """Start a detached updater that waits for this server to exit."""
    target = _root(target)
    port = int(port or os.environ.get('TRAINING_PORT', '8766'))
    log = Path(target) / 'logs' / 'update.log'
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(Path(target) / 'updater.py'),
               '--apply-pending', '--restart', '--port', str(port)]
    handle = open(log, 'ab')
    kwargs = {
        'cwd': str(target),
        'stdin': subprocess.DEVNULL,
        'stdout': handle,
        'stderr': subprocess.STDOUT,
        'close_fds': True,
    }
    if os.name == 'nt':
        kwargs['creationflags'] = (subprocess.DETACHED_PROCESS |
                                   subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs['start_new_session'] = True
    try:
        subprocess.Popen(command, **kwargs)
    finally:
        handle.close()


def restart_flow(target: Path | None = None, port: int | None = None) -> dict:
    target = _root(target)
    port = int(port or os.environ.get('TRAINING_PORT', '8766'))
    pending = read_pending(target)
    if not pending:
        return {'ok': True, 'skipped': True, 'message': '没有待应用的更新'}
    expected = pending['version']
    previous = read_installed_version(target)

    if not wait_port_free(port, timeout=30):
        message = f'端口 {port} 仍被占用，更新未执行'
        _write_result(target, False, message, version=previous)
        return {'ok': False, 'message': message}

    try:
        applied = apply_pending(target)
    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'message': str(exc)}

    process = None
    last = {}
    try:
        process = start_server(target, port)
        if wait_health(port, expected, timeout=90):
            last = read_last_result(target) or {}
            if (Path(target) / CLEAN_REQUEST).is_file() or last.get('ok') is False:
                raise RuntimeError(last.get('message') or '清装未完成，版本文件不能代表安装完成')
            message = f"已更新到 {expected}，服务已重启"
            _write_result(target, True, message, version=expected)
            return {'ok': True, 'message': message, 'version': expected}
        raise RuntimeError('新版本启动后健康检查未通过')
    except Exception as exc:  # noqa: BLE001
        if process is not None:
            _terminate(process)
        # 健康检查超时也会走到这里；此时 last 还是空字典，必须重新读结果，
        # 否则会误用只有几个新文件的 bootstrap 备份，留下混版安装。
        last = read_last_result(target) or last
        # 清装失败时 last_result 指向保留旧文件的清装备份；引导备份只有几个新文件。
        backup_value = (last.get('backupDir') if last.get('ok') is False
                        else applied.get('backupDir'))
        if backup_value:
            backup = Path(backup_value)
            if not backup.is_absolute():
                backup = Path(target) / backup
        else:
            backup = None
        (Path(target) / CLEAN_REQUEST).unlink(missing_ok=True)
        _sweep_clean_artifacts(target)
        rollback_ok = False
        if backup and backup.is_dir():
            try:
                restore_backup(backup, target)
                rollback_ok = True
            except Exception:
                pass
        old_process = None
        try:
            old_process = start_server(target, port)
            wait_health(port, previous, timeout=60)
        except Exception:
            if old_process is not None:
                _terminate(old_process)
        message = (f'更新启动失败，{"已回滚到 " + previous if rollback_ok else "回滚失败"}：{exc}')
        _write_result(target, False, message, version=previous)
        return {'ok': False, 'message': message}


def _print_check(target: Path, as_json: bool) -> int:
    result = check_for_update(target, read_installed_version(target), force=True)
    public = {key: value for key, value in result.items() if key != 'manifest'}
    if as_json:
        print(json.dumps(public, ensure_ascii=False, indent=2))
        return 0
    if not result.get('ok'):
        print(f"检查失败：{result.get('reason', '未知错误')}")
        return 1
    print(f"当前版本：{result['currentVersion']}")
    print(f"最新版本：{result['latestVersion']}")
    if result.get('updateAvailable'):
        print('发现更新：')
        for note in result.get('notes', []):
            print(f'  - {note}')
    else:
        print('已是最新版本。')
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='KPL 赛训工作台更新器')
    parser.add_argument('--target', help='应用根目录（默认脚本所在目录）')
    parser.add_argument('--apply', metavar='ZIP', help='应用本地更新包')
    parser.add_argument('--apply-pending', action='store_true',
                        help='应用已暂存的更新')
    parser.add_argument('--restart', action='store_true',
                        help='应用后重启服务并做健康检查')
    parser.add_argument('--port', type=int, default=int(os.environ.get('TRAINING_PORT', '8766')))
    parser.add_argument('--check', action='store_true', help='检查更新')
    parser.add_argument('--json', action='store_true', help='以 JSON 输出检查结果')
    parser.add_argument('--force', action='store_true', help='允许同版本重装')
    args = parser.parse_args(argv)
    target = _root(args.target)

    try:
        if args.check:
            return _print_check(target, args.json)
        if args.apply:
            pending = stage_patch(Path(args.apply), target, source=str(args.apply),
                                  force=args.force)
            print(f"已暂存 {pending['version']}")
            if args.restart:
                result = restart_flow(target, args.port)
            else:
                result = apply_pending(target)
        elif args.apply_pending:
            if args.restart:
                result = restart_flow(target, args.port)
            else:
                result = apply_pending(target)
        else:
            parser.print_help()
            return 2
    except Exception as exc:  # noqa: BLE001
        print(f'更新失败：{exc}', file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result.get('message', '完成'))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
