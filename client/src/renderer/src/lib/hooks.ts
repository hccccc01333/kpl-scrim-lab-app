import { useQuery } from '@tanstack/react-query'
import { api, queryString } from './api'
import type {
  BpBoard,
  CampCompare,
  CampPartners,
  CampCombos,
  CoachBoard,
  CrossVectors,
  DepthAnalysis,
  EquipImpactPayload,
  EquipMatrixPayload,
  HeroDetailData,
  LaneMatchupPayload,
  CampSync,
  ChannelDetail,
  ChannelSummary,
  Health,
  MatchDetail,
  MatchSummary,
  Metadata,
  OfficialReplaysData,
  Overview,
  PlayerBoard,
  PlayerDetail,
  PlayersBoard,
  PositionsData,
  ReplayData,
  ResearchReportDetail,
  ResearchReportsData,
  SchedulesResponse,
  TeamBpRow,
  TeamTrainingData,
  TeamsBoard,
  TempoData,
  TrainingDashboardData,
  TrainingEffectData,
  TrainingSessionData,
  WeekMetrics,
  TrainingDashboard
} from './types'

const common = {
  staleTime: 30_000,
  refetchOnWindowFocus: false,
  retry: 1
}

export function useHealth(baseUrl: string, active = true) {
  return useQuery({
    queryKey: ['health', baseUrl],
    queryFn: () => api<Health>(baseUrl, '/api/health', { timeout: 4500 }),
    enabled: active && Boolean(baseUrl),
    retry: false,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    staleTime: 8_000
  })
}

export function useMetadata(baseUrl: string) {
  return useQuery({
    queryKey: ['metadata', baseUrl],
    queryFn: () => api<Metadata>(baseUrl, '/api/metadata'),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 10 * 60_000
  })
}

export function useOverview(baseUrl: string) {
  return useQuery({
    queryKey: ['overview', baseUrl],
    queryFn: () => api<Overview>(baseUrl, '/api/overview'),
    enabled: Boolean(baseUrl),
    ...common
  })
}

export function useMatches(baseUrl: string) {
  return useQuery({
    queryKey: ['matches', baseUrl],
    queryFn: async () => {
      const data = await api<{ matches: MatchSummary[]; warnings?: string[] }>(baseUrl, '/api/matches')
      return data.matches || []
    },
    enabled: Boolean(baseUrl),
    ...common
  })
}

export function useMatch(baseUrl: string, key: string) {
  return useQuery({
    queryKey: ['match', baseUrl, key],
    queryFn: () => api<MatchDetail>(baseUrl, `/api/matches/${encodeURIComponent(key)}`, { timeout: 60_000 }),
    enabled: Boolean(baseUrl && key),
    ...common
  })
}

export function useReplay(baseUrl: string, key: string) {
  return useQuery({
    queryKey: ['replay', baseUrl, key],
    queryFn: () => api<ReplayData>(baseUrl, `/api/replay/${encodeURIComponent(key)}`, { timeout: 60_000 }),
    enabled: Boolean(baseUrl && key),
    staleTime: 10 * 60_000,
    retry: false,
    refetchOnWindowFocus: false
  })
}

export function usePositions(baseUrl: string, key: string) {
  return useQuery({
    queryKey: ['positions', baseUrl, key],
    queryFn: () => api<PositionsData>(baseUrl, `/api/positions/${encodeURIComponent(key)}`, { timeout: 60_000 }),
    enabled: Boolean(baseUrl && key),
    staleTime: 10 * 60_000,
    retry: false,
    refetchOnWindowFocus: false
  })
}

export function usePlayerBoard(baseUrl: string) {
  return useQuery({
    queryKey: ['player-board', baseUrl],
    queryFn: () => api<PlayerBoard>(baseUrl, '/api/v3/players/board'),
    enabled: Boolean(baseUrl),
    ...common
  })
}

export function usePlayer(baseUrl: string, key: string) {
  return useQuery({
    queryKey: ['player', baseUrl, key],
    queryFn: () => api<PlayerDetail>(baseUrl, `/api/players/${encodeURIComponent(key)}`),
    enabled: Boolean(baseUrl && key),
    ...common
  })
}

export function useTeams(baseUrl: string) {
  return useQuery({
    queryKey: ['teams', baseUrl],
    queryFn: () => api<TeamsBoard>(baseUrl, '/api/studio/teams'),
    enabled: Boolean(baseUrl),
    ...common
  })
}

export function useCrossVectors(baseUrl: string) {
  return useQuery({
    queryKey: ['cross-vectors', baseUrl],
    queryFn: () => api<CrossVectors>(baseUrl, '/api/cross/vectors', { timeout: 90_000 }),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function useTempo(baseUrl: string) {
  return useQuery({
    queryKey: ['tempo', baseUrl],
    queryFn: () => api<TempoData>(baseUrl, '/api/tempo', { timeout: 60_000 }),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function usePlayersBoard(baseUrl: string) {
  return useQuery({
    queryKey: ['players-board-v3', baseUrl],
    queryFn: () => api<PlayersBoard>(baseUrl, '/api/v3/players-board', { timeout: 60_000 }),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function useCampCompare(baseUrl: string, teamId?: string) {
  return useQuery({
    queryKey: ['camp-compare', baseUrl, teamId || ''],
    queryFn: () => api<CampCompare>(baseUrl, `/api/studio/camp-compare${queryString({ team: teamId })}`, { timeout: 60_000 }),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function useCampPartners(baseUrl: string, hero: string) {
  return useQuery({
    queryKey: ['camp-partners', baseUrl, hero],
    queryFn: () => api<CampPartners>(baseUrl, `/api/studio/camp-partners${queryString({ hero })}`),
    enabled: Boolean(baseUrl && hero),
    ...common,
    staleTime: 5 * 60_000
  })
}

export function useCampCombos(baseUrl: string, min = 3) {
  return useQuery({
    queryKey: ['camp-combos', baseUrl, min],
    queryFn: () => api<CampCombos>(baseUrl, `/api/studio/camp-combos${queryString({ min })}`),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 5 * 60_000
  })
}

export function useBpBoard(baseUrl: string) {
  return useQuery({
    queryKey: ['bp-board', baseUrl],
    queryFn: () => api<BpBoard>(baseUrl, '/api/v3/bp-board', { timeout: 60_000 }),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function useTeamBp(baseUrl: string) {
  return useQuery({
    queryKey: ['team-bp', baseUrl],
    queryFn: async () => {
      const data = await api<{ teams: TeamBpRow[] }>(baseUrl, '/api/v3/team-bp', { timeout: 60_000 })
      return data.teams || []
    },
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function useCoachBoard(baseUrl: string) {
  return useQuery({
    queryKey: ['coach-board', baseUrl],
    queryFn: () => api<CoachBoard>(baseUrl, '/api/studio/coach'),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function useTeamTraining(baseUrl: string) {
  return useQuery({
    queryKey: ['team-training', baseUrl],
    queryFn: () => api<TeamTrainingData>(baseUrl, '/api/v3/team-training', { timeout: 60_000 }),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function useHeroDetail(baseUrl: string, hero: string) {
  return useQuery({
    queryKey: ['hero-detail', baseUrl, hero],
    queryFn: () => api<HeroDetailData>(baseUrl, `/api/v3/hero-detail/${encodeURIComponent(hero)}`, { timeout: 60_000 }),
    enabled: Boolean(baseUrl && hero),
    ...common,
    staleTime: 5 * 60_000
  })
}

export function useLaneMatchup(baseUrl: string) {
  return useQuery({
    queryKey: ['depth-lane-matchup', baseUrl],
    queryFn: () => api<DepthAnalysis<LaneMatchupPayload>>(baseUrl, '/api/depth/analysis/lane_matchup', { timeout: 60_000 }),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 5 * 60_000
  })
}

export function useEquipMatrix(baseUrl: string, hero: string) {
  return useQuery({
    queryKey: ['depth-equip-matrix', baseUrl, hero],
    queryFn: () => api<DepthAnalysis<EquipMatrixPayload>>(baseUrl, `/api/depth/analysis/equip_matrix${queryString({ hero })}`, { timeout: 60_000 }),
    enabled: Boolean(baseUrl && hero),
    ...common,
    staleTime: 5 * 60_000
  })
}

export function useEquipImpact(baseUrl: string, hero: string) {
  return useQuery({
    queryKey: ['depth-equip-impact', baseUrl, hero],
    queryFn: () => api<DepthAnalysis<EquipImpactPayload>>(baseUrl, `/api/depth/analysis/equip_impact${queryString({ hero })}`, { timeout: 60_000 }),
    enabled: Boolean(baseUrl && hero),
    ...common,
    staleTime: 5 * 60_000
  })
}

export function useTrainingDashboard(baseUrl: string) {
  return useQuery({
    queryKey: ['training-dashboard', baseUrl],
    queryFn: () => api<TrainingDashboardData>(baseUrl, '/api/studio/workspace/dashboard'),
    enabled: Boolean(baseUrl),
    ...common
  })
}


export function useSchedules(baseUrl: string) {
  return useQuery({
    queryKey: ['schedules', baseUrl],
    queryFn: () => api<SchedulesResponse>(baseUrl, '/api/studio/workspace/schedules'),
    enabled: Boolean(baseUrl),
    ...common
  })
}

export function useTrainingEffect(baseUrl: string) {
  return useQuery({
    queryKey: ['training-effect', baseUrl],
    queryFn: () => api<TrainingEffectData>(baseUrl, '/api/v3/effect', { timeout: 60_000 }),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function useTrainingSession(baseUrl: string, id: string) {
  return useQuery({
    queryKey: ['training-session', baseUrl, id],
    queryFn: () => api<TrainingSessionData>(baseUrl, `/api/studio/workspace/sessions/${encodeURIComponent(id)}`),
    enabled: Boolean(baseUrl && id),
    ...common
  })
}

export function useWeeklyMetrics(baseUrl: string, start: string) {
  return useQuery({
    queryKey: ['training-week', baseUrl, start],
    queryFn: () => api<WeekMetrics>(baseUrl, `/api/studio/workspace/metrics/week${queryString({ start })}`, { timeout: 60_000 }),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 2 * 60_000
  })
}

export function useResearchReports(baseUrl: string) {
  return useQuery({
    queryKey: ['research-reports', baseUrl],
    queryFn: () => api<ResearchReportsData>(baseUrl, '/api/v3/research/reports'),
    enabled: Boolean(baseUrl),
    ...common
  })
}

export function useResearchReport(baseUrl: string, id: string) {
  return useQuery({
    queryKey: ['research-report', baseUrl, id],
    queryFn: () => api<ResearchReportDetail>(baseUrl, `/api/v3/research/reports/${encodeURIComponent(id)}`),
    enabled: Boolean(baseUrl && id),
    ...common
  })
}

export function useOfficialReplays(baseUrl: string) {
  return useQuery({
    queryKey: ['official-replays', baseUrl],
    queryFn: () => api<OfficialReplaysData>(baseUrl, '/api/official/replays'),
    enabled: Boolean(baseUrl),
    ...common,
    staleTime: 30_000
  })
}

export function useCampStatus(baseUrl: string) {
  return useQuery({
    queryKey: ['camp-status', baseUrl],
    queryFn: () => api<CampSync>(baseUrl, '/api/camp/sync'),
    enabled: Boolean(baseUrl),
    staleTime: 5_000,
    retry: 1,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => (query.state.data?.running ? 2500 : false)
  })
}

export function useChannels(baseUrl: string) {
  return useQuery({
    queryKey: ['channels', baseUrl],
    queryFn: async () => {
      const data = await api<{ channels: ChannelSummary[] }>(baseUrl, '/api/channels')
      return data.channels || []
    },
    enabled: Boolean(baseUrl),
    ...common
  })
}

export function useChannel(baseUrl: string, id: string) {
  return useQuery({
    queryKey: ['channel', baseUrl, id],
    queryFn: () => api<ChannelDetail>(baseUrl, `/api/channels/${encodeURIComponent(id)}`),
    enabled: Boolean(baseUrl && id),
    ...common
  })
}
