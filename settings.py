"""
Application settings. Default port is 8000.
Override via environment variables or .env if needed.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root (directory containing settings.py)
PROJECT_ROOT = Path(__file__).resolve().parent

# Data directory and paths
DATA_DIR = PROJECT_ROOT / "data"

# Chat persistence database (for UI sessions/history)
CHAT_DB_PATH = DATA_DIR / "chat.db"

# Knowledge database for Hybrid RAG SQL retrieval (SQLite for development; upgradeable to Postgres)
KNOWLEDGE_DB_PATH = DATA_DIR / "knowledge.db"

# Server defaults (localhost only; use HOST=0.0.0.0 to allow network access)
DEFAULT_PORT = int(os.environ.get("PORT", 8000))
HOST = os.environ.get("HOST", "127.0.0.1")
DEBUG = os.environ.get("FLASK_DEBUG", "true").lower() in ("1", "true", "yes")
