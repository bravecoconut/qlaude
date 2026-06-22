"""Generate OpenAI-compatible tool schemas for GeepSeek search functions.

Run this module to regenerate app/server/json/tools.json.
"""

import json


def buildTools():
    """Build tool definitions and write them to tools.json."""
    OPENAI_SEARCH_TOOLS = [
        {
            "type": "function",
            "function": {
                "name": "lookup_fact",
                "description": (
                    "Best tool for factual or current-events questions (news, awards, sports, elections, releases). "
                    "Fetches DuckDuckGo web + news snippets, then scrapes top pages."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Full question or search phrase (include year/date if relevant)."
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of result pages to scrape after snippets (1-5). Default is 4.",
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
                "description": "General web search + scrape. Use lookup_fact instead for news/awards/current events.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search term or phrase to look up."
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "How many result links to scrape (1-5). Default is 3.",
                            "default": 3
                        },
                        "key_words": {
                            "type": "string",
                            "description": "Optional comma-separated terms to filter matching sentences on the scraped pages."
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
                "description": "Scrape specific URLs and return filtered page text.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sites": {
                            "type": "string",
                            "description": "Comma-separated full URLs (e.g., https://example.com, https://wikipedia.org)."
                        },
                        "key_words": {
                            "type": "string",
                            "description": "Optional comma-separated terms to filter matching sentences on the scraped pages."
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
                "description": (
                    "List section headings on pages. Call fetch_sections next with chosen headings to read their content."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Web search query (use this OR sites)."
                        },
                        "sites": {
                            "type": "string",
                            "description": "Comma-separated URLs to read directly instead of searching."
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "When using query, how many search results to open (1-5). Default is 2.",
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
                "description": "Get section body text after list_page_sections.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "choosen_headings": {
                            "type": "string",
                            "description": "Comma-separated headings exactly as shown in available_headings from list_page_sections."
                        }
                    },
                    "required": ["choosen_headings"]
                }
            }
        }
    ]

    with open("tools.json", "w") as file:
        json.dump(OPENAI_SEARCH_TOOLS, file)


if __name__ == "__main__":
    buildTools()
