import pytest


@pytest.fixture(autouse=True)
def no_local_llm(monkeypatch):
    # Keep tests deterministic: an empty OLLAMA_HOST turns the AI step off, so
    # parsing uses the fallback parser and categorization uses keyword rules.
    monkeypatch.setenv('OLLAMA_HOST', '')
