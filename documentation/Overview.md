# Architecture Overview

Qlaude operates on a modern, decoupled SaaS architecture. It utilizes a frontend web application for user interactions and a separate, high-performance API backend handling AI inference, search integrations, user authentication, and billing.

## Directory Layout

| Path | Purpose |
|------|---------|
| `app/client/` | Frontend web service (templates, static assets, UI routing, billing portal integrations) |
| `app/server/` | Core REST API, session management, RAG search agent, subscription quota enforcement |
| `app/data/` | Data persistence layer (user accounts, session metadata, chat histories) |
| `sql/` | Database schemas and migrations |
| `logs/` | System monitoring and telemetry output |
| `assets/` | Documentation assets |

## Core Services

### Frontend Client (`app/client/`)

Serves the customer-facing HTML and static assets (port **5001**). It orchestrates the user experience, integrating with Google OAuth for identity and Stripe Checkout for subscription upgrades, while seamlessly communicating with the core API for chat streaming.

### Core API (`app/server/`)

The backend microservice (port **5000**) powers the platform's intelligence and business logic:

- Multi-tenant session lifecycle and conversation storage
- Subscription quota enforcement and feature gating
- Real-time web search orchestration (Search Agent)
- Streaming chat completions via SSE (Server-Sent Events)
- Automated session contextualization

### Data Layer (`app/data/`)

Our scalable data layer manages multiple SQLite databases optimized for concurrent workloads. It handles user profiles, subscription states, daily usage quotas, and isolated message histories for data privacy.

## Request Flow

```
Customer Browser
    │
    ├─► GET  /auth/google (Identity provider)
    ├─► GET  /api/sessions (Load workspace)
    ├─► POST /stripe/create-checkout (Subscription upgrades)
    └─► POST /chat  (SSE AI stream)
            │
            ├─► Quota & Feature Authorization
            ├─► [Search enabled]  search_agent → web tools
            ├─► LLM completion (streamed reasoning and content)
            └─► Persist interaction data and update usage limits
```

1. The customer authenticates and loads their active session workspace.
2. Messages sent to `/chat` are first validated against the user's active subscription tier (Free, Basic, Plus).
3. If Search is active and authorized, the search agent queries external sources before inference.
4. The API streams real-time reasoning (Think) and final responses back to the client.
5. Turns and usage metrics are securely recorded.

## Architectural Principles

- **Microservice Separation** — The frontend client and core API scale independently.
- **Data Privacy & Tenant Isolation** — Conversations are isolated in dedicated session structures.
- **Subscription-First** — Deep Stripe integration ensures quotas and billing are handled seamlessly at the API edge.
- **Provider Agnostic** — Inference requests can be routed to any compatible LLM backend depending on load and tier requirements.
