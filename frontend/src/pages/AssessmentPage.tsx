import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api'
import { useAuth } from '../auth'
import type {
  AnswerValue,
  AssessmentDocument,
  AssessmentProgress,
  Decision,
  DocumentFormat,
  Question,
  RoadmapItem,
  StateOutcome,
} from '../types'
import { Badge, Empty, Notice, formatDate, formatDay } from '../ui'

export function AssessmentPage() {
  const { assessmentId = '' } = useParams()
  const { can } = useAuth()

  const [progress, setProgress] = useState<AssessmentProgress | null>(null)
  const [roadmap, setRoadmap] = useState<RoadmapItem[]>([])
  const [documents, setDocuments] = useState<AssessmentDocument[]>([])
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [loadedProgress, loadedRoadmap, loadedDocuments] = await Promise.all([
        api.assessment(assessmentId),
        api.roadmap(assessmentId),
        api.documents(assessmentId),
      ])
      setProgress(loadedProgress)
      setRoadmap(loadedRoadmap)
      setDocuments(loadedDocuments)
      setError(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Проверка не найдена')
    } finally {
      setLoading(false)
    }
  }, [assessmentId])

  useEffect(() => {
    void load()
  }, [load])

  async function act<T>(action: () => Promise<T>): Promise<T | undefined> {
    setBusy(true)
    setError(null)
    setInfo(null)
    try {
      return await action()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Операция не выполнена')
      return undefined
    } finally {
      setBusy(false)
    }
  }

  const answer = (key: string, value: AnswerValue) =>
    act(async () => setProgress(await api.saveAnswers(assessmentId, { [key]: value })))

  const decide = () =>
    act(async () => {
      await api.decide(assessmentId)
      setProgress(await api.assessment(assessmentId))
    })

  const approve = () =>
    act(async () => {
      await api.approve(assessmentId)
      setProgress(await api.assessment(assessmentId))
      // Утверждение формирует протокол автоматически.
      setDocuments(await api.documents(assessmentId))
    })

  const buildRoadmap = (codes: string[]) =>
    act(async () => setRoadmap(await api.buildRoadmap(assessmentId, codes)))

  const toggleItem = (item: RoadmapItem) =>
    act(async () => {
      const updated = await api.updateRoadmapItem(item.id, {
        status: item.status === 'done' ? 'pending' : 'done',
      })
      setRoadmap((current) => current.map((row) => (row.id === item.id ? updated : row)))
    })

  const generateDocuments = () =>
    act(async () => {
      setDocuments(await api.generateDocuments(assessmentId))
      setInfo('Протокол сформирован и сохранён в системе.')
    })

  const downloadDocument = (item: AssessmentDocument) =>
    act(() => api.downloadDocument(assessmentId, item.format, item.filename))

  const escalate = (comment: string) =>
    act(async () => {
      await api.createEscalation({
        case_id: progress!.assessment.case_id,
        assessment_id: assessmentId,
        comment,
      })
      setInfo('Обращение направлено методологу. Ответ появится в разделе «Обращения».')
    })

  if (loading) return <div className="page"><Empty>Загружаем…</Empty></div>
  if (!progress) {
    return <div className="page"><Notice tone="danger" title="Недоступно">{error}</Notice></div>
  }

  const { assessment, answered, next_question: question, remaining, complete } = progress
  const decision = assessment.decision
  const editable = can('specialist', 'operator') && assessment.status !== 'approved'
  const totalSteps = answered.length + remaining

  return (
    <div className="page stack">
      <div className="page__head">
        <div>
          <Link to={`/cases/${assessment.case_id}`} style={{ fontSize: 13 }}>← Карточка объекта</Link>
          <h1 style={{ marginTop: 4 }}>Проверка объекта</h1>
          <p>
            Автор: {assessment.author.full_name} · начата {formatDate(assessment.created_at)}
          </p>
        </div>
      </div>

      {error && <Notice tone="danger">{error}</Notice>}
      {info && <Notice tone="ok">{info}</Notice>}

      {assessment.status === 'approved' && (
        <Notice tone="ok" title="Решение утверждено">
          {assessment.approved_by?.full_name}, {formatDate(assessment.approved_at)}. Отпечаток:{' '}
          <span className="mono">{assessment.content_hash}</span>. Проверка больше не
          редактируется — для пересмотра создайте новую.
        </Notice>
      )}

      <div className="card">
        <div className="card__head">
          <h2>Признаки объекта</h2>
          <Badge>{answered.length} из {totalSteps}</Badge>
        </div>
        <div className="card__body stack">
          <div className="wizard__progress">
            <span style={{ width: `${totalSteps ? (answered.length / totalSteps) * 100 : 0}%` }} />
          </div>

          {answered.length > 0 && (
            <div className="answered-list">
              {answered.map((item) => (
                <div key={item.key}>
                  <span>{item.label}</span>
                  <b>{item.value_label}</b>
                </div>
              ))}
            </div>
          )}

          {question && editable && (
            <div className="stack stack--tight">
              <div className="wizard__question">{question.label}</div>
              <p style={{ color: 'var(--ink-faint)', fontSize: 13 }}>
                Источник: {question.source_hint}
              </p>
              <div className="choice">
                {question.options.map((option) => (
                  <button
                    key={String(option.value)}
                    type="button"
                    disabled={busy}
                    onClick={() => answer(question.key, option.value)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {complete && editable && (
            <EditAnswers progress={progress} busy={busy} onAnswer={answer} />
          )}

          {complete && editable && !decision && (
            <button className="btn btn--primary" disabled={busy} onClick={decide}>
              Определить способ
            </button>
          )}

          {!editable && !question && assessment.status !== 'approved' && (
            <Notice>Опрос доступен только специалисту своего муниципального образования.</Notice>
          )}
        </div>
      </div>

      {decision && (
        <DecisionView
          decision={decision}
          busy={busy}
          canAct={editable}
          approved={assessment.status === 'approved'}
          roadmap={roadmap}
          documents={documents}
          onApprove={approve}
          onGenerateDocuments={generateDocuments}
          onDownloadDocument={downloadDocument}
          onBuildRoadmap={buildRoadmap}
          onToggleItem={toggleItem}
          onEscalate={escalate}
        />
      )}
    </div>
  )
}

function EditAnswers({
  progress,
  busy,
  onAnswer,
}: {
  progress: AssessmentProgress
  busy: boolean
  onAnswer: (key: string, value: AnswerValue) => void
}) {
  const [open, setOpen] = useState(false)
  const [attributes, setAttributes] = useState<Question[] | null>(null)

  useEffect(() => {
    if (!open || attributes) return
    api.dictionaries().then((data) => setAttributes(data.attributes)).catch(() => setAttributes([]))
  }, [open, attributes])

  const answeredKeys = new Set(progress.answered.map((item) => item.key))

  return (
    <div className="stack stack--tight">
      <button className="btn btn--small" onClick={() => setOpen((value) => !value)}>
        {open ? 'Скрыть правку ответов' : 'Изменить ответы'}
      </button>
      {open && (
        <div className="stack stack--tight">
          {(attributes ?? [])
            .filter((attr) => answeredKeys.has(attr.key))
            .map((attr) => (
              <div key={attr.key} className="field">
                <label>{attr.label}</label>
                <div className="choice">
                  {attr.options.map((option) => (
                    <button
                      key={String(option.value)}
                      type="button"
                      disabled={busy}
                      aria-pressed={progress.assessment.answers[attr.key] === option.value}
                      onClick={() => onAnswer(attr.key, option.value)}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          <small style={{ color: 'var(--ink-faint)' }}>
            Правка ответа сбрасывает ранее рассчитанное решение — его нужно определить заново.
          </small>
        </div>
      )}
    </div>
  )
}

function DecisionView({
  decision,
  busy,
  canAct,
  approved,
  roadmap,
  documents,
  onApprove,
  onGenerateDocuments,
  onDownloadDocument,
  onBuildRoadmap,
  onToggleItem,
  onEscalate,
}: {
  decision: Decision
  busy: boolean
  canAct: boolean
  approved: boolean
  roadmap: RoadmapItem[]
  documents: AssessmentDocument[]
  onApprove: () => void
  onGenerateDocuments: () => void
  onDownloadDocument: (item: AssessmentDocument) => void
  onBuildRoadmap: (codes: string[]) => void
  onToggleItem: (item: RoadmapItem) => void
  onEscalate: (comment: string) => void
}) {
  const [selected, setSelected] = useState<string[]>([])
  const [comment, setComment] = useState('')

  // После пересчёта решения шаги от прежнего способа к делу не относятся.
  // Остаются только те, чей способ предложен текущим решением; если не осталось
  // ни одного, снова показывается форма сборки карты.
  const offeredCodes = new Set(
    decision.outcomes.flatMap((outcome) => outcome.methods).map((method) => method.code),
  )
  const currentRoadmap = roadmap.filter((item) => offeredCodes.has(item.method_code))

  // Один способ приходит из нескольких состояний (у квартиры в МКД совпадают
  // ветки «бесхозяйное» и «аварийное») — в списке он должен быть один.
  const offered = Array.from(
    new Map(
      decision.outcomes.flatMap((outcome) => outcome.methods).map((method) => [method.code, method]),
    ).values(),
  )

  return (
    <>
      {decision.needs_review ? (
        <Notice tone="warn" title="Точного сценария в матрице нет">
          Комбинация признаков не описана в техническом задании. Ниже — ближайшие сценарии с
          указанием расходящихся признаков. Решение нельзя утвердить, пока методолог не
          рассмотрит случай.
        </Notice>
      ) : (
        <Notice tone="ok" title="Сценарий определён">
          Решение выведено из матрицы ТЗ. Версия набора правил:{' '}
          <span className="mono">{decision.ruleset_version}</span>
        </Notice>
      )}

      {decision.outcomes.map((outcome) => (
        <OutcomeCard key={outcome.state} outcome={outcome} />
      ))}

      <div className="card">
        <div className="card__head"><h2>На чём основано решение</h2></div>
        <div className="card__body">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Признак</th>
                  <th>Значение</th>
                  <th>Источник сведений</th>
                </tr>
              </thead>
              <tbody>
                {decision.answer_breakdown.map((item) => (
                  <tr key={item.key}>
                    <td>{item.label}</td>
                    <td><b>{item.value_label}</b></td>
                    <td style={{ color: 'var(--ink-soft)' }}>{item.source_hint}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {decision.needs_review && canAct && (
        <div className="card">
          <div className="card__head"><h2>Передать методологу</h2></div>
          <div className="card__body stack stack--tight">
            <textarea
              placeholder="Опишите ситуацию: что известно об объекте и чем случай отличается от ближайших сценариев"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
            />
            <div className="row">
              <button
                className="btn btn--primary"
                disabled={busy || !comment.trim()}
                onClick={() => onEscalate(comment.trim())}
              >
                Направить обращение
              </button>
            </div>
          </div>
        </div>
      )}

      {!decision.needs_review && canAct && currentRoadmap.length === 0 && (
        <div className="card">
          <div className="card__head"><h2>Сформировать дорожную карту</h2></div>
          <div className="card__body stack stack--tight">
            <p style={{ color: 'var(--ink-soft)' }}>
              Выберите способы, по которым будете работать. Их порядок действий превратится в
              чек-лист поручений.
            </p>
            {offered.map((method) => (
              <label key={method.code} className="row" style={{ alignItems: 'flex-start' }}>
                <input
                  type="checkbox"
                  checked={selected.includes(method.code)}
                  onChange={() =>
                    setSelected((current) =>
                      current.includes(method.code)
                        ? current.filter((code) => code !== method.code)
                        : [...current, method.code],
                    )
                  }
                />
                <span style={{ flex: 1 }}>{method.title}</span>
              </label>
            ))}
            <div className="row">
              <button
                className="btn btn--primary"
                disabled={busy || selected.length === 0}
                onClick={() => onBuildRoadmap(selected)}
              >
                Создать дорожную карту
              </button>
            </div>
          </div>
        </div>
      )}

      {currentRoadmap.length > 0 && (
        <div className="card">
          <div className="card__head">
            <h2>Дорожная карта</h2>
            <Badge tone="accent">
              {currentRoadmap.filter((item) => item.status === 'done').length} из{' '}
              {currentRoadmap.filter((item) => item.kind === 'action').length}
            </Badge>
          </div>
          <div className="card__body roadmap">
            {currentRoadmap.map((item) =>
              item.kind === 'header' ? (
                <div key={item.id} className="roadmap__header">{item.text}</div>
              ) : (
                <div
                  key={item.id}
                  className={`roadmap__item${item.status === 'done' ? ' is-done' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={item.status === 'done'}
                    disabled={busy || !canAct}
                    onChange={() => onToggleItem(item)}
                  />
                  <div>
                    <div className="roadmap__text">{item.text}</div>
                    {(item.due_date || item.completed_at) && (
                      <div className="roadmap__meta">
                        {item.due_date && <Badge>срок {formatDay(item.due_date)}</Badge>}
                        {item.completed_at && (
                          <Badge tone="ok">выполнено {formatDate(item.completed_at)}</Badge>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              ),
            )}
          </div>
        </div>
      )}

      <ProtocolCard
        documents={documents}
        busy={busy}
        canGenerate={canAct}
        approved={approved}
        onGenerate={onGenerateDocuments}
        onDownload={onDownloadDocument}
      />

      {!decision.needs_review && canAct && !approved && (
        <div className="card">
          <div className="card__body row">
            <button className="btn btn--primary" disabled={busy} onClick={onApprove}>
              Утвердить решение
            </button>
            <span style={{ color: 'var(--ink-soft)', fontSize: 13 }}>
              Будут зафиксированы автор, время и отпечаток содержимого. После утверждения
              проверка не редактируется.
            </span>
          </div>
        </div>
      )}
    </>
  )
}

const FORMAT_LABELS: Record<DocumentFormat, string> = {
  docx: 'Word (.docx)',
  pdf: 'PDF',
}

const FORMAT_HINTS: Record<DocumentFormat, string> = {
  docx: 'редактируется и вкладывается в СЭДО',
  pdf: 'для архива и печати',
}

function formatSize(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.round(bytes / 1024)} КБ`
    : `${(bytes / 1024 / 1024).toFixed(1)} МБ`
}

function ProtocolCard({
  documents,
  busy,
  canGenerate,
  approved,
  onGenerate,
  onDownload,
}: {
  documents: AssessmentDocument[]
  busy: boolean
  canGenerate: boolean
  approved: boolean
  onGenerate: () => void
  onDownload: (item: AssessmentDocument) => void
}) {
  return (
    <div className="card">
      <div className="card__head">
        <h2>Протокол проверки</h2>
        {canGenerate && !approved && (
          <button className="btn btn--primary btn--small" disabled={busy} onClick={onGenerate}>
            {documents.length > 0 ? 'Сформировать заново' : 'Сформировать протокол'}
          </button>
        )}
      </div>

      <div className="card__body stack stack--tight">
        {documents.length === 0 ? (
          <p style={{ color: 'var(--ink-soft)' }}>
            Протокол содержит карточку объекта, все ответы опроса с источниками сведений,
            определённый сценарий и порядок действий. Он сохраняется в системе и выгружается
            файлом; при утверждении решения формируется автоматически.
          </p>
        ) : (
          <>
            {approved && (
              <Notice tone="ok">
                Протокол сформирован при утверждении решения и больше не изменяется.
              </Notice>
            )}
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Формат</th>
                    <th>Файл</th>
                    <th>Размер</th>
                    <th>Сформирован</th>
                    <th>Отпечаток файла</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {documents.map((item) => (
                    <tr key={item.id}>
                      <td>
                        {FORMAT_LABELS[item.format]}
                        <div style={{ color: 'var(--ink-faint)', fontSize: 12 }}>
                          {FORMAT_HINTS[item.format]}
                        </div>
                      </td>
                      <td>{item.filename}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>{formatSize(item.size_bytes)}</td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {formatDate(item.generated_at)}
                        <div style={{ color: 'var(--ink-faint)', fontSize: 12 }}>
                          {item.generated_by.full_name}
                        </div>
                      </td>
                      <td className="mono" style={{ fontSize: 11 }}>
                        {item.content_sha256.slice(0, 16)}…
                      </td>
                      <td>
                        <button
                          className="btn btn--small"
                          disabled={busy}
                          onClick={() => onDownload(item)}
                        >
                          Скачать
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function OutcomeCard({ outcome }: { outcome: StateOutcome }) {
  return (
    <div className="card">
      <div className="outcome__head">
        <h3>Состояние: {outcome.state_label}</h3>
        {outcome.exact ? (
          <Badge tone="ok">сценарий № {outcome.scenario_num}</Badge>
        ) : (
          <Badge tone="warn">сценарий не определён</Badge>
        )}
      </div>

      <div className="card__body stack">
        {outcome.conflicting_rules.length > 0 && (
          <Notice tone="warn" title="Пересечение правил">
            Условиям также отвечают: {outcome.conflicting_rules.join(', ')}. Применено самое
            специфичное — методологу следует устранить пересечение.
          </Notice>
        )}

        {outcome.exact ? (
          <>
            {outcome.methods.map((method) => (
              <div key={method.code} className="stack stack--tight">
                <h3>{method.title}</h3>
                <ol className="steps">
                  {method.steps.map((step, index) => (
                    <li key={index} className={step.kind === 'header' ? 'is-header' : undefined}>
                      {step.text}
                    </li>
                  ))}
                </ol>
              </div>
            ))}
            {outcome.source && (
              <small style={{ color: 'var(--ink-faint)' }}>Основание: {outcome.source}</small>
            )}
          </>
        ) : (
          <>
            <p style={{ color: 'var(--ink-soft)' }}>
              Ближайшие описанные сценарии — порядок действий приведён для справки и требует
              подтверждения методолога.
            </p>
            {outcome.nearest.map((near) => (
              <div key={near.rule_code} className="stack stack--tight">
                <div className="row">
                  <h3 style={{ marginRight: 'auto' }}>
                    Сценарий № {near.scenario_num}
                  </h3>
                  <Badge tone="warn">
                    расхождений: {near.distance}
                  </Badge>
                </div>
                <div className="diff">
                  {near.differences.map((diff) => (
                    <div key={diff.key}>
                      <b>{diff.label}:</b> в сценарии «{diff.expected_label}», у вас «
                      {diff.actual_label}»
                    </div>
                  ))}
                </div>
                <div style={{ color: 'var(--ink-soft)' }}>
                  Способы: {near.methods.map((method) => method.title).join('; ') || '—'}
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  )
}
