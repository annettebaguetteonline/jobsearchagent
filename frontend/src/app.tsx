import { lazy, Suspense } from "react"
import { Routes, Route, Navigate } from "react-router-dom"
import { PageLayout } from "@/components/layout/page-layout"
import { ErrorBoundary } from "@/components/ui/error-boundary"

const Uebersicht = lazy(() => import("@/pages/uebersicht"))
const Stellen = lazy(() => import("@/pages/stellen"))
const Klaerungsbedarf = lazy(() => import("@/pages/klaerungsbedarf"))
const Analytics = lazy(() => import("@/pages/analytics"))
const Steuerung = lazy(() => import("@/pages/steuerung"))

export function App() {
  return (
    <PageLayout>
      <ErrorBoundary>
        <Suspense fallback={<div className="p-8 text-muted-foreground">Laden...</div>}>
          <Routes>
            <Route path="/" element={<Navigate to="/uebersicht" replace />} />
            <Route path="/uebersicht" element={<Uebersicht />} />
            <Route path="/stellen" element={<Stellen />} />
            <Route path="/klaerungsbedarf" element={<Klaerungsbedarf />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/steuerung" element={<Steuerung />} />
          </Routes>
        </Suspense>
      </ErrorBoundary>
    </PageLayout>
  )
}
