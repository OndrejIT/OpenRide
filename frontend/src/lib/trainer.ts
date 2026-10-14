// Client of the ESP32 trainer bridge (openride/firmware): the browser talks to it directly on the home network.

export interface BridgeDevice {
  mac: string
  name: string
  rssi: number
  kettler: boolean
}

export interface BridgeStatus {
  version: string
  mode: 'setup' | 'station'
  wifi: { ssid: string; connected: boolean; ip: string | null; rssi: number | null }
  kettler: { mac: string; name: string; connected: boolean; scanning: boolean; devices: BridgeDevice[] }
  data: {
    rpm: number | null
    power: number | null
    pulse: number | null
    speed: number | null
    brake: number | null
    brake_min: number | null
    brake_max: number | null
    distance: number | null
    energy: number | null
    time: number | null
    online: boolean | null
    device_name: string | null
    device_type: string | null
  }
}

export const DEFAULT_BRIDGE_URL = 'http://nakole.local'
const TIMEOUT_MS = 2500

export class BridgeError extends Error {}

async function call<T>(base: string, path: string, body?: object, timeoutMs = TIMEOUT_MS): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${base.replace(/\/+$/, '')}${path}`, {
      method: body ? 'POST' : 'GET',
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(timeoutMs),
    })
  } catch {
    throw new BridgeError('Most trenažéru neodpovídá')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok || data.ok === false) throw new BridgeError(data.error ?? `HTTP ${res.status}`)
  return data as T
}

export const bridge = {
  status: (base: string, timeoutMs?: number) => call<BridgeStatus>(base, '/api/status', undefined, timeoutMs),
  setBrake: (base: string, brake: number) => call<{ brake: number }>(base, '/api/brake', { brake }),
  scan: (base: string) => call(base, '/api/kettler/scan', {}),
  selectKettler: (base: string, d: Pick<BridgeDevice, 'mac' | 'name'>) => call(base, '/api/kettler', d),
  forgetKettler: (base: string) => call(base, '/api/kettler/forget', {}),
  forgetWifi: (base: string) => call(base, '/api/wifi/forget', {}),
}

/** Simulated grade range spread over the brake levels: below → lowest level, above → highest. */
export const SIM_MIN = -5
export const SIM_MAX = 15

/** Simulated grade (grade × difficulty, see resistance()) → Kettler brake level within [lo, hi]. */
export function brakeLevel(sim: number, lo: number, hi: number): number {
  const t = Math.min(1, Math.max(0, (sim - SIM_MIN) / (SIM_MAX - SIM_MIN)))
  return Math.round(lo + t * (hi - lo))
}
