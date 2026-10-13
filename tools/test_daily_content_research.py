#!/usr/bin/env python3
"""Offline regression tests for malformed daily research JSON output."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import daily_content_research as research

def response(text):
    return {"provider":"main_worker_groq","choices":[{"message":{"content":text}}]}

def test_repair():
    os.environ["GROQ_API_KEY"] = ""
    calls = []
    old = research.chat_completion
    old_log = list(research._AI_CALL_LOG)
    def fake(payload, workflow_path, timeout=90):
        calls.append(payload)
        return response('{"category" "AI News"}') if len(calls)==1 else response('{"category":"AI News"}')
    research.chat_completion = fake
    research._AI_CALL_LOG.clear()
    try:
        assert research.groq_json("test","test",max_tokens=100)=={"category":"AI News"}
        assert len(calls)==2, calls
        assert [x.get("phase") for x in research._AI_CALL_LOG]==["primary","single_json_repair"]
    finally:
        research.chat_completion = old
        research._AI_CALL_LOG[:] = old_log

def test_fail_closed():
    old = research.chat_completion
    old_sleep = research.time.sleep
    old_start = research._LAST_GROQ_START
    research.time.sleep = lambda _: None
    research._LAST_GROQ_START = 0.0
    calls=[]
    research.chat_completion=lambda *args,**kwargs: (calls.append(1) or response('{"bad" "json"}'))
    try:
        try:
            research.groq_json("test","test",max_tokens=100)
        except RuntimeError as e:
            assert "malformed JSON twice" in str(e)
        else:
            raise AssertionError("Must fail closed")
        assert len(calls)==2
    finally:
        research.chat_completion=old
        research.time.sleep=old_sleep
        research._LAST_GROQ_START=old_start


def test_ai_trend_relevance_gate():
    # Generic US technology chart winners must not drive an AI Tech Lab topic.
    chart = [
        {"video_id": "phone001", "category": "Science & Technology", "title": "Testing the iPhone duo's most asked questions"},
        {"video_id": "tv001", "category": "Science & Technology", "title": "How to install a 115-inch TV"},
        {"video_id": "chat001", "category": "Science & Technology", "title": "Which AI is smartest?"},
        {"video_id": "agent001", "category": "Education", "title": "AI agents can automate a real workflow"},
    ]
    targeted = [
        {"video_id": "chat001", "title": "Which AI is smartest?"},
        {"video_id": "grok001", "title": "Grok and AI agent workflows explained"},
        {"video_id": "llm001", "title": "Large language models compared"},
        {"video_id": "phone002", "title": "iPhone camera comparison"},
    ]
    calls = []
    def fallback():
        calls.append(True)
        return targeted

    rows, fallback_used = research.collect_ai_trend_signals(chart, fallback_fn=fallback, minimum=4)
    assert fallback_used is True
    assert len(calls) == 1
    assert len(rows) == 4
    assert "phone001" not in {row["video_id"] for row in rows}
    assert "tv001" not in {row["video_id"] for row in rows}
    assert len({row["video_id"] for row in rows}) == len(rows)

    # If the chart already has enough AI-related entries, do not add extra API/search work.
    calls.clear()
    enough = chart + [
        {"video_id": "llm002", "title": "Large language models can reason"},
        {"video_id": "agent002", "title": "AI agents in business automation"},
        {"video_id": "openai002", "title": "OpenAI demonstrates a new model"},
    ]
    rows, fallback_used = research.collect_ai_trend_signals(enough, fallback_fn=fallback, minimum=5)
    assert fallback_used is False
    assert calls == []
    assert len(rows) >= 5


def test_ai_trend_gate_fails_closed():
    chart = [
        {"video_id": "phone001", "title": "Testing the iPhone duo"},
        {"video_id": "tv001", "title": "Best smart TVs of 2026"},
        {"video_id": "gpu001", "title": "A gaming PC upgrade"},
    ]
    try:
        research.collect_ai_trend_signals(chart, fallback_fn=None, minimum=5)
    except RuntimeError as exc:
        assert "explicit AI-related YouTube videos" in str(exc)
    else:
        raise AssertionError("The topic selector must fail closed when AI trend evidence is insufficient")


if __name__=="__main__":
    test_repair()
    test_fail_closed()
    test_ai_trend_relevance_gate()
    test_ai_trend_gate_fails_closed()
    print("DAILY_CONTENT_RESEARCH_JSON_REPAIR_AND_AI_TREND_GATES_PASS")
