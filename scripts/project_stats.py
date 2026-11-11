"""生成一份可用于简历/作品集的项目数据快照（只读，不上传任何东西）。

用法：
    python scripts/project_stats.py                # 打印 Markdown 摘要
    python scripts/project_stats.py --json         # 输出 JSON
    python scripts/project_stats.py --out test-results/project-stats.json

包含：
- 版本、git 提交数、开发周期、代码行数（按语言，排除依赖/构建/缓存）
- 后端路由数、决策台 API 数、测试用例数（AST 静态统计）
- 本机真实数据覆盖（局数/回放/团战/死亡/事件；读不到就跳过）
- 客户端构建体积、安装包体积
- 公开仓库的 stars/forks/watches 与 Release 下载次数（GitHub/Gitee，公开 API）

注意：下载次数 ≠ 用户数。简历里请写「Release 下载 N 次」而不是「N 个用户」，
真实使用人数用访谈、群人数、反馈记录等可核实的材料单独说明。
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SKIP_DIRS = {
    '.git', 'node_modules', '.venv-oss', '.venv', 'dist', 'dist-gitee', 'out',
    'release', 'release-final', 'release-final2', 'build', '.cache', '.archive',
    'test-results', 'logs', 'data', 'datasets', '__pycache__', '.pytest_cache',
    'resources', 'web', 'website', 'internal', 'marketing',
}
LANG_BY_SUFFIX = {
    '.py': 'Python', '.tsx': 'TypeScript/TSX', '.ts': 'TypeScript',
    '.js': 'JavaScript', '.css': 'CSS', '.html': 'HTML', '.mjs': 'JavaScript',
    '.md': 'Markdown', '.sql': 'SQL', '.sh': 'Shell', '.bat': 'Batch',
}
SOURCE_DIRS = ('client/src', 'v3/public', 'scripts', 'tests', 'docs')
ROOT_GLOBS = ('*.py',)


def _git(*args: str) -> str:
    try:
        result = subprocess.run(['git', *args], cwd=str(ROOT), capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=30)
        return result.stdout.strip() if result.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def source_files():
    files = []
    for pattern in ROOT_GLOBS:
        files.extend(sorted(ROOT.glob(pattern)))
    for folder in SOURCE_DIRS:
        base = ROOT / folder
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*')):
            if not path.is_file() or path.suffix not in LANG_BY_SUFFIX:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            files.append(path)
    seen, result = set(), []
    for path in files:
        if path in seen:
            continue
        seen.add(path)
        result.append(path)
    return result


def code_stats():
    by_lang = Counter()
    files = Counter()
    largest = []
    for path in source_files():
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        lines = text.count('\n') + 1
        lang = LANG_BY_SUFFIX.get(path.suffix, '其他')
        by_lang[lang] += lines
        files[lang] += 1
        largest.append((lines, path.relative_to(ROOT).as_posix()))
    largest.sort(reverse=True)
    return {
        'totalLines': sum(by_lang.values()),
        'byLanguage': dict(by_lang.most_common()),
        'filesByLanguage': dict(files.most_common()),
        'largestFiles': [{'lines': n, 'path': p} for n, p in largest[:8]],
    }


def route_stats():
    pattern = re.compile(r'@\w+\.(get|post|put|delete|patch)\(', re.MULTILINE)
    by_file = Counter()
    for path in ROOT.glob('*.py'):
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        count = len(pattern.findall(text))
        if count:
            by_file[path.name] = count
    decision = 0
    try:
        sys.path.insert(0, str(ROOT))
        import decision_api  # noqa: WPS433
        decision = len(decision_api.ANALYSES) + 2  # 5 个分析 + catalog + briefing
    except Exception:
        decision = 7
    return {'routeDecorators': sum(by_file.values()),
            'byFile': dict(by_file.most_common()), 'decisionEndpoints': decision}


def test_stats():
    total, files = 0, 0
    for path in sorted((ROOT / 'tests').glob('test_*.py')):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8', errors='ignore'))
        except (OSError, SyntaxError):
            continue
        files += 1
        total += sum(1 for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name.startswith('test_'))
    return {'testFiles': files, 'testFunctions': total}


def data_stats():
    try:
        sys.path.insert(0, str(ROOT))
        import decision_facts  # noqa: WPS433
        facts = decision_facts.load_facts(ROOT / 'data' / 'official_replays',
                                          ROOT / 'data' / 'camp_details',
                                          ROOT / 'data', ROOT / 'data' / 'training.sqlite3')
        return {'coverage': facts['coverage'], 'opponents': len(facts['opponents'])}
    except Exception as error:  # pragma: no cover - 没有本机数据时跳过
        return {'available': False, 'reason': str(error)}


def build_stats():
    assets = []
    for pattern in ('client/out/renderer/assets/*.js', 'client/out/renderer/assets/*.css',
                    'client/out/renderer/assets/*.woff2'):
        for path in ROOT.glob(pattern):
            assets.append({'name': path.name, 'bytes': path.stat().st_size})
    installers = []
    for path in sorted((ROOT / 'client' / 'release').glob('*.exe')):
        stat = path.stat()
        installers.append({'name': path.name, 'bytes': stat.st_size,
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                           'mtime': datetime.fromtimestamp(stat.st_mtime).timestamp()})
    return {'rendererAssets': assets, 'installers': installers}


def _fetch_json(url: str):
    request = urllib.request.Request(url, headers={'User-Agent': 'kpl-scrim-lab-stats'})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode('utf-8'))


def public_stats():
    result = {'note': '下载次数不等于用户数，只作为传播量级参考'}
    try:
        repo = _fetch_json('https://api.github.com/repos/hccccc01333/kpl-scrim-lab-app')
        releases = _fetch_json(
            'https://api.github.com/repos/hccccc01333/kpl-scrim-lab-app/releases?per_page=100')
        downloads = sum(asset.get('download_count', 0)
                        for release in releases for asset in release.get('assets', []))
        result['github'] = {
            'stars': repo.get('stargazers_count'), 'forks': repo.get('forks_count'),
            'watchers': repo.get('subscribers_count'),
            'releases': len(releases), 'releaseDownloads': downloads,
            'createdAt': repo.get('created_at'), 'pushedAt': repo.get('pushed_at'),
        }
    except Exception as error:
        result['github'] = {'available': False, 'reason': str(error)}
    try:
        repo = _fetch_json('https://gitee.com/api/v5/repos/Rainfun42/kpl-scrim-lab-app')
        result['gitee'] = {
            'stars': repo.get('stargazers_count'), 'forks': repo.get('forks_count'),
            'watchers': repo.get('watchers_count'),
        }
    except Exception as error:
        result['gitee'] = {'available': False, 'reason': str(error)}
    return result


def git_stats():
    commits = _git('rev-list', '--count', 'HEAD')
    first = _git('log', '--reverse', '--format=%ad', '--date=short', 'HEAD')
    first = first.splitlines()[0] if first else ''
    last = _git('log', '-1', '--format=%ad', '--date=short', 'HEAD').strip()
    contributors = _git('shortlog', '-sne', 'HEAD')
    return {
        'commits': int(commits) if commits.isdigit() else None,
        'firstCommitDate': first,
        'lastCommitDate': last,
        'contributorCount': len([line for line in contributors.splitlines() if line.strip()]),
    }


def collect():
    try:
        from version import VERSION, RELEASE_DATE, RELEASE_NAME  # noqa: WPS433
        version = {'version': VERSION, 'releaseDate': RELEASE_DATE, 'name': RELEASE_NAME}
    except Exception:
        version = {}
    return {
        'generatedAt': datetime.now().isoformat(timespec='seconds'),
        'version': version,
        'git': git_stats(),
        'code': code_stats(),
        'routes': route_stats(),
        'tests': test_stats(),
        'data': data_stats(),
        'build': build_stats(),
        'public': public_stats(),
    }


def markdown(stats):
    version = stats['version']
    code = stats['code']
    docs_lines = code['byLanguage'].get('Markdown', 0)
    source_lines = code['totalLines'] - docs_lines
    tests = stats['tests']
    data = stats['data']
    build = stats['build']
    public = stats['public']
    git = stats['git']
    coverage = data.get('coverage') or {}
    gh = public.get('github') or {}
    lines = [
        f"# 项目数据快照（{stats['generatedAt']}）",
        '',
        f"- 版本：{version.get('version', '—')} · {version.get('name', '')}",
        f"- 提交：{git.get('commits', '—')} 次 · {git.get('firstCommitDate', '—')} 至 {git.get('lastCommitDate', '—')}",
        f"- 源码：{source_lines:,} 行（" +
        '、'.join(f'{lang} {n:,}' for lang, n in code['byLanguage'].items() if lang != 'Markdown') +
        f"）；文档 {docs_lines:,} 行", 
        f"- 后端路由：{stats['routes']['routeDecorators']} 个 · 决策台 API {stats['routes']['decisionEndpoints']} 个",
        f"- 测试：{tests['testFiles']} 个测试文件 / {tests['testFunctions']} 个测试函数",
    ]
    if coverage:
        lines.append(
            f"- 真实数据：{coverage.get('games', '—')} 局回放 / {coverage.get('panelGames', '—')} 局面板 / "
            f"{coverage.get('fights', '—')} 场团战 / {coverage.get('deaths', '—')} 次死亡 / "
            f"{coverage.get('events', '—')} 条事件")
    for asset in build['rendererAssets']:
        if asset['name'].endswith('.js'):
            lines.append(f"- 客户端渲染包：{asset['bytes'] / 1024 / 1024:.2f} MB（{asset['name']}）")
            break
    if build['installers']:
        installer = max(build['installers'], key=lambda item: item['bytes'])
        stamp = datetime.fromtimestamp(installer['mtime']).isoformat(timespec='minutes')
        lines.append(f"- 安装包：{installer['name']} · {installer['bytes'] / 1024 / 1024:.1f} MB · "
                     f"{stamp} · SHA256 {installer['sha256'][:16]}…")
    if gh.get('stars') is not None:
        lines.append(f"- GitHub：Star {gh.get('stars')} · Fork {gh.get('forks')} · "
                     f"Release 下载 {gh.get('releaseDownloads')} 次（≠用户数）")
    gitee = public.get('gitee') or {}
    if gitee.get('stars') is not None:
        lines.append(f"- Gitee：Star {gitee.get('stars')} · Fork {gitee.get('forks')} · Watch {gitee.get('watchers')}")
    lines += ['', '> 用法提醒：简历里写可核实的工程指标（代码/测试/性能/数据覆盖）与真实用户证据；'
                  '不要把 Release 下载次数直接写成用户数。']
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--out', default='')
    args = parser.parse_args()
    stats = collect()
    output = json.dumps(stats, ensure_ascii=False, indent=2) if args.json else markdown(stats)
    print(output)
    if args.out:
        target = ROOT / args.out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding='utf-8')
        print(f'\n已写入 {target.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
