# Identity & Authentication

Qlaude uses an enterprise-grade **Google OAuth 2.0** integration for secure, seamless customer authentication. All application routes (excluding public landing pages) are secured behind this authentication layer.

## Authentication Flow

```
Customer Browser → /auth/google → Google Consent → /auth/google/callback → Secure Session → /chat/new
```

1. Unauthenticated users attempting to access protected `/chat/*` paths are routed to the `/login` portal.
2. Selecting "Continue with Google" initiates the `/auth/google` flow.
3. The API constructs a secure Google OAuth URL requesting `openid`, `email`, and `profile` scopes, protected by a CSRF `state` token.
4. Google redirects back to the `/auth/google/callback` endpoint with a single-use authorization code.
5. The API exchanges the code for a secure access token, retrieves the customer's verified profile, and synchronizes the identity with the `users.db` data layer.
6. A cryptographically signed session is established containing the customer's ID, name, email, and avatar.
7. The customer is routed to their secure `/chat/new` workspace.

## Session State

The secure application session manages:

| Key | Value |
|-----|-------|
| `user_id` | Platform internal customer ID |
| `google_id` | Immutable Google account identifier |
| `user_name` | Customer display name |
| `user_picture` | Customer avatar URL |
| `user_email` | Verified customer email address |

## Core Identity Routes

| Route | Method | Security Level | Description |
|-------|--------|------|-------------|
| `/login` | GET | Public | Authentication portal |
| `/auth/google` | GET | Public | Initiates secure OAuth flow |
| `/auth/google/callback` | GET | Public | Processes OAuth authorization code |
| `/auth/logout` | GET | Public | Terminates session and clears state |
| `/api/user` | GET | Protected | Exposes customer profile and active usage quotas |

## Security & Error Handling

Authentication errors are robustly handled and gracefully presented on the login portal:

- **Missing authorization code** — Google authorization payload was incomplete.
- **Invalid OAuth state** — CSRF validation failure; mitigates potential replay attacks.
- **Token exchange failure** — Upstream network latency or Google API unavailability.
- **Profile fetch failure** — Identity verification incomplete.

## Environment Configuration

Critical security variables required for the OAuth integration:

```
GOOGLE_CLIENT_ID=<provided-by-gcp>
GOOGLE_CLIENT_SECRET=<provided-by-gcp>
FLASK_SECRET_KEY=<cryptographic-signing-key>
```

In production, ensure the OAuth callback URL matches the registered redirect URIs in the Google Cloud Console.

## Customer Data Layer

Customer identities are durably stored in the `app/data/users.db` relational database. See [Data Architecture](Data.md) for full schema definitions.

The identity table tracks:
- `google_id` — Immutable identity provider reference
- `email`, `name`, `picture` — Profile attributes (synchronized on login)
- `plan` — Active subscription tier (`free`, `basic`, `plus`)
- `stripe_customer_id` — Linked billing identity
