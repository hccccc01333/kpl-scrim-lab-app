"""BP 规则唯一来源：征召 18 手 / KPL 18|20 手 / 排位·巅峰 20 手。

三种格式（`FORMATS`）：

* ``draft-18``：4 Ban/方 + 5 Pick/方，18 手。征召；KPL 2020 春季赛~2024 夏季赛。
* ``draft-20``：5 Ban/方 + 5 Pick/方，20 手。KPL 2024 年度总决赛起。
* ``rank-20``：5+5 同时 Ban + 10 Pick，20 手。排位/巅峰。

身份口径（教练组 2026-11-18 确认）：

* **Pick / 全局 BP**：元流之子五形态（坦克/辅助/射手/法师/刺客）算一个英雄。
* **Ban**：按形态。Ban ``元流之子(坦克)`` 不影响 Pick ``元流之子(射手)``；
  KPL 数据 102 局同局出现两个不同形态的 Ban、105 局 Ban 一个形态选另一个形态，
  且同形态 Ban+Pick = 0 局，全部合法。

全局 BP：``draft-18`` / ``draft-20`` 固定开启；``rank-20`` 不启用。
巅峰对决：KPL BO7 第 7 局；征召默认没有，双方约定时用单场开关（``decider_override``）。

本模块只做规则，不碰展示、不读写文件。``bp_rules.py`` 已收敛为兼容层，
默认 ``draft-18``，旧 id ``scrim-global-20`` 仅作别名。
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

SERIES_LENGTHS = {"BO3": 3, "BO5": 5, "BO7": 7}
YUANLIU = "元流之子"
YUANLIU_FORMS = ("坦克", "辅助", "射手", "法师", "刺客")


# ---------------------------------------------------------------------------
# 身份口径
# ---------------------------------------------------------------------------

def hero_form(name):
    """``元流之子(坦克)`` → ``坦克``；不是元流形态返回空串。"""
    text = str(name or "").strip()
    if text.startswith(YUANLIU) and text.endswith(")") and "(" in text:
        return text[text.index("(") + 1:-1]
    return ""


def pick_key(name):
    """Pick / 全局 BP 的唯一性口径：元流之子五形态算一个英雄。"""
    text = str(name or "").strip()
    return YUANLIU if text.startswith(YUANLIU) else text


def ban_key(name):
    """Ban 的唯一性口径：按形态。"""
    return str(name or "").strip()


def display_name(name):
    return str(name or "").strip()


# ---------------------------------------------------------------------------
# 排程
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Phase:
    """一个 BP 阶段。

    ``layout``：
    * ``sequential``：按 ``steps`` 逐手交替；``steps`` 是 (camp, 连续次数)。
    * ``parallel``：双方同时禁用；``counts`` 是 (camp, 数量)，阶段内无先后。
    * ``blind``：双方同时盲选；``counts`` 同上，允许双方选到同一个英雄。
    """

    key: str
    action: str
    layout: str
    steps: tuple = ()
    counts: tuple = ()

    def total(self):
        if self.layout == "sequential":
            return sum(count for _, count in self.steps)
        return sum(count for _, count in self.counts)

    def expanded(self):
        """sequential 阶段的逐手 ``(action, camp)``；其他 layout 返回空。"""
        if self.layout != "sequential":
            return ()
        rows = []
        for camp, count in self.steps:
            rows.extend([(self.action, camp)] * count)
        return tuple(rows)


@dataclass(frozen=True)
class DraftFormat:
    id: str
    title: str
    modes: tuple
    phases: tuple
    global_bp: bool = False
    allow_shared_bans: bool = False
    allow_shared_picks: bool = False
    pick_identity: str = "canonical"
    ban_identity: str = "form"
    decider: str | None = None
    decider_override: bool = False

    @property
    def total_hands(self):
        return sum(phase.total() for phase in self.phases)

    def _per_side(self, action):
        out = Counter()
        for phase in self.phases:
            if phase.action != action:
                continue
            if phase.layout == "sequential":
                for camp, count in phase.steps:
                    out[camp] += count
            else:
                for camp, count in phase.counts:
                    out[camp] += count
        return {"1": out["1"], "2": out["2"]}

    @property
    def bans_per_side(self):
        return self._per_side("ban")

    @property
    def picks_per_side(self):
        return self._per_side("pick")

    @property
    def schedule(self):
        """平铺手序。``parallel=True`` 的行只表示存储位次，不是对局先后。"""
        rows = []
        order = 0
        for phase in self.phases:
            if phase.layout == "sequential":
                for action, camp in phase.expanded():
                    order += 1
                    rows.append({"order": order, "phase": phase.key, "action": action,
                                 "camp": camp, "parallel": False, "blind": False})
                continue
            for camp, count in phase.counts:
                for _ in range(count):
                    order += 1
                    rows.append({"order": order, "phase": phase.key,
                                 "action": phase.action, "camp": camp,
                                 "parallel": phase.layout == "parallel",
                                 "blind": phase.layout == "blind"})
        return rows


BAN1 = Phase("ban1", "ban", "sequential",
             steps=(("1", 1), ("2", 1), ("1", 1), ("2", 1)))
PICK1 = Phase("pick1", "pick", "sequential",
              steps=(("1", 1), ("2", 2), ("1", 2), ("2", 1)))
BAN2_TWO = Phase("ban2", "ban", "sequential",
                 steps=(("2", 1), ("1", 1), ("2", 1), ("1", 1)))
BAN2_THREE = Phase("ban2", "ban", "sequential",
                   steps=(("2", 1), ("1", 1), ("2", 1), ("1", 1),
                          ("2", 1), ("1", 1)))
PICK2 = Phase("pick2", "pick", "sequential",
              steps=(("2", 1), ("1", 2), ("2", 1)))

RANK_BAN = Phase("ban", "ban", "parallel", counts=(("1", 5), ("2", 5)))
RANK_PICK = Phase("pick", "pick", "sequential",
                  steps=(("1", 1), ("2", 2), ("1", 2), ("2", 2),
                         ("1", 2), ("2", 1)))

DRAFT_18 = DraftFormat(
    "draft-18", "征召 · 4 Ban + 5 Pick", ("scrim", "kpl"),
    (BAN1, PICK1, BAN2_TWO, PICK2),
    global_bp=True, decider="peak-duel", decider_override=True,
)
DRAFT_20 = DraftFormat(
    "draft-20", "KPL · 5 Ban + 5 Pick", ("kpl",),
    (BAN1, PICK1, BAN2_THREE, PICK2),
    global_bp=True, decider="peak-duel",
)
RANK_20 = DraftFormat(
    "rank-20", "排位/巅峰 · 5+5 同时 Ban", ("rank",),
    (RANK_BAN, RANK_PICK),
    global_bp=False, allow_shared_bans=True,
)
BLIND = DraftFormat(
    "blind", "巅峰对决 · 双方盲选 5", ("kpl", "scrim"),
    (Phase("decider", "pick", "blind", counts=(("1", 5), ("2", 5))),),
    global_bp=False, allow_shared_bans=True, allow_shared_picks=True,
)

FORMATS = {fmt.id: fmt for fmt in (DRAFT_18, DRAFT_20, RANK_20, BLIND)}


def get_format(name=None):
    if name in (None, ""):
        return DRAFT_18
    fmt = FORMATS.get(str(name))
    if fmt is None:
        raise ValueError(f"未知 BP 格式：{name}；可用：{', '.join(FORMATS)}")
    return fmt


def resolve_format(*, explicit=None, bans_per_side=None, source=None,
                   map_name=None, blind=False):
    """按记录信息判定格式。优先显式 id，再 Ban 数 / 来源 / 地图名。

    不按日期猜：日期只用于展示「当时是不是 4 Ban」。
    """
    if blind:
        return BLIND
    if explicit:
        return get_format(explicit)
    text = str(map_name or "")
    if "排位" in text or "巅峰赛" in text:
        return RANK_20
    try:
        bans = int(bans_per_side) if bans_per_side is not None else None
    except (TypeError, ValueError):
        bans = None
    if source == "kpl":
        if bans == 4:
            return DRAFT_18
        if bans == 5:
            return DRAFT_20
        raise ValueError("KPL 记录需要每方 4 或 5 个 Ban 才能判定格式")
    if source == "scrim":
        return DRAFT_18
    if bans == 4:
        return DRAFT_18
    if bans == 5:
        return RANK_20
    raise ValueError("无法判定 BP 格式：缺少规则 id、Ban 数或来源")


def decider_applies(fmt, *, mode, bo, game_number, score=None, override=False):
    """本局是否进入巅峰对决。

    KPL：BO7 第 7 局（比分 3:3；不传比分时按已打到第 7 局处理）。
    征召：BO7 第 7 局且双方约定（``override=True``）。
    """
    if fmt.decider != "peak-duel":
        return False
    if str(bo) != "BO7" or int(game_number or 0) != 7:
        return False
    if score is not None:
        try:
            a, b = score
            if (int(a), int(b)) != (3, 3):
                return False
        except (TypeError, ValueError):
            return False
    if mode == "kpl":
        return True
    if mode == "scrim":
        return bool(override)
    return False


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------

def _rows(events):
    rows = []
    for index, event in enumerate(events or []):
        if not isinstance(event, dict):
            raise ValueError(f"第 {index + 1} 个 BP 事件不是对象")
        action = str(event.get("action") or "")
        camp = str(event.get("camp") or "")
        hero = str(event.get("hero") or "").strip()
        if action not in ("ban", "pick"):
            raise ValueError(f"第 {index + 1} 手动作必须是 ban 或 pick")
        if camp not in ("1", "2"):
            raise ValueError(f"第 {index + 1} 手阵营必须是 1 或 2")
        if not hero:
            raise ValueError(f"第 {index + 1} 手缺少英雄")
        raw_order = event.get("order", index + 1)
        if isinstance(raw_order, bool):
            raise ValueError(f"第 {index + 1} 手 order 不能是布尔值")
        try:
            order = int(raw_order)
        except (TypeError, ValueError) as error:
            raise ValueError(f"第 {index + 1} 手 order 必须是整数") from error
        if order != index + 1:
            raise ValueError("order 必须从 1 连续递增")
        rows.append({"order": order,
                     "action": action, "camp": camp, "hero": hero,
                     "phase": str(event.get("phase") or "")})
    return rows


def _hero_rules(rows, fmt, *, strict):
    errors, warnings = [], []
    seen_ban = {"1": set(), "2": set()}
    all_bans = set()
    picked_keys = set()
    picked_forms = set()
    for row in rows:
        if row["action"] == "ban":
            key = ban_key(row["hero"])
            if key in seen_ban[row["camp"]]:
                errors.append(f"同一方重复 Ban：{row['hero']}")
            if not fmt.allow_shared_bans and key in all_bans:
                errors.append(f"跨方重复 Ban：{row['hero']}")
            if key in picked_forms:
                errors.append(f"已 Pick 的形态不能 Ban：{row['hero']}")
            elif pick_key(row["hero"]) in picked_keys:
                (errors if strict else warnings).append(
                    f"该英雄已在局内被选，仍出现 Ban：{row['hero']}")
            seen_ban[row["camp"]].add(key)
            all_bans.add(key)
            continue
        key = pick_key(row["hero"])
        if key in picked_keys and not fmt.allow_shared_picks:
            errors.append(f"重复 Pick：{row['hero']}")
        if ban_key(row["hero"]) in all_bans:
            errors.append(f"已 Ban 的形态不能 Pick：{row['hero']}")
        picked_keys.add(key)
        picked_forms.add(ban_key(row["hero"]))
    return errors, warnings


def check_draft(events, fmt=None, *, strict=True):
    """校验一段 BP 事件。

    返回 ``{ok, errors, warnings, completed, total}``，不抛异常；调用方决定
    是否把 ``errors`` 变成 400。``strict=True`` 逐手核对排程（新录入/沙盘）；
    ``strict=False`` 只核对数量与英雄合法性（历史导入，允许顺序与模版不同）。
    """
    fmt = fmt or DRAFT_18
    try:
        rows = _rows(events)
    except ValueError as error:
        return {"ok": False, "errors": [str(error)], "warnings": [],
                "completed": 0, "total": fmt.total_hands}
    errors, warnings = [], []
    if len(rows) > fmt.total_hands:
        errors.append(f"手数超过 {fmt.total_hands}：{len(rows)}")
        return {"ok": False, "errors": errors, "warnings": warnings,
                "completed": len(rows), "total": fmt.total_hands}

    if strict:
        cursor = 0
        for phase in fmt.phases:
            if cursor >= len(rows):
                break
            take = rows[cursor:cursor + phase.total()]
            if phase.layout == "sequential":
                expected = phase.expanded()
                for offset, row in enumerate(take):
                    if offset >= len(expected):
                        errors.append(f"第 {cursor + offset + 1} 手超出 {phase.key} 阶段")
                        break
                    action, camp = expected[offset]
                    if row["action"] != action or row["camp"] != camp:
                        errors.append(
                            f"第 {cursor + offset + 1} 手应为 {action}/{camp}，"
                            f"实际 {row['action']}/{row['camp']}")
                        break
            else:
                counts = Counter(row["camp"] for row in take)
                allowed = dict(phase.counts)
                for camp, count in counts.items():
                    if count > allowed.get(camp, 0):
                        errors.append(
                            f"{phase.key} 阶段 {camp} 方超出 {allowed.get(camp, 0)} 手")
            cursor += len(take)
    else:
        counts = Counter((row["action"], row["camp"]) for row in rows)
        for action in ("ban", "pick"):
            limit = fmt._per_side(action)
            for camp in ("1", "2"):
                if counts[(action, camp)] > limit[camp]:
                    errors.append(
                        f"{camp} 方 {action} 超过 {limit[camp]}：{counts[(action, camp)]}")
        if len(rows) == fmt.total_hands:
            for action in ("ban", "pick"):
                limit = fmt._per_side(action)
                for camp in ("1", "2"):
                    if counts[(action, camp)] != limit[camp]:
                        errors.append(
                            f"{camp} 方 {action} 应为 {limit[camp]}，"
                            f"实际 {counts[(action, camp)]}")

    hero_errors, hero_warnings = _hero_rules(rows, fmt, strict=strict)
    errors.extend(hero_errors)
    warnings.extend(hero_warnings)
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "completed": len(rows), "total": fmt.total_hands}


# ---------------------------------------------------------------------------
# 下一手 / 合法候选
# ---------------------------------------------------------------------------

def next_action(events, fmt=None):
    """按排程返回下一手；已完成返回 None；前缀不合法抛 ValueError。"""
    fmt = fmt or DRAFT_18
    result = check_draft(events, fmt, strict=True)
    if not result["ok"]:
        raise ValueError("；".join(result["errors"]))
    rows = _rows(events)
    cursor = 0
    for phase in fmt.phases:
        take = rows[cursor:cursor + phase.total()]
        if phase.layout == "sequential":
            expected = phase.expanded()
            if len(take) < len(expected):
                action, camp = expected[len(take)]
                return {"order": cursor + len(take) + 1, "phase": phase.key,
                        "action": action, "camp": camp, "parallel": False,
                        "blind": False}
        else:
            counts = Counter(row["camp"] for row in take)
            remaining = {camp: count - counts.get(camp, 0)
                         for camp, count in phase.counts}
            open_camps = [camp for camp, left in remaining.items() if left > 0]
            if open_camps:
                return {"order": None, "phase": phase.key, "action": phase.action,
                        "parallel": phase.layout == "parallel",
                        "blind": phase.layout == "blind",
                        "camps": open_camps,
                        "remaining": {camp: remaining[camp] for camp in open_camps}}
        cursor += len(take)
    return None


def can_assign_to_players(chosen, pools):
    """五个位置与五个英雄的二分匹配；pools 为 None 时不做选手池限制。"""
    if pools is None:
        return True
    if len(pools) != 5 or len(chosen) > 5 or len(set(chosen)) != len(chosen):
        return False
    if any(not pool for pool in pools):
        return False
    assignments = {}

    def allocate(hero, visited):
        for player_id, pool in enumerate(pools):
            if player_id in visited or hero not in pool:
                continue
            visited.add(player_id)
            if player_id not in assignments or allocate(assignments[player_id], visited):
                assignments[player_id] = hero
                return True
        return False

    return all(allocate(hero, set()) for hero in chosen)


def legal_candidates(events, fmt, hero_pool, *, camp, used_pick_keys=(),
                     player_pools=None):
    """当前行动方的合法英雄列表；按排程判断该谁行动。

    * Ban：已选（任意形态）的英雄不能 Ban；``allow_shared_bans`` 时只挡本方
      已 Ban 的形态，不挡对方；否则挡全部 Ban。
    * Pick：同一英雄（元流五形态合一）本局只能出现一次；被 Ban 的形态不能选，
      其他形态可以；全局 BP 还要扣己方已用。
    """
    fmt = fmt or DRAFT_18
    nxt = next_action(events, fmt)
    if nxt is None:
        return []
    camp = str(camp)
    if nxt.get("parallel") or nxt.get("blind"):
        if camp not in nxt.get("camps", ()):
            raise ValueError("该方当前不能行动")
    elif camp != nxt["camp"]:
        raise ValueError("还没到该方行动")
    action = nxt["action"]
    rows = _rows(events)
    picked_keys = {pick_key(row["hero"]) for row in rows if row["action"] == "pick"}
    picked_forms = {ban_key(row["hero"]) for row in rows if row["action"] == "pick"}
    banned_forms = {ban_key(row["hero"]) for row in rows if row["action"] == "ban"}
    own_bans = {ban_key(row["hero"]) for row in rows
                if row["action"] == "ban" and row["camp"] == camp}
    used = {pick_key(hero) for hero in (used_pick_keys or ())}

    blocked = set()
    if action == "ban":
        blocked |= picked_keys | picked_forms
        blocked |= banned_forms if not fmt.allow_shared_bans else own_bans
    else:
        blocked |= picked_keys | picked_forms | banned_forms
        if fmt.global_bp:
            blocked |= used

    selected = [row["hero"] for row in rows
                if row["action"] == "pick" and row["camp"] == camp]
    out = []
    for hero in hero_pool or ():
        name = str(hero or "").strip()
        if not name:
            continue
        key = ban_key(name) if action == "ban" else pick_key(name)
        if key in blocked:
            continue
        if action == "ban" and ban_key(name) in blocked:
            continue
        if action == "pick" and player_pools is not None:
            if not can_assign_to_players(selected + [name], player_pools):
                continue
        out.append(name)
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# 系列赛全局 BP
# ---------------------------------------------------------------------------

def validate_series_context(bo="BO5", game_number=1):
    if bo not in SERIES_LENGTHS:
        raise ValueError("赛制必须是 BO3、BO5 或 BO7")
    if isinstance(game_number, bool) or not isinstance(game_number, int):
        raise ValueError("局数必须为整数")
    if not 1 <= game_number <= SERIES_LENGTHS[bo]:
        raise ValueError("当前局数超出了赛制范围")
    return SERIES_LENGTHS[bo]


def series_used(history, *, teams, bo="BO5", game_number=1):
    """按稳定战队身份累计己方已 Pick 的英雄（元流五形态合一）。

    只累计 Pick；Ban 不跨局；对手已选不影响我方。历史必须按真实局序连续、
    每局每方 5 个真实选人，缺一局就拒绝推算。
    """
    validate_series_context(bo, game_number)
    if not isinstance(teams, (list, tuple)) or len(teams) != 2:
        raise ValueError("必须指定系列赛双方稳定的战队身份")
    a, b = [str(team or "").strip() for team in teams]
    if not a or not b or a == b:
        raise ValueError("系列赛双方战队身份必须不同且非空")
    if not isinstance(history, (list, tuple)) or len(history) != game_number - 1:
        raise ValueError("缺少此前某局 BP 选人记录，不能确认全局英雄禁复用")
    used = {a: set(), b: set()}
    for index, row in enumerate(history, 1):
        if not isinstance(row, dict) or row.get("game") != index:
            raise ValueError("系列赛历史必须按真实局序连续排列")
        picks = row.get("picks")
        if not isinstance(picks, dict) or set(picks) != {a, b}:
            raise ValueError("历史每局必须提供双方战队真实选人")
        this_game = set()
        for team in (a, b):
            heroes = picks[team]
            if (not isinstance(heroes, (list, tuple)) or len(heroes) != 5
                    or any(not isinstance(h, str) or not h.strip() for h in heroes)):
                raise ValueError("历史每方每局必须明确提供五个英雄")
            keys = [pick_key(h) for h in heroes]
            if len(set(keys)) != 5:
                raise ValueError("同局同一方不能重复选择同一英雄")
            if used[team].intersection(keys):
                raise ValueError("该战队存在跨局复用已选英雄的非法记录")
            if not row.get("blind") and this_game.intersection(keys):
                raise ValueError("同局双方不能重复选择同一英雄")
            used[team].update(keys)
            this_game.update(keys)
    return {team: frozenset(heroes) for team, heroes in used.items()}
