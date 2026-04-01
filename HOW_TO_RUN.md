# 🚀 HOW TO RUN — MultiAgent Platform v6

## ⚡ Quick Start (Docker — Recommended)

### Step 1 — Clone & Configure
```bash
git clone https://github.com/YOUR_USERNAME/multiagent-platform-v6.git
cd multiagent-platform-v6
cp .env.example .env
```

Edit `.env` and fill in:
```
GROQ_API_KEY=your_groq_key        # Free at console.groq.com
ERPUIUX_API_KEY=your_erp_key      # From ERP-UI-UX Settings → API Access
ERPUIUX_SECRET=your_erp_secret
```

### Step 2 — Launch
```bash
docker-compose up --build
```

Services started automatically:
| Service | URL |
|---|---|
| FastAPI (backend) | http://localhost:8000 |
| Frontend dashboard | Open `frontend/index.html` in browser |
| Flower (Celery monitor) | http://localhost:5555 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

### Step 3 — Open Dashboard
Open `frontend/index.html` directly in your browser.
- Use API key: `demo-key-001`

---

## 🖥️ Manual Run (Without Docker)

### Prerequisites
```bash
python --version   # Python 3.11+
redis-server       # Redis running locally
# PostgreSQL running locally
```

### Install dependencies
```bash
pip install -r requirements.txt
```

### Initialize database
```bash
psql -U postgres -c "CREATE DATABASE platform;"
psql -U postgres -d platform -f db/init.sql
```

### Terminal 1 — FastAPI Backend
```bash
cp .env.example .env   # fill in your keys
uvicorn api.main:app --reload --port 8000
```

### Terminal 2 — Celery Worker
```bash
celery -A worker worker --loglevel=info -Q light,heavy
```

### Terminal 3 — Celery Monitor (optional)
```bash
celery -A worker flower --port=5555
```

### Open Frontend
Open `frontend/index.html` in your browser.

---

## 🔑 API Keys Needed

| Key | Where to get | Cost |
|---|---|---|
| `GROQ_API_KEY` | console.groq.com | Free |
| `ERPUIUX_API_KEY` | ERP-UI-UX → Settings → API Access | Local |
| Weather | No key needed (Open-Meteo) | Free |

---

## ✅ Verify Everything Works

```bash
# Health check
curl http://localhost:8000/health

# Test analysis
curl -X POST http://localhost:8000/analyze \
  -H "X-API-Key: demo-key-001" \
  -H "Content-Type: application/json" \
  -d '{"sector":"supply_chain","location":"Tunis, Tunisia","product_id":"HARISSA-140G"}'
```

Expected response:
```json
{"job_id": "...", "status": "queued"}
```

Poll result:
```bash
curl http://localhost:8000/jobs/{job_id} -H "X-API-Key: demo-key-001"
```

---

## 🌡️ Data Sources

| Agent | Data Source |
|---|---|
| `weather_agent` | Open-Meteo API (free, no key) — real weather |
| `production_agent` | ERP-UI-UX live stock (Bin doctype) |
| `sales_agent` | ERP-UI-UX Delivery Notes (last 30 days) |
| `decision_agent` | Groq LLM (Llama 3.3 70B) + RAG memory |

> All agents have automatic fallback to simulated data if external services are unavailable.

---

## 🐛 Common Issues

**`ModuleNotFoundError: langgraph`**
```bash
pip install -r requirements.txt
```

**Redis connection refused**
```bash
redis-server   # Start Redis first
```

**ERP connector returns fallback data**
- Check that ERP-UI-UX is running on `localhost:8000`
- Verify `ERPUIUX_API_KEY` and `ERPUIUX_SECRET` in `.env`
- Generate keys in ERP: Settings → My Settings → API Access

**`__pycache__` appears after running**
- Normal — Python creates it automatically
- Already in `.gitignore` — will NOT be pushed to GitHub

---

## 📁 Project Structure

```
multiagent_platform_v6/
├── api/                    ← FastAPI routes
├── core/                   ← Shared infrastructure
│   ├── orchestrator.py     ← LangGraph pipeline
│   ├── erpuiux_connector.py← ERP-UI-UX live data  ← NEW v6.1
│   ├── circuit_breaker.py  ← Fault tolerance
│   ├── hitl.py             ← Human-in-the-Loop
│   └── ...
├── sectors/
│   └── supply_chain/
│       ├── weather_agent.py    ← Open-Meteo live  ← UPDATED v6.1
│       ├── sales_agent.py      ← ERP live sales   ← UPDATED v6.1
│       ├── production_agent.py ← ERP live stock   ← UPDATED v6.1
│       ├── aggregator_agent.py
│       └── decision_agent.py   ← LLM + RAG
├── demo/
│   └── fake_db.py          ← Demo/test only
├── tests/
├── db/
├── frontend/
│   └── index.html          ← Dashboard UI
├── docker-compose.yml
├── .env.example            ← Copy to .env
└── requirements.txt
```
