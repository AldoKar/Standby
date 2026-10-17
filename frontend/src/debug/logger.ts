// Tiny in-app console. There is no remote inspector during QR sideload,
// so every state transition and failure gets logged here and to console.
export type LogEntry = { id: number; ts: string; msg: string }

const entries: LogEntry[] = []
const listeners = new Set<(entries: LogEntry[]) => void>()
let nextId = 1

export function log(msg: string) {
  const entry = { id: nextId++, ts: new Date().toLocaleTimeString(), msg }
  entries.push(entry)
  if (entries.length > 200) entries.shift()
  console.log(`[handle-it] ${msg}`)
  const snapshot = [...entries]
  listeners.forEach((fn) => fn(snapshot))
}

export function subscribeLogs(fn: (entries: LogEntry[]) => void): () => void {
  listeners.add(fn)
  fn([...entries])
  return () => listeners.delete(fn)
}

// Surface crashes instead of letting the app look frozen.
window.addEventListener('error', (e) => log(`[error] ${e.message}`))
window.addEventListener('unhandledrejection', (e) => log(`[unhandledrejection] ${String(e.reason)}`))
