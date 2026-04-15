import { Fragment, useCallback, useEffect, useMemo, useState, type ReactElement, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { client, ApiError } from "@/api/client";
import { useAsync } from "@/hooks/useAsync";

// ── Types (match backend telemetry query responses) ─────────

type SubTab = "conversations" | "aggregates" | "timeline";
type ConvType = "all" | "chat" | "pipeline";

interface SessionRow {
  id: number;
  session_key: string;
  channel: string | null;
  chat_id: string | null;
  project_id: number | null;
  mode: string | null;
  status: string | null;
  created_at: string | null;
  last_active_at: string | null;
}

interface TurnRow {
  ts: string | null;
  event_type: string | null;
  project_id: number | null;
  run_id: string | null;
  session_id: number | null;
  agent_role: string | null;
  stop_reason: string | null;
  subtype: string | null;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  input_preview: string | null;
  input_preview_full: string | null;
  output_preview: string | null;
  turn_id: string | null;
  parent_turn_id: string | null;
}

// Display helper: `null` is "not recorded" (show —), 0 is a valid
// measurement (show 0ms). Under 100ms use ms; above use s with one
// decimal. Minute-scale falls back to "Xm Ys" for long pipeline runs.
function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "—";
  // int((t * 1000)) truncates sub-ms durations to 0. Show "<1ms" instead
  // of "0ms" so the reader sees "measured but very small" rather than
  // "exactly zero" which looks broken.
  if (ms === 0) return "<1ms";
  if (ms < 100) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

// Pipeline-lifecycle events (subtype=pipeline_*) carry no node_name so
// their role/node cell would be blank. Surface a human label instead so
// the main column always has content.
function lifecycleLabel(subtype: string | null): string | null {
  switch (subtype) {
    case "pipeline_start":
      return "LangGraph-Start";
    case "pipeline_paused":
      return "LangGraph-Paused";
    case "pipeline_resumed":
      return "LangGraph-Resumed";
    case "pipeline_end":
      return "LangGraph-End";
    case "pipeline_failed":
      return "LangGraph-Failed";
    default:
      return null;
  }
}

interface CostBucket {
  bucket: string;
  cost_usd: number;
  missing_pricing_calls: number;
}
interface TokenBucket {
  bucket: string;
  input_tokens: number;
  output_tokens: number;
  cache_tokens: number;
}
interface StatusBucket {
  bucket: string;
  done: number;
  interrupt: number;
  error: number;
  idle_exit: number;
  pipeline_failed: number;
}
interface ErrorRateBucket {
  bucket: string;
  ratio: number;
}
interface AggregateResponse {
  window: string;
  project_id: number | null;
  cost_over_time: CostBucket[];
  tokens_over_time: TokenBucket[];
  turns_by_status: StatusBucket[];
  error_rate: ErrorRateBucket[];
}

interface SessionEvent {
  id: number;
  ts: string | null;
  event_type: string;
  agent_role: string | null;
  payload: Record<string, unknown>;
}

interface RunListItem {
  run_id: string;
  project_id: number;
  pipeline: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
}

type Window = "24h" | "7d" | "30d";

// ── Helpers ─────────────────────────────────────────────────

function EmptyState({ msg }: { msg: string }) {
  return (
    <div className="flex h-48 items-center justify-center text-sm text-slate-400">
      {msg}
    </div>
  );
}

function ChartCard({
  title,
  children,
  empty,
}: {
  title: string;
  children: ReactNode;
  empty: boolean;
}) {
  return (
    <section>
      <h3 className="text-sm font-medium text-slate-700 mb-2">{title}</h3>
      <div className="rounded border border-slate-200 bg-white p-4">
        {empty ? (
          <EmptyState msg="No data for this window" />
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            {children as ReactElement}
          </ResponsiveContainer>
        )}
      </div>
    </section>
  );
}

// ── Sub-tab: Conversations ───────────────────────────────────

interface ChatRowItem {
  kind: "chat";
  id: number;
  session_key: string;
  channel: string | null;
  mode: string | null;
  status: string;
  started: string | null;
  last_active: string | null;
  count_label: string;
}

interface PipelineRowItem {
  kind: "pipeline";
  run_id: string;
  pipeline: string | null;
  status: string;
  started: string | null;
  last_active: string | null;
}

type ConvRow = ChatRowItem | PipelineRowItem;

function ConversationsTab({ projectId }: { projectId: number }) {
  const [typeFilter, setTypeFilter] = useState<ConvType>("all");
  const [selectedChat, setSelectedChat] = useState<number | null>(null);

  const fetchMerged = useCallback(async () => {
    const [sessions, runs] = await Promise.all([
      client.get<SessionRow[]>(`/telemetry/sessions?project_id=${projectId}&limit=50`),
      client
        .get<{ items: RunListItem[] }>(`/projects/${projectId}/runs`)
        .catch(() => ({ items: [] as RunListItem[] })),
    ]);
    const chatRows: ChatRowItem[] = sessions.map((s) => ({
      kind: "chat" as const,
      id: s.id,
      session_key: s.session_key,
      channel: s.channel,
      mode: s.mode,
      status: s.status ?? "active",
      started: s.created_at,
      last_active: s.last_active_at,
      count_label: "—",
    }));
    const runRows: PipelineRowItem[] = (runs.items ?? []).map((r) => ({
      kind: "pipeline" as const,
      run_id: r.run_id,
      pipeline: r.pipeline,
      status: r.status,
      started: r.started_at,
      last_active: r.finished_at ?? r.started_at,
    }));
    const merged: ConvRow[] = [...chatRows, ...runRows];
    merged.sort((a, b) => {
      const ta = a.started ?? "";
      const tb = b.started ?? "";
      return tb.localeCompare(ta);
    });
    return merged;
  }, [projectId]);

  const { data, loading, error } = useAsync(fetchMerged, [projectId]);

  const filtered = useMemo(() => {
    if (!data) return [];
    if (typeFilter === "all") return data;
    return data.filter((r) => r.kind === typeFilter);
  }, [data, typeFilter]);

  if (loading) return <p className="text-sm text-slate-500">Loading conversations…</p>;
  if (error)
    return (
      <p className="text-sm text-rose-600 font-mono">
        Failed to load conversations: {error.message}
      </p>
    );

  return (
    <div className="space-y-4">
      {/* Type filter */}
      <div className="inline-flex rounded-md border border-slate-300 overflow-hidden text-xs">
        {(["all", "chat", "pipeline"] as ConvType[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => {
              setTypeFilter(t);
              setSelectedChat(null);
            }}
            className={
              "px-4 py-1.5 font-medium capitalize " +
              (typeFilter === t
                ? "bg-slate-900 text-white"
                : "bg-white text-slate-600 hover:bg-slate-50")
            }
          >
            {t}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <EmptyState msg="No conversations for this project yet" />
      ) : (
        <div className="rounded border border-slate-200 bg-white overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="text-left px-3 py-2">Type</th>
                <th className="text-left px-3 py-2">Name</th>
                <th className="text-left px-3 py-2">Started</th>
                <th className="text-left px-3 py-2">Last active</th>
                <th className="text-left px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {filtered.map((r) => {
                if (r.kind === "chat") {
                  const badgeLabel = r.channel ? `chat · ${r.channel}` : "chat";
                  return (
                    <tr
                      key={`chat-${r.id}`}
                      onClick={() =>
                        setSelectedChat((cur) => (cur === r.id ? null : r.id))
                      }
                      className={
                        "cursor-pointer hover:bg-slate-50 " +
                        (selectedChat === r.id ? "bg-blue-50" : "")
                      }
                    >
                      <td className="px-3 py-2">
                        <span className="rounded-full bg-blue-100 text-blue-800 px-2 py-0.5 text-[10px] font-medium">
                          {badgeLabel}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-mono truncate max-w-[320px]">
                        {r.session_key}
                      </td>
                      <td className="px-3 py-2 text-slate-500">
                        {r.started?.slice(0, 19).replace("T", " ") ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-slate-500">
                        {r.last_active?.slice(0, 19).replace("T", " ") ?? "—"}
                      </td>
                      <td className="px-3 py-2">
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono">
                          {r.mode ?? r.status}
                        </span>
                      </td>
                    </tr>
                  );
                }
                const href = `/projects/${projectId}/runs/${r.run_id}`;
                return (
                  <tr key={`run-${r.run_id}`} className="hover:bg-slate-50">
                    <td className="px-3 py-2">
                      <span className="rounded-full bg-purple-100 text-purple-800 px-2 py-0.5 text-[10px] font-medium">
                        pipeline
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono truncate max-w-[320px]">
                      <Link to={href} className="text-slate-900 hover:underline">
                        {r.pipeline ?? "—"} ·{" "}
                        <span className="text-slate-500">{r.run_id.slice(0, 8)}</span>
                      </Link>
                    </td>
                    <td className="px-3 py-2 text-slate-500">
                      {r.started?.slice(0, 19).replace("T", " ") ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-slate-500">
                      {r.last_active?.slice(0, 19).replace("T", " ") ?? "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={
                          "rounded px-1.5 py-0.5 text-[10px] font-mono " +
                          (r.status === "failed"
                            ? "bg-rose-100 text-rose-700"
                            : r.status === "paused"
                              ? "bg-amber-100 text-amber-700"
                              : r.status === "completed"
                                ? "bg-emerald-100 text-emerald-700"
                                : "bg-slate-100 text-slate-600")
                        }
                      >
                        {r.status}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {selectedChat !== null && <SessionTurnTimeline sessionId={selectedChat} />}
    </div>
  );
}

function SessionTurnTimeline({ sessionId }: { sessionId: number }) {
  const fetchTimeline = useCallback(
    () => client.get<SessionEvent[]>(`/telemetry/sessions/${sessionId}/timeline`),
    [sessionId]
  );
  const { data, loading, error } = useAsync(fetchTimeline, [sessionId]);

  if (loading) return <p className="text-sm text-slate-500">Loading turn timeline…</p>;
  if (error)
    return <p className="text-sm text-rose-600 font-mono">Failed: {error.message}</p>;
  if (!data) return null;

  const turns = data.filter((e) => e.event_type === "agent_turn");
  const shownTurns = turns.slice(0, 500);
  const truncated = turns.length > 500;

  if (shownTurns.length === 0)
    return (
      <div className="rounded border border-slate-200 bg-white p-4">
        <p className="text-sm text-slate-400">No agent turns recorded for this session.</p>
      </div>
    );

  return (
    <div className="rounded border border-slate-200 bg-white overflow-hidden">
      <div className="px-3 py-2 text-xs font-medium text-slate-600 bg-slate-50 border-b border-slate-200">
        Session #{sessionId} — {shownTurns.length} turns
        {truncated && <span className="ml-2 text-amber-600">(showing latest 500)</span>}
      </div>
      <table className="w-full text-xs">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="text-left px-3 py-2">Start</th>
            <th className="text-left px-3 py-2">Role</th>
            <th className="text-right px-3 py-2">Duration</th>
            <th className="text-right px-3 py-2">Tokens (in/out)</th>
            <th className="text-right px-3 py-2">Tool calls</th>
            <th className="text-left px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {shownTurns.map((e) => {
            const p = e.payload as Record<string, number | string | undefined>;
            return (
              <tr key={e.id}>
                <td className="px-3 py-2 font-mono text-slate-500">
                  {(p.started_at as string | undefined)?.slice(11, 19) ?? e.ts?.slice(11, 19) ?? "—"}
                </td>
                <td className="px-3 py-2">{e.agent_role ?? "—"}</td>
                <td className="px-3 py-2 text-right">
                  {formatDuration((p.duration_ms as number | null | undefined) ?? null)}
                </td>
                <td className="px-3 py-2 text-right">
                  {(p.input_tokens as number | undefined) ?? 0} /{" "}
                  {(p.output_tokens as number | undefined) ?? 0}
                </td>
                <td className="px-3 py-2 text-right">{(p.tool_call_count as number | undefined) ?? 0}</td>
                <td className="px-3 py-2">
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono">
                    {(p.stop_reason as string | undefined) ?? "done"}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Sub-tab: Aggregates ─────────────────────────────────────

function AggregatesTab({ projectId }: { projectId: number }) {
  const [win, setWin] = useState<Window>("24h");
  const fetchAggregate = useCallback(
    () =>
      client.get<AggregateResponse>(
        `/telemetry/aggregate?project_id=${projectId}&window=${win}`
      ),
    [projectId, win]
  );
  const { data, loading, error } = useAsync(fetchAggregate, [projectId, win]);

  const windows: Window[] = ["24h", "7d", "30d"];

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">Window:</span>
        {windows.map((w) => (
          <button
            key={w}
            type="button"
            onClick={() => setWin(w)}
            className={
              "rounded px-3 py-1 text-xs font-medium " +
              (w === win
                ? "bg-slate-900 text-white"
                : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-100")
            }
          >
            {w}
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-slate-500">Loading aggregates…</p>}
      {error && (
        <p className="text-sm text-rose-600 font-mono">Failed: {error.message}</p>
      )}

      {data && (() => {
        const totalMissingPricing = data.cost_over_time.reduce(
          (acc, b) => acc + (b.missing_pricing_calls || 0),
          0,
        );
        return (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <ChartCard
            title={
              totalMissingPricing > 0
                ? `Cost over time (USD) — ⚠ ${totalMissingPricing} unpriced llm_call(s)`
                : "Cost over time (USD)"
            }
            empty={data.cost_over_time.length === 0}
          >
            <LineChart data={data.cost_over_time}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} unit="$" />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="cost_usd"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={{ r: 2 }}
                name="USD"
              />
            </LineChart>
          </ChartCard>

          <ChartCard
            title="Token usage"
            empty={data.tokens_over_time.length === 0}
          >
            <AreaChart data={data.tokens_over_time}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Area
                type="monotone"
                dataKey="input_tokens"
                stackId="1"
                stroke="#6366f1"
                fill="#6366f1"
                fillOpacity={0.55}
                name="Input"
              />
              <Area
                type="monotone"
                dataKey="output_tokens"
                stackId="1"
                stroke="#22c55e"
                fill="#22c55e"
                fillOpacity={0.55}
                name="Output"
              />
              <Area
                type="monotone"
                dataKey="cache_tokens"
                stackId="1"
                stroke="#94a3b8"
                fill="#94a3b8"
                fillOpacity={0.55}
                name="Cache"
              />
            </AreaChart>
          </ChartCard>

          <ChartCard
            title="Executions by status"
            empty={data.turns_by_status.length === 0}
          >
            <BarChart data={data.turns_by_status}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="done" stackId="s" fill="#22c55e" name="done" />
              <Bar dataKey="interrupt" stackId="s" fill="#f59e0b" name="interrupt" />
              <Bar dataKey="error" stackId="s" fill="#ef4444" name="error" />
              <Bar dataKey="idle_exit" stackId="s" fill="#94a3b8" name="idle_exit" />
              <Bar dataKey="pipeline_failed" stackId="s" fill="#b91c1c" name="pipeline_failed" />
            </BarChart>
          </ChartCard>

          <ChartCard
            title="Error rate"
            empty={data.error_rate.length === 0}
          >
            <LineChart data={data.error_rate}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} domain={[0, 1]} />
              <Tooltip />
              <Line
                type="monotone"
                dataKey="ratio"
                stroke="#ef4444"
                strokeWidth={2}
                dot={{ r: 2 }}
                name="err/turn"
              />
            </LineChart>
          </ChartCard>
        </div>
        );
      })()}
    </div>
  );
}

// ── Sub-tab: Trace ──────────────────────────────────────────

type Scope = "chat" | "run";

interface TraceGroup {
  root: TurnRow;
  children: TurnRow[];
}

// Group flat events into parent→children trees.
//
// A "root" is either an agent_turn or a pipeline_event(node_start) — they
// carry a turn_id that children reference via parent_turn_id. Everything
// else (llm_call, tool_call, hook_event, compact, error, node_end,
// node_failed) is a child; if its parent isn't in the current fetch we
// promote it to a synthetic standalone root so nothing is hidden.
// Hide hook_event rows that carry no specific content. A hook with no
// rule_matched is a pass-through ping — shows up as noise in the trace.
function isEmptyHook(r: TurnRow): boolean {
  if (r.event_type !== "hook_event") return false;
  const preview = r.input_preview;
  return !preview || preview.trim() === "";
}

// pipeline_start / pipeline_paused / pipeline_resumed / pipeline_end /
// pipeline_failed carry no turn_id and no per-row content, but they are
// meaningful boundary markers (each resume is a new "pipeline session"
// inside the same run). Show them as standalone top-level rows without
// children, interleaved chronologically with node subtrees.
function isPipelineLifecycle(r: TurnRow): boolean {
  if (r.event_type !== "pipeline_event") return false;
  const st = r.subtype ?? "";
  return st.startsWith("pipeline_");
}

function groupTrace(rows: TurnRow[]): TraceGroup[] {
  // Node subtree roots — carry turn_id, have children.
  const isNodeRoot = (r: TurnRow) =>
    r.event_type === "agent_turn" ||
    (r.event_type === "pipeline_event" && r.subtype === "node_start");

  // Sort all rows chronologically (backend should already do this, but be
  // defensive in case the caller injects anything out of order).
  const sorted = [...rows].sort((a, b) =>
    (a.ts ?? "").localeCompare(b.ts ?? "")
  );

  // Build roots preserving chronological order. Each entry in `order` is
  // either a subtree (node root) or a standalone lifecycle marker. We
  // key lifecycle markers by `ts + stop_reason` since they have no turn_id.
  interface Entry {
    key: string;
    group: TraceGroup;
  }
  const order: Entry[] = [];
  const turnIndex = new Map<string, TraceGroup>();

  for (const r of sorted) {
    if (isNodeRoot(r) && r.turn_id && !turnIndex.has(r.turn_id)) {
      const g: TraceGroup = { root: r, children: [] };
      turnIndex.set(r.turn_id, g);
      order.push({ key: r.turn_id, group: g });
    } else if (isPipelineLifecycle(r)) {
      const key = `lc:${r.ts ?? ""}:${r.subtype ?? ""}`;
      order.push({ key, group: { root: r, children: [] } });
    }
  }

  // Second pass: attach non-root rows as children under their turn.
  const orphans: TraceGroup[] = [];
  for (const r of sorted) {
    if (isNodeRoot(r) && r.turn_id && turnIndex.get(r.turn_id)?.root === r) {
      continue;
    }
    if (isPipelineLifecycle(r)) continue;
    if (isEmptyHook(r)) continue;
    // llm_call stores parent_turn_id == turn_id. node_end / node_failed
    // don't set parent_turn_id but share turn_id with node_start — fall
    // back to turn_id so they nest under the node.
    const parentId = r.parent_turn_id ?? r.turn_id ?? null;
    if (parentId && turnIndex.has(parentId)) {
      turnIndex.get(parentId)!.children.push(r);
    } else {
      orphans.push({ root: r, children: [] });
    }
  }

  for (const e of order) {
    e.group.children.sort((a, b) => (a.ts ?? "").localeCompare(b.ts ?? ""));
  }

  // Collapse node_end / node_failed into the node_start root. Both rows
  // share the same turn_id and carry the "same" information from the
  // user's POV — showing them as parent + child looks like duplication.
  // We lift the end row's duration_ms / stop_reason / output_preview onto
  // the root and drop it from children. If duration_ms isn't recorded on
  // either row, fall back to (end.ts - start.ts).
  for (const e of order) {
    const g = e.group;
    if (g.root.event_type !== "pipeline_event") continue;
    const rootTid = g.root.turn_id;
    if (!rootTid) continue;
    const endIdx = g.children.findIndex(
      (c) =>
        c.event_type === "pipeline_event" &&
        c.turn_id === rootTid &&
        c !== g.root
    );
    if (endIdx < 0) continue;
    const end = g.children[endIdx];
    let dur = end.duration_ms ?? g.root.duration_ms ?? null;
    if (dur == null && g.root.ts && end.ts) {
      const d = Date.parse(end.ts) - Date.parse(g.root.ts);
      if (!Number.isNaN(d)) dur = d;
    }
    g.root = {
      ...g.root,
      duration_ms: dur,
      stop_reason: end.stop_reason ?? g.root.stop_reason,
      output_preview: end.output_preview ?? g.root.output_preview,
    };
    g.children.splice(endIdx, 1);
  }

  return [...order.map((e) => e.group), ...orphans];
}

// Muted palette, color picked by event hierarchy so the eye can scan the
// trace by level: pipeline > node > llm > tool > hook/compact > error.
// Failures override with rose regardless of level.
function statusBadgeClass(
  eventType: string | null,
  reason: string | null,
  subtype: string | null
): string {
  const r = reason ?? "";
  if (r === "failed" || r === "error") {
    return "bg-rose-50 text-rose-700 border border-rose-200";
  }
  if (r === "paused" || r === "interrupt") {
    return "bg-amber-50 text-amber-700 border border-amber-200";
  }
  switch (eventType) {
    case "pipeline_event":
      // Distinguish pipeline-lifecycle rows (subtype=pipeline_*) from
      // node-lifecycle rows (subtype=node_*) — stop_reason has been
      // normalized to ok/failed/etc. and no longer carries that info.
      if ((subtype ?? "").startsWith("pipeline_")) {
        return "bg-indigo-50 text-indigo-700 border border-indigo-200";
      }
      return "bg-sky-50 text-sky-700 border border-sky-200";
    case "llm_call":
      return "bg-violet-50 text-violet-700 border border-violet-200";
    case "tool_call":
      return "bg-emerald-50 text-emerald-700 border border-emerald-200";
    case "hook_event":
      return "bg-amber-50 text-amber-700 border border-amber-200";
    case "compact":
      return "bg-stone-50 text-stone-700 border border-stone-200";
    case "agent_turn":
      return "bg-slate-100 text-slate-700 border border-slate-200";
    case "error":
      return "bg-rose-50 text-rose-700 border border-rose-200";
    default:
      return "bg-slate-50 text-slate-600 border border-slate-200";
  }
}

function StatusBadge({
  eventType,
  reason,
  subtype,
}: {
  eventType: string | null;
  reason: string | null;
  subtype: string | null;
}) {
  const cls = statusBadgeClass(eventType, reason, subtype);
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-mono ${cls}`}>
      {reason ?? "done"}
    </span>
  );
}

function TraceRow({
  row,
  depth,
  expandState,
  onToggle,
  hasChildren,
}: {
  row: TurnRow;
  depth: number;
  expandState?: boolean;
  onToggle?: () => void;
  hasChildren?: boolean;
}) {
  const indent = depth * 16;
  const lcLabel = lifecycleLabel(row.subtype);

  // Pipeline-lifecycle rows (LangGraph-Start/End/Paused/Resumed/Failed)
  // are section markers, not subtrees. Render them as a compact banner
  // that spans the middle columns — the numeric cells (duration/tokens/
  // previews) are all N/A for these events, so collapsing them cleans up
  // the visual noise and makes the markers stand out as dividers.
  if (lcLabel) {
    const bannerClass =
      row.subtype === "pipeline_failed"
        ? "bg-rose-50/70 text-rose-700"
        : row.subtype === "pipeline_paused"
          ? "bg-amber-50/70 text-amber-700"
          : "bg-indigo-50/60 text-indigo-700";
    return (
      <tr className={bannerClass}>
        <td className="px-3 py-1.5 font-mono text-[11px] whitespace-nowrap">
          {row.ts?.slice(11, 19) ?? "—"}
        </td>
        <td colSpan={6} className="px-3 py-1.5">
          <span className="inline-flex items-center gap-2">
            <span className="h-px w-4 bg-current opacity-40" />
            <span className="font-semibold tracking-wide text-[11px] uppercase">
              {lcLabel}
            </span>
            <span className="h-px flex-1 bg-current opacity-20 min-w-[40px]" />
          </span>
        </td>
        <td className="px-3 py-1.5">
          <StatusBadge
            eventType={row.event_type}
            reason={row.stop_reason}
            subtype={row.subtype}
          />
        </td>
      </tr>
    );
  }

  const roleLabel = row.agent_role ?? "—";
  return (
    <tr className="hover:bg-slate-50">
      <td className="px-3 py-2 font-mono text-slate-400 whitespace-nowrap">
        {row.ts?.slice(11, 19) ?? "—"}
      </td>
      <td
        className={`px-3 py-2 ${
          depth === 0 ? "font-semibold text-slate-800" : "text-slate-600"
        }`}
      >
        <span style={{ paddingLeft: indent }} className="inline-flex items-center gap-1">
          {hasChildren ? (
            <button
              type="button"
              onClick={onToggle}
              className="text-slate-400 hover:text-slate-700 w-4 text-left"
              aria-label={expandState ? "collapse" : "expand"}
            >
              {expandState ? "▾" : "▸"}
            </button>
          ) : (
            <span className="inline-block w-4" />
          )}
          {roleLabel}
        </span>
      </td>
      <td className="px-3 py-2 font-mono text-slate-400">{row.event_type ?? "—"}</td>
      <td className="px-3 py-2 text-right">{formatDuration(row.duration_ms)}</td>
      <td className="px-3 py-2 text-right">
        {(row.input_tokens ?? 0)}/{(row.output_tokens ?? 0)}
      </td>
      <td
        className="px-3 py-2 truncate max-w-[280px] text-slate-600"
        title={row.input_preview_full ?? row.input_preview ?? ""}
      >
        {row.input_preview ?? ""}
      </td>
      <td className="px-3 py-2 truncate max-w-[200px] text-slate-600">
        {row.output_preview ?? ""}
      </td>
      <td className="px-3 py-2">
        <StatusBadge
          eventType={row.event_type}
          reason={row.stop_reason}
          subtype={row.subtype}
        />
      </td>
    </tr>
  );
}

function RawTimelineTab({ projectId }: { projectId: number }) {
  const [search, setSearch] = useSearchParams();
  // Scope is the 1st-level choice: chat (agent turns) vs pipeline run.
  // A deep-link carrying ?run=... implicitly activates run scope.
  const urlRun = search.get("run") ?? "";
  const urlScope = (search.get("scope") as Scope | null) ?? (urlRun ? "run" : "chat");
  const scope: Scope = urlScope === "run" || urlScope === "chat" ? urlScope : "chat";

  // 2nd-level controls: chat mode uses role/status; run mode uses run picker.
  const [role, setRole] = useState<string>("all");
  const [status, setStatus] = useState<string>("all");
  const [runInput, setRunInput] = useState<string>(urlRun);

  // Fetch the project's recent 20 runs for the dropdown.
  const fetchRuns = useCallback(
    () => client.get<{ items: RunListItem[] }>(`/projects/${projectId}/runs`),
    [projectId]
  );
  const { data: runsData } = useAsync(fetchRuns, [projectId]);
  const recentRuns = useMemo(
    () => (runsData?.items ?? []).slice(0, 20),
    [runsData]
  );

  const setScope = useCallback(
    (next: Scope) => {
      const params = new URLSearchParams(search);
      params.set("sub", "timeline");
      params.set("scope", next);
      if (next === "chat") params.delete("run");
      setSearch(params, { replace: true });
      if (next === "chat") setRunInput("");
    },
    [search, setSearch]
  );

  const applyRun = useCallback(
    (rid: string) => {
      const trimmed = rid.trim();
      const params = new URLSearchParams(search);
      params.set("sub", "timeline");
      params.set("scope", "run");
      if (trimmed) params.set("run", trimmed);
      else params.delete("run");
      setSearch(params, { replace: true });
    },
    [search, setSearch]
  );

  const query = useMemo(() => {
    const parts = [`project_id=${projectId}`, "limit=100"];
    if (scope === "chat") {
      if (role !== "all") parts.push(`role=${encodeURIComponent(role)}`);
      if (status !== "all") parts.push(`status=${encodeURIComponent(status)}`);
    } else if (urlRun) {
      parts.push(`run_id=${encodeURIComponent(urlRun)}`);
    }
    return parts.join("&");
  }, [projectId, scope, role, status, urlRun]);

  // In run scope with no run selected yet, don't fetch — show a hint.
  const shouldFetch = scope === "chat" || !!urlRun;
  const fetchTurns = useCallback(
    () => client.get<TurnRow[]>(`/telemetry/turns?${query}`),
    [query]
  );
  const { data, loading, error } = useAsync(
    shouldFetch ? fetchTurns : async () => [] as TurnRow[],
    [query, shouldFetch]
  );

  // Role dropdown is built from the current (chat) result set.
  const roles = useMemo(() => {
    if (!data) return [];
    const set = new Set<string>();
    for (const t of data) if (t.agent_role) set.add(t.agent_role);
    return Array.from(set).sort();
  }, [data]);

  return (
    <div className="space-y-4">
      {/* Level 1: scope segmented control */}
      <div className="inline-flex rounded-md border border-slate-300 overflow-hidden text-xs">
        {(["chat", "run"] as Scope[]).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setScope(s)}
            className={
              "px-4 py-1.5 font-medium " +
              (scope === s
                ? "bg-slate-900 text-white"
                : "bg-white text-slate-600 hover:bg-slate-50")
            }
          >
            {s === "chat" ? "Chat turns" : "Pipeline run"}
          </button>
        ))}
      </div>

      {/* Level 2: per-scope controls */}
      {scope === "chat" && (
        <div className="flex items-center gap-3">
          <label className="text-xs text-slate-500">Role</label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-xs"
          >
            <option value="all">all</option>
            {roles.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <label className="text-xs text-slate-500 ml-4">Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-xs"
          >
            <option value="all">all</option>
            <option value="done">done</option>
            <option value="interrupt">interrupt</option>
            <option value="error">error</option>
            <option value="idle_exit">idle_exit</option>
          </select>
        </div>
      )}

      {scope === "run" && (
        <div className="flex flex-wrap items-center gap-3">
          <label className="text-xs text-slate-500">Recent runs</label>
          <select
            value={urlRun}
            onChange={(e) => applyRun(e.target.value)}
            className="rounded border border-slate-300 bg-white px-2 py-1 text-xs min-w-[320px]"
          >
            <option value="">— pick a run —</option>
            {recentRuns.map((r) => {
              const label = `${r.pipeline ?? "pipeline"} · ${
                r.started_at?.slice(11, 19) ?? "—"
              } · ${r.run_id.slice(0, 8)} · ${r.status}`;
              return (
                <option key={r.run_id} value={r.run_id}>
                  {label}
                </option>
              );
            })}
          </select>
          <span className="text-xs text-slate-400">or paste</span>
          <input
            type="text"
            value={runInput}
            onChange={(e) => setRunInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") applyRun(runInput);
            }}
            placeholder="run_id"
            className="rounded border border-slate-300 bg-white px-2 py-1 text-xs font-mono w-[200px]"
          />
          <button
            type="button"
            onClick={() => applyRun(runInput)}
            className="rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-700"
          >
            Apply
          </button>
          {urlRun && (
            <button
              type="button"
              onClick={() => applyRun("")}
              className="text-xs text-slate-500 hover:text-slate-700 underline"
            >
              clear
            </button>
          )}
        </div>
      )}

      {loading && <p className="text-sm text-slate-500">Loading events…</p>}
      {error && (
        <p className="text-sm text-rose-600 font-mono">Failed: {error.message}</p>
      )}

      {scope === "run" && !urlRun && (
        <EmptyState msg="Pick a run above to see its events." />
      )}
      {shouldFetch && data && data.length === 0 && (
        <EmptyState msg="No events match these filters" />
      )}
      {shouldFetch && data && data.length > 0 && (
        <TraceTable rows={data} reverseRoots={scope === "chat"} />
      )}
    </div>
  );
}

// Nest tool_call visually under the preceding llm_call. hook_event /
// compact / error / node_end / node_failed break the chain and render at
// depth 1. Pure display transform — parent_turn_id isn't touched.
interface NestedChild {
  row: TurnRow;
  subs: TurnRow[];
}

function nestChildren(children: TurnRow[]): NestedChild[] {
  const out: NestedChild[] = [];
  let currentLlm: NestedChild | null = null;
  for (const c of children) {
    if (c.event_type === "llm_call") {
      currentLlm = { row: c, subs: [] };
      out.push(currentLlm);
    } else if (c.event_type === "tool_call" && currentLlm) {
      currentLlm.subs.push(c);
    } else {
      out.push({ row: c, subs: [] });
      currentLlm = null;
    }
  }
  return out;
}

function TraceTable({
  rows,
  reverseRoots = false,
}: {
  rows: TurnRow[];
  reverseRoots?: boolean;
}) {
  const groups = useMemo(() => {
    const g = groupTrace(rows);
    // Chat scope: newest turn on top, but children inside each group stay
    // chronological (groupTrace already sorted them). Pipeline-run scope
    // keeps strict ascending order so lifecycle markers read top-down.
    return reverseRoots ? [...g].reverse() : g;
  }, [rows, reverseRoots]);

  // Default: all roots with children are collapsed. When the row set
  // changes (e.g. user picks a different run), re-derive the initial
  // collapsed set so fresh data starts collapsed too.
  const initialCollapsed = useCallback(
    (gs: TraceGroup[]) =>
      new Set(
        gs
          .filter((g) => g.children.length > 0)
          .map((g, i) => g.root.turn_id ?? `orphan-${i}`)
      ),
    []
  );
  const [collapsed, setCollapsed] = useState<Set<string>>(() =>
    initialCollapsed(groups)
  );
  useEffect(() => {
    setCollapsed(initialCollapsed(groups));
  }, [groups, initialCollapsed]);

  const toggle = (id: string) => {
    setCollapsed((cur) => {
      const next = new Set(cur);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="rounded border border-slate-200 bg-white overflow-hidden">
      <table className="w-full text-xs">
        <thead className="bg-slate-50 text-slate-600 border-b border-slate-200">
          <tr>
            <th className="text-left px-3 py-2">Time</th>
            <th className="text-left px-3 py-2">Role / Node</th>
            <th className="text-left px-3 py-2">Event</th>
            <th className="text-right px-3 py-2">Duration</th>
            <th className="text-right px-3 py-2">Tokens</th>
            <th className="text-left px-3 py-2">Input preview</th>
            <th className="text-left px-3 py-2">Output preview</th>
            <th className="text-left px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {groups.map((g, gi) => {
            // Key precedence: turn_id (node subtrees, agent_turns) →
            // ts+stop_reason (pipeline lifecycle markers with no turn_id)
            // → positional fallback (orphans).
            const gid =
              g.root.turn_id ??
              (g.root.event_type === "pipeline_event"
                ? `lc:${g.root.ts ?? ""}:${g.root.subtype ?? ""}`
                : `orphan-${gi}`);
            const isCollapsed = collapsed.has(gid);
            const nested = nestChildren(g.children);
            return (
              <Fragment key={gid}>
                <TraceRow
                  row={g.root}
                  depth={0}
                  hasChildren={g.children.length > 0}
                  expandState={!isCollapsed}
                  onToggle={() => toggle(gid)}
                />
                {!isCollapsed &&
                  nested.map((nc, ci) => (
                    <Fragment key={`${gid}-${ci}`}>
                      <TraceRow row={nc.row} depth={1} />
                      {nc.subs.map((s, si) => (
                        <TraceRow
                          key={`${gid}-${ci}-${si}`}
                          row={s}
                          depth={2}
                        />
                      ))}
                    </Fragment>
                  ))}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "conversations", label: "Conversations" },
  { key: "aggregates", label: "Aggregates" },
  { key: "timeline", label: "Trace" },
];

export default function ObservabilityPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);
  const [search, setSearch] = useSearchParams();
  const raw = search.get("sub");
  // Back-compat: old ?sub=sessions deep-links map to the new Conversations tab.
  const normalised = raw === "sessions" ? "conversations" : raw;
  const sub: SubTab = ["conversations", "aggregates", "timeline"].includes(
    normalised ?? ""
  )
    ? (normalised as SubTab)
    : "aggregates";

  const fetchProject = useCallback(
    () => client.get<{ id: number; name: string }>(`/projects/${projectId}`),
    [projectId]
  );
  const { data: project, error: projectError } = useAsync(fetchProject, [projectId]);

  const is404 =
    projectError instanceof ApiError && projectError.status === 404;

  if (Number.isNaN(projectId)) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-6">
        <p className="text-sm text-rose-600">Invalid project id</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <div className="mb-4">
        <Link
          to={`/projects/${projectId}`}
          className="text-sm text-slate-500 hover:underline"
        >
          ← Back to project
        </Link>
      </div>

      {is404 && (
        <div className="rounded border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          <div className="font-medium">Project not found</div>
          <div className="font-mono text-xs mt-1">project_id={projectId} returned 404</div>
        </div>
      )}

      {!is404 && (
        <>
          <h1 className="text-2xl font-semibold">Insights</h1>
          <p className="text-sm text-slate-500 mt-1">
            {project ? `${project.name} (#${project.id})` : "Loading project…"}
          </p>

          <nav className="mt-6 border-b border-slate-200 flex gap-4">
            {SUB_TABS.map((t) => {
              const isActive = t.key === sub;
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setSearch({ sub: t.key })}
                  className={
                    "py-2 px-1 text-sm font-medium " +
                    (isActive
                      ? "border-b-2 border-slate-900 text-slate-900"
                      : "text-slate-500 hover:text-slate-700")
                  }
                >
                  {t.label}
                </button>
              );
            })}
          </nav>

          <div className="mt-6">
            {sub === "conversations" && <ConversationsTab projectId={projectId} />}
            {sub === "aggregates" && <AggregatesTab projectId={projectId} />}
            {sub === "timeline" && <RawTimelineTab projectId={projectId} />}
          </div>
        </>
      )}
    </div>
  );
}
