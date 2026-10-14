// Route list filters: ride length (video duration) and terrain (climbing per km), from the list data alone.
import type { RouteSummary } from '@/types/api'

export const LENGTHS = [
  { key: 'short', label: 'do 30 min', max: 30 },
  { key: 'medium', label: '30–60 min', max: 60 },
  { key: 'long', label: '60–90 min', max: 90 },
  { key: 'xlong', label: '90+ min', max: Infinity },
] as const
export type LengthKey = (typeof LENGTHS)[number]['key']

// metres climbed per km; bounds chosen so the processed rides spread over all classes
export const TERRAINS = [
  { key: 'flat', label: 'Rovina', max: 5 },
  { key: 'rolling', label: 'Zvlněné', max: 15 },
  { key: 'hilly', label: 'Kopcovité', max: 30 },
  { key: 'climb', label: 'Stoupání', max: Infinity },
  { key: 'descent', label: 'Sjezd', max: Infinity },
] as const
export type TerrainKey = (typeof TERRAINS)[number]['key']

/** Mostly downhill: descending more than twice the climbing, and not just a flat road losing a few metres. */
const DESCENT_RATIO = 2
const DESCENT_MIN_M_PER_KM = 5

export function lengthOf(r: RouteSummary): LengthKey | null {
  const s = r.video?.duration_s
  if (!s) return null
  const min = Math.round(s / 60)
  return LENGTHS.find((l) => min <= l.max)!.key
}

/** Metres climbed per km, null without a distance. */
export function climbPerKm(r: RouteSummary): number | null {
  return r.distance_km ? (r.elev_gain_m ?? 0) / r.distance_km : null
}

export function terrainOf(r: RouteSummary): TerrainKey | null {
  const perKm = climbPerKm(r)
  if (perKm == null) return null
  const loss = r.elev_loss_m ?? 0
  if (loss > DESCENT_RATIO * (r.elev_gain_m ?? 0) && loss / r.distance_km! >= DESCENT_MIN_M_PER_KM)
    return 'descent'
  return TERRAINS.find((t) => perKm < t.max)!.key
}

export interface RouteFilter {
  length: LengthKey | null
  terrain: TerrainKey | null
}

export function matches(r: RouteSummary, f: RouteFilter): boolean {
  return (!f.length || lengthOf(r) === f.length) && (!f.terrain || terrainOf(r) === f.terrain)
}
