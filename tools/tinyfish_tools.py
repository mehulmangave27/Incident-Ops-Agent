"""
TinyFish Tool Wrappers — External intelligence for the investigation agent.

These tools use the TinyFish API to scrape live vendor status pages
and search the web for related incidents.

Environment variables:
    TINYFISH_API_KEY — Your TinyFish API key (required)
"""

import json
import os
from urllib.parse import urlparse

import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

TINYFISH_AGENT_URL = "https://agent.tinyfish.ai/v1/automation/run"
TINYFISH_SEARCH_URL = "https://api.search.tinyfish.ai"
_API_KEY = os.environ.get("TINYFISH_API_KEY", "")

_VENDOR_STATUS_PAGES = {
    "stripe":     {"service": "Stripe",     "url": "https://status.stripe.com"},
    "aws":        {"service": "AWS",        "url": "https://health.aws.amazon.com/health/status"},
    "github":     {"service": "GitHub",     "url": "https://www.githubstatus.com"},
    "datadog":    {"service": "Datadog",    "url": "https://status.datadoghq.com"},
    "cloudflare": {"service": "Cloudflare", "url": "https://www.cloudflarestatus.com"},
    "pagerduty":  {"service": "PagerDuty",  "url": "https://status.pagerduty.com"},
}


# ---------------------------------------------------------------------------
# Tool: check_vendor_status
# ---------------------------------------------------------------------------

def tool_check_vendor_status(service_name: str, timestamp: str = "") -> dict:
    """MCP Tool: Check if a vendor had an outage around the incident time.

    Uses the TinyFish Agent API to scrape the vendor's live status page.

    Args:
        service_name: Vendor name (e.g. "stripe", "aws").
        timestamp: ISO timestamp to check around.

    Returns:
        dict with status key per MCP contract.
    """
    key = service_name.lower().strip()
    vendor = _VENDOR_STATUS_PAGES.get(key)

    if vendor is None:
        return {
            "status": "error",
            "error": f"Unknown vendor '{service_name}'. Supported: {list(_VENDOR_STATUS_PAGES)}",
        }

    if not _API_KEY:
        return {
            "status": "error",
            "error": "TINYFISH_API_KEY not set. Add it to .env or environment.",
        }

    time_ctx = f" Check for incidents around {timestamp}." if timestamp else ""
    goal = (
        f"Go to {vendor['url']} and extract the current operational status.{time_ctx} "
        f"Return a JSON object with: "
        f"overall_status (string: 'operational', 'degraded', or 'outage'), "
        f"active_incidents (integer count), "
        f"incidents (array of objects with: title, status, started_at, "
        f"resolved_at or null, description, severity). "
        f"If no incidents, return an empty array."
    )

    try:
        with httpx.Client(timeout=90.0) as client:
            resp = client.post(
                TINYFISH_AGENT_URL,
                json={"url": vendor["url"], "goal": goal, "browser_profile": "lite"},
                headers={"X-API-Key": _API_KEY, "Content-Type": "application/json"},
            )
            resp.raise_for_status()

        data = resp.json()
        agent_output = data.get("result") or data.get("output") or data.get("data") or data

        # Agent may return text with embedded JSON
        if isinstance(agent_output, str):
            start = agent_output.find("{")
            end = agent_output.rfind("}") + 1
            if start != -1 and end > start:
                agent_output = json.loads(agent_output[start:end])

        incidents = agent_output.get("incidents", [])
        has_outage = agent_output.get("overall_status", "operational") != "operational"

        return {
            "status": "success",
            "vendor": vendor["service"],
            "status_page": vendor["url"],
            "overall_status": agent_output.get("overall_status", "unknown"),
            "has_outage": has_outage,
            "active_incidents": agent_output.get("active_incidents") or len(incidents),
            "incidents": incidents,
            "details": (
                f"{vendor['service']} is {agent_output.get('overall_status', 'unknown')} "
                f"at {timestamp or 'current time'}"
                + (f" — {len(incidents)} incident(s) reported" if incidents else "")
            ),
        }

    except Exception as exc:
        return {"status": "error", "error": f"TinyFish scrape failed: {exc}"}


# ---------------------------------------------------------------------------
# Tool: search_related_incidents
# ---------------------------------------------------------------------------

def tool_search_related_incidents(error_message: str) -> dict:
    """MCP Tool: Search the web for similar incidents / known issues.

    Uses the TinyFish Search API.

    Args:
        error_message: Error text to search for.

    Returns:
        dict with status key per MCP contract.
    """
    if not _API_KEY:
        return {
            "status": "error",
            "error": "TINYFISH_API_KEY not set. Add it to .env or environment.",
        }

    query = _build_query(error_message)

    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                TINYFISH_SEARCH_URL,
                params={"query": query, "language": "en"},
                headers={"X-API-Key": _API_KEY},
            )
            resp.raise_for_status()

        data = resp.json()
        raw = data.get("results", data.get("items", []))

        results = [
            {
                "source": _domain(r.get("url", "")),
                "title": r.get("title", "Untitled"),
                "url": r.get("url", ""),
                "summary": r.get("description") or r.get("snippet") or "",
                "relevance": r.get("score", 0),
            }
            for r in raw[:5]
        ]

        return {
            "status": "success",
            "query": query,
            "result_count": len(results),
            "results": results,
        }

    except Exception as exc:
        return {"status": "error", "error": f"TinyFish search failed: {exc}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_query(error: str) -> str:
    lines = [l.strip() for l in error.splitlines() if l.strip() and not l.strip().startswith("at ")]
    return " ".join(lines[:2])[:200]


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Registry — for dynamic agent discovery
# ---------------------------------------------------------------------------

TINYFISH_REGISTRY = {
    "check_vendor_status": {
        "function": tool_check_vendor_status,
        "description": "Check external vendor for outages (scrapes live status page via TinyFish)",
        "parameters": {"service_name": "str", "timestamp": "str"},
    },
    "search_related_incidents": {
        "function": tool_search_related_incidents,
        "description": "Search web for similar incidents (via TinyFish Search API)",
        "parameters": {"error_message": "str"},
    },
}
