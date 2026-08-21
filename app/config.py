"""轻量配置管理，支持环境变量覆盖，不引入额外依赖。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: str) -> None:
    env_file = Path(path)
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str = "星旅 Agent"
    environment: str = os.getenv("ENVIRONMENT", "development")
    secret_key: str = os.getenv("SECRET_KEY", "travel-agent-dev-secret")
    token_ttl_hours: int = int(os.getenv("TOKEN_TTL_HOURS", "24"))

    db_path: str = os.getenv(
        "DB_PATH", str(PROJECT_ROOT / "data" / "travel.db")
    )
    frontend_dir: str = os.getenv(
        "FRONTEND_DIR", str(PROJECT_ROOT / "frontend")
    )

    llm_mode: str = os.getenv("LLM_MODE", "demo")  # demo | openai
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv(
        "OPENAI_BASE_URL", "https://api.openai.com/v1"
    )
    model_name: str = os.getenv("MODEL_NAME", "gpt-4o-mini")

    search_provider: str = os.getenv("SEARCH_PROVIDER", "auto")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    serpapi_api_key: str = os.getenv("SERPAPI_API_KEY", "")
    bing_search_key: str = os.getenv("BING_SEARCH_KEY", "")
    google_search_key: str = os.getenv("GOOGLE_SEARCH_KEY", "")
    google_cse_id: str = os.getenv("GOOGLE_CSE_ID", "")
    serper_api_key: str = os.getenv("SERPER_API_KEY", "")
    brave_search_key: str = os.getenv("BRAVE_SEARCH_KEY", "")
    map_mcp_mode: str = os.getenv("MAP_MCP_MODE", "demo")
    map_mcp_api_key: str = os.getenv("MAP_MCP_API_KEY", "")

    rate_limit_per_minute: int = int(
        os.getenv("RATE_LIMIT_PER_MINUTE", "20")
    )
    max_plan_retries: int = int(os.getenv("MAX_PLAN_RETRIES", "2"))
    cors_origins: str = os.getenv(
        "CORS_ORIGINS", "http://localhost:8000,http://localhost:5173"
    )

    @property
    def db_dir(self) -> str:
        return str(Path(self.db_path).parent)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

