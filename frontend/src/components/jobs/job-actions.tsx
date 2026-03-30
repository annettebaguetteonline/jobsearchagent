import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useUpdateJobStatus, useSubmitFeedback } from "@/lib/queries"

interface JobActionsProps {
  jobId: number
  currentStatus: string
}

const STATUS_OPTIONS = [
  "new",
  "reviewed",
  "applying",
  "applied",
  "interview",
  "offer",
  "rejected",
  "ignored",
]

export function JobActions({ jobId, currentStatus }: JobActionsProps) {
  const updateStatus = useUpdateJobStatus()
  const submitFeedback = useSubmitFeedback()
  const [feedbackDecision, setFeedbackDecision] = useState("")
  const [feedbackReasoning, setFeedbackReasoning] = useState("")

  const handleStatusChange = (status: string) => {
    updateStatus.mutate({ jobId, status })
  }

  const handleFeedback = () => {
    if (!feedbackDecision) return
    submitFeedback.mutate(
      { job_id: jobId, decision: feedbackDecision, reasoning: feedbackReasoning || undefined },
      {
        onSuccess: () => {
          setFeedbackDecision("")
          setFeedbackReasoning("")
        },
      },
    )
  }

  return (
    <div className="space-y-4 border-t pt-4">
      {/* Status */}
      <div>
        <h4 className="mb-2 text-sm font-semibold">Status</h4>
        <select
          value={currentStatus}
          onChange={(e) => handleStatusChange(e.target.value)}
          disabled={updateStatus.isPending}
          className="rounded-md border bg-background px-3 py-2 text-sm"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {/* Feedback */}
      <div>
        <h4 className="mb-2 text-sm font-semibold">Feedback</h4>
        <div className="flex gap-2">
          {["APPLY", "MAYBE", "SKIP", "IGNORE"].map((d) => (
            <Button
              key={d}
              variant={feedbackDecision === d ? "default" : "outline"}
              size="sm"
              onClick={() => setFeedbackDecision(d)}
            >
              {d}
            </Button>
          ))}
        </div>
        {feedbackDecision && (
          <div className="mt-2 space-y-2">
            <Input
              placeholder="Begründung (optional)"
              value={feedbackReasoning}
              onChange={(e) => setFeedbackReasoning(e.target.value)}
            />
            <Button
              size="sm"
              onClick={handleFeedback}
              disabled={submitFeedback.isPending}
            >
              Feedback absenden
            </Button>
          </div>
        )}
      </div>

      {/* Anschreiben */}
      <Button
        variant="secondary"
        className="w-full"
        disabled
        title="Anschreiben-Generator noch nicht verfügbar"
      >
        Anschreiben generieren
      </Button>
    </div>
  )
}
