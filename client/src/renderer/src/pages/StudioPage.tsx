import { BlockBoard } from '../blocks/BlockBoard'
import { PageHeader } from '../components/ui'

/**
 * 我的看板：空白页 + 分析库。
 * 所有注册块都能加到这里，自己排序、筛选、保存；三套模式各存一份。
 */
export function StudioPage() {
  return (
    <div className="page board-page">
      <PageHeader
        eyebrow="MY BOARD"
        title="我的看板"
        subtitle="所有分析都是一个块：从分析库加到这一页，自己排序、筛选、保存。块自带数据和口径，加到哪一页都能用。"
      />
      <BlockBoard page="studio" allowEmpty />
    </div>
  )
}
