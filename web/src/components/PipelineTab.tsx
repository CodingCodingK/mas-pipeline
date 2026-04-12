import { useCallback, useState, lazy, Suspense } from "react";
import { client } from "@/api/client";
import type { AgentListResponse, PipelineReadResponse } from "@/api/types";
import { useAsync } from "@/hooks/useAsync";

const MonacoEditor = lazy(() => import("@monaco-editor/react"));
const PipelineGraph = lazy(() => import("@/components/PipelineGraph"));

export default function PipelineTab({ pipelineName }: { pipelineName: string }) {
  const fetchPipeline = useCallback(
    () => client.get<PipelineReadResponse>(`/pipelines/${pipelineName}`),
    [pipelineName]
  );
  const { data, error, loading } = useAsync(fetchPipeline, [pipelineName]);

  const fetchAgents = useCallback(
    () => client.get<AgentListResponse>("/agents"),
    []
  );
  const { data: agentsData } = useAsync(fetchAgents, []);
  const agents = agentsData?.items.map((a) => ({ name: a.name, description: a.description })) ?? [];

  const [content, setContent] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const yaml = content ?? data?.content ?? "";

  const handleChange = (v: string) => {
    setContent(v);
    setSaved(false);
  };

  const save = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await client.put(`/pipelines/${pipelineName}`, { content: yaml });
      setSaved(true);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <p className="text-slate-500">Loading pipeline...</p>;
  if (error) return <p className="text-sm text-red-700 font-mono">{error.message}</p>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-slate-700">
          Pipeline: <code className="text-slate-900">{pipelineName}</code>
          {data && <span className="ml-2 text-xs text-slate-400">({data.source})</span>}
        </h2>
        <div className="flex items-center gap-2">
          {saved && <span className="text-xs text-green-600">Saved</span>}
          {saveError && <span className="text-xs text-red-600">{saveError}</span>}
          <button
            type="button"
            disabled={saving || content === null}
            onClick={save}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>

      <div className="rounded border border-slate-300 overflow-hidden">
        <Suspense
          fallback={
            <div className="h-80 bg-slate-50 flex items-center justify-center text-sm text-slate-400">
              Loading editor...
            </div>
          }
        >
          <MonacoEditor
            height="320px"
            language="yaml"
            value={yaml}
            onChange={(v) => handleChange(v ?? "")}
            theme="vs-light"
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              lineNumbers: "on",
              wordWrap: "on",
              tabSize: 2,
              scrollBeyondLastLine: false,
              renderLineHighlight: "line",
              padding: { top: 8 },
            }}
          />
        </Suspense>
      </div>

      <div className="rounded border border-slate-200 overflow-hidden" style={{ height: 480 }}>
        <Suspense
          fallback={
            <div className="h-full flex items-center justify-center text-sm text-slate-400">
              Loading graph...
            </div>
          }
        >
          <PipelineGraph yamlContent={yaml} onChange={handleChange} agents={agents} />
        </Suspense>
      </div>
    </div>
  );
}
