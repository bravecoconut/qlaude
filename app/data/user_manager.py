"""User, subscription, and usage management for Qlaude SaaS.

Handles user accounts (backed by Google OAuth), Stripe subscription
state, and per-day quota enforcement.  All data lives in a shared
``users.db`` SQLite database stored alongside the other app databases.
"""

import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "users.db"
SCHEMA_PATH = BASE_DIR.parent.parent / "sql" / "users.sql"

# ── Plan quotas ──────────────────────────────────────────────────────
PLAN_LIMITS = {
    "free": {
        "messages_per_day": 15,
        "search_allowed": False,
        "think_allowed": False,
        "max_sessions": 3,
    },
    "basic": {
        "messages_per_day": 150,
        "search_allowed": True,
        "think_allowed": True,
        "max_sessions": 50,
    },
    "plus": {
        "messages_per_day": -1,  # unlimited
        "search_allowed": True,
        "think_allowed": True,
        "max_sessions": -1,  # unlimited
    },
}


class UserManager:
    """CRUD operations for users, subscriptions, and daily usage."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self._ensure_schema()

    # ── helpers ───────────────────────────────────────────────────────

    def _get_db(self):
        """Return a connection with WAL mode and foreign keys enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self):
        """Create tables if they don't exist yet."""
        conn = self._get_db()
        with open(SCHEMA_PATH, "r") as f:
            conn.executescript(f.read())
        conn.commit()
        conn.close()

    # ── user CRUD ────────────────────────────────────────────────────

    def get_or_create_user(
        self,
        google_id: str,
        email: str,
        name: str,
        picture: str = "",
    ) -> dict:
        """Upsert a user from Google OAuth profile.  Returns the user row."""
        conn = self._get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM users WHERE google_id = ?", (google_id,))
        row = cur.fetchone()

        if row:
            # Update profile fields that may change
            cur.execute(
                "UPDATE users SET email=?, name=?, picture=?, updated_at=? WHERE google_id=?",
                (email, name, picture, datetime.now(timezone.utc).isoformat(), google_id),
            )
            conn.commit()
            cur.execute("SELECT * FROM users WHERE google_id = ?", (google_id,))
            row = cur.fetchone()
        else:
            cur.execute(
                "INSERT INTO users (google_id, email, name, picture) VALUES (?,?,?,?)",
                (google_id, email, name, picture),
            )
            conn.commit()
            cur.execute("SELECT * FROM users WHERE google_id = ?", (google_id,))
            row = cur.fetchone()

        user = dict(row)
        conn.close()
        return user

    def get_user_by_id(self, user_id: int) -> dict | None:
        """Fetch a single user by primary key."""
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_user_by_google_id(self, google_id: str) -> dict | None:
        """Fetch a single user by Google ID."""
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE google_id = ?", (google_id,))
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    def set_stripe_customer_id(self, user_id: int, stripe_customer_id: str):
        """Link a Stripe customer to a local user."""
        conn = self._get_db()
        conn.execute(
            "UPDATE users SET stripe_customer_id=?, updated_at=? WHERE id=?",
            (stripe_customer_id, datetime.now(timezone.utc).isoformat(), user_id),
        )
        conn.commit()
        conn.close()

    def set_user_plan(self, user_id: int, plan: str):
        """Update the user's current plan."""
        conn = self._get_db()
        conn.execute(
            "UPDATE users SET plan=?, updated_at=? WHERE id=?",
            (plan, datetime.now(timezone.utc).isoformat(), user_id),
        )
        conn.commit()
        conn.close()

    # ── subscription management ──────────────────────────────────────

    def upsert_subscription(
        self,
        user_id: int,
        stripe_subscription_id: str,
        stripe_price_id: str,
        plan: str,
        status: str,
        current_period_start: str = "",
        current_period_end: str = "",
    ):
        """Create or update a Stripe subscription record."""
        conn = self._get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT id FROM subscriptions WHERE stripe_subscription_id = ?",
            (stripe_subscription_id,),
        )
        existing = cur.fetchone()

        now = datetime.now(timezone.utc).isoformat()

        if existing:
            cur.execute(
                """UPDATE subscriptions
                   SET stripe_price_id=?, plan=?, status=?,
                       current_period_start=?, current_period_end=?, updated_at=?
                   WHERE stripe_subscription_id=?""",
                (
                    stripe_price_id,
                    plan,
                    status,
                    current_period_start,
                    current_period_end,
                    now,
                    stripe_subscription_id,
                ),
            )
        else:
            cur.execute(
                """INSERT INTO subscriptions
                   (user_id, stripe_subscription_id, stripe_price_id, plan, status,
                    current_period_start, current_period_end, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    user_id,
                    stripe_subscription_id,
                    stripe_price_id,
                    plan,
                    status,
                    current_period_start,
                    current_period_end,
                    now,
                    now,
                ),
            )

        conn.commit()
        conn.close()

        # Keep the user table in sync.
        #
        # Only update the plan when the subscription status is definitive:
        #   - active / trialing → apply the paid plan
        #   - canceled / unpaid / incomplete_expired → revert to free
        #   - incomplete / past_due / paused → leave the current plan alone;
        #     these are transient states and Stripe will follow up with
        #     another event once the situation resolves.
        if status in ("active", "trialing"):
            self.set_user_plan(user_id, plan)
        elif status in ("canceled", "unpaid", "incomplete_expired"):
            self.set_user_plan(user_id, "free")
        # "incomplete", "past_due", "paused" — do NOT change the plan

    def get_active_subscription(self, user_id: int) -> dict | None:
        """Return the active subscription for a user, if any."""
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM subscriptions WHERE user_id=? AND status='active' ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None

    # ── usage / quota ────────────────────────────────────────────────

    def get_today_usage(self, user_id: int) -> dict:
        """Return today's usage row, creating it if needed."""
        today = date.today().isoformat()
        conn = self._get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM usage WHERE user_id=? AND date=?", (user_id, today)
        )
        row = cur.fetchone()

        if not row:
            cur.execute(
                "INSERT INTO usage (user_id, date, messages_used, search_used, think_used) VALUES (?,?,0,0,0)",
                (user_id, today),
            )
            conn.commit()
            cur.execute(
                "SELECT * FROM usage WHERE user_id=? AND date=?", (user_id, today)
            )
            row = cur.fetchone()

        result = dict(row)
        conn.close()
        return result

    def increment_usage(self, user_id: int, field: str = "messages_used"):
        """Bump a usage counter for today."""
        today = date.today().isoformat()
        conn = self._get_db()

        # Ensure row exists
        conn.execute(
            "INSERT OR IGNORE INTO usage (user_id, date, messages_used, search_used, think_used) VALUES (?,?,0,0,0)",
            (user_id, today),
        )
        conn.execute(
            f"UPDATE usage SET {field} = {field} + 1 WHERE user_id=? AND date=?",
            (user_id, today),
        )
        conn.commit()
        conn.close()

    def check_quota(self, user_id: int) -> dict:
        """Check whether the user can send another message.

        Returns a dict with: ``allowed``, ``used``, ``limit``, ``plan``,
        ``search_allowed``, ``think_allowed``.
        """
        user = self.get_user_by_id(user_id)
        if not user:
            return {
                "allowed": False,
                "error": "User not found",
                "used": 0,
                "limit": 0,
                "plan": "free",
                "search_allowed": False,
                "think_allowed": False,
            }

        plan = user["plan"] or "free"
        limits = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])
        usage = self.get_today_usage(user_id)

        used = usage["messages_used"]
        limit = limits["messages_per_day"]
        allowed = (limit == -1) or (used < limit)

        return {
            "allowed": allowed,
            "used": used,
            "limit": limit,
            "plan": plan,
            "search_allowed": limits["search_allowed"],
            "think_allowed": limits["think_allowed"],
            "max_sessions": limits["max_sessions"],
        }

    def get_user_by_stripe_customer_id(self, stripe_customer_id: str) -> dict | None:
        """Fetch a user by their Stripe customer ID."""
        conn = self._get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM users WHERE stripe_customer_id = ?", (stripe_customer_id,)
        )
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
