# Data Architecture

Qlaude's data infrastructure is built for reliability, scalability, and tenant isolation, ensuring that customer data is securely partitioned and efficiently accessible.

## Core Databases

**Data Storage Location:** `app/data/`

| Database | Primary Role |
|----------|---------|
| `database.db` | Customer message histories and AI reasoning traces (isolated by session) |
| `session_info.db` | Session metadata, workspace organization, and timestamp tracking |
| `users.db` | Customer identity, OAuth profiles, Stripe subscription states, and daily usage quotas |
| `chat_comment.db` | UI copy management and dynamic placeholder content |

## Storage Partitioning (`database.db`)

To ensure maximum tenant isolation and query performance, each customer chat session is provisioned its own dedicated table. Tables are identified by the globally unique session ID (e.g., `S20260623015752524927`).

### Session Table Schema

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `role` | VARCHAR | Context role (`user`, `assistant`, or `system`) |
| `content` | TEXT | Payload content |
| `thought` | TEXT | Think extended reasoning traces |
| `source` | TEXT | JSON structured citations from web search integrations |

Tables are dynamically provisioned upon the first interaction in a new session workspace.

## Identity & Billing (`users.db`)

Central to the SaaS platform, the users database manages authentication and revenue generation.

### Users Table
- **OAuth Identity**: `google_id`, `email`, `name`, `picture`
- **Subscription Tier**: `plan` (`free`, `basic`, `plus`)
- **Stripe Integration**: `stripe_customer_id`

### Subscriptions Table
Tracks Stripe subscription lifecycles, active price IDs, and billing periods to ensure accurate service delivery.

### Usage Limits Table
Enforces daily quotas for message counts, search invocations, and compute-heavy GeepThink queries based on the customer's active subscription tier.

## Session Management (`session_info.db`)

### `info` Table

| Column | Type | Description |
|--------|------|-------------|
| `session_id` | VARCHAR | Globally unique identifier |
| `session_name` | VARCHAR | AI-generated semantic session title |
| `date_created` | VARCHAR | Initialization timestamp |
| `date_last_commit` | VARCHAR | Most recent interaction timestamp (for sorting) |

## Database Initialization

Database schemas and initial state migrations are located in the `sql/` directory:

| File | Associated Database |
|------|---------|
| `session_info.sql` | `session_info.db` |
| `chat_comment.sql` | `chat_comment.db` |
| `users.sql` | `users.db` |

The platform automatically bootstraps missing tables on startup for seamless deployment scaling.

## Operational Tuning

The data layer uses Write-Ahead Logging (`PRAGMA journal_mode=WAL`) to guarantee high concurrency, enabling simultaneous read operations by the API while writing AI generation streams.
