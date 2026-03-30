import { useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Select } from "@/components/ui/select"
import { useEvaluationStats, useRunStage1, useRunStage2, useProfile, useExtractProfile } from "@/lib/queries"

interface EvaluationStatsData {
  total_jobs: number
  evaluated: number
  stage1_passed: number
  stage1_skipped: number
  stage2_completed: number
  avg_score: number | null
  recommendations: Record<string, number>
}

const STRATEGIES = [
  { value: "structured_core", label: "Structured Core" },
  { value: "narrative", label: "Narrative" },
  { value: "technical", label: "Technical" },
]

const RECOMMENDATION_COLORS: Record<string, string> = {
  APPLY: "bg-green-100 text-green-800 border-transparent",
  MAYBE: "bg-yellow-100 text-yellow-800 border-transparent",
  SKIP: "bg-red-100 text-red-800 border-transparent",
}

export function EvaluationSection() {
  const [strategy, setStrategy] = useState("structured_core")
  const statsQuery = useEvaluationStats()
  const runStage1 = useRunStage1()
  const runStage2 = useRunStage2()
  const profileQuery = useProfile()
  const extractProfile = useExtractProfile()

  const stats = statsQuery.data as EvaluationStatsData | undefined

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Evaluierung</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Actions */}
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            onClick={() => runStage1.mutate(undefined)}
            disabled={runStage1.isPending}
          >
            {runStage1.isPending ? "Stage 1 läuft..." : "Stage 1 starten"}
          </Button>
          <Button
            size="sm"
            onClick={() => runStage2.mutate({ strategy })}
            disabled={runStage2.isPending}
          >
            {runStage2.isPending ? "Stage 2 läuft..." : "Stage 2 starten"}
          </Button>
          <Select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
            className="h-9 w-40 text-xs"
          >
            {STRATEGIES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
        </div>

        {/* Stage 1 result feedback */}
        {runStage1.isSuccess && (
          <p className="text-xs text-green-600">
            Stage 1 abgeschlossen:{" "}
            {(runStage1.data as { processed: number; passed: number }).passed} bestanden
          </p>
        )}
        {runStage2.isSuccess && (
          <p className="text-xs text-green-600">Stage 2 gestartet</p>
        )}

        {/* Stats */}
        {stats && (
          <div className="space-y-3 text-sm">
            <div className="grid grid-cols-2 gap-2">
              <div className="rounded bg-muted p-2">
                <div className="font-semibold">{stats.total_jobs}</div>
                <div className="text-xs text-muted-foreground">Jobs aktiv</div>
              </div>
              <div className="rounded bg-muted p-2">
                <div className="font-semibold">{stats.evaluated}</div>
                <div className="text-xs text-muted-foreground">Evaluiert</div>
              </div>
              <div className="rounded bg-muted p-2">
                <div className="font-semibold">{stats.stage1_passed}</div>
                <div className="text-xs text-muted-foreground">Stage 1 ✓</div>
              </div>
              <div className="rounded bg-muted p-2">
                <div className="font-semibold">
                  {stats.avg_score !== null ? stats.avg_score.toFixed(1) : "—"}
                </div>
                <div className="text-xs text-muted-foreground">Ø Score</div>
              </div>
            </div>

            {Object.keys(stats.recommendations).length > 0 && (
              <div className="flex flex-wrap gap-1">
                {Object.entries(stats.recommendations).map(([rec, count]) => (
                  <Badge
                    key={rec}
                    className={
                      RECOMMENDATION_COLORS[rec] ?? "bg-gray-100 text-gray-800 border-transparent"
                    }
                  >
                    {rec}: {count}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Profile */}
        <div className="border-t pt-3 text-sm">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-muted-foreground">Profil</span>
              {profileQuery.isError && (
                <span className="ml-2 text-xs text-muted-foreground">— nicht vorhanden</span>
              )}
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => extractProfile.mutate()}
              disabled={extractProfile.isPending}
            >
              {extractProfile.isPending ? "Extrahiere..." : "Neu extrahieren"}
            </Button>
          </div>
          {extractProfile.isSuccess && (
            <p className="mt-1 text-xs text-green-600">Extraktion gestartet</p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
