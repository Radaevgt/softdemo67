export type Role = 'operator' | 'methodologist' | 'specialist' | 'viewer'
export type ObjectKind = 'izhs' | 'mkd_apartment' | 'nonresidential'
export type ObjectState = 'ownerless' | 'fpo' | 'emergency' | 'cs_mode'
export type CaseStatus = 'draft' | 'in_progress' | 'decided' | 'archived'
export type AssessmentStatus = 'draft' | 'completed' | 'approved'
export type RoadmapStatus = 'pending' | 'in_progress' | 'done' | 'not_required'
export type EscalationStatus = 'open' | 'resolved' | 'rejected'

export interface Municipality {
  id: string
  name: string
  code: string | null
  is_active: boolean
}

export interface User {
  id: string
  login: string
  full_name: string
  position: string | null
  role: Role
  is_active: boolean
  municipality: Municipality | null
}

export interface ObjectCase {
  id: string
  address: string
  object_kind: ObjectKind
  states: ObjectState[]
  cadastral_number_oks: string | null
  cadastral_number_land: string | null
  notes: string | null
  status: CaseStatus
  municipality: Municipality
  created_by: User
  created_at: string
  updated_at: string
}

export type AnswerValue = boolean | string

export interface MethodStep {
  kind: 'action' | 'header'
  text: string
}

export interface Method {
  code: string
  title: string
  steps: MethodStep[]
}

export interface Difference {
  key: string
  label: string
  expected: AnswerValue
  expected_label: string
  actual: AnswerValue | null
  actual_label: string
}

export interface NearMatch {
  rule_code: string
  scenario_num: number
  distance: number
  differences: Difference[]
  methods: Method[]
  source: string | null
}

export interface StateOutcome {
  state: ObjectState
  state_label: string
  exact: boolean
  rule_code: string | null
  scenario_num: number | null
  methods: Method[]
  source: string | null
  nearest: NearMatch[]
  conflicting_rules: string[]
}

export interface AnswerBreakdown {
  key: string
  label: string
  value: AnswerValue
  value_label: string
  source_hint: string
}

export interface Decision {
  object_kind: ObjectKind
  object_kind_label: string
  states: ObjectState[]
  answers: Record<string, AnswerValue>
  answer_breakdown: AnswerBreakdown[]
  outcomes: StateOutcome[]
  needs_review: boolean
  ruleset_version: string
}

export interface Assessment {
  id: string
  case_id: string
  status: AssessmentStatus
  answers: Record<string, AnswerValue>
  decision: Decision | null
  ruleset_version: string | null
  author: User
  approved_by: User | null
  approved_at: string | null
  content_hash: string | null
  signed_at: string | null
  created_at: string
  updated_at: string
}

export interface Question {
  key: string
  label: string
  type: 'boolean' | 'enum'
  source_hint: string
  options: { value: AnswerValue; label: string }[]
}

export interface AssessmentProgress {
  assessment: Assessment
  answered: AnswerBreakdown[]
  next_question: Question | null
  remaining: number
  complete: boolean
}

export interface RoadmapItem {
  id: string
  method_code: string
  order_index: number
  kind: 'action' | 'header'
  text: string
  status: RoadmapStatus
  due_date: string | null
  note: string | null
  completed_at: string | null
  assignee: User | null
}

export type DocumentFormat = 'docx' | 'pdf'

export interface AssessmentDocument {
  id: string
  format: DocumentFormat
  filename: string
  content_sha256: string
  size_bytes: number
  generated_at: string
  generated_by: User
}

export interface Rule {
  id: string
  code: string
  object_kind: ObjectKind
  state: ObjectState
  scenario_num: number
  conditions: Record<string, AnswerValue>
  method_codes: string[]
  source: string | null
  is_active: boolean
  is_builtin: boolean
}

export interface CoverageCell {
  object_kind: ObjectKind
  state: ObjectState
  described: number
  combinations: number
  gaps: number
}

export interface Escalation {
  id: string
  case_id: string
  assessment_id: string | null
  inputs: { object_kind: ObjectKind; states: ObjectState[]; answers: Record<string, AnswerValue>; decision?: Decision }
  comment: string | null
  status: EscalationStatus
  resolution: string | null
  created_by: User
  resolved_by: User | null
  resolved_at: string | null
  created_at: string
}

export interface AuditEntry {
  id: string
  actor_login: string | null
  action: string
  entity_type: string | null
  entity_id: string | null
  payload: Record<string, unknown> | null
  created_at: string
}

export interface Dictionaries {
  object_kinds: { value: ObjectKind; label: string }[]
  states: { value: ObjectState; label: string }[]
  roles: { value: Role; label: string }[]
  rule_value_labels: Record<string, Record<string, string>>
  attributes: Question[]
}
