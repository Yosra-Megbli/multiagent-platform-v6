## Built for production — not a wrapper

This platform demonstrates:
- Dynamic tool-calling agents (LLM decides which tools to invoke)
- Multi-agent orchestration with LangGraph StateGraph
- RAG memory with pgvector (sentence-transformers, zero-cost)
- Non-blocking Human-in-the-Loop with confidence scoring
- Circuit breakers, rate limiting, distributed job queue
- Multi-tenant SaaS architecture
# MultiAgent Platform — v6

> Production-grade multi-agent autonomous AI platform for Tunisian SMEs and beyond.
> Built by **Yosra Meguebli** — Senior AI Engineer & PhD Candidate.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    FRONTEND (HTML/JS)                   │
│  Dashboard · Run Analysis · History · HITL · Memory     │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP (REST + polling)
┌────────────────────▼────────────────────────────────────┐
│              FastAPI — api/main.py                      │
│  /analyze  /jobs  /kpis  /circuit-breakers  /hitl       │
│  /observability/*  /audit-logs  /rate-limit             │
└──────┬─────────────┬───────────────────────────────────┘
       │             │
  Celery           Redis
  Worker           ├── Job state
  worker.py        ├── Circuit breakers
       │           ├── Rate limiting
       │           ├── HITL approvals
       │           └── Idempotency cache
┌──────▼──────────────────────────────────────────────────┐
│              AGENT PIPELINE (LangGraph)                 │
│                                                         │
│  Phase 1 (parallel):                                    │
│    weather_agent ─┐                                     │
│    sales_agent ───┼─► aggregator_agent ► decision_agent │
│    production_agent┘                                    │
│                                                         │
│  decision_agent: LLM tool-calling + RAG retrieval       │
│  Tools: weather · sales · production · inventory · rag  │
└─────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────┐
│              PostgreSQL + pgvector                      │
│  Jobs · Audit logs · RAG memory · KPIs                  │
└─────────────────────────────────────────────────────────┘
```

---

## Key Features

| Feature | Implementation |
|---|---|
| Multi-agent orchestration | LangGraph `StateGraph` with parallel + sequential phases |
| Tool-calling agents | OpenAI-format tool schemas, dynamic dispatch |
| RAG memory | pgvector semantic retrieval, per-tenant isolation |
| Circuit breakers | Redis-backed, 3 states: CLOSED / OPEN / HALF_OPEN |
| Human-in-the-Loop | Non-blocking HITL — confidence threshold triggers review |
| Rate limiting | Per-tenant, per-plan, Redis sliding window |
| Idempotency | Header-based, Redis-cached responses |
| Job queue | Celery with light/heavy routing, DLQ, retry |
| RBAC | Permission-based access control per tenant plan |
| Cost alerting | Per-call LLM cost tracking with configurable thresholds |
| Observability | Tracing, KPIs, audit logs, queue stats |
| Chaos testing | `tests/test_chaos.py` validates fault tolerance |
| CI/CD | GitHub Actions — test → build → deploy |

---

## Quick Start

### 1. Environment
```bash
cp .env.example .env
# Edit .env: set GROQ_API_KEY, DATABASE_URL, REDIS_URL
```

### 2. Docker (recommended)
```bash
docker-compose up --build
```

Services started:
- **FastAPI** → http://localhost:8000
- **Redis** → localhost:6379
- **PostgreSQL** → localhost:5432
- **Celery worker** → background
- **Flower** (Celery monitor) → http://localhost:5555

### 3. Frontend
Open `frontend/index.html` directly in your browser.
- Demo mode: API key `sk-demo-123456` (no backend needed)
- Real backend: API key `demo-key-001`

### 4. Manual (no Docker)
```bash
pip install -r requirements.txt

# Terminal 1 — API
uvicorn api.main:app --reload --port 8000

# Terminal 2 — Worker
celery -A worker worker --loglevel=info -Q light,heavy

# Terminal 3 — Monitor (optional)
celery -A worker flower --port=5555
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Platform health + queue stats |
| POST | `/analyze` | Submit analysis job (async) |
| GET | `/jobs` | List tenant jobs |
| GET | `/jobs/{id}` | Poll job status |
| POST | `/jobs/{id}/retry` | Retry failed job |
| GET | `/kpis` | Business KPIs (30-day default) |
| GET | `/circuit-breakers` | Circuit breaker states |
| GET | `/rate-limit` | Rate limit status |
| GET | `/audit-logs` | Audit trail |
| POST | `/hitl/respond/{job_id}` | Approve or reject HITL decision |
| GET | `/observability/dashboard` | Full observability snapshot |
| GET | `/observability/costs` | LLM cost summary |
| GET | `/observability/memory/{product_id}` | RAG memory inspect |
| DELETE | `/observability/memory/{product_id}` | Reset RAG memory |

### Demo API Keys
| Key | Tenant | Plan | Permissions |
|---|---|---|---|
| `demo-key-001` | demo | enterprise | all |
| `test-key-002` | test | starter | analyze, view_jobs |

---

## Project Structure

```
multiagent_platform_v6/
├── frontend/
│   └── index.html              ← Full dashboard UI (no build step)
├── api/
│   ├── main.py                 ← FastAPI app, all routes
│   ├── hitl_routes.py          ← HITL approve/reject endpoints
│   └── observability_routes.py ← Costs, memory, dashboard
├── core/
│   ├── orchestrator.py         ← LangGraph pipeline builder
│   ├── state.py                ← UniversalState TypedDict
│   ├── tools.py                ← Tool schemas + executors
│   ├── hitl.py                 ← Non-blocking HITL logic
│   ├── circuit_breaker.py      ← 3-state circuit breaker
│   ├── cost_alerting.py        ← LLM cost tracking + alerts
│   ├── memory.py               ← Agent memory management
│   ├── memory_safety.py        ← Safe reset with audit trail
│   ├── rag_memory.py           ← pgvector RAG retrieval
│   ├── rate_limiting.py        ← Redis sliding window
│   ├── rbac.py                 ← Permissions + audit log
│   ├── jobs.py                 ← Job CRUD (PostgreSQL)
│   ├── kpis.py                 ← Business KPIs aggregation
│   ├── tracing.py              ← Request tracing
│   ├── idempotency.py          ← Idempotency cache
│   ├── job_locking.py          ← Distributed job locking
│   ├── queue_control.py        ← Backpressure + queue routing
│   ├── connectors.py           ← External API connectors
│   ├── llm.py                  ← LLM client (Groq)
│   ├── schemas.py              ← Pydantic schemas
│   └── secrets.py              ← Secret management
├── sectors/
│   ├── registry.py             ← Sector plugin registry
│   └── supply_chain/
│       ├── weather_agent.py
│       ├── sales_agent.py
│       ├── production_agent.py
│       ├── aggregator_agent.py
│       └── decision_agent.py
├── db/
│   ├── database.py             ← PostgreSQL async client
│   └── init.sql                ← Schema + seed data
├── tests/
│   ├── test_supply_chain.py    ← Unit + integration tests
│   ├── test_chaos.py           ← Chaos/fault-tolerance tests
│   └── load_test.py            ← Load testing (Locust)
├── worker.py                   ← Celery worker tasks
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## Sector Extension

Add a new sector in 4 files — no core changes needed:

```bash
sectors/
└── real_estate/
    ├── weather_agent.py     # run_weather_agent(state)
    ├── market_agent.py      # run_market_agent(state)
    ├── aggregator_agent.py  # aggregate(state)
    └── decision_agent.py    # run_decision_agent(state)
```

Then register in `sectors/registry.py`:
```python
SECTOR_REGISTRY["real_estate"] = ["weather_agent", "market_agent", "aggregator_agent", "decision_agent"]
```

---

## Built With

- **LangGraph** — stateful multi-agent orchestration
- **FastAPI** — async REST API
- **Celery + Redis** — distributed job queue
- **PostgreSQL + pgvector** — persistent state + RAG
- **Groq (Llama 3.3 70B)** — LLM inference (free tier)
- **Docker Compose** — one-command deployment

---

*© 2026 — Yosra Meguebli — github.com/Yosra-Megbli*
