# Search Tools

GeepSeek exposes five search tools to the LLM through OpenAI-compatible function calling. Tool schemas live in `app/server/json/tools.json`; implementations are in `app/server/search/search.py`.

## Tool reference

| Tool | Use case |
|------|----------|
| `lookup_fact` | Time-sensitive facts: news, scores, releases, live data. Fetches DuckDuckGo snippets and news, then scrapes top pages. |
| `web_search` | General web search with optional keyword filtering on scraped text. |
| `search_sites` | Direct scraping of specified URLs. |
| `list_page_sections` | Lists headings on a page for selective extraction. |
| `fetch_sections` | Retrieves content under headings returned by `list_page_sections`. |

`lookup_fact` is listed first in the tool registry so the model prefers it for current-events queries.

## JSON schema

The following schemas are registered with the model (also stored in `tools.json`):

```python
OPENAI_SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_fact",
            "description": (
                "Best for time-sensitive questions (news, sports, elections, releases). "
                "Returns DuckDuckGo snippets and scraped page content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query. Include dates or years when relevant."
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Pages to scrape after snippets (1–5). Default: 4.",
                        "default": 4
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "General web search. Prefer lookup_fact for current events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "max_results": {
                        "type": "integer",
                        "description": "Links to scrape (1–5). Default: 3.",
                        "default": 3
                    },
                    "key_words": {
                        "type": "string",
                        "description": "Optional comma-separated terms to filter scraped sentences."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_sites",
            "description": "Scrape specific URLs directly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sites": {
                        "type": "string",
                        "description": "Comma-separated URLs (https://...)."
                    },
                    "key_words": {
                        "type": "string",
                        "description": "Optional comma-separated filter terms."
                    }
                },
                "required": ["sites"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_page_sections",
            "description": "List page headings. Call fetch_sections next with selected headings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query (use query or sites)."},
                    "sites": {"type": "string", "description": "Comma-separated URLs."},
                    "max_results": {
                        "type": "integer",
                        "description": "Search results to open when using query. Default: 2.",
                        "default": 2
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_sections",
            "description": "Extract content for headings from list_page_sections.",
            "parameters": {
                "type": "object",
                "properties": {
                    "choosen_headings": {
                        "type": "string",
                        "description": "Comma-separated headings matching available_headings output."
                    }
                },
                "required": ["choosen_headings"]
            }
        }
    }
]
```

## Integration flow

1. `search_agent.py` sends the conversation and tool schemas to the model.
2. The model may return one or more tool calls.
3. Each call is dispatched to the matching function from `build_search_tools()`.
4. Results are serialized as JSON and attached to the message thread.
5. The main chat handler injects structured facts into the completion prompt with mandatory citation rules.

### Example control loop

```python
import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from app.server.search.search import build_search_tools

load_dotenv()

client = OpenAI(
    api_key=os.getenv("API_KEY"),
    base_url=os.getenv("BASE_URL"),
)

local_tools = build_search_tools()
tool_mapping = {func.__name__: func for func in local_tools}


def run_search(user_message: str):
    messages = [
        {"role": "system", "content": "Use search tools for time-sensitive facts."},
        {"role": "user", "content": user_message},
    ]

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=OPENAI_SEARCH_TOOLS,
        tool_choice="auto",
    )

    message = response.choices[0].message
    messages.append(message)

    if not message.tool_calls:
        return message.content

    for tool_call in message.tool_calls:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        func = tool_mapping.get(name)
        result = func(**args) if func else {"error": f"Unknown tool: {name}"}
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": name,
            "content": json.dumps(result),
        })

    final = client.chat.completions.create(model="gpt-4o", messages=messages)
    return final.choices[0].message.content
```

## Operational notes

### Per-request tool state

`build_search_tools()` creates an isolated closure so `list_page_sections` and `fetch_sections` share state within a single request. Instantiate a new tool set per chat request to avoid cross-session contamination.

### Timeouts and retries

- Trafilatura downloads use a 5-second timeout.
- DuckDuckGo queries retry up to two times with exponential backoff.
- Bare domains (e.g. `example.com`) are normalized to `https://` before fetching.

### Context limits

Scraped excerpts are capped at 12,000 characters and 30 sentences per page to stay within model context windows.

## Regenerating `tools.json`

Run `app/server/json/tools.py` to write the schema file from the in-code definitions:

```bash
python app/server/json/tools.py
```
