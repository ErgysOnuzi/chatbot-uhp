import sys
import types
from types import SimpleNamespace as NS

import pytest

# Testet nuk kërkojnë openai/pydantic-settings të instaluar: zëvendësohen me module të thjeshta.
if "openai" not in sys.modules:
    try:
        import openai  # noqa: F401
    except ImportError:
        sys.modules["openai"] = types.SimpleNamespace(OpenAI=object)
try:
    import pydantic_settings  # noqa: F401
except ImportError:
    fake_config = types.ModuleType("app.config")
    fake_config.settings = NS(llm_base_url="http://x", llm_api_key="", llm_model="m", llm_temperature=0.2, llm_max_tokens=10)
    sys.modules["app.config"] = fake_config

from app import llm  # noqa: E402


def event(content=None, reasoning=None, finish=None):
    delta = NS(content=content, reasoning_content=reasoning)
    return NS(choices=[NS(delta=delta, finish_reason=finish)])


def fake_client(events):
    create = lambda **kwargs: iter(events)  # noqa: E731
    return NS(chat=NS(completions=NS(create=create)))


def test_stream_returns_only_content_not_reasoning(monkeypatch):
    events = [event(reasoning="Po mendoj..."), event(content="Afati "), event(content="është 15 janar."), event(finish="stop")]
    monkeypatch.setattr(llm, "_client", lambda: fake_client(events))
    assert "".join(llm.stream_chat([])) == "Afati është 15 janar."


def test_reasoning_only_answer_raises_clear_error(monkeypatch):
    events = [event(reasoning="arsyetim i gjatë " * 50), event(finish="length")]
    monkeypatch.setattr(llm, "_client", lambda: fake_client(events))
    with pytest.raises(llm.EmptyAnswerError, match="finish_reason=length"):
        list(llm.stream_chat([]))


def test_empty_stream_raises(monkeypatch):
    monkeypatch.setattr(llm, "_client", lambda: fake_client([event(finish="stop")]))
    with pytest.raises(llm.EmptyAnswerError):
        list(llm.stream_chat([]))
