from aibridge.adapters.sqlite.repository import build_fts_query


def test_fts_query_quotes_only_extracted_terms() -> None:
    query = build_fts_query('JWT OR "*" NOT refresh_token; DROP TABLE memory_item')

    assert query == (
        '"jwt" OR "or" OR "not" OR "refresh_token" OR "drop" OR "table" OR "memory_item"'
    )
    assert "*" not in query
    assert ";" not in query


def test_fts_query_deduplicates_and_limits_terms() -> None:
    assert build_fts_query("Alpha alpha beta gamma", max_terms=2) == '"alpha" OR "beta"'
    assert build_fts_query("! _ +") is None
