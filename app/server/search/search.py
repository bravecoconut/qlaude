"""Web search and page extraction tools for Qlaude.

Provides DuckDuckGo queries, page scraping, and section-based extraction.
Registered with the LLM through build_search_tools().
"""

import time
import re
from datetime import datetime

from ddgs import DDGS
import trafilatura
from trafilatura.settings import use_config
from bs4 import BeautifulSoup

# Trafilatura download timeout (seconds)
_trafilatura_config = use_config()
_trafilatura_config.set("DEFAULT", "DOWNLOAD_TIMEOUT", "5")

# Lazy-loaded spaCy model (avoids import cost when search is disabled)
_nlp = None

# Response size limits (keep tool output within model context)
MAX_RESULTS_CAP = 5
EXCERPT_MAX_CHARS = 12_000
EXCERPT_MAX_SENTENCES = 30
SNIPPET_QUERY_MAX = 5
NEWS_QUERY_MAX = 4

# DuckDuckGo retry policy
DDG_MAX_RETRIES = 2
DDG_RETRY_BASE_DELAY = 1.0
FETCH_TIMEOUT = 15


def _get_nlp():
    global _nlp
    if _nlp is None:
        import spacy

        _nlp = spacy.load("en_core_web_sm")
    return _nlp


def _normalize_url(url: str) -> str:
    """Ensure a URL has an https:// scheme so urllib/trafilatura don't choke."""
    url = url.strip()
    if not url:
        return url
    if not re.match(r"https?://", url, re.IGNORECASE):
        url = "https://" + url
    return url


def _retry_ddg(fn, *args, **kwargs):
    """
    Call *fn* with retry + exponential back-off for transient DDG failures
    (rate-limits, DNS hiccups, etc.).
    """
    last_exc = None
    for attempt in range(1 + DDG_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < DDG_MAX_RETRIES:
                time.sleep(DDG_RETRY_BASE_DELAY * (2**attempt))
    raise last_exc  # type: ignore[misc]


def _collect_ddg_snippets(query: str, include_news: bool = True) -> list:
    """
    Fast layer: DuckDuckGo titles + bodies (and news) before any page scrape.
    Often enough to answer factual / current-events questions on their own.
    """
    snippets = []
    if not query or not query.strip():
        return snippets

    def _fetch():
        results = []
        with DDGS() as ddgs:
            for hit in ddgs.text(query.strip(), max_results=SNIPPET_QUERY_MAX):
                results.append(
                    {
                        "title": hit.get("title", ""),
                        "url": hit.get("href", ""),
                        "snippet": hit.get("body", ""),
                        "source": "web",
                    }
                )

            if include_news:
                try:
                    for hit in ddgs.news(query.strip(), max_results=NEWS_QUERY_MAX):
                        results.append(
                            {
                                "title": hit.get("title", ""),
                                "url": hit.get("url") or hit.get("href", ""),
                                "snippet": hit.get("body", ""),
                                "source": hit.get("source", "news"),
                                "date": hit.get("date", ""),
                            }
                        )
                except Exception:
                    # News backend can fail; web snippets are still useful
                    pass
        return results

    try:
        snippets = _retry_ddg(_fetch)
    except Exception as exc:
        return [{"error": str(exc), "hint": "DuckDuckGo query failed after retries."}]

    return snippets


def prefetch_snippets(query: str) -> dict:
    """
    Called from core.py before the model runs (search mode ON).
    Injects fresh web/news lines into the system prompt so answers are not
    guessed from training data alone.
    """
    return {
        "query": query,
        "today": datetime.now().strftime("%Y-%m-%d"),
        "time": datetime.now().strftime("%H:%M:%S"),
        "instant_snippets": _collect_ddg_snippets(query, include_news=True),
    }


class Search:
    def __init__(
        self,
        query="",
        max_results=2,
        key_words="",
        sites="",
        section="",
        include_news=True,
    ):
        self.query = query
        self.max_results = min(int(max_results), MAX_RESULTS_CAP)
        self.key_words = [
            kw.strip().lower() for kw in key_words.split(",") if kw.strip()
        ]
        self.results = {}
        self.raw_sections = {}
        self.instant_snippets = []
        self.include_news = include_news

        # Normalize URLs — auto-prepend https:// to bare domains
        self.sites = [_normalize_url(si) for si in sites.split(",") if si.strip()]
        # True = DuckDuckGo search; False = scrape only the URLs in self.sites
        self.just_search = not bool(self.sites)
        # Any non-empty section string turns on heading discovery (see search_tool)
        self.section_mode = bool(section and str(section).strip())

    def search_tool(self):
        """Run search or site scrape. Returns snippets + page text or available_headings."""

        # Guard: nothing to do if no query and no sites
        if self.just_search and not self.query.strip():
            return {
                "error": "Empty query with no sites provided.",
                "hint": "Provide a search query or specific site URLs.",
                "instant_snippets": [],
            }

        try:
            if self.just_search:
                # Snippets first — cheap and often contain the direct answer
                self.instant_snippets = _collect_ddg_snippets(
                    self.query, include_news=self.include_news
                )

                def _ddg_search():
                    with DDGS() as ddgs:
                        return ddgs.text(self.query, max_results=self.max_results)

                results = _retry_ddg(_ddg_search)

                # Deduplicate: track snippet URLs so scraped pages don't repeat
                snippet_urls = {
                    s.get("url", "")
                    for s in self.instant_snippets
                    if isinstance(s, dict) and "url" in s
                }

                for result in results:
                    url = result["href"]
                    if url in snippet_urls:
                        continue  # already have a snippet for this URL
                    self._process_url(url)

            else:
                for site in self.sites:
                    self._process_url(site)

        except Exception as exc:
            return {
                "error": str(exc),
                "hint": "If web search failed, try search_sites with full https:// URLs.",
                "instant_snippets": self.instant_snippets,
            }

        if self.section_mode:
            all_headings = []
            for _url, head in self.raw_sections.items():
                if isinstance(head, dict):
                    all_headings.extend(head.keys())
            return {
                "available_headings": sorted(set(all_headings)),
                "instant_snippets": self.instant_snippets,
            }

        return self._package_results()

    def _package_results(self):
        """Standard payload: DDG/news snippets plus scraped page excerpts."""
        return {
            "instant_snippets": self.instant_snippets,
            "page_content": self.results,
        }

    def _process_url(self, url):
        """Scrape one URL into self.results or self.raw_sections."""
        try:
            raw_text = (
                self.section_scrape_tool(url)
                if self.section_mode
                else self.web_scrape_tool(url)
            )
        except Exception as exc:
            key = url
            payload = {"error": f"Could not scrape: {exc}"}
            if self.section_mode:
                self.raw_sections[key] = payload
            else:
                self.results[key] = payload
            return

        if self.section_mode:
            self.raw_sections[url] = self.section_filter_results(raw_text)
        else:
            self.results[url] = self.filter_results(raw_text)

    def choose_section(self, choosen_headings: list):
        """Return content for headings chosen after list_page_sections (section mode)."""
        filtered = {}
        not_found = []

        for h_requested in choosen_headings:
            found = False
            req_lower = h_requested.strip().lower()

            for url, head in self.raw_sections.items():
                if not isinstance(head, dict):
                    continue
                for heading, paragraphs in head.items():
                    if heading.strip().lower() == req_lower:
                        filtered[h_requested] = {
                            "content": self._paragraphs_to_text(paragraphs),
                            "source": url,
                        }
                        found = True
                        break
                if found:
                    break

            if not found:
                not_found.append(h_requested)

        return {
            "results": filtered,
            "not_found": not_found,
            "instant_snippets": self.instant_snippets,
        }

    def web_scrape_tool(self, url):
        """Download and extract plain text from a URL."""
        downloaded = trafilatura.fetch_url(url, no_ssl=True, config=_trafilatura_config)
        if downloaded is None:
            return ""
        text = trafilatura.extract(
            downloaded,
            output_format="txt",
            include_tables=True,
            include_links=True,
            include_images=False,
            no_fallback=False,
        )
        return text if text else ""

    def section_filter_results(self, data):
        if not data:
            return {}

        soup = BeautifulSoup(data, "html.parser")
        content_dict = {}
        current_heading = None

        for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p"]):
            if element.name.startswith("h"):
                current_heading = element.get_text(strip=True)
                content_dict[current_heading] = []
            elif element.name == "p" and current_heading:
                text = element.get_text(strip=True)
                if text:
                    content_dict[current_heading].append(text)

        return content_dict

    def section_scrape_tool(self, url):
        """Download and extract HTML (with headings) from a URL."""
        downloaded = trafilatura.fetch_url(url, no_ssl=True, config=_trafilatura_config)
        if downloaded is None:
            return ""
        text = trafilatura.extract(
            downloaded,
            output_format="html",
            include_tables=True,
            include_links=True,
            include_images=False,
            no_fallback=False,
        )
        return text if text else ""

    def filter_results(self, data):
        """
        Filter scraped text.  When keywords are set, use spaCy to find
        matching sentences.  When no keywords are given, take a fast
        paragraph-split excerpt without loading the NLP pipeline.
        """
        if not data:
            return []

        # Fast path: no keyword filtering — just split into paragraphs/sentences
        if not self.key_words:
            return self._quick_excerpt(data)

        # Keyword path: use spaCy for sentence segmentation + matching
        nlp = _get_nlp()
        doc = nlp(data)
        matched_sentences = []

        for sentence in doc.sents:
            sentence_text = sentence.text.strip()
            if not sentence_text:
                continue
            sentence_lower = sentence_text.lower()

            if any(kw in sentence_lower for kw in self.key_words):
                matched_sentences.append(sentence_text)

        if matched_sentences:
            return self._trim_list(matched_sentences)

        # No keyword matches — fall back to a plain excerpt
        return self._excerpt_from_doc(doc)

    @staticmethod
    def _quick_excerpt(data: str) -> list:
        """
        Cheap excerpt that avoids loading spaCy.
        Splits on double-newlines (paragraphs) then on sentence-ending
        punctuation if paragraphs are too long.
        """
        paragraphs = [p.strip() for p in re.split(r"\n{2,}", data) if p.strip()]
        sentences = []
        for para in paragraphs:
            # If a paragraph is short enough, keep it whole
            if len(para) <= 300:
                sentences.append(para)
            else:
                # Split on sentence-ending punctuation
                for s in re.split(r"(?<=[.!?])\s+", para):
                    s = s.strip()
                    if s:
                        sentences.append(s)
        return Search._trim_list(sentences)

    @staticmethod
    def _paragraphs_to_text(paragraphs):
        if isinstance(paragraphs, list):
            return "\n\n".join(paragraphs)
        return str(paragraphs) if paragraphs is not None else ""

    @staticmethod
    def _trim_list(items):
        out = []
        total = 0
        for item in items:
            if total + len(item) > EXCERPT_MAX_CHARS:
                break
            out.append(item)
            total += len(item)
            if len(out) >= EXCERPT_MAX_SENTENCES:
                break
        return out

    @staticmethod
    def _excerpt_from_doc(doc):
        sentences = [s.text.strip() for s in doc.sents if s.text.strip()]
        return Search._trim_list(sentences)


def _format_tool_payload(payload):
    """Normalize Search output for the model (unchanged shape if already structured)."""
    if not isinstance(payload, dict):
        return payload

    # Already in new format or section-discovery format
    if "instant_snippets" in payload or "available_headings" in payload:
        return payload

    # Legacy: bare url -> sentences dict from older callers
    return {
        "instant_snippets": [],
        "page_content": payload,
    }


def build_search_tools():
    """
    Build Gemini tool callables for one chat request.
    list_page_sections + fetch_sections share state via a small closure (same HTTP request).
    """
    ctx = {"search": None}

    def lookup_fact(query: str, max_results: int = 4) -> dict:
        """Best tool for factual / current-events questions (news, awards, releases, winners).

        Fetches DuckDuckGo web + news snippets, then scrapes top pages. Prefer this over
        guessing from memory when the user asks about recent events or \"latest\" anything.

        Args:
            query: Full question or search phrase (include year if the user mentions one).
            max_results: Number of result pages to scrape after snippets (1–5).
        """
        s = Search(query=query, max_results=max_results, include_news=True)
        return _format_tool_payload(s.search_tool())

    def web_search(query: str, max_results: int = 3, key_words: str = "") -> dict:
        """General web search + scrape. Use lookup_fact for news/awards/current events.

        Args:
            query: What to search for (DuckDuckGo).
            max_results: How many result links to scrape (1–5).
            key_words: Optional comma-separated terms to filter sentences; empty = excerpt.
        """
        s = Search(query=query, max_results=max_results, key_words=key_words)
        return _format_tool_payload(s.search_tool())

    def search_sites(sites: str, key_words: str = "") -> dict:
        """Scrape specific URLs and return filtered page text.

        Args:
            sites: Comma-separated full URLs (https://...).
            key_words: Optional comma-separated filter terms; empty returns an excerpt.
        """
        s = Search(sites=sites, key_words=key_words)
        return _format_tool_payload(s.search_tool())

    def list_page_sections(
        query: str = "",
        sites: str = "",
        max_results: int = 2,
    ) -> dict:
        """List section headings on pages. Call fetch_sections next with chosen headings.

        Args:
            query: Web search query (use this OR sites, not both required).
            sites: Comma-separated URLs to read directly instead of searching.
            max_results: When using query, how many search results to open (1–5).
        """
        s = Search(
            query=query or "",
            sites=sites,
            max_results=max_results,
            section="on",
        )
        ctx["search"] = s
        return _format_tool_payload(s.search_tool())

    def fetch_sections(choosen_headings: str) -> dict:
        """Get section body text after list_page_sections.

        Args:
            choosen_headings: Comma-separated headings exactly as shown in available_headings.
        """
        s = ctx.get("search")
        if s is None:
            return {
                "error": "No section data in memory. Call list_page_sections first, then fetch_sections.",
            }
        headings = [h.strip() for h in choosen_headings.split(",") if h.strip()]
        return s.choose_section(headings)

    # lookup_fact first so the model sees it as the primary choice in tool lists
    return [lookup_fact, web_search, search_sites, list_page_sections, fetch_sections]
