"""External APIs used only for user-supplied scheduling constraints.

These tools never infer an alarm cause or connect a manual check item to a
schedule. FR-E800 facts remain the responsibility of the local RAG tool.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from planner.tools.base import COMMON_OUTPUT_SCHEMA, ToolResult, ToolSpec

DEFAULT_TIMEOUT = 15.0
DEFAULT_USER_AGENT = "manufacturing-alarm-rag/3.0 github.com/js05157/manufacturing-alarm-rag"


def _request_json(session, url: str, *, params=None, headers=None, timeout=DEFAULT_TIMEOUT):
    try:
        response = session.get(
            url,
            params=params,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
        )
        if response.status_code >= 400:
            return None, ToolResult.failure(
                "HTTP_ERROR",
                f"외부 API가 HTTP {response.status_code}로 응답했습니다.",
                retryable=response.status_code in {429, 500, 502, 503, 504},
            )
        try:
            return response.json(), None
        except (TypeError, ValueError):
            return None, ToolResult.failure("INVALID_RESPONSE", "외부 API 응답이 JSON 형식이 아닙니다.")
    except requests.Timeout:
        return None, ToolResult.failure("TIMEOUT", "외부 API 응답 시간이 초과되었습니다.", retryable=True)
    except requests.ConnectionError:
        return None, ToolResult.failure("CONNECTION_ERROR", "외부 API에 연결할 수 없습니다.", retryable=True)
    except requests.RequestException:
        return None, ToolResult.failure("REQUEST_ERROR", "외부 API 요청을 처리하지 못했습니다.", retryable=True)


class LocationSearchTool:
    spec = ToolSpec(
        name="search_maintenance_location",
        description="사용자가 정비 지역 이름을 말했지만 좌표가 없을 때 후보 위치와 좌표를 확인한다.",
        category="external_api",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "minLength": 2},
                "country_code": {"type": "string", "default": "KR"},
                "count": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
        },
        output_schema=COMMON_OUTPUT_SCHEMA,
    )
    endpoint = "https://geocoding-api.open-meteo.com/v1/search"

    def __init__(self, session=None, timeout=DEFAULT_TIMEOUT):
        self.session = session or requests.Session()
        self.timeout = timeout

    def invoke(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        country_code = str(kwargs.get("country_code", "KR")).strip().upper()
        try:
            count = int(kwargs.get("count", 5))
        except (TypeError, ValueError):
            return ToolResult.failure("INVALID_INPUT", "count는 1부터 10까지의 정수여야 합니다.")
        if len(query) < 2 or not (1 <= count <= 10) or len(country_code) != 2:
            return ToolResult.failure("INVALID_INPUT", "지역명, 국가 코드 또는 후보 수가 올바르지 않습니다.")

        body, error = _request_json(
            self.session,
            self.endpoint,
            params={"name": query, "count": count, "language": "ko", "countryCode": country_code},
            timeout=self.timeout,
        )
        if error:
            return error
        if not isinstance(body, dict) or not isinstance(body.get("results", []), list):
            return ToolResult.failure("INVALID_RESPONSE", "위치 API 응답 구조를 확인할 수 없습니다.")
        candidates = []
        for item in body.get("results", []):
            if not isinstance(item, dict) or "latitude" not in item or "longitude" not in item:
                continue
            candidates.append(
                {
                    "location_id": item.get("id"),
                    "name": item.get("name"),
                    "admin1": item.get("admin1"),
                    "admin2": item.get("admin2"),
                    "country": item.get("country"),
                    "country_code": item.get("country_code"),
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "elevation_m": item.get("elevation"),
                    "timezone": item.get("timezone"),
                    "population": item.get("population"),
                }
            )
        if not candidates:
            return ToolResult.failure("NO_RESULT", "입력한 지역의 위치 후보를 찾지 못했습니다.")
        return ToolResult.success(
            {
                "query": query,
                "candidates": candidates,
                "ambiguous": len(candidates) > 1,
                "source": "Open-Meteo Geocoding API / GeoNames",
                "source_url": "https://open-meteo.com/en/docs/geocoding-api",
            }
        )


class WeatherForecastTool:
    spec = ToolSpec(
        name="get_maintenance_weather",
        description="사용자가 날씨 조건을 지정한 정비 일정을 요청했을 때 해당 좌표의 예보를 확인한다.",
        category="external_api",
        input_schema={
            "type": "object",
            "required": ["latitude", "longitude"],
            "properties": {
                "latitude": {"type": "number", "minimum": -90, "maximum": 90},
                "longitude": {"type": "number", "minimum": -180, "maximum": 180},
                "timezone": {"type": "string", "default": "Asia/Seoul"},
            },
        },
        output_schema=COMMON_OUTPUT_SCHEMA,
    )
    endpoint = "https://api.met.no/weatherapi/locationforecast/2.0/compact"

    def __init__(self, session=None, timeout=DEFAULT_TIMEOUT, user_agent=DEFAULT_USER_AGENT):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.user_agent = user_agent

    def invoke(self, **kwargs: Any) -> ToolResult:
        try:
            latitude = float(kwargs["latitude"])
            longitude = float(kwargs["longitude"])
        except (KeyError, TypeError, ValueError):
            return ToolResult.failure("INVALID_INPUT", "위도와 경도를 숫자로 입력해야 합니다.")
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            return ToolResult.failure("INVALID_INPUT", "위도 또는 경도의 범위를 벗어났습니다.")
        timezone_name = str(kwargs.get("timezone", "Asia/Seoul"))
        try:
            local_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return ToolResult.failure("INVALID_INPUT", "지원되는 IANA 시간대를 입력해야 합니다.")

        body, error = _request_json(
            self.session,
            self.endpoint,
            params={"lat": round(latitude, 4), "lon": round(longitude, 4)},
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout,
        )
        if error:
            return error
        try:
            properties = body["properties"]
            timeseries = properties["timeseries"]
            units = properties["meta"]["units"]
        except (KeyError, TypeError):
            return ToolResult.failure("INVALID_RESPONSE", "날씨 API 응답 구조를 확인할 수 없습니다.")
        if not isinstance(timeseries, list) or not timeseries:
            return ToolResult.failure("NO_FORECAST", "해당 위치의 예보를 찾지 못했습니다.")

        daily: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for step in timeseries:
            try:
                instant = datetime.fromisoformat(step["time"].replace("Z", "+00:00")).astimezone(local_timezone)
                data = step["data"]
                details = data.get("instant", {}).get("details", {})
                period = data.get("next_1_hours") or data.get("next_6_hours") or data.get("next_12_hours") or {}
                period_details = period.get("details", {})
                daily[instant.date().isoformat()].append(
                    {
                        "time": instant.isoformat(timespec="minutes"),
                        "temperature_c": details.get("air_temperature"),
                        "wind_speed_mps": details.get("wind_speed"),
                        "precipitation_mm": period_details.get("precipitation_amount"),
                        "precipitation_period_hours": 1 if data.get("next_1_hours") else 6 if data.get("next_6_hours") else 12,
                        "symbol_code": period.get("summary", {}).get("symbol_code"),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        if not daily:
            return ToolResult.failure("INVALID_RESPONSE", "예보 시계열에서 유효한 값을 찾지 못했습니다.")
        return ToolResult.success(
            {
                "latitude": latitude,
                "longitude": longitude,
                "timezone": timezone_name,
                "updated_at": properties.get("meta", {}).get("updated_at"),
                "units": units,
                "daily": [{"date": day, "periods": periods} for day, periods in sorted(daily.items())],
                "source": "MET Norway Locationforecast 2.0",
                "source_url": "https://api.met.no/weatherapi/locationforecast/2.0/documentation",
            }
        )


class HolidayTool:
    spec = ToolSpec(
        name="get_public_holidays",
        description="사용자가 평일이나 공휴일 제외 조건을 말했을 때 국가별 공휴일을 확인한다.",
        category="external_api",
        input_schema={
            "type": "object",
            "required": ["year"],
            "properties": {
                "year": {"type": "integer", "minimum": 2000, "maximum": 2100},
                "country_code": {"type": "string", "default": "KR"},
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
            },
        },
        output_schema=COMMON_OUTPUT_SCHEMA,
    )
    endpoint = "https://nagerholidays.com/api/v4/Holidays/{country_code}/{year}"

    def __init__(self, session=None, timeout=DEFAULT_TIMEOUT):
        self.session = session or requests.Session()
        self.timeout = timeout

    def invoke(self, **kwargs: Any) -> ToolResult:
        try:
            year = int(kwargs["year"])
        except (KeyError, TypeError, ValueError):
            return ToolResult.failure("INVALID_INPUT", "연도를 정수로 입력해야 합니다.")
        country_code = str(kwargs.get("country_code", "KR")).strip().upper()
        if not (2000 <= year <= 2100) or len(country_code) != 2:
            return ToolResult.failure("INVALID_INPUT", "연도 또는 국가 코드가 올바르지 않습니다.")
        try:
            start = date.fromisoformat(str(kwargs["start_date"])) if kwargs.get("start_date") else date(year, 1, 1)
            end = date.fromisoformat(str(kwargs["end_date"])) if kwargs.get("end_date") else date(year, 12, 31)
        except ValueError:
            return ToolResult.failure("INVALID_INPUT", "날짜는 YYYY-MM-DD 형식이어야 합니다.")
        if start > end or start.year != year or end.year != year:
            return ToolResult.failure("INVALID_INPUT", "조회 시작일과 종료일은 같은 연도 안에서 순서대로 입력해야 합니다.")

        body, error = _request_json(
            self.session,
            self.endpoint.format(country_code=country_code, year=year),
            timeout=self.timeout,
        )
        if error:
            return error
        if not isinstance(body, list):
            return ToolResult.failure("INVALID_RESPONSE", "공휴일 API 응답 구조를 확인할 수 없습니다.")
        holidays = []
        for item in body:
            try:
                holiday_date = date.fromisoformat(item["date"])
            except (KeyError, TypeError, ValueError):
                continue
            if start <= holiday_date <= end:
                holidays.append(
                    {
                        "date": holiday_date.isoformat(),
                        "name": item.get("name"),
                        "national_holiday": item.get("nationalHoliday"),
                        "subdivision_codes": item.get("subdivisionCodes"),
                        "holiday_types": item.get("holidayTypes", []),
                    }
                )
        return ToolResult.success(
            {
                "year": year,
                "country_code": country_code,
                "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
                "holidays": holidays,
                "source": "Nager.Date Community REST API v4",
                "source_url": "https://github.com/nager/Nager.Date/blob/main/doc/examples/rest-api.md",
            }
        )
