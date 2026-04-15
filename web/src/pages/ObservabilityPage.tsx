import { useCallback, useMemo, useState, type ReactElement, type ReactNode } from "react";
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

type SubTab = "sessions" | "aggregates" | "timeline";

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
  project_id: number | null;
  run_id: string | null;
  session_id: number | null;
  agent_role: string | null;
  stop_reason: string | null;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  input_preview: string | null;
  output_preview: string | null;
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

// ── Sub-tab: Sessions ────────────────────────────────────────

function SessionsTab({ projectId }: { projectId: number }) {
  const fetchSessions = useCallback(
    () => client.get<SessionRow[]>(`/telemetry/sessions?project_id=${projectId}&limit=50`),
    [projectId]
  );
  const { data, loading, error } = useAsync(fetchSessions, [projectId]);
  const [selected, setSelected] = useState<number | null>(null);

  if (loading) return <p className="text-sm text-slate-500">Loading sessions…</p>;
  if (error)
    return (
      <p className="text-sm text-rose-600 font-mono">
        Failed to load sessions: {error.message}
      </p>
    );
  if (!data || data.length === 0)
    return <EmptyState msg="No chat sessions for this project yet" />;

  return (
    <div className="space-y-4">
      <div className="rounded border border-slate-200 bg-white overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="text-left px-3 py-2">Session key</th>
              <th className="text-left px-3 py-2">Channel</th>
              <th className="text-left px-3 py-2">Mode</th>
              <th className="text-left px-3 py-2">Created</th>
              <th className="text-left px-3 py-2">Last active</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {data.map((s) => (
              <tr
                key={s.id}
                onClick={() => setSelected(s.id)}
                className={
                  "cursor-pointer hover:bg-slate-50 " +
                  (selected === s.id ? "bg-blue-50" : "")
                }
              >
                <td className="px-3 py-2 font-mono truncate max-w-[240px]">{s.session_key}</td>
                <td className="px-3 py-2">{s.channel ?? "—"}</td>
                <td className="px-3 py-2">{s.mode ?? "—"}</td>
                <td className="px-3 py-2 text-slate-500">{s.created_at?.slice(0, 19).replace("T", " ") ?? "—"}</td>
                <td className="px-3 py-2 text-slate-500">{s.last_active_at?.slice(0, 19).replace("T", " ") ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selected !== null && <SessionTurnTimeline sessionId={selected} />}
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
                  {p.duration_ms ? `${((p.duration_ms as number) / 1000).toFixed(1)}s` : "—"}
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
            title="Turns by status"
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

// ── Sub-tab: Raw Timeline ───────────────────────────────────

function RawTimelineTab({ projectId }: { projectId: number }) {
  const [role, setRole] = useState<string>("all");
  const [status, setStatus] = useState<string>("all");

  const query = useMemo(() => {
    const parts = [`project_id=${projectId}`, "limit=100"];
    if (role !== "all") parts.push(`role=${encodeURIComponent(role)}`);
    if (status !== "all") parts.push(`status=${encodeURIComponent(status)}`);
    return parts.join("&");
  }, [projectId, role, status]);

  const fetchTurns = useCallback(
    () => client.get<TurnRow[]>(`/telemetry/turns?${query}`),
    [query]
  );
  const { data, loading, error } = useAsync(fetchTurns, [query]);

  // Build role dropdown from the current result set.
  const roles = useMemo(() => {
    if (!data) return [];
    const set = new Set<string>();
    for (const t of data) if (t.agent_role) set.add(t.agent_role);
    return Array.from(set).sort();
  }, [data]);

  return (
    <div className="space-y-3">
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

      {loading && <p className="text-sm text-slate-500">Loading turns…</p>}
      {error && (
        <p className="text-sm text-rose-600 font-mono">Failed: {error.message}</p>
      )}

      {data && data.length === 0 && <EmptyState msg="No turns match these filters" />}
      {data && data.length > 0 && (
        <div className="rounded border border-slate-200 bg-white overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 text-slate-600">
              <tr>
                <th className="text-left px-3 py-2">Time</th>
                <th className="text-left px-3 py-2">Role</th>
                <th className="text-right px-3 py-2">Duration</th>
                <th className="text-right px-3 py-2">Tokens</th>
                <th className="text-left px-3 py-2">Input preview</th>
                <th className="text-left px-3 py-2">Output preview</th>
                <th className="text-left px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.map((t, i) => (
                <tr key={`${t.ts}-${i}`}>
                  <td className="px-3 py-2 font-mono text-slate-500 whitespace-nowrap">
                    {t.ts?.slice(11, 19) ?? "—"}
                  </td>
                  <td className="px-3 py-2">{t.agent_role ?? "—"}</td>
                  <td className="px-3 py-2 text-right">
                    {t.duration_ms ? `${(t.duration_ms / 1000).toFixed(1)}s` : "—"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {(t.input_tokens ?? 0)}/{(t.output_tokens ?? 0)}
                  </td>
                  <td className="px-3 py-2 truncate max-w-[200px] text-slate-600">
                    {t.input_preview ?? ""}
                  </td>
                  <td className="px-3 py-2 truncate max-w-[200px] text-slate-600">
                    {t.output_preview ?? ""}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        "rounded px-1.5 py-0.5 text-[10px] font-mono " +
                        (t.stop_reason === "error"
                          ? "bg-rose-100 text-rose-700"
                          : t.stop_reason === "interrupt"
                            ? "bg-amber-100 text-amber-700"
                            : "bg-slate-100 text-slate-600")
                      }
                    >
                      {t.stop_reason ?? "done"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Main page ───────────────────────────────────────────────

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "sessions", label: "Sessions" },
  { key: "aggregates", label: "Aggregates" },
  { key: "timeline", label: "Raw Timeline" },
];

export default function ObservabilityPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);
  const [search, setSearch] = useSearchParams();
  const raw = search.get("sub");
  const sub: SubTab = ["sessions", "aggregates", "timeline"].includes(raw ?? "")
    ? (raw as SubTab)
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
          <h1 className="text-2xl font-semibold">Observability</h1>
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
            {sub === "sessions" && <SessionsTab projectId={projectId} />}
            {sub === "aggregates" && <AggregatesTab projectId={projectId} />}
            {sub === "timeline" && <RawTimelineTab projectId={projectId} />}
          </div>
        </>
      )}
    </div>
  );
}
