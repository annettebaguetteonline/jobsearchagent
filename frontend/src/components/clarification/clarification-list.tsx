import { useState } from "react"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty-state"
import { AlertCircle } from "lucide-react"
import { ClarificationCard } from "./clarification-card"

interface ClarificationItem {
  id: number
  entity_title: string | null
  entity_company: string | null
  entity_score: number | null
  issue_type: string
  severity: string
  attempts: Array<{ stage: string; tried_at: string; result: string }> | null
  created_at: string
}

interface ClarificationListProps {
  urgent: ClarificationItem[]
  normal: ClarificationItem[]
  isLoading: boolean
  isError?: boolean
}

export function ClarificationList({ urgent, normal, isLoading, isError }: ClarificationListProps) {
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const toggleExpand = (id: number) => {
    setExpandedId(expandedId === id ? null : id)
  }

  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-20 w-full rounded-lg" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <EmptyState
        icon={<AlertCircle className="mx-auto h-10 w-10 text-destructive" />}
        title="Fehler beim Laden"
        description="Klärungsbedarf konnte nicht geladen werden. Bitte Seite neu laden."
      />
    )
  }

  if (urgent.length === 0 && normal.length === 0) {
    return (
      <EmptyState
        title="Kein Klärungsbedarf"
        description="Alles erledigt."
      />
    )
  }

  return (
    <div className="space-y-6">
      {urgent.length > 0 && (
        <section>
          <h3 className="mb-3 text-sm font-semibold text-red-700">
            Dringend ({urgent.length})
          </h3>
          <div className="space-y-3">
            {urgent.map((item) => (
              <ClarificationCard
                key={item.id}
                id={item.id}
                entityTitle={item.entity_title}
                entityCompany={item.entity_company}
                entityScore={item.entity_score}
                issueType={item.issue_type}
                severity={item.severity}
                attempts={item.attempts}
                createdAt={item.created_at}
                expanded
                onToggle={() => undefined}
              />
            ))}
          </div>
        </section>
      )}

      {normal.length > 0 && (
        <section>
          <h3 className="mb-3 text-sm font-semibold text-yellow-700">
            Normal ({normal.length})
          </h3>
          <div className="space-y-3">
            {normal.map((item) => (
              <ClarificationCard
                key={item.id}
                id={item.id}
                entityTitle={item.entity_title}
                entityCompany={item.entity_company}
                entityScore={item.entity_score}
                issueType={item.issue_type}
                severity={item.severity}
                attempts={item.attempts}
                createdAt={item.created_at}
                expanded={expandedId === item.id}
                onToggle={() => toggleExpand(item.id)}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  )
}
