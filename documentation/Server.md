# API Backend Service

The Qlaude API Backend is a robust, isolated microservice responsible for orchestrating LLM inference, real-time web search capabilities (RAG), secure session management, and streaming low-latency responses back to the client interface.

## Service Entry Point

**Microservice Target:** `app/server/server.py`  
**Internal Port Bind:** `5000`

## REST API Endpoints

| Endpoint | HTTP Method | Operational Description |
|----------|--------|-------------|
| `/api/sessions` | GET | Enumerates active customer workspaces, including semantic names and timestamps |
| `/api/load_conversation_on_session_id` | GET | Rehydrates complete interaction histories for a specific workspace |
| `/chat` | POST | Ingests customer prompts, executes RAG/Reasoning pipelines, and streams responses (SSE) |

### POST `/chat` Payload Structure

```json
{
  "session_id": "S20260623015752524927",
  "user_input": "Customer inquiry text",
  "think": false,
  "search": false
}
```

A null or omitted `session_id` instructs the backend to provision a new, secure workspace for the incoming interaction.

### Server-Sent Events (SSE) Stream Architecture

The `/chat` endpoint utilizes high-performance SSE to deliver chunked payloads:

| Event Identifier | Description |
|-------------|-------------|
| `check_session` | Emits workspace validation and provisioning status |
| `searching` | Signals activation of the RAG search agent |
| `sources` | Streams individual citation links retrieved during search |
| `search_not_required` | Indicates the search agent determined external data was unnecessary |
| `reasoning_chunk` | Streams incremental tokens from the Think reasoning models |
| `content_chunk` | Streams incremental tokens for the final assistant response |

## Core Platform Modules

### `main_manager.py` (Session & Persistence Lifecycle)

Responsible for executing the core business logic of data persistence and context management.

- **`GenMan`** — Provisions workspaces, constructs LLM context windows, persists conversational turns, and catalogs active sessions. Dynamically injects system instructions based on active feature toggles (Think/Search).
- **`Man`** — Extends `GenMan` capabilities to securely rehydrate full conversational records (including internal reasoning traces and source citations) for the frontend client.

Workspaces are securely partitioned using dedicated tables mapped to the globally unique session ID.

### `search_agent.py` (Orchestration & RAG)

Manages autonomous tool-calling when the Search tier feature is requested. The LLM evaluates registered tools and dispatches requests; retrieved data is structured and injected into the primary generation pipeline with strict citation mandates.

Agent capabilities are defined in the schema registry at `app/server/json/tools.json`.

### `search/search.py` (External Data Acquisition)

Executes the physical acquisition of external data for the RAG pipeline:

- Proxies DuckDuckGo queries for text and news data.
- Executes distributed page scraping via `trafilatura`.
- Leverages `spaCy` NLP models for semantic keyword filtering.
- Implements section-based extraction algorithms for processing long-form documents.

These capabilities are securely exposed to the inference models via `build_search_tools()`.

### `assets.py`

Utility class for dynamically injecting localized placeholder content from `chat_comment.db` into the UI.

### `utills/utills.py`

Shared infrastructure utilities for standardized telemetry, logging, and debug serialization.

## Platform Environment Configuration

Runtime configurations managed via `.env`:

| Variable | System Purpose |
|----------|-------------|
| `BASE_URL` | Upstream OpenAI-compatible inference endpoint |
| `API_KEY` | Upstream authentication secret |
| `RESONNING_MODEL` | Specified model identifier for Think premium reasoning |
| `NON_RESONNING_MODEL` | Default model identifier for standard inference |

## Automated Workspace Contextualization

Upon workspace creation, the `session_name_gen()` async worker requests a concise, semantic title from the LLM based on the initial customer prompt, ensuring an organized workspace environment. If the upstream provider is degraded, the platform gracefully degrades to a default `"New Chat"` label.
