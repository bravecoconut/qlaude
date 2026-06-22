"""Legacy alternate API routes for GeepSeek.

The primary production entry point is server.py. This module retains an
earlier request/response pattern for reference.
"""

import json
import os
from openai import OpenAI
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    Response,
    stream_with_context,
)
from main_manager import GenMan, Man
from flask_cors import CORS
import pytz
from datetime import datetime
from search_agent import search_agent

base_url = os.getenv("BASE_URL")
api_key = os.getenv("API_KEY")
model = os.getenv("MODEL")

app = Flask(__name__)
CORS(app)


def _final_response_from_generator(gen):
    """Collect the final payload from an SSE generator stream."""
    payload = None
    for item in gen:
        if not isinstance(item, str) or not item.startswith("data: "):
            continue
        try:
            data = json.loads(item.removeprefix("data: ").strip())
        except json.JSONDecodeError:
            continue
        if data.get("type") == "done":
            payload = data
    return payload


@app.route("/api/sessions")
def list_sessions():
    return jsonify(GenMan().all_session())


@app.route("/api/load_conversation_on_session_id")
def load_conversation_on_session_id():
    session_id = request.args.get("session_id")
    return jsonify(Man(session=session_id).load_conversation())


@app.route("/api/send")
def send():
    think_bool = request.args.get("think") == "true"
    search_bool = request.args.get("search") == "true"
    session_id = (
        request.args.get("session_id", "").strip('"').strip("'").strip() or None
    )
    userInput = request.args.get("userInput")
    filePath = request.args.get("filePath")

    result = GenMan(
        think=think_bool,
        search=search_bool,
        session=session_id,
        user_input=userInput,
        file_path=filePath,
    ).check_session()

    return jsonify(result)


def model_response(messages, think, search):
    """Run a non-streaming completion with optional search context."""
    client = OpenAI(base_url=f"{base_url}/v1", api_key=api_key)

    if search:
        search_context = search_agent(user_prompt=messages[-1]["content"])

        messages.append(
            {
                "role": "system",
                "content": (
                    "## Live search context (structured facts from search agent)\n\n"
                    f"{search_context}\n\n"
                    "The above is raw extracted data from the web, fetched moments ago.\n"
                    "Use it as your only source of truth for this answer.\n"
                    "Do not use your training memory for any fact that could have changed.\n"
                    "## Citation Rules (Mandatory):\n"
                    "1. ANY word, phrase, number, name, or sentence taken from the search results MUST be a markdown hyperlink.\n"
                    "2. The anchor text is exactly the text you are writing — wrap it in the link, do not add a separate citation.\n"
                    "3. Format: [the exact text you are writing](full source url)\n"
                    "4. Examples:\n"
                    "   - A full sentence: [Gujarat Titans beat CSK by 89 runs in Match 66](https://example.com)\n"
                    "   - A name: [Shubman Gill](https://example.com) scored a century\n"
                    "   - A number: the rate was cut by [25 basis points](https://example.com)\n"
                    "   - A rule/policy: RBI mandated [a 7-day notice before loan recovery](https://example.com)\n"
                    "5. Never print raw URLs anywhere in the response.\n"
                    "6. Never use 'Source', 'here', 'click here', or a website name as anchor text.\n"
                    "7. If you write something not from the search results (your own connecting words like 'According to the findings'), do NOT link it.\n"
                    "8. If a fact was marked CONFLICT, link both versions separately to their respective URLs.\n"
                ),
            }
        )

    response_stream = client.chat.completions.create(
        model=model, messages=messages, extra_body={"think": think}, stream=True
    )

    full_content = ""
    full_thought = ""
    for chunk in response_stream:
        delta = chunk.choices[0].delta

        if getattr(delta, "reasoning", None):
            full_thought += delta.reasoning

        elif getattr(delta, "reasoning_content", None):
            full_thought += delta.reasoning_content

        elif delta.content:
            full_content += delta.content

    return {"response": full_content, "thought": full_thought}
