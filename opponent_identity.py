"""战队身份统一解析：把「战队分析」里的命名/合并接到所有逐局视图。

背景
----
战队分析（studio/teams）用营地十人面板的阵容签名把对面五个人聚成 cluster id，
命名/教练/合并写在 ``teams`` 与 ``team_clusters`` 覆盖层里；而对局档案、系列赛
编组、跨局分析这些页面读的是 ``match.opponent`` 自由文本（外加 match_meta
逐局覆盖层）。两条链互不相通，导致战队分析里命名后，其他页面依旧是
「对手未标注 / 对手待补」。

做法
----
只在**读取时**解析，不回写任何原始数据包、不复制队名到 match_meta：

1. ``resolve_names`` 读 DB，得到 cluster id → 当前队名（合并链指向目标队）、
   历史旧队名 → 当前队名（别名）。
2. ``resolve`` 再按 camp_details 的 gameSeq 建立「这一局属于哪支战队」。
3. ``apply_to_matches`` 在内存快照上把逐局 opponent 换成当前队名，
   并把散落在自由文本里的旧队名折成当前队名。

于是改名/合并后，不用批量改历史对局，全站下一次读取就是新名字；新导入的对局
只要带 gameSeq 也自动归到已命名的战队。原始数据一个字节都不动。

本模块只做「读」；旧名登记（写覆盖层）在 ``team_clusters.record_alias``。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

import team_clusters

_CACHE = {}
_LOCK = threading.Lock()
_TTL = 5.0
# 每次改名/合并都会 clear_cache()；调用方（分析快照）用这个代际号发现自己
# 手里烤进去的旧队名已经作废，不必依赖跨模块调用或 15 秒 TTL。
_GENERATION = 0


def camp_dir_for(matches_dir):
    """营地十人面板目录；与 studio_api.camp_dir 同一口径（演示数据可重定向）。"""
    override = os.environ.get('STUDIO_CAMP_DIR')
    if override:
        return Path(override)
    return Path(matches_dir).parent / 'camp_details'


def clean(value) -> str:
    return team_clusters.clean_name(value)


def _stat(path):
    try:
        info = Path(path).stat()
        return (info.st_mtime_ns, info.st_size)
    except OSError:
        return (0, 0)


def _signature(db_path, camp_dir=None):
    db = Path(db_path)
    key = (_stat(db), _stat(str(db) + '-wal'), _stat(str(db) + '-journal'))
    if camp_dir is None:
        return key
    try:
        files = list(Path(camp_dir).glob('*.json'))
        camp = (len(files), max((_stat(path)[0] for path in files), default=0))
    except OSError:
        camp = (0, 0)
    return key + (camp,)


def _cached(name, key, builder):
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(name)
        if hit and hit[0] == key and now - hit[1] < _TTL:
            return hit[2]
    value = builder()
    with _LOCK:
        _CACHE[name] = (key, now, value)
    return value


def clear_cache():
    """改名/合并后调用：立刻丢掉解析缓存（DB 指纹也会变，这里是双保险）。"""
    global _GENERATION
    with _LOCK:
        _CACHE.clear()
        _GENERATION += 1


def generation():
    """当前命名代际号；写入方每改名/合并一次 +1。"""
    return _GENERATION


def _canonical(team_id, overrides):
    """跟随 mergedInto 链，返回最终目标战队 id；环路用 seen 截断。"""
    current, seen = str(team_id or ''), set()
    while current and current not in seen:
        seen.add(current)
        target = (overrides.get(current) or {}).get('mergedInto')
        if not target or str(target) == current:
            break
        current = str(target)
    return current


def _real_name(team_id, overrides, workspace):
    """战队当前显示名：工作区 teams 权威，覆盖层兜底；占位名不算真名。"""
    workspace_name = clean((workspace.get(team_id) or {}).get('name'))
    if workspace_name and not team_clusters.is_placeholder(workspace_name):
        return workspace_name
    override_name = clean((overrides.get(team_id) or {}).get('name'))
    if override_name and not team_clusters.is_placeholder(override_name):
        return override_name
    return ''


def _alias_list(value):
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = clean(item)
        if text and not team_clusters.is_placeholder(text) and text not in out:
            out.append(text)
    return out


def merge_alias(existing, old_name, current_name=''):
    """纯计算：把旧队名追加进别名列表。改名/合并共用，避免重复/占位名。"""
    aliases = _alias_list(existing)
    old = clean(old_name)
    if old and not team_clusters.is_placeholder(old) and old != clean(current_name) \
            and old not in aliases:
        aliases.append(old)
    return aliases


def _workspace_aliases(db_path):
    """teams.aliases（战队分析表单）与 team_aliases（旧 id 映射）。"""
    by_id, old_ids = {}, {}
    path = Path(db_path)
    if not path.is_file():
        return by_id, old_ids
    try:
        connection = sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)
        try:
            for team_id, raw in connection.execute('SELECT id, aliases FROM teams'):
                try:
                    by_id[str(team_id)] = _alias_list(json.loads(raw or '[]'))
                except (TypeError, ValueError):
                    continue
            for old_id, team_id in connection.execute(
                    'SELECT old_id, team_id FROM team_aliases'):
                old_ids[str(old_id)] = str(team_id)
        finally:
            connection.close()
    except sqlite3.Error:
        pass
    return by_id, old_ids


def resolve_names(db_path):
    """只读 DB：{names, aliases, canonical}。

    names:     cluster id（含被合并的源 id）→ 当前队名
    aliases:   旧队名 / 旧 id → 当前队名，用来把历史自由文本折成新名字
    canonical: cluster id → 合并后的目标 id
    """
    def build():
        overrides = team_clusters.load_overrides(db_path)
        workspace = team_clusters.load_workspace_teams(db_path)
        ws_aliases, old_ids = _workspace_aliases(db_path)
        ids = set(overrides) | set(workspace) | set(ws_aliases) | set(old_ids.values())
        canonical = {key: _canonical(key, overrides) for key in ids}
        names = {}
        for key in ids:
            name = _real_name(canonical[key], overrides, workspace)
            if name:
                names[key] = name
        aliases = {}
        for key, name in names.items():
            # 按 id 过滤也要认得新名字（match_facts 用 opponentId 当筛选值）
            aliases.setdefault(str(key), name)
            for source in (key, canonical[key]):
                aliases.setdefault(str(source), name)
                for old in _alias_list((overrides.get(source) or {}).get('aliases')):
                    aliases.setdefault(old, name)
                for old in ws_aliases.get(source, []):
                    aliases.setdefault(old, name)
                old_override = clean((overrides.get(source) or {}).get('name'))
                old_workspace = clean((workspace.get(source) or {}).get('name'))
                for old in (old_override, old_workspace):
                    if old and not team_clusters.is_placeholder(old) and old != name:
                        aliases.setdefault(old, name)
        # 被合并掉的源战队的旧 id 也要能查到目标队
        for old_id, team_id in old_ids.items():
            target = canonical.get(team_id, team_id)
            name = names.get(target)
            if name:
                aliases.setdefault(str(old_id), name)
        return {'names': names, 'aliases': aliases, 'canonical': canonical}

    return _cached('names', _signature(db_path), build)


def resolve(db_path, camp_dir):
    """完整解析：DB 名字 + camp_details 的 gameSeq → 战队归属。"""
    def build():
        names = resolve_names(db_path)
        seq_to_id, by_id = {}, dict(names['names'])
        try:
            panels = team_clusters.load_panels(camp_dir)
        except (OSError, ValueError):
            panels = []
        for cluster in team_clusters.build(
                panels, team_clusters.cluster_key_of(db_path, panels))['clusters']:
            team_id = names['canonical'].get(cluster['id'], cluster['id'])
            for seq in cluster['seqs']:
                seq_to_id[str(seq)] = team_id
        by_seq = {seq: by_id.get(team_id, '') for seq, team_id in seq_to_id.items()}
        return {**names, 'byId': by_id, 'bySeq': by_seq, 'seqToId': seq_to_id}

    return _cached('full', _signature(db_path, camp_dir), build)


def game_seq(match):
    """这一局对应的营地 gameSeq；没有面板的对局返回空串。"""
    camp_bp = match.get('campBp') or {}
    official = match.get('officialReplay') or {}
    seq = camp_bp.get('gameSeq') or official.get('gameSeq')
    if not seq and str(official.get('id') or '').startswith('camp-'):
        seq = str(official['id'])[5:]
    if not seq and str(match.get('key') or '').startswith('camp:'):
        seq = str(match['key'])[5:]
    return str(seq or '').strip()


def normalize_text(value, resolution):
    text = clean(value)
    return (resolution.get('aliases') or {}).get(text, text)


def apply_to_matches(matches, resolution):
    """把战队当前队名写进内存快照的逐局 opponent；不落盘、不改原始包。"""
    if not resolution or not (resolution.get('names') or resolution.get('aliases')):
        return
    by_id = resolution.get('byId') or resolution.get('names') or {}
    seq_to_id = resolution.get('seqToId') or {}
    aliases = resolution.get('aliases') or {}
    for match in matches:
        # 「匹配与编组」保存的 opponentTeamId 是教练确认过的归属，优先于
        # camp_details 面板按 gameSeq 推出来的旧 cluster id：面板的 cluster
        # 可能已改名/合并，旧 id 解析不到队名，以前会把它写回 match，反而
        # 把已匹配的队名抹掉，于是局列表里还是「对手未标注」。
        explicit_id = clean(match.get('opponentTeamId'))
        record_id = clean(match.get('recordTeamId'))
        seq_id = seq_to_id.get(game_seq(match))
        named = False
        for team_id in (explicit_id, record_id, seq_id):
            if not team_id:
                continue
            name = by_id.get(team_id) or aliases.get(team_id)
            if not name:
                continue
            match['opponentTeamId'] = team_id
            match['opponent'] = name
            match['opponentNameSource'] = 'team'
            named = True
            break
        if named:
            continue
        text = clean(match.get('opponent'))
        if text and text in aliases:
            match['opponent'] = aliases[text]
            match['opponentNameSource'] = 'alias'
