import { describe, expect, it } from 'vitest'
import type { RouteSummary } from '@/types/api'
import { lengthOf, matches, terrainOf } from './routeFilter'

const route = (km: number, gain: number, loss: number, minutes: number | null): RouteSummary => ({
  id: 1,
  title: '',
  distance_km: km,
  elev_gain_m: gain,
  elev_loss_m: loss,
  max_grade: null,
  video: minutes == null ? null : { source: 'youtube', source_id: 'x', duration_s: minutes * 60 },
})

describe('route filter', () => {
  it('sorts the processed rides into length classes', () => {
    expect(lengthOf(route(6.3, 68, 0, 15))).toBe('short')
    expect(lengthOf(route(11, 236, 0, 30))).toBe('short')
    expect(lengthOf(route(27.7, 41, 0, 60))).toBe('medium')
    expect(lengthOf(route(65, 1898, 0, 90))).toBe('long')
    expect(lengthOf(route(41.7, 972, 0, 93))).toBe('xlong')
    expect(lengthOf(route(10, 0, 0, null))).toBeNull()
  })

  it('classifies terrain by metres climbed per km', () => {
    expect(terrainOf(route(27.7, 41, 40, 60))).toBe('flat') // Saarschleife 1.5 m/km
    expect(terrainOf(route(24.2, 184, 180, 45))).toBe('rolling') // 7.6 m/km
    expect(terrainOf(route(11.2, 236, 230, 30))).toBe('hilly') // 21.1 m/km
    expect(terrainOf(route(14.9, 528, 100, 40))).toBe('climb') // Vinschgau 35.4 m/km
  })

  it('tells a descent from a flat road', () => {
    expect(terrainOf(route(20, 100, 1500, 40))).toBe('descent')
    expect(terrainOf(route(20, 10, 40, 40))).toBe('flat') // loses a little, but 2 m/km is no descent
  })

  it('matches both filters, an unset one matches anything', () => {
    const r = route(14.9, 528, 100, 40)
    expect(matches(r, { length: null, terrain: null })).toBe(true)
    expect(matches(r, { length: 'medium', terrain: 'climb' })).toBe(true)
    expect(matches(r, { length: 'short', terrain: null })).toBe(false)
    expect(matches(route(10, 0, 0, null), { length: 'short', terrain: null })).toBe(false)
  })
})
