import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ScoreBadge } from "./score-badge"
import { useUpdateJobStatus } from "@/lib/queries"
import { Check, X, MapPin, Building2, Calendar } from "lucide-react"

interface JobCardProps {
  job: Record<string, unknown>
}

export function JobCard({ job }: JobCardProps) {
  const updateStatus = useUpdateJobStatus()
  const companyName = job.company_name as string | undefined
  const locationRaw = job.location_raw as string | undefined
  const deadline = job.deadline as string | undefined
  const workModel = job.work_model as string | undefined

  const handleReviewed = () => {
    updateStatus.mutate({ jobId: job.id as number, status: "reviewed" })
  }

  const handleIgnore = () => {
    updateStatus.mutate({ jobId: job.id as number, status: "ignored" })
  }

  return (
    <Card className="transition-shadow hover:shadow-md">
      <CardContent className="flex items-center gap-4 p-4">
        {/* Score Badge */}
        <ScoreBadge score={job.stage2_score as number | null} />

        {/* Job Info */}
        <div className="min-w-0 flex-1">
          <h4 className="truncate font-semibold">{job.title as string}</h4>
          <div className="mt-1 flex flex-wrap gap-3 text-sm text-muted-foreground">
            {companyName && (
              <span className="flex items-center gap-1">
                <Building2 className="h-3.5 w-3.5" />
                {companyName}
              </span>
            )}
            {locationRaw && (
              <span className="flex items-center gap-1">
                <MapPin className="h-3.5 w-3.5" />
                {locationRaw}
              </span>
            )}
            {deadline && (
              <span className="flex items-center gap-1">
                <Calendar className="h-3.5 w-3.5" />
                {deadline.split("T")[0]}
              </span>
            )}
            {workModel && (
              <Badge variant="outline" className="text-xs">
                {workModel}
              </Badge>
            )}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="flex shrink-0 gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleReviewed}
            disabled={updateStatus.isPending}
            title="Als gepr\u00FCft markieren"
          >
            <Check className="mr-1 h-4 w-4" />
            Reviewed
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleIgnore}
            disabled={updateStatus.isPending}
            title="Ignorieren"
          >
            <X className="h-4 w-4" />
          </Button>
          <Button
            variant="secondary"
            size="sm"
            disabled
            title="Anschreiben-Generator noch nicht verf\u00FCgbar"
          >
            Anschreiben
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
