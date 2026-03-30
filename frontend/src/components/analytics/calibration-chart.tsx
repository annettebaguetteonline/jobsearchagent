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
  ReferenceLine,
} from "recharts"
import { useAnalyticsCalibration } from "@/lib/queries"

interface CalibrationEntry {
  strategy: string
  avg_score_delta: number
  sample_count: number
  avg_model_score: number
}

interface CalibrationData {
  entries: CalibrationEntry[]
}

function deltaColor(delta: number): string {
  const abs = Math.abs(delta)
  if (abs <= 0.5) return "#16a34a"
  if (abs <= 1.5) return "#ca8a04"
  return "#dc2626"
}

export function CalibrationChart() {
  const { data, isLoading } = useAnalyticsCalibration()

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Modell-Kalibrierung</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-48 w-full" />
        </CardContent>
      </Card>
    )
  }

  const entries = (data as CalibrationData | undefined)?.entries ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Modell-Kalibrierung</CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            Noch keine Kalibrierungsdaten verfügbar
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={entries} margin={{ bottom: 30 }}>
              <XAxis
                dataKey="strategy"
                tick={{ fontSize: 11 }}
                angle={-30}
                textAnchor="end"
                interval={0}
              />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip
                formatter={(value: number, _name: string, props: { payload?: CalibrationEntry }) => [
                  `${value > 0 ? "+" : ""}${value.toFixed(2)} (n=${props.payload?.sample_count ?? 0})`,
                  "Ø Score-Delta",
                ]}
              />
              <ReferenceLine y={0} stroke="#94a3b8" strokeDasharray="3 3" />
              <Bar dataKey="avg_score_delta" name="Ø Score-Delta" radius={[4, 4, 0, 0]}>
                {entries.map((entry, i) => (
                  <Cell key={i} fill={deltaColor(entry.avg_score_delta)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
