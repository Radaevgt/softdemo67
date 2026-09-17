import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api } from '../api'
import { useAuth } from '../auth'
import type { ObjectCase, ObjectKind, ObjectState } from '../types'
import {
  Badge,
  CaseStatusBadge,
  Empty,
  Field,
  Notice,
  OBJECT_KIND_LABELS,
  STATE_LABELS,
  formatDate,
} from '../ui'

const ALL_STATES: ObjectState[] = ['ownerless', 'fpo', 'emergency', 'cs_mode']
const PAGE_SIZE = 50

export function CasesPage() {
  const { can } = useAuth()
  const navigate = useNavigate()

  const [cases, setCases] = useState<ObjectCase[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)

  const [search, setSearch] = useState('')
  const [kindFilter, setKindFilter] = useState('')
  const [stateFilter, setStateFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await api.cases({
        search: search.trim() || undefined,
        object_kind: kindFilter || undefined,
        state: stateFilter || undefined,
        case_status: statusFilter || undefined,
        limit: String(PAGE_SIZE),
        offset: String(page * PAGE_SIZE),
      })
      setCases(data.items)
      setTotal(data.total)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить реестр')
    } finally {
      setLoading(false)
    }
  }, [search, kindFilter, stateFilter, statusFilter, page])

  // Смена условий отбора возвращает на первую страницу, иначе список окажется
  // пустым из-за смещения, оставшегося от прежней выборки.
  useEffect(() => {
    setPage(0)
  }, [search, kindFilter, stateFilter, statusFilter])

  useEffect(() => {
    const timer = setTimeout(load, search ? 300 : 0)
    return () => clearTimeout(timer)
  }, [load, search])

  return (
    <div className="page">
      <div className="page__head">
        <div>
          <h1>Реестр объектов</h1>
          <p>
            Найдено дел: {total}. Определение способа оформления права муниципальной
            собственности или понуждения к сносу.
          </p>
        </div>
        {can('specialist', 'operator') && (
          <div className="page__actions">
            <button className="btn btn--primary" onClick={() => setCreating((value) => !value)}>
              {creating ? 'Отменить' : 'Завести дело'}
            </button>
          </div>
        )}
      </div>

      {creating && (
        <div className="card" style={{ marginBottom: 'var(--space-4)' }}>
          <div className="card__head">
            <h2>Новый объект</h2>
          </div>
          <div className="card__body">
            <NewCaseForm
              onCancel={() => setCreating(false)}
              onCreated={(created) => navigate(`/cases/${created.id}`)}
            />
          </div>
        </div>
      )}

      <div className="card">
        <div className="card__head">
          <input
            type="text"
            placeholder="Поиск по адресу или кадастровому номеру"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            style={{ maxWidth: 320 }}
          />
          <select value={kindFilter} onChange={(e) => setKindFilter(e.target.value)} style={{ width: 'auto' }}>
            <option value="">Все виды</option>
            {Object.entries(OBJECT_KIND_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select value={stateFilter} onChange={(e) => setStateFilter(e.target.value)} style={{ width: 'auto' }}>
            <option value="">Все состояния</option>
            {ALL_STATES.map((state) => (
              <option key={state} value={state}>{STATE_LABELS[state]}</option>
            ))}
          </select>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} style={{ width: 'auto' }}>
            <option value="">Все статусы</option>
            <option value="draft">Черновик</option>
            <option value="in_progress">В работе</option>
            <option value="decided">Решение принято</option>
            <option value="archived">В архиве</option>
          </select>
        </div>

        {error && <div className="card__body"><Notice tone="danger">{error}</Notice></div>}

        {loading ? (
          <Empty>Загружаем…</Empty>
        ) : cases.length === 0 ? (
          <Empty>
            Дел не найдено.
            {can('specialist', 'operator') && ' Заведите первое дело, чтобы начать проверку.'}
          </Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Адрес</th>
                  <th>Кадастровый номер</th>
                  <th>Вид</th>
                  <th>Состояние</th>
                  <th>Статус</th>
                  <th>Изменено</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <Link to={`/cases/${item.id}`}>{item.address}</Link>
                      <div style={{ color: 'var(--ink-faint)', fontSize: 12 }}>
                        {item.municipality.name}
                      </div>
                    </td>
                    <td className="mono">{item.cadastral_number_oks ?? '—'}</td>
                    <td>{OBJECT_KIND_LABELS[item.object_kind]}</td>
                    <td>
                      <div className="row">
                        {item.states.length === 0 ? (
                          <Badge tone="warn">не указано</Badge>
                        ) : (
                          item.states.map((state) => (
                            <Badge key={state}>{STATE_LABELS[state]}</Badge>
                          ))
                        )}
                      </div>
                    </td>
                    <td><CaseStatusBadge status={item.status} /></td>
                    <td style={{ whiteSpace: 'nowrap' }}>{formatDate(item.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {total > PAGE_SIZE && (
          <div className="card__head" style={{ borderTop: '1px solid var(--line)', borderBottom: 0 }}>
            <span style={{ color: 'var(--ink-soft)' }}>
              Показаны {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} из {total}
            </span>
            <div className="row" style={{ marginLeft: 'auto' }}>
              <button
                className="btn btn--small"
                disabled={page === 0}
                onClick={() => setPage((value) => value - 1)}
              >
                Назад
              </button>
              <button
                className="btn btn--small"
                disabled={(page + 1) * PAGE_SIZE >= total}
                onClick={() => setPage((value) => value + 1)}
              >
                Вперёд
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function NewCaseForm({
  onCancel,
  onCreated,
}: {
  onCancel: () => void
  onCreated: (created: ObjectCase) => void
}) {
  const [address, setAddress] = useState('')
  const [kind, setKind] = useState<ObjectKind>('izhs')
  const [states, setStates] = useState<ObjectState[]>([])
  const [oks, setOks] = useState('')
  const [land, setLand] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  function toggleState(state: ObjectState) {
    setStates((current) =>
      current.includes(state) ? current.filter((item) => item !== state) : [...current, state],
    )
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onCreated(
        await api.createCase({
          address: address.trim(),
          object_kind: kind,
          states,
          cadastral_number_oks: oks.trim() || undefined,
          cadastral_number_land: land.trim() || undefined,
          notes: notes.trim() || undefined,
        }),
      )
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось создать дело')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <Field label="Адрес объекта">
        <input type="text" value={address} onChange={(e) => setAddress(e.target.value)} required />
      </Field>

      <div className="grid-2">
        <Field label="Кадастровый номер ОКС" hint="Определяется на этапе 2, например 52:18:0000000:123">
          <input type="text" value={oks} onChange={(e) => setOks(e.target.value)} />
        </Field>
        <Field label="Кадастровый номер земельного участка">
          <input type="text" value={land} onChange={(e) => setLand(e.target.value)} />
        </Field>
      </div>

      <Field label="Вид объекта">
        <select value={kind} onChange={(e) => setKind(e.target.value as ObjectKind)}>
          {Object.entries(OBJECT_KIND_LABELS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </Field>

      <div className="field">
        <label>Состояние объекта (установлено при обследовании)</label>
        <div className="choice">
          {ALL_STATES.map((state) => (
            <button
              key={state}
              type="button"
              aria-pressed={states.includes(state)}
              onClick={() => toggleState(state)}
            >
              {STATE_LABELS[state]}
            </button>
          ))}
        </div>
        <small>
          Можно выбрать несколько: объект бывает одновременно бесхозяйным и ФПО. Порядок
          действий будет предложен по каждому состоянию.
        </small>
      </div>

      <Field label="Примечание">
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} />
      </Field>

      {error && <Notice tone="danger">{error}</Notice>}

      <div className="row">
        <button className="btn btn--primary" type="submit" disabled={busy}>
          {busy ? 'Сохраняем…' : 'Создать'}
        </button>
        <button className="btn" type="button" onClick={onCancel}>Отмена</button>
      </div>
    </form>
  )
}
