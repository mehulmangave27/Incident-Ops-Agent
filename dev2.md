# Developer 2 (Agent + TinyFish + API Layer)

## Goal
Build agent + external intelligence + integration

## Tasks (5-hour plan)

### Hour 1: Agent Loop
- Simple loop:
  - call tool
  - get result
  - continue
- Hardcode sequence initially

### Hour 2: TinyFish Integration (SIMPLIFIED)
- Implement:
  - check_vendor_status (mock or simple scrape)
  - search_related_incidents (basic web fetch or mock)
- Focus on structured output

### Hour 3: WunderGraph-style API (Lightweight)
- Create simple API layer (FastAPI)
- Endpoints:
  - /investigate
  - /results

### Hour 4: Combine Internal + External
- Merge:
  - backend output
  - TinyFish output
- Add reasoning layer (LLM or template)

### Hour 5: Demo + Polish
- Create demo scenario:
  - failing API
  - external outage
- Format final explanation

## Output
- Final explanation:
  - root cause
  - external validation
  - timeline
