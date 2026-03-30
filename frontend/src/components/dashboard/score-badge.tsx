interface ScoreBadgeProps {
  score: number | null | undefined
  size?: "sm" | "md"
}

export function ScoreBadge({ score, size = "md" }: ScoreBadgeProps) {
  if (score == null) {
    return (
      <div className={`flex items-center justify-center rounded-lg bg-muted ${
        size === "sm" ? "h-8 w-8 text-xs" : "h-12 w-12 text-sm"
      } font-medium text-muted-foreground`}>
        —
      </div>
    )
  }

  const color =
    score >= 7 ? "bg-green-100 text-green-800" :
    score >= 5 ? "bg-yellow-100 text-yellow-800" :
    "bg-red-100 text-red-800"

  return (
    <div className={`flex items-center justify-center rounded-lg ${color} ${
      size === "sm" ? "h-8 w-8 text-xs" : "h-12 w-12 text-sm"
    } font-bold`}>
      {score.toFixed(1)}
    </div>
  )
}
