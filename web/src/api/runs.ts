import { client } from "./client";
import { fetchEventStream, type SseEvent } from "./sse";
import type { RunGraphNode, RunGraphEdge } from "../components/RunGraph";

export interface RunGraphResponse {
  run_id: string;
  pipeline: string;
  status: string;
  nodes: RunGraphNode[];
  edges: RunGraphEdge[];
}

export function getRunGraph(runId: string): Promise<RunGraphResponse> {
  return client.get<RunGraphResponse>(`/runs/${runId}/graph`);
}

export interface ResumeValue {
  action: "approve" | "reject" | "edit";
  feedback?: string;
  edited?: string;
}

export function resumeRun(runId: string, value: ResumeValue): Promise<unknown> {
  return client.post(`/runs/${runId}/resume`, { value });
}

export function pauseRun(runId: string): Promise<unknown> {
  return client.post(`/runs/${runId}/pause`);
}

export function cancelRun(runId: string): Promise<unknown> {
  return client.post(`/runs/${runId}/cancel`);
}

/**
 * Subscribe to the standalone run event stream. Used for re-attaching after
 * a pause→resume transition (the original stream is drained by the first
 * interrupt). Caller owns the AbortController.
 */
export function subscribeRunEvents(
  runId: string,
  opts: { signal: AbortSignal; onEvent: (ev: SseEvent) => void }
): Promise<void> {
  return fetchEventStream(`/runs/${runId}/events`, {
    signal: opts.signal,
    method: "GET",
    onEvent: opts.onEvent,
  });
}
