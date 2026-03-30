import { ClarificationList } from "@/components/clarification/clarification-list"
import { useClarifications } from "@/lib/queries"

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

interface ClarificationsResponse {
  total: number
  urgent: ClarificationItem[]
  normal: ClarificationItem[]
}

export default function Klaerungsbedarf() {
  const { data, isLoading, isError } = useClarifications()

  const clarifData = data as ClarificationsResponse | undefined

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Klärungsbedarf</h2>
        <span className="text-sm text-muted-foreground">
          {clarifData?.total ?? 0} offen
        </span>
      </div>
      <ClarificationList
        urgent={clarifData?.urgent ?? []}
        normal={clarifData?.normal ?? []}
        isLoading={isLoading}
        isError={isError}
      />
    </div>
  )
}
