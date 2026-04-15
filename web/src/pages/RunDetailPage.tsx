import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, Link } from "react-router-dom";
import { client, ApiError, __internal } from "@/api/client";
import { fetchEventStream, type SseEvent } from "@/api/sse";
import {
  subscribeRunEvents,
  pauseRun,
  cancelRun,
  getRunGraph,
  type RunGraphResponse,
} from "@/api/runs";
import type { RunDetail } from "@/api/types";
import {
  AgentRunDrawerProvider,
} from "@/components/AgentRunDrawerContext";
import RunGraph from "@/components/RunGraph";
import RunNodeDrawer from "@/components/RunNodeDrawer";

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

interface StreamState {
  liveStream?: boolean;
  pipelineName?: string;
  inputText?: string;
}

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  running: "bg-blue-100 text-blue-800",
  pending: "bg-slate-100 text-slate-600",
  paused: "bg-yellow-100 text-yellow-800",
  cancelled: "bg-slate-100 text-slate-500",
};

export default function RunDetailPage() {
  return (
    <AgentRunDrawerProvider>
      <RunDetailPageInner />
    </AgentRunDrawerProvider>
  );
}

function RunDetailPageInner() {
  const { id, runId } = useParams<{ id: string; runId: string }>();
  const projectId = Number(id);
  const location = useLocation();
  const navigate = useNavigate();
  const state = (location.state ?? {}) as StreamState;

  const [sseEvents, setSseEvents] = useState<SseEvent[]>([]);
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [graph, setGraph] = useState<RunGraphResponse | null>(null);
  const [status, setStatus] = useState<string>("—");
  const [error, setError] = useState<Error | null>(null);
  const [streaming, setStreaming] = useState<boolean>(false);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const liveRunIdRef = useRef<string | null>(null);
  const [liveRunId, setLiveRunId] = useState<string | null>(null);

  const liveStream = state.liveStream === true && runId === "pending";

  // Live stream effect (fresh-triggered run arriving at /runs/pending)
  useEffect(() => {
    if (!liveStream || !state.pipelineName) return;
    const ac = new AbortController();
    abortRef.current = ac;
    setStreaming(true);
    setStatus("running");
    // Wipe history.state immediately so a refresh during the live stream
    // can't re-trigger this effect and POST a duplicate run. We've already
    // captured pipelineName/inputText into the closure above.
    window.history.replaceState(null, "");
    fetchEventStream(
      `/projects/${projectId}/pipelines/${state.pipelineName}/runs?stream=true`,
      {
        signal: ac.signal,
        body: { input: state.inputText ? { text: state.inputText } : {} },
        onEvent: (ev) => {
          setSseEvents((prev) => [...prev, ev]);
          if (ev.type === "started" && liveRunIdRef.current === null) {
            try {
              const parsed = JSON.parse(ev.data) as { run_id?: string };
              if (parsed.run_id) {
                liveRunIdRef.current = parsed.run_id;
                setLiveRunId(parsed.run_id);
                // Clear history.state BEFORE the user can refresh. The
                // browser's History API preserves location.state across a
                // hard reload, so if we leave {liveStream:true, …} sitting
                // there and the user hits F5 while still on /runs/pending,
                // this effect fires again and POSTs a duplicate run. Wipe
                // the state bag now that the run is created; the current
                // SSE stream is unaffected because we don't touch the URL
                // (React Router won't re-render / re-run deps).
                window.history.replaceState(null, "");
              }
            } catch {
              // malformed started frame — ignore
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
        const realId = liveRunIdRef.current;
        if (realId) {
          navigate(`/projects/${projectId}/runs/${realId}`, { replace: true });
        }
      });
    return () => ac.abort();
  }, [liveStream, projectId, state.pipelineName, state.inputText, navigate]);

  // Task 8.3: resubscribe SSE for real runs that are still active.
  // The initial liveStream above tears itself down as soon as the pipeline
  // reaches `paused` (the LangGraph interrupt drains the stream). After the
  // user clicks Approve/Reject/Edit the run transitions back to `running`
  // and subsequently emits more node_start / node_end / pipeline_end events,
  // but the old connection is gone. This effect attaches to the standalone
  // /runs/{id}/events endpoint whenever we are on a real run id that is in
  // a non-terminal state, keeping the UI live across pause → resume cycles.
  useEffect(() => {
    if (liveStream) return;
    if (!runId || runId === "pending") return;
    if (status !== "running" && status !== "paused") return;
    const ac = new AbortController();
    setStreaming(true);
    subscribeRunEvents(runId, {
      signal: ac.signal,
      onEvent: (ev) => {
        setSseEvents((prev) => [...prev, ev]);
        if (ev.type === "pipeline_end") setStatus("completed");
        if (ev.type === "pipeline_failed") setStatus("failed");
        if (ev.type === "pipeline_paused") setStatus("paused");
        if (ev.type === "terminal") {
          try {
            const parsed = JSON.parse(ev.data) as { status?: string };
            if (parsed.status) setStatus(parsed.status);
          } catch {
            // ignore malformed terminal frame
          }
        }
      },
    })
      .catch((err: unknown) => {
        if ((err as { name?: string }).name === "AbortError") return;
        setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        setStreaming(false);
      });
    return () => ac.abort();
  }, [liveStream, runId, status]);

  // Load historical run detail + graph on mount / after resume.
  const loadHistorical = useCallback(async () => {
    if (liveStream || !runId || runId === "pending") return;
    try {
      const [d, g] = await Promise.all([
        client.get<RunDetail>(`/runs/${runId}`),
        getRunGraph(runId).catch(() => null),
      ]);
      setDetail(d);
      if (g) setGraph(g);
      setStatus(d.status);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, [liveStream, runId]);

  useEffect(() => {
    void loadHistorical();
  }, [loadHistorical]);

  const realRunId = liveRunId ?? (runId && runId !== "pending" ? runId : null);

  // Re-fetch the graph whenever new SSE events land so node statuses stay
  // fresh. This covers BOTH the pending live-stream path (URL still says
  // `/runs/pending`, but `liveRunId` has been captured from the `started`
  // frame) AND the historical/paused path (real URL run id).
  useEffect(() => {
    if (!realRunId) return;
    if (sseEvents.length === 0) return;
    getRunGraph(realRunId)
      .then((g) => setGraph(g))
      .catch(() => {
        /* graph may not be ready yet */
      });
  }, [sseEvents.length, realRunId]);

  // Whenever SSE flips status to a state-changed value, refresh the REST
  // detail so detail.paused_at / paused_output / final_output catch up.
  // Without this, ResumePanel (gated on detail?.paused_at) never appears
  // on the 2nd/3rd pause because detail is frozen at load-time.
  useEffect(() => {
    if (!realRunId) return;
    if (status !== "paused" && status !== "completed" && status !== "failed") return;
    client
      .get<RunDetail>(`/runs/${realRunId}`)
      .then((d) => setDetail(d))
      .catch(() => {
        /* detail may not be ready yet */
      });
  }, [status, realRunId]);

  const graphNodes = graph?.nodes ?? [];
  const graphEdges = graph?.edges ?? [];

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
          <span className="text-xs text-blue-600 animate-pulse">streaming…</span>
        )}
        <div className="flex-1" />
        {realRunId && status === "completed" && (
          <button
            type="button"
            onClick={() => void downloadExport(realRunId, "md")}
            className="rounded border border-slate-300 px-3 py-1 text-xs text-slate-700 hover:bg-slate-50 mr-2"
          >
            Download
          </button>
        )}
        <RunOpsButtons
          runId={realRunId}
          status={status}
          onChanged={() => void loadHistorical()}
        />
      </div>

      {/* Meta */}
      <p className="text-sm text-slate-500 font-mono mb-4">
        run_id: {runId}
        {detail?.pipeline && ` · pipeline: ${detail.pipeline}`}
        {detail?.started_at && ` · started: ${detail.started_at}`}
        {detail?.finished_at && ` · finished: ${detail.finished_at}`}
      </p>

      {/* Resume banner for paused runs — above the DAG, not inside drawer. */}
      {status === "paused" && detail?.paused_at && (
        <ResumePanel
          runId={realRunId ?? runId!}
          pausedAt={detail.paused_at}
          pausedOutput={detail.paused_output ?? ""}
          onResumed={() => {
            // Optimistically flip to "running" so the banner dismisses
            // immediately. Do NOT refetch detail here: resume is 202
            // async, backend.status is still "paused" for a beat, and a
            // GET would overwrite our optimistic value. SSE will drive
            // the next state change and the status-watching effect
            // above will refresh detail when it lands.
            setStatus("running");
          }}
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

      {/* Pipeline DAG — primary view. Pending runs render an empty graph
          with a placeholder; clicking any node opens RunNodeDrawer. */}
      <section className="rounded border border-slate-200 bg-white">
        <div className="h-[520px]">
          <RunGraph
            nodes={graphNodes}
            edges={graphEdges}
            onNodeClick={(nodeId) => setSelectedNode(nodeId)}
            emptyMessage={
              streaming || status === "running"
                ? "Waiting for first node to start…"
                : "Waiting for run to start…"
            }
          />
        </div>
      </section>

      <RunNodeDrawer
        runId={realRunId ?? ""}
        nodeName={realRunId ? selectedNode : null}
        isOpen={!!selectedNode && !!realRunId}
        onClose={() => setSelectedNode(null)}
        sseEvents={sseEvents}
      />
    </div>
  );
}

function RunOpsButtons({
  runId,
  status,
  onChanged,
}: {
  runId: string | null;
  status: string;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<"pause" | "cancel" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  if (!runId) return null;
  const canPause = status === "running";
  const canCancel = status === "running" || status === "paused";
  if (!canPause && !canCancel) return null;

  const doPause = async () => {
    setBusy("pause");
    setErr(null);
    try {
      await pauseRun(runId);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const doCancel = async () => {
    if (!window.confirm("Cancel this run? In-flight LLM calls may still bill.")) return;
    setBusy("cancel");
    setErr(null);
    try {
      await cancelRun(runId);
      onChanged();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex items-center gap-2">
      {canPause && (
        <button
          type="button"
          disabled={busy !== null}
          onClick={doPause}
          className="rounded border border-amber-400 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-50"
        >
          {busy === "pause" ? "Pausing…" : "⏸ Pause"}
        </button>
      )}
      {canCancel && (
        <button
          type="button"
          disabled={busy !== null}
          onClick={doCancel}
          className="rounded border border-rose-400 bg-rose-50 px-3 py-1 text-xs font-medium text-rose-800 hover:bg-rose-100 disabled:opacity-50"
        >
          {busy === "cancel" ? "Cancelling…" : "✕ Cancel"}
        </button>
      )}
      {err && <span className="text-[11px] text-rose-600 font-mono">{err}</span>}
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
  const [mode, setMode] = useState<"reject" | "edit" | null>(null);

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

      {err && <div className="mb-2 text-xs text-red-700 font-mono">{err}</div>}

      {mode === null && (
        <div className="flex gap-2">
          <button
            type="button"
            disabled={resuming}
            onClick={() => handleAction("approve")}
            className="rounded bg-green-600 px-4 py-1.5 text-sm text-white hover:bg-green-700 disabled:opacity-50"
          >
            {resuming ? "..." : "✓ Approve"}
          </button>
          <button
            type="button"
            disabled={resuming}
            onClick={() => setMode("reject")}
            className="rounded bg-red-600 px-4 py-1.5 text-sm text-white hover:bg-red-700 disabled:opacity-50"
          >
            ✗ Reject
          </button>
          <button
            type="button"
            disabled={resuming}
            onClick={() => {
              if (!editedText && outputContent) setEditedText(outputContent);
              setMode("edit");
            }}
            className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            ✎ Edit
          </button>
        </div>
      )}

      {mode === "reject" && (
        <div>
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={3}
            placeholder="Feedback for rejection (e.g. 'rewrite the intro, too formal')..."
            className="w-full rounded border border-yellow-300 bg-white p-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-yellow-400 mb-3"
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={resuming || !feedback.trim()}
              onClick={() => handleAction("reject")}
              className="rounded bg-red-600 px-4 py-1.5 text-sm text-white hover:bg-red-700 disabled:opacity-50"
            >
              {resuming ? "..." : "Submit Reject"}
            </button>
            <button
              type="button"
              disabled={resuming}
              onClick={() => {
                setMode(null);
                setFeedback("");
              }}
              className="rounded border border-yellow-400 bg-white px-4 py-1.5 text-sm text-yellow-900 hover:bg-yellow-100"
            >
              Back
            </button>
          </div>
          {!feedback.trim() && (
            <p className="mt-1.5 text-[11px] text-yellow-700">
              Write feedback above to enable "Submit Reject"
            </p>
          )}
        </div>
      )}

      {mode === "edit" && (
        <div>
          <p className="text-xs text-yellow-800 mb-2">
            Edit the output directly, then save to continue the pipeline with your version.
          </p>
          <textarea
            value={editedText}
            onChange={(e) => setEditedText(e.target.value)}
            rows={10}
            className="w-full rounded border border-yellow-300 bg-white p-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-yellow-400 mb-3"
          />
          <div className="flex gap-2">
            <button
              type="button"
              disabled={resuming || !editedText.trim()}
              onClick={() => handleAction("edit")}
              className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {resuming ? "..." : "Save Edit"}
            </button>
            <button
              type="button"
              disabled={resuming}
              onClick={() => setMode(null)}
              className="rounded border border-yellow-400 bg-white px-4 py-1.5 text-sm text-yellow-900 hover:bg-yellow-100"
            >
              Back
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
