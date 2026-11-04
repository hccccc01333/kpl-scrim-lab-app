#!/usr/bin/env python3
"""Decode the 10-player block layout of normal-5v5 `.abc` replays (12.1.1.x, build 5069040).

Read-only research tool. It never writes the replay, never touches the game
process, never reads param.json, and never uses runtime_dump memory.

What the block layout is (verified on 172 blocks / 20 samples):

    off +0x00  u8      team            1|2
    off +0x01  u8      teamEcho        always == team
    off +0x02  u8      0x01            constant tag
    off +0x03  u8      slot            0..4
    off +0x04  u16BE   reserved        always 0
    off +0x06  u16BE   entityID        battle unit id; equals the trailer roster
                                        first value and the frame-stream unit id
    off +0x08  u32BE   accountLevel    7..30, account constant, duplicated at post+0x10
    off +0x0C  u32BE   nameLen         includes the NUL terminator
    off +0x10  utf8    name            nameLen bytes

    post = off + 0x10 + nameLen      (30-byte record that follows the name)
    post+0x00  u32BE   flagA           2 for 106/172 blocks, else a copy of hash1
    post+0x04  u32BE   reserved        0
    post+0x08  u32LE   hash1           account hash, repeats at s+0x28
    post+0x0C  u32BE   accountValue1   account constant, repeats at s+0x2C
    post+0x10  u32BE   accountLevel    duplicate of off+0x08
    post+0x14  u32BE   accountValue2
    post+0x18  u32BE   accountValue3
    post+0x1C  u16BE   reserved        0

    s = post + 30
    s+0x00     u16BE   accountValue4
    s+0x02..27         zero padding (38 B)
    s+0x28     u32LE   hash1 dup
    s+0x2C     u32BE   accountValue1 dup
    s+0x30     u32BE   accountValue5
    s+0x34     u32BE   accountValue6
    s+0x38     u32BE   accountValue7
    s+0x3C     u32BE   0
    s+0x40     u32BE   accountValue8
    s+0x44     u32BE   0
    s+0x48     u16BE   heroID        <-- the field this tool exists for
    s+0x4A     u16BE   heroFlagA     0|2
    s+0x4C     u16BE   3
    s+0x4E     u16BE   1
    s+0x50     bytes   constant pattern (16 B)
    s+0x60     bytes   constant pattern (15 B)
    s+0x6F     u16BE   heroID again (present in 139/172 blocks of 12.1.1.x)
    s+0x71     u32BE   heroValue1
    s+0x75     u8      heroValue2
    s+0x76     u32BE   heroValue3
    s+0x7A     u32BE   heroValue4
    s+0xB8     u8/..   hero tags (1|2, 4, 3 small bytes ...)
    ...                opaque profile/social blob (length-prefixed openid,
                       avatar / portrait URLs, recent-player hash list)
    end-19     bytes   block footer (19 B, last 11 B constant)

Hero anchor: for the recording player's block the s+0x48 value equals the
`localHeroId` in the .abc header (offset 34, u32 LE) in 13/13 parseable
samples, and the recording player's block carries the 32-hex tag that is the
file-name suffix.  That fixes the field as the hero row id of the C# hero table
`0x111C3C` (row_id -> hero name).

Outputs (default `data/replays/_analysis/datasets/`):
    agent_player_block_schema.csv   player / offset / field / type / value
    agent_normal5v5_player_heroes.csv
        player / team / slot / entityID / heroID / heroName / confidence

Usage:
    python tools/agent_player_block_schema.py
    python tools/agent_player_block_schema.py --abc <file.abc> --out-dir <dir>
    python tools/agent_player_block_schema.py --verify-all
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import struct
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABC_BATCH = ROOT / 'data' / 'replays' / 'samples' / 'abc_batch'
MAIN_SAMPLE = ABC_BATCH / ('20260925_105224_-1505729760_4933_1790303631_'
                           'CBDD358E761B15A4DF526A179E8119E2.abc')
OUT_DIR = ROOT / 'data' / 'replays' / '_analysis' / 'datasets'
HERO_TABLE = (ROOT / 'data' / 'replays' / '_analysis' / 'datasets'
              / 'agent_hero_tables' / '0x111C3C_hero_base_attributes.csv')
CATALOG = ROOT / 'resources' / 'catalog.json'

SUPPORTED_VERSION = '12.1.1.'
HEADER_SCAN_LIMIT = 0x20000      # player blocks only live in the file header area
MAX_BLOCKS = 10
BLOCK_FOOTER_LEN = 19
RECORDER_TAG = re.compile(rb'(?<![0-9A-F])([0-9A-F]{32})(?![0-9A-F])')   # file-name suffix


# --------------------------------------------------------------------------- #
# hero name sources
# --------------------------------------------------------------------------- #
def load_hero_names() -> dict[int, str]:
    """row_id -> hero name from the decoded 0x111C3C table, catalog as fallback."""
    names: dict[int, str] = {}
    if HERO_TABLE.exists():
        with HERO_TABLE.open(encoding='utf-8-sig') as fp:
            for row in csv.DictReader(fp):
                try:
                    names[int(row['row_id'])] = row['name']
                except (KeyError, ValueError):
                    continue
    if CATALOG.exists():
        try:
            for entry in json.loads(CATALOG.read_text(encoding='utf-8')).get('entries', []):
                if entry.get('kind') != 'hero':
                    continue
                hero_id = int(str(entry.get('id', '')).split('-')[-1])
                names.setdefault(hero_id, entry.get('name'))
        except (ValueError, json.JSONDecodeError):
            pass
    return names


# --------------------------------------------------------------------------- #
# container parsing
# --------------------------------------------------------------------------- #
def parse_header(data: bytes) -> dict:
    """4 length-prefixed header strings, then localHeroId u32 LE at offset 34."""
    offset = 0
    texts = []
    for index in range(4):
        size = data[offset]
        texts.append(data[offset + 1:offset + 1 + size].decode('latin1'))
        offset += 1 + size
    local_hero = struct.unpack_from('<I', data, offset)[0] if offset + 4 <= len(data) else None
    return {
        'headerEnd': offset,
        'versions': texts[:2],
        'builds': texts[2:],
        'localHeroId': local_hero,
        'supported': bool(texts) and texts[0].startswith(SUPPORTED_VERSION),
        'nicknameOffset': offset + 16,   # u32 localHeroId + 3 u32 header values
    }


def header_nickname(data: bytes, header: dict) -> str:
    """Recorder nickname: u16BE length + UTF-8, 16 B after the header strings."""
    pos = header['nicknameOffset']
    if pos + 2 > len(data):
        return ''
    size = struct.unpack_from('>H', data, pos)[0]
    if not 1 <= size <= 64 or pos + 2 + size > len(data):
        return ''
    try:
        text = data[pos + 2:pos + 2 + size].decode('utf-8')
    except UnicodeDecodeError:
        return ''
    return text if all(c.isprintable() for c in text) else ''


def find_blocks(data: bytes) -> list[dict]:
    """Scan the header area for the 8-byte player-block header."""
    limit = min(len(data), HEADER_SCAN_LIMIT)
    found = []
    pos = 0
    while pos + 24 <= limit:
        if (data[pos] in (1, 2) and data[pos + 1] in (1, 2) and data[pos + 2] == 1
                and data[pos + 3] <= 4 and data[pos + 4] == 0 and data[pos + 5] == 0):
            entity = struct.unpack_from('>H', data, pos + 6)[0]
            if 100 <= entity <= 3000 and data[pos + 12:pos + 15] == b'\x00\x00\x00':
                name_len = data[pos + 15]
                end = pos + 16 + name_len
                if 2 <= name_len <= 40 and end <= len(data):
                    raw = data[pos + 16:end]
                    try:
                        name = raw.rstrip(b'\x00').decode('utf-8')
                    except UnicodeDecodeError:
                        name = ''
                    if name and all(c.isprintable() for c in name):
                        found.append({'offset': pos, 'entityID': entity,
                                      'name': name, 'nameLen': name_len})
                        pos = end
                        continue
        pos += 1
    return found[:MAX_BLOCKS]


def read_value(data: bytes, offset: int, kind: str):
    if kind == 'utf8':
        name_len = struct.unpack_from('>I', data, offset - 4)[0]
        raw = data[offset:offset + name_len]
        return raw.rstrip(b'\x00').decode('utf-8', 'replace')
    if offset < 0 or offset + {'u8': 1, 'u16BE': 2, 'u16LE': 2,
                               'u32BE': 4, 'u32LE': 4}[kind] > len(data):
        return None
    if kind == 'u8':
        return data[offset]
    if kind == 'u16BE':
        return struct.unpack_from('>H', data, offset)[0]
    if kind == 'u16LE':
        return struct.unpack_from('<H', data, offset)[0]
    if kind == 'u32BE':
        return struct.unpack_from('>I', data, offset)[0]
    return struct.unpack_from('<I', data, offset)[0]


HDR_FIELDS = [
    (0x00, 'u8', 'team'),
    (0x01, 'u8', 'teamEcho'),
    (0x02, 'u8', 'constTag'),
    (0x03, 'u8', 'slot'),
    (0x04, 'u16BE', 'reserved0'),
    (0x06, 'u16BE', 'entityID'),
    (0x08, 'u32BE', 'accountLevel'),
    (0x0C, 'u32BE', 'nameLen'),
]

POST_FIELDS = [
    (0x00, 'u32BE', 'flagA'),
    (0x04, 'u32BE', 'reserved0'),
    (0x08, 'u32LE', 'hash1'),
    (0x0C, 'u32BE', 'accountValue1'),
    (0x10, 'u32BE', 'accountLevelDup'),
    (0x14, 'u32BE', 'accountValue2'),
    (0x18, 'u32BE', 'accountValue3'),
    (0x1C, 'u16BE', 'reserved0'),
]

S_FIELDS = [
    (0x00, 'u16BE', 'accountValue4'),
    (0x28, 'u32LE', 'hash1Dup'),
    (0x2C, 'u32BE', 'accountValue1Dup'),
    (0x30, 'u32BE', 'accountValue5'),
    (0x34, 'u32BE', 'accountValue6'),
    (0x38, 'u32BE', 'accountValue7'),
    (0x3C, 'u32BE', 'reserved0'),
    (0x40, 'u32BE', 'accountValue8'),
    (0x44, 'u32BE', 'reserved0'),
    (0x48, 'u16BE', 'heroID'),
    (0x4A, 'u16BE', 'heroFlagA'),
    (0x4C, 'u16BE', 'const3'),
    (0x4E, 'u16BE', 'const1'),
    (0x6F, 'u16BE', 'heroID2'),
    (0x71, 'u32BE', 'heroValue1'),
    (0x75, 'u8', 'heroValue2'),
    (0x76, 'u32BE', 'heroValue3'),
    (0x7A, 'u32BE', 'heroValue4'),
    (0xB8, 'u8', 'heroTag0'),
    (0xB9, 'u8', 'heroTag1'),
]

S_CONST_REGIONS = [
    (0x02, 0x26, 'zeroPadding'),
    (0x50, 0x10, 'constPattern1'),
    (0x60, 0x0F, 'constPattern2'),
]

FOOTER_TAIL = bytes.fromhex('000000000004b000000000')   # last 11 B of the 19 B footer


def parse_player_block(data: bytes, block: dict, block_end: int) -> dict:
    off = block['offset']
    name_len = struct.unpack_from('>I', data, off + 12)[0]
    post = off + 16 + name_len
    s = post + 30
    rec = dict(block)
    rec.update({
        'blockEnd': block_end,
        'blockLen': block_end - off,
        'post': post,
        's': s,
        'fields': [],
        'regions': [],
        'strings': [],
    })

    def add(rel, base, kind, name):
        value = read_value(data, base + rel, kind)
        rec['fields'].append({'rel': rel, 'base': base, 'kind': kind,
                              'name': name, 'value': value})

    for rel, kind, name in HDR_FIELDS:
        add(rel, off, kind, name)
    add(0x10, off, 'utf8', 'name')
    for rel, kind, name in POST_FIELDS:
        add(rel, post, kind, name)
    for rel, kind, name in S_FIELDS:
        add(rel, s, kind, name)
    for rel, size, name in S_CONST_REGIONS:
        rec['regions'].append({'rel': rel, 'base': s, 'kind': f'bytes[{size}]',
                               'name': name,
                               'value': data[s + rel:s + rel + size].hex()})

    # hero duplicate is not present in every build; drop it when it is not the hero
    hero = next(f['value'] for f in rec['fields'] if f['name'] == 'heroID')
    rec['heroID'] = hero
    hero2 = next(f['value'] for f in rec['fields'] if f['name'] == 'heroID2')
    rec['heroID2'] = hero2 if hero2 == hero else None
    rec['fields'] = [f for f in rec['fields']
                     if not (f['name'] == 'heroID2' and rec['heroID2'] is None)]

    # opaque profile blob + footer
    opaque_start = s + 0xC8
    footer_start = block_end - BLOCK_FOOTER_LEN
    rec['opaque'] = (opaque_start, max(opaque_start, footer_start))
    rec['footer'] = (footer_start, block_end)

    # printable strings inside the opaque blob (openid / avatar / portrait URLs)
    seen = 0
    for match in re.finditer(rb'[\x20-\x7e]{8,}', data[opaque_start:block_end]):
        absolute = opaque_start + match.start()
        raw = match.group()
        kind = 'ascii'
        # the profile blob prefixes every string with a u8 length byte that
        # counts itself; printable prefixes (>= 0x20) end up inside the run
        if raw[0] == len(raw) and raw[0] >= 0x20:
            kind = 'ascii(len-prefixed)'
            raw = raw[1:]
            absolute += 1
        elif absolute > opaque_start and data[absolute - 1] == len(raw) + 1:
            kind = 'ascii(len-prefixed)'
        rec['strings'].append({'offset': absolute, 'text': raw.decode('latin1'),
                               'kind': kind})
        seen += 1
        if seen >= 12:
            break
    return rec


def locate_block_end(data: bytes, block_off: int, next_off: int | None,
                     search_from: int | None = None) -> int:
    if next_off is not None:
        return next_off
    idx = data.find(FOOTER_TAIL, search_from if search_from is not None else block_off)
    if idx == -1:
        return len(data)
    return idx + len(FOOTER_TAIL)


def parse_replay(path: Path) -> dict:
    data = path.read_bytes()
    header = parse_header(data)
    blocks = find_blocks(data)
    tag = RECORDER_TAG.search(path.stem.encode())
    tag_bytes = tag.group(1) if tag else None
    nickname = header_nickname(data, header)

    records = []
    for index, block in enumerate(blocks):
        next_off = blocks[index + 1]['offset'] if index + 1 < len(blocks) else None
        name_len = struct.unpack_from('>I', data, block['offset'] + 12)[0]
        s = block['offset'] + 16 + name_len + 30
        end = locate_block_end(data, block['offset'], next_off, search_from=s + 0xC8)
        rec = parse_player_block(data, block, end)
        rec['recorder'] = bool(tag_bytes and tag_bytes in data[block['offset']:end])
        records.append(rec)

    # fallback: local player = the block whose hero equals the header localHeroId
    if not any(r['recorder'] for r in records) and header['localHeroId'] is not None:
        for rec in records:
            if rec['heroID'] == header['localHeroId']:
                rec['recorder'] = True
                break

    return {'path': path, 'header': header, 'nickname': nickname,
            'recorderTag': tag_bytes.decode() if tag_bytes else None,
            'blocks': records}


# --------------------------------------------------------------------------- #
# reporting helpers
# --------------------------------------------------------------------------- #
def field_value_text(field: dict) -> str:
    if field['kind'] == 'utf8':
        return field['value'] or ''
    if field['name'].startswith('hash'):
        return f"0x{field['value']:08X}"
    return str(field['value'])


def schema_rows(replay: dict) -> list[dict]:
    rows = []
    for rec in replay['blocks']:
        player = f"{rec['name']}#{rec['entityID']}"
        team, slot = None, None
        for field in rec['fields']:
            if field['name'] == 'team':
                team = field['value']
            elif field['name'] == 'slot':
                slot = field['value']
        rows.append({'player': player, 'offset': f"0x{rec['offset']:06X}",
                     'field': 'block.start', 'type': 'marker',
                     'value': f"team={team} slot={slot} blockLen={rec['blockLen']}"})
        for field in rec['fields']:
            base_name = 'hdr' if field['base'] == rec['offset'] else (
                'post' if field['base'] == rec['post'] else 's')
            label = f"{base_name}+0x{field['rel']:02X} {field['name']}"
            if field['kind'] == 'utf8':
                label = f"{base_name}+0x{field['rel']:02X} name"
            rows.append({'player': player,
                         'offset': f"0x{field['base'] + field['rel']:06X}",
                         'field': label, 'type': field['kind'],
                         'value': field_value_text(field)})
        for region in rec['regions']:
            rows.append({'player': player,
                         'offset': f"0x{region['base'] + region['rel']:06X}",
                         'field': f"s+0x{region['rel']:02X} {region['name']}",
                         'type': region['kind'], 'value': region['value']})
        start, end = rec['opaque']
        rows.append({'player': player, 'offset': f"0x{start:06X}",
                     'field': f"profile+0x{start - rec['s']:02X} opaqueBlob",
                     'type': f"bytes[{max(0, end - start)}]",
                     'value': 'opaque (length-prefixed openid / avatar / portrait / recent-player list)'})
        for item in rec['strings']:
            rows.append({'player': player, 'offset': f"0x{item['offset']:06X}",
                         'field': 'profile.string', 'type': item['kind'],
                         'value': item['text']})
        fs, fe = rec['footer']
        rows.append({'player': player, 'offset': f"0x{fs:06X}",
                     'field': f"footer+0x00 blockFooter",
                     'type': f"bytes[{fe - fs}]", 'value': 'block footer'})
    return rows


def hero_rows(replay: dict, hero_names: dict[int, str]) -> list[dict]:
    records = replay['blocks']
    counts = Counter(r['heroID'] for r in records)
    local_hero = replay['header'].get('localHeroId')
    rows = []
    for rec in records:
        team = slot = None
        for field in rec['fields']:
            if field['name'] == 'team':
                team = field['value']
            elif field['name'] == 'slot':
                slot = field['value']
        in_table = rec['heroID'] in hero_names
        if rec['recorder']:
            confidence = 'high' if in_table and rec['heroID'] == local_hero else 'medium'
        elif in_table and counts[rec['heroID']] == 1:
            confidence = 'high'
        elif in_table:
            confidence = 'medium'
        else:
            confidence = 'low'
        rows.append({
            'player': rec['name'],
            'team': team,
            'slot': slot,
            'entityID': rec['entityID'],
            'heroID': rec['heroID'],
            'heroName': hero_names.get(rec['heroID'], ''),
            'confidence': confidence,
        })
    return rows


# --------------------------------------------------------------------------- #
# verification across samples
# --------------------------------------------------------------------------- #
def verify_all(hero_names: dict[int, str]) -> int:
    """Cross-check heroID against the header localHeroId for every parseable sample."""
    ok = bad = 0
    for path in sorted(ABC_BATCH.glob('*.abc')):
        replay = parse_replay(path)
        if not replay['header']['supported'] or not replay['blocks']:
            continue
        recorder = next((r for r in replay['blocks'] if r['recorder']), None)
        local_hero = replay['header']['localHeroId']
        if recorder is None:
            bad += 1
            print(f"{path.name[:21]:22} no recorder block (localHeroId={local_hero})")
            continue
        match = recorder['heroID'] == local_hero
        ok += match
        bad += not match
        print(f"{path.name[:21]:22} blocks={len(replay['blocks']):2} "
              f"recorder={recorder['entityID']:5} hero={recorder['heroID']:4} "
              f"{hero_names.get(recorder['heroID'], '?'):8} localHeroId={local_hero:4} "
              f"{'OK' if match else 'MISMATCH'}")
    print(f"\nheader-localHeroId anchor: {ok} ok / {bad} failed")
    return 0 if bad == 0 else 1


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--abc', type=Path, default=MAIN_SAMPLE)
    parser.add_argument('--out-dir', type=Path, default=OUT_DIR)
    parser.add_argument('--verify-all', action='store_true',
                        help='re-run the header localHeroId cross-check on every batch sample')
    args = parser.parse_args()

    hero_names = load_hero_names()
    if not hero_names:
        print('warning: hero name table not found, heroName will be empty')

    if args.verify_all:
        code = verify_all(hero_names)
        if args.abc == MAIN_SAMPLE:
            return code

    if not args.abc.exists():
        print(f'error: {args.abc} not found')
        return 1

    replay = parse_replay(args.abc)
    if not replay['header']['supported']:
        print(f"error: unsupported version {replay['header']['versions']}")
        return 1
    if not replay['blocks']:
        print('error: no player block found')
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    schema_path = args.out_dir / 'agent_player_block_schema.csv'
    hero_path = args.out_dir / ('agent_normal5v5_player_heroes.csv'
                                if 'normal' in args.abc.name or len(replay['blocks']) == 10
                                else 'agent_player_heroes.csv')

    rows = schema_rows(replay)
    with schema_path.open('w', newline='', encoding='utf-8-sig') as fp:
        writer = csv.DictWriter(fp, fieldnames=['player', 'offset', 'field', 'type', 'value'])
        writer.writeheader()
        writer.writerows(rows)

    heroes = hero_rows(replay, hero_names)
    with hero_path.open('w', newline='', encoding='utf-8-sig') as fp:
        writer = csv.DictWriter(fp, fieldnames=['player', 'team', 'slot', 'entityID',
                                                'heroID', 'heroName', 'confidence'])
        writer.writeheader()
        writer.writerows(heroes)

    header = replay['header']
    print(f"file      : {args.abc.name}")
    print(f"version   : {header['versions']} build {header['builds']}")
    print(f"header    : localHeroId={header['localHeroId']} "
          f"recorderTag={replay['recorderTag']}")
    print(f"blocks    : {len(replay['blocks'])}  bytes {replay['blocks'][0]['offset']}"
          f"..{replay['blocks'][-1]['blockEnd']}")
    print(f"schema    : {schema_path}  rows={len(rows)}")
    print(f"heroes    : {hero_path}  rows={len(heroes)}")
    print()
    print(f"{'team':>4} {'slot':>4} {'entity':>6}  {'hero':>5}  {'name':<8} {'confidence':<10} player")
    for row in heroes:
        mark = '  <recorder' if any(r['recorder'] and r['entityID'] == row['entityID']
                                    for r in replay['blocks']) else ''
        print(f"{row['team']:>4} {row['slot']:>4} {row['entityID']:>6}  "
              f"{row['heroID']:>5}  {row['heroName']:<8} {row['confidence']:<10} "
              f"{row['player']}{mark}")

    # integrity checks
    problems = []
    for rec in replay['blocks']:
        hash1 = next(f['value'] for f in rec['fields'] if f['name'] == 'hash1')
        dup = next(f['value'] for f in rec['fields'] if f['name'] == 'hash1Dup')
        if hash1 != dup:
            problems.append(f"entity {rec['entityID']}: hash copy mismatch")
        if rec['heroID'] not in hero_names:
            problems.append(f"entity {rec['entityID']}: heroID {rec['heroID']} not in hero table")
    recorder = next((r for r in replay['blocks'] if r['recorder']), None)
    if recorder and header['localHeroId'] is not None and recorder['heroID'] != header['localHeroId']:
        problems.append('recorder heroID != header localHeroId')
    if problems:
        print('\nwarnings:')
        for problem in problems:
            print('  -', problem)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
