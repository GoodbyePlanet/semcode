from __future__ import annotations

import pytest

from eval.matching import find_first_correct_rank
from eval.metrics import mrr, recall_at_k


class _FakePoint:
    def __init__(self, symbol_name: str, file_path: str = "svc/File.java") -> None:
        self.payload = {"symbol_name": symbol_name, "file_path": file_path}
        self.score = 0.9


# ── metrics ──────────────────────────────────────────────────────────────────

def test_recall_at_k_partial():
    assert recall_at_k([1, None, 3], k=1) == pytest.approx(1 / 3)


def test_recall_at_k_all_hit():
    assert recall_at_k([1, 2, 3], k=3) == 1.0


def test_recall_at_k_none_hit():
    assert recall_at_k([None, None], k=5) == 0.0


def test_recall_empty():
    assert recall_at_k([], k=1) == 0.0


def test_mrr_basic():
    ranks = [1, None, 2]
    expected = (1 / 1 + 1 / 2) / 3
    assert abs(mrr(ranks) - expected) < 1e-9


def test_mrr_all_miss():
    assert mrr([None, None]) == 0.0


# ── matching ─────────────────────────────────────────────────────────────────

def test_matching_symbol_name_case_insensitive():
    hits = [_FakePoint("FooBar")]
    assert find_first_correct_rank(hits, [{"symbol_name": "foobar"}]) == 1


def test_matching_symbol_name_substring():
    hits = [_FakePoint("getUserById")]
    assert find_first_correct_rank(hits, [{"symbol_name": "getUser"}]) == 1


def test_matching_file_path_contains():
    hits = [_FakePoint("save", file_path="svc/UserRepository.java")]
    assert find_first_correct_rank(hits, [{"symbol_name": "save", "file_path_contains": "Repository"}]) == 1


def test_matching_file_path_miss():
    hits = [_FakePoint("save", file_path="svc/UserService.java")]
    assert find_first_correct_rank(hits, [{"symbol_name": "save", "file_path_contains": "Repository"}]) is None


def test_matching_second_result():
    hits = [_FakePoint("unrelated"), _FakePoint("placeOrder")]
    assert find_first_correct_rank(hits, [{"symbol_name": "placeOrder"}]) == 2


def test_matching_no_hit():
    hits = [_FakePoint("BarBaz")]
    assert find_first_correct_rank(hits, [{"symbol_name": "foobar"}]) is None


def test_matching_or_semantics():
    hits = [_FakePoint("listProducts")]
    expected = [{"symbol_name": "getProducts"}, {"symbol_name": "listProducts"}]
    assert find_first_correct_rank(hits, expected) == 1


