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

export interface Lesson {
  id: string
  order: number
  title: string
  summary: string
  estimated_minutes: number
  skill_id: string
  stage: 'introduced' | 'guided' | 'independent'
  target_tags: string[]
  requires_target: boolean
  term: { name: string; definition: string }
  worked_example: string
  prediction_question: string
  command: string
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
