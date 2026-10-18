// Thin wrapper around the Even Hub SDK.
// - Works inside the Even App WebView / simulator (real bridge).
// - Falls back to "browser mode" in a normal browser (HUD mirror only).
//
// Rendering: callers hand over a PagePlan (hud/layout.ts). A single serial loop applies only the latest
// plan: full rebuild when the layout signature changes, otherwise per-container text/image updates.
import {
  AudioInputSource,
  AudioSpeakerRole,
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

// Team decision: double tap does nothing in the app (it must never close Standby mid-demo).
// ⚠ Even's review expects double tap to exit via shutDownPageContainer(1) (see SKILLEVEN.md); the system may
// also show its own exit dialog on the root page regardless. Flip to `true` before submitting if Even asks.
const DOUBLE_TAP_EXITS = false

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

// ---------- microphone ----------
// PCM s16le, 16 kHz, mono, via onEvenHubEvent → audioEvent. The page must exist before the glasses mic opens.
export type AudioListener = (pcm: Uint8Array, role: AudioSpeakerRole) => void
const audioListeners = new Set<AudioListener>()
let micOpen = false

export function onAudio(fn: AudioListener): () => void {
  audioListeners.add(fn)
  return () => {
    audioListeners.delete(fn)
  }
}

/**
 * Open or close the glasses mic. Returns what the SDK says, but that boolean can be `false` without
 * throwing in QR sideload (SKILLEVEN): the voice layer counts real audio chunks instead of trusting it.
 */
export async function setMic(open: boolean): Promise<boolean> {
  if (!bridge || !pageReady) return false
  if (open === micOpen) return true
  micOpen = open
  try {
    const ok = await withTimeout(
      open ? bridge.audioControl(true, AudioInputSource.Glasses) : bridge.audioControl(false),
      CALL_TIMEOUT_MS,
      'audioControl',
    )
    log(`mic ${open ? 'on' : 'off'} → audioControl returned ${ok}`)
    return ok
  } catch (err) {
    log(`mic ${open ? 'on' : 'off'} failed: ${(err as Error).message}`)
    micOpen = !open
    return false
  }
}

export function canUseMic(): boolean {
  return Boolean(bridge && pageReady)
}

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
          borderColor: t.border ? (t.borderLevel ?? BORDER_COLOR) : 0,
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

// Host limits (SKILLEVEN.md). Breaking ANY of them fails the whole page: the lens goes blank and the host may
// close the app. The simulator doesn't enforce them, so check here before sending.
const IMAGE_W = [20, 288]
const IMAGE_H = [20, 144]
const MAX_TEXTS = 8
const MAX_IMAGES = 4
const MAX_CONTAINERS = 12

/** What's wrong with a page for the real glasses (empty = fine). */
export function planProblems(plan: PagePlan): string[] {
  const out: string[] = []
  const total = plan.texts.length + plan.images.length
  if (total < 1 || total > MAX_CONTAINERS) out.push(`${total} containers (1–${MAX_CONTAINERS})`)
  if (plan.texts.length > MAX_TEXTS) out.push(`${plan.texts.length} text containers (max ${MAX_TEXTS})`)
  if (plan.images.length > MAX_IMAGES) out.push(`${plan.images.length} image containers (max ${MAX_IMAGES})`)
  if (plan.texts.filter((t) => t.capture).length !== 1) out.push('exactly one text container must capture events')
  for (const i of plan.images) {
    if (i.w < IMAGE_W[0] || i.w > IMAGE_W[1] || i.h < IMAGE_H[0] || i.h > IMAGE_H[1]) {
      out.push(`image ${i.name} ${i.w}×${i.h} (w ${IMAGE_W.join('–')}, h ${IMAGE_H.join('–')})`)
    }
  }
  const zs = [...plan.texts, ...plan.images].map((c) => c.z)
  if (new Set(zs).size !== zs.length) out.push('z orders must be unique')
  return out
}

// The last page the glasses accepted: if a new one is rejected, go back to it instead of leaving the lens
// empty (an empty page with nothing capturing events can close the app).
let lastGood: PagePlan | null = null

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
    const problems = planProblems(plan)
    if (problems.length) {
      // Never send a page the glasses would reject: keep what's on the lens.
      log(`page ${plan.signature} NOT sent, invalid for the glasses: ${problems.join('; ')}`)
      return
    }
    const ok = await withTimeout(b.rebuildPageContainer(new RebuildPageContainer(pageModel(plan))), CALL_TIMEOUT_MS, 'rebuildPageContainer')
    if (!ok) {
      log(`rebuildPageContainer returned false (${plan.signature})`)
      applied = null // the native page is in an unknown state
      if (lastGood && lastGood !== plan && !desired) {
        log(`restoring the last page that worked (${lastGood.signature})`)
        desired = lastGood // flush() picks it up right away
      }
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
  lastGood = plan
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

    // The first page must be valid or the app never shows; fall back to the boot screen if it isn't.
    const plan = desired && planProblems(desired).length === 0 ? desired : fallback
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
    lastGood = plan

    bridge.onEvenHubEvent((event) => {
      // Mic frames arrive on the same channel as gestures; they are never gestures.
      if (event.audioEvent) {
        const a = event.audioEvent
        audioListeners.forEach((fn) => fn(a.audioPcm, a.speakerRole))
        return
      }
      // WebView audio is about to die (phone locked / app backgrounded): close the mic cleanly.
      if (event.sysEvent?.eventType === OsEventTypeList.FOREGROUND_EXIT_EVENT) {
        log('foreground exit → mic off')
        void setMic(false)
        return
      }
      const input = toInput(event)
      if (!input) return
      if (input === 'double_tap') {
        if (DOUBLE_TAP_EXITS) {
          log('double tap → shutDownPageContainer(1)')
          void bridge?.shutDownPageContainer(1)
        } else {
          log('double tap ignored (DOUBLE_TAP_EXITS = false)')
        }
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
