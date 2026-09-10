from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STATUS_", env_file=".env")

    face_host: str = Field(default="")
    known_hosts_path: str = Field(default="")
    ping_count: int = Field(default=3)
    poll_interval_seconds: int = Field(default=15)
    routing_table: str = Field(default="")
    show_recovered: bool = Field(default=True)
    ssh_key_path: str = Field(default="")
    ssh_port: int = Field(default=22)
    ssh_timeout_seconds: int = Field(default=10)
    ssh_username: str = Field(default="")
    tunnel_network: str = Field(default="")


settings = Settings()
