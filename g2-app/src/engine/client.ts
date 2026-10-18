// Engine client: SSE in (GET /events), gestures and demo controls out (POST).
// The engine replays state.snapshot + the current hud.screen on every (re)connect, so a dropped
// connection redraws by itself. EventSource reconnects automatically.
import { log } from '../debug/logger'
import type { EngineEvent, Gesture, InputResult, Ledger, TestsResult, VoiceResult } from './types'

export type EngineStatus = 'connecting' | 'live' | 'offline'

const POST_TIMEOUT_MS = 5000
const VOICE_TIMEOUT_MS = 12000 // speech-to-text + intent; the engine itself gives up after ~13 s worst case

/**
 * Engine base URL, in order: `?api=https://host`, VITE_ENGINE_URL, or the same host on :8000
 * (works for the simulator on localhost and for QR sideload on the laptop's LAN IP).
 */
export function engineUrl(): string {
  const fromQuery = new URLSearchParams(location.search).get('api')
  const fromEnv = import.meta.env.VITE_ENGINE_URL as string | undefined
  const fallback = `${location.protocol}//${location.hostname}:8000`
  return (fromQuery || fromEnv || fallback).replace(/\/+$/, '')
}

export function connectEngine(
  baseUrl: string,
  onEvent: (e: EngineEvent) => void,
  onStatus: (s: EngineStatus) => void,
): () => void {
  log(`engine: connecting to ${baseUrl}/events`)
  onStatus('connecting')
  const es = new EventSource(`${baseUrl}/events`)
  let live = false
  es.onopen = () => {
    live = true
    log('engine: live')
    onStatus('live')
  }
  es.onerror = () => {
    if (live) log('engine: connection lost, retrying')
    live = false
    onStatus('offline')
  }
  es.onmessage = (msg) => {
    let event: EngineEvent
    try {
      event = JSON.parse(msg.data) as EngineEvent
    } catch {
      log(`engine: bad event ${String(msg.data).slice(0, 80)}`)
      return
    }
    if (!live) {
      live = true
      onStatus('live')
    }
    onEvent(event)
  }
  return () => es.close()
}

async function post<T>(baseUrl: string, path: string, body: unknown, timeoutMs = POST_TIMEOUT_MS): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(`${baseUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
      signal: ctrl.signal,
    })
    if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`)
    return (await res.json()) as T
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw new Error(`${path} timed out after ${timeoutMs}ms`)
    throw err
  } finally {
    clearTimeout(timer)
  }
}

async function get<T>(baseUrl: string, path: string, timeoutMs = POST_TIMEOUT_MS): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(`${baseUrl}${path}`, { cache: 'no-store', signal: ctrl.signal })
    if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`)
    return (await res.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

export function createEngine(baseUrl: string) {
  return {
    baseUrl,
    /** GET /ledger: mandate, spends, refunds, consents, denied attempts. */
    ledger: () => get<Ledger>(baseUrl, '/ledger'),
    /** GET /tests: last engine test run (404 until tests have run). */
    tests: () => get<TestsResult>(baseUrl, '/tests'),
    /** Recorded-call fallback the engine serves from dashboard/. */
    recordedCallUrl: `${baseUrl}/dashboard/recorded-call.mp3`,
    /** POST /input. Always sends the screen_id so the engine can tell a stale gesture apart. */
    input: (gesture: Gesture, screen_id: string) => post<InputResult>(baseUrl, '/input', { gesture, screen_id }),
    /** POST /voice: a WAV utterance (base64) or a typed transcript, for the given screen. */
    voice: (body: { screen_id: string; audio?: string; format?: 'wav'; transcript?: string }) =>
      post<VoiceResult>(baseUrl, '/voice', body, VOICE_TIMEOUT_MS),
    /** POST /simulate/cancel (dashboard backup for "Tap to start"). */
    simulateCancel: () => post<{ handled: boolean }>(baseUrl, '/simulate/cancel', {}),
    /** POST /demo/reset */
    reset: () => post<{ ok: boolean }>(baseUrl, '/demo/reset', {}),
  }
}

export type Engine = ReturnType<typeof createEngine>
