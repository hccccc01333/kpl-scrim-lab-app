#!/usr/bin/env python3
"""Inventory the client replay system from the installed IL2CPP metadata.

Read-only: loads the local copies of libil2cpp.so / global-metadata.dat and
writes a JSON inventory. It does not touch the emulator or the game process.

The inventory is a name/field/method map, not a decompilation. It records
which classes the current client uses for recording, replaying, seeking,
streaming and recovery so the .abc/.ope file contract can be matched to code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'data' / 'replays' / '_analysis' / 'tools'))
from kpl_i2cpp import Il2Cpp  # noqa: E402

TYPES = [
    'GameReplayModule',
    'GameReplayModuleProxy',
    'IGameReplayModule',
    'ReplayFileInfo',
    'BeginReplayParam',
    'stReplayHeadOutParam',
    'ReplayMsgType',
    'ReplayMsgLoader',
    'ReplayMsgLoadResultHandle',
    'GetStreamingReplayData',
    'ReplayControl',
    'ReplayControlTimeInput',
    'ReplayMemoryRecover',
    'CAutoReplayManager',
    'CAutoReplayConfig',
    'CAutoReplayConfigReader',
    'CReplayKitSys',
    'CReplayKitSysProxy',
    'VisualFrameReplayManager',
    'QuickReplaySystem',
    'QuickReplayInfo',
    'QuickReplaySysMediator',
    'battle.ReplayEntry',
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path,
                        default=ROOT / 'data/replays/_analysis/client_extract_20261102/replay_system.json')
    args = parser.parse_args()

    api = Il2Cpp()
    inventory = {'metadata': {}, 'types': {}}
    for name in ('libil2cpp.so', 'global-metadata.dat'):
        path = ROOT / 'data/replays/_analysis' / name
        if path.exists():
            inventory['metadata'][name] = {'bytes': path.stat().st_size, 'sha256': sha256(path)}

    for type_name in TYPES:
        try:
            fields = api.fields_of(type_name)
            methods = api.methods_of(type_name)
        except StopIteration:
            continue
        type_row = next(t for t in api.types if t['name'] == type_name)
        inventory['types'][type_name] = {
            'namespace': type_row['ns'],
            'fields': [{'name': f[0], 'type_index': f[1]} for f in fields],
            'methods': [
                {'name': m['name'], 'token': f"0x{m['token']:x}",
                 'params': m['paramCount'], 'flags': m['flags']}
                for m in methods
            ],
        }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'out': str(args.out),
                      'types': {k: {'fields': len(v['fields']), 'methods': len(v['methods'])}
                                for k, v in inventory['types'].items()}},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
