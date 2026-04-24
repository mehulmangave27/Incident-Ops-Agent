"""
Incident Investigation CLI Agent

Interactive command-line agent that investigates software failures
by reasoning over logs, stack traces, code changes, and (when Dev2
integrates) external web signals via TinyFish.

Usage:
    python main.py
    python main.py --service payment-service --deploy-time 2026-04-24T09:55:18Z
    python main.py --auto   (skip prompts, run full investigation)
"""

import argparse
import json
import sys
import os
import time
import subprocess

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

# Load .env for TINYFISH_API_KEY
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from tools.mcp_tools import (
    tool_get_logs,
    tool_get_git_diff,
    tool_extract_stack_trace,
    tool_find_failure_times,
    tool_rank_root_causes,
    tool_generate_timeline,
    tool_check_cache,
    tool_store_result,
    TOOL_REGISTRY,
)
from tools.tinyfish_tools import (
    tool_check_vendor_status,
    tool_search_related_incidents,
    TINYFISH_REGISTRY,
)


# ------------------------------------------------------------------
# Theme / colors (works on Windows 10+ and most terminals)
# ------------------------------------------------------------------

class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_BLUE = "\033[44m"


def c(text, color):
    return f"{color}{text}{Colors.RESET}"


# ------------------------------------------------------------------
# Display helpers
# ------------------------------------------------------------------

def banner():
    print()
    print(c("=" * 64, Colors.CYAN))
    print(c("  INCIDENT-OPS AGENT", Colors.BOLD + Colors.CYAN))
    print(c("  Autonomous Incident Investigation System", Colors.DIM))
    print(c("=" * 64, Colors.CYAN))
    print()


def step_header(num, title):
    print(c(f"\n  [{num}] {title}", Colors.BOLD + Colors.BLUE))
    print(c("  " + "-" * 50, Colors.DIM))


def thinking(msg):
    """Simulates the agent 'thinking' with a brief pause."""
    print(c(f"      > {msg}", Colors.DIM), end="", flush=True)
    time.sleep(0.3)
    print(c(" done", Colors.GREEN))


def success(msg):
    print(c(f"      [OK] {msg}", Colors.GREEN))


def warn(msg):
    print(c(f"      [!!] {msg}", Colors.YELLOW))


def error(msg):
    print(c(f"      [ERR] {msg}", Colors.RED))


def info(msg):
    print(c(f"      {msg}", Colors.WHITE))


# ------------------------------------------------------------------
# Git helpers
# ------------------------------------------------------------------

def _run_git(args: list[str], repo_path: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + args,
        capture_output=True,
        text=True,
        cwd=repo_path,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()

def get_deploy_time(repo_path: str) -> str:
    """Get the ISO timestamp of the latest commit (= deploy time) in strict UTC."""
    env = os.environ.copy()
    env["TZ"] = "UTC"
    result = subprocess.run(
        ["git", "log", "-1", "--date=format-local:%Y-%m-%dT%H:%M:%SZ", "--format=%cd"],
        capture_output=True, text=True, cwd=repo_path, env=env
    )
    return result.stdout.strip()

def get_git_diff_from_repo(repo_path: str, num_commits: int = 1) -> str:
    """Get the diff of the last N commits."""
    return _run_git(["log", f"-{num_commits}", "-p", "--no-color"], repo_path)

def get_latest_commit_info(repo_path: str) -> dict:
    """Get summary info about the latest commit."""
    env = os.environ.copy()
    env["TZ"] = "UTC"
    result = subprocess.run(
        ["git", "log", "-1", "--date=format-local:%Y-%m-%dT%H:%M:%SZ", "--format=%H%n%an%n%cd%n%s"],
        capture_output=True, text=True, cwd=repo_path, env=env
    )
    lines = result.stdout.strip().splitlines()
    return {
        "hash": lines[0] if len(lines) > 0 else "?",
        "author": lines[1] if len(lines) > 1 else "?",
        "time": lines[2] if len(lines) > 2 else "?",
        "subject": lines[3] if len(lines) > 3 else "?",
    }


# ------------------------------------------------------------------
# Agent steps
# ------------------------------------------------------------------

def step_check_cache(service, exception_type, file, line):
    """Step 0: Check if we've investigated this before."""
    step_header("0", "Checking incident cache")
    thinking("Generating fingerprint and checking Redis...")
    result = tool_check_cache(service, exception_type, file, line)
    if result["status"] == "cache_hit":
        success(f"Cache HIT! Seen {result['occurrences']} time(s) before.")
        return result["cached_result"]
    else:
        info(f"Cache miss (fingerprint: {result['fingerprint']}). Running full analysis.")
        return None


def step_get_logs(service, time_window="1h"):
    """Step 1: Retrieve logs."""
    step_header("1", f"Retrieving logs for '{service}'")
    thinking("Fetching log data...")
    result = tool_get_logs(service=service, time_window=time_window)
    if result["status"] != "success":
        error(result.get("error", "Unknown error"))
        return None
    success(f"Retrieved {result['log_count']} log lines (source: {result['source']})")
    return result["logs"]


def step_extract_traces(raw_logs):
    """Step 2: Extract stack traces."""
    step_header("2", "Extracting stack traces from logs")
    thinking("Scanning for exception patterns...")
    result = tool_extract_stack_trace(raw_logs)
    if result["trace_count"] == 0:
        warn("No stack traces found in logs.")
        return None
    trace = result["traces"][0]
    success(f"Found {result['trace_count']} stack trace(s)")
    info(f"Exception: {c(trace['exception_type'], Colors.RED)}")
    info(f"Message:   {trace['exception_message']}")
    info(f"Top frame: {c(trace['frames'][0]['file'] + ':' + str(trace['frames'][0]['line']), Colors.YELLOW)}"
         f" ({trace['frames'][0]['method']})")
    return result


def step_failure_timeline(raw_logs, deploy_time):
    """Step 3: Detect failure timeline."""
    step_header("3", "Analyzing failure timeline")
    thinking("Correlating events with deploy time...")
    result = tool_find_failure_times(raw_logs, deploy_time)
    if result["status"] != "success":
        error(result.get("error", "Unknown error"))
        return None

    info(f"Deploy:       {result['deploy_time']}")
    if result.get("first_anomaly_time"):
        tta = result.get("time_to_anomaly_seconds", "?")
        info(f"1st anomaly:  {result['first_anomaly_time']}  ({c(f'+{tta:.0f}s', Colors.YELLOW)})")
    if result.get("first_error_time"):
        ttf = result.get("time_to_failure_seconds", "?")
        info(f"1st error:    {result['first_error_time']}  ({c(f'+{ttf:.0f}s', Colors.RED)})")
    return result


def step_git_diff(local_diff: str = None):
    """Step 4: Retrieve recent code changes."""
    step_header("4", "Retrieving recent code changes")
    thinking("Fetching git diff for latest commit...")
    
    if local_diff is not None:
        diff_lines = local_diff.count("\n")
        success(f"Retrieved diff ({diff_lines} lines changed from local repo)")
        return local_diff
        
    result = tool_get_git_diff()
    if result["status"] != "success":
        error(result.get("error", "Unknown error"))
        return None
    diff_lines = result["diff"].count("\n")
    success(f"Retrieved diff ({diff_lines} lines changed in commit {result.get('commit_id', '?')})")
    return result["diff"]


def step_rank_causes(trace_result, git_diff, failure_times):
    """Step 5: Rank root causes."""
    step_header("5", "Ranking root cause candidates")
    thinking("Cross-referencing stack trace, diff, and timeline...")
    result = tool_rank_root_causes(
        stack_trace_dict=trace_result["traces"][0],
        git_diff=git_diff,
        failure_times_dict=failure_times,
    )
    if result["status"] != "success":
        error(result.get("error", "Unknown error"))
        return None

    success(f"Identified {result['candidate_count']} candidate(s)\n")
    for cand in result["candidates"]:
        conf = cand["confidence"]
        bar_len = int(conf * 20)
        bar = c("█" * bar_len, Colors.GREEN if conf >= 0.7 else Colors.YELLOW if conf >= 0.4 else Colors.RED)
        bar += c("░" * (20 - bar_len), Colors.DIM)

        print(f"      #{cand['rank']}  {bar}  {c(f'{conf:.0%}', Colors.BOLD)}")
        print(f"         {cand['description']}")
        if cand.get("file"):
            print(f"         File: {c(cand['file'] + ':' + str(cand.get('line', '?')), Colors.YELLOW)}")
        if cand.get("recommendation"):
            print(f"         Fix:  {c(cand['recommendation'], Colors.GREEN)}")
        print(f"         Evidence:")
        for ev in cand["evidence"][:5]:  # limit to 5 for readability
            print(f"           - {ev}")
        if len(cand["evidence"]) > 5:
            print(f"           ... and {len(cand['evidence']) - 5} more")
        print()

    return result


def step_timeline(raw_logs, deploy_time):
    """Step 6: Generate incident timeline."""
    step_header("6", "Generating incident timeline")
    thinking("Ordering and classifying events...")
    result = tool_generate_timeline(raw_logs, deploy_time)
    if result["status"] != "success":
        error(result.get("error", "Unknown error"))
        return None

    success(f"{result['event_count']} events\n")
    icons = {
        "deploy": ">>",
        "anomaly": "??",
        "error": "XX",
        "degradation": "vv",
        "alert": "!!",
        "recovery": "OK",
    }
    colors = {
        "deploy": Colors.CYAN,
        "anomaly": Colors.YELLOW,
        "error": Colors.RED,
        "degradation": Colors.MAGENTA,
        "alert": Colors.RED + Colors.BOLD,
        "recovery": Colors.GREEN,
    }
    for event in result["timeline"]:
        etype = event["event_type"]
        icon = icons.get(etype, "  ")
        col = colors.get(etype, Colors.WHITE)
        ts = event["timestamp"][-15:-1] if len(event["timestamp"]) > 15 else event["timestamp"]
        print(f"      {c(ts, Colors.DIM)}  {c(f'[{icon}]', col)}  "
              f"{c(event['description'][:75], col)}")

    return result


def step_external_signals(failure_times, trace_result):
    """Step 7: External intelligence via TinyFish."""
    step_header("7", "External intelligence (TinyFish)")
    external = {"vendor_status": None, "related_incidents": None}

    # --- 7a: Vendor status ---
    thinking("Checking vendor status pages...")
    vendor_name = _detect_vendor(trace_result)
    timestamp = ""
    if failure_times and failure_times.get("first_error_time"):
        timestamp = failure_times["first_error_time"]

    vendor = tool_check_vendor_status(vendor_name, timestamp)
    if vendor["status"] == "success":
        external["vendor_status"] = vendor
        if vendor["has_outage"]:
            warn(f"{vendor['vendor']} outage detected: {vendor['details']}")
        else:
            success(f"{vendor['vendor']}: {vendor['overall_status']} — no outage")
    elif vendor["status"] == "error":
        warn(f"Vendor check: {vendor['error']}")

    # --- 7b: Related incidents ---
    thinking("Searching web for similar incidents...")
    error_msg = ""
    if trace_result and trace_result.get("traces"):
        t = trace_result["traces"][0]
        error_msg = f"{t['exception_type']} {t['frames'][0]['file']}"

    related = tool_search_related_incidents(error_msg)
    if related["status"] == "success":
        external["related_incidents"] = related
        success(f"Found {related['result_count']} related incidents")
        for r in related.get("results", [])[:3]:
            info(f"  [{r['source']}] {r['title']}")
    elif related["status"] == "error":
        warn(f"Web search: {related['error']}")

    return external


def _detect_vendor(trace_result):
    """Heuristic: Try to figure out which vendor might be relevant."""
    # For the demo scenario, the logs mention Stripe
    # In a real system, this would scan logs/stack trace for vendor keywords
    vendors = ["stripe", "aws", "github", "cloudflare", "datadog", "pagerduty"]
    if trace_result and trace_result.get("traces"):
        text = json.dumps(trace_result).lower()
        for v in vendors:
            if v in text:
                return v
    return "stripe"  # default for demo


# ------------------------------------------------------------------
# Final report
# ------------------------------------------------------------------

def print_final_report(ranking_result, timeline_result, failure_times, external=None):
    """Print the final investigation summary."""
    print()
    print(c("=" * 64, Colors.GREEN))
    print(c("  INVESTIGATION COMPLETE", Colors.BOLD + Colors.GREEN))
    print(c("=" * 64, Colors.GREEN))

    if ranking_result and ranking_result.get("candidates"):
        top = ranking_result["candidates"][0]
        print(f"""
  {c('Root Cause:', Colors.BOLD)}   {top['description']}
  {c('Confidence:', Colors.BOLD)}   {c(f"{top['confidence']:.0%}", Colors.GREEN if top['confidence'] >= 0.7 else Colors.YELLOW)}
  {c('Category:', Colors.BOLD)}     {top['category']}
  {c('File:', Colors.BOLD)}         {top.get('file', 'N/A')}:{top.get('line', 'N/A')}
  {c('Fix:', Colors.BOLD)}          {top.get('recommendation', 'N/A')}""")

        if failure_times:
            ttf = failure_times.get('time_to_failure_seconds')
            if ttf:
                print(f"  {c('Time to fail:', Colors.BOLD)}  {ttf:.0f}s after deploy")

    # --- External signals section ---
    if external:
        print()
        print(c("  ── External Intelligence ──", Colors.BOLD + Colors.CYAN))

        vendor = external.get("vendor_status")
        if vendor and vendor.get("status") == "success":
            v_icon = c("⚠ OUTAGE", Colors.RED + Colors.BOLD) if vendor["has_outage"] else c("✓ OK", Colors.GREEN)
            print(f"  {c('Vendor:', Colors.BOLD)}       {vendor['vendor']} — {v_icon}")
            print(f"  {c('Status:', Colors.BOLD)}       {vendor['overall_status']}")
            if vendor.get("incidents"):
                for inc in vendor["incidents"][:2]:
                    print(f"                  • {inc.get('title', 'N/A')} ({inc.get('severity', '?')})")

        related = external.get("related_incidents")
        if related and related.get("status") == "success" and related.get("results"):
            print(f"  {c('Web Results:', Colors.BOLD)}  {related['result_count']} similar incidents found")
            for r in related["results"][:3]:
                print(f"                  • [{r['source']}] {r['title']}")

    print()
    print(c("=" * 64, Colors.GREEN))


# ------------------------------------------------------------------
# Interactive mode
# ------------------------------------------------------------------

def interactive_prompt():
    """Ask the user what to investigate."""
    print(c("  What would you like to investigate?", Colors.BOLD))
    print()
    print(f"    {c('1', Colors.CYAN)} - Run full investigation on payment-service (demo scenario)")
    print(f"    {c('2', Colors.CYAN)} - Investigate a custom service")
    print(f"    {c('3', Colors.CYAN)} - List available tools")
    print(f"    {c('q', Colors.CYAN)} - Quit")
    print()

    choice = input(c("  > ", Colors.CYAN)).strip()
    return choice


def list_tools():
    """Display all available tools."""
    step_header("?", "Available MCP Tools (Dev1)")
    for name, info in TOOL_REGISTRY.items():
        params = ", ".join(f"{k}: {v}" for k, v in info["parameters"].items())
        print(f"      {c(name, Colors.YELLOW)}({c(params, Colors.DIM)})")
        print(f"        {info['description']}")
    print()
    step_header("?", "TinyFish Tools (Dev2)")
    for name, info in TINYFISH_REGISTRY.items():
        params = ", ".join(f"{k}: {v}" for k, v in info["parameters"].items())
        print(f"      {c(name, Colors.YELLOW)}({c(params, Colors.DIM)})")
        print(f"        {info['description']}")
    print()


# ------------------------------------------------------------------
# Main investigation runner
# ------------------------------------------------------------------

def run_investigation(service="payment-service", deploy_time="2026-04-24T09:55:18Z", git_diff_override=None):
    """Run a complete incident investigation."""

    # Step 1: Get logs
    raw_logs = step_get_logs(service)
    if not raw_logs:
        return

    # Step 2: Extract stack traces
    trace_result = step_extract_traces(raw_logs)

    # Step 3: Failure timeline
    failure_times = step_failure_timeline(raw_logs, deploy_time)

    # Step 4: Git diff
    git_diff = step_git_diff(local_diff=git_diff_override)

    # Step 5: Rank root causes
    ranking_result = None
    if trace_result and trace_result.get("traces") and git_diff and failure_times:
        ranking_result = step_rank_causes(trace_result, git_diff, failure_times)

    # Step 6: Timeline
    timeline_result = step_timeline(raw_logs, deploy_time)

    # Step 7: External signals (TinyFish)
    external = step_external_signals(failure_times, trace_result)

    # Final report
    print_final_report(ranking_result, timeline_result, failure_times, external)

    # Attempt to cache result
    if ranking_result and ranking_result.get("candidates") and trace_result.get("traces"):
        top_trace = trace_result["traces"][0]
        top_candidate = ranking_result["candidates"][0]
        tool_store_result(
            service=service,
            exception_type=top_trace["exception_type"],
            file=top_trace["frames"][0]["file"],
            line=top_trace["frames"][0]["line"],
            result={
                "root_cause": top_candidate,
                "failure_times": failure_times,
                "external_signals": external,
            },
        )

    return ranking_result


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main():
    # Enable ANSI colors on Windows
    os.system("")

    parser = argparse.ArgumentParser(
        description="Incident-Ops Agent — Autonomous incident investigation",
    )
    parser.add_argument("--service", default="payment-service",
                        help="Service name to investigate (default: payment-service)")
    parser.add_argument("--deploy-time", default="2026-04-24T09:55:18Z",
                        help="Deploy timestamp in ISO format")
    parser.add_argument("--repo", default=None,
                        help="Path to git repo to extract real diff and deploy time from (overrides static dev1 values)")
    parser.add_argument("--commits", type=int, default=1,
                        help="If using --repo, number of commits to include in diff")
    parser.add_argument("--auto", action="store_true",
                        help="Run full investigation without prompts")
    args = parser.parse_args()

    banner()

    # If --repo is provided, compute real dynamic git diff & deploy time overrides
    git_diff_override = None
    deploy_time = args.deploy_time

    if args.repo:
        repo_path = os.path.abspath(args.repo)
        try:
            commit_info = get_latest_commit_info(repo_path)
            deploy_time = commit_info["time"]
            git_diff_override = get_git_diff_from_repo(repo_path, args.commits)
            info(f"Loaded real repo context from: {c(repo_path, Colors.CYAN)}")
            info(f"Latest commit: {c(commit_info['hash'][:8], Colors.CYAN)} ({commit_info['subject']})")
            info(f"Deploy time dynamically updated to: {c(deploy_time, Colors.CYAN)}\n")
        except RuntimeError as e:
            error(f"Git extraction failed: {e}")
            sys.exit(1)

    if args.auto:
        run_investigation(service=args.service, deploy_time=deploy_time, git_diff_override=git_diff_override)
        return

    # Interactive loop
    while True:
        choice = interactive_prompt()

        if choice == "1":
            run_investigation()
        elif choice == "2":
            svc = input(c("  Service name: ", Colors.CYAN)).strip() or "payment-service"
            
            repo_q = input(c("  Path to git repo (leave blank for demo diff): ", Colors.CYAN)).strip()
            if repo_q:
                try:
                    repo_path = os.path.abspath(repo_q)
                    commit_info = get_latest_commit_info(repo_path)
                    dt = commit_info["time"]
                    git_override = get_git_diff_from_repo(repo_path, 1)
                    print(c(f"  [OK] Extracted deploy time {dt} from repo\n", Colors.GREEN))
                    run_investigation(service=svc, deploy_time=dt, git_diff_override=git_override)
                except Exception as e:
                    error(f"Failed to read from repo: {e}")
            else:
                dt = input(c("  Deploy time (ISO): ", Colors.CYAN)).strip() or "2026-04-24T09:55:18Z"
                run_investigation(service=svc, deploy_time=dt)
        elif choice == "3":
            list_tools()
        elif choice.lower() == "q":
            print(c("\n  Goodbye!\n", Colors.DIM))
            break
        else:
            warn("Invalid choice. Try 1, 2, 3, or q.")


if __name__ == "__main__":
    main()
