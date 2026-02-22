const API_BASE = "/api"

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) {
    const body = await res.text()
    throw new Error(`API ${res.status}: ${body}`)
  }
  return res.json()
}

const UPLOAD_TIMEOUT_MS = 120_000 

async function uploadFile<T>(path: string, file: File, fieldName = "file"): Promise<T> {
  const form = new FormData()
  form.append(fieldName, file)
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS)
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      body: form,
      signal: controller.signal,
    })
    if (!res.ok) {
      const body = await res.text()
      throw new Error(`Upload ${res.status}: ${body}`)
    }
    return res.json()
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") {
      throw new Error("Загрузка превысила время ожидания (2 мин). Проверьте размер файла и бэкенд.")
    }
    throw e
  } finally {
    clearTimeout(timeoutId)
  }
}

// ── Ingestion ──
export const ingestTickets = (file: File) =>
  uploadFile<import("@/types").IngestTicketsResponse>("/ingest/tickets", file)

export const ingestManagers = (file: File) =>
  uploadFile<import("@/types").IngestManagersResponse>("/ingest/managers", file)

export const ingestBusinessUnits = (file: File) =>
  uploadFile<import("@/types").IngestBusinessUnitsResponse>("/ingest/business-units", file)

// ── Processing ──
export const startProcessing = (batchId: string) =>
  request<{ message: string; batch_id: string; total_rows: number }>(`/processing/start/${batchId}`, { method: "POST" })

export interface ProcessingProgressResult {
  ticket_id: string
  csv_row: number | null
  type: string
  sentiment: string
  summary: string
  latitude: number | null
  longitude: number | null
  is_spam: boolean
  is_complete: boolean
  geo_filter?: { candidates: number; distance_km?: number; office_name?: string; note: string }
  skills_filter?: { before: number; after: number; relaxation: string | null }
  priority?: { final: number; segment?: number; type?: number; sentiment?: number }
}

export const getProcessingProgress = (batchId: string) =>
  request<{
    total: number
    processed: number
    spam: number
    current: number
    status: string
    results?: ProcessingProgressResult[]
  }>(`/processing/progress/${batchId}`)

export const getProcessingStatus = (batchId: string) =>
  request<import("@/types").ProcessingState[]>(`/processing/status/${batchId}`)

// ── Tickets ──
export const getTickets = (page = 1, pageSize = 50) =>
  request<import("@/types").Ticket[]>(`/tickets?page=${page}&page_size=${pageSize}`)

export const getTicketCount = () =>
  request<{ count: number }>("/tickets/count")

export const getTicketByRow = (rowIndex: number) =>
  request<import("@/types").TicketLookup>(`/tickets/row/${rowIndex}`)

export const getBatchStatus = (batchId: string) =>
  request<import("@/types").BatchUpload>(`/tickets/batch/${batchId}`)

// ── Dashboard ──
export const getDashboardStats = () =>
  request<import("@/types").DashboardStats>("/dashboard/stats")

export const getTypeDistribution = () =>
  request<Record<string, number>>("/dashboard/types")

export const getSentimentDistribution = () =>
  request<Record<string, number>>("/dashboard/sentiment")

export const getManagerLoad = () =>
  request<import("@/types").ManagerLoad[]>("/dashboard/managers")

// ── Health ──
export const getHealth = () =>
  request<{ status: string; service: string; version: string }>("/health".replace("/api", ""))

// Special: health is at root, not under /api
export const checkHealth = async (): Promise<boolean> => {
  try {
    const res = await fetch("/health")
    return res.ok
  } catch {
    return false
  }
}
