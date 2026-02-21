import { useEffect, useRef, useCallback, useState } from "react"
import type { SSEEvent, PipelineLogEntry, TicketProcessingState, LogLevel, TicketStage } from "@/types"

const SSE_URL = "/api/processing/stream"

function sseToLogEntry(event: SSEEvent): PipelineLogEntry {
  let level: LogLevel = "info"
  let message = event.message || ""

  if (event.status === "failed") {
    level = "error"
  } else if (event.status === "completed") {
    level = "success"
  }

  if (event.stage === "spam_filter" && event.data?.is_spam) {
    level = "spam"
    message = `Спам обнаружен: ${event.message || "отфильтровано"}`
  }

  if (event.stage === "pipeline" && event.status === "in_progress") {
    level = "info"
    message = event.message || `Обработка пакета...`
  }

  if (event.stage === "pipeline" && event.status === "completed") {
    level = "success"
    const d = event.data
    message = `Пакет завершён: ${d.total ?? "?"} обращений (${d.spam ?? 0} спам, ${d.enriched ?? 0} обогащено)`
  }

  if (!message && event.field) {
    const val = event.data?.value ?? event.data?.[event.field]
    message = `${event.field}: ${val}`
  }

  if (!message) {
    message = `${event.stage} ${event.status}`
  }

  return {
    id: `${event.ticket_id}-${event.stage}-${event.timestamp}-${Math.random().toString(36).slice(2, 6)}`,
    timestamp: event.timestamp,
    ticketId: event.ticket_id === "00000000-0000-0000-0000-000000000000" ? null : event.ticket_id,
    csvRow: null, // will be resolved by the component
    stage: event.stage,
    status: event.status,
    message,
    level,
    data: event.data as Record<string, unknown>,
  }
}

function updateTicketState(
  state: Map<string, TicketProcessingState>,
  event: SSEEvent,
): Map<string, TicketProcessingState> {
  // Skip batch-level events (ticket_id is zero UUID)
  if (event.ticket_id === "00000000-0000-0000-0000-000000000000") return state

  const next = new Map(state)
  const existing = next.get(event.ticket_id)

  const ticketState: TicketProcessingState = existing ?? {
    ticketId: event.ticket_id,
    csvRow: null,
    stages: {},
    isSpam: false,
    isComplete: false,
  }

  const stage = event.stage as TicketStage
  const validStages: TicketStage[] = ["spam_filter", "pii_anonymization", "llm_analysis", "geocoding", "enrichment"]

  if (validStages.includes(stage)) {
    ticketState.stages[stage] = {
      status: event.status === "completed" ? "completed" : event.status === "failed" ? "failed" : "in_progress",
      message: event.message ?? undefined,
      data: event.data as Record<string, unknown>,
    }
  }

  if (event.stage === "spam_filter" && event.data?.is_spam) {
    ticketState.isSpam = true
    ticketState.isComplete = true
  }

  if (event.stage === "enrichment" && event.status === "completed") {
    ticketState.isComplete = true
  }

  next.set(event.ticket_id, ticketState)
  return next
}

export interface UseSSEReturn {
  logs: PipelineLogEntry[]
  ticketStates: Map<string, TicketProcessingState>
  isConnected: boolean
  batchProgress: { total: number; processed: number; spam: number } | null
  batchStatus: "idle" | "processing" | "completed" | "failed"
  clearLogs: () => void
}

export function useSSE(): UseSSEReturn {
  const [logs, setLogs] = useState<PipelineLogEntry[]>([])
  const [ticketStates, setTicketStates] = useState<Map<string, TicketProcessingState>>(new Map())
  const [isConnected, setIsConnected] = useState(false)
  const [batchProgress, setBatchProgress] = useState<{ total: number; processed: number; spam: number } | null>(null)
  const [batchStatus, setBatchStatus] = useState<"idle" | "processing" | "completed" | "failed">("idle")
  const eventSourceRef = useRef<EventSource | null>(null)
  const ticketStatesRef = useRef(ticketStates)

  // Keep ref in sync with state
  ticketStatesRef.current = ticketStates

  const clearLogs = useCallback(() => {
    setLogs([])
    setTicketStates(new Map())
    setBatchProgress(null)
    setBatchStatus("idle")
  }, [])

  useEffect(() => {
    const connect = () => {
      const es = new EventSource(SSE_URL)
      eventSourceRef.current = es

      es.onopen = () => setIsConnected(true)
      es.onerror = () => {
        setIsConnected(false)
        es.close()
        // Reconnect after 2s
        setTimeout(connect, 2000)
      }

      es.onmessage = (e) => {
        try {
          const event: SSEEvent = JSON.parse(e.data)

          // Update logs
          const logEntry = sseToLogEntry(event)
          setLogs((prev) => [...prev, logEntry])

          // Update ticket states
          setTicketStates((prev) => updateTicketState(prev, event))

          // Update batch progress
          if (event.stage === "pipeline") {
            if (event.status === "in_progress") {
              setBatchStatus("processing")
              setBatchProgress({
                total: (event.data.total as number) || 0,
                processed: 0,
                spam: 0,
              })
            } else if (event.status === "completed") {
              setBatchStatus("completed")
              setBatchProgress({
                total: (event.data.total as number) || 0,
                processed: (event.data.total as number) || 0,
                spam: (event.data.spam as number) || 0,
              })
            } else if (event.status === "failed") {
              setBatchStatus("failed")
            }
          }

          // Increment processed count on enrichment complete or spam
          if (
            (event.stage === "enrichment" && event.status === "completed") ||
            (event.stage === "spam_filter" && event.data?.is_spam)
          ) {
            setBatchProgress((prev) =>
              prev
                ? {
                    ...prev,
                    processed: prev.processed + 1,
                    spam: event.data?.is_spam ? prev.spam + 1 : prev.spam,
                  }
                : null
            )
          }
        } catch {
          // ignore parse errors
        }
      }
    }

    connect()

    return () => {
      eventSourceRef.current?.close()
    }
  }, [])

  return { logs, ticketStates, isConnected, batchProgress, batchStatus, clearLogs }
}
