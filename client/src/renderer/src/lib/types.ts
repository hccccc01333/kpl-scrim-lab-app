export interface Health {
  ok: boolean
  version?: string
  releaseDate?: string
  releaseName?: string
  dbPath?: string
  matchesDir?: string
  importsDir?: string
  pid?: number
  demo?: boolean
}

export interface Metadata {
  teamName?: string
  demo?: boolean
  icons?: Record<string, string>
  [key: string]: unknown
}

export interface TopHero {
  hero: string
  picks: number
  wins: number
  decided: number
  winRate: number
  positions?: string[]
}

export interface Coverage {
  timelineMatches: number
  scoreboardMatches: number
  povMatches: number
  completeMatches: number
  partialRows: number
  unknownOpponentMatches: number
}

export interface Summary {
  teamName: string
  coach?: string
  season?: string
  matches: number
  decided: number
  wins: number
  winRate: number
  players: number
  heroes: number
  ownPlayers: number
  ownHeroes?: number
  boundPlayers: number
  rows?: number
  sources?: string[]
  coverage: Coverage
  topHeroes?: TopHero[]
  inventory?: Record<string, number>
  dataQuality?: {
    score: number
    total: number
    checks: { key: string; label: string; ok: number; missing: number; total: number; hint: string }[]
  }
}

export interface TeamOpponent {
  name: string
  matches: number
  wins: number
  decided: number
  winRate: number
}

export interface TeamOverview {
  available: boolean
  matches: number
  fullMatches: number
  wins: number
  decided: number
  winRate: number
  avgGold: number
  avgKills: number
  avgDamage: number
  avgTaken: number
  avgGoldDiff: number | null
  side?: Record<string, number>
  opponents?: TeamOpponent[]
}

export interface MatchSummary {
  key: string
  date: string
  dateText?: string
  opponent?: string | null
  session?: string | null
  version?: string | null
  duration?: number | null
  mode?: string | null
  title?: string | null
  sources?: string[]
  source?: string
  ownCamp?: string
  result?: 'win' | 'loss' | 'draw' | 'unknown' | string
  scores?: Record<string, number>
  players?: number
  complete?: boolean
  hasTimeline?: boolean
  hasScoreboard?: boolean
  hasPov?: boolean
  warnings?: number | string[]
  isSeed?: boolean
  own?: TeamSideSummary | null
  enemy?: TeamSideSummary | null
  goldDiff?: number | null
  missing?: string[]
  heroes?: string[]
}

export interface TeamSideSummary {
  kills: number
  deaths: number
  assists: number
  gold: number
  damage: number
  games: number
  kda: number
}

export interface ProcessMatch {
  key?: string
  date?: string
  opponent?: string
  points?: [number, number][]
  coverage?: number
  finalDiff?: number
  observedStart?: number
  observedEnd?: number
  [key: string]: unknown
}

export interface ProcessAggregate {
  games: number
  leadAt10Conversion: number | null
  leadAt10Games: number
  avgDiffAt: Record<string, number>
  landmarkSamples: Record<string, number>
  avgPhases?: Record<string, number>
  phaseSamples?: Record<string, number>
  comebacks?: number
  blownLeads?: number
  avgKillsPerMinute?: number
  [key: string]: unknown
}

export interface ProcessData {
  gate?: unknown
  matches: ProcessMatch[]
  aggregate?: ProcessAggregate
  dataQuality?: unknown
  warnings?: string[]
}

export interface Overview {
  summary: Summary
  team: TeamOverview
  matches: MatchSummary[]
  process: ProcessData
}

export interface HeroPick {
  name: string
  id?: string
  icon?: string
  lane?: string | null
}

export interface Draft {
  source?: string
  bans?: { left?: HeroPick[]; right?: HeroPick[] }
  picks?: { left?: HeroPick[]; right?: HeroPick[] }
  pickOrderKnown?: boolean
  firstPick?: string
  [key: string]: unknown
}

export interface MatchPlayer {
  playerId: string
  label: string
  camp: string
  side?: string
  slot: number
  hero: string
  position?: string
  kills: number
  deaths: number
  assists: number
  gold: number
  damage: number
  taken: number
  participation?: number | null
  rating?: number | null
  cs?: number | null
  bound?: boolean
  partial?: boolean
  finalSource?: string
  [key: string]: unknown
}

export interface TeamTotalsSide {
  players: number
  totals: { kills: number; gold: number; damage: number; taken: number }
  complete: boolean
}

export interface TimelinePoint {
  gameTime: number
  blueGold: number
  redGold: number
}

export interface MatchDetail extends Omit<MatchSummary, 'players' | 'warnings'> {
  campBacked?: boolean
  campBp?: unknown
  process?: {
    timeline?: TimelinePoint[]
    scoreboardSnapshots?: unknown[]
    killEvents?: unknown[]
    [key: string]: unknown
  } | null
  players?: MatchPlayer[]
  draft?: Draft | null
  teamTotals?: Record<string, TeamTotalsSide>
  bp?: unknown
  teamSide?: string
  warnings?: string[]
}

export interface PlayerHero {
  hero: string
  matches: number
}

export interface RosterPlayer {
  id: string
  label: string
  position?: string
  games: number
  wins: number
  decided: number
  winRate: number
  kda: number
  gpm: number
  dpm: number
  participation: number
  lastDate?: string
  heroes: PlayerHero[]
  played: boolean
}

export interface PlayerStat {
  playerKey: string
  playerId: string
  label: string
  bound: boolean
  matches: number
  wins: number
  decided: number
  winRate: number
  kills: number
  deaths: number
  assists: number
  kda: number
  kdaPerfectMatches?: number
  gpm: number
  dpm: number
  tpm: number
  goldShare: number
  damageShare: number
  takenShare: number
  participation: number
  rating?: number | null
  heroes: PlayerHero[]
  positions: string[]
  lastDate?: string
  [key: string]: unknown
}

export interface PlayerForm {
  id: string
  label?: string
  samples: number
  available: boolean
  prior: number
  recent: number
  delta: number
  tone: 'up' | 'down' | 'flat' | string
}

export interface PlayerPair {
  a: { id: string; label: string }
  b: { id: string; label: string }
  games: number
  wins: number
  winRate: number
}

export interface UnboundPlayer {
  label: string
  games: number
  lastDate?: string
}

export interface PlayerBoard {
  teamName: string
  players: PlayerStat[]
  roster: RosterPlayer[]
  form: PlayerForm[]
  pairs: PlayerPair[]
  unbound: UnboundPlayer[]
  summary: {
    matches: number
    roster: number
    played: number
    bench: number
    unbound: number
    unboundGames: number
    rising: number
    falling: number
    formReady: number
  }
  warnings?: string[]
}

export interface PlayerPoint {
  matchKey: string
  date: string
  opponent: string
  result: string
  hero: string
  kills: number
  deaths: number
  assists: number
  kda: number
  gold: number
  gpm: number
  damage: number
  dpm: number
  participation: number
  rating?: number | null
  source?: string
  partial?: boolean
}

export interface PlayerDetail {
  stats: PlayerStat | null
  playerKey: string
  label: string
  points: PlayerPoint[]
  warnings?: string[]
}

export interface TeamPlayer {
  id: string
  name: string
  lane?: string
  games: number
}

export interface TeamGame {
  seq: string
  start: string
  win: boolean
  map?: string
  duration?: number
}

export interface TeamInfo {
  id: string
  name: string
  displayName?: string
  named?: boolean
  matches: number
  wins: number
  losses: number
  winRate: number
  firstSeen?: string
  lastSeen?: string
  players: TeamPlayer[]
  heroes: { hero: string; games: number }[]
  games?: TeamGame[]
  metrics?: Record<string, number>
  percentiles?: Record<string, number>
  roster?: unknown
}

export interface TeamsResponse {
  own: TeamInfo
  teams: TeamInfo[]
  suggestions?: unknown[]
  summary?: unknown
  warnings?: string[]
}

export interface TrainingWeek {
  start: string
  end: string
  label: string
  sessionCount: number
  gameCount: number
  duration: number | null
  goalCompletion: number | null
  reviewCompletion: number | null
  goalMetricCoverage: number | null
  linkCoverage: number | null
}

export interface TrainingGoal {
  id?: string
  title?: string
  label?: string
  metric?: string
  target?: number
  actual?: number
  state?: string
  status?: string
  [key: string]: unknown
}

export interface TrainingDashboard {
  weeks: TrainingWeek[]
  days: unknown[]
  goals: TrainingGoal[] | Record<string, TrainingGoal>
  recent: unknown[]
  current?: unknown
}

export interface CampAuth {
  authorized: boolean
  nickname?: string
  userId?: string
  loginAt?: string
  expired?: boolean
  reason?: string
  code?: string
  checkedAt?: string
  invalidAt?: string
  valid?: boolean | null
  cached?: boolean
}

export interface CampPlayer {
  campUserId: string
  nickname: string
}

export interface CampConfig {
  players: CampPlayer[]
}

export interface CampSyncDetail {
  gameSeq: string
  mapName?: string
  gametime?: string
  startedAt?: string
  eventAt?: string
  battleType?: string
  winCamp?: string
  kda?: (number | null)[]
  syncedAt?: number
  channelId?: string
}

export interface CampSyncResultPlayer {
  nickname?: string
  campUserId?: string
  ok?: boolean
  authInvalid?: boolean
  reason?: string
  error?: string
  summary?: unknown
}

export interface CampSync {
  running: boolean
  result?: { players?: CampSyncResultPlayer[]; autoAttached?: unknown[] } | null
  error?: string | null
  startedAt?: number | null
  finishedAt?: number | null
  detailsCount: number
  details: CampSyncDetail[]
  config: CampConfig
  auth: CampAuth
}

export interface CampEntry {
  gameSeq: string
  dtEventTime: number
  usedTime: number
  startedAt?: string | null
  gameSvrId?: string | null
  relaySvrId?: string | null
  uniqueRoleId?: string | null
  campDetailAvailable?: boolean | null
  channelReady?: boolean
  channelExists?: boolean
  detailCached?: boolean
  mapName?: string
  gametime?: string
  battleType?: string
  winCamp?: string
  killcnt?: number
  deadcnt?: number
  assistcnt?: number
  imported?: boolean
  hero?: string
  heroName?: string
  heroIcon?: string
  heroId?: string | number
  kda?: (number | null)[]
  gameresult?: number | string | null
  gradeGame?: number | null
  roleJobName?: string
  desc?: string
  ownerName?: string
  ownerCampUserId?: string
  owners?: string[]
}

export interface CampListResult {
  entries: CampEntry[]
  hasMore?: boolean
  lastTime?: number
  gaming?: unknown
}

export interface OfficialReplayRow {
  id: string
  meta?: Record<string, unknown>
  [key: string]: unknown
}

export interface OfficialReplaysData {
  schema?: string
  replays: OfficialReplayRow[]
}

export interface CampQr {
  taskId: string
  qrcodeBase64: string
}

export interface CampPoll {
  status: string
  message?: string
  nickname?: string
  userId?: string
}

export interface ChannelMatch {
  date?: string
  session?: string
  mode?: string
  opponent?: string
  scores?: { left?: number; right?: number; blue?: number; red?: number }
  winner?: string
  ownSide?: string
  durationSec?: number
  version?: string
  heroName?: string
  heroIcon?: string
  kda?: (number | null)[]
  gameresult?: number | string | null
  gradeGame?: number | null
  roleJobName?: string
  desc?: string
  [key: string]: unknown
}

export interface ChannelSourceStatus {
  counts?: Record<string, number>
  requiredSources?: string[]
  missing?: string[]
  complete?: boolean
}

export interface ChannelReview {
  status?: string
  reviewedBy?: string
  reviewedAt?: string
  notes?: string
}

export interface ChannelSaved {
  status?: string
  bundleKey?: string
  savedAt?: string
}

export interface ChannelLog {
  at?: string
  action?: string
  actor?: string
  detail?: unknown
}

export interface ChannelSummary {
  id: string
  revision?: number
  match?: ChannelMatch
  sourceStatus?: ChannelSourceStatus
  coverage?: Record<string, unknown>
  missing?: string[]
  review?: ChannelReview
  saved?: ChannelSaved
  updatedAt?: string
  changeLog?: ChannelLog[]
}

export interface DraftField {
  value?: number | string | null
  source?: string
  confidence?: string
  [key: string]: unknown
}

export interface DraftPlayer {
  side: string
  slot: number
  nickname?: string
  hero?: string
  fields?: Record<string, DraftField>
}

export interface ChannelDetail extends ChannelSummary {
  draft?: { players?: DraftPlayer[]; [key: string]: unknown }
  sources?: Record<string, unknown>
}

/* ── 单局深度：官方回放事件、团战账本、逐秒位置 ─────────────────── */

export interface PositionPlayer {
  camp: string
  slot: number
  nickname?: string | null
  hero?: string | null
  points: [number, number][]
}

export interface PositionsData {
  step: number
  duration: number
  players: PositionPlayer[]
}

export interface ReplayEvent {
  t: number
  kind: string
  id?: string | number | null
  killerCamp?: string | null
  killer?: string | null
  killerHero?: string | null
  ownerCamp?: string | null
  x?: number | null
  y?: number | null
  zone?: string | null
  participants?: { key?: string; name?: string; hero?: string; camp?: string }[]
}

export interface ReplayKill {
  t: number
  fight?: string
  killer: string
  killerCamp: string
  victim: string
  victimCamp: string
}

export interface ReplayDeath {
  t: number
  hero: string
  camp: string
  x: number
  y: number
}

export interface ReplayFightDetail {
  hero: string
  camp: string
  hurt?: number | null
  taken?: number | null
  hardCtrl?: number | null
  softCtrl?: number | null
  ultimates?: number | null
}

export interface ReplayFight {
  id?: string
  t: number
  end?: number | null
  camp1?: number | null
  camp2?: number | null
  first?: string | null
  blue?: number | null
  red?: number | null
  details?: ReplayFightDetail[]
}

export interface ReplayCoverage {
  goldPoints?: number
  events?: number
  resources?: number
  structures?: number
  positions?: { seconds?: number; players?: number; perSecond?: boolean }
  builds?: { players?: number; items?: number }
  heroKills?: boolean
  [key: string]: unknown
}

export interface ReplayGoldPoint {
  t: number
  blue: number
  red: number
  diff: number
}

export interface ReplayGold {
  points?: ReplayGoldPoint[]
  interval?: number | null
  landmarks?: Record<string, number | null>
}

export interface ReplayData {
  gold?: ReplayGold
  events?: ReplayEvent[]
  kills?: ReplayKill[]
  deaths?: ReplayDeath[]
  fights?: ReplayFight[]
  coverage?: ReplayCoverage
  notes?: string[]
}

/* ── M2：选手看板（/api/v3/players-board） ─────────────────────── */

export interface PlayerLaneMix {
  lane: string
  games: number
}

export interface BoardHeroStat {
  hero: string
  games: number
  wins: number
  decided: number
  rating: number | null
  kda: number | null
}

export interface BoardRecentGame {
  gameId: string
  day: string
  at?: string
  opponent?: string
  hero?: string
  lane?: string
  result?: string
  kda?: number | null
  gpm?: number | null
  dpm?: number | null
  rating?: number | null
  mvp?: boolean
}

export interface PlayerSplit {
  games: number
  wins: number
  decided: number
  winRate: number | null
  kda: number | null
  gpm: number | null
  dpm: number | null
  participation: number | null
  damageShare: number | null
  rating: number | null
  mvp: number
}

export interface BoardPlayer {
  name: string
  lane: string
  laneMix: PlayerLaneMix[]
  side: 'own' | 'enemy' | string
  bound: boolean
  memberId?: string | null
  games: number
  wins: number
  decided: number
  winRate: number | null
  kda: number | null
  gpm: number | null
  dpm: number | null
  dtpm: number | null
  participation: number | null
  goldShare: number | null
  damageShare: number | null
  takenShare: number | null
  cs: number | null
  rating: number | null
  mvp: number
  splits?: {
    opponent?: Record<string, PlayerSplit>
    day?: Record<string, PlayerSplit>
  }
  heroes?: BoardHeroStat[]
  percent?: Record<string, number | null>
  score?: number | null
  form?: {
    available: boolean
    prior?: number
    recent?: number
    delta?: number
    samples: number
    tone?: 'up' | 'down' | 'flat' | string
  } | null
  recent?: BoardRecentGame[]
}

export interface BoardLaneSide {
  games: number
  winRate: number | null
  gpm: number | null
  dpm: number | null
  dtpm: number | null
  participation: number | null
  players: number
}

export interface BoardLane {
  lane: string
  own: BoardLaneSide
  enemy: BoardLaneSide
}

export interface BoardGamePlayer {
  name: string
  hero: string
  lane: string
  kda: number | null
  gold: number | null
}

export interface BoardGame {
  id: string
  day: string
  at: string
  sort: string
  title: string
  match: string
  opponent: string
  map?: string
  ownCamp?: string
  result?: string
  duration?: number
  own: BoardGamePlayer[]
  enemy: BoardGamePlayer[]
}

export interface BoardRosterSlot {
  lane: string
  member: string
  memberId?: string | null
  player: string
  games: number
  winRate: number | null
  bound: boolean
}

export interface BoardDuo {
  a: string
  b: string
  games: number
  wins: number
  winRate: number | null
}

export interface BoardLineup {
  names: string[]
  games: number
  wins: number
}

export interface BoardUnclaimed {
  name: string
  games: number
  lane: string
  winRate: number | null
  heroes: string[]
  teammates: { name: string; games: number }[]
}

export interface BoardIdentityEntry {
  label: string
  matches: number
  lane?: string
  heroes?: string[]
  winRate?: number | null
  bound?: boolean
  memberId?: string | null
}

export interface BoardIdentity {
  entries: BoardIdentityEntry[]
  members: { id: string; label: string; name?: string; position?: string }[]
  aliases: Record<string, string>
  teamName: string
}

export interface PlayersBoard {
  games: BoardGame[]
  players: BoardPlayer[]
  lanes: BoardLane[]
  pairs: { a: string; b: string; games: number; wins: number; winRate: number | null }[]
  roster: BoardRosterSlot[]
  duos: BoardDuo[]
  lineups: BoardLineup[]
  opponents: { name: string; games: number }[]
  days: string[]
  unclaimed: BoardUnclaimed[]
  identity: BoardIdentity
  summary: {
    games: number
    decided: number
    wins: number
    winRate: number | null
    players: number
    ownPlayers: number
    bound: number
    unclaimed: number
    formReady: number
    rising: number
    falling: number
    pairs: number
    days: number
    positions: number
    teamName: string
  }
}

/* ── M2：战队（/api/studio/teams、camp-compare、team-bp、team-training） ── */

export interface TeamMetrics {
  winRate?: number | null
  gpm?: number | null
  dpm?: number | null
  dtpm?: number | null
  kda?: number | null
  towerPerGame?: number | null
  duration?: number | null
  killsPerGame?: number | null
  deathsPerGame?: number | null
  assistsPerGame?: number | null
  killsPerMin?: number | null
  assistsPerMin?: number | null
  controlPerMin?: number | null
  participation?: number | null
  conversion?: number | null
  [key: string]: number | null | undefined
}

export type TeamPercentiles = Record<string, number | null>

export interface TeamRosterPlayer {
  id: string
  name: string
  lane: string
  games: number
  wins: number
  decided: number
  winRate: number | null
  kills?: number | null
  deaths?: number | null
  assists?: number | null
  kda: number | null
  gpm?: number | null
  dpm?: number | null
  dtpm?: number | null
  participation?: number | null
  heroes?: { hero: string; games: number }[]
}

export interface TeamRosterLane {
  lane: string
  players: TeamRosterPlayer[]
}

export interface TeamLineup {
  names: string[]
  games: number
  wins: number
  losses?: number
  firstSeen?: string
  lastSeen?: string
}

export interface TeamRoster {
  games: number
  lanes: TeamRosterLane[]
  lineups?: TeamLineup[]
  stability?: number | null
  rotation?: number | null
  anomalies?: unknown[]
  players?: TeamRosterPlayer[]
}

export interface StudioTeam {
  id: string
  name: string
  coach?: string
  displayName: string
  named: boolean
  number?: number
  matches: number
  wins: number
  losses: number
  winRate: number | null
  firstSeen?: string
  lastSeen?: string
  players: TeamPlayer[]
  heroes: { hero: string; games: number }[]
  games?: TeamGame[]
  seqs?: string[]
  metrics: TeamMetrics
  percentiles: TeamPercentiles
  roster?: TeamRoster
}

export interface OwnTeamRow {
  name: string
  matches: number
  wins: number
  losses: number
  winRate: number | null
  metrics: TeamMetrics
  percentiles: TeamPercentiles
  roster?: TeamRoster
}

export interface TeamsBoard {
  own: OwnTeamRow
  teams: StudioTeam[]
  suggestions?: unknown[]
  summary: { teams: number; named: number; pending: number; games: number; unclustered: number }
  warnings: string[]
}

export interface CampAggregate {
  games: number
  seconds?: number
  kills?: number | null
  deaths?: number | null
  assists?: number | null
  gold?: number | null
  damage?: number | null
  heroDamage?: number | null
  taken?: number | null
  control?: number | null
  heal?: number | null
  towers?: number | null
  participation?: number | null
  wins: number
  decided: number
  kda?: number | null
  gpm?: number | null
  dpm?: number | null
  dpmTotal?: number | null
  dtpm?: number | null
  controlPerMin?: number | null
  healPerMin?: number | null
  winRate: number | null
  id?: string
  name?: string
  lane?: string
  teamId?: string
}

export interface CampHeroRow extends CampAggregate {
  hero: string
  lane: string
}

export interface CampCombo {
  heroes: string[]
  games: number
  decided: number
  wins: number
  winRate: number | null
  expected: number | null
  synergy: number | null
  small: boolean
}

export interface CampComboGroup {
  combos: CampCombo[]
  pairs?: number
}

export interface CampCombos {
  games: number
  pairs: { minGames: number; size: number; own: CampComboGroup; enemy: CampComboGroup }
  trios: { minGames: number; size: number; own: CampComboGroup; enemy: CampComboGroup }
  warnings?: string[]
}

export interface CampCompare {
  teamId?: string
  games: number
  players: { own: CampAggregate[]; enemy: CampAggregate[] }
  heroes: { own: CampHeroRow[]; enemy: CampHeroRow[] }
  lanes: { lane: string; own: CampAggregate; enemy: CampAggregate }[]
  combos: { games: number; minGames: number; size: number; own: CampComboGroup; enemy: CampComboGroup }
  combos3: { games: number; minGames: number; size: number; own: CampComboGroup; enemy: CampComboGroup }
  pool: {
    own: { heroes: number; picks: number; hhi: number; effective: number }
    enemy: { heroes: number; picks: number; hhi: number; effective: number }
    games: number
  }
  warnings: string[]
}

export interface CampPartners {
  hero: string
  side: string
  games: number
  minGames: number
  partners: (CampCombo & { partner: string })[]
  pairs: number
  warnings?: string[]
}

export interface TeamBpRow {
  id: string
  name: string
  games: number
  available: number
  picks: { hero: string; count: number }[]
  bans: { hero: string; count: number }[]
}

export interface TeamTrainingGame {
  seq: string
  start: string
  day: string
  win: boolean
  duration: number
  map?: string
  session?: string
  matchKey?: string
}

export interface TeamTrainingSession {
  id: string
  source: string
  date: string
  time?: string
  session?: string
  format?: string
  rules?: string
  version?: string
  status?: string
  notes?: string
  goals: { label: string; target?: string | number | null; status?: string }[]
  reviewStatus?: string
  review?: string
  games: TeamTrainingGame[]
  matches: number
  wins: number
  losses: number
  duration: number
}

export interface TeamTrainingTeam {
  id: string
  name: string
  displayName: string
  named: boolean
  coach?: string
  matches: number
  wins: number
  losses: number
  winRate: number | null
  lastSeen?: string
  sessions: TeamTrainingSession[]
  sessionCount: number
  planCount: number
  goalCount: number
  goalsDone: number
  reviewed: number
  lastSession?: string | null
}

export interface TeamTrainingData {
  teams: TeamTrainingTeam[]
  unassigned: unknown[]
  summary: {
    teams: number
    withPlans: number
    plans: number
    goals: number
    goalsDone: number
    reviewed: number
    sessions: number
    unassigned: number
  }
  warnings: string[]
}

/* ── M2：BP（/api/v3/bp-board、/api/studio/coach） ─────────────── */

export interface BpEntry {
  name: string
  icon?: string | null
  lane?: string | null
}

export interface BpGame {
  key: string
  start: string
  day: string
  session: string
  opponent: string
  teamId: string
  coach: string
  result: 'win' | 'loss' | null | string
  side: string
  ownSide: string
  duration: number
  mapName?: string
  picks: { own: BpEntry[]; enemy: BpEntry[] }
  bans: { own: BpEntry[]; enemy: BpEntry[] }
  players: { own: string[]; enemy: string[] }
  stats: { own: Record<string, number | boolean>; enemy: Record<string, number | boolean> }
}

export interface BpBoard {
  games: BpGame[]
  teams: { id: string; name: string; coach: string; matches: number; wins: number; losses: number; players: string[] }[]
  heroMeta: Record<string, { id?: string; icon?: string; lane?: string | null }>
  source: string
}

export interface CoachTeam {
  id: string
  name: string
  named: boolean
  coach: string
  players: { id: string; name: string; lanes: string[]; games: number }[]
}

export interface CoachBoard {
  own: { coach: string }
  teams: CoachTeam[]
}

/* ── M2：英雄（/api/v3/hero-detail、depth analysis） ───────────── */

export interface HeroDetailRow {
  name: string
  games: number
  wins: number
  decided: number
  winRate: number | null
  kda: number | null
  gpm: number | null
}

export interface HeroBuild {
  name: string
  games: number
  wins: number
  decided: number
  winRate: number | null
  gold: number | null
  kda: number | null
  equips: { name: string; count: number }[]
  first: { name: string; count: number }[]
  summoner: { name: string; count: number }[]
}

export interface HeroDetailData {
  hero: string
  games: number
  players: HeroDetailRow[]
  teams: HeroDetailRow[]
  league: Record<string, { hero: number | null; all: number | null }>
  growth: { t: number; value: number }[]
  curveGames: number
  playerBuilds: HeroBuild[]
}

export interface DepthAnalysis<T = Record<string, unknown>> {
  meta?: Record<string, unknown>
  payload: T & { note?: string }
}

export interface LaneMatchupPayload {
  viz: string
  lanes: { lane: string; n: number; avgGoldDiff: number | null; aheadRate: number | null; avgKdaDiff: number | null; winWhenAhead: number | null; winRate: number | null }[]
  roads: {
    match: string
    label: string
    opponent?: string
    lane: string
    ownPlayer: string
    ownHero: string
    enemyPlayer: string
    enemyHero: string
    ownGold: number
    enemyGold: number
    goldDiff: number
    ownKda?: number
    enemyKda?: number
    kdaDiff?: number
    ahead: boolean
    win: boolean
    winLabel?: string
  }[]
  heroes: { ownHero: string; enemyHero: string; n: number; avgGoldDiff: number | null; aheadRate: number | null; winRate: number | null; avgKdaDiff?: number | null }[]
  players: { ownPlayer: string; enemyPlayer: string; lane: string; n: number; avgGoldDiff: number | null; aheadRate: number | null; winRate: number | null }[]
  note?: string
}

export interface EquipMatrixPayload {
  viz: string
  rows: string[]
  cols: string[]
  cells: { value: number; n: number }[]
  unit: string
  items: { label: string; count: number; pct: number }[]
  note?: string
}

export interface EquipImpactPayload {
  viz: string
  rows: {
    label: string
    withN: number
    withoutN: number
    deltas: Record<string, { with: number | null; without: number | null; delta: number | null }>
  }[]
  metricLabels: string[]
  note?: string
}


/* ── M3：跨局向量与节奏 ─────────────────────────────────────────── */

export interface CrossLaneDiff {
  gold?: number | null
  damage?: number | null
  taken?: number | null
}

export interface CrossVector {
  key: string
  date: string
  clock?: string
  order: string
  session?: string
  version?: string
  opponent?: string
  result?: string
  duration: number
  camp?: string
  at10: number | null
  finalDiff: number | null
  g: (number | null)[]
  w: (number | null)[]
  s: (number | null)[]
  killsOwn?: number | null
  killsFoe?: number | null
  lanes: Record<string, CrossLaneDiff>
  heroes: string[]
  bans: string[]
}

export interface CrossVectors {
  total: number
  vectors: CrossVector[]
  unit: string
  segments: number
  windowMin: number
}

export interface TempoMatch {
  key: string
  date?: string
  opponent?: string
  session?: string
  points?: [number, number][]
  coverage?: number
  finalDiff?: number
  observedStart?: number
  observedEnd?: number
  diffAt?: Record<string, number | null>
  signFlips?: number
  duration?: number
  killsPerMinute?: number
  win?: boolean
  [key: string]: unknown
}

export interface TempoData {
  process: {
    gate?: unknown
    matches: TempoMatch[]
    aggregate: ProcessAggregate
    dataQuality?: unknown
    warnings?: string[]
  }
  objectives?: unknown
}


/* ── M4：训练计划、训练课、训练效果、周报、报告库 ─────────────── */

export interface ScheduleRow {
  id: string
  date: string
  start_time?: string | null
  opponent_team_id?: string | null
  session?: string | null
  format?: string | null
  rules?: string | null
  version?: string | null
  notes?: string | null
  status?: string | null
  goals?: string | null
  review?: string | null
  review_status?: string | null
  attendance?: string | null
  created_at?: string | null
  updated_at?: string | null
  [key: string]: unknown
}

export interface SchedulesResponse {
  schedules: ScheduleRow[]
}

export interface DashboardDay {
  date: string
  weekday: number
  sessions: number
  games: number
}

export interface DashboardRecent {
  id: string
  date?: string
  opponent?: string
  session?: string
  games?: number
  goals?: number
  achieved?: number
  reviewed?: boolean
}

export interface TrainingDashboardData {
  weeks: TrainingWeek[]
  days: DashboardDay[]
  goals: Record<string, number>
  recent: DashboardRecent[]
  current?: TrainingWeek & { [key: string]: unknown }
}

export interface EffectResult {
  id: string
  goal: string
  intervention?: string
  start_date?: string
  end_date?: string
  metric?: string
  target?: number | string | null
  player_ids?: string | null
  review?: string | null
  effect?: {
    available: boolean
    label?: string
    preMean?: number | null
    postMean?: number | null
    nPre?: number
    nPost?: number
    effectSize?: number | null
    reason?: string
  }
}

export interface TrainingEffectData {
  results: EffectResult[]
  dateNote?: string
}

export interface SessionMetric {
  id: string
  label: string
  unit?: string
  value: number | null
  sampleSize?: number
  expected?: number
  coverage?: number | null
  missingReason?: string | null
  [key: string]: unknown
}

export interface TrainingSessionData {
  schedule: ScheduleRow & { metrics?: Record<string, SessionMetric> }
  metrics?: Record<string, SessionMetric>
  goalMetrics?: unknown[]
  team?: { id: string; name: string } | null
  matches: {
    key: string
    date?: string
    session?: string
    enemy_team_id?: string
    enemyName?: string
    own_side?: string
    winner?: string
    score?: unknown
    duration?: number | null
    status?: string
  }[]
  matchReason?: string
  manualLinks?: boolean
  manualMatchKeys?: string[]
  availableMatches?: unknown[]
  opponentBrief?: {
    name?: string
    matches?: number
    winRate?: number | null
    heroes?: { hero: string; games: number }[]
    bans?: { hero: string; games: number }[]
    players?: { lane?: string; name?: string }[]
  } | null
  players: { id: string; name: string; position?: string; [key: string]: unknown }[]
}

export interface WeekMetrics {
  start: string
  end: string
  metrics: Record<string, SessionMetric>
}

export interface ResearchReportSummary {
  id: string
  title: string
  topic?: string
  createdAt?: string
  type?: string
  [key: string]: unknown
}

export interface ResearchReportsData {
  reports: ResearchReportSummary[]
}

export interface ReportResult {
  columns?: string[]
  rows?: Record<string, unknown>[]
  summary?: Record<string, unknown>
  note?: string
  sourceRows?: number
  warnings?: string[]
  filters?: unknown
  fingerprint?: string
}

export interface ResearchReportDetail extends ResearchReportSummary {
  result?: ReportResult
}
