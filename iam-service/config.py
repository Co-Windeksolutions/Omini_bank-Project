from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://iam_user:iam_pass@localhost:5432/iam_db"

    # JWT
    jwt_secret_key: str = "changeme-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60

    # Password hashing
    # bcrypt work factor (rounds). Each increment doubles the hash time.
    # 12 is the OWASP-recommended minimum for 2024 hardware.
    # Raise to 13-14 on hardware that can afford ~500ms+ per hash.
    bcrypt_rounds: int = 12

    # App
    app_host: str = "0.0.0.0"
    app_port: int = 8001

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
