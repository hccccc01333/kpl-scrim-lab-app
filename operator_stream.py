"""Sequential decoder for the .ope operator stream (observed 12.1.1.x profile).

The stream is a flat sequence of type-delimited records without an outer
length prefix, so variable-length records (Touch/Move/SkillUse/GameCoreFrame
…) have no locally decodable boundary. Boundaries are resolved globally: a
dynamic program over the whole stream picks, for every candidate start, the
record layout whose suffix to end-of-stream needs the fewest tentative
records. Ties are genuine ambiguities and are counted in the summary.

UILayout (0x16) is not a raw length-prefixed payload: after the u16 tag it
carries exactly 75 ULEB128 values.  That count is identical in 44/44 local
samples spanning builds 4442288/4750749/4989537/5230306, and the 75th value
always ends immediately before a SkillSlotOpe run.  The old
``stream[7:11]`` length field and the 27-byte stream header were artifacts
of older builds; ``parse_stream`` now probes both offset 0 and the legacy
HEADER_BYTES and keeps whichever reaches further.

Record type bytes are the emOperatorDataType enum (global-metadata.dat,
assets under Assets.Scripts.OperatorMonitor): 0x00 Common … 0x19
DeadOrReviveOpe, with 0x1A/0x1B as Num/Max sentinels. Type bytes ≥ 0x1A
cannot start a record; class field lists come from the same metadata.

MemoryData (0x10) has two disjoint forms.  A payload form is
``frame + lenvar(data)``: 11/1 frames 424/4618/46849/28437 carry 45/63/98/2
byte memory blobs (the 45-byte blob repeats and contains ASCII "null").
Frames 256..267 are different: the third field is the local unity clock, not
a length, because those bytes are the tail of a preceding Move/Skil record
(``… 10 <frame> <unity>``).  Treating them as payloads produced the fake
18,748/24,946/30,116-byte jumps; the payload layout is therefore gated to
frames outside 256..267.

This parses container and event structure only. Field names beyond
frame/unityFrame/eventId are inferred from client metadata class fields and
stay positional; nothing here maps to ten-player state, kills or economy.
"""
from collections import Counter

HEADER_BYTES = 27
STREAM_PARSE_LIMIT = 4 * 1024 * 1024
LAYOUT_PAYLOAD_CAP = 4096

PROFILE = 'ope-stream-observed-12.1.1.x-v3'

TYPE_NAMES = {
    0x00: 'Common', 0x01: 'UnityFrameOpe', 0x02: 'GameCoreFrameOpe',
    0x03: 'SkillUseOpe', 0x04: 'SkilOpe', 0x05: 'TouchOpe', 0x06: 'MoveOpe',
    0x07: 'CoreChangeOpe', 0x08: 'SkillBtnForceUpOpe',
    0x09: 'RefreshSkillBtnStatusOpe', 0x0A: 'UIntOpe', 0x0B: 'UIEventOpe',
    0x0C: 'CppEventOpe', 0x0D: 'BtnBrokenContactOpe',
    0x0E: 'GameObjectNameOpe', 0x0F: 'UIViewChangeOpe', 0x10: 'MemoryData',
    0x11: 'CustomLog', 0x12: 'SkillHitRate', 0x13: 'SkillSlotOpe',
    0x14: 'SkillCancelOpe', 0x15: 'DirSkillOpe', 0x16: 'UILayout',
    0x17: 'PredictMoveOpe', 0x18: 'SendMsgToServerOpe',
    0x19: 'DeadOrReviveOpe',
}


class OperatorStreamError(ValueError):
    pass


# Field ops: ('frame',), ('varint', name), ('u8', name), ('u16', name),
# ('u24', name), ('u32', name), ('raw', size), ('len8', name) = u8 length +
# bytes, ('lenvar', name) = varint length + bytes, ('varints', name, count) =
# exactly ``count`` varints, ('frame_in', lo, hi) / ('frame_not_in', lo, hi) =
# value gates on the already parsed ``frame`` (the plan returns None when the
# frame is outside/inside the range), used to keep same-type subtypes apart.
# Multiple layouts per type are candidates; the DP
# prefers fewest tentative records, then listed order. `tentative` layouts are
# derived from metadata class fields but not yet validated against the sample;
# `confirmed` ones were observed repeatedly.
CONFIRMED, TENTATIVE = 0, 1
LAYOUTS = {
    0x00: [(CONFIRMED, [('frame',)]),
           (CONFIRMED, [('frame',), ('varint', 'unityFrame')])],
    0x01: [(CONFIRMED, [('varint', 'unityFrame')])],
    0x02: [(CONFIRMED, [('frame',), ('varint', 'unityFrame')]),
           (CONFIRMED, [('frame',)])],
    0x03: [(CONFIRMED, [('frame',), ('varint', 'slotType'), ('varint', 'skillId'),
                        ('varint', 'skillSeq'), ('varint', 'unityFrame')]),
           (CONFIRMED, [('frame',), ('varint', 'slotType'), ('varint', 'skillId'),
                        ('varint', 'skillSeq')]),
           (TENTATIVE, [('frame',), ('varint', 'x1'), ('varint', 'x2'), ('varint', 'x3'),
                        ('varint', 'x4'), ('varint', 'x5')]),
           (TENTATIVE, [('frame',), ('varint', 'x1'), ('varint', 'x2'), ('varint', 'x3'),
                        ('varint', 'x4'), ('varint', 'x5'), ('varint', 'x6')]),
           (TENTATIVE, [('frame',), ('varint', 'x1'), ('varint', 'x2'), ('varint', 'x3'),
                        ('varint', 'x4'), ('varint', 'x5'), ('varint', 'x6'), ('varint', 'x7')])],
    0x04: [(CONFIRMED, [('frame',), ('varint', 'x'), ('varint', 'y')]),
           (CONFIRMED, [('frame',), ('varint', 'x'), ('varint', 'y'), ('varint', 'slot')]),
           (CONFIRMED, [('frame',), ('varint', 'x'), ('varint', 'y'), ('varint', 'slot'),
                        ('varint', 'touchId')]),
           (CONFIRMED, [('frame',), ('varint', 'x'), ('varint', 'y'), ('varint', 'slot'),
                        ('varint', 'touchId'), ('varint', 'unityFrame')]),
           (CONFIRMED, [('frame',), ('varint', 's1'), ('varint', 's2'), ('varint', 's3'),
                        ('varint', 's4'), ('varint', 's5'), ('varint', 's6')])],
    0x05: [(CONFIRMED, [('frame',), ('varint', 't1'), ('varint', 't2'), ('varint', 't3'),
                        ('varint', 't4')]),
           (CONFIRMED, [('frame',), ('varint', 't1'), ('varint', 't2'), ('varint', 't3'),
                        ('varint', 't4'), ('varint', 't5')])],
    0x06: [(CONFIRMED, [('frame',), ('varint', 'degree'), ('varint', 'gameSvrPing'),
                        ('varint', 'seq')]),
           # 11/2 build 5247758: 9-byte MoveOpe records in long clean runs
           # (e.g. 0x233..0x37E) carry four varints and are byte-aligned on
           # every following 06 88 01; the fourth is the monotone unity clock.
           (CONFIRMED, [('frame',), ('varint', 'm1'), ('varint', 'm2'),
                        ('varint', 'm3'), ('varint', 'unityFrame')]),
           (CONFIRMED, [('frame',), ('varint', 'm1'), ('varint', 'm2'), ('varint', 'm3'),
                        ('varint', 'm4'), ('varint', 'm5')]),
           (CONFIRMED, [('frame',), ('varint', 'm1'), ('varint', 'm2'), ('varint', 'm3'),
                        ('varint', 'm4'), ('varint', 'm5'), ('varint', 'm6')]),
           (CONFIRMED, [('frame',), ('varint', 'm1'), ('varint', 'm2'), ('varint', 'm3'),
                        ('varint', 'm4'), ('varint', 'm5'), ('varint', 'm6'), ('varint', 'm7')]),
           # 11/2 build 5247758: the record after UILayout needs an eighth
           # varint; without it the stream falsely walls at 0x24B/0x3E5.
           (TENTATIVE, [('frame',), ('varint', 'm1'), ('varint', 'm2'), ('varint', 'm3'),
                        ('varint', 'm4'), ('varint', 'm5'), ('varint', 'm6'), ('varint', 'm7'),
                        ('varint', 'm8')])],
    0x07: [(TENTATIVE, [('frame',), ('varint', 'c1'), ('varint', 'c2'), ('varint', 'c3'),
                        ('varint', 'c4'), ('varint', 'c5')]),
           (TENTATIVE, [('frame',), ('varint', 'c1'), ('varint', 'c2'), ('varint', 'c3'),
                        ('varint', 'c4')]),
           (TENTATIVE, [('frame',), ('varint', 'c1'), ('varint', 'c2'), ('varint', 'c3')])],
    0x08: [(TENTATIVE, [('frame',), ('u8', 'buttonState')]),
           (TENTATIVE, [('frame',), ('varint', 'buttonState')])],
    0x09: [(TENTATIVE, [('frame',), ('varint', 'forceUseWhenLimited'), ('varint', 'disableFlags'),
                        ('varint', 'slotType')]),
           (TENTATIVE, [('frame',), ('varint', 'forceUseWhenLimited'), ('varint', 'disableFlags')])],
    0x0A: [(CONFIRMED, [('frame',), ('u32', 'value')]),
           (TENTATIVE, [('frame',), ('varint', 'value')]),
           # 11/2 build 5247758: `0a 12 00 00 00 00 18 b6 01 6d 9d …` occurs
           # in both 11/2 games; a six-byte UInt (frame + three value bytes)
           # ends exactly on the following SendMsgToServerOpe `18 b6 01`.
           # With only the four-byte varint layout the same bytes get read
           # as UInt+Common and the stream falsely walls at 0x6F2D/0xECDA.
           (TENTATIVE, [('frame',), ('u24', 'value')])],
    0x0B: [(CONFIRMED, [('u8', 'tag'), ('varint', 'eventId')]),
           (CONFIRMED, [('varint', 'eventId')]),
           (TENTATIVE, [('frame',), ('varint', 'eventId')])],
    0x0C: [(CONFIRMED, [('u8', 'slotType'), ('varint', 'skillId'), ('varint', 'value')]),
           (CONFIRMED, [('u8', 'slotType'), ('varint', 'skillId')]),
           (CONFIRMED, [('u8', 'slotType'), ('varint', 'skillId'), ('varint', 'value'),
                        ('varint', 'extra')]),
           (TENTATIVE, [('frame',), ('u8', 'slotType'), ('varint', 'skillId'), ('varint', 'value')])],
    0x0D: [(TENTATIVE, [('frame',), ('varint', 'rawGameObjectInstId')])],
    0x0E: [(CONFIRMED, [('frame',), ('varint', 'instId'), ('len8', 'path')])],
    0x0F: [(TENTATIVE, [('frame',), ('u8', 'viewType'), ('u8', 'open')]),
           (TENTATIVE, [('frame',), ('u8', 'viewType')])],
    0x10: [  # The observed 11/1 dumps are `frame + byte-length payload`
           # (frames 424/4618/46849/28437 with 45/63/98/2-byte payloads; the
           # 45-byte blob repeats and contains ASCII "null").  11/2 also has
           # payload-form dumps with 500-series frames (e.g. 520 + 9,750 B).
           #
           # Frames 256..267 are NOT a payload form.  In all nine big 11/2
           # candidates the third field is the unity clock (previous record
           # +1..4, next UnityFrame -1..3), because those bytes are actually
           # the tail of a preceding Move/Skil record (`… 10 <frame> <unity>`)
           # that the DP cut one varint short.  Treating them as 30 KB payloads
           # created the fake walls at 0x1991E/0x38D26; the linear parse reads
           # the same bytes as records instead.
           (CONFIRMED, [('frame',), ('frame_not_in', 256, 267),
                        ('lenvar', 'data')])],
    0x11: [(TENTATIVE, [('frame',), ('len8', 'log')]),
           (TENTATIVE, [('frame',), ('lenvar', 'log')])],
    0x12: [(TENTATIVE, [('frame',), ('varint', 'skillId'), ('varint', 'skillSeq'),
                        ('varint', 'defaultTargetId'), ('varint', 'flags'), ('varint', 'shape')]),
           (TENTATIVE, [('frame',), ('varint', 'skillId'), ('varint', 'skillSeq'),
                        ('varint', 'defaultTargetId'), ('varint', 'flags')]),
           (TENTATIVE, [('frame',), ('varint', 'h1'), ('varint', 'h2'), ('varint', 'h3')])],
    0x13: [(CONFIRMED, [('frame',), ('u8', 'slot'), ('u8', 'value')]),
           (CONFIRMED, [('frame',), ('u8', 'slot')])],
    0x14: [(CONFIRMED, [('frame',), ('varint', 'skillId'), ('varint', 'cancelTime'),
                        ('varint', 'cancelDistance'), ('varint', 'openDebug')]),
           (CONFIRMED, [('frame',), ('varint', 'skillId'), ('varint', 'cancelTime'),
                        ('varint', 'cancelDistance')])],
    0x15: [(CONFIRMED, [('frame',), ('varint', 'skillId'), ('varint', 'seq'),
                        ('varint', 'param1'), ('varint', 'param2')]),
           # 11/2b 0x7EF3: `15 6f 02 a4 99 01 08 37 e9 02 e2 0c` is followed
           # by CppEvent `0c 04 02 00 08`.  The fifth varint ends exactly on
           # that boundary and the CppEvent's extra repeats seq (8); without
           # it the stream walls at 0x7EFD.
           (TENTATIVE, [('frame',), ('varint', 'skillId'), ('varint', 'seq'),
                        ('varint', 'param1'), ('varint', 'param2'),
                        ('varint', 'extra')]),
           # 11/2: every `15 6f 02 …` block is followed by CppEventOpe
           # `0c 04 02 00 <seq>`; the four varints end exactly on that
           # boundary (e.g., 0x1B41 and 39 repeats in 20261102_161129).
           (TENTATIVE, [('frame',), ('varint', 'degree')])],
    0x16: [(CONFIRMED, [('u16', 'tag'), ('varints', 'layout', 75)]),
           # Legacy fallback: a raw u16-length payload.  The length was read
           # from stream[7:11] in older builds; only usable when that field is
           # in range, so it is kept tentative and never decides a boundary
           # unless the 75-varint layout is impossible.
           (TENTATIVE, [('frame',), ('raw', None)])],
    0x17: [(TENTATIVE, [('frame',), ('varint', 'iParam1'), ('varint', 'iParam2'),
                        ('varint', 'byteParam')]),
           (TENTATIVE, [('frame',), ('varint', 'iParam1'), ('varint', 'iParam2')])],
    0x18: [(TENTATIVE, [('frame',), ('u16', 'csMsgId'), ('u8', 'result')]),
           (TENTATIVE, [('frame',), ('varint', 'csMsgId'), ('varint', 'result')]),
           (TENTATIVE, [('frame',), ('u8', 'csMsgId'), ('u8', 'result')])],
    0x19: [(TENTATIVE, [('frame',), ('varint', 'hostPlayerId'), ('varint', 'curPlayerId'),
                        ('varint', 'reviveTime'), ('varint', 'configId'), ('varint', 'isHostPlayer'),
                        ('varint', 'isDead'), ('varint', 'bSuicide'), ('varint', 'bImmediateRevive')]),
           (TENTATIVE, [('frame',), ('varint', 'hostPlayerId'), ('varint', 'curPlayerId'),
                        ('varint', 'reviveTime'), ('varint', 'configId')]),
           (TENTATIVE, [('frame',), ('varint', 'hostPlayerId'), ('varint', 'curPlayerId'),
                        ('varint', 'reviveTime')])],
}


def _varint(data, pos):
    value = 0
    shift = 0
    while True:
        if pos >= len(data):
            raise IndexError
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
        if shift > 35:
            raise IndexError


def _consume(data, pos, layout_payload_size, plan):
    fields = {}
    start = pos
    pos += 1
    try:
        for op in plan:
            kind = op[0]
            if kind == 'frame':
                fields['frame'] = int.from_bytes(data[pos:pos + 2], 'little')
                pos += 2
            elif kind == 'varint':
                fields[op[1]], pos = _varint(data, pos)
            elif kind == 'u8':
                fields[op[1]] = data[pos]
                pos += 1
            elif kind == 'u16':
                fields[op[1]] = int.from_bytes(data[pos:pos + 2], 'little')
                pos += 2
            elif kind == 'u24':
                fields[op[1]] = int.from_bytes(data[pos:pos + 3], 'little')
                pos += 3
            elif kind == 'u32':
                fields[op[1]] = int.from_bytes(data[pos:pos + 4], 'little')
                pos += 4
            elif kind == 'frame_in':
                # Subtype gate: the plan only applies when the field that was
                # just read as ``frame`` is inside [lo, hi].
                if not (op[1] <= fields.get('frame', -1) <= op[2]):
                    return None
            elif kind == 'frame_not_in':
                if op[1] <= fields.get('frame', -1) <= op[2]:
                    return None
            elif kind == 'raw':
                if layout_payload_size is None:
                    return None
                size = layout_payload_size if op[1] is None else op[1]
                pos += size
            elif kind == 'varints':
                values = []
                for _ in range(op[2]):
                    value, pos = _varint(data, pos)
                    values.append(value)
                fields[op[1]] = values
            elif kind == 'len8':
                size = data[pos]
                pos += 1
                fields[op[1]] = data[pos:pos + size].decode('utf-8', 'replace')
                pos += size
            elif kind == 'lenvar':
                size, pos = _varint(data, pos)
                if size > len(data) - pos:
                    return None
                fields[op[1]] = data[pos:pos + size]
                pos += size
    except IndexError:
        return None
    if pos > len(data):
        return None
    return {'offset': start, 'end': pos, 'fields': fields}


def _reachable(data, layout_payload_size, start=None):
    """Forward pass: every position a candidate record can start on."""
    if start is None:
        start = HEADER_BYTES
    seen = set()
    stack = [start]
    while stack:
        pos = stack.pop()
        if pos in seen or pos >= len(data):
            continue
        seen.add(pos)
        if data[pos] not in LAYOUTS:
            continue
        for _tier, plan in LAYOUTS[data[pos]]:
            record = _consume(data, pos, layout_payload_size, plan)
            if record is not None and record['end'] not in seen:
                stack.append(record['end'])
    return seen


def _layout_payload_size(stream):
    """Legacy stream[7:11] length; None when it cannot feed the raw fallback."""
    size = int.from_bytes(stream[7:11], 'little') if len(stream) >= 11 else 0
    return size if 1 <= size <= LAYOUT_PAYLOAD_CAP else None


def _probe_starts(stream, layout_payload_size, starts):
    """Run the forward pass from each candidate start; keep the best one.

    11/2 streams start a record at offset 0, while older samples carried a
    27-byte prefix.  A start that can consume the stream to EOF wins, with
    the usual tentative-bytes cost as tie-break; when no start reaches EOF,
    the furthest structural reach wins.  Both are boundary evidence, not
    semantic claims.
    """
    completed = []
    frontier = []
    for start in starts:
        if start >= len(stream):
            continue
        reachable = _reachable(stream, layout_payload_size, start)
        if not reachable:
            continue
        try:
            records, _ambiguities = _resolve(stream, reachable,
                                             layout_payload_size, start)
        except OperatorStreamError:
            records = None
        if records is None:
            frontier.append(((max(reachable), len(reachable)), start, reachable))
            continue
        tentative_bytes = sum(record['size'] for record in records
                              if record['tentative'])
        tentative_count = sum(1 for record in records if record['tentative'])
        completed.append(((tentative_bytes, tentative_count, len(records)),
                          start, reachable))
    if completed:
        _score, start, reachable = min(completed)
        return start, reachable
    if not frontier:
        raise OperatorStreamError('操作流为空或起点超出范围')
    _score, start, reachable = max(frontier)
    return start, reachable


def _parse_with_start(stream, starts=None):
    """Decode the whole stream and report the winning record start.

    ``starts=None`` probes offset 0 and the legacy HEADER_BYTES and keeps the
    one that reaches further (used for real files); an explicit tuple pins the
    start (used by synthetic tests and callers that know the layout).
    """
    if len(stream) < 2:
        raise OperatorStreamError('操作流总头被截断')
    if len(stream) > STREAM_PARSE_LIMIT:
        raise OperatorStreamError(f'操作流超过 {STREAM_PARSE_LIMIT} 字节，未解析事件')
    layout_payload_size = _layout_payload_size(stream)
    if starts is None:
        starts = (0, HEADER_BYTES) if HEADER_BYTES else (0,)
    start, reachable = _probe_starts(stream, layout_payload_size, starts)
    try:
        records, ambiguities = _resolve(stream, reachable, layout_payload_size, start)
    except OperatorStreamError as error:
        raise OperatorStreamError(f'{error}；起点 offset={start:#x}') from error
    return records, ambiguities, start


def parse_stream(stream, start=None):
    """Decode the whole operator stream. Returns (records, ambiguities).

    Each record: {type, typeName, offset, size, tentative, fields…}.
    `tentative` records use layouts derived from metadata fields that the
    sample has not yet validated.  ``start=None`` uses HEADER_BYTES; pass
    ``start=0`` for streams whose first record is at offset 0.
    """
    starts = (HEADER_BYTES,) if start is None else (start,)
    records, ambiguities, _start = _parse_with_start(stream, starts)
    return records, ambiguities


def _resolve(stream, reachable, layout_payload_size, start=None):
    """Minimum-uncertainty DP. Cost is (tentative bytes, tentative segments,
    record count) in lexicographic order: keep bytes on confirmed layouts,
    avoid tentative layouts, then prefer fewer records."""
    if start is None:
        start = HEADER_BYTES
    order = sorted(reachable)
    best = {len(stream): (0, 0, 0)}
    choice = {}
    for pos in reversed(order):
        type_byte = stream[pos]
        options = []
        for tier, plan in LAYOUTS.get(type_byte, ()):
            record = _consume(stream, pos, layout_payload_size, plan)
            if record is None or record['end'] not in best:
                continue
            tail_bytes, tail_segments, tail_count = best[record['end']]
            size = record['end'] - pos
            if tier == TENTATIVE:
                cost = (size + tail_bytes, 1 + tail_segments, 1 + tail_count)
            else:
                cost = (tail_bytes, tail_segments, 1 + tail_count)
            options.append((cost, tier, plan, record))
        if not options:
            continue
        min_cost = min(option[0] for option in options)
        best[pos] = min_cost
        choice[pos] = [option for option in options if option[0] == min_cost]
    records = []
    ambiguities = 0
    pos = start
    while pos < len(stream):
        if pos not in choice:
            frontier = max(reachable)
            raise OperatorStreamError(
                f'操作流无法用 0x00–0x19 已知形态完整解析到结尾；'
                f'最远推进到 {frontier:#x}（type={stream[frontier]:#04x}，'
                f'context {stream[frontier:frontier + 16].hex(" ")}）；'
                f'当前卡在 {pos:#x}（type={stream[pos]:#04x}）')
        tied = choice[pos]
        if len(tied) > 1:
            ambiguities += 1
        _, tier, plan, record = tied[0]
        record['type'] = stream[pos]
        record['typeName'] = TYPE_NAMES.get(stream[pos], f'{stream[pos]:#04x}')
        record['size'] = record['end'] - record['offset']
        record['tentative'] = tier == TENTATIVE
        del record['end']
        records.append(record)
        pos += record['size']
    return records, ambiguities


def summarize(stream, start=None):
    """Aggregate summary for the workspace report (no raw record dump)."""
    starts = None if start is None else (start,)
    records, ambiguities, start = _parse_with_start(stream, starts)
    type_counts = Counter(record['typeName'] for record in records)
    frames = [record['fields']['frame'] for record in records
              if not record['tentative'] and 'frame' in record['fields']]
    unity_frames = [record['fields']['unityFrame'] for record in records
                    if not record['tentative'] and 'unityFrame' in record['fields']]
    confirmed = [record for record in records if not record['tentative']]
    unresolved = [record for record in records if record['tentative']]

    def count(name):
        return sum(1 for record in confirmed if record['typeName'] == name)

    return {
        'profile': PROFILE,
        'decoded': True,
        'streamStart': start,
        'recordCount': len(records),
        'confirmedCount': len(confirmed),
        'tentativeCount': len(unresolved),
        'tentativeBytes': sum(record['size'] for record in unresolved),
        'ambiguousChoices': ambiguities,
        'typeCounts': dict(sorted(type_counts.items())),
        'frameRange': [min(frames), max(frames)] if frames else None,
        'unityFrameRange': [min(unity_frames), max(unity_frames)] if unity_frames else None,
        'touchCount': count('TouchOpe'),
        'moveCount': count('MoveOpe'),
        'skillUseCount': count('SkillUseOpe'),
        'skillSlotCount': count('SkillSlotOpe'),
        'uiEventCount': count('UIEventOpe'),
        'deadOrReviveCount': count('DeadOrReviveOpe'),
        'skillCancelCount': count('SkillCancelOpe'),
        'gameObjectNames': [record['fields'].get('path') for record in confirmed
                            if record['typeName'] == 'GameObjectNameOpe'
                            and record['fields'].get('path')],
        'note': '记录边界由全流最小不确定度解析确定；类型字节为 emOperatorDataType 枚举，'
                '字段名除 frame/unityFrame/eventId 外均为推断，不代表十人状态或经济数据。',
    }
