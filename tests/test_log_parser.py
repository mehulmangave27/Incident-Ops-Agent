"""
Tests for the core log parser module.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.log_parser import LogParser


def test_parse_entries():
    """Test that log lines are correctly parsed into LogEntry objects."""
    raw = (
        "2026-04-24T10:00:00Z INFO  [payment-service] Service started\n"
        "2026-04-24T10:00:01Z WARN  [payment-service] Slow query\n"
        "2026-04-24T10:00:02Z ERROR [payment-service] NullPointerException\n"
    )
    parser = LogParser()
    entries = parser.parse(raw)

    assert len(entries) == 3, f"Expected 3 entries, got {len(entries)}"
    assert entries[0].level == "INFO"
    assert entries[1].level == "WARN"
    assert entries[2].level == "ERROR"
    assert entries[0].service == "payment-service"
    assert "Service started" in entries[0].message
    print("  ✓ test_parse_entries passed")


def test_extract_stack_traces():
    """Test stack trace extraction from logs."""
    raw = (
        "2026-04-24T10:00:00Z ERROR [svc] Something broke\n"
        "java.lang.NullPointerException: Cannot invoke method on null reference\n"
        "\tat com.acme.payment.PaymentService.processPayment(PaymentService.java:84)\n"
        "\tat com.acme.payment.PaymentController.handleRequest(PaymentController.java:42)\n"
        "2026-04-24T10:00:01Z INFO  [svc] Recovery\n"
    )
    parser = LogParser()
    traces = parser.extract_stack_traces(raw)

    assert len(traces) == 1, f"Expected 1 trace, got {len(traces)}"
    trace = traces[0]
    assert trace.exception_type == "java.lang.NullPointerException"
    assert len(trace.frames) == 2
    assert trace.frames[0].file == "PaymentService.java"
    assert trace.frames[0].line == 84
    assert trace.frames[0].method == "processPayment"
    print("  ✓ test_extract_stack_traces passed")


def test_first_error_and_anomaly():
    """Test finding first error and anomaly."""
    raw = (
        "2026-04-24T10:00:00Z INFO  [svc] OK\n"
        "2026-04-24T10:00:01Z WARN  [svc] Slow\n"
        "2026-04-24T10:00:02Z ERROR [svc] Broken\n"
        "2026-04-24T10:00:03Z ERROR [svc] Still broken\n"
    )
    parser = LogParser()
    entries = parser.parse(raw)

    first_error = parser.get_first_error(entries)
    assert first_error is not None
    assert "Broken" in first_error.message

    first_anomaly = parser.get_first_anomaly(entries)
    assert first_anomaly is not None
    assert "Slow" in first_anomaly.message
    print("  ✓ test_first_error_and_anomaly passed")


def test_serialization():
    """Test that LogEntry serializes to dict correctly."""
    raw = "2026-04-24T10:00:00Z INFO  [svc] Test message\n"
    parser = LogParser()
    entries = parser.parse(raw)
    d = entries[0].to_dict()

    assert isinstance(d, dict)
    assert d["level"] == "INFO"
    assert "timestamp" in d
    print("  ✓ test_serialization passed")


def test_sample_data():
    """Integration test using the actual sample log file."""
    log_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "sample_logs.txt"
    )
    with open(log_file, "r", encoding="utf-8") as f:
        raw = f.read()

    parser = LogParser()
    entries = parser.parse(raw)
    traces = parser.extract_stack_traces(raw)

    assert len(entries) > 20, f"Expected >20 entries, got {len(entries)}"
    assert len(traces) >= 1, f"Expected >=1 stack trace, got {len(traces)}"

    errors = parser.get_errors(entries)
    assert len(errors) >= 2, f"Expected >=2 errors, got {len(errors)}"

    first_error = parser.get_first_error(entries)
    assert "NullPointerException" in first_error.message

    print(f"  ✓ test_sample_data passed ({len(entries)} entries, "
          f"{len(traces)} traces, {len(errors)} errors)")


if __name__ == "__main__":
    print("Running log parser tests...")
    test_parse_entries()
    test_extract_stack_traces()
    test_first_error_and_anomaly()
    test_serialization()
    test_sample_data()
    print("\nAll tests passed! ✅")
