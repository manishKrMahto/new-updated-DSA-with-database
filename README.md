# PBM Deep Research Agent

A **Pharmacy Benefit Manager (PBM)** style research agent with a chat UI. It uses LangGraph to route queries (direct answers vs. data analysis), runs analytics on synthetic pharmacy claims data, and returns cost/formulary-focused reports. Chat history is stored in SQLite and survives restarts and page refreshes.

## Features

- **Chat UI** – Ask questions in natural language; responses support Markdown.
- **Intent routing** – Agent classifies queries as direct answers or data analysis (e.g. NSCLC claims).
- **Synthetic claims data** – Uses `data/synthetic_claims_120.csv` (drug, diagnosis, cost, etc.) for analytics.
- **Persistent history** – Sessions and messages stored in `data/chat.db` (SQLite).
- **Configurable server** – Default port **8000**, localhost-only; override via `settings.py` or env.

## Project structure

| Path | Description |
|------|-------------|
| `settings.py` | App settings: default port **8000**, host, debug, and paths. Env: `PORT`, `HOST`, `FLASK_DEBUG`. |
| `app.py` | Flask app: serves UI and `/api/chat/*`; calls `pbm_agent.run_agent()`. |
| `db.py` | SQLite persistence for sessions and messages (`data/chat.db`). |
| `pbm_agent.py` | LangGraph agent: intent router, direct answer, data retrieval, analytics, PBM reasoning. |
| `manage.py` | Run server: `python manage.py runserver` (Django-style). |
| `data/synthetic_claims_120.csv` | Synthetic pharmacy claims (e.g. drug_name, diagnosis, ingredient_cost). |
| `data/chat.db` | Chat DB (created automatically). |
| `templates/chat/index.html` | Chat UI (Tailwind, Markdown, session list, New Chat). |

## Requirements

- Python 3.10+
- OpenAI API key (for the PBM agent LLM)

## Setup

1. **Create and activate a virtual environment**

   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows

   # source .venv/bin/activate   # macOS/Linux
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Environment variables**

   Create a `.env` file or edit on `.env.example` in the project root (or set env vars):

   ```env
   OPENAI_API_KEY=paste_your_openai_key
   ```


## For Table migrations
```bash
python manage.py migrate
```

## Run

```bash
python manage.py runserver
```


Then open **http://127.0.0.1:8000/** in your browser.


## Usage

- **Direct questions** – e.g. “What is NSCLC?” → answered by the LLM.
- **Data-style questions** – e.g. “NSCLC claims” or “cost by drug” → agent filters claims (e.g. by diagnosis), runs analytics (e.g. avg cost, utilization by drug), and returns a short PBM-style report.

Chat history is saved in the sidebar; use **New Chat** to start a new conversation. Refreshing the page or restarting the server keeps existing sessions and messages.

---

# Final Architecture Summary — Multi-Agent LangGraph Hybrid RAG System

---

# 1. Core Philosophy

You are building a:

**Stateful Multi-Agent Hybrid RAG System**

where:

* one **orchestrator agent** manages the workflow
* specialized agents perform tasks
* shared state flows across nodes
* answers are grounded, validated, and traceable
* deep research becomes an escalation mechanism
* latency and cost are controlled via early exits

---

# 2. High-Level Flow

```text
User Query
     ↓
LangGraph Orchestrator Agent
     ↓
Intent Routing (small LLM + rules)
     ↓
Normal Processing Pipeline
     ↓
Evaluation Layer
     ↓
(If needed) Web Augmentation
     ↓
Final Grounded Response
```

---

# 3. Multi-Agent System Design

Yes — you are correctly using a **multi-agent architecture**, but with an important principle:

> Multiple specialized agents operate under ONE orchestrator using shared state.

This avoids agent chaos.

---

## Agents in the System

| Agent                   | Responsibility                  | Model       |
| ----------------------- | ------------------------------- | ----------- |
| **Orchestrator Agent**  | Controls workflow & transitions | GPT-4o-mini |
| **Router Agent**        | Decide Direct vs Hybrid RAG     | GPT-4o-mini |
| **SQL Agent**           | Generate SQL queries            | GPT-4o-mini |
| **Report Agent**        | Generate grounded answers       | GPT-4.1     |
| **Judge Agent**         | Confidence + reasoning          | GPT-4.1     |
| **Web Retrieval Agent** | Tavily search                   | Tool        |

All agents communicate through **LangGraph state**.

---

# 4. Shared State Management (Fix for LOOPHOLE 7)

LangGraph manages a global object:

## AgentState (Single Source of Truth)

```python
AgentState = {
    "query": "",
    "route": "",
    "sql_query": "",
    "db_result": None,
    "web_context": None,
    "answer": "",
    "sources": [],
    "confidence": 0.0,
    "reasoning": "",
    "retry_count": 0
}
```

### Benefits

* no manual passing of outputs
* easy debugging
* retries supported
* deep research integration clean
* observability ready

---

# 5. Normal Agent Workflow

## Step 1 — Hybrid Routing

Router uses:

* small LLM (GPT-4o-mini)
* rule signals (numbers, schema keywords)

Outputs:

```text
DIRECT_LLM
HYBRID_RAG
```

---

## Step 2A — Direct LLM Path

```text
Query → GPT-4.1 → Answer
```

### Early Exit Optimization (Latency Fix)

If:

* simple question
* high certainty

→ Skip judge
→ Return immediately.

This prevents unnecessary model calls.

---

## Step 2B — Hybrid RAG Path

### SQL Retrieval Flow

```text
Query
  ↓
SQL Agent
  ↓
SQL Guardrail
  ↓
Execute SQLite DB
```

(SQLite used for testing → PostgreSQL later.)

---

### SQL Guardrail

Checks:

* SELECT only
* schema validation
* column existence
* no destructive queries

---

# 6. Retry Strategy (Fix for LOOPHOLE 8)

Wrapped inside try–catch logic:

```text
Execute SQL
   ↓
If Error:
     retry_count += 1
     LLM repairs SQL
     retry once
```

Rules:

* maximum 1 retry
* prevent infinite loops

---

# 7. Grounded Report Generation

```text
DB Result
   ↓
Report Agent (GPT-4.1)
   ↓
Structured Answer
```

Answer MUST reference retrieved data.

---

# 8. Source Attribution Layer (Fix for LOOPHOLE 5)

Every response includes grounding metadata:

```json
{
  "answer": "...",
  "sources": ["database", "web"],
  "confidence": 0.87,
  "reasoning": "Database covered 80% of query; web added explanation."
}
```

### Why this matters

* debugging
* observability
* trust
* evaluation metrics
* production monitoring

Sources automatically appended during retrieval steps.

---

# 9. Evaluation Layer (Judge Agent)

Judge receives:

* user query
* generated answer
* retrieved context

Outputs:

* confidence score
* reasoning

---

## Early Exit Strategy (Fix for LOOPHOLE 10)

Skip judge if:

* direct LLM path
* short factual answer
* structured DB query success
* confidence heuristics high

Reduces latency significantly.

---

# 10. Adaptive Web Augmentation

If:

```text
confidence < threshold
```

Then:

```text
Web Agent → Tavily Search
        ↓
Merge DB + Web Context
        ↓
Regenerate Final Answer
```

Important:
Web results **augment**, not replace DB facts.

Sources updated:

```text
["database", "web"]
```

---

# 11. Latency Optimization Strategy (Major Improvement)

Worst-case calls reduced using:

### Early Exit Rules

| Condition                 | Action             |
| ------------------------- | ------------------ |
| Simple query              | Skip judge         |
| High confidence DB answer | Return early       |
| Router certainty high     | Skip fallback      |
| Retry success             | Skip re-evaluation |

Average calls drop from:

```
6 LLM calls → ~2–3 calls
```

---

# 12. Database Strategy

### Current

* SQLite (testing)

### Future (Production)

```text
PostgreSQL
   + connection pooling
   + concurrency safe
   + analytics queries
```

No architecture change needed later.

---

# 13. Final System Architecture Diagram

```text
                     USER
                       │
                       ▼
              Orchestrator Agent
                       │
               Router Agent
              /             \
       Direct LLM        Hybrid RAG
            │                │
            ▼                ▼
         Answer        SQL Agent
                             │
                      SQL Guardrail
                             │
                         Database
                             │
                       Report Agent
                             │
                       Judge Agent
                             │
           ┌────────Pass─────────┐
           │                     │
           ▼                     ▼
      Return Answer        Web Augment
                                   │
                                   ▼
                           Final Answer
                                   │
```

---

# 14. What You Have Built (Conceptually)

Your system is now:

**A Stateful Agentic Knowledge Engine**

Not just RAG.

It includes:

* multi-agent orchestration
* grounded reasoning
* evaluation loops
* adaptive retrieval
* escalation intelligence
* source attribution
* latency control

This architecture closely resembles internal enterprise AI assistants.
