import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api'
import { useAuth } from '../auth'
import type { Escalation } from '../types'
import {
  Badge,
  Empty,
  ESCALATION_STATUS_LABELS,
  Notice,
  OBJECT_KIND_LABELS,
  STATE_LABELS,
  formatDate,
} from '../ui'

export function EscalationsPage() {
  const { can } = useAuth()
  const [items, setItems] = useState<Escalation[]>([])
  const [filter, setFilter] = useState('open')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await api.escalations(filter || undefined))
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить обращения')
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="page stack">
      <div className="page__head">
        <div>
          <h1>Обращения к методологу</h1>
          <p>Случаи, для которых в матрице ТЗ нет описанного сценария.</p>
        </div>
        <div className="page__actions">
          <select value={filter} onChange={(event) => setFilter(event.target.value)}>
            <option value="">Все</option>
            <option value="open">На рассмотрении</option>
            <option value="resolved">Рассмотренные</option>
            <option value="rejected">Отклонённые</option>
          </select>
        </div>
      </div>

      {error && <Notice tone="danger">{error}</Notice>}

      {loading ? (
        <Empty>Загружаем…</Empty>
      ) : items.length === 0 ? (
        <div className="card"><Empty>Обращений нет.</Empty></div>
      ) : (
        items.map((item) => (
          <EscalationCard
            key={item.id}
            escalation={item}
            canResolve={can('methodologist', 'operator')}
            onResolved={load}
          />
        ))
      )}
    </div>
  )
}

function EscalationCard({
  escalation,
  canResolve,
  onResolved,
}: {
  escalation: Escalation
  canResolve: boolean
  onResolved: () => void
}) {
  const [resolution, setResolution] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function resolve(status: 'resolved' | 'rejected') {
    setBusy(true)
    setError(null)
    try {
      await api.resolveEscalation(escalation.id, { status, resolution: resolution.trim() })
      onResolved()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  const tone =
    escalation.status === 'open' ? 'warn' : escalation.status === 'resolved' ? 'ok' : 'danger'

  return (
    <div className="card">
      <div className="card__head">
        <h2>{escalation.created_by.full_name}</h2>
        <Badge tone={tone}>{ESCALATION_STATUS_LABELS[escalation.status]}</Badge>
        <span style={{ color: 'var(--ink-faint)', fontSize: 13 }}>
          {formatDate(escalation.created_at)}
        </span>
      </div>

      <div className="card__body stack stack--tight">
        <div className="row">
          <Badge tone="accent">{OBJECT_KIND_LABELS[escalation.inputs.object_kind]}</Badge>
          {escalation.inputs.states.map((state) => (
            <Badge key={state}>{STATE_LABELS[state]}</Badge>
          ))}
          <Link to={`/cases/${escalation.case_id}`}>Карточка объекта →</Link>
        </div>

        {escalation.comment && <p>{escalation.comment}</p>}

        {escalation.inputs.decision && (
          <div className="answered-list">
            {escalation.inputs.decision.answer_breakdown.map((item) => (
              <div key={item.key}>
                <span>{item.label}</span>
                <b>{item.value_label}</b>
              </div>
            ))}
          </div>
        )}

        {escalation.status !== 'open' ? (
          <Notice tone={escalation.status === 'resolved' ? 'ok' : 'danger'} title="Итог">
            {escalation.resolution} — {escalation.resolved_by?.full_name},{' '}
            {formatDate(escalation.resolved_at)}
          </Notice>
        ) : canResolve ? (
          <div className="stack stack--tight">
            <textarea
              placeholder="Итог рассмотрения: какое правило добавлено или почему случай отклонён"
              value={resolution}
              onChange={(event) => setResolution(event.target.value)}
            />
            {error && <Notice tone="danger">{error}</Notice>}
            <div className="row">
              <button
                className="btn btn--primary"
                disabled={busy || !resolution.trim()}
                onClick={() => resolve('resolved')}
              >
                Рассмотрено
              </button>
              <button
                className="btn btn--danger"
                disabled={busy || !resolution.trim()}
                onClick={() => resolve('rejected')}
              >
                Отклонить
              </button>
              <Link className="btn btn--small" to="/admin/rules">
                Открыть матрицу правил
              </Link>
            </div>
          </div>
        ) : (
          <Notice>Обращение ожидает рассмотрения методологом.</Notice>
        )}
      </div>
    </div>
  )
}
