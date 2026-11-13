"""共享 pytest 配置：让 tests/ 下的 helper（facts_fixtures）可直接 import。"""
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
