"""One explicit E5 encoder for indexing and queries; no provider fallback."""
from functools import cached_property
from pathlib import Path


class E5Encoder:
    def __init__(self, model_name, revision=None, local_files_only=False):
        self.model_name = model_name
        self.revision = revision
        self.local_files_only = local_files_only

    @cached_property
    def resolved_revision(self):
        from huggingface_hub import hf_hub_download, try_to_load_from_cache
        import re
        cached = try_to_load_from_cache(self.model_name, "config.json", revision=self.revision or "main")
        if not isinstance(cached, str) and self.local_files_only:
            raise FileNotFoundError("로컬 E5 모델 캐시가 없습니다. 기존 인덱스와 동일한 모델 revision을 먼저 준비하세요. 자동 다운로드하지 않습니다.")
        config_path = cached if isinstance(cached, str) else hf_hub_download(self.model_name, "config.json", revision=self.revision or "main")
        revision = Path(config_path).parent.name
        if not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ValueError("임베딩 모델의 정확한 revision을 확인할 수 없습니다.")
        return revision

    @cached_property
    def model(self):
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(self.model_name, revision=self.resolved_revision, device="cpu", trust_remote_code=False, local_files_only=self.local_files_only)

    @property
    def identity(self):
        return {"model": self.model_name, "revision": self.resolved_revision,
                "dimension": getattr(self.model, "get_embedding_dimension", self.model.get_sentence_embedding_dimension)(),
                "prefix_policy": "query:/passage:", "max_tokens": 512}

    def token_count(self, text):
        return len(self.model.tokenizer.encode("passage: "+text, add_special_tokens=True, truncation=False))

    def passages(self, texts):
        if any(self.token_count(t) > 512 for t in texts):
            raise ValueError("512-token E5 limit exceeded; refusing silent truncation")
        return self.model.encode(["passage: "+t for t in texts], normalize_embeddings=True, batch_size=32, show_progress_bar=True).tolist()

    def query(self, question):
        length = len(self.model.tokenizer.encode("query: "+question, add_special_tokens=True, truncation=False))
        if length > 512:
            raise ValueError("질문이 너무 깁니다. 512 토큰 이내로 줄여 주세요.")
        return self.model.encode(["query: "+question], normalize_embeddings=True, show_progress_bar=False).tolist()[0]
