import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { api } from '../api'
import { useAuth } from '../auth'
import type { Assessment, ObjectCase, ObjectState } from '../types'
import {
  AssessmentStatusBadge,
  Badge,
  CaseStatusBadge,
  Empty,
  Notice,
  OBJECT_KIND_LABELS,
  STATE_LABELS,
  formatDate,
} from '../ui'

const ALL_STATES: ObjectState[] = ['ownerless', 'fpo', 'emergency', 'cs_mode']

export function CasePage() {
  const { caseId = '' } = useParams()
  const navigate = useNavigate()
  const { can } = useAuth()

  const [objectCase, setObjectCase] = useState<ObjectCase | null>(null)
  const [assessments, setAssessments] = useState<Assessment[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [editingStates, setEditingStates] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [loadedCase, loadedAssessments] = await Promise.all([
        api.case(caseId),
        api.assessments(caseId),
      ])
      setObjectCase(loadedCase)
      setAssessments(loadedAssessments)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Дело не найдено')
    } finally {
      setLoading(false)
    }
  }, [caseId])

  useEffect(() => {
    void load()
  }, [load])

  async function startAssessment() {
    try {
      const assessment = await api.startAssessment(caseId)
      navigate(`/assessments/${assessment.id}`)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось начать проверку')
    }
  }

  async function saveStates(states: ObjectState[]) {
    try {
      setObjectCase(await api.updateCase(caseId, { states }))
      setEditingStates(false)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось сохранить')
    }
  }

  if (loading) return <div className="page"><Empty>Загружаем…</Empty></div>
  if (!objectCase) {
    return (
      <div className="page">
        <Notice tone="danger" title="Дело недоступно">{error}</Notice>
      </div>
    )
  }

  const editable = can('specialist', 'operator')
  const approved = assessments.find((item) => item.status === 'approved')

  return (
    <div className="page stack">
      <div className="page__head">
        <div>
          <Link to="/cases" style={{ fontSize: 13 }}>← Реестр объектов</Link>
          <h1 style={{ marginTop: 4 }}>{objectCase.address}</h1>
          <p>
            {objectCase.municipality.name} · заведено {formatDate(objectCase.created_at)} ·{' '}
            {objectCase.created_by.full_name}
          </p>
        </div>
        <div className="page__actions">
          <CaseStatusBadge status={objectCase.status} />
          {editable && (
            <button className="btn btn--primary" onClick={startAssessment}>
              {assessments.some((item) => item.status === 'draft')
                ? 'Продолжить проверку'
                : 'Начать проверку'}
            </button>
          )}
        </div>
      </div>

      {error && <Notice tone="danger">{error}</Notice>}

      <div className="card">
        <div className="card__head"><h2>Сведения об объекте</h2></div>
        <div className="card__body stack">
          <div className="grid-2">
            <Detail label="Вид объекта" value={OBJECT_KIND_LABELS[objectCase.object_kind]} />
            <Detail label="Кадастровый номер ОКС" value={objectCase.cadastral_number_oks} mono />
            <Detail label="Кадастровый номер ЗУ" value={objectCase.cadastral_number_land} mono />
            <Detail label="Примечание" value={objectCase.notes} />
          </div>

          <div className="field">
            <label>Состояние объекта</label>
            {editingStates ? (
              <StatesEditor
                initial={objectCase.states}
                onCancel={() => setEditingStates(false)}
                onSave={saveStates}
              />
            ) : (
              <div className="row">
                {objectCase.states.length === 0 ? (
                  <Badge tone="warn">не указано — проверка невозможна</Badge>
                ) : (
                  objectCase.states.map((state) => (
                    <Badge key={state} tone="accent">{STATE_LABELS[state]}</Badge>
                  ))
                )}
                {editable && (
                  <button className="btn btn--small" onClick={() => setEditingStates(true)}>
                    Изменить
                  </button>
                )}
              </div>
            )}
            <small>
              Состояние определяется при обследовании и служит обязательным входом: один и тот
              же набор правовых признаков приводит к разным способам в разных состояниях.
            </small>
          </div>
        </div>
      </div>

      {approved && (
        <Notice tone="ok" title="По объекту есть утверждённое решение">
          Проверку утвердил {approved.approved_by?.full_name} — {formatDate(approved.approved_at)}.
          Отпечаток решения: <span className="mono">{approved.content_hash?.slice(0, 16)}…</span>
        </Notice>
      )}

      <div className="card">
        <div className="card__head"><h2>История проверок</h2></div>
        {assessments.length === 0 ? (
          <Empty>Проверок ещё не было.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Автор</th>
                  <th>Статус</th>
                  <th>Результат</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {assessments.map((item) => (
                  <tr key={item.id}>
                    <td style={{ whiteSpace: 'nowrap' }}>{formatDate(item.created_at)}</td>
                    <td>{item.author.full_name}</td>
                    <td><AssessmentStatusBadge status={item.status} /></td>
                    <td>
                      {!item.decision ? (
                        '—'
                      ) : item.decision.needs_review ? (
                        <Badge tone="warn">требует решения методолога</Badge>
                      ) : (
                        <div className="stack stack--tight">
                          {item.decision.outcomes.map((outcome) => (
                            <div key={outcome.state}>
                              <Badge>{outcome.state_label}</Badge>{' '}
                              {outcome.methods.map((method) => method.title).join('; ')}
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      <Link className="btn btn--small" to={`/assessments/${item.id}`}>
                        Открыть
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

function Detail({
  label,
  value,
  mono,
}: {
  label: string
  value: string | null
  mono?: boolean
}) {
  return (
    <div className="field">
      <label>{label}</label>
      <div className={mono ? 'mono' : undefined}>{value || '—'}</div>
    </div>
  )
}

function StatesEditor({
  initial,
  onSave,
  onCancel,
}: {
  initial: ObjectState[]
  onSave: (states: ObjectState[]) => void
  onCancel: () => void
}) {
  const [states, setStates] = useState<ObjectState[]>(initial)

  return (
    <div className="stack stack--tight">
      <div className="choice">
        {ALL_STATES.map((state) => (
          <button
            key={state}
            type="button"
            aria-pressed={states.includes(state)}
            onClick={() =>
              setStates((current) =>
                current.includes(state)
                  ? current.filter((item) => item !== state)
                  : [...current, state],
              )
            }
          >
            {STATE_LABELS[state]}
          </button>
        ))}
      </div>
      <div className="row">
        <button className="btn btn--primary btn--small" onClick={() => onSave(states)}>
          Сохранить
        </button>
        <button className="btn btn--small" onClick={onCancel}>Отмена</button>
      </div>
    </div>
  )
}
