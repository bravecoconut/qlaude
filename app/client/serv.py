"""Qlaude web client with Google OAuth and Stripe integration.

Serves the chat UI on port 5001.  All inference is handled by the API
server on port 5000.  This module adds:

* Google OAuth 2.0 login / logout
* Stripe Checkout for plan upgrades
* Stripe webhooks for subscription lifecycle
* User info / quota API for the frontend
"""

import json
import os
import secrets
import sys
from functools import wraps

import requests as http_requests
import stripe
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    Response,
    session,
    stream_with_context,
    url_for,
)
from dotenv import load_dotenv

# ── Allow imports from sibling packages ──────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "server"))
from user_manager import UserManager  # noqa: E402
from main_manager import GenMan  # noqa: E402

load_dotenv()

# ── Configuration ────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = "http://127.0.0.1:5001/auth/google/callback"

STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_BASIC_PRICE_ID = os.getenv("STRIPE_BASIC_PRICE_ID", "")
STRIPE_PLUS_PRICE_ID = os.getenv("STRIPE_PLUS_PRICE_ID", "")

stripe.api_key = STRIPE_SECRET_KEY

FLASK_SECRET_KEY = os.getenv(
    "FLASK_SECRET_KEY", secrets.token_hex(32)
)
API_SERVER_URL = os.getenv("API_SERVER_URL", "http://127.0.0.1:5000")

app = Flask(__name__)
app.secret_key = FLASK_SECRET_KEY

user_manager = UserManager()

# ── Price → plan mapping ─────────────────────────────────────────────
PRICE_TO_PLAN = {
    STRIPE_BASIC_PRICE_ID: "basic",
    STRIPE_PLUS_PRICE_ID: "plus",
}

PLAN_TO_PRICE = {
    "basic": STRIPE_BASIC_PRICE_ID,
    "plus": STRIPE_PLUS_PRICE_ID,
}


# ─────────────────────────────────────────────────────────────────────
#  Auth decorator
# ─────────────────────────────────────────────────────────────────────

def login_required(f):
    """Redirect to /login if the user is not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────────────
#  Google OAuth 2.0
# ─────────────────────────────────────────────────────────────────────

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


@app.route("/login")
def login_page():
    """Render the login page.  Logged-in users go straight to chat."""
    if "user_id" in session:
        return redirect(url_for("new_chat"))
    error = request.args.get("error", "")
    return render_template("login.html", error=error)


@app.route("/auth/google")
def auth_google():
    """Redirect the browser to Google's OAuth consent screen."""
    state = secrets.token_urlsafe(32)
    session["oauth_state"] = state

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "state": state,
        "prompt": "select_account",
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return redirect(f"{GOOGLE_AUTH_URL}?{query}")


@app.route("/auth/google/callback")
def auth_google_callback():
    """Handle the OAuth callback from Google."""
    error = request.args.get("error")
    if error:
        return redirect(url_for("login_page", error=f"Google auth error: {error}"))

    code = request.args.get("code")
    state = request.args.get("state")

    if not code:
        return redirect(url_for("login_page", error="No authorization code received."))

    # Verify state
    if state != session.pop("oauth_state", None):
        return redirect(url_for("login_page", error="Invalid OAuth state. Please try again."))

    # Exchange code for tokens
    try:
        token_resp = http_requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()
    except Exception as e:
        print(f"[AUTH] Token exchange failed: {e}")
        return redirect(url_for("login_page", error="Failed to authenticate with Google. Please try again."))

    access_token = tokens.get("access_token")
    if not access_token:
        return redirect(url_for("login_page", error="No access token received from Google."))

    # Fetch user profile
    try:
        profile_resp = http_requests.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        profile_resp.raise_for_status()
        profile = profile_resp.json()
    except Exception as e:
        print(f"[AUTH] Profile fetch failed: {e}")
        return redirect(url_for("login_page", error="Failed to fetch your Google profile. Please try again."))

    google_id = profile.get("id", "")
    email = profile.get("email", "")
    name = profile.get("name", "User")
    picture = profile.get("picture", "")

    if not google_id:
        return redirect(url_for("login_page", error="Could not retrieve your Google account ID."))

    # Upsert user
    user = user_manager.get_or_create_user(
        google_id=google_id,
        email=email,
        name=name,
        picture=picture,
    )

    session["user_id"] = user["id"]
    session["google_id"] = google_id
    session["user_name"] = name
    session["user_picture"] = picture
    session["user_email"] = email

    print(f"[AUTH] User logged in: {name} ({email})")
    return redirect(url_for("new_chat"))


@app.route("/auth/logout")
def auth_logout():
    """Clear the session and redirect to login."""
    session.clear()
    return redirect(url_for("login_page"))


# ─────────────────────────────────────────────────────────────────────
#  Stripe Checkout & Webhooks
# ─────────────────────────────────────────────────────────────────────

@app.route("/stripe/create-checkout", methods=["POST"])
@login_required
def stripe_create_checkout():
    """Create a Stripe Checkout Session for the selected plan."""
    plan = request.form.get("plan", "")
    price_id = PLAN_TO_PRICE.get(plan)

    if not price_id:
        return redirect(url_for("pricing_page", error="Invalid plan selected."))

    user_id = session["user_id"]
    user = user_manager.get_user_by_id(user_id)

    if not user:
        return redirect(url_for("pricing_page", error="User not found. Please log in again."))

    try:
        # Get or create Stripe customer
        stripe_customer_id = user.get("stripe_customer_id", "")
        if not stripe_customer_id:
            customer = stripe.Customer.create(
                email=user["email"],
                name=user["name"],
                metadata={"qlaude_user_id": str(user_id)},
            )
            stripe_customer_id = customer.id
            user_manager.set_stripe_customer_id(user_id, stripe_customer_id)

        checkout_session = stripe.checkout.Session.create(
            customer=stripe_customer_id,
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="subscription",
            success_url="http://127.0.0.1:5001/stripe/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="http://127.0.0.1:5001/pricing",
            metadata={"qlaude_user_id": str(user_id), "plan": plan},
        )

        return redirect(checkout_session.url, code=303)

    except stripe.error.StripeError as e:
        print(f"[STRIPE] Checkout error: {e}")
        return redirect(url_for("pricing_page", error=f"Payment error: {str(e)}"))
    except Exception as e:
        print(f"[STRIPE] Unexpected error: {e}")
        return redirect(url_for("pricing_page", error="Something went wrong. Please try again."))


@app.route("/stripe/success")
@login_required
def stripe_success():
    """Handle the redirect after a successful checkout."""
    return redirect(url_for("pricing_page", success="Payment successful! Your plan has been upgraded."))


@app.route("/stripe/webhook", methods=["POST"])
def stripe_webhook():
    """Process Stripe webhook events for subscription lifecycle."""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        print("[STRIPE WEBHOOK] Invalid payload")
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        print("[STRIPE WEBHOOK] Invalid signature")
        return jsonify({"error": "Invalid signature"}), 400

    event_type = event["type"]
    data = event["data"]["object"]

    print(f"[STRIPE WEBHOOK] Event: {event_type}")

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data)
    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        _handle_subscription_change(data)

    return jsonify({"status": "ok"}), 200


def _handle_checkout_completed(checkout_data):
    """Process a completed checkout — link subscription to user."""
    checkout_data = checkout_data.to_dict()
    customer_id = checkout_data.get("customer", "")
    subscription_id = checkout_data.get("subscription", "")
    metadata = checkout_data.get("metadata", {})
    user_id = metadata.get("qlaude_user_id")
    plan = metadata.get("plan", "")

    if not user_id or not subscription_id:
        print("[STRIPE WEBHOOK] Missing qlaude_user_id or subscription_id in checkout")
        return

    user_id = int(user_id)

    # Ensure the Stripe customer is linked to the user
    if customer_id:
        existing = user_manager.get_user_by_id(user_id)
        if existing and not existing.get("stripe_customer_id"):
            user_manager.set_stripe_customer_id(user_id, customer_id)
            print(f"[STRIPE WEBHOOK] Linked customer {customer_id} to user {user_id}")

    try:
        sub = stripe.Subscription.retrieve(subscription_id).to_dict()
        price_id = sub["items"]["data"][0]["price"]["id"] if sub["items"]["data"] else ""
        resolved_plan = PRICE_TO_PLAN.get(price_id, "")

        # Use the plan from PRICE_TO_PLAN if found, otherwise fall back to
        # the plan from the checkout metadata.  Never default to "free" here
        # — the user just paid.
        if resolved_plan:
            plan = resolved_plan
        elif not plan:
            print(f"[STRIPE WEBHOOK] WARNING: Could not resolve plan from price_id={price_id}, no metadata plan")
            return

        status = sub.get("status", "active")
        period_start = sub.get("current_period_start", "")
        period_end = sub.get("current_period_end", "")

        user_manager.upsert_subscription(
            user_id=user_id,
            stripe_subscription_id=subscription_id,
            stripe_price_id=price_id,
            plan=plan,
            status=status,
            current_period_start=str(period_start),
            current_period_end=str(period_end),
        )
        print(f"[STRIPE WEBHOOK] Subscription {subscription_id} → plan={plan}, status={status} for user {user_id}")
    except Exception as e:
        print(f"[STRIPE WEBHOOK] Error processing checkout: {e}")


def _handle_subscription_change(sub_data):
    """Handle subscription updates and cancellations."""
    sub_data = sub_data.to_dict()
    subscription_id = sub_data.get("id", "")
    customer_id = sub_data.get("customer", "")
    status = sub_data.get("status", "")
    price_id = ""

    if sub_data.get("items", {}).get("data"):
        price_id = sub_data["items"]["data"][0]["price"]["id"]

    resolved_plan = PRICE_TO_PLAN.get(price_id, "")
    period_start = sub_data.get("current_period_start", "")
    period_end = sub_data.get("current_period_end", "")

    # Find user by Stripe customer ID
    user = user_manager.get_user_by_stripe_customer_id(customer_id)
    if not user:
        print(f"[STRIPE WEBHOOK] No user found for customer {customer_id}")
        return

    # Determine the plan: use the price lookup if it matched, otherwise
    # preserve the plan already recorded on the existing subscription or
    # the user's current plan.  NEVER default to "free" — that would
    # revert a paid upgrade whenever Stripe sends a subscription.updated
    # event with a price_id we can't resolve.
    if resolved_plan:
        plan = resolved_plan
    else:
        existing_sub = user_manager.get_active_subscription(user["id"])
        if existing_sub:
            plan = existing_sub["plan"]
            print(f"[STRIPE WEBHOOK] price_id lookup missed, preserving existing plan={plan}")
        else:
            plan = user.get("plan") or "free"
            print(f"[STRIPE WEBHOOK] price_id lookup missed, no active sub, using user plan={plan}")

    user_manager.upsert_subscription(
        user_id=user["id"],
        stripe_subscription_id=subscription_id,
        stripe_price_id=price_id,
        plan=plan,
        status=status,
        current_period_start=str(period_start),
        current_period_end=str(period_end),
    )
    print(f"[STRIPE WEBHOOK] Sub {subscription_id} updated: status={status}, plan={plan}")


# ─────────────────────────────────────────────────────────────────────
#  User & Quota API
# ─────────────────────────────────────────────────────────────────────

@app.route("/api/user")
@login_required
def api_user():
    """Return current user info, plan, and quota for the frontend."""
    user_id = session["user_id"]
    user = user_manager.get_user_by_id(user_id)

    if not user:
        return jsonify({"error": "User not found"}), 404

    quota = user_manager.check_quota(user_id)

    return jsonify({
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "picture": user["picture"],
            "plan": user["plan"] or "free",
        },
        "quota": quota,
    })


# ─────────────────────────────────────────────────────────────────────
#  Authenticated API proxy (injects user_id from server session)
# ─────────────────────────────────────────────────────────────────────

@app.route("/api/sessions")
@login_required
def api_sessions():
    """Return chat sessions owned by the logged-in user."""
    user_id = session["user_id"]
    return jsonify(GenMan(user_id=user_id).all_session())


@app.route("/api/load_conversation_on_session_id")
@login_required
def api_load_conversation():
    """Load conversation history for a session owned by the logged-in user."""
    user_id = session["user_id"]
    session_id = request.args.get("session_id")

    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    genman = GenMan(user_id=user_id, session=session_id)
    if not genman.session_belongs_to_user(session_id, user_id):
        return jsonify({"error": "Session not found or access denied"}), 403

    from main_manager import Man

    conversation_data = Man(session=session_id, user_id=user_id).load_conversation()
    if isinstance(conversation_data, dict) and conversation_data.get("error"):
        return jsonify(conversation_data), 403

    return jsonify(
        {"conversation": conversation_data, "redirect_url": f"/chat/{session_id}"}
    )


@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat_proxy():
    """Proxy chat requests to the API server with the authenticated user_id."""
    user_id = session["user_id"]
    body = request.get_json() or {}
    body["user_id"] = user_id

    try:
        upstream = http_requests.post(
            f"{API_SERVER_URL}/chat",
            json=body,
            stream=True,
            timeout=300,
        )
    except http_requests.RequestException as exc:
        print(f"[CHAT PROXY] Upstream error: {exc}")
        return jsonify({"error": "Chat service unavailable"}), 502

    def generate():
        for chunk in upstream.iter_content(chunk_size=None):
            if chunk:
                yield chunk

    return Response(
        stream_with_context(generate()),
        mimetype=upstream.headers.get("Content-Type", "text/event-stream"),
        status=upstream.status_code,
    )


# ─────────────────────────────────────────────────────────────────────
#  Pages
# ─────────────────────────────────────────────────────────────────────

@app.route("/chat/<session_id>")
@login_required
def home(session_id):
    """Render an existing conversation."""
    if session_id != "new":
        user_id = session["user_id"]
        genman = GenMan(user_id=user_id, session=session_id)
        if not genman.session_belongs_to_user(session_id, user_id):
            flash("That session does not exist or belongs to another account.")
            return redirect(url_for("new_chat"))

    return render_template(
        "chat.html",
        session_id=session_id,
        user_name=session.get("user_name", ""),
        user_picture=session.get("user_picture", ""),
    )


@app.route("/chat/new")
@login_required
def new_chat():
    """Render a blank conversation."""
    return render_template(
        "chat.html",
        session_id="new",
        user_name=session.get("user_name", ""),
        user_picture=session.get("user_picture", ""),
    )


@app.route("/chat/")
@app.route("/chat")
@login_required
def redirect_to_new():
    """Normalize /chat paths to the new-chat route."""
    return redirect(url_for("new_chat"))


@app.route("/")
def root():
    """Redirect the site root to chat (or login if not authenticated)."""
    if "user_id" in session:
        return redirect(url_for("new_chat"))
    return redirect(url_for("login_page"))


@app.route("/pricing")
@login_required
def pricing_page():
    """Render the pricing page with plan comparison."""
    user_id = session["user_id"]
    user = user_manager.get_user_by_id(user_id)
    current_plan = user["plan"] if user else "free"

    error = request.args.get("error", "")
    success = request.args.get("success", "")

    return render_template(
        "pricing.html",
        current_plan=current_plan or "free",
        error=error,
        success=success,
    )


# ─────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5001)
