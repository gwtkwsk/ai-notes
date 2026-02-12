from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Generator, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.data.repository import Repository
from app.rag.service import RagService


class TagOut(BaseModel):
    id: int
    name: str


class NoteOut(BaseModel):
    id: int
    title: str
    content: str
    is_markdown: bool
    created_at: str
    updated_at: str


class NoteCreate(BaseModel):
    title: str = Field(default="New note")
    content: str = Field(default="")
    is_markdown: bool = Field(default=False)


class NoteUpdate(BaseModel):
    title: str
    content: str
    is_markdown: bool


class NoteTagsUpdate(BaseModel):
    tags: List[str]


class RagAsk(BaseModel):
    question: str


class RagAnswer(BaseModel):
    answer: str
    thinking: str
    sources: List[str]


class ReindexStatus(BaseModel):
    running: bool
    current: int
    total: int
    error: Optional[str]


class _ReindexState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running = False
        self.current = 0
        self.total = 0
        self.error: Optional[str] = None


reindex_state = _ReindexState()


def create_app() -> FastAPI:
    app = FastAPI(title="Disco Notes API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/notes", response_model=list[NoteOut])
    def list_notes(tag_ids: Optional[str] = Query(default=None)) -> list[NoteOut]:
        repo = Repository(_default_db_path())
        try:
            ids = _parse_tag_ids(tag_ids)
            notes = repo.list_notes(ids if ids else None)
            return [NoteOut(**_note_row(note)) for note in notes]
        finally:
            repo.close()

    @app.post("/notes", response_model=NoteOut)
    def create_note(payload: NoteCreate) -> NoteOut:
        repo = Repository(_default_db_path())
        try:
            note_id = repo.create_note(payload.title, payload.content, payload.is_markdown)
            note = repo.get_note(note_id)
            if not note:
                raise HTTPException(status_code=404, detail="Note not found")
            return NoteOut(**_note_row(note))
        finally:
            repo.close()

    @app.get("/notes/{note_id}", response_model=NoteOut)
    def get_note(note_id: int) -> NoteOut:
        repo = Repository(_default_db_path())
        try:
            note = repo.get_note(note_id)
            if not note:
                raise HTTPException(status_code=404, detail="Note not found")
            return NoteOut(**_note_row(note))
        finally:
            repo.close()

    @app.put("/notes/{note_id}", response_model=NoteOut)
    def update_note(note_id: int, payload: NoteUpdate) -> NoteOut:
        repo = Repository(_default_db_path())
        try:
            repo.update_note(note_id, payload.title, payload.content, payload.is_markdown)
            note = repo.get_note(note_id)
            if not note:
                raise HTTPException(status_code=404, detail="Note not found")
            return NoteOut(**_note_row(note))
        finally:
            repo.close()

    @app.delete("/notes/{note_id}")
    def delete_note(note_id: int) -> dict:
        repo = Repository(_default_db_path())
        try:
            repo.delete_note(note_id)
            return {"status": "deleted"}
        finally:
            repo.close()

    @app.get("/tags", response_model=list[TagOut])
    def list_tags() -> list[TagOut]:
        repo = Repository(_default_db_path())
        try:
            tags = repo.list_tags()
            return [TagOut(**tag) for tag in tags]
        finally:
            repo.close()

    @app.get("/notes/{note_id}/tags", response_model=list[TagOut])
    def get_note_tags(note_id: int) -> list[TagOut]:
        repo = Repository(_default_db_path())
        try:
            tags = repo.get_note_tags(note_id)
            return [TagOut(**tag) for tag in tags]
        finally:
            repo.close()

    @app.put("/notes/{note_id}/tags")
    def set_note_tags(note_id: int, payload: NoteTagsUpdate) -> dict:
        repo = Repository(_default_db_path())
        try:
            cleaned = [name.strip() for name in payload.tags if name.strip()]
            repo.set_note_tags(note_id, cleaned)
            return {"status": "ok"}
        finally:
            repo.close()

    @app.post("/rag/ask", response_model=RagAnswer)
    def ask_rag(payload: RagAsk) -> RagAnswer:
        question = payload.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="Question is empty")
        service = RagService(Repository(_default_db_path()))
        try:
            result = service.ask(question)
            answer = str(result.get("answer", ""))
            thinking = str(result.get("thinking", ""))
            sources = result.get("sources", [])
            return RagAnswer(
                answer=answer,
                thinking=thinking,
                sources=[str(src) for src in sources] if isinstance(sources, list) else [],
            )
        finally:
            service.close()

    @app.post("/rag/ask/stream")
    def ask_rag_stream(payload: RagAsk) -> StreamingResponse:
        question = payload.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail="Question is empty")
        service = RagService(Repository(_default_db_path()))

        def event_gen() -> Generator[str, None, None]:
            sources: list[str] = []
            try:
                yield _sse_event("status", {"stage": "send", "label": "Send"})
                for chunk in service.ask_stream(question):
                    if chunk.get("status"):
                        stage, label = _map_status(str(chunk.get("status")))
                        yield _sse_event("status", {"stage": stage, "label": label})
                    thinking_delta = str(chunk.get("thinking_delta", ""))
                    answer_delta = str(chunk.get("answer_delta", ""))
                    if thinking_delta:
                        yield _sse_event("thinking", {"delta": thinking_delta})
                    if answer_delta:
                        yield _sse_event("answer", {"delta": answer_delta})
                    if chunk.get("sources"):
                        sources = [str(src) for src in chunk.get("sources", [])]
                    if chunk.get("done") is True:
                        if sources:
                            yield _sse_event("done", {"sources": sources})
                        else:
                            yield _sse_event("done", {})
                        yield _sse_event("status", {"stage": "done", "label": "Done"})
            except Exception as exc:
                yield _sse_event("error", {"message": str(exc)})
                yield _sse_event("status", {"stage": "error", "label": "Error"})
            finally:
                service.close()

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    @app.post("/rag/reindex")
    def reindex_rag() -> dict:
        _start_reindex()
        return {"status": "started"}

    @app.get("/rag/reindex")
    def reindex_status() -> ReindexStatus:
        with reindex_state.lock:
            return ReindexStatus(
                running=reindex_state.running,
                current=reindex_state.current,
                total=reindex_state.total,
                error=reindex_state.error,
            )

    return app


def _start_reindex() -> None:
    with reindex_state.lock:
        if reindex_state.running:
            return
        reindex_state.running = True
        reindex_state.current = 0
        reindex_state.total = 0
        reindex_state.error = None

    def worker() -> None:
        service = RagService(Repository(_default_db_path()))
        try:
            def progress(cur: int, total: int, _note: dict) -> None:
                with reindex_state.lock:
                    reindex_state.current = cur
                    reindex_state.total = total

            total = service.build_index(progress)
            with reindex_state.lock:
                reindex_state.current = total
                reindex_state.total = total
        except Exception as exc:
            with reindex_state.lock:
                reindex_state.error = str(exc)
        finally:
            with reindex_state.lock:
                reindex_state.running = False
            service.close()

    threading.Thread(target=worker, daemon=True).start()


def _note_row(note: dict) -> dict:
    return {
        "id": int(note.get("id")),
        "title": note.get("title", ""),
        "content": note.get("content", ""),
        "is_markdown": bool(note.get("is_markdown")),
        "created_at": note.get("created_at", ""),
        "updated_at": note.get("updated_at", ""),
    }


def _sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=True)
    return f"event: {event}\ndata: {payload}\n\n"


def _map_status(message: str) -> tuple[str, str]:
    lower = message.lower()
    if "embed" in lower:
        return "embed", "Embed"
    if "search" in lower:
        return "search", "Search"
    if "ollama" in lower or "compose" in lower or "generate" in lower:
        return "compose", "Compose"
    return "compose", "Compose"


def _parse_tag_ids(tag_ids: Optional[str]) -> list[int]:
    if not tag_ids:
        return []
    parts = [item.strip() for item in tag_ids.split(",") if item.strip()]
    ids = []
    for part in parts:
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return ids


def _default_db_path() -> str:
    base_dir = Path.home() / ".disco_notes"
    os.makedirs(base_dir, exist_ok=True)
    return str(base_dir / "notes.db")


app = create_app()
