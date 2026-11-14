from __future__ import annotations

from server.config import ServiceConfig, settings
from server.indexer.sources.base import CodeSource
from server.indexer.sources.github import GitHubSource


def get_source(svc: ServiceConfig) -> CodeSource:
    """Build the `CodeSource` for a service. GitHub is the only source today."""
    return GitHubSource(settings.github_token, svc.repo)
