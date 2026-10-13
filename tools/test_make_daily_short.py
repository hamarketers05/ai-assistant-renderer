#!/usr/bin/env python3
"""Regression tests for parsing the AI-generated YouTube Short package."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_daily_short import parse_json


def main():
    assert parse_json('{"title":"A Short","script":"hello"}') == {"title": "A Short", "script": "hello"}
    assert parse_json('{"title":"A Short"}')["title"] == "A Short"
    fenced = '' + chr(96) * 3 + 'json\n{"title":"Wrapped"}\n' + chr(96) * 3
    assert parse_json(fenced) == {"title": "Wrapped"}
    for raw in ("null", "[]", '"not an object"'):
        try:
            parse_json(raw)
        except RuntimeError:
            continue
        raise AssertionError(f"Non-object AI JSON must be rejected: {raw}")
    print("DAILY_SHORT_JSON_TEST_PASS: object parsing, fenced JSON and non-object rejection")


if __name__ == "__main__":
    main()
