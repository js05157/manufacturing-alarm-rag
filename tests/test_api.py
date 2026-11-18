from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from api import create_app
from config import Settings
from planner.agent import MaintenanceAgent
from planner.storage import PlannerDatabase
from planner.tools.base import COMMON_OUTPUT_SCHEMA, ToolResult, ToolSpec
from planner.tools.registry import ToolRegistry


class NeverCalledTool:
    def __init__(self, name, category="external_api"):
        self.spec = ToolSpec(name, f"{name}이 필요할 때 사용", category, {"type": "object"}, COMMON_OUTPUT_SCHEMA)

    def invoke(self, **kwargs):
        raise AssertionError("인사 요청에서 Tool을 호출하면 안 됩니다.")


def client_for(tmp_path):
    settings = replace(
        Settings(),
        sqlite=tmp_path / "manual.db",
        chroma=tmp_path / "chroma",
        chat_db=tmp_path / "chat.db",
        planner_db=tmp_path / "planner.db",
    )
    tools = [
        NeverCalledTool("search_maintenance_location"),
        NeverCalledTool("get_maintenance_weather"),
        NeverCalledTool("get_public_holidays"),
        NeverCalledTool("search_fr_e800_manual", "local_server_api"),
    ]
    agent = MaintenanceAgent(
        settings=settings,
        registry=ToolRegistry(tools),
        database=PlannerDatabase(settings.planner_db),
        clock=lambda: datetime(2026, 11, 18, 10, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    return TestClient(create_app(agent=agent, settings=settings))


def test_frontend_health_tool_specs_and_agent_log_flow(tmp_path):
    client = client_for(tmp_path)
    page = client.get("/")
    assert page.status_code == 200 and "FR-E800 정비 플래너" in page.text
    health = client.get("/api/v1/health").json()
    assert health == {"status": "ok", "manual_index_ready": False, "vector_index_ready": False}
    tools = client.get("/api/v1/tools").json()["tools"]
    assert len(tools) == 4 and {tool["category"] for tool in tools} == {"external_api", "local_server_api"}

    response = client.post("/api/v1/chat", json={"message": "안녕하세요", "session_id": "room-1"})
    assert response.status_code == 200
    answer = response.json()
    assert answer["status"] == "completed" and answer["conversation_id"] == "room-1"
    detail = client.get(f"/api/v1/logs/{answer['session_id']}").json()
    assert detail["session"]["status"] == "completed"
    assert detail["events"][0]["event_type"] == "stage.started"


def test_plan_crud_overlap_warning_and_log_has_no_update_route(tmp_path):
    client = client_for(tmp_path)
    payload = {
        "title": "E.OC1 점검",
        "alarm_code": "E.OC1",
        "location": "수원 1공장",
        "plan_date": "2026-11-25",
        "start_time": "09:00",
        "end_time": "10:30",
        "notes": "안전 절차 확인",
    }
    first = client.post("/api/v1/plans", json=payload)
    assert first.status_code == 201 and first.json()["overlaps"] == []
    plan_id = first.json()["plan"]["id"]
    second = client.post("/api/v1/plans", json={**payload, "title": "겹치는 점검", "start_time": "10:00"})
    assert second.status_code == 201 and second.json()["overlaps"][0]["id"] == plan_id
    assert len(client.get("/api/v1/plans").json()["plans"]) == 2

    updated = client.patch(
        f"/api/v1/plans/{plan_id}", json={"start_time": "13:00", "end_time": "14:00"}
    )
    assert updated.status_code == 200 and updated.json()["plan"]["start_time"] == "13:00"
    assert client.delete(f"/api/v1/plans/{plan_id}").status_code == 204
    assert client.get(f"/api/v1/plans/{plan_id}").status_code == 404

    run = client.post("/api/v1/chat", json={"message": "안녕하세요"}).json()["session_id"]
    assert client.patch(f"/api/v1/logs/{run}", json={"status": "tampered"}).status_code == 405
    assert client.delete(f"/api/v1/logs/{run}").status_code == 204


def test_invalid_requests_are_safe_and_do_not_echo_payload(tmp_path):
    client = client_for(tmp_path)
    secret = "sk-sensitive-value"
    invalid = client.post("/api/v1/chat", json={"message": "", "api_key": secret})
    assert invalid.status_code == 422
    assert secret not in invalid.text and invalid.json()["detail"] == "요청 형식을 확인해 주세요."
    bad_time = client.post(
        "/api/v1/plans",
        json={
            "title": "잘못된 계획",
            "plan_date": "2026-11-25",
            "start_time": "15:00",
            "end_time": "14:00",
        },
    )
    assert bad_time.status_code == 400 and "종료 시각" in bad_time.json()["detail"]
