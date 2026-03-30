import { describe, it, expect, vi, beforeEach } from "vitest"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderWithProviders } from "../test-helpers"
import { ClarificationCard } from "@/components/clarification/clarification-card"
import { ClarificationList } from "@/components/clarification/clarification-list"
import { ResolutionActions } from "@/components/clarification/resolution-actions"

const mockResolve = vi.fn()

vi.mock("@/lib/queries", () => ({
  useResolveClarification: vi.fn(),
  queryKeys: {
    clarifications: { all: ["clarifications"] },
  },
}))

vi.mock("@/lib/api-client", () => ({
  api: {
    post: vi.fn().mockResolvedValue({}),
  },
}))

import { useResolveClarification } from "@/lib/queries"

beforeEach(() => {
  vi.mocked(useResolveClarification).mockReturnValue({
    mutate: mockResolve,
    isPending: false,
  } as ReturnType<typeof useResolveClarification>)
})

const baseCardProps = {
  id: 1,
  entityTitle: "Senior Python Developer",
  entityCompany: "TechCorp GmbH",
  entityScore: 7.5,
  issueType: "address_unknown",
  severity: "yellow",
  attempts: null,
  createdAt: "2026-03-20T00:00:00Z",
  expanded: false,
  onToggle: vi.fn(),
}

describe("ClarificationCard", () => {
  it("rendert Titel und Firma", () => {
    renderWithProviders(<ClarificationCard {...baseCardProps} />)
    expect(screen.getByText("Senior Python Developer")).toBeInTheDocument()
    expect(screen.getByText("TechCorp GmbH")).toBeInTheDocument()
  })

  it("zeigt Issue-Label", () => {
    renderWithProviders(<ClarificationCard {...baseCardProps} />)
    expect(screen.getByText("Adresse unbekannt")).toBeInTheDocument()
  })

  it("zeigt Score-Badge", () => {
    renderWithProviders(<ClarificationCard {...baseCardProps} />)
    expect(screen.getByText("7.5")).toBeInTheDocument()
  })

  it("zeigt Toggle-Button bei nicht-urgent", () => {
    renderWithProviders(<ClarificationCard {...baseCardProps} />)
    expect(screen.getByRole("button", { name: /▼/ })).toBeInTheDocument()
  })

  it("zeigt Details wenn expanded=true", () => {
    renderWithProviders(
      <ClarificationCard {...baseCardProps} expanded={true} />,
    )
    expect(screen.getByText(/näherung übernehmen/i)).toBeInTheDocument()
  })

  it("zeigt immer Details bei urgenten Karten (severity=red)", () => {
    renderWithProviders(
      <ClarificationCard {...baseCardProps} severity="red" />,
    )
    // Kein Toggle-Button bei urgent
    expect(screen.queryByRole("button", { name: /▼/ })).not.toBeInTheDocument()
    // Details direkt sichtbar
    expect(screen.getByText(/näherung übernehmen/i)).toBeInTheDocument()
  })

  it("zeigt Versuche wenn vorhanden", () => {
    renderWithProviders(
      <ClarificationCard
        {...baseCardProps}
        expanded={true}
        attempts={[{ stage: "geocode", tried_at: "2026-03-19T00:00:00Z", result: "failed" }]}
      />,
    )
    expect(screen.getByText("geocode")).toBeInTheDocument()
    expect(screen.getByText("failed")).toBeInTheDocument()
  })

  it("zeigt Fallback #id wenn kein Titel", () => {
    renderWithProviders(
      <ClarificationCard {...baseCardProps} entityTitle={null} />,
    )
    expect(screen.getByText("#1")).toBeInTheDocument()
  })
})

describe("ClarificationList", () => {
  it("zeigt Loading-Skeletons", () => {
    const { container } = renderWithProviders(
      <ClarificationList urgent={[]} normal={[]} isLoading={true} />,
    )
    const skeletons = container.querySelectorAll(".animate-pulse")
    expect(skeletons.length).toBeGreaterThan(0)
  })

  it("zeigt EmptyState wenn keine Elemente", () => {
    renderWithProviders(
      <ClarificationList urgent={[]} normal={[]} isLoading={false} />,
    )
    expect(screen.getByText(/kein klärungsbedarf/i)).toBeInTheDocument()
  })

  it("zeigt Fehlermeldung bei isError", () => {
    renderWithProviders(
      <ClarificationList urgent={[]} normal={[]} isLoading={false} isError={true} />,
    )
    expect(screen.getByText(/fehler beim laden/i)).toBeInTheDocument()
  })

  it("rendert dringende Elemente mit Abschnittstitel", () => {
    const urgentItem = {
      id: 1,
      entity_title: "Dringende Stelle",
      entity_company: "Firma AG",
      entity_score: 8.0,
      issue_type: "address_unknown",
      severity: "red",
      attempts: null,
      created_at: "2026-03-20T00:00:00Z",
    }
    renderWithProviders(
      <ClarificationList urgent={[urgentItem]} normal={[]} isLoading={false} />,
    )
    expect(screen.getByText(/dringend \(1\)/i)).toBeInTheDocument()
    expect(screen.getByText("Dringende Stelle")).toBeInTheDocument()
  })

  it("rendert normale Elemente mit Abschnittstitel", () => {
    const normalItem = {
      id: 2,
      entity_title: "Normale Stelle",
      entity_company: "Firma GmbH",
      entity_score: 6.0,
      issue_type: "salary_parse",
      severity: "yellow",
      attempts: null,
      created_at: "2026-03-21T00:00:00Z",
    }
    renderWithProviders(
      <ClarificationList urgent={[]} normal={[normalItem]} isLoading={false} />,
    )
    expect(screen.getByText(/normal \(1\)/i)).toBeInTheDocument()
    expect(screen.getByText("Normale Stelle")).toBeInTheDocument()
  })
})

describe("ResolutionActions", () => {
  it("zeigt Näherung-Button", () => {
    renderWithProviders(<ResolutionActions id={1} issueType="address_unknown" />)
    expect(screen.getByRole("button", { name: /näherung übernehmen/i })).toBeInTheDocument()
  })

  it("zeigt Ausblenden-Button", () => {
    renderWithProviders(<ResolutionActions id={1} issueType="address_unknown" />)
    expect(screen.getByRole("button", { name: /ausblenden/i })).toBeInTheDocument()
  })

  it("Näherung-Button ruft resolve.mutate auf", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ResolutionActions id={42} issueType="address_unknown" />)
    await user.click(screen.getByRole("button", { name: /näherung übernehmen/i }))
    expect(mockResolve).toHaveBeenCalledWith({
      id: 42,
      resolved_by: "manual",
      resolution_note: "Näherung akzeptiert",
    })
  })

  it("Ausblenden-Button ruft resolve.mutate auf", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ResolutionActions id={42} issueType="address_unknown" />)
    await user.click(screen.getByRole("button", { name: /ausblenden/i }))
    expect(mockResolve).toHaveBeenCalledWith({
      id: 42,
      resolved_by: "manual",
      resolution_note: "Ausgeblendet",
    })
  })

  it("zeigt URL-Button für website_unknown Issue-Typ", () => {
    renderWithProviders(<ResolutionActions id={1} issueType="website_unknown" />)
    expect(screen.getByRole("button", { name: /url eingeben/i })).toBeInTheDocument()
  })

  it("zeigt kein URL-Button für andere Issue-Typen", () => {
    renderWithProviders(<ResolutionActions id={1} issueType="address_unknown" />)
    expect(screen.queryByRole("button", { name: /url eingeben/i })).not.toBeInTheDocument()
  })

  it("öffnet URL-Input nach Klick auf URL-Button", async () => {
    const user = userEvent.setup()
    renderWithProviders(<ResolutionActions id={1} issueType="website_unknown" />)
    await user.click(screen.getByRole("button", { name: /url eingeben/i }))
    expect(screen.getByPlaceholderText(/https/)).toBeInTheDocument()
  })
})
