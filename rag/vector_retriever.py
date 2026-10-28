from pathlib import Path
from functools import cached_property
import re

from rag.embeddings import E5Encoder
from rag.lexical_ranker import BM25
from scripts.common import read_json


def unique_code_ranking(hits, k=3):
    codes = []
    for hit in hits:
        code = hit["metadata"].get("error_code")
        if code and code not in codes:
            codes.append(code)
        if len(codes) == k:
            break
    return codes


def hit_name(hit):
    title = hit["text"].split("\n", 1)[0]
    return title.split(" ", 1)[-1] if hit["metadata"].get("content_type") == "alarm" else title


def phases(text):
    compact = re.sub(r"\s+", "", text)
    if "가감속" in compact:
        return {"가속", "감속"}
    found = {phase for phase in ("가속", "정속", "감속") if phase in compact}
    # '정속 운전 중 ... 정지했다' describes steady-speed operation, not
    # a fault occurring while stopped. Stop must be an explicit phase.
    if re.search(r"정지(?:중|할때|시|구간|상태)", compact):
        found.add("정지")
    return found


def title_phases(text):
    return phases(text) if re.search(r"(?:가속|정속|감속(?:/정지)?|정지)\s*중", text) else set()


def score_ranks(scores):
    """Equal lexical scores receive equal ranks, independent of chunk IDs."""
    result, previous, rank = {}, None, 0
    for position, (identifier, score) in enumerate(sorted(scores.items(), key=lambda x: (-x[1], x[0])), 1):
        if score <= 0:
            continue
        if score != previous:
            rank = position
            previous = score
        result[identifier] = rank
    return result


def select_evidence(hits, question, k=3):
    """Keep one alarm record family, or directly named symptom groups."""
    if not hits:
        return [], ""
    first = hits[0]
    compact = re.sub(r"\W+", "", question).casefold()
    first_name = re.sub(r"\W+", "", hit_name(first)).casefold()
    # Stall prevention explicitly prevents tripping; a question saying the
    # output tripped must not be answered with that warning merely because
    # both contain '과전류'. Resolve the operating phase against source titles.
    faults = [word for word in ("과전류", "과전압") if word in compact and word in first_name]
    if faults and "차단" in compact and "스톨방지" in first_name and "스톨방지" not in compact:
        branches = [h for h in hits if h["metadata"].get("content_type") == "alarm"
                    and "차단" in hit_name(h) and any(word in hit_name(h) for word in faults)
                    and title_phases(hit_name(h))]
        wanted = phases(question)
        if branches and not wanted:
            return [], "과전류·과전압 차단과 스톨 방지 표시는 구분이 필요합니다. 표시 코드와 발생 구간(가속 중, 정속 중, 감속·정지 중)을 알려 주세요."
        compatible = [h for h in branches if wanted & title_phases(hit_name(h))]
        if compatible:
            first = compatible[0]
    metadata = first["metadata"]
    if metadata.get("content_type") == "alarm":
        name = re.sub(r"\s+", "", hit_name(first))
        same_name = {h["metadata"].get("error_code") for h in hits[:12]
                     if h["metadata"].get("content_type") == "alarm" and re.sub(r"\s+", "", hit_name(h)) == name}
        same_records = {h["metadata"].get("record_id") for h in hits[:12]
                        if h["metadata"].get("content_type") == "alarm" and re.sub(r"\s+", "", hit_name(h)) == name}
        if len(same_records) > 1:
            codes = ", ".join(sorted(same_name))
            return [], f"같은 명칭으로 검색되는 표시가 여러 개입니다({codes}). 조작 패널에 표시된 코드를 알려 주세요."
        if title_phases(hit_name(first)) and not phases(question):
            return [], "알람이 발생한 운전 구간을 알려 주세요. 가속 중, 정속 운전 중, 감속·정지 중 어느 때인가요? 표시 코드도 함께 알려 주시면 해당 항목을 확인할 수 있습니다."
        selected = [h for h in hits if h["metadata"].get("record_id") == metadata.get("record_id")]
    else:
        sections = {metadata.get("section")}
        for hit in hits[:6]:
            if hit["metadata"].get("content_type") != "symptom":
                continue
            name = re.sub(r"\W+", "", hit_name(hit)).casefold()
            # A shared predicate such as '이상음이' does not make motor and
            # inverter sections interchangeable. Additional device-specific
            # sections require that device to be stated in the question.
            targets = [target for target in ("모터", "기계", "인버터", "조작패널", "ethernet") if target in name]
            if targets and not any(target in compact for target in targets):
                continue
            # A second symptom is included only when a source-title phrase is
            # explicitly present, e.g. both motor start and panel display.
            if any(name[i:i+4] in compact for i in range(max(0, len(name)-3))):
                sections.add(hit["metadata"].get("section"))
        selected = [h for h in hits if h["metadata"].get("content_type") == "symptom" and h["metadata"].get("section") in sections]
        # Cover explicitly named source areas before filling remaining slots.
        # Keep the selected rows in their original retrieval order.
        requested = {}
        for hit in selected:
            match = re.search(r"^확인 부위: (.+)$", hit["text"], re.M)
            area = re.sub(r"\W+", "", match[1]).casefold() if match else ""
            if area and area in compact:
                requested.setdefault(area, hit["id"])
        chosen = set(list(requested.values())[:k])
        for hit in selected:
            if len(chosen) >= k:
                break
            chosen.add(hit["id"])
        selected = [h for h in selected if h["id"] in chosen]
    return selected[:k], ""


class VectorRetriever:
    def __init__(self, path, model_name, revision=None, encoder=None):
        self.path = Path(path)
        self.manifest = read_json(self.path / "manifest.json")
        indexed_revision = self.manifest["identity"]["revision"]
        if revision and revision != indexed_revision:
            raise ValueError("설정한 임베딩 revision이 인덱스와 다릅니다. 동일 revision으로 재구축하세요.")
        self.encoder = encoder or E5Encoder(model_name, indexed_revision, local_files_only=True)
        if self.manifest["identity"]["model"] != model_name:
            raise ValueError("임베딩 모델 설정이 인덱스와 다릅니다. 동일 모델로 재구축하세요.")
        import chromadb
        from chromadb.config import Settings
        self.client = chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))
        self.collection = self.client.get_collection(self.manifest["collection"], embedding_function=None)

    def vector_search(self, question, k=3, code=None, max_distance=None):
        if self.encoder.identity != self.manifest["identity"]:
            raise ValueError("임베딩 revision/차원/입력 규칙이 인덱스와 다릅니다. 인덱스를 재구축하세요.")
        where = {"error_code": code} if code else None
        result = self.collection.query(query_embeddings=[self.encoder.query(question)], n_results=min(k, self.collection.count()),
                                       where=where, include=["documents", "metadatas", "distances"])
        hits = [{"id": i, "text": t, "metadata": m, "distance": float(d)}
                for i, t, m, d in zip(result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0])]
        return [h for h in hits if max_distance is None or h["distance"] <= max_distance]

    @cached_property
    def lexical(self):
        stored = self.collection.get(include=["documents", "metadatas"])
        documents = {i: {"id": i, "text": t, "metadata": m} for i, t, m in
                     zip(stored["ids"], stored["documents"], stored["metadatas"])}
        identifiers = sorted(documents)
        return (identifiers, BM25([documents[i]["text"] for i in identifiers]),
                BM25([hit_name(documents[i]) for i in identifiers]))

    def search(self, question, k=3, code=None, max_distance=None):
        # Every request still uses the pinned E5 model. Lexical scores do not
        # provide a fallback when embeddings are unavailable.
        hits = self.vector_search(question, self.collection.count(), code=code)
        identifiers, body, title = self.lexical
        body_scores = dict(zip(identifiers, body.scores(question)))
        title_scores = dict(zip(identifiers, title.scores(question)))
        body_ranks, title_ranks = score_ranks(body_scores), score_ranks(title_scores)
        wanted_phase = phases(question)
        for rank, hit in enumerate(hits, 1):
            identifier = hit["id"]
            hit["vector_rank"] = rank
            hit["lexical_score"] = body_scores[identifier]
            hit["rrf_score"] = 1/(60+rank) + sum(1/(60+r[identifier]) for r in (body_ranks, title_ranks) if identifier in r)
            source_phase = title_phases(hit_name(hit)) if hit["metadata"].get("content_type") == "alarm" else set()
            hit["phase_mismatch"] = bool(wanted_phase and source_phase and not wanted_phase & source_phase)
        hits.sort(key=lambda h: (h["phase_mismatch"], -h["rrf_score"], h["distance"], h["id"]))
        return [h for h in hits if max_distance is None or h["distance"] <= max_distance][:k]

    def code_candidates(self, question, k=3):
        # Fetch all candidates to avoid under-filling Hit@3 after duplicate-code
        # collapse. This small single-manual corpus fits in one bounded query.
        hits = self.search(question, self.collection.count())
        return unique_code_ranking(hits, k)
