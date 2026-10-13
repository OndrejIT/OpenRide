import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import type { RouteDetail } from '@/types/api'
import { useRide } from './useRide'

const dist = Array.from({ length: 201 }, (_, i) => i * 10)
const base: RouteDetail = {
  id: 1,
  title: 'test',
  distance_km: 2,
  elev_gain_m: 100,
  elev_loss_m: 0,
  max_grade: 5,
  segment: null,
  // constant 5 % climb over 2 km
  profile: { step_m: 10, dist, elev: dist.map((d) => d * 0.05), grade: dist.map(() => 5) },
  video: null,
}
const withVideo: RouteDetail = {
  ...base,
  // 10 m/s for 200 s
  video: {
    source: 'youtube',
    source_id: 'x',
    duration_s: 200,
    timing: { t: Array.from({ length: 201 }, (_, i) => i), dist },
  },
}

describe('useRide – virtual', () => {
  it('advances by speed only while playing and stops at the finish', () => {
    const r = useRide(ref(base))
    r.speedKmh.value = 36
    r.advance(1)
    expect(r.dist.value).toBe(0)
    r.playing.value = true
    r.advance(2)
    expect(r.dist.value).toBeCloseTo(20)
    expect(r.time.value).toBe(2)
    r.advance(1000)
    expect(r.dist.value).toBe(2000)
    expect(r.playing.value).toBe(false)
    expect(r.ahead.value).toBeNull()
  })
  it('steps ±100 m and derives HUD values', () => {
    const r = useRide(ref(base))
    expect(r.step(1)).toBeNull()
    expect(r.dist.value).toBe(100)
    expect(r.grade.value).toBe(5)
    expect(r.ahead.value!.grade).toBeCloseTo(5)
    expect(r.trainer.value).toEqual({ sim: 2.5, level: 3 })
    r.setDifficulty(1.3)
    expect(r.difficulty.value).toBe(1)
    expect(r.trainer.value.sim).toBe(5)
    r.step(-1)
    r.step(-1)
    expect(r.dist.value).toBe(0)
  })
})

describe('useRide – video', () => {
  it('position follows video time', () => {
    const r = useRide(ref(withVideo))
    r.setVideoTime(12.5)
    expect(r.dist.value).toBeCloseTo(125)
    expect(r.speed.value).toBeCloseTo(36)
    expect(r.duration.value).toBe(200)
  })
  it('seeks by distance and ±10 s', () => {
    const r = useRide(ref(withVideo))
    expect(r.seekDist(500)).toBeCloseTo(50)
    expect(r.dist.value).toBeCloseTo(500)
    expect(r.step(1)).toBeCloseTo(60)
    expect(r.step(-1)).toBeCloseTo(50)
    r.playing.value = true
    r.advance(5)
    expect(r.dist.value).toBeCloseTo(500)
  })
})
