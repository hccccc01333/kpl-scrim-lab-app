"""王者营地微信扫码授权（独立实现）。

只依赖公开可观察的协议行为：营地 App 走微信开放平台扫码登录，授权码换取
营地登录态（token / userKey）。业务接口的鉴权字段都在请求头里。

本工具只在本机保存使用者自己的登录凭证，不采集、不存储他人数据。

    python tools/camp_auth.py            生成二维码并等待确认，凭证写入 data/camp_auth.json
    python tools/camp_auth.py --status   查看已存凭证（脱敏）
    python tools/camp_auth.py --clear    删除凭证

安全提醒：camp_auth.json 等同于账号登录态，不要提交进 git、不要发给别人；
感觉泄露就删掉它并重扫一次。
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib import parse, request

from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA

ROOT = Path(__file__).resolve().parents[1]
AUTH_PATH = Path(os.environ.get('CAMP_AUTH_FILE', ROOT / 'data' / 'camp_auth.json'))
QR_PATH = ROOT / 'test-results' / 'camp-login-qr.png'

CAMP_BASE = 'https://ssl.kohsocialapp.qq.com:10001'
WX_QR_URL = 'https://open.weixin.qq.com/connect/sdk/qrconnect'
WX_POLL_URL = 'https://long.open.weixin.qq.com/connect/l/qrconnect'
WX_APPID = os.environ.get('WX_APPID', '')  # 用自己的微信开放平台 AppID

# 营地返回的 RSA 公钥（base64，DER），用于解开登录响应里的 encodeRes
RSA_PUBLIC_B64 = (
    'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC0h62mV/zjJtFsNdfFNlxksfUOpjDI2KCcBrPiA8T7'
    'szABT4InLDTrdXAW84QyGNiazB0i7pgPCNGSAYbiJrCRutZ5jQsVS0Wg/RnXfwVQDJcAHJDjP5IXyroeLX7'
    'NUxDai8nPcpfRsvq6sneobyPexZSH0TlVSnecsJZTj5wu/wIDAQAB'
)

BASE_HEADERS = {
    'Content-Encrypt': '',
    'Accept-Encrypt': '',
    'NOENCRYPT': '1',
    'X-Client-Proto': 'https',
    'User-Agent': 'okhttp/4.9.1',
}

# 营地客户端版本字符串。协议升级导致登录失败时，先更新这里。
CLIENT_CONSTANTS = {
    'cChannelId': '10003391',
    'cClientVersionCode': '2057957801',
    'cClientVersionName': '10.111.0323',
    'cCurrentGameId': '20001',
    'cGameId': '20001',
    'cGzip': '1',
    'cIsArm64': 'true',
    'cSupportArm64': 'true',
    'cSystem': 'android',
    'cSystemVersionCode': '34',
    'cSystemVersionName': '14',
    'cpuHardware': 'qcom',
    'gameId': '20001',
    'tinkerId': '2057957801_64_0',
}


def _public_key() -> RSA.RsaKey:
    return RSA.import_key(base64.b64decode(RSA_PUBLIC_B64))


def rsa_public_decrypt(signature: bytes) -> bytes:
    """营地用私钥对 encodeRes 签名，这里用公钥恢复原文（PKCS#1 v1.5）。"""
    key = _public_key()
    size = (key.n.bit_length() + 7) // 8
    recovered = pow(int.from_bytes(signature, 'big'), key.e, key.n)
    raw = recovered.to_bytes(size, 'big')
    if raw[:2] != b'\x00\x01':
        raise ValueError('PKCS#1 v1.5 块类型不符')
    separator = raw.index(b'\x00', 2)
    return raw[separator + 1:]


def rsa_encrypt(data: bytes) -> bytes:
    cipher = PKCS1_v1_5.new(_public_key())
    output = b''
    for offset in range(0, len(data), 117):
        output += cipher.encrypt(data[offset:offset + 117])
    return output


def http_json(url, method='GET', headers=None, body=None, timeout=20):
    payload = body.encode('utf-8') if isinstance(body, str) else body
    req = request.Request(url, method=method, data=payload, headers=headers or {})
    with request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode('utf-8', 'replace')
    try:
        return json.loads(text)
    except ValueError:
        return {'raw': text}


def device_fingerprint() -> str:
    """登录表单要求的设备描述，RSA 加密后随表单提交。值只用于本地这一次登录。"""
    device = uuid.uuid4().hex
    now = int(time.time() * 1000)
    payload = {
        'timestamp': now,
        'nonce': f':{device}:{now}',
        'cDeviceId': device,
        'deviceid': device,
        'cDeviceImei': device[:15],
        'cDeviceMac': '02:00:00:00:00:00',
        'cDevicePPI': 480,
        'cDeviceScreenWidth': 1080,
        'cDeviceScreenHeight': 2400,
        'cDeviceBrand': 'OnePlus',
        'cDeviceModel': 'PHK110',
        'cDeviceMem': 12 * 1024 * 1024 * 1024,
        'cDeviceCPU': 'SM8650',
        'cSystemVersionCode': '34',
        'cDeviceNet': 'WIFI',
        'cDeviceSP': 'China Mobile',
        'cDeviceOaid': device,
        'deviceLevel': 3,
        'px': 0,
        'py': 0,
        'wifi_ssid': 'unknown',
        'wifi_mac': '02:00:00:00:00:00',
    }
    return base64.b64encode(rsa_encrypt(json.dumps(payload).encode('utf-8'))).decode()


def get_sdk_ticket(xlog_uid: str) -> str:
    result = http_json(f'{CAMP_BASE}/a/getwxsdkticket', 'POST',
                       {**BASE_HEADERS, 'x-log-uid': xlog_uid}, body='')
    ticket = (result.get('data') or {}).get('sdkTicket')
    if result.get('returnCode') != 0 or not ticket:
        raise RuntimeError(f"获取微信登录票据失败：{json.dumps(result, ensure_ascii=False)[:200]}")
    return ticket


def get_qrcode(ticket: str):
    nonce = ''.join(secrets.choice('0123456789') for _ in range(8))
    timestamp = str(int(time.time()))
    signature = hashlib.sha1(
        f'appid={WX_APPID}&noncestr={nonce}&sdk_ticket={ticket}&timestamp={timestamp}'.encode()
    ).hexdigest()
    query = parse.urlencode({'appid': WX_APPID, 'noncestr': nonce, 'timestamp': timestamp,
                             'scope': 'snsapi_userinfo', 'signature': signature})
    result = http_json(f'{WX_QR_URL}?{query}')
    qrcode = (result.get('qrcode') or {}).get('qrcodebase64')
    if result.get('errcode') != 0 or not qrcode or not result.get('uuid'):
        raise RuntimeError(f"获取登录二维码失败：{json.dumps(result, ensure_ascii=False)[:200]}")
    return result['uuid'], qrcode


def poll_qrcode(uuid_value: str):
    result = http_json(f'{WX_POLL_URL}?' + parse.urlencode({'f': 'json', 'uuid': uuid_value}))
    status = result.get('wx_errcode', result.get('errcode'))
    auth_code = result.get('wx_code', result.get('code'))
    return status, auth_code


def login_with_code(auth_code: str, xlog_uid: str) -> dict:
    fingerprint = device_fingerprint()
    form = {
        'loginType': 'wx',
        'code': auth_code,
        'delOldUser': '0',
        'key1': uuid.uuid4().hex,
        'lastLoginTime': '0',
        'lastGetRemarkTime': '0',
        'cRand': str(int(time.time() * 1000)),
        'specialEncodeParam': fingerprint,
        **CLIENT_CONSTANTS,
    }
    headers = {
        **BASE_HEADERS,
        'x-log-uid': xlog_uid,
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'specialEncodeParam': fingerprint,
        **CLIENT_CONSTANTS,
    }
    result = http_json(f'{CAMP_BASE}/user/login', 'POST', headers,
                       body=parse.urlencode(form))
    data = result.get('data') or {}
    if result.get('returnCode') != 0 or not data.get('token'):
        raise RuntimeError(f"营地登录失败：{json.dumps(result, ensure_ascii=False)[:300]}")
    return data


def build_account(data: dict, xlog_uid: str) -> dict:
    encode_res = str(data.get('encodeRes') or '')
    user_key = ''
    if encode_res:
        try:
            payload = rsa_public_decrypt(base64.b64decode(encode_res))
            user_key = str(json.loads(payload.decode('utf-8', 'replace')).get('userKey') or '')
        except Exception as error:
            print(f'警告：encodeRes 解析失败（{error}），加密接口暂不可用', file=sys.stderr)
    return {
        'userId': str(data.get('userId') or ''),
        'token': str(data.get('token') or ''),
        'userKey': user_key,
        'openId': str(data.get('openId') or data.get('appOpenid') or ''),
        'nickname': str(data.get('nickname') or data.get('snsnickname') or ''),
        'expires': str(data.get('expires') or ''),
        'xLogUid': xlog_uid,
        'loginAt': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }


# ---- 登录会话（供工作台网页逐步扫码/轮询使用） ----

_login_sessions: dict = {}
SESSION_TTL = 180


def create_login_session() -> dict:
    """生成一次扫码会话，返回 {taskId, qrcodeBase64}。二维码 3 分钟内有效。"""
    xlog_uid = str(uuid.uuid4()).upper()
    uuid_value, qrcode_b64 = get_qrcode(get_sdk_ticket(xlog_uid))
    task_id = uuid.uuid4().hex
    _login_sessions[task_id] = {'xlogUid': xlog_uid, 'uuid': uuid_value,
                                'createdAt': time.time()}
    return {'taskId': task_id, 'qrcodeBase64': qrcode_b64}


def poll_login_once(task_id: str) -> dict:
    """轮询一次扫码状态。success 时凭证已写入 AUTH_PATH。

    任何一步失败都返回结构化 status，不把异常抛到 HTTP 层：轮询一旦变成
    500，前端会静默停在「已扫码，等待确认」，用户只能刷新页面重来。
    """
    session = _login_sessions.get(task_id)
    if not session or time.time() - session['createdAt'] > SESSION_TTL:
        _login_sessions.pop(task_id, None)
        return {'status': 'expired'}
    try:
        status, auth_code = poll_qrcode(session['uuid'])
    except Exception as error:
        # 微信长轮询偶发超时/断网：保留会话，下一次继续。
        return {'status': 'waiting', 'warning': str(error)}
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = 0
    if auth_code and status == 405:
        # create_login_session 存的是 xlogUid；写成 xLogUid 会让「手机上点了
        # 确定」变成 KeyError → 500，二维码永远停在等待确认。
        xlog_uid = session.get('xlogUid') or session.get('xLogUid') or ''
        try:
            account = build_account(login_with_code(auth_code, xlog_uid), xlog_uid)
            AUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
            AUTH_PATH.write_text(json.dumps(account, ensure_ascii=False, indent=2),
                                 encoding='utf-8')
            reset_health()
        except Exception as error:
            _login_sessions.pop(task_id, None)
            return {'status': 'error', 'message': f'登录确认失败：{error}'}
        _login_sessions.pop(task_id, None)
        return {'status': 'success', 'nickname': account.get('nickname') or '',
                'userId': account.get('userId') or ''}
    if status == 405 and not auth_code:
        # 已确认却没拿到 code：继续轮询也是白等，明确让用户重扫一次。
        _login_sessions.pop(task_id, None)
        return {'status': 'error', 'message': '微信已确认但未返回授权码，请重新扫码。'}
    if status == 404:
        return {'status': 'scanned'}
    if status == 402:
        _login_sessions.pop(task_id, None)
        return {'status': 'expired'}
    if status == 403:
        _login_sessions.pop(task_id, None)
        return {'status': 'canceled'}
    return {'status': 'waiting'}


def cancel_login_session(task_id: str = '') -> None:
    """放弃一次扫码会话；不传 taskId 时清空全部（删除凭证时一并调用）。"""
    if task_id:
        _login_sessions.pop(task_id, None)
    else:
        _login_sessions.clear()


# ---- 登录态健康状态（供工作台提示「授权失效 → 补充授权」） ----

_HEALTH_LOCK = threading.Lock()


def _now_text() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def health_path() -> Path:
    """健康状态文件跟着凭证走。

    只覆盖 CAMP_AUTH_FILE（测试/多实例）时也不会写到真实的 data/ 目录；
    需要单独指定时用 CAMP_AUTH_HEALTH_FILE。
    """
    explicit = os.environ.get('CAMP_AUTH_HEALTH_FILE')
    if explicit:
        return Path(explicit)
    return AUTH_PATH.with_name(f'{AUTH_PATH.stem}_health.json')


def _empty_health() -> dict:
    return {'invalid': False, 'reason': '', 'code': '', 'invalidAt': '', 'checkedAt': ''}


def read_health() -> dict:
    """读取最近一次授权检测结果；没有记录时按「未发现问题」返回。"""
    try:
        data = json.loads(health_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return _empty_health()
    if not isinstance(data, dict):
        return _empty_health()
    return {
        'invalid': bool(data.get('invalid')),
        'reason': str(data.get('reason') or ''),
        'code': str(data.get('code') or ''),
        'invalidAt': str(data.get('invalidAt') or ''),
        'checkedAt': str(data.get('checkedAt') or ''),
    }


def _write_health(**changes) -> dict:
    with _HEALTH_LOCK:
        state = read_health()
        state.update({key: value for key, value in changes.items() if value is not None})
        path = health_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # 先写临时文件再替换：请求线程与同步线程并发读写时不会读到半截 JSON。
        temporary = path.with_name(path.name + '.tmp')
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
        os.replace(temporary, path)
    return state


def mark_invalid(reason: str, code: str = '') -> None:
    """营地接口明确报登录态失效时记下来，页面不必等到拉取失败才提示。"""
    _write_health(invalid=True, reason=str(reason or ''), code=str(code or ''),
                  invalidAt=_now_text(), checkedAt=_now_text())


def mark_valid() -> None:
    """接口确认登录态可用：清掉失效标记；没有失效记录时不写盘。"""
    state = read_health()
    if not state['invalid'] and not state['reason']:
        return
    _write_health(invalid=False, reason='', code='', invalidAt='', checkedAt=_now_text())


def mark_checked(valid: bool, reason: str = '', code: str = '') -> dict:
    """主动检测的结果（网络错误不要走到这里，避免把断网当成失效）。"""
    return _write_health(invalid=not valid,
                         reason='' if valid else str(reason or ''),
                         code='' if valid else str(code or ''),
                         invalidAt='' if valid else _now_text(),
                         checkedAt=_now_text())


def reset_health() -> None:
    """重新授权或删除凭证后清空旧状态。"""
    with _HEALTH_LOCK:
        try:
            health_path().unlink()
        except FileNotFoundError:
            pass


def read_account() -> dict:
    """读取已保存的凭证（脱敏摘要），没有则返回 {'authorized': False}。

    expired/reason/code/checkedAt 来自最近一次接口报错或主动检测；没有失效记录
    时 expired 为 False、reason 为空，页面不会因此提前报警。
    """
    if not AUTH_PATH.is_file():
        return {'authorized': False}
    try:
        account = json.loads(AUTH_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'authorized': False}
    if not account.get('token'):
        return {'authorized': False}
    health = read_health()
    return {'authorized': True, 'nickname': account.get('nickname') or '',
            'userId': account.get('userId') or '', 'loginAt': account.get('loginAt') or '',
            'expired': health['invalid'], 'reason': health['reason'],
            'code': health['code'], 'invalidAt': health['invalidAt'],
            'checkedAt': health['checkedAt']}


def show_status():
    if not AUTH_PATH.is_file():
        print('还没有登录凭证。先运行 python tools/camp_auth.py 扫码。')
        return
    account = json.loads(AUTH_PATH.read_text(encoding='utf-8'))
    token = account.get('token') or ''
    print(f"昵称   : {account.get('nickname') or '—'}")
    print(f"userId : {account.get('userId') or '—'}")
    print(f"token  : {token[:6]}…({len(token)} 字符)" if token else 'token  : 无')
    print(f"userKey: {'有' if account.get('userKey') else '无'}")
    print(f"登录于 : {account.get('loginAt') or '—'}（expires 字段：{account.get('expires') or '未提供'}）")
    health = read_health()
    if health['invalid']:
        print('状态   : 已失效 → 重新扫码授权')
        print(f"原因   : {health['reason'] or '营地接口报登录态失效'}")
    else:
        print(f"状态   : 未发现登录态问题（最近检测：{health['checkedAt'] or '未检测'}）")
    print(f"位置   : {AUTH_PATH}")


def login_flow():
    print('获取登录二维码…')
    session = create_login_session()
    QR_PATH.parent.mkdir(parents=True, exist_ok=True)
    QR_PATH.write_bytes(base64.b64decode(session['qrcodeBase64']))
    print(f'二维码已保存：{QR_PATH}')
    try:
        os.startfile(QR_PATH)
    except AttributeError:
        pass
    print('请用打过训练赛的微信扫码并在手机上确认（3 分钟内有效）…')
    deadline = time.time() + SESSION_TTL + 10
    last_status = None
    while time.time() < deadline:
        time.sleep(2)
        result = poll_login_once(session['taskId'])
        if result['status'] == 'success':
            print(f"登录成功：{result.get('nickname') or result.get('userId')}")
            print(f'凭证已写入 {AUTH_PATH}（含登录态，勿外传、勿入 git）。')
            return
        if result['status'] == 'scanned' and last_status != 'scanned':
            print('已扫码，等待手机上确认…')
        elif result['status'] == 'expired':
            raise SystemExit('二维码已过期，请重新运行本命令。')
        elif result['status'] == 'canceled':
            raise SystemExit('已在手机上取消登录。')
        last_status = result['status']
    raise SystemExit('等待超时。重新运行 python tools/camp_auth.py 会生成新二维码。')


def main(argv):
    if '--status' in argv:
        show_status()
    elif '--clear' in argv:
        AUTH_PATH.unlink(missing_ok=True)
        reset_health()
        print(f'已删除 {AUTH_PATH}')
    else:
        login_flow()


if __name__ == '__main__':
    main(sys.argv[1:])
