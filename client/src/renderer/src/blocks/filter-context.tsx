import { createContext, useContext } from 'react'
import { EMPTY_BLOCK_FILTERS, type BlockFilterValues } from './filters'

/** 块级筛选上下文：页面里的块、块库里的块都从这里拿筛选值。 */
export const BlockFilterContext = createContext<BlockFilterValues>(EMPTY_BLOCK_FILTERS)

export function useBlockFilter(): BlockFilterValues {
  return useContext(BlockFilterContext)
}
