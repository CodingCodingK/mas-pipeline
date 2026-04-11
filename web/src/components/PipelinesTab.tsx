import { useCallback, useState } from "react";
import { client } from "@/api/client";
import type { PipelineListResponse } from "@/api/types";
import { useAsync } from "@/hooks/useAsync";
import SourceBadge from "./SourceBadge";
import FileEditor from "./FileEditor";

interface EditorTarget {
  name: string;
  isNew: boolean;
}

export default function PipelinesTab({ projectId }: { projectId: number }) {
  const fetchList = useCallback(
    () => client.get<PipelineListResponse>(`/projects/${projectId}/pipelines`),
    [projectId]
  );
  const { data, error, loading, reload } = useAsync(fetchList, [projectId]);
  const [target, setTarget] = useState<EditorTarget | null>(null);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-lg font-medium">Pipelines</h2>
          <button
            type="button"
            onClick={() => setTarget({ name: "", isNew: true })}
            className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white"
          >
            + New
          </button>
        </div>
        {loading && <p className="text-slate-500">Loading…</p>}
        {error && (
          <p className="text-sm text-red-700 font-mono">{error.message}</p>
        )}
        {data && data.items.length === 0 && (
          <p className="text-slate-500 text-sm">No pipelines.</p>
        )}
        {data && data.items.length > 0 && (
          <ul className="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
            {data.items.map((item) => (
              <li key={item.name}>
                <button
                  type="button"
                  onClick={() => setTarget({ name: item.name, isNew: false })}
                  className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-slate-50"
                >
                  <span className="font-mono text-sm">{item.name}</span>
                  <SourceBadge source={item.source} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        {target ? (
          <FileEditor
            projectId={projectId}
            kind="pipeline"
            name={target.name}
            isNew={target.isNew}
            onSaved={() => {
              setTarget(null);
              reload();
            }}
            onClose={() => setTarget(null)}
          />
        ) : (
          <p className="text-slate-500 text-sm">
            Select a pipeline to edit, or create a new one.
          </p>
        )}
      </div>
    </div>
  );
}
