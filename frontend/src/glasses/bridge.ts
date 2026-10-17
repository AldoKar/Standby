// Thin wrapper around the Even Hub SDK.
// - Works inside the Even App WebView / simulator (real bridge).
// - Falls back to "browser mode" in a normal browser (HUD mirror only).
import {
  CreateStartUpPageContainer,
  OsEventTypeList,
  StartUpPageCreateResult,
  TextContainerProperty,
  TextContainerUpgrade,
  waitForEvenAppBridge,
  type EvenAppBridge,
  type EvenHubEvent,
} from '@evenrealities/even_hub_sdk'
import { log } from '../debug/logger'

export type BridgeStatus = 'connecting' | 'connected' | 'browser' | 'error'
export type GlassesInput = 'tap' | 'double_tap' | 'scroll_up' | 'scroll_down'

const CONTAINER_ID = 1
const CONTAINER_NAME = 'hud'
const BRIDGE_TIMEOUT_MS = 2500
const RENDER_DEBOUNCE_MS = 120

let bridge: EvenAppBridge | null = null
let initPromise: Promise<BridgeStatus> | null = null
let renderTimer: ReturnType<typeof setTimeout> | null = null
let pendingText: string | null = null
const inputListeners = new Set<(input: GlassesInput) => void>()

function withTimeout<T>(p: Promise<T>, ms: number, label: string): Promise<T> {
  return Promise.race([
    p,
    new Promise<T>((_, reject) =>
      setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms),
    ),
  ])
}

/** Map an SDK event to a gesture. CLICK arrives with eventType undefined (protobuf omits 0). */
function toInput(event: EvenHubEvent): GlassesInput | null {
  const item = event.textEvent ?? event.sysEvent ?? event.listEvent
  if (!item) return null // audio / menu / other events are not gestures
  const type = item.eventType ?? OsEventTypeList.CLICK_EVENT
  switch (type) {
    case OsEventTypeList.CLICK_EVENT:
      return 'tap'
    case OsEventTypeList.DOUBLE_CLICK_EVENT:
      return 'double_tap'
    case OsEventTypeList.SCROLL_TOP_EVENT:
      return 'scroll_up'
    case OsEventTypeList.SCROLL_BOTTOM_EVENT:
      return 'scroll_down'
    default:
      return null
  }
}

export function emitInput(input: GlassesInput) {
  log(`input: ${input}`)
  inputListeners.forEach((fn) => fn(input))
}

export function onGlassesInput(fn: (input: GlassesInput) => void): () => void {
  inputListeners.add(fn)
  return () => inputListeners.delete(fn)
}

/** Idempotent: safe under React StrictMode double effects. */
export function initGlasses(initialText: string): Promise<BridgeStatus> {
  if (initPromise) return initPromise
  initPromise = (async (): Promise<BridgeStatus> => {
    try {
      bridge = await withTimeout(waitForEvenAppBridge(), BRIDGE_TIMEOUT_MS, 'waitForEvenAppBridge')
    } catch (err) {
      log(`no Even bridge → browser mode (${(err as Error).message})`)
      return 'browser'
    }
    log('bridge ready')

    try {
      const result = await withTimeout(
        bridge.createStartUpPageContainer(
          new CreateStartUpPageContainer({
            containerTotalNum: 1,
            textObject: [
              new TextContainerProperty({
                xPosition: 0,
                yPosition: 0,
                width: 576,
                height: 288,
                paddingLength: 8,
                containerID: CONTAINER_ID,
                containerName: CONTAINER_NAME,
                content: initialText,
                isEventCapture: 1, // exactly one container must capture gestures
              }),
            ],
          }),
        ),
        5000,
        'createStartUpPageContainer',
      )
      if (result !== StartUpPageCreateResult.success) {
        log(`createStartUpPageContainer failed: ${StartUpPageCreateResult[result]} (${result})`)
        return 'error'
      }
    } catch (err) {
      log(`createStartUpPageContainer error: ${(err as Error).message}`)
      return 'error'
    }

    bridge.onEvenHubEvent((event) => {
      const input = toInput(event)
      if (!input) return
      if (input === 'double_tap') {
        // Double tap = exit. Never intercept (store review rule).
        log('double tap → shutDownPageContainer(1)')
        void bridge?.shutDownPageContainer(1)
      }
      emitInput(input)
    })

    log('startup page created')
    return 'connected'
  })()
  return initPromise
}

/** Debounced write to the lens. Drops intermediate frames, only the latest text is sent. */
export function renderToGlasses(text: string) {
  pendingText = text
  if (renderTimer) return
  renderTimer = setTimeout(async () => {
    renderTimer = null
    const content = pendingText
    pendingText = null
    if (!bridge || content === null) return
    try {
      const ok = await withTimeout(
        bridge.textContainerUpgrade(
          new TextContainerUpgrade({ containerID: CONTAINER_ID, containerName: CONTAINER_NAME, content }),
        ),
        3000,
        'textContainerUpgrade',
      )
      if (!ok) log('textContainerUpgrade returned false')
    } catch (err) {
      log(`textContainerUpgrade error: ${(err as Error).message}`)
    }
  }, RENDER_DEBOUNCE_MS)
}
