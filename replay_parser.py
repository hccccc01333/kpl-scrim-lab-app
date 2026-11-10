"""Read-only replay inspection for the observed 12.1.1.x layout.

This parses containers and structural counts, not gameplay state or tactics.
All offsets are a versioned research profile, not an official file contract.
"""
from collections import Counter, OrderedDict
import copy
import hashlib
import re
import threading
import unicodedata
import zlib

from operator_stream import OperatorStreamError, summarize as summarize_operator_stream
from replay_profiles import load_registry, profile_layout, resolve_profile

PROFILE = 'observed-12.1.1.x-v3'
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_DECODED_BYTES = 8 * 1024 * 1024
BLOCK_STRIDE = 1517
HERO_OFFSETS = (771, 1415, 1445)
TLV_START = 17652
SECOND_DEFLATE_START = 0x8B
ROSTER_SCAN_LIMIT = 0x20000
ROSTER_HERO_OFFSET = 0x48
ROSTER_BOT_BLOCK_BYTES = 2782
ROSTER_FOOTER_TAIL = bytes.fromhex('000000000004b000000000')
ROSTER_HUMAN_POST_BYTES = 30
ROSTER_BOT_POST_BYTES = 5
ROSTER_MAX_HUMAN_BLOCK_BYTES = 0x2000
FRAME_SCAN_LIMIT = 0x60000

# The constants above are the built-in defaults.  A profile from
# resources/replay_profiles.json overlays them for one parse; the resolved
# layout is passed down as an argument, so two parses of different client
# builds never share mutable module state.
_DEFAULT_LAYOUT = {
    'blockStride': BLOCK_STRIDE,
    'heroOffsets': HERO_OFFSETS,
    'tlvStart': TLV_START,
    'secondDeflateStart': SECOND_DEFLATE_START,
    'rosterScanLimit': ROSTER_SCAN_LIMIT,
    'rosterHeroOffset': ROSTER_HERO_OFFSET,
    'rosterBotBlockBytes': ROSTER_BOT_BLOCK_BYTES,
    'rosterFooterTail': ROSTER_FOOTER_TAIL,
    'rosterHumanPostBytes': ROSTER_HUMAN_POST_BYTES,
    'rosterBotPostBytes': ROSTER_BOT_POST_BYTES,
    'rosterMaxHumanBlockBytes': ROSTER_MAX_HUMAN_BLOCK_BYTES,
    'frameScanLimit': FRAME_SCAN_LIMIT,
}


def layout_for(profile):
    """Resolve a profile to a complete layout dict, defaults filled in."""
    layout = dict(_DEFAULT_LAYOUT)
    layout.update(profile_layout(profile))
    return layout


# The upload endpoint validates a file by parsing it, then the import endpoint
# parses it again; the sha256 that is already the file id makes that cacheable.
# Bounded so a long session cannot pin every replay's event lists in memory.
_CACHE_LOCK = threading.Lock()
_CACHE = OrderedDict()
_CACHE_MAX = 8


def _cache_get(sha):
    with _CACHE_LOCK:
        report = _CACHE.get(sha)
        if report is None:
            return None
        _CACHE.move_to_end(sha)
    return copy.deepcopy(report)


def _cache_put(report):
    sha = report['abc']['sha256']
    with _CACHE_LOCK:
        _CACHE[sha] = copy.deepcopy(report)
        _CACHE.move_to_end(sha)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def cache_clear():
    """Drop cached parses (tests and data-dir switches)."""
    with _CACHE_LOCK:
        _CACHE.clear()


class ReplayFormatError(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked_slice(data, start, size, label):
    if start < 0 or size < 0 or start+size > len(data):
        raise ReplayFormatError(f'{label}被截断（偏移 {start}，需要 {size} 字节）')
    return data[start:start+size]


def prefixed_text(data, offset, label):
    size = checked_slice(data, offset, 1, label)[0]
    if not 1 <= size <= 80:
        raise ReplayFormatError(f'{label}长度无效')
    try:
        text = checked_slice(data, offset+1, size, label).decode('utf-8')
    except UnicodeDecodeError as error:
        raise ReplayFormatError(f'{label}不是预期的 UTF-8 字符串') from error
    if not all(c.isprintable() for c in text):
        raise ReplayFormatError(f'{label}包含非显示字符')
    return text, offset+1+size


def dotnet_string(data, offset, label):
    """Read a .NET BinaryReader string: 7-bit encoded length + UTF-8."""
    size = 0
    shift = 0
    while True:
        byte = checked_slice(data, offset, 1, label)[0]
        offset += 1
        size |= (byte & 0x7f) << shift
        if not byte & 0x80:
            break
        shift += 7
        if shift > 28:
            raise ReplayFormatError(f'{label}长度编码无效')
    try:
        text = checked_slice(data, offset, size, label).decode('utf-8')
    except UnicodeDecodeError as error:
        raise ReplayFormatError(f'{label}不是预期的 UTF-8 字符串') from error
    if not all(c.isprintable() for c in text):
        raise ReplayFormatError(f'{label}包含非显示字符')
    return text, offset + size


def parse_header(data):
    texts, offset = [], 0
    for index in range(4):
        text, offset = dotnet_string(data, offset, f'头部字符串 {index+1}')
        texts.append(text)
    if any(not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', value) for value in texts[:2]):
        raise ReplayFormatError('未识别为预期的 .abc 版本头')
    if any(not value.isdigit() for value in texts[2:]):
        raise ReplayFormatError('构建号格式与已知样本不符')
    registry = load_registry()
    profile = resolve_profile(texts[:2], texts[2:], registry)
    supported = profile is not None
    local_hero = None
    start_time = map_type = map_id = None
    user_name = user_head = None
    rank_grade = rank_class = None
    nickname = nickname_offset = None
    total_frame_num = None
    if supported:
        local_hero = int.from_bytes(checked_slice(data, offset, 4, '本地英雄 ID'), 'little')
        offset += 4
        # Public GameReplayModule.cs order: startTime, mapType, mapId,
        # userName, userHead, rankGrade, rankClass. 2026 samples add a
        # fourth build string before this block; the rest matches.
        try:
            start_time = int.from_bytes(checked_slice(data, offset, 8, '开始时间'), 'little', signed=True)
            offset += 8
            map_type = checked_slice(data, offset, 1, '地图类型')[0]
            offset += 1
            map_id = int.from_bytes(checked_slice(data, offset, 4, '地图 ID'), 'little')
            offset += 4
            user_name, user_name_offset = dotnet_string(data, offset, '玩家名')
            offset = user_name_offset
            user_head, offset = dotnet_string(data, offset, '头像 URL')
            rank_grade = checked_slice(data, offset, 1, '段位等级')[0]
            offset += 1
            rank_class = int.from_bytes(checked_slice(data, offset, 4, '段位阶级'), 'little')
            offset += 4
            # 2026 header tail: 13 bytes before the first 1075 packet; the
            # last u32LE is the total frame count (10,674 / 15,540 observed).
            tail = data[offset:offset+13]
            if len(tail) == 13:
                value = int.from_bytes(tail[9:13], 'little')
                if 0 < value < 10_000_000:
                    total_frame_num = value
            nickname, nickname_offset = user_name, user_name_offset
        except ReplayFormatError:
            # Old/synthetic headers may stop after heroID; keep the
            # historical nickname fallback instead of rejecting the file.
            start_time = map_type = map_id = None
            user_name = user_head = None
            rank_grade = rank_class = None
            nickname = nickname_offset = None
            position = offset - 4 + 16
            if position + 2 <= len(data):
                size = int.from_bytes(data[position:position+2], 'big')
                if 1 <= size <= 64 and position + 2 + size <= len(data):
                    try:
                        text = data[position+2:position+2+size].decode('utf-8')
                    except UnicodeDecodeError:
                        text = ''
                    if text and all(c.isprintable() for c in text):
                        nickname, nickname_offset = text, position + 2
    return {'versions': texts[:2], 'builds': texts[2:],
            'localHeroId': local_hero, 'startTime': start_time,
            'mapType': map_type, 'mapId': map_id,
            'userName': user_name, 'userHead': user_head,
            'rankGrade': rank_grade, 'rankClass': rank_class,
            'nickname': nickname, 'nicknameOffset': nickname_offset,
            'totalFrameNum': total_frame_num,
            'layoutSupported': supported,
            'profile': profile['id'] if supported else None,
            'profileSource': registry['source'] if supported else None}


def _discover_legacy_blocks(data, hero_ids, local_hero=None, layout=None):
    layout = layout or _DEFAULT_LAYOUT
    stride = layout['blockStride']
    hero_offsets = layout['heroOffsets']
    starts = set()
    # Only inspect the header area. A large payload cannot turn this into an
    # unbounded byte-by-byte scan or introduce distant accidental blocks.
    header = data[:128*1024]
    for hero_id in hero_ids:
        pattern = int(hero_id).to_bytes(4,'big')
        position = header.find(pattern)
        while position != -1:
            start = position-hero_offsets[0]
            if start >= 0 and start+stride <= len(header):
                if all(header[start+o:start+o+4] == pattern for o in hero_offsets):
                    starts.add(start)
            position = header.find(pattern,position+1)
    candidates = []
    for start in sorted(starts):
        if start-stride in starts:
            continue
        chain = []
        while start+len(chain)*stride in starts:
            chain.append(start+len(chain)*stride)
        if len(chain) == 9:
            first = chain[0]-stride
            if first >= 0:
                hero = int.from_bytes(header[first+hero_offsets[2]:first+hero_offsets[2]+4],'big')
                if hero in hero_ids and (local_hero is None or hero == local_hero):
                    chain.insert(0,first)
        if len(chain) == 10:
            candidates.append(chain)
    if len(candidates) != 1:
        return [], ['未找到唯一的十人连续玩家块；保留未知，不推断阵营或英雄。']
    blocks = []
    for index,start in enumerate(candidates[0]):
        hero = int.from_bytes(header[start+hero_offsets[2]:start+hero_offsets[2]+4],'big')
        blocks.append({'order':index,'start':start,'heroId':hero,'self':False,'camp':None,'position':None})
    matching = [b for b in blocks if b['heroId'] == local_hero]
    if len(matching) == 1:
        matching[0]['self'] = True
    warnings = []
    if len(matching) != 1:
        warnings.append('未能唯一对应本地英雄；本地玩家身份仍未知。')
    if len({b['heroId'] for b in blocks}) != 10:
        warnings.append('发现重复英雄 ID，请结合模式与截图核对。')
    return blocks,warnings


def _roster_name(raw):
    """Decode a player name, allowing the invisible formatting characters used in-game.

    Normal-5v5 names may end with a NUL padding byte and contain zero-width
    separators (category Cf), so `str.isprintable()` alone drops valid blocks.
    Control and unassigned code points still reject the candidate.
    """
    try:
        name = raw.rstrip(b'\x00').decode('utf-8')
    except UnicodeDecodeError:
        return None
    if not name or not any(c.isprintable() and not c.isspace() for c in name):
        return None
    if any(unicodedata.category(c) in ('Cc','Cs','Cn') for c in name):
        return None
    return name


def _roster_candidates(data, limit):
    """Scan the header area for the 5247758 variable-length player blocks."""
    found, position = [], 0
    while position+24 <= limit:
        tag = data[position+2]
        if (data[position] in (1,2) and data[position+1] == data[position]
                and tag in (1,2) and data[position+3] <= 4
                and data[position+4] == 0 and data[position+5] == 0):
            entity = int.from_bytes(data[position+6:position+8],'big')
            if (100 <= entity <= 9999
                    and data[position+12:position+15] == b'\x00\x00\x00'):
                size = data[position+15]
                end = position+16+size
                if 2 <= size <= 40 and end <= limit:
                    name = _roster_name(data[position+16:end])
                    if name is not None:
                        found.append({'start':position, 'tag':tag, 'camp':data[position],
                                      'position':data[position+3], 'entityId':entity,
                                      'name':name, 'nameLen':size})
                        position = end
                        continue
        position += 1
    return found


def _roster_block_end(data, candidate, next_start=None, layout=None):
    layout = layout or _DEFAULT_LAYOUT
    if candidate['tag'] != 1:
        end = candidate['start']+layout['rosterBotBlockBytes']
        return end if end <= len(data) else None
    name_end = candidate['start']+16+candidate['nameLen']
    limit = min(len(data), candidate['start']+layout['rosterMaxHumanBlockBytes'])
    # Blue-side human blocks carry the 12-byte footer ending exactly at the
    # next block; red-side human blocks in 10-human games do not, and some
    # later blocks contain a footer pattern, so the next start wins unless
    # the footer itself lands there.
    footer = data.find(layout['rosterFooterTail'], name_end, limit)
    if footer != -1:
        end = footer+len(layout['rosterFooterTail'])
        if end == next_start:
            return end
    if next_start is not None and name_end < next_start <= limit:
        return next_start
    if footer != -1:
        end = footer+len(layout['rosterFooterTail'])
        return end if end <= len(data) else None
    return None


def _discover_roster_blocks(data, hero_ids, local_hero=None, layout=None):
    """The 5247758 ten-block layout, with human and bot variants.

    Human blocks (tag 1) carry a 30-byte post record; blue-side human blocks
    add a 19-byte footer, while red-side human blocks in all-human games end
    at the next block start. Bot blocks (tag 2) are a fixed 2782 bytes with a
    5-byte post record. Hero IDs are u16BE at s+0x48, where
    s = start+0x10+nameLen+post.
    """
    layout = layout or _DEFAULT_LAYOUT
    limit = min(len(data),layout['rosterScanLimit'])
    candidates = _roster_candidates(data,limit)
    ordered = sorted(candidates,key=lambda item:item['start'])
    for index,candidate in enumerate(ordered):
        following = ordered[index+1]['start'] if index+1 < len(ordered) else None
        candidate['end'] = _roster_block_end(data,candidate,following,layout)
    by_start = {candidate['start']:candidate for candidate in ordered}
    chains = []
    for candidate in ordered:
        chain = [candidate]
        while len(chain) < 10 and chain[-1]['end'] is not None:
            following = by_start.get(chain[-1]['end'])
            if following is None or following['start'] <= chain[-1]['start']:
                break
            chain.append(following)
        if len(chain) == 10:
            chains.append(chain)
    unique = {chain[0]['start']:chain for chain in chains}
    expected = {(camp,slot) for camp in (1,2) for slot in range(5)}
    if len(unique) == 1:
        pairs = {(block['camp'],block['position']) for block in next(iter(unique.values()))}
        if pairs != expected:
            return [], ['十人玩家块的阵营/槽位不完整，未推断阵容。']
    if len(unique) != 1:
        return [], ['未找到唯一的十人连续玩家块；保留未知，不推断阵营或英雄。']
    chain = next(iter(unique.values()))
    blocks = []
    hero_offset = layout['rosterHeroOffset']
    for order,candidate in enumerate(chain):
        post = (layout['rosterHumanPostBytes'] if candidate['tag'] == 1
                else layout['rosterBotPostBytes'])
        start = candidate['start']+16+candidate['nameLen']+post
        if start+hero_offset+2 > len(data):
            return [], ['十人玩家块中的英雄字段被截断，未推断阵容。']
        hero = int.from_bytes(data[start+hero_offset:start+hero_offset+2],'big')
        if hero not in hero_ids:
            return [], ['十人玩家块中的英雄 ID 不在英雄表内，未推断阵容。']
        blocks.append({'order':order, 'start':candidate['start'], 'heroId':hero,
                       'self':False, 'camp':candidate['camp'],
                       'position':candidate['position'], 'name':candidate['name'],
                       'entityId':candidate['entityId'], 'bot':candidate['tag'] != 1,
                       'blockEnd':candidate.get('end')})
    if len({block['heroId'] for block in blocks}) != 10:
        return [], ['十人玩家块出现重复英雄 ID，未推断阵容。']
    matching = [block for block in blocks if block['heroId'] == local_hero]
    if len(matching) == 1:
        matching[0]['self'] = True
    warnings = []
    if len(matching) != 1:
        warnings.append('未能唯一对应本地英雄；本地玩家身份仍未知。')
    bots = sum(1 for block in blocks if block['bot'])
    if bots:
        warnings.append(f'十人名单含 {bots} 名电脑玩家（块标记 02），不是十名真人。')
    return blocks,warnings


def _discover_variable_human_blocks(data, hero_ids, local_hero=None, layout=None):
    """2026-11 variable-stride ten-human layout.

    Blocks keep the legacy prefix (team/teamEcho/const1/slot/entity/level/
    nameLen/name/post) but their stride varies with profile length, so the
    fixed-stride legacy walker cannot chain them. Scan the pre-frame header
    for the prefix, validate hero IDs at s+0x48, then require exactly ten
    unique entities with five slots per team.
    """
    layout = layout or _DEFAULT_LAYOUT
    limit = min(len(data), layout['rosterScanLimit'])
    starts = []
    index = 0x100
    while index + 16 <= limit:
        team, echo, const1, slot = data[index:index+4]
        if not (team in (1, 2) and echo == team and const1 == 1
                and slot <= 9 and data[index+4:index+6] == b'\0\0'):
            index += 1
            continue
        entity = int.from_bytes(data[index+6:index+8], 'big')
        level = data[index+11]
        name_len = int.from_bytes(data[index+12:index+16], 'big')
        if not (entity and 1 <= level <= 99 and 1 <= name_len <= 64
                and index + 16 + name_len <= len(data)):
            index += 1
            continue
        try:
            name = data[index+16:index+16+name_len].decode('utf-8').rstrip('\x00')
        except UnicodeDecodeError:
            index += 1
            continue
        if not name or any(not c.isprintable() for c in name):
            index += 1
            continue
        s = index + 16 + name_len + 30
        if s + 0x50 > len(data):
            index += 1
            continue
        hero = int.from_bytes(data[s+0x48:s+0x4a], 'big')
        if hero not in hero_ids:
            index += 1
            continue
        starts.append({
            'start': index, 'team': team, 'slot': slot, 'entityId': entity,
            'name': name, 'heroId': hero, 'skinRaw': data[s+0x7a:s+0x7e].hex(),
        })
        index += 16 + name_len
    starts.sort(key=lambda item: item['start'])
    if len(starts) != 10:
        return [], ['未找到唯一的十人变长玩家块。']
    if len({item['entityId'] for item in starts}) != 10:
        return [], ['十人变长玩家块出现重复 entityID。']
    if len({item['heroId'] for item in starts}) != 10:
        return [], ['十人变长玩家块出现重复英雄 ID。']
    for team in (1, 2):
        slots = sorted(item['slot'] for item in starts if item['team'] == team)
        if slots != list(range(5)):
            return [], ['十人变长玩家块的队伍/槽位不完整。']
    blocks = []
    for order, item in enumerate(starts):
        blocks.append({
            'order': order, 'start': item['start'], 'heroId': item['heroId'],
            'self': item['heroId'] == local_hero, 'camp': item['team'],
            'position': item['slot'], 'name': item['name'],
            'entityId': item['entityId'], 'bot': False, 'slot': item['slot'],
            'blockEnd': starts[order+1]['start'] if order+1 < len(starts) else None,
        })
    warnings = []
    if sum(1 for block in blocks if block['self']) != 1:
        warnings.append('未能唯一对应本地英雄；本地玩家身份仍未知。')
    return blocks, warnings


def discover_blocks(data, hero_ids, local_hero=None, layout=None):
    blocks,warnings = _discover_legacy_blocks(data,hero_ids,local_hero,layout)
    if len(blocks) == 10:
        return blocks,warnings
    roster,roster_warnings = _discover_roster_blocks(data,hero_ids,local_hero,layout)
    if len(roster) == 10:
        return roster,roster_warnings
    variable,variable_warnings = _discover_variable_human_blocks(data,hero_ids,local_hero,layout)
    if len(variable) == 10:
        return variable,variable_warnings
    return [], ['未找到唯一的十人连续玩家块；保留未知，不推断阵营或英雄。']


def inflate_raw(data, label, limit=MAX_DECODED_BYTES):
    try:
        decoder = zlib.decompressobj(-15)
        decoded = decoder.decompress(data,limit+1)
    except zlib.error as error:
        raise ReplayFormatError(f'{label}不是完整的 raw DEFLATE 流') from error
    if len(decoded) > limit or decoder.unconsumed_tail:
        raise ReplayFormatError(f'{label}解压结果超过 {limit} 字节上限')
    if not decoder.eof or decoder.unused_data:
        raise ReplayFormatError(f'{label}被截断或存在未解释的尾部数据')
    return decoded


def _locate_second_layer(inner):
    """Find the marker/u32-length pair that starts the operator stream.

    5230306 places it at 0x8A; 5247758 adds six header bytes and moves it to
    0x90. The marker is followed by a raw DEFLATE stream whose declared
    remaining length must equal the rest of the inner buffer.
    """
    upper = min(len(inner)-1,0x200)
    for position in range(0x40,upper):
        if inner[position] != 1:
            continue
        declared = int.from_bytes(inner[position-4:position],'little')
        if declared != len(inner)-position:
            continue
        try:
            stream = inflate_raw(inner[position+1:],'.ope 第二层')
        except ReplayFormatError:
            continue
        if len(stream) >= 27:
            return position,declared,stream
    raise ReplayFormatError('.ope 第二层标记或声明长度不一致')


def parse_ope_bytes(raw):
    if not 6 <= len(raw) <= MAX_FILE_BYTES:
        raise ReplayFormatError('.ope 文件过短或超过大小上限')
    if raw[0] != 1:
        raise ReplayFormatError('不支持该 .ope 外层标记')
    inner = inflate_raw(raw[1:],'.ope 外层')
    if len(inner) < SECOND_DEFLATE_START+2 or inner[:3] != b'\x01\x01\x01':
        raise ReplayFormatError('.ope 内层头不匹配已验证的版本布局')
    texts, offset = [],3
    for i in range(3):
        text,offset = prefixed_text(inner,offset,f'.ope 头部字符串 {i+1}')
        texts.append(text)
    if any(not re.fullmatch(r'12\.1\.1\.\d+',value) for value in texts[:2]):
        raise ReplayFormatError('.ope 版本尚未适配，未使用固定偏移解压')
    second_layer,remaining,operator_stream = _locate_second_layer(inner)
    try:
        events = summarize_operator_stream(operator_stream)
        events_decoded = True
    except OperatorStreamError as error:
        events = {'decoded': False, 'note': f'操作流未解析: {error}'}
        events_decoded = False
    metadata = []
    for pos in range(3,min(len(inner),second_layer)):
        size = inner[pos]
        if not 4 <= size <= 64 or pos+1+size > second_layer:
            continue
        try:
            text=inner[pos+1:pos+1+size].decode('utf-8')
        except UnicodeDecodeError:
            continue
        if all(c.isprintable() for c in text):
            metadata.append(text)
    ids=[s for s in metadata if re.fullmatch(r'[A-Fa-f0-9]{32}',s)]
    dates=[s for s in metadata if re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d',s)]
    return {'size':len(raw),'sha256':digest(raw),'outerHeader':raw[0], 'innerSize':len(inner),
            'versions':texts[:2],'builds':texts[2:], 'matchId':ids[0] if ids else None,
            'timestamp':dates[0] if dates else None, 'secondLayerOffset':second_layer+1,
            'secondLayerMarkerOffset':second_layer,
            'declaredRemainingBytes':remaining, 'operatorStreamBytes':len(operator_stream),
            'operatorStreamSha256':digest(operator_stream), 'operatorHeaderBytes':events.get('streamStart',27),
            'operatorEventsDecoded':events_decoded, 'operatorEvents':events, 'scope':'local-player-operations-candidate',
            'note':'已验证两层解压并解析事件结构；字段语义多为推断，不构成十人状态、技能次数或局内时间。'}


def inspect_tlv(data, layout=None):
    layout = layout or _DEFAULT_LAYOUT
    tlv_start = layout['tlvStart']
    marker=b'\x29\x0e\x00\x00'
    if data[tlv_start+3:tlv_start+7] != marker:
        return {'status':'not_matched','start':None,'records':0,'note':'未匹配样本中的尾部 TLV 起点。'}
    cursor=tlv_start; types=Counter();keys=Counter();seq_min=seq_max=None;previous=None;retreats=0
    while len(data)-cursor >= 8 and data[cursor+3:cursor+7] == marker:
        length=data[cursor+7]
        end=cursor+8+length
        if end > len(data):
            return {'status':'truncated','start':tlv_start,'records':sum(keys.values()),'end':cursor,'note':'TLV 负载被截断。'}
        keys[data[cursor:cursor+3].hex()]+=1
        payload=data[cursor+8:end]
        if len(payload)>=9 and payload[:5] == b'\0'*5:
            seq=int.from_bytes(payload[5:7],'big')
            seq_min=seq if seq_min is None else min(seq_min,seq)
            seq_max=seq if seq_max is None else max(seq_max,seq)
            if previous is not None and seq < previous:
                retreats+=1
            previous=seq
            types[f'{payload[7]:02x}/{payload[8]:02x}']+=1
        cursor=end
    return {'status':'structural-prefix','start':tlv_start,'end':cursor,'records':sum(keys.values()),
            'trailingBytes':len(data)-cursor,'keyKinds':len(keys),'topKeys':keys.most_common(5),
            'typeCounts':dict(sorted(types.items())),'sequenceMin':seq_min,'sequenceMax':seq_max,
            'sequenceRetreats':retreats,'note':'只统计容器结构；类型值未映射到击杀、经济、坐标或技能事件。'}


def _frame_record_end(data, position):
    if position+10 > len(data) or data[position+1] != 0:
        return None
    length = data[position+2]
    end = position+10+length
    return end if end <= len(data) else None


def inspect_frame_stream(data, layout=None):
    """Find the longest seq/pad/L/payload/a/5B/b record chain.

    5069040 samples start at seq 0x22; the 5247758 sample starts at seq 1.
    The 5 bytes between `a` and `b` are not always zero in the newer build,
    so only pad==0 and the stride grammar are required.
    Only the container grammar is counted; payload semantics are not decoded.

    The sequence byte on the wire is 8 bits and wraps, so the reported
    ``lastSequence`` is the unwrapped frame number (``firstSequence + records
    - 1``); the raw field value is kept as ``lastSequenceByte``.
    """
    layout = layout or _DEFAULT_LAYOUT
    limit = min(len(data),layout['frameScanLimit'])
    best = None
    for start in range(0,min(limit,len(data)-10)):
        if data[start+1] != 0:
            continue
        position, sequence, count = start, data[start], 0
        while position+10 <= len(data):
            end = _frame_record_end(data,position)
            if end is None or data[position] != sequence & 0xff:
                break
            count += 1
            sequence += 1
            position = end
        if best is None or count > best['records']:
            best = {'start':start, 'end':position, 'records':count,
                    'firstSequence':data[start]}
            # The scan walks forward, so the first long run is its earliest
            # start; later starts inside the same run are strictly shorter.
            if count >= 1000:
                break
    if not best or best['records'] < 64:
        return {'status':'not_matched','start':None,'records':0,
                'note':'未匹配 seq/pad/L/payload/a/5B/b 记录链。'}
    first = best['firstSequence']
    last = first + best['records'] - 1
    return {'status':'frame-stream','start':best['start'],'end':best['end'],
            'records':best['records'],'firstSequence':first,
            'lastSequence':last,'lastSequenceByte':last & 0xff,
            'sequenceWraps':last > 255,
            'trailingBytes':len(data)-best['end'],
            'note':'只统计记录容器；payload 尚未映射到坐标、经济或技能事件。'}


PLAYER_EVENT_BODY_LENGTHS = {0x80:12, 0x81:22, 0x82:16, 0x85:7, 0x87:7}


def _iter_frame_payloads(data, frames):
    if not frames or frames.get('status') != 'frame-stream':
        return
    position, index = frames['start'], 0
    while position < frames['end']:
        length = data[position+2]
        yield index+1, position, data[position+3:position+3+length]
        position += 10+length
        index += 1


def _iter_payload_messages(payload):
    """Yield complete top-level messages; stop at the first unknown shape."""
    if not payload:
        return
    index, size = 1, len(payload)
    while index < size:
        tag = payload[index]
        if tag == 0x12:
            index += 3
            continue
        if tag == 0x13:
            index += 2
            continue
        if tag == 0x14:
            index += 4
            continue
        if tag == 0x01:
            if index+5 > size:
                return
            length = payload[index+4]
            if index+5+length > size:
                return
            yield ('01', int.from_bytes(payload[index+1:index+3],'big'),
                   payload[index+3], payload[index+5:index+5+length])
            index += 5+length
            continue
        if tag == 0x02:
            if index+4 > size:
                return
            entity = int.from_bytes(payload[index+1:index+3],'big')
            subtype = payload[index+3]
            length = PLAYER_EVENT_BODY_LENGTHS.get(subtype)
            if length is None or index+4+length > size:
                return
            yield ('02', entity, subtype, payload[index+4:index+4+length])
            index += 4+length
            continue
        return


def _dedupe(events, keys):
    seen, unique = set(), []
    for event in events:
        signature = tuple(event[key] for key in keys)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(event)
    return unique, len(events)-len(unique)


def inspect_player_events(data, frames):
    """Extract the tail-stream 0x85 buy echo, 0x87 skill and 0x82 position messages.

    The 7-byte 0x85 body is `[equip_id:u16BE][pad:u8 x3][objectId:u8][flag:u8]`
    and mirrors each BUYEQUIP frame command one-to-one (docs 5.130): all event
    frames coincide with purchase commands and the equip ids match. It carries
    no gold amounts, so no income ledger can be built from the tail stream.
    """
    if not frames or frames.get('status') != 'frame-stream':
        return None
    buy_echo, skills, positions = [], [], []
    for frame, offset, payload in _iter_frame_payloads(data, frames):
        for tag, entity, subtype, body in _iter_payload_messages(payload):
            if tag != '02':
                continue
            if subtype == 0x85:
                buy_echo.append({'frame':frame,'offset':offset,'entityId':entity,
                                 'equipId':int.from_bytes(body[0:2],'big'),
                                 'objectId':body[5],
                                 'flag':body[6]})
            elif subtype == 0x87:
                skills.append({'frame':frame,'offset':offset,'entityId':entity,
                               'actorId':int.from_bytes(body[2:4],'big'),
                               'skill':body[4],'levelIndex':body[5]})
            elif subtype == 0x82:
                positions.append({'frame':frame,'offset':offset,'entityId':entity,
                                  'kind':body[0],
                                  'x':int.from_bytes(body[1:5],'big',signed=True),
                                  'y':int.from_bytes(body[5:9],'big',signed=True),
                                  'tail':body[9:].hex()})
    buy_echo, echo_duplicates = _dedupe(buy_echo,('frame','entityId','equipId','objectId','flag'))
    skills, skill_duplicates = _dedupe(skills,('frame','entityId','actorId','skill','levelIndex'))
    echo_by_entity = {}
    for event in buy_echo:
        entry = echo_by_entity.setdefault(str(event['entityId']),{'events':0})
        entry['events'] += 1
    skills_by_entity = {}
    for event in skills:
        entry = skills_by_entity.setdefault(str(event['entityId']),{'events':0})
        entry['events'] += 1
    positions_by_entity = {}
    for event in positions:
        entry = positions_by_entity.setdefault(str(event['entityId']),{'samples':0,'kinds':{}})
        entry['samples'] += 1
        kind = str(event['kind'])
        entry['kinds'][kind] = entry['kinds'].get(kind,0)+1
    return {'status':'raw-events',
            'buyEcho':{'records':len(buy_echo)+echo_duplicates,'unique':len(buy_echo),
                       'duplicates':echo_duplicates,
                       'byEntity':echo_by_entity,'events':buy_echo},
            'skills':{'unique':len(skills),'duplicates':skill_duplicates,
                      'byEntity':skills_by_entity,'events':skills},
            'positions':{'records':len(positions),'byEntity':positions_by_entity,
                         'events':positions},
            'note':'0x85=购买镜像/0x87/0x82 只覆盖回放写入的真人消息；尾部流没有金币收入事件，'
                   '坐标标尺未校准。'}


def inspect_score_table(data, entity_ids):
    """Find the postgame ten-player score table in the trailing bytes.

    5247758 appends ten u32BE pairs (entityID, score x100) after the frame
    stream. 5069040/5230306 did not expose this table; the value is a client
    aggregate, not a raw per-event field.
    """
    ids = list(dict.fromkeys(entity_ids))
    if len(ids) < 10:
        return None
    wanted = set(ids)
    start = max(0,len(data)-0x1000)
    for position in range(start,len(data)-8*len(ids)+1):
        entries, seen, valid = [], set(), True
        for index in range(len(ids)):
            entity = int.from_bytes(data[position+8*index:position+8*index+4],'big')
            value = int.from_bytes(data[position+8*index+4:position+8*index+8],'big')
            if entity not in wanted or entity in seen or not 0 < value <= 10000:
                valid = False
                break
            seen.add(entity)
            entries.append({'entityId':entity,'scoreRaw':value,'score':value/100})
        if valid and seen == wanted:
            return {'status':'score-table','offset':position,'players':entries,
                    'note':'赛后十人评分为汇总字段（×100），不是原始 KDA、经济或伤害流水。'}
    return None


def _mvp_player(blocks, entity_id):
    block = next((item for item in blocks if item.get('entityId') == entity_id), None)
    if not block:
        return {'entityId': entity_id}
    return {'entityId': entity_id, 'nickname': block.get('name'),
            'hero': block.get('heroName'), 'heroId': block.get('heroId'),
            'camp': 'blue' if block.get('camp') == 1 else 'red' if block.get('camp') == 2 else None,
            'slot': block.get('position'), 'rating': block.get('score'),
            'bot': bool(block.get('bot'))}


def inspect_mvp_score(data, blocks, score_table):
    """Decode the 1251 SCPKG_GAMEOVER_MVPSCORE tail used by 5247758.

    Layout: 21-byte header (msgID 1251 at +2, win MVP u32BE at +16,
    score count at +20), 10 x (entity u32BE, score x100 u32BE), then
    u32 loseMvpCount + loseMvpEntityID list.  The win/lose camp is
    derived from the roster entity IDs; it is not a separate bWinCamp field.
    """
    if not score_table:
        return None
    start = score_table['offset'] - 21
    if start < 0 or start + 109 > len(data):
        return None
    if int.from_bytes(data[start+2:start+4], 'big') != 1251:
        return None
    win_id = int.from_bytes(data[start+16:start+20], 'big')
    lose_count = int.from_bytes(data[start+101:start+105], 'big')
    if not 0 <= lose_count <= 10:
        return None
    lose_ids = []
    for index in range(lose_count):
        offset = start + 105 + 4 * index
        if offset + 4 > len(data):
            break
        lose_ids.append(int.from_bytes(data[offset:offset+4], 'big'))
    win = _mvp_player(blocks, win_id)
    lose = [_mvp_player(blocks, entity_id) for entity_id in lose_ids]
    winning_camp = win.get('camp')
    if winning_camp is None and lose and lose[0].get('camp'):
        winning_camp = 'red' if lose[0]['camp'] == 'blue' else 'blue'
    return {'status': 'mvp-score', 'winMvpEntityId': win_id,
            'loseMvpEntityIds': lose_ids, 'winningCamp': winning_camp,
            'winMvp': win, 'loseMvp': lose, 'offset': start,
            'note': '1251 SCPKG_GAMEOVER_MVPSCORE：胜方 MVP + 十人评分 + 败方 MVP；胜负由 MVP 阵营反推。'}


def inspect_abc(abc, hero_names=None):
    """Decode one .abc container (never its .ope).

    Cached by content hash when the caller does not pass its own hero map, so
    the upload check and the import parse share one decode.
    """
    if not 39 <= len(abc) <= MAX_FILE_BYTES:
        raise ReplayFormatError('.abc 文件过短或超过 16 MB 上限')
    cacheable = hero_names is None
    if cacheable:
        cached = _cache_get(digest(abc))
        if cached is not None:
            return cached
        from vision import catalog
        hero_names={int(e['id'].split('-')[1]):e['name'] for e in catalog()['entries'] if e['kind']=='hero'}
    header=parse_header(abc)
    profile=resolve_profile(header['versions'],header['builds'])
    warnings=[]; frames=None; player_events=None
    if header['layoutSupported']:
        layout=layout_for(profile)
        blocks, warnings=discover_blocks(abc,set(hero_names),header['localHeroId'],layout)
        tlv=inspect_tlv(abc,layout)
        if tlv['status'] != 'structural-prefix':
            frames=inspect_frame_stream(abc,layout)
            player_events=inspect_player_events(abc,frames)
    else:
        blocks=[];tlv={'status':'not_supported','records':0}
        warnings.append('仅头部版本可读；该版本未配置解析档案，'
                        '未复用其他版本的偏移（resources/replay_profiles.json）。')
    for block in blocks:
        block['heroName']=hero_names.get(block['heroId'])
    header['localHeroName']=hero_names.get(header['localHeroId'])
    if frames and frames['status'] == 'frame-stream':
        if player_events and player_events['status'] == 'raw-events':
            warnings.append(f'帧流识别到 {frames["records"]} 条记录；0x85/0x87/0x82 已解析，其他标签未解。')
        else:
            warnings.append(f'帧流按容器结构识别到 {frames["records"]} 条记录；payload 语义尚未解码。')
    blocks_layout = ('roster-5247758' if blocks and 'name' in blocks[0]
                     else 'legacy-1517' if blocks else None)
    score_table = None
    if blocks_layout == 'roster-5247758':
        score_table = inspect_score_table(abc,[block['entityId'] for block in blocks])
        if score_table:
            scores = {entry['entityId']:entry['score'] for entry in score_table['players']}
            for block in blocks:
                block['score'] = scores.get(block['entityId'])
        if player_events:
            for block in blocks:
                entity = str(block.get('entityId'))
                echo = player_events['buyEcho']['byEntity'].get(entity)
                if echo:
                    block['buyEvents'] = echo['events']
                skills = player_events['skills']['byEntity'].get(entity)
                if skills:
                    block['skillEvents'] = skills['events']
                samples = player_events['positions']['byEntity'].get(entity)
                if samples:
                    block['positionSamples'] = samples['samples']
    mvp_score = inspect_mvp_score(abc, blocks, score_table) if blocks_layout == 'roster-5247758' else None
    if blocks_layout == 'roster-5247758':
        if mvp_score and mvp_score['winningCamp']:
            warnings.append('已读出十人阵营、槽位、电脑标记，以及 1251 的胜负/MVP/评分；分路和完整过程状态仍未解码，不进入胜率统计。')
        else:
            warnings.append('已读出十人阵营、槽位与电脑标记；分路、完整过程状态和胜负仍未解码，不进入胜率统计。')
    else:
        warnings.append('单一版本样本的实验解析；十人阵营、分路和完整过程状态仍未知，不进入胜率统计。')
    if player_events and player_events['buyEcho']['unique']:
        warnings.append(f'尾部流购买镜像 {player_events["buyEcho"]["unique"]} 条，与 BUYEQUIP 命令一一对应；'
                        '尾部流没有金币收入事件，不能据此重建收入账本。')
    report = {'parserVersion':PROFILE,'profileId':header.get('profile'),
            'profileSource':header.get('profileSource'),
            'abc':{'size':len(abc),'sha256':digest(abc)},'header':header,
            'blocks':blocks,'blocksLayout':blocks_layout,'tlv':tlv,'frames':frames,
            'scoreTable':score_table,'mvpScore':mvp_score,'playerEvents':player_events,
            'ope':None,
            'pairingStatus':'abc-only',
            'provenance':{
                'container':{'source':'abc-container','confidence':'decoded'},
                'playerBlocks':{'source':'abc-container','confidence':'decoded'},
                'events':{'source':'abc-frame-commands','confidence':'decoded'},
                'positions':{'source':'abc-input-direction','confidence':'estimated'},
                'gameplayState':{'source':'none','confidence':'undecoded'},
            },
            'confidence':{'container':'decoded','playerBlocks':'decoded',
                          'events':'decoded','positions':'estimated',
                          'gameplayState':'undecoded'},
            'warnings':warnings,'gameplayStateDecoded':False}
    if cacheable:
        _cache_put(report)
    return report


def inspect_replay(abc, ope=None, hero_names=None):
    """Decode a .abc and, when given, pair it with its .ope."""
    report = inspect_abc(abc, hero_names)
    if ope is None:
        return report
    header = report['header']
    blocks = report['blocks']
    operator = parse_ope_bytes(ope)
    if operator['versions'] != header['versions']:
        raise ReplayFormatError('.abc 与 .ope 的版本不一致，未作为配对回放保存')
    pairing_status = 'user-selected-unverified'
    tag = operator.get('matchId')
    matched = False
    if tag:
        raw = tag.encode()
        candidates = [block for block in blocks if block.get('self')] or blocks
        for block in candidates:
            end = block.get('blockEnd') or len(abc)
            if raw in abc[block['start']:end]:
                matched = True
                break
    if matched:
        pairing_status = 'recorder-tag-matched'
        report['warnings'].append(
            '同局标签匹配：.abc 录制者块内出现与 .ope 相同的 32 位标签。')
    else:
        report['warnings'].append(
            '配对由用户指定；版本一致不证明属于同一局，尚未交叉核验对局 ID。')
    report['ope'] = operator
    report['pairingStatus'] = pairing_status
    return report
