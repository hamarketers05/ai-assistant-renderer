#!/usr/bin/env python3
"""Generate a sourced, topic-specific thumbnail brief with Groq primary and Workers AI fallback."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from ai_text_client import chat_completion


ALLOWED_FOCI = {
    "security shield", "AI chip", "robot hand", "neural network",
    "data center", "digital globe",
}
GENERIC_HOOKS = {
    "ai explained", "future of ai", "the future", "game changer",
    "ai changes everything", "the next big thing",
}


def main() -> None:
    title = Path("work/title.txt").read_text(encoding="utf-8").strip()
    script = Path("work/script.txt").read_text(encoding="utf-8").strip()
    category = os.getenv("EDITORIAL_CATEGORY", "").strip()
    package_path = Path("work/daily_content_package.json")
    if package_path.is_file():
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
            category = category or str(package.get("editorial_category", "")).strip()
        except (OSError, json.JSONDecodeError):
            pass
    if not title or not script:
        raise SystemExit("Topic-specific thumbnail brief blocked: title or script is missing.")

    out = Path("work/thumbnail_brief.json")
    payload = {
        "model": os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-20b"),
        "temperature": 0.2,
        "max_tokens": 180,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Create a concise, category-specific YouTube thumbnail creative brief for AI Tech Lab. "
                    "Return only one JSON object with keys hook, visual_focus, visual_reason. "
                    "hook must contain two to five short, readable words tied to this exact story tension, never generic AI hype. "
                    "visual_focus must be exactly one of: security shield, AI chip, robot hand, neural network, data center, digital globe. "
                    "Never invent numbers, product features, or imagery that implies a result not established by the narration. "
                    "Choose the focal object and composition from the category and actual title: security/privacy uses shield-threat contrast; "
                    "robotics uses a robot form; agents/automation uses a network or machine interface; hardware/compute uses chip or data center; "
                    "science/future uses a digital globe or neural system. Keep one focal object, premium cinematic contrast, negative space for text, "
                    "and no fake UI, fake charts, fake metrics or misleading competitor comparisons."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Editorial category: " + category + "\n"
                    "Exact video title: " + title + "\n"
                    "Narration opening and story context:\n" + script[:1800] + "\n"
                    "Return one distinctive thumbnail hook and visual focus that could not be reused unchanged for an unrelated AI video."
                ),
            },
        ],
    }
    try:
        response = chat_completion(
            payload, ".github/workflows/daily-content-research.yml", timeout=60
        )
        choices = response.get("choices") or []
        if not choices:
            raise RuntimeError("AI provider returned no choices.")
        raw = str(choices[0].get("message", {}).get("content", "")).strip()
        try:
            brief = json.loads(raw)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.S)
            if not match:
                raise RuntimeError("AI provider returned invalid thumbnail JSON.")
            brief = json.loads(match.group(0))
        hook = re.sub(r"[^A-Za-z0-9 '&!?-]", "", str(brief.get("hook", ""))).strip()
        hook_words = re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", hook)
        hook = " ".join(hook_words[:5])
        if len(hook_words) < 2:
            raise ValueError("Thumbnail hook must contain at least two readable words.")
        if hook.casefold() in GENERIC_HOOKS:
            raise ValueError("Thumbnail hook is too generic; regenerate with the story-specific angle.")
        focus_raw = str(brief.get("visual_focus", "")).strip()
        focus = next((x for x in ALLOWED_FOCI if x.casefold() == focus_raw.casefold()), "")
        if not focus:
            raise ValueError("Thumbnail visual focus is missing or outside the approved set.")
        reason = re.sub(r"\s+", " ", str(brief.get("visual_reason", "")).strip())[:300]
        if len(reason) < 15:
            raise ValueError("Thumbnail reasoning is too short to verify story relevance.")
        provider = str(response.get("provider", "groq"))
        result = {
            "provider": "Groq text inference" if provider == "groq" else "Cloudflare Workers AI fallback",
            "hook": hook,
            "editorial_category": category,
            "visual_focus": focus,
            "visual_reason": reason,
            "story_title": title,
            "validation": {
                "hook_word_count": len(hook.split()),
                "topic_specific_title_present": True,
                "generic_hook_rejected": False,
            },
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        # If both hosted AI routes are unavailable (for example, a missing GitHub
        # GROQ_API_KEY and no authenticated Workers AI context), use a conservative,
        # deterministic story-derived brief. This is explicitly labelled non-AI and
        # still passes through the normal thumbnail asset/visual QA gates.
        title_low = title.casefold()
        script_low = script[:2400].casefold()
        if any(term in title_low + " " + script_low for term in ("security", "privacy", "risk", "cyber", "safety", "oversight", "threat")):
            hook, focus = "AI NEEDS GUARDRAILS", "security shield"
            reason = "The title and narration emphasize risks, safety, privacy, or human oversight; a shield makes that tension visible."
        elif any(term in title_low + " " + script_low for term in ("agent", "automation", "workflow", "autonomous")):
            hook, focus = "WHO CONTROLS AI?", "neural network"
            reason = "The story concerns autonomous agents or automation; a network represents delegated decisions and oversight."
        elif any(term in title_low + " " + script_low for term in ("robot", "humanoid", "robotics")):
            hook, focus = "ROBOTS ARE HERE", "robot hand"
            reason = "The title and narration focus on robotics, so a robot visual directly represents the subject."
        elif any(term in title_low + " " + script_low for term in ("chip", "gpu", "processor", "compute")):
            hook, focus = "THE AI CHIP RACE", "AI chip"
            reason = "The title and narration focus on AI compute hardware, so a chip is the clearest subject cue."
        elif any(term in title_low + " " + script_low for term in ("data center", "datacenter", "server")):
            hook, focus = "INSIDE AI COMPUTE", "data center"
            reason = "The title and narration focus on infrastructure, so a data-center visual directly fits the subject."
        else:
            hook, focus = "THE AI SHIFT", "digital globe"
            reason = "A restrained technology visual is used because a topic-specific AI brief could not be generated."
        hook_words = re.findall(r"[A-Za-z0-9]+(?:['-][A-Za-z0-9]+)*", hook)
        result = {
            "provider": "deterministic local fallback (AI provider unavailable)",
            "hook": hook,
            "editorial_category": category,
            "visual_focus": focus,
            "visual_reason": reason,
            "story_title": title,
            "fallback_reason": str(exc)[:180],
            "validation": {
                "hook_word_count": len(hook_words),
                "topic_specific_title_present": True,
                "generic_hook_rejected": False,
                "non_ai_fallback": True,
            },
        }
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
        print("WARNING: deterministic thumbnail brief used; video QA must independently validate the final thumbnail.")


if __name__ == "__main__":
    main()
