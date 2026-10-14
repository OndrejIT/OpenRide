import { computed, onBeforeUnmount, onMounted, ref, shallowRef, triggerRef, useTemplateRef, watch } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { fetchRoute, saveRide } from '@/api'
import type YoutubePlayer from '@/components/YoutubePlayer.vue'
import { useRide } from '@/composables/useRide'
import { useTrainer } from '@/composables/useTrainer'
import { addSample, emptySamples, summarize } from '@/lib/record'
import type { RouteDetail } from '@/types/api'

const DIFFICULTY_STEP = 0.05
// repeated jumps the same way grow: 10, 20, 30, 60, 120 s (×100 m without video); a pause starts again at 10 s
const STEP_TIMES = [1, 2, 3, 6, 12]
const STEP_STREAK_MS = 1500
// no cadence for this long pauses the video; pedalling again resumes it
const STOP_PEDALLING_MS = 2000

/**
 * Everything a ride screen does apart from its layout: loading the route, the clock, the trainer (resistance,
 * pausing when the rider stops pedalling), the ride record and the keyboard.
 */
export function useRideSession(opts: { keys?: Record<string, () => void>; onInput?: () => void } = {}) {
  const routeParams = useRoute()
  const data = ref<RouteDetail | null>(null)
  const error = ref<string | null>(null)
  const ride = useRide(data)
  // the screen's <YoutubePlayer ref="player">
  const player = useTemplateRef<InstanceType<typeof YoutubePlayer>>('player')
  const trainer = useTrainer()

  const video = computed(() => data.value?.video ?? null)
  const difficulty = computed({ get: () => ride.difficulty.value, set: ride.setDifficulty })
  const trainerInfo = computed(() => {
    const s = trainer.status.value
    if (!s) return null
    return {
      connected: s.kettler.connected,
      name: s.kettler.name || s.data.device_name || 'Kettler',
      brake: s.data.brake,
      brakeMax: trainer.range.value.hi,
      rpm: s.data.rpm,
      power: s.data.power,
      pulse: s.data.pulse,
    }
  })

  // trainer data, null without a trainer; pulse only with a heart rate sensor (the Kettler reports 0)
  const trainerData = computed(() => {
    const s = trainer.status.value
    return s?.kettler.connected ? s.data : null
  })
  const live = computed(() => {
    const d = trainerData.value
    return { power: d?.power ?? null, rpm: d?.rpm ?? null, pulse: d?.pulse || null, brake: d?.brake ?? null }
  })
  // a trainer that dropped out mid-ride is worth a warning even in video-only mode
  const trainerSeen = ref(false)
  watch(trainer.connected, (c) => (trainerSeen.value ||= c))
  const trainerLost = computed(() => trainerSeen.value && !trainer.connected.value)

  // the status refreshes every second, so a level skipped by the send throttle is retried
  watch([() => ride.trainer.value.sim, trainer.status], () => trainer.applySim(ride.trainer.value.sim))

  let pedalledAt = Date.now()
  let pausedByTrainer = false
  watch(trainer.status, (s) => {
    if (!trainer.settings.autoPause) pausedByTrainer = false
    if (!video.value || !trainer.settings.autoPause || !s?.kettler.connected || s.data.rpm == null) return
    const now = Date.now()
    if (s.data.rpm > 0) {
      pedalledAt = now
      if (pausedByTrainer && !ride.playing.value) player.value?.play()
      pausedByTrainer = false
    } else if (ride.playing.value && now - pedalledAt >= STOP_PEDALLING_MS) {
      pausedByTrainer = true
      player.value?.pause()
    }
  })

  // ---- ride record: one sample per second while riding, saved only when the rider confirms at the end
  const record = shallowRef(emptySamples())
  let startedAt: Date | null = null
  const finish = ref<{ finished: boolean } | null>(null)
  const saving = ref(false)
  const savedId = ref<number | null>(null)
  const saveError = ref<string | null>(null)
  const recordSummary = computed(() => summarize(record.value))
  const unsaved = computed(() => record.value.t.length > 0 && savedId.value == null)

  const recordTimer = setInterval(() => {
    if (!ride.playing.value || finish.value) return
    startedAt ??= new Date()
    const d = trainerData.value
    addSample(record.value, {
      dist: ride.dist.value,
      elev: ride.elev.value,
      grade: ride.grade.value,
      sim: ride.trainer.value.sim,
      brake: d?.brake ?? null,
      power: d?.power ?? null,
      rpm: d?.rpm ?? null,
      pulse: d?.pulse ?? null,
    })
    triggerRef(record)
  }, 1000)

  function openFinish(finished: boolean) {
    if (video.value) player.value?.pause()
    ride.playing.value = false
    if (record.value.t.length) finish.value = { finished }
  }

  // the end of the route (or of the video) ends the ride
  watch(
    () =>
      ride.length.value > 0 &&
      (ride.dist.value >= ride.length.value - 1 ||
        (ride.duration.value != null && ride.time.value >= ride.duration.value - 1)),
    (atEnd) => {
      if (atEnd && !finish.value && unsaved.value) openFinish(true)
    },
  )

  async function save() {
    saving.value = true
    saveError.value = null
    try {
      const r = await saveRide(data.value?.id ?? null, startedAt ?? new Date(), record.value)
      savedId.value = r.id
    } catch (e) {
      saveError.value = (e as Error).message
    } finally {
      saving.value = false
    }
  }

  function discard() {
    if (!confirm('Záznam jízdy se zahodí. Pokračovat?')) return
    record.value = emptySamples()
    startedAt = null
    savedId.value = null
    saveError.value = null
    finish.value = null
  }

  const LEAVE_MSG = 'Jízda není uložená a záznam se zahodí. Odejít?'
  onBeforeRouteLeave(() => !unsaved.value || confirm(LEAVE_MSG))
  function onBeforeUnload(e: BeforeUnloadEvent) {
    if (unsaved.value) e.preventDefault()
  }

  function toggle() {
    pausedByTrainer = false // a manual pause/start wins over the pedalling rule
    pedalledAt = Date.now()
    if (video.value) {
      if (ride.playing.value) player.value?.pause()
      else player.value?.play()
    } else if (ride.dist.value < ride.length.value) {
      ride.playing.value = !ride.playing.value
    }
  }

  function seek(d: number) {
    const s = ride.seekDist(d)
    if (s != null) player.value?.seekTo(s)
  }

  // the last jump direction and its size index; reset once the rider stops pressing
  const streak = ref<{ direction: 1 | -1; n: number } | null>(null)
  let streakTimer: ReturnType<typeof setTimeout> | undefined
  function step(direction: 1 | -1) {
    const n = streak.value?.direction === direction ? Math.min(streak.value.n + 1, STEP_TIMES.length - 1) : 0
    streak.value = { direction, n }
    clearTimeout(streakTimer)
    streakTimer = setTimeout(() => (streak.value = null), STEP_STREAK_MS)
    const s = ride.step(direction, STEP_TIMES[n])
    if (s != null) player.value?.seekTo(s)
  }
  /** How many 10 s (100 m) the next jump that way takes: for the label under the button. */
  const nextStep = (direction: 1 | -1) =>
    streak.value?.direction === direction
      ? STEP_TIMES[Math.min(streak.value.n + 1, STEP_TIMES.length - 1)]!
      : 1

  function onKey(e: KeyboardEvent) {
    const t = e.target as HTMLElement | null
    if (
      t &&
      (t.tagName === 'SELECT' ||
        t.tagName === 'TEXTAREA' ||
        (t.tagName === 'INPUT' && t.getAttribute('type') !== 'range'))
    )
      return
    const actions: Record<string, () => void> = {
      Space: toggle,
      ArrowRight: () => step(1),
      ArrowLeft: () => step(-1),
      ArrowUp: () => ride.setDifficulty(ride.difficulty.value + DIFFICULTY_STEP),
      ArrowDown: () => ride.setDifficulty(ride.difficulty.value - DIFFICULTY_STEP),
      ...opts.keys,
    }
    const action = actions[e.code]
    opts.onInput?.()
    if (!action || finish.value) return
    // also stops a focused slider from moving on its own
    e.preventDefault()
    action()
  }

  // the player (video) or the wall clock (virtual) drives the position
  let raf = 0
  let lastFrame = 0
  function frame(now: number) {
    const dt = lastFrame ? Math.min(0.25, (now - lastFrame) / 1000) : 0
    lastFrame = now
    if (video.value) {
      const t = player.value?.currentTime()
      if (t != null && Math.abs(t - ride.videoTime.value) > 0.05) ride.setVideoTime(t)
    } else {
      ride.advance(dt)
    }
    raf = requestAnimationFrame(frame)
  }

  onMounted(async () => {
    addEventListener('keydown', onKey)
    addEventListener('beforeunload', onBeforeUnload)
    raf = requestAnimationFrame(frame)
    try {
      data.value = await fetchRoute(String(routeParams.params.id))
      document.title = `Trenažér – ${data.value.title}`
    } catch (e) {
      error.value = (e as Error).message
    }
  })

  onBeforeUnmount(() => {
    removeEventListener('keydown', onKey)
    removeEventListener('beforeunload', onBeforeUnload)
    clearInterval(recordTimer)
    clearTimeout(streakTimer)
    cancelAnimationFrame(raf)
  })

  return {
    data,
    error,
    ride,
    trainer,
    video,
    difficulty,
    trainerInfo,
    live,
    trainerLost,
    record,
    finish,
    saving,
    savedId,
    saveError,
    recordSummary,
    openFinish,
    save,
    discard,
    toggle,
    seek,
    step,
    nextStep,
  }
}
