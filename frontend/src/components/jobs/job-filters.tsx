import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { JobFilterState } from "@/hooks/use-job-filters"
import { Search, X } from "lucide-react"

interface JobFiltersProps {
  filters: JobFilterState
  onFilterChange: (key: string, value: string | number | boolean | undefined) => void
  onReset: () => void
}

const STATUS_OPTIONS = [
  { value: "", label: "Alle Status" },
  { value: "new", label: "Neu" },
  { value: "reviewed", label: "Geprüft" },
  { value: "applying", label: "Bewerbe mich" },
  { value: "applied", label: "Beworben" },
  { value: "interview", label: "Interview" },
  { value: "offer", label: "Angebot" },
  { value: "ignored", label: "Ignoriert" },
]

const WORK_MODEL_OPTIONS = [
  { value: "", label: "Alle Modelle" },
  { value: "remote", label: "Remote" },
  { value: "hybrid", label: "Hybrid" },
  { value: "onsite", label: "Vor Ort" },
]

const SORT_OPTIONS = [
  { value: "date", label: "Datum" },
  { value: "score", label: "Score" },
  { value: "deadline", label: "Frist" },
  { value: "title", label: "Titel" },
]

export function JobFilters({ filters, onFilterChange, onReset }: JobFiltersProps) {
  const hasActiveFilters =
    filters.status ||
    filters.min_score ||
    filters.work_model ||
    filters.source ||
    filters.search ||
    filters.has_deadline

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card p-3">
      {/* Freitext-Suche */}
      <div className="relative">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Suche..."
          value={filters.search ?? ""}
          onChange={(e) => onFilterChange("search", e.target.value || undefined)}
          className="w-48 pl-8"
        />
      </div>

      {/* Status */}
      <select
        value={filters.status ?? ""}
        onChange={(e) => onFilterChange("status", e.target.value || undefined)}
        className="rounded-md border bg-background px-3 py-2 text-sm"
      >
        {STATUS_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Work Model */}
      <select
        value={filters.work_model ?? ""}
        onChange={(e) => onFilterChange("work_model", e.target.value || undefined)}
        className="rounded-md border bg-background px-3 py-2 text-sm"
      >
        {WORK_MODEL_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Min Score */}
      <Input
        type="number"
        placeholder="Min Score"
        value={filters.min_score ?? ""}
        onChange={(e) =>
          onFilterChange("min_score", e.target.value ? Number(e.target.value) : undefined)
        }
        className="w-28"
        min={1}
        max={10}
        step={0.5}
      />

      {/* Sortierung */}
      <select
        value={filters.sort_by}
        onChange={(e) => onFilterChange("sort_by", e.target.value)}
        className="rounded-md border bg-background px-3 py-2 text-sm"
      >
        {SORT_OPTIONS.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <Button
        variant="ghost"
        size="sm"
        onClick={() =>
          onFilterChange("sort_dir", filters.sort_dir === "asc" ? "desc" : "asc")
        }
      >
        {filters.sort_dir === "asc" ? "↑" : "↓"}
      </Button>

      {/* Reset */}
      {hasActiveFilters && (
        <Button variant="ghost" size="sm" onClick={onReset}>
          <X className="mr-1 h-4 w-4" />
          Reset
        </Button>
      )}
    </div>
  )
}
