from __future__ import annotations

from server.config import ServiceConfig, settings
from server.indexer.sources.base import CodeSource
from server.indexer.sources.github import GitHubSource
from server.indexer.sources.gitlab import GitLabSource


def get_source(svc: ServiceConfig) -> CodeSource:
    """Build the `CodeSource` for a service from its configured `source`."""
    if svc.source == "gitlab":
        return GitLabSource(settings.gitlab_token, svc.repo)
    return GitHubSource(settings.github_token, svc.repo)
