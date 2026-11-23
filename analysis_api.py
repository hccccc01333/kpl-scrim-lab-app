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
            # 赛事归属：对局直连 match_records.competition_id。不传时保持原有口径。
            'competition': query.get('competition') or query.get('competitionId') or None,
            'includePartial': query.get('includePartial') in ('1', 'true', 'yes'),
        }

    def competition_match_keys(competition_id):
        """赛事下的对局 key；老库无 match_records 时视为空集。"""
        if not competition_id or not Path(db_path).is_file():
            return set()
        try:
            from workspace_store import Workspace
            # 赛事域（M1）：统一走 scope 口径（直连 U 归集窗口 U 手动挂载 U 正赛）。
            return Workspace(db_path).competition_scope_keys(competition_id)
        except (sqlite3.Error, OSError):
            return set()

    def scoped(values):
        """按当前请求的 filters 选取仓库；无 competition 参数时直接复用原仓库。"""
        competition = values.get('competition')
        if not competition:
            return repository
        return CompetitionScopedRepository(
            Path(db_path), Path(matches_dir), Path(imports_dir), official_dir=official_dir,
            match_keys=competition_match_keys(competition), shared_data=repository.get())

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
