"""
Flask backend for the Stateful Multi-Agent Hybrid RAG System.
Serves the chat UI and exposes API endpoints that use pbm_agent.run_agent.
Chat history is persisted in SQLite (data/chat.db) so it survives restarts and refreshes.
"""
from flask import Flask, jsonify, request, send_from_directory

from settings import PROJECT_ROOT
from pbm_agent import run_agent
import db

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)
app.config["JSON_AS_ASCII"] = False


@app.before_request
def _ensure_db():
    db.init_db()


TEMPLATES_DIR = PROJECT_ROOT / "templates"


@app.route("/")
def index():
    """Serve the chat UI."""
    return send_from_directory(TEMPLATES_DIR / "chat", "index.html")


@app.route("/api/chat/send/", methods=["POST"])
def chat_send():
    """
    Accept { "session_id": null | string, "message": string }.
    Run PBM agent and return { "session_id", "final_report", "agent_message" }.
    Sessions and messages are stored in the database.
    """
    try:
        data = request.get_json() or {}
        session_id = data.get("session_id")
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({"error": "message is required"}), 400

        session_id = db.get_or_create_session(session_id)

        # Run the multi-agent LangGraph backend (stateful hybrid RAG system)
        agent_result = run_agent(message)
        # Human-readable provenance footer so users see where answers come from
        sources_list = agent_result.sources or []
        confidence_value = agent_result.confidence or 0.0
        provenance_footer = f"\n\nSources: {sources_list}\nConfidence: {round(confidence_value, 3)}"
        final_report = (agent_result.answer or "") + provenance_footer

        # Persist in database
        db.add_message(session_id, "user", message)
        db.add_message(session_id, "assistant", final_report)
        last_preview = message[:80] + ("..." if len(message) > 80 else "")
        db.update_session_last_message(session_id, last_preview)

        return jsonify({
            "session_id": session_id,
            "final_report": final_report,
            "agent_message": final_report,
            "sources": agent_result.sources,
            "confidence": agent_result.confidence,
            "reasoning": agent_result.reasoning,
        })
    except Exception as e:
        app.logger.exception("chat_send error")
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat/sessions/")
def chat_sessions():
    """Return list of sessions for sidebar (from database)."""
    return jsonify(db.get_sessions())


@app.route("/api/chat/history/<session_id>/")
def chat_history(session_id):
    """Return messages for a session (from database)."""
    if not db.session_exists(session_id):
        return jsonify({"error": "session not found"}), 404
    return jsonify(db.get_messages(session_id))


if __name__ == "__main__":
    from settings import DEBUG, DEFAULT_PORT, HOST
    app.run(host=HOST, port=DEFAULT_PORT, debug=DEBUG)
