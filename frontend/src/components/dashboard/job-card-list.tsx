import { JobCard } from "./job-card"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty-state"
import { AlertCircle } from "lucide-react"

interface JobCardListProps {
  data: { total: number; jobs: unknown[] } | undefined
  isLoading: boolean
  isError?: boolean
}

export function JobCardList({ data, isLoading, isError }: JobCardListProps) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <EmptyState
        icon={<AlertCircle className="mx-auto h-10 w-10 text-destructive" />}
        title="Fehler beim Laden"
        description="Stellen konnten nicht geladen werden. Bitte Seite neu laden."
      />
    )
  }

  const jobs = (data?.jobs ?? []) as Record<string, unknown>[]

  if (jobs.length === 0) {
    return (
      <EmptyState
        title="Keine neuen Stellen"
        description="Starte einen Scan oder ändere die Filter."
      />
    )
  }

  return (
    <div className="space-y-3">
      {jobs.map((job) => (
        <JobCard key={job.id as number} job={job} />
      ))}
    </div>
  )
}
