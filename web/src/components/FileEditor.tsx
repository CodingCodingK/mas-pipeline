import { useState, useCallback, useEffect } from "react";
import { client, ApiError } from "@/api/client";
import type {
  AgentReadResponse,
  PipelineReadResponse,
  InUseErrorBody,
} from "@/api/types";

type Kind = "agent" | "pipeline";

interface Props {
  projectId: number;
  kind: Kind;
  name: string;
  isNew: boolean;
  onSaved: () => void;
  onClose: () => void;
}

function pathFor(projectId: number, kind: Kind, name: string): string {
  const base = kind === "agent" ? "agents" : "pipelines";
  return `/projects/${projectId}/${base}/${name}`;
}

function globalPathFor(kind: Kind, name: string): string {
  const base = kind === "agent" ? "agents" : "pipelines";
  return `/${base}/${name}`;
}

export default function FileEditor({
  projectId,
  kind,
  name,
  isNew,
  onSaved,
  onClose,
}: Props) {
  const [content, setContent] = useState<string>("");
  const [nameState, setNameState] = useState<string>(name);
  const [loading, setLoading] = useState<boolean>(!isNew);
  const [saving, setSaving] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const [references, setReferences] = useState<InUseErrorBody["references"] | null>(
    null
  );

  useEffect(() => {
    let alive = true;
    setError(null);
    setReferences(null);
    if (isNew) {
      setContent("");
      setLoading(false);
      return () => {
        alive = false;
      };
    }
    setLoading(true);
    const path = pathFor(projectId, kind, name);
    (kind === "agent"
      ? client.get<AgentReadResponse>(path)
      : client.get<PipelineReadResponse>(path)
    ).then(
      (resp) => {
        if (!alive) return;
        setContent(resp.content);
        setLoading(false);
      },
      (err: unknown) => {
        if (!alive) return;
        setError(err instanceof Error ? err : new Error(String(err)));
        setLoading(false);
      }
    );
    return () => {
      alive = false;
    };
  }, [projectId, kind, name, isNew]);

  const handleTabKey = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key !== "Tab") return;
      e.preventDefault();
      const el = e.currentTarget;
      const start = el.selectionStart;
      const end = el.selectionEnd;
      const next = content.slice(0, start) + "  " + content.slice(end);
      setContent(next);
      requestAnimationFrame(() => {
        el.selectionStart = el.selectionEnd = start + 2;
      });
    },
    [content]
  );

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    setReferences(null);
    try {
      await client.put(pathFor(projectId, kind, nameState), { content });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setSaving(false);
    }
  }, [projectId, kind, nameState, content, onSaved]);

  const remove = useCallback(async () => {
    setSaving(true);
    setError(null);
    setReferences(null);
    try {
      await client.del(pathFor(projectId, kind, nameState));
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const body = err.body as InUseErrorBody;
        if (body && Array.isArray(body.references)) {
          setReferences(body.references);
        }
      }
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setSaving(false);
    }
  }, [projectId, kind, nameState, onSaved]);

  const removeGlobal = useCallback(async () => {
    setSaving(true);
    setError(null);
    setReferences(null);
    try {
      await client.del(globalPathFor(kind, nameState));
      onSaved();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const body = err.body as InUseErrorBody;
        if (body && Array.isArray(body.references)) {
          setReferences(body.references);
        }
      }
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setSaving(false);
    }
  }, [kind, nameState, onSaved]);

  if (loading) return <p className="text-slate-500">Loading…</p>;

  return (
    <div className="rounded border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase text-slate-500">{kind}</span>
          {isNew ? (
            <input
              type="text"
              placeholder="new-name"
              value={nameState}
              onChange={(e) => setNameState(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-sm font-mono"
            />
          ) : (
            <span className="font-mono text-sm">{nameState}</span>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-slate-500 hover:text-slate-700"
        >
          Close
        </button>
      </div>
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        onKeyDown={handleTabKey}
        spellCheck={false}
        className="w-full h-80 rounded border border-slate-300 bg-slate-50 p-3 font-mono text-sm"
      />
      {error && (
        <div className="mt-3 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          <div className="font-medium">
            {error instanceof ApiError ? `Error ${error.status}` : "Error"}
          </div>
          <div className="font-mono">{error.message}</div>
          {references && references.length > 0 && (
            <ul className="mt-1 list-disc list-inside">
              {references.map((r, i) => (
                <li key={i}>
                  pipeline <code>{r.pipeline}</code>
                  {r.project_id === null
                    ? " (global)"
                    : ` (project ${r.project_id})`}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={saving || nameState.length === 0}
          onClick={save}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save (project layer)"}
        </button>
        {!isNew && (
          <button
            type="button"
            disabled={saving}
            onClick={remove}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 disabled:opacity-50"
          >
            Delete project override
          </button>
        )}
        {!isNew && (
          <button
            type="button"
            disabled={saving}
            onClick={removeGlobal}
            className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-700 disabled:opacity-50"
          >
            Delete global
          </button>
        )}
      </div>
    </div>
  );
}
