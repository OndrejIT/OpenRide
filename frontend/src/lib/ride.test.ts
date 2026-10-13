import { describe, expect, it } from 'vitest'
import type { Profile, Timing } from '@/types/api'
import {
  aheadElevations,
  aheadGrade,
  bearing,
  distToTime,
  elevAt,
  fmtPct,
  fmtTime,
  gradeAt,
  gradeKind,
  headingAt,
  interp,
  nearestDist,
  resistance,
  speedAt,
  timeToDist,
} from './ride'

// 1 km: 0–500 m flat at 100 m, 500–1000 m climbing 5 % (to 125 m)
const dist = Array.from({ length: 101 }, (_, i) => i * 10)
const profile: Profile = {
  step_m: 10,
  dist,
  elev: dist.map((d) => (d <= 500 ? 100 : 100 + (d - 500) * 0.05)),
  grade: dist.map((d) => (d < 500 ? 0 : 5)),
  // due north along a meridian, ~1 m per 1e-5 deg ≈ 1.11 m
  lat: dist.map((d) => 50 + d * 1e-5),
  lon: dist.map(() => 14),
}

describe('interp', () => {
  it('interpolates and clamps to the ends', () => {
    expect(interp([0, 10], [0, 100], 2.5)).toBe(25)
    expect(interp([0, 10], [0, 100], -5)).toBe(0)
    expect(interp([0, 10], [0, 100], 99)).toBe(100)
  })
  it('handles duplicate x without dividing by zero', () => {
    expect(interp([0, 5, 5, 10], [0, 1, 2, 3], 5)).toBe(2)
  })
})

describe('profile lookups', () => {
  it('grade and elevation by distance', () => {
    expect(gradeAt(profile, 250)).toBe(0)
    expect(gradeAt(profile, 495)).toBeCloseTo(2.5)
    expect(gradeAt(profile, 800)).toBe(5)
    expect(elevAt(profile, 700)).toBeCloseTo(110)
  })
})

describe('aheadGrade', () => {
  it('averages the next 500 m', () => {
    const a = aheadGrade(profile, 500)!
    expect(a.meters).toBe(500)
    expect(a.grade).toBeCloseTo(5)
    expect(aheadGrade(profile, 250)!.grade).toBeCloseTo(2.5)
  })
  it('shortens near the finish and stops in the last 50 m', () => {
    expect(aheadGrade(profile, 800)!.meters).toBe(200)
    expect(aheadGrade(profile, 960)).toBeNull()
  })
  it('samples 25 m columns', () => {
    const e = aheadElevations(profile, 0)
    expect(e).toHaveLength(21)
    expect(e[20]).toBeCloseTo(100)
    expect(aheadElevations(profile, 900)).toHaveLength(5)
  })
})

describe('resistance', () => {
  it('scales climbs by difficulty', () => {
    expect(resistance(10, 0.5).sim).toBe(5)
    expect(resistance(10, 1).sim).toBe(10)
    expect(resistance(10, 0).sim).toBe(0)
  })
  it('halves descents further and floors at −5 %', () => {
    expect(resistance(-8, 0.5).sim).toBe(-2)
    expect(resistance(-30, 1).sim).toBe(-5)
  })
  it('caps at 20 % and maps to level 0–10', () => {
    expect(resistance(40, 1)).toEqual({ sim: 20, level: 10 })
    expect(resistance(-30, 1).level).toBe(0)
    expect(resistance(0, 0.5).level).toBe(1)
    expect(resistance(12, 1).level).toBe(10)
  })
})

describe('timing', () => {
  // stops between 2–4 s at 20 m
  const timing: Timing = { t: [0, 1, 2, 3, 4, 5], dist: [0, 10, 20, 20, 20, 30] }
  it('video time → distance', () => {
    expect(timeToDist(timing, 0.5)).toBe(5)
    expect(timeToDist(timing, 3.5)).toBe(20)
    expect(timeToDist(timing, 4.5)).toBe(25)
    expect(timeToDist(timing, 99)).toBe(30)
  })
  it('distance → first video time reaching it', () => {
    expect(distToTime(timing, 15)).toBe(1.5)
    expect(distToTime(timing, 20)).toBe(2)
    expect(distToTime(timing, 25)).toBe(4.5)
    expect(distToTime(timing, -1)).toBe(0)
    expect(distToTime(timing, 1000)).toBe(5)
  })
  it('round-trips while moving', () => {
    for (const s of [0.3, 1.7, 4.2]) expect(distToTime(timing, timeToDist(timing, s))).toBeCloseTo(s)
  })
  it('speed from timing', () => {
    expect(speedAt(timing, 1, 1)).toBeCloseTo(36)
    expect(speedAt(timing, 3, 1)).toBe(0)
  })
})

describe('heading and map pick', () => {
  it('bearing north/east', () => {
    expect(bearing([50, 14], [51, 14])).toBeCloseTo(0)
    expect(bearing([0, 14], [0, 15])).toBeCloseTo(90)
    expect(bearing([50, 14], [49, 14])).toBeCloseTo(180)
  })
  it('heading along the profile', () => {
    expect(headingAt(profile, 300)).toBeCloseTo(0)
    expect(headingAt({ ...profile, lat: undefined }, 300)).toBeNull()
  })
  it('nearest distance to a point', () => {
    expect(nearestDist(profile, 50 + 431e-5, 14)).toBe(430)
  })
})

describe('formatting', () => {
  it('cs number format', () => {
    expect(fmtPct(-3.25)).toBe('−3,3 %')
    expect(fmtPct(2)).toBe('+2,0 %')
    expect(fmtTime(3725)).toBe('1:02:05')
    expect(fmtTime(65)).toBe('1:05')
    expect(gradeKind(0.5)).toBe('flat')
    expect(gradeKind(-2)).toBe('descent')
  })
})
