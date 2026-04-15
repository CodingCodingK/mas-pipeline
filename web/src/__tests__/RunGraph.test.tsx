/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi, beforeAll } from "vitest";

// jsdom doesn't implement ResizeObserver, which React Flow touches on mount.
beforeAll(() => {
  if (typeof globalThis.ResizeObserver === "undefined") {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
  if (typeof globalThis.DOMMatrixReadOnly === "undefined") {
    globalThis.DOMMatrixReadOnly = class {
      m22 = 1;
      constructor(_transform?: string) {}
    } as unknown as typeof DOMMatrixReadOnly;
  }
});

import { render, screen } from "@testing-library/react";
import RunGraph, { STATUS_CLASS, type RunGraphNode, type RunGraphEdge } from "@/components/RunGraph";

const NODES: RunGraphNode[] = [
  {
    id: "planner",
    name: "planner",
    role: "planner",
    output: "plan",
    status: "completed",
    started_at: null,
    finished_at: null,
    output_preview: null,
  },
  {
    id: "writer",
    name: "writer",
    role: "writer",
    output: "draft",
    status: "running",
    started_at: null,
    finished_at: null,
    output_preview: null,
  },
  {
    id: "editor",
    name: "editor",
    role: "editor",
    output: "final",
    status: "idle",
    started_at: null,
    finished_at: null,
    output_preview: null,
  },
];

const EDGES: RunGraphEdge[] = [
  { from: "planner", to: "writer", kind: "sequence" },
  { from: "writer", to: "editor", kind: "sequence" },
];

describe("RunGraph status → color mapping", () => {
  it("assigns the full closed-set color classes", () => {
    expect(STATUS_CLASS.idle).toMatch(/slate/);
    expect(STATUS_CLASS.running).toMatch(/blue/);
    expect(STATUS_CLASS.running).toMatch(/animate-pulse/);
    expect(STATUS_CLASS.completed).toMatch(/emerald/);
    expect(STATUS_CLASS.failed).toMatch(/rose/);
    expect(STATUS_CLASS.paused).toMatch(/amber/);
    expect(STATUS_CLASS.cancelled).toMatch(/slate/);
    expect(STATUS_CLASS.skipped).toMatch(/dashed/);
  });
});

describe("RunGraph rendering", () => {
  it("renders each node with its status attribute", () => {
    render(<RunGraph nodes={NODES} edges={EDGES} />);
    const running = screen.getAllByText("running", { exact: false });
    expect(running.length).toBeGreaterThan(0);
    const nodeEls = document.querySelectorAll("[data-status]");
    expect(nodeEls.length).toBe(3);
    const statuses = Array.from(nodeEls).map((el) => el.getAttribute("data-status"));
    expect(statuses.sort()).toEqual(["completed", "idle", "running"]);
  });

  it("mounts with an onNodeClick callback prop without throwing", () => {
    // React Flow's click events rely on a real layout engine (width/height
    // and ResizeObserver) that jsdom cannot provide end-to-end. We assert
    // the component accepts the callback prop and the node we would click
    // exists in the DOM. The actual handler wiring is verified by the
    // component's source.
    const spy = vi.fn();
    render(<RunGraph nodes={NODES} edges={EDGES} onNodeClick={spy} />);
    const editorNode = Array.from(document.querySelectorAll("[data-status]")).find(
      (el) => el.textContent?.includes("editor")
    );
    expect(editorNode).toBeTruthy();
    expect(spy).not.toHaveBeenCalled();
  });

  it("shows an empty-state placeholder when given zero nodes", () => {
    render(<RunGraph nodes={[]} edges={[]} />);
    expect(screen.getByText(/no nodes to display/i)).toBeTruthy();
  });
});
