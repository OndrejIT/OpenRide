// Response shapes of the read-only DRF API (SPEC.md › API).

export type VideoSource = 'youtube'

export interface VideoSummary {
  source: VideoSource
  source_id: string
  duration_s: number | null
}

/** Video time → distance along the route, one sample per second of video. */
export interface Timing {
  t: number[]
  dist: number[]
}

export interface VideoDetail extends VideoSummary {
  timing: Timing
}

/** Distance-based profile, `step_m` apart; `lat`/`lon` only when the route has a GPX. */
export interface Profile {
  step_m: number
  dist: number[]
  elev: number[]
  grade: number[]
  lat?: number[]
  lon?: number[]
}

export type LatLon = [number, number]

export interface RouteSummary {
  id: number
  title: string
  distance_km: number | null
  elev_gain_m: number | null
  elev_loss_m: number | null
  max_grade: number | null
  video: VideoSummary | null
}

export interface RouteDetail extends Omit<RouteSummary, 'video'> {
  segment: LatLon[] | null
  profile: Profile
  video: VideoDetail | null
}

/** Per-second ride record; trainer series are null while the trainer is not connected. */
export interface RideSamples {
  t: number[]
  dist: number[]
  elev: number[]
  grade: number[]
  sim: number[]
  brake: (number | null)[]
  power: (number | null)[]
  rpm: (number | null)[]
  pulse: (number | null)[]
}

export interface RideSummary {
  id: number
  route: number | null
  title: string
  started_at: string
  duration_s: number
  distance_m: number
  elev_gain_m: number
  avg_power: number | null
  max_power: number | null
  avg_rpm: number | null
  avg_pulse: number | null
  max_pulse: number | null
}

export interface RideDetail extends RideSummary {
  samples: RideSamples
}
