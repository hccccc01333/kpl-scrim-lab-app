"""XXTEA（Corrected Block TEA）标准实现。

算法出自 Wheeler 需要的公开描述（Wikipedia 可查），这里的约定：
数据按 4 字节小端组成 u32 数组，加密前在末尾附加原始字节长度，
密钥取前 16 字节、不足补零。与营地客户端的行为一致。

    encrypt_bytes(data, key) -> bytes   输出长度为对齐后的密文
    decrypt_bytes(data, key) -> bytes   还原原始数据
"""

MASK = 0xFFFFFFFF
DELTA = 0x9E3779B9


def _to_words(data: bytes, with_length: bool) -> list:
    words = [int.from_bytes(data[i:i + 4].ljust(4, b'\x00'), 'little')
             for i in range(0, len(data), 4)]
    if with_length:
        words.append(len(data))
    return words


def _to_bytes(words: list, with_length: bool) -> bytes:
    if with_length:
        size = words[-1]
        if size < 0 or size > len(words) * 4 - 4:
            return b''
    else:
        size = len(words) * 4
    return b''.join(word.to_bytes(4, 'little') for word in words)[:size]


def _key_words(key: bytes) -> list:
    words = _to_words(key[:16], False)
    while len(words) < 4:
        words.append(0)
    return words


def _mx(total, y, z, p, e, key):
    return (((z >> 5) ^ (y << 2)) + ((y >> 3) ^ (z << 4))) ^ ((total ^ y) + (key[(p & 3) ^ e] ^ z))


def encrypt_bytes(data: bytes, key: bytes) -> bytes:
    if not data:
        return b''
    words = _to_words(data, True)
    key = _key_words(key)
    count = len(words)
    rounds = 6 + 52 // count
    last = count - 1
    total = 0
    z = words[last]
    for _ in range(rounds):
        total = (total + DELTA) & MASK
        e = (total >> 2) & 3
        for p in range(last):
            y = words[p + 1]
            z = words[p] = (words[p] + _mx(total, y, z, p, e, key)) & MASK
        y = words[0]
        z = words[last] = (words[last] + _mx(total, y, z, last, e, key)) & MASK
    return _to_bytes(words, False)


def decrypt_bytes(data: bytes, key: bytes) -> bytes:
    if not data or len(data) % 4:
        return b''
    words = _to_words(data, False)
    key = _key_words(key)
    count = len(words)
    rounds = 6 + 52 // count
    last = count - 1
    total = (rounds * DELTA) & MASK
    y = words[0]
    while total:
        e = (total >> 2) & 3
        for p in range(last, 0, -1):
            z = words[p - 1]
            # 解密轮的 y/z 与加密相反：y 取本项旧值，z 取前一项
            y = words[p] = (words[p] - _mx(total, y, z, p, e, key)) & MASK
        z = words[last]
        y = words[0] = (words[0] - _mx(total, y, z, 0, e, key)) & MASK
        total = (total - DELTA) & MASK
    return _to_bytes(words, True)
