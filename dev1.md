# Developer 1 (Backend + Core Intelligence)

## Goal
Build core investigation engine (logs → root cause)

## Tasks (5-hour plan)

### Hour 1: Setup + Data
- Create sample logs (with bug)
- Create sample stack trace
- Create fake git diff
- Store locally (no need S3 initially)

### Hour 2: Log Parser (CRITICAL)
- Extract timestamps
- Detect ERROR / WARN
- Extract first error
- Extract first anomaly

### Hour 3: Core Analysis
- Implement:
  - find_failure_times
  - simple root cause ranking
- Map stack trace → file + line

### Hour 4: Redis Integration
- Store:
  - fingerprint
  - root cause
- Implement:
  - cache lookup
  - reuse logic

### Hour 5: MCP Tool Wrappers
Expose functions as tools:
- get_logs
- extract_stack_trace
- find_failure_times
- rank_root_causes

## Output
- Structured JSON:
  - root cause
  - timeline
  - confidence
