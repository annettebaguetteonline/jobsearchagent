import { describe, it, expect } from "vitest"
import { screen } from "@testing-library/react"
import { renderWithProviders } from "../test-helpers"
import { ScoreBadge } from "@/components/dashboard/score-badge"

describe("ScoreBadge", () => {
  it("zeigt — bei null Score", () => {
    renderWithProviders(<ScoreBadge score={null} />)
    expect(screen.getByText("—")).toBeInTheDocument()
  })

  it("zeigt — bei undefined Score", () => {
    renderWithProviders(<ScoreBadge score={undefined} />)
    expect(screen.getByText("—")).toBeInTheDocument()
  })

  it("hat grüne Farbe bei Score >= 7", () => {
    renderWithProviders(<ScoreBadge score={7.5} />)
    const el = screen.getByText("7.5")
    expect(el).toHaveClass("bg-green-100")
    expect(el).toHaveClass("text-green-800")
  })

  it("hat gelbe Farbe bei Score 5-6.9", () => {
    renderWithProviders(<ScoreBadge score={6.0} />)
    const el = screen.getByText("6.0")
    expect(el).toHaveClass("bg-yellow-100")
    expect(el).toHaveClass("text-yellow-800")
  })

  it("hat rote Farbe bei Score < 5", () => {
    renderWithProviders(<ScoreBadge score={3.5} />)
    const el = screen.getByText("3.5")
    expect(el).toHaveClass("bg-red-100")
    expect(el).toHaveClass("text-red-800")
  })

  it("zeigt Score mit einer Dezimalstelle", () => {
    renderWithProviders(<ScoreBadge score={8} />)
    expect(screen.getByText("8.0")).toBeInTheDocument()
  })
})
