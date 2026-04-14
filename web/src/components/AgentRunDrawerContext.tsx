import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import AgentRunDetailDrawer from "./AgentRunDetailDrawer";

interface AgentRunDrawerCtx {
  open: (agentRunId: number) => void;
}

const ctx = createContext<AgentRunDrawerCtx | null>(null);

export function useAgentRunDrawer(): AgentRunDrawerCtx {
  const v = useContext(ctx);
  if (!v) {
    // Outside a provider — return a no-op so consumers don't crash in tests.
    return { open: () => {} };
  }
  return v;
}

export function AgentRunDrawerProvider({ children }: { children: ReactNode }) {
  const [agentRunId, setAgentRunId] = useState<number | null>(null);
  const open = useCallback((id: number) => setAgentRunId(id), []);
  const close = useCallback(() => setAgentRunId(null), []);
  return (
    <ctx.Provider value={{ open }}>
      {children}
      <AgentRunDetailDrawer agentRunId={agentRunId} onClose={close} />
    </ctx.Provider>
  );
}
