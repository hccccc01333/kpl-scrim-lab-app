import { Link } from 'react-router-dom'
import { PageHeader } from '../components/ui'

export function NotFoundPage() {
  return (
    <div className="page">
      <PageHeader eyebrow="404" title={<>这一页不存在<em>可能是旧链接，或页面已经改过名字。</em></>} subtitle="回到概览，或者用 Ctrl K 搜索比赛、选手和命令。" actions={<Link className="btn btn-primary" to="/">回到概览</Link>} />
    </div>
  )
}
