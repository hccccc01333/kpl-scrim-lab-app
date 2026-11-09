import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { HashRouter } from 'react-router-dom'
import App from './App'
import { SettingsProvider, ConnectionProvider } from './lib/app-context'
import './styles/index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false
    }
  }
})

window.addEventListener('error', (event) => {
  window.kpl?.log(`window.error ${event.message} @ ${event.filename}:${event.lineno}`)
})
window.addEventListener('unhandledrejection', (event) => {
  window.kpl?.log(`unhandledrejection ${String(event.reason)}`)
})

try {
  if (!location.hash) {
    const saved = localStorage.getItem('kpl-last-route')
    if (saved && saved.startsWith('#')) history.replaceState(null, '', saved)
  }
} catch {
  /* first run or storage unavailable */
}

createRoot(document.getElementById('root')!).render(
  <QueryClientProvider client={queryClient}>
    <HashRouter>
      <SettingsProvider>
        <ConnectionProvider>
          <App />
        </ConnectionProvider>
      </SettingsProvider>
    </HashRouter>
  </QueryClientProvider>
)
