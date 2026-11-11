"""Local recording library: original video, OCR report and evidence frames.

Files live under ``data/recordings/<id>/``.  The database is not involved, so a
large recording never goes into SQLite or a JSON backup.  All paths are local;
the OCR job reads the original video and writes a report beside it.
"""
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from paths import data_root

ROOT = Path(__file__).resolve().parent
LIBRARY = Path(os.environ.get('KPL_RECORDINGS', data_root() / 'recordings'))
TEMP = LIBRARY / '.tmp'
MAX_BYTES = int(os.environ.get('KPL_MAX_RECORDING_BYTES', 2 * 1024 * 1024 * 1024))
ALLOWED_EXT = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.m4v'}


class RecordingError(ValueError):
    """A recording cannot be stored or read."""


def _safe_id(value):
    value = str(value or '')
    if not re.fullmatch(r'[0-9a-f]{16,64}', value):
        raise RecordingError('录像 ID 无效')
    return value


def new_temp_path():
    TEMP.mkdir(parents=True, exist_ok=True)
    return TEMP / f'{uuid.uuid4().hex}.upload'


def finalize(temp_path, name):
    """Validate, hash and move an uploaded video into the local library."""
    temp_path = Path(temp_path)
    name = _clean_name(name)
    try:
        size = temp_path.stat().st_size
    except OSError as error:
        raise RecordingError('上传文件已丢失') from error
    if size <= 0:
        _remove_quietly(temp_path)
        raise RecordingError('录像文件为空')
    if size > MAX_BYTES:
        _remove_quietly(temp_path)
        raise RecordingError(f'录像请小于 {MAX_BYTES // (1024 ** 3)} GB')
    free = free_bytes()
    if free < size + 128 * 1024 * 1024:
        _remove_quietly(temp_path)
        raise RecordingError(
            f'本机录屏磁盘剩余空间不足：需要约 {size // (1024 ** 2) + 128} MB，'
            f'当前仅 {free // (1024 ** 2)} MB。请清理磁盘或设置 KPL_RECORDINGS 到其他盘。')
    digest = _sha256(temp_path)
    recording_id = digest[:32]
    folder = LIBRARY / recording_id
    meta_path = folder / 'meta.json'
    if meta_path.is_file():
        _remove_quietly(temp_path)
        return public(read_meta(recording_id))
    try:
        from video_ocr import VideoOCRError, probe_video
        info = probe_video(str(temp_path))
    except Exception as error:
        _remove_quietly(temp_path)
        message = str(error) or type(error).__name__
        raise RecordingError(f'无法读取录像：{message}') from error
    extension = Path(name).suffix.lower()
    if extension not in ALLOWED_EXT:
        extension = '.mp4'
    folder.mkdir(parents=True, exist_ok=True)
    video_path = folder / f'video{extension}'
    temp_path.replace(video_path)
    now = time.time()
    meta = {
        'id': recording_id,
        'name': name,
        'size': size,
        'sha256': digest,
        'createdAt': now,
        'updatedAt': now,
        'video': {
            'duration': info.get('duration'),
            'width': info.get('width'),
            'height': info.get('height'),
            'fps': info.get('fps'),
            'codec': info.get('codec'),
            'file': video_path.name,
        },
        'status': 'uploaded',
        'stage': '待识别',
        'progress': 0,
        'engine': None,
        'sampleFps': None,
        'report': {'available': False, 'updatedAt': None, 'warnings': 0,
                   'coverage': None, 'match': None, 'pov': None,
                   'lineupHeroes': None, 'gameCoverage': None},
        'error': None,
    }
    _write_meta(recording_id, meta)
    return public(meta)


def _clean_name(name):
    name = Path(str(name or '录屏.mp4')).name.strip()
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', '_', name)
    return (name or '录屏.mp4')[:200]


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_quietly(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def _meta_path(recording_id):
    return LIBRARY / _safe_id(recording_id) / 'meta.json'


def read_meta(recording_id):
    path = _meta_path(recording_id)
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise RecordingError('录像记录不存在或已损坏') from error
    if not isinstance(value, dict) or not value.get('id'):
        raise RecordingError('录像记录格式错误')
    return value


def _write_meta(recording_id, meta):
    path = _meta_path(recording_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    meta['updatedAt'] = time.time()
    temp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def update_meta(recording_id, **fields):
    meta = read_meta(recording_id)
    meta.update(fields)
    _write_meta(recording_id, meta)
    return public(meta)


def set_progress(recording_id, stage, progress=None, message=None):
    fields = {'stage': stage}
    if progress is not None:
        fields['progress'] = max(0, min(100, int(progress)))
    if message is not None:
        fields['error'] = None
        fields['stage'] = f'{stage} · {message}' if message else stage
    return update_meta(recording_id, **fields)


def save_report(recording_id, report, engine, sample_fps):
    folder = LIBRARY / _safe_id(recording_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'report.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
    meta = read_meta(recording_id)
    coverage = report.get('coverage') or {}
    meta.update({
        'status': 'done',
        'stage': '识别完成',
        'progress': 100,
        'error': None,
        'engine': engine,
        'sampleFps': sample_fps,
        'report': {
            'available': True,
            'updatedAt': time.time(),
            'warnings': len(report.get('warnings') or []),
            'coverage': coverage,
            'match': report.get('match') or {},
            'pov': report.get('pov'),
            'lineupHeroes': coverage.get('lineupHeroes'),
            'gameCoverage': (report.get('scenes') or [{}])[-1].get('end') if report.get('scenes') else None,
            'mimo': bool((report.get('mimo') or {}).get('available')),
        },
    })
    _write_meta(recording_id, meta)
    return public(meta)


def read_report(recording_id):
    path = LIBRARY / _safe_id(recording_id) / 'report.json'
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise RecordingError('该录像还没有识别报告') from error
    if not isinstance(value, dict):
        raise RecordingError('识别报告格式错误')
    return value


def video_path(recording_id):
    meta = read_meta(recording_id)
    folder = LIBRARY / _safe_id(recording_id)
    path = folder / meta['video']['file']
    if not path.is_file():
        raise RecordingError('录像原文件不存在')
    return path


def evidence_dir(recording_id):
    folder = LIBRARY / _safe_id(recording_id) / 'evidence'
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def evidence_files(recording_id):
    folder = LIBRARY / _safe_id(recording_id) / 'evidence'
    if not folder.is_dir():
        return []
    return sorted(path.name for path in folder.iterdir()
                  if path.is_file() and path.suffix.lower() in ('.png', '.jpg', '.jpeg'))


def evidence_path(recording_id, name):
    name = Path(str(name or '')).name
    if not name or name != str(name):
        raise RecordingError('证据帧名称无效')
    path = LIBRARY / _safe_id(recording_id) / 'evidence' / name
    if not path.is_file():
        raise RecordingError('证据帧不存在')
    return path


def list_recordings():
    if not LIBRARY.is_dir():
        return []
    result = []
    for folder in LIBRARY.iterdir():
        if not folder.is_dir() or folder.name == '.tmp':
            continue
        try:
            meta = read_meta(folder.name)
        except RecordingError:
            continue
        result.append(public(meta))
    result.sort(key=lambda item: item.get('createdAt') or 0, reverse=True)
    return result


def delete(recording_id):
    folder = LIBRARY / _safe_id(recording_id)
    if not folder.is_dir():
        raise RecordingError('录像记录不存在')
    shutil.rmtree(folder)
    return True


def public(meta):
    value = dict(meta)
    recording_id = value.get('id')
    value['evidence'] = evidence_files(recording_id) if recording_id else []
    value['reportAvailable'] = (LIBRARY / recording_id / 'report.json').is_file() if recording_id else False
    video = dict(value.get('video') or {})
    video.pop('path', None)
    value['video'] = video
    return value


def identity(meta):
    """一段录像的身份三线索：id / 视频 sha256 / 旧流程挂载时的报告文件名。

    「已补采」判断不能只看视频 sha256：旧流程是人工导出报告 JSON 再上传挂载，
    通道里存的是报告 JSON 的 sha/name，与录屏 meta 的视频 sha 天然不同；
    只能靠文件名（视频名 stem + 报告后缀）反查回录像。
    """
    meta = meta or {}
    recording_id = str(meta.get('id') or '').strip()
    name = Path(str(meta.get('name') or '')).name.strip()
    stem = Path(name).stem if name else ''
    names = []
    if recording_id:
        # 当前前端 attachRecording 的命名。
        names.append(f'录像报告-{recording_id}.json')
    if stem:
        # 真实旧数据：20261102_27-6_录屏.mp4 → 20261102_27-6_录屏报告.json
        names.extend([f'{stem}报告.json', f'{stem}_录屏报告.json', f'{stem}.json'])
    return {'id': recording_id,
            'sha256': str(meta.get('sha256') or '').strip(),
            'names': list(dict.fromkeys(names))}


def identities(metas=None):
    """批量生成录像身份；不传 metas 时读一遍本地录像库。"""
    metas = list_recordings() if metas is None else metas
    return [identity(meta) for meta in metas]


def match_file(file_info, known=None):
    """把通道 sources.video.files 里的一条挂载记录映射回录像 id。

    三线索（任一命中）：
    - file.recordingId：新版录入时写入的显式录像 id；
    - file.sha256：视频文件摘要（新流程挂的就是 meta 的 name/size/sha256）；
    - file.name：旧流程人工导出的报告 JSON 文件名。
    名称线索只在录像库里唯一对应一段录像时采用，避免同名录屏互相误判。
    """
    if not isinstance(file_info, dict):
        return ''
    known = identities() if known is None else list(known)
    explicit = str(file_info.get('recordingId') or '').strip()
    known_ids = {item['id'] for item in known if item['id']}
    if explicit and explicit in known_ids:
        return explicit
    sha = str(file_info.get('sha256') or '').strip()
    if sha:
        for item in known:
            if item.get('sha256') and item['sha256'] == sha:
                return item['id']
    name = Path(str(file_info.get('name') or '')).name.strip()
    if name:
        matches = {item['id'] for item in known if name in (item.get('names') or [])}
        if len(matches) == 1:
            return next(iter(matches))
    return ''


def free_bytes():
    try:
        return shutil.disk_usage(LIBRARY if LIBRARY.exists() else LIBRARY.parent).free
    except OSError:
        return 0


def library_stats():
    recordings = list_recordings()
    return {
        'root': str(LIBRARY),
        'count': len(recordings),
        'bytes': sum(item.get('size') or 0 for item in recordings),
        'maxBytes': MAX_BYTES,
        'freeBytes': free_bytes(),
        'tempFiles': len(list(TEMP.glob('*'))) if TEMP.is_dir() else 0,
    }
