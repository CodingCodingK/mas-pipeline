import { useCallback, useState } from "react";
import { client } from "@/api/client";
import type { AgentListResponse, ToolListResponse } from "@/api/types";
import { useAsync } from "@/hooks/useAsync";
import SourceBadge from "./SourceBadge";
import FileEditor from "./FileEditor";

interface EditorTarget {
  name: string;
  isNew: boolean;
  source?: string;
  readonly?: boolean;
}

export default function AgentsTab({ projectId }: { projectId: number }) {
  const fetchList = useCallback(
    () => client.get<AgentListResponse>(`/projects/${projectId}/agents`),
    [projectId]
  );
  const fetchTools = useCallback(
    () => client.get<ToolListResponse>("/tools"),
    []
  );
  const { data, error, loading, reload } = useAsync(fetchList, [projectId]);
  const { data: toolsData } = useAsync(fetchTools, []);
  const [target, setTarget] = useState<EditorTarget | null>(null);

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-lg font-medium">Agents</h2>
            <button
              type="button"
              onClick={() => setTarget({ name: "", isNew: true })}
              className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white"
            >
              + New
            </button>
          </div>
          <p className="mb-3 text-xs text-slate-500">
            Showing only system roles (assistant / coordinator), agents
            overridden by this project, and agents referenced by this
            project's pipeline. Other global roles are hidden.
          </p>
          {loading && <p className="text-slate-500">Loading…</p>}
          {error && (
            <p className="text-sm text-red-700 font-mono">{error.message}</p>
          )}
          {data && data.items.length === 0 && (
            <p className="text-slate-500 text-sm">No agents.</p>
          )}
          {data && data.items.length > 0 && (
            <ul className="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
              {data.items.map((item) => (
                <li key={item.name}>
                  <button
                    type="button"
                    onClick={() =>
                      setTarget({
                        name: item.name,
                        isNew: false,
                        source: item.source,
                        readonly: item.readonly,
                      })
                    }
                    className="w-full px-3 py-2.5 text-left hover:bg-slate-50"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-sm">
                        {item.readonly && (
                          <span className="mr-1.5" title="read-only">🔒</span>
                        )}
                        {item.name}
                      </span>
                      <SourceBadge source={item.source} />
                    </div>
                    {(item.description || item.model_tier || item.tools.length > 0) && (
                      <div className="mt-1 flex items-center gap-3 text-xs text-slate-500">
                        {item.description && (
                          <span className="truncate max-w-[200px]">{item.description}</span>
                        )}
                        {item.model_tier && (
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono">
                            {item.model_tier}
                          </span>
                        )}
                        {item.tools.length > 0 && (
                          <span className="text-slate-400">
                            {item.tools.length} tool{item.tools.length > 1 ? "s" : ""}
                          </span>
                        )}
                      </div>
                    )}
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
              kind="agent"
              name={target.name}
              isNew={target.isNew}
              source={target.source as any}
              readonly={target.readonly}
              onSaved={() => {
                setTarget(null);
                reload();
              }}
              onClose={() => setTarget(null)}
            />
          ) : (
            <p className="text-slate-500 text-sm">
              Select an agent to edit, or create a new one.
            </p>
          )}
        </div>
      </div>

      {toolsData && toolsData.items.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-slate-700 mb-2">
            Available Tools
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {toolsData.items.map((t) => (
              <div
                key={t.name}
                className="rounded border border-slate-200 bg-white px-3 py-2"
              >
                <div className="font-mono text-sm">{t.name}</div>
                <div className="text-xs text-slate-500 mt-0.5 line-clamp-2">
                  {t.description}
                </div>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-400">
            Add tool names to the <code>tools</code> list in agent frontmatter to enable them.
          </p>
        </div>
      )}
    </div>
  );
}
