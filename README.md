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
- **Telemetry** — token usage, latency, tool call tracking with web dashboard

## Prebuilt Pipelines

- **Blog Generation**: Researcher → Writer → Reviewer → Editor
- **Courseware Exam**: Parser (multimodal) → Analyzer → ExamGenerator → Reviewer

## Tech Stack

Python 3.12 · FastAPI · PostgreSQL · pgvector · Redis · LangGraph · Docker Compose

## Status

🚧 In development
