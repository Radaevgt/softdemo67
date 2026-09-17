import { useState, type FormEvent } from 'react'

import { useAuth } from '../auth'
import { Field, Notice } from '../ui'

export function LoginPage() {
  const { signIn } = useAuth()
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await signIn(login.trim(), password)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось войти')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login">
      <div className="card">
        <div className="card__body">
          <h1 className="login__title">Вход в портал</h1>
          <p className="login__sub">
            Работа с выявленными неиспользуемыми объектами капитального строительства
          </p>

          <form className="stack" onSubmit={submit}>
            <Field label="Логин">
              <input
                type="text"
                value={login}
                onChange={(event) => setLogin(event.target.value)}
                autoComplete="username"
                autoFocus
                required
              />
            </Field>

            <Field label="Пароль">
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </Field>

            {error && <Notice tone="danger">{error}</Notice>}

            <button className="btn btn--primary" type="submit" disabled={busy}>
              {busy ? 'Проверяем…' : 'Войти'}
            </button>

            <p style={{ color: 'var(--ink-faint)', fontSize: 12 }}>
              Доступ выдаёт оператор системы. Если учётной записи нет — обратитесь к нему.
            </p>
          </form>
        </div>
      </div>
    </div>
  )
}
