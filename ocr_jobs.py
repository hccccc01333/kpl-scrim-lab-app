"""Small in-process job queue for long OCR runs.

Mimo whole-page OCR takes minutes on CPU and video OCR takes minutes as well.
Both run in one background worker so the HTTP request returns immediately and
the workbench can poll progress.  Jobs are intentionally in-memory: a restart
marks unfinished work as interrupted rather than pretending it completed.
"""
import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger('kpl.ocr_jobs')

_LOCK = threading.RLock()
_JOBS = {}
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ocr-job')
_MAX_JOBS = 80


class JobCancelled(RuntimeError):
    """Raised by a runner when the user cancels a queued/running job."""


class Job:
    def __init__(self, data):
        self._data = data

    @property
    def id(self):
        return self._data['id']

    @property
    def kind(self):
        return self._data['kind']

    @property
    def target_id(self):
        return self._data['targetId']

    def update(self, **fields):
        with _LOCK:
            self._data.update(fields)
        return self

    def stage(self, stage, progress=None, message=None):
        fields = {'stage': stage}
        if progress is not None:
            fields['progress'] = max(0, min(100, int(progress)))
        if message is not None:
            fields['message'] = str(message)
        return self.update(**fields)

    def cancelled(self):
        with _LOCK:
            return bool(self._data.get('cancelRequested'))

    def check_cancelled(self):
        if self.cancelled():
            raise JobCancelled('用户已取消任务')

    def meta(self):
        with _LOCK:
            return dict(self._data.get('meta') or {})


def submit(kind, target_id, runner, meta=None):
    """Queue ``runner(job)`` and return the public job record."""
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    data = {
        'id': job_id, 'kind': kind, 'targetId': target_id,
        'status': 'queued', 'stage': '排队中', 'progress': 0, 'message': '',
        'createdAt': now, 'startedAt': None, 'finishedAt': None,
        'cancelRequested': False, 'error': None, 'result': None,
        'meta': dict(meta or {}),
    }
    with _LOCK:
        _JOBS[job_id] = data
        _prune()
    _EXECUTOR.submit(_run, job_id, runner)
    return public(data)


def _run(job_id, runner):
    with _LOCK:
        data = _JOBS.get(job_id)
        if not data:
            return
        if data['cancelRequested']:
            data.update(status='cancelled', stage='已取消', finishedAt=time.time())
            return
        data.update(status='running', stage='正在启动…', startedAt=time.time())
    job = Job(data)
    try:
        result = runner(job)
        job.update(status='done', stage='完成', progress=100,
                   finishedAt=time.time(), result=result)
    except JobCancelled as error:
        job.update(status='cancelled', stage='已取消', message=str(error),
                   finishedAt=time.time())
    except Exception as error:  # noqa: BLE001 - job boundary must not kill the worker
        log.error('OCR job %s failed:\n%s', job_id, traceback.format_exc())
        job.update(status='error', stage='失败', finishedAt=time.time(),
                   error=f'{type(error).__name__}: {error}')
    finally:
        with _LOCK:
            _prune()


def _prune():
    if len(_JOBS) <= _MAX_JOBS:
        return
    finished = sorted(
        ((job['finishedAt'] or job['createdAt'], job_id) for job_id, job in _JOBS.items()
         if job['status'] in ('done', 'error', 'cancelled')),
    )
    for _, job_id in finished[:len(_JOBS) - _MAX_JOBS]:
        _JOBS.pop(job_id, None)


def public(data):
    with _LOCK:
        return {key: value for key, value in data.items() if key != 'cancelRequested'}


def get(job_id):
    with _LOCK:
        data = _JOBS.get(job_id)
        return public(data) if data else None


def list_jobs(kind=None, target_id=None, limit=50):
    with _LOCK:
        data = [dict(job) for job in _JOBS.values()]
    if kind:
        data = [job for job in data if job['kind'] == kind]
    if target_id:
        data = [job for job in data if job['targetId'] == target_id]
    data.sort(key=lambda job: job['createdAt'], reverse=True)
    return [public(job) for job in data[:limit]]


def find_active(kind, target_id):
    with _LOCK:
        for job in _JOBS.values():
            if job['kind'] == kind and job['targetId'] == target_id and \
                    job['status'] in ('queued', 'running'):
                return public(job)
    return None


def cancel(job_id):
    with _LOCK:
        data = _JOBS.get(job_id)
        if not data:
            return None
        if data['status'] in ('queued', 'running'):
            data['cancelRequested'] = True
            data['stage'] = '正在取消…'
        return public(data)


def active_count():
    with _LOCK:
        return sum(1 for job in _JOBS.values() if job['status'] in ('queued', 'running'))
