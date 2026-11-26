"""Read-only analysis API router, shared by the workbench and standalone dev app."""
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from analysis_data import ALL_SOURCES, DEFAULT_SOURCES, AnalysisRepository


class CompetitionScopedRepository(AnalysisRepository):
    """叠加「赛事直连对局」约束的分析仓库。

    每次请求构造独立实例、共享已加载快照：不修改 analysis_data 的查询实现，
    也不把可变状态挂到全局仓库上（多线程请求安全）。只覆盖 _selected_rows，
    _selected_matches 内部会调用它，于是所有走统一筛选口径的端点（matches /
    teams / players / heroes / bp / ...）自动按赛事收窄。
    """

    def __init__(self, *args, match_keys=(), shared_data=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._competition_match_keys = frozenset(match_keys)
        if shared_data is not None:
            self._data = shared_data

    def _selected_rows(self, filters):
        rows, warnings = super()._selected_rows(filters)
        if filters.get('competition') and self._competition_match_keys is not None:
            rows = [row for row in rows if row.get('matchKey') in self._competition_match_keys]
        return rows, warnings


def create_analysis_router(db_path, matches_dir, imports_dir, official_dir=None):
    repository = AnalysisRepository(Path(db_path), Path(matches_dir), Path(imports_dir),
                                    official_dir=official_dir)
    router = APIRouter(prefix='/api/analysis', tags=['analysis'])

    def filters(request: Request):
        query = request.query_params
        sources = [item.strip() for item in query.get('source', '').split(',') if item.strip()]
        return {
            'sources': [item for item in sources if item in ALL_SOURCES] or list(DEFAULT_SOURCES),
            'from': query.get('from') or None,
            'to': query.get('to') or None,
            'player': query.get('player') or None,
            'hero': query.get('hero') or None,
            'opponent': query.get('opponent') or None,
            'session': query.get('session') or None,
            'version': query.get('version') or None,
            'result': query.get('result') or None,
            'camp': query.get('camp') or None,
            # 赛事归属：全站唯一数据范围。不传时保持原有口径。
            'competition': query.get('competition') or query.get('competitionId') or None,
            'includePartial': query.get('includePartial') in ('1', 'true', 'yes'),
        }

    def competition_match_keys(competition_id, data=None):
        """赛事下的对局 key：DB 归属 + 文件层落在赛事窗口内的对局。

        DB scope 只覆盖 match_records 登记过的局；营地采集 / 表格导入可能只落
        数据包，不在权威表建行，会被赛事域分析页整批漏掉（首页无赛事参数仍可见）。
        这里按赛事窗口把快照里的文件层对局补齐，同时保留单一赛事归属纪律。
        """
        keys = set()
        if competition_id and Path(db_path).is_file():
            try:
                from workspace_store import Workspace
                # 赛事域（M1）：统一走 scope 口径（直连 U 训练起止 U 手动挂载 U 正赛）。
                keys |= set(Workspace(db_path).competition_scope_keys(competition_id))
            except (sqlite3.Error, OSError):
                pass
        if not competition_id or not isinstance(data, dict):
            return keys
        try:
            from workspace_store import Workspace
            ws = Workspace(db_path)
            competition = ws.get_competition(competition_id)
            if not competition:
                return keys
            training = ws._collect_bounds(competition)
            formal = ws._date_bounds(competition.get('formal_from'),
                                     competition.get('formal_to')) or training
            other = set()
            with sqlite3.connect(f'file:{Path(db_path).as_posix()}?mode=ro', uri=True) as conn:
                other = {str(row[0]) for row in conn.execute(
                    'SELECT match_key FROM match_records '
                    'WHERE competition_id IS NOT NULL AND competition_id != "" '
                    'AND competition_id != ?', (competition_id,))}
            for match in list(data.get('matches') or []) + list(data.get('sheetMatches') or []):
                key = str(match.get('key') or '')
                if not key or key in keys or key in other:
                    continue
                day = str(match.get('date') or '')[:10]
                if day and (ws._in_window(day, training) or ws._in_window(day, formal)):
                    keys.add(key)
        except (sqlite3.Error, OSError, ValueError):
            pass
        return keys

    def scoped(values):
        """按当前请求的赛事选取仓库；无赛事参数时直接复用原仓库。"""
        competition = values.get('competition')
        if not competition:
            return repository
        keys = competition_match_keys(competition, repository.get())
        return CompetitionScopedRepository(
            Path(db_path), Path(matches_dir), Path(imports_dir), official_dir=official_dir,
            match_keys=keys, shared_data=repository.get())

    @router.get('/overview')
    def overview(request: Request):
        values = filters(request)
        return scoped(values).overview(values)

    @router.get('/filters')
    def filter_options():
        return repository.filters()

    @router.get('/players')
    def players(request: Request):
        values = filters(request)
        return {'players': scoped(values).player_stats(values), 'filters': values}

    @router.get('/players/{key:path}/trend')
    def player_trend(key: str, request: Request):
        values = filters(request)
        return scoped(values).player_trend(key, values)

    @router.get('/heroes')
    def heroes(request: Request):
        values = filters(request)
        return {'heroes': scoped(values).hero_stats(values), 'filters': values}

    @router.get('/teams')
    def teams(request: Request):
        values = filters(request)
        return {'team': scoped(values).team_stats(values), 'filters': values}

    @router.get('/matches')
    def matches(request: Request):
        values = filters(request)
        return scoped(values).matches(values)

    @router.get('/lane-matchups')
    def lane_matchups(request: Request):
        values = filters(request)
        return scoped(values).lane_matchups(values)

    @router.get('/profiles')
    def profiles(request: Request):
        values = filters(request)
        return scoped(values).profiles(values)

    @router.get('/pairs')
    def pairs(request: Request):
        values = filters(request)
        return scoped(values).pairs(values)

    @router.get('/process')
    def process(request: Request):
        values = filters(request)
        return scoped(values).process(values)

    @router.get('/bp')
    def bp_summary(request: Request):
        values = filters(request)
        return scoped(values).bp_summary(values)

    @router.get('/objectives')
    def objectives(request: Request):
        values = filters(request)
        return scoped(values).objectives(values)

    @router.get('/scouting')
    def scouting(request: Request):
        values = filters(request)
        return scoped(values).scouting(values)

    @router.get('/matches/{key:path}')
    def match_detail(key: str):
        detail = repository.match_detail(key)
        if detail is None:
            raise HTTPException(404, '比赛不存在')
        return detail

    @router.get('/sources')
    def sources():
        return repository.sources()

    @router.get('/imports')
    def imports():
        return repository.imports()

    @router.get('/imports/{import_id}/rows')
    def import_rows(import_id: str, sheet: str, limit: int = 500, offset: int = 0):
        if not 1 <= limit <= 2000 or offset < 0:
            raise HTTPException(400, '分页参数无效')
        value = repository.import_rows(import_id, sheet, limit=limit, offset=offset)
        if value is None:
            raise HTTPException(404, '导入表不存在')
        return value

    @router.post('/reload')
    def reload():
        repository.invalidate()
        data = repository.get()
        return {'ok': True, 'matches': len(data['matches']), 'imports': len(data['imports']),
                'warnings': data['warnings']}

    return router
