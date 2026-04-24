"""
Log Parser — Regex-based deterministic log parsing.

Extracts structured events from raw application logs including
timestamps, severity levels, service names, messages, and
embedded stack traces.
"""

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches: 2026-04-24T10:00:16Z ERROR [payment-service] Some message
LOG_LINE_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T[\d:]+Z)\s+"   # timestamp
    r"(INFO|WARN|ERROR)\s+"                # severity
    r"\[([^\]]+)\]\s+"                     # service name
    r"(.+)$"                               # message
)

# Matches: at com.acme.payment.PaymentService.processPayment(PaymentService.java:84)
STACK_FRAME_PATTERN = re.compile(
    r"^\s+at\s+"                             # leading whitespace + "at "
    r"([\w.$]+)\."                           # fully qualified class
    r"(\w+)"                                 # method name
    r"\(([^:]+):(\d+)\)$"                    # (FileName.java:lineNo)
)

# Matches: java.lang.NullPointerException: Cannot invoke method on null reference
EXCEPTION_PATTERN = re.compile(
    r"^([\w.]+(?:Exception|Error)):\s+(.+)$"
)

# Matches exception line embedded inside a log message
INLINE_EXCEPTION_PATTERN = re.compile(
    r"([\w.]+(?:Exception|Error))\s+at\s+([\w.]+):(\d+)"
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LogEntry:
    """A single parsed log line."""
    timestamp: datetime
    level: str          # INFO, WARN, ERROR
    service: str
    message: str
    raw: str

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat() + "Z"
        return d


@dataclass
class StackFrame:
    """One frame in a stack trace."""
    class_name: str
    method: str
    file: str
    line: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StackTrace:
    """A complete stack trace with exception info and frames."""
    exception_type: str
    exception_message: str
    frames: List[StackFrame] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "frames": [f.to_dict() for f in self.frames],
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class LogParser:
    """Deterministic regex-based log parser."""

    def parse(self, raw_logs: str) -> List[LogEntry]:
        """Parse raw log text into structured LogEntry objects.

        Lines that don't match the expected log format (e.g. stack trace
        continuation lines) are silently skipped.
        """
        entries: List[LogEntry] = []
        for line in raw_logs.splitlines():
            line = line.strip()
            if not line:
                continue
            m = LOG_LINE_PATTERN.match(line)
            if m:
                ts_str, level, service, message = m.groups()
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                entries.append(LogEntry(
                    timestamp=ts,
                    level=level,
                    service=service,
                    message=message,
                    raw=line,
                ))
        return entries

    def extract_stack_traces(self, raw_logs: str) -> List[StackTrace]:
        """Extract all stack traces found in the log text.

        Handles two formats:
        1. Standalone exception lines: ``java.lang.NPE: msg``
        2. Embedded in log lines: ``TIMESTAMP ERROR [svc] java.lang.NPE: msg``

        In both cases, collects subsequent ``at ...`` / ``\\tat ...`` frame
        lines into StackTrace objects.
        """
        traces: List[StackTrace] = []
        lines = raw_logs.splitlines()
        i = 0
        seen_sigs: set = set()  # deduplicate identical traces

        while i < len(lines):
            raw_line = lines[i]
            line = raw_line.strip()
            exc_match = None

            # Try 1: standalone exception line
            exc_match = EXCEPTION_PATTERN.match(line)

            # Try 2: exception embedded in a log line message
            if not exc_match:
                log_match = LOG_LINE_PATTERN.match(line)
                if log_match:
                    message = log_match.group(4)
                    exc_match = EXCEPTION_PATTERN.match(message)

            if exc_match:
                trace = StackTrace(
                    exception_type=exc_match.group(1),
                    exception_message=exc_match.group(2),
                )
                i += 1
                # Collect frames (handle both \t and spaces before "at")
                while i < len(lines):
                    frame_match = STACK_FRAME_PATTERN.match(lines[i])
                    if frame_match:
                        class_name, method, filename, lineno = frame_match.groups()
                        trace.frames.append(StackFrame(
                            class_name=class_name,
                            method=method,
                            file=filename,
                            line=int(lineno),
                        ))
                        i += 1
                    else:
                        break
                # Only add if it has frames and we haven't seen it before
                if trace.frames:
                    sig = (trace.exception_type, trace.frames[0].file, trace.frames[0].line)
                    if sig not in seen_sigs:
                        seen_sigs.add(sig)
                        traces.append(trace)
            else:
                i += 1
        return traces

    def get_first_error(self, entries: List[LogEntry]) -> Optional[LogEntry]:
        """Return the first ERROR-level entry, or None."""
        for entry in entries:
            if entry.level == "ERROR":
                return entry
        return None

    def get_first_anomaly(self, entries: List[LogEntry]) -> Optional[LogEntry]:
        """Return the first WARN-level entry (earliest anomaly signal)."""
        for entry in entries:
            if entry.level == "WARN":
                return entry
        return None

    def get_errors(self, entries: List[LogEntry]) -> List[LogEntry]:
        """Return all ERROR-level entries."""
        return [e for e in entries if e.level == "ERROR"]

    def get_warnings(self, entries: List[LogEntry]) -> List[LogEntry]:
        """Return all WARN-level entries."""
        return [e for e in entries if e.level == "WARN"]

    def get_entries_by_service(
        self, entries: List[LogEntry], service: str
    ) -> List[LogEntry]:
        """Filter entries by service name."""
        return [e for e in entries if e.service == service]
