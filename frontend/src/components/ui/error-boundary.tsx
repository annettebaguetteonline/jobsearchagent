import { Component, type ErrorInfo, type ReactNode } from "react"
import { Button } from "./button"
import { Card, CardContent } from "./card"

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info)
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback

      return (
        <Card className="mx-auto mt-8 max-w-md border-destructive">
          <CardContent className="p-6 text-center">
            <h3 className="text-lg font-semibold text-destructive">Etwas ist schiefgelaufen</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              {this.state.error?.message ?? "Unbekannter Fehler"}
            </p>
            <Button
              variant="outline"
              className="mt-4"
              onClick={() => this.setState({ hasError: false, error: null })}
            >
              Erneut versuchen
            </Button>
          </CardContent>
        </Card>
      )
    }

    return this.props.children
  }
}
