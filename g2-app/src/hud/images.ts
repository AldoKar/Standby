// Icons and bars drawn on a canvas, then exported two ways:
// - grayscale bytes (1 byte/px, row-major) for updateImageRawData on the glasses
// - a green-tinted data URL for the browser mirror (same pixels, so mirror == lens)
// Keys: "icon:<name>[:<frame>]", "bar:wave[:<frame>]". Black = off = transparent on the lens.
// Animation frames are just more keys (see hud/animations.ts); every key is drawn once and cached.
const BRIGHT = 255
const MID = 150
const DIM = 60

const gray = (v: number) => `rgb(${v},${v},${v})`

// Dot spinner: 8 dots on a ring, one bright head + one mid trail stepping clockwise.
// Discrete steps read fine at ~3 fps, unlike a rotating arc.
const SPINNER_DOTS = 8
// Voice bars per frame; frame 0 is also the static wave.
const WAVE_FRAMES = [
  [8, 16, 24, 14, 22, 10, 18, 8, 14, 20, 10, 6],
  [14, 22, 12, 20, 10, 18, 8, 16, 22, 10, 16, 10],
  [20, 10, 18, 8, 16, 24, 12, 20, 8, 14, 22, 14],
  [10, 18, 22, 16, 8, 14, 22, 12, 18, 24, 8, 18],
]
export const WAVE_FRAME_COUNT = WAVE_FRAMES.length
export const SPINNER_FRAME_COUNT = SPINNER_DOTS

function drawIcon(ctx: CanvasRenderingContext2D, name: string, frame: number | null) {
  ctx.strokeStyle = gray(BRIGHT)
  ctx.fillStyle = gray(BRIGHT)
  ctx.lineWidth = 5
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.beginPath()
  switch (name) {
    case 'search':
      ctx.arc(20, 20, 13, 0, Math.PI * 2)
      ctx.moveTo(30, 30)
      ctx.lineTo(42, 42)
      ctx.stroke()
      break
    case 'spinner': {
      const head = (frame ?? 0) % SPINNER_DOTS
      for (let d = 0; d < SPINNER_DOTS; d++) {
        const a = (d / SPINNER_DOTS) * Math.PI * 2 - Math.PI / 2 // start at 12 o'clock
        const v = d === head ? BRIGHT : d === (head + SPINNER_DOTS - 1) % SPINNER_DOTS ? MID : DIM
        ctx.fillStyle = gray(v)
        ctx.beginPath()
        ctx.arc(24 + Math.cos(a) * 17, 24 + Math.sin(a) * 17, d === head ? 4.5 : 3.5, 0, Math.PI * 2)
        ctx.fill()
      }
      break
    }
    case 'check':
      // Draw-in: frame 0 = short stroke, frame 1 = half of the long stroke, no frame = complete.
      ctx.moveTo(5, 25)
      ctx.lineTo(18, 38)
      if (frame === 1) ctx.lineTo(30, 24)
      else if (frame === null) ctx.lineTo(43, 9)
      ctx.stroke()
      break
    case 'alert':
      ctx.moveTo(24, 4)
      ctx.lineTo(45, 43)
      ctx.lineTo(3, 43)
      ctx.closePath()
      ctx.stroke()
      ctx.beginPath()
      ctx.moveTo(24, 17)
      ctx.lineTo(24, 29)
      ctx.stroke()
      ctx.beginPath()
      ctx.arc(24, 36, 3, 0, Math.PI * 2)
      ctx.fill()
      break
    case 'phone':
      ctx.moveTo(8, 6)
      ctx.bezierCurveTo(6, 28, 20, 42, 42, 40)
      ctx.lineTo(43, 31)
      ctx.lineTo(34, 27)
      ctx.lineTo(29, 31)
      ctx.bezierCurveTo(22, 28, 18, 24, 15, 17)
      ctx.lineTo(19, 12)
      ctx.lineTo(15, 4)
      ctx.closePath()
      ctx.stroke()
      break
    case 'clock':
      ctx.arc(24, 24, 19, 0, Math.PI * 2)
      ctx.moveTo(24, 12)
      ctx.lineTo(24, 24)
      ctx.lineTo(33, 30)
      ctx.stroke()
      break
    case 'plane': {
      // Silhouette pointing right, scaled into the 48×48 slot.
      ctx.save()
      ctx.translate(2, 3)
      ctx.scale(0.8, 0.8)
      const p = [
        [0, 21], [20, 19], [33, 0], [40, 0], [33, 19], [45, 19], [51, 11], [55, 11],
        [53, 24], [55, 37], [51, 37], [45, 29], [33, 29], [40, 48], [33, 48], [20, 29], [0, 27],
      ]
      p.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
      ctx.closePath()
      ctx.fill()
      ctx.restore()
      break
    }
    // 'none' draws nothing (all black = transparent)
  }
}

function drawBar(ctx: CanvasRenderingContext2D, kind: string, arg: string | undefined, h: number) {
  if (kind === 'wave') {
    const heights = WAVE_FRAMES[Number(arg ?? 0) % WAVE_FRAMES.length]
    ctx.fillStyle = gray(BRIGHT)
    heights.forEach((bh, i) => ctx.fillRect(2 + i * 14, (h - bh) / 2, 8, bh))
  }
}

// Destination photo for the flight list, already converted for the lens (public/golden-gate-g2.png:
// grayscale, black sky = unlit, 16 levels). Loaded once at startup; until it's ready (or if it fails) the
// line-art bridge is used. Separate keys so the cache never keeps the fallback once the photo is there.
const photo = { img: new Image(), ready: false }
const photoListeners = new Set<() => void>()
photo.img.onload = () => {
  photo.ready = true
  photoListeners.forEach((fn) => fn())
}

/** Runs once the destination photo has loaded (the controller re-renders a screen already showing it). */
export function onDestinationArtReady(fn: () => void): void {
  if (photo.ready) fn()
  else photoListeners.add(fn)
}
photo.img.src = `${import.meta.env.BASE_URL}golden-gate-g2.png`

// Standby's logo for the home screen (public/standby-logo-g2.png: the mascot converted for the lens, black =
// unlit, outlines bright, fills dim). Until it loads the slot is blank; the controller re-renders on load.
const logo = { img: new Image(), ready: false }
const logoListeners = new Set<() => void>()
logo.img.onload = () => {
  logo.ready = true
  logoListeners.forEach((fn) => fn())
}
logo.img.src = `${import.meta.env.BASE_URL}standby-logo-g2.png`

/** Runs once the logo has loaded (the controller re-renders the home screen if it's showing). */
export function onLogoReady(fn: () => void): void {
  if (logo.ready) fn()
  else logoListeners.add(fn)
}

/** Image key for the logo: a separate key once loaded, so the cache never keeps the blank. */
export function logoKey(): string {
  return logo.ready ? 'art:logo' : 'art:logo-loading'
}

/** Image key for the destination art: the photo once loaded, else the drawn bridge. */
export function destinationArtKey(): string {
  return photo.ready ? 'art:goldengate-photo' : 'art:goldengate'
}

// Centred text as pixels ("text:<px>:<gray>:<uri text>", see textImageKey in layout.ts). A clean sans close to
// the G2's own font; shrinks to fit so a longer title never gets cut.
const TEXT_FONT = '"Segoe UI", "Helvetica Neue", Roboto, Arial, sans-serif'

function drawText(ctx: CanvasRenderingContext2D, key: string, w: number, h: number) {
  const [, pxS, grayS, ...rest] = key.split(':')
  const text = decodeURIComponent(rest.join(':'))
  if (!text.trim()) return
  let px = Number(pxS) || 22
  ctx.font = `${px}px ${TEXT_FONT}`
  while (px > 10 && ctx.measureText(text).width > w - 8) {
    px -= 1
    ctx.font = `${px}px ${TEXT_FONT}`
  }
  ctx.fillStyle = gray(Number(grayS) || BRIGHT)
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(text, w / 2, h / 2)
}

// Golden Gate in thin line art (the trip's destination, SFO), for the flight list's right column.
// Mid brightness and strokes only: on a see-through lens a filled shape would cover the world behind it.
function drawGoldenGate(ctx: CanvasRenderingContext2D, w: number, h: number) {
  const deckY = Math.round(h * 0.7)
  const towerTop = Math.round(h * 0.12)
  const waterY = h - 10
  const left = Math.round(w * 0.27)
  const right = Math.round(w * 0.73)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'

  // Main span cable: a quadratic from tower top to tower top, sagging to just above the deck.
  const sag = deckY - 6
  const ctrlY = 2 * sag - towerTop // so the curve's lowest point is `sag`
  const cableY = (x: number) => {
    const t = (x - left) / (right - left)
    return (1 - t) * (1 - t) * towerTop + 2 * t * (1 - t) * ctrlY + t * t * towerTop
  }

  // Suspender cables (dim) first, so the main lines draw over them.
  ctx.strokeStyle = gray(DIM)
  ctx.lineWidth = 1
  ctx.beginPath()
  for (let x = left + 9; x < right - 4; x += 9) {
    ctx.moveTo(x, cableY(x))
    ctx.lineTo(x, deckY)
  }
  for (let x = 12; x < left - 4; x += 9) {
    const t = (left - x) / left
    ctx.moveTo(x, towerTop + (deckY - 4 - towerTop) * Math.sqrt(t))
    ctx.lineTo(x, deckY)
  }
  for (let x = right + 9; x < w - 8; x += 9) {
    const t = (x - right) / (w - right)
    ctx.moveTo(x, towerTop + (deckY - 4 - towerTop) * Math.sqrt(t))
    ctx.lineTo(x, deckY)
  }
  ctx.stroke()

  // Cables: main span and the two side spans down to the anchors.
  ctx.strokeStyle = gray(MID)
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(left, towerTop)
  ctx.quadraticCurveTo((left + right) / 2, ctrlY, right, towerTop)
  ctx.moveTo(left, towerTop)
  ctx.quadraticCurveTo(left * 0.45, deckY * 0.75, 4, deckY - 4)
  ctx.moveTo(right, towerTop)
  ctx.quadraticCurveTo(right + (w - right) * 0.55, deckY * 0.75, w - 4, deckY - 4)
  ctx.stroke()

  // Deck.
  ctx.lineWidth = 3
  ctx.beginPath()
  ctx.moveTo(2, deckY)
  ctx.lineTo(w - 2, deckY)
  ctx.stroke()

  // Towers: two legs with cross braces, the brightest part (the Golden Gate's signature).
  ctx.strokeStyle = gray(BRIGHT)
  ctx.lineWidth = 3
  for (const cx of [left, right]) {
    ctx.beginPath()
    ctx.moveTo(cx - 6, waterY - 4)
    ctx.lineTo(cx - 6, towerTop - 4)
    ctx.moveTo(cx + 6, waterY - 4)
    ctx.lineTo(cx + 6, towerTop - 4)
    for (const by of [towerTop + 2, towerTop + (deckY - towerTop) * 0.38, towerTop + (deckY - towerTop) * 0.72]) {
      ctx.moveTo(cx - 6, by)
      ctx.lineTo(cx + 6, by)
    }
    ctx.stroke()
  }

  // Water: two short dim dashes rows.
  ctx.strokeStyle = gray(DIM)
  ctx.lineWidth = 1
  ctx.setLineDash([10, 8])
  ctx.beginPath()
  ctx.moveTo(10, waterY)
  ctx.lineTo(w - 10, waterY)
  ctx.moveTo(30, waterY + 6)
  ctx.lineTo(w - 30, waterY + 6)
  ctx.stroke()
  ctx.setLineDash([])
}

function render(key: string, w: number, h: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return canvas
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, w, h)
  const [type, name, arg] = key.split(':')
  if (type === 'text') {
    drawText(ctx, key, w, h)
  } else if (type === 'art' && name === 'goldengate-photo' && photo.ready) {
    // The photo is 288 wide; the slot may be narrower: crop the centre instead of squashing it.
    const sw = Math.min(photo.img.naturalWidth, (w / h) * photo.img.naturalHeight)
    const sx = (photo.img.naturalWidth - sw) / 2
    ctx.drawImage(photo.img, sx, 0, sw, photo.img.naturalHeight, 0, 0, w, h)
  } else if (type === 'art' && name === 'logo' && logo.ready) {
    ctx.drawImage(logo.img, 0, 0, w, h)
  } else if (type === 'art' && name.startsWith('goldengate')) {
    drawGoldenGate(ctx, w, h)
  } else if (type === 'dot') {
    // "dot:on" / "dot:off": the minimized call's live blink, a ~10 px dot in the top-left of a container
    // that is bigger only to meet the glasses' 20 px minimum. Off = all black = nothing lit.
    if (name === 'on') {
      ctx.fillStyle = gray(BRIGHT)
      ctx.beginPath()
      ctx.arc(7, 7, 5, 0, Math.PI * 2)
      ctx.fill()
    }
  } else if (type === 'icon') {
    ctx.scale(w / 48, h / 48) // icons are drawn on a 48×48 grid; smaller slots (minimized call) scale down
    drawIcon(ctx, name, arg === undefined ? null : Number(arg))
  }
  else if (type === 'bar') drawBar(ctx, name, arg, h)
  return canvas
}

const grayCache = new Map<string, number[]>()
const urlCache = new Map<string, string>()

/** Grayscale bytes for the glasses (1 byte per pixel, row-major). */
export function imageGray(key: string, w: number, h: number): number[] {
  const id = `${key}@${w}x${h}`
  const hit = grayCache.get(id)
  if (hit) return hit
  const rgba = render(key, w, h).getContext('2d')?.getImageData(0, 0, w, h).data
  const out = new Array<number>(w * h).fill(0)
  if (rgba) for (let i = 0; i < w * h; i++) out[i] = rgba[i * 4]
  grayCache.set(id, out)
  return out
}

/** Green-tinted, alpha-by-brightness PNG for the browser mirror. */
export function imageMirrorUrl(key: string, w: number, h: number): string {
  const id = `${key}@${w}x${h}`
  const hit = urlCache.get(id)
  if (hit) return hit
  const canvas = render(key, w, h)
  const ctx = canvas.getContext('2d')
  if (ctx) {
    const img = ctx.getImageData(0, 0, w, h)
    for (let i = 0; i < img.data.length; i += 4) {
      const v = img.data[i]
      img.data[i] = 61
      img.data[i + 1] = 255
      img.data[i + 2] = 110
      img.data[i + 3] = v
    }
    ctx.putImageData(img, 0, 0)
  }
  const url = canvas.toDataURL('image/png')
  urlCache.set(id, url)
  return url
}
