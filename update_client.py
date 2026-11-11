"""Update manifest client used by the workbench and the standalone updater.

The module is deliberately dependency-free so the portable package can run it
with the embedded Python.  Network problems are never fatal: callers receive a
result dict with ``ok: False`` and a short reason.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from paths import data_root

# Gitee 放第一位：国内不翻墙也能检查更新；GitHub 作为海外网络兜底。
DEFAULT_MANIFEST_URLS = (
    'https://gitee.com/Rainfun42/kpl-scrim-lab-app/raw/main/update.json',
    'https://github.com/hccccc01333/kpl-scrim-lab-app/releases/latest/download/update.json',
    'https://raw.githubusercontent.com/hccccc01333/kpl-scrim-lab-app/main/update.json',
)
MAX_MANIFEST_BYTES = 256 * 1024
CACHE_MAX_AGE = 6 * 3600
USER_AGENT = 'KPL-Scrim-Lab-Updater/1.0'

# Paths an update patch may never write to.  Business data, credentials and
# build artefacts stay outside the update surface.
FORBIDDEN_PREFIXES = (
    'data/',
    '.git/',
    'runtime/',
    'logs/',
    'models/',
    'test-results/',
    'tests/',
    # tools/ 下的 camp_sync/camp_client 等是运行期模块（随包发布，server.py
    # 会 import）；整体禁写会让所有含 tools/ 修复的增量包装不上。只保护
    # 应用内安装的 ffmpeg 二进制目录，避免被补丁覆盖。
    'tools/ffmpeg/',
    '内部资料/',
)
FORBIDDEN_FILES = {'.env', 'camp_auth.json', 'camp_config.json'}

_VERSION_RE = re.compile(
    r'^[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?'
    r'(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$'
)
_SHA256_RE = re.compile(r'^[0-9a-f]{64}$')


class UpdateError(RuntimeError):
    """Manifest lookup or validation failed."""


def parse_version(value: str) -> tuple[int, int, int, tuple]:
    text = str(value or '').strip()
    match = _VERSION_RE.match(text)
    if not match:
        raise ValueError(f'无法识别的版本号：{value!r}')
    major, minor, patch = (int(match.group(i) or 0) for i in (1, 2, 3))
    prerelease = match.group(4)
    if prerelease is None:
        pre_key: tuple = (1, ())
    else:
        parts = []
        for item in prerelease.split('.'):
            if item.isdigit():
                parts.append((0, int(item)))
            else:
                parts.append((1, item))
        pre_key = (0, tuple(parts))
    return major, minor, patch, pre_key


def compare_versions(left: str, right: str) -> int:
    a, b = parse_version(left), parse_version(right)
    return (a > b) - (a < b)


def normalize_rel_path(value: str) -> str:
    """Return a safe ``a/b/c`` path relative to the application root."""
    text = str(value or '').replace('\\', '/').strip()
    if not text or text.startswith('/'):
        raise ValueError(f'非法文件路径：{value!r}')
    if re.match(r'^[A-Za-z]:', text):
        raise ValueError(f'非法文件路径：{value!r}')
    parts = [part for part in text.split('/') if part not in ('', '.')]
    if not parts or any(part == '..' for part in parts):
        raise ValueError(f'非法文件路径：{value!r}')
    normalized = '/'.join(parts)
    if normalized in FORBIDDEN_FILES:
        raise ValueError(f'更新包不允许修改 {normalized}')
    if any(normalized.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
        raise ValueError(f'更新包不允许修改 {normalized}')
    return normalized


def manifest_urls(root: Path | str | None = None,
                  env: dict | None = None) -> list[str]:
    source = env if env is not None else os.environ
    raw = str(source.get('UPDATE_MANIFEST_URLS', '') or '').strip()
    if raw:
        return [item.strip() for item in raw.split(',') if item.strip()]
    if root:
        try:
            config = json.loads((Path(root) / 'update_config.json').read_text(encoding='utf-8'))
            items = config.get('manifestUrls') or config.get('urls') or []
            items = [str(item).strip() for item in items if str(item).strip()]
            if items:
                return items
        except Exception:
            pass
    return list(DEFAULT_MANIFEST_URLS)


def _allow_http(env: dict | None = None) -> bool:
    source = env if env is not None else os.environ
    return str(source.get('UPDATE_ALLOW_HTTP', '') or '').strip().lower() in (
        '1', 'true', 'yes', 'on')


def _check_url(url: str, allow_http: bool | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme == 'https':
        return url
    if parsed.scheme == 'http' and (
            allow_http is True or parsed.hostname in ('127.0.0.1', 'localhost', '::1')):
        return url
    raise ValueError(f'更新源必须使用 HTTPS：{url}')


def _read_url(url: str, limit: int, timeout: float,
              allow_http: bool | None = None) -> bytes:
    _check_url(url, allow_http)
    request = Request(url, headers={'User-Agent': USER_AGENT,
                                    'Accept': 'application/json'})
    with urlopen(request, timeout=timeout) as response:
        length = response.headers.get('Content-Length')
        if length and int(length) > limit:
            raise UpdateError('更新清单超过大小限制')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError('更新清单超过大小限制')
    return data


def _normalize_hashes(items, label: str) -> list[dict]:
    if not isinstance(items, list) or not items:
        raise ValueError(f'{label} 文件列表为空')
    result = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f'{label} 文件条目格式错误')
        path = normalize_rel_path(item.get('path', ''))
        digest = str(item.get('sha256', '') or '').lower()
        if not _SHA256_RE.match(digest):
            raise ValueError(f'{path} 的 sha256 无效')
        if path in seen:
            raise ValueError(f'{label} 中文件重复：{path}')
        seen.add(path)
        size = item.get('size', 0)
        try:
            size = int(size)
        except (TypeError, ValueError):
            raise ValueError(f'{path} 的 size 无效') from None
        if size < 0:
            raise ValueError(f'{path} 的 size 无效')
        result.append({'path': path, 'sha256': digest, 'size': size})
    return result


def normalize_manifest(data) -> dict:
    if not isinstance(data, dict):
        raise ValueError('更新清单不是 JSON 对象')
    version = str(data.get('version', '') or '').strip()
    parse_version(version)

    notes = data.get('notes', [])
    if isinstance(notes, str):
        notes = [notes]
    if not isinstance(notes, list):
        raise ValueError('notes 必须是字符串或字符串数组')
    notes = [str(item).strip() for item in notes if str(item).strip()]

    result = {
        'schema': int(data.get('schema', 1) or 1),
        'version': version,
        'publishedAt': str(data.get('publishedAt', '') or ''),
        'channel': str(data.get('channel', 'stable') or 'stable'),
        'notes': notes,
    }
    if data.get('minVersion'):
        parse_version(str(data['minVersion']))
        result['minVersion'] = str(data['minVersion'])

    patch = data.get('patch')
    if patch:
        if not isinstance(patch, dict):
            raise ValueError('patch 必须是对象')
        url = str(patch.get('url', '') or '').strip()
        if not url:
            raise ValueError('patch.url 为空')
        normalized_patch = {
            'url': url,
            'files': _normalize_hashes(patch.get('files'), 'patch'),
            'remove': [],
        }
        for item in patch.get('remove', []) or []:
            normalized_patch['remove'].append(normalize_rel_path(item))
        if patch.get('sha256'):
            digest = str(patch['sha256']).lower()
            if not _SHA256_RE.match(digest):
                raise ValueError('patch.sha256 无效')
            normalized_patch['sha256'] = digest
        if patch.get('size') is not None:
            normalized_patch['size'] = int(patch['size'])
        result['patch'] = normalized_patch

    full = data.get('full')
    if full:
        if not isinstance(full, dict) or not str(full.get('url', '') or '').strip():
            raise ValueError('full.url 为空')
        normalized_full = {'url': str(full['url']).strip()}
        if full.get('sha256'):
            digest = str(full['sha256']).lower()
            if not _SHA256_RE.match(digest):
                raise ValueError('full.sha256 无效')
            normalized_full['sha256'] = digest
        if full.get('size') is not None:
            normalized_full['size'] = int(full['size'])
        result['full'] = normalized_full
    return result


def fetch_manifest(urls=None, timeout: float = 3.0,
                   allow_http: bool | None = None,
                   root: Path | str | None = None) -> tuple[dict, str]:
    errors = []
    for url in urls or manifest_urls(root):
        try:
            payload = _read_url(url, MAX_MANIFEST_BYTES, timeout, allow_http)
            return normalize_manifest(json.loads(payload.decode('utf-8'))), url
        except Exception as exc:  # noqa: BLE001 - try the next mirror
            errors.append(f'{url}: {exc}')
    raise UpdateError('更新源均不可用：' + '；'.join(errors))


def cache_file(root: Path) -> Path:
    return data_root(root) / 'update_cache.json'


def load_cache(root: Path) -> dict | None:
    path = cache_file(root)
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        manifest = normalize_manifest(payload.get('manifest'))
        checked_at = float(payload.get('checkedAt') or 0)
        source = str(payload.get('source') or '')
        if checked_at <= 0 or not source:
            return None
        return {'checkedAt': checked_at, 'source': source, 'manifest': manifest}
    except Exception:
        return None


def save_cache(root: Path, manifest: dict, source: str) -> None:
    path = cache_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({'checkedAt': time.time(), 'source': source,
                          'manifest': manifest}, ensure_ascii=False, indent=2)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(payload, encoding='utf-8')
    os.replace(temp, path)


def check_for_update(root: Path, current_version: str, force: bool = False,
                     timeout: float = 3.0, urls=None) -> dict:
    """Return update state.  Never raises for ordinary network failures."""
    root = Path(root)
    cached = load_cache(root)
    now = time.time()
    stale = False
    if cached and not force and now - cached['checkedAt'] < CACHE_MAX_AGE:
        manifest, source = cached['manifest'], cached['source']
    else:
        try:
            manifest, source = fetch_manifest(urls, timeout, root=root)
        except Exception as exc:  # noqa: BLE001
            if cached:
                manifest, source, stale = cached['manifest'], cached['source'], True
            else:
                return {'ok': False, 'currentVersion': current_version,
                        'reason': str(exc), 'checkedAt': now}
        else:
            try:
                save_cache(root, manifest, source)
            except Exception:
                pass

    available = compare_versions(manifest['version'], current_version) > 0
    min_version = manifest.get('minVersion')
    blocked = bool(min_version and compare_versions(current_version, min_version) < 0)
    return {
        'ok': True,
        'currentVersion': current_version,
        'latestVersion': manifest['version'],
        'updateAvailable': available,
        'blocked': blocked,
        'minVersion': min_version,
        'channel': manifest.get('channel', 'stable'),
        'publishedAt': manifest.get('publishedAt', ''),
        'notes': manifest.get('notes', []),
        'patch': manifest.get('patch'),
        'full': manifest.get('full'),
        'source': source,
        'stale': stale,
        'checkedAt': now,
        'manifest': manifest,
    }


def resolve_url(base: str, value: str) -> str:
    return urljoin(base, value)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, destination: Path, timeout: float = 60.0,
                  max_bytes: int = 120 * 1024 * 1024,
                  expected_sha256: str | None = None,
                  allow_http: bool | None = None) -> Path:
    _check_url(url, allow_http)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + '.part')
    request = Request(url, headers={'User-Agent': USER_AGENT})
    digest = hashlib.sha256()
    total = 0
    try:
        with urlopen(request, timeout=timeout) as response, open(temp, 'wb') as handle:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise UpdateError('更新包超过大小限制')
                digest.update(chunk)
                handle.write(chunk)
        actual = digest.hexdigest()
        if expected_sha256 and actual.lower() != expected_sha256.lower():
            raise UpdateError('更新包校验失败（SHA-256 不匹配）')
        os.replace(temp, destination)
        return destination
    except HTTPError as exc:
        raise UpdateError(f'下载更新包失败：HTTP {exc.code}') from exc
    except URLError as exc:
        raise UpdateError(f'下载更新包失败：{exc.reason}') from exc
    finally:
        temp.unlink(missing_ok=True)
