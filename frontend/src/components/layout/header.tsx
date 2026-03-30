import { NavLink } from "react-router-dom"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useEvaluationStats, useClarifications, useStartScrape } from "@/lib/queries"
import { RefreshCw } from "lucide-react"

const navItems = [
  { to: "/uebersicht", label: "Übersicht" },
  { to: "/stellen", label: "Stellen" },
  { to: "/klaerungsbedarf", label: "Klärungsbedarf" },
  { to: "/analytics", label: "Analytics" },
  { to: "/steuerung", label: "Steuerung" },
]

export function Header() {
  const stats = useEvaluationStats()
  const clarifications = useClarifications()
  const startScrape = useStartScrape()

  const evalData = stats.data as Record<string, unknown> | undefined
  const clarifData = clarifications.data as Record<string, unknown> | undefined

  const newCount = evalData
    ? (evalData.total_jobs as number) - (evalData.evaluated as number)
    : 0
  const urgentCount = clarifData
    ? (clarifData.urgent as unknown[])?.length ?? 0
    : 0
  const clarifTotal = clarifData ? (clarifData.total as number) ?? 0 : 0

  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 sm:px-6 lg:px-8">
        {/* Linke Seite: Badges */}
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">Job Agent</h1>
          {newCount > 0 && (
            <Badge variant="default">{newCount} neu</Badge>
          )}
          {clarifTotal > 0 && (
            <Badge variant="secondary">{clarifTotal} Klärung</Badge>
          )}
          {urgentCount > 0 && (
            <Badge variant="destructive">{urgentCount} dringend</Badge>
          )}
        </div>

        {/* Mitte: Navigation */}
        <nav className="flex gap-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Rechte Seite: Scan-Button */}
        <Button
          variant="outline"
          size="sm"
          onClick={() => startScrape.mutate(undefined)}
          disabled={startScrape.isPending}
        >
          <RefreshCw className={`mr-1.5 h-4 w-4 ${startScrape.isPending ? "animate-spin" : ""}`} />
          Scan starten
        </Button>
      </div>
    </header>
  )
}
