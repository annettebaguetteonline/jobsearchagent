import { Link } from "react-router-dom"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useClarifications } from "@/lib/queries"
import { AlertTriangle } from "lucide-react"

export function ClarificationSummary() {
  const { data, isLoading } = useClarifications()

  if (isLoading) return null

  const clarifData = data as { total: number; urgent: unknown[]; normal: unknown[] } | undefined
  const total = clarifData?.total ?? 0
  const urgentCount = clarifData?.urgent?.length ?? 0

  if (total === 0) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <AlertTriangle className="h-4 w-4 text-yellow-600" />
          Kl\u00E4rungsbedarf
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {urgentCount > 0 && (
            <div className="flex items-center gap-2">
              <Badge variant="destructive">{urgentCount}</Badge>
              <span className="text-sm">dringend</span>
            </div>
          )}
          <div className="flex items-center gap-2">
            <Badge variant="secondary">{total}</Badge>
            <span className="text-sm">gesamt offen</span>
          </div>
          <Link
            to="/klaerungsbedarf"
            className="mt-2 block text-sm font-medium text-primary hover:underline"
          >
            Alle anzeigen \u2192
          </Link>
        </div>
      </CardContent>
    </Card>
  )
}
