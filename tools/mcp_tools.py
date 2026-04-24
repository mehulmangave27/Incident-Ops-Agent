"""
MCP Tool Wrappers — Clean JSON-returning functions for the agent.

These are the tools that Dev2's agent loop will call. Each tool
takes simple inputs and returns a JSON-serializable dict.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional

from core.log_parser import LogParser, StackTrace, StackFrame
from core.failure_detector import (
    find_failure_times,
    generate_timeline,
    FailureTimes,
)
from core.root_cause_ranker import rank_root_causes
from cache.redis_store import IncidentCache

logger = logging.getLogger(__name__)

# Base directory for data files
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Shared parser instance
_parser = LogParser()

# Shared cache instance (lazy init)
_cache: Optional[IncidentCache] = None


def _get_cache() -> IncidentCache:
    global _cache
    if _cache is None:
        _cache = IncidentCache()
    return _cache


# ------------------------------------------------------------------
# Tool: get_logs
# ------------------------------------------------------------------

def tool_get_logs(service: str = "payment-service", time_window: str = "1h") -> dict:
    """MCP Tool: Retrieve raw logs for a service.

    For MVP, reads from local sample data files.
    In production this would query S3/CloudWatch/etc.
    """
    try:
        log_file = os.path.join(DATA_DIR, "sample_logs.txt")
        with open(log_file, "r", encoding="utf-8") as f:
            logs = f.read()
        return {
            "status": "success",
            "service": service,
            "time_window": time_window,
            "source": "local_file",
            "log_count": len(logs.splitlines()),
            "logs": logs,
        }
    except FileNotFoundError:
        return {"status": "error", "error": f"Log file not found for {service}"}


# ------------------------------------------------------------------
# Tool: get_git_diff
# ------------------------------------------------------------------

def tool_get_git_diff(commit_id: str = "a3f8b2c") -> dict:
    """MCP Tool: Retrieve git diff for a commit."""
    try:
        diff_file = os.path.join(DATA_DIR, "sample_git_diff.txt")
        with open(diff_file, "r", encoding="utf-8") as f:
            diff = f.read()
        return {
            "status": "success",
            "commit_id": commit_id,
            "source": "local_file",
            "diff": diff,
        }
    except FileNotFoundError:
        return {"status": "error", "error": "Git diff not found"}


# ------------------------------------------------------------------
# Tool: extract_stack_trace
# ------------------------------------------------------------------

def tool_extract_stack_trace(logs: str) -> dict:
    """MCP Tool: Extract stack traces from raw log text."""
    traces = _parser.extract_stack_traces(logs)
    if not traces:
        return {
            "status": "success",
            "trace_count": 0,
            "traces": [],
            "message": "No stack traces found in logs",
        }
    return {
        "status": "success",
        "trace_count": len(traces),
        "traces": [t.to_dict() for t in traces],
    }


# ------------------------------------------------------------------
# Tool: find_failure_times
# ------------------------------------------------------------------

def tool_find_failure_times(logs: str, deploy_time: str) -> dict:
    """MCP Tool: Detect failure timeline from logs.

    Args:
        logs: Raw log text.
        deploy_time: ISO-format deploy timestamp.
    """
    try:
        entries = _parser.parse(logs)
        dt = datetime.fromisoformat(deploy_time.replace("Z", "+00:00"))
        result = find_failure_times(entries, dt)
        return {"status": "success", **result.to_dict()}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ------------------------------------------------------------------
# Tool: rank_root_causes
# ------------------------------------------------------------------

def tool_rank_root_causes(
    stack_trace_dict: dict,
    git_diff: str,
    failure_times_dict: dict,
) -> dict:
    """MCP Tool: Rank potential root causes.

    Args:
        stack_trace_dict: StackTrace as a dict (from tool_extract_stack_trace).
        git_diff: Raw unified diff text.
        failure_times_dict: FailureTimes as a dict (from tool_find_failure_times).
    """
    try:
        # Reconstruct StackTrace from dict
        frames = [
            StackFrame(**f) for f in stack_trace_dict.get("frames", [])
        ]
        st = StackTrace(
            exception_type=stack_trace_dict["exception_type"],
            exception_message=stack_trace_dict["exception_message"],
            frames=frames,
        )

        # Reconstruct FailureTimes from dict
        def _parse_ts(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            # Normalize: remove trailing Z, then remove any existing +00:00
            s = val.rstrip("Z")
            if s.endswith("+00:00"):
                s = s[:-6]
            return datetime.fromisoformat(s + "+00:00")

        ft = FailureTimes(
            deploy_time=_parse_ts(failure_times_dict["deploy_time"]),
            first_anomaly_time=_parse_ts(failure_times_dict.get("first_anomaly_time")),
            first_error_time=_parse_ts(failure_times_dict.get("first_error_time")),
            time_to_anomaly_seconds=failure_times_dict.get("time_to_anomaly_seconds"),
            time_to_failure_seconds=failure_times_dict.get("time_to_failure_seconds"),
            anomaly_to_error_seconds=failure_times_dict.get("anomaly_to_error_seconds"),
        )

        candidates = rank_root_causes(st, git_diff, ft)
        return {
            "status": "success",
            "candidate_count": len(candidates),
            "candidates": [c.to_dict() for c in candidates],
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ------------------------------------------------------------------
# Tool: generate_timeline
# ------------------------------------------------------------------

def tool_generate_timeline(logs: str, deploy_time: str) -> dict:
    """MCP Tool: Build an ordered incident timeline."""
    try:
        entries = _parser.parse(logs)
        dt = datetime.fromisoformat(deploy_time.replace("Z", "+00:00"))
        events = generate_timeline(entries, dt)
        return {
            "status": "success",
            "event_count": len(events),
            "timeline": [e.to_dict() for e in events],
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


# ------------------------------------------------------------------
# Tool: check_cache
# ------------------------------------------------------------------

def tool_check_cache(
    service: str,
    exception_type: str,
    file: str,
    line: int,
) -> dict:
    """MCP Tool: Check if we've seen this incident before."""
    cache = _get_cache()
    fingerprint = cache.generate_fingerprint(service, exception_type, file, line)
    cached = cache.lookup(fingerprint)
    if cached:
        return {
            "status": "cache_hit",
            "fingerprint": fingerprint,
            "occurrences": cache.get_occurrence_count(fingerprint),
            "cached_result": cached,
        }
    return {
        "status": "cache_miss",
        "fingerprint": fingerprint,
    }


# ------------------------------------------------------------------
# Tool: store_result
# ------------------------------------------------------------------

def tool_store_result(
    service: str,
    exception_type: str,
    file: str,
    line: int,
    result: dict,
) -> dict:
    """MCP Tool: Cache an investigation result for future lookups."""
    cache = _get_cache()
    fingerprint = cache.generate_fingerprint(service, exception_type, file, line)
    stored = cache.store(fingerprint, result)
    return {
        "status": "stored" if stored else "not_stored",
        "fingerprint": fingerprint,
        "cache_available": cache.available,
    }


# ------------------------------------------------------------------
# Registry — all tools in one place for Dev2's agent
# ------------------------------------------------------------------

TOOL_REGISTRY = {
    "get_logs": {
        "function": tool_get_logs,
        "description": "Retrieve raw logs for a service",
        "parameters": {"service": "str", "time_window": "str"},
    },
    "get_git_diff": {
        "function": tool_get_git_diff,
        "description": "Retrieve git diff for a commit",
        "parameters": {"commit_id": "str"},
    },
    "extract_stack_trace": {
        "function": tool_extract_stack_trace,
        "description": "Extract stack traces from raw logs",
        "parameters": {"logs": "str"},
    },
    "find_failure_times": {
        "function": tool_find_failure_times,
        "description": "Detect failure timeline from logs",
        "parameters": {"logs": "str", "deploy_time": "str"},
    },
    "rank_root_causes": {
        "function": tool_rank_root_causes,
        "description": "Rank potential root causes",
        "parameters": {
            "stack_trace_dict": "dict",
            "git_diff": "str",
            "failure_times_dict": "dict",
        },
    },
    "generate_timeline": {
        "function": tool_generate_timeline,
        "description": "Build ordered incident timeline",
        "parameters": {"logs": "str", "deploy_time": "str"},
    },
    "check_cache": {
        "function": tool_check_cache,
        "description": "Check if incident was seen before",
        "parameters": {
            "service": "str",
            "exception_type": "str",
            "file": "str",
            "line": "int",
        },
    },
    "store_result": {
        "function": tool_store_result,
        "description": "Cache investigation result",
        "parameters": {
            "service": "str",
            "exception_type": "str",
            "file": "str",
            "line": "int",
            "result": "dict",
        },
    },
}
