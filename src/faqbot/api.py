"""HTTP API and embeddable widget.

The API is intentionally tiny: one endpoint to ask a question, one to collect
feedback, one to expose the widget configuration. Sessions are kept in memory,
which is fine for the single-process deployment this project targets. Use one
worker (``uvicorn --workers 1``) or move the session store to Redis if you need
to scale horizontally.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from .engine import Answer, Bot, ChatSession
from .kb import KnowledgeBase, load_kb

_WIDGET_DIR = Path(__file__).parent / "widget"


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session: str = Field(default="", max_length=64)
    page: str = Field(default="", max_length=2000)


class FeedbackRequest(BaseModel):
    session: str = Field(default="", max_length=64)
    qa_id: int = 0
    value: Literal[-1, 1]
    comment: str = Field(default="", max_length=1000)


@dataclass
class _Sessions:
    """Bounded in-memory session store."""

    limit: int = 5000
    data: dict[str, ChatSession] = field(default_factory=dict)
    touched: dict[str, float] = field(default_factory=dict)

    def get(self, key: str) -> ChatSession:
        if not key:
            return ChatSession()
        self.touched[key] = time.monotonic()
        session = self.data.get(key)
        if session is None:
            session = ChatSession()
            self.data[key] = session
            if len(self.data) > self.limit:
                self._evict()
        return session

    def _evict(self) -> None:
        oldest = sorted(self.touched, key=self.touched.get)
        for key in oldest[: max(1, len(oldest) // 10)]:
            self.data.pop(key, None)
            self.touched.pop(key, None)


def _append_jsonl(path: Path | None, payload: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def create_app(
    kb_path: str | Path,
    *,
    unanswered_path: str | Path | None = None,
    feedback_path: str | Path | None = None,
    cors_origins: tuple[str, ...] = ("*",),
    title: str | None = None,
) -> FastAPI:
    kb: KnowledgeBase = load_kb(kb_path)
    bot = Bot(kb)
    sessions = _Sessions()
    unanswered = Path(unanswered_path) if unanswered_path else None
    feedback = Path(feedback_path) if feedback_path else None

    app = FastAPI(
        title=title or f"{kb.settings.bot_name} API",
        description="Offline FAQ matching over a YAML knowledge base.",
        version="0.3.0",
    )
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

    app.state.bot = bot
    app.state.kb = kb

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "qa": len(kb.items), "bot": kb.settings.bot_name}

    @app.get("/api/config")
    def config() -> dict:
        return {
            "enabled": True,
            "botName": kb.settings.bot_name,
            "greeting": kb.settings.greeting,
            "operator": kb.settings.operator_url,
            "operatorLabel": kb.settings.operator_label,
            "quick": [chip.to_dict() for chip in kb.settings.quick],
        }

    @app.get("/api/search")
    def search(q: str = Query(min_length=1, max_length=500), limit: int = 3) -> dict:
        matches = bot.find(q, limit=max(1, min(limit, 20)))
        return {
            "query": q,
            "matches": [
                {
                    "id": match.item.id,
                    "question": match.item.question,
                    "category": match.item.category,
                    "score": match.score,
                }
                for match in matches
            ],
        }

    @app.post("/api/ask")
    def ask(request: AskRequest) -> dict:
        answer: Answer = bot.respond(sessions.get(request.session), request.message)
        if answer.intent == "fallback":
            _append_jsonl(
                unanswered,
                {
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "message": request.message,
                    "session": request.session,
                    "page": request.page,
                    "score": answer.score,
                },
            )
        payload = answer.to_dict()
        payload["session"] = request.session
        return payload

    @app.post("/api/feedback")
    def collect_feedback(request: FeedbackRequest) -> dict:
        _append_jsonl(
            feedback,
            {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **request.model_dump()},
        )
        return {"ok": True}

    @app.get("/widget.js", include_in_schema=False)
    def widget_js() -> Response:
        return Response(
            (_WIDGET_DIR / "widget.js").read_text(encoding="utf-8"),
            media_type="text/javascript; charset=utf-8",
        )

    @app.get("/widget.css", include_in_schema=False)
    def widget_css() -> Response:
        return Response(
            (_WIDGET_DIR / "widget.css").read_text(encoding="utf-8"),
            media_type="text/css; charset=utf-8",
        )

    @app.get("/", include_in_schema=False)
    def demo() -> HTMLResponse:
        html = (_WIDGET_DIR / "demo.html").read_text(encoding="utf-8")
        html = html.replace("{{BOT_NAME}}", kb.settings.bot_name)
        return HTMLResponse(html)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(_WIDGET_DIR / "favicon.svg", media_type="image/svg+xml")

    return app
