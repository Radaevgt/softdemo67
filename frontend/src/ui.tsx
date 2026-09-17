import type { ReactNode } from 'react'
import type {
  AssessmentStatus,
  CaseStatus,
  EscalationStatus,
  ObjectKind,
  ObjectState,
  Role,
} from './types'

export const OBJECT_KIND_LABELS: Record<ObjectKind, string> = {
  izhs: 'ИЖС',
  mkd_apartment: 'Квартира в МКД',
  nonresidential: 'Нежилое',
}

export const STATE_LABELS: Record<ObjectState, string> = {
  ownerless: 'Бесхозяйное',
  fpo: 'ФПО',
  emergency: 'Аварийное',
  cs_mode: 'Режим ЧС / ПГ',
}

export const CASE_STATUS_LABELS: Record<CaseStatus, string> = {
  draft: 'Черновик',
  in_progress: 'В работе',
  decided: 'Решение принято',
  archived: 'В архиве',
}

export const ASSESSMENT_STATUS_LABELS: Record<AssessmentStatus, string> = {
  draft: 'Заполняется',
  completed: 'Рассчитано',
  approved: 'Утверждено',
}

export const ROLE_LABELS: Record<Role, string> = {
  operator: 'Оператор системы',
  methodologist: 'Методолог',
  specialist: 'Специалист ОМСУ',
  viewer: 'Наблюдатель',
}

export const ESCALATION_STATUS_LABELS: Record<EscalationStatus, string> = {
  open: 'На рассмотрении',
  resolved: 'Рассмотрено',
  rejected: 'Отклонено',
}

type Tone = 'neutral' | 'ok' | 'warn' | 'danger' | 'accent'

const TONE_CLASS: Record<Tone, string> = {
  neutral: '',
  ok: 'badge--ok',
  warn: 'badge--warn',
  danger: 'badge--danger',
  accent: 'badge--accent',
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge ${TONE_CLASS[tone]}`}>{children}</span>
}

export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  const tone: Tone =
    status === 'decided' ? 'ok' : status === 'in_progress' ? 'accent' : 'neutral'
  return <Badge tone={tone}>{CASE_STATUS_LABELS[status]}</Badge>
}

export function AssessmentStatusBadge({ status }: { status: AssessmentStatus }) {
  const tone: Tone = status === 'approved' ? 'ok' : status === 'completed' ? 'accent' : 'neutral'
  return <Badge tone={tone}>{ASSESSMENT_STATUS_LABELS[status]}</Badge>
}

export function Notice({
  tone = 'neutral',
  title,
  children,
}: {
  tone?: Tone
  title?: string
  children?: ReactNode
}) {
  const cls = tone === 'neutral' ? '' : `notice--${tone === 'accent' ? 'ok' : tone}`
  return (
    <div className={`notice ${cls}`}>
      <div>
        {title && <strong>{title}</strong>}
        {title && children ? <br /> : null}
        {children}
      </div>
    </div>
  )
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>
}

export function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatDay(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('ru-RU')
}
