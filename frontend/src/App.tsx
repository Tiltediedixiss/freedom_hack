import { Routes, Route, NavLink } from "react-router-dom"
import { Flame, Upload, Activity, Search, BarChart3 } from "lucide-react"
import { useSSE } from "@/hooks/useSSE"
import UploadPage from "@/pages/UploadPage"
import PipelinePage from "@/pages/PipelinePage"
import LookupPage from "@/pages/LookupPage"
import DashboardPage from "@/pages/DashboardPage"
import { cn } from "@/lib/utils"

const navItems = [
  { to: "/", icon: Upload, label: "Загрузка" },
  { to: "/pipeline", icon: Activity, label: "Конвейер" },
  { to: "/lookup", icon: Search, label: "Поиск" },
  { to: "/dashboard", icon: BarChart3, label: "Дашборд" },
]

export default function App() {
  const sse = useSSE()

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 border-r bg-card flex flex-col">
        <div className="flex items-center gap-2 px-4 py-5 border-b">
          <Flame className="h-6 w-6 text-primary" />
          <div>
            <h1 className="font-bold text-sm tracking-tight">F.I.R.E.</h1>
            <p className="text-[10px] text-muted-foreground leading-tight">
              Freedom Intelligent Routing Engine
            </p>
          </div>
        </div>

        <nav className="flex-1 p-2 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                )
              }
            >
              <item.icon className="h-4 w-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* SSE status */}
        <div className="border-t px-4 py-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                sse.isConnected ? "bg-emerald-500" : "bg-red-500 animate-pulse"
              )}
            />
            {sse.isConnected ? "SSE подключён" : "Отключён"}
          </div>
          {sse.batchStatus === "processing" && sse.batchProgress && (
            <div className="mt-1 text-xs text-muted-foreground">
              {sse.batchProgress.processed}/{sse.batchProgress.total} обработано
            </div>
          )}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/" element={<UploadPage sse={sse} />} />
          <Route path="/pipeline" element={<PipelinePage sse={sse} />} />
          <Route path="/lookup" element={<LookupPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
        </Routes>
      </main>
    </div>
  )
}
