import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { client, ApiError, request } from "@/api/client";

type FetchArgs = { url: string; init: RequestInit };

function installFetch(responder: (url: string, init: RequestInit) => Response): {
  calls: FetchArgs[];
} {
  const calls: FetchArgs[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : (input as URL).toString();
    const i = init ?? {};
    calls.push({ url, init: i });
    return responder(url, i);
  }) as unknown as typeof fetch;
  return { calls };
}

function jsonResponse(status: number, body: unknown): Response {
  const headers = new Headers({ "content-type": "application/json" });
  return new Response(JSON.stringify(body), { status, headers });
}

describe("api client", () => {
  const originalEnv = { ...import.meta.env };

  beforeEach(() => {
    (import.meta.env as Record<string, string>).VITE_API_BASE = "http://api.test/api";
  });

  afterEach(() => {
    (import.meta.env as Record<string, string>).VITE_API_BASE =
      originalEnv.VITE_API_BASE ?? "";
    (import.meta.env as Record<string, string>).VITE_API_KEY =
      originalEnv.VITE_API_KEY ?? "";
    vi.restoreAllMocks();
  });

  it("injects X-API-Key header when VITE_API_KEY is set", async () => {
    (import.meta.env as Record<string, string>).VITE_API_KEY = "secret";
    const { calls } = installFetch(() => jsonResponse(200, { items: [] }));
    await client.get<{ items: unknown[] }>("/agents");
    expect(calls).toHaveLength(1);
    const call = calls[0]!;
    expect(call.url).toBe("http://api.test/api/agents");
    const headers = call.init.headers as Record<string, string>;
    expect(headers["X-API-Key"]).toBe("secret");
  });

  it("omits X-API-Key header when VITE_API_KEY is empty", async () => {
    (import.meta.env as Record<string, string>).VITE_API_KEY = "";
    const { calls } = installFetch(() => jsonResponse(200, {}));
    await client.get("/agents");
    const headers = calls[0]!.init.headers as Record<string, string>;
    expect("X-API-Key" in headers).toBe(false);
  });

  it("adds Content-Type JSON on PUT with body", async () => {
    const { calls } = installFetch(() => jsonResponse(200, {}));
    await client.put("/agents/writer", { content: "G" });
    const headers = calls[0]!.init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(calls[0]!.init.body).toBe(JSON.stringify({ content: "G" }));
  });

  it("throws ApiError with preserved body on 404", async () => {
    installFetch(() => jsonResponse(404, { detail: "agent not found" }));
    await expect(request("GET", "/agents/nobody")).rejects.toMatchObject({
      status: 404,
    });
    try {
      await request("GET", "/agents/nobody");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const e = err as ApiError;
      expect(e.status).toBe(404);
      expect((e.body as { detail: string }).detail).toBe("agent not found");
    }
  });

  it("returns undefined on 204 without parse error", async () => {
    installFetch(
      () => new Response(null, { status: 204 })
    );
    const result = await client.del<undefined>("/agents/writer");
    expect(result).toBeUndefined();
  });

  it("surfaces 409 references payload through ApiError.body", async () => {
    const body = {
      detail: "agent 'writer' is referenced by 1 pipeline(s)",
      references: [{ project_id: null, pipeline: "blog", role: "writer" }],
    };
    installFetch(() => jsonResponse(409, { detail: body }));
    try {
      await client.del("/agents/writer");
      throw new Error("expected throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const e = err as ApiError;
      expect(e.status).toBe(409);
    }
  });
});
