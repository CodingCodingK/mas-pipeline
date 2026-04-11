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

export interface RunDetail {
  run_id: string;
  project_id: number;
  pipeline: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
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
