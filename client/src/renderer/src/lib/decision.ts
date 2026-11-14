import { useQuery } from '@tanstack/react-query'
import { api, queryString } from './api'

/**
 * 赛训分析数据层（/api/decision/*）。
 *
 * 类型按 docs/decision_workbench_contract.md 第 3 节与各报告模块的输出契约编写：
 * - 顶层 always-present 的字段标必需；报告内部可缺省/小样本时给 null 的字段标 optional。
 * - 所有报告在无数据时返回 available=false + reason，不抛 500；页面据此显示原因而不是空图。
 */

const common = {
  staleTime: 30_000,
  refetchOnWindowFocus: false,
  retry: 1
}

/* ── 通用 ─────────────────────────────────────────────────────────── */

export interface DecisionCoverageOpponents {
  total?: number
  replayOpponents?: number
  with3Games?: number
}

export interface DecisionIdentityCoverage {
  playersWithNickname?: number
  namedOpponents?: number
}

export interface DecisionCoverage {
  panelGames?: number
  panelRows?: number
  replayGames?: number
  pairedGames?: number
  games?: number
  withResult?: number
  wins?: number
  losses?: number
  positionGames?: number
  fightGames?: number
  fights?: number
  deaths?: number
  events?: number
  dateRange?: string[]
  calibrated?: boolean
  calibrationNote?: string
  opponents?: DecisionCoverageOpponents
  identity?: DecisionIdentityCoverage
  errors?: number
}

export interface DecisionFiltersApplied {
  game?: string | null
  opponent?: string | null
  from?: string | null
  to?: string | null
  result?: string | null
  side?: string | null
  lane?: string | null
  player?: string | null
  limit?: number | null
}

/* ── 参数 ───────────────────────────────────────────────────────── */

export interface DecisionRangeParams {
  opponent?: string
  from?: string
  to?: string
  result?: string
}

/* ── hooks ──────────────────────────────────────────────────────── */


