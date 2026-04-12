import { useCallback, useRef, useState, type DragEvent } from "react";
import { client } from "@/api/client";
import { fetchEventStream } from "@/api/sse";
import { useAsync } from "@/hooks/useAsync";

interface FileOut {
  id: number;
  project_id: number;
  filename: string;
  file_type: string;
  file_size: number | null;
  parsed: boolean;
  chunk_count: number;
  created_at: string | null;
}

interface ChunkOut {
  chunk_index: number;
  content: string;
  metadata: Record<string, unknown>;
}

interface ChunkPage {
  items: ChunkOut[];
  total: number;
  offset: number;
  limit: number;
}

interface KnowledgeStatus {
  file_count: number;
  parsed_count: number;
  total_chunks: number;
}

interface IngestProgress {
  event: string;
  [key: string]: unknown;
}

function formatSize(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function FilesTab({ projectId }: { projectId: number }) {
  const fetchFiles = useCallback(
    () => client.get<FileOut[]>(`/projects/${projectId}/files`),
    [projectId]
  );
  const fetchStatus = useCallback(
    () => client.get<KnowledgeStatus>(`/projects/${projectId}/knowledge/status`),
    [projectId]
  );
  const { data: files, loading, error, reload } = useAsync(fetchFiles, [projectId]);
  const { data: status, reload: reloadStatus } = useAsync(fetchStatus, [projectId]);

  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Ingest state
  const [ingestingId, setIngestingId] = useState<number | null>(null);
  const [ingestProgress, setIngestProgress] = useState<IngestProgress[]>([]);
  const [ingestDone, setIngestDone] = useState(false);

  // Chunk preview state
  const [chunkFileId, setChunkFileId] = useState<number | null>(null);
  const [chunks, setChunks] = useState<ChunkOut[]>([]);
  const [chunkTotal, setChunkTotal] = useState(0);
  const [chunkOffset, setChunkOffset] = useState(0);
  const chunkLimit = 10;

  const doUpload = useCallback(
    async (fileList: FileList | File[]) => {
      setUploading(true);
      setUploadError(null);
      try {
        for (const file of fileList) {
          const form = new FormData();
          form.append("file", file);
          const url = `/projects/${projectId}/files`;
          const base = (import.meta.env.VITE_API_BASE as string) || "/api";
          const key = (import.meta.env.VITE_API_KEY as string) || "";
          const headers: Record<string, string> = {};
          if (key) headers["X-API-Key"] = key;
          const resp = await fetch(base.replace(/\/$/, "") + url, {
            method: "POST",
            headers,
            body: form,
          });
          if (!resp.ok) {
            const body = await resp.text();
            throw new Error(`Upload failed (${resp.status}): ${body}`);
          }
        }
        reload();
        reloadStatus();
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : String(err));
      } finally {
        setUploading(false);
      }
    },
    [projectId, reload, reloadStatus]
  );

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      if (e.dataTransfer.files.length > 0) {
        doUpload(e.dataTransfer.files);
      }
    },
    [doUpload]
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      if (e.target.files && e.target.files.length > 0) {
        doUpload(e.target.files);
        e.target.value = "";
      }
    },
    [doUpload]
  );

  const handleDelete = useCallback(
    async (fileId: number) => {
      try {
        await client.del(`/projects/${projectId}/files/${fileId}`);
        reload();
        reloadStatus();
        if (chunkFileId === fileId) {
          setChunkFileId(null);
          setChunks([]);
        }
      } catch {
        // ignore
      }
    },
    [projectId, reload, reloadStatus, chunkFileId]
  );

  const handleIngest = useCallback(
    async (fileId: number) => {
      setIngestingId(fileId);
      setIngestProgress([]);
      setIngestDone(false);
      try {
        const res = await client.post<{ job_id: string }>(
          `/projects/${projectId}/files/${fileId}/ingest`
        );
        const ctrl = new AbortController();
        fetchEventStream(`/jobs/${res.job_id}/stream`, {
          signal: ctrl.signal,
          method: "GET",
          onEvent: (evt) => {
            try {
              const parsed = JSON.parse(evt.data) as IngestProgress;
              setIngestProgress((prev) => [...prev, parsed]);
              if (parsed.event === "done" || parsed.event === "failed") {
                setIngestDone(true);
                reload();
                reloadStatus();
              }
            } catch {
              // ignore
            }
          },
        }).catch(() => {
          setIngestDone(true);
        });
      } catch (err) {
        setIngestProgress([{ event: "failed", error: String(err) }]);
        setIngestDone(true);
      }
    },
    [projectId, reload, reloadStatus]
  );

  const loadChunks = useCallback(
    async (fileId: number, offset: number) => {
      setChunkFileId(fileId);
      setChunkOffset(offset);
      try {
        const res = await client.get<ChunkPage>(
          `/projects/${projectId}/files/${fileId}/chunks?offset=${offset}&limit=${chunkLimit}`
        );
        setChunks(res.items);
        setChunkTotal(res.total);
      } catch {
        setChunks([]);
        setChunkTotal(0);
      }
    },
    [projectId]
  );

  const lastProgress = ingestProgress[ingestProgress.length - 1];

  return (
    <div className="space-y-6">
      {/* Status bar */}
      {status && (
        <div className="flex gap-6 text-sm text-slate-600">
          <span>{status.file_count} files</span>
          <span>{status.parsed_count} parsed</span>
          <span>{status.total_chunks} chunks</span>
        </div>
      )}

      {/* Upload zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`rounded-lg border-2 border-dashed p-8 text-center transition-colors ${
          dragOver
            ? "border-blue-400 bg-blue-50"
            : "border-slate-300 bg-white hover:border-slate-400"
        }`}
      >
        <p className="text-sm text-slate-500 mb-2">
          {uploading ? "Uploading…" : "Drag & drop files here, or"}
        </p>
        <button
          type="button"
          disabled={uploading}
          onClick={() => inputRef.current?.click()}
          className="rounded bg-slate-900 px-4 py-1.5 text-sm text-white disabled:opacity-50"
        >
          Browse files
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFileInput}
        />
      </div>
      {uploadError && (
        <div className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          {uploadError}
        </div>
      )}

      {/* File list */}
      {loading && <p className="text-slate-500">Loading…</p>}
      {error && <p className="text-sm text-red-700 font-mono">{error.message}</p>}
      {files && files.length === 0 && (
        <p className="text-slate-500 text-sm">No files uploaded yet.</p>
      )}
      {files && files.length > 0 && (
        <div className="rounded border border-slate-200 bg-white overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-left">
                <th className="px-3 py-2 font-medium text-slate-600">Filename</th>
                <th className="px-3 py-2 font-medium text-slate-600">Type</th>
                <th className="px-3 py-2 font-medium text-slate-600">Size</th>
                <th className="px-3 py-2 font-medium text-slate-600">Chunks</th>
                <th className="px-3 py-2 font-medium text-slate-600">Status</th>
                <th className="px-3 py-2 font-medium text-slate-600">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {files.map((f) => (
                <tr key={f.id} className="hover:bg-slate-50">
                  <td className="px-3 py-2 font-mono text-xs">{f.filename}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{f.file_type}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">{formatSize(f.file_size)}</td>
                  <td className="px-3 py-2 text-xs text-slate-500">
                    {f.chunk_count > 0 ? (
                      <button
                        type="button"
                        onClick={() => loadChunks(f.id, 0)}
                        className="text-blue-600 hover:underline"
                      >
                        {f.chunk_count}
                      </button>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                        f.parsed
                          ? "bg-green-100 text-green-800"
                          : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {f.parsed ? "parsed" : "pending"}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex gap-2">
                      {!f.parsed && (
                        <button
                          type="button"
                          disabled={ingestingId === f.id && !ingestDone}
                          onClick={() => handleIngest(f.id)}
                          className="rounded bg-blue-600 px-2 py-1 text-xs text-white disabled:opacity-50"
                        >
                          Ingest
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => handleDelete(f.id)}
                        className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Ingest progress */}
      {ingestingId !== null && ingestProgress.length > 0 && (
        <div className="rounded border border-slate-200 bg-white p-4">
          <h3 className="text-sm font-medium mb-2">
            Ingest Progress
            {ingestDone && (
              <span
                className={`ml-2 text-xs ${
                  lastProgress?.event === "done" ? "text-green-600" : "text-red-600"
                }`}
              >
                ({lastProgress?.event})
              </span>
            )}
          </h3>
          <div className="space-y-1 max-h-48 overflow-auto">
            {ingestProgress.map((p, i) => (
              <div key={i} className="text-xs font-mono text-slate-600">
                <span className="inline-block min-w-[120px] text-slate-400">
                  {p.event}
                </span>
                {p.event === "embedding_progress" && (
                  <span>
                    {String(p.done)}/{String(p.total)} chunks
                  </span>
                )}
                {p.event === "chunking_done" && (
                  <span>{String(p.total_chunks)} chunks</span>
                )}
                {p.event === "parsing_done" && (
                  <span>{String(p.text_length)} chars</span>
                )}
                {p.event === "done" && (
                  <span>{String(p.chunks)} chunks stored</span>
                )}
                {p.event === "failed" && (
                  <span className="text-red-600">{String(p.error)}</span>
                )}
              </div>
            ))}
          </div>
          {/* Progress bar for embedding */}
          {!ingestDone && lastProgress?.event === "embedding_progress" && (
            <div className="mt-2 h-2 rounded bg-slate-200 overflow-hidden">
              <div
                className="h-full bg-blue-600 transition-all"
                style={{
                  width: `${
                    ((lastProgress.done as number) /
                      Math.max(lastProgress.total as number, 1)) *
                    100
                  }%`,
                }}
              />
            </div>
          )}
        </div>
      )}

      {/* Chunk preview */}
      {chunkFileId !== null && (
        <div className="rounded border border-slate-200 bg-white p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-medium">
              Chunks (file #{chunkFileId}) — {chunkTotal} total
            </h3>
            <button
              type="button"
              onClick={() => {
                setChunkFileId(null);
                setChunks([]);
              }}
              className="text-xs text-slate-500 hover:text-slate-700"
            >
              Close
            </button>
          </div>
          {chunks.length === 0 && (
            <p className="text-xs text-slate-400">No chunks.</p>
          )}
          <div className="space-y-2">
            {chunks.map((c) => (
              <div
                key={c.chunk_index}
                className="rounded border border-slate-100 bg-slate-50 p-2"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[10px] font-mono text-slate-400">
                    #{c.chunk_index}
                  </span>
                  <span className="text-[10px] text-slate-400">
                    {c.content.length} chars
                  </span>
                </div>
                <div className="text-xs text-slate-700 whitespace-pre-wrap max-h-32 overflow-auto">
                  {c.content}
                </div>
              </div>
            ))}
          </div>
          {/* Pagination */}
          {chunkTotal > chunkLimit && (
            <div className="flex items-center justify-between mt-3">
              <button
                type="button"
                disabled={chunkOffset === 0}
                onClick={() => loadChunks(chunkFileId, Math.max(0, chunkOffset - chunkLimit))}
                className="rounded border border-slate-300 px-2 py-1 text-xs disabled:opacity-50"
              >
                Previous
              </button>
              <span className="text-xs text-slate-500">
                {chunkOffset + 1}–{Math.min(chunkOffset + chunkLimit, chunkTotal)} of{" "}
                {chunkTotal}
              </span>
              <button
                type="button"
                disabled={chunkOffset + chunkLimit >= chunkTotal}
                onClick={() => loadChunks(chunkFileId, chunkOffset + chunkLimit)}
                className="rounded border border-slate-300 px-2 py-1 text-xs disabled:opacity-50"
              >
                Next
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
