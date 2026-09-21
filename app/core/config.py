from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "sso-dispatcher"
    app_env: str = "dev"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://sso:sso@localhost:5432/sso"
    sync_database_url: str = "postgresql+psycopg://sso:sso@localhost:5432/sso"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = "change-me-in-env"
    jwt_alg: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7

    webhook_timeout_seconds: int = 10
    webhook_max_attempts: int = 5
    webhook_backoff_base_seconds: int = 2
    webhook_hmac_header: str = "X-Signature"

    rate_limit_auth_per_minute: int = 10
    rate_limit_token_per_minute: int = 20
    rate_limit_window_seconds: int = 60

    password_reset_token_minutes: int = 15
    audit_log_retention_days: int = 90


settings = Settings()
