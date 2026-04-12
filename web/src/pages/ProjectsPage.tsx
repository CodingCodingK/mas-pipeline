import { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { client, ApiError } from "@/api/client";
import type { ProjectList, ProjectOut, PipelineListResponse } from "@/api/types";
import { useAsync } from "@/hooks/useAsync";

export default function ProjectsPage() {
  const fetchProjects = useCallback(
    () => client.get<ProjectList>("/projects"),
    []
  );
  const fetchPipelines = useCallback(
    () => client.get<PipelineListResponse>("/pipelines"),
    []
  );
  const { data, error, loading, reload } = useAsync(fetchProjects, []);
  const { data: plData } = useAsync(fetchPipelines, []);

  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [pipeline, setPipeline] = useState("");
  const [creating, setCreating] = useState(false);

  const pipelineNames = plData?.items.map((p) => p.name) ?? [];

  const handleCreate = async () => {
    if (!name.trim() || !pipeline) return;
    setCreating(true);
    try {
      await client.post("/projects", {
        name: name.trim(),
        description: desc.trim() || null,
        pipeline,
      });
      setName("");
      setDesc("");
      setPipeline("");
      setShowCreate(false);
      reload();
    } catch {
      // ignore
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, p: ProjectOut) => {
    e.preventDefault();
    e.stopPropagation();
    if (!confirm(`Delete project "${p.name}"?`)) return;
    try {
      await client.del(`/projects/${p.id}`);
      reload();
    } catch {
      // ignore
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">Projects</h1>
        <div className="flex items-center gap-2">
          <Link
            to="/pipelines"
            className="rounded border border-slate-300 px-4 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            Pipeline Editor
          </Link>
          <button
            type="button"
            onClick={() => setShowCreate((v) => !v)}
            className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700"
          >
            {showCreate ? "Cancel" : "+ New Project"}
          </button>
        </div>
      </div>

      {showCreate && (
        <div className="mb-6 rounded-lg border border-slate-200 bg-white p-4 space-y-3">
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Name
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Project"
              className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Description
            </label>
            <input
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
              placeholder="Optional description"
              className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Pipeline
            </label>
            <select
              value={pipeline}
              onChange={(e) => setPipeline(e.target.value)}
              className="w-full rounded border border-slate-300 px-3 py-1.5 text-sm"
            >
              <option value="">-- select pipeline --</option>
              {pipelineNames.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            onClick={handleCreate}
            disabled={creating || !name.trim() || !pipeline}
            className="rounded bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {creating ? "Creating..." : "Create"}
          </button>
        </div>
      )}

      {loading && <p className="text-slate-500">Loading…</p>}
      {error && <ErrorBlock error={error} />}
      {data && data.items.length === 0 && !showCreate && (
        <p className="text-slate-500">No projects found.</p>
      )}
      {data && data.items.length > 0 && (
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {data.items.map((p) => (
            <ProjectCard key={p.id} project={p} onDelete={handleDelete} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ProjectCard({
  project,
  onDelete,
}: {
  project: ProjectOut;
  onDelete: (e: React.MouseEvent, p: ProjectOut) => void;
}) {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4 hover:border-slate-400 transition group">
      <Link to={`/projects/${project.id}`} className="block">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">{project.name}</h2>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">#{project.id}</span>
            <button
              type="button"
              onClick={(e) => onDelete(e, project)}
              className="hidden group-hover:inline-block text-xs text-slate-400 hover:text-red-500 px-1"
              title="Delete project"
            >
              ✕
            </button>
          </div>
        </div>
        {project.description && (
          <p className="text-sm text-slate-600 mt-1">{project.description}</p>
        )}
        <div className="mt-3 flex gap-2 text-xs">
          <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-700">
            {project.pipeline}
          </span>
          <span className="rounded bg-emerald-100 px-2 py-0.5 text-emerald-800">
            {project.status}
          </span>
        </div>
      </Link>
    </li>
  );
}

function ErrorBlock({ error }: { error: Error }) {
  const status = error instanceof ApiError ? error.status : "—";
  return (
    <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <div className="font-medium">Failed to load projects ({status})</div>
      <div className="font-mono text-xs mt-1">{error.message}</div>
    </div>
  );
}
