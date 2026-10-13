#!/usr/bin/env python3
"""Generate a sourced thumbnail brief with Groq primary and verified Workers AI fallback."""
import json, os, re
from pathlib import Path
from ai_text_client import chat_completion


def main():
    title = Path("work/title.txt").read_text(encoding="utf-8").strip()
    script = Path("work/script.txt").read_text(encoding="utf-8").strip()
    out = Path("work/thumbnail_brief.json")
    payload = {
        "model": os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-20b"),
        "temperature": 0.2,
        "max_tokens": 180,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": (
                "Create a concise YouTube thumbnail creative brief. Return ONLY valid JSON with keys "
                "hook (2-5 words, no clickbait), visual_focus (one of: security shield, AI chip, robot hand, "
                "neural network, data center, digital globe), and visual_reason (one sentence). Never invent facts."
            )},
            {"role": "user", "content": "Title: " + title + "\\nScript opening: " + script[:1400] +
                "\\nMake a distinctive topic-specific AI Tech Lab thumbnail concept, readable on a phone."}
        ]
    }
    try:
        response = chat_completion(payload, ".github/workflows/daily-content-research.yml", timeout=60)
        choices = response.get("choices") or []
        if not choices:
            raise RuntimeError("AI provider returned no choices.")
        content = str(choices[0].get("message", {}).get("content", ""))
        match = re.search(r"\\{.*\\}", content, re.S)
        brief = json.loads(match.group(0) if match else content)
        hook = re.sub(r"[^A-Za-z0-9 '&!?-]", "", str(brief.get("hook", ""))).strip()[:38]
        allowed = {"security shield", "AI chip", "robot hand", "neural network", "data center", "digital globe"}
        focus_raw = str(brief.get("visual_focus", "AI chip")).strip()
        focus = focus_raw if focus_raw.casefold() in {x.casefold() for x in allowed} else "AI chip"
        if not hook:
            raise ValueError("AI provider returned an empty thumbnail hook.")
        provider = str(response.get("provider", "groq"))
        result = {
            "provider": "Groq text inference" if provider == "groq" else "Cloudflare Workers AI fallback",
            "hook": hook,
            "visual_focus": focus,
            "visual_reason": str(brief.get("visual_reason", ""))[:220]
        }
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
    except Exception as exc:
        result = {
            "provider": "blocked",
            "hook": "",
            "visual_focus": "AI chip",
            "note": "Thumbnail brief generation failed safely: " + str(exc)[:180]
        }
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result))
        raise SystemExit("No validated thumbnail brief was available; the publishing pipeline must remain blocked.")


if __name__ == "__main__":
    main()
