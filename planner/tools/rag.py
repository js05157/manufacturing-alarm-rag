"""Local server Tool wrapping the verified second-round RAG service."""
from __future__ import annotations

from typing import Any

from planner.tools.base import COMMON_OUTPUT_SCHEMA, ToolResult, ToolSpec


class ManualSearchTool:
    spec = ToolSpec(
        name="search_fr_e800_manual",
        description="FR-E800 알람 원인·점검·대처 또는 설비 증상의 제조사 매뉴얼 근거가 필요할 때 검색한다.",
        category="local_server_api",
        input_schema={
            "type": "object",
            "required": ["question"],
            "properties": {"question": {"type": "string", "minLength": 1}},
        },
        output_schema=COMMON_OUTPUT_SCHEMA,
    )

    def __init__(self, service=None, settings=None):
        self._service = service
        self.settings = settings

    @property
    def service(self):
        if self._service is None:
            from config import Settings
            from rag.pipeline import RAGService

            self._service = RAGService(self.settings or Settings())
        return self._service

    def invoke(self, **kwargs: Any) -> ToolResult:
        question = str(kwargs.get("question", "")).strip()
        if not question:
            return ToolResult.failure("INVALID_INPUT", "매뉴얼 검색 질문을 입력해야 합니다.")
        try:
            answer = self.service.answer(question, evidence_only=True)
        except FileNotFoundError:
            return ToolResult.failure("NO_INDEX", "검증된 FR-E800 검색 인덱스가 구축되지 않았습니다.")
        except ValueError as exc:
            return ToolResult.failure("INDEX_ERROR", str(exc))
        except RuntimeError:
            return ToolResult.failure("RAG_ERROR", "FR-E800 매뉴얼 검색을 완료하지 못했습니다.")
        if answer.get("status") == "insufficient":
            return ToolResult.failure("NO_EVIDENCE", "질문에 대응하는 검증된 FR-E800 근거를 찾지 못했습니다.")
        retrieval = answer.get("retrieval", {})
        sources = []
        seen = set()
        for record in retrieval.get("records", []):
            for collection in ("notes", "check_points", "actions"):
                for item in record.get(collection, []):
                    for evidence in item.get("evidence", []):
                        key = (evidence.get("source_pdf"), evidence.get("pdf_page"), evidence.get("printed_page"))
                        if key not in seen:
                            seen.add(key)
                            sources.append(
                                {"manual": key[0], "pdf_page": key[1], "printed_page": key[2]}
                            )
        return ToolResult.success(
            {
                "answer": answer.get("text", ""),
                "status": answer.get("status"),
                "evidence_ids": answer.get("evidence_ids", []),
                "sources": sources,
                "validation": answer.get("validation", {}),
            }
        )
