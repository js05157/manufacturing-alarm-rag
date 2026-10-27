"""Environment configuration; paths are always relative to the repository."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def path_env(name, default):
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else ROOT / value


@dataclass(frozen=True)
class Settings:
    pdf: Path = path_env("PDF_PATH", "data/raw/E800매뉴얼_보수편.pdf")
    sqlite: Path = path_env("SQLITE_PATH", "storage/alarms.db")
    chroma: Path = path_env("CHROMA_PATH", "storage/chroma")
    chat_db: Path = path_env("CHAT_DB_PATH", "storage/chats.db")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
    embedding_revision: str | None = os.getenv("EMBEDDING_REVISION") or None
    llm_backend: str = os.getenv("LLM_BACKEND", "local")
    local_llm_url: str = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1")
    local_llm_model: str = os.getenv("LOCAL_LLM_MODEL", "qwen3-4b")
    local_llm_model_path: Path = path_env("LOCAL_LLM_MODEL_PATH", "C:/AI/models/qwen3-4b/Qwen3-4B-Q4_K_M.gguf")
    llama_server_path: Path = path_env("LLAMA_SERVER_PATH", "C:/llama.cpp/llama-b11900-bin-win-cpu-x64/llama-server.exe")
    local_llm_context: int = int(os.getenv("LOCAL_LLM_CONTEXT", "4096"))
    local_llm_max_tokens: int = int(os.getenv("LOCAL_LLM_MAX_TOKENS", "512"))
    local_llm_timeout: float = float(os.getenv("LOCAL_LLM_TIMEOUT", "180"))
    local_llm_temperature: float = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.2"))
    local_llm_margin: int = 96
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "")
    llm_api_key: str = field(default=os.getenv("LLM_API_KEY", ""), repr=False)
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "45"))
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "1800"))
    llm_token_parameter: str = os.getenv("LLM_TOKEN_PARAMETER", "max_completion_tokens")
    top_k: int = int(os.getenv("TOP_K", "3"))
    max_distance: float = float(os.getenv("MAX_DISTANCE", "0.30"))


os.environ.setdefault("HF_HOME", str(path_env("HF_HOME", ".cache/huggingface")))


def configure_console():
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
