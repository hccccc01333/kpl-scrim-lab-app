"""Read-only analysis API router, shared by the workbench and standalone dev app."""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from analysis_data import ALL_SOURCES, DEFAULT_SOURCES, AnalysisRepository


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
            'includePartial': query.get('includePartial') in ('1', 'true', 'yes'),
        }

    @router.get('/overview')
    def overview(request: Request):
        return repository.overview(filters(request))

    @router.get('/filters')
    def filter_options():
        return repository.filters()

    @router.get('/players')
    def players(request: Request):
        values = filters(request)
        return {'players': repository.player_stats(values), 'filters': values}

    @router.get('/players/{key:path}/trend')
    def player_trend(key: str, request: Request):
        return repository.player_trend(key, filters(request))

    @router.get('/heroes')
    def heroes(request: Request):
        values = filters(request)
        return {'heroes': repository.hero_stats(values), 'filters': values}

    @router.get('/teams')
    def teams(request: Request):
        values = filters(request)
        return {'team': repository.team_stats(values), 'filters': values}

    @router.get('/matches')
    def matches(request: Request):
        return repository.matches(filters(request))

    @router.get('/lane-matchups')
    def lane_matchups(request: Request):
        return repository.lane_matchups(filters(request))

    @router.get('/profiles')
    def profiles(request: Request):
        return repository.profiles(filters(request))

    @router.get('/pairs')
    def pairs(request: Request):
        return repository.pairs(filters(request))

    @router.get('/process')
    def process(request: Request):
        return repository.process(filters(request))

    @router.get('/bp')
    def bp_summary(request: Request):
        return repository.bp_summary(filters(request))

    @router.get('/objectives')
    def objectives(request: Request):
        return repository.objectives(filters(request))

    @router.get('/scouting')
    def scouting(request: Request):
        return repository.scouting(filters(request))

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
