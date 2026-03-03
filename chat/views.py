from __future__ import annotations

import json
from typing import Any, Dict

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

import db
from pbm_agent import run_agent


@ensure_csrf_cookie
def index(request: HttpRequest) -> HttpResponse:
    """
    Serve the chat UI.

    This renders the existing templates/chat/index.html file via Django's
    template engine and ensures a CSRF cookie is set for the frontend JS.
    """
    return render(request, "chat/index.html")


@require_POST
def chat_send(request: HttpRequest) -> JsonResponse:
    """
    Accept { "session_id": null | string, "message": string }.
    Run PBM agent and return { "session_id", "final_report", "agent_message" }.
    Sessions and messages are stored in the SQLite chat database via db.py.
    """
    try:
        try:
            payload: Dict[str, Any] = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON payload"}, status=400)

        session_id = payload.get("session_id")
        message = (payload.get("message") or "").strip()
        if not message:
            return JsonResponse({"error": "message is required"}, status=400)

        session_id = db.get_or_create_session(session_id)

        # Run the multi-agent LangGraph backend (stateful hybrid RAG system)
        agent_result = run_agent(message)
        # Human-readable provenance footer so users see where answers come from
        sources_list = agent_result.sources or []
        confidence_value = agent_result.confidence or 0.0
        parts = [
            "database (SQLite: pbm_claims)" if s == "database" else s
            for s in sources_list
        ]
        sources_str = ", ".join(parts) if parts else "—"
        provenance_footer = (
            f"\n\nSources: {sources_str}\nConfidence: {round(confidence_value, 3)}"
        )
        final_report = (agent_result.answer or "") + provenance_footer

        # Persist in database
        db.add_message(session_id, "user", message)
        db.add_message(session_id, "assistant", final_report)
        last_preview = message[:80] + ("..." if len(message) > 80 else "")
        db.update_session_last_message(session_id, last_preview)

        return JsonResponse(
            {
                "session_id": session_id,
                "final_report": final_report,
                "agent_message": final_report,
                "sources": agent_result.sources,
                "confidence": agent_result.confidence,
                "reasoning": agent_result.reasoning,
            }
        )
    except Exception as exc:  # pragma: no cover - safety net
        return JsonResponse({"error": str(exc)}, status=500)


@require_GET
def chat_sessions(request: HttpRequest) -> JsonResponse:
    """
    Return list of sessions for sidebar (from SQLite chat database).
    """
    sessions = db.get_sessions()
    return JsonResponse(sessions, safe=False)


@require_GET
def chat_history(request: HttpRequest, session_id: str) -> JsonResponse:
    """
    Return messages for a session (from SQLite chat database).
    """
    if not db.session_exists(session_id):
        return JsonResponse({"error": "session not found"}, status=404)
    messages = db.get_messages(session_id)
    return JsonResponse(messages, safe=False)

