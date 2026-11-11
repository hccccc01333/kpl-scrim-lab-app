"""Read-only CLI using the same bounded replay parser as the workspace."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from replay_parser import MAX_FILE_BYTES,inspect_replay,parse_header,discover_blocks,parse_ope_bytes
from vision import catalog


def load_hero_names():
    return {int(e['id'].split('-')[1]):e['name'] for e in catalog()['entries'] if e['kind']=='hero'}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def parse_ope(path):
    if path.stat().st_size>MAX_FILE_BYTES:
        raise ValueError('.ope 文件超过 16 MB 上限')
    return parse_ope_bytes(path.read_bytes())


def probe(abc_path,ope_path=None):
    if abc_path.stat().st_size>MAX_FILE_BYTES or (ope_path and ope_path.stat().st_size>MAX_FILE_BYTES):
        raise ValueError('回放文件超过 16 MB 上限')
    report=inspect_replay(abc_path.read_bytes(),ope_path.read_bytes() if ope_path else None,load_hero_names())
    report['abc']['path']=str(abc_path)
    return report


def print_report(report):
    print(f"回放: {report['abc'].get('path','本地文件')}")
    print(f"大小: {report['abc']['size']:,} 字节")
    print(f"版本: {' / '.join(report['header']['versions'])}")
    print(f"解析配置: {report['parserVersion']}（单一样本版本）")
    print(f"本地英雄: {report['header'].get('localHeroName') or '未知'}")
    print(f"玩家块: {len(report['blocks'])}/10")
    for block in report['blocks']:
        if block.get('camp'):
            label=f"{'蓝方' if block['camp']==1 else '红方'} · 槽位 {block['position']+1}"
        else:
            label='阵营未知'
        if block.get('bot'):
            label+=' · 电脑'
        if block['self']:
            label+=' · 本地英雄对应块'
        name=f" · {block['name']}" if block.get('name') else ''
        score=f" · 评分 {block['score']:.2f}" if block.get('score') is not None else ''
        buys=block.get('buyEvents') or 0
        gold=f" · 购买事件 {buys}" if buys else ''
        print(f"  块 {block['order']+1}: {block['heroName'] or '未知'} ({block['heroId']}){name} · {label}{score}{gold}")
    if report.get('scoreTable'):
        print(f"赛后评分表: {report['scoreTable']['offset']}（汇总字段，不是原始流水）")
    player_events=report.get('playerEvents')
    if player_events:
        echo=player_events['buyEcho']; skills=player_events['skills']; positions=player_events['positions']
        print(f"原始事件: 购买镜像 {echo['unique']}/{echo['records']} 条"
              f"（重复 {echo['duplicates']}） · 技能升级 {skills['unique']} 条"
              f" · 坐标样本 {positions['records']} 条")
        print('  0x85 是 BUYEQUIP 的镜像，不含金币数额；不能据此重建收入账本。')
    frames=report.get('frames')
    if frames and frames.get('status')=='frame-stream':
        print(f"帧流记录: {frames['records']} 条（seq {frames['firstSequence']}–{frames['lastSequence']}，"
              f"偏移 {frames['start']}–{frames['end']}）")
    else:
        print(f"尾部结构记录: {report['tlv']['records']}；状态 {report['tlv']['status']}")
    if report['ope']:
        ope=report['ope']
        print(f".ope 双层解压: {ope['size']} → {ope['innerSize']} → {ope['operatorStreamBytes']} 字节"
              f"（第二层压缩流偏移 {ope['secondLayerOffset']}）")
        events=ope.get('operatorEvents') or {}
        if events.get('decoded'):
            print(f"操作流事件: {events['resolvedCount']}/{events['recordCount']} 条已知形态"
                  f"（未定形态 {events['unresolvedCount']} 段 / {events['unresolvedBytes']} 字节，多解 {events['ambiguousChoices']} 处）")
            print(f"  计数: Touch {events['touchCount']} · Move {events['moveCount']} · SkillUse {events['skillUseCount']}"
                  f" · SkillSlot {events['skillSlotCount']} · UIEvent {events['uiEventCount']}")
            if events.get('frameRange'):
                print(f"  逻辑帧范围 {events['frameRange'][0]}–{events['frameRange'][1]}"
                      f" · UnityFrame 范围 {events['unityFrameRange'][0]}–{events['unityFrameRange'][1]}")
            print('  字段名多为推断；不构成十人状态、击杀或经济数据。')
        else:
            print(events.get('note','操作流未解析，原因未知'))
    for warning in report['warnings']:
        print(f'注意: {warning}')


def main():
    # Player names carry zero-width and variation-selector code points, which a
    # GBK console cannot encode; without this the whole report dies on a print.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser=argparse.ArgumentParser(description='只读查看 .abc / .ope 的已验证容器结构。')
    parser.add_argument('replay',help='.abc 文件路径')
    parser.add_argument('--ope',help='配套 .ope；默认寻找同目录同名文件')
    parser.add_argument('--json',action='store_true',help='输出 JSON')
    args=parser.parse_args()
    abc=Path(args.replay).expanduser().resolve()
    ope=Path(args.ope).expanduser().resolve() if args.ope else abc.with_suffix('.ope')
    if not abc.is_file() or (args.ope and not ope.is_file()):
        print('找不到指定的回放文件',file=sys.stderr)
        return 2
    try:
        report=probe(abc,ope if ope.is_file() else None)
    except (OSError,ValueError) as error:
        print(f'解析失败: {error}',file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report,ensure_ascii=False,indent=2))
    else:
        print_report(report)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
