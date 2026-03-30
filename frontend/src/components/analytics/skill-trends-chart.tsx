import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts"
import { useAnalyticsSkillTrends } from "@/lib/queries"

interface SkillTrend {
  skill: string
  period: string
  count: number
}

interface SkillTrendsData {
  trends: SkillTrend[]
  top_skills: string[]
}

const COLORS = [
  "#2563eb", "#16a34a", "#dc2626", "#ca8a04", "#7c3aed",
  "#0891b2", "#be185d", "#ea580c", "#65a30d", "#0d9488",
]

export function SkillTrendsChart() {
  const { data, isLoading } = useAnalyticsSkillTrends()

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top-Skills</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-48 w-full" />
        </CardContent>
      </Card>
    )
  }

  const trendsData = data as SkillTrendsData | undefined
  const topSkills = trendsData?.top_skills ?? []
  const trends = trendsData?.trends ?? []

  if (topSkills.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Top-Skills</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="py-8 text-center text-sm text-muted-foreground">
            Noch keine Trend-Daten verfügbar
          </p>
        </CardContent>
      </Card>
    )
  }

  // Pivot: period → { skill: count }
  const periodMap = new Map<string, Record<string, number>>()
  for (const t of trends) {
    if (!periodMap.has(t.period)) periodMap.set(t.period, {})
    periodMap.get(t.period)![t.skill] = t.count
  }

  const chartData = Array.from(periodMap.entries())
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([period, skillCounts]) => ({ period, ...skillCounts }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Top-Skills</CardTitle>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart data={chartData} margin={{ bottom: 10 }}>
            <XAxis dataKey="period" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 12 }} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {topSkills.slice(0, 10).map((skill, i) => (
              <Bar
                key={skill}
                dataKey={skill}
                stackId="skills"
                fill={COLORS[i % COLORS.length]}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  )
}
