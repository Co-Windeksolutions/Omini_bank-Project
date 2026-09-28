from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # RabbitMQ — set via K8s Secret in the cluster
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # Must match the Wallet/Ledger publisher's exchange name exactly.
    transfer_exchange_name: str = "transfers"

    # Queue name must be unique to this consumer.
    # A durable named queue (rather than an anonymous auto-delete queue) survives
    # a consumer pod restart — messages published while the pod was down are
    # delivered when it comes back up.
    notification_queue_name: str = "notification.transfers"

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8003

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
