/**
 * 上帝模式 · 分析块注册表
 *
 * 每个分析 = 一个注册块：全局 id、数据域、标题、回答的问题、支持的筛选、组件。
 * 注册块自带数据请求（组件内部调 hooks），因此可以放在任何页面、被自由拼装。
 * 页面里的内联块（Block）和库里的注册块最终都走同一套 BlockBoard。
 */
import type { ComponentType } from 'react'
import type { BlockFilterKey } from './filters'
import { BUILTIN_BLOCKS } from './builtin'

/** 超块的可配置项：内容 / 范围 / 展示 / 交互。 */
export interface BlockOptionField {
  key: string
  label: string
  type: 'select' | 'toggle' | 'number'
  options?: { value: string; label: string }[]
  min?: number
  max?: number
  step?: number
  default?: string | number | boolean
  note?: string
}

export type BlockOptions = Record<string, string | number | boolean | undefined>

export interface RegisteredBlock {
  /** 全局唯一，例如 bp.combos；不要改，改了会丢已保存布局 */
  id: string
  /** 同一分析的不同变体共用一个 base；分析库按 base 分组、按 variant 选版式 */
  base?: string
  variant?: string
  /** 数据域：bp / match / hero / player / team / training / lane */
  domain: string
  title: string
  /** 这个块回答什么问题（分析库展示给教练看） */
  question: string
  filters: BlockFilterKey[]
  /** 超块配置项；有配置项的块在编辑态显示「配置」按钮，配置随布局保存 */
  options?: BlockOptionField[]
  Component: ComponentType<{ options?: BlockOptions }>
}

const registry = new Map<string, RegisteredBlock>()

export function registerBlocks(list: RegisteredBlock[]): void {
  for (const block of list) registry.set(block.id, block)
}

export function listRegisteredBlocks(): RegisteredBlock[] {
  return [...registry.values()]
}

export function getRegisteredBlock(id: string): RegisteredBlock | undefined {
  return registry.get(id)
}

export function domainLabel(domain: string): string {
  const labels: Record<string, string> = {
    bp: 'BP',
    match: '比赛',
    hero: '英雄',
    player: '选手',
    team: '战队',
    training: '赛训',
    lane: '对位'
  }
  return labels[domain] || domain
}

registerBlocks(BUILTIN_BLOCKS)
