"""Synthetic container fixtures; contain no original game/client assets."""
import struct
import zlib

HERO_IDS=[118,196,548,558,193,112,144,172,195,148]
NORMAL_5V5_HERO_IDS=[166,538,108,152,196,175,107,142,123,132]
NORMAL_5V5_NAMES=['信则\u2060\u2061有\u2062','深藏功与名','憨熊笨拳','冷静宝宝',
                 '漂流网咖','南巷转转儿','西行感怀录','野心蓝图','蟹谢谢礼','别再浪']


def text(value):
    data=value.encode('utf-8')
    return bytes([len(data)])+data


def abc_fixture():
    payload=b'\0'*5+(2).to_bytes(2,'big')+b'\x01\x00x'
    record=b'\x02\x23\x01\x29\x0e\0\0'+bytes([len(payload)])+payload
    tail=record*2+b'\0'*7
    raw=bytearray(17652+len(tail))
    header=b''.join(text(v) for v in ('12.1.1.1','12.1.1.23','4989537','5230306'))
    raw[:len(header)]=header
    raw[35:39]=HERO_IDS[0].to_bytes(4,'little')
    for i,hero in enumerate(HERO_IDS):
        start=674+i*1517
        for offset in ((1445,) if i==0 else (771,1415,1445)):
            raw[start+offset:start+offset+4]=hero.to_bytes(4,'big')
    raw[17652:]=tail
    return bytes(raw)


def normal_5v5_parts():
    """(fixed header through the rank bytes, block area incl. trailing zeros)."""
    prefix=bytearray(b''.join(text(v) for v in ('12.1.1.1','12.1.1.26','4989537','5247758')))
    prefix+=(196).to_bytes(4,'little')
    prefix+=(1793606215).to_bytes(8,'little',signed=True)
    prefix+=bytes([1])+(0).to_bytes(4,'little')
    prefix+=text('tester')+text('')
    prefix+=bytes([0])+(0).to_bytes(4,'little')
    blocks=bytearray()
    for index,(hero,name) in enumerate(zip(NORMAL_5V5_HERO_IDS,NORMAL_5V5_NAMES)):
        camp,slot=divmod(index,5)
        camp+=1
        encoded=name.encode('utf-8')
        if index==0:
            encoded+=b'\x00'
        block=bytearray([camp,camp,1,slot,0,0])
        block+= (1000+index).to_bytes(2,'big')
        block+= (30).to_bytes(4,'big')
        block+=len(encoded).to_bytes(4,'big')
        block+=encoded
        block+=b'\0'*30
        block+=b'\0'*0x48
        block+=hero.to_bytes(2,'big')
        block+=b'\0'*64
        if camp==1:
            block+=bytes.fromhex('000000000004b000000000')
        blocks+=block
    return bytes(prefix), bytes(blocks)+b'\0'*100


def normal_5v5_fixture():
    """Ten human blocks: blue side has the 12-byte footer, red side does not."""
    prefix, blocks = normal_5v5_parts()
    return prefix + b'\0' * 64 + blocks


def inputs_5v5_fixture(commands=(b"\0",)):
    """5v5 roster plus an ID1075 record stream carrying frame command payloads."""
    prefix, blocks = normal_5v5_parts()
    body = (1075).to_bytes(4, 'big') + blocks
    raw = bytearray(prefix)
    raw += struct.pack('<IiBI', 0, 0, 0, len(commands))
    raw += struct.pack('<i', -len(body)) + body
    for sequence, payload in enumerate(commands, 1):
        raw += struct.pack('<i', 6 + len(payload)) + struct.pack('>IH', sequence, len(payload)) + payload
    raw += struct.pack('<i', -16) + struct.pack('>IIII', 1251, 1, 2, 3)
    return bytes(raw)


def single_game_1051_fixture(entries=((1, b"\x01\x00\x02\x23\x01\x03\x13\x00\x00"),)):
    """Single-game header + ID1051 packet + per-entry [len][seq][payload] records.

    `entries` are (frame, payload) pairs; the payload length is the i32 length
    and the frame number repeats across entries of one frame (docs 5.133).
    """
    header = b''.join(text(v) for v in ('12.1.1.1', '12.1.1.23', '4989537', '5230306'))
    raw = bytearray(header)
    raw += (196).to_bytes(4, 'little')
    raw += (1793606215).to_bytes(8, 'little', signed=True)
    raw += bytes([1]) + (0).to_bytes(4, 'little')
    raw += text('tester') + text('')
    raw += bytes([0]) + (0).to_bytes(4, 'little')
    raw += struct.pack('<IiBI', 0, 0, 0, len(entries))
    body = (1051).to_bytes(4, 'big') + b'\0' * 32
    raw += struct.pack('<i', -len(body)) + body
    for frame, payload in entries:
        raw += struct.pack('<i', len(payload)) + struct.pack('>I', frame) + payload
    return bytes(raw)


def deflate(data):
    compressor=zlib.compressobj(wbits=-15)
    return compressor.compress(data)+compressor.flush()


def ope_fixture(extra=b''):
    header=bytes.fromhex(
        '020001f3dd010a7b0000000001fadd011717000000000000000000')
    records=b'\x00\x8c\x01'+b'\x01\x93\xe0\x01'
    stream=header+records+extra
    compressed=deflate(stream)
    header_block=bytearray(139)
    header_block[:3]=b'\x01\x01\x01'
    texts=b''.join(text(v) for v in ('12.1.1.1','12.1.1.23','4989537'))
    header_block[3:3+len(texts)]=texts
    header_block[0x42:0x63]=text('0'*32)
    header_block[0x63:0x77]=text('2026-10-28 13:55:16')
    header_block[0x86:0x8a]=(len(compressed)+1).to_bytes(4,'little')
    header_block[0x8a]=1
    return b'\x01'+deflate(bytes(header_block)+compressed),stream
