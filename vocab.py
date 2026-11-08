"""赛训词表：版本 / 规则 / 赛制（附训练组建议值）。

为什么收口：`version` 已经是「版本对比」以及对局筛选的分组键，`rules` 会被写进
训练赛排期与预填确认。同一个东西手写成 `S40` / `s40` / `S40赛季`，分组就会裂开。

设计约定：
- 词表存在 `<data>/vocab.json`，是唯一事实来源；前端表单、预填确认、赛训排期、
  单局补录都走这里的 `prepare()`，不再各写各的。
- 归一化 = NFKC（全角转半角）+ 去空白 + 大小写 + 别名映射，例如
  `S40赛季 → S40`、`kpl全局bp → 全局BP（KPL）`、`bo3 → BO3`。
- 不在词表里的值默认**收下并登记**（教练在局间填表，不能被 400 拦住），下次
  自动成为选项；需要合并历史脏数据时跑 `scripts/vocab_report.py`（默认只出报告）。
"""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from pathlib import Path

# 词表种类；sessions 是「可增长的名词」，只做去空白，不做别名。
KINDS = ('versions', 'rules', 'formats', 'sessions')
# 业务字段 → 词表种类；单局补录与预填确认都按这张表归一化。
FIELD_KINDS = {'version': 'versions', 'rules': 'rules', 'format': 'formats', 'session': 'sessions'}

DEFAULTS = {
    'versions': ['S42', 'S41', 'S40', 'S39', 'S38'],
    'rules': ['全局BP（KPL）', '常规BP', '盲选', '巅峰对决', '其他'],
    'formats': ['BO7', 'BO5', 'BO3', 'BO1'],
    'sessions': [],
}

VOCAB_FILE = 'vocab.json'
_LOCK = threading.Lock()


def _clean(value) -> str:
    """全角转半角 + 收掉首尾与连续空白；中文内部的间距不动。"""
    text = unicodedata.normalize('NFKC', str(value if value is not None else ''))
    return re.sub(r'\s+', ' ', text).strip()


def _canonical_version(value: str) -> str:
    text = _clean(value).replace(' ', '')
    if not text:
        return ''
    text = re.sub(r'^(?:版本|赛季)', '', text)
    text = re.sub(r'(?:赛季|版本)$', '', text)
    text = text.upper()
    text = re.sub(r'^V(?=\d)', '', text)
    hit = re.fullmatch(r'S?(\d{1,2})', text)
    if hit:
        return 'S' + str(int(hit.group(1)))
    if re.fullmatch(r'\d+(?:\.\d+)*', text):
        return text
    return text


_RULE_ALIASES = {
    '全局bp': '全局BP（KPL）',
    'kpl全局bp': '全局BP（KPL）',
    '全局bp（kpl）': '全局BP（KPL）',
    '全局bp(kpl)': '全局BP（KPL）',
    'kpl全局bp（kpl）': '全局BP（KPL）',
    'kpl规则': '全局BP（KPL）',
    'kpl': '全局BP（KPL）',
    '常规bp': '常规BP',
    '常规征召': '常规BP',
    '征召': '常规BP',
    '盲选模式': '盲选',
    '盲选': '盲选',
    '巅峰对决': '巅峰对决',
    '其他': '其他',
}


def _canonical_rule(value: str) -> str:
    text = _clean(value).replace(' ', '')
    if not text:
        return ''
    hit = _RULE_ALIASES.get(text.lower())
    if hit:
        return hit
    return re.sub(r'bp', 'BP', text, flags=re.IGNORECASE)


def _canonical_format(value: str) -> str:
    text = _clean(value).upper().replace(' ', '')
    if not text:
        return ''
    hit = re.fullmatch(r'BO?(\d)', text) or re.fullmatch(r'BESTOF(\d+)', text) or re.fullmatch(r'(\d)局', text)
    if hit:
        return 'BO' + hit.group(1)
    return text


def normalize(kind: str, value, *, add: bool = False, data_dir=None) -> str:
    """把用户输入折成词表写法；add=True 时登记到 data_dir 的词表。

    空值返回 ''（调用方自己决定存不存）；未知值在 add=False 时原样返回，
    方便迁移脚本先出报告再决定是否收编。
    """
    if kind not in KINDS:
        raise ValueError(f'未知词表种类：{kind}')
    text = _clean(value)
    if not text or text == '__custom__':
        return ''
    if kind == 'versions':
        canonical = _canonical_version(text)
    elif kind == 'rules':
        canonical = _canonical_rule(text)
    elif kind == 'formats':
        canonical = _canonical_format(text)
    else:
        canonical = text
    if add and data_dir is not None and canonical:
        register(kind, canonical, data_dir)
    return canonical


def prepare(kind: str, value, data_dir) -> str:
    """写入路径使用的入口：归一化并登记，空值保持空。"""
    return normalize(kind, value, add=True, data_dir=data_dir)


def vocab_path(data_dir) -> Path:
    return Path(data_dir) / VOCAB_FILE


def load(data_dir) -> dict:
    """读词表；文件里没有的种类回落到默认值，文件里有就以文件为准。"""
    result = {kind: list(DEFAULTS[kind]) for kind in KINDS}
    path = vocab_path(data_dir)
    body = {}
    try:
        body = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        body = {}
    if isinstance(body, dict):
        for kind in KINDS:
            values = body.get(kind)
            if isinstance(values, list):
                result[kind] = _dedupe(str(item) for item in values if str(item).strip())
    return {kind: sort_values(kind, result[kind]) for kind in KINDS}


def save(data_dir, values: dict) -> None:
    payload = {kind: _dedupe(str(item) for item in (values.get(kind) or [])) for kind in KINDS}
    path = vocab_path(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except OSError:
        # 词表写不进去不能挡住保存动作：内存里本次仍按规范值写入。
        pass


def register(kind: str, value, data_dir) -> str:
    """把一个规范值并入词表；已存在则不重复写盘。

    注意：这里不能再做 NFKC / 别名归一化 —— 传进来的是 normalize() 的产物，
    再折一次会把全角括号（KPL）折成半角，词表里出现两个「看起来一样」的值。
    """
    canonical = str(value if value is not None else '').strip()
    if not canonical or data_dir is None:
        return canonical
    with _LOCK:
        current = load(data_dir)
        values = list(current.get(kind) or [])
        if canonical in values:
            return canonical
        values.append(canonical)
        current[kind] = values
        save(data_dir, current)
    return canonical


def _dedupe(values) -> list:
    seen, out = set(), []
    for item in values:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _version_key(value) -> tuple:
    """统一成可比较的三元组：赛季号 > 补丁号 > 其它文本。"""
    text = _clean(value).upper()
    hit = re.fullmatch(r'S(\d+)', text)
    if hit:
        return (2, (int(hit.group(1)),), '')
    numbers = re.findall(r'\d+', text)
    if numbers:
        return (1, tuple(int(item) for item in numbers), '')
    return (0, (), text)


def sort_values(kind: str, values) -> list:
    """统一排序：版本按数字倒序（新的在前），训练组按中文，其余保持声明顺序。"""
    items = _dedupe(str(item) for item in values if str(item).strip())
    if kind == 'versions':
        return sorted(items, key=_version_key, reverse=True)
    if kind == 'sessions':
        return sorted(items, key=lambda item: item)
    return items


def merge(*lists) -> list:
    return _dedupe(str(item) for group in lists for item in (group or []) if str(item).strip())
