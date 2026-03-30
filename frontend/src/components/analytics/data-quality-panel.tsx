import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { useDataQuality } from "@/lib/queries"

// ─── Typen (spiegeln backend/scripts/data_quality_report.py) ────────────────

interface FieldStats {
  field: string
  null_count: number
  empty_count: number
  filled_count: number
  total: number
  coverage_pct: number
}

interface ImputationEntry {
  field: string
  null_count: number
  null_with_multiple_sources: number
  null_with_raw_text: number
  rescrapable_pct: number
  llm_extractable_pct: number
}

interface FilterImpact {
  stage1b_no_raw_text: number
  stage1a_no_title_no_text: number
  location_score_missing: number
  needs_reevaluation: number
}

interface Recommendation {
  category: string
  severity: string
  message: string
  affected_count: number
  affected_pct: number
}

interface DataQualityReport {
  general: { total_jobs: number; total_active: number }
  field_completeness: { fields: FieldStats[] }
  imputation: { fields: ImputationEntry[] }
  filter_impact: FilterImpact
  recommendations: Recommendation[]
}

// ─── Hilfs-Komponenten ───────────────────────────────────────────────────────

function CoverageBadge({ pct }: { pct: number }) {
  const variant =
    pct >= 80 ? "default" : pct >= 50 ? "secondary" : "destructive"
  return <Badge variant={variant}>{pct.toFixed(1)} %</Badge>
}

function SeverityBadge({ severity }: { severity: string }) {
  const variant =
    severity === "high" ? "destructive" : severity === "medium" ? "secondary" : "outline"
  return <Badge variant={variant}>{severity.toUpperCase()}</Badge>
}

// ─── Haupt-Komponente ────────────────────────────────────────────────────────

export function DataQualityPanel() {
  const { data, isLoading } = useDataQuality()
  const report = data as DataQualityReport | undefined

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Datenqualität</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Skeleton className="h-48 w-full" />
          <Skeleton className="h-32 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (!report) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Datenqualität</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="py-8 text-center text-sm text-muted-foreground">Keine Daten verfügbar</p>
        </CardContent>
      </Card>
    )
  }

  const fi = report.filter_impact
  const totalActive = report.general.total_active || 1
  const stage1bPct = ((fi.stage1b_no_raw_text / totalActive) * 100).toFixed(1)
  const locMissPct = ((fi.location_score_missing / totalActive) * 100).toFixed(1)

  const severityOrder: Record<string, number> = { high: 0, medium: 1, low: 2 }
  const sortedRecs = [...(report.recommendations ?? [])].sort(
    (a, b) => (severityOrder[a.severity] ?? 3) - (severityOrder[b.severity] ?? 3),
  )

  return (
    <div className="space-y-4">
      {/* ── Feldvollständigkeit ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Feldvollständigkeit</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="pb-2 text-left font-medium">Feld</th>
                <th className="pb-2 text-right font-medium">Abdeckung</th>
                <th className="pb-2 text-right font-medium">NULL</th>
                <th className="pb-2 text-right font-medium">Leer</th>
                <th className="pb-2 text-right font-medium">Befüllt</th>
              </tr>
            </thead>
            <tbody>
              {report.field_completeness.fields.map((f) => {
                const nullPct = f.total > 0 ? ((f.null_count / f.total) * 100).toFixed(1) : "0.0"
                const emptyPct = f.total > 0 ? ((f.empty_count / f.total) * 100).toFixed(1) : "0.0"
                return (
                  <tr key={f.field} className="border-b last:border-0">
                    <td className="py-1.5 font-mono text-xs">{f.field}</td>
                    <td className="py-1.5 text-right">
                      <CoverageBadge pct={f.coverage_pct} />
                    </td>
                    <td className="py-1.5 text-right text-muted-foreground">
                      {f.null_count.toLocaleString()} ({nullPct}%)
                    </td>
                    <td className="py-1.5 text-right text-muted-foreground">
                      {f.empty_count.toLocaleString()} ({emptyPct}%)
                    </td>
                    <td className="py-1.5 text-right">{f.filled_count.toLocaleString()}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* ── Imputations-Potential ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Imputations-Potential</CardTitle>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-muted-foreground">
                <th className="pb-2 text-left font-medium">Feld</th>
                <th className="pb-2 text-right font-medium">NULL</th>
                <th className="pb-2 text-right font-medium">Re-Scraping mögl.</th>
                <th className="pb-2 text-right font-medium">LLM mögl.</th>
              </tr>
            </thead>
            <tbody>
              {report.imputation.fields.map((e) => (
                <tr key={e.field} className="border-b last:border-0">
                  <td className="py-1.5 font-mono text-xs">{e.field}</td>
                  <td className="py-1.5 text-right">{e.null_count.toLocaleString()}</td>
                  <td className="py-1.5 text-right">
                    {e.null_with_multiple_sources.toLocaleString()}{" "}
                    <span className="text-muted-foreground">({e.rescrapable_pct.toFixed(1)}%)</span>
                  </td>
                  <td className="py-1.5 text-right">
                    {e.null_with_raw_text.toLocaleString()}{" "}
                    <span className="text-muted-foreground">({e.llm_extractable_pct.toFixed(1)}%)</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* ── Filter-Impact ── */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Filter-Impact</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Stage 1b ohne raw_text</p>
              <p className="mt-1 text-2xl font-semibold">{fi.stage1b_no_raw_text.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">{stage1bPct}% der aktiven Jobs</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Stage 1a ohne Inhalt</p>
              <p className="mt-1 text-2xl font-semibold">{fi.stage1a_no_title_no_text.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">kein Keyword-Match möglich</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Kein Pendel-Score</p>
              <p className="mt-1 text-2xl font-semibold">{fi.location_score_missing.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">{locMissPct}% der aktiven Jobs</p>
            </div>
            <div className="rounded-lg border p-3">
              <p className="text-xs text-muted-foreground">Re-Evaluation nötig</p>
              <p className="mt-1 text-2xl font-semibold">{fi.needs_reevaluation.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">Profil geändert</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── Empfehlungen ── */}
      {sortedRecs.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Empfehlungen</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {sortedRecs.map((rec, i) => (
              <div key={i} className="flex items-start gap-3 rounded-lg border p-3">
                <SeverityBadge severity={rec.severity} />
                <div className="min-w-0 flex-1">
                  <span className="text-xs font-medium text-muted-foreground uppercase">
                    {rec.category}
                  </span>
                  <p className="mt-0.5 text-sm">{rec.message}</p>
                </div>
                <span className="shrink-0 text-sm text-muted-foreground">
                  {rec.affected_count.toLocaleString()} Jobs ({rec.affected_pct.toFixed(1)}%)
                </span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
