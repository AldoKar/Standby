// Utterance detector for the G2 mic (PCM s16le, 16 kHz, mono).
//
// - Energy VAD with hysteresis (SKILLEVEN): a high threshold to open, ~50% of it to sustain, so quiet
//   syllables and unvoiced consonants (s, f, th) don't cut a phrase in half.
// - Adaptive noise floor: the open threshold follows the room's background level.
// - Only the wearer: frames the Even app tags `other` (e.g. the clerk on the speakerphone) count as silence.
// - Short-command timing: ~800 ms of silence ends an utterance; capped at 5 s.
// - Keeps ~300 ms of pre-roll so the first syllable isn't lost.
import { AudioSpeakerRole } from '@evenrealities/even_hub_sdk'

export const SAMPLE_RATE = 16000

const FRAME_MS = 30 // analyse in 30 ms windows regardless of how the host chunks audio
const FRAME_SAMPLES = (SAMPLE_RATE * FRAME_MS) / 1000
const OPEN_MIN_RMS = 900 // absolute floor for "speech" (int16 RMS); quiet rooms sit ~100–300
const OPEN_OVER_NOISE = 3 // open at 3× the background level…
const SUSTAIN_RATIO = 0.5 // …and keep going down to 50% of the open threshold
const OPEN_FRAMES = 3 // ~90 ms above threshold to start (ignores clicks)
const END_SILENCE_MS = 800
const MIN_SPEECH_MS = 250
const MAX_UTTERANCE_MS = 5000
const PREROLL_MS = 300

export type Utterance = { pcm: Int16Array; ms: number; endedAt: number }

export class UtteranceDetector {
  private noise = 300
  private carry = new Int16Array(0)
  private oddByte: number | null = null
  private preroll: Int16Array[] = []
  private speech: Int16Array[] = []
  private speaking = false
  private loudRun = 0
  private silentMs = 0
  private speechMs = 0
  private readonly onUtterance: (u: Utterance) => void
  private readonly onSpeechStart?: () => void

  constructor(onUtterance: (u: Utterance) => void, onSpeechStart?: () => void) {
    this.onUtterance = onUtterance
    this.onSpeechStart = onSpeechStart
  }

  reset() {
    this.carry = new Int16Array(0)
    this.oddByte = null
    this.preroll = []
    this.speech = []
    this.speaking = false
    this.loudRun = 0
    this.silentMs = 0
    this.speechMs = 0
  }

  /** Feed raw bytes from audioEvent.audioPcm. An odd trailing byte is carried to the next chunk. */
  push(bytes: Uint8Array, role: AudioSpeakerRole) {
    // PCM16 = 2 bytes per sample: losing one byte would misalign every later sample (silence reads as loud).
    let raw = bytes
    if (this.oddByte !== null) {
      raw = new Uint8Array(bytes.byteLength + 1)
      raw[0] = this.oddByte
      raw.set(bytes, 1)
      this.oddByte = null
    }
    const even = raw.byteLength - (raw.byteLength % 2)
    if (even < raw.byteLength) this.oddByte = raw[raw.byteLength - 1]
    const fresh = new Int16Array(raw.buffer.slice(raw.byteOffset, raw.byteOffset + even))
    const samples = new Int16Array(this.carry.length + fresh.length)
    samples.set(this.carry)
    samples.set(fresh, this.carry.length)
    let i = 0
    for (; i + FRAME_SAMPLES <= samples.length; i += FRAME_SAMPLES) {
      this.frame(samples.subarray(i, i + FRAME_SAMPLES), role)
    }
    this.carry = samples.slice(i)
  }

  private frame(f: Int16Array, role: AudioSpeakerRole) {
    let sum = 0
    for (let k = 0; k < f.length; k++) sum += f[k] * f[k]
    const rms = Math.sqrt(sum / f.length)
    const open = Math.max(OPEN_MIN_RMS, this.noise * OPEN_OVER_NOISE)
    const someoneElse = role === AudioSpeakerRole.Other
    const copy = f.slice()

    if (!this.speaking) {
      // Background level: slow average of frames that aren't speech.
      if (rms < open) this.noise = this.noise * 0.95 + rms * 0.05
      this.preroll.push(copy)
      if (this.preroll.length * FRAME_MS > PREROLL_MS) this.preroll.shift()
      this.loudRun = !someoneElse && rms >= open ? this.loudRun + 1 : 0
      if (this.loudRun >= OPEN_FRAMES) {
        this.speaking = true
        this.speech = [...this.preroll]
        this.speechMs = this.preroll.length * FRAME_MS
        this.silentMs = 0
        this.onSpeechStart?.()
      }
      return
    }

    this.speech.push(copy)
    this.speechMs += FRAME_MS
    const voiced = !someoneElse && rms >= open * SUSTAIN_RATIO
    this.silentMs = voiced ? 0 : this.silentMs + FRAME_MS
    if (this.silentMs >= END_SILENCE_MS || this.speechMs >= MAX_UTTERANCE_MS) this.finish()
  }

  private finish() {
    const voicedMs = this.speechMs - this.silentMs
    const chunks = this.speech
    this.reset()
    if (voicedMs < MIN_SPEECH_MS) return // a cough or a click
    const total = chunks.reduce((n, c) => n + c.length, 0)
    const pcm = new Int16Array(total)
    let at = 0
    for (const c of chunks) {
      pcm.set(c, at)
      at += c.length
    }
    this.onUtterance({ pcm, ms: Math.round((total / SAMPLE_RATE) * 1000), endedAt: performance.now() })
  }
}

/** 16 kHz mono PCM16 → base64 WAV for POST /voice. */
export function wavBase64(pcm: Int16Array): string {
  const dataBytes = pcm.length * 2
  const buf = new ArrayBuffer(44 + dataBytes)
  const v = new DataView(buf)
  const str = (o: number, s: string) => [...s].forEach((ch, k) => v.setUint8(o + k, ch.charCodeAt(0)))
  str(0, 'RIFF')
  v.setUint32(4, 36 + dataBytes, true)
  str(8, 'WAVE')
  str(12, 'fmt ')
  v.setUint32(16, 16, true) // PCM chunk size
  v.setUint16(20, 1, true) // PCM
  v.setUint16(22, 1, true) // mono
  v.setUint32(24, SAMPLE_RATE, true)
  v.setUint32(28, SAMPLE_RATE * 2, true) // byte rate
  v.setUint16(32, 2, true) // block align
  v.setUint16(34, 16, true) // bits per sample
  str(36, 'data')
  v.setUint32(40, dataBytes, true)
  new Int16Array(buf, 44).set(pcm)
  const bytes = new Uint8Array(buf)
  let bin = ''
  for (let k = 0; k < bytes.length; k += 0x8000) bin += String.fromCharCode(...bytes.subarray(k, k + 0x8000))
  return btoa(bin)
}
