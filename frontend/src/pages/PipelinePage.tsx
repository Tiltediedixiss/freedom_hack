import { useEffect, useRef, useMemo } from "react"
import {
  ShieldAlert,
  Eye,
  Brain,
  MapPin,
  Layers,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  Ban,
  ChevronRight,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"
import type { UseSSEReturn } from "@/hooks/useSSE"
import type { PipelineLogEntry, TicketStage } from "@/types"

interface PipelinePageProps {
  sse: UseSSEReturn
}

const STAGE_META: Record<TicketStage, { icon: React.ComponentType<{ className?: string }>; label: string; color: string }> = {
  spam_filter: { icon: ShieldAlert, label: "Спам-фильтр", color: "text-amber-500" },
  pii_anonymization: { icon: Eye, label: "Анонимизация", color: "text-blue-500" },
  llm_analysis: { icon: Brain, label: "LLM-анализ", color: "text-purple-500" },
  geocoding: { icon: MapPin, label: "Геокодирование", color: "text-emerald-500" },
  enrichment: { icon: Layers, label: "Обогащение", color: "text-primary" },
}

const STAGES: TicketStage[] = ["spam_filter", "pii_anonymization", "llm_analysis", "geocoding", "enrichment"]

export default function PipelinePage({ sse }: PipelinePageProps) {
  const { logs, ticketStates, batchProgress, batchStatus } = sse
  const logEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [logs.length])

  const progressPct =
    batchProgress && batchProgress.total > 0
      ? Math.round((batchProgress.processed / batchProgress.total) * 100)
      : 0

  // Get tickets sorted by activity (most recent first)
  const sortedTickets = useMemo(() => {
    const arr = Array.from(ticketStates.values())
    return arr.reverse().slice(0, 50) // show last 50
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
        {/* Left: Ticket state cards */}
        <div className="flex flex-col min-h-0">
          <h3 className="text-sm font-semibold mb-3 text-muted-foreground uppercase tracking-wider">
            Обращения ({ticketStates.size})
          </h3>
          <ScrollArea className="flex-1 pr-3">
            {sortedTickets.length === 0 ? (
              <div className="text-sm text-muted-foreground text-center py-8">
                {batchStatus === "idle" ? "Запустите обработку на странице загрузки" : "Ожидание событий..."}
              </div>
            ) : (
              <div className="space-y-2">
                {sortedTickets.map((ts) => (
                  <TicketCard key={ts.ticketId} ticket={ts} />
                ))}
              </div>
            )}
          </ScrollArea>
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

function TicketCard({ ticket }: { ticket: import("@/types").TicketProcessingState }) {
  return (
    <Card className={cn("transition-all", ticket.isSpam && "border-amber-500/30 bg-amber-500/5")}>
      <CardContent className="py-3 px-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-mono text-muted-foreground">
            {ticket.ticketId.slice(0, 8)}…
          </span>
          {ticket.isSpam ? (
            <Badge variant="warning">Спам</Badge>
          ) : ticket.isComplete ? (
            <Badge variant="success">Готово</Badge>
          ) : (
            <Badge variant="secondary">В процессе</Badge>
          )}
        </div>
        <div className="flex items-center gap-1">
          {STAGES.map((stage, idx) => {
            const info = STAGE_META[stage]
            const stageState = ticket.stages[stage]
            const Icon = info.icon
            const isActive = stageState?.status === "in_progress"
            const isDone = stageState?.status === "completed"
            const isFailed = stageState?.status === "failed"

            return (
              <div key={stage} className="flex items-center">
                <div
                  className={cn(
                    "flex items-center justify-center w-7 h-7 rounded-full border transition-all",
                    isDone && "bg-emerald-500/10 border-emerald-500/50",
                    isActive && "bg-primary/10 border-primary animate-pulse",
                    isFailed && "bg-destructive/10 border-destructive/50",
                    !stageState && "border-muted-foreground/20 opacity-40",
                  )}
                  title={info.label}
                >
                  {isActive ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                  ) : isDone ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                  ) : isFailed ? (
                    <XCircle className="h-3.5 w-3.5 text-destructive" />
                  ) : (
                    <Icon className={cn("h-3.5 w-3.5", stageState ? info.color : "text-muted-foreground/40")} />
                  )}
                </div>
                {idx < STAGES.length - 1 && (
                  <ChevronRight className="h-3 w-3 text-muted-foreground/30 mx-0.5" />
                )}
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
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
