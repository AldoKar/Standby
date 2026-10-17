// Local mock of the Handle It agent (no backend yet).
// Each reply has the full chat text and a HUD version (max 3 short lines).
// `onTap` is what happens if the user taps the glasses while this reply is on screen.
export type AgentReply = { chat: string; hud: string[]; onTap?: AgentReply }

export const HUD_MAX_LINES = 3

export const IDLE_HUD = ['Handle It', 'Ready']

const REBOOKED: AgentReply = {
  chat: 'Paid $215 with Visa (mock). I called United and they confirmed. You are rebooked on UA927, gate 61.',
  hud: ['✓ Rebooked', 'UA927 · 8:40 PM', 'Gate 61'],
}

const ALTERNATIVE: AgentReply = {
  chat:
    'I checked alternatives: DL412 is $340 (over your $250 budget), AS1098 lands after 10 PM. Best fit is UA927, 7:15 PM → 8:40 PM, $215. Tap to approve.',
  hud: ['UA927 · 8:40 PM', '$215', 'Tap to approve'],
  onTap: REBOOKED,
}

export function mockReply(input: string): AgentReply {
  const text = input.toLowerCase()

  if (/\b(sf|san francisco|sfo|flight|vuelo)\b/.test(text)) {
    return {
      chat:
        'I compared flights LAX → SFO for tomorrow. Best option: United UA183, departs 6:10 PM, arrives 7:35 PM, $189. Tap on the glasses to buy it.',
      hud: ['UA183 · 6:10 PM', '$189', 'Tap to buy'],
      onTap: {
        chat: 'Paid $189 with Visa (mock). Boarding pass saved to your Vault.',
        hud: ['✓ Booked', 'UA183 · 6:10 PM', 'Gate 52'],
      },
    }
  }
  if (/\b(gate|puerta)\b/.test(text)) {
    return { chat: 'Heads up: your gate changed from 52 to 61.', hud: ['Gate changed', '52 → 61'] }
  }
  if (/\b(cancel|cancelado|cancelled)\b/.test(text)) {
    return {
      chat: 'UA183 was cancelled. Want me to find an alternative and rebook you? Tap on the glasses = yes.',
      hud: ['UA183 CANCELLED', 'Want me to fix it?', 'Tap = yes'],
      onTap: ALTERNATIVE,
    }
  }
  return {
    chat: `Got it: "${input}". Try "book me a flight to SF", "gate" or "cancel".`,
    hud: ['Handle It', 'Listening…'],
  }
}

export function hudText(lines: string[]): string {
  return lines.slice(0, HUD_MAX_LINES).join('\n')
}
