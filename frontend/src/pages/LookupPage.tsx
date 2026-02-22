import { useState } from "react"
import {
  Search,
  User,
  MapPin,
  Brain,
  Building2,
  UserCheck,
  AlertTriangle,
  ShieldAlert,
  Loader2,
  ChevronRight,
  Hash,
} from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { cn } from "@/lib/utils"
import { getTicketByRow } from "@/lib/api"
import type { TicketLookup } from "@/types"
import ArchitectureModal from "@/components/ui/archModal"

export default function LookupPage() {
  const [rowInput, setRowInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<TicketLookup | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showArchitectureModal, setShowArchitectureModal] = useState(true)

  const handleSearch = async () => {
    const row = parseInt(rowInput, 10)
    if (isNaN(row) || row < 0) {
      setError("Введите корректный номер строки (≥ 0)")
      return
    }
    setError(null)
    setData(null)
    setLoading(true)
    try {
      const result = await getTicketByRow(row)
      setData(result)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Поиск обращения</h2>
        <p className="text-muted-foreground text-sm mt-1">
          Найдите обращение по номеру строки из CSV и просмотрите полную цепочку обработки
        </p>
      </div>

      {/* Search bar */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex gap-3">
            <div className="relative flex-1">
              <Hash className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Номер строки CSV (например, 0, 1, 2...)"
                value={rowInput}
                onChange={(e) => setRowInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                className="pl-9"
              />
            </div>
            <Button onClick={handleSearch} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4 mr-2" />}
              Найти
            </Button>
          </div>
          {error && (
            <p className="text-sm text-destructive mt-2 flex items-center gap-1">
              <AlertTriangle className="h-3.5 w-3.5" />
              {error}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Results */}
      {data && (
        <Tabs defaultValue="ticket">
          <TabsList>
            <TabsTrigger value="ticket">Обращение</TabsTrigger>
            <TabsTrigger value="analysis">AI-анализ</TabsTrigger>
            <TabsTrigger value="assignment">Назначение</TabsTrigger>
          </TabsList>

          {/* ── Обращение ── */}
          <TabsContent value="ticket">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <User className="h-5 w-5" />
                  Обращение #{data.ticket.csv_row_index}
                </CardTitle>
                <CardDescription>
                  ID: {data.ticket.id}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="flex flex-wrap gap-2">
                  <Badge>{data.ticket.status}</Badge>
                  {data.ticket.is_spam && <Badge variant="warning">Спам ({(data.ticket.spam_probability * 100).toFixed(0)}%)</Badge>}
                  {data.ticket.ticket_type && <Badge variant="secondary">{data.ticket.ticket_type}</Badge>}
                  {data.ticket.segment && <Badge variant="outline">{data.ticket.segment}</Badge>}
                </div>

                <Separator />

                <div className="grid grid-cols-2 gap-4 text-sm">
                  <Field label="GUID" value={data.ticket.guid} />
                  <Field label="Пол" value={data.ticket.gender} />
                  <Field label="Дата рождения" value={data.ticket.birth_date} />
                  <Field label="Возраст" value={data.ticket.age?.toString()} />
                  <Field label="Сегмент" value={data.ticket.segment} />
                  <Field label="Длина текста" value={data.ticket.text_length?.toString()} />
                </div>

                <Separator />

                <div className="space-y-2">
                  <p className="text-sm font-medium text-muted-foreground">Описание (оригинал)</p>
                  <p className="text-sm bg-muted/50 rounded-md p-3 whitespace-pre-wrap">
                    {data.ticket.description || "—"}
                  </p>
                </div>

                {data.ticket.description_anonymized && (
                  <div className="space-y-2">
                    <p className="text-sm font-medium text-muted-foreground">Описание (анонимизированное)</p>
                    <p className="text-sm bg-muted/50 rounded-md p-3 whitespace-pre-wrap">
                      {data.ticket.description_anonymized}
                    </p>
                  </div>
                )}

                <Separator />

                <div className="space-y-2">
                  <p className="text-sm font-medium text-muted-foreground flex items-center gap-1">
                    <MapPin className="h-3.5 w-3.5" /> Адрес
                  </p>
                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <Field label="Страна" value={data.ticket.country} />
                    <Field label="Регион" value={data.ticket.region} />
                    <Field label="Город" value={data.ticket.city} />
                    <Field label="Улица" value={data.ticket.street} />
                    <Field label="Дом" value={data.ticket.house} />
                    <Field label="Статус адреса" value={data.ticket.address_status} />
                    <Field label="Широта" value={data.ticket.latitude?.toFixed(6)} />
                    <Field label="Долгота" value={data.ticket.longitude?.toFixed(6)} />
                  </div>
                </div>

                {data.ticket.attachments && data.ticket.attachments.length > 0 && (
                  <>
                    <Separator />
                    <div className="space-y-2">
                      <p className="text-sm font-medium text-muted-foreground">Вложения</p>
                      <div className="flex flex-wrap gap-1">
                        {data.ticket.attachments.map((a, i) => (
                          <Badge key={i} variant="outline">{a}</Badge>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ── AI-анализ ── */}
          <TabsContent value="analysis">
            {data.ai_analysis ? (
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Brain className="h-5 w-5" />
                    AI-анализ
                  </CardTitle>
                  <CardDescription>
                    Обработка: {data.ai_analysis.processing_time_ms} мс
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="flex flex-wrap gap-2">
                    {data.ai_analysis.detected_type && <Badge>{data.ai_analysis.detected_type}</Badge>}
                    {data.ai_analysis.sentiment && <Badge variant="secondary">{data.ai_analysis.sentiment}</Badge>}
                    {data.ai_analysis.needs_data_change && <Badge variant="warning">Изменение данных</Badge>}
                    {data.ai_analysis.needs_location_routing && <Badge variant="outline">Маршр. по локации</Badge>}
                  </div>

                  <Separator />

                  <div className="grid grid-cols-2 gap-4 text-sm">
                    <Field label="Тип обращения" value={data.ai_analysis.detected_type} />
                    <Field label="Язык" value={data.ai_analysis.language_actual} />
                    <Field label="Смешанный язык" value={data.ai_analysis.language_is_mixed ? "Да" : "Нет"} />
                    <Field label="Тональность" value={data.ai_analysis.sentiment} />
                    <Field label="Уверенность" value={data.ai_analysis.sentiment_confidence?.toFixed(2)} />
                  </div>

                  <Separator />

                  <div className="space-y-2">
                    <p className="text-sm font-medium text-muted-foreground">Краткое содержание</p>
                    <p className="text-sm bg-muted/50 rounded-md p-3 whitespace-pre-wrap">
                      {data.ai_analysis.summary || "—"}
                    </p>
                  </div>

                  {data.ai_analysis.attachment_analysis && (
                    <div className="space-y-2">
                      <p className="text-sm font-medium text-muted-foreground">Анализ вложений</p>
                      <p className="text-sm bg-muted/50 rounded-md p-3 whitespace-pre-wrap">
                        {data.ai_analysis.attachment_analysis}
                      </p>
                    </div>
                  )}

                  <Separator />

                  <div className="space-y-2">
                    <p className="text-sm font-medium text-muted-foreground">Приоритет</p>
                    <div className="grid grid-cols-3 gap-4 text-sm">
                      <Field label="Базовый" value={data.ai_analysis.priority_base?.toString()} />
                      <Field label="Доп. баллы" value={data.ai_analysis.priority_extra?.toString()} />
                      <Field label="Итого" value={data.ai_analysis.priority_final?.toString()} />
                    </div>
                  </div>

                  {data.ai_analysis.anomaly_flags && data.ai_analysis.anomaly_flags.length > 0 && (
                    <>
                      <Separator />
                      <div className="space-y-2">
                        <p className="text-sm font-medium text-muted-foreground flex items-center gap-1">
                          <ShieldAlert className="h-3.5 w-3.5" /> Аномалии
                        </p>
                        <div className="flex flex-wrap gap-1">
                          {data.ai_analysis.anomaly_flags.map((f, i) => (
                            <Badge key={i} variant="destructive">{String(f)}</Badge>
                          ))}
                        </div>
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="py-8 text-center text-muted-foreground">
                  AI-анализ не выполнен для данного обращения
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* ── Назначение ── */}
          <TabsContent value="assignment">
            <div className="space-y-4">
              {data.assignment ? (
                <>
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <UserCheck className="h-5 w-5" />
                        Назначенный менеджер
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      {data.manager ? (
                        <div className="space-y-3">
                          <div className="grid grid-cols-2 gap-4 text-sm">
                            <Field label="ФИО" value={data.manager.full_name} />
                            <Field label="Должность" value={data.manager.position} />
                            <Field label="Навыки" value={data.manager.skills?.join(", ")} />
                            <Field label="Фактор навыков" value={data.manager.skill_factor?.toFixed(2)} />
                            <Field label="Нагрузка (CSV)" value={data.manager.csv_load?.toString()} />
                            <Field label="Стресс-оценка" value={data.manager.stress_score?.toFixed(2)} />
                          </div>
                        </div>
                      ) : (
                        <p className="text-sm text-muted-foreground">Менеджер не найден</p>
                      )}
                    </CardContent>
                  </Card>

                  {data.business_unit && (
                    <Card>
                      <CardHeader>
                        <CardTitle className="flex items-center gap-2">
                          <Building2 className="h-5 w-5" />
                          Офис
                        </CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="grid grid-cols-2 gap-4 text-sm">
                          <Field label="Название" value={data.business_unit.name} />
                          <Field label="Адрес" value={data.business_unit.address} />
                          <Field label="Широта" value={data.business_unit.latitude?.toFixed(6)} />
                          <Field label="Долгота" value={data.business_unit.longitude?.toFixed(6)} />
                        </div>
                      </CardContent>
                    </Card>
                  )}

                  {data.assignment.explanation && (
                    <Card>
                      <CardHeader>
                        <CardTitle className="text-base">Обоснование</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <p className="text-sm whitespace-pre-wrap bg-muted/50 rounded-md p-3">
                          {data.assignment.explanation}
                        </p>
                      </CardContent>
                    </Card>
                  )}
                </>
              ) : (
                <Card>
                  <CardContent className="py-8 text-center text-muted-foreground">
                    Назначение ещё не выполнено для данного обращения
                  </CardContent>
                </Card>
              )}
            </div>
          </TabsContent>
        </Tabs>
      )}

      {!data && !loading && !error && (
        <div className="text-center py-16 text-muted-foreground">
          <Search className="h-12 w-12 mx-auto mb-3 opacity-30" />
          <p>Введите номер строки CSV для поиска обращения</p>
        </div>
      )}
      <ArchitectureModal show={showArchitectureModal} onClose={() => setShowArchitectureModal(false)} />
    </div>
  )
}

/* ─── Helper ─── */

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <p className="text-muted-foreground text-xs uppercase tracking-wider">{label}</p>
      <p className="font-medium">{value || "—"}</p>
    </div>
  )
}
