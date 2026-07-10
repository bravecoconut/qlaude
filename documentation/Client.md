# Frontend Web Application

The Qlaude client is a high-performance Flask web service that orchestrates the customer-facing SaaS interface. It acts as a presentation layer, delegating all heavy computational inference and search logic to the core API backend microservice.

## Service Entry Point

**Microservice Target:** `app/client/serv.py`  
**Internal Port Bind:** `5001`

## Application Routing

The frontend handles session initialization and interface rendering:

| Route | Behavior |
|-------|----------|
| `/` | Initial entry; redirects to secure workspace `/chat/new` |
| `/chat`, `/chat/` | Routing aliases; redirects to `/chat/new` |
| `/chat/new` | Provisions a new, isolated conversation workspace |
| `/chat/<session_id>` | Restores a persistent customer session, hydrating history on initialization |

The secure active session ID is seamlessly injected into the server-side template and consumed by the JavaScript application state on load.

## Interface Templates

**Resource Directory:** `app/client/templates/`

- `chat.html` — The primary single-page application (SPA) layout, featuring the navigation sidebar, real-time message stream, composition area, and premium feature toggles (GeepThink Reasoning, Real-Time Search).

The platform utilizes Jinja2 templating with dynamic `url_for` bindings for robust static asset delivery.

## Static Asset Delivery

**Resource Directory:** `app/client/static/`

| Asset | Role |
|-------|------|
| `app.js` | The core client-side controller. Manages session navigation, asynchronous history hydration, SSE stream parsing, and dynamic UI state. |
| `styles/style_light.css` | Light interface design system |
| `styles/style_dark.css` | Dark interface design system |
| `images/` | Brand assets and typography icons |

## Backend API Integration

The frontend client acts as an orchestrator, communicating with the core backend API (internally mapped to `http://127.0.0.1:5000` during development):

| Endpoint | Method | Operational Usage |
|----------|--------|-------|
| `/api/sessions` | GET | Hydrates the persistent sessions sidebar navigation |
| `/api/load_conversation_on_session_id` | GET | Restores complete message context for a selected workspace |
| `/chat` | POST | Dispatches customer payloads and establishes the SSE streaming connection |

## Interactive Customer Controls

- **New Workspace** — Clears the active UI state and re-routes to `/chat/new` for fresh interactions.
- **Think Toggle** — Attaches the `think: true` payload parameter to route the request through the advanced reasoning models.
- **Web Search Toggle** — Attaches the `search: true` parameter to invoke the backend RAG agents before generation.

Markdown payloads streamed from the API are compiled and rendered client-side using the highly optimized [marked.js](https://marked.js.org/) library.
