import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { api, ApiError } from "@/lib/api-client"

function makeFetchResponse(data: unknown, status = 200, statusText = "OK") {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText,
    json: () => Promise.resolve(data),
  }) as unknown as Promise<Response>
}

describe("api-client", () => {
  let fetchSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, "fetch")
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("GET Request formatiert URL korrekt", async () => {
    fetchSpy.mockReturnValue(makeFetchResponse({ jobs: [] }))
    await api.get("/jobs")
    const [url] = fetchSpy.mock.calls[0] as [string, ...unknown[]]
    expect(url).toContain("/api/jobs")
  })

  it("Query-Params werden korrekt gesetzt", async () => {
    fetchSpy.mockReturnValue(makeFetchResponse({}))
    await api.get("/jobs", { status: "new", limit: 20 })
    const [url] = fetchSpy.mock.calls[0] as [string, ...unknown[]]
    expect(url).toContain("status=new")
    expect(url).toContain("limit=20")
  })

  it("Undefined Params werden ausgelassen", async () => {
    fetchSpy.mockReturnValue(makeFetchResponse({}))
    await api.get("/jobs", { status: undefined, limit: 10 })
    const [url] = fetchSpy.mock.calls[0] as [string, ...unknown[]]
    expect(url).not.toContain("status=")
    expect(url).toContain("limit=10")
  })

  it("ApiError wird bei nicht-2xx Response geworfen", async () => {
    fetchSpy.mockReturnValue(makeFetchResponse({ detail: "Not found" }, 404, "Not Found"))
    await expect(api.get("/jobs/999")).rejects.toThrow(ApiError)
  })

  it("ApiError enthält Detail aus JSON-Response", async () => {
    fetchSpy.mockReturnValue(makeFetchResponse({ detail: "Stelle nicht gefunden" }, 404, "Not Found"))
    try {
      await api.get("/jobs/999")
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError)
      expect((e as ApiError).detail).toBe("Stelle nicht gefunden")
      expect((e as ApiError).status).toBe(404)
    }
  })

  it("POST Request sendet Body als JSON", async () => {
    fetchSpy.mockReturnValue(makeFetchResponse({ run_id: 42 }))
    await api.post("/scrape/start", { sources: ["kimeta"] })
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe("POST")
    expect(init.body).toBe(JSON.stringify({ sources: ["kimeta"] }))
  })

  it("GET Request ohne Body sendet keinen Body", async () => {
    fetchSpy.mockReturnValue(makeFetchResponse({}))
    await api.get("/evaluation/stats")
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit]
    expect(init.body).toBeUndefined()
  })
})
