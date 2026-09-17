import { useCallback, useEffect, useState } from 'react'

import { api } from '../api'
import type { AuditEntry } from '../types'
import { Badge, Empty, Notice, formatDate } from '../ui'

const ACTION_LABELS: Record<string, string> = {
  'login.success': 'Вход выполнен',
  'login.failed': 'Неудачный вход',
  'case.create': 'Заведено дело',
  'case.update': 'Изменено дело',
  'case.delete': 'Удалено дело',
  'assessment.create': 'Начата проверка',
  'assessment.decide': 'Рассчитано решение',
  'assessment.approve': 'Утверждено решение',
  'roadmap.build': 'Сформирована дорожная карта',
  'rule.create': 'Добавлено правило',
  'rule.update': 'Изменено правило',
  'rule.resync': 'Перезалита матрица ТЗ',
  'user.create': 'Создана учётная запись',
  'user.update': 'Изменена учётная запись',
  'municipality.create': 'Создан муниципалитет',
  'escalation.create': 'Создано обращение',
  'escalation.resolve': 'Рассмотрено обращение',
}

export function AdminAuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [action, setAction] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setEntries(await api.audit(action || undefined))
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить журнал')
    } finally {
      setLoading(false)
    }
  }, [action])

  useEffect(() => {
    void load()
  }, [load])

  return (
    <div className="page stack">
      <div className="page__head">
        <div>
          <h1>Журнал действий</h1>
          <p>Кто выполнил проверку и сформировал решение — требование ответа № 2 брифа.</p>
        </div>
        <div className="page__actions">
          <select value={action} onChange={(event) => setAction(event.target.value)}>
            <option value="">Все действия</option>
            {Object.entries(ACTION_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </div>
      </div>

      {error && <Notice tone="danger">{error}</Notice>}

      <div className="card">
        {loading ? (
          <Empty>Загружаем…</Empty>
        ) : entries.length === 0 ? (
          <Empty>Записей нет.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Время</th>
                  <th>Пользователь</th>
                  <th>Действие</th>
                  <th>Объект</th>
                  <th>Детали</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id}>
                    <td style={{ whiteSpace: 'nowrap' }}>{formatDate(entry.created_at)}</td>
                    <td className="mono">{entry.actor_login ?? '—'}</td>
                    <td>
                      {entry.action === 'login.failed' ? (
                        <Badge tone="danger">{ACTION_LABELS[entry.action]}</Badge>
                      ) : (
                        ACTION_LABELS[entry.action] ?? entry.action
                      )}
                    </td>
                    <td className="mono" style={{ fontSize: 11 }}>
                      {entry.entity_id ? `${entry.entity_type}:${entry.entity_id.slice(0, 8)}` : '—'}
                    </td>
                    <td className="mono" style={{ fontSize: 11, maxWidth: 320, overflowWrap: 'anywhere' }}>
                      {entry.payload ? JSON.stringify(entry.payload) : '—'}
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
