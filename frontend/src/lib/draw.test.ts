import { describe, expect, it } from 'vitest'
import { loadColor } from './draw'

describe('loadColor', () => {
  it('runs from green (easy) to red (hard) and clamps outside 0…1', () => {
    expect(loadColor(0)).toBe('rgb(0,214,143)')
    expect(loadColor(1)).toBe('rgb(214,48,49)')
    expect(loadColor(-0.5)).toBe(loadColor(0))
    expect(loadColor(2)).toBe(loadColor(1))
    expect(loadColor(0.5)).toBe('rgb(255,159,67)') // the middle stop: orange
  })
})
