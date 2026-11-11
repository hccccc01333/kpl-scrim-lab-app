"""解密并解包 PC 微信的 wxapkg（V1MMWX 加密）。

只为查看本机已缓存的小程序代码、找接口路径，不修改原包。

    python tools/wxapkg_unpack.py <wxapkg> <appid> <输出目录>

加密结构（社区公开）：PBKDF2(appid, salt="saltiest", 1000, SHA1) 得 32 字节 AES 密钥，
前 1024 字节 AES-CBC，其余逐字节 XOR，密钥取 appid 倒数第二个字符的 ASCII。
"""
import struct
import sys
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Hash import SHA1
from Crypto.Protocol.KDF import PBKDF2

MAGIC = b'V1MMWX'
SALT = b'saltiest'
IV = b'the iv: 16 bytes'


def decrypt(data, wxid):
    if data[:6] != MAGIC:
        return data
    key = PBKDF2(wxid, SALT, dkLen=32, count=1000, hmac_hash_module=SHA1)
    head = AES.new(key, AES.MODE_CBC, IV).decrypt(data[6:6 + 1024])
    xor_key = ord(wxid[-2])
    tail = bytes(byte ^ xor_key for byte in data[6 + 1024:])
    return head + tail


def unpack(blob):
    """返回 [(路径, 内容)]。"""
    if not blob or blob[0] != 0xBE:
        raise ValueError(f'解密后首字节是 {blob[0]:#x}，不是 wxapkg（IV 或 appid 不对）')
    pos = 1
    info1, index_len, body_len = struct.unpack('>III', blob[pos:pos + 12])
    pos += 12
    if blob[pos] != 0xED:
        raise ValueError(f'标记位异常 {blob[pos]:#x}')
    pos += 1
    count = struct.unpack('>I', blob[pos:pos + 4])[0]
    pos += 4
    entries = []
    for _ in range(count):
        name_len = struct.unpack('>I', blob[pos:pos + 4])[0]
        pos += 4
        name = blob[pos:pos + name_len].decode('utf-8', 'replace')
        pos += name_len
        offset, size = struct.unpack('>II', blob[pos:pos + 8])
        pos += 8
        entries.append((name, offset, size))
    # 索引里的 offset 是相对整个文件的绝对偏移，不是相对 body 起点
    files = []
    for name, offset, size in entries:
        files.append((name, blob[offset:offset + size]))
    return files


def main():
    if len(sys.argv) < 4:
        raise SystemExit('用法：wxapkg_unpack.py <wxapkg> <appid> <out_dir>')
    src, wxid, out_dir = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    blob = decrypt(src.read_bytes(), wxid)
    files = unpack(blob)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files:
        target = out_dir / name.lstrip('/').replace('..', '_')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    print(f'{src.name}: {len(files)} 个文件 → {out_dir}')


if __name__ == '__main__':
    main()
