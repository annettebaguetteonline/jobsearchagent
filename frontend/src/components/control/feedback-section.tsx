import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { useFeedbackStats } from "@/lib/queries"

interface PreferencePattern {
  type: string
  key: string
  value: string | null
  confidence: number | null
  sample_count: number | null
}

interface FeedbackStatsData {
  total: number
  by_decision: Record<string, number>
  preference_patterns: PreferencePattern[]
}

const DECISION_COLORS: Record<string, string> = {
  APPLY: "bg-green-100 text-green-800 border-transparent",
  MAYBE: "bg-yellow-100 text-yellow-800 border-transparent",
  SKIP: "bg-red-100 text-red-800 border-transparent",
  IGNORE: "bg-gray-100 text-gray-800 border-transparent",
}

export function FeedbackSection() {
  const statsQuery = useFeedbackStats()
  const stats = statsQuery.data as FeedbackStatsData | undefined

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Feedback</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {stats && (
          <>
            <div className="text-sm">
              <span className="text-muted-foreground">Gesamt: </span>
              <span className="font-semibold">{stats.total}</span>
            </div>

            {Object.keys(stats.by_decision).length > 0 && (
              <div className="flex flex-wrap gap-1">
                {Object.entries(stats.by_decision).map(([dec, count]) => (
                  <Badge
                    key={dec}
                    className={
                      DECISION_COLORS[dec] ?? "bg-gray-100 text-gray-800 border-transparent"
                    }
                  >
                    {dec}: {count}
                  </Badge>
                ))}
              </div>
            )}

            {stats.preference_patterns.length > 0 && (
              <div className="space-y-1">
                <p className="text-xs font-medium text-muted-foreground">Präferenzmuster</p>
                {stats.preference_patterns.map((p, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">
                      {p.type}:{" "}
                      <span className="font-medium text-foreground">{p.key}</span>
                      {p.value != null ? ` = ${p.value}` : ""}
                    </span>
                    {p.confidence !== null && (
                      <span className="text-muted-foreground">
                        {(p.confidence * 100).toFixed(0)}%
                        {p.sample_count !== null ? ` (${p.sample_count})` : ""}
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {stats.total === 0 && (
              <p className="text-xs text-muted-foreground">Noch kein Feedback vorhanden</p>
            )}
          </>
        )}

        <Button size="sm" variant="outline" disabled>
          Export (demnächst)
        </Button>
      </CardContent>
    </Card>
  )
}
