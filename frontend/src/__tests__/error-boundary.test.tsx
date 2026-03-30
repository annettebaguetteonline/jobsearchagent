import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { renderWithProviders } from "../test-helpers"
import { ErrorBoundary } from "@/components/ui/error-boundary"

function ThrowingComponent({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) throw new Error("Test-Fehler")
  return <div>Kein Fehler</div>
}

describe("ErrorBoundary", () => {
  // Unterdrücke React-Fehler-Logs in Tests
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("rendert Kinder wenn kein Fehler", () => {
    renderWithProviders(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={false} />
      </ErrorBoundary>,
    )
    expect(screen.getByText("Kein Fehler")).toBeInTheDocument()
  })

  it("zeigt Fehler-UI wenn Kind einen Fehler wirft", () => {
    renderWithProviders(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    )
    expect(screen.getByText(/schiefgelaufen/i)).toBeInTheDocument()
    expect(screen.getByText("Test-Fehler")).toBeInTheDocument()
  })

  it("zeigt Fehlermeldung in der Fehler-UI", () => {
    renderWithProviders(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    )
    expect(screen.getByRole("button", { name: /erneut versuchen/i })).toBeInTheDocument()
  })

  it("zeigt custom Fallback wenn angegeben", () => {
    renderWithProviders(
      <ErrorBoundary fallback={<div>Mein Fallback</div>}>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    )
    expect(screen.getByText("Mein Fallback")).toBeInTheDocument()
  })

  it("Erneut-versuchen-Button ist klickbar", async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <ErrorBoundary>
        <ThrowingComponent shouldThrow={true} />
      </ErrorBoundary>,
    )
    expect(screen.getByText(/schiefgelaufen/i)).toBeInTheDocument()
    const retryBtn = screen.getByRole("button", { name: /erneut versuchen/i })
    expect(retryBtn).toBeEnabled()
    // Klick sollte keinen Fehler werfen
    await user.click(retryBtn)
  })
})
