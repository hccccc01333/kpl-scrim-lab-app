import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { shortDate } from '../lib/format'
import type { MatchSummary, RosterPlayer } from '../lib/types'
import { Icon } from './Icon'

interface Command {
  id: string
  group: string
  label: string
  hint: string
  icon: string
  run: () => void
}

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  matches: MatchSummary[]
  players: RosterPlayer[]
  onTheme: () => void
  onDensity: () => void
  onRefresh: () => void
  onOpenWorkbench: () => void
  onDisconnect: () => void
}

const pages = [
  ['概览', '/', 'overview'],
  ['采集', '/collect', 'ingest'],
  ['比赛', '/matches', 'matches'],
  ['跨局分析', '/matches/cross', 'matches'],
  ['智能找局', '/matches/query', 'matches'],
  ['精选对局', '/matches/featured', 'matches'],
  ['训练纪录', '/matches/records', 'matches'],
  ['版本对比', '/matches/versions', 'matches'],
  ['选手', '/players', 'players'],
  ['选手档案', '/players/archive', 'players'],
  ['选手对比', '/players/compare', 'players'],
  ['战队', '/teams', 'teams'],
  ['战队风格', '/teams/style', 'teams'],
  ['英雄', '/heroes', 'heroes'],
  ['英雄对比', '/heroes/compare', 'heroes'],
  ['BP', '/bp', 'bp'],
  ['教练档案', '/bp/coach', 'bp'],
  ['赛训', '/training', 'training'],
  ['设置', '/settings', 'settings']
] as const

export function CommandPalette({
  open,
  onClose,
  matches,
  players,
  onTheme,
  onDensity,
  onRefresh,
  onOpenWorkbench,
  onDisconnect
}: CommandPaletteProps) {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  useEffect(() => {
    if (!open) return
    setQuery('')
    setActive(0)
    const timer = window.setTimeout(() => inputRef.current?.focus(), 20)
    return () => window.clearTimeout(timer)
  }, [open])

  const commands = useMemo<Command[]>(() => {
    const list: Command[] = []
    for (const [label, path, icon] of pages) {
      list.push({
        id: `page-${path}`,
        group: '前往',
        label,
        hint: path,
        icon,
        run: () => navigate(path)
      })
    }
    const search = query.trim().toLowerCase()
    if (search) {
      for (const match of matches.slice(0, 8)) {
        const text = `${match.opponent || ''} ${match.date || ''} ${match.version || ''} ${match.session || ''}`.toLowerCase()
        if (!text.includes(search)) continue
        list.push({
          id: `match-${match.key}`,
          group: '比赛',
          label: `${match.opponent ? `对阵 ${match.opponent}` : '未标注对手'} · ${shortDate(match.date)}`,
          hint: match.result === 'win' ? '胜' : match.result === 'loss' ? '负' : '',
          icon: 'matches',
          run: () => navigate(`/matches/${encodeURIComponent(match.key)}`)
        })
      }
      for (const player of players.slice(0, 8)) {
        const text = `${player.label} ${player.position || ''}`.toLowerCase()
        if (!text.includes(search)) continue
        list.push({
          id: `player-${player.label}`,
          group: '选手',
          label: player.label,
          hint: player.position || '',
          icon: 'players',
          run: () => navigate(`/players/${encodeURIComponent(player.label)}`)
        })
      }
    }
    list.push(
      { id: 'action-theme', group: '操作', label: '切换主题', hint: '纸本 / 比赛房', icon: 'moon', run: onTheme },
      { id: 'action-density', group: '操作', label: '切换界面密度', hint: '舒适 / 紧凑', icon: 'density', run: onDensity },
      { id: 'action-refresh', group: '操作', label: '刷新当前数据', hint: '重新读取工作台', icon: 'refresh', run: onRefresh },
      { id: 'action-workbench', group: '操作', label: '打开工作台网页版', hint: '采集与导入', icon: 'external', run: onOpenWorkbench },
      { id: 'action-disconnect', group: '操作', label: '断开工作台', hint: '回到连接页', icon: 'closeCircle', run: onDisconnect }
    )
    if (!search) return list
    return list.filter((item) => `${item.group} ${item.label} ${item.hint}`.toLowerCase().includes(search))
  }, [query, matches, players, navigate, onTheme, onDensity, onRefresh, onOpenWorkbench, onDisconnect])

  useEffect(() => {
    setActive((current) => Math.min(current, Math.max(0, commands.length - 1)))
  }, [commands.length])

  if (!open) return null

  const run = (command?: Command) => {
    if (!command) return
    onClose()
    command.run()
  }

  let lastGroup = ''
  return (
    <div className="cmdk-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <div className="cmdk" role="dialog" aria-modal="true" aria-label="命令面板" onMouseDown={(event) => event.stopPropagation()}>
        <div className="cmdk-head">
          <Icon name="search" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => { setQuery(event.target.value); setActive(0) }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setActive((current) => Math.min(commands.length - 1, current + 1))
              } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                setActive((current) => Math.max(0, current - 1))
              } else if (event.key === 'Enter') {
                event.preventDefault()
                run(commands[active])
              } else if (event.key === 'Escape') {
                event.preventDefault()
                onClose()
              }
            }}
            placeholder="搜索比赛、选手或命令"
            spellCheck={false}
            autoComplete="off"
          />
          <kbd>ESC</kbd>
        </div>
        <div className="cmdk-list">
          {commands.length ? commands.map((command, index) => {
            const group = command.group !== lastGroup ? command.group : ''
            lastGroup = command.group
            return (
              <div key={command.id}>
                {group ? <div className="cmdk-group">{group}</div> : null}
                <button
                  type="button"
                  className={`cmdk-item${index === active ? ' is-active' : ''}`}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => run(command)}
                >
                  <span className="cmdk-icon"><Icon name={command.icon} /></span>
                  <b>{command.label}</b>
                  <small>{command.hint}</small>
                  <span className="cmdk-enter">↵</span>
                </button>
              </div>
            )
          }) : <div className="cmdk-empty">没有匹配的页面或命令。换个关键词试试。</div>}
        </div>
        <div className="cmdk-foot">
          <span><kbd>↑↓</kbd> 选择</span>
          <span><kbd>↵</kbd> 打开</span>
          <span><kbd>CTRL K</kbd> 关闭</span>
        </div>
      </div>
    </div>
  )
}
