"""Import a public Camp (王者营地) replay link into data/official_replays.

Usage:
    python scripts/import_camp_replay.py "https://camp.qq.com/h5/webdist/battle-replay/...?gameseq=..."
    python scripts/import_camp_replay.py "<link>" --force --json
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import camp_replay


def main():
    parser = argparse.ArgumentParser(description='只读提取王者营地公开回放链接的官方数据。')
    parser.add_argument('url', help='camp.qq.com 回放链接')
    parser.add_argument('--force', action='store_true', help='忽略缓存，重新请求官方接口')
    parser.add_argument('--json', action='store_true', help='输出完整归一化 JSON')
    args = parser.parse_args()
    try:
        result = camp_replay.import_link(args.url, force=args.force)
    except camp_replay.CampReplayError as error:
        print(f'提取失败：{error}', file=sys.stderr)
        return 2
    meta = result['meta']
    match = meta.get('match') or {}
    print(f"官方回放：{result['id']}" + ('（缓存）' if result.get('cached') else ''))
    teams = match.get('teams') or []
    if teams:
        print('队伍：' + ' vs '.join(str(team.get('name')) for team in teams))
    print(f"胜方：{match.get('winCamp')}  时长：{match.get('durationSec')}s  "
          f"金币点：{match.get('goldPoints')}（约30秒）")
    print(f"团队金币：{match.get('teamGold')}  事件：{match.get('keyEvents')} + "
          f"{match.get('extendedEvents')}")
    print(f"位置：每人 {((meta.get('files') or {}).get('positions') or '无')}  "
          f"文件：data/official_replays/{result['id']}/")
    if args.json:
        normalized = result.get('normalized')
        if normalized is None:
            _, normalized = camp_replay.read_normalized(result['id'])
        print(json.dumps(normalized, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
