"""Unit tests for path/query normalization in pipeline."""

from specdrift.modules.pipeline import _split_path_and_query


def test_split_path_and_query_from_path_string() -> None:
    path, query = _split_path_and_query("/auth/bearer-protected?drift=true", None)
    assert path == "/auth/bearer-protected"
    assert query == {"drift": "true"}


def test_split_path_and_query_merges_with_explicit_query_params() -> None:
    path, query = _split_path_and_query(
        "/auth/apikey-protected?drift=true&mode=from-path",
        {"mode": "explicit", "extra": "1"},
    )
    assert path == "/auth/apikey-protected"
    assert query == {"drift": "true", "mode": "explicit", "extra": "1"}

