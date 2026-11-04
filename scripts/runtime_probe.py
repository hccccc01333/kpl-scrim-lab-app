"""Read-only probe for the GameCore runtime replay path.

The probe never writes to the game process. It requires an online Android
device/emulator with the game already running. ``--dump`` is opt-in and reads
``/proc/<pid>/mem`` through root; without root the probe only reports maps.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'test-results'
KEYWORDS = ('libgamecore.so', 'ashmem', 'memfd', 'shm', 'battle', 'replay')


def adb(serial, *args, timeout=20):
    command = ['adb'] + (['-s', serial] if serial else []) + list(args)
    result = subprocess.run(command, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        error = result.stderr.decode('utf-8', 'replace').strip()
        raise RuntimeError(error or 'adb 命令失败')
    return result.stdout


def devices():
    text = adb(None, 'devices').decode('utf-8', 'replace')
    found = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == 'device':
            found.append(parts[0])
    return found


def pick_device(serial):
    available = devices()
    if serial:
        if serial not in available:
            raise RuntimeError(f'设备 {serial} 不在线；当前在线：{available or "无"}')
        return serial
    if not available:
        raise RuntimeError('没有在线设备；请先启动模拟器并确认 adb devices')
    if len(available) > 1:
        raise RuntimeError(f'有多个在线设备，请用 --serial 指定：{available}')
    return available[0]


def root_available(serial):
    if shell_is_root(serial):
        return True
    try:
        output = adb(serial, 'shell', 'su', '-c', 'id').decode('utf-8', 'replace')
    except RuntimeError:
        return False
    return 'uid=0' in output


def shell_is_root(serial):
    output = adb(serial, 'shell', 'id').decode('utf-8', 'replace')
    return re.search(r'\buid=0\b', output) is not None


def parse_maps(serial, pid):
    text = adb(serial, 'shell', 'cat', f'/proc/{pid}/maps').decode('utf-8', 'replace')
    entries = []
    for line in text.splitlines():
        lower = line.lower()
        if not any(keyword in lower for keyword in KEYWORDS):
            continue
        parts = line.split(maxsplit=5)
        if len(parts) < 5:
            continue
        start, end = (int(part, 16) for part in parts[0].split('-', 1))
        entries.append({
            'start': start,
            'end': end,
            'size': end - start,
            'permissions': parts[1],
            'offset': parts[2],
            'path': parts[5] if len(parts) > 5 else '',
            'line': line,
        })
    return entries


def dump_region(serial, pid, entry, destination, max_bytes):
    size = min(entry['size'], max_bytes)
    block = 4096
    count = (size + block - 1) // block
    command = f'dd if=/proc/{pid}/mem bs={block} skip={entry["start"] // block} count={count} 2>/dev/null'
    if shell_is_root(serial):
        data = adb(serial, 'exec-out', 'sh', '-c', command, timeout=60)
    else:
        data = adb(serial, 'exec-out', 'su', '-c', command, timeout=60)
    destination.write_bytes(data[:size])
    return len(data[:size])


def probe(serial, package, dump=False, max_bytes=4 * 1024 * 1024):
    serial = pick_device(serial)
    pid_text = adb(serial, 'shell', 'pidof', package).decode('utf-8', 'replace').strip()
    if not pid_text:
        raise RuntimeError(f'找不到进程 {package}；请先在设备上进入回放')
    pid = int(pid_text.split()[0])
    entries = parse_maps(serial, pid)
    root = root_available(serial)
    result = {
        'device': serial,
        'package': package,
        'pid': pid,
        'root': root,
        'mapCount': len(entries),
        'maps': entries,
        'dumps': [],
        'next': [
            '在回放中读取 CAutoReplayManager.GetIsShmReplay()；false 时共享内存路线不成立',
            '为 true 时用 CShmReplayConsumer 的 mapfile/shm_name 复核映射',
            '不要直接假设原始帧字节字段；先确认英雄、位置、经济等标签来源',
        ],
    }
    if not dump:
        return result
    if not root:
        raise RuntimeError('--dump 需要 root；当前设备无法读取 /proc/<pid>/mem')
    OUT.mkdir(exist_ok=True)
    budget = max_bytes
    for index, entry in enumerate(entries):
        if budget <= 0:
            break
        if not entry['permissions'].startswith('r'):
            continue
        name = re.sub(r'[^a-zA-Z0-9_.-]+', '-', entry['path'].rsplit('/', 1)[-1] or f'region-{index}')[:40]
        destination = OUT / f'runtime-probe-{serial}-{pid}-{index}-{name}.bin'
        written = dump_region(serial, pid, entry, destination, budget)
        budget -= written
        result['dumps'].append({'path': str(destination), 'bytes': written, 'source': entry['line']})
    return result


def main():
    parser = argparse.ArgumentParser(description='只读检查 GameCore 运行时映射；不修改游戏进程。')
    parser.add_argument('--serial', help='adb 设备序列号；只有一台在线设备时可省略')
    parser.add_argument('--package', default='com.tencent.tmgp.sgame', help='游戏包名')
    parser.add_argument('--dump', action='store_true', help='读取候选映射（需要 root，只读）')
    parser.add_argument('--max-bytes', type=int, default=4 * 1024 * 1024, help='--dump 总字节上限，默认 4 MB')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    args = parser.parse_args()
    try:
        result = probe(args.serial, args.package, args.dump, args.max_bytes)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print(f'探测失败: {error}', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"设备: {result['device']} · 包名: {result['package']} · PID: {result['pid']} · root: {result['root']}")
        print(f"候选映射: {result['mapCount']}")
        for entry in result['maps'][:20]:
            print(f"  {entry['start']:#x}-{entry['end']:#x} {entry['permissions']} {entry['path'] or '匿名'}")
        if result['dumps']:
            print(f"已只读导出: {sum(item['bytes'] for item in result['dumps']):,} 字节")
        else:
            print('未导出；确认 root 和授权后加 --dump。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
