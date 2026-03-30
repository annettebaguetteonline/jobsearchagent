import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts"
import { useAnalyticsFunnel } from "@/lib/queries"

interface FunnelData {
  steps: Array<{ stage: string; count: number }>
}

export function FunnelChart() {
  const { data, isLoading } = useAnalyticsFunnel()

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Pipeline-Funnel</CardTitle>
        </CardHeader>
        <CardContent>
          <Skeleton className="h-48 w-full" />
        </CardContent>
      </Card>
    )
  }

  const steps = (data as FunnelData | undefined)?.steps ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Pipeline-Funnel</CardTitle>
      </CardHeader>
      <CardContent>
        {steps.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Keine Daten verfügbar</p>
        ) : (
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={steps} layout="vertical" margin={{ left: 10, right: 20 }}>
              <XAxis type="number" tick={{ fontSize: 12 }} />
              <YAxis type="category" dataKey="stage" width={130} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Bar dataKey="count" name="Anzahl" fill="hsl(222, 47%, 31%)" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </CardContent>
    </Card>
  )
}
