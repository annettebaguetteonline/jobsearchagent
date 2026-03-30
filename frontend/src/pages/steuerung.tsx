import { ScrapingSection } from "@/components/control/scraping-section"
import { EvaluationSection } from "@/components/control/evaluation-section"
import { LocationSection } from "@/components/control/location-section"
import { FeedbackSection } from "@/components/control/feedback-section"

export default function Steuerung() {
  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold">Steuerung</h2>
      <div className="grid gap-6 lg:grid-cols-2">
        <ScrapingSection />
        <EvaluationSection />
        <LocationSection />
        <FeedbackSection />
      </div>
    </div>
  )
}
