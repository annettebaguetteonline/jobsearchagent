import "@testing-library/jest-dom"

// Recharts uses ResizeObserver — mock it in jsdom
class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = ResizeObserverMock
