// Local event bus. Everything the UI shows comes from engine events published here:
// the SSE client publishes live events; the DEV preview panel publishes sample ones.
import { log } from '../debug/logger'
import type { EngineEvent, EngineEventType, EventData } from '../engine/types'

type Listener = (e: EngineEvent) => void
const listeners = new Set<Listener>()

export function makeEvent<K extends EngineEventType>(type: K, data: EventData[K], task_id: string | null = null): EngineEvent {
  return { type, ts: new Date().toISOString(), task_id, data } as EngineEvent
}

export function publish(e: EngineEvent) {
  if (e.type === 'hud.screen') log(`screen: ${e.data.screen_id}`)
  else if (e.type !== 'state.snapshot') log(`event: ${e.type}`)
  listeners.forEach((fn) => fn(e))
}

export function subscribe(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
