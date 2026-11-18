"""Execution events and a logger subscriber that never controls the Agent."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass(frozen=True)
class ExecutionEvent:
    session_id: str
    event_type: str
    stage: str
    payload: dict[str, Any] = field(default_factory=dict)
    tool_name: str | None = None
    duration_ms: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    """Synchronous publisher; subscriber failures are isolated and observable."""

    def __init__(self):
        self._subscribers: list[Callable[[ExecutionEvent], None]] = []
        self.delivery_failures: list[dict[str, str]] = []

    def subscribe(self, subscriber: Callable[[ExecutionEvent], None]) -> None:
        self._subscribers.append(subscriber)

    def publish(self, event: ExecutionEvent) -> None:
        for subscriber in tuple(self._subscribers):
            try:
                subscriber(event)
            except Exception as exc:  # Logging must not stop the main Agent.
                self.delivery_failures.append(
                    {"subscriber": type(subscriber).__name__, "error_type": type(exc).__name__}
                )


class LoggingAgent:
    """Stores original events without LLM transformation."""

    def __init__(self, log_store):
        self.log_store = log_store

    def __call__(self, event: ExecutionEvent) -> None:
        self.log_store.append_event(event)
