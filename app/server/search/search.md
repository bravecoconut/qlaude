# RAG Search Infrastructure

Qlaude's Retrieval-Augmented Generation (RAG) search pipeline exposes advanced data acquisition tools to the inference models through OpenAI-compatible function calling schemas. Tool definitions are version-controlled in `app/server/json/tools.json` and executed via the `app/server/search/search.py` module.

## Tool Capabilities

| Tool Registration | Enterprise Use Case |
|------|----------|
| `lookup_fact` | Rapid acquisition of time-sensitive data (market events, news, dynamic metrics). Aggregates search engine snippets and executes parallel scraping on high-value targets. |
| `web_search` | Broad web crawling with integrated NLP keyword filtering on extracted datasets. |
| `search_sites` | Targeted, direct data extraction from specified domains or URLs. |
| `list_page_sections` | Structural analysis of long-form documents. Returns a manifest of available content headings for selective extraction. |
| `fetch_sections` | High-precision extraction of specific document sections identified by `list_page_sections`. |

The `lookup_fact` capability is prioritized in the tool registry to encourage the model to seek out real-time, current-events data.

## Schema Registration

The platform registers the following strict schemas with the LLM backend (mirrored in `tools.json`):

```python
OPENAI_SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_fact",
            "description": (
                "Best for time-sensitive questions (news, sports, elections, releases). "
                "Returns search engine snippets and scraped page content."
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

## RAG Orchestration Flow

1. The `search_agent.py` orchestrator dispatches the active customer context and tool schemas to the inference backend.
2. The model evaluates the request and may yield one or more autonomous tool invocations.
3. Invocations are mapped and dispatched to the concrete implementations within `build_search_tools()`.
4. Retrieved external data is structured, serialized as JSON, and securely appended to the conversational state.
5. The primary generation pipeline ingests the structured facts into its prompt template, bound by strict, system-level citation mandates.

### Execution Control Loop Example

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
        {"role": "system", "content": "Utilize RAG search tools for external data acquisition."},
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
        result = func(**args) if func else {"error": f"Unknown capability requested: {name}"}
        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": name,
            "content": json.dumps(result),
        })

    final = client.chat.completions.create(model="gpt-4o", messages=messages)
    return final.choices[0].message.content
```

## Operational Guidelines

### Secure State Management

`build_search_tools()` implements an isolated closure pattern. This ensures that stateful tools like `list_page_sections` and `fetch_sections` share secure state *only* within the bounds of a single customer request. A fresh tool set is instantiated per interaction to prevent cross-tenant data contamination.

### Resilience and Fallbacks

- Upstream `trafilatura` extractions are governed by a strict 5-second timeout policy.
- Search engine API queries implement exponential backoff with a maximum of two retries to guarantee high availability.
- Raw domain inputs are automatically sanitized and normalized to secure `https://` protocols prior to extraction.

### Context Window Optimization

To maintain peak inference performance and prevent context window overflow, scraped payloads are aggressively optimized: excerpts are strictly capped at 12,000 characters and a maximum of 30 semantic sentences per document.

## Schema Synchronization

If modifications are made to the core tool definitions, the schema registry must be manually synchronized. Execute the `app/server/json/tools.py` utility to serialize the latest in-code schemas to the `tools.json` file:

```bash
python app/server/json/tools.py
```
