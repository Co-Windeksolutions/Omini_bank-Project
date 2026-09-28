from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database — set via K8s Secret in the cluster
    database_url: str = "postgresql+asyncpg://wallet_user:wallet_pass@localhost:5432/wallet_db"

    # RabbitMQ — set via K8s Secret in the cluster
    # aio_pika.connect_robust accepts the standard AMQP URL format
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # Exchange name must match the Notification service's consumer config.
    # Changing this requires redeploying both services simultaneously.
    transfer_exchange_name: str = "transfers"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8002

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
