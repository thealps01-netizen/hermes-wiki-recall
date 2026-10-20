"""Search the open LLM Wiki project for the user's message and return page pointers.

Only titles and paths are returned; the assistant decides whether to read a page.
Any failure (app closed, timeout, bad reply) yields no pointers, so a chat turn never breaks;
it leaves one "wiki-recall: <reason> (<exception class>)" warning in Hermes' logs.
"""
import json
import logging
import os
import re
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:19828"
# Measured on one real wiki: relevant pages mostly score 0.65-1.0, but unrelated pages reach that
# range too, because the app caps page scores at 1.0 (best chunk + 30% of the other chunks) and long
# pages score high on weak matches. A pointer costs one line, so that rate is accepted (README, Known limit).
MIN_VECTOR_SCORE = 0.8
MAX_POINTERS = 3
# With no page at MIN_VECTOR_SCORE, the best pages down to this score are listed as low confidence:
# relevant pages often score 0.65-0.8, and naming them beats leaving the turn without a hint.
MIN_WEAK_SCORE = 0.65
MAX_WEAK_POINTERS = 2
MAX_QUERY_CHARS = 1000
TIMEOUT_S = 2.0


def _warn(reason, exc_class) -> None:
    # Only the class name: an exception's text can carry the URL, the reply body or the query.
    logger.warning("wiki-recall: %s (%s)", reason, exc_class)


def _failure_reason(exc) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    if isinstance(exc, TimeoutError) or (
            isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, TimeoutError)):
        return "timed out"
    if isinstance(exc, OSError):
        return "app unreachable"
    if isinstance(exc, ValueError):
        return "bad reply"
    return "unexpected error"


def message_text(message) -> str:
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        return " ".join(p.get("text", "") for p in message if isinstance(p, dict) and p.get("type") == "text")
    return ""


def read_token(lookup):
    try:
        token = lookup("LLM_WIKI_API_TOKEN")
    except Exception as exc:
        _warn("token lookup failed", type(exc).__name__)
        return None
    return (token.strip() or None) if isinstance(token, str) else None


def compile_skip(pattern):
    if not isinstance(pattern, str) or not pattern:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        _warn("invalid skip_pattern", type(exc).__name__)
        return None


def search(query, *, base_url=None, token=None, timeout=TIMEOUT_S, skip=None):
    query = (query or "").strip()[:MAX_QUERY_CHARS]
    if not query or (skip is not None and skip.search(query)):
        return []
    url = (base_url or os.environ.get("LLM_WIKI_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps({"query": query, "topK": 5}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url + "/api/v1/projects/current/search", data=body, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            reply = json.load(response)
        results = (reply.get("results") or []) if isinstance(reply, dict) else None
        if not isinstance(results, list):
            raise ValueError("reply shape")
    except Exception as exc:
        _warn(_failure_reason(exc), type(exc).__name__)
        return []
    scored = [r for r in results if isinstance(r, dict) and r.get("path")
              and isinstance(r.get("vectorScore"), (int, float))]
    strong = [r for r in scored if r["vectorScore"] >= MIN_VECTOR_SCORE]
    if strong:
        return strong[:MAX_POINTERS]
    weak = sorted((r for r in scored if r["vectorScore"] >= MIN_WEAK_SCORE),
                  key=lambda r: r["vectorScore"], reverse=True)
    return [dict(r, low_confidence=True) for r in weak[:MAX_WEAK_POINTERS]]


def format_context(hits) -> str:
    if not hits:
        return ""
    lines = "\n".join(f"- {h.get('title') or h['path']} ({h['path']})" for h in hits)
    if any(h.get("low_confidence") for h in hits):
        return ("No LLM Wiki page matched this message closely. Closest pages (automatic search, "
                "low confidence, may be unrelated). If the message is about the user's own setup, "
                "work or past decisions, search the wiki or read one of these:\n" + lines)
    return ("LLM Wiki pages that may be relevant to this message (automatic search; titles only, "
            "may be unrelated). Read one with the llm-wiki tools only if it helps answer:\n" + lines)
