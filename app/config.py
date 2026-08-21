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


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


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

    # 账号安全
    access_token_ttl_minutes: int = int(os.getenv("ACCESS_TOKEN_TTL_MINUTES", "30"))
    refresh_token_ttl_days: int = int(os.getenv("REFRESH_TOKEN_TTL_DAYS", "7"))
    max_login_failures: int = int(os.getenv("MAX_LOGIN_FAILURES", "5"))
    login_lock_minutes: int = int(os.getenv("LOGIN_LOCK_MINUTES", "15"))
    auth_register_per_hour: int = int(os.getenv("AUTH_REGISTER_PER_HOUR", "5"))
    auth_login_per_minute: int = int(os.getenv("AUTH_LOGIN_PER_MINUTE", "5"))
    auth_login_per_hour: int = int(os.getenv("AUTH_LOGIN_PER_HOUR", "10"))
    totp_issuer: str = os.getenv("TOTP_ISSUER", "星旅 Agent")

    # 手机号验证码（未配置短信服务商时验证码打印到服务端日志）
    sms_provider: str = os.getenv("SMS_PROVIDER", "log")
    sms_access_key: str = os.getenv("SMS_ACCESS_KEY", "")
    sms_secret_key: str = os.getenv("SMS_SECRET_KEY", "")
    sms_sign_name: str = os.getenv("SMS_SIGN_NAME", "星旅 Agent")
    sms_template_code: str = os.getenv("SMS_TEMPLATE_CODE", "")
    phone_register_per_hour: int = int(os.getenv("PHONE_REGISTER_PER_HOUR", "5"))
    phone_code_per_minute: int = int(os.getenv("PHONE_CODE_PER_MINUTE", "1"))

    # 邮件验证（本地未配置时验证码打印到服务端日志）
    mail_enabled: bool = _as_bool(os.getenv("MAIL_ENABLED", "false"), False)
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from: str = os.getenv("SMTP_FROM", "")

    # 管理员初始化与演示账号
    admin_init_password: str = os.getenv("ADMIN_INIT_PASSWORD", "")
    demo_seed_enabled: bool = _as_bool(os.getenv("DEMO_SEED_ENABLED", "false"), False)

    @property
    def db_dir(self) -> str:
        return str(Path(self.db_path).parent)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

