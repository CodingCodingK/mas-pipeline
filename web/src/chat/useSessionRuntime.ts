import { useCallback, useEffect, useRef, useState } from "react";
import {
  useExternalStoreRuntime,
  type ThreadMessageLike,
  type AppendMessage,
} from "@assistant-ui/react";
import { client } from "@/api/client";
import { fetchEventStream } from "@/api/sse";
import type { CreateSessionResponse } from "@/api/types";

interface ToolCallState {
  toolCallId: string;
  toolName: string;
  args: string;
  result?: string;
  isError?: boolean;
}

interface StreamingState {
  text: string;
  thinking: string;
  toolCalls: ToolCallState[];
}

function streamingToParts(s: StreamingState): any[] {
  const parts: any[] = [];
  // Always include both thinking and text parts to keep array structure
  // stable — prevents assistant-ui from unmounting/remounting components
  // when the array length changes (e.g. thinking-only → thinking+text).
  parts.push({ type: "data-thinking" as const, data: { thinking: s.thinking } });
  parts.push({ type: "text" as const, text: s.text });
  for (const tc of s.toolCalls) {
    parts.push({
      type: "tool-call" as const,
      toolCallId: tc.toolCallId,
      toolName: tc.toolName,
      args: tc.args ? safeParseJson(tc.args) : {},
      result: tc.result,
      isError: tc.isError,
    });
  }
  return parts;
}

function buildMessages(
  history: ThreadMessageLike[],
  streaming: StreamingState | null,
  isRunning: boolean
): ThreadMessageLike[] {
  const msgs = [...history];
  if (streaming && isRunning) {
    msgs.push({
      id: "streaming-assistant",
      role: "assistant",
      content: streamingToParts(streaming) as any,
      status: { type: "running" },
    });
  }
  return msgs;
}

function safeParseJson(s: string): unknown {
  try {
    return JSON.parse(s);
  } catch {
    return s;
  }
}

function convertHistoryMessages(
  items: Array<Record<string, unknown>>
): ThreadMessageLike[] {
  const result: ThreadMessageLike[] = [];
  let pendingAssistant: { parts: any[]; id: string } | null = null;

  const flushAssistant = () => {
    if (!pendingAssistant) return;
    if (pendingAssistant.parts.length === 0) {
      pendingAssistant.parts.push({ type: "text", text: "" });
    }
    result.push({
      id: pendingAssistant.id,
      role: "assistant" as const,
      content: pendingAssistant.parts,
      status: { type: "complete" as const, reason: "stop" as const },
    });
    pendingAssistant = null;
  };

  for (let i = 0; i < items.length; i++) {
    const m = items[i];
    const role = m.role as string;

    if (role === "user") {
      flushAssistant();
      const meta = m.metadata as Record<string, unknown> | undefined;
      if (meta?.kind === "task_notification") {
        let extractedResult = "";
        if (typeof m.content === "string") {
          const match = m.content.match(/<result>([\s\S]*?)<\/result>/);
          extractedResult = match ? match[1].trim() : "";
        }
        result.push({
          id: `hist-${i}`,
          role: "assistant" as const,
          content: [
            {
              type: "data-task-notification" as any,
              data: {
                sub_agent_role: meta.sub_agent_role as string,
                status: meta.status as string,
                result: extractedResult,
                agent_run_id: meta.agent_run_id as number | undefined,
                tool_use_count: meta.tool_use_count as number | undefined,
                total_tokens: meta.total_tokens as number | undefined,
                duration_ms: meta.duration_ms as number | undefined,
              },
            },
          ],
          status: { type: "complete" as const, reason: "stop" as const },
        });
        continue;
      }
      const content = m.content;
      const text = typeof content === "string" ? content : JSON.stringify(content ?? "");
      result.push({
        id: `hist-${i}`,
        role: "user" as const,
        content: [{ type: "text" as const, text }],
      });
    } else if (role === "assistant") {
      flushAssistant();
      pendingAssistant = { parts: [], id: `hist-${i}` };

      if (m.thinking && typeof m.thinking === "string") {
        pendingAssistant.parts.push({
          type: "data-thinking",
          data: { thinking: m.thinking },
        });
      }

      const content = m.content;
      if (content && typeof content === "string" && content.length > 0) {
        pendingAssistant.parts.push({ type: "text", text: content });
      }

      const toolCalls = m.tool_calls as Array<Record<string, unknown>> | undefined;
      if (toolCalls && Array.isArray(toolCalls)) {
        for (const tc of toolCalls) {
          pendingAssistant.parts.push({
            type: "tool-call",
            toolCallId: tc.id as string,
            toolName: (tc.function as Record<string, unknown>)?.name as string ?? "unknown",
            args: safeParseJson(
              (tc.function as Record<string, unknown>)?.arguments as string ?? "{}"
            ),
          });
        }
      }
    } else if (role === "tool") {
      // Attach tool result to the pending assistant message's matching tool-call
      if (pendingAssistant) {
        const tcId = m.tool_call_id as string;
        const output = typeof m.content === "string" ? m.content : JSON.stringify(m.content ?? "");
        const existing = pendingAssistant.parts.find(
          (p: any) => p.type === "tool-call" && p.toolCallId === tcId
        );
        if (existing) {
          existing.result = output;
        }
      }
      // tool messages are not rendered as standalone messages
    }
    // skip system and other roles
  }

  flushAssistant();
  return result;
}

export function useSessionRuntime(
  projectId: number,
  sessionId: number | null,
  onSessionCreated: (id: number) => void,
  mode: "chat" | "autonomous" = "chat",
) {
  const [history, setHistory] = useState<ThreadMessageLike[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [streaming, setStreaming] = useState<StreamingState | null>(null);
  const [turnCount, setTurnCount] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const sidRef = useRef(sessionId);
  sidRef.current = sessionId;

  // Load message history when session changes
  useEffect(() => {
    if (!sessionId) {
      setHistory([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await client.get<{
          items: Array<Record<string, unknown>>;
        }>(`/sessions/${sessionId}/messages`);
        if (cancelled) return;
        const loaded = convertHistoryMessages(res.items);
        setHistory(loaded);
      } catch {
        // fresh session
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const reloadHistory = useCallback(
    async (sid: number) => {
      try {
        const res = await client.get<{
          items: Array<Record<string, unknown>>;
        }>(`/sessions/${sid}/messages`);
        setHistory(convertHistoryMessages(res.items));
      } catch {
        // ignore
      }
    },
    []
  );

  // Subscribe to SSE events
  const subscribe = useCallback(
    (sid: number) => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      const state: StreamingState = { text: "", thinking: "", toolCalls: [] };
      let rafPending = 0;

      const flushToReact = () => {
        rafPending = 0;
        setStreaming({ ...state, toolCalls: [...state.toolCalls] });
      };

      const scheduleFlush = () => {
        if (!rafPending) {
          rafPending = requestAnimationFrame(flushToReact);
        }
      };

      fetchEventStream(`/sessions/${sid}/events`, {
        signal: ctrl.signal,
        method: "GET",
        onEvent: (evt) => {
          let parsed: Record<string, unknown>;
          try {
            parsed = JSON.parse(evt.data);
          } catch {
            return;
          }

          if (evt.type === "done") {
            if (rafPending) {
              cancelAnimationFrame(rafPending);
              rafPending = 0;
            }

            const hasContent = state.text || state.thinking || state.toolCalls.length > 0;
            if (hasContent) {
              const snapshotParts = streamingToParts(state);
              setHistory((prev) => [
                ...prev,
                {
                  id: `stream-done-${Date.now()}`,
                  role: "assistant" as const,
                  content: snapshotParts,
                  status: { type: "complete" as const, reason: "stop" as const },
                },
              ]);
            }

            setStreaming(null);
            setIsRunning(false);
            setTurnCount((c) => c + 1);

            void reloadHistory(sid);

            state.text = "";
            state.thinking = "";
            state.toolCalls = [];
            return;
          }

          if (evt.type === "error") {
            state.text += `\n[Error: ${parsed.content}]`;
            flushToReact();
            return;
          }

          if (evt.type === "text_delta") {
            state.text += parsed.content as string;
          } else if (evt.type === "thinking_delta") {
            state.thinking += parsed.content as string;
          } else if (evt.type === "tool_start") {
            state.toolCalls.push({
              toolCallId: parsed.tool_call_id as string,
              toolName: parsed.name as string,
              args: "",
            });
          } else if (evt.type === "tool_end") {
            const tcId = parsed.tool_call_id as string;
            const tc = state.toolCalls.find((t) => t.toolCallId === tcId);
            if (tc) tc.args = parsed.arguments as string;
          } else if (evt.type === "tool_result") {
            const tcId = parsed.tool_call_id as string;
            const tc = state.toolCalls.find((t) => t.toolCallId === tcId);
            if (tc) {
              tc.result = parsed.output as string;
              tc.isError = !(parsed.success as boolean);
            }
          }

          scheduleFlush();
        },
      }).catch(() => {
        if (ctrl.signal.aborted) return;
        // SSE dropped — reload history and reconnect after a short delay
        void reloadHistory(sid);
        setTimeout(() => {
          if (!ctrl.signal.aborted) subscribe(sid);
        }, 2000);
      });
    },
    [reloadHistory]
  );

  useEffect(() => {
    if (!sessionId) return;
    subscribe(sessionId);
    return () => {
      abortRef.current?.abort();
    };
  }, [sessionId, subscribe]);

  const onNew = useCallback(
    async (message: AppendMessage) => {
      const textPart = message.content.find((p) => p.type === "text");
      const text = textPart && "text" in textPart ? textPart.text : "";
      if (!text.trim()) return;

      let currentSid = sidRef.current;
      if (!currentSid) {
        const chatId = crypto.randomUUID();
        const res = await client.post<CreateSessionResponse>(
          `/projects/${projectId}/sessions`,
          { mode, channel: "web", chat_id: chatId }
        );
        currentSid = res.id;
        sidRef.current = res.id;
        onSessionCreated(res.id);
      }

      setHistory((prev) => [
        ...prev,
        {
          role: "user" as const,
          content: [{ type: "text" as const, text }],
          id: `user-${Date.now()}`,
        },
      ]);
      setIsRunning(true);
      setStreaming({ text: "", thinking: "", toolCalls: [] });

      // Ensure SSE is connected before posting — avoids race where
      // LLM starts emitting events before the subscription is established.
      subscribe(currentSid);

      await client.post(`/sessions/${currentSid}/messages`, { content: text });
    },
    [projectId, onSessionCreated, mode, subscribe]
  );

  const onCancel = useCallback(async () => {
    abortRef.current?.abort();
    setIsRunning(false);
    setStreaming(null);
  }, []);

  const messages = buildMessages(history, streaming, isRunning);

  const convertMessage = useCallback(
    (msg: ThreadMessageLike): ThreadMessageLike => msg,
    []
  );

  const runtime = useExternalStoreRuntime({
    messages,
    convertMessage,
    isRunning,
    onNew,
    onCancel,
  });

  return { runtime, isRunning, turnCount };
}
