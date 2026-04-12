import { useCallback, useState } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { client } from "@/api/client";
import { useAsync } from "@/hooks/useAsync";

interface CostBucket {
  key: string;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  llm_calls: number;
  total_latency_ms: number;
}

interface Trends {
  project_id: number;
  latency: Array<{ day: string; avg_latency_ms: number }>;
  tokens: Array<{ day: string; input_tokens: number; output_tokens: number }>;
  cost: Array<{ day: string; cost_usd: number }>;
}

interface RunSummary {
  run_id: string;
  llm_calls: number;
  tool_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_cost_usd: number;
  total_llm_latency_ms: number;
  duration_ms: number | null;
  started_at: string | null;
  ended_at: string | null;
  errors: number;
}

interface RunListItem {
  run_id: string;
  status: string;
  pipeline: string | null;
  started_at: string | null;
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-slate-200 bg-white px-4 py-3">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold mt-0.5">{value}</div>
    </div>
  );
}

function RunTelemetryPanel({ runId }: { projectId: number; runId: string }) {
  const fetchSummary = useCallback(
    () => client.get<RunSummary>(`/telemetry/runs/${runId}/summary`),
    [runId]
  );
  const { data, error, loading } = useAsync(fetchSummary, [runId]);

  if (loading) return <p className="text-xs text-slate-500">Loading telemetry…</p>;
  if (error) return <p className="text-xs text-slate-400">No telemetry data</p>;
  if (!data) return null;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="LLM Calls" value={String(data.llm_calls)} />
        <StatCard label="Tool Calls" value={String(data.tool_calls)} />
        <StatCard
          label="Tokens (in/out)"
          value={`${(data.total_input_tokens / 1000).toFixed(1)}k / ${(data.total_output_tokens / 1000).toFixed(1)}k`}
        />
        <StatCard label="Cost" value={`$${data.total_cost_usd.toFixed(4)}`} />
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <StatCard
          label="Avg Latency"
          value={
            data.llm_calls > 0
              ? `${(data.total_llm_latency_ms / data.llm_calls).toFixed(0)}ms`
              : "—"
          }
        />
        <StatCard
          label="Duration"
          value={data.duration_ms ? `${(data.duration_ms / 1000).toFixed(1)}s` : "—"}
        />
        <StatCard label="Errors" value={String(data.errors)} />
      </div>
    </div>
  );
}

export default function DashboardTab({ projectId }: { projectId: number }) {
  const fetchTrends = useCallback(
    () => client.get<Trends>(`/telemetry/projects/${projectId}/trends`),
    [projectId]
  );
  const fetchCost = useCallback(
    () => client.get<CostBucket[]>(`/telemetry/projects/${projectId}/cost?group_by=day`),
    [projectId]
  );
  const fetchRuns = useCallback(
    () => client.get<{ items: RunListItem[] }>(`/projects/${projectId}/runs`),
    [projectId]
  );

  const { data: trends, error: trendsError } = useAsync(fetchTrends, [projectId]);
  useAsync(fetchCost, [projectId]);
  const { data: runsData } = useAsync(fetchRuns, [projectId]);

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  const hasData = trends && (trends.cost.length > 0 || trends.tokens.length > 0);

  return (
    <div className="space-y-8">
      {/* Cost Trend */}
      <section>
        <h2 className="text-lg font-medium mb-3">Cost Trend</h2>
        {trendsError && (
          <p className="text-sm text-slate-400">No telemetry data yet. Run a pipeline to see metrics.</p>
        )}
        {hasData && trends.cost.length > 0 ? (
          <div className="rounded border border-slate-200 bg-white p-4">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={trends.cost}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="cost_usd" fill="#3b82f6" name="Cost (USD)" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          !trendsError && <p className="text-sm text-slate-400">No cost data yet.</p>
        )}
      </section>

      {/* Token Usage */}
      <section>
        <h2 className="text-lg font-medium mb-3">Token Usage</h2>
        {hasData && trends.tokens.length > 0 ? (
          <div className="rounded border border-slate-200 bg-white p-4">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={trends.tokens}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Legend />
                <Bar dataKey="input_tokens" fill="#6366f1" name="Input" radius={[2, 2, 0, 0]} />
                <Bar dataKey="output_tokens" fill="#22c55e" name="Output" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-sm text-slate-400">No token data yet.</p>
        )}
      </section>

      {/* Latency Trend */}
      <section>
        <h2 className="text-lg font-medium mb-3">Avg LLM Latency</h2>
        {hasData && trends.latency.length > 0 ? (
          <div className="rounded border border-slate-200 bg-white p-4">
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={trends.latency}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="day" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} unit="ms" />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="avg_latency_ms"
                  stroke="#f59e0b"
                  name="Latency (ms)"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-sm text-slate-400">No latency data yet.</p>
        )}
      </section>

      {/* Run Telemetry Drill-down */}
      <section>
        <h2 className="text-lg font-medium mb-3">Run Telemetry</h2>
        {runsData && runsData.items.length > 0 ? (
          <div className="space-y-3">
            <select
              value={selectedRunId || ""}
              onChange={(e) => setSelectedRunId(e.target.value || null)}
              className="rounded border border-slate-300 px-2 py-1 text-sm w-full max-w-md"
            >
              <option value="">Select a run…</option>
              {runsData.items
                .filter((r) => r.status === "completed")
                .slice(0, 20)
                .map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id.slice(0, 8)}… — {r.pipeline ?? "—"} ({r.started_at?.slice(0, 16) ?? ""})
                  </option>
                ))}
            </select>
            {selectedRunId && (
              <RunTelemetryPanel projectId={projectId} runId={selectedRunId} />
            )}
          </div>
        ) : (
          <p className="text-sm text-slate-400">No completed runs yet.</p>
        )}
      </section>
    </div>
  );
}
