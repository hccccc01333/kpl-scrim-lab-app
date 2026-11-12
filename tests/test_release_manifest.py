"""发布清单必须包含运行期真正 import 的 tools/ 模块。

server.py 的 ``_camp_tools()`` 会把 ``tools/`` 插进 sys.path 再 import 营地同步模块；
``replay_timeline_build._catalog()`` 懒加载出装时间轴依赖。历史上这整批文件没进
``ship_files()``，安装版一进采集页就 500（ModuleNotFoundError: camp_sync）。

这里用 **AST 静态求 import 闭包**，而不是运行期 ``sys.modules`` 前后快照：
全量 discover 时别的用例会先 import 掉这些模块，快照法拿到的是空集，会假失败。
"""
import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from make_release import ship_files  # noqa: E402

TOOLS_DIR = ROOT / 'tools'
# 会 import tools/ 模块的两个运行期入口文件。
ENTRY_FILES = ('server.py', 'replay_timeline_build.py')


def _available_tools():
    """tools/ 下所有可 import 的模块名。"""
    return {p.stem for p in TOOLS_DIR.glob('*.py') if p.name != '__init__.py'}


def _local_imports(tree, available):
    """收集一个 AST 里所有指向 tools/ 内模块的 import 名。

    兼容三种写法：``import camp_sync``、``from camp_client import x``、
    ``from tools.replay_frame_commands import x``（安装源以 ROOT 为 sys.path）。
    """
    names = set()

    def take(raw):
        parts = raw.split('.')
        cand = parts[1] if parts[0] == 'tools' and len(parts) > 1 else parts[0]
        if cand in available:
            names.add(cand)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                take(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == 'tools':
                for alias in node.names:
                    take(alias.name)
            else:
                take(node.module)
    return names


def _parse(path):
    return ast.parse(path.read_text(encoding='utf-8'), filename=str(path))


def _closure():
    """从入口文件出发，沿 tools/ 内 import 递归展开，得到必须随包发布的相对路径集合。"""
    available = _available_tools()
    seeds = set()
    for name in ENTRY_FILES:
        seeds |= _local_imports(_parse(ROOT / name), available)

    seen = set()
    pending = list(seeds)
    while pending:
        mod = pending.pop()
        if mod in seen:
            continue
        seen.add(mod)
        pending.extend(_local_imports(_parse(TOOLS_DIR / f'{mod}.py'), available) - seen)
    return {f'tools/{m}.py' for m in seen}


class ReleaseManifestTests(unittest.TestCase):
    def test_runtime_tool_modules_are_shipped(self):
        needed = _closure()
        self.assertIn('tools/camp_sync.py', needed, '入口模块没被 AST 解析到')
        self.assertGreaterEqual(len(needed), 8, sorted(needed))
        shipped = set(ship_files())
        for relative in sorted(needed):
            with self.subTest(module=relative):
                self.assertIn(relative, shipped)

    def test_core_entries_are_shipped(self):
        shipped = set(ship_files())
        for name in ('server.py', 'launcher.py', 'paths.py', 'version.py',
                     'v3/serve.py', 'v3/public/app.js', 'v3/public/index.html'):
            with self.subTest(entry=name):
                self.assertIn(name, shipped)

    def test_tools_directory_is_not_shipped_wholesale(self):
        """研究脚本不进安装包：只发运行期依赖的那几个。"""
        shipped = {name for name in ship_files() if name.startswith('tools/')}
        self.assertLessEqual(len(shipped), 12, sorted(shipped))
        self.assertFalse(any('agent_' in name for name in shipped), sorted(shipped))

    def test_shell_referenced_assets_are_shipped(self):
        """index.html 引用的资源必须都在清单里，否则安装版直接 404。

        server.py 把 ``/static`` 挂到 ``v3/public`` 目录本身，所以外壳里的
        ``static/app.js`` 对应发布路径 ``v3/public/app.js``。
        godmode.js 这类「先不随包」的文件一旦被重新引回外壳却忘了从
        NEVER_SHIP 删掉，这条会拦住。
        """
        import re
        shipped = set(ship_files())
        html = (ROOT / 'v3' / 'public' / 'index.html').read_text(encoding='utf-8-sig')
        refs = re.findall(r'(?:src|href)="static/([^"?#]+)', html)
        self.assertTrue(refs, '外壳里没解析到任何 static 引用')
        for ref in refs:
            with self.subTest(asset=ref):
                self.assertIn(f'v3/public/{ref}', shipped)

    def test_never_ship_files_stay_out(self):
        from make_release import NEVER_SHIP
        shipped = set(ship_files())
        for name in sorted(NEVER_SHIP):
            with self.subTest(file=name):
                self.assertNotIn(name, shipped)


if __name__ == '__main__':
    unittest.main()
