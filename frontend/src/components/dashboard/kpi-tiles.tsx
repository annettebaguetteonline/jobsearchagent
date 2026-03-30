import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

interface KpiTilesProps {
  stats: Record<string, unknown> | undefined
  isLoading: boolean
  isError?: boolean
}

export function KpiTiles({ stats, isLoading, isError }: KpiTilesProps) {
  if (isLoading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}><CardContent className="p-4"><Skeleton className="h-12 w-full" /></CardContent></Card>
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <div className="rounded-lg border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
        Statistiken konnten nicht geladen werden.
      </div>
    )
  }

  const tiles = [
    {
      label: "Noch nicht evaluiert",
      value: stats ? (stats.total_jobs as number) - (stats.evaluated as number) : 0,
      color: "text-blue-600",
    },
    {
      label: "Stage 1 bestanden",
      value: (stats?.stage1_passed as number) ?? 0,
      color: "text-green-600",
    },
    {
      label: "Stage 2 bewertet",
      value: (stats?.stage2_completed as number) ?? 0,
      color: "text-purple-600",
    },
    {
      label: "\u00D8 Score",
      value: (stats?.avg_score as number)?.toFixed(1) ?? "\u2014",
      color: "text-orange-600",
    },
  ]

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map((tile) => (
        <Card key={tile.label}>
          <CardContent className="p-4">
            <p className="text-sm text-muted-foreground">{tile.label}</p>
            <p className={`text-2xl font-bold ${tile.color}`}>{tile.value}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
