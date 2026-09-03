from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STATUS_", env_file=".env")
    face_host: str = Field(default="")
    ssh_username: str = Field(default="")
    ssh_key_path: str = Field(default="")
    routing_table: str = Field(default="")
    tunnel_network: str = Field(default="")

    ssh_timeout_seconds: int = 10
    poll_interval_seconds: int = 15
    ping_count: int = 3


settings = Settings()
