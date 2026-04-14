import {
  ThreadPrimitive,
  MessagePrimitive,
  ComposerPrimitive,
  ActionBarPrimitive,
  useMessage,
  type ToolCallMessagePartProps,
  type DataMessagePartProps,
} from "@assistant-ui/react";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowUp, Square, ChevronDown, ChevronRight, Copy, Check, Download, Loader2 } from "lucide-react";
import { useRef, useLayoutEffect, useState, type FC } from "react";
import { useAgentRunDrawer } from "@/components/AgentRunDrawerContext";

function formatDurationShort(ms: number): string {
  if (!ms) return "0ms";
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

function formatTokensShort(n: number): string {
  if (!n) return "0";
  if (n < 1000) return `${n}`;
  return `${(n / 1000).toFixed(1)}k`;
}

const MarkdownText: FC<{ text: string }> = () => (
  <MarkdownTextPrimitive className="aui-md-root" remarkPlugins={[remarkGfm]} />
);

const ThinkingPart: FC<DataMessagePartProps<{ thinking: string }>> = ({ data }) => {
  const [open, setOpen] = useState(false);
  if (!data?.thinking) return <></>;
  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1 text-xs text-slate-400 hover:text-slate-600"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        Thinking
      </button>
      {open && (
        <div className="mt-1 rounded bg-slate-50 border border-slate-200 p-2 text-xs text-slate-500 italic whitespace-pre-wrap max-h-48 overflow-auto">
          {data.thinking}
        </div>
      )}
    </div>
  );
};

const TaskNotificationPart: FC<
  DataMessagePartProps<{
    sub_agent_role: string;
    status: string;
    result: string;
    agent_run_id?: number;
    tool_use_count?: number;
    total_tokens?: number;
    duration_ms?: number;
  }>
> = ({ data }) => {
  const [open, setOpen] = useState(false);
  const { open: openDrawer } = useAgentRunDrawer();
  if (!data) return null;
  const isOk = data.status === "completed";
  const preview =
    data.result.length > 80
      ? data.result.slice(0, 80) + "…"
      : data.result;
  const hasStats =
    data.agent_run_id != null ||
    data.tool_use_count != null ||
    data.total_tokens != null ||
    data.duration_ms != null;
  const canDrill = data.agent_run_id != null;
  return (
    <div className="my-1.5 rounded border border-slate-200 bg-white text-xs overflow-hidden">
      <div className="w-full flex items-center gap-2 px-2.5 py-1.5 hover:bg-slate-50">
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className="flex-shrink-0 p-0.5 -m-0.5 rounded hover:bg-slate-200"
          aria-label={open ? "Collapse" : "Expand"}
        >
          {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        </button>
        <span
          className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${isOk ? "bg-green-500" : "bg-red-500"}`}
        />
        <button
          type="button"
          disabled={!canDrill}
          onClick={() => canDrill && openDrawer(data.agent_run_id!)}
          className={`font-medium flex-shrink-0 ${canDrill ? "hover:underline text-blue-700" : "text-slate-700 cursor-default"}`}
          title={canDrill ? "Open transcript" : undefined}
        >
          {data.sub_agent_role}
        </button>
        {!open && preview && (
          <span className="text-slate-400 truncate ml-1">{preview}</span>
        )}
        {hasStats && (
          <div className="ml-auto flex items-center gap-1 flex-shrink-0">
            {data.tool_use_count != null && (
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                <span className="text-slate-400">tools</span> {data.tool_use_count}
              </span>
            )}
            {data.total_tokens != null && (
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                <span className="text-slate-400">tk</span> {formatTokensShort(data.total_tokens)}
              </span>
            )}
            {data.duration_ms != null && (
              <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-600">
                {formatDurationShort(data.duration_ms)}
              </span>
            )}
            <span className={`text-[10px] ${isOk ? "text-green-600" : "text-red-500"}`}>
              {data.status}
            </span>
          </div>
        )}
        {!hasStats && (
          <span className={`ml-auto text-[10px] flex-shrink-0 ${isOk ? "text-green-600" : "text-red-500"}`}>
            {data.status}
          </span>
        )}
      </div>
      {open && data.result && (
        <div className="border-t border-slate-100 px-2.5 py-2 max-h-72 overflow-y-auto">
          <pre className="whitespace-pre-wrap text-slate-700 text-[11px] leading-relaxed">
            {data.result}
          </pre>
        </div>
      )}
    </div>
  );
};

const ToolCallFallback: FC<ToolCallMessagePartProps> = ({
  toolName,
  args,
  result,
  status,
}) => {
  const [open, setOpen] = useState(false);
  const isError = status?.type === "incomplete";
  const isDone = status?.type === "complete" || isError;
  return (
    <div className="my-1.5 rounded border border-slate-200 bg-white text-xs">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-2.5 py-1.5 text-left hover:bg-slate-50"
      >
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        <span className="font-mono font-medium">{toolName}</span>
        {isDone && (
          <span className={`ml-auto text-[10px] ${isError ? "text-red-500" : "text-green-600"}`}>
            {isError ? "failed" : "done"}
          </span>
        )}
      </button>
      {open && (
        <div className="border-t border-slate-100 px-2.5 py-2 space-y-2">
          {args !== undefined && (
            <div>
              <div className="text-[10px] text-slate-400 mb-0.5">Arguments</div>
              <pre className="whitespace-pre-wrap text-slate-700 bg-slate-50 rounded p-1.5 max-h-32 overflow-auto">
                {typeof args === "string" ? args : JSON.stringify(args, null, 2)}
              </pre>
            </div>
          )}
          {result !== undefined && (
            <div>
              <div className="text-[10px] text-slate-400 mb-0.5">Output</div>
              <pre className={`whitespace-pre-wrap rounded p-1.5 max-h-32 overflow-auto ${
                isError ? "bg-red-50 text-red-700" : "bg-slate-50 text-slate-700"
              }`}>
                {typeof result === "string" ? result : JSON.stringify(result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

function CopyButton() {
  const [copied, setCopied] = useState(false);
  return (
    <ActionBarPrimitive.Copy
      copiedDuration={2000}
      onClick={() => setCopied(true)}
      onBlur={() => setCopied(false)}
      className="p-1 rounded hover:bg-slate-200 text-slate-400 hover:text-slate-600"
    >
      {copied ? <Check className="w-3.5 h-3.5" /> : <Copy className="w-3.5 h-3.5" />}
    </ActionBarPrimitive.Copy>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="flex justify-end mb-3">
      <div className="max-w-[80%] rounded-lg px-4 py-2.5 text-sm bg-blue-600 text-white">
        <MessagePrimitive.Content
          components={{ Text: ({ text }) => <span>{text}</span> }}
        />
      </div>
    </MessagePrimitive.Root>
  );
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1.5 py-1">
      <Loader2 className="w-3.5 h-3.5 text-slate-400 animate-spin" />
      <span className="text-xs text-slate-400">Thinking...</span>
    </div>
  );
}

function AssistantMessage() {
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const [isLong, setIsLong] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);

  const msgState = useMessage();
  const isRunning = msgState.status?.type === "running";

  useLayoutEffect(() => {
    const el = contentRef.current;
    if (!el) return;
    const check = () => {
      if (!expanded) {
        const ov = el.scrollHeight > el.clientHeight + 4;
        setOverflows((prev) => prev !== ov ? ov : prev);
      }
      const textLen = el.innerText.trim().length;
      setIsLong((prev) => (textLen > 500) !== prev ? textLen > 500 : prev);
    };
    check();
    const obs = new MutationObserver(check);
    obs.observe(el, { childList: true, subtree: true, characterData: true });
    return () => obs.disconnect();
  }, [expanded]);

  return (
    <MessagePrimitive.Root className="flex justify-start mb-3 group min-w-0 w-full">
      <div className="min-w-0" style={{ maxWidth: "min(80%, 48rem)" }}>
        <div
          ref={contentRef}
          className={`rounded-lg px-4 py-2.5 text-sm bg-slate-100 text-slate-900 overflow-hidden relative ${
            expanded ? "" : "max-h-[32rem]"
          }`}
          style={{ overflowWrap: "anywhere" }}
        >
          {isRunning && <TypingIndicator />}
          <MessagePrimitive.Content
            components={{
              Text: MarkdownText,
              data: {
                by_name: {
                  thinking: ThinkingPart as any,
                  "task-notification": TaskNotificationPart as any,
                },
              },
              tools: {
                Fallback: ToolCallFallback,
              },
            }}
          />
          {!expanded && overflows && (
            <div className="absolute bottom-0 left-0 right-0 h-16 bg-gradient-to-t from-slate-100 to-transparent pointer-events-none" />
          )}
        </div>
        {overflows && !expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="mt-1 text-xs text-blue-600 hover:text-blue-800"
          >
            Show full message
          </button>
        )}
        {expanded && (
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="mt-1 text-xs text-blue-600 hover:text-blue-800"
          >
            Collapse
          </button>
        )}
        <div className="opacity-0 group-hover:opacity-100 transition-opacity mt-1 flex items-center gap-0.5">
          <ActionBarPrimitive.Root hideWhenRunning>
            <CopyButton />
          </ActionBarPrimitive.Root>
          {isLong && (
            <button
              type="button"
              title="Download as Markdown"
              onClick={() => {
                const el = contentRef.current;
                if (!el) return;
                const mdParts = el.querySelectorAll(".aui-md-root");
                const text = mdParts.length > 0
                  ? Array.from(mdParts).map((p) => p.textContent ?? "").join("\n\n")
                  : el.innerText;
                const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
                const a = document.createElement("a");
                a.href = URL.createObjectURL(blob);
                a.download = `message_${Date.now()}.md`;
                a.click();
                URL.revokeObjectURL(a.href);
              }}
              className="p-1 rounded hover:bg-slate-200 text-slate-400 hover:text-slate-600"
            >
              <Download className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>
    </MessagePrimitive.Root>
  );
}

function Composer() {
  return (
    <ComposerPrimitive.Root className="border-t border-slate-200 px-4 py-3 bg-white">
      <div className="flex items-end gap-2 max-w-4xl mx-auto">
        <ComposerPrimitive.Input
          autoFocus
          placeholder="Type a message..."
          className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent min-h-[40px] max-h-40"
          rows={1}
        />
        <ComposerPrimitive.Send className="rounded-lg bg-blue-600 p-2 text-white hover:bg-blue-700 disabled:opacity-50 disabled:hover:bg-blue-600 flex-shrink-0">
          <ArrowUp className="w-4 h-4" />
        </ComposerPrimitive.Send>
        <ComposerPrimitive.Cancel className="rounded-lg border border-slate-300 p-2 text-slate-600 hover:bg-slate-50 flex-shrink-0">
          <Square className="w-4 h-4" />
        </ComposerPrimitive.Cancel>
      </div>
    </ComposerPrimitive.Root>
  );
}

export default function ChatThread() {
  return (
    <ThreadPrimitive.Root className="flex flex-col h-full">
      <ThreadPrimitive.Viewport className="flex-1 overflow-y-auto overflow-x-hidden px-4 py-4">
        <ThreadPrimitive.Empty>
          <div className="text-center text-sm text-slate-400 mt-8">
            Send a message to start the conversation.
          </div>
        </ThreadPrimitive.Empty>
        <ThreadPrimitive.Messages
          components={{
            UserMessage,
            AssistantMessage,
          }}
        />
      </ThreadPrimitive.Viewport>
      <Composer />
    </ThreadPrimitive.Root>
  );
}
