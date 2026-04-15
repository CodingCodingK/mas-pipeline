/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { render, screen, cleanup, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import RunNodeDrawer from "@/components/RunNodeDrawer";
import { client } from "@/api/client";

const NODE_NAME = "writer";

const RUN_DETAIL = {
  run_id: "abc123",
  project_id: 42,
  pipeline: "blog_generation",
  status: "completed",
  started_at: null,
  finished_at: null,
  outputs: { writer: "Draft output text.", researcher: "Research notes." },
  final_output: "Draft output text.",
  error: null,
  paused_at: null,
  paused_output: "",
};

const TIMELINE = [
  {
    id: 1,
    ts: "2026-04-15T10:00:00Z",
    event_type: "llm_call",
    agent_role: "writer",
    payload: {
      node_name: "writer",
      input_tokens: 100,
      output_tokens: 50,
      cost_usd: 0.001,
      duration_ms: 1200,
    },
  },
  {
    id: 2,
    ts: "2026-04-15T10:00:01Z",
    event_type: "tool_call",
    agent_role: "writer",
    payload: { node_name: "writer", duration_ms: 80 },
  },
  {
    id: 3,
    ts: "2026-04-15T10:00:02Z",
    event_type: "llm_call",
    agent_role: "researcher",
    payload: { node_name: "researcher", input_tokens: 200, output_tokens: 80, cost_usd: 0.002 },
  },
];

const GRAPH = {
  run_id: "abc123",
  pipeline: "blog_generation",
  status: "completed",
  nodes: [
    {
      id: "writer",
      name: "writer",
      role: "writer",
      status: "completed",
      started_at: null,
      finished_at: null,
      output_preview: null,
    },
  ],
  edges: [],
};

function wrap(ui: React.ReactNode) {
  return <MemoryRouter>{ui}</MemoryRouter>;
}

function mockFetches() {
  vi.spyOn(client, "get").mockImplementation((path: string) => {
    if (path === `/runs/abc123`) return Promise.resolve(RUN_DETAIL as unknown);
    if (path === `/telemetry/runs/abc123/timeline`)
      return Promise.resolve(TIMELINE as unknown);
    if (path === `/runs/abc123/graph`) return Promise.resolve(GRAPH as unknown);
    return Promise.reject(new Error(`unexpected path ${path}`));
  });
}

describe("RunNodeDrawer", () => {
  beforeEach(() => {
    mockFetches();
  });
  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
  });

  it("renders nothing when closed", () => {
    const { container } = render(
      wrap(
        <RunNodeDrawer
          runId="abc123"
          nodeName={null}
          isOpen={false}
          onClose={() => {}}
        />
      )
    );
    expect(container.querySelector("[data-testid=run-node-drawer]")).toBeNull();
  });

  it("renders four segments when open", async () => {
    render(
      wrap(
        <RunNodeDrawer
          runId="abc123"
          nodeName={NODE_NAME}
          isOpen={true}
          onClose={() => {}}
        />
      )
    );
    await waitFor(() => {
      expect(screen.getByText("Output")).toBeTruthy();
    });
    expect(screen.getByText(/Timeline \(/)).toBeTruthy();
    expect(screen.getByText("Telemetry")).toBeTruthy();
    expect(screen.getByText(/Events \(/)).toBeTruthy();
  });

  it("filters timeline by node_name and rolls up telemetry", async () => {
    render(
      wrap(
        <RunNodeDrawer
          runId="abc123"
          nodeName={NODE_NAME}
          isOpen={true}
          onClose={() => {}}
        />
      )
    );
    await waitFor(() => {
      // writer has 1 llm_call + 1 tool_call = 2 events, researcher excluded.
      expect(screen.getByText(/Timeline \(2\)/)).toBeTruthy();
    });
    // writer llm_call cost 0.001, researcher's 0.002 excluded.
    expect(screen.getByText(/\$0\.001000/)).toBeTruthy();
    // llm_calls rolls up to 1 (not 2).
    const llmCard = screen.getByText("llm_calls").parentElement!;
    expect(llmCard.textContent).toContain("1");
  });

  it("shows empty state when output is missing", async () => {
    vi.restoreAllMocks();
    vi.spyOn(client, "get").mockImplementation((path: string) => {
      if (path === `/runs/abc123`)
        return Promise.resolve({ ...RUN_DETAIL, outputs: {} } as unknown);
      if (path === `/telemetry/runs/abc123/timeline`) return Promise.resolve([] as unknown);
      if (path === `/runs/abc123/graph`) return Promise.resolve(GRAPH as unknown);
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    render(
      wrap(
        <RunNodeDrawer
          runId="abc123"
          nodeName={NODE_NAME}
          isOpen={true}
          onClose={() => {}}
        />
      )
    );
    await waitFor(() => {
      expect(screen.getByText(/No output recorded/i)).toBeTruthy();
    });
  });

  it("deep links to Observability with correct run query", async () => {
    render(
      wrap(
        <RunNodeDrawer
          runId="abc123"
          nodeName={NODE_NAME}
          isOpen={true}
          onClose={() => {}}
        />
      )
    );
    await waitFor(() => {
      expect(screen.getByText("Output")).toBeTruthy();
    });
    const anchors = Array.from(document.querySelectorAll("a"));
    const anchor = anchors.find((a) =>
      (a.getAttribute("href") || "").includes("observability")
    );
    expect(anchor?.getAttribute("href")).toBe(
      "/projects/42/observability?sub=timeline&run=abc123"
    );
  });

  it("calls onClose when X button is clicked", async () => {
    const onClose = vi.fn();
    render(
      wrap(
        <RunNodeDrawer
          runId="abc123"
          nodeName={NODE_NAME}
          isOpen={true}
          onClose={onClose}
        />
      )
    );
    await waitFor(() => {
      expect(screen.getByText("Output")).toBeTruthy();
    });
    fireEvent.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalled();
  });
});
