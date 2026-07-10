"""Session and conversation persistence for Qlaude.

Manages SQLite storage for chat messages, session metadata, and
context assembly for LLM requests.  Sessions are scoped per user.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import pytz

now = datetime.now(pytz.timezone("Asia/Kolkata"))

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
SESSION_INFO_SCHEMA = BASE_DIR.parent.parent / "sql" / "session_info.sql"


class GenMan:
    """Base session manager: create sessions, load context, save messages."""

    def __init__(
        self,
        think=False,
        search=False,
        session=None,
        user_input="",
        file_path="",
        model="gemini-2.5-flash",
        user_id=None,
        database_path=None,
        session_info_path=None,
    ):
        self.think = think
        self.search = search
        self.session = (
            session if session else f"S{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        )
        self.user_input = user_input
        self.file_path = file_path
        self.model = model
        self.user_id = user_id

        self.database = (
            Path(database_path)
            if database_path
            else BASE_DIR.parent / "data" / "database.db"
        )
        self.session_info = (
            Path(session_info_path)
            if session_info_path
            else BASE_DIR.parent / "data" / "session_info.db"
        )

        self.now = datetime.now()

        self.system_instructions = f"""
        ## Informations
        Current date: {now.strftime("%A, %B %d, %Y")},
        Current time: {now.strftime("%I:%M %p")} IST (UTC+5:30)
        Think: {'Enabled' if think else 'Disabled'}
        Search: {'Enabled' if search else 'Disabled'}

        ## Rules
        1. If the user's query requires real-time information, news, dates, scores, or events from this month, but 'Live Search: Disabled' is active, you MUST NOT guess or hallucinate. 
    - Instead, stop immediately and output a clean message asking the user to enable the **Search** toggle so can provide latest updates based on internet, because you don't have access to searching agents until user enable **search** mode.
        2. If the user's query requires complex calculation, coding logic, deep reasoning, or debugging, but 'Think Mode: Disabled' is active:
        - If query requires to think or the query is complicated to answer, Output a clean message asking the user to enable the **Think** toggle for a better response so you can think in more detail about query.
        3. Keep the request polite, concise, and professional. Do not add any other placeholder conversational text.
        4. never ask user to enable any toggle if query doesn't required realtime update or thining, such for normal greetings.
        """

        self._ensure_session_schema()

    def get_db(self, path):
        """Open a SQLite connection with WAL mode for concurrent reads."""
        connect = sqlite3.connect(path, timeout=10)
        connect.execute("PRAGMA journal_mode=WAL")
        return connect

    def _ensure_session_schema(self):
        """Ensure session metadata table exists and has user_id column."""
        connect = self.get_db(self.session_info)
        cursor = connect.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='info'"
        )
        if not cursor.fetchone():
            with open(SESSION_INFO_SCHEMA, "r") as f:
                connect.executescript(f.read())
        else:
            cursor.execute("PRAGMA table_info(info)")
            columns = {row[1] for row in cursor.fetchall()}
            if "user_id" not in columns:
                cursor.execute("ALTER TABLE info ADD COLUMN user_id INTEGER")

        connect.commit()
        connect.close()

    def session_belongs_to_user(self, session_id=None, user_id=None):
        """Return True when the session is owned by the given user."""
        session_id = session_id or self.session
        user_id = user_id if user_id is not None else self.user_id
        if user_id is None:
            return False

        connect = self.get_db(self.session_info)
        cursor = connect.cursor()
        cursor.execute(
            "SELECT user_id FROM info WHERE session_id = ?", (session_id,)
        )
        row = cursor.fetchone()
        connect.close()

        if not row:
            return False
        return row[0] == user_id

    def count_user_sessions(self, user_id=None):
        """Count sessions owned by a user."""
        user_id = user_id if user_id is not None else self.user_id
        if user_id is None:
            return 0

        connect = self.get_db(self.session_info)
        cursor = connect.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM info WHERE user_id = ?", (user_id,)
        )
        count = cursor.fetchone()[0]
        connect.close()
        return count

    def check_session(self):
        """Ensure the session table exists; create one and register metadata if new."""
        from server import session_name_gen

        if self.user_id is None:
            return {
                "error": "Authentication required",
                "error_type": "auth_required",
            }

        connect = self.get_db(self.database)
        cursor = connect.cursor()

        result = {}

        cursor.execute(f"PRAGMA table_info({self.session})")
        exist = cursor.fetchone()
        connect.close()

        if exist:
            if not self.session_belongs_to_user(self.session, self.user_id):
                return {
                    "error": "Session not found or access denied",
                    "error_type": "session_forbidden",
                }
        else:
            connect = self.get_db(self.database)
            cursor = connect.cursor()

            cursor.execute(f"""
                CREATE TABLE {self.session} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role VARCHAR(10),
                    content TEXT,
                    thought TEXT,
                    source TEXT
                )
                """)

            connect.commit()
            connect.close()

            connect = self.get_db(self.session_info)
            cursor = connect.cursor()

            session_name = session_name_gen(self.user_input)

            cursor.execute(
                """INSERT INTO info
                   (session_id, session_name, date_created, date_last_commit, user_id)
                   VALUES (?,?,?,?,?)""",
                (self.session, session_name, f"{self.now}", f"{self.now}", self.user_id),
            )

            connect.commit()
            connect.close()

            print("creating new session")

            result["new_session"] = {
                "session_name": session_name,
                "session_id": self.session,
            }

        result["session_exist"] = bool(exist)
        result["results"] = {"session_id": self.session}

        return result

    def load_contents(self):
        """Build the message list sent to the LLM, including system instructions."""
        contents_list = [
            {"role": "system", "content": self.system_instructions},
        ]

        connect = self.get_db(self.database)
        cursor = connect.cursor()

        cursor.execute(f"SELECT * FROM {self.session}")

        rows = cursor.fetchall()

        connect.commit()
        connect.close()

        for row in rows:
            role = row[1]
            parts = row[2]
            new_part = {"role": role, "content": parts}
            contents_list.append(new_part)

        return contents_list

    def save_into_session(self, data):
        """Persist a single message and update the session last-modified timestamp."""
        connect = self.get_db(self.database)
        cursor = connect.cursor()

        cursor.execute(
            f"INSERT INTO {self.session} (role, content, thought, source) VALUES(?,?,?,?)",
            (data["role"], data["content"], data["thought"], data["sources"]),
        )

        connect.commit()
        connect.close()

        connect = self.get_db(self.session_info)
        cursor = connect.cursor()

        cursor.execute(
            "UPDATE info SET date_last_commit = ? WHERE session_id = ? AND user_id = ?",
            (f"{self.now}", self.session, self.user_id),
        )

        connect.commit()
        connect.close()

    def all_session(self, user_id=None):
        """Return sessions owned by the given user."""
        user_id = user_id if user_id is not None else self.user_id
        if user_id is None:
            return {}

        session_pairs = {}

        connect = self.get_db(self.database)
        cursor = connect.cursor()

        cursor.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")

        rows = cursor.fetchall()

        connect.commit()
        connect.close()

        connect = self.get_db(self.session_info)
        cursor = connect.cursor()

        cursor.execute("SELECT * FROM info WHERE user_id = ?", (user_id,))

        rowws = cursor.fetchall()

        connect.commit()
        connect.close()

        for row in rows:
            for roww in rowws:
                if row[0] == roww[0]:
                    session_pairs[row[0]] = {
                        "id": roww[0],
                        "session_name": roww[1],
                        "date_created": roww[2],
                        "date_last_commit": roww[3],
                    }

        return session_pairs


class Man(GenMan):
    """Extended session manager that loads full records for UI display."""

    def __init__(self, session, user_id=None, database_path=None, session_info_path=None):
        super().__init__(
            session=session,
            user_id=user_id,
            database_path=database_path,
            session_info_path=session_info_path,
        )
        self.session = session
        self.session_conversation = {}

    def load_conversation(self):
        """Return all messages for the session, including thought and source fields."""
        if self.user_id is None:
            return {"error": "Authentication required"}

        if not self.session_belongs_to_user(self.session, self.user_id):
            return {"error": "Session not found or access denied"}

        contents_list = []

        connect = self.get_db(self.database)
        cursor = connect.cursor()

        cursor.execute(f"SELECT * FROM {self.session}")

        rows = cursor.fetchall()

        connect.commit()
        connect.close()

        for row in rows:
            id = row[0]
            role = row[1]
            content = row[2]
            thought = row[3]
            source = row[4]

            new_part = {
                "id": id,
                "role": role,
                "content": content,
                "thought": thought,
                "source": source,
            }

            contents_list.append(new_part)

        self.session_conversation[f"{self.session}"] = contents_list
        return self.session_conversation
