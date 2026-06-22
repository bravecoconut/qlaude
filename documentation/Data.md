# Data Layer

GeepSeek stores all conversation data locally in SQLite. No external database is required.

## Location

**Directory:** `app/data/`

| Database | Purpose |
|----------|---------|
| `database.db` | Message history (one table per session) |
| `session_info.db` | Session metadata (ID, title, timestamps) |
| `chat_comment.db` | Optional placeholder comments for empty chat state |

## `database.db`

Each chat session has its own table, named with the session ID (for example, `S20260623015752524927`).

### Message table schema

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key, auto-increment |
| `role` | VARCHAR | Message role: `user`, `assistant`, or `system` |
| `content` | TEXT | Message body |
| `thought` | TEXT | Reasoning trace when GeepThink is enabled |
| `source` | TEXT | JSON array of search source references |

Tables are created on first message for a new session.

## `session_info.db`

### Table: `info`

| Column | Type | Description |
|--------|------|-------------|
| `session_id` | VARCHAR | Unique session identifier |
| `session_name` | VARCHAR | Display title (LLM-generated or default) |
| `date_created` | VARCHAR | Session creation timestamp |
| `date_last_commit` | VARCHAR | Last message timestamp |

Updated on every saved turn.

## `chat_comment.db`

### Table: `comments`

| Column | Type | Description |
|--------|------|-------------|
| `comment` | VARCHAR | Short placeholder text for the new-chat screen |

## Schema definitions

**Directory:** `sql/`

| File | Creates |
|------|---------|
| `session_info.sql` | `info` table in `session_info.db` |
| `chat_comment.sql` | `comments` table in `chat_comment.db` |

Run these scripts once when initializing a fresh deployment if the database files do not yet exist.

## Concurrency

Connections use WAL journal mode (`PRAGMA journal_mode=WAL`) to allow concurrent reads during writes.

## Session ID format

New sessions receive IDs in the form `S` + timestamp with microsecond precision, for example `S20260623015752524927`.
