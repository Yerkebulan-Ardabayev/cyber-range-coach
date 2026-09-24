export type Role = 'owner' | 'operator' | 'viewer'

export interface Principal {
  role: Role
  device_id: number | null
  local_owner: boolean
}

export interface CheckResult {
  id: string
  status: 'ok' | 'warning' | 'blocked' | 'unavailable'
  title: string
  detail: string
  action: string | null
  evidence: Record<string, unknown>
}

export interface Preflight {
  ready: boolean
  platform: string
  windows_supported: boolean
  checks: CheckResult[]
  generated_at: string
}

export interface SimpleTheory {
  analogy: string
  what_it_does: string[]
  words: Array<{ term: string; meaning: string }>
  picture: string
  check_question: string
  check_answer: string
}

export interface Lesson {
  id: string
  order: number
  title: string
  summary: string
  estimated_minutes: number
  skill_id: string
  stage: 'introduced' | 'guided' | 'independent' | 'transfer'
  ladder_step: 1 | 2 | 3
  target_tags: string[]
  requires_target: boolean
  term: { name: string; definition: string }
  simple_theory?: SimpleTheory | null
  worked_example: string
  prediction_question: string
  command: string
  accepted_commands?: string[]
  command_hidden?: boolean
  command_explanation: string[]
  explanation_prompt: string
  review_question: string
}

export interface Curriculum {
  tracks: Array<{ id: string; title: string; summary: string; role: string; version: number }>
  lessons: Lesson[]
}

export interface SessionPlan {
  duration_minutes: number
  lessons: Array<Pick<Lesson, 'id' | 'title' | 'summary' | 'estimated_minutes' | 'skill_id' | 'stage' | 'target_tags'>>
  rationale: string[]
}

export interface LearningSession {
  id: number
  duration_minutes: number
  status: 'planned' | 'active' | 'completed' | 'abandoned'
  lesson_ids: string[]
  current_lesson_id: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface PublishedPort {
  container_port: number
  protocol: 'tcp' | 'udp'
  host_ip: string
  host_port: number
  loopback_endpoint: string | null
  exposure: 'loopback' | 'lan' | 'unknown'
}

export interface DiscoveredTarget {
  container_id: string
  name: string
  image: string
  image_digest: string
  state: string
  health: string | null
  started_at: string | null
  ports: PublishedPort[]
  detected_kind: 'webgoat' | 'juice_shop' | 'generic'
  warnings: string[]
}

export interface Target {
  id: number
  display_name: string
  provider: string
  container_reference: string
  container_port: number
  image_digest: string
  host_endpoint: string
  health_check: Record<string, unknown>
  reset_policy: string
  fingerprint: string
  allowed_curriculum_tags: string[]
  exposure_warnings: string[]
  approved_at: string
  last_verified_at: string | null
}

export interface TargetVerification {
  target_id: number
  reachable: boolean
  tcp_connected: boolean
  http_response_received: boolean
  http_status: number | null
  detail: string
  checked_at: string
}

export interface LabRun {
  id: number
  session_id: number
  lesson_id: string
  skill_id: string
  target_id: number | null
  target_fingerprint: string | null
  status: string
  prediction: string | null
  explanation: string | null
  tutor_feedback_at: string | null
  tutor_question: string | null
  tutor_explanation: string | null
  correction: string | null
  transcript: string
  terminal_inputs: string[]
  terminal_input_offsets: number[]
  grader_status: string | null
  grader_report: Record<string, unknown>
  help_used: boolean
  relay_port: number | null
  created_at: string
  stopped_at: string | null
}

export interface RunLesson extends Lesson {
  rendered_command: string
  variables: Record<string, string>
}

export interface GradeResult {
  run_id: number
  status: 'passed' | 'failed' | 'needs_evidence'
  checks: Array<{ kind: string; pattern: string; passed: boolean }>
  explanation_prompt: string
  evidence_stage: string | null
}

export interface TutorFeedback {
  provider: string
  available: boolean
  question: string
  explanation: string
  missed: string[]
  caution: string | null
  redactions: number
}

export interface Evidence {
  id: number
  run_id: number
  skill_id: string
  stage: string
  source_type: string
  source_id: string
  target_fingerprint: string | null
  fact: string
  grader_decision: string
  created_at: string
}

export interface Review {
  id: number
  skill_id: string
  lesson_id: string
  due_at: string
  reason: string
  completed_at: string | null
}

export type CommandShell = 'bash' | 'cmd'

export type CommandExecutionStatus = 'range_ready' | 'awaiting_stand'

export type RecallReason = 'correct' | 'correct_with_help' | 'wrong_tool' | 'wrong_flag' | 'wrong_shell' | 'insufficient_data'

export interface CommandTechnique {
  id: string
  family: string
  shell: CommandShell
  execution_status: CommandExecutionStatus
  purpose: string
  significant_flags: string[]
  typical_error: string
  mnemonic_image: string
  source_refs: Array<{ source: string; address: string }>
  version: number
}

export interface CommandPracticeChallenge {
  id: string
  prompt: string
  context: {
    shell: CommandShell
    working_directory: string | null
    named_inputs: Record<string, string>
    constraints: string[]
  }
  answer_fields: Array<{ id: string; label: string; kind: 'command' }>
  estimated_minutes: number
  hints: Array<{ level: 1 | 2 | 3 | 4; label: string }>
  observation_prompt: string
  version: number
}

export interface CommandPracticeItem {
  technique_id: string
  shell: CommandShell
  execution_status: CommandExecutionStatus
  challenge: CommandPracticeChallenge
  due_at: string | null
  overdue: boolean
  retry_in_session: boolean
  draft_answer: string
  draft_observation_answer: string
  draft_attempt_key: string | null
  attempt_type: 'assessment' | 'rehearsal'
  eligible_at: string | null
  window_id: number | null
  phase: 'recall' | 'observation'
}

export interface CommandPracticePlan {
  items: CommandPracticeItem[]
  due_total: number
  new_total: number
  debt_remaining: number
  session_limit: number
}

export interface CommandPracticeResult {
  attempt_id: number
  technique_id: string
  reason: RecallReason
  correct: boolean
  independent: boolean
  observation_correct: boolean
  next_due_at: string | null
  interval_days: number | null
  retry_in_session: boolean
  duplicate: boolean
  verification_status: 'verified' | 'unverified'
  detail: string
  attempt_type: 'assessment' | 'rehearsal'
  completed: boolean
  observation_example: string | null
  observation_fields: Array<{ id: string; label: string; required: boolean }>
  correction?: { answer: string; purpose: string; typical_error: string } | null
}

export interface CommandObservationResult {
  attempt_id: number
  technique_id: string
  observation_correct: boolean
  field_errors: Record<string, string>
  free_text_review_status: 'not_assessed'
  completed: boolean
}

export type MissionGradeStatus = 'solved' | 'wrong_artifact' | 'unexplained' | 'needs_review'

export interface MissionPreparedDataEntry {
  path: string
  kind: 'directory' | 'text' | 'note'
  content: string
}

export interface MissionPlanItem {
  mission_id: string
  title: string
  story: string
  allowed_environment: string
  prepared_data_description: string
  required_actions: string[]
  final_artifact_prompt: string
  explanation_prompt: string
  technique_ids: string[]
  technique_refs: Array<{ id: string; label: string; shell: CommandShell }>
  variant_rule: string
  requires_free_text: boolean
  version: number
  variant_id: string
  scenario: string
  prepared_data: MissionPreparedDataEntry[]
  delivery?: 'screen' | 'terminal'
  mission_directory?: string | null
  fact_fields: Array<{ id: string; label: string; required: boolean }>
  draft_attempt_key: string | null
  draft_artifact: string
  draft_explanation: string
  draft_structured_facts: Record<string, string>
}

export interface MissionPlan {
  items: MissionPlanItem[]
}

export interface MissionResult {
  run_id: number
  mission_id: string
  variant_id: string
  status: MissionGradeStatus
  reason: string
  explanation_accepted: boolean
  debrief: string
  evidence_kind: string
  duplicate: boolean
  field_errors: Record<string, string>
  free_text_review_status: 'not_assessed'
}

export interface Note {
  id: number
  title: string
  body: string
  lesson_id: string | null
  run_id: number | null
  source_v1_id: number | null
  source_hash: string | null
  created_at: string
  updated_at: string
}

export interface StudioSource {
  id: number
  original_name: string
  stored_name: string
  media_type: string
  sha256: string
  size_bytes: number
  extractor: string
  immutable_ok: boolean
  created_at: string
  block_count: number
}

export interface Draft {
  id: number
  title: string
  source_ids: number[]
  covered_block_ids: number[]
  content: Record<string, unknown>
  status: 'draft' | 'validated' | 'published'
  validation_report: Record<string, unknown>
  created_at: string
  published_at: string | null
}

export interface LinuxHost {
  id: number
  name: string
  host: string
  port: number
  relay_source_ip: string | null
  username: string
  runner_username: string
  public_key: string
  runner_public_key: string
  host_key_fingerprint: string | null
  confirmed: boolean
  last_preflight_at: string | null
}

export interface WslUbuntuPrepare {
  status: 'ready_for_probe' | 'sudo_password_required' | 'blocked'
  distribution: string | null
  host: string
  port: number
  relay_source_ip: string | null
  ssh_reachable: boolean
  detail: string
  sudo_command: string | null
}

export interface PairingCreated {
  token: string
  role: 'operator' | 'viewer'
  expires_at: string
  certificate_fingerprint: string
}

export interface Device {
  id: number
  name: string
  role: Role
  created_at: string
  last_seen_at: string | null
  revoked_at: string | null
}
