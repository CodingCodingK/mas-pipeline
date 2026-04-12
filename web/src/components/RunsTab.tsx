import { useCallback, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { client } from "@/api/client";
import type { RunListResponse } from "@/api/types";
import { useAsync } from "@/hooks/useAsync";

const STATUS_COLORS: Record<string, string> = {
  completed: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  running: "bg-blue-100 text-blue-800",
  pending: "bg-slate-100 text-slate-600",
  paused: "bg-yellow-100 text-yellow-800",
  cancelled: "bg-slate-100 text-slate-500",
};

export default function RunsTab({
  projectId,
  pipelineName,
}: {
  projectId: number;
  pipelineName: string;
}) {
  const navigate = useNavigate();
  const fetchRuns = useCallback(
    () => client.get<RunListResponse>(`/projects/${projectId}/runs`),
    [projectId]
  );
  const { data: runsData, error: runsError, loading: runsLoading } = useAsync(
    fetchRuns,
    [projectId]
  );

  const [inputText, setInputText] = useState<string>("");

  const start = useCallback(() => {
    navigate(`/projects/${projectId}/runs/pending`, {
      state: {
        liveStream: true,
        pipelineName,
        inputText,
      },
    });
  }, [projectId, pipelineName, inputText, navigate]);

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-lg font-medium mb-3">Start a pipeline run</h2>
        <div className="space-y-3 max-w-xl rounded border border-slate-200 bg-white p-4">
          <div>
            <label className="block text-xs text-slate-500 mb-1">
              Pipeline
            </label>
            <div className="rounded border border-slate-200 bg-slate-50 px-2 py-1.5 text-sm font-mono text-slate-700">
              {pipelineName}
            </div>
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
          <button
            type="button"
            onClick={start}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white"
          >
            Start
          </button>
        </div>
      </div>

      <div>
        <h2 className="text-lg font-medium mb-3">Run History</h2>
        {runsLoading && <p className="text-slate-500">Loading runs…</p>}
        {runsError && (
          <p className="text-sm text-red-700 font-mono">{runsError.message}</p>
        )}
        {runsData && runsData.items.length === 0 && (
          <p className="text-slate-500 text-sm">No runs yet.</p>
        )}
        {runsData && runsData.items.length > 0 && (
          <div className="rounded border border-slate-200 bg-white overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50 text-left">
                  <th className="px-3 py-2 font-medium text-slate-600">Run ID</th>
                  <th className="px-3 py-2 font-medium text-slate-600">Pipeline</th>
                  <th className="px-3 py-2 font-medium text-slate-600">Status</th>
                  <th className="px-3 py-2 font-medium text-slate-600">Started</th>
                  <th className="px-3 py-2 font-medium text-slate-600">Finished</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {runsData.items.map((r) => (
                  <tr key={r.run_id} className="hover:bg-slate-50">
                    <td className="px-3 py-2 font-mono text-xs">
                      <Link
                        to={`/projects/${projectId}/runs/${r.run_id}`}
                        className="text-blue-600 hover:underline"
                      >
                        {r.run_id.slice(0, 8)}…
                      </Link>
                    </td>
                    <td className="px-3 py-2">{r.pipeline ?? "—"}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                          STATUS_COLORS[r.status] ?? "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {r.status}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {r.started_at ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-xs text-slate-500">
                      {r.finished_at ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
