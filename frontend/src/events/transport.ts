// What the frontend can ask the backend to do. One method per endpoint in readme.md "Backend endpoints".
// Results never come back as return values: the backend answers by broadcasting events (bus.ts).
// Phase 4: mock implementation (mockBackend.ts). Phase 5: HTTP + SSE implementation, same interface.
import type { TripRequestBody } from '@contracts/events'
import { mockBackend } from './mockBackend'

export type SimulateKind = 'gate' | 'boarding' | 'cancel'

export interface Transport {
  /** POST /trip/request */
  requestTrip(body: TripRequestBody): Promise<void>
  /** POST /approval */
  approve(task_id: string, approved: boolean): Promise<void>
  /** POST /accept-alert */
  acceptAlert(task_id: string | null): Promise<void>
  /** POST /simulate/{gate|boarding|cancel} */
  simulate(kind: SimulateKind): Promise<void>
  /** POST /demo/reset */
  reset(): Promise<void>
}

export const transport: Transport = mockBackend
