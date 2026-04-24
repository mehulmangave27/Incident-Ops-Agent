# Agentic Incident Investigation System (MVP)

## 1. Overview

This project is an **Agentic AI system** that autonomously investigates software failures by reasoning over logs, stack traces, code changes, and external web signals.

The system combines:
- **Deterministic parsing (regex-based)** for reliable extraction
- **Lightweight model reasoning** for interpretation
- **Agentic workflow** for dynamic decision-making
- **Web intelligence (TinyFish)** for external validation

Instead of a fixed pipeline, the system behaves like an **investigation agent**:
- Understands a user query
- Decides what data to retrieve
- Uses tools dynamically
- Forms and validates hypotheses
- Produces a root cause explanation

---

## 2. MVP Scope

### Goal
Build a working agent that can:
- Analyze logs
- Automatically extract stack traces from logs
- Fetch recent code changes (git diffs)
- Infer deploy time (using commit timestamp)
- Detect failure timelines (anomaly + error)
- Correlate events
- Identify likely root cause
- Validate with external signals (status pages, release notes, issues)
- Explain findings clearly

### Out of Scope
- Large-scale distributed systems
- Real-time streaming pipelines
- Complex UI dashboards

---

## 3. Sponsor Integrations (Core Stack)

### 🐠 TinyFish (Primary Differentiator)

**Role:** External Web Intelligence Layer

Used for:
- Fetching vendor status pages (Stripe, AWS, etc.)
- Extracting incident timelines from live websites
- Scraping release notes and changelogs
- Searching GitHub issues and forums for similar failures

**Impact:**
Adds external evidence to internal debugging, enabling more accurate root cause analysis.

---

### 🔗 WunderGraph (Unified API Layer)

**Role:** Data Federation Layer

Used for:
- Unifying multiple data sources into a single API:
  - Logs (S3)
  - Git commits
  - TinyFish outputs
  - Redis cache
- Providing a clean interface for the agent

**Impact:**
Simplifies multi-source correlation and enables clean architecture.

---

### ⚡ Redis (Agent Memory + Caching)

**Role:** Real-time Memory Store

Used for:
- Incident fingerprint caching
- Deduplication of repeated failures
- Storing parsed logs and intermediate results
- Maintaining agent state across steps

**Impact:**
Enables faster responses, reduces compute, and supports reasoning across repeated incidents.

---

### 🔐 Chainguard (Secure Deployment)

**Role:** Secure Runtime Environment

Used for:
- Running the agent in a hardened container
- Ensuring secure software supply chain

**Impact:**
Provides production-grade security for AI infrastructure.

---

## 4. Optional Enhancements

### 🔄 Nexla (Data Ingestion)

**Role:** Multi-format Data Integration

Used for:
- Ingesting logs from different formats
- Normalizing data before processing

---

### 🎤 Vapi (Voice Interface)

**Role:** Natural Interaction Layer

Used for:
- Voice-based querying of the agent

Example:
> "Why did my system break?"

---

## 5. Storage Strategy

### S3 (Source of Truth)
Store raw artifacts:
- Logs
- Git diffs
- Incident metadata

### Redis (Working Memory)
Store processed data:
- Parsed events
- Extracted stack trace
- Failure timestamps
- Ranked root causes
- Agent state

---

## 6. MCP Server Design

### Core Tools

#### get_logs
```
Input: { service, time_window }
Output: raw logs
```

#### extract_stack_trace
```
Input: logs
Output: structured stack trace
```

#### get_recent_commits
```
Input: repo, time_window
Output: commits
```

#### get_commit_diff
```
Input: commit_id
Output: diff
```

#### find_failure_times
```
Input: logs, deploy_time
Output: { first_anomaly_time, error_time }
```

#### rank_root_causes
```
Input: stack trace + commits + anomalies
Output: ranked candidates
```

#### generate_timeline
```
Input: events
Output: ordered timeline
```

---

### TinyFish-Powered Tools (NEW)

#### check_vendor_status
```
Input: { service_name, timestamp }
Output: outage information
```

#### scan_release_notes
```
Input: { library_name, time_window }
Output: breaking changes
```

#### search_related_incidents
```
Input: { error_message }
Output: similar incidents from web
```

---

## 7. Log Processing Strategy (Hybrid)

### 7.1 Deterministic Layer (Regex-Based)

Used for:
- Timestamp extraction
- Severity detection (ERROR, WARN)
- Stack trace extraction
- Failure time detection

### 7.2 Lightweight Model Layer

Used ONLY for:
- Interpreting ambiguous log segments
- Classifying events as root-cause vs downstream
- Ranking competing hypotheses
- Generating explanations

---

## 8. Failure Time Detection Logic

- deploy_time = commit timestamp
- error_time = first high-confidence error after deploy
- first_anomaly_time = first abnormal signal before error

---

## 9. Agentic Workflow

### Step 1: User Query

> "Why is my payment API failing after the last deploy?"

### Step 2: Internal Analysis

- Logs
- Stack trace
- Failure timeline
- Code changes

### Step 3: External Investigation (TinyFish)

- Check vendor outages
- Scan release notes
- Search similar incidents

### Step 4: Correlation

Agent combines:
- Internal signals
- External signals
- Temporal alignment

### Step 5: Output

- Root cause hypothesis
- Supporting evidence
- Confidence score
- Timeline

---

## 10. Key Value Proposition

- Autonomous debugging agent
- Combines internal telemetry with external web intelligence
- Deterministic + AI hybrid approach
- Timeline-based reasoning
- Incident deduplication using Redis

---

## 11. MVP Deliverables

- Agent loop
- MCP tools (internal + TinyFish)
- Regex parser
- Lightweight model integration
- Timeline detection
- Root cause ranking
- External signal integration

---

## 12. Incident Deduplication & Optimization (Redis)

### Failure Fingerprint

Example:
```
payment-service|NullPointerException|PaymentService.java|84|missing_user_id
```

### Redis Usage

- Cache root causes
- Store timelines
- Track occurrence count

### Benefit

- Faster repeated analysis
- Reduced compute
- Consistent diagnosis

---

## 13. Architecture Summary

- **TinyFish** → Web intelligence (external signals)
- **WunderGraph** → Unified API layer
- **Redis** → Memory + caching
- **Chainguard** → Secure deployment

---

**End of Document**

