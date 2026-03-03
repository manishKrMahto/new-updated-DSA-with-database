## Multi-Agent LangGraph Hybrid RAG Backend

This backend replaces the previous PBM-specific agent with a **stateful multi-agent hybrid RAG system**.

### Architecture

- **Orchestrator (LangGraph)** managing shared `AgentState`
- **Router Agent** (`ROUTER` node, `gpt-4o-mini`): decides `DIRECT_LLM` vs `HYBRID_RAG`
- **Direct LLM Agent** (`DIRECT_LLM`, `gpt-4.1`): answers simple queries with early-exit heuristic
- **SQL Agent** (`SQL_AGENT`, `gpt-4o-mini`): generates `SELECT`-only SQL for SQLite
- **SQL Guardrail** (`SQL_GUARDRAIL`): enforces safe, read-only SQL
- **SQL Execute** (`SQL_EXECUTE`): runs against `data/knowledge.db` with 1-shot retry & repair
- **Report Agent** (`REPORT`, `gpt-4.1`): produces grounded answers from DB rows
- **Judge Agent** (`JUDGE`, `gpt-4.1`): outputs `confidence` and `reasoning`
- **Web Retrieval Agent** (`WEB`, Tavily): augments low-confidence answers with web context
- **Deep Research Agent** (`DEEP_RESEARCH`, `gpt-4.1`): escalation path for very low confidence

The shared state matches the conceptual `AgentState` from the spec and flows through all nodes.

### Files

- `settings.py`: defines `KNOWLEDGE_DB_PATH` (`data/knowledge.db`) and chat DB path
- `pbm_agent.py`: implements the LangGraph multi-agent system and `run_agent(query)`
- `app.py`: Flask API, calls `run_agent` and returns `{ answer, sources, confidence, reasoning }`
- `db.py`: unchanged; persists chat sessions and messages in SQLite

### API Behavior

`POST /api/chat/send/` with:

```json
{ "session_id": null, "message": "your question" }
```

returns:

```json
{
  "session_id": "uuid",
  "final_report": "answer text",
  "agent_message": "answer text",
  "sources": ["database", "web"],
  "confidence": 0.87,
  "reasoning": "short judge explanation"
}
```

### Database Notes

- The hybrid RAG path uses **SQLite** via `data/knowledge.db`.
- You can create tables and load data manually (e.g., `facts`, `documents`, etc.).
- For production, you can migrate the SQL-related code in `pbm_agent.py` to PostgreSQL with:
  - a real connection pool
  - the same SQL Agent / Guardrail / Judge / Web / Deep Research structure.

