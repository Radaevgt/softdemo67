import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { api } from '../api'
import type { Municipality, Role, User } from '../types'
import { Badge, Empty, Field, Notice, ROLE_LABELS } from '../ui'

export function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [municipalities, setMunicipalities] = useState<Municipality[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<'users' | 'municipalities'>('users')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [loadedUsers, loadedMunicipalities] = await Promise.all([
        api.users(),
        api.municipalities(),
      ])
      setUsers(loadedUsers)
      setMunicipalities(loadedMunicipalities)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить данные')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function toggleUser(user: User) {
    try {
      const updated = await api.updateUser(user.id, { is_active: !user.is_active })
      setUsers((current) => current.map((item) => (item.id === user.id ? updated : item)))
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось изменить учётную запись')
    }
  }

  return (
    <div className="page stack">
      <div className="page__head">
        <div>
          <h1>Пользователи и муниципалитеты</h1>
          <p>Доступ к порталу выдаёт оператор системы.</p>
        </div>
        <div className="page__actions">
          <button
            className={`btn ${tab === 'users' ? 'btn--primary' : ''}`}
            onClick={() => setTab('users')}
          >
            Учётные записи
          </button>
          <button
            className={`btn ${tab === 'municipalities' ? 'btn--primary' : ''}`}
            onClick={() => setTab('municipalities')}
          >
            Муниципалитеты
          </button>
        </div>
      </div>

      {error && <Notice tone="danger">{error}</Notice>}

      {tab === 'users' ? (
        <>
          <div className="card">
            <div className="card__head"><h2>Новая учётная запись</h2></div>
            <div className="card__body">
              <NewUserForm municipalities={municipalities} onCreated={load} />
            </div>
          </div>

          <div className="card">
            <div className="card__head"><h2>Учётные записи</h2></div>
            {loading ? (
              <Empty>Загружаем…</Empty>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ФИО</th>
                      <th>Логин</th>
                      <th>Роль</th>
                      <th>Муниципалитет</th>
                      <th>Статус</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((user) => (
                      <tr key={user.id}>
                        <td>
                          {user.full_name}
                          {user.position && (
                            <div style={{ color: 'var(--ink-faint)', fontSize: 12 }}>
                              {user.position}
                            </div>
                          )}
                        </td>
                        <td className="mono">{user.login}</td>
                        <td>{ROLE_LABELS[user.role]}</td>
                        <td>{user.municipality?.name ?? '— все —'}</td>
                        <td>
                          {user.is_active ? (
                            <Badge tone="ok">активна</Badge>
                          ) : (
                            <Badge tone="danger">заблокирована</Badge>
                          )}
                        </td>
                        <td>
                          <button className="btn btn--small" onClick={() => toggleUser(user)}>
                            {user.is_active ? 'Заблокировать' : 'Разблокировать'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      ) : (
        <MunicipalitiesTab municipalities={municipalities} onChanged={load} loading={loading} />
      )}
    </div>
  )
}

function NewUserForm({
  municipalities,
  onCreated,
}: {
  municipalities: Municipality[]
  onCreated: () => void
}) {
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [position, setPosition] = useState('')
  const [role, setRole] = useState<Role>('specialist')
  const [municipalityId, setMunicipalityId] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  const needsMunicipality = role === 'specialist' || role === 'viewer'

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setDone(false)
    try {
      await api.createUser({
        login: login.trim(),
        password,
        full_name: fullName.trim(),
        position: position.trim() || undefined,
        role,
        municipality_id: municipalityId || undefined,
      })
      setLogin('')
      setPassword('')
      setFullName('')
      setPosition('')
      setDone(true)
      onCreated()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось создать учётную запись')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="stack" onSubmit={submit}>
      <div className="grid-2">
        <Field label="ФИО">
          <input type="text" value={fullName} onChange={(e) => setFullName(e.target.value)} required />
        </Field>
        <Field label="Должность">
          <input type="text" value={position} onChange={(e) => setPosition(e.target.value)} />
        </Field>
        <Field label="Логин">
          <input type="text" value={login} onChange={(e) => setLogin(e.target.value)} required minLength={3} />
        </Field>
        <Field label="Пароль" hint="Не менее 8 символов">
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoComplete="new-password"
          />
        </Field>
        <Field label="Роль">
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {Object.entries(ROLE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </Field>
        <Field
          label="Муниципальное образование"
          hint={needsMunicipality ? 'Обязательно для этой роли' : 'Методолог и оператор работают со всеми МО'}
        >
          <select
            value={municipalityId}
            onChange={(e) => setMunicipalityId(e.target.value)}
            required={needsMunicipality}
          >
            <option value="">— не выбрано —</option>
            {municipalities.map((item) => (
              <option key={item.id} value={item.id}>{item.name}</option>
            ))}
          </select>
        </Field>
      </div>

      {error && <Notice tone="danger">{error}</Notice>}
      {done && <Notice tone="ok">Учётная запись создана.</Notice>}

      <div className="row">
        <button className="btn btn--primary" type="submit" disabled={busy}>
          {busy ? 'Сохраняем…' : 'Создать'}
        </button>
      </div>
    </form>
  )
}

function MunicipalitiesTab({
  municipalities,
  onChanged,
  loading,
}: {
  municipalities: Municipality[]
  onChanged: () => void
  loading: boolean
}) {
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.createMunicipality({ name: name.trim(), code: code.trim() || undefined })
      setName('')
      setCode('')
      onChanged()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось создать')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="card">
        <div className="card__head"><h2>Новое муниципальное образование</h2></div>
        <div className="card__body">
          <form className="stack" onSubmit={submit}>
            <div className="grid-2">
              <Field label="Наименование">
                <input type="text" value={name} onChange={(e) => setName(e.target.value)} required />
              </Field>
              <Field label="Код">
                <input type="text" value={code} onChange={(e) => setCode(e.target.value)} />
              </Field>
            </div>
            {error && <Notice tone="danger">{error}</Notice>}
            <div className="row">
              <button className="btn btn--primary" type="submit" disabled={busy}>Создать</button>
            </div>
          </form>
        </div>
      </div>

      <div className="card">
        <div className="card__head"><h2>Муниципальные образования</h2></div>
        {loading ? (
          <Empty>Загружаем…</Empty>
        ) : municipalities.length === 0 ? (
          <Empty>Ничего не заведено.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Наименование</th><th>Код</th></tr>
              </thead>
              <tbody>
                {municipalities.map((item) => (
                  <tr key={item.id}>
                    <td>{item.name}</td>
                    <td className="mono">{item.code ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
