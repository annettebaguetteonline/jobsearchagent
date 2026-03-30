import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Cell } from "recharts"

interface ScoreBreakdownChartProps {
  breakdown: Record<string, number>
}

const DIMENSION_LABELS: Record<string, string> = {
  skills: "Skills",
  level: "Level",
  domain: "Branche",
  location: "Standort",
  potential: "Potenzial",
}

function getBarColor(value: number): string {
  if (value >= 7) return "#22c55e" // green-500
  if (value >= 5) return "#eab308" // yellow-500
  return "#ef4444" // red-500
}

export function ScoreBreakdownChart({ breakdown }: ScoreBreakdownChartProps) {
  const data = Object.entries(breakdown).map(([key, value]) => ({
    name: DIMENSION_LABELS[key] ?? key,
    value,
    key,
  }))

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ left: 60, right: 20, top: 5, bottom: 5 }}
      >
        <XAxis type="number" domain={[0, 10]} tickCount={6} fontSize={12} />
        <YAxis type="category" dataKey="name" width={55} fontSize={12} />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={20}>
          {data.map((entry) => (
            <Cell key={entry.key} fill={getBarColor(entry.value)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}
