// Stand-in for the backend calls the glasses make (POST /approval, POST /accept-alert).
// It answers by publishing the event the backend would broadcast. Phase 4 extends this into
// full scripted acts; Phase 5 replaces it with real fetch calls.
import { makeEvent, publish } from './bus'

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

export async function sendApproval(task_id: string, approved: boolean): Promise<void> {
  await delay(300)
  publish(makeEvent(approved ? 'approval.granted' : 'approval.rejected', task_id, {}))
}

export async function acceptAlert(task_id: string | null): Promise<void> {
  await delay(300)
  publish(makeEvent('task.started', task_id ?? `task_${Date.now()}`, { kind: 'resolve' }))
}
