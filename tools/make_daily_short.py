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
        "response_format": {"type": "json_object"},
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
    try:
        result = parse_json(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError, ValueError, RuntimeError) as exc:
        raise SystemExit("Short AI response was not valid JSON; no Short was released. Details: " + type(exc).__name__) from None
    if not isinstance(result, dict):
        raise SystemExit("Short AI response was not a JSON object; no Short was released.")
    short_title = re.sub(r"\s+", " ", str(result.get("title", "")).strip())[:85]
    short_text = re.sub(r"\r\n?", "\n", str(result.get("script", "")).strip())
    words = len(re.findall(r"\b[\w'-]+\b", short_text))

    # Free fallback models can return a good idea in too few words. Repair additively
    # and keep the original, evidence-grounded narration intact wherever possible.
    if words < 100:
        original_short = short_text
        segment_prompt = (
            "You are editing a 45-60 second English YouTube Short for a US audience. "
            "Return JSON with exactly one key: segment. Write an ADDITIVE middle segment of 55-75 spoken words. "
            "Do not rewrite, repeat, or summarize the existing narration. Add practical viewer value with one "
            "specific decision tip, real-world implication, or trade-off tied to the supplied sources. "
            "Use no unsupported facts, statistics, dates, quotes, capabilities, product tests, or personal experience. "
            "No heading, bullets, CTA, or production notes. The segment must flow between the supplied narration "
            "and its final CTA."
        )
        segment_input = {
            "title": short_title,
            "existing_short_script": original_short,
            "full_long_script": script,
            "sources": [{"title": x.get("title", ""), "url": x.get("url", ""),
                         "evidence": str(x.get("content", ""))[:350]} for x in sources[:8]],
        }
        for repair_attempt in range(2):
            try:
                repair_data = chat_completion({
                    "model": MODEL, "temperature": 0.15, "max_tokens": 650,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": segment_prompt if repair_attempt == 0 else (
                            "Return JSON with exactly one key: segment. Add a concise 25-40 word spoken narration "
                            "bridge to the supplied YouTube Short. Add one useful implication or next step supported "
                            "by the source evidence. Do not repeat prior lines or create facts. No CTA, heading, or bullets."
                        )},
                        {"role": "user", "content": json.dumps(segment_input, ensure_ascii=False)}
                    ]
                }, ".github/workflows/daily-auto-production.yml", timeout=90)
                if not repair_data or not repair_data.get("choices"):
                    raise RuntimeError("AI provider returned no Short expansion.")
                segment_result = parse_json(repair_data["choices"][0]["message"]["content"])
                segment = re.sub(r"\s+", " ", str(segment_result.get("segment", "")).strip())
                segment_words = len(re.findall(r"\b[\w'-]+\b", segment))
                if repair_attempt == 0 and segment_words < 25:
                    continue
                sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", original_short) if x.strip()]
                if len(sentences) >= 2:
                    candidate = " ".join(sentences[:-1]) + " " + segment + " " + sentences[-1]
                else:
                    candidate = original_short.rstrip() + " " + segment
                candidate_words = len(re.findall(r"\b[\w'-]+\b", candidate))
                if 100 <= candidate_words <= 135:
                    short_text, words = candidate, candidate_words
                    print(f"Short length repair passed: {words} words ({segment_words} added words).")
                    break
                if candidate_words < 100 and repair_attempt == 0:
                    segment_input["prior_addition"] = segment
                    segment_input["current_candidate"] = candidate
                    continue
                if candidate_words > 135:
                    sentences2 = [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", candidate) if x.strip()]
                    # Preserve the original CTA/final sentence while trimming only complete middle sentences.
                    final_sentence = sentences2[-1] if sentences2 else ""
                    kept, running = [], 0
                    for sentence in sentences2[:-1]:
                        count = len(re.findall(r"\b[\w'-]+\b", sentence))
                        final_count = len(re.findall(r"\b[\w'-]+\b", final_sentence))
                        if running + count + final_count > 135:
                            break
                        kept.append(sentence)
                        running += count
                    trimmed = " ".join(kept + ([final_sentence] if final_sentence else []))
                    trimmed_words = len(re.findall(r"\b[\w'-]+\b", trimmed))
                    if 100 <= trimmed_words <= 135:
                        short_text, words = trimmed, trimmed_words
                        print(f"Short length repair passed after safe sentence trim: {words} words.")
                        break
            except Exception as repair_error:
                print("Short length repair attempt " + str(repair_attempt + 1) + " failed (" + type(repair_error).__name__ + ").")
        if words < 100:
            # Deterministic editorial fallback: practical advice, not invented product facts.
            editorial = str(package.get("editorial_category", "")).casefold()
            topic_text = (short_title + " " + title).casefold()
            if "agent" in editorial or "automation" in editorial or "automation" in topic_text or "agent" in topic_text:
                safe_segment = (
                    "Here’s a practical way to reduce that risk: start with one low-stakes task, define what a "
                    "correct result looks like, and compare each output with a trusted baseline. Give the system "
                    "only the access it needs, and keep human approval for actions involving money, private data, "
                    "or customers. Track mistakes as well as time saved over repeated attempts. If you cannot trace "
                    "an answer to reliable evidence, treat it as a draft—not a decision. Automation works best "
                    "when responsibility stays clear."
                )
            elif "tool" in editorial or "workflow" in editorial:
                safe_segment = (
                    "Before adopting any AI tool, test it on a small task you can check independently. Compare its "
                    "answer with your current method, note time saved, and watch for mistakes, hidden costs, or "
                    "extra cleanup. Keep sensitive information out until you have checked the tool’s data rules. "
                    "One impressive demo is not enough; repeat the test with different inputs before trusting it "
                    "with routine work. Choose the tool that reliably improves the process you actually use."
                )
            else:
                safe_segment = (
                    "To judge what this means for you, separate verified details from predictions and check the "
                    "original source before acting. Ask which real task changes today, what limitations remain, and "
                    "what evidence would change your mind. Try a small, reversible test where possible, and compare "
                    "the result with a method you already trust. Watch for reliability, privacy, and extra work—not "
                    "just impressive demos. A useful takeaway should help you make a better decision, not merely "
                    "feel excited about new technology."
                )
            base_script = original_short
            base_sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", base_script) if x.strip()]
            last_sentence = base_sentences[-1] if len(base_sentences) >= 2 else ""
            leading_sentences = base_sentences[:-1] if len(base_sentences) >= 2 else base_sentences
            segment_sentences = [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", safe_segment) if x.strip()]
            existing_words = len(re.findall(r"\b[\w'-]+\b", " ".join(leading_sentences + ([last_sentence] if last_sentence else []))))
            budget = 135 - existing_words
            selected, selected_count = [], 0
            for sentence in segment_sentences:
                sentence_count = len(re.findall(r"\b[\w'-]+\b", sentence))
                if selected_count + sentence_count > budget:
                    break
                selected.append(sentence)
                selected_count += sentence_count
            parts = leading_sentences + ([" ".join(selected)] if selected else []) + ([last_sentence] if last_sentence else [])
            candidate = " ".join(x for x in parts if x).strip()
            candidate_words = len(re.findall(r"\b[\w'-]+\b", candidate))
            if 100 <= candidate_words <= 135 and selected_count >= 35:
                short_text, words = candidate, candidate_words
                print(f"Deterministic practical-value fallback passed: {words} words; added {selected_count} guidance words.")
            else:
                print(f"Short expansion remained below target ({words} words; safe fallback would be {candidate_words}); final QA will block it.")
    elif words > 135:
        try:
            compact_data = chat_completion({
                "model": MODEL, "temperature": 0.15, "max_tokens": 700,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": (
                        "Edit this YouTube Short to exactly 110-125 spoken words. Preserve its source-supported core, "
                        "natural US English, one useful takeaway, and the final CTA. Remove repetition only. Do not add "
                        "facts or personal experience. Return JSON with exactly one key: script."
                    )},
                    {"role": "user", "content": json.dumps({"title": short_title, "script": short_text,
                        "sources": [{"title": x.get("title", ""), "url": x.get("url", ""),
                                     "evidence": str(x.get("content", ""))[:300]} for x in sources[:8]],
                        "long_script": script}, ensure_ascii=False)}
                ]
            }, ".github/workflows/daily-auto-production.yml", timeout=90)
            compact_result = parse_json(compact_data["choices"][0]["message"]["content"])
            compact_text = re.sub(r"\r\n?", "\n", str(compact_result.get("script", "")).strip())
            compact_words = len(re.findall(r"\b[\w'-]+\b", compact_text))
            if 100 <= compact_words <= 135:
                short_text, words = compact_text, compact_words
                print(f"Short compacted to {words} words.")
        except Exception as compact_error:
            print("Short compaction failed (" + type(compact_error).__name__ + "); length gate remains active.")

    # Last-resort recovery: reuse sentences from the already fact-checked long script
    # rather than failing or inventing a new claim when free AI inference under-runs.
    if short_title and not 100 <= words <= 135:
        original_sentences = [
            re.sub(r"\s+", " ", part).strip()
            for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", script)
            if part.strip()
        ]
        short_sentences = [
            re.sub(r"\s+", " ", part).strip()
            for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", short_text)
            if part.strip()
        ]
        if short_sentences and original_sentences:
            from difflib import SequenceMatcher
            existing_norm = {re.sub(r"[^a-z0-9]+", " ", part.lower()).strip() for part in short_sentences}
            title_terms = set(re.findall(r"[a-z0-9]{3,}", short_title.lower()))
            short_terms = set(re.findall(r"[a-z0-9]{3,}", short_text.lower()))
            stop_terms = {"the", "and", "for", "that", "this", "with", "you", "your", "are", "but", "not", "what", "how", "why", "from"}
            anchor_terms = (title_terms | short_terms) - stop_terms
            candidates = []
            for idx, sentence in enumerate(original_sentences):
                normalized = re.sub(r"[^a-z0-9]+", " ", sentence.lower()).strip()
                if not normalized or normalized in existing_norm:
                    continue
                if any(SequenceMatcher(None, normalized, existing).ratio() >= 0.78 for existing in existing_norm if existing):
                    continue
                terms = set(re.findall(r"[a-z0-9]{3,}", normalized)) - stop_terms
                overlap = len(terms & anchor_terms)
                sentence_words = len(re.findall(r"\b[\w'-]+\b", sentence))
                if overlap and 8 <= sentence_words <= 42:
                    candidates.append((overlap / max(1, len(terms)) + min(overlap, 5) * 0.08, idx, sentence, sentence_words))
            candidates.sort(key=lambda item: (item[0], -item[1]), reverse=True)
            insertion = max(0, len(short_sentences) - 1)  # preserve the original final CTA/closing sentence
            selected = []
            current_words = words
            for _, _, sentence, sentence_words in candidates:
                if current_words + sentence_words > 132:
                    continue
                selected.append(sentence)
                current_words += sentence_words
                if 105 <= current_words <= 132:
                    break
            if 100 <= current_words <= 135 and selected:
                short_sentences[insertion:insertion] = selected
                short_text = " ".join(short_sentences)
                words = len(re.findall(r"\b[\w'-]+\b", short_text))
                if 100 <= words <= 135:
                    print("Short recovery passed using only non-duplicated sentences from the fact-checked long script: " + str(words) + " words.")
                else:
                    print("Source-script Short recovery did not hit the word-count gate; no rendered Short will be released.")
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
