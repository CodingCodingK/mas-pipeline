import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { client, ApiError } from "@/api/client";
import type { PipelineListResponse, TriggerRunResponse } from "@/api/types";
import { useAsync } from "@/hooks/useAsync";

export default function RunsTab({ projectId }: { projectId: number }) {
  const navigate = useNavigate();
  const fetchPipelines = useCallback(
    () => client.get<PipelineListResponse>(`/projects/${projectId}/pipelines`),
    [projectId]
  );
  const { data, error, loading } = useAsync(fetchPipelines, [projectId]);

  const [pipelineName, setPipelineName] = useState<string>("");
  const [inputText, setInputText] = useState<string>("");
  const [triggering, setTriggering] = useState<boolean>(false);
  const [triggerError, setTriggerError] = useState<Error | null>(null);

  const trigger = useCallback(async () => {
    if (!pipelineName) return;
    setTriggering(true);
    setTriggerError(null);
    try {
      const resp = await client.post<TriggerRunResponse>(
        `/projects/${projectId}/pipelines/${pipelineName}/runs`,
        { input: inputText ? { text: inputText } : {} }
      );
      navigate(`/projects/${projectId}/runs/${resp.run_id}`, {
        state: { liveStream: false },
      });
    } catch (err) {
      setTriggerError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setTriggering(false);
    }
  }, [projectId, pipelineName, inputText, navigate]);

  const triggerStream = useCallback(() => {
    if (!pipelineName) return;
    navigate(`/projects/${projectId}/runs/pending`, {
      state: {
        liveStream: true,
        pipelineName,
        inputText,
      },
    });
  }, [projectId, pipelineName, inputText, navigate]);

  return (
    <div>
      <h2 className="text-lg font-medium mb-3">Trigger a pipeline run</h2>
      {loading && <p className="text-slate-500">Loading pipelines…</p>}
      {error && (
        <p className="text-sm text-red-700 font-mono">{error.message}</p>
      )}
      {data && (
        <div className="space-y-3 max-w-xl rounded border border-slate-200 bg-white p-4">
          <div>
            <label className="block text-xs text-slate-500 mb-1">
              Pipeline
            </label>
            <select
              value={pipelineName}
              onChange={(e) => setPipelineName(e.target.value)}
              className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
            >
              <option value="">-- select --</option>
              {data.items.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} ({p.source})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">
              User input
            </label>
            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              rows={4}
              className="w-full rounded border border-slate-300 p-2 font-mono text-sm"
              placeholder="Free-form text fed to the pipeline as input.text"
            />
          </div>
          {triggerError && (
            <div className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800 font-mono">
              {triggerError instanceof ApiError
                ? `Error ${triggerError.status}: `
                : ""}
              {triggerError.message}
            </div>
          )}
          <div className="flex gap-2">
            <button
              type="button"
              disabled={triggering || !pipelineName}
              onClick={trigger}
              className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {triggering ? "Triggering…" : "Trigger (fire & forget)"}
            </button>
            <button
              type="button"
              disabled={triggering || !pipelineName}
              onClick={triggerStream}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 disabled:opacity-50"
            >
              Trigger + stream
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
