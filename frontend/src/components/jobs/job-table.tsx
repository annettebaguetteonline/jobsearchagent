import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
} from "@tanstack/react-table"
import {
  Table,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from "@/components/ui/table"
import { Button } from "@/components/ui/button"
import { ScoreBadge } from "@/components/dashboard/score-badge"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { EmptyState } from "@/components/ui/empty-state"
import { AlertCircle } from "lucide-react"
import type { JobFilterState } from "@/hooks/use-job-filters"

interface JobTableProps {
  data: { total: number; jobs: Record<string, unknown>[] } | undefined
  isLoading: boolean
  isError?: boolean
  selectedJobId: number | null
  onSelectJob: (id: number) => void
  filters: JobFilterState
  onFilterChange: (key: string, value: string | number | undefined) => void
}

const columns: ColumnDef<Record<string, unknown>>[] = [
  {
    id: "score",
    header: "Score",
    cell: ({ row }) => (
      <ScoreBadge score={row.original.stage2_score as number | null} size="sm" />
    ),
    size: 60,
  },
  {
    accessorKey: "title",
    header: "Titel",
    cell: ({ getValue }) => (
      <span className="font-medium">{getValue() as string}</span>
    ),
  },
  {
    accessorKey: "company_name",
    header: "Unternehmen",
  },
  {
    accessorKey: "location_raw",
    header: "Standort",
  },
  {
    accessorKey: "work_model",
    header: "Modell",
    cell: ({ getValue }) => {
      const v = getValue() as string | null
      return v ? (
        <Badge variant="outline" className="text-xs">
          {v}
        </Badge>
      ) : null
    },
    size: 80,
  },
  {
    accessorKey: "deadline",
    header: "Frist",
    cell: ({ getValue }) => {
      const v = getValue() as string | null
      return v ? v.split("T")[0] : "—"
    },
    size: 100,
  },
  {
    accessorKey: "status",
    header: "Status",
    cell: ({ getValue }) => (
      <Badge variant="secondary" className="text-xs">
        {getValue() as string}
      </Badge>
    ),
    size: 90,
  },
]

export function JobTable({
  data,
  isLoading,
  isError,
  selectedJobId,
  onSelectJob,
  filters,
  onFilterChange,
}: JobTableProps) {
  const jobs = data?.jobs ?? []
  const total = data?.total ?? 0

  const table = useReactTable({
    data: jobs,
    columns,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    pageCount: Math.ceil(total / filters.limit),
  })

  if (isLoading) {
    return (
      <div className="space-y-2">
        {Array.from({ length: 10 }).map((_, i) => (
          <Skeleton key={i} className="h-10 w-full" />
        ))}
      </div>
    )
  }

  if (isError) {
    return (
      <EmptyState
        icon={<AlertCircle className="mx-auto h-10 w-10 text-destructive" />}
        title="Fehler beim Laden"
        description="Stellen konnten nicht geladen werden. Bitte Seite neu laden."
      />
    )
  }

  return (
    <div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((header) => (
                  <TableHead key={header.id} style={{ width: header.getSize() }}>
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  className="py-8 text-center text-muted-foreground"
                >
                  Keine Stellen gefunden.
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  onClick={() => onSelectJob(row.original.id as number)}
                  className={`cursor-pointer transition-colors ${
                    (row.original.id as number) === selectedJobId
                      ? "bg-accent"
                      : "hover:bg-muted/50"
                  }`}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      {/* Pagination */}
      <div className="mt-4 flex items-center justify-between">
        <span className="text-sm text-muted-foreground">
          {filters.offset + 1}–{Math.min(filters.offset + filters.limit, total)} von {total}
        </span>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() =>
              onFilterChange("offset", Math.max(0, filters.offset - filters.limit))
            }
            disabled={filters.offset === 0}
          >
            Zurück
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => onFilterChange("offset", filters.offset + filters.limit)}
            disabled={filters.offset + filters.limit >= total}
          >
            Weiter
          </Button>
        </div>
      </div>
    </div>
  )
}
