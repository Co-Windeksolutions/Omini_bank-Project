from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Downstream service base URLs — set via K8s ConfigMap in the cluster.
    # In the cluster these will be in-cluster DNS names, e.g. http://iam-service:8001
    iam_service_url: str = "http://localhost:8001"
    wallet_service_url: str = "http://localhost:8002"

    # Rate limit strings in slowapi format: "N/period"
    # These can be tuned per environment via ConfigMap without a code change.
    rate_limit_register: str = "10/minute"
    rate_limit_login: str = "20/minute"

    # Outbound request timeout (seconds) — avoids the Gateway hanging indefinitely
    # if a downstream service is slow. Surfaces as a 500 to the client today;
    # add explicit httpx exception handling if you want a 504 response.
    http_timeout: float = 10.0

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
