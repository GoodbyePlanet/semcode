from __future__ import annotations

from server.config import ServiceConfig
from server.indexer.sources.base import CodeSource
from server.indexer.sources.factory import get_source
from server.indexer.sources.github import GitHubSource
from server.indexer.sources.gitlab import GitLabSource


def test_github_service_gets_github_source() -> None:
    source = get_source(ServiceConfig(name="svc", repo="org/svc"))

    assert isinstance(source, GitHubSource)


def test_gitlab_service_gets_gitlab_source() -> None:
    source = get_source(ServiceConfig(name="svc", source="gitlab", repo="g/p"))

    assert isinstance(source, GitLabSource)


def test_both_sources_satisfy_the_code_source_protocol() -> None:
    assert isinstance(GitHubSource("t", "org/svc"), CodeSource)
    assert isinstance(GitLabSource("t", "g/p"), CodeSource)
