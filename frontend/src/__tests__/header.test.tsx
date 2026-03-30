import { describe, it, expect, vi } from "vitest"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderWithProviders } from "../test-helpers"
import { Header } from "@/components/layout/header"

const mockStartScrape = vi.fn()

vi.mock("@/lib/queries", () => ({
  useEvaluationStats: vi.fn(),
  useClarifications: vi.fn(),
  useStartScrape: vi.fn(),
}))

import { useEvaluationStats, useClarifications, useStartScrape } from "@/lib/queries"

function setupMocks({
  statsData = undefined as Record<string, unknown> | undefined,
  clarifData = undefined as Record<string, unknown> | undefined,
  isPending = false,
} = {}) {
  vi.mocked(useEvaluationStats).mockReturnValue({
    data: statsData,
    isLoading: false,
  } as ReturnType<typeof useEvaluationStats>)

  vi.mocked(useClarifications).mockReturnValue({
    data: clarifData,
    isLoading: false,
  } as ReturnType<typeof useClarifications>)

  vi.mocked(useStartScrape).mockReturnValue({
    mutate: mockStartScrape,
    isPending,
  } as ReturnType<typeof useStartScrape>)
}

describe("Header", () => {
  it("rendert ohne Fehler", () => {
    setupMocks()
    renderWithProviders(<Header />)
    expect(screen.getByText("Job Agent")).toBeInTheDocument()
  })

  it("zeigt Navigation-Links", () => {
    setupMocks()
    renderWithProviders(<Header />)
    expect(screen.getByRole("link", { name: "Übersicht" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Stellen" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Klärungsbedarf" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Analytics" })).toBeInTheDocument()
    expect(screen.getByRole("link", { name: "Steuerung" })).toBeInTheDocument()
  })

  it("zeigt Scan-Button", () => {
    setupMocks()
    renderWithProviders(<Header />)
    expect(screen.getByRole("button", { name: /scan starten/i })).toBeInTheDocument()
  })

  it("Scan-Button ist disabled während Pending", () => {
    setupMocks({ isPending: true })
    renderWithProviders(<Header />)
    expect(screen.getByRole("button", { name: /scan starten/i })).toBeDisabled()
  })

  it("zeigt Badge für neue Stellen wenn newCount > 0", () => {
    setupMocks({
      statsData: { total_jobs: 100, evaluated: 70 },
    })
    renderWithProviders(<Header />)
    expect(screen.getByText(/30 neu/)).toBeInTheDocument()
  })

  it("zeigt Badge für Klärungen wenn clarifTotal > 0", () => {
    setupMocks({
      clarifData: { total: 5, urgent: [] },
    })
    renderWithProviders(<Header />)
    expect(screen.getByText(/5 klärung/i)).toBeInTheDocument()
  })

  it("zeigt dringend-Badge wenn urgentCount > 0", () => {
    setupMocks({
      clarifData: { total: 3, urgent: [{ id: 1 }, { id: 2 }] },
    })
    renderWithProviders(<Header />)
    expect(screen.getByText(/2 dringend/i)).toBeInTheDocument()
  })

  it("Scan-Button ruft mutate auf", async () => {
    const user = userEvent.setup()
    setupMocks()
    renderWithProviders(<Header />)
    await user.click(screen.getByRole("button", { name: /scan starten/i }))
    expect(mockStartScrape).toHaveBeenCalled()
  })
})
