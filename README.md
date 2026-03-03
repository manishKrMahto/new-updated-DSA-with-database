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

   Create a `.env` file in the project root (or set env vars):

   ```env
   OPENAI_API_KEY=your-openai-api-key
   ```

   Optional overrides:

   - `PORT` – Server port (default: 8000)
   - `HOST` – Bind address (default: 127.0.0.1)
   - `FLASK_DEBUG` – Set to `true` for debug mode

## Run

```bash
python manage.py runserver
```

Or:

```bash
python app.py
```

Then open **http://127.0.0.1:8000/** in your browser.


## Usage

- **Direct questions** – e.g. “What is NSCLC?” → answered by the LLM.
- **Data-style questions** – e.g. “NSCLC claims” or “cost by drug” → agent filters claims (e.g. by diagnosis), runs analytics (e.g. avg cost, utilization by drug), and returns a short PBM-style report.

Chat history is saved in the sidebar; use **New Chat** to start a new conversation. Refreshing the page or restarting the server keeps existing sessions and messages.
