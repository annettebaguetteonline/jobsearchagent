import { describe, it, expect, vi } from "vitest"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderWithProviders } from "../test-helpers"
import { ScrapingSection } from "@/components/control/scraping-section"
import { EvaluationSection } from "@/components/control/evaluation-section"
import { LocationSection } from "@/components/control/location-section"
import { FeedbackSection } from "@/components/control/feedback-section"

const mockStartScrape = vi.fn()
const mockRunStage1 = vi.fn()
const mockRunStage2 = vi.fn()
const mockResolveBatch = vi.fn()

vi.mock("@/lib/queries", () => ({
  useStartScrape: vi.fn(),
  useScrapeRun: vi.fn(),
  useCancelScrape: vi.fn(),
  useEvaluationStats: vi.fn(),
  useRunStage1: vi.fn(),
  useRunStage2: vi.fn(),
  useProfile: vi.fn(),
  useExtractProfile: vi.fn(),
  useLocationStats: vi.fn(),
  useResolveLocationBatch: vi.fn(),
  useFeedbackStats: vi.fn(),
}))

import {
  useStartScrape,
  useScrapeRun,
  useCancelScrape,
  useEvaluationStats,
  useRunStage1,
  useRunStage2,
  useProfile,
  useExtractProfile,
  useLocationStats,
  useResolveLocationBatch,
  useFeedbackStats,
} from "@/lib/queries"

function setupScrapingMocks({ isPending = false } = {}) {
  vi.mocked(useStartScrape).mockReturnValue({
    mutate: mockStartScrape,
    isPending,
    isError: false,
  } as ReturnType<typeof useStartScrape>)
  vi.mocked(useScrapeRun).mockReturnValue({
    data: undefined,
    isLoading: false,
  } as ReturnType<typeof useScrapeRun>)
  vi.mocked(useCancelScrape).mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as ReturnType<typeof useCancelScrape>)
}

function setupEvaluationMocks() {
  vi.mocked(useEvaluationStats).mockReturnValue({
    data: {
      total_jobs: 50,
      evaluated: 30,
      stage1_passed: 20,
      stage2_completed: 10,
      avg_score: 7.2,
      recommendations: { APPLY: 5, MAYBE: 3, SKIP: 2 },
    },
    isLoading: false,
  } as ReturnType<typeof useEvaluationStats>)
  vi.mocked(useRunStage1).mockReturnValue({
    mutate: mockRunStage1,
    isPending: false,
    isSuccess: false,
  } as ReturnType<typeof useRunStage1>)
  vi.mocked(useRunStage2).mockReturnValue({
    mutate: mockRunStage2,
    isPending: false,
    isSuccess: false,
  } as ReturnType<typeof useRunStage2>)
  vi.mocked(useProfile).mockReturnValue({
    data: undefined,
    isError: true,
    isLoading: false,
  } as ReturnType<typeof useProfile>)
  vi.mocked(useExtractProfile).mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
    isSuccess: false,
  } as ReturnType<typeof useExtractProfile>)
}

function setupLocationMocks() {
  vi.mocked(useLocationStats).mockReturnValue({
    data: {
      jobs_total: 100,
      jobs_resolved: 80,
      jobs_unknown: 10,
      jobs_failed: 5,
      companies_total: 40,
      companies_with_address: 35,
      companies_without_address: 5,
      transit_cache_entries: 120,
    },
    isLoading: false,
  } as ReturnType<typeof useLocationStats>)
  vi.mocked(useResolveLocationBatch).mockReturnValue({
    mutate: mockResolveBatch,
    isPending: false,
    isSuccess: false,
  } as ReturnType<typeof useResolveLocationBatch>)
}

function setupFeedbackMocks() {
  vi.mocked(useFeedbackStats).mockReturnValue({
    data: {
      total: 15,
      by_decision: { APPLY: 8, MAYBE: 5, SKIP: 2 },
      preference_patterns: [],
    },
    isLoading: false,
  } as ReturnType<typeof useFeedbackStats>)
}

describe("ScrapingSection", () => {
  it("zeigt Scan-Button", () => {
    setupScrapingMocks()
    renderWithProviders(<ScrapingSection />)
    expect(screen.getByRole("button", { name: /scan starten/i })).toBeInTheDocument()
  })

  it("Scan-Button ist disabled während Pending", () => {
    setupScrapingMocks({ isPending: true })
    renderWithProviders(<ScrapingSection />)
    expect(screen.getByRole("button", { name: /scan starten/i })).toBeDisabled()
  })

  it("Scan-Button ruft mutate auf", async () => {
    const user = userEvent.setup()
    setupScrapingMocks()
    renderWithProviders(<ScrapingSection />)
    await user.click(screen.getByRole("button", { name: /scan starten/i }))
    expect(mockStartScrape).toHaveBeenCalled()
  })
})

describe("EvaluationSection", () => {
  it("zeigt Stage 1 Button", () => {
    setupEvaluationMocks()
    renderWithProviders(<EvaluationSection />)
    expect(screen.getByRole("button", { name: /stage 1 starten/i })).toBeInTheDocument()
  })

  it("zeigt Stage 2 Button", () => {
    setupEvaluationMocks()
    renderWithProviders(<EvaluationSection />)
    expect(screen.getByRole("button", { name: /stage 2 starten/i })).toBeInTheDocument()
  })

  it("zeigt Evaluierungs-Stats", () => {
    setupEvaluationMocks()
    renderWithProviders(<EvaluationSection />)
    expect(screen.getByText("50")).toBeInTheDocument()
    expect(screen.getByText("30")).toBeInTheDocument()
  })

  it("Stage 1 Button ruft mutate auf", async () => {
    const user = userEvent.setup()
    setupEvaluationMocks()
    renderWithProviders(<EvaluationSection />)
    await user.click(screen.getByRole("button", { name: /stage 1 starten/i }))
    expect(mockRunStage1).toHaveBeenCalled()
  })
})

describe("LocationSection", () => {
  it("zeigt Batch-Auflösen-Button", () => {
    setupLocationMocks()
    renderWithProviders(<LocationSection />)
    expect(screen.getByRole("button", { name: /batch auflösen/i })).toBeInTheDocument()
  })

  it("zeigt Location-Stats", () => {
    setupLocationMocks()
    renderWithProviders(<LocationSection />)
    expect(screen.getByText("80")).toBeInTheDocument()
    expect(screen.getByText("Aufgelöst")).toBeInTheDocument()
  })
})

describe("FeedbackSection", () => {
  it("zeigt Feedback-Übersicht mit Gesamtanzahl", () => {
    setupFeedbackMocks()
    renderWithProviders(<FeedbackSection />)
    expect(screen.getByText("15")).toBeInTheDocument()
    expect(screen.getByText(/gesamt/i)).toBeInTheDocument()
  })

  it("zeigt Entscheidungs-Badges", () => {
    setupFeedbackMocks()
    renderWithProviders(<FeedbackSection />)
    expect(screen.getByText(/APPLY: 8/)).toBeInTheDocument()
    expect(screen.getByText(/MAYBE: 5/)).toBeInTheDocument()
  })

  it("zeigt Export-Button (disabled)", () => {
    setupFeedbackMocks()
    renderWithProviders(<FeedbackSection />)
    expect(screen.getByRole("button", { name: /export/i })).toBeDisabled()
  })
})
