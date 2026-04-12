import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { client } from "@/api/client";
import { useSessionRuntime } from "@/chat/useSessionRuntime";
import ChatThread from "@/chat/ChatThread";
import SessionTelemetry from "@/components/SessionTelemetry";

interface SessionItem {
  id: number;
  mode: string;
  status: string;
  created_at: string | null;
  last_active_at: string | null;
}

function formatTime(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

type SessionMode = "chat" | "autonomous";

export default function ChatPage() {
  const { id, sessionId } = useParams<{ id: string; sessionId: string }>();
  const projectId = Number(id);
  const navigate = useNavigate();

  const [sid, setSid] = useState<number | null>(
    sessionId ? Number(sessionId) : null
  );
  const [sessions, setSessions] = useState<SessionItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [newMode, setNewMode] = useState<SessionMode>("chat");
  const [showTelemetry, setShowTelemetry] = useState(false);

  const currentSession = sessions.find((s) => s.id === sid);
  const activeMode: SessionMode =
    (currentSession?.mode as SessionMode) || newMode;

  const onSessionCreated = useCallback(
    (newId: number) => {
      setSid(newId);
      navigate(`/projects/${projectId}/chat/${newId}`, { replace: true });
    },
    [projectId, navigate]
  );

  const { runtime, turnCount } = useSessionRuntime(
    projectId,
    sid,
    onSessionCreated,
    activeMode
  );

  const loadSessions = useCallback(() => {
    client
      .get<{ items: SessionItem[] }>(`/projects/${projectId}/sessions`)
      .then((res) => setSessions(res.items))
      .catch(() => {});
  }, [projectId]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions, sid]);

  useEffect(() => {
    if (sessionId || sid) return;
    if (sessions.length > 0) {
      const latest = sessions[0];
      setSid(latest.id);
      navigate(`/projects/${projectId}/chat/${latest.id}`, { replace: true });
    }
  }, [sessions, sessionId, sid, projectId, navigate]);

  const handleNewChat = useCallback(
    async (mode: SessionMode) => {
      setError(null);
      try {
        const chatId = crypto.randomUUID();
        const res = await client.post<{ id: number }>(
          `/projects/${projectId}/sessions`,
          { mode, channel: "web", chat_id: chatId }
        );
        setSid(res.id);
        navigate(`/projects/${projectId}/chat/${res.id}`, { replace: true });
      } catch (err) {
        setError(`Failed to create session: ${err}`);
      }
    },
    [projectId, navigate]
  );

  const handleSelectSession = useCallback(
    (s: SessionItem) => {
      if (s.id === sid) return;
      setError(null);
      setSid(s.id);
      navigate(`/projects/${projectId}/chat/${s.id}`, { replace: true });
    },
    [projectId, sid, navigate]
  );

  const handleDeleteSession = useCallback(
    async (e: React.MouseEvent, s: SessionItem) => {
      e.stopPropagation();
      try {
        await client.del(`/sessions/${s.id}`);
        if (s.id === sid) {
          setSid(null);
          navigate(`/projects/${projectId}/chat`, { replace: true });
        }
        loadSessions();
      } catch {
        // ignore
      }
    },
    [sid, projectId, navigate, loadSessions]
  );

  const modeBadge = (mode: string) => {
    if (mode === "autonomous") {
      return (
        <span className="ml-1 inline-block rounded bg-purple-100 px-1 py-0.5 text-[10px] font-medium text-purple-700">
          Auto
        </span>
      );
    }
    return null;
  };

  return (
    <div className="flex h-full overflow-hidden">
      {/* Sidebar */}
      <div className="w-56 flex-shrink-0 border-r border-slate-200 flex flex-col bg-slate-50">
        <div className="p-3 border-b border-slate-200 space-y-2">
          <select
            value={newMode}
            onChange={(e) => setNewMode(e.target.value as SessionMode)}
            className="w-full rounded border border-slate-300 px-2 py-1 text-xs"
          >
            <option value="chat">Chat (assistant)</option>
            <option value="autonomous">Autonomous (coordinator)</option>
          </select>
          <button
            type="button"
            onClick={() => handleNewChat(newMode)}
            className="w-full rounded bg-blue-600 px-3 py-1.5 text-sm text-white hover:bg-blue-700"
          >
            + New{" "}
            {newMode === "autonomous" ? "Autonomous Session" : "Chat"}
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {sessions.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => handleSelectSession(s)}
              className={`w-full text-left px-3 py-2 text-sm border-b border-slate-100 hover:bg-slate-100 group ${
                s.id === sid ? "bg-white font-medium" : "text-slate-600"
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="truncate">
                  #{s.id}
                  {modeBadge(s.mode)}
                </span>
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => handleDeleteSession(e, s)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter")
                      handleDeleteSession(
                        e as unknown as React.MouseEvent,
                        s
                      );
                  }}
                  className="hidden group-hover:inline-block text-slate-400 hover:text-red-500 text-xs px-1"
                  title="Delete session"
                >
                  x
                </span>
              </div>
              <div className="text-xs text-slate-400">
                {formatTime(s.last_active_at || s.created_at)}
              </div>
            </button>
          ))}
          {sessions.length === 0 && (
            <p className="p-3 text-xs text-slate-400">No sessions yet</p>
          )}
        </div>
        <div className="p-2 border-t border-slate-200">
          <Link
            to={`/projects/${projectId}?tab=agents`}
            className="text-xs text-slate-500 hover:underline"
          >
            &larr; Back to project
          </Link>
        </div>
      </div>

      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center gap-3 px-4 py-2 border-b border-slate-200">
          <span className="text-sm text-slate-500">
            {sid ? (
              <>
                Session #{sid}
                {currentSession && modeBadge(currentSession.mode)}
              </>
            ) : (
              "Select a session or start a new chat"
            )}
          </span>
          {sid && (
            <button
              type="button"
              onClick={() => setShowTelemetry((v) => !v)}
              className={`ml-auto rounded px-2.5 py-1 text-xs font-medium border ${
                showTelemetry
                  ? "bg-blue-50 border-blue-300 text-blue-700"
                  : "border-slate-300 text-slate-500 hover:text-slate-700"
              }`}
            >
              Telemetry
            </button>
          )}
        </div>

        {error && (
          <div className="mx-4 mt-2 rounded border border-red-200 bg-red-50 p-2 text-sm text-red-800">
            {error}
          </div>
        )}

        <div className="flex-1 min-h-0 relative">
          <div className="w-full h-full min-w-0 overflow-hidden">
            <AssistantRuntimeProvider runtime={runtime}>
              <ChatThread />
            </AssistantRuntimeProvider>
          </div>
          {showTelemetry && sid && (
            <div className="absolute top-0 right-0 h-full w-[560px] max-w-[55%] border-l border-slate-200 bg-white shadow-lg overflow-y-auto p-4 z-10">
              <SessionTelemetry sessionId={sid} refreshSignal={turnCount} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
