import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { useLocationStats, useResolveLocationBatch } from "@/lib/queries"

interface LocationStatsData {
  jobs_total: number
  jobs_resolved: number
  jobs_unknown: number
  jobs_failed: number
  companies_total: number
  companies_with_address: number
  companies_without_address: number
  transit_cache_entries: number
}

export function LocationSection() {
  const statsQuery = useLocationStats()
  const resolveBatch = useResolveLocationBatch()

  const stats = statsQuery.data as LocationStatsData | undefined

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Location</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Button
          size="sm"
          onClick={() => resolveBatch.mutate()}
          disabled={resolveBatch.isPending}
        >
          {resolveBatch.isPending ? "Läuft..." : "Batch auflösen"}
        </Button>

        {resolveBatch.isSuccess && (
          <p className="text-xs text-green-600">
            {(resolveBatch.data as { processed: number }).processed} Jobs verarbeitet
          </p>
        )}

        {stats && (
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="rounded bg-muted p-2">
              <div className="font-semibold">{stats.jobs_resolved}</div>
              <div className="text-xs text-muted-foreground">Aufgelöst</div>
            </div>
            <div className="rounded bg-muted p-2">
              <div className="font-semibold">{stats.jobs_unknown}</div>
              <div className="text-xs text-muted-foreground">Unbekannt</div>
            </div>
            <div className="rounded bg-muted p-2">
              <div className="font-semibold">{stats.jobs_failed}</div>
              <div className="text-xs text-muted-foreground">Fehlgeschlagen</div>
            </div>
            <div className="rounded bg-muted p-2">
              <div className="font-semibold">{stats.companies_with_address}</div>
              <div className="text-xs text-muted-foreground">Firmen mit Adresse</div>
            </div>
            <div className="rounded bg-muted p-2 col-span-2">
              <div className="font-semibold">{stats.transit_cache_entries}</div>
              <div className="text-xs text-muted-foreground">Transit-Cache Einträge</div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
