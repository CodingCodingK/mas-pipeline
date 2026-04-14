import { useEffect, useState } from "react";
import { X, Loader2 } from "lucide-react";
import { client } from "@/api/client";
import type { AgentRunDetail } from "@/api/types";

interface Props {
  agentRunId: number | null;
  onClose: () => void;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const rem = Math.round(seconds - mins * 60);
  return `${mins}m ${rem}s`;
}

function formatTokens(n: number): string {
  if (n < 1000) return `${n}`;
  return `${(n / 1000).toFixed(1)}k`;
}

function StatBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
      <span className="text-slate-400">{label}</span>
      <span>{value}</span>
    </span>
  );
}

function MessageRow({ msg, index }: { msg: Record<string, unknown>; index: number }) {
  const role = String(msg.role ?? "unknown");
  const content = msg.content;
  const toolCalls = msg.tool_calls as Array<Record<string, unknown>> | undefined;
  const toolCallId = msg.tool_call_id as string | undefined;

  const bg =
    role === "user"
      ? "bg-blue-50 border-blue-200"
      : role === "assistant"
      ? "bg-white border-slate-200"
      : role === "tool"
      ? "bg-amber-50 border-amber-200"
      : role === "system"
      ? "bg-slate-50 border-slate-200"
      : "bg-slate-50 border-slate-200";

  const contentText =
    typeof content === "string"
      ? content
      : content == null
      ? ""
      : JSON.stringify(content, null, 2);

  return (
    <div className={`rounded border ${bg} px-3 py-2 text-xs`}>
      <div className="mb-1 flex items-center gap-2 text-[10px] uppercase tracking-wide text-slate-500">
        <span className="font-semibold">{role}</span>
        <span className="text-slate-300">#{index}</span>
        {toolCallId && <span className="font-mono text-slate-400">tc={toolCallId}</span>}
      </div>
      {contentText && (
        <pre className="whitespace-pre-wrap break-words text-slate-800 leading-relaxed font-sans">
          {contentText}
        </pre>
      )}
      {toolCalls && toolCalls.length > 0 && (
        <div className="mt-1 space-y-1">
          {toolCalls.map((tc, i) => {
            const fn = (tc.function as Record<string, unknown>) ?? {};
            return (
              <div key={i} className="rounded bg-slate-50 px-2 py-1 font-mono text-[10px]">
                <span className="text-slate-400">tool:</span>{" "}
                <span className="font-semibold">{String(fn.name ?? "?")}</span>
                <pre className="mt-0.5 whitespace-pre-wrap text-slate-600">
                  {String(fn.arguments ?? "")}
                </pre>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function AgentRunDetailDrawer({ agentRunId, onClose }: Props) {
  const [detail, setDetail] = useState<AgentRunDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (agentRunId == null) {
      setDetail(null);
      setError(null);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    setDetail(null);
    (async () => {
      try {
        const res = await client.get<AgentRunDetail>(`/agent-runs/${agentRunId}`);
        if (ctrl.signal.aborted) return;
        setDetail(res);
      } catch (err: unknown) {
        if (ctrl.signal.aborted) return;
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      } finally {
        if (!ctrl.signal.aborted) setLoading(false);
      }
    })();
    return () => ctrl.abort();
  }, [agentRunId]);

  useEffect(() => {
    if (agentRunId == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [agentRunId, onClose]);

  if (agentRunId == null) return null;

  const statusColor =
    detail?.status === "completed"
      ? "text-green-600"
      : detail?.status === "failed"
      ? "text-red-600"
      : "text-slate-600";

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-slate-900/20"
        onClick={onClose}
        aria-hidden
      />
      <aside
        className="fixed right-0 top-0 z-50 h-full w-[640px] max-w-[92vw] flex flex-col border-l border-slate-200 bg-white shadow-2xl"
        role="dialog"
        aria-modal="true"
      >
        <header className="flex items-center gap-3 border-b border-slate-200 px-4 py-3">
          <div className="flex-1 min-w-0">
            {loading && (
              <div className="flex items-center gap-2 text-sm text-slate-500">
                <Loader2 className="w-4 h-4 animate-spin" />
                Loading agent run #{agentRunId}…
              </div>
            )}
            {error && (
              <div className="text-sm text-red-600">
                Failed to load agent run #{agentRunId}: {error}
              </div>
            )}
            {detail && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-slate-900">
                  {detail.role}
                </span>
                <span className={`text-xs font-medium ${statusColor}`}>
                  {detail.status}
                </span>
                <span className="text-[11px] text-slate-400">#{detail.id}</span>
                <div className="ml-2 flex gap-1">
                  <StatBadge label="tools" value={String(detail.tool_use_count)} />
                  <StatBadge label="tokens" value={formatTokens(detail.total_tokens)} />
                  <StatBadge label="time" value={formatDuration(detail.duration_ms)} />
                </div>
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        {detail && (
          <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-4">
            {detail.description && (
              <section>
                <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                  Task
                </h3>
                <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs whitespace-pre-wrap text-slate-800">
                  {detail.description}
                </div>
              </section>
            )}

            <section>
              <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                Transcript ({detail.messages.length} messages)
              </h3>
              <div className="space-y-2">
                {detail.messages.length === 0 && (
                  <div className="text-xs text-slate-400 italic">
                    No transcript recorded.
                  </div>
                )}
                {detail.messages.map((m, i) => (
                  <MessageRow key={i} msg={m} index={i} />
                ))}
              </div>
            </section>

            {detail.result && (
              <section>
                <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                  Result
                </h3>
                <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs whitespace-pre-wrap text-slate-800">
                  {detail.result}
                </div>
              </section>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
