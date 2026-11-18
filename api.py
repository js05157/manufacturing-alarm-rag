"""FastAPI service for the maintenance planner and its separate web client."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import ROOT, Settings
from planner.agent import MaintenanceAgent


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, min_length=1, max_length=100)


class ChatResponse(BaseModel):
    session_id: str
    conversation_id: str
    status: str
    text: str
    conditions: dict[str, Any]
    memory_used: bool
    tool_plan: list[dict[str, Any]]
    tool_results: dict[str, Any]
    selected_date: str | None = None
    replan_count: int
    exclusion_reasons: list[dict[str, Any]]


class PlanCreate(BaseModel):
    session_id: str | None = Field(default=None, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    alarm_code: str | None = Field(default=None, max_length=30)
    location: str | None = Field(default=None, max_length=200)
    plan_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    notes: str = Field(default="", max_length=2000)


class PlanUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    alarm_code: str | None = Field(default=None, max_length=30)
    location: str | None = Field(default=None, max_length=200)
    plan_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    notes: str | None = Field(default=None, max_length=2000)


def _assert_separate_databases(settings: Settings) -> None:
    paths = {
        "PLANNER_DB_PATH": settings.planner_db.resolve(),
        "SQLITE_PATH": settings.sqlite.resolve(),
        "CHAT_DB_PATH": settings.chat_db.resolve(),
    }
    if len(set(paths.values())) != len(paths):
        raise ValueError("PLANNER_DB_PATH, SQLITE_PATH, CHAT_DB_PATH는 서로 다른 파일이어야 합니다.")


def create_app(*, agent: MaintenanceAgent | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    _assert_separate_databases(settings)
    agent = agent or MaintenanceAgent(settings=settings)
    frontend = ROOT / "frontend"

    app = FastAPI(
        title="FR-E800 정비 플래너 API",
        version="3.0.0",
        description="검증된 FR-E800 RAG와 외부 일정 Tool을 결합한 Agent API",
    )
    app.state.agent = agent
    app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        fields = [".".join(str(part) for part in error["loc"][1:]) for error in exc.errors()]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": "요청 형식을 확인해 주세요.", "fields": fields},
        )

    @app.exception_handler(sqlite3.Error)
    async def database_error(_request: Request, _exc: sqlite3.Error):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "저장소를 처리하지 못했습니다. 서버 로그를 확인해 주세요."},
        )

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(frontend / "index.html")

    @app.get("/api/v1/health", tags=["system"])
    def health():
        return {
            "status": "ok",
            "manual_index_ready": settings.sqlite.is_file(),
            "vector_index_ready": (settings.chroma / "manifest.json").is_file(),
        }

    @app.get("/api/v1/tools", tags=["tools"])
    def tools():
        return {"tools": agent.registry.specs()}

    @app.post("/api/v1/chat", response_model=ChatResponse, tags=["agent"])
    def chat(payload: ChatRequest):
        try:
            return agent.invoke(payload.message, conversation_id=payload.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception as exc:
            # Do not expose request URLs, credentials, tracebacks, or remote payloads.
            raise HTTPException(
                status_code=500,
                detail=f"Agent 실행에 실패했습니다({type(exc).__name__}). 서버 로그를 확인해 주세요.",
            ) from None

    @app.get("/api/v1/plans", tags=["plans"])
    def list_plans():
        return {"plans": agent.plan_store.list()}

    @app.post("/api/v1/plans", status_code=201, tags=["plans"])
    def create_plan(payload: PlanCreate):
        values = payload.model_dump(exclude={"session_id"})
        try:
            return agent.plan_store.create(values, session_id=payload.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.get("/api/v1/plans/{plan_id}", tags=["plans"])
    def get_plan(plan_id: str):
        plan = agent.plan_store.get(plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="계획을 찾을 수 없습니다.")
        return {"plan": plan}

    @app.patch("/api/v1/plans/{plan_id}", tags=["plans"])
    def update_plan(plan_id: str, payload: PlanUpdate):
        try:
            result = agent.plan_store.update(plan_id, payload.model_dump(exclude_unset=True))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        if not result:
            raise HTTPException(status_code=404, detail="계획을 찾을 수 없습니다.")
        return result

    @app.delete("/api/v1/plans/{plan_id}", status_code=204, tags=["plans"])
    def delete_plan(plan_id: str):
        if not agent.plan_store.delete(plan_id):
            raise HTTPException(status_code=404, detail="계획을 찾을 수 없습니다.")

    @app.get("/api/v1/logs", tags=["logs"])
    def list_logs():
        return {"logs": agent.log_store.list_sessions()}

    @app.get("/api/v1/logs/{session_id}", tags=["logs"])
    def get_log(session_id: str):
        detail = agent.log_store.detail(session_id)
        if not detail:
            raise HTTPException(status_code=404, detail="실행 로그를 찾을 수 없습니다.")
        return detail

    @app.delete("/api/v1/logs/{session_id}", status_code=204, tags=["logs"])
    def delete_log(session_id: str):
        if not agent.log_store.delete(session_id):
            raise HTTPException(status_code=404, detail="실행 로그를 찾을 수 없습니다.")

    return app


app = create_app()
