# 100 局语料基准压测（工程健康项，按需运行）
# 用法：python scripts/bench_corpus_100.py
# 生成 100 个最小对局包到隔离目录，测 AnalysisRepository 冷加载 + 全量向量构建时间。
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix='kpl-bench-'))
matches_dir = tmp / 'matches'
matches_dir.mkdir(parents=True, exist_ok=True)

for index in range(100):
    players = []
    for camp in ('blue', 'red'):
        for slot in range(5):
            players.append({
                'key': f'{camp}-{slot}', 'camp': camp, 'slot': slot,
                'hero': f'英雄{index}-{camp}{slot}',
                'nickname': f'选手{camp}{slot}',
                'final': {'kills': 3, 'deaths': 2, 'assists': 5,
                          'totalGold': 10000 + slot * 500, 'damage': 20000,
                          'participation': 55, 'complete': True},
                'process': {}, 'sources': [],
            })
    body = {
        'schema': 'kpl-match-data-v1',
        'match': {'key': f'bench-{index:03d}', 'title': f'压测局 {index}',
                  'mode': '峡谷—快速赛', 'date': {'text': f'2026-11-{(index % 28) + 1:02d}'},
                  'duration': 1200 + index, 'scores': {}, 'identity': {}},
        'pov': {'camp': 'blue'},
        'sources': [],
        'players': players,
        'warnings': [],
    }
    (matches_dir / f'bench-{index:03d}.json').write_text(
        json.dumps(body, ensure_ascii=False), encoding='utf-8')

from analysis_data import AnalysisRepository  # noqa: E402

db = tmp / 'training.sqlite3'
import sqlite3
connection = sqlite3.connect(db)
connection.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
connection.execute("INSERT OR IGNORE INTO settings VALUES (1, '{}')")
connection.commit()
connection.close()

started = time.time()
repo = AnalysisRepository(db, matches_dir, tmp / 'imports')
data = repo.get()
cold = time.time() - started

started2 = time.time()
data2 = repo.get()
warm = time2 = time.time() - started2

print(f"冷加载（100 局包）: {cold:.2f}s")
print(f"温加载: {warm:.3f}s")
print(f"对局数: {len(data.get('matches') or [])}")
shutil.rmtree(tmp, ignore_errors=True)
print('done')
