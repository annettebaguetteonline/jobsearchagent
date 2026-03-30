import { useSearchParams } from "react-router-dom"
import { useCallback, useMemo } from "react"

export interface JobFilterState {
  status?: string
  min_score?: number
  work_model?: string
  source?: string
  search?: string
  has_deadline?: boolean
  sort_by: string
  sort_dir: string
  limit: number
  offset: number
}

const DEFAULTS: JobFilterState = {
  sort_by: "date",
  sort_dir: "desc",
  limit: 50,
  offset: 0,
}

export function useJobFilters() {
  const [searchParams, setSearchParams] = useSearchParams()

  const filters: JobFilterState = useMemo(
    () => ({
      status: searchParams.get("status") ?? undefined,
      min_score: searchParams.has("min_score")
        ? Number(searchParams.get("min_score"))
        : undefined,
      work_model: searchParams.get("work_model") ?? undefined,
      source: searchParams.get("source") ?? undefined,
      search: searchParams.get("search") ?? undefined,
      has_deadline: searchParams.has("has_deadline")
        ? searchParams.get("has_deadline") === "true"
        : undefined,
      sort_by: searchParams.get("sort_by") ?? DEFAULTS.sort_by,
      sort_dir: searchParams.get("sort_dir") ?? DEFAULTS.sort_dir,
      limit: Number(searchParams.get("limit") ?? DEFAULTS.limit),
      offset: Number(searchParams.get("offset") ?? DEFAULTS.offset),
    }),
    [searchParams],
  )

  const setFilter = useCallback(
    (key: string, value: string | number | boolean | undefined) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        if (value === undefined || value === "") {
          next.delete(key)
        } else {
          next.set(key, String(value))
        }
        if (key !== "offset") {
          next.delete("offset")
        }
        return next
      })
    },
    [setSearchParams],
  )

  const resetFilters = useCallback(() => {
    setSearchParams({})
  }, [setSearchParams])

  return { filters, setFilter, resetFilters }
}
