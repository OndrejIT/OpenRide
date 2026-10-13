// Management API (staff only, Django session): backend/routes/manage.py.

export type Verdict = 'good' | 'warn' | 'bad'
export type VideoStatus = 'new' | 'queued' | 'processing' | 'ready' | 'failed'

export interface Choice {
  value: string
  label: string
}

export interface Session {
  user: string | null
  is_staff: boolean
  grade_sources: Choice[]
}

export interface QualityRow {
  label: string
  value: string
  verdict: Verdict | null
}

export interface ManagedVideo {
  id: number
  route_id: number
  title: string
  source_id: string
  data_source_id: string
  grade_source: string
  grade_source_label: string
  has_gpx: boolean
  status: VideoStatus
  status_label: string
  /** One line: current step with percent and remaining time, or how the last run ended. */
  state: string
  progress: { step: string; pct: number; since: number } | null
  error: string
  duration_s: number | null
  quality: QualityRow[]
  verdict: Verdict | null
  started_at: string | null
  finished_at: string | null
  admin_url: string
}

/** Django form errors: field (or __all__) → messages. */
export type FormErrors = Record<string, string[]>
