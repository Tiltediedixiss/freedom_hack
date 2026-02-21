import { useEffect, useState } from "react"
import {
  BarChart3,
  Ticket,
  ShieldAlert,
  Users,
  UserCheck,
  Loader2,
  RefreshCw,
} from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  getDashboardStats,
  getTypeDistribution,
  getSentimentDistribution,
  getManagerLoad,
} from "@/lib/api"
import type { DashboardStats, ManagerLoad } from "@/types"
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts"

const COLORS = ["#3b82f6", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#ef4444", "#ec4899", "#6366f1"]

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [types, setTypes] = useState<Record<string, number>>({})
  const [sentiment, setSentiment] = useState<Record<string, number>>({})
  const [managers, setManagers] = useState<ManagerLoad[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const loadAll = async () => {
    setLoading(true)
    setError(null)
    try {
      const [s, t, se, m] = await Promise.all([
        getDashboardStats(),
        getTypeDistribution(),
        getSentimentDistribution(),
        getManagerLoad(),
      ])
      setStats(s)
      setTypes(t)
      setSentiment(se)
      setManagers(m)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
  }, [])

  const typePieData = Object.entries(types).map(([name, value]) => ({ name, value }))
  const sentimentPieData = Object.entries(sentiment).map(([name, value]) => ({ name, value }))
  const managerBarData = managers.map((m) => ({
    name: m.full_name.split(" ").slice(0, 2).join(" "),
    Нагрузка: m.csv_load,
    Стресс: +(m.stress_score * 100).toFixed(0),
  }))

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-4">
        <p className="text-destructive">{error}</p>
        <Button variant="outline" onClick={loadAll}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Повторить
        </Button>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Дашборд</h2>
          <p className="text-muted-foreground text-sm mt-1">
            Общая аналитика по обработанным обращениям
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={loadAll}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Обновить
        </Button>
      </div>

      {/* Stats cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard icon={Ticket} label="Всего обращений" value={stats.total_tickets} />
          <StatCard icon={ShieldAlert} label="Спам" value={stats.spam_tickets} color="text-amber-500" />
          <StatCard icon={Users} label="Менеджеров" value={stats.total_managers} />
          <StatCard icon={UserCheck} label="Назначений" value={stats.total_assignments} />
        </div>
      )}

      {/* Status breakdown */}
      {stats && stats.by_status && Object.keys(stats.by_status).length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">По статусу</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(stats.by_status).map(([status, count]) => (
                <Badge key={status} variant="outline" className="text-sm py-1 px-3">
                  {status}: {count}
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Type distribution */}
        {typePieData.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Типы обращений</CardTitle>
              <CardDescription>Распределение по категориям</CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie
                    data={typePieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={2}
                    label={({ name, percent }) => `${name} (${(percent! * 100).toFixed(0)}%)`}
                    labelLine={{ strokeWidth: 0.5 }}
                  >
                    {typePieData.map((_, idx) => (
                      <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: "8px" }}
                    labelStyle={{ color: "hsl(var(--foreground))" }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        )}

        {/* Sentiment distribution */}
        {sentimentPieData.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Тональность</CardTitle>
              <CardDescription>Эмоциональная окраска обращений</CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={280}>
                <PieChart>
                  <Pie
                    data={sentimentPieData}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={2}
                    label={({ name, percent }) => `${name} (${(percent! * 100).toFixed(0)}%)`}
                    labelLine={{ strokeWidth: 0.5 }}
                  >
                    {sentimentPieData.map((_, idx) => (
                      <Cell key={idx} fill={COLORS[(idx + 3) % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: "8px" }}
                    labelStyle={{ color: "hsl(var(--foreground))" }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Manager load bar chart */}
      {managerBarData.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Нагрузка менеджеров</CardTitle>
            <CardDescription>Текущая загрузка и уровень стресса</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={managerBarData} layout="vertical" margin={{ left: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis type="number" stroke="hsl(var(--muted-foreground))" fontSize={12} />
                <YAxis
                  dataKey="name"
                  type="category"
                  width={120}
                  stroke="hsl(var(--muted-foreground))"
                  fontSize={12}
                  tick={{ fill: "hsl(var(--muted-foreground))" }}
                />
                <Tooltip
                  contentStyle={{ background: "hsl(var(--card))", border: "1px solid hsl(var(--border))", borderRadius: "8px" }}
                  labelStyle={{ color: "hsl(var(--foreground))" }}
                />
                <Legend />
                <Bar dataKey="Нагрузка" fill="#3b82f6" radius={[0, 4, 4, 0]} />
                <Bar dataKey="Стресс" fill="#f59e0b" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      )}

      {/* Manager table */}
      {managers.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Менеджеры</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-muted-foreground text-left">
                    <th className="py-2 pr-4 font-medium">ФИО</th>
                    <th className="py-2 pr-4 font-medium">Должность</th>
                    <th className="py-2 pr-4 font-medium">Навыки</th>
                    <th className="py-2 pr-4 font-medium text-right">Нагрузка</th>
                    <th className="py-2 font-medium text-right">Стресс</th>
                  </tr>
                </thead>
                <tbody>
                  {managers.map((m) => (
                    <tr key={m.id} className="border-b border-border/50 hover:bg-muted/30 transition-colors">
                      <td className="py-2 pr-4 font-medium">{m.full_name}</td>
                      <td className="py-2 pr-4 text-muted-foreground">{m.position || "—"}</td>
                      <td className="py-2 pr-4">
                        <div className="flex flex-wrap gap-1">
                          {m.skills?.map((s) => (
                            <Badge key={s} variant="outline" className="text-xs">{s}</Badge>
                          ))}
                        </div>
                      </td>
                      <td className="py-2 pr-4 text-right">{m.csv_load}</td>
                      <td className="py-2 text-right">
                        <Badge variant={m.stress_score > 0.7 ? "destructive" : m.stress_score > 0.4 ? "warning" : "success"}>
                          {(m.stress_score * 100).toFixed(0)}%
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

/* ─── Sub-components ─── */

function StatCard({
  icon: Icon,
  label,
  value,
  color,
}: {
  icon: React.ComponentType<{ className?: string }>
  label: string
  value: number
  color?: string
}) {
  return (
    <Card>
      <CardContent className="pt-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{label}</p>
            <p className={`text-2xl font-bold ${color || ""}`}>{value}</p>
          </div>
          <Icon className={`h-8 w-8 ${color || "text-muted-foreground/30"}`} />
        </div>
      </CardContent>
    </Card>
  )
}
