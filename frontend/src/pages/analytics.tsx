import { FunnelChart } from "@/components/analytics/funnel-chart"
import { SourceScoresChart } from "@/components/analytics/source-scores-chart"
import { SalaryChart } from "@/components/analytics/salary-chart"
import { SkillTrendsChart } from "@/components/analytics/skill-trends-chart"
import { CalibrationChart } from "@/components/analytics/calibration-chart"
import { SkillNetwork } from "@/components/analytics/skill-network"
import { DataQualityPanel } from "@/components/analytics/data-quality-panel"

export default function Analytics() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Analytics</h2>
      <div className="grid gap-6 lg:grid-cols-2">
        <FunnelChart />
        <SourceScoresChart />
        <SalaryChart />
        <SkillTrendsChart />
        <CalibrationChart />
        <SkillNetwork />
      </div>
      <div>
        <h3 className="mb-4 text-lg font-semibold">Datenqualität</h3>
        <DataQualityPanel />
      </div>
    </div>
  )
}
