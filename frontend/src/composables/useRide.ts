import { computed, ref, type Ref } from 'vue'
import type { RouteDetail } from '@/types/api'
import {
  aheadGrade,
  distToTime,
  elevAt,
  gradeAt,
  headingAt,
  latLonAt,
  resistance,
  routeLength,
  speedAt,
  timeToDist,
} from '@/lib/ride'

const SEEK_S = 10
const SEEK_M = 100

/** Ride state: position along the route (m) driven by video time or by the virtual speed, plus derived HUD values. */
export function useRide(route: Ref<RouteDetail | null>) {
  const dist = ref(0)
  const videoTime = ref(0)
  const elapsed = ref(0)
  const playing = ref(false)
  // full grade by default: matches the brake mapping tuned on the Kettler (NaKole)
  const difficulty = ref(1)
  const speedKmh = ref(25)

  const profile = computed(() => route.value?.profile ?? null)
  const timing = computed(() => route.value?.video?.timing ?? null)
  const length = computed(() => (profile.value ? routeLength(profile.value) : 0))

  const grade = computed(() => (profile.value ? gradeAt(profile.value, dist.value) : 0))
  const ahead = computed(() => (profile.value ? aheadGrade(profile.value, dist.value) : null))
  const elev = computed(() => (profile.value ? elevAt(profile.value, dist.value) : 0))
  const latLon = computed(() => (profile.value ? latLonAt(profile.value, dist.value) : null))
  const heading = computed(() => (profile.value ? headingAt(profile.value, dist.value) : null))
  const trainer = computed(() => resistance(grade.value, difficulty.value))
  const speed = computed(() => (timing.value ? speedAt(timing.value, videoTime.value) : speedKmh.value))
  const time = computed(() => (timing.value ? videoTime.value : elapsed.value))
  const duration = computed(() => {
    const t = timing.value?.t
    return route.value?.video ? (route.value.video.duration_s ?? t?.[t.length - 1] ?? null) : null
  })

  const clampDist = (d: number) => Math.min(length.value, Math.max(0, d))

  /** Video mode: the player is the clock. */
  function setVideoTime(s: number) {
    videoTime.value = s
    if (timing.value) dist.value = clampDist(timeToDist(timing.value, s))
  }

  /** Virtual mode: integrate the set speed. */
  function advance(dtS: number) {
    if (!playing.value || timing.value) return
    dist.value = clampDist(dist.value + (speedKmh.value / 3.6) * dtS)
    elapsed.value += dtS
    if (dist.value >= length.value) playing.value = false
  }

  /** Jumps to a distance; returns the video time to seek the player to (null without video). */
  function seekDist(d: number): number | null {
    if (timing.value) {
      setVideoTime(distToTime(timing.value, clampDist(d)))
      return videoTime.value
    }
    dist.value = clampDist(d)
    return null
  }

  /** ←/→: ±10 s of video (or ±100 m without video) times `times`. */
  function step(direction: 1 | -1, times = 1): number | null {
    if (timing.value) {
      const last = timing.value.t[timing.value.t.length - 1] ?? 0
      setVideoTime(Math.min(last, Math.max(0, videoTime.value + direction * SEEK_S * times)))
      return videoTime.value
    }
    return seekDist(dist.value + direction * SEEK_M * times)
  }

  function setDifficulty(v: number) {
    difficulty.value = Math.round(Math.min(1, Math.max(0, v)) * 20) / 20
  }

  return {
    dist,
    videoTime,
    playing,
    difficulty,
    speedKmh,
    profile,
    timing,
    length,
    grade,
    ahead,
    elev,
    latLon,
    heading,
    trainer,
    speed,
    time,
    duration,
    setVideoTime,
    advance,
    seekDist,
    step,
    setDifficulty,
  }
}
