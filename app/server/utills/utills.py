"""Shared utilities for GeepSeek server logging and debug output."""

from datetime import datetime
import json


def log(string):
    """Append a timestamped entry to logs/log.txt."""
    with open("logs/log.txt", "a") as file:
        entry = f"**{datetime.now()}\n  {string} \n\n\n"
        file.write(entry)


def list_to_string(data):
    """Serialize a list to a string representation for debugging."""
    data_str = repr(data)
    return data_str
