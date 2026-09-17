import type {
  Assessment,
  AssessmentDocument,
  AssessmentProgress,
  AuditEntry,
  AnswerValue,
  CoverageCell,
  Decision,
  Dictionaries,
  DocumentFormat,
  Escalation,
  Method,
  Municipality,
  ObjectCase,
  ObjectKind,
  ObjectState,
  RoadmapItem,
  Role,
  Rule,
  User,
} from './types'

const TOKEN_KEY = 'portal.token'

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message)
  }
}

export const token = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (value: string) => localStorage.setItem(TOKEN_KEY, value),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

/** Вызывается при 401, чтобы приложение вернуло пользователя на вход. */
let onUnauthorized: () => void = () => {}
export const setUnauthorizedHandler = (handler: () => void) => {
  onUnauthorized = handler
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  const current = token.get()
  if (current) headers.set('Authorization', `Bearer ${current}`)
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(path, { ...init, headers })

  if (response.status === 401) {
    token.clear()
    onUnauthorized()
    throw new ApiError(401, 'Сессия истекла, войдите заново')
  }

  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response))
  }

  return response.status === 204 ? (undefined as T) : ((await response.json()) as T)
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    // Ошибки валидации FastAPI приходят массивом объектов.
    if (Array.isArray(detail)) {
      return detail.map((item: { msg?: string }) => item.msg ?? '').filter(Boolean).join('; ')
    }
  } catch {
    /* тело не JSON — ниже вернём общий текст */
  }
  return `Ошибка ${response.status}`
}

const qs = (params: Record<string, string | undefined>) => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value)
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

export const api = {
  async login(login: string, password: string): Promise<string> {
    const body = new URLSearchParams({ username: login, password })
    const response = await fetch('/api/auth/login', { method: 'POST', body })
    if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
    const data = (await response.json()) as { access_token: string }
    token.set(data.access_token)
    return data.access_token
  },

  me: () => request<User>('/api/auth/me'),
  dictionaries: () => request<Dictionaries>('/api/catalog/dictionaries'),
  methods: () => request<(Method & { family: string; version: number })[]>('/api/catalog/methods'),

  cases: (filters: {
    search?: string
    object_kind?: string
    state?: string
    case_status?: string
    limit?: string
    offset?: string
  }) => request<{ items: ObjectCase[]; total: number }>(`/api/cases${qs(filters)}`),

  case: (id: string) => request<ObjectCase>(`/api/cases/${id}`),

  createCase: (payload: {
    address: string
    object_kind: ObjectKind
    states: ObjectState[]
    cadastral_number_oks?: string
    cadastral_number_land?: string
    notes?: string
  }) => request<ObjectCase>('/api/cases', { method: 'POST', body: JSON.stringify(payload) }),

  updateCase: (id: string, payload: Partial<ObjectCase>) =>
    request<ObjectCase>(`/api/cases/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  deleteCase: (id: string) => request<void>(`/api/cases/${id}`, { method: 'DELETE' }),

  assessments: (caseId: string) => request<Assessment[]>(`/api/cases/${caseId}/assessments`),

  startAssessment: (caseId: string) =>
    request<Assessment>(`/api/cases/${caseId}/assessments`, { method: 'POST' }),

  assessment: (id: string) => request<AssessmentProgress>(`/api/assessments/${id}`),

  saveAnswers: (id: string, answers: Record<string, AnswerValue>) =>
    request<AssessmentProgress>(`/api/assessments/${id}/answers`, {
      method: 'PATCH',
      body: JSON.stringify({ answers }),
    }),

  decide: (id: string) => request<Assessment>(`/api/assessments/${id}/decide`, { method: 'POST' }),

  approve: (id: string) =>
    request<Assessment>(`/api/assessments/${id}/approve`, { method: 'POST' }),

  preview: (payload: { object_kind: ObjectKind; states: ObjectState[]; answers: Record<string, AnswerValue> }) =>
    request<Decision>('/api/decisions/preview', { method: 'POST', body: JSON.stringify(payload) }),

  buildRoadmap: (id: string, methodCodes: string[]) =>
    request<RoadmapItem[]>(`/api/assessments/${id}/roadmap`, {
      method: 'POST',
      body: JSON.stringify({ method_codes: methodCodes }),
    }),

  roadmap: (id: string) => request<RoadmapItem[]>(`/api/assessments/${id}/roadmap`),

  documents: (id: string) => request<AssessmentDocument[]>(`/api/assessments/${id}/documents`),

  generateDocuments: (id: string) =>
    request<AssessmentDocument[]>(`/api/assessments/${id}/documents`, { method: 'POST' }),

  /** Файл отдаётся под авторизацией, поэтому скачивается через fetch, а не ссылкой. */
  async downloadDocument(id: string, format: DocumentFormat, filename: string): Promise<void> {
    const current = token.get()
    const response = await fetch(`/api/assessments/${id}/documents/${format}`, {
      headers: current ? { Authorization: `Bearer ${current}` } : {},
    })
    if (!response.ok) throw new ApiError(response.status, await errorMessage(response))

    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    // Освобождать сразу нельзя: Safari не успевает начать загрузку.
    setTimeout(() => URL.revokeObjectURL(url), 10_000)
  },

  updateRoadmapItem: (
    id: string,
    payload: { status?: string; due_date?: string | null; note?: string | null },
  ) => request<RoadmapItem>(`/api/roadmap-items/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  }),

  escalations: (status?: string) =>
    request<Escalation[]>(`/api/escalations${qs({ escalation_status: status })}`),

  createEscalation: (payload: { case_id: string; assessment_id?: string; comment?: string }) =>
    request<Escalation>('/api/escalations', { method: 'POST', body: JSON.stringify(payload) }),

  resolveEscalation: (id: string, payload: { status: string; resolution: string }) =>
    request<Escalation>(`/api/escalations/${id}/resolve`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  municipalities: () => request<Municipality[]>('/api/admin/municipalities'),

  createMunicipality: (payload: { name: string; code?: string }) =>
    request<Municipality>('/api/admin/municipalities', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  users: () => request<User[]>('/api/admin/users'),

  createUser: (payload: {
    login: string
    password: string
    full_name: string
    position?: string
    role: Role
    municipality_id?: string
  }) => request<User>('/api/admin/users', { method: 'POST', body: JSON.stringify(payload) }),

  updateUser: (id: string, payload: Record<string, unknown>) =>
    request<User>(`/api/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  rules: (filters: { object_kind?: string; state?: string } = {}) =>
    request<Rule[]>(`/api/admin/rules${qs(filters)}`),

  createRule: (payload: {
    object_kind: ObjectKind
    state: ObjectState
    conditions: Record<string, AnswerValue>
    method_codes: string[]
    source?: string
  }) => request<Rule>('/api/admin/rules', { method: 'POST', body: JSON.stringify(payload) }),

  updateRule: (id: string, payload: { is_active?: boolean }) =>
    request<Rule>(`/api/admin/rules/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),

  coverage: () => request<CoverageCell[]>('/api/admin/rules/coverage'),

  resyncRules: () =>
    request<{ created: number; updated: number }>('/api/admin/rules/resync', { method: 'POST' }),

  audit: (action?: string) => request<AuditEntry[]>(`/api/admin/audit${qs({ action })}`),
}
