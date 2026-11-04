"""营地业务接口客户端（独立实现）。

带登录态请求 kohcamp.qq.com 的业务接口。鉴权字段在请求头；响应是否加密
由服务端响应头 campencrypt 决定，加密时用登录返回的 userKey 做 XXTEA 解密。

    python tools/camp_client.py detail <gameSeq> <gameSvr> <relaySvr> <battleType> <targetRoleId>
    python tools/camp_client.py list <page>

参数来自营地分享链接（mp-redirect 的 query），不需要抓包。
"""
from __future__ import annotations

import base64
import json
import sys
import time
import uuid
from pathlib import Path
from urllib import request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camp_auth import AUTH_PATH, BASE_HEADERS, CLIENT_CONSTANTS, rsa_encrypt  # noqa: E402
from xxtea_algo import decrypt_bytes as xxtea_decrypt_bytes  # noqa: E402
from xxtea_algo import encrypt_bytes as xxtea_encrypt_bytes  # noqa: E402

API_BASE = 'https://kohcamp.qq.com'


def load_account() -> dict:
    if not AUTH_PATH.is_file():
        raise SystemExit('没有登录凭证。先运行 python tools/camp_auth.py 扫码。')
    account = json.loads(AUTH_PATH.read_text(encoding='utf-8'))
    if not account.get('token') or not account.get('userId'):
        raise SystemExit('凭证不完整，请重新运行 python tools/camp_auth.py 扫码。')
    return account


def special_encode_param() -> str:
    """无 XXTEA 密钥时的安全参数：RSA 加密的 {timestamp, nonce}。"""
    now = int(time.time() * 1000)
    payload = {'timestamp': now, 'nonce': f':{uuid.uuid4().hex}:{now}'}
    return base64.b64encode(rsa_encrypt(json.dumps(payload).encode('utf-8'))).decode()


def build_headers(account: dict) -> dict:
    headers = {
        **BASE_HEADERS,
        'Host': 'kohcamp.qq.com',
        'Content-Type': 'application/json; charset=UTF-8',
        'x-log-uid': account.get('xLogUid') or str(uuid.uuid4()).upper(),
        'traceparent': '00-' + uuid.uuid4().hex + '-' + uuid.uuid4().hex[:16] + '-01',
        'istrpcrequest': 'true',
        'crand': str(int(time.time() * 1000)),
        'gameareaid': '1',
        'gameusersex': '1',
        'kohdimgender': '2',
        'token': account['token'],
        'userid': account['userId'],
    }
    if account.get('openId'):
        headers['openid'] = account['openId']
    if account.get('userKey'):
        headers['encodeParam'] = xxtea_encode_param(account['userKey'])
    else:
        headers['specialEncodeParam'] = special_encode_param()
    for key, value in CLIENT_CONSTANTS.items():
        headers[key.lower()] = value
    return headers


def xxtea_encode_param(user_key: str) -> str:
    """请求头 encodeParam：XXTEA(userKey) 加密的 {timestamp, nonce}。

    nonce 约定为 `<userId>:<32位随机串>:<毫秒时间戳>`。
    """
    now = int(time.time() * 1000)
    payload = json.dumps({'timestamp': now,
                          'nonce': f'{account_user_id()}:{uuid.uuid4().hex}:{now}'})
    cipher = xxtea_encrypt_bytes(payload.encode('utf-8'), user_key.encode('utf-8'))
    return base64.b64encode(cipher).decode()


def account_user_id() -> str:
    account = json.loads(AUTH_PATH.read_text(encoding='utf-8'))
    return account.get('userId') or ''


def xxtea_decrypt_camp(text: str, user_key: str) -> str:
    data = xxtea_decrypt_bytes(base64.b64decode(text.strip()), user_key.encode('utf-8'))
    return data.decode('utf-8', 'replace').rstrip('\x00')


def call(endpoint: str, body: dict) -> dict:
    account = load_account()
    req = request.Request(API_BASE + endpoint,
                          data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
                          method='POST', headers=build_headers(account))
    with request.urlopen(req, timeout=30) as resp:
        raw = resp.read(8 * 1024 * 1024).decode('utf-8', 'replace')
        headers = {k.lower(): v for k, v in resp.headers.items()}
    if headers.get('encryptparamerr'):
        raise SystemExit(f'安全参数被拒（{headers["encryptparamerr"]}），重新扫码可能解决。')
    code = headers.get('returncode', '')
    message = headers.get('returnmsg', '')
    if headers.get('campencrypt') == 'true':
        if not account.get('userKey'):
            raise SystemExit('响应已加密但缺少 userKey，请重新扫码。')
        raw = xxtea_decrypt_camp(raw, account['userKey'])
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {'raw': raw[:500]}
    return {'returnCode': code, 'returnMsg': message, 'encrypted': headers.get('campencrypt') == 'true',
            'body': payload}


def battle_detail(game_seq: str, game_svr: str, relay_svr: str, battle_type: str, role_id: str) -> dict:
    return call('/game/battledetail', {
        'recommendPrivacy': 0,
        'battleType': int(battle_type),
        'gameSvr': game_svr,
        'relaySvr': relay_svr,
        'targetRoleId': role_id,
        'gameSeq': game_seq,
    })


def battle_list(friend_user_id: str, last_time: int = 0) -> dict:
    """战绩列表。lastTime=增量水位（秒级或毫秒级时间戳，传 0 拉最新）。"""
    return call('/game/morebattlelist', {
        'lastTime': last_time,
        'recommendPrivacy': 0,
        'apiVersion': 5,
        'friendUserId': friend_user_id,
        'option': 0,
    })


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    if argv[1] == 'detail' and len(argv) >= 7:
        result = battle_detail(argv[2], argv[3], argv[4], argv[5], argv[6])
    elif argv[1] == 'list' and len(argv) >= 3:
        result = battle_list(argv[2], int(argv[3]) if len(argv) > 3 else 0)
    else:
        raise SystemExit(__doc__)
    print(json.dumps({'returnCode': result['returnCode'], 'returnMsg': result['returnMsg'],
                      'encrypted': result['encrypted']}, ensure_ascii=False))
    print(json.dumps(result['body'], ensure_ascii=False, indent=1)[:4000])


if __name__ == '__main__':
    main(sys.argv)
