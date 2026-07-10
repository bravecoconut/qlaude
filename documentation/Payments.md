# Subscription Management & Billing

Qlaude's SaaS monetization model is powered by a robust **Stripe** integration, enabling flexible, tiered subscription plans for our customers.

## Platform Subscription Tiers

| Tier | Price | Daily Interaction Quota | RAG Search Access | Think Reasoning | Concurrent Sessions |
|------|-------|-------------|--------|-----------|----------|
| **Free** | ₹0 | 15 Interactions | ❌ | ❌ | 3 |
| **Basic** | ₹499/mo | 150 Interactions | ✅ | ✅ | 50 |
| **Plus** | ₹999/mo | Unlimited | ✅ | ✅ | Unlimited |

## Automated Checkout Flow

```
Pricing Portal → POST /stripe/create-checkout → Stripe Hosted Checkout → Platform Webhook → Quota Updated
```

1. Customers access the `/pricing` portal and initiate an upgrade (e.g., "Upgrade to Plus").
2. The platform generates a secure Stripe Checkout Session via `POST /stripe/create-checkout`.
3. The platform maps the customer to an existing Stripe identity or provisions a new one.
4. The customer completes the transaction on Stripe's PCI-compliant hosted checkout interface.
5. Stripe asynchronously broadcasts a `checkout.session.completed` webhook.
6. The platform's webhook listener processes the payload and instantly upgrades the customer's capabilities in the `users.db` data layer.
7. The customer returns to the application via the `/stripe/success` path and is granted immediate access to their new features.

## Webhook Architecture

To ensure data integrity between the platform and the payment gateway, we process the following Stripe webhooks:

| Event | System Action |
|-------|--------|
| `checkout.session.completed` | Provision subscription record and activate new tier limits |
| `customer.subscription.updated` | Reconcile tier changes (upgrades/downgrades) and payment status |
| `customer.subscription.deleted` | Revoke premium capabilities and gracefully fallback to the Free tier |

## Edge Quota Enforcement

To protect platform resources, strict quota enforcement is evaluated at the API edge before any compute is consumed:

1. The API extracts the authenticated customer ID from the `/chat` request.
2. The platform executes a synchronous quota validation checking:
   - Available daily interactions against the customer's active tier.
   - Authorization to utilize premium models (GeepThink) and Search endpoints.
3. If quota limits are exceeded, the API intercepts the request and streams an actionable error event to the client:

```json
{
    "error": "You've reached your daily limit for this tier.",
    "error_type": "quota_exceeded",
    "quota": { "allowed": false, "used": 15, "limit": 15, "plan": "free" }
}
```

4. Upon successful interaction, telemetry is updated, and the new quota state is appended to the stream:

```json
{
    "quota_update": { "allowed": true, "used": 8, "limit": 150, "plan": "basic" }
}
```

## Customer Billing Portal

Customers on paid tiers have full self-serve control over their billing lifecycle (invoices, payment methods, cancellations) via the Stripe Customer Portal. Access is provisioned dynamically via `POST /stripe/create-portal`.

## Billing API Routes

| Route | Method | Security Level | Purpose |
|-------|--------|------|-------------|
| `/pricing` | GET | Protected | Tier comparison and checkout initiation |
| `/stripe/create-checkout` | POST | Protected | Orchestrates secure Checkout Session |
| `/stripe/success` | GET | Protected | Transaction success redirect handler |
| `/stripe/webhook` | POST | Public (Sig Validated) | Asynchronous event processing from Stripe |
| `/stripe/create-portal` | POST | Protected | Generates temporary Customer Portal session |

## Stripe Environment Configuration

Required deployment secrets:

```
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_SECRET_KEY=sk_test_...
STRIPE_BASIC_PRICE_ID=price_...
STRIPE_PLUS_PRICE_ID=price_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

## Data Persistence

Customer billing state is persisted in `app/data/users.db`:

- **`subscriptions`**: Authoritative record of Stripe subscription IDs, bound price IDs, service statuses, and renewal periods.
- **`usage`**: Ephemeral table tracking rolling daily interaction metrics.

See [Data Architecture](Data.md) for comprehensive schema documentation.
