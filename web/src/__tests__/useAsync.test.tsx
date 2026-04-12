/**
 * @vitest-environment jsdom
 */
import { describe, it, expect, vi } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useAsync } from "@/hooks/useAsync";

describe("useAsync", () => {
  it("sets data on successful fetch", async () => {
    const fn = vi.fn(async () => ({ items: [1, 2, 3] }));
    const { result } = renderHook(() => useAsync(fn, []));

    expect(result.current.loading).toBe(true);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toEqual({ items: [1, 2, 3] });
    expect(result.current.error).toBeNull();
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("sets error on failed fetch", async () => {
    const fn = vi.fn(async () => {
      throw new Error("network error");
    });
    const { result } = renderHook(() => useAsync(fn, []));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toBe("network error");
  });

  it("refetches on reload()", async () => {
    let count = 0;
    const fn = vi.fn(async () => ({ count: ++count }));
    const { result } = renderHook(() => useAsync(fn, []));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });
    expect(result.current.data).toEqual({ count: 1 });

    act(() => {
      result.current.reload();
    });

    await waitFor(() => {
      expect(result.current.data).toEqual({ count: 2 });
    });
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("wraps non-Error throws into Error", async () => {
    const fn = vi.fn(async () => {
      throw "string error";
    });
    const { result } = renderHook(() => useAsync(fn, []));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toBe("string error");
  });
});
