import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts"
import { useAnalyticsSourceScores } from "@/lib/queries"

interface SourceScoresData {
  sources: Array<{ source_name: string; avg_score: number; job_count: number }>
}

function scoreColor(score: number): string {
  if (score >= 7) return "#16a34a"
  if (score >= 5) return "#ca8a04"
  return "#dc2626"
}

export function SourceScoresChart() {
  const { data, isLoading } = useAnalyticsSourceScores()

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Score nach Quelle</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-48 w-full" />
        </CardContent>
      </Card>
    )
  }

  const sources = (data as SourceScoresData | undefined)?.sources ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Score nach Quelle</CardTitle>
      </CardHeader>
      <CardContent>
        {sources.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Keine Daten verfügbar</p>
        ) : (
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={sources} margin={{ bottom: 30 }}>
              <XAxis
                dataKey="source_name"
                tick={{ fontSize: 11 }}
                angle={-30}
                textAnchor="end"
                interval={0}
              />
              <YAxis domain={[0, 10]} tick={{ fontSize: 12 }} />
              <Tooltip
                formatter={(value: number, _name: string, props: { payload?: { job_count?: number } }) => [
                  `${value.toFixed(2)} (${props.payload?.job_count ?? 0} Jobs)`,
                  "Ø Score",
                ]}
              />
              <Bar dataKey="avg_score" name="Ø Score" radius={[4, 4, 0, 0]}>
                {sources.map((entry, i) => (
                  <Cell key={i} fill={scoreColor(entry.avg_score)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
