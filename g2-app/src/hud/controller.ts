// Single owner of what is on the lens. Every render bumps a generation counter;
// async work captures the generation and only renders if nothing newer was shown since.
//
// Also runs the icon animations (hud/animations.ts): one timer at most, stopped on every screen change,
// lowest priority (a frame waits while any real render is queued or in flight), capped duration.
import { log } from '../debug/logger'
import { imageLatencyMs, isRenderIdle, renderPlan } from '../glasses/bridge'
import { animationFor, SLOW_IMAGE_MS, type Animation } from './animations'
import { onDestinationArtReady, onLogoReady } from './images'
import { planScreen, type PagePlan } from './layout'
import { blankScreen, type HudScreen } from './screens'

type Listener = (screen: HudScreen, plan: PagePlan) => void

let current: HudScreen = blankScreen('boot')
let currentPlan: PagePlan = planScreen(current)
let generation = 0
let animTimer: ReturnType<typeof setTimeout> | null = null
const listeners = new Set<Listener>()

function withImageKeys(plan: PagePlan, overrides: Partial<Record<string, string>>): PagePlan {
  return { ...plan, images: plan.images.map((i) => (overrides[i.name] ? { ...i, key: overrides[i.name] as string } : i)) }
}

function render(overrides: Partial<Record<string, string>> = {}) {
  currentPlan = withImageKeys(planScreen(current), overrides)
  renderPlan(currentPlan)
  listeners.forEach((fn) => fn(current, currentPlan))
}

function stopAnimation() {
  if (animTimer) clearTimeout(animTimer)
  animTimer = null
}

function runAnimation(anim: Animation, gen: number) {
  const started = performance.now()
  let frame = 0
  const tick = () => {
    animTimer = null
    if (gen !== generation) return // a newer screen owns the lens
    if (!isRenderIdle()) {
      // Never compete with a real update: wait, don't skip (one-shots must reach their last frame).
      animTimer = setTimeout(tick, anim.intervalMs)
      return
    }
    if (anim.loop && performance.now() - started > anim.maxMs) {
      log(`animation rested after ${anim.maxMs / 1000}s`)
      render({ [anim.image]: anim.restKey })
      return
    }
    const latency = imageLatencyMs()
    if (anim.optional && latency !== null && latency > SLOW_IMAGE_MS) {
      log(`animation rested: image updates too slow (${Math.round(latency)}ms)`)
      render({ [anim.image]: anim.restKey })
      return
    }
    frame++
    if (!anim.loop && frame >= anim.frames.length) return
    render({ [anim.image]: anim.frames[frame % anim.frames.length] })
    if (!anim.loop && frame === anim.frames.length - 1) return
    animTimer = setTimeout(tick, anim.intervalMs)
  }
  animTimer = setTimeout(tick, anim.intervalMs)
}

let clearTimer: ReturnType<typeof setTimeout> | null = null
let shownAt = 0

/** ms since the current screen was shown (gesture settle guard). */
export function screenAgeMs(): number {
  return performance.now() - shownAt
}

/**
 * @param clearAfterS engine `clear_after_s`: blank the lens after this many seconds,
 *   unless a newer screen arrived first.
 */
export function showScreen(screen: HudScreen, clearAfterS: number | null = null): number {
  stopAnimation()
  if (clearTimer) clearTimeout(clearTimer)
  clearTimer = null
  generation++
  current = screen
  shownAt = performance.now()
  const anim = animationFor(screen, imageLatencyMs())
  render(anim ? { [anim.image]: anim.frames[0] } : {})
  if (anim) runAnimation(anim, generation)
  if (clearAfterS) {
    const gen = generation
    clearTimer = setTimeout(() => showScreenIfCurrent(gen, blankScreen(screen.id)), clearAfterS * 1000)
  }
  const gen = generation
  changeListeners.forEach((fn) => fn(screen, gen))
  return generation
}

export function currentGeneration(): number {
  return generation
}

/** Render only if `gen` is still the latest screen (prevents stale async renders). */
export function showScreenIfCurrent(gen: number, screen: HudScreen): boolean {
  if (gen !== generation) return false
  showScreen(screen)
  return true
}

/**
 * Update fields of the screen that is showing (e.g. the voice state) without making it a "new" screen:
 * the generation, gesture settle timer and clear timer stay as they are. No-op if `gen` is stale.
 */
export function patchScreen(gen: number, patch: Partial<HudScreen>): boolean {
  if (gen !== generation) return false
  current = { ...current, ...patch }
  render()
  return true
}

const changeListeners = new Set<(screen: HudScreen, gen: number) => void>()

/** Fires once per new screen (not on patches or animation frames). */
export function onScreenChange(fn: (screen: HudScreen, gen: number) => void): () => void {
  changeListeners.add(fn)
  return () => {
    changeListeners.delete(fn)
  }
}

// The home screen may have appeared before the logo loaded: draw it in.
onLogoReady(() => {
  if (current.home) render()
})

// The flight list may be showing the drawn bridge if it appeared before the photo loaded: swap it in.
onDestinationArtReady(() => {
  if (current.list) render()
})

export function currentScreen(): HudScreen {
  return current
}

export function currentPagePlan(): PagePlan {
  return currentPlan
}

export function subscribeHud(fn: Listener): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
