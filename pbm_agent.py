from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph

from settings import KNOWLEDGE_DB_PATH

# --------------------------------------------------
# Setup: Models & Environment
# --------------------------------------------------

load_dotenv()

# Orchestrated models
small_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
sql_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
report_llm = ChatOpenAI(model="gpt-4.1", temperature=0)
judge_llm = ChatOpenAI(model="gpt-4.1", temperature=0)
deep_research_llm = ChatOpenAI(model="gpt-4.1", temperature=0.1)


# --------------------------------------------------
# Shared Agent State (Single Source of Truth)
# --------------------------------------------------

class AgentState(TypedDict, total=False):
    query: str
    route: Literal["DIRECT_LLM", "HYBRID_RAG"]
    sql_query: str
    db_result: Optional[List[Dict[str, Any]]]
    web_context: Optional[str]
    answer: str
    sources: List[str]
    confidence: float
    reasoning: str
    retry_count: int
    escalated_to_research: bool


@dataclass
class AgentOutput:
    answer: str
    sources: List[str]
    confidence: float
    reasoning: str


# --------------------------------------------------
# SQLite helper (current dev backend)
# --------------------------------------------------

def _get_db_connection() -> sqlite3.Connection:
    KNOWLEDGE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(KNOWLEDGE_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _introspect_schema() -> str:
    """Return a lightweight textual description of available tables/columns."""
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        tables = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        schema_parts: List[str] = []
        for (table_name,) in tables:
            cols = cur.execute(f"PRAGMA table_info({table_name})").fetchall()
            col_list = ", ".join(str(c[1]) for c in cols)
            schema_parts.append(f"Table {table_name}({col_list})")
        conn.close()
        return "; ".join(schema_parts) or "No tables defined."
    except Exception:
        return "Schema introspection failed."


# --------------------------------------------------
# Router Agent — Direct vs Hybrid RAG
# --------------------------------------------------

def router_agent(state: AgentState) -> Dict[str, Any]:
    query = state["query"]
    schema_text = _introspect_schema()

    prompt = f"""
You are a routing agent for a hybrid RAG system.

User query:
\"\"\"{query}\"\"\"

Database schema (SQLite):
{schema_text}

Decide whether this query should be answered:
- DIRECT_LLM: simple conversational or general question where SQL is not needed
- HYBRID_RAG: question that clearly benefits from querying the database

Return ONLY one word: DIRECT_LLM or HYBRID_RAG.
"""
    route = small_llm.invoke(prompt).content.strip().upper()
    if route not in ("DIRECT_LLM", "HYBRID_RAG"):
        route = "DIRECT_LLM"
    return {"route": route, "retry_count": state.get("retry_count", 0), "sources": state.get("sources", [])}


def route_after_router(state: AgentState) -> Literal["DIRECT_LLM", "HYBRID_RAG"]:
    return state.get("route", "DIRECT_LLM")


# --------------------------------------------------
# Direct LLM Path
# --------------------------------------------------

def direct_llm_agent(state: AgentState) -> Dict[str, Any]:
    query = state["query"]
    prompt = f"""
You are a helpful assistant.
Answer the user's question concisely but clearly.

User query:
\"\"\"{query}\"\"\"

Respond with just the answer.
"""
    answer = report_llm.invoke(prompt).content.strip()

    # Simple early-exit heuristic: short questions, no obvious analytics language.
    simple = len(query) < 120 and not any(
        kw in query.lower()
        for kw in ["join", "group by", "sum(", "average", "count(", "trend", "time series"]
    )

    confidence = 0.9 if simple else 0.75
    return {
        "answer": answer,
        "sources": ["model"],
        "confidence": confidence,
        "reasoning": "Direct LLM path with heuristic high confidence.",
    }


def route_after_direct_llm(state: AgentState) -> Literal["END", "JUDGE"]:
    # Early exit optimization: skip judge for simple / confident answers
    if state.get("confidence", 0.0) >= 0.85:
        return "END"
    return "JUDGE"


# --------------------------------------------------
# SQL Agent + Guardrail + Execution (Hybrid RAG)
# --------------------------------------------------

def sql_agent(state: AgentState) -> Dict[str, Any]:
    query = state["query"]
    schema_text = _introspect_schema()
    prompt = f"""
You are a SQL generation assistant for SQLite.

User query:
\"\"\"{query}\"\"\"

Database schema:
{schema_text}

Write a single safe SQL SELECT query in SQLite dialect that best answers the question.
Rules:
- SELECT only (no INSERT/UPDATE/DELETE/DDL)
- No semicolons, comments, or multiple statements
- Only use existing tables/columns from the schema.

Return ONLY the SQL query, nothing else.
"""
    sql = sql_llm.invoke(prompt).content.strip()
    return {"sql_query": sql}


def _sql_guardrail(sql: str, schema_text: str) -> None:
    upper = sql.upper()
    # At this point we expect the caller to have normalized the SQL
    # so that it starts with SELECT. If not, it's considered unsafe.
    if not upper.startswith("SELECT"):
        raise ValueError("Only SELECT queries are allowed.")
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", ";", "--", "/*"]
    if any(token in upper for token in forbidden):
        raise ValueError("Destructive or unsafe SQL pattern detected.")
    # Very lightweight column/table check (string containment on schema text)
    tokens = [t for t in sql.replace(",", " ").split() if "." in t]
    for token in tokens:
        if token.strip("()") not in schema_text:
            # Non-fatal: we allow judge/LLM to recover via retry mechanism
            return


def sql_guardrail_node(state: AgentState) -> Dict[str, Any]:
    raw_sql = state.get("sql_query", "") or ""
    schema_text = _introspect_schema()

    # Many models occasionally return explanations or formatting around the SQL.
    # Normalize by extracting the first SELECT statement and trimming trailing semicolons.
    upper = raw_sql.upper()
    select_idx = upper.find("SELECT")
    if select_idx == -1:
        # Let the downstream retry / judge logic deal with this, but avoid crashing the graph.
        # We mark db_result as empty so the system can still answer via model/web.
        return {"sql_query": "", "db_result": []}

    cleaned = raw_sql[select_idx:].strip()
    # Drop everything after a semicolon to enforce a single statement.
    if ";" in cleaned:
        cleaned = cleaned.split(";", 1)[0].strip()

    _sql_guardrail(cleaned, schema_text)
    return {"sql_query": cleaned}


def _execute_sql(sql: str) -> List[Dict[str, Any]]:
    conn = _get_db_connection()
    try:
        cur = conn.cursor()
        rows = cur.execute(sql).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def sql_execute_node(state: AgentState) -> Dict[str, Any]:
    sql = state.get("sql_query", "")
    retry_count = state.get("retry_count", 0)

    try:
        rows = _execute_sql(sql)
        return {"db_result": rows, "retry_count": retry_count}
    except Exception as e:
        if retry_count >= 1:
            # Max 1 retry; surface error up the stack
            raise

        # Let LLM repair SQL once
        schema_text = _introspect_schema()
        repair_prompt = f"""
The following SQL query failed when executed against a SQLite database:

Original SQL:
\"\"\"{sql}\"\"\"

Error:
{e}

Database schema:
{schema_text}

Produce a corrected single SELECT query (SQLite dialect) that may fix the issue.
Rules:
- SELECT only
- No comments
- No semicolons
- Only one statement.

Return ONLY the corrected SQL, nothing else.
"""
        repaired_sql = sql_llm.invoke(repair_prompt).content.strip()
        rows = _execute_sql(repaired_sql)
        return {"db_result": rows, "sql_query": repaired_sql, "retry_count": retry_count + 1}


# --------------------------------------------------
# Report Agent — Grounded Answer from DB
# --------------------------------------------------

def report_agent(state: AgentState) -> Dict[str, Any]:
    query = state["query"]
    db_result = state.get("db_result") or []

    preview_rows = json.dumps(db_result[:20], indent=2, default=str)
    prompt = f"""
You are a report-writing agent that must ground all answers in the provided database rows.

User query:
\"\"\"{query}\"\"\"

Database rows (JSON, up to 20):
{preview_rows}

Write a clear, structured answer that directly references what is present in the data.
If the data is insufficient to fully answer, say so explicitly and do not invent rows or values.
"""
    answer = report_llm.invoke(prompt).content.strip()

    return {
        "answer": answer,
        "sources": list(sorted(set(state.get("sources", []) + ["database"]))),
    }


# --------------------------------------------------
# Web Retrieval Agent (Tavily)
# --------------------------------------------------

try:
    from tavily import TavilyClient  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    TavilyClient = None  # type: ignore


def web_retrieval_agent(state: AgentState) -> Dict[str, Any]:
    if TavilyClient is None:
        # Web is unavailable; keep existing state
        return {"web_context": None}

    client = TavilyClient()
    query = state["query"]

    try:
        result = client.search(query=query, max_results=5)
        # Tavily returns JSON; keep a compact text representation
        web_context = json.dumps(result, indent=2, default=str)
    except Exception:
        web_context = None

    sources = list(sorted(set(state.get("sources", []) + (["web"] if web_context else []))))
    return {"web_context": web_context, "sources": sources}


# --------------------------------------------------
# Judge Agent — Confidence + Reasoning
# --------------------------------------------------

def judge_agent(state: AgentState) -> Dict[str, Any]:
    query = state["query"]
    answer = state.get("answer", "")
    db_result = state.get("db_result") or []
    web_context = state.get("web_context")

    context_snippet = {
        "db_result": db_result[:10],
        "has_more_db_rows": len(db_result) > 10,
        "web_context_preview": (web_context[:2000] + "…") if web_context else None,
    }

    prompt = f"""
You are an evaluation agent.
You will receive a user query, an answer, and the context that was used to produce it.

You must:
- Judge whether the answer is well grounded in the context
- Provide a confidence score between 0.0 and 1.0
- Explain your reasoning briefly.

Respond strictly as JSON with keys: confidence (float), reasoning (string).

User query:
\"\"\"{query}\"\"\"

Answer:
\"\"\"{answer}\"\"\"

Context (JSON):
{json.dumps(context_snippet, indent=2, default=str)}
"""
    raw = judge_llm.invoke(prompt).content.strip()
    try:
        parsed = json.loads(raw)
        confidence = float(parsed.get("confidence", 0.0))
        reasoning = str(parsed.get("reasoning", "")).strip()
    except Exception:
        confidence = 0.6
        reasoning = f"Failed to parse judge JSON. Raw: {raw!r}"

    return {"confidence": confidence, "reasoning": reasoning}


def route_after_judge(state: AgentState) -> Literal["END", "WEB"]:
    # Early exit: return answer if reasonably confident
    if state.get("confidence", 0.0) >= 0.8:
        return "END"
    return "WEB"


def route_after_web(state: AgentState) -> Literal["END", "DEEP_RESEARCH"]:
    # If web added context but we are still low confidence, escalate to deep research
    if state.get("confidence", 0.0) < 0.6:
        return "DEEP_RESEARCH"
    return "END"


# --------------------------------------------------
# Deep Research Agent — Escalation Layer
# --------------------------------------------------

def deep_research_agent(state: AgentState) -> Dict[str, Any]:
    query = state["query"]
    answer = state.get("answer", "")
    db_result = state.get("db_result") or []
    web_context = state.get("web_context")

    context_snippet = {
        "existing_answer": answer,
        "db_rows": db_result[:20],
        "web_context_preview": (web_context[:4000] + "…") if web_context else None,
    }

    prompt = f"""
You are a deep research agent that improves an existing answer using iterative reasoning.

You will receive:
- The original user query
- The current best answer
- Database rows
- Web search context

Your job:
- Carefully re-check the data and web context
- Strengthen the answer
- Clarify uncertainty and explicitly state what is unknown
- Keep the answer grounded; no fabrications.

User query:
\"\"\"{query}\"\"\"

Context (JSON):
{json.dumps(context_snippet, indent=2, default=str)}

Write the improved final answer.
"""
    improved_answer = deep_research_llm.invoke(prompt).content.strip()

    return {
        "answer": improved_answer,
        "escalated_to_research": True,
        "sources": list(sorted(set(state.get("sources", []) + ["database", "web"]))),
    }


# --------------------------------------------------
# Build LangGraph Orchestrator
# --------------------------------------------------

builder = StateGraph(AgentState)

builder.add_node("ROUTER", router_agent)
builder.add_node("DIRECT_LLM", direct_llm_agent)
builder.add_node("SQL_AGENT", sql_agent)
builder.add_node("SQL_GUARDRAIL", sql_guardrail_node)
builder.add_node("SQL_EXECUTE", sql_execute_node)
builder.add_node("REPORT", report_agent)
builder.add_node("JUDGE", judge_agent)
builder.add_node("WEB", web_retrieval_agent)
builder.add_node("DEEP_RESEARCH", deep_research_agent)

builder.set_entry_point("ROUTER")

builder.add_conditional_edges(
    "ROUTER",
    route_after_router,
    {
        "DIRECT_LLM": "DIRECT_LLM",
        "HYBRID_RAG": "SQL_AGENT",
    },
)

builder.add_conditional_edges(
    "DIRECT_LLM",
    route_after_direct_llm,
    {
        "END": END,
        "JUDGE": "JUDGE",
    },
)

builder.add_edge("SQL_AGENT", "SQL_GUARDRAIL")
builder.add_edge("SQL_GUARDRAIL", "SQL_EXECUTE")
builder.add_edge("SQL_EXECUTE", "REPORT")
builder.add_edge("REPORT", "JUDGE")

builder.add_conditional_edges(
    "JUDGE",
    route_after_judge,
    {
        "END": END,
        "WEB": "WEB",
    },
)

builder.add_conditional_edges(
    "WEB",
    route_after_web,
    {
        "END": END,
        "DEEP_RESEARCH": "DEEP_RESEARCH",
    },
)

builder.add_edge("DEEP_RESEARCH", END)

graph = builder.compile()


# --------------------------------------------------
# Public API
# --------------------------------------------------

def run_agent(query: str) -> AgentOutput:
    """
    Run the stateful multi-agent hybrid RAG system and return
    the final grounded response plus attribution metadata.
    """
    initial_state: AgentState = {
        "query": query,
        "route": "DIRECT_LLM",
        "sql_query": "",
        "db_result": None,
        "web_context": None,
        "answer": "",
        "sources": [],
        "confidence": 0.0,
        "reasoning": "",
        "retry_count": 0,
        "escalated_to_research": False,
    }
    final_state = graph.invoke(initial_state)

    return AgentOutput(
        answer=final_state.get("answer", ""),
        sources=final_state.get("sources", []),
        confidence=float(final_state.get("confidence", 0.0)),
        reasoning=final_state.get("reasoning", ""),
    )


if __name__ == "__main__":
    user_query = input("\nAsk the Knowledge Engine: ")
    result = run_agent(user_query)
    print("\n===== FINAL ANSWER =====\n")
    print(result.answer)
    print("\nSources:", ", ".join(result.sources))
    print("Confidence:", result.confidence)
    print("Reasoning:", result.reasoning)