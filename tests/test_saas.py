"""Validation tests for Qlaude SaaS features.

Tests the user manager (database), quota enforcement, and route
configuration without requiring live Google/Stripe credentials.

Run from the project root:
    python -m pytest tests/test_saas.py -v
"""

import json
import os
import sys
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Setup paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "app" / "data"))
sys.path.insert(0, str(PROJECT_ROOT / "app" / "client"))
sys.path.insert(0, str(PROJECT_ROOT / "app" / "server"))


# ═════════════════════════════════════════════════════════════════════
#  1. UserManager unit tests
# ═════════════════════════════════════════════════════════════════════

from user_manager import UserManager, PLAN_LIMITS


@pytest.fixture
def tmp_db(tmp_path):
    """Create a UserManager with a temp database."""
    db_path = tmp_path / "test_users.db"
    # Copy the schema file to where UserManager expects it
    schema_src = PROJECT_ROOT / "sql" / "users.sql"
    schema_dst = tmp_path / "sql"
    schema_dst.mkdir(parents=True)
    shutil.copy(schema_src, schema_dst / "users.sql")

    # Patch SCHEMA_PATH so UserManager can find the schema
    with patch("user_manager.SCHEMA_PATH", schema_dst / "users.sql"):
        mgr = UserManager(db_path=db_path)
    yield mgr


class TestUserCreation:
    """Test user CRUD operations."""

    def test_create_new_user(self, tmp_db):
        """New user should be created with free plan."""
        user = tmp_db.get_or_create_user(
            google_id="g_123",
            email="test@example.com",
            name="Test User",
            picture="https://example.com/pic.jpg",
        )
        assert user["google_id"] == "g_123"
        assert user["email"] == "test@example.com"
        assert user["name"] == "Test User"
        assert user["plan"] == "free"
        assert user["id"] is not None

    def test_upsert_existing_user(self, tmp_db):
        """Re-login should update profile, not duplicate."""
        user1 = tmp_db.get_or_create_user("g_123", "old@test.com", "Old Name", "")
        user2 = tmp_db.get_or_create_user("g_123", "new@test.com", "New Name", "pic.jpg")

        assert user1["id"] == user2["id"]
        assert user2["email"] == "new@test.com"
        assert user2["name"] == "New Name"
        assert user2["picture"] == "pic.jpg"

    def test_get_user_by_id(self, tmp_db):
        """Lookup by primary key should work."""
        user = tmp_db.get_or_create_user("g_456", "a@b.com", "A", "")
        found = tmp_db.get_user_by_id(user["id"])
        assert found is not None
        assert found["google_id"] == "g_456"

    def test_get_user_by_id_not_found(self, tmp_db):
        """Non-existent user returns None."""
        assert tmp_db.get_user_by_id(9999) is None

    def test_get_user_by_google_id(self, tmp_db):
        """Lookup by Google ID should work."""
        tmp_db.get_or_create_user("g_789", "x@y.com", "X", "")
        found = tmp_db.get_user_by_google_id("g_789")
        assert found is not None
        assert found["email"] == "x@y.com"

    def test_set_stripe_customer_id(self, tmp_db):
        """Stripe customer ID should be persisted."""
        user = tmp_db.get_or_create_user("g_100", "s@t.com", "S", "")
        tmp_db.set_stripe_customer_id(user["id"], "cus_test123")
        updated = tmp_db.get_user_by_id(user["id"])
        assert updated["stripe_customer_id"] == "cus_test123"


class TestPlanManagement:
    """Test plan and subscription operations."""

    def test_set_user_plan(self, tmp_db):
        """Plan should update correctly."""
        user = tmp_db.get_or_create_user("g_200", "p@q.com", "P", "")
        assert user["plan"] == "free"

        tmp_db.set_user_plan(user["id"], "basic")
        updated = tmp_db.get_user_by_id(user["id"])
        assert updated["plan"] == "basic"

    def test_upsert_subscription_active(self, tmp_db):
        """Active subscription should set user plan."""
        user = tmp_db.get_or_create_user("g_300", "sub@test.com", "Sub", "")

        tmp_db.upsert_subscription(
            user_id=user["id"],
            stripe_subscription_id="sub_test1",
            stripe_price_id="price_basic",
            plan="basic",
            status="active",
        )

        updated = tmp_db.get_user_by_id(user["id"])
        assert updated["plan"] == "basic"

    def test_upsert_subscription_canceled(self, tmp_db):
        """Canceled subscription should revert user to free."""
        user = tmp_db.get_or_create_user("g_400", "cancel@test.com", "C", "")
        tmp_db.set_user_plan(user["id"], "plus")

        tmp_db.upsert_subscription(
            user_id=user["id"],
            stripe_subscription_id="sub_test2",
            stripe_price_id="price_plus",
            plan="plus",
            status="canceled",
        )

        updated = tmp_db.get_user_by_id(user["id"])
        assert updated["plan"] == "free"

    def test_upsert_subscription_update(self, tmp_db):
        """Updating an existing subscription should update the record."""
        user = tmp_db.get_or_create_user("g_500", "upd@test.com", "U", "")

        tmp_db.upsert_subscription(
            user_id=user["id"],
            stripe_subscription_id="sub_test3",
            stripe_price_id="price_basic",
            plan="basic",
            status="active",
        )

        # Upgrade same subscription
        tmp_db.upsert_subscription(
            user_id=user["id"],
            stripe_subscription_id="sub_test3",
            stripe_price_id="price_plus",
            plan="plus",
            status="active",
        )

        updated = tmp_db.get_user_by_id(user["id"])
        assert updated["plan"] == "plus"

    def test_get_active_subscription(self, tmp_db):
        """Should return the active subscription."""
        user = tmp_db.get_or_create_user("g_600", "act@test.com", "A", "")
        tmp_db.upsert_subscription(
            user_id=user["id"],
            stripe_subscription_id="sub_active1",
            stripe_price_id="price_basic",
            plan="basic",
            status="active",
        )

        sub = tmp_db.get_active_subscription(user["id"])
        assert sub is not None
        assert sub["stripe_subscription_id"] == "sub_active1"
        assert sub["plan"] == "basic"


class TestQuotaEnforcement:
    """Test daily message quotas and feature gating."""

    def test_free_plan_quota_starts_at_zero(self, tmp_db):
        """New user on free plan should have 0 used, 15 limit."""
        user = tmp_db.get_or_create_user("g_q1", "q1@test.com", "Q1", "")
        quota = tmp_db.check_quota(user["id"])

        assert quota["allowed"] is True
        assert quota["used"] == 0
        assert quota["limit"] == 15
        assert quota["plan"] == "free"
        assert quota["search_allowed"] is False
        assert quota["think_allowed"] is False

    def test_free_plan_quota_enforcement(self, tmp_db):
        """Free user should be blocked after 15 messages."""
        user = tmp_db.get_or_create_user("g_q2", "q2@test.com", "Q2", "")

        # Simulate 15 messages
        for _ in range(15):
            tmp_db.increment_usage(user["id"], "messages_used")

        quota = tmp_db.check_quota(user["id"])
        assert quota["allowed"] is False
        assert quota["used"] == 15
        assert quota["limit"] == 15

    def test_basic_plan_higher_limit(self, tmp_db):
        """Basic user should have 150 message limit."""
        user = tmp_db.get_or_create_user("g_q3", "q3@test.com", "Q3", "")
        tmp_db.set_user_plan(user["id"], "basic")

        quota = tmp_db.check_quota(user["id"])
        assert quota["limit"] == 150
        assert quota["search_allowed"] is True
        assert quota["think_allowed"] is True

    def test_plus_plan_unlimited(self, tmp_db):
        """Plus user should have unlimited messages (-1)."""
        user = tmp_db.get_or_create_user("g_q4", "q4@test.com", "Q4", "")
        tmp_db.set_user_plan(user["id"], "plus")

        quota = tmp_db.check_quota(user["id"])
        assert quota["limit"] == -1
        assert quota["allowed"] is True

        # Even after 1000 messages, still allowed
        for _ in range(1000):
            tmp_db.increment_usage(user["id"], "messages_used")

        quota = tmp_db.check_quota(user["id"])
        assert quota["allowed"] is True
        assert quota["used"] == 1000

    def test_increment_usage(self, tmp_db):
        """Usage counters should increment correctly."""
        user = tmp_db.get_or_create_user("g_q5", "q5@test.com", "Q5", "")

        tmp_db.increment_usage(user["id"], "messages_used")
        tmp_db.increment_usage(user["id"], "messages_used")
        tmp_db.increment_usage(user["id"], "search_used")

        usage = tmp_db.get_today_usage(user["id"])
        assert usage["messages_used"] == 2
        assert usage["search_used"] == 1
        assert usage["think_used"] == 0

    def test_nonexistent_user_quota(self, tmp_db):
        """Quota check for non-existent user returns allowed=False."""
        quota = tmp_db.check_quota(99999)
        assert quota["allowed"] is False
        assert "error" in quota

    def test_get_user_by_stripe_customer_id(self, tmp_db):
        """Lookup by Stripe customer ID should work."""
        user = tmp_db.get_or_create_user("g_stripe1", "stripe@test.com", "Stripe", "")
        tmp_db.set_stripe_customer_id(user["id"], "cus_stripetest")

        found = tmp_db.get_user_by_stripe_customer_id("cus_stripetest")
        assert found is not None
        assert found["google_id"] == "g_stripe1"


# ═════════════════════════════════════════════════════════════════════
#  2. Plan limits configuration tests
# ═════════════════════════════════════════════════════════════════════

class TestPlanLimits:
    """Verify plan configuration constants."""

    def test_free_plan_limits(self):
        assert PLAN_LIMITS["free"]["messages_per_day"] == 15
        assert PLAN_LIMITS["free"]["search_allowed"] is False
        assert PLAN_LIMITS["free"]["think_allowed"] is False
        assert PLAN_LIMITS["free"]["max_sessions"] == 3

    def test_basic_plan_limits(self):
        assert PLAN_LIMITS["basic"]["messages_per_day"] == 150
        assert PLAN_LIMITS["basic"]["search_allowed"] is True
        assert PLAN_LIMITS["basic"]["think_allowed"] is True
        assert PLAN_LIMITS["basic"]["max_sessions"] == 50

    def test_plus_plan_limits(self):
        assert PLAN_LIMITS["plus"]["messages_per_day"] == -1  # unlimited
        assert PLAN_LIMITS["plus"]["search_allowed"] is True
        assert PLAN_LIMITS["plus"]["think_allowed"] is True
        assert PLAN_LIMITS["plus"]["max_sessions"] == -1  # unlimited


# ═════════════════════════════════════════════════════════════════════
#  3. Client server route tests
# ═════════════════════════════════════════════════════════════════════

class TestClientRoutes:
    """Test Flask route access control and redirects."""

    @pytest.fixture
    def client(self, tmp_path):
        """Create a test Flask client with mocked UserManager."""
        # We need to import serv after setting env vars
        os.environ.setdefault("GOOGLE_CLIENT_ID", "test_id")
        os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test_secret")
        os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
        os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_fake")
        os.environ.setdefault("STRIPE_BASIC_PRICE_ID", "price_basic")
        os.environ.setdefault("STRIPE_PLUS_PRICE_ID", "price_plus")
        os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key")

        # Import after env setup
        import serv
        serv.app.config["TESTING"] = True
        serv.app.config["SECRET_KEY"] = "test-secret-key"

        # Use temp database
        db_path = tmp_path / "test_users.db"
        schema_src = PROJECT_ROOT / "sql" / "users.sql"
        with patch("user_manager.SCHEMA_PATH", schema_src):
            serv.user_manager = UserManager(db_path=db_path)

        with serv.app.test_client() as client:
            yield client, serv

    def test_root_redirects_to_login(self, client):
        """Unauthenticated root should redirect to login."""
        test_client, _ = client
        resp = test_client.get("/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_login_page_loads(self, client):
        """Login page should render successfully."""
        test_client, _ = client
        resp = test_client.get("/login")
        assert resp.status_code == 200
        assert b"Google" in resp.data

    def test_chat_requires_login(self, client):
        """Chat route should redirect unauthenticated users."""
        test_client, _ = client
        resp = test_client.get("/chat/new", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_pricing_requires_login(self, client):
        """Pricing page should redirect unauthenticated users."""
        test_client, _ = client
        resp = test_client.get("/pricing", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_auth_google_redirects_to_google(self, client):
        """/auth/google should redirect to accounts.google.com."""
        test_client, _ = client
        resp = test_client.get("/auth/google", follow_redirects=False)
        assert resp.status_code == 302
        assert "accounts.google.com" in resp.headers["Location"]

    def test_chat_accessible_when_logged_in(self, client):
        """Authenticated users should see the chat page."""
        test_client, serv = client

        # Simulate login via session
        with test_client.session_transaction() as sess:
            user = serv.user_manager.get_or_create_user(
                "g_test", "test@test.com", "Test", "pic.jpg"
            )
            sess["user_id"] = user["id"]
            sess["user_name"] = "Test"
            sess["user_picture"] = "pic.jpg"
            sess["user_email"] = "test@test.com"

        resp = test_client.get("/chat/new")
        assert resp.status_code == 200
        assert b"Qlaude" in resp.data

    def test_api_user_returns_quota(self, client):
        """Authenticated /api/user should return user info and quota."""
        test_client, serv = client

        with test_client.session_transaction() as sess:
            user = serv.user_manager.get_or_create_user(
                "g_api", "api@test.com", "API User", ""
            )
            sess["user_id"] = user["id"]
            sess["user_name"] = "API User"

        resp = test_client.get("/api/user")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "user" in data
        assert "quota" in data
        assert data["user"]["plan"] == "free"
        assert data["quota"]["limit"] == 15
        assert data["quota"]["search_allowed"] is False

    def test_logout_clears_session(self, client):
        """Logout should clear session and redirect to login."""
        test_client, serv = client

        with test_client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user_name"] = "Test"

        resp = test_client.get("/auth/logout", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

        # Session should be cleared
        with test_client.session_transaction() as sess:
            assert "user_id" not in sess

    def test_stripe_webhook_rejects_bad_signature(self, client):
        """Webhook with invalid signature should return 400."""
        test_client, _ = client
        resp = test_client.post(
            "/stripe/webhook",
            data="{}",
            headers={"Stripe-Signature": "bad_sig"},
            content_type="application/json",
        )
        assert resp.status_code == 400


# ═════════════════════════════════════════════════════════════════════
#  4. SQL schema validation
# ═════════════════════════════════════════════════════════════════════

class TestSchema:
    """Validate that the SQL schema creates expected tables."""

    def test_schema_creates_tables(self, tmp_db):
        """All three tables should exist after init."""
        conn = tmp_db._get_db()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        conn.close()

        assert "users" in tables
        assert "subscriptions" in tables
        assert "usage" in tables

    def test_users_table_columns(self, tmp_db):
        """Users table should have expected columns."""
        conn = tmp_db._get_db()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in cur.fetchall()}
        conn.close()

        expected = {"id", "google_id", "email", "name", "picture", "plan",
                    "stripe_customer_id", "created_at", "updated_at"}
        assert expected.issubset(columns)


# ═════════════════════════════════════════════════════════════════════
#  5. Per-user session isolation
# ═════════════════════════════════════════════════════════════════════

@pytest.fixture
def session_env(tmp_path, monkeypatch):
    """Provide isolated chat databases and two test users."""
    server_dir = tmp_path / "server"
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    database_path = data_dir / "database.db"
    session_info_path = data_dir / "session_info.db"
    users_db_path = data_dir / "users.db"

    monkeypatch.setattr("main_manager.BASE_DIR", server_dir)

    schema_src = PROJECT_ROOT / "sql" / "users.sql"
    with patch("user_manager.SCHEMA_PATH", schema_src):
        user_mgr = UserManager(db_path=users_db_path)

    user_a = user_mgr.get_or_create_user("g_user_a", "a@test.com", "User A", "")
    user_b = user_mgr.get_or_create_user("g_user_b", "b@test.com", "User B", "")

    yield {
        "user_mgr": user_mgr,
        "user_a": user_a,
        "user_b": user_b,
        "database_path": database_path,
        "session_info_path": session_info_path,
    }


from main_manager import GenMan, Man


class TestSessionIsolation:
    """Verify chat sessions are scoped to individual users."""

    def _genman(self, session_env, **kwargs):
        return GenMan(
            database_path=session_env["database_path"],
            session_info_path=session_env["session_info_path"],
            **kwargs,
        )

    def _create_session(self, session_env, user_id, session_id, name):
        genman = self._genman(
            session_env,
            user_id=user_id,
            session=session_id,
            user_input=f"Hello from {name}",
        )
        with patch("server.session_name_gen", return_value=name):
            result = genman.check_session()
        assert "error" not in result
        genman.save_into_session(
            {
                "role": "user",
                "content": f"Message from {name}",
                "thought": "",
                "sources": "",
            }
        )
        return genman

    def test_sessions_are_scoped_per_user(self, session_env):
        """Each user should only see their own sessions."""
        user_a = session_env["user_a"]["id"]
        user_b = session_env["user_b"]["id"]

        self._create_session(session_env, user_a, "S_USER_A_1", "Alpha Chat")
        self._create_session(session_env, user_b, "S_USER_B_1", "Beta Chat")

        sessions_a = self._genman(session_env, user_id=user_a).all_session()
        sessions_b = self._genman(session_env, user_id=user_b).all_session()

        assert set(sessions_a.keys()) == {"S_USER_A_1"}
        assert set(sessions_b.keys()) == {"S_USER_B_1"}
        assert sessions_a["S_USER_A_1"]["session_name"] == "Alpha Chat"
        assert sessions_b["S_USER_B_1"]["session_name"] == "Beta Chat"

    def test_user_cannot_access_other_users_session(self, session_env):
        """Loading another user's session should be denied."""
        user_a = session_env["user_a"]["id"]
        user_b = session_env["user_b"]["id"]

        self._create_session(session_env, user_a, "S_PRIVATE", "Private Chat")

        assert self._genman(
            session_env, user_id=user_b, session="S_PRIVATE"
        ).session_belongs_to_user("S_PRIVATE", user_b) is False

        conversation = Man(
            session="S_PRIVATE",
            user_id=user_b,
            database_path=session_env["database_path"],
            session_info_path=session_env["session_info_path"],
        ).load_conversation()
        assert conversation["error"] == "Session not found or access denied"

    def test_user_can_load_own_session(self, session_env):
        """Owners can load their session history."""
        user_a = session_env["user_a"]["id"]
        self._create_session(session_env, user_a, "S_OWNED", "Owned Chat")

        conversation = Man(
            session="S_OWNED",
            user_id=user_a,
            database_path=session_env["database_path"],
            session_info_path=session_env["session_info_path"],
        ).load_conversation()
        messages = conversation["S_OWNED"]

        assert len(messages) == 1
        assert messages[0]["content"] == "Message from Owned Chat"

    def test_max_sessions_enforced_for_free_plan(self, session_env):
        """Free users should be blocked after reaching max_sessions."""
        user_a = session_env["user_a"]["id"]

        for i in range(3):
            self._create_session(session_env, user_a, f"S_FREE_{i}", f"Chat {i}")

        assert self._genman(session_env, user_id=user_a).count_user_sessions(user_a) == 3

        genman = self._genman(
            session_env,
            user_id=user_a,
            session="S_FREE_4",
            user_input="Fourth chat",
        )
        from server import _max_sessions_error_response

        error = _max_sessions_error_response(user_a, genman)
        assert error is not None
        assert error["error_type"] == "max_sessions_exceeded"
        assert error["max_sessions"] == 3

    def test_plus_plan_allows_unlimited_sessions(self, session_env):
        """Plus users should not be capped by max_sessions."""
        user_mgr = session_env["user_mgr"]
        user_a = session_env["user_a"]["id"]
        user_mgr.set_user_plan(user_a, "plus")

        for i in range(5):
            self._create_session(session_env, user_a, f"S_PLUS_{i}", f"Plus Chat {i}")

        genman = self._genman(
            session_env,
            user_id=user_a,
            session="S_PLUS_6",
            user_input="Another",
        )
        from server import _max_sessions_error_response

        with patch("server.user_manager", session_env["user_mgr"]):
            assert _max_sessions_error_response(user_a, genman) is None


# ═════════════════════════════════════════════════════════════════════
#  6. API server auth and isolation
# ═════════════════════════════════════════════════════════════════════

class TestApiServerIsolation:
    """Test API server enforces user_id and session ownership."""

    @pytest.fixture
    def api_client(self, session_env):
        os.environ.setdefault("BASE_URL", "http://test")
        os.environ.setdefault("API_KEY", "test-key")
        os.environ.setdefault("RESONNING_MODEL", "test-model")
        os.environ.setdefault("NON_RESONNING_MODEL", "test-model")

        import server as api_server

        api_server.user_manager = session_env["user_mgr"]
        api_server.app.config["TESTING"] = True

        user_a = session_env["user_a"]["id"]
        user_b = session_env["user_b"]["id"]

        genman = GenMan(
            user_id=user_a,
            session="S_API_A",
            user_input="API test",
            database_path=session_env["database_path"],
            session_info_path=session_env["session_info_path"],
        )
        with patch("server.session_name_gen", return_value="API Chat"):
            genman.check_session()

        with api_server.app.test_client() as client:
            yield client, api_server, user_a, user_b

    def test_list_sessions_requires_user_id(self, api_client):
        test_client, _, _, _ = api_client
        resp = test_client.get("/api/sessions")
        assert resp.status_code == 401

    def test_list_sessions_returns_only_owned(self, api_client):
        test_client, _, user_a, user_b = api_client
        resp_a = test_client.get(f"/api/sessions?user_id={user_a}")
        resp_b = test_client.get(f"/api/sessions?user_id={user_b}")

        data_a = json.loads(resp_a.data)
        data_b = json.loads(resp_b.data)

        assert "S_API_A" in data_a
        assert "S_API_A" not in data_b

    def test_load_conversation_denies_foreign_session(self, api_client):
        test_client, _, user_a, user_b = api_client
        resp = test_client.get(
            f"/api/load_conversation_on_session_id?session_id=S_API_A&user_id={user_b}"
        )
        assert resp.status_code == 403

    def test_load_conversation_allows_owner(self, api_client):
        test_client, _, user_a, _ = api_client
        resp = test_client.get(
            f"/api/load_conversation_on_session_id?session_id=S_API_A&user_id={user_a}"
        )
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "S_API_A" in data["conversation"]

    def test_chat_requires_user_id(self, api_client):
        test_client, _, _, _ = api_client
        resp = test_client.post(
            "/chat",
            json={"session_id": "", "user_input": "hi", "think": False, "search": False},
        )
        assert resp.status_code == 401

    def test_chat_denies_foreign_session(self, api_client):
        test_client, _, _, user_b = api_client
        resp = test_client.post(
            "/chat",
            json={
                "session_id": "S_API_A",
                "user_input": "intruder",
                "think": False,
                "search": False,
                "user_id": user_b,
            },
        )
        assert resp.status_code == 403

    def test_chat_enforces_quota_without_bypass(self, api_client):
        test_client, api_server, user_a, _ = api_client

        for _ in range(15):
            api_server.user_manager.increment_usage(user_a, "messages_used")

        with patch.object(api_server, "client") as mock_client:
            mock_client.chat.completions.create.side_effect = AssertionError(
                "LLM should not be called when quota is exceeded"
            )
            resp = test_client.post(
                "/chat",
                json={
                    "session_id": "",
                    "user_input": "blocked",
                    "think": False,
                    "search": False,
                    "user_id": user_a,
                },
            )

        body = resp.get_data(as_text=True)
        assert "quota_exceeded" in body


# ═════════════════════════════════════════════════════════════════════
#  7. Client proxy routes and SaaS integration
# ═════════════════════════════════════════════════════════════════════

class TestClientProxyRoutes:
    """Test authenticated client routes proxy data correctly."""

    @pytest.fixture
    def proxy_client(self, session_env):
        os.environ.setdefault("GOOGLE_CLIENT_ID", "test_id")
        os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test_secret")
        os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
        os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_fake")
        os.environ.setdefault("STRIPE_BASIC_PRICE_ID", "price_basic")
        os.environ.setdefault("STRIPE_PLUS_PRICE_ID", "price_plus")
        os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key")

        import serv

        serv.user_manager = session_env["user_mgr"]
        serv.app.config["TESTING"] = True
        serv.app.config["SECRET_KEY"] = "test-secret-key"

        user_a = session_env["user_a"]["id"]
        genman = GenMan(
            user_id=user_a,
            session="S_PROXY_A",
            user_input="Proxy test",
            database_path=session_env["database_path"],
            session_info_path=session_env["session_info_path"],
        )
        with patch("server.session_name_gen", return_value="Proxy Chat"):
            genman.check_session()

        with serv.app.test_client() as client:
            yield client, serv, user_a, session_env["user_b"]["id"]

    def _login(self, test_client, serv, user_id, email, name):
        with test_client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_email"] = email
            sess["user_name"] = name

    def test_api_sessions_requires_login(self, proxy_client):
        test_client, _, _, _ = proxy_client
        resp = test_client.get("/api/sessions", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_api_sessions_returns_owned_only(self, proxy_client):
        test_client, serv, user_a, user_b = proxy_client
        self._login(test_client, serv, user_a, "a@test.com", "User A")

        resp_a = test_client.get("/api/sessions")
        assert resp_a.status_code == 200
        data_a = json.loads(resp_a.data)
        assert "S_PROXY_A" in data_a

        self._login(test_client, serv, user_b, "b@test.com", "User B")
        resp_b = test_client.get("/api/sessions")
        data_b = json.loads(resp_b.data)
        assert "S_PROXY_A" not in data_b

    def test_chat_page_blocks_foreign_session(self, proxy_client):
        test_client, serv, _, user_b = proxy_client
        self._login(test_client, serv, user_b, "b@test.com", "User B")

        resp = test_client.get("/chat/S_PROXY_A", follow_redirects=False)
        assert resp.status_code == 302
        assert "/chat/new" in resp.headers["Location"]

    def test_load_conversation_denied_for_foreign_session(self, proxy_client):
        test_client, serv, _, user_b = proxy_client
        self._login(test_client, serv, user_b, "b@test.com", "User B")

        resp = test_client.get(
            "/api/load_conversation_on_session_id?session_id=S_PROXY_A"
        )
        assert resp.status_code == 403

    def test_stripe_checkout_requires_login(self, proxy_client):
        test_client, _, _, _ = proxy_client
        resp = test_client.post(
            "/stripe/create-checkout",
            data={"plan": "basic"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_stripe_checkout_creates_session_for_logged_in_user(self, proxy_client):
        test_client, serv, user_a, _ = proxy_client
        self._login(test_client, serv, user_a, "a@test.com", "User A")

        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test"
        mock_customer = MagicMock()
        mock_customer.id = "cus_test123"

        with patch("serv.stripe.Customer.create", return_value=mock_customer), \
             patch("serv.stripe.checkout.Session.create", return_value=mock_session) as mock_checkout:
            resp = test_client.post(
                "/stripe/create-checkout",
                data={"plan": "basic"},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert mock_checkout.called
        metadata = mock_checkout.call_args.kwargs["metadata"]
        assert metadata["qlaude_user_id"] == str(user_a)

    def test_stripe_webhook_upgrades_plan(self, proxy_client):
        test_client, serv, user_a, _ = proxy_client
        serv.user_manager.set_stripe_customer_id(user_a, "cus_webhook")

        checkout_data = {
            "customer": "cus_webhook",
            "subscription": "sub_webhook_1",
            "metadata": {"qlaude_user_id": str(user_a), "plan": "basic"},
        }

        mock_sub = {
            "items": {"data": [{"price": {"id": "price_basic"}}]},
            "status": "active",
            "current_period_start": 1,
            "current_period_end": 2,
        }

        with patch("serv.stripe.Webhook.construct_event", return_value={
            "type": "checkout.session.completed",
            "data": {"object": checkout_data},
        }), patch("serv.stripe.Subscription.retrieve", return_value=mock_sub):
            resp = test_client.post(
                "/stripe/webhook",
                data="{}",
                headers={"Stripe-Signature": "valid"},
                content_type="application/json",
            )

        assert resp.status_code == 200
        updated = serv.user_manager.get_user_by_id(user_a)
        assert updated["plan"] == "basic"

    def test_api_chat_proxy_injects_authenticated_user_id(self, proxy_client):
        test_client, serv, user_a, _ = proxy_client
        self._login(test_client, serv, user_a, "a@test.com", "User A")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/event-stream"}
        mock_response.iter_content = lambda chunk_size: [b"data: {}\n\n"]

        with patch("serv.http_requests.post", return_value=mock_response) as mock_post:
            resp = test_client.post(
                "/api/chat",
                json={"session_id": "", "user_input": "hello", "think": False, "search": False},
            )

        assert resp.status_code == 200
        sent_body = mock_post.call_args.kwargs["json"]
        assert sent_body["user_id"] == user_a
        assert "user_id" not in mock_post.call_args.args


# ═════════════════════════════════════════════════════════════════════
#  11. Feature gating via API
# ═════════════════════════════════════════════════════════════════════

class TestFeatureGating:
    """Verify /api/user returns correct feature flags per plan."""

    @pytest.fixture
    def feature_client(self, tmp_path):
        os.environ["GOOGLE_CLIENT_ID"] = "test_id"
        os.environ["GOOGLE_CLIENT_SECRET"] = "test_secret"
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_fake"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_fake"
        os.environ["STRIPE_BASIC_PRICE_ID"] = "price_basic"
        os.environ["STRIPE_PLUS_PRICE_ID"] = "price_plus"
        os.environ["FLASK_SECRET_KEY"] = "test-secret-key"

        import serv
        serv.app.config["TESTING"] = True
        serv.app.config["SECRET_KEY"] = "test-secret-key"

        db_path = tmp_path / "feature_users.db"
        schema_src = PROJECT_ROOT / "sql" / "users.sql"
        with patch("user_manager.SCHEMA_PATH", schema_src):
            mgr = UserManager(db_path=db_path)
        serv.user_manager = mgr

        with serv.app.test_client() as client:
            yield client, serv, mgr

    def _login(self, test_client, user_id):
        with test_client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["user_name"] = "Test"
            sess["user_email"] = "test@test.com"

    def test_free_plan_api_response(self, feature_client):
        """Free plan should show features locked."""
        test_client, serv, mgr = feature_client
        user = mgr.get_or_create_user("g_feat1", "feat1@test.com", "Feat1", "")
        self._login(test_client, user["id"])

        resp = test_client.get("/api/user")
        data = json.loads(resp.data)

        assert data["user"]["plan"] == "free"
        assert data["quota"]["search_allowed"] is False
        assert data["quota"]["think_allowed"] is False
        assert data["quota"]["limit"] == 15
        assert data["quota"]["max_sessions"] == 3

    def test_basic_plan_api_response(self, feature_client):
        """Basic plan should show features unlocked."""
        test_client, serv, mgr = feature_client
        user = mgr.get_or_create_user("g_feat2", "feat2@test.com", "Feat2", "")
        mgr.set_user_plan(user["id"], "basic")
        self._login(test_client, user["id"])

        resp = test_client.get("/api/user")
        data = json.loads(resp.data)

        assert data["user"]["plan"] == "basic"
        assert data["quota"]["search_allowed"] is True
        assert data["quota"]["think_allowed"] is True
        assert data["quota"]["limit"] == 150
        assert data["quota"]["max_sessions"] == 50

    def test_plus_plan_api_response(self, feature_client):
        """Plus plan should show unlimited everything."""
        test_client, serv, mgr = feature_client
        user = mgr.get_or_create_user("g_feat3", "feat3@test.com", "Feat3", "")
        mgr.set_user_plan(user["id"], "plus")
        self._login(test_client, user["id"])

        resp = test_client.get("/api/user")
        data = json.loads(resp.data)

        assert data["user"]["plan"] == "plus"
        assert data["quota"]["search_allowed"] is True
        assert data["quota"]["think_allowed"] is True
        assert data["quota"]["limit"] == -1
        assert data["quota"]["max_sessions"] == -1

    def test_upgrade_reflected_in_api(self, feature_client):
        """After upgrading plan, /api/user should reflect new features."""
        test_client, serv, mgr = feature_client
        user = mgr.get_or_create_user("g_feat4", "feat4@test.com", "Feat4", "")
        self._login(test_client, user["id"])

        # Start free
        resp = test_client.get("/api/user")
        data = json.loads(resp.data)
        assert data["user"]["plan"] == "free"
        assert data["quota"]["search_allowed"] is False

        # Upgrade to basic
        mgr.upsert_subscription(
            user_id=user["id"],
            stripe_subscription_id="sub_feat4",
            stripe_price_id="price_basic",
            plan="basic",
            status="active",
        )

        # Check again
        resp = test_client.get("/api/user")
        data = json.loads(resp.data)
        assert data["user"]["plan"] == "basic"
        assert data["quota"]["search_allowed"] is True
        assert data["quota"]["think_allowed"] is True

    def test_downgrade_reflected_in_api(self, feature_client):
        """After canceling subscription, /api/user should show free."""
        test_client, serv, mgr = feature_client
        user = mgr.get_or_create_user("g_feat5", "feat5@test.com", "Feat5", "")
        self._login(test_client, user["id"])

        # Set to basic
        mgr.upsert_subscription(
            user_id=user["id"],
            stripe_subscription_id="sub_feat5",
            stripe_price_id="price_basic",
            plan="basic",
            status="active",
        )

        resp = test_client.get("/api/user")
        data = json.loads(resp.data)
        assert data["user"]["plan"] == "basic"

        # Cancel
        mgr.upsert_subscription(
            user_id=user["id"],
            stripe_subscription_id="sub_feat5",
            stripe_price_id="price_basic",
            plan="basic",
            status="canceled",
        )

        resp = test_client.get("/api/user")
        data = json.loads(resp.data)
        assert data["user"]["plan"] == "free"
        assert data["quota"]["search_allowed"] is False
        assert data["quota"]["think_allowed"] is False
