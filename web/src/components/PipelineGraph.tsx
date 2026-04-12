import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent as ReactMouseEvent,
} from "react";
import {
  ReactFlow,
  Background,
  Controls,
  Panel,
  Handle,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  type Node,
  type Edge,
  type OnNodesChange,
  type OnEdgesChange,
  type OnConnect,
  type Connection,
  type NodeProps,
  Position,
  MarkerType,
} from "@xyflow/react";
import Dagre from "@dagrejs/dagre";
import { parse as parseYaml, stringify as stringifyYaml } from "yaml";
import "@xyflow/react/dist/style.css";

// ── Types ─────────────────────────────────────────────────

interface PipelineNode {
  name: string;
  role?: string;
  input?: string[];
  output?: string;
  interrupt?: boolean;
}

interface PipelineYaml {
  pipeline?: string;
  description?: string;
  nodes?: PipelineNode[];
}

interface NodeData extends Record<string, unknown> {
  label: string;
  role: string;
  output: string;
  interrupt: boolean;
}

interface AgentOption {
  name: string;
  description: string;
}

interface Props {
  yamlContent: string;
  onChange?: (yaml: string) => void;
  agents?: AgentOption[];
}

// ── Constants ─────────────────────────────────────────────

const NODE_W = 180;
const NODE_H = 60;

const nodeStyle = {
  width: NODE_W,
  background: "#fff",
  border: "1px solid #e2e8f0",
  borderRadius: 8,
  fontSize: 12,
  fontFamily: "ui-monospace, monospace",
  padding: "6px 10px",
};

const interruptNodeStyle = {
  ...nodeStyle,
  border: "2px dashed #f59e0b",
  background: "#fffbeb",
};

const edgeDefaults = {
  style: { stroke: "#94a3b8", strokeWidth: 1.5 },
  markerEnd: { type: MarkerType.ArrowClosed, color: "#94a3b8", width: 14, height: 14 },
  labelStyle: { fontSize: 10, fill: "#94a3b8" },
};

// ── YAML → Graph ──────────────────────────────────────────

function yamlToGraph(yamlContent: string): {
  nodes: Node[];
  edges: Edge[];
  meta: { pipeline?: string; description?: string };
} | null {
  let parsed: PipelineYaml;
  try {
    parsed = parseYaml(yamlContent) as PipelineYaml;
  } catch {
    return null;
  }
  if (!parsed?.nodes?.length) return null;

  const outputToNode = new Map<string, string>();
  for (const n of parsed.nodes) {
    if (n.output) outputToNode.set(n.output, n.name);
  }

  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", nodesep: 60, ranksep: 80 });

  for (const n of parsed.nodes) {
    g.setNode(n.name, { width: NODE_W, height: NODE_H });
  }

  const edges: Edge[] = [];
  for (const n of parsed.nodes) {
    if (n.input) {
      for (const inp of n.input) {
        const source = outputToNode.get(inp);
        if (source) {
          g.setEdge(source, n.name);
          edges.push({
            id: `${source}->${n.name}:${inp}`,
            source,
            target: n.name,
            label: inp,
            ...edgeDefaults,
          });
        }
      }
    }
  }

  Dagre.layout(g);

  const nodes: Node[] = parsed.nodes.map((n) => {
    const pos = g.node(n.name);
    const data: NodeData = {
      label: n.name,
      role: n.role || n.name,
      output: n.output || n.name,
      interrupt: !!n.interrupt,
    };
    return {
      id: n.name,
      type: "pipeline",
      position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
      data,
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
      style: n.interrupt ? interruptNodeStyle : nodeStyle,
    };
  });

  return {
    nodes,
    edges,
    meta: { pipeline: parsed.pipeline, description: parsed.description },
  };
}

// ── Graph → YAML ──────────────────────────────────────────

function graphToYaml(
  nodes: Node[],
  edges: Edge[],
  meta: { pipeline?: string; description?: string }
): string {
  const edgesByTarget = new Map<string, string[]>();
  const edgeLabel = new Map<string, string>();
  for (const e of edges) {
    const key = `${e.source}->${e.target}`;
    edgeLabel.set(key, (e.label as string) || "");
    const arr = edgesByTarget.get(e.target) || [];
    arr.push(e.source);
    edgesByTarget.set(e.target, arr);
  }

  // Topological sort via Kahn's algorithm
  const inDegree = new Map<string, number>();
  for (const n of nodes) inDegree.set(n.id, 0);
  for (const e of edges) {
    inDegree.set(e.target, (inDegree.get(e.target) || 0) + 1);
  }
  const queue = nodes.filter((n) => (inDegree.get(n.id) || 0) === 0).map((n) => n.id);
  const sorted: string[] = [];
  while (queue.length) {
    const id = queue.shift()!;
    sorted.push(id);
    for (const e of edges) {
      if (e.source === id) {
        const deg = (inDegree.get(e.target) || 1) - 1;
        inDegree.set(e.target, deg);
        if (deg === 0) queue.push(e.target);
      }
    }
  }
  // Append any nodes missed by topo sort (cycles or isolates)
  for (const n of nodes) {
    if (!sorted.includes(n.id)) sorted.push(n.id);
  }

  const nodeMap = new Map(nodes.map((n) => [n.id, n]));

  const yamlNodes: PipelineNode[] = sorted.map((id) => {
    const n = nodeMap.get(id)!;
    const d = n.data as NodeData;
    const sources = edgesByTarget.get(id);
    const inputs = sources
      ?.map((src) => {
        const label = edgeLabel.get(`${src}->${id}`);
        return label || (nodeMap.get(src)?.data as NodeData)?.output || src;
      })
      .filter((x): x is string => Boolean(x));

    const entry: PipelineNode = { name: d.label || id };
    if (d.role && d.role !== entry.name) entry.role = d.role;
    if (inputs && inputs.length > 0) entry.input = inputs;
    if (d.output) entry.output = d.output;
    if (d.interrupt) entry.interrupt = true;
    return entry;
  });

  const obj: PipelineYaml = {};
  if (meta.pipeline) obj.pipeline = meta.pipeline;
  if (meta.description) obj.description = meta.description;
  obj.nodes = yamlNodes;

  return stringifyYaml(obj, { lineWidth: 0 });
}

// ── Edit Dialog ───────────────────────────────────────────

function NodeEditDialog({
  node,
  onSave,
  onCancel,
  agents,
  availableOutputs,
}: {
  node: Node;
  onSave: (data: { name: string; role: string; output: string; interrupt: boolean }) => void;
  onCancel: () => void;
  agents: AgentOption[];
  availableOutputs: { nodeId: string; output: string }[];
}) {
  const d = node.data as NodeData;
  const isNew = node.id.startsWith("node_");
  const [name, setName] = useState(isNew ? "" : (d.label || node.id));
  const [role, setRole] = useState(d.role || "");
  const [output, setOutput] = useState(isNew ? "" : (d.output || ""));
  const [interrupt, setInterrupt] = useState(d.interrupt || false);
  const selectedAgent = agents.find((a) => a.name === role);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onCancel]);

  // Auto-fill output from name
  const handleNameChange = (v: string) => {
    setName(v);
    if (!output || output === name) setOutput(v);
  };

  return (
    <div
      ref={ref}
      className="absolute inset-0 z-50 flex items-center justify-center bg-black/20"
      onClick={(e) => { if (e.target === ref.current) onCancel(); }}
    >
      <div className="bg-white rounded-lg border border-slate-200 shadow-lg p-4 w-80 space-y-3">
        <h3 className="text-sm font-medium">{isNew ? "Add Node" : "Edit Node"}</h3>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Name</label>
          <input
            autoFocus
            value={name}
            onChange={(e) => handleNameChange(e.target.value)}
            placeholder="e.g. writer"
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm font-mono"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Role (Agent)</label>
          {agents.length > 0 ? (
            <>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full rounded border border-slate-300 px-2 py-1 text-sm font-mono"
              >
                <option value="">-- select agent --</option>
                {agents.map((a) => (
                  <option key={a.name} value={a.name}>{a.name}</option>
                ))}
              </select>
              {selectedAgent?.description && (
                <p className="mt-1 text-[11px] text-slate-400 leading-tight">{selectedAgent.description}</p>
              )}
            </>
          ) : (
            <input
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="agent role name"
              className="w-full rounded border border-slate-300 px-2 py-1 text-sm font-mono"
            />
          )}
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Output key</label>
          <input
            value={output}
            onChange={(e) => setOutput(e.target.value)}
            placeholder="e.g. draft"
            className="w-full rounded border border-slate-300 px-2 py-1 text-sm font-mono"
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-600 cursor-pointer">
          <input
            type="checkbox"
            checked={interrupt}
            onChange={(e) => setInterrupt(e.target.checked)}
            className="rounded border-slate-300"
          />
          Interrupt (pause for human review)
        </label>
        {availableOutputs.length > 0 && (
          <div>
            <label className="block text-xs text-slate-500 mb-1">
              Inputs (connect from)
            </label>
            <p className="text-[10px] text-slate-400 mb-1">
              Connections are managed by dragging edges on the graph
            </p>
            <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-xs text-slate-600 space-y-0.5">
              {availableOutputs.map((o) => (
                <div key={o.nodeId} className="font-mono">
                  {o.nodeId} → <span className="text-slate-400">{o.output}</span>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-slate-300 px-3 py-1 text-xs"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onSave({ name: name.trim(), role: role.trim(), output: output.trim(), interrupt })}
            disabled={!name.trim()}
            className="rounded bg-slate-900 px-3 py-1 text-xs text-white disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Custom Node ──────────────────────────────────────────

function PipelineNodeComponent({ data }: NodeProps) {
  const d = data as NodeData;
  return (
    <>
      <Handle type="target" position={Position.Top} />
      <div className="text-center">
        <span>{d.label}</span>
        {d.interrupt && (
          <span className="ml-1.5 text-amber-600 text-[10px] font-semibold" title="Interrupt: pauses for human review">
            &#x23F8;
          </span>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} />
    </>
  );
}

const nodeTypes = { pipeline: PipelineNodeComponent };

// ── Main Component ────────────────────────────────────────

export default function PipelineGraph({ yamlContent, onChange, agents = [] }: Props) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [meta, setMeta] = useState<{ pipeline?: string; description?: string }>({});
  const [editNode, setEditNode] = useState<Node | null>(null);

  // Suppress feedback loop: skip syncing from YAML when we just generated it
  const selfUpdate = useRef(false);

  // YAML → Graph (external edits)
  useEffect(() => {
    if (selfUpdate.current) {
      selfUpdate.current = false;
      return;
    }
    const result = yamlToGraph(yamlContent);
    if (result) {
      setNodes(result.nodes);
      setEdges(result.edges);
      setMeta(result.meta);
    }
  }, [yamlContent]);

  // Graph → YAML (visual edits)
  const emitYaml = useCallback(
    (n: Node[], e: Edge[]) => {
      if (!onChange) return;
      selfUpdate.current = true;
      onChange(graphToYaml(n, e, meta));
    },
    [onChange, meta]
  );

  const onNodesChange: OnNodesChange = useCallback(
    (changes) => {
      setNodes((prev) => {
        const next = applyNodeChanges(changes, prev);
        // Only emit on position changes (drag end) or removes
        const hasMeaningful = changes.some(
          (c) => c.type === "remove" || (c.type === "position" && c.dragging === false)
        );
        if (hasMeaningful) emitYaml(next, edges);
        return next;
      });
    },
    [edges, emitYaml]
  );

  const onEdgesChange: OnEdgesChange = useCallback(
    (changes) => {
      setEdges((prev) => {
        const next = applyEdgeChanges(changes, prev);
        if (changes.some((c) => c.type === "remove")) emitYaml(nodes, next);
        return next;
      });
    },
    [nodes, emitYaml]
  );

  const onConnect: OnConnect = useCallback(
    (conn: Connection) => {
      const sourceNode = nodes.find((n) => n.id === conn.source);
      const label = (sourceNode?.data as NodeData | undefined)?.output || conn.source;
      const newEdge: Edge = {
        ...conn,
        id: `${conn.source}->${conn.target}:${label}`,
        label,
        ...edgeDefaults,
      };
      setEdges((prev) => {
        const next = addEdge(newEdge, prev);
        emitYaml(nodes, next);
        return next;
      });
    },
    [nodes, emitYaml]
  );

  const addNode = useCallback(() => {
    const id = `node_${Date.now()}`;
    const maxY = nodes.reduce((m, n) => Math.max(m, n.position.y), 0);
    const data: NodeData = { label: id, role: id, output: id, interrupt: false };
    const newNode: Node = {
      id,
      type: "pipeline",
      position: { x: 100, y: maxY + NODE_H + 60 },
      data,
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
      style: nodeStyle,
    };
    setNodes((prev) => {
      const next = [...prev, newNode];
      emitYaml(next, edges);
      return next;
    });
    // Open edit dialog immediately
    setEditNode(newNode);
  }, [nodes, edges, emitYaml]);

  const onNodeDoubleClick = useCallback(
    (_: ReactMouseEvent, node: Node) => setEditNode(node),
    []
  );

  const handleNodeSave = useCallback(
    (data: { name: string; role: string; output: string; interrupt: boolean }) => {
      if (!editNode) return;
      const oldId = editNode.id;
      const newId = data.name || oldId;

      setNodes((prev) => {
        const newData: NodeData = {
          label: data.name,
          role: data.role || data.name,
          output: data.output || data.name,
          interrupt: data.interrupt,
        };
        const style = data.interrupt ? interruptNodeStyle : nodeStyle;
        const next = prev.map((n) =>
          n.id === oldId
            ? { ...n, id: newId, data: newData, style }
            : n
        );
        // Also update edges if node was renamed
        if (oldId !== newId) {
          setEdges((prevEdges) => {
            const nextEdges = prevEdges.map((e) => ({
              ...e,
              id: e.id.replace(oldId, newId),
              source: e.source === oldId ? newId : e.source,
              target: e.target === oldId ? newId : e.target,
            }));
            emitYaml(next, nextEdges);
            return nextEdges;
          });
        } else {
          emitYaml(next, edges);
        }
        return next;
      });
      setEditNode(null);
    },
    [editNode, edges, emitYaml]
  );

  const readOnly = !onChange;

  if (!yamlContent.trim() && nodes.length === 0) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-slate-400">
        {readOnly ? "Invalid or empty pipeline YAML" : "Click \"+ Add Node\" to start building"}
      </div>
    );
  }

  return (
    <div className="h-full relative">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={readOnly ? undefined : onNodesChange}
        onEdgesChange={readOnly ? undefined : onEdgesChange}
        onConnect={readOnly ? undefined : onConnect}
        onNodeDoubleClick={readOnly ? undefined : onNodeDoubleClick}
        fitView
        proOptions={{ hideAttribution: true }}
        nodesDraggable={!readOnly}
        nodesConnectable={!readOnly}
        elementsSelectable={!readOnly}
        deleteKeyCode={readOnly ? "" : "Backspace"}
        minZoom={0.3}
        maxZoom={2}
        snapToGrid
        snapGrid={[10, 10]}
      >
        <Background gap={16} size={1} color="#f1f5f9" />
        <Controls showInteractive={false} />
        {!readOnly && (
          <Panel position="top-right">
            <button
              type="button"
              onClick={addNode}
              className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white shadow"
            >
              + Add Node
            </button>
          </Panel>
        )}
        {!readOnly && (
          <Panel position="bottom-left">
            <div className="text-[10px] text-slate-400 bg-white/80 rounded px-2 py-1">
              Double-click to edit &middot; Drag to connect &middot; Backspace to delete
            </div>
          </Panel>
        )}
      </ReactFlow>
      {editNode && (
        <NodeEditDialog
          node={editNode}
          onSave={handleNodeSave}
          onCancel={() => setEditNode(null)}
          agents={agents}
          availableOutputs={nodes
            .filter((n) => n.id !== editNode.id)
            .map((n) => ({
              nodeId: n.id,
              output: (n.data as NodeData).output || n.id,
            }))}
        />
      )}
    </div>
  );
}
