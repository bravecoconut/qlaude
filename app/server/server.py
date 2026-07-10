"""Qlaude API server.

Provides session management, optional web search, and streaming chat
completions over Server-Sent Events (SSE).  Includes per-user quota
enforcement for the SaaS tier system.
"""

import json
import os
import sys
from openai import OpenAI, APIConnectionError, InternalServerError, OpenAIError
from flask import (
    Flask,
    jsonify,
    request,
    Response,
    stream_with_context,
)
from main_manager import GenMan, Man
from flask_cors import CORS
import pytz
from datetime import datetime
from search_agent import search_agent

from dotenv import load_dotenv

load_dotenv()

# Allow imports from sibling data package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data"))
from user_manager import UserManager  # noqa: E402

user_manager = UserManager()

base_url = os.getenv("BASE_URL")
api_key = os.getenv("API_KEY")
resonning_model = os.getenv("RESONNING_MODEL")
non_resonning_model = os.getenv("NON_RESONNING_MODEL")

model_name = None

app = Flask(__name__)
CORS(app)


def _parse_user_id(raw_user_id):
    """Validate and normalize a user_id from the request."""
    if raw_user_id is None or raw_user_id == "":
        return None, (jsonify({"error": "Authentication required"}), 401)

    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return None, (jsonify({"error": "Invalid user_id"}), 400)

    user = user_manager.get_user_by_id(user_id)
    if not user:
        return None, (jsonify({"error": "User not found"}), 404)

    return user_id, None


def _check_session_access(user_id, session_id):
    """Verify the user owns the session when loading an existing one."""
    if not session_id:
        return None

    genman = GenMan(user_id=user_id, session=session_id)
    if genman.session_belongs_to_user(session_id, user_id):
        return None

    return jsonify({"error": "Session not found or access denied"}), 403


def _session_table_exists(genman):
    """Return True when the per-session message table already exists."""
    connect = genman.get_db(genman.database)
    cursor = connect.cursor()
    cursor.execute(f"PRAGMA table_info({genman.session})")
    exists = cursor.fetchone()
    connect.close()
    return bool(exists)


def _max_sessions_error_response(user_id, genman):
    """Return an SSE-friendly error when the user is at their session limit."""
    quota = user_manager.check_quota(user_id)
    max_sessions = quota.get("max_sessions", 3)
    if max_sessions == -1:
        return None

    current_count = genman.count_user_sessions(user_id)
    if current_count < max_sessions:
        return None

    return {
        "error": (
            f"You've reached your limit of {max_sessions} sessions "
            f"on the {quota['plan']} plan. Delete an old session or upgrade."
        ),
        "error_type": "max_sessions_exceeded",
        "max_sessions": max_sessions,
        "current_sessions": current_count,
    }


@app.route("/api/sessions")
def list_sessions():
    """Return sessions owned by the authenticated user."""
    user_id, error = _parse_user_id(request.args.get("user_id"))
    if error:
        return error

    return jsonify(GenMan(user_id=user_id).all_session())


@app.route("/api/load_conversation_on_session_id")
def load_conversation_on_session_id():
    """Load full message history for a session owned by the user."""
    user_id, error = _parse_user_id(request.args.get("user_id"))
    if error:
        return error

    session_id = request.args.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400

    access_error = _check_session_access(user_id, session_id)
    if access_error:
        return access_error

    conversation_data = Man(session=session_id, user_id=user_id).load_conversation()
    if isinstance(conversation_data, dict) and conversation_data.get("error"):
        return jsonify(conversation_data), 403

    return jsonify(
        {"conversation": conversation_data, "redirect_url": f"/chat/{session_id}"}
    )


client = OpenAI(base_url=f"{base_url}/v1", api_key=api_key)


@app.route("/chat", methods=["POST"])
def chat():
    """Handle a chat turn: optional search, streamed LLM response, persistence."""
    body = request.get_json() or {}
    session_id = body.get("session_id")
    user_input = body.get("user_input")
    think = body.get("think")
    search = body.get("search")

    user_id, error = _parse_user_id(body.get("user_id"))
    if error:
        return error

    print(
        f" think: {think}\n search: {search}\n userinpt: {user_input}\n user_id: {user_id}"
    )

    if session_id:
        access_error = _check_session_access(user_id, session_id)
        if access_error:
            return access_error

    # ── Quota enforcement ────────────────────────────────────────
    quota = user_manager.check_quota(user_id)

    if not quota["allowed"]:
        def quota_error():
            limit = quota["limit"]
            plan = quota["plan"]
            msg = (
                f"You've reached your daily limit of {limit} messages on the **{plan}** plan. "
                f"Upgrade your plan for more messages."
            )
            yield f"data: {json.dumps({'error': msg, 'error_type': 'quota_exceeded', 'quota': quota})}\n\n".encode()

        return Response(stream_with_context(quota_error()), mimetype="text/event-stream")

    if search and not quota["search_allowed"]:
        def feature_error_search():
            msg = "**Search mode** is not available on the free plan. Upgrade to Basic or Plus to unlock it."
            yield f"data: {json.dumps({'error': msg, 'error_type': 'feature_locked', 'feature': 'search'})}\n\n".encode()

        return Response(stream_with_context(feature_error_search()), mimetype="text/event-stream")

    if think and not quota["think_allowed"]:
        def feature_error_think():
            msg = "**Think mode** is not available on the free plan. Upgrade to Basic or Plus to unlock it."
            yield f"data: {json.dumps({'error': msg, 'error_type': 'feature_locked', 'feature': 'think'})}\n\n".encode()

        return Response(stream_with_context(feature_error_think()), mimetype="text/event-stream")
    # ─────────────────────────────────────────────────────────────

    if think:
        model_name = resonning_model
    else:
        model_name = non_resonning_model

    genman = GenMan(
        think=think,
        search=search,
        user_input=user_input,
        session=session_id,
        user_id=user_id,
    )
    print("instance created.. working ahead")

    def generate():
        if not _session_table_exists(genman):
            max_sessions_error = _max_sessions_error_response(user_id, genman)
            if max_sessions_error:
                yield f"data: {json.dumps(max_sessions_error)}\n\n".encode()
                return

        check_session = genman.check_session()
        if check_session.get("error"):
            yield f"data: {json.dumps(check_session)}\n\n".encode()
            return

        yield f"data: {json.dumps({'check_session': check_session})}\n\n".encode()

        past_content = genman.load_contents()
        messages = past_content

        sources = []
        if search:
            user_contents = []
            for message in messages:
                if (message["role"] == "user") or (message["role"] == "assistant"):
                    user_contents.append(message)
            user_contents.append({"role": "user", "content": user_input})

            yield f"data: {json.dumps({'searching': True})}\n\n".encode()
            search_context = search_agent(user_contents=user_contents)
            print("search_context type:", type(search_context))
            print("search_context:", str(search_context)[:300])

            try:
                content = json.loads(search_context["content"])
                result = content.get("result", {})

                print("result keys:", list(result.keys()))

                for item in result.get("organic_results", []):
                    if item.get("link"):
                        source = {
                            "sources": {
                                "title": item.get("title", item["link"]),
                                "link": item["link"],
                            }
                        }
                        sources.append(source)
                        yield f"data: {json.dumps(source)}\n\n".encode()

                for item in result.get("instant_snippets", []):
                    if item.get("url"):
                        source = {
                            "sources": {
                                "title": item.get("title", item["url"]),
                                "url": item["url"],
                            }
                        }
                        sources.append(source)
                        yield f"data: {json.dumps(source)}\n\n".encode()

            except Exception:
                yield f"data: {json.dumps({'search_not_required': True})}\n\n".encode()

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
                        "9. never write url in anchor tag like this: [https://example.com](https://example.com)"
                    ),
                }
            )

        user_for_api = {"role": "user", "content": user_input}
        user_for_db = {
            "role": "user",
            "content": user_input,
            "thought": "",
            "sources": "",
        }
        messages.append(user_for_api)

        stream = client.chat.completions.create(
            model=model_name,
            messages=messages,
            stream=True,
            extra_body={"think": think, "enable_thinking": think},
        )

        full_thought_buffer = ""
        full_content_buffer = ""

        print("generating", end="", flush=True)

        for chunk in stream:
            print(".", end="", flush=True)

            if not getattr(chunk, "choices", None) or len(chunk.choices) == 0:
                continue
            delta = chunk.choices[0].delta

            reasoning_chunk = getattr(delta, "reasoning", None) or getattr(
                delta, "reasoning_content", None
            )

            payload = None
            if reasoning_chunk:
                full_thought_buffer += reasoning_chunk
                payload = {"reasoning_chunk": reasoning_chunk}
            elif getattr(delta, "content", None):
                full_content_buffer += delta.content
                payload = {"content_chunk": delta.content}

            if payload:
                data_string = f"data: {json.dumps(payload)}\n\n"
                yield data_string.encode("utf-8")

        print("")

        sources_str = json.dumps(sources)

        model = {
            "role": "assistant",
            "content": full_content_buffer,
            "thought": full_thought_buffer,
            "sources": sources_str,
        }

        print("saving both input and output")

        genman.save_into_session(user_for_db)
        print("saving user input")

        genman.save_into_session(model)
        print("saving model output")

        user_manager.increment_usage(user_id, "messages_used")
        if search:
            user_manager.increment_usage(user_id, "search_used")
        if think:
            user_manager.increment_usage(user_id, "think_used")
        updated_quota = user_manager.check_quota(user_id)
        yield f"data: {json.dumps({'quota_update': updated_quota})}\n\n".encode()

    return Response(stream_with_context(generate()), mimetype="text/event-stream")


def session_name_gen(user_input):
    """Generate a short session title from the first user message."""
    try:
        model_name = non_resonning_model
        instructions = f"""
            "You are a session title generator. "
            "Read the user's message and reply with ONLY a short title, 5 to 7 words. "
            "No punctuation, no quotes, no explanation. Just the title."
            """

        messages = [
            {"role": "system", "content": instructions},
            {
                "role": "user",
                "content": f"{user_input}",
            },
        ]

        client = OpenAI(base_url=f"{base_url}/v1", api_key=api_key)
        response = client.chat.completions.create(model=model_name, messages=messages)

        content = response.choices[0].message.content
        return content.strip() if content else "New Chat"

    except (InternalServerError, OpenAIError, APIConnectionError) as e:
        print(f"OpenAI API Error caught: {e}")
        return "New Chat"


if __name__ == "__main__":
    app.run(debug=True, port=5000)
