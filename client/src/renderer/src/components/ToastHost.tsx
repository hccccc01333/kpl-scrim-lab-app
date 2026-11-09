import { useEffect, useState } from 'react'
import { subscribeToasts, type ToastMessage } from '../lib/toast'

export function ToastHost() {
  const [toasts, setToasts] = useState<ToastMessage[]>([])

  useEffect(() => {
    const unsubscribe = subscribeToasts((toast) => {
      setToasts((current) => [...current.slice(-3), toast])
      window.setTimeout(() => {
        setToasts((current) => current.filter((item) => item.id !== toast.id))
      }, 5200)
    })
    return unsubscribe
  }, [])

  if (!toasts.length) return null
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      {toasts.map((toast) => (
        <div className={`toast is-${toast.tone}`} key={toast.id}>{toast.text}</div>
      ))}
    </div>
  )
}
