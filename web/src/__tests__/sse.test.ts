import { describe, it, expect, vi, afterEach } from "vitest";
import { fetchEventStream, __sseInternal, type SseEvent } from "@/api/sse";

function encode(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

function streamFromChunks(chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encode(c));
      controller.close();
    },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("sse feedLines parser", () => {
  it("parses event + data frames and ignores heartbeats", () => {
    const events: SseEvent[] = [];
    const state = { pendingType: "message", dataLines: [] as string[], buffer: "" };
    const raw =
      "event: pipeline_start\n" +
      'data: {"run_id":"x"}\n' +
      "\n" +
      ": ping\n" +
      "\n" +
      "event: pipeline_end\n" +
      "data: {}\n" +
      "\n";
    __sseInternal.feedLines(state, raw, (ev) => events.push(ev));
    expect(events).toHaveLength(2);
    expect(events[0]).toEqual({ type: "pipeline_start", data: '{"run_id":"x"}' });
    expect(events[1]).toEqual({ type: "pipeline_end", data: "{}" });
  });

  it("resets pending type to 'message' after each frame", () => {
    const events: SseEvent[] = [];
    const state = { pendingType: "message", dataLines: [] as string[], buffer: "" };
    __sseInternal.feedLines(
      state,
      "event: a\ndata: 1\n\ndata: 2\n\n",
      (ev) => events.push(ev)
    );
    expect(events).toEqual([
      { type: "a", data: "1" },
      { type: "message", data: "2" },
    ]);
  });

  it("handles multi-line data", () => {
    const events: SseEvent[] = [];
    const state = { pendingType: "message", dataLines: [] as string[], buffer: "" };
    __sseInternal.feedLines(
      state,
      "event: multi\ndata: line1\ndata: line2\n\n",
      (ev) => events.push(ev)
    );
    expect(events[0]).toEqual({ type: "multi", data: "line1\nline2" });
  });

  it("tolerates CRLF line endings", () => {
    const events: SseEvent[] = [];
    const state = { pendingType: "message", dataLines: [] as string[], buffer: "" };
    __sseInternal.feedLines(
      state,
      "event: a\r\ndata: 1\r\n\r\n",
      (ev) => events.push(ev)
    );
    expect(events).toEqual([{ type: "a", data: "1" }]);
  });
});

describe("fetchEventStream", () => {
  it("reads a ReadableStream and emits frames in order", async () => {
    const stream = streamFromChunks([
      "event: pipeline_start\n",
      'data: {"run_id":"x"}\n\n',
      ": ping\n\n",
      "event: pipeline_end\ndata: {}\n\n",
    ]);
    globalThis.fetch = vi.fn(
      async () =>
        new Response(stream, {
          status: 200,
          headers: { "content-type": "text/event-stream" },
        })
    ) as unknown as typeof fetch;

    const received: SseEvent[] = [];
    await fetchEventStream("/projects/1/pipelines/blog/runs?stream=true", {
      body: { input: {} },
      onEvent: (ev) => received.push(ev),
    });
    expect(received).toEqual([
      { type: "pipeline_start", data: '{"run_id":"x"}' },
      { type: "pipeline_end", data: "{}" },
    ]);
  });

  it("rejects on non-2xx status", async () => {
    globalThis.fetch = vi.fn(
      async () => new Response("nope", { status: 500 })
    ) as unknown as typeof fetch;
    await expect(
      fetchEventStream("/x", { onEvent: () => {} })
    ).rejects.toThrow(/HTTP 500/);
  });
});
