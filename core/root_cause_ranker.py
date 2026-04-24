"""
Root Cause Ranker — Heuristic-based root cause analysis.

Correlates stack traces, git diffs, and failure timelines to rank
potential root cause candidates by confidence score.
"""

import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

from core.log_parser import StackTrace, StackFrame
from core.failure_detector import FailureTimes


@dataclass
class RootCauseCandidate:
    """A ranked root cause hypothesis."""
    rank: int
    description: str
    confidence: float           # 0.0 – 1.0
    category: str               # code_change, null_safety, external_dependency, etc.
    evidence: List[str] = field(default_factory=list)
    file: Optional[str] = None
    line: Optional[int] = None
    recommendation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Diff parsing helpers
# ---------------------------------------------------------------------------

def _parse_diff_hunks(git_diff: str) -> List[dict]:
    """Extract changed files and line ranges from a unified diff.

    Returns a list of dicts with keys:
      - file: the filename
      - removed_lines: list of removed line strings
      - added_lines: list of added line strings
    """
    hunks = []
    current_file = None
    removed = []
    added = []

    for line in git_diff.splitlines():
        # Detect file header
        if line.startswith("diff --git"):
            if current_file:
                hunks.append({
                    "file": current_file,
                    "removed_lines": removed,
                    "added_lines": added,
                })
            # Extract filename: diff --git a/path/to/file b/path/to/file
            parts = line.split()
            if len(parts) >= 4:
                current_file = parts[3].lstrip("b/")
            removed = []
            added = []
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:].strip())
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:].strip())

    # Don't forget last hunk
    if current_file:
        hunks.append({
            "file": current_file,
            "removed_lines": removed,
            "added_lines": added,
        })

    return hunks


def _check_null_safety_removal(hunks: List[dict]) -> List[str]:
    """Check if any removed lines contained null safety checks."""
    evidence = []
    null_patterns = [
        r"if\s*\(.+==\s*null\)",
        r"if\s*\(.+!=\s*null\)",
        r"null\s*check",
        r"\.isPresent\(\)",
        r"Optional\.",
    ]
    for hunk in hunks:
        for removed_line in hunk["removed_lines"]:
            for pattern in null_patterns:
                if re.search(pattern, removed_line, re.IGNORECASE):
                    evidence.append(
                        f"Removed null-safety check in {hunk['file']}: '{removed_line}'"
                    )
    return evidence


def _check_stack_trace_file_overlap(
    stack_trace: StackTrace, hunks: List[dict]
) -> List[str]:
    """Check if files in the stack trace overlap with changed files in the diff."""
    evidence = []
    changed_files = {h["file"] for h in hunks}
    for frame in stack_trace.frames:
        for changed in changed_files:
            if frame.file in changed or changed.endswith(frame.file):
                evidence.append(
                    f"Stack trace frame {frame.file}:{frame.line} "
                    f"({frame.method}) matches changed file {changed}"
                )
    return evidence


def _check_removed_fallback_logic(hunks: List[dict]) -> List[str]:
    """Check if fallback/retry logic was removed."""
    evidence = []
    fallback_patterns = [
        r"fallback",
        r"retry",
        r"default",
        r"findBy\w+",  # e.g., findByExternalId as a fallback
    ]
    for hunk in hunks:
        for removed_line in hunk["removed_lines"]:
            for pattern in fallback_patterns:
                if re.search(pattern, removed_line, re.IGNORECASE):
                    evidence.append(
                        f"Removed fallback logic in {hunk['file']}: '{removed_line}'"
                    )
                    break  # one match per line is enough
    return evidence


# ---------------------------------------------------------------------------
# Main ranking function
# ---------------------------------------------------------------------------

def rank_root_causes(
    stack_trace: StackTrace,
    git_diff: str,
    failure_times: FailureTimes,
) -> List[RootCauseCandidate]:
    """Rank potential root causes by analysing evidence from multiple signals.

    Heuristics:
    1. Stack trace ↔ diff file overlap → high signal
    2. Null safety removal + NullPointerException → very high signal
    3. Removed fallback logic → medium signal
    4. Temporal correlation (quick failure after deploy) → supporting signal
    """
    candidates: List[RootCauseCandidate] = []
    hunks = _parse_diff_hunks(git_diff)

    # -----------------------------------------------------------------------
    # Candidate 1: Code change removed null safety
    # -----------------------------------------------------------------------
    null_evidence = _check_null_safety_removal(hunks)
    file_overlap = _check_stack_trace_file_overlap(stack_trace, hunks)
    fallback_evidence = _check_removed_fallback_logic(hunks)

    if null_evidence or file_overlap:
        confidence = 0.50

        # Boost for null-safety removal + NPE
        if null_evidence and "NullPointerException" in stack_trace.exception_type:
            confidence += 0.30

        # Boost for file overlap
        if file_overlap:
            confidence += 0.15

        # Boost for removed fallback
        if fallback_evidence:
            confidence += 0.05

        # Cap at 1.0
        confidence = min(confidence, 1.0)

        # Find the most relevant frame
        top_frame = stack_trace.frames[0] if stack_trace.frames else None

        all_evidence = null_evidence + file_overlap + fallback_evidence
        if failure_times.time_to_failure_seconds is not None:
            all_evidence.append(
                f"Failure occurred {failure_times.time_to_failure_seconds:.0f}s "
                f"after deployment"
            )

        candidates.append(RootCauseCandidate(
            rank=0,  # will be set after sorting
            description=(
                f"Recent code change removed null-safety checks in "
                f"{top_frame.file if top_frame else 'unknown file'}, causing "
                f"{stack_trace.exception_type} for inputs with missing fields."
            ),
            confidence=confidence,
            category="code_change_null_safety",
            evidence=all_evidence,
            file=top_frame.file if top_frame else None,
            line=top_frame.line if top_frame else None,
            recommendation=(
                "Restore the null check / fallback logic that was removed in the "
                "recent commit, or add proper validation before accessing "
                "billing_address fields."
            ),
        ))

    # -----------------------------------------------------------------------
    # Candidate 2: Temporal correlation (fast failure post-deploy)
    # -----------------------------------------------------------------------
    if failure_times.time_to_failure_seconds is not None:
        ttf = failure_times.time_to_failure_seconds
        if ttf < 600:  # Failed within 10 minutes of deploy
            confidence = 0.40 if ttf < 300 else 0.25
            candidates.append(RootCauseCandidate(
                rank=0,
                description=(
                    f"Service began failing {ttf:.0f}s after deployment, "
                    f"suggesting the deploy introduced a regression."
                ),
                confidence=confidence,
                category="temporal_correlation",
                evidence=[
                    f"Deploy at {failure_times.deploy_time.isoformat()}",
                    f"First error at {failure_times.first_error_time.isoformat()}",
                    f"Time to failure: {ttf:.0f} seconds",
                ],
                recommendation="Consider rolling back to the previous version.",
            ))

    # -----------------------------------------------------------------------
    # Candidate 3: External dependency issue (Stripe latency)
    # -----------------------------------------------------------------------
    # Check if warnings mention external service latency
    stripe_evidence = []
    for hunk in hunks:
        for line in hunk.get("added_lines", []):
            if "stripe" in line.lower() or "external" in line.lower():
                stripe_evidence.append(f"Diff references external service: '{line}'")

    if failure_times.first_anomaly_time and failure_times.first_error_time:
        gap = failure_times.anomaly_to_error_seconds
        if gap and gap > 0:
            stripe_evidence.append(
                f"Anomaly preceded error by {gap:.0f}s — possible external degradation"
            )

    if stripe_evidence:
        candidates.append(RootCauseCandidate(
            rank=0,
            description=(
                "External dependency (e.g. Stripe API) may have contributed "
                "to degraded performance before the failure cascade."
            ),
            confidence=0.20,
            category="external_dependency",
            evidence=stripe_evidence,
            recommendation=(
                "Check vendor status pages for outages around the incident time. "
                "Consider adding circuit breakers for external API calls."
            ),
        ))

    # -----------------------------------------------------------------------
    # Sort by confidence and assign ranks
    # -----------------------------------------------------------------------
    candidates.sort(key=lambda c: c.confidence, reverse=True)
    for i, candidate in enumerate(candidates):
        candidate.rank = i + 1

    return candidates
