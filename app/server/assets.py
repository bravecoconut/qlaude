"""Auxiliary data accessors for GeepSeek."""

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def get_chat_comment():
    """Return a random placeholder comment for the new-chat screen."""
    database = BASE_DIR.parent / "data" / "chat_comment.db"
    connect = sqlite3.connect(database=database)
    cursor = connect.cursor()

    cursor.execute("SELECT comment FROM comments ORDER BY RANDOM() LIMIT 1")

    row = cursor.fetchone()

    connect.close()

    return row[0] if row else "Ask me anything!"
