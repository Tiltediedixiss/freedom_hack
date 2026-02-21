import { useState, useRef, useCallback } from "react"
import { Upload, FileText, Users, Building2, Play, CheckCircle2, AlertCircle, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { ingestTickets, ingestManagers, ingestBusinessUnits, startProcessing } from "@/lib/api"
import type { UseSSEReturn } from "@/hooks/useSSE"
import type { IngestTicketsResponse, IngestManagersResponse, IngestBusinessUnitsResponse } from "@/types"

interface UploadPageProps {
  sse: UseSSEReturn
}

type Step = "upload" | "processing" | "done"

interface UploadState {
  file: File | null
  loading: boolean
  result: IngestTicketsResponse | IngestManagersResponse | IngestBusinessUnitsResponse | null
  error: string | null
}

const initialUpload: UploadState = { file: null, loading: false, result: null, error: null }

export default function UploadPage({ sse }: UploadPageProps) {
  const [step, setStep] = useState<Step>("upload")
  const [tickets, setTickets] = useState<UploadState>(initialUpload)
  const [managers, setManagers] = useState<UploadState>(initialUpload)
  const [units, setUnits] = useState<UploadState>(initialUpload)
  const [processing, setProcessing] = useState(false)

  const ticketsRef = useRef<HTMLInputElement>(null)
  const managersRef = useRef<HTMLInputElement>(null)
  const unitsRef = useRef<HTMLInputElement>(null)

  const batchId = tickets.result && "batch_id" in tickets.result ? tickets.result.batch_id : null

  const handleUpload = useCallback(
    async (
      type: "tickets" | "managers" | "units",
      file: File,
      setState: React.Dispatch<React.SetStateAction<UploadState>>,
    ) => {
      setState({ file, loading: true, result: null, error: null })
      try {
        let result: IngestTicketsResponse | IngestManagersResponse | IngestBusinessUnitsResponse
        if (type === "tickets") result = await ingestTickets(file)
        else if (type === "managers") result = await ingestManagers(file)
        else result = await ingestBusinessUnits(file)
        setState({ file, loading: false, result, error: null })
      } catch (e) {
        setState({ file, loading: false, result: null, error: (e as Error).message })
      }
    },
    [],
  )

  const handleStartProcessing = async () => {
    if (!batchId) return
    setProcessing(true)
    sse.clearLogs()
    try {
      await startProcessing(batchId)
      setStep("processing")
    } catch (e) {
      console.error(e)
    } finally {
      setProcessing(false)
    }
  }

  const progressPct =
    sse.batchProgress && sse.batchProgress.total > 0
      ? Math.round((sse.batchProgress.processed / sse.batchProgress.total) * 100)
      : 0

  const allUploaded = tickets.result && managers.result && units.result

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Загрузка данных</h2>
        <p className="text-muted-foreground text-sm mt-1">
          Загрузите три CSV-файла, затем запустите обработку конвейера
        </p>
      </div>

      {/* Step indicator */}
      <div className="flex items-center gap-2 text-sm">
        <StepBadge active={step === "upload"} done={step !== "upload"} label="1. Загрузка" />
        <span className="text-muted-foreground">→</span>
        <StepBadge active={step === "processing"} done={step === "done"} label="2. Обработка" />
        <span className="text-muted-foreground">→</span>
        <StepBadge active={step === "done"} done={false} label="3. Готово" />
      </div>

      {step === "upload" && (
        <>
          <div className="grid gap-4 md:grid-cols-3">
            <UploadCard
              title="Обращения"
              description="tickets.csv"
              icon={FileText}
              inputRef={ticketsRef}
              state={tickets}
              onSelect={(f) => handleUpload("tickets", f, setTickets)}
            />
            <UploadCard
              title="Менеджеры"
              description="managers.csv"
              icon={Users}
              inputRef={managersRef}
              state={managers}
              onSelect={(f) => handleUpload("managers", f, setManagers)}
            />
            <UploadCard
              title="Офисы"
              description="business_units.csv"
              icon={Building2}
              inputRef={unitsRef}
              state={units}
              onSelect={(f) => handleUpload("units", f, setUnits)}
            />
          </div>

          <Button
            size="lg"
            className="w-full"
            disabled={!allUploaded || processing}
            onClick={handleStartProcessing}
          >
            {processing ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Play className="h-4 w-4 mr-2" />
            )}
            Запустить конвейер
          </Button>
        </>
      )}

      {step === "processing" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              Обработка конвейера
            </CardTitle>
            <CardDescription>
              {sse.batchStatus === "completed"
                ? "Обработка завершена!"
                : `Идёт обработка пакета ${batchId?.slice(0, 8)}...`}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-muted-foreground">Прогресс</span>
                <span className="font-medium">{progressPct}%</span>
              </div>
              <Progress value={progressPct} />
            </div>
            {sse.batchProgress && (
              <div className="flex gap-4 text-sm text-muted-foreground">
                <span>Всего: {sse.batchProgress.total}</span>
                <span>Обработано: {sse.batchProgress.processed}</span>
                <span>Спам: {sse.batchProgress.spam}</span>
              </div>
            )}
            {sse.batchStatus === "completed" && (
              <Button onClick={() => setStep("done")}>Перейти к результатам</Button>
            )}
          </CardContent>
        </Card>
      )}

      {step === "done" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-emerald-500">
              <CheckCircle2 className="h-5 w-5" />
              Готово!
            </CardTitle>
            <CardDescription>
              Все обращения обработаны. Перейдите в «Поиск» для просмотра результатов или
              в «Дашборд» для аналитики.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button variant="outline" onClick={() => { setStep("upload"); setTickets(initialUpload); setManagers(initialUpload); setUnits(initialUpload) }}>
              Загрузить новый пакет
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

/* ─── Sub-components ─── */

function StepBadge({ active, done, label }: { active: boolean; done: boolean; label: string }) {
  return (
    <Badge variant={active ? "default" : done ? "success" : "secondary"}>
      {label}
    </Badge>
  )
}

function UploadCard({
  title,
  description,
  icon: Icon,
  inputRef,
  state,
  onSelect,
}: {
  title: string
  description: string
  icon: React.ComponentType<{ className?: string }>
  inputRef: React.RefObject<HTMLInputElement | null>
  state: UploadState
  onSelect: (file: File) => void
}) {
  return (
    <Card
      className="cursor-pointer hover:border-primary/50 transition-colors"
      onClick={() => inputRef.current?.click()}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".csv"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0]
          if (f) onSelect(f)
        }}
      />
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon className="h-4 w-4" />
          {title}
        </CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        {state.loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Загрузка...
          </div>
        )}
        {state.result && (
          <div className="flex items-center gap-2 text-sm text-emerald-500">
            <CheckCircle2 className="h-4 w-4" />
            {"batch_id" in state.result
              ? `${(state.result as IngestTicketsResponse).processed_rows} строк`
              : `${(state.result as IngestManagersResponse).total_imported} записей`}
          </div>
        )}
        {state.error && (
          <div className="flex items-center gap-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4" />
            {state.error}
          </div>
        )}
        {!state.loading && !state.result && !state.error && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Upload className="h-4 w-4" />
            Нажмите для выбора файла
          </div>
        )}
      </CardContent>
    </Card>
  )
}
