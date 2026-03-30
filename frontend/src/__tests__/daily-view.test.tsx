import { describe, it, expect, vi } from "vitest"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderWithProviders, mockJobListItem, mockEvaluationStats } from "../test-helpers"
import { KpiTiles } from "@/components/dashboard/kpi-tiles"
import { JobCard } from "@/components/dashboard/job-card"
import { JobCardList } from "@/components/dashboard/job-card-list"

const mockMutate = vi.fn()

vi.mock("@/lib/queries", () => ({
  useUpdateJobStatus: () => ({
    mutate: mockMutate,
    isPending: false,
  }),
}))

describe("KpiTiles", () => {
  it("zeigt Loading-Skeletons bei isLoading", () => {
    const { container } = renderWithProviders(
      <KpiTiles stats={undefined} isLoading={true} />,
    )
    // Skeletons haben animate-pulse Klasse
    const skeletons = container.querySelectorAll(".animate-pulse")
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it("zeigt Fehlermeldung bei isError", () => {
    renderWithProviders(<KpiTiles stats={undefined} isLoading={false} isError={true} />)
    expect(screen.getByText(/konnten nicht geladen/i)).toBeInTheDocument()
  })

  it("zeigt korrekte Werte aus Stats", () => {
    const stats = mockEvaluationStats()
    renderWithProviders(<KpiTiles stats={stats} isLoading={false} />)
    // total_jobs(100) - evaluated(80) = 20 noch nicht evaluiert
    expect(screen.getByText("20")).toBeInTheDocument()
    // stage1_passed = 50
    expect(screen.getByText("50")).toBeInTheDocument()
    // stage2_completed = 40
    expect(screen.getByText("40")).toBeInTheDocument()
    // avg_score = 6.5
    expect(screen.getByText("6.5")).toBeInTheDocument()
  })

  it("zeigt Labels der KPI-Tiles", () => {
    const stats = mockEvaluationStats()
    renderWithProviders(<KpiTiles stats={stats} isLoading={false} />)
    expect(screen.getByText("Stage 1 bestanden")).toBeInTheDocument()
    expect(screen.getByText("Stage 2 bewertet")).toBeInTheDocument()
  })
})

describe("JobCard", () => {
  it("rendert Titel und Firma", () => {
    const job = mockJobListItem()
    renderWithProviders(<JobCard job={job} />)
    expect(screen.getByText("Senior Python Developer")).toBeInTheDocument()
    expect(screen.getByText("TechCorp GmbH")).toBeInTheDocument()
  })

  it("rendert Score", () => {
    const job = mockJobListItem({ stage2_score: 8.5 })
    renderWithProviders(<JobCard job={job} />)
    expect(screen.getByText("8.5")).toBeInTheDocument()
  })

  it("Anschreiben-Button ist disabled", () => {
    const job = mockJobListItem()
    renderWithProviders(<JobCard job={job} />)
    const btn = screen.getByRole("button", { name: /anschreiben/i })
    expect(btn).toBeDisabled()
  })

  it("Reviewed-Button ruft mutate mit status reviewed auf", async () => {
    const user = userEvent.setup()
    const job = mockJobListItem()
    renderWithProviders(<JobCard job={job} />)
    await user.click(screen.getByRole("button", { name: /reviewed/i }))
    expect(mockMutate).toHaveBeenCalledWith({ jobId: 1, status: "reviewed" })
  })

  it("Ignorieren-Button ruft mutate mit status ignored auf", async () => {
    const user = userEvent.setup()
    const job = mockJobListItem()
    renderWithProviders(<JobCard job={job} />)
    // X-Button hat kein label — suchen nach title
    const ignoreBtn = screen.getByTitle(/ignorieren/i)
    await user.click(ignoreBtn)
    expect(mockMutate).toHaveBeenCalledWith({ jobId: 1, status: "ignored" })
  })
})

describe("JobCardList", () => {
  it("zeigt EmptyState wenn keine Jobs vorhanden", () => {
    renderWithProviders(
      <JobCardList data={{ total: 0, jobs: [] }} isLoading={false} />,
    )
    expect(screen.getByText(/keine neuen stellen/i)).toBeInTheDocument()
  })

  it("rendert Job-Cards wenn Daten vorhanden", () => {
    const job = mockJobListItem()
    renderWithProviders(
      <JobCardList data={{ total: 1, jobs: [job] }} isLoading={false} />,
    )
    expect(screen.getByText("Senior Python Developer")).toBeInTheDocument()
  })
})
