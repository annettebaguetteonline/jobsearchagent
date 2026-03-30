import { Badge } from "@/components/ui/badge"
import { ScoreBadge } from "@/components/dashboard/score-badge"
import { ResolutionActions } from "./resolution-actions"
import { cn } from "@/lib/utils"

interface Attempt {
  stage: string
  tried_at: string
  result: string
}

interface ClarificationCardProps {
  id: number
  entityTitle: string | null
  entityCompany: string | null
  entityScore: number | null
  issueType: string
  severity: string
  attempts: Attempt[] | null
  createdAt: string
  expanded: boolean
  onToggle: () => void
}

const ISSUE_LABELS: Record<string, string> = {
  address_unknown: "Adresse unbekannt",
  website_unknown: "Website unbekannt",
  salary_parse: "Gehalt nicht lesbar",
}

export function ClarificationCard({
  id,
  entityTitle,
  entityCompany,
  entityScore,
  issueType,
  severity,
  attempts,
  createdAt,
  expanded,
  onToggle,
}: ClarificationCardProps) {
  const isUrgent = severity === "red"

  return (
    <div
      className={cn(
        "rounded-lg border p-4 transition-colors",
        isUrgent ? "border-red-300 bg-red-50/30" : "border-yellow-300 bg-yellow-50/20",
      )}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <ScoreBadge score={entityScore} size="sm" />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">
              {entityTitle ?? `#${id}`}
            </p>
            {entityCompany && (
              <p className="truncate text-xs text-muted-foreground">{entityCompany}</p>
            )}
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <Badge
            className={cn(
              "text-xs",
              isUrgent
                ? "bg-red-100 text-red-800 border-red-200"
                : "bg-yellow-100 text-yellow-800 border-yellow-200",
            )}
            variant="outline"
          >
            {ISSUE_LABELS[issueType] ?? issueType}
          </Badge>

          {!isUrgent && (
            <button
              onClick={onToggle}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              aria-expanded={expanded}
            >
              {expanded ? "▲" : "▼"}
            </button>
          )}
        </div>
      </div>

      {/* Collapsible details */}
      {(isUrgent || expanded) && (
        <div className="mt-3 space-y-3">
          {/* Attempts history */}
          {attempts && attempts.length > 0 && (
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Versuche</p>
              <ul className="space-y-0.5">
                {attempts.map((a, i) => (
                  <li key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span className="font-mono">{a.stage}</span>
                    <span>→</span>
                    <span>{a.result}</span>
                    <span className="ml-auto">{a.tried_at.slice(0, 10)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            Erstellt: {createdAt.slice(0, 10)}
          </p>

          <ResolutionActions id={id} issueType={issueType} />
        </div>
      )}
    </div>
  )
}
