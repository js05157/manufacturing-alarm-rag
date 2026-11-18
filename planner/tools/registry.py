"""Tool registration visible to the Agent and API."""
from __future__ import annotations

from collections.abc import Iterable

from planner.tools.base import Tool, ToolResult
from planner.tools.external import HolidayTool, LocationSearchTool, WeatherForecastTool


class ToolRegistry:
    def __init__(self, tools: Iterable[Tool] = ()):
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.spec.name in self._tools:
            raise ValueError(f"Tool 이름이 중복되었습니다: {tool.spec.name}")
        self._tools[tool.spec.name] = tool

    def specs(self) -> list[dict]:
        return [tool.spec.as_dict() for tool in self._tools.values()]

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def invoke(self, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if not tool:
            return ToolResult.failure("TOOL_NOT_FOUND", f"등록되지 않은 Tool입니다: {name}")
        return tool.invoke(**arguments)


def build_tool_registry(*, sessions=None, timeout=15.0, user_agent=None) -> ToolRegistry:
    sessions = sessions or {}
    weather_kwargs = {"session": sessions.get("weather"), "timeout": timeout}
    if user_agent:
        weather_kwargs["user_agent"] = user_agent
    return ToolRegistry(
        [
            LocationSearchTool(session=sessions.get("location"), timeout=timeout),
            WeatherForecastTool(**weather_kwargs),
            HolidayTool(session=sessions.get("holiday"), timeout=timeout),
        ]
    )
