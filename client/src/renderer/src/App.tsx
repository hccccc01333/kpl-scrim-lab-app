import { useConnection, useSettings } from './lib/app-context'
import { AppShell } from './components/AppShell'
import { ConnectPage } from './pages/ConnectPage'

function BootScreen({ label }: { label: string }) {
  return (
    <div className="boot-screen">
      <div className="window-drag" aria-hidden="true" />
      <div className="boot-mark"><span className="brand-mark"><i /><i /><i /></span><b>赛训台</b></div>
      <p>{label}</p>
      <div className="boot-line"><i /></div>
    </div>
  )
}

export default function App() {
  const { ready } = useSettings()
  const { phase } = useConnection()

  if (!ready) return <BootScreen label="正在读取客户端偏好…" />
  if (phase === 'boot' || phase === 'checking') return <BootScreen label="正在连接工作台…" />
  if (phase === 'error') return <ConnectPage />
  return <AppShell />
}
