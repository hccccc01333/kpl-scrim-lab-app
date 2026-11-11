export interface ToastMessage {
  id: number
  text: string
  tone: 'info' | 'success' | 'error'
}

type Listener = (toast: ToastMessage) => void

const listeners = new Set<Listener>()
let sequence = 0

export function pushToast(text: string, tone: ToastMessage['tone'] = 'info'): void {
  const message: ToastMessage = { id: ++sequence, text, tone }
  for (const listener of listeners) listener(message)
}

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
