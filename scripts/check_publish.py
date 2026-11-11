"""开源发布前的自检：哪些文件不该出现在公开仓库。

用法：
    python scripts/check_publish.py            # 只查路径与疑似个人信息
    python scripts/check_publish.py --strict   # 额外查正文里的邮箱

退出码：0 = 可以推；1 = 有必须处理的问题。
规则来源与原因见 PUBLISHING.md。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 永远不进入公开仓库的路径前缀（相对仓库根）
BANNED_PREFIXES = (
    '内部资料/',
    'marketing/',
    'datasets/',
    'docs/afdian/',
    'web/refsite/',
    'resources/icons/',
    'data/',
    'logs/',
    'dist/',
    'packaging/dist/',
)

BANNED_FILES = (
    '_qr.json',
    '_pid.txt',
    '_server_run.log',
    '_rewrite_research.py',
)

BANNED_SUFFIXES = (
    '.sqlite3', '.sqlite3-wal', '.sqlite3-shm', '.db',
    '.abc', '.ope', '.log',
)

# 营地面板截图等：路径含这些目录的图片不允许跟踪
BANNED_IMAGE_DIRS = ('web/capture-guide/',)

TEXT_SUFFIXES = ('.md', '.py', '.js', '.ts', '.tsx', '.json', '.txt', '.yml', '.yaml',
                 '.html', '.css', '.toml', '.cfg', '.ini', '.ps1', '.bat', '.sh')

# 本机路径 / 用户名 / 外部项目引用的模式：命中就报
PERSONAL_PATTERNS = (
    (re.compile(r'[A-Za-z]:\\Users\\[^\\\s"\']+'), '本机用户目录路径'),
    (re.compile(r'[A-Za-z]:/Users/[^/\s"\']+'), '本机用户目录路径'),
    (re.compile(r'\bHzz\b'), '本机用户名'),
    (re.compile(r'AI数据分析|KPLBPagentRL|kpl-insight|KPL赛研|kpl-data-center'), '外部项目引用'),
)

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
# 这些文件里的邮箱是公开联系方式或第三方元数据，允许存在
EMAIL_ALLOW = {
    'LICENSE', 'NOTICE', 'LICENSING.md', 'README.md', 'CONTRIBUTING.md', 'SECURITY.md',
    'scripts/make_release.py', 'client/package-lock.json',
    'packaging/ChineseSimplified.isl',
    'LICENSES/PolyForm-Noncommercial-1.0.0.txt',
}
# 自检脚本自身含有规则文本，正文扫描跳过它
TEXT_SCAN_SKIP = {'scripts/check_publish.py'}


def tracked_files() -> list[str]:
    out = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, capture_output=True)
    if out.returncode != 0:
        print('不是 git 仓库或 git 不可用', file=sys.stderr)
        sys.exit(2)
    return [p.decode('utf-8', 'replace') for p in out.stdout.split(b'\0') if p]


def path_problem(path: str) -> str | None:
    if path in BANNED_FILES:
        return '禁止文件'
    if any(path.startswith(prefix) for prefix in BANNED_PREFIXES):
        return '禁止目录'
    if path.lower().endswith(BANNED_SUFFIXES):
        return '禁止后缀'
    if path.lower().endswith(('.jpg', '.jpeg', '.png')) and path.startswith(BANNED_IMAGE_DIRS):
        return '营地截图（可能含真实昵称）'
    return None


def scan_text(path: str) -> list[tuple[str, int, str]]:
    issues = []
    try:
        text = (ROOT / path).read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return issues
    for lineno, line in enumerate(text.splitlines(), 1):
        for pattern, label in PERSONAL_PATTERNS:
            if pattern.search(line):
                issues.append((label, lineno, line.strip()[:120]))
                break
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict', action='store_true', help='额外检查正文中的邮箱')
    args = parser.parse_args()

    files = tracked_files()
    problems: list[str] = []

    for path in files:
        reason = path_problem(path)
        if reason:
            problems.append(f'[路径] {path} —— {reason}')

    for path in files:
        if not path.lower().endswith(TEXT_SUFFIXES) or path in TEXT_SCAN_SKIP:
            continue
        for label, lineno, snippet in scan_text(path):
            problems.append(f'[{label}] {path}:{lineno}  {snippet}')

    if args.strict:
        for path in files:
            if not path.lower().endswith(TEXT_SUFFIXES) or path in EMAIL_ALLOW or path in TEXT_SCAN_SKIP:
                continue
            try:
                text = (ROOT / path).read_text(encoding='utf-8', errors='ignore')
            except OSError:
                continue
            for match in EMAIL_RE.finditer(text):
                problems.append(f'[邮箱] {path}  {match.group(0)}')

    print(f'已跟踪文件：{len(files)}')
    if not problems:
        print('通过：没有发现不该公开的路径或个人信息。')
        return 0

    print(f'发现 {len(problems)} 处需要处理：')
    for item in problems[:80]:
        print('  -', item)
    if len(problems) > 80:
        print(f'  …… 其余 {len(problems) - 80} 处省略')
    print('\n处理方式见 PUBLISHING.md（取消跟踪 / 改成本地路径 / 加白名单）。')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
