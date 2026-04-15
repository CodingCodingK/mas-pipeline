// Hand-maintained mirrors of the Pydantic models in src/api/*.py.
// Update in lockstep when the backend changes.

export interface ProjectOut {
  id: number;
  name: string;
  description: string | null;
  pipeline: string;
  status: string;
}

export interface ProjectList {
  items: ProjectOut[];
}

export type SourceKind = "global" | "project-only" | "project-override" | "project";

export interface AgentItem {
  name: string;
  source: SourceKind;
  description: string;
  model_tier: string;
  tools: string[];
  readonly: boolean;
}

export interface ToolItem {
  name: string;
  description: string;
}

export interface ToolListResponse {
  items: ToolItem[];
}

export interface AgentListResponse {
  items: AgentItem[];
}

export interface AgentReadResponse {
  name: string;
  content: string;
  source: SourceKind;
}

export interface PipelineItem {
  name: string;
  source: SourceKind;
}

export interface PipelineListResponse {
  items: PipelineItem[];
}

export interface PipelineReadResponse {
  name: string;
  content: string;
  source: SourceKind;
}

export interface TriggerRunResponse {
  run_id: string;
}

export interface RunListItem {
  run_id: string;
  project_id: number;
  pipeline: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunListResponse {
  items: RunListItem[];
}

export interface RunDetail {
  run_id: string;
  project_id: number;
  pipeline: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  outputs: Record<string, string>;
  final_output: string;
  error: string | null;
  paused_at: string | null;
  paused_output: string;
}

export interface AgentReference {
  project_id: number | null;
  pipeline: string;
  role: string;
}

export interface InUseErrorBody {
  detail: string;
  references: AgentReference[];
}

export type ApiErrorBody = { detail: string } | InUseErrorBody | unknown;

// ── Agent runs ──

export interface AgentRunListItem {
  id: number;
  role: string;
  description: string | null;
  status: string;
  owner: string | null;
  result: string | null;
  tool_use_count: number;
  total_tokens: number;
  duration_ms: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface AgentRunListResponse {
  items: AgentRunListItem[];
}

export interface AgentRunDetail {
  id: number;
  run_id: number;
  role: string;
  description: string | null;
  status: string;
  owner: string | null;
  result: string | null;
  messages: Array<Record<string, unknown>>;
  tool_use_count: number;
  total_tokens: number;
  duration_ms: number;
  created_at: string | null;
  updated_at: string | null;
}

// ── Chat ──

export interface CreateSessionResponse {
  id: number;
  mode: string;
  session_key: string;
  conversation_id: number;
}

export interface SendMessageResponse {
  message_index: number;
}

