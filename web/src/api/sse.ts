export interface SseEvent {
  type: string;
  data: string;
}

export interface FetchEventStreamOptions {
  signal?: AbortSignal;
  body?: unknown;
  onEvent: (event: SseEvent) => void;
}

function apiBase(): string {
  const raw = import.meta.env.VITE_API_BASE;
  return typeof raw === "string" && raw.length > 0 ? raw : "/api";
}

function apiKey(): string {
  const raw = import.meta.env.VITE_API_KEY;
  return typeof raw === "string" ? raw : "";
}

/**
 * Parse a chunk of SSE text. Maintains cross-chunk state in `state`.
 * Emits a frame when a blank line is seen.
 */
function feedLines(
  state: { pendingType: string; dataLines: string[]; buffer: string },
  chunk: string,
  onEvent: (event: SseEvent) => void
): void {
  state.buffer += chunk;
  let idx: number;
  while ((idx = state.buffer.indexOf("\n")) !== -1) {
    // Preserve raw line for this iteration; strip trailing \r if present.
    let line = state.buffer.slice(0, idx);
    state.buffer = state.buffer.slice(idx + 1);
    if (line.endsWith("\r")) line = line.slice(0, -1);

    if (line.length === 0) {
      if (state.dataLines.length > 0) {
        onEvent({
          type: state.pendingType,
          data: state.dataLines.join("\n"),
        });
      }
      state.pendingType = "message";
      state.dataLines = [];
      continue;
    }
    if (line.startsWith(":")) continue; // heartbeat comment

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") {
      state.pendingType = value;
    } else if (field === "data") {
      state.dataLines.push(value);
    }
    // id / retry fields are intentionally ignored for the MVP.
  }
}

export async function fetchEventStream(
  path: string,
  opts: FetchEventStreamOptions
): Promise<void> {
  const url = apiBase().replace(/\/$/, "") + path;
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  const key = apiKey();
  if (key.length > 0) headers["X-API-Key"] = key;
  if (opts.body !== undefined && opts.body !== null) {
    headers["Content-Type"] = "application/json";
  }

  const resp = await fetch(url, {
    method: "POST",
    headers,
    body:
      opts.body !== undefined && opts.body !== null
        ? JSON.stringify(opts.body)
        : undefined,
    signal: opts.signal,
  });

  if (!resp.ok || !resp.body) {
    throw new Error(`SSE stream failed: HTTP ${resp.status}`);
  }

  const decoder = new TextDecoder("utf-8");
  const reader = resp.body.getReader();
  const state = { pendingType: "message", dataLines: [] as string[], buffer: "" };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      feedLines(state, chunk, opts.onEvent);
    }
    // Flush any trailing buffered content with a synthetic blank line.
    feedLines(state, "\n", opts.onEvent);
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // ignore
    }
  }
}

// Internal export for unit tests.
export const __sseInternal = { feedLines };
