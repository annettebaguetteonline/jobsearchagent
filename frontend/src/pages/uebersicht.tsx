import { KpiTiles } from "@/components/dashboard/kpi-tiles"
import { JobCardList } from "@/components/dashboard/job-card-list"
import { ClarificationSummary } from "@/components/dashboard/clarification-summary"
import { useJobs, useEvaluationStats } from "@/lib/queries"

export default function Uebersicht() {
  const stats = useEvaluationStats()
  const newJobs = useJobs({
    status: "new",
    sort_by: "score",
    sort_dir: "desc",
    limit: 20,
  })

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Übersicht</h2>

      <KpiTiles
        stats={stats.data as Record<string, unknown> | undefined}
        isLoading={stats.isLoading}
        isError={stats.isError}
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <h3 className="mb-3 text-lg font-semibold">Neue Stellen</h3>
          <JobCardList
            data={newJobs.data as { total: number; jobs: unknown[] } | undefined}
            isLoading={newJobs.isLoading}
            isError={newJobs.isError}
          />
        </div>
        <div>
          <ClarificationSummary />
        </div>
      </div>
    </div>
  )
}
