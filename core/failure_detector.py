"""
Failure Detector — Timeline-based failure analysis.

Identifies the failure timeline: deploy time → first anomaly → first error,
and computes key metrics like time-to-failure.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional

from core.log_parser import LogEntry, LogParser


@dataclass
class FailureTimes:
    """Detected failure timeline."""
    deploy_time: datetime
    first_anomaly_time: Optional[datetime]
    first_error_time: Optional[datetime]
    time_to_anomaly_seconds: Optional[float]   # deploy → first anomaly
    time_to_failure_seconds: Optional[float]    # deploy → first error
    anomaly_to_error_seconds: Optional[float]   # anomaly → error

    def to_dict(self) -> dict:
        d = {}
        for key, val in asdict(self).items():
            if isinstance(val, datetime):
                d[key] = val.isoformat() + "Z"
            else:
                d[key] = val
        return d


@dataclass
class TimelineEvent:
    """A single event in the incident timeline."""
    timestamp: datetime
    event_type: str      # deploy, anomaly, error, recovery, alert
    description: str
    service: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat() + "Z",
            "event_type": self.event_type,
            "description": self.description,
            "service": self.service,
        }


def find_failure_times(
    entries: List[LogEntry],
    deploy_time: datetime,
) -> FailureTimes:
    """Detect the failure timeline from parsed log entries.

    Args:
        entries: Parsed log entries (should be chronologically ordered).
        deploy_time: The time the deployment completed.

    Returns:
        FailureTimes with computed intervals.
    """
    parser = LogParser()

    # Only look at entries after deploy
    post_deploy = [e for e in entries if e.timestamp >= deploy_time]

    first_anomaly = parser.get_first_anomaly(post_deploy)
    first_error = parser.get_first_error(post_deploy)

    anomaly_time = first_anomaly.timestamp if first_anomaly else None
    error_time = first_error.timestamp if first_error else None

    # Compute intervals
    time_to_anomaly = None
    if anomaly_time:
        time_to_anomaly = (anomaly_time - deploy_time).total_seconds()

    time_to_failure = None
    if error_time:
        time_to_failure = (error_time - deploy_time).total_seconds()

    anomaly_to_error = None
    if anomaly_time and error_time:
        anomaly_to_error = (error_time - anomaly_time).total_seconds()

    return FailureTimes(
        deploy_time=deploy_time,
        first_anomaly_time=anomaly_time,
        first_error_time=error_time,
        time_to_anomaly_seconds=time_to_anomaly,
        time_to_failure_seconds=time_to_failure,
        anomaly_to_error_seconds=anomaly_to_error,
    )


def generate_timeline(
    entries: List[LogEntry],
    deploy_time: datetime,
) -> List[TimelineEvent]:
    """Build an ordered incident timeline from log entries.

    Classifies each entry as deploy, anomaly, error, alert, or recovery
    and returns them in chronological order.
    """
    events: List[TimelineEvent] = []

    # Add the deploy event
    events.append(TimelineEvent(
        timestamp=deploy_time,
        event_type="deploy",
        description="Deployment completed",
        service="deploy-agent",
    ))

    for entry in entries:
        if entry.timestamp < deploy_time:
            continue

        # Classify the event
        if entry.level == "ERROR":
            event_type = "error"
        elif entry.level == "WARN":
            # Distinguish alerts from anomalies
            if "ALERT" in entry.message or "PagerDuty" in entry.message:
                event_type = "alert"
            elif "Circuit breaker" in entry.message:
                event_type = "degradation"
            else:
                event_type = "anomaly"
        elif "Circuit breaker CLOSED" in entry.message or "recovery" in entry.message.lower():
            event_type = "recovery"
        else:
            continue  # Skip normal INFO lines for the timeline

        events.append(TimelineEvent(
            timestamp=entry.timestamp,
            event_type=event_type,
            description=entry.message,
            service=entry.service,
        ))

    # Sort chronologically
    events.sort(key=lambda e: e.timestamp)
    return events
