import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, Link } from "react-router-dom";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import { client, ApiError, __internal } from "@/api/client";
import { fetchEventStream, type SseEvent } from "@/api/sse";
import type { RunDetail } from "@/api/types";

async function downloadExport(runId: string, fmt: "md" | "json") {
  const url =
    __internal.apiBase().replace(/\/$/, "") +
    `/runs/${runId}/export?fmt=${fmt}`;
  const headers = __internal.buildHeaders(false);
  const resp = await fetch(url, { headers });
  if (!resp.ok) throw new Error(`Export failed: ${resp.status}`);
  const blob = await resp.blob();
  const cd = resp.headers.get("content-disposition") || "";
  const match = cd.match(/filename="?([^"]+)"?/);
  const filename = match ? match[1] : `${runId}.${fmt}`;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ── Types ─────────────────────────────────────────────────

interface StreamState {
  liveStream?: boolean;
  pipelineName?: string;
  inputText?: string;
}

interface RunSummary {
  llm_calls: number;
  tool_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  total_llm_latency_ms: number;
  duration_ms: number | null;
  errors: number;
}

interface TimelineEvent {
  id: number;
  ts: string;
  event_type: string;
  agent_role: string | null;
  payload: Record<string, unknown>;
}

interface AgentRollup {
  agent_role: string;
  turn_count: number;
  llm_calls: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  errors: number;
}

interface AgentRunItem {
  id: number;
  role: string;
  description: string | null;
  status: string;
  owner: string | null;
  result: string | null;
  created_at: string | null;
  updated_at: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  running: "bg-blue-100 text-blue-800",
  pending: "bg-slate-100 text-slate-600",
  paused: "bg-yellow-100 text-yellow-800",
  cancelled: "bg-slate-100 text-slate-500",
};

const PIE_COLORS = [
  "#3b82f6",
  "#22c55e",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#ec4899",
  "#64748b",
];

type TabId = "result" | "timeline" | "telemetry" | "events";

// ── Stat Card ─────────────────────────────────────────────

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold mt-0.5">{value}</div>
    </div>
  );
}

// ── Timeline ──────────────────────────────────────────────

interface TimelineNode {
  event: TimelineEvent;
  children: TimelineEvent[];
}

function buildTimelineTree(events: TimelineEvent[]): TimelineNode[] {
  const nodes: TimelineNode[] = [];
  let currentNode: TimelineNode | null = null;

  for (const e of events) {
    const et = e.event_type;
    if (et === "pipeline_event") {
      const pet = e.payload.pipeline_event_type as string;
      if (pet === "node_start") {
        currentNode = { event: e, children: [] };
        nodes.push(currentNode);
      } else if (pet === "node_end" || pet === "node_failed") {
        if (currentNode) {
          currentNode.children.push(e);
          currentNode = null;
        } else {
          nodes.push({ event: e, children: [] });
        }
      } else {
        nodes.push({ event: e, children: [] });
      }
    } else if (et === "agent_turn") {
      if (currentNode) currentNode.children.push(e);
      else nodes.push({ event: e, children: [] });
    } else if (et === "tool_call" || et === "llm_call") {
      if (currentNode) currentNode.children.push(e);
    }
  }
  return nodes;
}

function eventIcon(e: TimelineEvent): string {
  const p = e.payload;
  if (e.event_type === "pipeline_event") {
    const pet = p.pipeline_event_type as string;
    if (pet === "pipeline_start") return "🚀";
    if (pet === "pipeline_end") return "✅";
    if (pet === "node_start") return "▶";
    if (pet === "node_end") return "■";
    if (pet === "node_failed") return "✗";
    if (pet === "paused") return "⏸";
    if (pet === "resumed") return "▶";
  }
  if (e.event_type === "agent_turn") return "🤖";
  if (e.event_type === "tool_call") return "🔧";
  if (e.event_type === "llm_call") return "💬";
  return "·";
}

function eventLabel(e: TimelineEvent): string {
  const p = e.payload;
  if (e.event_type === "pipeline_event") {
    const pet = p.pipeline_event_type as string;
    const node = p.node_name as string | undefined;
    if (pet === "pipeline_start") return `Pipeline started: ${p.pipeline_name}`;
    if (pet === "pipeline_end") return "Pipeline completed";
    if (pet === "node_start") return `Node: ${node}`;
    if (pet === "node_end") {
      const dur = p.duration_ms as number | undefined;
      return `Completed${dur ? ` (${(dur / 1000).toFixed(1)}s)` : ""}`;
    }
    if (pet === "node_failed") return `Failed: ${p.error_msg || ""}`;
    if (pet === "paused") return `Paused at: ${node}`;
    return pet;
  }
  if (e.event_type === "agent_turn") {
    const dur = p.duration_ms as number | undefined;
    return `Agent: ${p.agent_role}${dur ? ` (${(dur / 1000).toFixed(1)}s)` : ""}`;
  }
  if (e.event_type === "tool_call") {
    const dur = p.duration_ms as number | undefined;
    const ok = p.success as boolean | undefined;
    return `${p.tool_name}${dur ? ` ${(Number(dur) / 1000).toFixed(2)}s` : ""}${ok === false ? " FAILED" : ""}`;
  }
  if (e.event_type === "llm_call") {
    const dur = p.latency_ms as number | undefined;
    const inp = p.input_tokens as number | undefined;
    const out = p.output_tokens as number | undefined;
    return `LLM${dur ? ` ${(Number(dur) / 1000).toFixed(1)}s` : ""}${inp ? ` (${inp}→${out})` : ""}`;
  }
  return e.event_type;
}

function eventColor(e: TimelineEvent): string {
  if (e.event_type === "pipeline_event") {
    const pet = e.payload.pipeline_event_type as string;
    if (pet === "node_failed" || pet === "pipeline_failed")
      return "border-red-400 bg-red-50";
    if (pet === "pipeline_end") return "border-green-400 bg-green-50";
    if (pet === "paused") return "border-yellow-400 bg-yellow-50";
  }
  if (e.event_type === "tool_call" && e.payload.success === false)
    return "border-red-300 bg-red-50";
  if (e.event_type === "tool_call") return "border-amber-200 bg-amber-50";
  if (e.event_type === "llm_call") return "border-indigo-200 bg-indigo-50";
  return "border-slate-300 bg-white";
}

function PipelineTimeline({ events }: { events: TimelineEvent[] }) {
  const tree = buildTimelineTree(events);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  if (tree.length === 0)
    return <p className="text-sm text-slate-400">No pipeline events.</p>;

  const toggle = (id: number) =>
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="relative pl-6">
      <div className="absolute left-2 top-0 bottom-0 w-0.5 bg-slate-200" />
      {tree.map((node) => {
        const e = node.event;
        const hasChildren = node.children.length > 0;
        const expanded = expandedIds.has(e.id);
        const toolCount = node.children.filter(
          (c) => c.event_type === "tool_call"
        ).length;
        const llmCount = node.children.filter(
          (c) => c.event_type === "llm_call"
        ).length;

        return (
          <div key={e.id} className="relative mb-3">
            <div className="absolute -left-4 top-1 w-3 h-3 rounded-full bg-slate-300 border-2 border-white" />
            <div
              className={`rounded border px-3 py-2 text-sm ${eventColor(e)} ${hasChildren ? "cursor-pointer" : ""}`}
              onClick={hasChildren ? () => toggle(e.id) : undefined}
            >
              <div className="flex items-center gap-2">
                <span>{eventIcon(e)}</span>
                <span className="font-medium">{eventLabel(e)}</span>
                {hasChildren && (
                  <span className="ml-auto flex items-center gap-1 text-xs text-slate-400">
                    {toolCount > 0 && (
                      <span className="rounded bg-amber-100 px-1 py-0.5 text-amber-700">
                        🔧{toolCount}
                      </span>
                    )}
                    {llmCount > 0 && (
                      <span className="rounded bg-indigo-100 px-1 py-0.5 text-indigo-700">
                        💬{llmCount}
                      </span>
                    )}
                    <span>{expanded ? "▲" : "▼"}</span>
                  </span>
                )}
              </div>
              <div className="text-xs text-slate-400 mt-0.5">
                {new Date(e.ts).toLocaleTimeString()}
              </div>
            </div>
            {expanded && node.children.length > 0 && (
              <div className="ml-4 mt-1 space-y-1 relative pl-4">
                <div className="absolute left-1 top-0 bottom-0 w-0.5 bg-slate-100" />
                {node.children.map((child) => (
                  <div
                    key={child.id}
                    className={`rounded border px-2.5 py-1.5 text-xs ${eventColor(child)}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <span className="text-[11px]">{eventIcon(child)}</span>
                      <span>{eventLabel(child)}</span>
                    </div>
                    {child.event_type === "tool_call" &&
                      typeof child.payload.args_preview === "string" && (
                        <div className="mt-0.5 text-[10px] text-slate-400 font-mono truncate max-w-md">
                          {child.payload.args_preview}
                        </div>
                      )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Agent Gantt ───────────────────────────────────────────

interface GanttSubItem {
  type: "tool" | "llm";
  name: string;
  durationMs: number;
  ok?: boolean;
  tokens?: string;
}

interface GanttBar {
  name: string;
  startMs: number;
  durationMs: number;
  status: string;
  items: GanttSubItem[];
}

function AgentGantt({
  events,
  agentRuns,
}: {
  events: TimelineEvent[];
  agentRuns: AgentRunItem[];
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  let minTs = Infinity;
  for (const e of events) {
    const ts = new Date(e.ts).getTime();
    if (ts < minTs) minTs = ts;
  }

  const nodeStarts: Record<string, number> = {};
  const nodeEnds: Record<string, { ts: number; status: string }> = {};
  for (const e of events) {
    if (e.event_type !== "pipeline_event") continue;
    const pet = e.payload.pipeline_event_type as string;
    const node = e.payload.node_name as string;
    const ts = new Date(e.ts).getTime();
    if (pet === "node_start") nodeStarts[node] = ts;
    else if (pet === "node_end" || pet === "node_failed")
      nodeEnds[node] = { ts, status: pet === "node_end" ? "completed" : "failed" };
  }

  const toolAndLlm = events.filter(
    (e) => e.event_type === "tool_call" || e.event_type === "llm_call"
  );
  const nodeNames = Object.keys(nodeStarts).filter((n) => n in nodeEnds);

  const bars: GanttBar[] = nodeNames.map((node) => {
    const start = nodeStarts[node];
    const end = nodeEnds[node];
    const items: GanttSubItem[] = [];

    for (const e of toolAndLlm) {
      const ts = new Date(e.ts).getTime();
      if (ts >= start && ts <= end.ts) {
        if (e.event_type === "tool_call") {
          items.push({
            type: "tool",
            name: e.payload.tool_name as string,
            durationMs: Number(e.payload.duration_ms || 0),
            ok: e.payload.success !== false,
          });
        } else {
          const inp = e.payload.input_tokens as number | undefined;
          const out = e.payload.output_tokens as number | undefined;
          items.push({
            type: "llm",
            name: "LLM Call",
            durationMs: Number(e.payload.latency_ms || 0),
            tokens: inp ? `${inp}→${out}` : undefined,
          });
        }
      }
    }

    return {
      name: node,
      startMs: start - minTs,
      durationMs: end.ts - start,
      status: end.status,
      items,
    };
  });

  if (bars.length === 0 && agentRuns.length > 0) {
    let earliest = Infinity;
    for (const ar of agentRuns) {
      if (ar.created_at) {
        const t = new Date(ar.created_at).getTime();
        if (t < earliest) earliest = t;
      }
    }
    for (const ar of agentRuns) {
      if (ar.created_at) {
        const s = new Date(ar.created_at).getTime();
        const e = ar.updated_at ? new Date(ar.updated_at).getTime() : s + 1000;
        bars.push({
          name: ar.description?.slice(0, 30) || ar.role,
          startMs: s - earliest,
          durationMs: Math.max(e - s, 500),
          status: ar.status,
          items: [],
        });
      }
    }
  }

  if (bars.length === 0)
    return <p className="text-sm text-slate-400">No timing data available.</p>;

  const maxEnd = Math.max(...bars.map((b) => b.startMs + b.durationMs));
  const scale = maxEnd > 0 ? 100 / maxEnd : 1;

  const toggle = (name: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  return (
    <div className="space-y-0.5">
      {bars.map((b) => {
        const isOpen = expanded.has(b.name);
        const toolCount = b.items.filter((i) => i.type === "tool").length;
        const llmCount = b.items.filter((i) => i.type === "llm").length;
        const hasItems = b.items.length > 0;

        return (
          <div key={b.name}>
            {/* Node row */}
            <div
              className={`flex items-center gap-2 py-1 ${hasItems ? "cursor-pointer" : ""}`}
              onClick={hasItems ? () => toggle(b.name) : undefined}
            >
              <span className="w-28 text-xs font-mono text-slate-600 truncate text-right flex items-center justify-end gap-1">
                {hasItems && (
                  <span className="text-[10px] text-slate-400">
                    {isOpen ? "▼" : "▶"}
                  </span>
                )}
                {b.name}
              </span>
              <div className="flex-1 h-6 bg-slate-100 rounded relative overflow-hidden">
                <div
                  className={`absolute top-0 h-full rounded ${
                    b.status === "failed"
                      ? "bg-red-400"
                      : b.status === "completed"
                        ? "bg-blue-400"
                        : "bg-yellow-400"
                  }`}
                  style={{
                    left: `${b.startMs * scale}%`,
                    width: `${Math.max(b.durationMs * scale, 1)}%`,
                  }}
                />
                <span className="absolute right-1.5 top-0.5 text-[10px] text-slate-600 font-medium z-10">
                  {(b.durationMs / 1000).toFixed(1)}s
                  {toolCount > 0 && (
                    <span className="ml-1 text-amber-600">
                      {toolCount} tool{toolCount > 1 ? "s" : ""}
                    </span>
                  )}
                  {llmCount > 0 && (
                    <span className="ml-1 text-indigo-600">
                      {llmCount} llm
                    </span>
                  )}
                </span>
              </div>
            </div>

            {/* Expanded detail rows */}
            {isOpen && (
              <div className="ml-[7.5rem] space-y-0.5 mb-2">
                {b.items.map((item, j) => {
                  const barWidth =
                    b.durationMs > 0
                      ? Math.max((item.durationMs / b.durationMs) * 100, 2)
                      : 2;
                  return (
                    <div key={j} className="flex items-center gap-2">
                      <span className="w-28 text-[10px] font-mono text-slate-500 truncate text-right">
                        {item.type === "tool" ? (
                          <span className="text-amber-600">{item.name}</span>
                        ) : (
                          <span className="text-indigo-600">{item.name}</span>
                        )}
                      </span>
                      <div className="flex-1 h-4 bg-slate-50 rounded relative overflow-hidden">
                        <div
                          className={`absolute top-0 h-full rounded ${
                            item.type === "tool"
                              ? item.ok === false
                                ? "bg-red-300"
                                : "bg-amber-300"
                              : "bg-indigo-300"
                          }`}
                          style={{ width: `${barWidth}%` }}
                        />
                        <span className="absolute right-1 top-0 text-[9px] text-slate-500 z-10">
                          {item.durationMs > 0
                            ? `${(item.durationMs / 1000).toFixed(2)}s`
                            : "—"}
                          {item.tokens && (
                            <span className="ml-1">({item.tokens})</span>
                          )}
                          {item.ok === false && (
                            <span className="ml-1 text-red-600">FAIL</span>
                          )}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Tool Call Table ────────────────────────────────────────

function ToolCallTable({ events }: { events: TimelineEvent[] }) {
  const toolEvents = events.filter((e) => e.event_type === "tool_call");
  if (toolEvents.length === 0)
    return <p className="text-sm text-slate-400">No tool calls recorded.</p>;

  return (
    <div className="overflow-auto max-h-80">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 sticky top-0">
          <tr>
            <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">
              Tool
            </th>
            <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">
              Duration
            </th>
            <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">
              Status
            </th>
            <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">
              Args Preview
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {toolEvents.map((e) => {
            const p = e.payload;
            const success = p.success as boolean | undefined;
            return (
              <tr key={e.id} className="hover:bg-slate-50">
                <td className="px-3 py-2 font-mono text-xs">
                  {p.tool_name as string}
                </td>
                <td className="px-3 py-2 text-xs text-slate-600">
                  {p.duration_ms
                    ? `${(Number(p.duration_ms) / 1000).toFixed(2)}s`
                    : "—"}
                </td>
                <td className="px-3 py-2">
                  <span
                    className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      success === false
                        ? "bg-red-100 text-red-700"
                        : "bg-green-100 text-green-700"
                    }`}
                  >
                    {success === false ? "failed" : "ok"}
                  </span>
                </td>
                <td className="px-3 py-2 text-xs text-slate-500 max-w-xs truncate">
                  {(p.args_preview as string) || "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Main Component ────────────────────────────────────────

export default function RunDetailPage() {
  const { id, runId } = useParams<{ id: string; runId: string }>();
  const projectId = Number(id);
  const location = useLocation();
  const navigate = useNavigate();
  const state = (location.state ?? {}) as StreamState;

  const [sseEvents, setSseEvents] = useState<SseEvent[]>([]);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [status, setStatus] = useState<string>("—");
  const [error, setError] = useState<Error | null>(null);
  const [streaming, setStreaming] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<TabId>("result");
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const abortRef = useRef<AbortController | null>(null);
  const liveRunIdRef = useRef<string | null>(null);
  const [liveRunId, setLiveRunId] = useState<string | null>(null);

  // Telemetry data
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [agentRollups, setAgentRollups] = useState<AgentRollup[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRunItem[]>([]);

  const liveStream = state.liveStream === true && runId === "pending";

  // Live stream effect
  useEffect(() => {
    if (!liveStream || !state.pipelineName) return;
    const ac = new AbortController();
    abortRef.current = ac;
    setStreaming(true);
    setStatus("running");
    fetchEventStream(
      `/projects/${projectId}/pipelines/${state.pipelineName}/runs?stream=true`,
      {
        signal: ac.signal,
        body: { input: state.inputText ? { text: state.inputText } : {} },
        onEvent: (ev) => {
          setSseEvents((prev) => [...prev, ev]);
          // Capture the real run_id from the first "started" frame so that
          // resume/cancel/edit actions can target the real run instead of
          // the URL placeholder "pending".
          if (ev.type === "started" && liveRunIdRef.current === null) {
            try {
              const parsed = JSON.parse(ev.data) as { run_id?: string };
              if (parsed.run_id) {
                liveRunIdRef.current = parsed.run_id;
                setLiveRunId(parsed.run_id);
              }
            } catch {
              // malformed started frame — ignore, fall back to 404 on action
            }
          }
          if (ev.type === "pipeline_end") setStatus("completed");
          if (ev.type === "pipeline_failed") setStatus("failed");
          if (ev.type === "pipeline_paused") setStatus("paused");
        },
      }
    )
      .catch((err: unknown) => {
        setError(err instanceof Error ? err : new Error(String(err)));
        setStatus("failed");
      })
      .finally(() => {
        setStreaming(false);
        // SSE has drained (pipeline reached paused/end/failed or errored).
        // Replace the /runs/pending placeholder URL with the real run id so
        // refresh/back-forward lands on the historical route and never
        // re-triggers the pipeline.
        const realId = liveRunIdRef.current;
        if (realId) {
          navigate(`/projects/${projectId}/runs/${realId}`, { replace: true });
        }
      });
    return () => ac.abort();
  }, [liveStream, projectId, state.pipelineName, state.inputText, navigate]);

  // Load historical run detail
  const loadHistorical = useCallback(async () => {
    if (liveStream || !runId || runId === "pending") return;
    try {
      const d = await client.get<RunDetail>(`/runs/${runId}`);
      setDetail(d);
      setStatus(d.status);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, [liveStream, runId]);

  useEffect(() => {
    void loadHistorical();
  }, [loadHistorical]);

  // Load telemetry data (for historical runs)
  useEffect(() => {
    if (liveStream || !runId || runId === "pending") return;
    const load = async () => {
      try {
        const [s, t, a, ar] = await Promise.all([
          client
            .get<RunSummary>(`/telemetry/runs/${runId}/summary`)
            .catch(() => null),
          client
            .get<TimelineEvent[]>(`/telemetry/runs/${runId}/timeline`)
            .catch(() => []),
          client
            .get<AgentRollup[]>(`/telemetry/runs/${runId}/agents`)
            .catch(() => []),
          client
            .get<{ items: AgentRunItem[] }>(`/runs/${runId}/agents`)
            .catch(() => ({ items: [] })),
        ]);
        setSummary(s);
        setTimeline(t);
        setAgentRollups(a);
        setAgentRuns(ar.items);
      } catch {
        // telemetry may not exist for older runs
      }
    };
    void load();
  }, [liveStream, runId]);

  const toggleNode = useCallback((name: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }, []);

  const outputs = detail?.outputs ?? {};
  const finalOutput = detail?.final_output ?? "";
  const outputKeys = Object.keys(outputs);
  const hasResults = outputKeys.length > 0 || finalOutput;

  // Pie chart data for token distribution by agent
  const tokenPieData = agentRollups
    .filter((a) => a.input_tokens + a.output_tokens > 0)
    .map((a) => ({
      name: a.agent_role,
      value: a.input_tokens + a.output_tokens,
    }));

  // Bar chart data for cost by agent
  const costBarData = agentRollups
    .filter((a) => a.cost_usd > 0)
    .map((a) => ({
      agent: a.agent_role,
      cost: a.cost_usd,
      input: a.input_tokens,
      output: a.output_tokens,
    }));

  const tabs: { id: TabId; label: string; badge?: number }[] = [
    { id: "result", label: "Result", badge: hasResults ? outputKeys.length : undefined },
    { id: "timeline", label: "Timeline", badge: timeline.length > 0 ? timeline.length : undefined },
    { id: "telemetry", label: "Telemetry" },
    { id: "events", label: "Event Log", badge: sseEvents.length > 0 ? sseEvents.length : undefined },
  ];

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <div className="mb-4">
        <Link
          to={`/projects/${projectId}?tab=runs`}
          className="text-sm text-slate-500 hover:underline"
        >
          &larr; Back to runs
        </Link>
      </div>

      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <h1 className="text-2xl font-semibold">Run Detail</h1>
        <span
          className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
            STATUS_COLORS[status] ?? "bg-slate-100 text-slate-600"
          }`}
        >
          {status}
        </span>
        {streaming && (
          <span className="text-xs text-blue-600 animate-pulse">
            streaming…
          </span>
        )}
      </div>

      {/* Meta */}
      <p className="text-sm text-slate-500 font-mono mb-4">
        run_id: {runId}
        {detail?.pipeline && ` · pipeline: ${detail.pipeline}`}
        {detail?.started_at && ` · started: ${detail.started_at}`}
        {detail?.finished_at && ` · finished: ${detail.finished_at}`}
      </p>

      {/* Summary stats (if telemetry available) */}
      {summary && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <StatCard label="LLM Calls" value={String(summary.llm_calls)} />
          <StatCard label="Tool Calls" value={String(summary.tool_calls)} />
          <StatCard
            label="Tokens (in/out)"
            value={`${(summary.total_input_tokens / 1000).toFixed(1)}k / ${(summary.total_output_tokens / 1000).toFixed(1)}k`}
          />
          <StatCard
            label="Cost"
            value={`$${summary.total_cost_usd.toFixed(4)}`}
          />
          <StatCard
            label="Duration"
            value={
              summary.duration_ms
                ? `${(summary.duration_ms / 1000).toFixed(1)}s`
                : "—"
            }
          />
          <StatCard
            label="Avg Latency"
            value={
              summary.llm_calls > 0
                ? `${(summary.total_llm_latency_ms / summary.llm_calls).toFixed(0)}ms`
                : "—"
            }
          />
          <StatCard label="Errors" value={String(summary.errors)} />
        </div>
      )}

      {/* Resume UI for paused runs. We wait until `detail` has been loaded
          via the historical path (post-navigate) so paused_at / paused_output
          are populated — otherwise the panel would briefly render empty. */}
      {status === "paused" && detail?.paused_at && (
        <ResumePanel
          runId={liveRunId ?? runId!}
          pausedAt={detail.paused_at}
          pausedOutput={detail.paused_output ?? ""}
          onResumed={loadHistorical}
        />
      )}

      {/* Error displays */}
      {detail?.error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <span className="font-medium">Error: </span>
          <span className="font-mono text-xs">{detail.error}</span>
        </div>
      )}
      {error && (
        <div className="mb-4 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <div className="font-medium">
            {error instanceof ApiError ? `Error ${error.status}` : "Error"}
          </div>
          <div className="font-mono text-xs mt-1">{error.message}</div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-200 mb-4">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px ${
              activeTab === t.id
                ? "border-slate-900 text-slate-900"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            {t.label}
            {t.badge !== undefined && (
              <span className="ml-1.5 rounded-full bg-slate-100 text-slate-600 px-1.5 py-0.5 text-xs">
                {t.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Result Tab ── */}
      {activeTab === "result" && (
        <section>
          {!hasResults && (
            <p className="text-slate-500 text-sm">
              {status === "completed"
                ? "No outputs recorded for this run."
                : "Results will appear here once the run completes."}
            </p>
          )}
          {hasResults && (
            <div className="space-y-4">
              {runId && runId !== "pending" && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => downloadExport(runId, "md")}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    Export .md
                  </button>
                  <button
                    type="button"
                    onClick={() => downloadExport(runId, "json")}
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    Export .json
                  </button>
                </div>
              )}
              {finalOutput && (
                <div className="rounded border border-green-200 bg-green-50 p-4">
                  <h3 className="text-sm font-medium text-green-800 mb-2">
                    Final Output
                  </h3>
                  <div className="whitespace-pre-wrap text-sm text-slate-900 max-h-96 overflow-auto">
                    {finalOutput}
                  </div>
                </div>
              )}
              {outputKeys.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-slate-700 mb-2">
                    Node Outputs
                  </h3>
                  <div className="space-y-2">
                    {outputKeys.map((name) => {
                      const expanded = expandedNodes.has(name);
                      const content = outputs[name];
                      const preview = content.slice(0, 200);
                      return (
                        <div
                          key={name}
                          className="rounded border border-slate-200 bg-white"
                        >
                          <button
                            type="button"
                            onClick={() => toggleNode(name)}
                            className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-slate-50"
                          >
                            <span className="font-mono text-sm font-medium">
                              {name}
                            </span>
                            <span className="text-xs text-slate-400">
                              {content.length} chars{" "}
                              {expanded ? "▲" : "▼"}
                            </span>
                          </button>
                          {!expanded && preview && (
                            <div className="px-3 pb-2 text-xs text-slate-500 truncate">
                              {preview}
                              {content.length > 200 && "…"}
                            </div>
                          )}
                          {expanded && (
                            <div className="border-t border-slate-100 px-3 py-3 max-h-96 overflow-auto">
                              <pre className="whitespace-pre-wrap text-sm text-slate-900">
                                {content}
                              </pre>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {/* ── Timeline Tab ── */}
      {activeTab === "timeline" && (
        <section className="space-y-8">
          {/* Pipeline event timeline */}
          <div>
            <h2 className="text-lg font-medium mb-3">Pipeline Lifecycle</h2>
            {timeline.length > 0 ? (
              <PipelineTimeline events={timeline} />
            ) : (
              <p className="text-sm text-slate-400">
                No telemetry events. Run a pipeline to see the lifecycle.
              </p>
            )}
          </div>

          {/* Agent Gantt chart */}
          <div>
            <h2 className="text-lg font-medium mb-3">
              Agent Execution Timeline
            </h2>
            <div className="rounded border border-slate-200 bg-white p-4">
              <AgentGantt events={timeline} agentRuns={agentRuns} />
            </div>
          </div>

          {/* Agent Runs table */}
          {agentRuns.length > 0 && (
            <div>
              <h2 className="text-lg font-medium mb-3">Agent Runs</h2>
              <div className="overflow-auto rounded border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">
                        Role
                      </th>
                      <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">
                        Description
                      </th>
                      <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">
                        Status
                      </th>
                      <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">
                        Created
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {agentRuns.map((ar) => (
                      <tr key={ar.id} className="hover:bg-slate-50">
                        <td className="px-3 py-2 font-mono text-xs">
                          {ar.role}
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-600 max-w-xs truncate">
                          {ar.description || "—"}
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-medium ${
                              STATUS_COLORS[ar.status] ??
                              "bg-slate-100 text-slate-600"
                            }`}
                          >
                            {ar.status}
                          </span>
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-500">
                          {ar.created_at
                            ? new Date(ar.created_at).toLocaleTimeString()
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}

      {/* ── Telemetry Tab ── */}
      {activeTab === "telemetry" && (
        <section className="space-y-8">
          {!summary && agentRollups.length === 0 && (
            <p className="text-sm text-slate-400">
              No telemetry data available for this run.
            </p>
          )}

          {/* Token distribution pie */}
          {tokenPieData.length > 0 && (
            <div>
              <h2 className="text-lg font-medium mb-3">
                Token Distribution by Agent
              </h2>
              <div className="rounded border border-slate-200 bg-white p-4">
                <ResponsiveContainer width="100%" height={280}>
                  <PieChart>
                    <Pie
                      data={tokenPieData}
                      cx="50%"
                      cy="50%"
                      outerRadius={100}
                      dataKey="value"
                      label={({ name, percent }: any) =>
                        `${name ?? ""} (${((percent ?? 0) * 100).toFixed(0)}%)`
                      }
                    >
                      {tokenPieData.map((_, i) => (
                        <Cell
                          key={i}
                          fill={PIE_COLORS[i % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                    <Tooltip
                      formatter={(v) => Number(v).toLocaleString()}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Cost by agent bar chart */}
          {costBarData.length > 0 && (
            <div>
              <h2 className="text-lg font-medium mb-3">Cost by Agent</h2>
              <div className="rounded border border-slate-200 bg-white p-4">
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={costBarData}>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="#e2e8f0"
                    />
                    <XAxis dataKey="agent" tick={{ fontSize: 11 }} />
                    <YAxis tick={{ fontSize: 11 }} />
                    <Tooltip />
                    <Legend />
                    <Bar
                      dataKey="cost"
                      fill="#3b82f6"
                      name="Cost (USD)"
                      radius={[2, 2, 0, 0]}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* Agent rollup table */}
          {agentRollups.length > 0 && (
            <div>
              <h2 className="text-lg font-medium mb-3">Agent Summary</h2>
              <div className="overflow-auto rounded border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50">
                    <tr>
                      <th className="text-left px-3 py-2 text-xs font-medium text-slate-500">
                        Agent
                      </th>
                      <th className="text-right px-3 py-2 text-xs font-medium text-slate-500">
                        Turns
                      </th>
                      <th className="text-right px-3 py-2 text-xs font-medium text-slate-500">
                        LLM
                      </th>
                      <th className="text-right px-3 py-2 text-xs font-medium text-slate-500">
                        Tools
                      </th>
                      <th className="text-right px-3 py-2 text-xs font-medium text-slate-500">
                        Input Tokens
                      </th>
                      <th className="text-right px-3 py-2 text-xs font-medium text-slate-500">
                        Output Tokens
                      </th>
                      <th className="text-right px-3 py-2 text-xs font-medium text-slate-500">
                        Cost
                      </th>
                      <th className="text-right px-3 py-2 text-xs font-medium text-slate-500">
                        Errors
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {agentRollups.map((a) => (
                      <tr key={a.agent_role} className="hover:bg-slate-50">
                        <td className="px-3 py-2 font-mono text-xs">
                          {a.agent_role}
                        </td>
                        <td className="px-3 py-2 text-xs text-right">
                          {a.turn_count}
                        </td>
                        <td className="px-3 py-2 text-xs text-right">
                          {a.llm_calls}
                        </td>
                        <td className="px-3 py-2 text-xs text-right">
                          {a.tool_calls}
                        </td>
                        <td className="px-3 py-2 text-xs text-right">
                          {a.input_tokens.toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-xs text-right">
                          {a.output_tokens.toLocaleString()}
                        </td>
                        <td className="px-3 py-2 text-xs text-right">
                          ${a.cost_usd.toFixed(4)}
                        </td>
                        <td className="px-3 py-2 text-xs text-right">
                          {a.errors > 0 ? (
                            <span className="text-red-600">{a.errors}</span>
                          ) : (
                            "0"
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Tool call table */}
          {timeline.length > 0 && (
            <div>
              <h2 className="text-lg font-medium mb-3">Tool Calls</h2>
              <div className="rounded border border-slate-200 bg-white p-4">
                <ToolCallTable events={timeline} />
              </div>
            </div>
          )}
        </section>
      )}

      {/* ── Event Log Tab ── */}
      {activeTab === "events" && (
        <section>
          {sseEvents.length === 0 && !liveStream && (
            <p className="text-slate-500 text-sm">
              No events buffered. Trigger a run with streaming enabled from
              the Runs tab to see live events here.
            </p>
          )}
          {sseEvents.length > 0 && (
            <ol className="rounded border border-slate-200 bg-white divide-y divide-slate-200 max-h-96 overflow-auto">
              {sseEvents.map((ev, i) => (
                <li key={i} className="px-3 py-2 text-xs font-mono">
                  <span className="inline-block min-w-[8rem] text-slate-600">
                    {ev.type}
                  </span>
                  <span className="text-slate-900 break-all">{ev.data}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      )}
    </div>
  );
}

function ResumePanel({
  runId,
  pausedAt,
  pausedOutput,
  onResumed,
}: {
  runId: string;
  pausedAt: string | null;
  pausedOutput: string;
  onResumed: () => void;
}) {
  const [feedback, setFeedback] = useState("");
  const [editedText, setEditedText] = useState("");
  const [resuming, setResuming] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);
  const [mode, setMode] = useState<"review" | "edit">("review");

  const outputContent = pausedOutput || null;

  const handleAction = async (action: "approve" | "reject" | "edit") => {
    setResuming(true);
    setErr(null);
    try {
      const value: Record<string, string> = { action };
      if (action === "reject") {
        value.feedback = feedback.trim();
      } else if (action === "edit") {
        value.edited = editedText;
      }
      await client.post(`/runs/${runId}/resume`, { value });
      onResumed();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setResuming(false);
    }
  };

  return (
    <div className="mb-4 rounded-lg border-2 border-yellow-300 bg-yellow-50 p-4">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">⏸</span>
        <h3 className="text-sm font-semibold text-yellow-900">
          Pipeline paused at{" "}
          {pausedAt ? (
            <code className="bg-yellow-200 px-1.5 py-0.5 rounded text-yellow-900">{pausedAt}</code>
          ) : (
            "unknown node"
          )}
          {" "}&mdash; waiting for review
        </h3>
      </div>

      {/* Mode tabs */}
      <div className="flex gap-1 mb-3">
        <button
          type="button"
          onClick={() => setMode("review")}
          className={`px-3 py-1 text-xs rounded ${mode === "review" ? "bg-yellow-200 text-yellow-900 font-medium" : "text-yellow-700 hover:bg-yellow-100"}`}
        >
          Review
        </button>
        <button
          type="button"
          onClick={() => {
            setMode("edit");
            if (!editedText && outputContent) setEditedText(outputContent);
          }}
          className={`px-3 py-1 text-xs rounded ${mode === "edit" ? "bg-yellow-200 text-yellow-900 font-medium" : "text-yellow-700 hover:bg-yellow-100"}`}
        >
          Edit output
        </button>
      </div>

      {mode === "review" && (
        <>
          {outputContent && (
            <div className="mb-3 rounded border border-yellow-300 bg-white overflow-hidden">
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-yellow-900 hover:bg-yellow-50"
              >
                <span>Output from <code>{pausedAt}</code></span>
                <span>{expanded ? "▾" : "▸"}</span>
              </button>
              {expanded && (
                <div className="px-3 pb-3 text-sm font-mono text-slate-800 whitespace-pre-wrap max-h-64 overflow-auto border-t border-yellow-200">
                  {outputContent}
                </div>
              )}
            </div>
          )}

          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={3}
            placeholder="Feedback for rejection (e.g. 'rewrite the intro, too formal')..."
            className="w-full rounded border border-yellow-300 bg-white p-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-yellow-400 mb-3"
          />

          {err && (
            <div className="mb-2 text-xs text-red-700 font-mono">{err}</div>
          )}

          <div className="flex gap-2">
            <button
              type="button"
              disabled={resuming}
              onClick={() => handleAction("approve")}
              className="rounded bg-green-600 px-4 py-1.5 text-sm text-white hover:bg-green-700 disabled:opacity-50"
            >
              {resuming ? "..." : "Approve & Continue"}
            </button>
            <button
              type="button"
              disabled={resuming || !feedback.trim()}
              onClick={() => handleAction("reject")}
              className="rounded bg-red-600 px-4 py-1.5 text-sm text-white hover:bg-red-700 disabled:opacity-50"
            >
              {resuming ? "..." : "Reject & Redo"}
            </button>
          </div>
          {!feedback.trim() && (
            <p className="mt-1.5 text-[11px] text-yellow-700">
              Write feedback above to enable "Reject & Redo"
            </p>
          )}
        </>
      )}

      {mode === "edit" && (
        <>
          <p className="text-xs text-yellow-800 mb-2">
            Edit the output directly, then save to continue the pipeline with your version.
          </p>
          <textarea
            value={editedText}
            onChange={(e) => setEditedText(e.target.value)}
            rows={10}
            className="w-full rounded border border-yellow-300 bg-white p-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-yellow-400 mb-3"
          />

          {err && (
            <div className="mb-2 text-xs text-red-700 font-mono">{err}</div>
          )}

          <button
            type="button"
            disabled={resuming || !editedText.trim()}
            onClick={() => handleAction("edit")}
            className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {resuming ? "..." : "Save Edit & Continue"}
          </button>
        </>
      )}
    </div>
  );
}
