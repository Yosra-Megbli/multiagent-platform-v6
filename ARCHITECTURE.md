# ARCHITECTURE — MultiAgent Platform v6

> **Author:** Yosra Meguebli — Senior AI Engineer & PhD Candidate
> **Version:** 6.0.0
> **Last Updated:** 2026

---

## Table of Contents

1. [Overview](#1-overview)
2. [Global Diagram](#2-global-diagram)
3. [API Layer — FastAPI](#3-api-layer--fastapi)
4. [Multi-Agent Pipeline — LangGraph](#4-multi-agent-pipeline--langgraph)
5. [Tool-Calling System](#5-tool-calling-system)
6. [Persistence — PostgreSQL + pgvector](#6-persistence--postgresql--pgvector)
7. [Cache & Queue — Redis + Celery](#7-cache--queue--redis--celery)
8. [Cross-Cutting Modules](#8-cross-cutting-modules)
9. [Multi-Tenant Architecture](#9-multi-tenant-architecture)
10. [Multi-Sector Architecture](#10-multi-sector-architecture)
11. [Complete Data Flow](#11-complete-data-flow)
12. [Architecture Decision Records](#12-architecture-decision-records)

---

## 1. Overview

The platform is a production-grade SaaS infrastructure — multi-agent, multi-tenant, multi-sector. It transforms raw business data (sales, stock, weather) into strategic decisions through an AI agent pipeline orchestrated by LangGraph.

### Core Principles

| Principle | Implementation |
|---|---|
| **Full isolation** | Each tenant has its own data, queue, and rate limits |
| **Plugin architecture** | Adding a sector = 4 files, zero core changes |
| **Fault tolerance** | Circuit breakers, fallbacks, DLQ at every failure point |
| **Observability** | Tracing, KPIs, audit logs, LLM cost tracking — everything measured |
| **Async-first** | FastAPI + asyncpg + asyncio — no I/O blocking |

---

## 2. Global Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     FRONTEND (HTML/JS)                          │
│   Dashboard · Run Analysis · History · HITL · Memory · Obs      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP REST
                           │ X-API-Key header
┌──────────────────────────▼──────────────────────────────────────┐
│                    FastAPI  api/main.py                         │
│                                                                 │
│  Middlewares:  CORS · Auth · Rate Limit · Idempotency           │
│  Routes:       /analyze · /jobs · /kpis · /hitl · /obs          │
│                                                                 │
│  api/deps.py                 → shared get_tenant()             │
│  api/hitl_routes.py          → approve / reject / respond      │
│  api/observability_routes.py → costs / memory / dashboard      │
└──────┬───────────────────────────────────────────┬─────────────┘
       │ create_job()                               │ read
       │ apply_async()                              │
┌──────▼──────────┐                    ┌───────────▼─────────────┐
│     Redis       │                    │      PostgreSQL          │
│                 │                    │                          │
│  job:{id}       │                    │  tenants                 │
│  tenant:jobs:*  │                    │  sales                   │
│  ratelimit:*    │                    │  production_config       │
│  hitl:*         │                    │  decisions               │
│  circuit:*      │                    │  decision_memory (RAG)   │
│  dlq:*          │                    │  audit_logs              │
│  cost:*         │                    │                          │
└──────┬──────────┘                    └─────────────────────────┘
       │ broker
┌──────▼──────────────────────────────────────────────────────────┐
│                      Celery Workers                             │
│                                                                 │
│  worker-analysis  (queue: analysis)                            │
│  worker-light     (queue: light)                               │
│  worker-heavy     (queue: heavy)                               │
│                                                                 │
│  worker.py → process_analysis_job()                            │
│           → resume_hitl_job()                                  │
└──────┬──────────────────────────────────────────────────────────┘
       │ asyncio
┌──────▼──────────────────────────────────────────────────────────┐
│              AGENT PIPELINE — LangGraph StateGraph              │
│                                                                 │
│  Phase 1 (parallel):                                           │
│    weather_agent ──┐                                           │
│    sales_agent ────┼──► aggregator_agent ──► decision_agent    │
│    production_agent┘                                           │
│                                                                 │
│  State: UniversalState (TypedDict)                             │
│  Graph: compiled once per sector, cached in memory             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. API Layer — FastAPI

### File Structure

```
api/
├── main.py                  ← Main app, all routes
├── deps.py                  ← get_tenant() — shared dependency
├── hitl_routes.py           ← /hitl/approve, /hitl/reject, /hitl/respond
└── observability_routes.py  ← /observability/dashboard, /costs, /memory
```

### Request Lifecycle — POST /analyze

```
POST /analyze
    │
    ├── 1. APIKeyHeader → get_tenant() → PostgreSQL lookup
    │
    ├── 2. Idempotency check → Redis (Idempotency-Key header)
    │
    ├── 3. Rate limit check → Redis sliding window
    │       starter: 10/min | pro: 60/min | enterprise: unlimited
    │
    ├── 4. Backpressure check → queue depth < capacity
    │
    ├── 5. create_job() → Redis (job:{uuid})
    │
    ├── 6. increment_queue() → Redis counter
    │
    ├── 7. process_analysis_job.apply_async() → Celery queue
    │
    ├── 8. audit_log() → PostgreSQL
    │
    └── 9. Return { job_id, status: "queued", poll_url }
```

### SSRF Protection

Webhooks are validated against a blocklist of private IP prefixes:
```
10.* | 172.* | 192.168.* | 127.* | 169.254.* | ::1 | fc* | fd*
```

---

## 4. Multi-Agent Pipeline — LangGraph

### Dynamic Orchestrator

```python
# core/orchestrator.py
async def build_orchestrator(sector: str):
    """
    Builds the LangGraph StateGraph for a given sector.
    Result is cached in memory — built only once per sector.
    """
```

### Supply Chain Graph

```
Entry Point
    │
    ▼
parallel_agents (Phase 1)
    ├── run_weather_agent()     → agent_outputs["weather_agent"]
    ├── run_sales_agent()       → agent_outputs["sales_agent"]
    └── run_production_agent()  → agent_outputs["production_agent"]
    │
    ▼
aggregator_agent (Phase 2)
    └── aggregate()             → aggregated_insights
    │
    ▼
decision_agent (Phase 3)
    └── run_decision_agent()    → final_decision
    │
    ▼
END
```

### UniversalState — Shared State

```python
# core/state.py
class UniversalState(TypedDict):
    tenant_id:           str
    sector:              str
    input_data:          dict      # location, product_id, facility_id...
    agent_outputs:       dict      # {agent_name: {output}}
    aggregated_insights: dict      # alerts, urgency, summaries
    final_decision:      str       # LLM-generated text
    errors:              list[str] # non-blocking errors
    status:              str       # running | done | error
```

### Supply Chain Agents

#### WeatherAgent
```
Input:  location (string)
Source: OpenWeatherMap API /forecast (40 data points, 5 days)
Output: avg_temp, max_temp, rain_days, heat_wave (bool)
CB:     circuit breaker "openweather" — fallback after 3 failures
```

#### SalesAgent
```
Input:  product_id, tenant_id
Source: PostgreSQL (365 days history) or ERP connector
Model:  Facebook Prophet (yearly + weekly seasonality)
        → offloaded to thread executor (CPU-bound operation)
Output: baseline_daily, total_30_days, adjusted_30_days,
        weather_multiplier, memory_adjustment, peak_day
```

#### ProductionAgent
```
Input:  product_id, tenant_id
Source: PostgreSQL production_config or ERP connector
Output: daily_capacity, current_stock, packaging_stock,
        days_of_stock, days_of_packaging, capacity_gap,
        can_meet_demand, reorder_needed
```

#### AggregatorAgent
```
Input:  agent_outputs (weather + sales + production)
Logic:  Rules-based (no LLM call)
        - HEAT_WAVE_DEMAND_SURGE  if heat_wave = True
        - STOCK_CRITICAL          if days_of_stock < 7
        - REORDER_URGENT          if reorder_needed = True
        - CAPACITY_GAP            if capacity_gap > 0
Output: alerts[], urgency (LOW / MEDIUM / HIGH), summaries
```

#### DecisionAgent
```
Input:  aggregated_insights + tool results + RAG context
LLM:    Groq Llama 3.3 70B (llama-3.3-70b-versatile)
Tools:  weather_tool, sales_tool, production_tool, rag_tool
Output: decision_text (Situation / Actions / Risk / Confidence)
        tools_selected, tools_called, decision_cost, hitl
```

---

## 5. Tool-Calling System

The decision_agent does not follow a fixed pipeline. It **dynamically selects** which tools to call based on the current situation.

```python
# core/tools.py
SUPPLY_CHAIN_TOOLS = [
    { "name": "weather_tool",    "description": "..." },
    { "name": "sales_tool",      "description": "..." },
    { "name": "production_tool", "description": "..." },
    { "name": "rag_tool",        "description": "..." },
]
```

### Tool-Calling Flow

```
DecisionAgent receives prompt with:
    - aggregated_insights
    - description of all available tools
    - RAG context (similar past decisions)

LLM decides:
    → If urgency HIGH:       call all tools
    → If stock critical:     prioritize production_tool
    → If normal situation:   call rag_tool + sales_tool

run_tools_parallel(tool_names, state)
    → asyncio.gather() — parallel execution
    → each tool = isolated agent with deepcopy of state

LLM generates final decision using tool results
```

---

## 6. Persistence — PostgreSQL + pgvector

### Schema

```sql
-- Tenants (multi-tenant isolation)
tenants (tenant_id PK, name, sector, plan, api_key UNIQUE,
         config JSONB, active, role, user_id)

-- Supply Chain Data
sales (id, tenant_id FK, product_id, sale_date, quantity)
production_config (tenant_id FK, product_id PK,
                   daily_capacity, current_stock,
                   packaging_stock, supplier_lead_time)

-- Decisions (audit trail)
decisions (id, tenant_id FK, sector, decision_text, insights, created_at)

-- RAG Memory (pgvector)
decision_memory (id, tenant_id FK, product_id, sector,
                 summary, decision_text, insights JSONB,
                 accuracy, embedding vector(384), created_at)

-- Indexes
idx_sales_tenant_product ON sales(tenant_id, product_id, sale_date)
idx_decision_memory_vector USING ivfflat (embedding vector_cosine_ops)
```

### RAG Memory — Embedding Strategy

```python
# core/rag_memory.py
def _hash_embed(text: str) -> list[float]:
    """
    Deterministic embedding via MD5 hash chunks.
    Dimension: 384 — compatible with pgvector.
    No GPU, no model download required.
    """
```

Cosine similarity search:
```sql
SELECT summary, decision_text, accuracy,
       1 - (embedding <=> $3::vector) AS similarity
FROM decision_memory
WHERE tenant_id = $1 AND sector = $2
ORDER BY embedding <=> $3::vector
LIMIT 3
```

---

## 7. Cache & Queue — Redis + Celery

### Redis Key Structure

```
job:{uuid}                     → Full job JSON          (TTL: 7 days)
tenant:jobs:{tenant_id}        → Set of job_ids         (TTL: 7 days)
ratelimit:{tenant_id}:{window} → Request counter        (TTL: 120s)
hitl:approval:{request_id}     → Approval JSON          (TTL: 3600s)
hitl:job:{job_id}              → request_id mapping     (TTL: 3600s)
circuit:{name}                 → State JSON             (no TTL)
dlq:failed_jobs                → Failed jobs list       (max 500)
cost:{tenant_id}:daily:{date}  → Daily cost float       (TTL: 90 days)
kpi:decisions:{tenant_id}      → Decision list JSON     (TTL: 90 days)
queue:depth:{tenant_id}        → Active job counter
idempotency:{key}:{tenant_id}  → Cached response JSON   (TTL: 24h)
```

### Celery — Queue Routing

```python
task_routes = {
    "worker.process_analysis_job": {"queue": "analysis"},
    "worker.resume_hitl_job":       {"queue": "light"},
}

# Sector-based routing (core/queue_control.py)
def get_queue_for_sector(sector: str) -> str:
    heavy_sectors = ["supply_chain"]  # Prophet = CPU-heavy
    return "heavy" if sector in heavy_sectors else "light"
```

### Circuit Breaker — 3 States

```
CLOSED ──(failures >= threshold)──► OPEN
  ▲                                    │
  │                                    │ (recovery_timeout elapsed)
  └──(success)── HALF_OPEN ◄───────────┘
                     │
                     └──(failure)──► OPEN
```

```python
# core/circuit_breaker.py
_breakers = {
    "openweather": CircuitBreaker("openweather"),
    "groq_llm":    CircuitBreaker("groq_llm"),
    "postgres":    CircuitBreaker("postgres"),
}
```

---

## 8. Cross-Cutting Modules

### HITL — Human-in-the-Loop

```
decision_agent computes confidence score
    │
    ├── confidence >= 0.80 → auto-approve → job DONE
    │
    └── confidence < 0.80  → PENDING_HUMAN
            │
            ├── Redis: hitl:approval:{request_id} = "pending"
            ├── Redis: hitl:job:{job_id} = request_id
            ├── Celery: resume_hitl_job (countdown = HITL_TIMEOUT_SECONDS)
            │
            └── Human via POST /hitl/respond/{job_id}
                    │
                    ├── action: "approve" → job DONE
                    └── action: "reject"  → job REJECTED
```

### Rate Limiting — Sliding Window

```python
window  = int(time.time() / 60)       # 60-second window
key     = f"ratelimit:{tenant_id}:{window}"
current = await redis.incr(key)
await redis.expire(key, 120)

if current > limit:
    raise HTTP 429 Too Many Requests
```

### Cost Alerting

```python
# core/cost_alerting.py
# Tracks Groq token usage per call (input + output tokens)
# Fires alert if cumulative cost > COST_BUDGET_THRESHOLD
# Storage: cost:{tenant_id}:daily:{date} → float
```

### Idempotency

```
Header: Idempotency-Key: <client-generated-uuid>

1. check_idempotency(key, tenant_id) → Redis lookup
2. If found  → return cached response (no duplicate job)
3. If not    → execute + store_idempotency(key, tenant_id, response)
```

### Distributed Job Locking

```python
# core/job_locking.py
# Prevents double-execution on Celery retry
acquire_job_lock_sync(job_id)   # before execution
release_job_lock_sync(job_id)   # in finally block
```

---

## 9. Multi-Tenant Architecture

```
API Key: "demo-key-001"
    │
    ▼
PostgreSQL: SELECT * FROM tenants WHERE api_key = 'demo-key-001'
    │
    ▼
tenant = {
    tenant_id: "demo",
    sector:    "supply_chain",
    plan:      "enterprise",
    config:    {"connector_type": "database"}
}
    │
    ├── All SQL queries:    WHERE tenant_id = 'demo'
    ├── All Redis keys:     prefixed with tenant_id
    ├── Rate limiting:      per tenant_id
    ├── Queue depth:        per tenant_id
    └── Audit logs:         per tenant_id
```

### Plans and Permissions

| Plan | Rate Limit | Permissions |
|---|---|---|
| starter | 10 req/min | analyze, view_jobs |
| pro | 60 req/min | analyze, view_jobs, retry_jobs |
| enterprise | unlimited | all + manage_secrets + view_audit_logs |

---

## 10. Multi-Sector Architecture

### Registry Pattern

```python
# sectors/registry.py
SECTOR_REGISTRY = {
    "supply_chain": [
        "weather_agent",
        "sales_agent",
        "production_agent",
        "aggregator_agent",
        "decision_agent",
    ],
    # "hr":          [...],  # coming soon
    # "legal":       [...],  # coming soon
    # "real_estate": [...],  # coming soon
}
```

### Adding a New Sector — 4 Files Only

```
sectors/real_estate/
    ├── market_agent.py      → run_market_agent(state)
    ├── valuation_agent.py   → run_valuation_agent(state)
    ├── aggregator_agent.py  → aggregate(state)
    └── decision_agent.py    → run_decision_agent(state)
```

```python
# sectors/registry.py — one line to add
SECTOR_REGISTRY["real_estate"] = [
    "market_agent", "valuation_agent",
    "aggregator_agent", "decision_agent"
]
```

The orchestrator loads agents dynamically via `importlib` — zero changes to core code.

---

## 11. Complete Data Flow

```
1. Client → POST /analyze { location: "Tunis", product_id: "PROD-001" }
            X-API-Key: demo-key-001

2. FastAPI → Auth → tenant = { id:"demo", sector:"supply_chain" }
           → Rate limit OK (enterprise: unlimited)
           → Idempotency check (no duplicate)
           → Backpressure check (queue < 100)

3. Redis   → create_job(job_id) → status: "queued"
           → increment_queue("demo")

4. Celery  → process_analysis_job.apply_async(queue="light")
           → Return { job_id, poll_url: /jobs/{id} }

5. Worker  → acquire_job_lock(job_id)
           → update_job(RUNNING)
           → run_analysis(tenant_id, sector, input_data)

6. LangGraph → build_orchestrator("supply_chain") [from cache]
             → invoke(initial_state)

7. Phase 1 (parallel — asyncio.gather):
   WeatherAgent    → OpenWeatherMap API → avg_temp:15.1, max_temp:19.6
   SalesAgent      → PostgreSQL 365d   → Prophet → 33,497 units/30d
   ProductionAgent → PostgreSQL        → stock:18,000, capacity:1,500/d

8. Phase 2:
   AggregatorAgent → rules engine → urgency:LOW, alerts:[]

9. Phase 3:
   DecisionAgent → RAG lookup (pgvector cosine similarity)
                → Tool-calling: [rag_tool, sales_tool, production_tool]
                → Groq Llama 3.3 70B → decision_text
                → confidence: 1.0 → auto-approved

10. Worker → update_job(DONE, result=final_state)
           → release_job_lock(job_id)
           → decrement_queue("demo")

11. Client → GET /jobs/{id} → status:"done", final_decision:"..."
```

---

## 12. Architecture Decision Records

### Why LangGraph instead of plain LangChain?

LangGraph enables a stateful graph with parallel and sequential phases. Phase 1 agents run via `asyncio.gather()` — approximately 60% faster than sequential execution.

### Why Celery instead of FastAPI Background Tasks?

FastAPI Background Tasks are lost if the process restarts. Celery persists tasks in Redis, supports retry logic, Dead Letter Queue, and real-time monitoring via Flower.

### Why Redis for jobs instead of PostgreSQL?

Jobs are read/written very frequently (client polls every 1.5s). Redis O(1) key lookup vs PostgreSQL O(log n). Automatic TTL eliminates manual cleanup.

### Why Prophet instead of ARIMA or LSTM?

Prophet handles missing data gracefully, detects seasonality automatically, and requires no GPU. For SMEs with 365 days of sales history, it offers the best accuracy/simplicity tradeoff.

### Why hash embedding instead of sentence-transformers?

sentence-transformers downloads 500MB+ of PyTorch/CUDA models. For a lightweight SaaS platform, a deterministic MD5-based embedding provides sufficient approximate semantic similarity for RAG retrieval.

### Why asyncpg instead of SQLAlchemy?

asyncpg is a pure async PostgreSQL driver with no ORM overhead. For a high-throughput API, raw async queries with a connection pool (min=2, max=10) outperform ORM abstractions significantly.

---

*© 2026 — Yosra Meguebli — github.com/Yosra-Megbli*
