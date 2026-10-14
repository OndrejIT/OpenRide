// Ride recording: one sample per ridden second, summarised the same way as the backend (routes/rides.py).
import type { RideSamples } from '@/types/api'

export interface Sample {
  dist: number
  elev: number
  grade: number
  sim: number
  brake: number | null
  power: number | null
  rpm: number | null
  pulse: number | null
}

export const emptySamples = (): RideSamples => ({
  t: [],
  dist: [],
  elev: [],
  grade: [],
  sim: [],
  brake: [],
  power: [],
  rpm: [],
  pulse: [],
})

const round = (v: number, digits: number) => Math.round(v * 10 ** digits) / 10 ** digits

export function addSample(s: RideSamples, x: Sample): void {
  s.t.push(s.t.length)
  s.dist.push(round(x.dist, 1))
  s.elev.push(round(x.elev, 1))
  s.grade.push(round(x.grade, 1))
  s.sim.push(round(x.sim, 1))
  s.brake.push(x.brake)
  s.power.push(x.power)
  s.rpm.push(x.rpm)
  s.pulse.push(x.pulse)
}

const present = (a: (number | null)[]) => a.filter((v): v is number => v != null)
const mean = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null)
const rise = (a: number[]) => a.slice(1).reduce((sum, v, i) => sum + Math.max(0, v - a[i]!), 0)

export interface RecordSummary {
  durationS: number
  distanceM: number
  elevGainM: number
  avgPower: number | null
  avgRpm: number | null
  avgPulse: number | null
}

/** Seeking back is not riding; cadence and pulse averages ignore standing still and missing readings. */
export function summarize(s: RideSamples): RecordSummary {
  return {
    durationS: s.t.length,
    distanceM: rise(s.dist),
    elevGainM: rise(s.elev),
    avgPower: mean(present(s.power)),
    avgRpm: mean(present(s.rpm).filter((v) => v > 0)),
    avgPulse: mean(present(s.pulse).filter((v) => v > 0)),
  }
}
