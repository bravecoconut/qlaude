# Client

The GeepSeek client is a Flask application that renders the chat interface and delegates all inference to the API server.

## Entry point

**File:** `app/client/serv.py`  
**Port:** 5001

## Routes

| Route | Behavior |
|-------|----------|
| `/` | Redirects to `/chat/new` |
| `/chat`, `/chat/` | Redirects to `/chat/new` |
| `/chat/new` | New conversation; no session ID loaded |
| `/chat/<session_id>` | Existing conversation; history loaded on page init |

The active session ID is injected into the page template and consumed by `app.js` on load.

## Templates

**Directory:** `app/client/templates/`

- `chat.html` — Main chat layout: sidebar, message list, input area, and feature toggles (GeepThink, Search).

Templates use Jinja2 and Flask's `url_for` helper for static asset paths.

## Static assets

**Directory:** `app/client/static/`

| Asset | Role |
|-------|------|
| `app.js` | Session list, conversation loading, SSE streaming, UI toggles |
| `styles/style_light.css` | Light theme stylesheet |
| `styles/style_dark.css` | Dark theme stylesheet |
| `images/` | Branding and icons |

## API integration

The client calls the server at `http://127.0.0.1:5000` (or `http://localhost:5000` for chat):

| Endpoint | Method | Usage |
|----------|--------|-------|
| `/api/sessions` | GET | Populate the recent sessions sidebar |
| `/api/load_conversation_on_session_id` | GET | Restore messages for a session |
| `/chat` | POST | Send a message; receive SSE stream |

## User controls

- **New chat** — Clears the view and resets the URL to `/chat/new`.
- **GeepThink** — Sends `think: true` to use the reasoning model.
- **Search** — Sends `search: true` to run the search agent before generation.

Markdown in messages is rendered client-side with [marked.js](https://marked.js.org/).
