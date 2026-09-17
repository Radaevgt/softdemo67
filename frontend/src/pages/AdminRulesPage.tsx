import { useCallback, useEffect, useMemo, useState } from 'react'

import { api } from '../api'
import type {
  AnswerValue,
  CoverageCell,
  Method,
  ObjectKind,
  ObjectState,
  Question,
  Rule,
} from '../types'
import {
  Badge,
  Empty,
  Field,
  Notice,
  OBJECT_KIND_LABELS,
  STATE_LABELS,
} from '../ui'

export function AdminRulesPage() {
  const [rules, setRules] = useState<Rule[]>([])
  const [coverage, setCoverage] = useState<CoverageCell[]>([])
  const [methods, setMethods] = useState<(Method & { family: string })[]>([])
  const [attributes, setAttributes] = useState<Question[]>([])
  const [ruleValueLabels, setRuleValueLabels] = useState<Record<string, Record<string, string>>>({})
  const [kind, setKind] = useState<ObjectKind>('izhs')
  const [state, setState] = useState<ObjectState>('ownerless')
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [adding, setAdding] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [loadedRules, loadedCoverage, loadedMethods, dictionaries] = await Promise.all([
        api.rules({ object_kind: kind, state }),
        api.coverage(),
        api.methods(),
        api.dictionaries(),
      ])
      setRules(loadedRules)
      setCoverage(loadedCoverage)
      setMethods(loadedMethods)
      setAttributes(dictionaries.attributes)
      setRuleValueLabels(dictionaries.rule_value_labels)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось загрузить матрицу')
    } finally {
      setLoading(false)
    }
  }, [kind, state])

  useEffect(() => {
    void load()
  }, [load])

  async function toggleRule(rule: Rule) {
    try {
      const updated = await api.updateRule(rule.id, { is_active: !rule.is_active })
      setRules((current) => current.map((item) => (item.id === rule.id ? updated : item)))
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось изменить правило')
    }
  }

  const labelFor = useMemo(() => {
    const index = new Map(attributes.map((attr) => [attr.key, attr]))
    return (key: string, value: AnswerValue) => {
      const attr = index.get(key)
      const option = attr?.options.find((item) => item.value === value)
      // Правила ТЗ используют значения, недоступные для ответа сотрудника
      // (объединённый статус «умер/ликвидировано») — их подписи приходят отдельно.
      const extra = ruleValueLabels[key]?.[String(value)]
      return { label: attr?.label ?? key, value: option?.label ?? extra ?? String(value) }
    }
  }, [attributes, ruleValueLabels])

  return (
    <div className="page stack">
      <div className="page__head">
        <div>
          <h1>Матрица сценариев</h1>
          <p>
            61 сценарий выгружен из технического задания. Недостающие комбинации закрываются
            правилами методолога — они начинают действовать сразу, без обновления системы.
          </p>
        </div>
      </div>

      {error && <Notice tone="danger">{error}</Notice>}
      {info && <Notice tone="ok">{info}</Notice>}

      <div className="card">
        <div className="card__head"><h2>Покрытие матрицы</h2></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Вид объекта</th>
                <th>Состояние</th>
                <th>Описано сценариев</th>
                <th>Комбинаций признаков</th>
                <th>Покрытие</th>
              </tr>
            </thead>
            <tbody>
              {coverage.map((cell) => {
                const covered = cell.combinations - cell.gaps
                const percent = Math.round((covered / cell.combinations) * 100)
                return (
                  <tr key={`${cell.object_kind}.${cell.state}`}>
                    <td>{OBJECT_KIND_LABELS[cell.object_kind]}</td>
                    <td>{STATE_LABELS[cell.state]}</td>
                    <td>{cell.described}</td>
                    <td>{cell.combinations}</td>
                    <td>
                      <div className="meter">
                        <span style={{ width: `${percent}%` }} />
                        <b>{covered} из {cell.combinations}</b>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <div className="card__head">
          <h2>Правила</h2>
          <select value={kind} onChange={(e) => setKind(e.target.value as ObjectKind)} style={{ width: 'auto' }}>
            {Object.entries(OBJECT_KIND_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <select value={state} onChange={(e) => setState(e.target.value as ObjectState)} style={{ width: 'auto' }}>
            {Object.entries(STATE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
          <button className="btn btn--primary btn--small" onClick={() => setAdding((v) => !v)}>
            {adding ? 'Отменить' : 'Добавить правило'}
          </button>
        </div>

        {adding && (
          <div className="card__body" style={{ borderBottom: '1px solid var(--line)' }}>
            <NewRuleForm
              objectKind={kind}
              state={state}
              attributes={attributes}
              methods={methods}
              onCancel={() => setAdding(false)}
              onCreated={(created) => {
                setAdding(false)
                setInfo(`Правило ${created.code} добавлено и уже действует`)
                void load()
              }}
            />
          </div>
        )}

        {loading ? (
          <Empty>Загружаем…</Empty>
        ) : rules.length === 0 ? (
          <Empty>Для этой связки правил нет.</Empty>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Код</th>
                  <th>Условия</th>
                  <th>Способы</th>
                  <th>Происхождение</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id} style={{ opacity: rule.is_active ? 1 : 0.5 }}>
                    <td className="mono">{rule.code}</td>
                    <td>
                      <div className="stack stack--tight">
                        {Object.entries(rule.conditions).map(([key, value]) => {
                          const described = labelFor(key, value)
                          return (
                            <div key={key} style={{ fontSize: 12 }}>
                              {described.label}: <b>{described.value}</b>
                            </div>
                          )
                        })}
                      </div>
                    </td>
                    <td>
                      <div className="stack stack--tight">
                        {rule.method_codes.map((code) => (
                          <div key={code} style={{ fontSize: 12 }}>
                            {methods.find((method) => method.code === code)?.title ?? code}
                          </div>
                        ))}
                      </div>
                    </td>
                    <td>
                      {rule.is_builtin ? (
                        <Badge>из ТЗ</Badge>
                      ) : (
                        <Badge tone="accent">методолог</Badge>
                      )}
                    </td>
                    <td>
                      <button className="btn btn--small" onClick={() => toggleRule(rule)}>
                        {rule.is_active ? 'Отключить' : 'Включить'}
                      </button>
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

function NewRuleForm({
  objectKind,
  state,
  attributes,
  methods,
  onCancel,
  onCreated,
}: {
  objectKind: ObjectKind
  state: ObjectState
  attributes: Question[]
  methods: Method[]
  onCancel: () => void
  onCreated: (rule: Rule) => void
}) {
  const [conditions, setConditions] = useState<Record<string, AnswerValue>>({})
  const [selectedMethods, setSelectedMethods] = useState<string[]>([])
  const [source, setSource] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Применимость признаков повторяет логику опроса: наследники спрашиваются
  // только при неживом правообладателе, прописка — не для нежилого объекта.
  const applicable = attributes.filter((attr) => {
    if (attr.key === 'registered_citizens') return objectKind !== 'nonresidential'
    if (attr.key === 'heirs') {
      const status = conditions.owner_status
      return typeof status === 'string' && status !== 'alive'
    }
    return true
  })

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const applicableKeys = new Set(applicable.map((attr) => attr.key))
      const payload = Object.fromEntries(
        Object.entries(conditions).filter(([key]) => applicableKeys.has(key)),
      )
      onCreated(
        await api.createRule({
          object_kind: objectKind,
          state,
          conditions: payload,
          method_codes: selectedMethods,
          source: source.trim() || undefined,
        }),
      )
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Не удалось сохранить правило')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <Notice>
        Новое правило для связки «{OBJECT_KIND_LABELS[objectKind]} / {STATE_LABELS[state]}».
        Заполните все применимые признаки — частичное правило система не примет.
      </Notice>

      {applicable.map((attr) => (
        <div key={attr.key} className="field">
          <label>{attr.label}</label>
          <div className="choice">
            {attr.options.map((option) => (
              <button
                key={String(option.value)}
                type="button"
                aria-pressed={conditions[attr.key] === option.value}
                onClick={() =>
                  setConditions((current) => ({ ...current, [attr.key]: option.value }))
                }
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
      ))}

      <div className="field">
        <label>Способы оформления</label>
        <div className="stack stack--tight">
          {methods.map((method) => (
            <label key={method.code} className="row" style={{ alignItems: 'flex-start' }}>
              <input
                type="checkbox"
                checked={selectedMethods.includes(method.code)}
                onChange={() =>
                  setSelectedMethods((current) =>
                    current.includes(method.code)
                      ? current.filter((code) => code !== method.code)
                      : [...current, method.code],
                  )
                }
              />
              <span style={{ flex: 1 }}>
                {method.title}
                <span className="mono" style={{ color: 'var(--ink-faint)', marginLeft: 6 }}>
                  {method.code} · шагов: {method.steps.length}
                </span>
              </span>
            </label>
          ))}
        </div>
      </div>

      <Field label="Основание" hint="Например: решение методического совета от 17.09.2026">
        <input type="text" value={source} onChange={(event) => setSource(event.target.value)} />
      </Field>

      {error && <Notice tone="danger">{error}</Notice>}

      <div className="row">
        <button
          className="btn btn--primary"
          disabled={busy || selectedMethods.length === 0}
          onClick={submit}
        >
          Сохранить правило
        </button>
        <button className="btn" onClick={onCancel}>Отмена</button>
      </div>
    </div>
  )
}
