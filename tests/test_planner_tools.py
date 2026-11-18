from __future__ import annotations

import requests

from planner.tools.external import HolidayTool, LocationSearchTool, WeatherForecastTool
from planner.tools.registry import ToolRegistry, build_tool_registry


class Response:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, payload=None, failure=None):
        self.payload = payload
        self.failure = failure
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.failure:
            raise self.failure
        return Response(self.payload)


def test_registry_exposes_three_external_tools_and_common_contract():
    registry = build_tool_registry(
        sessions={"location": Session({"results": []}), "weather": Session({}), "holiday": Session([])}
    )
    assert registry.names() == (
        "search_maintenance_location",
        "get_maintenance_weather",
        "get_public_holidays",
    )
    assert all(spec["category"] == "external_api" for spec in registry.specs())
    assert all("언제" not in spec["description"] or spec["description"] for spec in registry.specs())
    assert registry.invoke("missing", {}).as_dict() == {
        "ok": False,
        "error": {"code": "TOOL_NOT_FOUND", "message": "등록되지 않은 Tool입니다: missing", "retryable": False},
    }


def test_location_candidates_preserve_ambiguity_and_coordinates():
    session = Session(
        {
            "results": [
                {
                    "id": 1,
                    "name": "수원시",
                    "latitude": 37.27,
                    "longitude": 127.03,
                    "country_code": "KR",
                    "country": "대한민국",
                    "admin1": "경기도",
                    "admin2": "수원시",
                    "timezone": "Asia/Seoul",
                    "population": 123,
                },
                {"id": 2, "name": "수원", "latitude": 35.35, "longitude": 126.53},
            ]
        }
    )
    result = LocationSearchTool(session=session).invoke(query="Suwon")
    assert result.ok and result.data["ambiguous"] is True
    assert result.data["candidates"][0]["admin1"] == "경기도"
    assert result.data["candidates"][0]["latitude"] == 37.27
    assert session.calls[0][1]["params"]["countryCode"] == "KR"


def test_location_no_result_and_invalid_input_are_structured_failures():
    tool = LocationSearchTool(session=Session({"results": []}))
    assert tool.invoke(query="x").error.code == "INVALID_INPUT"
    assert tool.invoke(query="없는곳").error.code == "NO_RESULT"


def test_weather_converts_utc_and_keeps_forecast_provenance():
    session = Session(
        {
            "properties": {
                "meta": {"updated_at": "2026-11-18T01:00:00Z", "units": {"air_temperature": "celsius"}},
                "timeseries": [
                    {
                        "time": "2026-11-18T04:00:00Z",
                        "data": {
                            "instant": {"details": {"air_temperature": 11.2, "wind_speed": 2.3}},
                            "next_1_hours": {
                                "details": {"precipitation_amount": 0.0},
                                "summary": {"symbol_code": "clearsky_day"},
                            },
                        },
                    }
                ],
            }
        }
    )
    result = WeatherForecastTool(session=session, user_agent="test/1 contact.example").invoke(
        latitude=37.27, longitude=127.03
    )
    assert result.ok
    period = result.data["daily"][0]["periods"][0]
    assert period["time"] == "2026-11-18T13:00+09:00"
    assert period["precipitation_mm"] == 0.0
    assert result.data["updated_at"] == "2026-11-18T01:00:00Z"
    assert session.calls[0][1]["headers"]["User-Agent"] == "test/1 contact.example"
    assert session.calls[0][1]["params"] == {"lat": 37.27, "lon": 127.03}


def test_holidays_filter_date_range_without_fabricating_names():
    session = Session(
        [
            {"date": "2026-01-01", "name": "New Year's Day", "nationalHoliday": True, "holidayTypes": ["Public"]},
            {"date": "2026-03-01", "name": "Independence Movement Day", "nationalHoliday": True, "holidayTypes": ["Public"]},
        ]
    )
    result = HolidayTool(session=session).invoke(
        year=2026, start_date="2026-02-01", end_date="2026-03-31"
    )
    assert result.ok and result.data["holidays"] == [
        {
            "date": "2026-03-01",
            "name": "Independence Movement Day",
            "national_holiday": True,
            "subdivision_codes": None,
            "holiday_types": ["Public"],
        }
    ]
    assert "/api/v4/Holidays/KR/2026" in session.calls[0][0]


def test_network_failures_never_escape_tool_boundary():
    registry = ToolRegistry(
        [
            LocationSearchTool(session=Session(failure=requests.Timeout("secret"))),
            WeatherForecastTool(session=Session(failure=requests.ConnectionError("secret"))),
            HolidayTool(session=Session(failure=requests.RequestException("secret"))),
        ]
    )
    results = [
        registry.invoke("search_maintenance_location", {"query": "Suwon"}),
        registry.invoke("get_maintenance_weather", {"latitude": 37, "longitude": 127}),
        registry.invoke("get_public_holidays", {"year": 2026}),
    ]
    assert [result.error.code for result in results] == ["TIMEOUT", "CONNECTION_ERROR", "REQUEST_ERROR"]
    assert all("secret" not in result.error.message for result in results)
