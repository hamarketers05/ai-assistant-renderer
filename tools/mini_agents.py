#!/usr/bin/env python3
"""Shared, quota-aware specialist-agent policies for AI Tech Lab.

These are stage agents, not one separately billed model per role. They share the existing
Groq-primary / authenticated Workers AI fallback and only report tools when runtime evidence
exists. Production code changes are never made from untrusted web content.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

POLICY_VERSION = "1.0.0"
NY = ZoneInfo("America/New_York")
ROTATION_ANCHOR = date(2026, 10, 13)

EDITORIAL_CATEGORIES = [
    {
        "name": "AI News & Breakthroughs",
        "brief": "Verified launches, model changes, research breakthroughs, and what they actually change.",
        "keywords": ["announces", "launches", "released", "new model", "breakthrough", "openai", "anthropic", "gemini", "claude", "deepseek", "gpt-5", "llama", "model update"],
    },
    {
        "name": "AI Tools & Practical Workflows",
        "brief": "Useful AI tools, real workflow demos, and clear before/after value without invented testing.",
        "keywords": ["ai tool", "tool review", "workflow", "how to", "productivity", "copilot", "coding tool", "app launch", "image generator", "video generator"],
    },
    {
        "name": "AI Agents & Automation",
        "brief": "AI agents, computer-use systems, autonomous task execution, and real automation trade-offs.",
        "keywords": ["ai agent", "agents", "agentic", "autonomous task", "computer use", "multi-agent", "automation agent", "agent framework"],
    },
    {
        "name": "Robotics & Physical AI",
        "brief": "Robots, humanoids, autonomous machines, physical AI, and what they can demonstrably do.",
        "keywords": ["robot", "robotics", "humanoid", "physical ai", "self-driving", "autonomous vehicle", "robot arm", "factory robot"],
    },
    {
        "name": "AI, Jobs & Business",
        "brief": "Work, careers, companies, enterprise deployment, productivity, economics, and evidence-backed impact.",
        "keywords": ["jobs", "career", "workforce", "business", "enterprise", "layoffs", "salary", "labor market", "productivity at work", "economy"],
    },
    {
        "name": "AI Safety, Privacy & Cybersecurity",
        "brief": "Security, privacy, misuse, deepfakes, data protection, safety, and policy explained carefully.",
        "keywords": ["cybersecurity", "privacy", "data leak", "security flaw", "deepfake", "ai safety", "alignment", "prompt injection", "scam", "regulation"],
    },
    {
        "name": "Future Tech, Science & Predictions",
        "brief": "Evidence-grounded forecasts about AI, science, compute, and future technology; separate forecasts from facts.",
        "keywords": ["future of ai", "forecast", "prediction", "agi", "superintelligence", "quantum computing", "space technology", "scientific discovery", "2030", "future technology"],
    },
]

AGENT_PROFILES = [
    {
        "id": "research_scout", "name": "US Research Scout", "stage": "research",
        "purpose": "Gather current US YouTube topic signals and sourced web evidence.",
        "tools": ["YouTube Data API v3", "Tavily Search API"],
        "rules": ["Preserve source URLs and dates", "Separate source facts from model interpretation", "No unsupported statistics"],
    },
    {
        "id": "category_editor", "name": "Category Rotation Editor", "stage": "research",
        "purpose": "Apply the seven-day editorial rotation and permit only evidence-backed trend overrides.",
        "tools": ["US Eastern calendar", "YouTube trend evidence"],
        "rules": ["Do not repeat yesterday's category", "Default to scheduled category", "An override needs at least three distinct supporting trend videos"],
    },
    {
        "id": "scriptwriter", "name": "Human-Voice Scriptwriter", "stage": "research",
        "purpose": "Write a distinctive spoken-English narrative with a clear angle, story arc, and reasoned point of view.",
        "tools": ["Groq primary / Cloudflare Workers AI fallback"],
        "rules": ["No fake lived experience", "No robotic list-reading", "Vary sentence length and openings", "Distinguish opinion and prediction from fact"],
    },
    {
        "id": "fact_editor", "name": "Independent Fact and Hook Editor", "stage": "research",
        "purpose": "Audit factual claims, hook strength, unsupported language, and conversational flow.",
        "tools": ["Groq primary / Cloudflare Workers AI fallback", "Tavily source evidence"],
        "rules": ["Keep source links", "Qualify uncertain claims", "Reject ungrounded numbers and quotations"],
    },
    {
        "id": "improvement_scout", "name": "Free-Tool Improvement Scout", "stage": "research",
        "purpose": "Weekly review of official tool documentation and release notes for safe improvements.",
        "tools": ["Tavily Search API", "Official vendor documentation"],
        "rules": ["Prefer official sources", "Never install a package or service automatically", "Record candidate changes and free-tier risks"],
    },
    {
        "id": "voice_agent", "name": "Voice and Audio Director", "stage": "render",
        "purpose": "Produce natural US-English narration and verify timing, pauses, captions, and mix.",
        "tools": ["Kokoro", "Pydub", "Faster-Whisper", "Librosa", "FFmpeg", "Rubber Band when available"],
        "rules": ["Narration is a prerequisite for the render", "Trim excessive dead air without cutting meaning", "Keep speech intelligible over music"],
    },
    {
        "id": "visual_agent", "name": "Visual Research and Scene Director", "stage": "render",
        "purpose": "Match distinct scene visuals to narration and verify asset provenance and licensing.",
        "tools": ["Scene director", "Vecteezy API free-license gate", "Wikimedia/NASA eligible sources", "Pillow", "Cloudflare FLUX when available"],
        "rules": ["Do not use Pixabay or Pexels", "Do not invent data charts", "Do not count generated/downloaded assets unless used in the final render"],
    },
    {
        "id": "editing_agent", "name": "Cinematic Editor", "stage": "render",
        "purpose": "Assemble voice-aligned scenes, transitions, original music, captions, and restrained cinematic grade.",
        "tools": ["FFmpeg", "OpenCV", "NumPy", "SciPy", "Matplotlib when source-backed numbers exist", "ImageMagick", "Pillow"],
        "rules": ["Report actual tool use", "Skip only with a reason", "Never force an irrelevant chart or unlicensed clip"],
    },
    {
        "id": "thumbnail_seo_agent", "name": "Thumbnail and SEO Editor", "stage": "render",
        "purpose": "Create readable branded packaging, accurate metadata, and source-linked description.",
        "tools": ["Groq creative brief", "Pillow", "ImageMagick"],
        "rules": ["Avoid clickbait and unsupported claims", "Keep thumbnail text short", "Title promise must match the video"],
    },
    {
        "id": "qa_agent", "name": "Independent Production QA", "stage": "render",
        "purpose": "Check rendered files, timing, unique scenes, audio, visual coverage, and evidence manifests.",
        "tools": ["OpenCV", "FFprobe", "audio QA", "Groq video/vision review", "visual budget gate"],
        "rules": ["Fail closed on missing evidence", "Do not confuse planned assets with rendered assets", "Never publish a failed render"],
    },
    {
        "id": "publisher_agent", "name": "YouTube Publisher", "stage": "publish",
        "purpose": "Use the existing idempotent upload/schedule workflow and verify final YouTube state.",
        "tools": ["YouTube Data API v3", "GitHub Actions", "D1 idempotency/state"],
        "rules": ["Do not duplicate uploads", "Use validated output only", "Verify scheduledAt/status after upload"],
    },
    {
        "id": "learning_agent", "name": "Analytics and Learning Editor", "stage": "learn",
        "purpose": "Turn actual retention, CTR, QA findings, and audience feedback into future content improvements.",
        "tools": ["YouTube Analytics/review artifacts", "existing learning JSON"],
        "rules": ["Use observed data, not assumed performance", "Keep reusable lessons and repeat-issue avoidance", "Do not claim success without metrics"],
    },
]

NATURAL_VOICE_GUIDANCE = """NATURAL SPOKEN-VOICE RULES:
Write for a real person to say aloud, not for a report to be read. Open with a specific tension, surprising implication, or concrete question; do not use canned openings such as 'In today's fast-paced world', 'Let's dive in', or 'In this video'. Use a clear narrative thread rather than a list of facts. Mix short punchy sentences with longer explanatory ones. Use natural US-English contractions where they sound right, specific nouns and verbs, and occasional direct questions; do not add filler or fake drama. Include a defensible editorial take and, when evidence permits, one clearly labeled prediction. Make transitions logical rather than repeating 'however', 'more importantly', or 'the bottom line'. Never invent human experiences, testing, numbers, quotes, or certainty. Opinion, interpretation, and forecasts must be distinguishable from verified facts."""

GENERIC_OPENERS = (
    "in today's fast-paced world", "let's dive in", "in this video",
    "let's break it down", "without further ado", "the future is here",
    "ai is changing everything", "game changer", "revolutionize the way",
)

OFFICIAL_TOOL_SCOUTS = [
    {"tool": "GitHub Actions", "domain": "docs.github.com", "query": "site:docs.github.com/actions recent official release notes security workflow permissions least privilege"},
    {"tool": "Cloudflare Workers AI", "domain": "developers.cloudflare.com", "query": "site:developers.cloudflare.com/workers-ai latest official updates pricing limits models"},
    {"tool": "YouTube Data API v3", "domain": "developers.google.com", "query": "site:developers.google.com/youtube/v3 recent official updates quota videos list"},
    {"tool": "FFmpeg", "domain": "ffmpeg.org", "query": "site:ffmpeg.org official FFmpeg release notes filters encoding updates"},
    {"tool": "OpenCV", "domain": "docs.opencv.org", "query": "site:docs.opencv.org official OpenCV release notes video image processing"},
    {"tool": "Pillow", "domain": "pillow.readthedocs.io", "query": "site:pillow.readthedocs.io official Pillow release notes image processing"},
    {"tool": "Tavily Search API", "domain": "docs.tavily.com", "query": "site:docs.tavily.com official Tavily API updates limits search parameters"},
]


def parse_editorial_date(value: str | None = None) -> date:
    if value:
        return date.fromisoformat(value)
    return datetime.now(NY).date()


def category_rotation(target_date: str | date | None = None) -> dict:
    day = target_date if isinstance(target_date, date) else parse_editorial_date(target_date)
    index = (day - ROTATION_ANCHOR).days % len(EDITORIAL_CATEGORIES)
    chosen = EDITORIAL_CATEGORIES[index]
    next_day = day.fromordinal(day.toordinal() + 1)
    return {
        "date_us_eastern": day.isoformat(),
        "category": chosen["name"],
        "category_index": index,
        "category_brief": chosen["brief"],
        "rotation_anchor": ROTATION_ANCHOR.isoformat(),
        "next_date_us_eastern": next_day.isoformat(),
        "next_category": EDITORIAL_CATEGORIES[(index + 1) % len(EDITORIAL_CATEGORIES)]["name"],
        "cycle_length_days": len(EDITORIAL_CATEGORIES),
        "rotation_policy": "Calendar-deterministic US Eastern rotation; no database writes or extra AI request required.",
    }


def score_trend_categories(items: list[dict]) -> dict:
    scores = {}
    for cat in EDITORIAL_CATEGORIES:
        matched_video_ids = []
        weighted = 0
        for item in items:
            text = (str(item.get("title", "")) + " " + str(item.get("description_excerpt", ""))).casefold()
            hits = [kw for kw in cat["keywords"] if kw.casefold() in text]
            if hits:
                matched_video_ids.append(str(item.get("video_id") or item.get("url") or item.get("title") or len(matched_video_ids)))
                weighted += min(3, len(hits))
        scores[cat["name"]] = {"matching_video_count": len(set(matched_video_ids)), "score": weighted}
    return scores


def resolve_category(candidate: str, rotation: dict, items: list[dict]) -> dict:
    """Only allow a trend override when three distinct US trend videos strongly support it."""
    planned = str(rotation["category"])
    names = {x["name"] for x in EDITORIAL_CATEGORIES}
    candidate = candidate.strip() if isinstance(candidate, str) else ""
    if candidate not in names or candidate == planned:
        return {"category": planned, "rotation_category": planned, "override": False,
                "override_status": "not_requested" if candidate == planned or not candidate else "unknown_category_rejected",
                "evidence_scores": score_trend_categories(items)}
    scores = score_trend_categories(items)
    challenger = scores[candidate]
    baseline = scores[planned]
    if challenger["matching_video_count"] >= 3 and challenger["score"] >= baseline["score"] + 3:
        return {"category": candidate, "rotation_category": planned, "override": True,
                "override_status": "accepted_strong_live_trend", "evidence_scores": scores}
    return {"category": planned, "rotation_category": planned, "override": False,
            "override_status": "rejected_insufficient_live_trend_evidence", "evidence_scores": scores}


def evaluate_human_voice(script: str) -> dict:
    """Deterministic style lint: a useful warning signal, not a claim that prose sounds human."""
    text = re.sub(r"\s+", " ", str(script or "")).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    words = re.findall(r"\b[\w'-]+\b", text)
    lengths = [len(re.findall(r"\b[\w'-]+\b", s)) for s in sentences]
    lower = text.casefold()
    cliches = [phrase for phrase in GENERIC_OPENERS if phrase in lower]
    openers = []
    for sentence in sentences:
        token = re.findall(r"[A-Za-z0-9']+", sentence.lower())
        if token:
            openers.append(" ".join(token[:2]))
    counts = Counter(openers)
    repeated = sorted({phrase: count for phrase, count in counts.items() if count >= 3}.items(), key=lambda x: (-x[1], x[0]))
    contractions = len(re.findall(r"\b(?:isn't|aren't|wasn't|weren't|don't|doesn't|didn't|can't|couldn't|won't|wouldn't|shouldn't|it's|that's|there's|here's|they're|we're|you're|I've|we've|they've|you've|I'd|we'd|they'd|you'd|I'm|we'll|they'll|you'll)\b", text, re.I))
    cv = 0.0
    if len(lengths) >= 5 and statistics.mean(lengths) > 0:
        cv = statistics.pstdev(lengths) / statistics.mean(lengths)
    score = 100
    score -= min(30, len(cliches) * 10)
    score -= min(24, sum(max(0, count - 2) * 8 for _, count in repeated))
    if len(sentences) >= 12 and cv < 0.22:
        score -= 12
    if len(words) >= 450 and contractions < 3:
        score -= 8
    if len(words) >= 250 and not re.search(r"\b(my take|i suspect|i think|i'd argue|in my view|i expect|my read)\b", lower):
        score -= 6
    score = max(0, min(100, score))
    return {
        "score": score, "word_count": len(words), "sentence_count": len(sentences),
        "average_words_per_sentence": round(statistics.mean(lengths), 2) if lengths else 0,
        "sentence_length_coefficient_of_variation": round(cv, 3),
        "contractions_count": contractions, "generic_phrase_flags": cliches,
        "repeated_sentence_openers": [{"opening": phrase, "count": count} for phrase, count in repeated],
        "interpretation": "Heuristic review aid only; final voice quality must also be checked in rendered narration and audio QA.",
    }


def agent_execution_report(stage: str, runs: list[dict], metadata: dict | None = None) -> dict:
    by_id = {str(x.get("agent_id")): x for x in runs if isinstance(x, dict) and x.get("agent_id")}
    applicable = [p for p in AGENT_PROFILES if p["stage"] == stage]
    return {
        "schema_version": POLICY_VERSION,
        "stage": stage,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
        "agents": [
            {**profile, **by_id.get(profile["id"], {
                "status": "not_run_in_this_stage", "actual_tools_used": [],
                "evidence_files": [], "note": "No runtime evidence supplied for this role in the current stage.",
            })}
            for profile in applicable
        ],
        "policy": "A tool is marked used only when this stage supplies runtime evidence; role definitions alone are not proof of execution.",
    }


def weekly_tool_scout_plan(target_date: str | date | None = None) -> dict:
    day = target_date if isinstance(target_date, date) else parse_editorial_date(target_date)
    if day.weekday() != 6:
        return {"enabled": False, "reason": "Runs once per US Sunday to conserve the free Tavily allocation.", "tool": None}
    week_index = max(0, (day - ROTATION_ANCHOR).days // 7) % len(OFFICIAL_TOOL_SCOUTS)
    return {"enabled": True, **OFFICIAL_TOOL_SCOUTS[week_index],
            "reason": "Weekly official-documentation review; this scout never installs dependencies or edits production code."}


def self_test() -> dict:
    day1 = category_rotation("2026-10-13")
    day2 = category_rotation("2026-10-14")
    cycle = [category_rotation(date.fromordinal(ROTATION_ANCHOR.toordinal() + i))["category"] for i in range(7)]
    if day1["category"] != "AI News & Breakthroughs" or day2["category"] != "AI Tools & Practical Workflows":
        raise SystemExit("Seven-day category anchor test failed.")
    if len(set(cycle)) != 7 or category_rotation("2026-10-20")["category"] != day1["category"]:
        raise SystemExit("Seven-day category rotation test failed.")
    weak_items = [{"video_id": str(i), "title": "AI model explainer", "description_excerpt": ""} for i in range(2)]
    weak = resolve_category("Robotics & Physical AI", day1, weak_items)
    if weak["override"]:
        raise SystemExit("Category override accepted without sufficient trend evidence.")
    strong_items = [
        {"video_id": "1", "title": "Humanoid robot demonstration"},
        {"video_id": "2", "title": "Robotics lab tests a new robot"},
        {"video_id": "3", "title": "Physical AI robot system explained"},
    ]
    strong = resolve_category("Robotics & Physical AI", day1, strong_items)
    if not strong["override"]:
        raise SystemExit("Strong live-trend category override did not pass its evidence gate.")
    natural = evaluate_human_voice("My take is that the change matters most when it saves people time. The detail that surprised me is how many practical constraints remain. I suspect the next step will be less dramatic than the headlines suggest, but more useful in everyday work. What would that look like for a small team? It depends on the evidence, and that is exactly why the caveats matter.")
    robotic = evaluate_human_voice(("In today's fast-paced world, AI is changing everything. Let's dive in. " * 12))
    if natural["score"] <= robotic["score"] or robotic["generic_phrase_flags"] == []:
        raise SystemExit("Natural-voice heuristic boundary test failed.")
    if len(AGENT_PROFILES) < 10:
        raise SystemExit("Specialist agent registry is unexpectedly incomplete.")
    return {
        "status": "self_test_passed", "policy_version": POLICY_VERSION,
        "agent_profiles": len(AGENT_PROFILES), "editorial_categories": len(EDITORIAL_CATEGORIES),
        "category_anchor": {"today": day1["category"], "tomorrow": day2["category"]},
        "checks": ["seven-day rotation", "evidence-gated trend override", "natural-voice heuristic", "specialist-agent registry"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--show-rotation", default="")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False))
        return
    if args.show_rotation:
        print(json.dumps(category_rotation(args.show_rotation), ensure_ascii=False, indent=2))
        return
    parser.error("choose --self-test or --show-rotation YYYY-MM-DD")


if __name__ == "__main__":
    main()
