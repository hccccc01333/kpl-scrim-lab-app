"""Deploy website/dist to the GitHub Pages repo through the REST API.

Direct ``git push`` to github.com is unreliable from this network, while
``gh api`` keeps working, so the deploy walks the git data API instead:

1. read the current ``main`` commit and its tree;
2. hash every local file with ``git hash-object`` and diff against that tree;
3. create one tree with the changed / added files inline (binary content goes
   through a separate base64 blob), plus ``sha: null`` entries for deletions;
4. create the commit and fast-forward ``main``.

Nothing is written unless the tree actually differs from the remote one.
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = 'hccccc01333/kpl-scrim-lab-site'
BRANCH = 'main'
ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'website' / 'dist'


def gh(*args: str, payload: dict | None = None) -> dict:
    command = ['gh', 'api', *args]
    temp = None
    if payload is not None:
        handle = tempfile.NamedTemporaryFile('w', suffix='.json', delete=False,
                                             encoding='utf-8')
        json.dump(payload, handle, ensure_ascii=False)
        handle.close()
        temp = handle.name
        command += ['--input', temp]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                encoding='utf-8', errors='replace',
                                cwd=str(ROOT))
    finally:
        if temp:
            Path(temp).unlink(missing_ok=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    text = result.stdout.strip()
    return json.loads(text) if text else {}


def blob_sha(data: bytes) -> str:
    header = f'blob {len(data)}\0'.encode('ascii')
    return hashlib.sha1(header + data).hexdigest()


def is_text(data: bytes) -> bool:
    if b'\0' in data:
        return False
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        return False
    return True


def main() -> int:
    files = sorted(path for path in DIST.rglob('*') if path.is_file())
    if not files:
        raise SystemExit(f'{DIST} 是空的，先跑 python scripts/build_website.py')
    local = {}
    for path in files:
        rel = path.relative_to(DIST).as_posix()
        local[rel] = (path, blob_sha(path.read_bytes()))

    ref = gh(f'repos/{REPO}/git/ref/heads/{BRANCH}')
    head = ref['object']['sha']
    commit = gh(f'repos/{REPO}/git/commits/{head}')
    base_tree = commit['tree']['sha']
    tree = gh(f'repos/{REPO}/git/trees/{base_tree}?recursive=1')
    remote = {item['path']: item['sha'] for item in tree.get('tree', [])
              if item['type'] == 'blob'}

    changed = [rel for rel, (_path, sha) in local.items() if remote.get(rel) != sha]
    removed = sorted(set(remote) - set(local))
    print(f'本地 {len(local)} 个文件，远端 {len(remote)} 个；'
          f'变更 {len(changed)}，删除 {len(removed)}')
    if not changed and not removed:
        print('远端已是最新，无需部署。')
        return 0

    entries = []
    for rel in sorted(changed):
        path = local[rel][0]
        data = path.read_bytes()
        if is_text(data):
            entries.append({'path': rel, 'mode': '100644', 'type': 'blob',
                            'content': data.decode('utf-8')})
        else:
            # base64 有几百 KB，不能塞进命令行（Windows 会报 WinError 206），
            # 必须走 --input 的 JSON 载荷。
            blob = gh(f'repos/{REPO}/git/blobs', payload={
                'content': base64.b64encode(data).decode('ascii'),
                'encoding': 'base64'})
            entries.append({'path': rel, 'mode': '100644', 'type': 'blob',
                            'sha': blob['sha']})
            print(f'  二进制 {rel} -> {blob["sha"][:8]}')
    for rel in removed:
        entries.append({'path': rel, 'mode': '100644', 'type': 'blob', 'sha': None})

    new_tree = gh(f'repos/{REPO}/git/trees', payload={'base_tree': base_tree,
                                                      'tree': entries})
    message = ('官网：v3.0.0（全新视觉体系 + 复盘细节打磨 + 跨局大场收口）\n\n'
               f'由 scripts/build_website.py 构建，{len(changed)} 个文件更新，'
               f'{len(removed)} 个删除。')
    new_commit = gh(f'repos/{REPO}/git/commits', payload={
        'message': message, 'tree': new_tree['sha'], 'parents': [head]})
    gh(f'repos/{REPO}/git/refs/heads/{BRANCH}', '-X', 'PATCH',
       payload={'sha': new_commit['sha'], 'force': False})
    print(f'已部署：{new_commit["sha"][:12]}（{len(changed)} 个文件）')
    for rel in sorted(changed):
        print(f'  + {rel}')
    for rel in removed:
        print(f'  - {rel}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
