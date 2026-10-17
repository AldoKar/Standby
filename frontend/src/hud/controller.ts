// Single owner of what is on the lens. Every render bumps a generation counter;
// async work captures the generation and only renders if nothing newer was shown since.
import { renderPlan } from '../glasses/bridge'
import { planScreen } from './layout'
import type { HudScreen } from './screens'

let current: HudScreen = { header: '', lines: [] }
let generation = 0
const listeners = new Set<(s: HudScreen) => void>()

export function showScreen(screen: HudScreen): number {
  generation++
  current = screen
  renderPlan(planScreen(screen))
  listeners.forEach((fn) => fn(screen))
  return generation
}

/** Render only if `gen` is still the latest screen (prevents stale async renders). */
export function showScreenIfCurrent(gen: number, screen: HudScreen): boolean {
  if (gen !== generation) return false
  showScreen(screen)
  return true
}

export function currentScreen(): HudScreen {
  return current
}

export function subscribeHud(fn: (s: HudScreen) => void): () => void {
  listeners.add(fn)
  return () => {
    listeners.delete(fn)
  }
}
