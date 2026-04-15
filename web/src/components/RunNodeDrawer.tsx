import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { client } from "../api/client";
import { getRunGraph, type RunGraphResponse } from "../api/runs";
import type { RunDetail } from "../api/types";

interface TimelineEvent {
  id: number;
  ts: string;
  event_type: string;
  agent_role: string | null;
  payload: Record<string, unknown>;
}

interface RunNodeDrawerProps {
  runId: string;
  nodeName: string | null;
  isOpen: boolean;
  onClose: () => void;
  sseEvents?: Array<{ type: string; data: string }>;
}

const OUTPUT_TRUNCATE = 2000;

function getPayloadNode(ev: TimelineEvent): string | null {
  const p = ev.payload ?? {};
  const n = (p as { node_name?: unknown }).node_name;
  return typeof n === "string" ? n : null;
}

function getNumber(obj: Record<string, unknown>, key: string): number {
  const v = obj[key];
  return typeof v === "number" ? v : 0;
}

function formatDuration(ms: number | null): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

export default function RunNodeDrawer({
  runId,
  nodeName,
  isOpen,
  onClose,
  sseEvents = [],
}: RunNodeDrawerProps) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [graph, setGraph] = useState<RunGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [showFullOutput, setShowFullOutput] = useState(false);

  useEffect(() => {
    if (!isOpen || !nodeName) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setShowFullOutput(false);
    Promise.all([
      client.get<RunDetail>(`/runs/${runId}`),
      client.get<TimelineEvent[]>(`/telemetry/runs/${runId}/timeline`),
      getRunGraph(runId),
    ])
      .then(([d, t, g]) => {
        if (cancelled) return;
        setDetail(d);
        setTimeline(t);
        setGraph(g);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, nodeName, runId]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose]);

  const filteredTimeline = useMemo(() => {
    if (!nodeName) return [];
    return timeline.filter((ev) => getPayloadNode(ev) === nodeName);
  }, [timeline, nodeName]);

  const rollup = useMemo(() => {
    let llmCalls = 0;
    let toolCalls = 0;
    let inTok = 0;
    let outTok = 0;
    let cost = 0;
    for (const ev of filteredTimeline) {
      if (ev.event_type === "llm_call") {
        llmCalls += 1;
        inTok += getNumber(ev.payload, "input_tokens");
        outTok += getNumber(ev.payload, "output_tokens");
        const c = ev.payload.cost_usd;
        if (typeof c === "number") cost += c;
      } else if (ev.event_type === "tool_call") {
        toolCalls += 1;
      }
    }
    return { llmCalls, toolCalls, inTok, outTok, cost };
  }, [filteredTimeline]);

  const nodeSseEvents = useMemo(() => {
    if (!nodeName) return [];
    return sseEvents.filter((ev) => {
      try {
        const parsed = JSON.parse(ev.data) as { node_name?: string };
        return parsed.node_name === nodeName;
      } catch {
        return false;
      }
    });
  }, [sseEvents, nodeName]);

  if (!isOpen || !nodeName) return null;

  const projectId = detail?.project_id ?? null;
  const output = detail?.outputs?.[nodeName] ?? "";
  const outputTruncated = output.length > OUTPUT_TRUNCATE;
  const displayOutput =
    outputTruncated && !showFullOutput ? output.slice(0, OUTPUT_TRUNCATE) : output;

  const graphNode = graph?.nodes.find((n) => n.name === nodeName);

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end"
      data-testid="run-node-drawer"
      role="dialog"
      aria-label={`Node detail: ${nodeName}`}
    >
      <div
        className="absolute inset-0 bg-black/30"
        onClick={onClose}
        data-testid="drawer-backdrop"
      />
      <div className="relative z-10 h-full w-full max-w-xl overflow-y-auto bg-white shadow-xl">
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-3">
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-500">Node</div>
            <div className="text-lg font-semibold">{nodeName}</div>
            {graphNode && (
              <div className="text-xs text-slate-500 mt-0.5">
                status: <span className="font-mono">{graphNode.status}</span>
                {graphNode.role ? ` · role: ${graphNode.role}` : ""}
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-2 py-1 text-slate-500 hover:bg-slate-100"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        {loading && (
          <div className="px-5 py-4 text-sm text-slate-500">Loading…</div>
        )}
        {error && (
          <div className="px-5 py-4 text-sm text-rose-600">
            Failed to load: {error.message}
          </div>
        )}

        {!loading && !error && (
          <div className="px-5 py-4 space-y-4">
            <details open className="rounded border border-slate-200">
              <summary className="cursor-pointer px-3 py-2 text-sm font-semibold bg-slate-50">
                Output
              </summary>
              <div className="p-3">
                {output.length === 0 ? (
                  <div className="text-sm text-slate-500">
                    No output recorded for this node.
                  </div>
                ) : (
                  <>
                    <pre className="whitespace-pre-wrap break-words text-xs bg-slate-50 rounded p-2 max-h-96 overflow-auto">
                      {displayOutput}
                    </pre>
                    {outputTruncated && (
                      <button
                        type="button"
                        onClick={() => setShowFullOutput((v) => !v)}
                        className="mt-2 text-xs text-blue-600 hover:underline"
                      >
                        {showFullOutput
                          ? "show less"
                          : `show more (${output.length - OUTPUT_TRUNCATE} more chars)`}
                      </button>
                    )}
                  </>
                )}
              </div>
            </details>

            <details open className="rounded border border-slate-200">
              <summary className="cursor-pointer px-3 py-2 text-sm font-semibold bg-slate-50">
                Timeline ({filteredTimeline.length})
              </summary>
              <div className="p-3">
                {filteredTimeline.length === 0 ? (
                  <div className="text-sm text-slate-500">No events for this node.</div>
                ) : (
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="text-left text-slate-500 border-b">
                        <th className="py-1 pr-2">ts</th>
                        <th className="py-1 pr-2">event</th>
                        <th className="py-1 pr-2">duration</th>
                        <th className="py-1">stop_reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTimeline.map((ev) => {
                        const dur = ev.payload.duration_ms;
                        const stop = ev.payload.stop_reason;
                        return (
                          <tr key={ev.id} className="border-b last:border-b-0">
                            <td className="py-1 pr-2 font-mono">
                              {new Date(ev.ts).toLocaleTimeString()}
                            </td>
                            <td className="py-1 pr-2">{ev.event_type}</td>
                            <td className="py-1 pr-2">
                              {typeof dur === "number" ? formatDuration(dur) : "—"}
                            </td>
                            <td className="py-1">
                              {typeof stop === "string" ? stop : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                )}
              </div>
            </details>

            <details open className="rounded border border-slate-200">
              <summary className="cursor-pointer px-3 py-2 text-sm font-semibold bg-slate-50">
                Telemetry
              </summary>
              <div className="p-3 grid grid-cols-2 gap-2 text-xs">
                <div className="rounded bg-slate-50 px-2 py-1">
                  <div className="text-slate-500">llm_calls</div>
                  <div className="font-semibold">{rollup.llmCalls}</div>
                </div>
                <div className="rounded bg-slate-50 px-2 py-1">
                  <div className="text-slate-500">tool_calls</div>
                  <div className="font-semibold">{rollup.toolCalls}</div>
                </div>
                <div className="rounded bg-slate-50 px-2 py-1">
                  <div className="text-slate-500">tokens (in / out)</div>
                  <div className="font-semibold">
                    {rollup.inTok} / {rollup.outTok}
                  </div>
                </div>
                <div className="rounded bg-slate-50 px-2 py-1">
                  <div className="text-slate-500">cost_usd</div>
                  <div className="font-semibold">${rollup.cost.toFixed(6)}</div>
                </div>
              </div>
            </details>

            <details open className="rounded border border-slate-200">
              <summary className="cursor-pointer px-3 py-2 text-sm font-semibold bg-slate-50">
                Events ({nodeSseEvents.length})
              </summary>
              <div className="p-3 max-h-64 overflow-auto">
                {nodeSseEvents.length === 0 ? (
                  <div className="text-sm text-slate-500">
                    No live SSE events for this node.
                  </div>
                ) : (
                  <ul className="space-y-1 text-xs font-mono">
                    {nodeSseEvents.map((ev, i) => (
                      <li key={i} className="border-b border-slate-100 pb-1">
                        <span className="text-slate-500">{ev.type}</span>{" "}
                        <span className="text-slate-700">{ev.data}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </details>
          </div>
        )}

        <div className="sticky bottom-0 border-t border-slate-200 bg-white px-5 py-3">
          {projectId !== null ? (
            <Link
              to={`/projects/${projectId}/observability?sub=timeline&run=${runId}`}
              className="text-sm text-blue-600 hover:underline"
            >
              See all events for this run in Observability →
            </Link>
          ) : (
            <span className="text-sm text-slate-400">
              See all events for this run in Observability →
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
