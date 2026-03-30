import { lazy, Suspense, useState } from "react"
import { JobFilters } from "@/components/jobs/job-filters"
import { JobTable } from "@/components/jobs/job-table"
import { useJobFilters } from "@/hooks/use-job-filters"
import { useJobs } from "@/lib/queries"

const JobDetailPanel = lazy(() => import("@/components/jobs/job-detail-panel"))

export default function Stellen() {
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null)
  const { filters, setFilter, resetFilters } = useJobFilters()
  const { data, isLoading, isError } = useJobs(filters)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold">Stellen</h2>
        <span className="text-sm text-muted-foreground">
          {(data as { total?: number } | undefined)?.total ?? 0} Ergebnisse
        </span>
      </div>

      <JobFilters filters={filters} onFilterChange={setFilter} onReset={resetFilters} />

      <div className="flex gap-4">
        <div className={selectedJobId ? "w-1/2" : "w-full"}>
          <JobTable
            data={data as { total: number; jobs: Record<string, unknown>[] } | undefined}
            isLoading={isLoading}
            isError={isError}
            selectedJobId={selectedJobId}
            onSelectJob={setSelectedJobId}
            filters={filters}
            onFilterChange={setFilter}
          />
        </div>
        {selectedJobId && (
          <div className="w-1/2">
            <Suspense fallback={<div className="p-4">Laden...</div>}>
              <JobDetailPanel
                jobId={selectedJobId}
                onClose={() => setSelectedJobId(null)}
              />
            </Suspense>
          </div>
        )}
      </div>
    </div>
  )
}
