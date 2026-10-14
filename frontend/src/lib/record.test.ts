import { describe, expect, it } from 'vitest'
import { addSample, emptySamples, summarize } from './record'

describe('ride record', () => {
  it('summarises like the backend', () => {
    const s = emptySamples()
    const rows: [number, number, number | null, number | null, number | null][] = [
      [0, 100, 100, 80, 120],
      [5, 101, 150, 90, 130],
      [3, 100.5, null, null, null], // seek back, trainer gap
      [13, 102, 0, 0, 0],
    ]
    for (const [dist, elev, power, rpm, pulse] of rows)
      addSample(s, { dist, elev, grade: 2, sim: 1, brake: 5, power, rpm, pulse })
    expect(s.t).toEqual([0, 1, 2, 3])
    const sum = summarize(s)
    expect(sum).toMatchObject({ durationS: 4, distanceM: 15, elevGainM: 2.5, avgRpm: 85, avgPulse: 125 })
    expect(sum.avgPower).toBeCloseTo(83.33, 1)
  })

  it('has no averages without a trainer', () => {
    const s = emptySamples()
    addSample(s, { dist: 0, elev: 0, grade: 0, sim: 0, brake: null, power: null, rpm: null, pulse: null })
    expect(summarize(s)).toMatchObject({ avgPower: null, avgRpm: null, avgPulse: null })
  })
})
