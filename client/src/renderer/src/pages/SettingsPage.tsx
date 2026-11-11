import { useEffect, useState } from 'react'
import { useConnection, useSettings } from '../lib/app-context'
import { useHealth } from '../lib/hooks'
import { isLoopback } from '../lib/api'
import { PageHeader } from '../components/ui'
import { Icon } from '../components/Icon'

export function SettingsPage() {
  const { baseUrl, health, disconnect, connect, busy, error } = useConnection()
  const { settings, update } = useSettings()
  const healthQuery = useHealth(baseUrl)
  const [url, setUrl] = useState(settings.baseUrl)
  const [notice, setNotice] = useState('')
  const [workbenchPath, setWorkbenchPath] = useState(settings.workbenchPath)
  const [pathNotice, setPathNotice] = useState('')
  const [info, setInfo] = useState<{ version: string; electron: string; platform: string; packaged: boolean; userData: string; settingsPath: string } | null>(null)

  useEffect(() => {
    setUrl(settings.baseUrl)
  }, [settings.baseUrl])

  useEffect(() => {
    setWorkbenchPath(settings.workbenchPath)
  }, [settings.workbenchPath])

  useEffect(() => {
    window.kpl.appInfo().then(setInfo).catch(() => setInfo(null))
  }, [])

  const live = healthQuery.data || health
  const local = isLoopback(baseUrl)

  const saveConnection = async () => {
    setNotice('')
    const ok = await connect(url)
    setNotice(ok ? '已连接。' : '连接失败，检查地址和工作台状态。')
  }

  const saveWorkbenchPath = async () => {
    await update({ workbenchPath: workbenchPath.trim() })
    setPathNotice('已保存。启动本机工作台时会使用这个路径。')
  }

  const openWorkbench = () => {
    void window.kpl.openExternal(baseUrl)
  }

  const openData = () => {
    if (!live?.dbPath || !local) return
    void window.kpl.openPath(live.dbPath).then((result) => {
      if (!result.ok) setNotice(result.error || '没能打开数据目录')
    })
  }

  return (
    <div className="page">
      <PageHeader
        eyebrow="SETTINGS · CLIENT"
        title={<>设置<em>连接、外观与本地工作台</em></>}
        subtitle="客户端只读展示工作台的数据；采集、导入、校对和身份维护仍在工作台完成。"
        meta={[
          `工作台 ${live?.version ? `v${live.version}` : '未连接'}`,
          settings.theme === 'light' ? '纸本' : '比赛房',
          settings.density === 'comfortable' ? '舒适密度' : '紧凑密度'
        ].map((text) => <span key={text}>{text}</span>)}
        actions={<button type="button" className="btn" onClick={openWorkbench}>打开工作台 <Icon name="external" /></button>}
      />

      <div className="settings-grid">
        <section className="card settings-card">
          <div className="card-head"><div><h2 className="card-title">连接</h2><div className="card-sub">默认连接本机 127.0.0.1:8766；也可以填队内工作台的局域网地址。</div></div><span className={`badge ${live?.ok ? 'badge-win' : 'badge-loss'}`}>{live?.ok ? '已连接' : '未连接'}</span></div>
          <div className="settings-row">
            <div className="settings-row-copy" style={{ flex: 1 }}>
              <b>工作台地址</b>
              <small>只支持 http/https；客户端通过本机代理访问，不会把数据上传到云端。</small>
              <div className="input-row" style={{ marginTop: 9 }}>
                <input className="input" value={url} onChange={(event) => setUrl(event.target.value)} spellCheck={false} placeholder="http://127.0.0.1:8766" />
                <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void saveConnection()}>{busy ? '连接中…' : '保存并重连'}</button>
              </div>
              {error || notice ? <div className={`connect-status${error && !notice ? ' is-error' : ''}`} style={{ marginTop: 7 }}>{notice || error}</div> : null}
            </div>
          </div>
          <div className="settings-row">
            <div className="settings-row-copy"><b>版本</b><small>{live?.releaseName || '工作台'} · {live?.version || '—'} · {live?.demo ? '演示数据' : '本机数据'}</small></div>
            <span className="badge">{live?.pid ? `PID ${live.pid}` : '—'}</span>
          </div>
          <div className="settings-row">
            <div className="settings-row-copy"><b>数据位置</b><small>{live?.dbPath || '连接后显示工作台数据库路径'}{!local && live?.dbPath ? '（在远程工作台机器上）' : ''}</small></div>
            <button type="button" className="btn btn-sm" onClick={openData} disabled={!live?.dbPath || !local}>打开数据目录</button>
          </div>
          <div className="settings-actions">
            <button type="button" className="btn" onClick={() => void healthQuery.refetch()}><Icon name="refresh" />重新检测</button>
            <button type="button" className="btn btn-ghost" onClick={disconnect}>断开连接</button>
          </div>
        </section>

        <section className="card settings-card">
          <div className="card-head"><div><h2 className="card-title">外观</h2><div className="card-sub">偏好会在下次打开时保留。</div></div></div>
          <div className="settings-row">
            <div className="settings-row-copy"><b>主题</b><small>纸本适合长时间读数据；比赛房适合视频和大屏复盘。</small></div>
            <div className="segmented">
              <button type="button" className={settings.theme === 'light' ? 'is-active' : ''} onClick={() => void update({ theme: 'light' })}>纸本</button>
              <button type="button" className={settings.theme === 'dark' ? 'is-active' : ''} onClick={() => void update({ theme: 'dark' })}>比赛房</button>
            </div>
          </div>
          <div className="settings-row">
            <div className="settings-row-copy"><b>界面密度</b><small>紧凑模式会减少留白，适合一屏看更多数据。</small></div>
            <div className="segmented">
              <button type="button" className={settings.density === 'comfortable' ? 'is-active' : ''} onClick={() => void update({ density: 'comfortable' })}>舒适</button>
              <button type="button" className={settings.density === 'compact' ? 'is-active' : ''} onClick={() => void update({ density: 'compact' })}>紧凑</button>
            </div>
          </div>
          <div className="settings-row">
            <div className="settings-row-copy"><b>关闭时最小化到托盘</b><small>关闭窗口后客户端继续在托盘运行；再次打开会复用同一个实例。</small></div>
            <button type="button" className={`toggle${settings.minimizeToTray ? ' is-on' : ''}`} aria-label="切换关闭到托盘" onClick={() => void update({ minimizeToTray: !settings.minimizeToTray })} />
          </div>
        </section>
      </div>

      <div className="settings-grid">
        <section className="card settings-card">
          <div className="card-head"><div><h2 className="card-title">工作台</h2><div className="card-sub">采集、导入、校对、选手认领与训练计划在工作台完成，客户端会自动读到最新结果。</div></div></div>
          <div className="settings-row">
            <div className="settings-row-copy"><b>网页版地址</b><small>{baseUrl}</small></div>
            <button type="button" className="btn btn-sm" onClick={openWorkbench}>在浏览器打开 <Icon name="external" /></button>
          </div>
          <div className="settings-row">
            <div className="settings-row-copy" style={{ flex: 1 }}><b>本机启动器路径</b><small>自定义安装位置时填写 KPLScrimLab.exe；留空用默认路径。</small>
              <div className="input-row" style={{ marginTop: 8 }}><input className="input" value={workbenchPath} onChange={(event) => setWorkbenchPath(event.target.value)} placeholder="D:\KPL赛训工具\KPLScrimLab.exe" spellCheck={false} /><button type="button" className="btn btn-sm" onClick={() => void saveWorkbenchPath()}>保存</button></div>
              {pathNotice ? <div className="connect-status is-ok" style={{ marginTop: 5 }}>{pathNotice}</div> : null}
            </div>
          </div>
          <div className="settings-actions">
            <button type="button" className="btn" onClick={openWorkbench}>采集 / 导入 / 校对</button>
            <span className="quiet" style={{ alignSelf: 'center', fontSize: 10 }}>客户端不会修改工作台数据。</span>
          </div>
        </section>

        <section className="card">
          <div className="about-card">
            <div className="about-mark">
              <span className="brand-mark"><i /><i /><i /></span>
              <div><b>赛训台</b><small>ANALYST CLIENT</small></div>
            </div>
            <dl className="kv">
              <dt>客户端版本</dt><dd>{info?.version || '1.0.0'}</dd>
              <dt>Electron</dt><dd>{info?.electron || '—'}</dd>
              <dt>平台</dt><dd>{info?.platform || '—'}</dd>
              <dt>工作台</dt><dd>{live?.version || '未连接'}</dd>
              <dt>客户端数据</dt><dd>{info?.userData || '—'}</dd>
            </dl>
            <div className="settings-actions" style={{ padding: 0, borderTop: 0 }}>
              <button type="button" className="btn btn-sm" onClick={() => void window.kpl.openLogs()}>打开日志</button>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => void window.kpl.openExternal('https://github.com/hccccc01333/kpl-scrim-lab/issues')}>反馈问题</button>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
