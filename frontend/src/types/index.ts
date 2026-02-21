// ── SSE Event (matches backend SSEEvent schema) ──
export interface SSEEvent {
  event_type: string
  ticket_id: string
  batch_id: string | null
  stage: string
  status: string
  field: string | null
  data: Record<string, unknown>
  message: string | null
  timestamp: string
}

// ── Ingestion ──
export interface IngestTicketsResponse {
  batch_id: string
  total_rows: number
  processed_rows: number
  failed_rows: number
  message: string
  errors: string[]
}

export interface IngestManagersResponse {
  total_imported: number
  message: string
  errors: string[]
}

export interface IngestBusinessUnitsResponse {
  total_imported: number
  message: string
}

// ── Ticket ──
export interface Ticket {
  id: string
  csv_row_index: number | null
  guid: string | null
  gender: string | null
  birth_date: string | null
  age: number | null
  description: string | null
  description_anonymized: string | null
  attachments: string[]
  segment: string | null
  country: string | null
  region: string | null
  city: string | null
  street: string | null
  house: string | null
  latitude: number | null
  longitude: number | null
  address_status: string | null
  ticket_type: string | null
  status: string
  is_spam: boolean
  spam_probability: number
  text_length: number | null
  text_length_times_age: number | null
  id_count_of_user: number
  assigned_manager_id: string | null
  created_at: string
  updated_at: string
}

// ── AI Analysis ──
export interface AIAnalysis {
  id: string
  ticket_id: string
  detected_type: string | null
  language_label: string | null
  language_actual: string | null
  language_is_mixed: boolean
  language_note: string | null
  summary: string | null
  attachment_analysis: string | null
  sentiment: string | null
  sentiment_confidence: number | null
  priority_base: number | null
  priority_extra: number | null
  priority_final: number | null
  priority_breakdown: Record<string, unknown>
  anomaly_flags: unknown[]
  needs_data_change: boolean
  needs_location_routing: boolean
  processing_time_ms: number
  created_at: string
}

// ── Manager ──
export interface Manager {
  id: string
  full_name: string
  position: string
  skill_factor: number
  skills: string[]
  business_unit_id: string | null
  csv_load: number
  stress_score: number
  is_active: boolean
  created_at: string
}

// ── Business Unit ──
export interface BusinessUnit {
  id: string
  name: string
  address: string | null
  latitude: number | null
  longitude: number | null
  created_at: string
}

// ── Assignment ──
export interface Assignment {
  id: string
  ticket_id: string
  manager_id: string
  business_unit_id: string | null
  explanation: string | null
  routing_details: Record<string, unknown>
  assigned_at: string
}

// ── Ticket Lookup ──
export interface TicketLookup {
  ticket: Ticket
  ai_analysis: AIAnalysis | null
  assignment: Assignment | null
  manager: Manager | null
  business_unit: BusinessUnit | null
}

// ── Processing State ──
export interface ProcessingState {
  id: string
  ticket_id: string
  batch_id: string | null
  stage: string
  status: string
  progress_pct: number
  message: string | null
  error_detail: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

// ── Batch Upload ──
export interface BatchUpload {
  id: string
  filename: string | null
  total_rows: number
  processed_rows: number
  failed_rows: number
  status: string
  error_log: unknown[]
  created_at: string
  completed_at: string | null
}

// ── Dashboard ──
export interface DashboardStats {
  total_tickets: number
  spam_tickets: number
  total_managers: number
  total_assignments: number
  by_status: Record<string, number>
}

export interface ManagerLoad {
  id: string
  full_name: string
  position: string | null
  skills: string[]
  csv_load: number
  stress_score: number
}

// ── Pipeline log entry (frontend-only, built from SSE) ──
export type LogLevel = "info" | "success" | "error" | "warning" | "spam"

export interface PipelineLogEntry {
  id: string
  timestamp: string
  ticketId: string | null
  csvRow: number | null
  stage: string
  status: string
  message: string
  level: LogLevel
  data?: Record<string, unknown>
}

// ── Ticket processing state tracker (frontend-only) ──
export type TicketStage = "spam_filter" | "pii_anonymization" | "llm_analysis" | "geocoding" | "enrichment"

export interface TicketProcessingState {
  ticketId: string
  csvRow: number | null
  stages: Partial<Record<TicketStage, {
    status: "pending" | "in_progress" | "completed" | "failed"
    message?: string
    data?: Record<string, unknown>
  }>>
  isSpam: boolean
  isComplete: boolean
}
