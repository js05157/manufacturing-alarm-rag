from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from config import Settings
from planner.agent import MaintenanceAgent
from planner.events import EventBus, ExecutionEvent, LoggingAgent
from planner.storage import ExecutionLogStore, PlanStore, PlannerDatabase
from planner.tools.base import COMMON_OUTPUT_SCHEMA, ToolResult, ToolSpec
from planner.tools.rag import ManualSearchTool
from planner.tools.registry import ToolRegistry


class StubTool:
    def __init__(self, name, result):
        self.spec = ToolSpec(name, f"{name}이 필요할 때 사용", "test", {}, COMMON_OUTPUT_SCHEMA)
        self.result = result
        self.calls = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def make_agent(tmp_path, tools, *, max_replans=3):
    settings = replace(
        Settings(),
        planner_db=tmp_path / "planner.db",
        planner_max_replans=max_replans,
    )
    return MaintenanceAgent(
        settings=settings,
        registry=ToolRegistry(tools),
        database=PlannerDatabase(settings.planner_db),
        clock=lambda: datetime(2026, 11, 18, 10, tzinfo=ZoneInfo("Asia/Seoul")),
    )


def test_graph_has_explicit_flow_and_greeting_calls_no_tool(tmp_path):
    forbidden = StubTool("search_fr_e800_manual", ToolResult.failure("BAD", "호출되면 안 됨"))
    agent = make_agent(tmp_path, [forbidden])
    graph = agent.graph.get_graph()
    assert {"analyze", "plan", "execute", "judge", "replan", "respond"} <= set(graph.nodes)
    result = agent.invoke("안녕하세요", conversation_id="room-1")
    assert result["status"] == "completed"
    assert result["tool_plan"] == [] and forbidden.calls == []
    detail = agent.log_store.detail(result["session_id"])
    assert [e["stage"] for e in detail["events"] if e["event_type"] == "stage.started"] == [
        "analyze",
        "plan",
        "execute",
        "judge",
        "respond",
    ]


def test_agent_replans_dates_without_recalling_tools_and_keeps_sources(tmp_path):
    manual = StubTool(
        "search_fr_e800_manual",
        ToolResult.success(
            {
                "answer": "E.OC1 매뉴얼 근거\n\n**출처** FR-E800 보수편 · PDF 23쪽",
                "sources": [{"manual": "FR-E800 보수편", "pdf_page": 23, "printed_page": "22"}],
                "validation": {"valid": True},
            }
        ),
    )
    location = StubTool(
        "search_maintenance_location",
        ToolResult.success(
            {
                "candidates": [
                    {
                        "name": "수원시",
                        "admin1": "경기도",
                        "latitude": 37.27,
                        "longitude": 127.03,
                        "timezone": "Asia/Seoul",
                    }
                ]
            }
        ),
    )
    daily = []
    for day, rain in [("2026-11-23", 1.0), ("2026-11-24", 2.0), ("2026-11-25", 0.0)]:
        daily.append(
            {
                "date": day,
                "periods": [
                    {
                        "time": f"{day}T09:00+09:00",
                        "precipitation_mm": rain,
                        "symbol_code": "rain" if rain else "clearsky_day",
                    }
                ],
            }
        )
    weather = StubTool(
        "get_maintenance_weather",
        ToolResult.success({"daily": daily, "source": "MET Norway Locationforecast 2.0"}),
    )
    holiday = StubTool("get_public_holidays", ToolResult.success({"holidays": []}))
    agent = make_agent(tmp_path, [manual, location, weather, holiday])
    result = agent.invoke(
        "E.OC1 점검 근거와 다음 주 수원시, 경기도에서 비 없는 평일 오전 공휴일 제외 정비 계획을 세워줘",
        conversation_id="room-1",
    )
    assert result["selected_date"] == "2026-11-25"
    assert result["replan_count"] == 2
    assert len(manual.calls) == len(location.calls) == len(weather.calls) == len(holiday.calls) == 1
    assert "PDF 23쪽" in result["text"]
    assert "시작·종료 시각은 만들지 않았습니다" in result["text"]
    detail = agent.log_store.detail(result["session_id"])
    replans = [event for event in detail["events"] if event["event_type"] == "agent.replanned"]
    assert len(replans) == 2 and all(event["payload"]["reused_tool_results"] for event in replans)


def test_replan_limit_is_reported_and_memory_updates_only_changed_conditions(tmp_path):
    location = StubTool(
        "search_maintenance_location",
        ToolResult.success(
            {"candidates": [{"name": "수원시", "latitude": 37.27, "longitude": 127.03, "timezone": "Asia/Seoul"}]}
        ),
    )
    weather = StubTool(
        "get_maintenance_weather",
        ToolResult.success(
            {
                "daily": [
                    {
                        "date": f"2026-11-{day}",
                        "periods": [
                            {"time": f"2026-11-{day}T09:00+09:00", "precipitation_mm": 1.0, "symbol_code": "rain"}
                        ],
                    }
                    for day in range(23, 28)
                ]
            }
        ),
    )
    holiday = StubTool("get_public_holidays", ToolResult.success({"holidays": []}))
    agent = make_agent(tmp_path, [location, weather, holiday], max_replans=1)
    first = agent.invoke(
        "다음 주 수원시, 경기도에서 비 없는 평일 오전 공휴일 제외 정비 계획",
        conversation_id="memory-room",
    )
    assert first["status"] == "replan_limit" and first["replan_count"] == 1
    second = agent.invoke("같은 조건에서 다시 계획해줘", conversation_id="memory-room")
    assert second["memory_used"] is True
    assert second["conditions"]["location"] == "수원시, 경기도"
    assert second["conditions"]["start_date"] == "2026-11-23"


def test_unavailable_required_constraint_never_becomes_a_schedule(tmp_path):
    location = StubTool(
        "search_maintenance_location",
        ToolResult.success(
            {"candidates": [{"name": "수원시", "latitude": 37.27, "longitude": 127.03, "timezone": "Asia/Seoul"}]}
        ),
    )
    weather = StubTool("get_maintenance_weather", ToolResult.failure("TIMEOUT", "날씨 API 시간 초과", retryable=True))
    agent = make_agent(tmp_path, [location, weather])
    result = agent.invoke(
        "2026-11-25 수원시, 경기도에서 비 없는 오전 정비 계획",
        conversation_id="failure-room",
    )
    assert result["status"] == "constraint_unavailable"
    assert result["selected_date"] is None and result["replan_count"] == 0
    assert "임의로 채우지 않고" in result["text"]


def test_manual_rag_tool_returns_exact_page_sources_and_no_index_failure():
    answer = {
        "status": "evidence",
        "text": "원문 답변",
        "evidence_ids": ["record:1:action:1"],
        "validation": {"valid": True},
        "retrieval": {
            "records": [
                {
                    "notes": [],
                    "check_points": [],
                    "actions": [
                        {
                            "text": "조치",
                            "evidence": [
                                {"source_pdf": "FR-E800 보수편", "pdf_page": 23, "printed_page": "22"}
                            ],
                        }
                    ],
                }
            ]
        },
    }
    service = SimpleNamespace(answer=lambda *args, **kwargs: answer)
    result = ManualSearchTool(service=service).invoke(question="E.OC1 대처")
    assert result.ok and result.data["sources"] == [
        {"manual": "FR-E800 보수편", "pdf_page": 23, "printed_page": "22"}
    ]

    class Missing:
        def answer(self, *args, **kwargs):
            raise FileNotFoundError

    missing = ManualSearchTool(service=Missing()).invoke(question="E.OC1")
    assert missing.error.code == "NO_INDEX"


def test_plan_crud_allows_overlap_but_returns_warning(tmp_path):
    store = PlanStore(PlannerDatabase(tmp_path / "planner.db"))
    first = store.create(
        {"title": "E.OC1 점검", "plan_date": "2026-11-25", "start_time": "09:00", "end_time": "10:30"}
    )
    second = store.create(
        {"title": "E.THT 점검", "plan_date": "2026-11-25", "start_time": "10:00", "end_time": "11:00"}
    )
    assert second["plan"]["id"] and [item["id"] for item in second["overlaps"]] == [first["plan"]["id"]]
    updated = store.update(second["plan"]["id"], {"start_time": "11:00", "end_time": "12:00"})
    assert updated["overlaps"] == [] and store.get(second["plan"]["id"])["start_time"] == "11:00"
    assert store.delete(first["plan"]["id"]) and store.get(first["plan"]["id"]) is None


def test_logging_agent_is_immutable_and_subscriber_failure_does_not_stop_publish(tmp_path):
    database = PlannerDatabase(tmp_path / "planner.db")
    store = ExecutionLogStore(database)
    store.start_session("run", "request")
    bus = EventBus()
    bus.subscribe(lambda event: (_ for _ in ()).throw(RuntimeError("logging down")))
    bus.subscribe(LoggingAgent(store))
    bus.publish(ExecutionEvent("run", "stage.started", "analyze"))
    assert len(bus.delivery_failures) == 1
    assert store.detail("run")["events"][0]["event_type"] == "stage.started"
    assert not hasattr(store, "update")
    assert store.delete("run") and store.detail("run") is None
