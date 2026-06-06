"""TrustFlow Guardian — LangGraph Edition.

FastAPI entrypoint with LangGraph-based orchestration.
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.services.chat_session_store import ChatSessionStore
from backend.routes import router as sessions_router, init as init_sessions
from backend.routes.chat import router as chat_router, init as init_chat

LOG_DIR = Path("/home/ubuntu/workspace/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "trustflow-banking.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=5, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# ─── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="TrustFlow Guardian (LangGraph)", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Initialize services ─────────────────────────────────────────────────────

chat_session_store = ChatSessionStore()

init_sessions(chat_session_store)
init_chat(chat_session_store)

app.include_router(sessions_router)
app.include_router(chat_router)

# ─── Static / frontend ───────────────────────────────────────────────────────

FRONTEND_INDEX_PATH = Path(__file__).resolve().parents[1] / "frontend" / "index.html"
FRONTEND_ROOT = FRONTEND_INDEX_PATH.parent

if FRONTEND_ROOT.exists():
    app.mount("/web_ui/static", StaticFiles(directory=FRONTEND_ROOT), name="web_ui_static")


@app.get("/health")
async def health():
    return {"status": "OK"}


@app.get("/")
async def root():
    return RedirectResponse(url="/web_ui", status_code=307)


@app.get("/web_ui", response_class=HTMLResponse)
async def web_ui():
    if not FRONTEND_INDEX_PATH.exists():
        return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)
    return HTMLResponse(FRONTEND_INDEX_PATH.read_text())


@app.get("/web_ui/")
async def web_ui_slash():
    return RedirectResponse(url="/web_ui", status_code=307)
