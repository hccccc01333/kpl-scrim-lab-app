"""营地战绩时间的统一换算。

战绩列表里的 ``dtEventTime`` 是「对局记录发送时间」（epoch 秒），不是开赛时间：
同一局的 ``gametime``（开赛）≈ ``dtEventTime - usedTime``。历史详情里的
``battle.dtEventTime`` 只是「MM-DD HH:MM」文本、没有年份，不能单独还原日期；
只有带 ``_campEntry.dtEventTime`` 的新同步详情能给出精确到秒的时间。

时间统一按北京时间（UTC+8）输出，和教练看到的营地时间一致。
"""
from datetime import datetime, timedelta, timezone

CAMP_TZ = timezone(timedelta(hours=8))


def _seconds(value) -> int:
    try:
        number = int(float(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0
    if number > 10_000_000_000:  # 毫秒时间戳
        number //= 1000
    return number if number > 0 else 0


def _iso(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, CAMP_TZ).isoformat(timespec='seconds')


def camp_times(detail) -> dict:
    """从营地详情提取发送时间与推算开赛时间；没有可用的 epoch 时返回空字典。

    返回 ``eventAt``（发送/记录时间）、``startedAt``（eventAt - usedTime）、
    ``date``（开赛日期，YYYY-MM-DD）和 ``durationSec``。
    """
    entry = (detail or {}).get('_campEntry') or {}
    event = _seconds(entry.get('dtEventTime'))
    if not event:
        return {}
    data = (detail or {}).get('data') or {}
    used = 0
    for value in ((data.get('battle') or {}).get('usedTime'), entry.get('usedTime')):
        try:
            number = int(float(value or 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if number > 0:
            used = number
            break
    started = _iso(max(0, event - used))
    return {'eventAt': _iso(event), 'startedAt': started,
            'date': started[:10], 'durationSec': used or None}
