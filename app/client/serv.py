"""GeepSeek web client.

Serves the chat UI on port 5001. All inference is handled by the API
server on port 5000.
"""

import json
from flask import Flask, render_template, redirect, url_for

app = Flask(__name__)


@app.route("/chat/<session_id>")
def home(session_id):
    """Render an existing conversation."""
    return render_template("chat.html", session_id=session_id)


@app.route("/chat/new")
def new_chat():
    """Render a blank conversation."""
    return render_template("chat.html", session_id="new")


@app.route("/chat/")
@app.route("/chat")
def redirect_to_new():
    """Normalize /chat paths to the new-chat route."""
    return redirect(url_for("new_chat"))


@app.route("/")
def root():
    """Redirect the site root to a new chat."""
    return redirect(url_for("new_chat"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
