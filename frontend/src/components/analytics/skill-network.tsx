import { useEffect, useRef, useCallback, useState } from "react"
import * as d3 from "d3"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { useAnalyticsSkillNetwork } from "@/lib/queries"

interface NetworkNode extends d3.SimulationNodeDatum {
  id: string
  count: number
  skill_type: string | null
}

interface NetworkLink extends d3.SimulationLinkDatum<NetworkNode> {
  source: string | NetworkNode
  target: string | NetworkNode
  weight: number
}

export function SkillNetwork() {
  const svgRef = useRef<SVGSVGElement>(null)
  const [threshold, setThreshold] = useState(2)
  const { data, isLoading } = useAnalyticsSkillNetwork()

  const networkData = data as {
    nodes: Array<{ id: string; count: number; skill_type: string | null }>
    links: Array<{ source: string; target: string; weight: number }>
  } | undefined

  const filteredLinks = (networkData?.links ?? []).filter((l) => l.weight >= threshold)
  const linkedNodeIds = new Set(filteredLinks.flatMap((l) => [l.source, l.target]))
  const filteredNodes = (networkData?.nodes ?? []).filter((n) => linkedNodeIds.has(n.id))

  const renderGraph = useCallback(() => {
    const svg = svgRef.current
    if (!svg || filteredNodes.length === 0) return

    const width = svg.clientWidth
    const height = 400

    d3.select(svg).selectAll("*").remove()

    const svgSelection = d3.select(svg)
      .attr("viewBox", `0 0 ${width} ${height}`)

    const g = svgSelection.append("g")
    svgSelection.call(
      d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.3, 3])
        .on("zoom", (event: d3.D3ZoomEvent<SVGSVGElement, unknown>) =>
          g.attr("transform", event.transform.toString())
        )
    )

    const maxCount = d3.max(filteredNodes, (d) => d.count) ?? 1
    const radiusScale = d3.scaleSqrt().domain([1, maxCount]).range([6, 24])

    const maxWeight = d3.max(filteredLinks, (d) => d.weight) ?? 1
    const widthScale = d3.scaleLinear().domain([1, maxWeight]).range([1, 5])

    const colorMap: Record<string, string> = {
      required: "#3b82f6",
      nice_to_have: "#a855f7",
      mentioned: "#6b7280",
    }
    const getColor = (type: string | null) => colorMap[type ?? "mentioned"] ?? "#6b7280"

    const simulation = d3.forceSimulation<NetworkNode>(filteredNodes as NetworkNode[])
      .force("link", d3.forceLink<NetworkNode, NetworkLink>(filteredLinks as NetworkLink[])
        .id((d) => d.id)
        .distance(80))
      .force("charge", d3.forceManyBody().strength(-150))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide<NetworkNode>().radius((d) => radiusScale(d.count) + 4))

    const link = g.selectAll<SVGLineElement, NetworkLink>("line")
      .data(filteredLinks as NetworkLink[])
      .join("line")
      .attr("stroke", "#d1d5db")
      .attr("stroke-width", (d) => widthScale(d.weight))
      .attr("stroke-opacity", 0.6)

    const node = g.selectAll<SVGCircleElement, NetworkNode>("circle")
      .data(filteredNodes as NetworkNode[])
      .join("circle")
      .attr("r", (d) => radiusScale(d.count))
      .attr("fill", (d) => getColor(d.skill_type))
      .attr("stroke", "#fff")
      .attr("stroke-width", 1.5)
      .call(d3.drag<SVGCircleElement, NetworkNode>()
        .on("start", (event: d3.D3DragEvent<SVGCircleElement, NetworkNode, NetworkNode>, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart()
          d.fx = d.x
          d.fy = d.y
        })
        .on("drag", (event: d3.D3DragEvent<SVGCircleElement, NetworkNode, NetworkNode>, d) => {
          d.fx = event.x
          d.fy = event.y
        })
        .on("end", (event: d3.D3DragEvent<SVGCircleElement, NetworkNode, NetworkNode>, d) => {
          if (!event.active) simulation.alphaTarget(0)
          d.fx = null
          d.fy = null
        })
      )

    const label = g.selectAll<SVGTextElement, NetworkNode>("text")
      .data(filteredNodes as NetworkNode[])
      .join("text")
      .text((d) => d.id)
      .attr("font-size", (d) => Math.max(9, Math.min(14, radiusScale(d.count))))
      .attr("text-anchor", "middle")
      .attr("dy", (d) => radiusScale(d.count) + 14)
      .attr("fill", "#374151")
      .attr("pointer-events", "none")

    node.on("mouseover", function (_event, d) {
      const connectedIds = new Set<string>()
      connectedIds.add(d.id)
      filteredLinks.forEach((l) => {
        const s = typeof l.source === "string" ? l.source : (l.source as NetworkNode).id
        const t = typeof l.target === "string" ? l.target : (l.target as NetworkNode).id
        if (s === d.id) connectedIds.add(t)
        if (t === d.id) connectedIds.add(s)
      })

      node.attr("opacity", (n) => connectedIds.has(n.id) ? 1 : 0.2)
      link.attr("opacity", (l) => {
        const s = typeof l.source === "string" ? l.source : l.source.id
        const t = typeof l.target === "string" ? l.target : l.target.id
        return s === d.id || t === d.id ? 1 : 0.1
      })
      label.attr("opacity", (n) => connectedIds.has(n.id) ? 1 : 0.2)
    })
    .on("mouseout", () => {
      node.attr("opacity", 1)
      link.attr("opacity", 0.6)
      label.attr("opacity", 1)
    })

    simulation.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as NetworkNode).x!)
        .attr("y1", (d) => (d.source as NetworkNode).y!)
        .attr("x2", (d) => (d.target as NetworkNode).x!)
        .attr("y2", (d) => (d.target as NetworkNode).y!)

      node
        .attr("cx", (d) => d.x!)
        .attr("cy", (d) => d.y!)

      label
        .attr("x", (d) => d.x!)
        .attr("y", (d) => d.y!)
    })

    return () => simulation.stop()
  }, [filteredNodes, filteredLinks])

  useEffect(() => {
    const cleanup = renderGraph()
    return () => cleanup?.()
  }, [renderGraph])

  if (isLoading) {
    return (
      <Card className="lg:col-span-2">
        <CardHeader><CardTitle className="text-base">Skill-Netzwerk</CardTitle></CardHeader>
        <CardContent><Skeleton className="h-[400px] w-full" /></CardContent>
      </Card>
    )
  }

  if (filteredNodes.length === 0) {
    return (
      <Card className="lg:col-span-2">
        <CardHeader><CardTitle className="text-base">Skill-Netzwerk</CardTitle></CardHeader>
        <CardContent className="flex h-48 items-center justify-center text-muted-foreground">
          Noch nicht genug Skill-Daten vorhanden.
        </CardContent>
      </Card>
    )
  }

  return (
    <Card className="lg:col-span-2">
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">Skill-Netzwerk</CardTitle>
        <div className="flex items-center gap-2 text-sm">
          <span>Min. Co-Occurrence:</span>
          <Input
            type="range"
            min={1}
            max={10}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            className="w-24"
          />
          <span className="font-mono">{threshold}</span>
        </div>
      </CardHeader>
      <CardContent>
        <svg ref={svgRef} className="h-[400px] w-full" />
        <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-full bg-blue-500" /> Required
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-full bg-purple-500" /> Nice-to-have
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-3 w-3 rounded-full bg-gray-500" /> Mentioned
          </span>
        </div>
      </CardContent>
    </Card>
  )
}
