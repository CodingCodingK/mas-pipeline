# mas-pipeline

A configurable Multi-Agent System engine for content production pipelines.

Define agent roles in Markdown, wire them into pipelines with YAML — zero code to add a new workflow.

## Features

- **Agent Loop (ReAct)** — autonomous LLM agents with tool calling
- **Pipeline Engine** — YAML-configured multi-agent workflows
- **Multi-Provider LLM** — Anthropic / OpenAI / Gemini / DeepSeek / Ollama
- **RAG** — multimodal document parsing + pgvector retrieval
- **Memory** — cross-session persistent knowledge
- **Task System** — DAG-based multi-agent coordination
- **LangGraph Integration** — checkpoint + human-in-the-loop for critical workflows
- **Sandbox** — kernel-level confinement of ShellTool via bubblewrap (Linux) / sandbox-exec (macOS)
- **Telemetry** — token usage, latency, tool call tracking with web dashboard

## Sandbox

ShellTool commands are wrapped in a kernel-level sandbox so that path and network confinement does not depend on string-pattern Permission rules.

| Platform | Backend | How to install |
|---|---|---|
| Linux / WSL2 | `bubblewrap` (`bwrap`) | `apt install bubblewrap` (or `dnf install bubblewrap`) |
| macOS | `sandbox-exec` | built in (`/usr/bin/sandbox-exec`) |
| Windows | — | passthrough with one-time warning at startup |

Configuration in `config/settings.yaml`:

```yaml
sandbox:
  enabled: true              # default — wrap when supported
  fail_if_unavailable: false # set true to refuse boot when bwrap is missing
```

The sandbox derives its writable / readable path lists from your active Permission rules: `Edit("projects/**")` becomes `--bind projects projects` automatically. Network is fully unshared inside the sandbox; tools that need network (WebSearch, MCP) run in the parent Python process and bypass it.

## Prebuilt Pipelines

- **Blog Generation**: Researcher → Writer → Reviewer → Editor
- **Courseware Exam**: Parser (multimodal) → Analyzer → ExamGenerator → Reviewer

## Tech Stack

Python 3.12 · FastAPI · PostgreSQL · pgvector · Redis · LangGraph · Docker Compose

## Status

🚧 In development
