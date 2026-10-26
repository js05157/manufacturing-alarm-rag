from dataclasses import asdict, dataclass, field
from functools import cached_property
from time import perf_counter

from config import Settings
from rag.router import DIRECT_REPLIES, route
from rag.sqlite_retriever import SQLiteRetriever
from rag.vector_retriever import VectorRetriever


@dataclass
class Retrieval:
    question: str
    route: str
    codes: list = field(default_factory=list)
    unknown_codes: list = field(default_factory=list)
    records: list = field(default_factory=list)
    symptom_rows: list = field(default_factory=list)
    hits: list = field(default_factory=list)


class RAGService:
    def __init__(self, settings=None, sqlite=None, vector=None, generator=None):
        self.settings = settings or Settings()
        self.sqlite = sqlite or SQLiteRetriever(self.settings.sqlite)
        self._vector = vector
        self._generator = generator

    @cached_property
    def vector(self):
        vector = self._vector or VectorRetriever(self.settings.chroma, self.settings.embedding_model, self.settings.embedding_revision)
        if vector.manifest["source_sha256"] != self.sqlite.source_hash():
            raise ValueError("SQLite와 Chroma의 원본 PDF가 다릅니다. 두 저장소를 함께 재구축하세요.")
        return vector

    def retrieve(self, question):
        if not question.strip():
            raise ValueError("질문을 입력해 주세요.")
        decision = route(question, self.sqlite.codes())
        result = Retrieval(question, decision.kind, list(decision.codes))
        if decision.kind in DIRECT_REPLIES:
            return result
        seen = set()
        for code in decision.codes:
            records = self.sqlite.get(code)
            if not records:
                result.unknown_codes.append(code)
            for record in records:
                if record["record_id"] not in seen:
                    seen.add(record["record_id"])
                    result.records.append(record)
        if decision.codes:
            # Exact records already contain the complete context and footnotes;
            # this also answers mixed questions without cross-code contamination.
            return result
        result.hits = self.vector.search(question, k=self.settings.top_k, max_distance=self.settings.max_distance)
        for hit in result.hits:
            metadata = hit["metadata"]
            if metadata.get("error_code"):
                for record in self.sqlite.get(metadata["error_code"]):
                    if record["record_id"] not in seen:
                        seen.add(record["record_id"])
                        result.records.append(record)
            elif metadata.get("content_type") == "symptom":
                symptom = self.sqlite.symptom(metadata["section"])
                if symptom:
                    selected = set(metadata["evidence_ids"].split("|"))
                    for row in symptom["rows"]:
                        if row["id"] in selected and row["id"] not in seen:
                            seen.add(row["id"])
                            result.symptom_rows.append({"name": symptom["name"], "section": symptom["section"], **row})
        return result

    def answer(self, question, evidence_only=False):
        started = perf_counter()
        retrieval = self.retrieve(question)
        if retrieval.route in DIRECT_REPLIES:
            return {"status": "guidance", "text": DIRECT_REPLIES[retrieval.route], "evidence_ids": [],
                    "highlights": [], "mode": "direct", "validation": {"valid": True, "reason": "non-retrieval guidance"},
                    "elapsed_seconds": perf_counter()-started, "retrieval": asdict(retrieval)}
        if self._generator:
            generator = self._generator
        elif self.settings.llm_backend in ("local", "evidence_only"):
            from rag.local_answer_generator import LocalAnswerGenerator
            generator = LocalAnswerGenerator(self.settings)
            evidence_only = evidence_only or self.settings.llm_backend == "evidence_only"
        elif self.settings.llm_backend == "openai":
            from rag.answer_generator import AnswerGenerator
            generator = AnswerGenerator(self.settings)
        else:
            raise ValueError("LLM_BACKEND는 local, evidence_only 또는 명시적으로 설정한 openai여야 합니다.")
        answer = generator.generate(retrieval, evidence_only=evidence_only)
        answer["elapsed_seconds"] = perf_counter()-started
        answer["retrieval"] = asdict(retrieval)
        return answer
