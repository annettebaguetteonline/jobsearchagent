import { MapPin, Train, Clock } from "lucide-react"
import { Badge } from "@/components/ui/badge"

interface LocationDetailsProps {
  workModel: string | null
  locationRaw: string | null
  locationScore: number | null
  effectiveMinutes: number | null
  remotePolicy: string | null
}

export function LocationDetails({
  workModel,
  locationRaw,
  locationScore,
  effectiveMinutes,
  remotePolicy,
}: LocationDetailsProps) {
  return (
    <section>
      <h4 className="mb-2 text-sm font-semibold">Standort & Pendeln</h4>
      <div className="space-y-1.5 text-sm">
        {locationRaw && (
          <div className="flex items-center gap-2">
            <MapPin className="h-4 w-4 text-muted-foreground" />
            {locationRaw}
          </div>
        )}
        {workModel && (
          <div className="flex items-center gap-2">
            <Badge variant="outline">{workModel}</Badge>
            {remotePolicy && remotePolicy !== "unknown" && (
              <span className="text-muted-foreground">(Firma: {remotePolicy})</span>
            )}
          </div>
        )}
        {effectiveMinutes != null && (
          <div className="flex items-center gap-2">
            <Train className="h-4 w-4 text-muted-foreground" />
            <span>
              Effektive Pendelzeit: <strong>{effectiveMinutes} min</strong>
            </span>
          </div>
        )}
        {locationScore != null && (
          <div className="flex items-center gap-2">
            <Clock className="h-4 w-4 text-muted-foreground" />
            <span>
              Location-Score: <strong>{(locationScore * 10).toFixed(1)}/10</strong>
            </span>
          </div>
        )}
      </div>
    </section>
  )
}
