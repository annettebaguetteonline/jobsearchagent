import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { useStartScrape, useScrapeRun, useCancelScrape } from "@/lib/queries"

const ALL_SOURCES = [
  "service_bund",
  "arbeitsagentur",
  "interamt",
  "arbeitnow",
  "stellenmarkt",
  "adzuna",
  "jooble",
  "jobboerse",
  "kimeta",
] as const

type Source = (typeof ALL_SOURCES)[number]

const SOURCE_LABELS: Record<Source, string> = {
  service_bund: "Service Bund",
  arbeitsagentur: "Arbeitsagentur",
  interamt: "Interamt",
  arbeitnow: "Arbeitnow",
  stellenmarkt: "Stellenmarkt",
  adzuna: "Adzuna",
  jooble: "Jooble",
  jobboerse: "Jobbörse",
  kimeta: "Kimeta",
}

interface ScrapeStats {
  fetched: number
  new: number
  duplicate: number
  skipped: number
  errors: number
  expired: number
}

interface ScrapeRunData {
  id: number
  started_at: string
  finished_at: string | null
  status: string
  sources_run: string[] | null
  stats: ScrapeStats | null
  error_log: string[] | null
}

export function ScrapingSection() {
  const [selectedSources, setSelectedSources] = useState<Source[]>([...ALL_SOURCES])
  const [runId, setRunId] = useState<number | null>(null)
  const [plannedSources, setPlannedSources] = useState<Source[]>([])

  const startScrape = useStartScrape()
  const cancelScrape = useCancelScrape()
  const scrapeRun = useScrapeRun(runId, runId !== null)

  const runData = scrapeRun.data as ScrapeRunData | undefined
  const isRunning = runData?.status === "running"
  const isCancelled = runData?.status === "cancelled"
  const isFailed = runData?.status === "failed"

  const completedSources = (runData?.sources_run ?? []) as Source[]
  const completedCount = completedSources.length
  const totalCount = plannedSources.length

  const toggleSource = (source: Source) => {
    setSelectedSources((prev) =>
      prev.includes(source) ? prev.filter((s) => s !== source) : [...prev, source],
    )
  }

  const toggleAll = () => {
    setSelectedSources(selectedSources.length === ALL_SOURCES.length ? [] : [...ALL_SOURCES])
  }

  const handleStart = () => {
    const sources = selectedSources.length === ALL_SOURCES.length ? undefined : selectedSources
    startScrape.mutate(sources, {
      onSuccess: (data) => {
        const resp = data as { run_id: number; sources: string[] }
        setRunId(resp.run_id)
        setPlannedSources(resp.sources as Source[])
      },
    })
  }

  const handleCancel = () => {
    if (runId !== null) {
      cancelScrape.mutate(runId)
    }
  }

  const statusColor = isRunning
    ? "text-yellow-600"
    : isCancelled || isFailed
      ? "text-destructive"
      : "text-green-600"

  const statusLabel: Record<string, string> = {
    running: "Läuft",
    finished: "Abgeschlossen",
    cancelled: "Abgebrochen",
    failed: "Fehlgeschlagen",
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Scraping</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Quellenauswahl */}
        {!isRunning && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">Quellen</span>
              <button
                onClick={toggleAll}
                className="text-xs text-primary hover:underline"
              >
                {selectedSources.length === ALL_SOURCES.length ? "Keine" : "Alle"}
              </button>
            </div>
            <div className="grid grid-cols-2 gap-1">
              {ALL_SOURCES.map((source) => (
                <label
                  key={source}
                  className="flex cursor-pointer items-center gap-1.5 rounded px-1.5 py-1 text-xs hover:bg-muted"
                >
                  <input
                    type="checkbox"
                    checked={selectedSources.includes(source)}
                    onChange={() => toggleSource(source)}
                    className="h-3 w-3 accent-primary"
                  />
                  {SOURCE_LABELS[source]}
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Aktions-Buttons */}
        <div className="flex gap-2">
          <Button
            size="sm"
            onClick={handleStart}
            disabled={startScrape.isPending || isRunning || selectedSources.length === 0}
          >
            {isRunning ? "Läuft..." : "Scan starten"}
          </Button>
          {isRunning && (
            <Button
              size="sm"
              variant="destructive"
              onClick={handleCancel}
              disabled={cancelScrape.isPending}
            >
              Abbrechen
            </Button>
          )}
        </div>

        {/* Laufender Fortschritt */}
        {isRunning && totalCount > 0 && (
          <div className="space-y-1">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>Fortschritt</span>
              <span>{completedCount}/{totalCount} Quellen</span>
            </div>
            <div className="flex flex-wrap gap-1">
              {plannedSources.map((source) => {
                const done = completedSources.includes(source)
                return (
                  <Badge
                    key={source}
                    variant={done ? "default" : "outline"}
                    className={`text-xs ${done ? "bg-green-100 text-green-800 border-transparent" : "text-muted-foreground"}`}
                  >
                    {SOURCE_LABELS[source]}
                  </Badge>
                )
              })}
            </div>
          </div>
        )}

        {/* Status & Statistiken */}
        {runData && (
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-muted-foreground">Status:</span>
              <span className={statusColor}>
                {statusLabel[runData.status] ?? runData.status}
              </span>
            </div>

            {runData.stats && (
              <div className="grid grid-cols-3 gap-2">
                <div className="rounded bg-muted p-2 text-center">
                  <div className="text-base font-bold">{runData.stats.new}</div>
                  <div className="text-xs text-muted-foreground">Neu</div>
                </div>
                <div className="rounded bg-muted p-2 text-center">
                  <div className="text-base font-bold">{runData.stats.duplicate}</div>
                  <div className="text-xs text-muted-foreground">Duplikate</div>
                </div>
                <div className="rounded bg-muted p-2 text-center">
                  <div className="text-base font-bold">{runData.stats.errors}</div>
                  <div className="text-xs text-muted-foreground">Fehler</div>
                </div>
                <div className="rounded bg-muted p-2 text-center">
                  <div className="text-base font-bold">{runData.stats.fetched}</div>
                  <div className="text-xs text-muted-foreground">Gesamt</div>
                </div>
                <div className="rounded bg-muted p-2 text-center">
                  <div className="text-base font-bold">{runData.stats.expired}</div>
                  <div className="text-xs text-muted-foreground">Abgelaufen</div>
                </div>
              </div>
            )}

            {runData.finished_at && (
              <p className="text-xs text-muted-foreground">
                {isCancelled ? "Abgebrochen" : "Abgeschlossen"}:{" "}
                {new Date(runData.finished_at).toLocaleTimeString("de-DE")}
              </p>
            )}

            {runData.error_log && runData.error_log.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer text-destructive">
                  {runData.error_log.length} Fehler
                </summary>
                <ul className="mt-1 space-y-0.5 text-muted-foreground">
                  {runData.error_log.map((e, i) => (
                    <li key={i} className="truncate">{e}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        )}

        {startScrape.isError && (
          <p className="text-sm text-destructive">Fehler beim Starten des Scans</p>
        )}
      </CardContent>
    </Card>
  )
}
