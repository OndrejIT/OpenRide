// Builds frontend/mock/*.json (API format) from the prototype's per-second web/*.js profiles.
// Usage: bun scripts/gen-mock.ts [path/to/prototype/web]
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { LatLon, Profile, RouteDetail, RouteSummary, Timing } from '../src/types/api'

interface Prototype {
  title: string
  videoId: string
  dist: number[] // km, per second of video
  elevAbs: number[]
  grade: number[]
  lat: number[]
  lon: number[]
  segment: LatLon[]
}

const STEP_M = 10
const webDir = process.argv[2] ?? fileURLToPath(new URL('../../../web/', import.meta.url))
const outDir = fileURLToPath(new URL('../mock/', import.meta.url))

function load(name: string): Prototype {
  const src = readFileSync(`${webDir}/${name}.js`, 'utf8')
  // file is `window.PROFILE = {...};` – parse the literal instead of evaluating it
  return JSON.parse(src.slice(src.indexOf('{'), src.lastIndexOf('}') + 1)) as Prototype
}

const round = (v: number, digits: number) => Math.round(v * 10 ** digits) / 10 ** digits

function interp(xs: number[], ys: number[], x: number): number {
  let lo = 0
  let hi = xs.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (xs[mid]! <= x) lo = mid
    else hi = mid
  }
  const x0 = xs[lo]!
  const x1 = xs[hi]!
  const f = x1 === x0 ? 0 : Math.min(1, Math.max(0, (x - x0) / (x1 - x0)))
  return ys[lo]! + (ys[hi]! - ys[lo]!) * f
}

function buildProfile(p: Prototype): Profile {
  // keep only samples where the rider moved, so distance is strictly increasing
  const idx: number[] = []
  p.dist.forEach((km, i) => {
    if (!idx.length || km * 1000 > p.dist[idx[idx.length - 1]!]! * 1000) idx.push(i)
  })
  const xs = idx.map((i) => p.dist[i]! * 1000)
  const pick = (arr: number[]) => idx.map((i) => arr[i]!)
  const [elev, grade, lat, lon] = [pick(p.elevAbs), pick(p.grade), pick(p.lat), pick(p.lon)]
  const n = Math.floor(xs[xs.length - 1]! / STEP_M) + 1
  const dist = Array.from({ length: n }, (_, i) => i * STEP_M)
  return {
    step_m: STEP_M,
    dist,
    elev: dist.map((d) => round(interp(xs, elev, d), 1)),
    grade: dist.map((d) => round(interp(xs, grade, d), 1)),
    lat: dist.map((d) => round(interp(xs, lat, d), 6)),
    lon: dist.map((d) => round(interp(xs, lon, d), 6)),
  }
}

function buildTiming(p: Prototype): Timing {
  return { t: p.dist.map((_, i) => i), dist: p.dist.map((km) => round(km * 1000, 1)) }
}

function summarize(profile: Profile) {
  let gain = 0
  let loss = 0
  for (let i = 1; i < profile.elev.length; i++) {
    const d = profile.elev[i]! - profile.elev[i - 1]!
    if (d > 0) gain += d
    else loss -= d
  }
  return {
    distance_km: round(profile.dist[profile.dist.length - 1]! / 1000, 2),
    elev_gain_m: Math.round(gain),
    elev_loss_m: Math.round(loss),
    max_grade: Math.max(...profile.grade),
  }
}

function route(id: number, p: Prototype, withVideo: boolean, title = p.title): RouteDetail {
  const profile = buildProfile(p)
  return {
    id,
    title,
    ...summarize(profile),
    segment: p.segment.map(([la, lo]) => [round(la, 5), round(lo, 5)]),
    profile,
    video: withVideo
      ? { source: 'youtube', source_id: p.videoId, duration_s: p.dist.length - 1, timing: buildTiming(p) }
      : null,
  }
}

const deer = load('perfection')
const tyrol = load('tyrol_gpx')
const routes = [
  route(1, deer, true),
  route(2, tyrol, true),
  route(3, tyrol, false, 'South Tyrol – virtuální trasa (bez videa)'),
]

mkdirSync(`${outDir}/routes`, { recursive: true })
const list: RouteSummary[] = routes.map((r) => ({
  id: r.id,
  title: r.title,
  distance_km: r.distance_km,
  elev_gain_m: r.elev_gain_m,
  elev_loss_m: r.elev_loss_m,
  max_grade: r.max_grade,
  video: r.video && { source: r.video.source, source_id: r.video.source_id, duration_s: r.video.duration_s },
}))
writeFileSync(`${outDir}/routes.json`, JSON.stringify(list, null, 1))
for (const r of routes) writeFileSync(`${outDir}/routes/${r.id}.json`, JSON.stringify(r))
console.log(
  routes.map((r) => `${r.id}: ${r.title} – ${r.distance_km} km, ${r.profile.dist.length} bodů`).join('\n'),
)
