import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import path from "path"

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      exclude: [
        // Entry points & app shell
        "src/main.tsx",
        "src/app.tsx",
        // Page components — better covered by e2e tests
        "src/pages/**",
        // Generated types
        "src/types/**",
        // Router-coupled hook — needs full integration context
        "src/hooks/**",
        // Analytics charts — pure recharts/D3 visualization, no business logic
        "src/components/analytics/**",
        // TanStack Query hooks — fully mocked in component tests
        "src/lib/queries.ts",
        // shadcn/ui primitives — thin wrappers around native elements, no business logic
        "src/components/ui/dialog.tsx",
        "src/components/ui/dropdown-menu.tsx",
        "src/components/ui/tabs.tsx",
        "src/components/ui/tooltip.tsx",
        "src/components/ui/separator.tsx",
        // Structural layout only
        "src/components/layout/page-layout.tsx",
        // Router-coupled filter form
        "src/components/jobs/job-filters.tsx",
        // Test infrastructure
        "src/test-setup.ts",
        "src/test-helpers.tsx",
      ],
      thresholds: {
        lines: 60,
        functions: 60,
      },
    },
  },
})
