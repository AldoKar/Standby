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

function render(key: string, w: number, h: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')
  if (!ctx) return canvas
  ctx.fillStyle = '#000'
  ctx.fillRect(0, 0, w, h)
  const [type, name, arg] = key.split(':')
  if (type === 'dot') {
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
