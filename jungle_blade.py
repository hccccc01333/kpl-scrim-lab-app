"""打野刀 → 打野定位标签。

口径（赛训组 2026-11-21）：打野的「坦野 / 野核」不能写死在英雄身上——同一个英雄
（如大司命）以前出肉刀是坦野，现在出红刀是野核。标签要看**这一局实际出的打野刀**。

三种打野刀（含二级升级名）→ 定位：
  肉刀：巡守利斧 / 巨人之握 → 坦野（tank）
  红刀：追击刀锋 / 贪婪之噬 → 野核（core，战野 / 刺野）
  法刀：游击弯刀 / 符文大剑 → 野核（core，法核）

只按打野刀判定，不掺英雄静态标签；拿不到打野刀就返回 None，交给上层退回英雄标签。
"""

from __future__ import annotations

# 打野刀装备名 → (定位标签, 经济口径)。升级前后的名字都列进来。
BLADE_TYPE = {
    '巡守利斧': ('坦野', 'tank'),
    '巨人之握': ('坦野', 'tank'),
    '追击刀锋': ('野核', 'core'),
    '贪婪之噬': ('野核', 'core'),
    '游击弯刀': ('野核', 'core'),
    '符文大剑': ('野核', 'core'),
}

# 肉刀通常对应坦野的细类；红/法刀按英雄静态标签细分战野/刺野由上层补，这里给核心两档。
_FINE_BY_KIND = {'tank': '坦野', 'core': None}


def classify(equips) -> dict | None:
    """从一串装备名里找打野刀，返回 {'blade', 'type', 'kind'}；没有则 None。

    装备列表来自营地 `battleRecords.finalEquips[].equipName`；也可能传名字字符串列表。
    多把刀同时出现（理论上不该）时按出现顺序取第一把，稳定可预期。
    """
    if not isinstance(equips, (list, tuple)):
        return None
    for equip in equips:
        name = str(equip or '').strip()
        hit = BLADE_TYPE.get(name)
        if hit:
            label, kind = hit
            return {'blade': name, 'type': label, 'kind': kind,
                    'fine': _FINE_BY_KIND[kind]}
    return None
