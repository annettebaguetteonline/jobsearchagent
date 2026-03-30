import { Badge } from "@/components/ui/badge"
import { CheckCircle, AlertCircle, Lightbulb } from "lucide-react"

interface MatchReasonsProps {
  matchReasons: string[] | null
  missingSkills: string[] | null
  applicationTips: string[] | null
}

export function MatchReasons({
  matchReasons,
  missingSkills,
  applicationTips,
}: MatchReasonsProps) {
  if (!matchReasons && !missingSkills && !applicationTips) return null

  return (
    <div className="space-y-3">
      {matchReasons && matchReasons.length > 0 && (
        <section>
          <h4 className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold text-green-700">
            <CheckCircle className="h-4 w-4" />
            Passt
          </h4>
          <ul className="space-y-1 text-sm text-muted-foreground">
            {matchReasons.map((r, i) => (
              <li key={i}>• {r}</li>
            ))}
          </ul>
        </section>
      )}

      {missingSkills && missingSkills.length > 0 && (
        <section>
          <h4 className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold text-orange-700">
            <AlertCircle className="h-4 w-4" />
            Fehlende Skills
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {missingSkills.map((s) => (
              <Badge key={s} variant="outline" className="text-xs">
                {s}
              </Badge>
            ))}
          </div>
        </section>
      )}

      {applicationTips && applicationTips.length > 0 && (
        <section>
          <h4 className="mb-1.5 flex items-center gap-1.5 text-sm font-semibold text-blue-700">
            <Lightbulb className="h-4 w-4" />
            Bewerbungstipps
          </h4>
          <ul className="space-y-1 text-sm text-muted-foreground">
            {applicationTips.map((t, i) => (
              <li key={i}>• {t}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
