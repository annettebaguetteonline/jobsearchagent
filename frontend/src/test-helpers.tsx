import { render, type RenderOptions } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter, type MemoryRouterProps } from "react-router-dom"
import type { ReactElement, ReactNode } from "react"

interface WrapperOptions {
  routerProps?: MemoryRouterProps
}

function createWrapper({ routerProps }: WrapperOptions = {}) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })

  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter {...routerProps}>
          {children}
        </MemoryRouter>
      </QueryClientProvider>
    )
  }
}

export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper"> & { wrapperOptions?: WrapperOptions },
) {
  const { wrapperOptions, ...renderOptions } = options ?? {}
  return render(ui, { wrapper: createWrapper(wrapperOptions), ...renderOptions })
}

// Mock-Daten-Factories

export function mockJobListItem(overrides: Record<string, unknown> = {}) {
  return {
    id: 1,
    canonical_id: "test-job-001",
    title: "Senior Python Developer",
    company_name: "TechCorp GmbH",
    company_city: "Frankfurt",
    company_remote_policy: "hybrid",
    company_careers_url: "https://techcorp.de/jobs",
    location_raw: "Frankfurt am Main",
    work_model: "hybrid",
    salary_raw: "65.000-80.000 EUR",
    deadline: "2026-04-30T00:00:00Z",
    first_seen_at: "2026-03-20T10:00:00Z",
    status: "new",
    stage2_score: 8.5,
    stage2_recommendation: "APPLY",
    stage1_pass: true,
    location_score: 0.85,
    location_effective_minutes: 25,
    ...overrides,
  }
}

export function mockEvaluationStats(overrides: Record<string, unknown> = {}) {
  return {
    total_jobs: 100,
    evaluated: 80,
    stage1_passed: 50,
    stage1_skipped: 30,
    stage2_completed: 40,
    avg_score: 6.5,
    recommendations: { APPLY: 15, MAYBE: 20, SKIP: 5 },
    ...overrides,
  }
}
