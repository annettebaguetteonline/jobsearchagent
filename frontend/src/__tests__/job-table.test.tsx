import { describe, it, expect, vi } from "vitest"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderWithProviders, mockJobListItem } from "../test-helpers"
import { JobTable } from "@/components/jobs/job-table"
import type { JobFilterState } from "@/hooks/use-job-filters"

const defaultFilters: JobFilterState = {
  sort_by: "date",
  sort_dir: "desc",
  limit: 50,
  offset: 0,
}

describe("JobTable", () => {
  it("rendert Spaltenheader", () => {
    renderWithProviders(
      <JobTable
        data={{ total: 0, jobs: [] }}
        isLoading={false}
        selectedJobId={null}
        onSelectJob={vi.fn()}
        filters={defaultFilters}
        onFilterChange={vi.fn()}
      />,
    )
    expect(screen.getByText("Score")).toBeInTheDocument()
    expect(screen.getByText("Titel")).toBeInTheDocument()
    expect(screen.getByText("Unternehmen")).toBeInTheDocument()
    expect(screen.getByText("Status")).toBeInTheDocument()
  })

  it("zeigt Keine Stellen gefunden bei leerer Liste", () => {
    renderWithProviders(
      <JobTable
        data={{ total: 0, jobs: [] }}
        isLoading={false}
        selectedJobId={null}
        onSelectJob={vi.fn()}
        filters={defaultFilters}
        onFilterChange={vi.fn()}
      />,
    )
    expect(screen.getByText(/keine stellen gefunden/i)).toBeInTheDocument()
  })

  it("rendert Zeilen mit Titel und Firma", () => {
    const job = mockJobListItem()
    renderWithProviders(
      <JobTable
        data={{ total: 1, jobs: [job] }}
        isLoading={false}
        selectedJobId={null}
        onSelectJob={vi.fn()}
        filters={defaultFilters}
        onFilterChange={vi.fn()}
      />,
    )
    expect(screen.getByText("Senior Python Developer")).toBeInTheDocument()
    expect(screen.getByText("TechCorp GmbH")).toBeInTheDocument()
  })

  it("rendert Score-Badge in Zeile", () => {
    const job = mockJobListItem({ stage2_score: 8.5 })
    renderWithProviders(
      <JobTable
        data={{ total: 1, jobs: [job] }}
        isLoading={false}
        selectedJobId={null}
        onSelectJob={vi.fn()}
        filters={defaultFilters}
        onFilterChange={vi.fn()}
      />,
    )
    expect(screen.getByText("8.5")).toBeInTheDocument()
  })

  it("Klick auf Zeile ruft onSelectJob auf", async () => {
    const user = userEvent.setup()
    const onSelectJob = vi.fn()
    const job = mockJobListItem({ id: 42 })
    renderWithProviders(
      <JobTable
        data={{ total: 1, jobs: [job] }}
        isLoading={false}
        selectedJobId={null}
        onSelectJob={onSelectJob}
        filters={defaultFilters}
        onFilterChange={vi.fn()}
      />,
    )
    await user.click(screen.getByText("Senior Python Developer"))
    expect(onSelectJob).toHaveBeenCalledWith(42)
  })

  it("Zurück-Button ist disabled wenn offset=0", () => {
    const job = mockJobListItem()
    renderWithProviders(
      <JobTable
        data={{ total: 100, jobs: [job] }}
        isLoading={false}
        selectedJobId={null}
        onSelectJob={vi.fn()}
        filters={{ ...defaultFilters, offset: 0 }}
        onFilterChange={vi.fn()}
      />,
    )
    expect(screen.getByRole("button", { name: /zurück/i })).toBeDisabled()
  })

  it("Weiter-Button ist disabled wenn keine weiteren Seiten vorhanden", () => {
    const job = mockJobListItem()
    renderWithProviders(
      <JobTable
        data={{ total: 1, jobs: [job] }}
        isLoading={false}
        selectedJobId={null}
        onSelectJob={vi.fn()}
        filters={{ ...defaultFilters, offset: 0, limit: 50 }}
        onFilterChange={vi.fn()}
      />,
    )
    expect(screen.getByRole("button", { name: /weiter/i })).toBeDisabled()
  })

  it("Weiter-Button ruft onFilterChange auf", async () => {
    const user = userEvent.setup()
    const onFilterChange = vi.fn()
    const jobs = Array.from({ length: 3 }, (_, i) => mockJobListItem({ id: i + 1 }))
    renderWithProviders(
      <JobTable
        data={{ total: 200, jobs: jobs }}
        isLoading={false}
        selectedJobId={null}
        onSelectJob={vi.fn()}
        filters={{ ...defaultFilters, offset: 0, limit: 50 }}
        onFilterChange={onFilterChange}
      />,
    )
    await user.click(screen.getByRole("button", { name: /weiter/i }))
    expect(onFilterChange).toHaveBeenCalledWith("offset", 50)
  })

  it("zeigt Fehlermeldung bei isError", () => {
    renderWithProviders(
      <JobTable
        data={undefined}
        isLoading={false}
        isError={true}
        selectedJobId={null}
        onSelectJob={vi.fn()}
        filters={defaultFilters}
        onFilterChange={vi.fn()}
      />,
    )
    expect(screen.getByText(/fehler beim laden/i)).toBeInTheDocument()
  })
})
