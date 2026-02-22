import { useEffect, useRef, useMemo, useState } from "react"
import { CheckCircle2, Loader2, Ban } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import type { UseSSEReturn } from "@/hooks/useSSE"
import ArchitectureModal from "@/components/ui/archModal"

interface PipelinePageProps {
  sse: UseSSEReturn
}

export default function PipelinePage({ sse }: PipelinePageProps) {
  const { ticketStates, extractedResults, batchProgress, batchStatus } = sse
  const tableEndRef = useRef<HTMLTableRowElement>(null)
  const [showArchitectureModal, setShowArchitectureModal] = useState(true)

  const progressPct =
    batchProgress && batchProgress.total > 0
      ? Math.min(
          100,
          Math.round(
            (Math.max(batchProgress.processed, (batchProgress.current ?? 1) - 1) / batchProgress.total) * 100
          )
        )
      : 0

  // Prefer polled extractedResults (reliable); fallback to ticketStates from SSE
  const tableRows = useMemo(() => {
    if (extractedResults.length > 0) {
      return extractedResults
    }
    return Array.from(ticketStates.values()).map((ts) => ({
      ticket_id: ts.ticketId,
      csv_row: ts.csvRow ?? null,
      type: (ts.stages.llm_analysis?.data?.type ?? ts.stages.enrichment?.data?.type ?? "—") as string,
      sentiment: (ts.stages.llm_analysis?.data?.sentiment ?? ts.stages.enrichment?.data?.sentiment ?? "—") as string,
      summary: (ts.stages.llm_analysis?.data?.summary ?? ts.stages.enrichment?.data?.summary ?? "—") as string,
      latitude: (ts.stages.geocoding?.data?.latitude ?? ts.stages.enrichment?.data?.latitude) as number | null,
      longitude: (ts.stages.geocoding?.data?.longitude ?? ts.stages.enrichment?.data?.longitude) as number | null,
      is_spam: ts.isSpam,
      is_complete: ts.isComplete,
    }))
  }, [extractedResults, ticketStates])

  useEffect(() => {
    tableEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })
  }, [tableRows.length])

  return (
    <div className="p-6 space-y-6 h-full flex flex-col">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Конвейер обработки</h2>
          <p className="text-muted-foreground text-sm mt-1">
            Наблюдайте за обработкой обращений в реальном времени через SSE
          </p>
        </div>
        {batchStatus !== "idle" && (
          <Badge variant={batchStatus === "completed" ? "success" : batchStatus === "failed" ? "destructive" : "default"}>
            {batchStatus === "processing" && "В процессе"}
            {batchStatus === "completed" && "Завершено"}
            {batchStatus === "failed" && "Ошибка"}
          </Badge>
        )}
      </div>

      {/* Batch progress */}
      {batchProgress && (
        <Card>
          <CardContent className="pt-4 space-y-3">
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">
                Обработано {batchProgress.processed} из {batchProgress.total}
                {batchProgress.spam > 0 && ` (спам: ${batchProgress.spam})`}
              </span>
              <span className="font-medium">{progressPct}%</span>
            </div>
            <Progress value={progressPct} />
          </CardContent>
        </Card>
      )}
      <ArchitectureModal show={showArchitectureModal} onClose={() => setShowArchitectureModal(false)} />

      <div className="flex flex-col flex-1 min-h-0">
        <h3 className="text-sm font-semibold mb-3 text-muted-foreground uppercase tracking-wider">
          Результаты извлечения ({tableRows.length})
        </h3>
        <Card className="flex-1 overflow-hidden">
          <ScrollArea className="h-full max-h-[calc(100vh-280px)]">
            <div className="overflow-x-auto">
              {tableRows.length === 0 ? (
                <div className="text-sm text-muted-foreground text-center py-8">
                  {batchStatus === "idle" ? "Запустите обработку на странице загрузки" : "Ожидание событий..."}
                </div>
              ) : (
                <table className="w-full text-sm min-w-[1000px]">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">№</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">ID</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">Тип</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">Тональность</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground">Сводка</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">Спам</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">Координаты</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">Гео-фильтр</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">Навыки</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">Приоритет</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground whitespace-nowrap">Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map((row, idx) => (
                      <ResultsTableRow key={row.ticket_id} row={row} index={idx + 1} />
                    ))}
                    <tr ref={tableEndRef} />
                  </tbody>
                </table>
              )}
            </div>
          </ScrollArea>
        </Card>
      </div>
    </div>
  )
}

/* ─── Sub-components ─── */

type TableRow = {
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

function ResultsTableRow({ row, index }: { row: TableRow; index: number }) {
  const coords =
    row.latitude != null && row.longitude != null
      ? `${row.latitude.toFixed(4)}, ${row.longitude.toFixed(4)}`
      : "—"
  const geo = row.geo_filter
  const skills = row.skills_filter
  const priority = row.priority

  return (
    <tr
      className={cn(
        "border-b border-border/50 transition-colors",
        row.is_spam && "bg-amber-500/5",
      )}
    >
      <td className="py-2 px-3 text-muted-foreground">{row.csv_row ?? index}</td>
      <td className="py-2 px-3 font-mono text-xs">{row.ticket_id.slice(0, 8)}…</td>
      <td className="py-2 px-3">{row.type}</td>
      <td className="py-2 px-3">{row.sentiment}</td>
      <td className="py-2 px-3 break-words max-w-[200px]" title={row.summary}>
        {row.summary || "—"}
      </td>
      <td className="py-2 px-3">
        {row.is_spam ? (
          <Badge variant="warning">Спам</Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className="py-2 px-3 font-mono text-xs">{coords}</td>
      <td className="py-2 px-3 text-xs" title={geo?.note}>
        {row.is_spam ? "—" : geo ? (geo.office_name ? `${geo.office_name} (${geo.distance_km} км)` : geo.note) : "—"}
      </td>
      <td className="py-2 px-3 text-xs" title={skills?.relaxation ?? undefined}>
        {row.is_spam ? "—" : skills ? `${skills.after}/${skills.before}${skills.relaxation ? " ⚠" : ""}` : "—"}
      </td>
      <td className="py-2 px-3 font-mono text-xs">
        {row.is_spam ? "—" : priority != null ? priority.final.toFixed(2) : "—"}
      </td>
      <td className="py-2 px-3">
        {row.is_spam ? (
          <Badge variant="warning">Спам</Badge>
        ) : row.is_complete ? (
          <Badge variant="success">Готово</Badge>
        ) : (
          <Badge variant="secondary">
            <Loader2 className="h-3 w-3 inline animate-spin mr-1" />
            В процессе
          </Badge>
        )}
      </td>
    </tr>
  )
}
