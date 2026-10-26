from pathlib import Path

from rag.embeddings import E5Encoder
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

    def search(self, question, k=3, code=None, max_distance=None):
        if self.encoder.identity != self.manifest["identity"]:
            raise ValueError("임베딩 revision/차원/입력 규칙이 인덱스와 다릅니다. 인덱스를 재구축하세요.")
        where = {"error_code": code} if code else None
        result = self.collection.query(query_embeddings=[self.encoder.query(question)], n_results=min(k, self.collection.count()),
                                       where=where, include=["documents", "metadatas", "distances"])
        hits = [{"id": i, "text": t, "metadata": m, "distance": float(d)}
                for i, t, m, d in zip(result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0])]
        return [h for h in hits if max_distance is None or h["distance"] <= max_distance]

    def code_candidates(self, question, k=3):
        # Fetch all candidates to avoid under-filling Hit@3 after duplicate-code
        # collapse. This small single-manual corpus fits in one bounded query.
        hits = self.search(question, self.collection.count())
        return unique_code_ranking(hits, k)
