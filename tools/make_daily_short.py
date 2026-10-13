#!/usr/bin/env python3
"""Create a fact-bound English YouTube Short from the daily researched long-form package."""
from __future__ import annotations
import json, os, re, sys, time, urllib.error, urllib.request
from ai_text_client import chat_completion
from pathlib import Path
from mini_agents import NATURAL_VOICE_GUIDANCE, evaluate_human_voice

ROOT = Path("work")
API = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-20b")
KEY = os.getenv("GROQ_API_KEY", "").strip()

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def parse_json(text):
    text = str(text).strip()
    if text.startswith(chr(96) * 3):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == chr(96) * 3:
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise RuntimeError("AI provider returned valid JSON, but not a JSON object.")
    return obj

def main():
    if not KEY and not (os.getenv("GITHUB_TOKEN", "").strip() and os.getenv("GITHUB_RUN_ID", "").isdigit()):
        raise SystemExit("Groq key and authenticated Cloudflare Workers AI fallback context are both missing.")
    package = load(ROOT / "daily_content_package.json")
    evidence = load(ROOT / "tavily_evidence.json")
    sources = evidence.get("sources", [])
    if len(sources) < 4:
        raise SystemExit("Short creation blocked: fewer than four researched sources.")
    title = str(package.get("title", "")).strip()
    script = str(package.get("script", "")).strip()
    if not title or len(script) < 2500:
        raise SystemExit("Long-form package failed input validation.")
    system = (
        "You write original English-language YouTube Shorts for a US audience. "
        "Create a punchy 45-60 second short from the supplied long script only, in the same editorial category. "
        "Do not invent facts, numbers, quotes, capabilities, statistics, or hands-on experience. "
        "Do not simply compress the long script into a generic summary; build one small story around one surprising, "
        "source-supported implication. Use a sharp natural hook, a clear narrative turn, a reasoned point of view, "
        "varied sentence lengths, US-English contractions where natural, and a concise CTA. "
        "No list-reading, canned intros, empty hype, repetitive transitions, or fake personal experience. "
        "Narration only, 100-135 words. Return JSON with title, script, description, tags. "
        "Keep title under 85 characters, description under 4900 characters, and tags an array.\n\n"
        + NATURAL_VOICE_GUIDANCE
    )
    user = {
        "long_title": title,
        "editorial_category": package.get("editorial_category", "AI News & Breakthroughs"),
        "category_rotation": package.get("category_rotation", {}),
        "human_voice_profile": package.get("human_voice_qa", {}),
        "long_script": script,
        "sources": [{"title": x.get("title", ""), "url": x.get("url", ""), "evidence": x.get("content", "")[:500]} for x in sources[:8]],
        "existing_description_with_source_links": str(package.get("description", ""))[:4500],
        "tags": package.get("tags", []),
    }
    body = json.dumps({
        "model": MODEL, "temperature": 0.25, "max_tokens": 850,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": json.dumps(user, ensure_ascii=False)}],
    }).encode()
    try:
        data = chat_completion(json.loads(body.decode("utf-8")), ".github/workflows/daily-auto-production.yml", timeout=90)
    except Exception as exc:
        raise SystemExit(f"Short AI generation failed safely: {str(exc)[:300]}") from None
    if not data or not data.get("choices"):
        raise SystemExit("AI provider returned no Short completion.")
    provider = str(data.get("provider", "groq"))
    result = parse_json(data["choices"][0]["message"]["content"])
    short_title = re.sub(r"\s+", " ", str(result.get("title", "")).strip())[:85]
    short_text = re.sub(r"\r\n?", "\n", str(result.get("script", "")).strip())
    words = len(re.findall(r"\b[\w'-]+\b", short_text))
    description = re.sub(r"\s+", " ", str(result.get("description", "")).strip())
    if not description:
        description = "A quick AI Tech Lab explainer based on the sources listed below."
    description = description.split("SOURCES & FURTHER READING", 1)[0].rstrip()
    source_block = "\n\nSOURCES & FURTHER READING\n" + "\n".join(
        "- " + str(item.get("title", "Source"))[:180] + ": " + str(item.get("url", ""))
        for item in sources[:8] if str(item.get("url", "")).startswith("https://")
    )
    description = (description[:max(0, 4900 - len(source_block))].rstrip() + source_block)[:4900]
    tags = result.get("tags", package.get("tags", []))
    if not isinstance(tags, list):
        tags = package.get("tags", [])
    normalized = []
    for tag in tags:
        item = re.sub(r"\s+", " ", str(tag)).strip(" ,#")[:80]
        if item and item.casefold() not in {x.casefold() for x in normalized}:
            normalized.append(item)
    if not short_title or not 100 <= words <= 135 or len(description) < 20:
        raise SystemExit(f"Short failed quality gates: title={bool(short_title)}, script_words={words}, description_chars={len(description)}.")
    human_voice_qa = evaluate_human_voice(short_text)
    if human_voice_qa["score"] < 55:
        raise SystemExit("Short narration failed the natural-voice style gate (score " + str(human_voice_qa["score"]) + "/100); render was blocked.")
    output = {
        "brand": "AI Tech Lab", "target_audience": "United States", "content_format": "SHORT",
        "editorial_category": package.get("editorial_category", ""),
        "category_rotation": package.get("category_rotation", {}),
        "human_voice_qa": human_voice_qa, "agent_policy_version": "1.0.0",
        "title": short_title, "script": short_text, "script_word_count": words,
        "description": description[:4900], "tags": normalized[:20],
        "sources": sources[:8], "derived_from_title": title,
        "provider": ("Groq" if provider == "groq" else "Cloudflare Workers AI fallback"), "qa": "passed",
    }
    (ROOT / "short_content_package.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "passed", "provider": provider, "title": short_title, "script_words": words, "source_count": len(sources), "human_voice_score": human_voice_qa["score"], "category": output["editorial_category"]}))

if __name__ == "__main__":
    main()
