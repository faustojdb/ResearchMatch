"""
Offline unit tests for the OpenAlex literature client.

No network calls are made:
- `_reconstruct_abstract` is pure.
- `is_available()` is driven purely by the RESEARCH_MATCH_DISABLE_OPENALEX env var.
- `search_works("")` short-circuits on the empty query before any HTTP request.

Run standalone with:
    RESEARCH_MATCH_DISABLE_OPENALEX=1 pytest tests/test_openalex.py -q
"""

from __future__ import annotations

from src.openalex_client import OpenAlexClient, _reconstruct_abstract


# =====================================================================
# _reconstruct_abstract — rebuild text from an inverted index
# =====================================================================

class TestReconstructAbstract:
    def test_reconstructs_word_order_from_positions(self):
        # "Hello" at positions 0 and 2, "world" at position 1 → "Hello world Hello".
        inverted = {"Hello": [0, 2], "world": [1]}
        assert _reconstruct_abstract(inverted) == "Hello world Hello"

    def test_none_returns_empty_string(self):
        assert _reconstruct_abstract(None) == ""

    def test_empty_dict_returns_empty_string(self):
        assert _reconstruct_abstract({}) == ""

    def test_single_word(self):
        assert _reconstruct_abstract({"solo": [0]}) == "solo"


# =====================================================================
# OpenAlexClient.is_available — env-gated, no network
# =====================================================================

class TestIsAvailable:
    def test_disabled_when_env_set_to_1(self, monkeypatch):
        monkeypatch.setenv("RESEARCH_MATCH_DISABLE_OPENALEX", "1")
        assert OpenAlexClient().is_available() is False

    def test_available_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("RESEARCH_MATCH_DISABLE_OPENALEX", raising=False)
        assert OpenAlexClient().is_available() is True

    def test_disabled_for_truthy_variants(self, monkeypatch):
        for val in ("true", "TRUE", "yes"):
            monkeypatch.setenv("RESEARCH_MATCH_DISABLE_OPENALEX", val)
            assert OpenAlexClient().is_available() is False


# =====================================================================
# search_works — empty query short-circuits (never touches the network)
# =====================================================================

class TestSearchWorks:
    def test_empty_query_returns_empty_list(self, monkeypatch):
        # Even with OpenAlex "enabled", an empty query returns [] before any HTTP call.
        monkeypatch.delenv("RESEARCH_MATCH_DISABLE_OPENALEX", raising=False)
        assert OpenAlexClient().search_works("", 5) == []

    def test_whitespace_query_returns_empty_list(self, monkeypatch):
        monkeypatch.delenv("RESEARCH_MATCH_DISABLE_OPENALEX", raising=False)
        assert OpenAlexClient().search_works("   ", 5) == []

    def test_disabled_client_returns_empty_list(self, monkeypatch):
        # Disabled → even a real query returns [] without a network call.
        monkeypatch.setenv("RESEARCH_MATCH_DISABLE_OPENALEX", "1")
        assert OpenAlexClient().search_works("quantum gravity", 5) == []


# =====================================================================
# work_text — combine title + abstract
# =====================================================================

class TestWorkText:
    def test_combines_title_and_abstract(self):
        text = OpenAlexClient.work_text({"title": "A Title", "abstract": "An abstract."})
        assert "A Title" in text
        assert "An abstract." in text

    def test_missing_fields(self):
        # Missing keys must not raise; result is a stripped string.
        assert isinstance(OpenAlexClient.work_text({}), str)
