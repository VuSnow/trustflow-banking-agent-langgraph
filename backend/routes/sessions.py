"""Session management routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.chat_session_store import ChatSessionStore

router = APIRouter(tags=["sessions"])

chat_session_store: ChatSessionStore = None


def init(store: ChatSessionStore):
    global chat_session_store
    chat_session_store = store


class SessionCreateRequest(BaseModel):
    user_id: str
    title: str | None = None


class SessionUpdateRequest(BaseModel):
    title: str | None = None
    status: str | None = None


@router.post("/sessions")
async def create_session(request: SessionCreateRequest):
    session = chat_session_store.create_session(
        user_id=request.user_id,
        title=request.title,
    )
    return session


@router.get("/sessions")
async def list_sessions(user_id: str):
    return chat_session_store.list_sessions(user_id)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = chat_session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 50):
    return chat_session_store.get_messages(session_id, limit=limit)
