import { createContext, useContext, type ReactNode } from 'react'

export interface AppMeta {
  baseUrl: string
  teamName: string
  icons: Record<string, string>
  demo: boolean
}

const AppMetaContext = createContext<AppMeta>({
  baseUrl: '',
  teamName: '本队',
  icons: {},
  demo: false
})

export function AppMetaProvider({ value, children }: { value: AppMeta; children: ReactNode }) {
  return <AppMetaContext.Provider value={value}>{children}</AppMetaContext.Provider>
}

export function useAppMeta(): AppMeta {
  return useContext(AppMetaContext)
}
