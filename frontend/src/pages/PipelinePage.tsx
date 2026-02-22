import { useEffect, useRef, useMemo } from "react"
import { ShieldAlert, CheckCircle2, XCircle, Clock, Loader2, Ban } from "lucide-react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import type { UseSSEReturn } from "@/hooks/useSSE"
import type { PipelineLogEntry } from "@/types"

interface PipelinePageProps {
  sse: UseSSEReturn
}

export default function PipelinePage({ sse }: PipelinePageProps) {
  const { logs, ticketStates, batchProgress, batchStatus } = sse
  const logEndRef = useRef<HTMLDivElement>(null)
  const tableEndRef = useRef<HTMLTableRowElement>(null)

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [logs.length])

  useEffect(() => {
    tableEndRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" })
  }, [ticketStates.size])

  const progressPct =
    batchProgress && batchProgress.total > 0
      ? Math.round((batchProgress.processed / batchProgress.total) * 100)
      : 0

  // Get tickets in order they arrived (rows load one by one)
  const tableRows = useMemo(() => {
    return Array.from(ticketStates.values()).slice(0, 100)
  }, [ticketStates])

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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 flex-1 min-h-0">
        {/* Left: Extracted features table — rows load one by one */}
        <div className="flex flex-col min-h-0">
          <h3 className="text-sm font-semibold mb-3 text-muted-foreground uppercase tracking-wider">
            Результаты извлечения ({tableRows.length})
          </h3>
          <Card className="flex-1 overflow-hidden">
            <ScrollArea className="h-full max-h-[calc(100vh-280px)]">
              {tableRows.length === 0 ? (
                <div className="text-sm text-muted-foreground text-center py-8">
                  {batchStatus === "idle" ? "Запустите обработку на странице загрузки" : "Ожидание событий..."}
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground">№</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground">ID</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground">Тип</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground">Тональность</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground">Сводка</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground">Спам</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground">Координаты</th>
                      <th className="text-left py-2 px-3 font-medium text-muted-foreground">Статус</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tableRows.map((ts, idx) => (
                      <ResultsTableRow key={ts.ticketId} ticket={ts} index={idx + 1} />
                    ))}
                    <tr ref={tableEndRef} />
                  </tbody>
                </table>
              )}
            </ScrollArea>
          </Card>
        </div>

        {/* Right: Live log stream */}
        <div className="flex flex-col min-h-0">
          <h3 className="text-sm font-semibold mb-3 text-muted-foreground uppercase tracking-wider">
            Лог событий ({logs.length})
          </h3>
          <Card className="flex-1 overflow-hidden">
            <ScrollArea className="h-full max-h-[calc(100vh-280px)]">
              <div className="p-3 font-mono text-xs space-y-0.5">
                {logs.length === 0 ? (
                  <div className="text-muted-foreground text-center py-8">
                    Нет событий
                  </div>
                ) : (
                  logs.map((log) => <LogLine key={log.id} entry={log} />)
                )}
                <div ref={logEndRef} />
              </div>
            </ScrollArea>
          </Card>
        </div>
      </div>
    </div>
  )
}

/* ─── Sub-components ─── */

function ResultsTableRow({
  ticket,
  index,
}: {
  ticket: import("@/types").TicketProcessingState
  index: number
}) {
  const llm = ticket.stages.llm_analysis?.data
  const geo = ticket.stages.geocoding?.data
  const enrich = ticket.stages.enrichment?.data
  const type = (llm?.type ?? enrich?.type ?? "—") as string
  const sentiment = (llm?.sentiment ?? enrich?.sentiment ?? "—") as string
  const summary = (llm?.summary ?? enrich?.summary ?? "") as string
  const lat = geo?.latitude ?? enrich?.latitude
  const lng = geo?.longitude ?? enrich?.longitude
  const latNum = typeof lat === "number" ? lat : null
  const lngNum = typeof lng === "number" ? lng : null
  const coords =
    latNum != null && lngNum != null ? `${latNum.toFixed(4)}, ${lngNum.toFixed(4)}` : "—"

  return (
    <tr
      className={cn(
        "border-b border-border/50 transition-colors",
        ticket.isSpam && "bg-amber-500/5",
      )}
    >
      <td className="py-2 px-3 text-muted-foreground">{ticket.csvRow ?? index}</td>
      <td className="py-2 px-3 font-mono text-xs">{ticket.ticketId.slice(0, 8)}…</td>
      <td className="py-2 px-3">{type}</td>
      <td className="py-2 px-3">{sentiment}</td>
      <td className="py-2 px-3 max-w-[180px] truncate" title={summary}>
        {summary || "—"}
      </td>
      <td className="py-2 px-3">
        {ticket.isSpam ? (
          <Badge variant="warning">Спам</Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        )}
      </td>
      <td className="py-2 px-3 font-mono text-xs">{coords}</td>
      <td className="py-2 px-3">
        {ticket.isSpam ? (
          <Badge variant="warning">Спам</Badge>
        ) : ticket.isComplete ? (
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

function LogLine({ entry }: { entry: PipelineLogEntry }) {
  const time = new Date(entry.timestamp).toLocaleTimeString("ru-RU")
  const levelColors: Record<string, string> = {
    info: "text-blue-400",
    success: "text-emerald-400",
    error: "text-red-400",
    warning: "text-amber-400",
    spam: "text-amber-500",
  }
  const levelIcons: Record<string, React.ComponentType<{ className?: string }>> = {
    info: Clock,
    success: CheckCircle2,
    error: XCircle,
    warning: ShieldAlert,
    spam: Ban,
  }
  const Icon = levelIcons[entry.level] || Clock

  return (
    <div className={cn("flex items-start gap-2 py-0.5 leading-relaxed", levelColors[entry.level])}>
      <Icon className="h-3.5 w-3.5 mt-0.5 shrink-0" />
      <span className="text-muted-foreground shrink-0">{time}</span>
      {entry.ticketId && (
        <span className="text-muted-foreground/60 shrink-0">[{entry.ticketId.slice(0, 8)}]</span>
      )}
      <span className="break-all">{entry.message}</span>
    </div>
  )
}
