// Thin wrapper around the Even Hub SDK.
// - Works inside the Even App WebView / simulator (real bridge).
// - Falls back to "browser mode" in a normal browser (HUD mirror only).
//
// Rendering: callers hand over a PagePlan (hud/layout.ts). A single serial loop applies only the latest
// plan: full rebuild when the layout signature changes, otherwise per-container text/image updates.
import {
  CreateStartUpPageContainer,
  ImageContainerProperty,
  ImageRawDataUpdate,
  ImageRawDataUpdateResult,
  OsEventTypeList,
  RebuildPageContainer,
  StartUpPageCreateResult,
  TextContainerProperty,
  TextContainerUpgrade,
  waitForEvenAppBridge,
  type EvenAppBridge,
  type EvenHubEvent,
} from '@evenrealities/even_hub_sdk'
import { log } from '../debug/logger'
import { imageGray } from '../hud/images'
import { PADDING, type PagePlan } from '../hud/layout'

export type BridgeStatus = 'connecting' | 'connected' | 'browser' | 'error'
export type GlassesInput = 'tap' | 'double_tap' | 'long_press' | 'scroll_up' | 'scroll_down'

const BRIDGE_TIMEOUT_MS = 2500
const CALL_TIMEOUT_MS = 4000
const RENDER_DEBOUNCE_MS = 120
const BORDER_COLOR = 12 // border brightness (0 = invisible)

let bridge: EvenAppBridge | null = null
let initPromise: Promise<BridgeStatus> | null = null
let pageReady = false

// What the lens should show (latest only) and what it currently shows.
let desired: PagePlan | null = null
let applied: { signature: string; texts: Map<number, string>; images: Map<number, string> } | null = null
let renderTimer: ReturnType<typeof setTimeout> | null = null
let rendering = false
let browserMode = false

// Measured time of one updateImageRawData round trip (exponential moving average).
let imageAvgMs: number | null = null
let imageSamples = 0

function recordImageLatency(ms: number) {
  imageAvgMs = imageAvgMs === null ? ms : imageAvgMs * 0.7 + ms * 0.3
  imageSamples++
  if (imageSamples <= 3 || imageSamples % 20 === 0) {
    log(`image update ${Math.round(ms)}ms (avg ${Math.round(imageAvgMs)}ms, n=${imageSamples})`)
  }
}

/** Average image update time; 0 in browser mode (no BLE), null until measured on a device. */
export function imageLatencyMs(): number | null {
  return browserMode ? 0 : imageAvgMs
}

/** True when nothing is queued or in flight, so an optional animation frame won't delay a real screen. */
export function isRenderIdle(): boolean {
  if (!pageReady) return true
  return !rendering && !renderTimer && desired === null
}

const inputListeners = new Set<(input: GlassesInput) => void>()

function withTimeout<T>(p: Promise<T>, ms: number, label: string): Promise<T> {
  return Promise.race([
    p,
    new Promise<T>((_, reject) => setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms)),
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
    case OsEventTypeList.LONG_PRESS_EVENT:
      return 'long_press'
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
  return () => {
    inputListeners.delete(fn)
  }
}

// ---------- page building ----------

function pageModel(plan: PagePlan) {
  return {
    containerTotalNum: plan.texts.length + plan.images.length,
    textObject: plan.texts.map(
      (t) =>
        new TextContainerProperty({
          xPosition: t.x,
          yPosition: t.y,
          width: t.w,
          height: t.h,
          paddingLength: t.padding ?? PADDING,
          borderWidth: t.border ? 2 : 0,
          borderColor: t.border ? BORDER_COLOR : 0,
          borderRadius: t.border ? (t.radius ?? 10) : 0,
          containerID: t.id,
          containerName: t.name,
          content: t.content,
          textColor: t.color,
          isEventCapture: t.capture ? 1 : 0,
          zOrderIndex: t.z,
        }),
    ),
    imageObject: plan.images.map(
      (i) =>
        new ImageContainerProperty({
          xPosition: i.x,
          yPosition: i.y,
          width: i.w,
          height: i.h,
          containerID: i.id,
          containerName: i.name,
          zOrderIndex: i.z,
        }),
    ),
  }
}

function textKey(content: string, color: number) {
  return `${color}|${content}`
}

function markBuilt(plan: PagePlan) {
  applied = {
    signature: plan.signature,
    texts: new Map(plan.texts.map((t) => [t.id, textKey(t.content, t.color)])),
    images: new Map(), // image containers start empty after create/rebuild
  }
}

async function apply(plan: PagePlan): Promise<void> {
  const b = bridge
  if (!b) return

  if (!applied || applied.signature !== plan.signature) {
    const ok = await withTimeout(b.rebuildPageContainer(new RebuildPageContainer(pageModel(plan))), CALL_TIMEOUT_MS, 'rebuildPageContainer')
    if (!ok) {
      log(`rebuildPageContainer returned false (${plan.signature})`)
      return
    }
    log(`page rebuilt: ${plan.signature}`)
    markBuilt(plan)
  }
  const state = applied
  if (!state) return

  for (const t of plan.texts) {
    const key = textKey(t.content, t.color)
    if (state.texts.get(t.id) === key) continue
    const ok = await withTimeout(
      b.textContainerUpgrade(
        new TextContainerUpgrade({ containerID: t.id, containerName: t.name, content: t.content, textColor: t.color }),
      ),
      CALL_TIMEOUT_MS,
      'textContainerUpgrade',
    )
    if (ok) state.texts.set(t.id, key)
    else log(`textContainerUpgrade(${t.name}) returned false`)
  }

  for (const i of plan.images) {
    if (state.images.get(i.id) === i.key) continue
    const started = performance.now()
    const result = await withTimeout(
      b.updateImageRawData(
        new ImageRawDataUpdate({ containerID: i.id, containerName: i.name, imageData: imageGray(i.key, i.w, i.h) }),
      ),
      CALL_TIMEOUT_MS,
      'updateImageRawData',
    )
    recordImageLatency(performance.now() - started)
    if (result === ImageRawDataUpdateResult.success) state.images.set(i.id, i.key)
    else log(`updateImageRawData(${i.name}, ${i.key}) → ${result}`)
  }
}

/** Serial render loop: one bridge write sequence at a time, intermediate plans are dropped. */
async function flush() {
  if (rendering || !pageReady) return
  rendering = true
  try {
    while (desired) {
      const plan = desired
      desired = null
      try {
        await apply(plan)
      } catch (err) {
        log(`render error: ${(err as Error).message}`)
        applied = null // unknown state → force a rebuild next time
      }
    }
  } finally {
    rendering = false
  }
}

/** Debounced: only the latest plan reaches the glasses. Safe to call before the bridge is ready. */
export function renderPlan(plan: PagePlan) {
  desired = plan
  if (renderTimer) return
  renderTimer = setTimeout(() => {
    renderTimer = null
    void flush()
  }, RENDER_DEBOUNCE_MS)
}

/** Idempotent: safe under React StrictMode double effects. Builds the startup page from the latest plan. */
export function initGlasses(fallback: PagePlan): Promise<BridgeStatus> {
  if (initPromise) return initPromise
  initPromise = (async (): Promise<BridgeStatus> => {
    try {
      bridge = await withTimeout(waitForEvenAppBridge(), BRIDGE_TIMEOUT_MS, 'waitForEvenAppBridge')
    } catch (err) {
      log(`no Even bridge → browser mode (${(err as Error).message})`)
      browserMode = true
      return 'browser'
    }
    // The SDK also resolves in a normal browser, but there is no native host behind it.
    if (!('flutter_inappwebview' in window)) {
      log('no flutter_inappwebview host → browser mode (mirror only)')
      bridge = null
      browserMode = true
      return 'browser'
    }
    log('bridge ready')

    const plan = desired ?? fallback
    try {
      const result = await withTimeout(
        bridge.createStartUpPageContainer(new CreateStartUpPageContainer(pageModel(plan))),
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
    markBuilt(plan)

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

    log(`startup page created: ${plan.signature}`)
    pageReady = true
    // Upload the images for the startup page, plus anything that changed while it was being created.
    desired = desired ?? plan
    void flush()
    return 'connected'
  })()
  return initPromise
}
