// Executes what a gesture means on the current screen.
import { log } from '../debug/logger'
import { transport } from '../events/transport'
import { showScreen, showScreenIfCurrent } from './controller'
import type { HudAction } from './screens'

let inFlight = false

export async function performAction(action: HudAction): Promise<void> {
  if (action.kind === 'dismiss') {
    showScreen({ header: 'STANDBY', icon: 'check', lines: ['Okay, leaving it', 'Ask me anytime'] })
    return
  }
  if (inFlight) return // ignore repeated taps while a request is pending
  inFlight = true
  const gen = showScreen({
    header: 'STANDBY',
    icon: 'search',
    lines: [action.kind === 'reject' ? 'Skipping…' : 'One sec…'],
  })
  try {
    if (action.kind === 'accept_alert') await transport.acceptAlert(action.task_id)
    else await transport.approve(action.task_id, action.kind === 'approve')
  } catch (err) {
    const msg = (err as Error).message
    log(`action ${action.kind} failed: ${msg}`)
    // Distinct on-lens wording per failure, but only if nothing newer replaced the screen.
    showScreenIfCurrent(gen, {
      header: 'STANDBY · REQUEST FAILED',
      alert: true,
      icon: 'alert',
      lines: ["Couldn't do that", msg],
      choices: { tap: 'Retry' },
      onTap: action,
    })
  } finally {
    inFlight = false
  }
}
