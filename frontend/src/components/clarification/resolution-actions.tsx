import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useResolveClarification } from "@/lib/queries"
import { api } from "@/lib/api-client"
import { useQueryClient } from "@tanstack/react-query"
import { queryKeys } from "@/lib/queries"

interface ResolutionActionsProps {
  id: number
  issueType: string
}

export function ResolutionActions({ id, issueType }: ResolutionActionsProps) {
  const resolve = useResolveClarification()
  const qc = useQueryClient()
  const [urlInput, setUrlInput] = useState("")
  const [showUrlInput, setShowUrlInput] = useState(false)
  const [urlPending, setUrlPending] = useState(false)

  const handleApproximate = () => {
    resolve.mutate({
      id,
      resolved_by: "manual",
      resolution_note: "Näherung akzeptiert",
    })
  }

  const handleHide = () => {
    resolve.mutate({
      id,
      resolved_by: "manual",
      resolution_note: "Ausgeblendet",
    })
  }

  const handleUrlSubmit = async () => {
    if (!urlInput.trim()) return
    setUrlPending(true)
    try {
      await api.post(`/clarifications/${id}/update-url`, { url: urlInput.trim() })
      void qc.invalidateQueries({ queryKey: queryKeys.clarifications.all })
      setUrlInput("")
      setShowUrlInput(false)
    } finally {
      setUrlPending(false)
    }
  }

  const isPending = resolve.isPending || urlPending

  return (
    <div className="flex flex-wrap items-center gap-2 pt-2">
      {issueType === "website_unknown" && (
        <>
          {showUrlInput ? (
            <div className="flex items-center gap-2">
              <Input
                className="h-8 w-56 text-sm"
                placeholder="https://…"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleUrlSubmit()
                }}
                autoFocus
              />
              <Button
                size="sm"
                onClick={() => void handleUrlSubmit()}
                disabled={isPending || !urlInput.trim()}
              >
                Speichern
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowUrlInput(false)}
              >
                Abbrechen
              </Button>
            </div>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowUrlInput(true)}
              disabled={isPending}
            >
              URL eingeben
            </Button>
          )}
        </>
      )}

      <Button
        size="sm"
        variant="outline"
        onClick={handleApproximate}
        disabled={isPending}
      >
        Näherung übernehmen
      </Button>

      <Button
        size="sm"
        variant="ghost"
        onClick={handleHide}
        disabled={isPending}
        className="text-muted-foreground"
      >
        Ausblenden
      </Button>
    </div>
  )
}
