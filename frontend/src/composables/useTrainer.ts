import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { bridge, type BridgeStatus, BridgeError, brakeLevel, DEFAULT_BRIDGE_URL } from '@/lib/trainer'

const STORAGE_KEY = 'openride.trainer'
const POLL_MS = 1000
// the trainer needs a moment to settle; quicker changes of the level are just noise
const MIN_SEND_INTERVAL_MS = 1000

interface Settings {
  url: string
  /** Brake level range used for the simulated grade; null = the trainer's own min/max. */
  min: number | null
  max: number | null
  /** Pause the video when the rider stops pedalling. */
  autoPause: boolean
  /** Levels added to every computed brake level: the quick "harder / easier" knob. */
  boost: number
  /** The bridge's own IP as it reported it: resolving nakole.local takes seconds on macOS, an IP does not. */
  resolved: string | null
}

const DEFAULTS: Settings = {
  url: DEFAULT_BRIDGE_URL,
  min: null,
  max: null,
  autoPause: true,
  boost: 0,
  resolved: null,
}
// first contact through the name may wait for a slow mDNS lookup
const NAME_TIMEOUT_MS = 8000
// level range tuned on the Kettler RACER RS in NaKole; the trainer itself goes 1–20
export const DEFAULT_LEVELS = { lo: 5, hi: 18 }

function loadSettings(): Settings {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '{}') }
  } catch {
    return { ...DEFAULTS }
  }
}

// one bridge per browser: shared by the ride and the settings page
const settings = reactive<Settings>(loadSettings())
const status = ref<BridgeStatus | null>(null)
const error = ref<string | null>(null)
let users = 0
let timer: ReturnType<typeof setTimeout> | undefined
let lastSent = { level: -1, at: 0 }

function saveSettings() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  } catch {
    // private mode / blocked storage: settings just do not survive a reload
  }
}

const base = () => settings.resolved ?? settings.url

/** Status via the remembered IP; when that fails (new IP from the router), via the configured address again. */
async function fetchStatus() {
  if (settings.resolved) {
    try {
      return await bridge.status(settings.resolved)
    } catch {
      settings.resolved = null
    }
  }
  const s = await bridge.status(settings.url, NAME_TIMEOUT_MS)
  const ip = s.wifi.ip ? `http://${s.wifi.ip}` : null
  if (ip && ip !== settings.url.replace(/\/+$/, '')) {
    settings.resolved = ip
    saveSettings()
  }
  return s
}

async function poll() {
  clearTimeout(timer)
  try {
    const s = await fetchStatus()
    if (!s.kettler.connected) lastSent = { level: -1, at: 0 } // resend after the trainer reconnects
    status.value = s
    error.value = null
  } catch (e) {
    status.value = null
    error.value = (e as Error).message
  }
  if (users > 0) timer = setTimeout(poll, POLL_MS)
}

/** Live trainer state while the calling component is mounted (polling stops when nobody uses it). */
export function useTrainer() {
  onMounted(() => {
    if (users++ === 0) poll()
  })
  onBeforeUnmount(() => {
    if (--users === 0) clearTimeout(timer)
  })

  const connected = computed(() => status.value?.kettler.connected ?? false)
  const range = computed(() => {
    const d = status.value?.data
    const lo = Math.max(settings.min ?? DEFAULT_LEVELS.lo, d?.brake_min ?? 1)
    const hi = Math.min(settings.max ?? DEFAULT_LEVELS.hi, d?.brake_max ?? 20)
    return { lo: Math.min(lo, hi), hi: Math.max(lo, hi) }
  })

  // enough to take any level to the trainer's lowest or highest one (e.g. 18 → 1 on the Kettler)
  const boostLimit = computed(() => {
    const d = status.value?.data
    return (d?.brake_max ?? 20) - (d?.brake_min ?? 1)
  })

  /** Brake level for a simulated grade: spread over the range, plus the boost, within the trainer's limits. */
  function levelFor(sim: number): number {
    const d = status.value?.data
    const level = brakeLevel(sim, range.value.lo, range.value.hi) + settings.boost
    return Math.min(d?.brake_max ?? 20, Math.max(d?.brake_min ?? 1, level))
  }

  /** Sends the level for a simulated grade when it changed; throttled, no-op without a connected trainer. */
  async function applySim(sim: number) {
    if (!connected.value) return
    const level = levelFor(sim)
    const now = Date.now()
    if (level === lastSent.level || now - lastSent.at < MIN_SEND_INTERVAL_MS) return
    lastSent = { level, at: now }
    try {
      await bridge.setBrake(base(), level)
    } catch (e) {
      if (e instanceof BridgeError) error.value = e.message
      lastSent = { level: -1, at: now }
    }
  }

  function setUrl(url: string) {
    settings.url = url.trim() || DEFAULT_BRIDGE_URL
    settings.resolved = null
    saveSettings()
    poll()
  }

  function setRange(min: number | null, max: number | null) {
    settings.min = min
    settings.max = max
    saveSettings()
  }

  function setAutoPause(on: boolean) {
    settings.autoPause = on
    saveSettings()
  }

  function setBoost(boost: number) {
    settings.boost = Math.min(boostLimit.value, Math.max(-boostLimit.value, Math.round(boost)))
    saveSettings()
  }

  return {
    settings,
    status,
    error,
    connected,
    range,
    boostLimit,
    levelFor,
    applySim,
    setUrl,
    setRange,
    setAutoPause,
    setBoost,
    base,
    refresh: poll,
  }
}
