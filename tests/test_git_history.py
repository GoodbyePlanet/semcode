from __future__ import annotations

from server.indexer.git_history import (
    _MAX_PATCH_CHARS,
    _build_embedding_text,
    _commit_to_payload,
)
from server.indexer.github_source import CommitFile, GitHubCommit


def _commit(
    message: str = "Fix bug in auth", files: list[CommitFile] | None = None
) -> GitHubCommit:
    return GitHubCommit(
        sha="abc123def456",
        message=message,
        author_name="Jane Doe",
        author_email="jane@example.com",
        committed_at="2024-03-15T10:00:00Z",
        files=files or [],
    )


def _file(filename: str = "src/Foo.java", patch: str | None = None) -> CommitFile:
    return CommitFile(
        filename=filename, status="modified", additions=5, deletions=2, patch=patch
    )


def test_embedding_text_contains_service_and_author():
    text = _build_embedding_text(_commit(), "auth-server")
    assert "auth-server" in text
    assert "Jane Doe" in text


def test_embedding_text_contains_message():
    text = _build_embedding_text(_commit("Refactor payment processing"), "payments")
    assert "Refactor payment processing" in text


def test_embedding_text_contains_date():
    text = _build_embedding_text(_commit(), "svc")
    assert "2024-03-15T10:00:00Z" in text


def test_embedding_text_contains_files():
    files = [_file("src/AuthService.java"), _file("src/TokenStore.java")]
    text = _build_embedding_text(_commit(files=files), "auth-server")
    assert "src/AuthService.java" in text
    assert "src/TokenStore.java" in text
    assert "Files changed" in text


def test_embedding_text_no_files_line_when_empty():
    text = _build_embedding_text(_commit(), "svc")
    assert "Files changed" not in text


def test_payload_fields():
    payload = _commit_to_payload(_commit(), "auth-server")
    assert payload["sha"] == "abc123def456"
    assert payload["service"] == "auth-server"
    assert payload["message"] == "Fix bug in auth"
    assert payload["author_name"] == "Jane Doe"
    assert payload["author_email"] == "jane@example.com"
    assert payload["committed_at"] == "2024-03-15T10:00:00Z"
    assert "indexed_at" in payload


def test_payload_has_diff_fields_when_files_present():
    files = [_file("src/Foo.java")]
    payload = _commit_to_payload(_commit(files=files), "svc")
    assert payload["has_diff"] is True
    assert payload["diff_truncated"] is False
    assert len(payload["files"]) == 1
    assert payload["files"][0]["filename"] == "src/Foo.java"


def test_payload_has_diff_false_when_no_files():
    payload = _commit_to_payload(_commit(), "svc")
    assert payload["has_diff"] is False
    assert payload["files"] == []


def test_payload_truncates_patch():
    long_patch = "x" * (_MAX_PATCH_CHARS + 500)
    payload = _commit_to_payload(_commit(files=[_file(patch=long_patch)]), "svc")
    assert len(payload["files"][0]["patch"]) == _MAX_PATCH_CHARS


def test_payload_diff_truncated_flag():
    files = [_file(f"src/File{i}.java") for i in range(51)]
    payload = _commit_to_payload(_commit(files=files), "svc")
    assert payload["diff_truncated"] is True
    assert len(payload["files"]) == 50
