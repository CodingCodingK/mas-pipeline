import { useCallback, useEffect, useState } from "react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
} from "recharts";
import { client } from "@/api/client";

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

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-200 bg-white px-3 py-2">
      <div className="text-[10px] text-slate-500">{label}</div>
      <div className="text-sm font-semibold mt-0.5">{value}</div>
    </div>
  );
}


interface TreeTurnNode {
  turn_id: string;
  agent_role: string | null;
  turn_index: number | null;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  stop_reason: string | null;
  input_preview: string | null;
  output_preview: string | null;
  children: TimelineEvent[];
  child_turns: TreeTurnNode[];
}

interface SessionTree {
  roots: TreeTurnNode[];
  orphans: TreeTurnNode[];
  spawns: Array<{
    spawn_id: string;
    parent_role: string;
    child_role: string;
    task_preview: string;
  }>;
}

function buildFlatFallback(events: TimelineEvent[]): TreeTurnNode[] {
  const nodes: TreeTurnNode[] = [];
  let current: TreeTurnNode | null = null;

  for (const e of events) {
    if (e.event_type === "agent_turn") {
      const p = e.payload;
      current = {
        turn_id: (p.turn_id as string) || `evt-${e.id}`,
        agent_role: (p.agent_role as string) || e.agent_role,
        turn_index: (p.turn_index as number) ?? null,
        started_at: (p.started_at as string) ?? e.ts,
        ended_at: (p.ended_at as string) ?? null,
        duration_ms: (p.duration_ms as number) ?? null,
        stop_reason: (p.stop_reason as string) ?? null,
        input_preview: (p.input_preview as string) ?? null,
        output_preview: (p.output_preview as string) ?? null,
        children: [],
        child_turns: [],
      };
      nodes.push(current);
    } else if (
      e.event_type === "llm_call" ||
      e.event_type === "tool_call" ||
      e.event_type === "error"
    ) {
      if (current) current.children.push(e);
      else {
        const fallback: TreeTurnNode = {
          turn_id: `evt-${e.id}`,
          agent_role: e.agent_role,
          turn_index: null,
          started_at: e.ts,
          ended_at: null,
          duration_ms: null,
          stop_reason: null,
          input_preview: null,
          output_preview: null,
          children: [e],
          child_turns: [],
        };
        nodes.push(fallback);
      }
    }
  }
  return nodes;
}

const ROLE_DOT_COLORS: Record<string, string> = {
  coordinator: "bg-blue-500",
  researcher: "bg-emerald-500",
  writer: "bg-purple-500",
  reviewer: "bg-amber-500",
  coder: "bg-cyan-500",
};

function roleDot(role: string | null): string {
  if (!role) return "bg-slate-400";
  return ROLE_DOT_COLORS[role] || "bg-slate-400";
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

interface Round {
  llm: TimelineEvent | null;
  tools: TimelineEvent[];
}

function groupIntoRounds(children: TimelineEvent[]): Round[] {
  const rounds: Round[] = [];
  let current: Round = { llm: null, tools: [] };

  for (const c of children) {
    if (c.event_type === "llm_call") {
      if (current.llm || current.tools.length > 0) {
        rounds.push(current);
      }
      current = { llm: c, tools: [] };
    } else if (c.event_type === "tool_call") {
      current.tools.push(c);
    }
  }
  if (current.llm || current.tools.length > 0) {
    rounds.push(current);
  }
  return rounds;
}

function formatTime(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function extractArgHint(argsPreview: string): string {
  if (!argsPreview) return "";
  try {
    const obj = JSON.parse(argsPreview);
    const val = obj.query || obj.url || obj.role || obj.task_description || obj.path || obj.command;
    if (typeof val === "string" && val.trim().length > 1) return val.slice(0, 60);
  } catch {
    const m = argsPreview.match(/"(?:query|url|role|task_description|path|command)":\s*"([^"]{2,60})/);
    if (m) return m[1];
  }
  return "";
}

function LlmDivider({ event }: { event: TimelineEvent }) {
  const p = event.payload;
  const lat = formatDuration((p.latency_ms as number) || null);
  const inTok = p.input_tokens as number;
  const outTok = p.output_tokens as number;
  const finish = p.finish_reason as string | undefined;
  const isToolCall = finish === "tool_calls";
  return (
    <div className="flex items-center gap-1.5 py-1 text-[11px]">
      <div className="flex-1 border-t border-dashed border-indigo-200" />
      <span className="flex-shrink-0 text-indigo-500 font-medium">LLM</span>
      <span className="flex-shrink-0 text-slate-500 font-medium">{lat}</span>
      <span className="flex-shrink-0 text-[10px] text-slate-400">
        {inTok}→{outTok}
      </span>
      {isToolCall && (
        <span className="flex-shrink-0 text-[10px] text-amber-500">→🔧</span>
      )}
      <div className="flex-1 border-t border-dashed border-indigo-200" />
    </div>
  );
}

function ToolBatch({ tools }: { tools: TimelineEvent[] }) {
  const n = tools.length;
  if (n === 0) return null;

  return (
    <div className="font-mono text-[11px] leading-relaxed">
      {tools.map((tc, i) => {
        const name = (tc.payload.tool_name as string) || "tool";
        const preview = (tc.payload.args_preview as string) || "";
        const argHint = extractArgHint(preview);
        const dur = formatDuration((tc.payload.duration_ms as number) || null);
        const failed = tc.payload.success === false;

        const bracket = n === 1
          ? " "
          : i === 0
            ? "┌"
            : i === n - 1
              ? "└"
              : "│";
        const bracketColor = n > 1 ? "text-amber-400" : "text-transparent";

        return (
          <div key={tc.id} className="flex items-baseline hover:bg-slate-50 rounded px-1 -mx-1 min-w-0 overflow-hidden">
            <span className={`flex-shrink-0 w-3 text-center ${bracketColor}`}>
              {bracket}
            </span>
            <span className="flex-shrink-0 text-slate-700 font-medium mr-1">
              {name}
            </span>
            <span className="text-slate-400 truncate flex-1 min-w-0" title={preview}>
              {argHint ? `"${argHint}"` : ""}
            </span>
            <span className="flex-shrink-0 ml-1 text-[10px] text-slate-400 tabular-nums">
              {dur}
            </span>
            {failed && (
              <span className="flex-shrink-0 ml-0.5 text-red-500 text-[10px]">✗</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

function StepTimeline({
  nodes,
  expandedIds,
  toggle,
  depth,
}: {
  nodes: TreeTurnNode[];
  expandedIds: Set<string>;
  toggle: (id: string) => void;
  depth: number;
}) {
  if (nodes.length === 0) return null;

  return (
    <div className={depth > 0 ? "ml-4 border-l-2 border-slate-100 pl-3" : ""}>
      {nodes.map((node, idx) => {
        const expanded = expandedIds.has(node.turn_id);
        const isOk = !node.stop_reason || node.stop_reason === "done" || node.stop_reason === "completed";
        const toolCount = node.children.filter((c) => c.event_type === "tool_call").length;
        const llmCount = node.children.filter((c) => c.event_type === "llm_call").length;
        const hasChildren = node.children.length > 0;
        const isLast = idx === nodes.length - 1;
        const rounds = expanded ? groupIntoRounds(node.children) : [];

        return (
          <div key={node.turn_id} className={isLast ? "" : "mb-1"}>
            {/* Node row */}
            <div
              className={`flex items-start gap-2 py-1.5 rounded px-1.5 -mx-1.5 ${hasChildren ? "cursor-pointer hover:bg-slate-50" : ""}`}
              onClick={hasChildren ? () => toggle(node.turn_id) : undefined}
            >
              <div className="flex-shrink-0 mt-0.5">
                <div className={`w-2.5 h-2.5 rounded-full ${roleDot(node.agent_role)} ${isOk ? "" : "ring-2 ring-red-300"}`} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-medium text-slate-800 truncate">
                    {node.agent_role || "agent"}
                    {node.turn_index != null ? ` #${node.turn_index}` : ""}
                  </span>
                  {isOk ? (
                    <span className="text-[10px] text-green-500">✓</span>
                  ) : (
                    <span className="text-[10px] text-red-500">{node.stop_reason}</span>
                  )}
                </div>
                <div className="flex items-center gap-2 text-[10px] text-slate-400 mt-0.5">
                  <span>{formatTime(node.started_at)}</span>
                  {node.duration_ms != null && (
                    <span className="text-slate-500 font-medium">{formatDuration(node.duration_ms)}</span>
                  )}
                  {llmCount > 0 && <span>💬{llmCount}</span>}
                  {toolCount > 0 && <span>🔧{toolCount}</span>}
                  {hasChildren && (
                    <span className="ml-auto text-slate-300">{expanded ? "▲" : "▼"}</span>
                  )}
                </div>
              </div>
            </div>

            {/* Expanded: LLM dividers + parallel tool batches */}
            {expanded && rounds.length > 0 && (
              <div className="ml-5 mt-0.5 mb-2">
                {rounds.map((round, ri) => (
                  <div key={ri}>
                    {round.llm && <LlmDivider event={round.llm} />}
                    <ToolBatch tools={round.tools} />
                  </div>
                ))}
              </div>
            )}

            {/* Child turns (spawned sub-agents) */}
            {node.child_turns.length > 0 && (
              <StepTimeline
                nodes={node.child_turns}
                expandedIds={expandedIds}
                toggle={toggle}
                depth={depth + 1}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

type TabId = "overview" | "timeline" | "agents";

export default function SessionTelemetry({
  sessionId,
  refreshSignal = 0,
}: {
  sessionId: number;
  refreshSignal?: number;
}) {
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [tree, setTree] = useState<SessionTree | null>(null);
  const [agents, setAgents] = useState<AgentRollup[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("overview");
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, t, tr, a] = await Promise.all([
        client
          .get<RunSummary>(`/telemetry/sessions/${sessionId}/summary`)
          .catch(() => null),
        client
          .get<TimelineEvent[]>(`/telemetry/sessions/${sessionId}/timeline`)
          .catch(() => []),
        client
          .get<SessionTree>(`/telemetry/sessions/${sessionId}/tree`)
          .catch(() => null),
        client
          .get<AgentRollup[]>(`/telemetry/sessions/${sessionId}/agents`)
          .catch(() => []),
      ]);
      setSummary(s);
      setTimeline(t);
      setTree(tr);
      setAgents(a);
    } catch {
      setError("Failed to load telemetry");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load, refreshSignal]);

  const toggle = (id: string) =>
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  if (loading) return <p className="text-xs text-slate-400 p-2">Loading telemetry…</p>;
  if (error) return <p className="text-xs text-red-600 p-2">{error}</p>;
  if (!summary && timeline.length === 0)
    return <p className="text-xs text-slate-400 p-2">No telemetry data yet.</p>;

  const tokenPieData = agents
    .filter((a) => a.input_tokens + a.output_tokens > 0)
    .map((a) => ({
      name: a.agent_role,
      value: a.input_tokens + a.output_tokens,
    }));

  const costBarData = agents
    .filter((a) => a.cost_usd > 0)
    .map((a) => ({
      agent: a.agent_role,
      cost: a.cost_usd,
    }));

  const tabs: { id: TabId; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "timeline", label: "Timeline" },
    { id: "agents", label: "Agents" },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1 border-b border-slate-200">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-xs font-medium border-b-2 -mb-px ${
              tab === t.id
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-slate-500 hover:text-slate-700"
            }`}
          >
            {t.label}
          </button>
        ))}
        <button
          type="button"
          onClick={load}
          className="ml-auto text-[10px] text-slate-400 hover:text-slate-600 px-2"
          title="Refresh"
        >
          ↻
        </button>
      </div>

      {tab === "overview" && summary && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
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
              label="LLM Latency"
              value={`${(summary.total_llm_latency_ms / 1000).toFixed(1)}s`}
            />
            <StatCard label="Errors" value={String(summary.errors)} />
            <StatCard label="Events" value={String(timeline.length)} />
          </div>

          {tokenPieData.length > 0 && (
            <div className="space-y-4">
              <div>
                <h4 className="text-xs font-medium text-slate-600 mb-1 text-center">
                  Token Distribution
                </h4>
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie
                      data={tokenPieData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="45%"
                      outerRadius={80}
                      label={({ percent }: any) =>
                        `${(percent * 100).toFixed(0)}%`
                      }
                    >
                      {tokenPieData.map((_, i) => (
                        <Cell
                          key={i}
                          fill={PIE_COLORS[i % PIE_COLORS.length]}
                        />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend
                      verticalAlign="bottom"
                      iconSize={8}
                      wrapperStyle={{ fontSize: 11 }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>
              {costBarData.length > 0 && (
                <div>
                  <h4 className="text-xs font-medium text-slate-600 mb-1">
                    Cost by Agent
                  </h4>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={costBarData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="agent" tick={{ fontSize: 10 }} />
                      <YAxis tick={{ fontSize: 10 }} />
                      <Tooltip
                        formatter={(v) =>
                          `$${Number(v).toFixed(4)}`
                        }
                      />
                      <Bar dataKey="cost" fill="#3b82f6" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {tab === "timeline" && (() => {
        const allNodes = tree ? [...tree.roots, ...tree.orphans] : [];
        const hasFlatFallback = allNodes.length === 0 && timeline.length > 0;
        const fallbackNodes: TreeTurnNode[] = hasFlatFallback
          ? buildFlatFallback(timeline)
          : [];
        const nodes = allNodes.length > 0 ? allNodes : fallbackNodes;

        return (
          <div className="max-h-[60vh] overflow-y-auto overflow-x-hidden">
            {nodes.length === 0 ? (
              <p className="text-xs text-slate-400">No events.</p>
            ) : (
              <StepTimeline
                nodes={nodes}
                expandedIds={expandedIds}
                toggle={toggle}
                depth={0}
              />
            )}
          </div>
        );
      })()}

      {tab === "agents" && (
        <div>
          {agents.length === 0 ? (
            <p className="text-xs text-slate-400">No agent data.</p>
          ) : (
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="text-left px-2 py-1.5 font-medium text-slate-500">
                      Role
                    </th>
                    <th className="text-right px-2 py-1.5 font-medium text-slate-500">
                      Turns
                    </th>
                    <th className="text-right px-2 py-1.5 font-medium text-slate-500">
                      LLM
                    </th>
                    <th className="text-right px-2 py-1.5 font-medium text-slate-500">
                      Tools
                    </th>
                    <th className="text-right px-2 py-1.5 font-medium text-slate-500">
                      In Tokens
                    </th>
                    <th className="text-right px-2 py-1.5 font-medium text-slate-500">
                      Out Tokens
                    </th>
                    <th className="text-right px-2 py-1.5 font-medium text-slate-500">
                      Cost
                    </th>
                    <th className="text-right px-2 py-1.5 font-medium text-slate-500">
                      Errors
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {agents.map((a) => (
                    <tr key={a.agent_role} className="hover:bg-slate-50">
                      <td className="px-2 py-1.5 font-mono">
                        {a.agent_role}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {a.turn_count}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {a.llm_calls}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {a.tool_calls}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {a.input_tokens.toLocaleString()}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {a.output_tokens.toLocaleString()}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        ${a.cost_usd.toFixed(4)}
                      </td>
                      <td className="px-2 py-1.5 text-right">
                        {a.errors > 0 ? (
                          <span className="text-red-600">{a.errors}</span>
                        ) : (
                          0
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
