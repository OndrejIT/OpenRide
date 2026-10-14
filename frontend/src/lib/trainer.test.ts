import { describe, expect, it } from 'vitest'
import { brakeLevel, SIM_MAX, SIM_MIN } from './trainer'

describe('brakeLevel', () => {
  it('spreads the simulated grade range over the level range', () => {
    expect(brakeLevel(SIM_MIN, 1, 20)).toBe(1)
    expect(brakeLevel(SIM_MAX, 1, 20)).toBe(20)
    expect(brakeLevel((SIM_MIN + SIM_MAX) / 2, 2, 12)).toBe(7)
  })
  it('clamps grades outside the range', () => {
    expect(brakeLevel(-12, 3, 15)).toBe(3)
    expect(brakeLevel(20, 3, 15)).toBe(15)
  })
})
