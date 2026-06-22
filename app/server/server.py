"""GeepSeek API server.

Provides session management, optional web search, and streaming chat
completions over Server-Sent Events (SSE).
"""

import json
import os
from openai import OpenAI, APIConnectionError, InternalServerError, OpenAIError
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
from assets import get_chat_comment

from dotenv import load_dotenv

load_dotenv()

base_url = os.getenv("BASE_URL")
api_key = os.getenv("API_KEY")
resonning_model = os.getenv("RESONNING_MODEL")
non_resonning_model = os.getenv("NON_RESONNING_MODEL")

model_name = None

app = Flask(__name__)
CORS(app)


@app.route("/api/sessions")
def list_sessions():
    """Return all sessions with metadata for the sidebar."""
    return jsonify(GenMan().all_session())


@app.route("/api/load_conversation_on_session_id")
def load_conversation_on_session_id():
    """Load full message history for the requested session."""
    session_id = request.args.get("session_id")
    conversation_data = Man(session=session_id).load_conversation()
    return jsonify(
        {"conversation": conversation_data, "redirect_url": f"/chat/{session_id}"}
    )


client = OpenAI(base_url=f"{base_url}/v1", api_key=api_key)


@app.route("/chat", methods=["POST"])
def chat():
    """Handle a chat turn: optional search, streamed LLM response, persistence."""
    body = request.get_json()
    session_id = body.get("session_id")
    user_input = body.get("user_input")
    think = body.get("think")
    search = body.get("search")

    print(f" think: {think}\n search: {search}\n userinpt: {user_input}")

    if think:
        model_name = resonning_model
    else:
        model_name = non_resonning_model

    genman = GenMan(
        think=think, search=search, user_input=user_input, session=session_id
    )
    print("instance created.. working ahead")

    def generate():
        check_session = genman.check_session()
        yield f"data: {json.dumps({'check_session': check_session})}\n\n".encode()

        past_content = genman.load_contents()
        messages = past_content

        sources = []
        if search:
            # Build recent user/assistant context for the search agent
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

                # Sources from web_search (organic_results)
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

                # Sources from lookup_fact (instant_snippets)
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

            except Exception as e:
                yield f"data: {json.dumps({'search_not_required': True})}\n\n".encode()

            # Inject search results and citation rules for the main model
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
