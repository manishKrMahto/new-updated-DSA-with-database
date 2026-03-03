from __future__ import annotations

from django.urls import path

from . import views

urlpatterns = [
    # Chat UI
    path("", views.index, name="chat_index"),
    # JSON API endpoints (matching the previous Flask routes)
    path("api/chat/send/", views.chat_send, name="chat_send"),
    path("api/chat/sessions/", views.chat_sessions, name="chat_sessions"),
    path("api/chat/history/<str:session_id>/", views.chat_history, name="chat_history"),
]

