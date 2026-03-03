from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, TypedDict

import io
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pypdf import PdfReader

from settings import KNOWLEDGE_DB_PATH

# --------------------------------------------------
# Setup: Models, Tools & Environment
# --------------------------------------------------

load_dotenv()

# Single core model used for all agent reasoning
core_llm = ChatOpenAI(model="gpt-4.1", temperature=0)


# --------------------------------------------------
# Formatter prompt for executive-style output
# --------------------------------------------------

FORMAT_PROMPT = """
You are a healthcare analytics assistant.

Rewrite the provided analysis into a clean, structured,
executive-friendly Markdown format using:

- Clear section headers
- Bullet points
- Short paragraphs
- Logical grouping
- No repetition
- Professional tone

You MUST output valid Markdown and you MUST use
exactly these section headings, each starting with "## ":

## Clinical Summary
## Key Findings
## Data Limitations
## Recommended Actions
## Final Conclusion

Formatting rules (VERY IMPORTANT):
- Start each section header with "## " exactly, followed by the section name.
- Put a blank line after each heading.
- Put blank lines between paragraphs.
- Use bullet lists under the *Findings*, *Limitations*, and *Recommended Actions* sections.
- Do not add any sign-off, author name, or date footer.
- Do not add any extra sections before or after these.

Analysis to format:
{analysis}
"""


# --------------------------------------------------
# Shared Agent State (Single Source of Truth)
# --------------------------------------------------

class AgentState(TypedDict, total=False):
    query: str
    route: Literal["DIRECT_LLM", "HYBRID_RAG"]
    sql_query: str
    db_result: Optional[List[Dict[str, Any]]]
    doc_text: Optional[str]
    web_context: Optional[str]
    answer: str  # current best answer / analysis (may be unformatted before formatter)
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
# Tool implementations (docs + simple web scraping)
# --------------------------------------------------

def _fetch_and_parse_document(url: str) -> str:
    """
    Fetch a PDF or HTML document and return extracted text (truncated for safety).
    """
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "").lower()
    text: str

    if "pdf" in content_type or url.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(resp.content))
        pages_text = []
        for page in reader.pages[:10]:  # cap pages for latency
            pages_text.append(page.extract_text() or "")
        text = "\n\n".join(pages_text)
    else:
        soup = BeautifulSoup(resp.text, "html.parser")
        # crude main-text extraction: drop script/style, join visible text
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(t.strip() for t in soup.get_text(separator=" ").split())

    # Truncate to protect token budget
    if len(text) > 10000:
        text = text[:10000]
    return text


def _scrape_web_page(url: str) -> str:
    """
    Scrape a general web page and return its main textual content (truncated).
    """
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(t.strip() for t in soup.get_text(separator=" ").split())
    if len(text) > 10000:
        text = text[:10000]
    return text


@tool
def fetch_and_parse_document(url: str) -> str:
    """Fetch a PDF or HTML document from a URL and return extracted text (truncated)."""
    return _fetch_and_parse_document(url)


@tool
def scrape_web_page(url: str) -> str:
    """Scrape a web page and return its main textual content (truncated)."""
    return _scrape_web_page(url)


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
    route = core_llm.invoke(prompt).content.strip().upper()
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
You are an expert analyst.
Decide first whether the user is asking for:
- A casual greeting or small-talk question (e.g., "hello", "hi", "what are you doing?", "how are you?", "thanks").
- Or a substantive question that deserves an in-depth analysis or report.

If it is a casual greeting / small-talk query:
- Respond in a friendly, conversational tone.
- Keep the response SHORT (1–3 sentences).
- Do NOT write a report, headings, or long sections.

If it is a substantive question:
Write an in-depth, well-structured report in response to the user's query.

Formatting requirements (very important) for substantive questions:
- Use Markdown headings (##, ###) for sections.
- Put a blank line after each heading.
- Put blank lines between paragraphs.
- Use bullet lists where helpful, with a blank line before and after each list.
- Do not add any sign-off, author name, or "Prepared by" / date footer.
- Do not reference this instruction block or say that you are an AI model.

User query:
\"\"\"{query}\"\"\"

Respond with either:
- A short conversational reply (for casual queries), OR
- A full report (for substantive queries).
"""
    answer = core_llm.invoke(prompt).content.strip()

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
    sql = core_llm.invoke(prompt).content.strip()
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
        repaired_sql = core_llm.invoke(repair_prompt).content.strip()
        rows = _execute_sql(repaired_sql)
        return {"db_result": rows, "sql_query": repaired_sql, "retry_count": retry_count + 1}


# --------------------------------------------------
# Report Agent — Grounded Analysis from DB
# --------------------------------------------------

def report_agent(state: AgentState) -> Dict[str, Any]:
    query = state["query"]
    db_result = state.get("db_result") or []
    doc_text = state.get("doc_text") or ""

    preview_rows = json.dumps(db_result[:20], indent=2, default=str)
    doc_snippet = doc_text[:2000] if doc_text else ""
    prompt = f"""
You are a PBM clinical analytics AI.

Your task is to write a detailed internal analysis (not yet formatted for executives)
based ONLY on the data and document context provided.

User query:
\"\"\"{query}\"\"\"

Database rows (JSON, up to 20):
{preview_rows}

Additional document context (may be empty, truncated):
\"\"\"{doc_snippet}\"\"\"

Write a thorough analytical narrative that:
- Explains what the data shows about utilization, prescribing patterns, and cost.
- Connects any clinical guidance from the document (if provided) to the observed or hypothetical claims.
- Explicitly calls out important caveats and data gaps.
- Uses plain paragraphs and inline lists; do NOT worry about headings, bullets, or final presentation.

This output is an intermediate analysis that will be passed to a separate formatter.
Do not add any sign-off, author name, or date footer.
"""
    answer = core_llm.invoke(prompt).content.strip()

    sources = set(state.get("sources", []))
    if db_result:
        sources.add("database")
    if doc_snippet:
        sources.add("doc")

    return {
        "answer": answer,
        "sources": list(sorted(sources)),
    }


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
    raw = core_llm.invoke(prompt).content.strip()
    try:
        parsed = json.loads(raw)
        confidence = float(parsed.get("confidence", 0.0))
        reasoning = str(parsed.get("reasoning", "")).strip()
    except Exception:
        confidence = 0.6
        reasoning = f"Failed to parse judge JSON. Raw: {raw!r}"

    return {"confidence": confidence, "reasoning": reasoning}


def route_after_judge(state: AgentState) -> Literal["END", "WEB"]:
    # Web augmentation is disabled in this version; always end after judging.
    return "END"


def route_after_web(state: AgentState) -> Literal["END", "DEEP_RESEARCH"]:
    # If web added context but we are still low confidence, escalate to deep research
    if state.get("confidence", 0.0) < 0.6:
        return "DEEP_RESEARCH"
    return "END"


# --------------------------------------------------
# Deep Research Agent — Escalation Layer (improves analysis)
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
You are a deep research agent that revises and expands an existing answer using iterative reasoning.

You will receive:
- The original user query
- The current best answer
- Database rows
- Optional external context

Your job:
- Carefully re-check the data and context.
- Produce a substantially more detailed, better organized, and more insightful report.
- Add missing nuance, caveats, and edge cases.
- Clarify uncertainty and explicitly state what is unknown.
- Keep the answer grounded; no fabrications beyond what is reasonably implied by the data and context.

Formatting requirements (very important):
- Use Markdown headings (##, ###) for sections.
- Put a blank line after each heading.
- Put blank lines between paragraphs.
- Use bullet lists where helpful, with a blank line before and after each list.
- Do not add any sign-off, author name, or "Prepared by" / date footer.

User query:
\"\"\"{query}\"\"\"

Context (JSON):
{json.dumps(context_snippet, indent=2, default=str)}

Write the improved, in-depth analytical narrative (still not formatted for executives).
"""
    improved_answer = core_llm.invoke(prompt).content.strip()

    sources = set(state.get("sources", []))
    sources.add("database")
    return {
        "answer": improved_answer,
        "escalated_to_research": True,
        "sources": list(sorted(sources)),
    }


# --------------------------------------------------
# Formatter Agent — Executive-Friendly Structure
# --------------------------------------------------

def formatter_agent(state: AgentState) -> Dict[str, Any]:
    """
    Take the current analytical answer and rewrite it into a
    clean, executive-friendly format using FORMAT_PROMPT.
    """
    raw_analysis = state.get("answer", "") or ""
    if not raw_analysis.strip():
        return {}

    prompt = FORMAT_PROMPT.format(analysis=raw_analysis)
    formatted = core_llm.invoke(prompt).content.strip()

    # Post-process to enforce Markdown headings even if the model
    # forgets to include the leading "## ".
    sections = [
        "Clinical Summary",
        "Key Findings",
        "Data Limitations",
        "Recommended Actions",
        "Final Conclusion",
    ]
    for name in sections:
        pattern = rf"(^|\n)\s*{name}\s*\n"
        replacement = rf"\1## {name}\n\n"
        formatted = re.sub(pattern, replacement, formatted)

    # Ensure the first section starts correctly if the model deviated.
    if "## Clinical Summary" not in formatted and "Clinical Summary" in formatted:
        formatted = formatted.replace(
            "Clinical Summary",
            "## Clinical Summary\n\n",
            1,
        )

    return {"answer": formatted}


# --------------------------------------------------
# Doc pre-processing node
# --------------------------------------------------

def doc_tool_node(state: AgentState) -> Dict[str, Any]:
    """
    Lightweight pre-processing node:
    - Detects URLs in the query
    - For the first URL, fetches and parses document or web page text
    - Stores resulting text in shared state as `doc_text`
    """
    query = state.get("query", "")
    url_match = re.search(r"https?://\S+", query)
    if not url_match:
        return {}
    url = url_match.group(0).strip().rstrip('\"\'')
    try:
        if url.lower().endswith(".pdf"):
            text = _fetch_and_parse_document(url)
        else:
            text = _scrape_web_page(url)
    except Exception:
        text = ""
    return {"doc_text": text}


# --------------------------------------------------
# Build LangGraph Orchestrator
# --------------------------------------------------

builder = StateGraph(AgentState)

builder.add_node("DOC_TOOL", doc_tool_node)
builder.add_node("ROUTER", router_agent)
builder.add_node("DIRECT_LLM", direct_llm_agent)
builder.add_node("SQL_AGENT", sql_agent)
builder.add_node("SQL_GUARDRAIL", sql_guardrail_node)
builder.add_node("SQL_EXECUTE", sql_execute_node)
builder.add_node("REPORT", report_agent)
builder.add_node("FORMATTER", formatter_agent)
builder.add_node("JUDGE", judge_agent)
builder.add_node("DEEP_RESEARCH", deep_research_agent)

builder.set_entry_point("DOC_TOOL")

builder.add_conditional_edges(
    "DOC_TOOL",
    lambda state: "ROUTER",
    {
        "ROUTER": "ROUTER",
    },
)

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
builder.add_edge("REPORT", "FORMATTER")
builder.add_edge("FORMATTER", "JUDGE")
builder.add_edge("JUDGE", END)
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