import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useParams, Link } from "react-router-dom";
import { client, ApiError } from "@/api/client";
import { fetchEventStream, type SseEvent } from "@/api/sse";
import type { RunDetail } from "@/api/types";

interface StreamState {
  liveStream?: boolean;
  pipelineName?: string;
  inputText?: string;
}

export default function RunDetailPage() {
  const { id, runId } = useParams<{ id: string; runId: string }>();
  const projectId = Number(id);
  const location = useLocation();
  const state = (location.state ?? {}) as StreamState;

  const [events, setEvents] = useState<SseEvent[]>([]);
  const [status, setStatus] = useState<string>("—");
  const [error, setError] = useState<Error | null>(null);
  const [streaming, setStreaming] = useState<boolean>(false);
  const abortRef = useRef<AbortController | null>(null);

  const liveStream = state.liveStream === true && runId === "pending";

  // Live streaming path.
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
          setEvents((prev) => [...prev, ev]);
          if (ev.type === "pipeline_end") setStatus("completed");
          if (ev.type === "pipeline_failed") setStatus("failed");
        },
      }
    )
      .catch((err: unknown) => {
        setError(err instanceof Error ? err : new Error(String(err)));
        setStatus("failed");
      })
      .finally(() => setStreaming(false));
    return () => ac.abort();
  }, [liveStream, projectId, state.pipelineName, state.inputText]);

  // Historical run fetch path (runId is a real id, not "pending").
  const loadHistorical = useCallback(async () => {
    if (liveStream || !runId || runId === "pending") return;
    try {
      const detail = await client.get<RunDetail>(`/runs/${runId}`);
      setStatus(detail.status);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, [liveStream, runId]);

  useEffect(() => {
    void loadHistorical();
  }, [loadHistorical]);

  return (
    <div>
      <div className="mb-4">
        <Link
          to={`/projects/${projectId}?tab=runs`}
          className="text-sm text-slate-500 hover:underline"
        >
          ← Back to runs
        </Link>
      </div>
      <h1 className="text-2xl font-semibold">Run detail</h1>
      <p className="text-sm text-slate-500 font-mono">
        run_id: {runId} · status: {status}
        {streaming ? " (streaming…)" : ""}
      </p>
      {error && (
        <div className="mt-3 rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <div className="font-medium">
            {error instanceof ApiError ? `Error ${error.status}` : "Error"}
          </div>
          <div className="font-mono text-xs mt-1">{error.message}</div>
        </div>
      )}
      <section className="mt-6">
        <h2 className="text-lg font-medium mb-2">Event log</h2>
        {events.length === 0 && !liveStream && (
          <p className="text-slate-500 text-sm">
            No events buffered. Trigger a run with streaming enabled from the
            Runs tab to see live events here.
          </p>
        )}
        {events.length > 0 && (
          <ol className="rounded border border-slate-200 bg-white divide-y divide-slate-200 max-h-96 overflow-auto">
            {events.map((ev, i) => (
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
    </div>
  );
}
