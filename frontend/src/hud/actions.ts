// Executes what a gesture means on the current screen.
import { log } from '../debug/logger'
import { acceptAlert, sendApproval } from '../events/mockTransport'
import { showScreen, showScreenIfCurrent } from './controller'
import type { HudAction } from './screens'

let inFlight = false

export async function performAction(action: HudAction): Promise<void> {
  if (action.kind === 'dismiss') {
    showScreen({ header: 'HANDLE IT', icon: 'check', lines: ['Okay, leaving it', 'Ask me anytime'] })
    return
  }
  if (inFlight) return // ignore repeated taps while a request is pending
  inFlight = true
  const gen = showScreen({
    header: 'HANDLE IT',
    icon: 'search',
    lines: [action.kind === 'reject' ? 'Skipping…' : 'One sec…'],
  })
  try {
    if (action.kind === 'accept_alert') await acceptAlert(action.task_id)
    else await sendApproval(action.task_id, action.kind === 'approve')
  } catch (err) {
    log(`action ${action.kind} failed: ${(err as Error).message}`)
    // Distinct on-lens wording per failure, but only if nothing newer replaced the screen.
    showScreenIfCurrent(gen, {
      header: 'HANDLE IT · OFFLINE',
      alert: true,
      icon: 'alert',
      lines: ['Request failed', 'Check your connection'],
      footer: 'Tap = retry',
      onTap: action,
    })
  } finally {
    inFlight = false
  }
}
