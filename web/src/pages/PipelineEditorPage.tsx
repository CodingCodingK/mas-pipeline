import { useCallback, useState, useEffect, lazy, Suspense } from "react";
import { Link } from "react-router-dom";
import { client, ApiError } from "@/api/client";
import type { PipelineListResponse, PipelineReadResponse } from "@/api/types";
import { useAsync } from "@/hooks/useAsync";

const MonacoEditor = lazy(() => import("@monaco-editor/react"));

export default function PipelineEditorPage() {
  const fetchList = useCallback(
    () => client.get<PipelineListResponse>("/pipelines"),
    []
  );
  const { data, error, loading, reload } = useAsync(fetchList, []);

  const [selected, setSelected] = useState<string | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [initialContent, setInitialContent] = useState("");
  const [cloneOpen, setCloneOpen] = useState(false);
  const [cloning, setCloning] = useState(false);

  const handleClone = async (sourceName: string) => {
    setCloning(true);
    try {
      const resp = await client.get<PipelineReadResponse>(
        `/pipelines/${sourceName}`
      );
      setInitialContent(resp.content);
      setSelected(null);
      setIsNew(true);
    } catch {
      // ignore
    } finally {
      setCloning(false);
      setCloneOpen(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <div className="mb-4">
        <Link to="/" className="text-sm text-slate-500 hover:underline">
          &larr; Projects
        </Link>
      </div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-2xl font-semibold">Pipeline Editor</h1>
        <div className="flex items-center gap-2">
          <div className="relative">
            <button
              type="button"
              disabled={cloning || !data?.items.length}
              onClick={() => setCloneOpen((v) => !v)}
              className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {cloning ? "Cloning..." : "Clone from..."}
            </button>
            {cloneOpen && data?.items && (
              <ul className="absolute right-0 top-full mt-1 z-10 w-56 rounded border border-slate-200 bg-white shadow-lg py-1 max-h-60 overflow-auto">
                {data.items.map((item) => (
                  <li key={item.name}>
                    <button
                      type="button"
                      onClick={() => handleClone(item.name)}
                      className="w-full text-left px-3 py-1.5 text-sm font-mono hover:bg-slate-50"
                    >
                      {item.name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <button
            type="button"
            onClick={() => {
              setSelected(null);
              setIsNew(true);
              setInitialContent("");
            }}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white"
          >
            + New Pipeline
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div>
          {loading && <p className="text-slate-500">Loading...</p>}
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
                    onClick={() => {
                      setSelected(item.name);
                      setIsNew(false);
                    }}
                    className={`w-full flex items-center justify-between px-3 py-2 text-left hover:bg-slate-50 ${
                      selected === item.name && !isNew
                        ? "bg-slate-100"
                        : ""
                    }`}
                  >
                    <span className="font-mono text-sm">{item.name}</span>
                    <span className="text-xs text-slate-400">
                      {item.source}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="lg:col-span-2">
          {selected || isNew ? (
            <EditorPanel
              name={selected ?? ""}
              isNew={isNew}
              initialContent={isNew ? initialContent : undefined}
              onSaved={() => {
                setSelected(null);
                setIsNew(false);
                setInitialContent("");
                reload();
              }}
              onClose={() => {
                setSelected(null);
                setIsNew(false);
                setInitialContent("");
              }}
            />
          ) : (
            <p className="text-slate-500 text-sm">
              Select a pipeline to edit, or create a new one.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function EditorPanel({
  name,
  isNew,
  initialContent,
  onSaved,
  onClose,
}: {
  name: string;
  isNew: boolean;
  initialContent?: string;
  onSaved: () => void;
  onClose: () => void;
}) {
  const [content, setContent] = useState("");
  const [nameState, setNameState] = useState(name);
  const [loadingContent, setLoadingContent] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    if (isNew) {
      setContent(initialContent ?? "");
      setNameState("");
      setLoadingContent(false);
      return () => { alive = false; };
    }
    setLoadingContent(true);
    setNameState(name);
    client.get<PipelineReadResponse>(`/pipelines/${name}`).then(
      (resp) => {
        if (!alive) return;
        setContent(resp.content);
        setLoadingContent(false);
      },
      (err: unknown) => {
        if (!alive) return;
        setError(err instanceof Error ? err : new Error(String(err)));
        setLoadingContent(false);
      }
    );
    return () => { alive = false; };
  }, [name, isNew]);

  const save = async () => {
    if (!nameState.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await client.put(`/pipelines/${nameState.trim()}`, { content });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!confirm(`Delete pipeline "${nameState}"?`)) return;
    setSaving(true);
    setError(null);
    try {
      await client.del(`/pipelines/${nameState}`);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setSaving(false);
    }
  };

  if (loadingContent) return <p className="text-slate-500">Loading...</p>;

  return (
    <div className="rounded border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase text-slate-500">pipeline</span>
          {isNew ? (
            <input
              type="text"
              placeholder="new-pipeline-name"
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

      <div className="rounded border border-slate-300 overflow-hidden">
        <Suspense
          fallback={
            <div className="h-96 bg-slate-50 flex items-center justify-center text-sm text-slate-400">
              Loading editor...
            </div>
          }
        >
          <MonacoEditor
            height="400px"
            language="yaml"
            value={content}
            onChange={(v) => setContent(v ?? "")}
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

      {error && (
        <div className="mt-3 rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          <div className="font-medium">
            {error instanceof ApiError ? `Error ${(error as ApiError).status}` : "Error"}
          </div>
          <div className="font-mono">{error.message}</div>
        </div>
      )}

      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={saving || !nameState.trim()}
          onClick={save}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          {saving ? "Saving..." : "Save"}
        </button>
        {!isNew && (
          <button
            type="button"
            disabled={saving}
            onClick={remove}
            className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-700 disabled:opacity-50"
          >
            Delete
          </button>
        )}
      </div>
    </div>
  );
}
