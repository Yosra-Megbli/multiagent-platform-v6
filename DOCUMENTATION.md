# Multi-Agent Platform — Full Documentation

## Table of Contents
1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Tech Stack](#3-tech-stack)
4. [Security](#4-security)
5. [Prerequisites](#5-prerequisites)
6. [Installation](#6-installation)
7. [API Reference](#7-api-reference)
8. [Adding a New Sector](#8-adding-a-new-sector)
9. [Adding a New Client](#9-adding-a-new-client)
10. [Tests](#10-tests)
11. [File Structure](#11-file-structure)

---

## 1. Overview

A production-grade multi-agent AI platform designed to serve multiple clients (multi-tenant)
across multiple business sectors (multi-sector) from a single codebase.

### Core Principles
- **Single deployment** for all clients and all sectors
- **Plugin architecture** — adding a sector = adding agent files, zero core changes
- **Full isolation** — each client only sees their own data

### Available Sectors
| Sector | Status | Agents |
|---|---|---|
| `supply_chain` | ✅ Implemented | Weather, Sales, Production, Decision |
| `legal` | 🔲 Ready (empty) | — |
| `hr` | 🔲 Ready (empty) | — |
| `real_estate` | 🔲 Ready (empty) | — |

---

## 2. Architecture

### Global Flow
```
Client (HTTP Request + API Key)
           │
    ┌──────▼──────────────┐
    │   FastAPI Gateway   │  ← Auth, Rate limit, Idempotency, RBAC
    └──────┬──────────────┘
           │ tenant lookup → sector
    ┌──────▼──────────────┐
    │ Dynamic Orchestrator│  ← LangGraph, built once per sector
    └──────┬──────────────┘
           │ parallel execution (asyncio.gather)
    ┌──────┼──────────────┐
    ▼      ▼              ▼
Agent1  Agent2         AgentN
    │      │              │
    └──────▼──────────────┘
         Aggregator (rules-based)
           │
     Decision Agent (LLM + tool-calling + RAG)
           │
       HITL checkpoint
           │
       Response ✅
```

### Supply Chain Data Flow
```
1. Client sends: { location, product_id }
2. Auth middleware: API Key → tenant_id + sector
3. Orchestrator: loads sector agents from registry
4. Phase 1 (parallel):
   - WeatherAgent    → OpenWeatherMap API
   - SalesAgent      → PostgreSQL + Prophet forecast
   - ProductionAgent → PostgreSQL (stock, capacity)
5. Phase 2: Aggregator → rules-based alerts + urgency score
6. Phase 3: DecisionAgent → tool-calling + RAG + Llama 3.3 70B
7. HITL: if confidence < 0.80 → await human approval
8. Redis: job result stored (TTL 7 days)
9. PostgreSQL: decision saved to audit trail
10. JSON response to client
```

### Multi-Tenant Isolation
```
tenant_id = "client_acme"
    └── sales WHERE tenant_id = 'client_acme'
    └── production_config WHERE tenant_id = 'client_acme'
    └── decisions WHERE tenant_id = 'client_acme'
    └── Redis keys prefixed: ratelimit:client_acme:*

tenant_id = "client_beta"
    └── sales WHERE tenant_id = 'client_beta'   ← fully isolated
```

---

## 3. Tech Stack

### Backend & API
| Tool | Version | Role |
|---|---|---|
| **Python** | 3.11 | Primary language |
| **FastAPI** | 0.115 | REST API framework |
| **Uvicorn** | 0.30 | ASGI server |
| **Pydantic** | 2.7 | Request/response validation |

### AI & Agents
| Tool | Version | Role |
|---|---|---|
| **LangGraph** | 0.2 | Multi-agent graph orchestration |
| **LangChain Core** | 0.3 | LLM abstractions |
| **Groq SDK** | 0.9+ | LLM calls — Llama 3.3 70B |
| **Prophet** | 1.1.5 | Time-series sales forecasting (Meta) |
| **Pandas** | 2.2 | Data manipulation |

### Database & Cache
| Tool | Version | Role |
|---|---|---|
| **PostgreSQL** | 16 | Primary database |
| **pgvector** | 0.3 | Vector embeddings for RAG memory |
| **asyncpg** | 0.29 | Async PostgreSQL driver |
| **Redis** | 7 | Job cache + Celery broker |
| **Celery** | 5.4 | Async background task queue |

### Infrastructure
| Tool | Role |
|---|---|
| **Docker** | Containerization |
| **Docker Compose** | Local orchestration |
| **GitHub Actions** | CI/CD pipeline |

### External APIs
| API | Role | Free tier |
|---|---|---|
| **OpenWeatherMap** | Weather forecast data | ✅ up to 60 req/min |
| **Groq** | LLM inference (Llama 3.3 70B) | ✅ generous free tier |

---

## 4. Security

### Authentication
- Each tenant receives a **unique API key** stored in the database
- All requests require the header: `X-API-Key: sk-xxx`
- Keys are verified against the `tenants` table on every request

```python
async def get_tenant(api_key: str = Depends(api_key_header)):
    tenant = await get_tenant_by_api_key(api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return tenant
```

### Data Isolation
- All SQL queries include `WHERE tenant_id = $1`
- A client can never access another client's data
- `tenant_id` is always sourced from the database — never from the client request

### RBAC — Role-Based Access Control
| Role | Permissions |
|---|---|
| `admin` | All permissions + manage secrets + view audit logs |
| `analyst` | analyze, view jobs, view costs, approve HITL |
| `viewer` | view jobs, view costs, view dashboard |

### Additional Protections
- **SSRF protection** — webhook URLs validated against private IP blocklist
- **Idempotency** — duplicate requests return cached responses (24h TTL)
- **Rate limiting** — sliding window per tenant (starter: 10/min, pro: 60/min, enterprise: unlimited)
- **Circuit breakers** — prevent cascade failures from external API outages
- **Job locking** — distributed Redis lock prevents double-execution on Celery retry
- **DLQ** — failed jobs stored in Dead Letter Queue for inspection

---

## 5. Prerequisites

### Required Software
| Software | Min version | Check |
|---|---|---|
| **Docker** | 24+ | `docker --version` |
| **Docker Compose** | 2.20+ | `docker compose version` |
| **Git** | 2+ | `git --version` |

### Required API Keys
| Key | Where to obtain | Free |
|---|---|---|
| `GROQ_API_KEY` | https://console.groq.com | ✅ |
| `OPENWEATHER_API_KEY` | https://openweathermap.org/api | ✅ |

### Recommended System Resources
| Resource | Minimum | Recommended |
|---|---|---|
| RAM | 4 GB | 8 GB |
| CPU | 2 cores | 4 cores |
| Disk | 5 GB | 20 GB |

---

## 6. Installation

### Step 1 — Extract the project
```bash
unzip multiagent_v6_final.zip
cd multiagent_v6_final
```

### Step 2 — Configure environment variables
```bash
cp .env.example .env
```

Edit `.env`:
```env
GROQ_API_KEY=gsk_...               # Groq API key (free: console.groq.com)
OPENWEATHER_API_KEY=abc123...      # OpenWeatherMap key (free)
DATABASE_URL=postgresql://user:password@postgres:5432/platform
REDIS_URL=redis://redis:6379
DEMO_MODE=false                    # Set to true to run without a real database
```

### Step 3 — Start services
```bash
docker compose up --build
```

Wait for all services to be ready:
```
✅ postgres    → healthy
✅ redis       → started
✅ api         → started on port 8000
✅ worker      → Celery worker ready
```

### Step 4 — Verify installation
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "ok",
  "version": "6.0.0",
  "available_sectors": ["supply_chain"]
}
```

### Step 5 — Open the frontend
Open `frontend/index.html` in your browser and log in with one of the demo keys:

| API Key | Plan | Role |
|---|---|---|
| `demo-key-001` | enterprise | admin |
| `test-key-002` | starter | analyst |

### Step 6 — Stop services
```bash
docker compose down

# To also remove persisted data volumes
docker compose down -v
```

---

## 7. API Reference

### POST /analyze
Launch a multi-agent analysis pipeline.

**Headers:**
```
X-API-Key: <your_api_key>
Content-Type: application/json
Idempotency-Key: <optional_uuid>
```

**Request body:**
```json
{
  "input_data": {
    "location": "Tunis, TN",
    "product_id": "HARISSA-140G"
  }
}
```

**Response (202 Accepted):**
```json
{
  "job_id": "uuid-xxx",
  "status": "queued",
  "poll_url": "/jobs/uuid-xxx"
}
```

---

### GET /jobs/{job_id}
Poll for job completion.

**Response when done:**
```json
{
  "status": "done",
  "final_decision": "Heat wave detected. Increase production by 40%...",
  "confidence": 0.91,
  "agent_outputs": {
    "weather_agent": { "max_temp": 38.0, "heat_wave": true },
    "sales_agent": { "adjusted_30_days": 42000 },
    "production_agent": { "days_of_stock": 4.2 },
    "tools_called": ["weather_tool", "sales_tool", "rag_tool"]
  },
  "outcome": null
}
```

---

### POST /outcomes/{job_id}
Record the actual result after acting on a recommendation.
Updates forecast accuracy in RAG memory for future analyses.

**Request body:**
```json
{
  "actual_demand": 31200,
  "action_taken": true,
  "notes": "Stockout avoided, inventory sufficient"
}
```

**Response:**
```json
{
  "job_id": "uuid-xxx",
  "product_id": "HARISSA-140G",
  "actual_demand": 31200,
  "accuracy": 0.93,
  "action_taken": true,
  "saved": true,
  "message": "Outcome recorded successfully"
}
```

---

### POST /hitl/respond/{job_id}
Approve or reject a decision pending human review.

**Request body:**
```json
{
  "action": "approve",
  "comment": "Validated — proceed with reorder"
}
```

---

### GET /kpis
Business KPIs for the authenticated tenant.

```json
{
  "total_decisions": 64,
  "success_rate": 0.94,
  "avg_latency_seconds": 2.3,
  "total_cost_usd": 0.0042
}
```

---

### Full Endpoint Reference
| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/health` | GET | No | Platform status + available sectors |
| `/analyze` | POST | Yes | Launch multi-agent analysis |
| `/jobs` | GET | Yes | List all jobs for tenant |
| `/jobs/{id}` | GET | Yes | Get job status and result |
| `/jobs/{id}/retry` | POST | Yes (pro+) | Retry a failed job |
| `/outcomes/{job_id}` | POST | Yes | Record actual outcome vs recommendation |
| `/kpis` | GET | Yes | Business KPIs |
| `/hitl/pending` | GET | Yes | List decisions awaiting human review |
| `/hitl/respond/{id}` | POST | Yes | Approve or reject a HITL decision |
| `/observability/dashboard` | GET | Yes | System health, queues, circuit breakers |
| `/audit-logs` | GET | Yes (admin) | Full audit trail |
| `/circuit-breakers` | GET | Yes | State of all circuit breakers |
| `/rate-limit` | GET | Yes | Current rate limit status |
| `/sectors` | GET | No | List active sectors |
| `/dlq` | GET | Yes (admin) | Dead letter queue contents |

---

## 8. Adding a New Sector

### Example: adding the `legal` sector

**Step 1 — Register agents in the registry**
```python
# sectors/registry.py
SECTOR_AGENTS = {
    "supply_chain": [...],   # existing
    "legal": [
        "document_agent",
        "risk_agent",
        "aggregator_agent",
        "decision_agent",
    ],
}
```

**Step 2 — Create agent files**
```bash
mkdir sectors/legal
touch sectors/legal/document_agent.py
touch sectors/legal/risk_agent.py
touch sectors/legal/aggregator_agent.py
touch sectors/legal/decision_agent.py
```

**Step 3 — Implement each agent**
```python
# sectors/legal/document_agent.py
from core.state import UniversalState

async def run_document_agent(state: UniversalState) -> UniversalState:
    state["agent_outputs"]["document_agent"] = {
        "clauses": [...],
        "parties": [...],
    }
    return state
```

**That is all — zero changes to the API, orchestrator, or any core file.**

---

## 9. Adding a New Client

```sql
-- Connect to the database
docker exec -it <postgres_container> psql -U user -d platform

-- Insert new tenant
INSERT INTO tenants (tenant_id, name, sector, plan, api_key, role, user_id)
VALUES ('client_new', 'New Company', 'supply_chain', 'pro', 'sk-new-xyz789', 'analyst', 'user-001');
```

The client can immediately use the API with `X-API-Key: sk-new-xyz789`.

---

## 10. Tests

### Run tests
```bash
# Inside the Docker container
docker exec -it <api_container> pytest tests/ -v

# Locally with a virtual environment
pip install -r requirements.txt
pytest tests/ -v
```

### Available test files
| File | Description |
|---|---|
| `test_supply_chain.py` | Registry, aggregator rules, full pipeline with mocks |
| `test_chaos.py` | Circuit breaker, DLQ, retry and failure recovery |
| `load_test.py` | Locust load test — concurrent request simulation |

---

## 11. File Structure

```
multiagent_v6_final/
│
├── sectors/                        # Agents organized by sector
│   ├── registry.py                 ← Central sector registry
│   ├── supply_chain/               ✅ Implemented
│   │   ├── weather_agent.py        → Weather data (OpenWeatherMap)
│   │   ├── sales_agent.py          → Sales forecast (Prophet)
│   │   ├── production_agent.py     → Stock & capacity (PostgreSQL)
│   │   ├── aggregator_agent.py     → Rules-based alerts
│   │   └── decision_agent.py       → LLM recommendation (tool-calling + RAG)
│   ├── legal/                      🔲 Ready (empty)
│   ├── hr/                         🔲 Ready (empty)
│   └── real_estate/                🔲 Ready (empty)
│
├── core/
│   ├── state.py                    ← UniversalState shared across all agents
│   ├── orchestrator.py             ← Dynamic LangGraph orchestrator
│   ├── circuit_breaker.py          ← 3-state circuit breaker (Redis-persisted)
│   ├── hitl.py                     ← Human-in-the-loop checkpoint
│   ├── rbac.py                     ← Role-based access control + audit logs
│   ├── rate_limiting.py            ← Sliding window rate limiter
│   ├── idempotency.py              ← Duplicate request prevention
│   ├── job_locking.py              ← Distributed Redis job lock
│   ├── rag_memory.py               ← RAG vector storage (pgvector)
│   ├── memory.py                   ← Short-term decision memory (Redis)
│   ├── memory_safety.py            ← Outcome recording + anomaly detection
│   ├── kpis.py                     ← Business KPI tracking
│   ├── cost_alerting.py            ← LLM cost tracking per tenant
│   ├── connectors.py               ← Data connectors (CSV, Google Sheets, REST)
│   ├── erpnext_connector.py        ← ERPNext/Frappe connector
│   ├── erpuiux_connector.py        ← ARKEYEZ ERP connector
│   ├── tools.py                    ← Tool-calling definitions
│   ├── llm.py                      ← LLM abstraction (Groq)
│   ├── tracing.py                  ← Agent tracing decorator
│   ├── queue_control.py            ← Backpressure + queue routing
│   ├── jobs.py                     ← Job CRUD (Redis)
│   └── secrets.py                  ← Encrypted secret storage
│
├── api/
│   ├── main.py                     ← FastAPI app + all routes
│   ├── deps.py                     ← Shared get_tenant() dependency
│   ├── hitl_routes.py              ← /hitl/* routes
│   └── observability_routes.py     ← /observability/* routes
│
├── db/
│   ├── database.py                 ← Async connection pool (asyncpg)
│   └── init.sql                    ← Schema + demo seed data
│
├── demo/
│   └── fake_db.py                  ← In-memory data for DEMO_MODE=true
│
├── tests/
│   ├── test_supply_chain.py
│   ├── test_chaos.py
│   └── load_test.py
│
├── frontend/
│   └── index.html                  ← Full SPA dashboard (vanilla JS + Lucide icons)
│
├── .github/workflows/
│   └── ci-cd.yml                   ← GitHub Actions CI/CD
│
├── docker-compose.yml
├── Dockerfile
├── worker.py                       ← Celery worker entry point
├── requirements.txt
├── .env.example
├── README.md                       ← Quick start
├── ARCHITECTURE.md                 ← Full architecture + diagrams + ADRs
├── DOCUMENTATION.md                ← This file — full API and usage guide
├── TECHNICAL_DESCRIPTION.md        ← Technical deep-dive
└── HOW_TO_RUN.md                   ← Step-by-step run guide
```
