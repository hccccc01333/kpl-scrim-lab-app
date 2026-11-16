import { Component, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

/** A failed chart or lazy route must leave navigation and recovery available. */
export class RouteErrorBoundary extends Component<{
  children: ReactNode
  resetKey: string
}, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() { return { failed: true } }

  componentDidUpdate(previous: Readonly<{ children: ReactNode; resetKey: string }>) {
    if (previous.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: false })
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="page">
        <section className="card error-state" role="alert">
          <h1 className="card-title">页面暂时无法显示</h1>
          <p>加载页面或绘制分析时出现问题。可以重新加载，或返回概览继续查看。</p>
          <div className="row">
            <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>重新加载页面</button>
            <Link className="btn" to="/">返回概览</Link>
          </div>
        </section>
      </div>
    )
  }
}
