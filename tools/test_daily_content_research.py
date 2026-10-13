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

if __name__=="__main__":
    test_repair()
    test_fail_closed()
    print("DAILY_CONTENT_RESEARCH_JSON_REPAIR_TEST_PASS")
