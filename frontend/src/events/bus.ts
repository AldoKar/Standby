// Local event bus. Everything the UI shows comes from Envelopes published here.
// Today the publisher is the mock transport; in Phase 5 the SSE stream (GET /events) publishes here.
import type { Envelope, EventData, EventType } from '@contracts/events'
import { log } from '../debug/logger'

type Listener = (e: Envelope) => void
const listeners = new Set<Listener>()
let seq = 1

export function makeEvent<K extends EventType>(type: K, task_id: string | null, data: EventData[K]): Envelope {
  return { id: `local_${seq++}`, type, task_id, ts: new Date().toISOString(), data } as Envelope
}

export function publish(e: Envelope) {
  log(`event: ${e.type}${e.task_id ? ` (${e.task_id})` : ''}`)
  listeners.forEach((fn) => fn(e))
}

export function subscribe(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
