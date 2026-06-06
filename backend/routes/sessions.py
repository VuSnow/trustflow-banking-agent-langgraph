"""Session management routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services.chat_session_store import ChatSessionStore
from backend.services.task_store import TaskStore

router = APIRouter(tags=["sessions"])

chat_session_store: ChatSessionStore = None
task_store: TaskStore = None


def init(store: ChatSessionStore, tasks: TaskStore | None = None):
    global chat_session_store, task_store
    chat_session_store = store
    task_store = tasks or TaskStore()


class SessionCreateRequest(BaseModel):
    user_id: str
    title: str | None = None


class SessionUpdateRequest(BaseModel):
    title: str | None = None
    status: str | None = None


class TaskUpdateRequest(BaseModel):
    action: str


@router.post("/sessions")
async def create_session(request: SessionCreateRequest):
    return chat_session_store.create_session(
        user_id=request.user_id,
        title=request.title,
    )


@router.get("/sessions")
async def list_sessions(user_id: str):
    return chat_session_store.list_sessions(user_id)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    session = chat_session_store.get_session_with_messages(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str, limit: int = 50):
    return chat_session_store.get_messages(session_id, limit=limit)


@router.get("/sessions/{session_id}/tasks")
async def get_tasks(session_id: str):
    if not chat_session_store.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"tasks": task_store.list_tasks(session_id)}


@router.patch("/sessions/{session_id}/tasks/{task_id}")
async def update_task(session_id: str, task_id: str, request: TaskUpdateRequest):
    if not chat_session_store.get_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    task = task_store.get_task(task_id)
    if not task or task["session_id"] != session_id:
        raise HTTPException(status_code=404, detail="Task not found")

    action = request.action.lower()
    if action == "resume":
        updated = task_store.resume_task(session_id, task_id)
    elif action == "cancel":
        updated = task_store.cancel_task(task_id)
        if updated:
            task_store.set_active_task(session_id, None)
    elif action == "suspend":
        updated = task_store.suspend_task(task_id)
        if updated:
            task_store.set_active_task(session_id, None)
    else:
        raise HTTPException(status_code=400, detail="action must be resume, cancel, or suspend")

    return updated


@router.patch("/sessions/{session_id}")
async def update_session(session_id: str, request: SessionUpdateRequest):
    session = chat_session_store.update_session(
        session_id,
        title=request.title,
        status=request.status,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str):
    chat_session_store.delete_session(session_id)
    return None
