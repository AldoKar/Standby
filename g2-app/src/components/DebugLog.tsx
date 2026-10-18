import { useEffect, useState } from 'react'
import { subscribeLogs, type LogEntry } from '../debug/logger'

export function DebugLog() {
  const [entries, setEntries] = useState<LogEntry[]>([])
  useEffect(() => subscribeLogs(setEntries), [])

  return (
    <details className="debug-log">
      <summary>Debug log ({entries.length})</summary>
      <ol>
        {entries.map((e) => (
          <li key={e.id}>
            <time>{e.ts}</time> {e.msg}
          </li>
        ))}
      </ol>
    </details>
  )
}
