import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"
import { useAnalyticsSalary } from "@/lib/queries"

interface SalaryBin {
  range_start: number
  range_end: number
  count: number
}

interface SalaryData {
  bins: SalaryBin[]
  total_with_salary: number
  total_without_salary: number
}

function formatK(value: number): string {
  return `${Math.round(value / 1000)}k`
}

export function SalaryChart() {
  const { data, isLoading } = useAnalyticsSalary()

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Gehaltsverteilung</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-48 w-full" />
        </CardContent>
      </Card>
    )
  }

  const salaryData = data as SalaryData | undefined
  const bins = salaryData?.bins ?? []
  const chartData = bins.map((b) => ({
    label: `${formatK(b.range_start)}–${formatK(b.range_end)}`,
    count: b.count,
  }))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Gehaltsverteilung</CardTitle>
      </CardHeader>
      <CardContent>
        {chartData.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Keine Gehaltsdaten verfügbar</p>
        ) : (
          <>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chartData} margin={{ bottom: 20 }}>
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 11 }}
                  angle={-30}
                  textAnchor="end"
                  interval={0}
                />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v: number) => [v, "Anzahl"]} />
                <Bar dataKey="count" name="Anzahl" fill="hsl(222, 47%, 31%)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            <p className="mt-1 text-center text-xs text-muted-foreground">
              {salaryData?.total_with_salary ?? 0} mit Gehalt ·{" "}
              {salaryData?.total_without_salary ?? 0} ohne Angabe
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}
