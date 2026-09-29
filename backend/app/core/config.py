"""Central, typed configuration for AxioNex (12-factor, env driven)."""
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # --- app -------------------------------------------------------------
    app_name: str = "AxioNex"
    app_version: str = "1.0.0"
    environment: Literal["dev", "staging", "prod"] = "dev"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000"]
    seed_demo_data: bool = True

    # --- attribution -----------------------------------------------------
    author_name: str = "NIKHIL CHARY SRIRAMOJU"
    author_github: str = "https://github.com/Nikhil-creat"
    author_linkedin: str = "https://in.linkedin.com/in/nikhil-chary-sriramoju-95041b38a"
    author_email: str = "sriramojunikhil66@gmail.com"

    # --- postgres / postgis ---------------------------------------------
    database_url: str = "postgresql+asyncpg://optimarket:optimarket@postgres:5432/optimarket"
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # --- redis (streams + cache) ----------------------------------------
    redis_url: str = "redis://redis:6379/0"
    redis_cluster: bool = False
    run_stream_ttl_seconds: int = 3600
    webhook_stream: str = "webhooks:inbound"
    webhook_dead_stream: str = "webhooks:dead"
    webhook_group: str = "mesh-workers"

    # --- vector memory ---------------------------------------------------
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str | None = None
    intel_collection: str = "market_intel"
    visual_collection: str = "product_visuals"
    embedding_backend: Literal["sentence-transformers", "hash"] = "sentence-transformers"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384

    # --- LLM (optional; RAG falls back to extractive answers) -----------
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-5"
    llm_max_tokens: int = 700

    # --- computer vision -------------------------------------------------
    cnn_backbone: Literal["resnet50", "efficientnet_b0"] = "resnet50"
    cnn_pretrained: bool = True
    cnn_head_checkpoint: str | None = None  # path to fine-tuned multi-head weights
    max_upload_mb: int = 10

    # --- security / guardrails ------------------------------------------
    webhook_secret: str = "change-me-in-production"
    webhook_tolerance_seconds: int = 300
    max_po_value: float = 500_000.0  # hard cap for an agent-proposed purchase order
    # API keys -> plan, e.g. API_KEYS='{"sk_live_abc":"growth"}'. Requests without a key run as "anonymous".
    api_keys: dict[str, str] = {}
    plan_limits: dict[str, dict[str, int]] = {
        "anonymous": {"rpm": 60, "runs_per_month": 20},
        "starter": {"rpm": 120, "runs_per_month": 50},
        "growth": {"rpm": 600, "runs_per_month": 2000},
        "scale": {"rpm": 3000, "runs_per_month": 50000},
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
