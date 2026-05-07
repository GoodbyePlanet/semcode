from __future__ import annotations

from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


class ServiceConfig:
    def __init__(
        self,
        name: str,
        github_repo: str,
        exclude: list[str],
        github_ref: str = "main",
        root: str | None = None,
    ) -> None:
        self.name = name
        self.github_repo = github_repo  # e.g. "myorg/catalog-service"
        self.github_ref = github_ref  # branch, tag, or commit SHA
        self.root = root  # optional path prefix within the repo
        self.exclude = exclude


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    embeddings_url: str = Field(default="http://localhost:8087", alias="EMBEDDINGS_URL")
    embeddings_model: str = Field(
        default="jinaai/jina-embeddings-v2-base-code", alias="EMBEDDINGS_MODEL"
    )
    embeddings_dimensions: int = Field(default=768, alias="EMBEDDINGS_DIMENSIONS")

    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_collection: str = Field(default="code_symbols", alias="QDRANT_COLLECTION")
    qdrant_commits_collection: str = Field(
        default="git_commits", alias="QDRANT_COMMITS_COLLECTION"
    )
    git_history_max_commits: int = Field(default=500, alias="GIT_HISTORY_MAX_COMMITS")

    mcp_transport: Literal["streamable-http", "sse", "stdio"] = Field(
        default="streamable-http", alias="MCP_TRANSPORT"
    )
    mcp_host: str = Field(default="127.0.0.1", alias="MCP_HOST")
    mcp_port: int = Field(default=8090, alias="MCP_PORT")

    config_path: str = Field(default="./config.yaml", alias="CONFIG_PATH")
    github_token: str = Field(alias="GITHUB_TOKEN")

    def load_services(self) -> list[ServiceConfig]:
        with open(self.config_path) as f:
            data = yaml.safe_load(f)
        services = []
        for svc in data.get("services", []):
            services.append(
                ServiceConfig(
                    name=svc["name"],
                    github_repo=svc["github_repo"],
                    github_ref=svc.get("github_ref", "main"),
                    root=svc.get("root"),
                    exclude=svc.get("exclude", []),
                )
            )
        return services


settings = Settings()
