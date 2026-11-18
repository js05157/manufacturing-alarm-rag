"""LangGraph maintenance planner with explicit Tool and replan boundaries."""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta
from time import perf_counter
from typing import Any, TypedDict
from uuid import uuid4
from zoneinfo import ZoneInfo

from langgraph.graph import END, START, StateGraph

from config import Settings
from planner.analysis import analyze_request, merge_memory
from planner.events import EventBus, ExecutionEvent, LoggingAgent
from planner.storage import ExecutionLogStore, MemoryStore, PlannerDatabase, PlanStore
from planner.tools.base import ToolResult
from planner.tools.registry import ToolRegistry, build_tool_registry


class AgentState(TypedDict, total=False):
    session_id: str
    conversation_id: str
    request: str
    analysis: dict[str, Any]
    memory_used: bool
    tool_plan: list[dict[str, Any]]
    tool_results: dict[str, dict[str, Any]]
    candidate_dates: list[str]
    candidate_index: int
    exclusion_reasons: list[dict[str, str]]
    replan_count: int
    needs_replan: bool
    selected_date: str | None
    clarification: str
    status: str
    response: dict[str, Any]


class MaintenanceAgent:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        registry: ToolRegistry | None = None,
        database: PlannerDatabase | None = None,
        event_bus: EventBus | None = None,
        clock=None,
    ):
        self.settings = settings or Settings()
        self.database = database or PlannerDatabase(self.settings.planner_db)
        self.plan_store = PlanStore(self.database)
        self.log_store = ExecutionLogStore(self.database)
        self.memory_store = MemoryStore(self.database)
        self.registry = registry or build_tool_registry(
            timeout=self.settings.planner_api_timeout,
            user_agent=self.settings.planner_user_agent,
            include_rag=True,
            settings=self.settings,
        )
        self.event_bus = event_bus or EventBus()
        self.logging_agent = LoggingAgent(self.log_store)
        self.event_bus.subscribe(self.logging_agent)
        self.clock = clock or (lambda: datetime.now(ZoneInfo("Asia/Seoul")))
        self.graph = self._build_graph()

    def _event(
        self,
        state: AgentState,
        event_type: str,
        stage: str,
        payload: dict[str, Any] | None = None,
        *,
        tool_name: str | None = None,
        duration_ms: float | None = None,
    ) -> None:
        self.event_bus.publish(
            ExecutionEvent(
                session_id=state["session_id"],
                event_type=event_type,
                stage=stage,
                payload=payload or {},
                tool_name=tool_name,
                duration_ms=duration_ms,
            )
        )

    def _analyze(self, state: AgentState) -> dict[str, Any]:
        self._event(state, "stage.started", "analyze")
        analysis = analyze_request(state["request"], now=self.clock())
        previous = self.memory_store.get(state["conversation_id"])
        conditions, memory_used = merge_memory(previous, analysis["conditions"], state["request"])
        analysis["conditions"] = conditions
        if analysis["intent"] == "maintenance_plan":
            analysis["missing"] = []
            if not conditions.get("start_date"):
                analysis["missing"].append("date")
            if conditions.get("no_precipitation") and not conditions.get("location"):
                analysis["missing"].append("location")
        self._event(
            state,
            "agent.decision",
            "analyze",
            {"intent": analysis["intent"], "reason": analysis["reason"], "source": "rule"},
        )
        self._event(state, "stage.completed", "analyze", {"memory_used": memory_used})
        return {"analysis": analysis, "memory_used": memory_used}

    def _plan(self, state: AgentState) -> dict[str, Any]:
        self._event(state, "stage.started", "plan")
        analysis, request = state["analysis"], state["request"]
        intent, conditions = analysis["intent"], analysis["conditions"]
        tasks = []
        if intent in {"manual_search", "maintenance_plan"} and (
            conditions.get("alarm_codes") or re.search(r"알람|원인|점검|대처|조치|증상|인버터|모터", request)
        ):
            tasks.append({"tool": "search_fr_e800_manual", "arguments": {"question": request}})
        if intent == "maintenance_plan" and conditions.get("no_precipitation") and conditions.get("location"):
            tasks.extend(
                [
                    {"tool": "search_maintenance_location", "arguments": {"query": conditions["location"]}},
                    {"tool": "get_maintenance_weather", "arguments_from": "search_maintenance_location"},
                ]
            )
        if intent == "maintenance_plan" and (conditions.get("weekdays_only") or conditions.get("exclude_holidays")):
            year = int((conditions.get("start_date") or self.clock().date().isoformat())[:4])
            tasks.append(
                {
                    "tool": "get_public_holidays",
                    "arguments": {
                        "year": year,
                        "country_code": "KR",
                        "start_date": conditions.get("start_date"),
                        "end_date": conditions.get("end_date"),
                    },
                }
            )
        self._event(
            state,
            "agent.decision",
            "plan",
            {"tools": [task["tool"] for task in tasks], "reason": "명시 조건에 필요한 Tool만 선택", "source": "rule"},
        )
        self._event(state, "stage.completed", "plan", {"task_count": len(tasks)})
        return {"tool_plan": tasks, "tool_results": {}}

    @staticmethod
    def _select_location(location_result: dict[str, Any], query: str) -> dict[str, Any] | None:
        if not location_result.get("ok"):
            return None
        candidates = location_result.get("data", {}).get("candidates", [])
        if len(candidates) == 1:
            return candidates[0]
        compact = re.sub(r"\s+", "", query).casefold()
        qualified = []
        for candidate in candidates:
            name = re.sub(r"\s+", "", str(candidate.get("name", ""))).casefold()
            admin1 = re.sub(r"\s+", "", str(candidate.get("admin1", ""))).casefold()
            if name and admin1 and name in compact and admin1 in compact:
                qualified.append(candidate)
        return qualified[0] if len(qualified) == 1 else None

    def _invoke_tool(self, state: AgentState, name: str, arguments: dict[str, Any]) -> ToolResult:
        self._event(state, "tool.requested", "execute", {"arguments": arguments}, tool_name=name)
        started = perf_counter()
        result = self.registry.invoke(name, arguments)
        elapsed = (perf_counter() - started) * 1000
        self._event(
            state,
            "tool.completed",
            "execute",
            {"ok": result.ok, "error_code": result.error.code if result.error else None},
            tool_name=name,
            duration_ms=round(elapsed, 3),
        )
        return result

    def _execute(self, state: AgentState) -> dict[str, Any]:
        self._event(state, "stage.started", "execute")
        results = dict(state.get("tool_results", {}))
        conditions = state["analysis"]["conditions"]
        for task in state.get("tool_plan", []):
            name = task["tool"]
            arguments = dict(task.get("arguments", {}))
            if name == "get_maintenance_weather":
                selected = self._select_location(
                    results.get("search_maintenance_location", {}), conditions.get("location", "")
                )
                if not selected:
                    results[name] = ToolResult.failure(
                        "AMBIGUOUS_LOCATION", "지역 후보가 여러 개이므로 시·도까지 지정해 주세요."
                    ).as_dict()
                    continue
                arguments = {
                    "latitude": selected["latitude"],
                    "longitude": selected["longitude"],
                    "timezone": selected.get("timezone") or "Asia/Seoul",
                }
                results["selected_location"] = selected
            # Remove absent optional fields instead of sending fabricated defaults.
            arguments = {key: value for key, value in arguments.items() if value is not None}
            results[name] = self._invoke_tool(state, name, arguments).as_dict()
        self._event(state, "stage.completed", "execute", {"completed_tools": list(results)})
        return {"tool_results": results}

    @staticmethod
    def _dates(start: str, end: str) -> list[str]:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        return [(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)]

    @staticmethod
    def _forecast_allows(day: str, weather: dict[str, Any], period: str | None) -> tuple[bool, str]:
        if not weather.get("ok"):
            return False, weather.get("error", {}).get("message", "날씨 예보를 확인하지 못했습니다.")
        daily = next((item for item in weather["data"].get("daily", []) if item.get("date") == day), None)
        if not daily:
            return False, "요청 날짜의 예보가 아직 제공되지 않았습니다."
        hours = range(9, 13) if period == "morning" else range(13, 18) if period == "afternoon" else range(9, 18)
        relevant = [
            item
            for item in daily.get("periods", [])
            if datetime.fromisoformat(item["time"]).hour in hours
        ]
        if not relevant:
            return False, "선호 시간대의 예보 값이 없습니다."
        if any(item.get("precipitation_mm") is None for item in relevant):
            return False, "강수량을 확인할 수 없는 시간대가 있습니다."
        rainy = any(
            item.get("precipitation_mm", 0) > 0
            or any(word in str(item.get("symbol_code", "")) for word in ("rain", "sleet", "snow"))
            for item in relevant
        )
        return (not rainy, "강수 예보가 있습니다." if rainy else "")

    def _judge(self, state: AgentState) -> dict[str, Any]:
        self._event(state, "stage.started", "judge")
        analysis, results = state["analysis"], state.get("tool_results", {})
        if analysis["intent"] != "maintenance_plan":
            self._event(state, "stage.completed", "judge", {"constraint_check": "not_required"})
            return {"needs_replan": False, "status": "completed"}
        if analysis.get("missing"):
            labels = {"date": "날짜 또는 기간", "location": "시·도까지 포함한 지역"}
            clarification = ", ".join(labels[item] for item in analysis["missing"]) + "을(를) 알려 주세요."
            self._event(state, "stage.completed", "judge", {"constraint_check": "missing"})
            return {"needs_replan": False, "status": "clarification", "clarification": clarification}

        conditions = analysis["conditions"]
        dates = state.get("candidate_dates") or self._dates(conditions["start_date"], conditions["end_date"])
        if conditions.get("weekdays_only"):
            dates = [day for day in dates if date.fromisoformat(day).weekday() < 5]
        holidays = set()
        holiday_result = results.get("get_public_holidays", {})
        if holiday_result.get("ok"):
            holidays = {item["date"] for item in holiday_result["data"].get("holidays", [])}
        if conditions.get("exclude_holidays"):
            dates = [day for day in dates if day not in holidays]

        index = state.get("candidate_index", 0)
        exclusions = list(state.get("exclusion_reasons", []))
        if not dates or index >= len(dates):
            self._event(state, "stage.completed", "judge", {"constraint_check": "no_candidate"})
            return {
                "candidate_dates": dates,
                "needs_replan": False,
                "selected_date": None,
                "status": "no_candidate",
                "exclusion_reasons": exclusions,
            }
        candidate = dates[index]
        allowed, reason = True, ""
        if conditions.get("no_precipitation"):
            allowed, reason = self._forecast_allows(
                candidate, results.get("get_maintenance_weather", {}), conditions.get("preferred_period")
            )
        if allowed:
            self._event(
                state,
                "agent.decision",
                "judge",
                {"candidate_date": candidate, "satisfied": True, "source": "rule"},
            )
            self._event(state, "stage.completed", "judge", {"constraint_check": "satisfied"})
            return {
                "candidate_dates": dates,
                "needs_replan": False,
                "selected_date": candidate,
                "status": "completed",
                "exclusion_reasons": exclusions,
            }
        exclusions.append({"date": candidate, "reason": reason})
        can_replan = index + 1 < len(dates) and state.get("replan_count", 0) < self.settings.planner_max_replans
        self._event(
            state,
            "agent.decision",
            "judge",
            {"candidate_date": candidate, "satisfied": False, "reason": reason, "replan": can_replan, "source": "rule"},
        )
        self._event(state, "stage.completed", "judge", {"constraint_check": "failed"})
        return {
            "candidate_dates": dates,
            "needs_replan": can_replan,
            "selected_date": None,
            "status": "replanning" if can_replan else "replan_limit",
            "exclusion_reasons": exclusions,
        }

    def _replan(self, state: AgentState) -> dict[str, Any]:
        count = state.get("replan_count", 0) + 1
        index = state.get("candidate_index", 0) + 1
        self._event(
            state,
            "agent.replanned",
            "replan",
            {"replan_count": count, "candidate_index": index, "reused_tool_results": True},
        )
        return {"replan_count": count, "candidate_index": index, "needs_replan": False}

    def _respond(self, state: AgentState) -> dict[str, Any]:
        self._event(state, "stage.started", "respond")
        intent = state["analysis"]["intent"]
        results = state.get("tool_results", {})
        parts = []
        status = state.get("status", "completed")
        if intent == "greeting":
            parts.append("안녕하세요. FR-E800 매뉴얼 근거 조회와 조건 기반 정비 일정 계획을 도와드립니다.")
        elif intent == "usage":
            parts.append("알람 코드·증상과 날짜, 지역, 평일·공휴일·강수 조건을 함께 알려 주세요.")
        elif intent == "out_of_scope":
            parts.append("FR-E800 알람 근거 조회와 정비 일정 계획 범위의 요청을 입력해 주세요.")
        if state.get("clarification"):
            parts.append(state["clarification"])
        manual = results.get("search_fr_e800_manual")
        if manual:
            if manual.get("ok"):
                parts.append(manual["data"]["answer"])
            else:
                parts.append(f"매뉴얼 근거 검색 실패: {manual['error']['message']} ({manual['error']['code']})")
                status = "partial" if intent == "maintenance_plan" else "failed"
        selected_date = state.get("selected_date")
        if intent == "maintenance_plan" and selected_date:
            period = state["analysis"]["conditions"].get("preferred_period")
            label = "오전" if period == "morning" else "오후" if period == "afternoon" else "업무 시간"
            parts.append(f"일정 조건을 만족하는 첫 후보는 {selected_date} {label}입니다.")
            if state["analysis"]["conditions"].get("duration_minutes") is None:
                parts.append("작업 소요 시간이 입력되지 않아 시작·종료 시각은 만들지 않았습니다. 저장 전에 소요 시간을 지정해 주세요.")
        elif intent == "maintenance_plan" and status in {"no_candidate", "replan_limit"}:
            parts.append(
                f"조건을 만족하는 날짜를 확정하지 못했습니다. 재계획 {state.get('replan_count', 0)}회 후 중단했습니다."
            )
        if results.get("get_maintenance_weather", {}).get("ok"):
            parts.append("날씨 정보: MET Norway Locationforecast 2.0 (예보는 정비 안전성이나 고장 원인을 판단하지 않습니다.)")
        if results.get("get_public_holidays", {}).get("ok"):
            parts.append("공휴일 정보: Nager.Date Community REST API v4")
        response = {
            "session_id": state["session_id"],
            "conversation_id": state["conversation_id"],
            "status": status,
            "text": "\n\n".join(parts),
            "conditions": state["analysis"]["conditions"],
            "memory_used": state.get("memory_used", False),
            "tool_plan": state.get("tool_plan", []),
            "tool_results": results,
            "selected_date": selected_date,
            "replan_count": state.get("replan_count", 0),
            "exclusion_reasons": state.get("exclusion_reasons", []),
        }
        if intent not in {"greeting", "out_of_scope"}:
            self.memory_store.put(state["conversation_id"], state["analysis"]["conditions"])
        self._event(state, "stage.completed", "respond", {"status": status})
        return {"response": response}

    @staticmethod
    def _after_judge(state: AgentState) -> str:
        return "replan" if state.get("needs_replan") else "respond"

    def _build_graph(self):
        graph = StateGraph(AgentState)
        graph.add_node("analyze", self._analyze)
        graph.add_node("plan", self._plan)
        graph.add_node("execute", self._execute)
        graph.add_node("judge", self._judge)
        graph.add_node("replan", self._replan)
        graph.add_node("respond", self._respond)
        graph.add_edge(START, "analyze")
        graph.add_edge("analyze", "plan")
        graph.add_edge("plan", "execute")
        graph.add_edge("execute", "judge")
        graph.add_conditional_edges("judge", self._after_judge, {"replan": "replan", "respond": "respond"})
        graph.add_edge("replan", "judge")
        graph.add_edge("respond", END)
        return graph.compile()

    def invoke(self, request: str, *, conversation_id: str | None = None) -> dict[str, Any]:
        if not isinstance(request, str) or not request.strip():
            raise ValueError("요청 내용을 입력해 주세요.")
        run_id = uuid4().hex
        conversation_id = conversation_id or uuid4().hex
        logging_started = True
        try:
            self.log_store.start_session(run_id, request)
        except (OSError, sqlite3.Error, ValueError):
            logging_started = False
        try:
            final = self.graph.invoke(
                {
                    "session_id": run_id,
                    "conversation_id": conversation_id,
                    "request": request,
                    "candidate_index": 0,
                    "replan_count": 0,
                    "exclusion_reasons": [],
                }
            )
            response = final["response"]
            if logging_started:
                self.log_store.finish_session(run_id, response["status"])
            return response
        except Exception:
            if logging_started:
                self.log_store.finish_session(run_id, "failed")
            raise
