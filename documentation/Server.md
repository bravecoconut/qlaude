# Server

The GeepSeek API server handles chat requests, optional web search, session management, and streaming responses.

## Entry point

**File:** `app/server/server.py`  
**Port:** 5000

## API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sessions` | GET | Returns all sessions with names and timestamps |
| `/api/load_conversation_on_session_id` | GET | Returns full message history for a session |
| `/chat` | POST | Processes a user message and streams the response (SSE) |

### POST `/chat` body

```json
{
  "session_id": "S20260623015752524927",
  "user_input": "Your message",
  "think": false,
  "search": false
}
```

An empty or missing `session_id` creates a new session on the first message.

### SSE event types

| Event field | Description |
|-------------|-------------|
| `check_session` | Session creation or validation result |
| `searching` | Search agent started |
| `sources` | Individual source link from search results |
| `search_not_required` | Search returned no usable results |
| `reasoning_chunk` | Incremental reasoning text (GeepThink) |
| `content_chunk` | Incremental assistant reply text |

## Core modules

### `main_manager.py`

Session and message persistence.

- **`GenMan`** — Creates sessions, loads conversation context for the LLM, saves turns, and lists sessions. Applies system instructions based on Think/Search flags.
- **`Man`** — Extends `GenMan` to load full conversation records (including thought and source fields) for the UI.

Each session uses a dedicated SQLite table named after its session ID.

### `search_agent.py`

Orchestrates tool-calling when Search mode is enabled. The model selects from registered search tools; results are structured and passed to the main completion as system context with citation rules.

Tool schemas are loaded from `app/server/json/tools.json`.

### `search/search.py`

Implements web search and page extraction:

- DuckDuckGo text and news queries
- Page scraping via trafilatura
- Optional keyword filtering with spaCy
- Section-based extraction for long documents

Exposed to the model through `build_search_tools()`.

### `assets.py`

Utility for reading random placeholder comments from `chat_comment.db` (reserved for future UI use).

### `model_response.py`

Legacy alternate API layout. The active production path is `server.py`.

### `utills/utills.py`

Shared helpers for file logging and debug serialization.

## Environment variables

Configured via `.env`:

| Variable | Purpose |
|----------|-------------|
| `BASE_URL` | OpenAI-compatible API base URL |
| `API_KEY` | Authentication key |
| `RESONNING_MODEL` | Model when GeepThink is enabled |
| `NON_RESONNING_MODEL` | Default model |

## Session naming

When a new session is created, `session_name_gen()` requests a short title from the LLM based on the first user message. On API failure, the title defaults to `"New Chat"`.
