import { useJob } from "@/lib/queries"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { ScoreBadge } from "@/components/dashboard/score-badge"
import { ScoreBreakdownChart } from "./score-breakdown-chart"
import { MatchReasons } from "./match-reasons"
import { LocationDetails } from "./location-details"
import { JobActions } from "./job-actions"
import { Skeleton } from "@/components/ui/skeleton"
import { X, ExternalLink } from "lucide-react"

interface JobDetailPanelProps {
  jobId: number
  onClose: () => void
}

export default function JobDetailPanel({ jobId, onClose }: JobDetailPanelProps) {
  const { data, isLoading } = useJob(jobId)

  if (isLoading) {
    return (
      <Card className="sticky top-4">
        <CardContent className="space-y-4 p-4">
          <Skeleton className="h-8 w-3/4" />
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    )
  }

  const job = data as Record<string, unknown> | undefined
  if (!job) return null

  const evaluation = job.evaluation as Record<string, unknown> | null
  const company = job.company as Record<string, unknown> | null
  const sources = (job.sources ?? []) as Record<string, unknown>[]
  const skills = (job.skills ?? []) as Record<string, unknown>[]

  return (
    <Card className="sticky top-4 max-h-[calc(100vh-8rem)] overflow-y-auto">
      <CardHeader className="flex flex-row items-start justify-between pb-3">
        <div className="flex items-center gap-3">
          <ScoreBadge score={evaluation?.stage2_score as number | null} />
          <div>
            <CardTitle className="text-lg">{job.title as string}</CardTitle>
            <p className="text-sm text-muted-foreground">
              {(company?.name as string) ?? "Unbekanntes Unternehmen"}
              {company?.address_city && ` — ${company.address_city as string}`}
            </p>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </CardHeader>

      <CardContent className="space-y-6 pt-0">
        {/* Score Breakdown */}
        {evaluation?.stage2_score_breakdown && (
          <section>
            <h4 className="mb-2 text-sm font-semibold">Score-Breakdown</h4>
            <ScoreBreakdownChart
              breakdown={evaluation.stage2_score_breakdown as Record<string, number>}
            />
          </section>
        )}

        {/* Zusammenfassung */}
        {evaluation?.stage2_summary && (
          <section>
            <h4 className="mb-1 text-sm font-semibold">Zusammenfassung</h4>
            <p className="text-sm text-muted-foreground">
              {evaluation.stage2_summary as string}
            </p>
          </section>
        )}

        {/* Match-Gründe & fehlende Skills */}
        <MatchReasons
          matchReasons={evaluation?.stage2_match_reasons as string[] | null}
          missingSkills={evaluation?.stage2_missing_skills as string[] | null}
          applicationTips={evaluation?.stage2_application_tips as string[] | null}
        />

        {/* Location */}
        <LocationDetails
          workModel={job.work_model as string | null}
          locationRaw={job.location_raw as string | null}
          locationScore={evaluation?.location_score as number | null}
          effectiveMinutes={evaluation?.location_effective_minutes as number | null}
          remotePolicy={company?.remote_policy as string | null}
        />

        {/* Skills */}
        {skills.length > 0 && (
          <section>
            <h4 className="mb-2 text-sm font-semibold">Erkannte Skills</h4>
            <div className="flex flex-wrap gap-1.5">
              {skills.map((sk) => (
                <span
                  key={sk.skill as string}
                  className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                    (sk.skill_type as string) === "required"
                      ? "bg-blue-100 text-blue-800"
                      : "bg-gray-100 text-gray-700"
                  }`}
                >
                  {sk.skill as string}
                </span>
              ))}
            </div>
          </section>
        )}

        {/* Quellen */}
        {sources.length > 0 && (
          <section>
            <h4 className="mb-2 text-sm font-semibold">Quellen</h4>
            <ul className="space-y-1">
              {sources.map((src) => (
                <li key={src.id as number} className="text-sm">
                  <a
                    href={src.url as string}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-primary hover:underline"
                  >
                    <ExternalLink className="h-3 w-3" />
                    {src.source_name as string}
                    {src.is_canonical && " (Hauptquelle)"}
                  </a>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Gehalt */}
        {(job.salary_raw || evaluation?.stage2_salary_estimate) && (
          <section>
            <h4 className="mb-1 text-sm font-semibold">Gehalt</h4>
            <p className="text-sm">
              {(job.salary_raw as string) ?? (evaluation?.stage2_salary_estimate as string)}
            </p>
          </section>
        )}

        {/* Actions */}
        <JobActions jobId={jobId} currentStatus={job.status as string} />
      </CardContent>
    </Card>
  )
}
