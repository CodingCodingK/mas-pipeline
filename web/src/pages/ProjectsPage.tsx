import { useCallback } from "react";
import { Link } from "react-router-dom";
import { client, ApiError } from "@/api/client";
import type { ProjectList, ProjectOut } from "@/api/types";
import { useAsync } from "@/hooks/useAsync";

export default function ProjectsPage() {
  const fetchProjects = useCallback(
    () => client.get<ProjectList>("/projects"),
    []
  );
  const { data, error, loading } = useAsync(fetchProjects, []);

  return (
    <div>
      <h1 className="text-2xl font-semibold mb-4">Projects</h1>
      {loading && <p className="text-slate-500">Loading…</p>}
      {error && <ErrorBlock error={error} />}
      {data && data.items.length === 0 && (
        <p className="text-slate-500">No projects found.</p>
      )}
      {data && data.items.length > 0 && (
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {data.items.map((p) => (
            <ProjectCard key={p.id} project={p} />
          ))}
        </ul>
      )}
    </div>
  );
}

function ProjectCard({ project }: { project: ProjectOut }) {
  return (
    <li className="rounded-lg border border-slate-200 bg-white p-4 hover:border-slate-400 transition">
      <Link to={`/projects/${project.id}`} className="block">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">{project.name}</h2>
          <span className="text-xs text-slate-500">#{project.id}</span>
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
