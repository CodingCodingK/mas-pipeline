import { useEffect, useMemo, type MouseEvent as ReactMouseEvent } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  MarkerType,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import Dagre from "@dagrejs/dagre";
import "@xyflow/react/dist/style.css";

// ── Types (match GET /api/runs/{id}/graph response) ───────

export type RunNodeStatus =
  | "idle"
  | "running"
  | "completed"
  | "failed"
  | "paused"
  | "cancelled"
  | "skipped";

export interface RunGraphNode {
  id: string;
  name: string;
  role: string;
  output: string;
  status: RunNodeStatus;
  started_at: string | null;
  finished_at: string | null;
  output_preview: string | null;
}

export interface RunGraphEdge {
  from: string;
  to: string;
  kind: "sequence" | "conditional";
}

interface Props {
  nodes: RunGraphNode[];
  edges: RunGraphEdge[];
  onNodeClick?: (nodeId: string) => void;
  emptyMessage?: string;
}

// ── Status → color class (spec run-dag-visualization) ─────

export const STATUS_CLASS: Record<RunNodeStatus, string> = {
  idle: "bg-slate-100 border-slate-300 text-slate-600",
  running: "bg-blue-100 border-blue-400 text-blue-800 animate-pulse",
  completed: "bg-emerald-100 border-emerald-400 text-emerald-800",
  failed: "bg-rose-100 border-rose-400 text-rose-800",
  paused: "bg-amber-100 border-amber-400 text-amber-800",
  cancelled: "bg-slate-200 border-slate-500 text-slate-700",
  skipped: "bg-slate-50 border-slate-300 text-slate-400 border-dashed",
};

const NODE_W = 200;
const NODE_H = 64;

// ── Custom node ───────────────────────────────────────────

interface NodeData extends Record<string, unknown> {
  name: string;
  role: string;
  status: RunNodeStatus;
  preview: string | null;
}

function RunNodeComponent({ data }: NodeProps) {
  const d = data as NodeData;
  const cls = STATUS_CLASS[d.status] ?? STATUS_CLASS.idle;
  return (
    <>
      <Handle type="target" position={Position.Top} />
      <div
        data-status={d.status}
        className={`w-[200px] rounded-md border px-3 py-2 font-mono text-xs ${cls}`}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="truncate font-semibold">{d.name}</span>
          <span className="text-[9px] uppercase tracking-wide">{d.status}</span>
        </div>
        <div className="text-[10px] opacity-70 truncate">{d.role}</div>
      </div>
      <Handle type="source" position={Position.Bottom} />
    </>
  );
}

const nodeTypes = { run: RunNodeComponent };

// ── Layout ────────────────────────────────────────────────

function layout(
  nodes: RunGraphNode[],
  edges: RunGraphEdge[]
): { rfNodes: Node[]; rfEdges: Edge[] } {
  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 60, ranksep: 80 });

  for (const n of nodes) {
    g.setNode(n.id, { width: NODE_W, height: NODE_H });
  }
  for (const e of edges) {
    g.setEdge(e.from, e.to);
  }
  Dagre.layout(g);

  const rfNodes: Node[] = nodes.map((n) => {
    const pos = g.node(n.id);
    const data: NodeData = {
      name: n.name,
      role: n.role,
      status: n.status,
      preview: n.output_preview,
    };
    return {
      id: n.id,
      type: "run",
      position: {
        x: (pos?.x ?? 0) - NODE_W / 2,
        y: (pos?.y ?? 0) - NODE_H / 2,
      },
      data,
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
    };
  });

  const rfEdges: Edge[] = edges.map((e) => ({
    id: `${e.from}->${e.to}:${e.kind}`,
    source: e.from,
    target: e.to,
    animated: e.kind === "conditional",
    style: {
      stroke: e.kind === "conditional" ? "#f59e0b" : "#94a3b8",
      strokeWidth: 1.5,
      strokeDasharray: e.kind === "conditional" ? "5 4" : undefined,
    },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: e.kind === "conditional" ? "#f59e0b" : "#94a3b8",
      width: 14,
      height: 14,
    },
  }));

  return { rfNodes, rfEdges };
}

// ── Main component ────────────────────────────────────────

export default function RunGraph({ nodes, edges, onNodeClick, emptyMessage }: Props) {
  const laid = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const [rfNodes, setRfNodes] = useNodesState(laid.rfNodes);
  const [rfEdges, setRfEdges] = useEdgesState(laid.rfEdges);

  // Keep local React Flow state in sync when props change (SSE patches).
  useEffect(() => {
    setRfNodes(laid.rfNodes);
    setRfEdges(laid.rfEdges);
  }, [laid.rfNodes, laid.rfEdges, setRfNodes, setRfEdges]);

  const handleNodeClick = (_: ReactMouseEvent, node: Node) => {
    onNodeClick?.(node.id);
  };

  if (nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-400">
        {emptyMessage ?? "No nodes to display"}
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable
        minZoom={0.3}
        maxZoom={2}
      >
        <Background gap={16} size={1} color="#f1f5f9" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
