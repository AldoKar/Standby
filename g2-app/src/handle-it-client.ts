// Handle It client for the Even Hub app (owner: P3).
// Framework-agnostic: subscribe to the engine, render the screens it sends, send gestures back.
// The engine writes all screen copy; the glasses only render `lines`. Contract: contract/events.md.

export type Gesture = 'press' | 'hold' | 'swipe_down'

export interface HudScreen {
  screen_id: string
  lines: string[] // at most 3; empty = blank screen
  gestures: Partial<Record<Gesture, string>> // gestures that do something on this screen
  clear_after_s: number | null
}

export interface EngineEvent {
  type: string
  ts: string
  task_id: string | null
  data: any
}

const BLANK: HudScreen = { screen_id: 'idle', lines: [], gestures: {}, clear_after_s: null }

/** Subscribe to GET /events. EventSource reconnects by itself, and the engine replays the current screen on connect. */
export function connect(
  baseUrl: string,
  onScreen: (screen: HudScreen) => void,
  onEvent?: (event: EngineEvent) => void,
): () => void {
  const es = new EventSource(`${baseUrl}/events`)
  let clearTimer: ReturnType<typeof setTimeout> | undefined
  es.onmessage = (msg) => {
    const event: EngineEvent = JSON.parse(msg.data)
    onEvent?.(event)
    if (event.type !== 'hud.screen') return
    const screen = event.data as HudScreen
    clearTimeout(clearTimer)
    onScreen(screen)
    if (screen.clear_after_s) clearTimer = setTimeout(() => onScreen(BLANK), screen.clear_after_s * 1000)
  }
  return () => es.close()
}

/** POST /input. Never map double press: on the root page it opens the system exit dialog. */
export async function sendGesture(baseUrl: string, gesture: Gesture, screenId?: string): Promise<void> {
  await fetch(`${baseUrl}/input`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ gesture, screen_id: screenId }),
  })
}
