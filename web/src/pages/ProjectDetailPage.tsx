import { useCallback } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { client, ApiError } from "@/api/client";
import type { ProjectOut } from "@/api/types";
import { useAsync } from "@/hooks/useAsync";
import AgentsTab from "@/components/AgentsTab";
import DashboardTab from "@/components/DashboardTab";
import FilesTab from "@/components/FilesTab";
import RunsTab from "@/components/RunsTab";

type TabKey = "agents" | "runs" | "files" | "dashboard" | "chat";

const TABS: { key: TabKey; label: string }[] = [
  { key: "dashboard", label: "Dashboard" },
  { key: "agents", label: "Agents" },
  { key: "runs", label: "Runs" },
  { key: "files", label: "Files" },
  { key: "chat", label: "Chat" },
];

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = Number(id);
  const [search, setSearch] = useSearchParams();
  const nav = useNavigate();
  const raw = search.get("tab");
  const validTabs: TabKey[] = ["agents", "runs", "files", "dashboard", "chat"];
  const active: TabKey = validTabs.includes(raw as TabKey)
    ? (raw as TabKey)
    : "dashboard";

  const fetchProject = useCallback(
    () => client.get<ProjectOut>(`/projects/${projectId}`),
    [projectId]
  );
  const { data, error, loading } = useAsync(fetchProject, [projectId]);

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <div className="mb-4">
        <Link to="/" className="text-sm text-slate-500 hover:underline">
          ← All projects
        </Link>
      </div>
      {loading && <p className="text-slate-500">Loading…</p>}
      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <div className="font-medium">
            Failed to load project ({error instanceof ApiError ? error.status : "—"})
          </div>
          <div className="font-mono text-xs mt-1">{error.message}</div>
        </div>
      )}
      {data && (
        <>
          <h1 className="text-2xl font-semibold">{data.name}</h1>
          <p className="text-sm text-slate-500">
            #{data.id} · pipeline <code>{data.pipeline}</code> · status {data.status}
          </p>
          <nav className="mt-6 border-b border-slate-200 flex gap-4">
            {TABS.map((t) => {
              const isActive = t.key === active;
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() =>
                    t.key === "chat"
                      ? nav(`/projects/${projectId}/chat`)
                      : setSearch({ tab: t.key })
                  }
                  className={
                    "py-2 px-1 text-sm font-medium " +
                    (isActive
                      ? "border-b-2 border-slate-900 text-slate-900"
                      : "text-slate-500 hover:text-slate-700")
                  }
                >
                  {t.label}
                </button>
              );
            })}
          </nav>
          <div className="mt-6">
            {active === "dashboard" && <DashboardTab projectId={projectId} />}
            {active === "agents" && <AgentsTab projectId={projectId} />}
            {active === "runs" && (
              <RunsTab projectId={projectId} pipelineName={data.pipeline} />
            )}
            {active === "files" && <FilesTab projectId={projectId} />}
          </div>
        </>
      )}
    </div>
  );
}
