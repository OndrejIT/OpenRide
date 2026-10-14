// Pure ride math: lookups on the distance profile and video timing, derived HUD values.
import type { Profile, Timing } from '@/types/api'

export const AHEAD_M = 500
/** |grade| below this reads as flat. */
export const FLAT_GRADE = 1

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** Index of the last sample with xs[i] <= x (0 when x is before the start). */
export function floorIndex(xs: readonly number[], x: number): number {
  let lo = 0
  let hi = xs.length - 1
  if (hi < 0 || x < xs[0]!) return 0
  if (x >= xs[hi]!) return hi
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (xs[mid]! <= x) lo = mid
    else hi = mid
  }
  return lo
}

/** Linear interpolation of ys over ascending xs, clamped to the ends. */
export function interp(xs: readonly number[], ys: readonly number[], x: number): number {
  const i = floorIndex(xs, x)
  const j = Math.min(i + 1, xs.length - 1)
  const x0 = xs[i]!
  const x1 = xs[j]!
  if (x1 <= x0) return ys[i]!
  const f = clamp((x - x0) / (x1 - x0), 0, 1)
  return ys[i]! + (ys[j]! - ys[i]!) * f
}

export const routeLength = (p: Profile) => p.dist[p.dist.length - 1] ?? 0
export const elevAt = (p: Profile, d: number) => interp(p.dist, p.elev, d)
export const gradeAt = (p: Profile, d: number) => interp(p.dist, p.grade, d)

export function latLonAt(p: Profile, d: number): [number, number] | null {
  if (!p.lat || !p.lon) return null
  return [interp(p.dist, p.lat, d), interp(p.dist, p.lon, d)]
}

/** Compass bearing (deg) from a to b, both [lat, lon]. */
export function bearing(a: [number, number], b: [number, number]): number {
  const rad = Math.PI / 180
  const [la1, lo1] = [a[0] * rad, a[1] * rad]
  const [la2, lo2] = [b[0] * rad, b[1] * rad]
  const y = Math.sin(lo2 - lo1) * Math.cos(la2)
  const x = Math.cos(la1) * Math.sin(la2) - Math.sin(la1) * Math.cos(la2) * Math.cos(lo2 - lo1)
  return (((Math.atan2(y, x) / rad) % 360) + 360) % 360
}

/** Heading of travel at d, measured over a window so GPS jitter does not swing the camera. */
export function headingAt(p: Profile, d: number, behindM = 20, aheadM = 60): number | null {
  const len = routeLength(p)
  const a = latLonAt(p, clamp(d - behindM, 0, len))
  const b = latLonAt(p, clamp(d + aheadM, 0, len))
  if (!a || !b || (a[0] === b[0] && a[1] === b[1])) return null
  return bearing(a, b)
}

/** Mean grade (%) over the next `span` metres, or null when less than 50 m remain. */
export function aheadGrade(p: Profile, d: number, span = AHEAD_M): { meters: number; grade: number } | null {
  const end = routeLength(p)
  const d0 = clamp(d, 0, end)
  const d1 = Math.min(d0 + span, end)
  if (d1 - d0 <= 50) return null
  return { meters: d1 - d0, grade: ((elevAt(p, d1) - elevAt(p, d0)) / (d1 - d0)) * 100 }
}

/**
 * Simulated grade sent to a smart trainer (Zwift-like trainer difficulty): grade × difficulty,
 * descents softened by half more and never below −5 %; level 0–10 for the HUD bars.
 */
export function resistance(grade: number, difficulty: number): { sim: number; level: number } {
  const k = clamp(difficulty, 0, 1)
  const sim = clamp(grade >= 0 ? grade * k : grade * k * 0.5, -5, 20)
  // −2 % → 0, ~+12 % → 10
  const level = clamp(Math.round((sim + 2) / 1.4), 0, 10)
  return { sim, level }
}

/** Video time (s) → distance (m). */
export const timeToDist = (t: Timing, s: number) => interp(t.t, t.dist, s)

/** Distance (m) → first video time reaching it; plateaus (rider stopped) resolve to their start. */
export function distToTime(t: Timing, d: number): number {
  const n = t.dist.length
  if (!n) return 0
  if (d <= t.dist[0]!) return t.t[0]!
  if (d >= t.dist[n - 1]!) {
    // first second at the final distance, not the end of a trailing standstill
    let i = n - 1
    while (i > 0 && t.dist[i - 1]! >= d) i--
    return t.t[i]!
  }
  let lo = 0
  let hi = n - 1
  // first index with dist >= d
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (t.dist[mid]! < d) lo = mid + 1
    else hi = mid
  }
  const d0 = t.dist[lo - 1]!
  const d1 = t.dist[lo]!
  const f = d1 > d0 ? (d - d0) / (d1 - d0) : 1
  return t.t[lo - 1]! + (t.t[lo]! - t.t[lo - 1]!) * f
}

/** Ground speed (km/h) implied by the timing around video time s. */
export function speedAt(t: Timing, s: number, halfWindow = 2): number {
  const a = Math.max(t.t[0] ?? 0, s - halfWindow)
  const b = Math.min(t.t[t.t.length - 1] ?? 0, s + halfWindow)
  if (b <= a) return 0
  return ((timeToDist(t, b) - timeToDist(t, a)) / (b - a)) * 3.6
}

/** Nearest profile distance to a clicked map point. */
export function nearestDist(p: Profile, lat: number, lon: number): number {
  if (!p.lat || !p.lon) return 0
  let best = 0
  let bestD = Infinity
  for (let i = 0; i < p.lat.length; i++) {
    const dd = (p.lat[i]! - lat) ** 2 + (p.lon[i]! - lon) ** 2
    if (dd < bestD) {
      bestD = dd
      best = i
    }
  }
  return p.dist[best]!
}

export type GradeKind = 'flat' | 'climb' | 'descent'
export const gradeKind = (g: number): GradeKind =>
  Math.abs(g) < FLAT_GRADE ? 'flat' : g > 0 ? 'climb' : 'descent'
export const GRADE_LABEL: Record<GradeKind, string> = {
  flat: 'ROVINA',
  climb: 'STOUPÁNÍ',
  descent: 'KLESÁNÍ',
}

// ---------- formatting (cs) ----------
const minus = (s: string) => s.replace('-', '−')
export const fmtPct = (g: number) => minus(`${g > 0 ? '+' : ''}${g.toFixed(1).replace('.', ',')} %`)
export const fmtKm = (m: number, digits = 2) => `${(m / 1000).toFixed(digits).replace('.', ',')} km`
export const fmtM = (m: number) => minus(`${Math.round(m)} m`)
export function fmtTime(s: number): string {
  const a = Math.max(0, Math.floor(s))
  const h = Math.floor(a / 3600)
  const mm = Math.floor((a % 3600) / 60)
  const ss = String(a % 60).padStart(2, '0')
  return h ? `${h}:${String(mm).padStart(2, '0')}:${ss}` : `${mm}:${ss}`
}
