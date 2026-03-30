import { describe, it, expect, vi, beforeEach } from "vitest"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderWithProviders } from "../test-helpers"
import JobDetailPanel from "@/components/jobs/job-detail-panel"
import { JobActions } from "@/components/jobs/job-actions"

const mockMutateStatus = vi.fn()
const mockMutateFeedback = vi.fn()

vi.mock("@/lib/queries", () => ({
  useJob: vi.fn(),
  useUpdateJobStatus: () => ({
    mutate: mockMutateStatus,
    isPending: false,
  }),
  useSubmitFeedback: () => ({
    mutate: mockMutateFeedback,
    isPending: false,
    isSuccess: false,
  }),
}))

import { useJob } from "@/lib/queries"

const mockJob = {
  id: 1,
  title: "Senior Python Developer",
  status: "new",
  work_model: "hybrid",
  location_raw: "Frankfurt am Main",
  salary_raw: "65.000-80.000 EUR",
  company: {
    id: 10,
    name: "TechCorp GmbH",
    address_city: "Frankfurt",
    remote_policy: "hybrid",
  },
  evaluation: {
    stage2_score: 8.5,
    stage2_score_breakdown: { skills: 9, level: 8, domain: 7 },
    stage2_summary: "Gute Übereinstimmung mit dem Profil.",
    stage2_match_reasons: ["Python Kenntnisse passen", "Remote-Option vorhanden"],
    stage2_missing_skills: ["Kubernetes", "Terraform"],
    stage2_application_tips: ["Erfahrung mit Microservices betonen"],
    location_score: 0.85,
    location_effective_minutes: 25,
  },
  sources: [
    { id: 1, url: "https://techcorp.de/jobs/1", source_name: "TechCorp Karriere", is_canonical: true },
  ],
  skills: [
    { skill: "Python", skill_type: "required" },
    { skill: "FastAPI", skill_type: "optional" },
  ],
}

describe("JobDetailPanel", () => {
  beforeEach(() => {
    vi.mocked(useJob).mockReturnValue({
      data: mockJob,
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useJob>)
  })

  it("zeigt Titel und Firma", () => {
    renderWithProviders(<JobDetailPanel jobId={1} onClose={vi.fn()} />)
    expect(screen.getByText("Senior Python Developer")).toBeInTheDocument()
    expect(screen.getByText(/TechCorp GmbH/)).toBeInTheDocument()
  })

  it("zeigt Score-Badge", () => {
    renderWithProviders(<JobDetailPanel jobId={1} onClose={vi.fn()} />)
    expect(screen.getByText("8.5")).toBeInTheDocument()
  })

  it("zeigt Match-Gründe als Liste", () => {
    renderWithProviders(<JobDetailPanel jobId={1} onClose={vi.fn()} />)
    expect(screen.getByText(/Python Kenntnisse passen/)).toBeInTheDocument()
    expect(screen.getByText(/Remote-Option vorhanden/)).toBeInTheDocument()
  })

  it("zeigt fehlende Skills als Badges", () => {
    renderWithProviders(<JobDetailPanel jobId={1} onClose={vi.fn()} />)
    expect(screen.getByText("Kubernetes")).toBeInTheDocument()
    expect(screen.getByText("Terraform")).toBeInTheDocument()
  })

  it("zeigt Quellen-Link als <a>-Tag mit target=_blank", () => {
    renderWithProviders(<JobDetailPanel jobId={1} onClose={vi.fn()} />)
    const link = screen.getByRole("link", { name: /TechCorp Karriere/ })
    expect(link).toHaveAttribute("href", "https://techcorp.de/jobs/1")
    expect(link).toHaveAttribute("target", "_blank")
  })

  it("ruft onClose auf beim Klick auf Schließen-Button", async () => {
    const user = userEvent.setup()
    const onClose = vi.fn()
    renderWithProviders(<JobDetailPanel jobId={1} onClose={onClose} />)
    // X-Button — findet den Button mit SVG-Icon
    const closeBtn = screen.getAllByRole("button").find((btn) =>
      btn.querySelector("svg"),
    )
    if (closeBtn) await user.click(closeBtn)
    expect(onClose).toHaveBeenCalled()
  })

  it("zeigt Skeleton bei isLoading", () => {
    vi.mocked(useJob).mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
    } as ReturnType<typeof useJob>)
    const { container } = renderWithProviders(<JobDetailPanel jobId={1} onClose={vi.fn()} />)
    const skeletons = container.querySelectorAll(".animate-pulse")
    expect(skeletons.length).toBeGreaterThan(0)
  })
})

describe("JobActions", () => {
  it("zeigt Status-Dropdown mit aktuellem Status", () => {
    renderWithProviders(<JobActions jobId={1} currentStatus="new" />)
    const select = screen.getByRole("combobox")
    expect(select).toHaveValue("new")
  })

  it("zeigt Feedback-Buttons APPLY/MAYBE/SKIP/IGNORE", () => {
    renderWithProviders(<JobActions jobId={1} currentStatus="new" />)
    expect(screen.getByRole("button", { name: "APPLY" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "MAYBE" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "SKIP" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "IGNORE" })).toBeInTheDocument()
  })

  it("zeigt Begründungsfeld nach Klick auf Feedback-Button", async () => {
    const user = userEvent.setup()
    renderWithProviders(<JobActions jobId={1} currentStatus="new" />)
    await user.click(screen.getByRole("button", { name: "APPLY" }))
    expect(screen.getByPlaceholderText(/begründung/i)).toBeInTheDocument()
  })

  it("Status-Änderung ruft mutate auf", async () => {
    const user = userEvent.setup()
    renderWithProviders(<JobActions jobId={1} currentStatus="new" />)
    const select = screen.getByRole("combobox")
    await user.selectOptions(select, "reviewed")
    expect(mockMutateStatus).toHaveBeenCalledWith({ jobId: 1, status: "reviewed" })
  })
})
