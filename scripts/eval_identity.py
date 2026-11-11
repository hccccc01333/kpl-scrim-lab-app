"""End-to-end identity alias evaluation on an isolated database."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results' / 'identity-eval'
OUT.mkdir(parents=True, exist_ok=True)
DB = OUT / 'identity.sqlite3'
PORT = '8779'
BASE = f'http://127.0.0.1:{PORT}'
sys.path.insert(0, str(ROOT))


def build():
    from tests.test_analysis_data import db_match, OWN, ENEMY
    ROSTER = [{'id': f'b{i + 1}', 'name': name} for i, name in enumerate(['甲', '乙', '丙', '丁', '戊'])]
    if DB.exists():
        DB.unlink()
    for folder in ('matches', 'imports'):
        path = OUT / folder
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    results = OUT / 'results.sqlite3'
    results.unlink(missing_ok=True)
    connection = sqlite3.connect(DB)
    connection.executescript('''
      CREATE TABLE settings (id INTEGER PRIMARY KEY, body TEXT NOT NULL);
      CREATE TABLE matches (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
    ''')
    connection.execute('INSERT INTO settings VALUES (1,?)',
                       (json.dumps({'teamName': '身份测试队', 'roster': ROSTER}, ensure_ascii=False),))
    for index in range(2):
        body = db_match(f'identity-{index}', f'2026-02-0{index + 1}', '对手A', 'left', 'left',
                        1200, OWN, ENEMY)
        for player in body['players']:
            if player.get('side') == 'left':
                player['playerId'] = None
                player['label'] = f'昵称{player["slot"] + 1}'
        connection.execute('INSERT INTO matches VALUES (?,1,?)',
                           (body['id'], json.dumps(body, ensure_ascii=False)))
    connection.commit()
    connection.close()


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as response:
        return json.loads(response.read().decode('utf-8'))


def put(path, value):
    request = urllib.request.Request(BASE + path, data=json.dumps(value).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'}, method='PUT')
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        print('PUT error', error.code, error.read().decode('utf-8'), file=sys.stderr)
        raise


def main():
    build()
    env = dict(os.environ, TRAINING_PORT=PORT, TRAINING_DB=str(DB),
               ANALYSIS_MATCHES=str(OUT / 'matches'), ANALYSIS_IMPORTS=str(OUT / 'imports'),
               STUDIO_RESULTS_DB=str(OUT / 'results.sqlite3'), PYTHONIOENCODING='utf-8')
    process = subprocess.Popen([sys.executable, str(ROOT / 'server.py')], cwd=str(ROOT), env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    report = {'checks': [], 'errors': []}

    def check(name, condition, detail=''):
        report['checks'].append({'name': name, 'ok': bool(condition), 'detail': detail})
        if not condition:
            report['errors'].append(f'{name}: {detail}')

    try:
        for _ in range(100):
            try:
                get('/api/studio/identity')
                break
            except OSError:
                time.sleep(.2)
        identity = get('/api/studio/identity')
        check('未绑定昵称', len(identity.get('unbound', [])) >= 1, str(len(identity.get('unbound', []))))
        state = get('/api/state')
        aliases = {'昵称1': 'b1', '昵称2': 'b2'}
        put('/api/settings', {**state['settings'], 'aliases': aliases})
        identity = get('/api/studio/identity')
        check('别名已保存', identity.get('aliases') == aliases, str(identity.get('aliases')))
        players = get('/api/studio/view/players?source=db')
        labels = {item['label']: item for item in players.get('players', [])}
        check('玩家已合并到稳定姓名', '甲' in labels and labels['甲'].get('bound'), str(list(labels)[:8]))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        (OUT / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    for item in report['checks']:
        print(('通过' if item['ok'] else '失败'), item['name'], item.get('detail', ''))
    raise SystemExit(0 if not report['errors'] else 1)


if __name__ == '__main__':
    main()
