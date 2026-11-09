import { useEffect, useState } from 'react'
import { useConnection, useSettings } from '../lib/app-context'
import { isLoopback } from '../lib/api'
import { Icon } from '../components/Icon'

export function ConnectPage() {
  const { connect, busy, error, recent, startLocal } = useConnection()
  const { settings } = useSettings()
  const [url, setUrl] = useState(settings.baseUrl || 'http://127.0.0.1:8766')
  const [detected, setDetected] = useState<{ running: boolean; version?: string; paths: string[] } | null>(null)
  const [checking, setChecking] = useState(false)
  const [attempted, setAttempted] = useState(false)
  const local = isLoopback(url)

  useEffect(() => {
    let alive = true
    setChecking(true)
    window.kpl.detectWorkbench(url)
      .then((result) => { if (alive) setDetected(result) })
      .catch(() => { if (alive) setDetected(null) })
      .finally(() => { if (alive) setChecking(false) })
    return () => { alive = false }
  }, [url])

  const submit = async () => {
    setAttempted(true)
    await connect(url)
  }

  return (
    <div className="connect-screen">
      <div className="window-drag" aria-hidden="true" />
      <section className="connect-copy">
        <div className="connect-brand">
          <span className="brand-mark"><i /><i /><i /></span>
          <div><strong>赛训台</strong><small>KPL SCRIM DESK · ANALYST CLIENT</small></div>
        </div>
        <div>
          <span className="eyebrow">A DESK FOR THE ANALYST</span>
          <h1 className="connect-headline">把训练赛，<br />变成<em>能读的结论</em>。</h1>
          <p className="connect-lead">给赛训组的数据分析师和教练组用的桌面客户端。连接本机工作台，按比赛、选手、战队和英雄读数据；不用打开浏览器，也不用记端口。</p>
        </div>
        <div className="connect-points">
          <div className="connect-point"><b>01</b><span>先看结论</span><small>比分、经济差、阶段与关键节点</small></div>
          <div className="connect-point"><b>02</b><span>再下钻</span><small>十人面板、BP、逐局与英雄池</small></div>
          <div className="connect-point"><b>03</b><span>只读工作台</span><small>采集与导入仍在工作台完成</small></div>
        </div>
        <div className="connect-foot"><span>LOCAL-FIRST</span><span>数据留在本机</span><span>v1.0</span></div>
      </section>

      <aside className="connect-side">
        <div className="connect-card">
          <div className="connect-card-head">
            <span className="eyebrow">CONNECT</span>
            <h2>连接工作台</h2>
            <p>默认连接本机 127.0.0.1:8766。工作台在队内另一台机器上时，直接填它的局域网地址。</p>
          </div>
          <div className="field">
            <label htmlFor="workbench-url">工作台地址</label>
            <div className="input-row">
              <input
                id="workbench-url"
                className="input"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                onKeyDown={(event) => { if (event.key === 'Enter') void submit() }}
                placeholder="http://127.0.0.1:8766"
                spellCheck={false}
                autoFocus
              />
              <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void submit()}>{busy ? '连接中…' : '连接'}</button>
            </div>
          </div>
          <div className={`connect-status${attempted && error ? ' is-error' : detected?.running ? ' is-ok' : ''}`}>
            {busy
              ? '正在读取工作台健康状态…'
              : attempted && error
                ? error
                : checking
                  ? '正在检测本机工作台…'
                  : detected?.running
                    ? `已检测到工作台${detected.version ? ` · v${detected.version}` : ''}`
                    : local
                      ? '本机默认地址没有检测到工作台。先启动工作台，或填一个已经在运行的地址。'
                      : '连不上这个地址。确认局域网工作台已启动，并允许远程 Host。'}
          </div>

          {recent.length ? (
            <div className="field">
              <label>最近连接</label>
              <div className="recent-list">
                {recent.map((item) => <button type="button" className="recent-chip" key={item} onClick={() => setUrl(item)}>{item.replace(/^https?:\/\//, '')}</button>)}
              </div>
            </div>
          ) : null}

          <div className="connect-help">
            <span>工作台没启动？</span>
            <div className="connect-help-actions">
              {local ? (
                <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void startLocal(url)}>
                  <Icon name="play" /> 启动本机工作台
                </button>
              ) : null}
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => void window.kpl.openExternal('https://hccccc01333.github.io/kpl-scrim-lab-site/')}>
                下载工作台 <Icon name="external" />
              </button>
            </div>
            <span>客户端和工作台共用同一套数据与接口；客户端不修改工作台数据。{local ? '' : ' 局域网工作台需要在工作台机器上允许远程 Host。'}</span>
          </div>
        </div>
      </aside>
    </div>
  )
}
