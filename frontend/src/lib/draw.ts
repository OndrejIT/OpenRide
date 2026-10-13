// Canvas + colour helpers shared by the profile charts.
import { FLAT_GRADE } from './ride'

/** Sizes the backing store for the device pixel ratio; height comes from the caller, never from canvas.height. */
export function setupCanvas(canvas: HTMLCanvasElement, cssHeight: number) {
  const dpr = window.devicePixelRatio || 1
  const w = canvas.clientWidth
  const h = cssHeight
  canvas.style.height = `${h}px`
  canvas.width = Math.round(w * dpr)
  canvas.height = Math.round(h * dpr)
  const ctx = canvas.getContext('2d')!
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, w, h)
  return { ctx, w, h }
}

/** Reads tokens from the element itself, so a dark-scoped subtree (trainer HUD) gets its own values. */
export const tokenReader = (el: Element) => {
  const style = getComputedStyle(el)
  return (name: string) => style.getPropertyValue(name).trim()
}

function mix(a: string, b: string, k: number): string {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16))
  const [x, y] = [p(a), p(b)]
  return `rgb(${x.map((v, i) => Math.round(v + (y[i]! - v) * k)).join(',')})`
}

/** Flat grey below 1 %, then towards climb/descent colour, saturating at ±10 %. */
export function gradeColor(token: (name: string) => string, g: number): string {
  if (Math.abs(g) < FLAT_GRADE) return token('--flat')
  return mix(
    token('--flat'),
    token(g > 0 ? '--climb' : '--descent'),
    0.35 + 0.65 * Math.min(Math.abs(g) / 10, 1),
  )
}
