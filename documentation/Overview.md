# Architecture Overview

GeepSeek is a two-tier application: a Flask web client serves the UI, and a separate Flask API handles inference, search, and persistence.

## Directory layout

| Path | Purpose |
|------|---------|
| `app/client/` | Web UI (templates, static assets, routing) |
| `app/server/` | REST API, session management, search agent, LLM integration |
| `app/data/` | SQLite databases for conversations and session metadata |
| `sql/` | Initial database schemas |
| `logs/` | Application log output |
| `assets/` | README and documentation images |

## Components

### Client (`app/client/`)

Serves HTML and static assets on port **5001**. The browser communicates with the API on port **5000** for sessions, history, and chat streaming.

### Server (`app/server/`)

Runs on port **5000**. Responsibilities include:

- Session lifecycle and conversation storage
- Optional web search via the search agent
- Streaming chat completions through an OpenAI-compatible client
- Automatic session title generation for new conversations

### Data layer (`app/data/`)

Three SQLite databases store chat messages, session metadata, and optional UI comments. Each chat session maps to a dedicated message table keyed by session ID.

## Request flow

```
Browser (port 5001)
    │
    ├─► GET  /api/sessions
    ├─► GET  /api/load_conversation_on_session_id
    └─► POST /chat  (SSE stream)
            │
            ├─► [Search enabled]  search_agent → web tools
            ├─► LLM completion (streamed)
            └─► Persist user + assistant messages
```

1. The user opens a chat page; the client loads session list and history from the API.
2. On send, the client POSTs to `/chat` with session ID, message, and feature flags.
3. If Search is on, the search agent retrieves web content before the main model responds.
4. The server streams reasoning and content chunks as SSE events.
5. Completed turns are written to SQLite.

## Design principles

- **Separation of concerns** — UI and API run as independent processes.
- **Local-first persistence** — No external database required for development.
- **Provider agnostic** — Any OpenAI-compatible endpoint can serve as the model backend.
