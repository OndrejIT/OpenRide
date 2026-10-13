import type { RouteDetail, RouteSummary } from '@/types/api'
import type { FormErrors, ManagedVideo, Session } from '@/types/manage'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  return (await res.json()) as T
}

export const fetchRoutes = () => get<RouteSummary[]>('/api/routes/')
export const fetchRoute = (id: number | string) => get<RouteDetail>(`/api/routes/${id}/`)

// ---- management (staff session; POSTs carry Django's CSRF token from its cookie)

export class FormError extends Error {
  constructor(public errors: FormErrors) {
    super('Formulář obsahuje chyby')
  }
}

function csrfToken(): string {
  return document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/)?.[1] ?? ''
}

async function post<T>(path: string, body?: FormData): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    body,
    headers: { Accept: 'application/json', 'X-CSRFToken': csrfToken() },
  })
  const data = await res.json().catch(() => ({}))
  if (res.status === 400) throw new FormError(data as FormErrors)
  if (!res.ok) throw new Error((data as { detail?: string }).detail ?? `${path}: HTTP ${res.status}`)
  return data as T
}

export const fetchSession = () => get<Session>('/api/manage/session/')
export const fetchManagedVideos = () => get<ManagedVideo[]>('/api/manage/videos/')
export const addVideo = (form: FormData) => post<ManagedVideo>('/api/manage/videos/', form)
export const processVideo = (id: number) => post<ManagedVideo>(`/api/manage/videos/${id}/process/`)
