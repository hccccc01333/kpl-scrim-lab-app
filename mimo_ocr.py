"""Local Xiaomi-OCR-0 (mimo-ocr-0) wrapper.

The model is a 0.8B vision-language OCR checkpoint.  On this workstation it is
used as the high-accuracy refinement pass: the fast layout engine still reads
the HUD every frame, while Mimo reads whole post-game pages or targeted key
frames.  Loading is lazy, inference is serialized, and results are cached by
image bytes + prompt so re-opening a page does not repeat a multi-minute run.

No network calls are made here: the checkpoint is resolved from a local
directory or the Hugging Face cache.
"""
import ast
import hashlib
import importlib.util
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

from PIL import Image

from paths import data_root

ROOT = Path(__file__).resolve().parent
ENGINE = 'mimo-ocr-0'
MODEL_REPO = 'SeerRay-Lab/Xiaomi-OCR-0'
CACHE_ROOT = Path(os.environ.get('MIMO_OCR_CACHE', data_root() / 'ocr_cache'))
CACHE_DIR = CACHE_ROOT / 'mimo'
DEFAULT_MAX_TOKENS = 768


class MimoUnavailable(RuntimeError):
    """The local checkpoint or its runtime dependencies are not available."""


def _hf_hub_roots():
    roots = []
    for key in ('HUGGINGFACE_HUB_CACHE', 'HF_HUB_CACHE'):
        value = os.environ.get(key)
        if value:
            roots.append(Path(value).expanduser())
    hf_home = os.environ.get('HF_HOME')
    if hf_home:
        roots.append(Path(hf_home).expanduser() / 'hub')
    roots.append(Path.home() / '.cache' / 'huggingface' / 'hub')
    return roots


def model_path():
    """Return the local snapshot directory, or None when the model is absent."""
    override = os.environ.get('MIMO_OCR_MODEL')
    if override:
        path = Path(override).expanduser()
        if (path / 'config.json').is_file() and (path / 'model.safetensors').is_file():
            return path.resolve()
        return None
    direct = ROOT / 'models' / 'Xiaomi-OCR-0'
    if (direct / 'config.json').is_file() and (direct / 'model.safetensors').is_file():
        return direct.resolve()
    candidates = []
    for root in _hf_hub_roots():
        pattern = root / 'models--SeerRay-Lab--Xiaomi-OCR-0' / 'snapshots' / '*' / 'config.json'
        for config in pattern.parent.parent.glob('*/config.json'):
            folder = config.parent
            if (folder / 'model.safetensors').is_file():
                candidates.append(folder)
    if not candidates:
        return None
    candidates.sort(key=lambda folder: (folder / 'model.safetensors').stat().st_mtime)
    return candidates[-1].resolve()


def _fingerprint(path):
    weights = path / 'model.safetensors'
    stat = weights.stat()
    return f'{path.name}:{stat.st_size}:{int(stat.st_mtime)}'


def _guess_device():
    if importlib.util.find_spec('torch') is None:
        return 'unavailable'
    try:
        import torch
        return 'cuda' if torch.cuda.is_available() else 'cpu'
    except Exception:
        return 'unavailable'


def status():
    """Cheap status for the workbench; does not load the checkpoint."""
    path = model_path()
    loaded = _engine is not None and _engine.loaded
    return {
        'engine': ENGINE,
        'repo': MODEL_REPO,
        'available': bool(path),
        'path': str(path) if path else None,
        'loaded': bool(loaded),
        'device': _engine.device if loaded else _guess_device(),
        'dtype': str(_engine.dtype).replace('torch.', '') if loaded else None,
        'torch': importlib.util.find_spec('torch') is not None,
        'transformers': importlib.util.find_spec('transformers') is not None,
        'cacheDir': str(CACHE_DIR),
        'cacheFiles': _cache_count(),
        'note': '本地模型；不访问云端。首次精读需加载权重，CPU 上整页约 2–3 分钟。',
    }


def _cache_count():
    try:
        return sum(1 for _ in CACHE_DIR.glob('*.json'))
    except OSError:
        return 0


def clear_cache():
    removed = 0
    for path in CACHE_DIR.glob('*.json'):
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def _clean_text(value):
    if value is None:
        return None
    text = str(value).strip().strip('"').strip("'")
    text = re.sub(r'[\u200b-\u200f\u2060\ufeff]', '', text)
    return text.strip() or None


def _repair_json(text):
    text = text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")
    text = re.sub(r',\s*([}\]])', r'\1', text)
    text = re.sub(r'(?m)^\s*//.*$', '', text)
    return text


def parse_json(text):
    """Best-effort JSON extraction from a VLM response.

    Returns ``(value, error)``.  ``value`` is None when no object could be
    parsed; the raw text is always kept by the caller for audit.
    """
    if not text:
        return None, 'empty output'
    cleaned = re.sub(r'<think>.*?</think>', '', str(text), flags=re.S)
    cleaned = re.sub(r'```(?:json)?\s*(\{.*?\})\s*```', r'\1', cleaned, flags=re.S)
    start, end = cleaned.find('{'), cleaned.rfind('}')
    if start < 0 or end <= start:
        return None, 'no JSON object'
    body = cleaned[start:end + 1]
    for candidate in (body, _repair_json(body)):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value, None
        except (TypeError, ValueError):
            pass
    try:
        value = ast.literal_eval(body)
        if isinstance(value, dict):
            return value, None
    except (ValueError, SyntaxError):
        pass
    return None, 'invalid JSON'


def clean_number(value, kind='big'):
    """Normalize an OCR/VLM number.  ``kind`` is big/int/percent/ratio."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = str(value).strip().replace(',', '').replace('，', '')
        text = text.replace('>', '').replace('约', '').replace(' ', '')
        if not text or text in ('-', '—', 'null', 'None', 'N/A', '无'):
            return None
        if kind in ('percent', 'ratio'):
            text = text.replace('%', '')
        match = re.fullmatch(r'(\d+(?:\.\d+)?)([kK万wW亿])?', text)
        if not match:
            return None
        number = float(match.group(1))
        suffix = (match.group(2) or '').lower()
        if suffix == 'k':
            number *= 1000
        elif suffix in ('万', 'w'):
            number *= 10000
        elif suffix == '亿':
            number *= 100000000
    if number < 0:
        return None
    if kind == 'int':
        return int(round(number))
    if kind == 'percent':
        return round(number, 1)
    if kind == 'ratio':
        return round(number, 2)
    return int(round(number))


def _image_digest(image):
    digest = hashlib.sha256()
    digest.update(f'{image.width}x{image.height}:{image.mode}:'.encode())
    digest.update(image.tobytes())
    return digest.hexdigest()


class MimoEngine:
    def __init__(self):
        self._lock = threading.RLock()
        self._model = None
        self._processor = None
        self.device = None
        self.dtype = None
        self.load_seconds = None
        self._error = None
        self._fingerprint = None

    @property
    def loaded(self):
        return self._model is not None

    def load(self):
        with self._lock:
            if self._model is not None:
                return self
            if self._error:
                raise MimoUnavailable(self._error)
            path = model_path()
            if not path:
                self._error = ('未找到本地 Xiaomi-OCR-0；请设置 MIMO_OCR_MODEL 或把模型放到 '
                               'models/Xiaomi-OCR-0。')
                raise MimoUnavailable(self._error)
            if importlib.util.find_spec('torch') is None or importlib.util.find_spec('transformers') is None:
                self._error = '缺少 torch / transformers；请运行 安装依赖.bat'
                raise MimoUnavailable(self._error)
            try:
                import torch
                from transformers import AutoModelForImageTextToText, AutoProcessor
            except Exception as error:  # pragma: no cover - depends on the local runtime
                self._error = f'无法导入 Mimo 运行库：{type(error).__name__}'
                raise MimoUnavailable(self._error) from error
            os.environ.setdefault('HF_HUB_OFFLINE', '1')
            os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
            started = time.time()
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            dtype = torch.float16 if device == 'cuda' else torch.float32
            if device == 'cpu':
                try:
                    torch.set_num_threads(int(os.environ.get(
                        'MIMO_OCR_THREADS', min(8, os.cpu_count() or 4))))
                except (TypeError, ValueError, RuntimeError):
                    pass
            try:
                processor = AutoProcessor.from_pretrained(str(path), local_files_only=True)
                try:
                    model = AutoModelForImageTextToText.from_pretrained(
                        str(path), dtype=dtype, local_files_only=True)
                except TypeError:
                    model = AutoModelForImageTextToText.from_pretrained(
                        str(path), torch_dtype=dtype, local_files_only=True)
                model = model.to(device).eval()
            except Exception as error:  # pragma: no cover - depends on the local runtime
                self._error = f'加载 Mimo 失败：{type(error).__name__}: {error}'
                raise MimoUnavailable(self._error) from error
            self._processor = processor
            self._model = model
            self.device = device
            self.dtype = dtype
            self.load_seconds = round(time.time() - started, 2)
            self._fingerprint = _fingerprint(path)
            return self

    def read(self, image, prompt, max_new_tokens=DEFAULT_MAX_TOKENS, cache=True,
             cache_tag='', on_stage=None):
        """Run one OCR prompt on a PIL image and return text plus timing.

        The caller owns the image.  Results are cached on disk under
        ``data/ocr_cache/mimo`` by model fingerprint, prompt and pixels.
        """
        if not isinstance(image, Image.Image):
            raise TypeError('image 必须是 PIL.Image')
        image = image.convert('RGB')
        if on_stage:
            on_stage('正在加载 Mimo 模型…' if not self.loaded else '正在读取画面…')
        path = model_path()
        if not path:
            raise MimoUnavailable('未找到本地 Xiaomi-OCR-0 模型')
        fingerprint = _fingerprint(path)
        key = hashlib.sha256(
            f'{fingerprint}|{prompt}|{max_new_tokens}|{cache_tag}|{_image_digest(image)}'
            .encode('utf-8')).hexdigest()
        cache_path = CACHE_DIR / f'{key}.json'
        if cache:
            cached = _read_cache(cache_path)
            if cached is not None:
                cached['cached'] = True
                cached['elapsedMs'] = 0
                return cached
        with self._lock:
            self.load()
            if on_stage:
                on_stage('正在生成 Mimo 结果…')
            started = time.time()
            text = self._generate(image, prompt, max_new_tokens)
            elapsed_ms = int((time.time() - started) * 1000)
        result = {
            'engine': ENGINE,
            'model': MODEL_REPO,
            'device': self.device,
            'text': text,
            'elapsedMs': elapsed_ms,
            'tokens': None,
            'cached': False,
        }
        if cache:
            _write_cache(cache_path, result)
        return result

    def read_json(self, image, prompt, max_new_tokens=DEFAULT_MAX_TOKENS, cache=True,
                  cache_tag='', on_stage=None):
        result = self.read(image, prompt, max_new_tokens=max_new_tokens, cache=cache,
                           cache_tag=cache_tag, on_stage=on_stage)
        parsed, error = parse_json(result['text'])
        result['json'] = parsed
        result['jsonError'] = error
        if parsed is None and error:
            result['error'] = f'Mimo 输出不是有效 JSON：{error}'
        return result

    def _generate(self, image, prompt, max_new_tokens):
        import torch

        temp_dir = CACHE_DIR / 'tmp'
        temp_dir.mkdir(parents=True, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(suffix='.png', dir=str(temp_dir))
        os.close(handle)
        try:
            image.save(temp_path, format='PNG')
            messages = [{
                'role': 'user',
                'content': [
                    {'type': 'image', 'url': temp_path},
                    {'type': 'text', 'text': prompt},
                ],
            }]
            try:
                inputs = self._processor.apply_chat_template(
                    messages, tokenize=True, add_generation_prompt=True,
                    return_dict=True, return_tensors='pt', enable_thinking=False)
            except TypeError:
                inputs = self._processor.apply_chat_template(
                    messages, tokenize=True, add_generation_prompt=True,
                    return_dict=True, return_tensors='pt')
            inputs = _to_device(inputs, self.device, self.dtype, torch)
            with torch.inference_mode():
                output = self._model.generate(
                    **inputs, max_new_tokens=max_new_tokens, do_sample=False, use_cache=True)
            new_tokens = output[:, inputs['input_ids'].shape[1]:]
            text = self._processor.batch_decode(new_tokens, skip_special_tokens=True)[0]
            return text.strip()
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def _to_device(inputs, device, dtype, torch):
    result = {}
    for key, value in inputs.items():
        if hasattr(value, 'to'):
            if key in ('input_ids', 'attention_mask'):
                value = value.to(device)
            elif getattr(value, 'is_floating_point', lambda: False)():
                value = value.to(device=device, dtype=dtype)
            else:
                value = value.to(device)
        result[key] = value
    return result


def _read_cache(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not value.get('text'):
        return None
    return value


def _write_cache(path, value):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)
    except OSError:
        pass


_engine = None
_engine_lock = threading.Lock()


def get_engine():
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = MimoEngine()
        return _engine


def is_loaded():
    return _engine is not None and _engine.loaded
