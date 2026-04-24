# Dev2 Handoff — What's Built & What You Need To Do

## Quick Start

```bash
# Run the demo (no setup needed, no dependencies required)
python main.py --auto

# Interactive mode
python main.py
```

Everything works end-to-end right now with sample data. Your job is to add the agent intelligence layer and external signals on top.

---

## What's Already Built (Dev1 — Complete)

### Project Structure

```
Incident-Ops-Agent/
├── data/
│   ├── sample_logs.txt          # 60-line realistic log file with a bug story
│   ├── sample_stacktrace.txt    # Java NPE stack trace
│   └── sample_git_diff.txt      # Git diff that introduced the bug
├── core/
│   ├── log_parser.py            # Regex parser → LogEntry, StackTrace objects
│   ├── failure_detector.py      # Timeline: deploy → anomaly → error
│   └── root_cause_ranker.py     # Multi-signal heuristic ranking engine
├── cache/
│   └── redis_store.py           # Redis cache (optional, works without Redis)
├── tools/
│   └── mcp_tools.py             # ⭐ YOUR INTERFACE — 8 JSON tools + TOOL_REGISTRY
├── tests/
│   └── test_log_parser.py       # 5 passing tests
├── main.py                      # CLI agent (interactive + auto mode)
├── requirements.txt             # redis, python-dateutil
└── DEV2_HANDOFF.md              # This file
```

### The Demo Scenario

A deploy of `payment-service v2.4.1` removed null-safety checks in `PaymentService.java`. New users without a `billing_address` hit a `NullPointerException` at line 84. The system detects this at **100% confidence** by cross-referencing the stack trace with the git diff.

---

## Your Interface — `tools/mcp_tools.py`

This is the **only file you need to import from**. Every tool takes simple types and returns a `dict` with a `"status"` key.

### How to Import

```python
# Option 1: Import specific tools
from tools.mcp_tools import (
    tool_get_logs,
    tool_extract_stack_trace,
    tool_find_failure_times,
    tool_get_git_diff,
    tool_rank_root_causes,
    tool_generate_timeline,
    tool_check_cache,
    tool_store_result,
)

# Option 2: Use the registry (for dynamic agent loop)
from tools.mcp_tools import TOOL_REGISTRY

for name, info in TOOL_REGISTRY.items():
    print(f"{name}: {info['description']}")
    # Call it: info["function"](**kwargs)
```

### Tool Reference

#### `tool_get_logs(service, time_window) → dict`
```python
>>> tool_get_logs(service="payment-service", time_window="1h")
{
    "status": "success",
    "service": "payment-service",
    "log_count": 60,
    "source": "local_file",
    "logs": "2026-04-24T09:55:00Z INFO  [deploy-agent] Starting..."
}
```

#### `tool_extract_stack_trace(logs) → dict`
```python
>>> tool_extract_stack_trace(logs=raw_logs)
{
    "status": "success",
    "trace_count": 1,
    "traces": [{
        "exception_type": "java.lang.NullPointerException",
        "exception_message": "Cannot invoke method on null reference",
        "frames": [
            {"class_name": "com.acme.payment.PaymentService", "method": "processPayment", "file": "PaymentService.java", "line": 84},
            {"class_name": "com.acme.payment.PaymentService", "method": "validateUser", "file": "PaymentService.java", "line": 67},
            ...
        ]
    }]
}
```

#### `tool_find_failure_times(logs, deploy_time) → dict`
```python
>>> tool_find_failure_times(logs=raw_logs, deploy_time="2026-04-24T09:55:18Z")
{
    "status": "success",
    "deploy_time": "2026-04-24T09:55:18+00:00Z",
    "first_anomaly_time": "2026-04-24T09:59:31+00:00Z",
    "first_error_time": "2026-04-24T10:00:16+00:00Z",
    "time_to_anomaly_seconds": 253.0,
    "time_to_failure_seconds": 298.0,
    "anomaly_to_error_seconds": 45.0
}
```

#### `tool_get_git_diff(commit_id) → dict`
```python
>>> tool_get_git_diff(commit_id="a3f8b2c")
{
    "status": "success",
    "commit_id": "a3f8b2c",
    "diff": "commit a3f8b2c ...\ndiff --git a/src/..."
}
```

#### `tool_rank_root_causes(stack_trace_dict, git_diff, failure_times_dict) → dict`
```python
>>> tool_rank_root_causes(
...     stack_trace_dict=traces["traces"][0],  # dict from tool_extract_stack_trace
...     git_diff=diff_result["diff"],           # string from tool_get_git_diff
...     failure_times_dict=failure_result,       # dict from tool_find_failure_times
... )
{
    "status": "success",
    "candidate_count": 3,
    "candidates": [
        {
            "rank": 1,
            "description": "Recent code change removed null-safety checks...",
            "confidence": 1.0,
            "category": "code_change_null_safety",
            "evidence": ["Removed null-safety check in...", ...],
            "file": "PaymentService.java",
            "line": 84,
            "recommendation": "Restore the null check..."
        },
        ...
    ]
}
```

#### `tool_generate_timeline(logs, deploy_time) → dict`
```python
>>> tool_generate_timeline(logs=raw_logs, deploy_time="2026-04-24T09:55:18Z")
{
    "status": "success",
    "event_count": 19,
    "timeline": [
        {"timestamp": "2026-04-24T09:55:18+00:00Z", "event_type": "deploy", "description": "Deployment completed", "service": "deploy-agent"},
        {"timestamp": "2026-04-24T09:59:31+00:00Z", "event_type": "anomaly", "description": "Slow response from Stripe API...", "service": "payment-service"},
        ...
    ]
}
```

#### `tool_check_cache(service, exception_type, file, line) → dict`
```python
>>> tool_check_cache("payment-service", "java.lang.NullPointerException", "PaymentService.java", 84)
{"status": "cache_miss", "fingerprint": "a3b2c1d4e5f6..."}
# or
{"status": "cache_hit", "fingerprint": "...", "occurrences": 3, "cached_result": {...}}
```

#### `tool_store_result(service, exception_type, file, line, result) → dict`
```python
>>> tool_store_result("payment-service", "...", "PaymentService.java", 84, {"root_cause": ...})
{"status": "stored", "fingerprint": "...", "cache_available": true}
```

### Error Handling

All tools return `{"status": "error", "error": "message"}` on failure. Always check `result["status"]` before accessing other keys.

---

## What You Need To Build

### 1. Your TinyFish Tools (Add to `tools/mcp_tools.py` or create new file)

You need to implement these external intelligence tools:

```python
# tools/tinyfish_tools.py (suggested)

def tool_check_vendor_status(service_name: str, timestamp: str) -> dict:
    """Check if an external vendor had an outage around the incident time.
    
    Args:
        service_name: e.g., "stripe", "aws", "cloudflare"
        timestamp: ISO timestamp to check around
    
    Returns:
        {
            "status": "success",
            "vendor": "stripe",
            "has_outage": false,
            "details": "No reported incidents at 2026-04-24T10:00:00Z"
        }
    """
    # Use TinyFish to scrape status pages, or mock it for demo
    pass

def tool_search_related_incidents(error_message: str) -> dict:
    """Search the web for similar incidents / known issues.
    
    Args:
        error_message: e.g., "NullPointerException PaymentService"
    
    Returns:
        {
            "status": "success",
            "result_count": 3,
            "results": [
                {"source": "github.com/acme/issues/142", "title": "NPE after removing null check", "relevance": 0.9},
                ...
            ]
        }
    """
    # Use TinyFish for web search, or mock it
    pass
```

### 2. Agent Loop (Make It Smart)

Right now `main.py` calls tools in a hardcoded sequence. You can either:

**Option A: Keep it hardcoded but add your tools** — Fastest, just add steps 7-8 in `run_investigation()`:

```python
# In main.py, replace step_external_signals() with real calls:
def step_external_signals(failure_times, trace_result):
    step_header("7", "External intelligence (TinyFish)")
    
    # Check vendor status
    vendor = tool_check_vendor_status("stripe", failure_times["first_error_time"])
    if vendor["has_outage"]:
        warn(f"Vendor outage detected: {vendor['details']}")
    else:
        success(f"No vendor outage found for {vendor['vendor']}")
    
    # Search related incidents  
    error_msg = trace_result["traces"][0]["exception_type"]
    related = tool_search_related_incidents(error_msg)
    success(f"Found {related['result_count']} related incidents")
    
    return {"vendor_status": vendor, "related_incidents": related}
```

**Option B: LLM-driven agent loop** — The agent decides which tools to call dynamically based on the query. You'd replace `run_investigation()` with something like:

```python
def run_investigation(service, query, deploy_time):
    all_tools = {**TOOL_REGISTRY, **TINYFISH_REGISTRY}
    
    messages = [{"role": "user", "content": query}]
    
    while not done:
        # LLM picks the next tool to call
        tool_choice = llm.choose_tool(messages, available_tools=all_tools)
        
        # Execute it
        result = all_tools[tool_choice.name]["function"](**tool_choice.args)
        
        # Add result to context
        messages.append({"role": "tool", "content": json.dumps(result)})
        
        # LLM decides if it has enough info or needs more tools
        done = llm.should_stop(messages)
    
    # Generate final explanation
    return llm.explain(messages)
```

### 3. Update the CLI (in `main.py`)

Places you'll touch:

| Location | What to change |
|----------|---------------|
| `step_external_signals()` | Replace placeholder with real TinyFish calls |
| `print_final_report()` | Add external signals to the final output |
| `run_investigation()` | Add external signal results to the flow |
| Optionally: add `--query` flag | Let user pass natural language query for LLM agent |

### 4. Register Your Tools (Optional but Clean)

If you add tools, register them so the agent can discover them:

```python
# In tools/mcp_tools.py or tools/tinyfish_tools.py
TINYFISH_REGISTRY = {
    "check_vendor_status": {
        "function": tool_check_vendor_status,
        "description": "Check external vendor for outages",
        "parameters": {"service_name": "str", "timestamp": "str"},
    },
    "search_related_incidents": {
        "function": tool_search_related_incidents,
        "description": "Search web for similar incidents",
        "parameters": {"error_message": "str"},
    },
}
```

---

## How to Run & Test

```bash
# Full auto demo (your changes should work with this)
python main.py --auto

# Interactive mode
python main.py

# Run existing tests (all should still pass)
python tests/test_log_parser.py

# Test a specific tool
python -c "from tools.mcp_tools import tool_get_logs; print(tool_get_logs()['status'])"
```

### Important: Set encoding on Windows
```bash
$env:PYTHONIOENCODING="utf-8"
```

---

## Rules / Contracts

1. **Every tool returns a `dict` with a `"status"` key** — `"success"`, `"error"`, `"cache_hit"`, etc.
2. **On error, include an `"error"` key** with the message.
3. **All timestamps use ISO format** with timezone: `"2026-04-24T10:00:16+00:00Z"`.
4. **Don't import from `core/` or `cache/` directly** — go through `tools/mcp_tools.py`.
5. **Redis is optional** — the system works without it. Don't add hard Redis dependencies.
6. **Python 3.10** is what we're running on.

---

## Questions? Coordinate On

- [ ] Do we want LLM-driven tool selection (Option B) or hardcoded sequence (Option A)?
- [ ] What TinyFish API/SDK are we using? Or mocking for demo?
- [ ] Should the final output be just CLI, or also write to a file/JSON?
- [ ] Any additional `--flags` we want on the CLI?
