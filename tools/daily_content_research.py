#!/usr/bin/env python3
"""Daily US-topic workflow: YouTube Data API v3 signals -> Tavily evidence -> Groq script + hook audit."""
from __future__ import annotations
import argparse, json, os, re, time, urllib.error, urllib.parse, urllib.request
from ai_text_client import chat_completion
from datetime import datetime, timedelta, timezone
from pathlib import Path
from mini_agents import (EDITORIAL_CATEGORIES, NATURAL_VOICE_GUIDANCE, agent_execution_report,
                         category_rotation, evaluate_human_voice, parse_editorial_date,
                         resolve_category, title_similarity_ratio, weekly_tool_scout_plan)

WORK = Path("work")
_LAST_GROQ_START = 0.0
_AI_CALL_LOG = []
TEXT_MODEL = os.getenv("GROQ_TEXT_MODEL", "openai/gpt-oss-20b")
YOUTUBE_API = "https://www.googleapis.com/youtube/v3/videos"
TAVILY_API = "https://api.tavily.com/search"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"

def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

def request_json(url, payload=None, headers=None, timeout=45):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    hdrs = {"Accept": "application/json", "User-Agent": "AI-Tech-Lab-Free-Research/1.0"}
    if payload is not None:
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                body = json.loads(exc.read().decode("utf-8"))
                detail = str(body.get("error", body.get("message", body)))[:260]
            except Exception:
                detail = "provider returned an unreadable error body"
            if (exc.code == 429 or exc.code >= 500) and attempt < 2:
                retry_after = exc.headers.get("Retry-After", "3")
                try:
                    delay = min(20, max(2, int(float(retry_after))))
                except ValueError:
                    delay = 3 * (attempt + 1)
                time.sleep(delay)
                continue
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            if attempt < 2:
                time.sleep(2 + 2 * attempt)
                continue
            raise RuntimeError(f"Request failed safely after retries: {type(exc).__name__}") from None
    raise RuntimeError("Request did not complete after retries.")

def extract_json(text):
    text = str(text).strip()
    lines = text.splitlines()
    if lines and lines[0].lstrip().startswith(chr(96) * 3):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith(chr(96) * 3):
        lines = lines[:-1]
    text = "\n".join(lines).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise RuntimeError("Groq returned no JSON object.")
        obj = json.loads(match.group(0))
    if not isinstance(obj, dict):
        raise RuntimeError("Groq response was not a JSON object.")
    return obj

def groq_json(system, user, max_tokens=2500, temperature=0.25):
    global _LAST_GROQ_START
    key = os.getenv("GROQ_API_KEY", "").strip()
    body = {"model": TEXT_MODEL, "temperature": temperature, "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system + "\\nReturn exactly one valid JSON object, with no Markdown fences."},
                {"role": "user", "content": user}]}
    if key:
        wait_seconds = 61.0 - (time.monotonic() - _LAST_GROQ_START) if _LAST_GROQ_START else 0.0
        if wait_seconds > 0:
            print(f"Respecting free-tier Groq TPM budget; spacing model calls by {int(wait_seconds)} seconds.")
            time.sleep(wait_seconds)
        _LAST_GROQ_START = time.monotonic()
    result = chat_completion(body, ".github/workflows/daily-content-research.yml", timeout=90)
    provider = str(result.get("provider", "groq"))
    _AI_CALL_LOG.append({"provider": provider, "workflow_path": ".github/workflows/daily-content-research.yml"})
    choices = result.get("choices") or []
    if not choices:
        raise RuntimeError(provider + " returned no completion choices.")
    print("AI provider for research step: " + provider)
    return extract_json(choices[0].get("message", {}).get("content", ""))

def duration_seconds(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", value or "")
    if not match:
        return 0
    h, m, s = match.groups()
    return int(h or 0) * 3600 + int(m or 0) * 60 + float(s or 0)

def worker_youtube_trending_fallback():
    """Use the existing authenticated Main Worker YouTube Data API search integration if chart=list fails."""
    token = os.getenv("WORKER_AUTH_TOKEN", "").strip()
    worker_url = os.getenv("WORKER_URL", "https://dark-sunset-a2a1.hamarketers05.workers.dev").rstrip("/")
    if not token:
        raise RuntimeError("YouTube chart failed and the authenticated Main Worker fallback is unavailable.")
    params = urllib.parse.urlencode({
        "brand": "AI_TECH_LAB",
        "q": "latest AI news, AI tools, technology breakthroughs and future technology videos in the United States"
    })
    result = request_json(
        worker_url + "/admin/research-self-test?" + params,
        headers={"Authorization": "Bearer " + token},
        timeout=100
    )
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Main Worker YouTube search fallback did not pass its research self-test.")

    rows = []
    seen = set()

    def video_id_from_url(value):
        try:
            parsed = urllib.parse.urlparse(str(value or ""))
            host = (parsed.hostname or "").lower()
            if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"}:
                return ""
            if host.endswith("youtu.be"):
                candidate = parsed.path.strip("/").split("/")[0]
            elif parsed.path == "/watch":
                candidate = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
            elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
                candidate = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
            else:
                candidate = ""
            return candidate if re.fullmatch(r"[A-Za-z0-9_-]{6,}", str(candidate)) else ""
        except (TypeError, ValueError):
            return ""

    def add_row(item, default_category="Science & Technology"):
        if not isinstance(item, dict):
            return
        url = str(item.get("url", item.get("source_url", "")) or "").strip()
        video_id = video_id_from_url(url)
        title = re.sub(r"\s+", " ", str(item.get("title", "") or "")).strip()
        if not video_id or not title or video_id in seen:
            return
        seen.add(video_id)
        try:
            views = int(item.get("view_count", item.get("views", 0)) or 0)
        except (TypeError, ValueError):
            views = 0
        try:
            likes = int(item.get("like_count", item.get("likes", 0)) or 0)
        except (TypeError, ValueError):
            likes = 0
        try:
            velocity = int(item.get("views_per_hour", 0) or 0)
        except (TypeError, ValueError):
            velocity = 0
        rows.append({
            "video_id": video_id,
            "category": default_category,
            "title": title[:220],
            "channel": str(item.get("channel", item.get("publisher", "")) or "")[:100],
            "published_at": str(item.get("published_at", item.get("published_date", "")) or ""),
            "description_excerpt": re.sub(r"\s+", " ", str(item.get("content", item.get("description", "")) or ""))[:260],
            "duration_seconds": round(duration_seconds(str(item.get("duration", ""))), 1) if str(item.get("duration", "")).startswith("PT") else 0,
            "view_count": views,
            "likes": likes,
            "views_per_hour": velocity,
            "url": url if url.startswith("https://") else "https://www.youtube.com/watch?v=" + video_id
        })

    for item in result.get("evidence", []) if isinstance(result.get("evidence", []), list) else []:
        add_row(item)
    candidates = result.get("recommended_topics", [])
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            signals = candidate.get("trend_evidence", [])
            if isinstance(signals, list):
                for item in signals:
                    add_row(item)
    if len(rows) < 5:
        raise RuntimeError(
            "YouTube Data API mostPopular failed and the authenticated Main Worker returned only "
            + str(len(rows)) + " usable YouTube video signals; refusing to fabricate trend evidence."
        )
    print("Trend source: authenticated Main Worker YouTube Data API search fallback; mostPopular chart unavailable.")
    return rows[:30]


def youtube_trending(api_key, access_token=""):
    # Preferred signal: YouTube Data API v3 videos.list chart=mostPopular (two US categories).
    all_items = []
    last_error = None
    for category, label in (("28", "Science & Technology"), ("27", "Education")):
        params = {
            "part": "snippet,statistics,contentDetails", "chart": "mostPopular",
            "regionCode": "US", "videoCategoryId": category, "maxResults": 25}
        headers = {}
        if access_token:
            headers["Authorization"] = "Bearer " + access_token
        elif api_key:
            params["key"] = api_key
        else:
            raise RuntimeError("YouTube Data API v3 requires the existing OAuth access token or API key.")
        try:
            data = request_json(YOUTUBE_API + "?" + urllib.parse.urlencode(params), headers=headers, timeout=35)
        except RuntimeError as exc:
            last_error = exc
            if access_token and api_key:
                try:
                    params["key"] = api_key
                    data = request_json(YOUTUBE_API + "?" + urllib.parse.urlencode(params), timeout=35)
                except RuntimeError as key_exc:
                    last_error = key_exc
                    break
            else:
                break
        for item in data.get("items", []):
            snippet, stats = item.get("snippet", {}), item.get("statistics", {})
            video_id = str(item.get("id", ""))
            views = int(stats.get("viewCount", 0) or 0)
            all_items.append({
                "video_id": video_id, "category": label,
                "title": str(snippet.get("title", ""))[:220],
                "channel": str(snippet.get("channelTitle", ""))[:100],
                "published_at": snippet.get("publishedAt", ""),
                "description_excerpt": re.sub(r"\s+", " ", str(snippet.get("description", "")))[:260],
                "duration_seconds": round(duration_seconds(item.get("contentDetails", {}).get("duration", "")), 1),
                "view_count": views, "likes": int(stats.get("likeCount", 0) or 0),
                "url": "https://www.youtube.com/watch?v=" + video_id})
    if len(all_items) >= 5:
        return all_items
    try:
        return worker_youtube_trending_fallback()
    except Exception as fallback_exc:
        original = str(last_error or "YouTube chart returned too few trend signals")[:220]
        fallback = str(fallback_exc)[:260]
        raise RuntimeError("YouTube trend collection failed safely. chart_error=" + original + "; worker_fallback=" + fallback) from None

def tavily_search(key, query, include_domains=None):
    """Search Tavily directly when its key is present; otherwise use the authenticated main Worker proxy.

    The Worker keeps its existing Tavily secret in Cloudflare, so GitHub does not need a duplicate key.
    """
    if key:
        payload = {
            "api_key": key, "query": query, "search_depth": "advanced", "topic": "general",
            "max_results": 6, "include_answer": False, "include_raw_content": False}
        if include_domains:
            payload["include_domains"] = include_domains
        result = request_json(TAVILY_API, payload, timeout=60)
        return result.get("results", []) if isinstance(result, dict) else []

    token = os.getenv("WORKER_AUTH_TOKEN", "").strip()
    worker_url = os.getenv("WORKER_URL", "https://dark-sunset-a2a1.hamarketers05.workers.dev").rstrip("/")
    if not token:
        raise RuntimeError("Tavily key is absent and authenticated main Worker research proxy is unavailable.")
    url = worker_url + "/research?" + urllib.parse.urlencode({
        "q": str(query)[:400], "brand_id": "AI_TECH_LAB"
    })
    result = request_json(url, headers={"Authorization": "Bearer " + token}, timeout=90)
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("Authenticated main Worker research proxy returned an unsuccessful response.")
    rows = result.get("results", [])
    normalized = []
    allowed_domains = [str(x).lower().strip().lstrip(".") for x in (include_domains or []) if str(x).strip()]
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            continue
        url_value = str(item.get("url", "")).strip()
        try:
            host = (urllib.parse.urlparse(url_value).hostname or "").lower()
        except ValueError:
            host = ""
        if allowed_domains and not any(host == d or host.endswith("." + d) for d in allowed_domains):
            continue
        normalized.append({
            "title": item.get("title", ""), "url": url_value,
            "content": item.get("content", ""),
            "published_date": item.get("published_at", item.get("published_date", "")) or "",
            "score": item.get("score", 0), "source_tier": item.get("source_tier", "unknown"),
            "source_type": item.get("source_type", "unknown")
        })
    if not normalized:
        raise RuntimeError("Authenticated main Worker research proxy returned no usable source results.")
    print("Research evidence provider: existing Cloudflare main Worker -> Tavily secret binding.")
    return normalized

def clean_sources(results):
    out, seen = [], set()
    for item in results:
        url = str(item.get("url", "")).strip()
        title = re.sub(r"\s+", " ", str(item.get("title", "")).strip())
        content = re.sub(r"\s+", " ", str(item.get("content", "")).strip())
        if not url.startswith("https://") or url in seen or not title or not content:
            continue
        seen.add(url)
        out.append({"title": title[:220], "url": url[:1000], "content": content[:1100],
                    "published_date": str(item.get("published_date", ""))[:60], "score": item.get("score")})
        if len(out) >= 10:
            break
    return out

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-topic", default="", help="Optional direction; current US trend evidence is still evaluated.")
    parser.add_argument("--target-date", default="", help="Optional date label for reproducible manual runs.")
    parser.add_argument("--outdir", default="work")
    args = parser.parse_args()
    yt_key = os.getenv("YOUTUBE_API_KEY", "").strip()
    yt_token = os.getenv("YOUTUBE_ACCESS_TOKEN", "").strip()
    tv_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not yt_key and not yt_token:
        raise SystemExit("YouTube Data API v3 authentication is missing: the existing Worker OAuth token or YOUTUBE_API_KEY is required.")
    if not tv_key and not os.getenv("WORKER_AUTH_TOKEN", "").strip():
        raise SystemExit("Neither TAVILY_API_KEY nor the authenticated main Worker research proxy is configured.")
    if not os.getenv("GROQ_API_KEY", "").strip():
        if not (os.getenv("GITHUB_TOKEN", "").strip() and os.getenv("GITHUB_RUN_ID", "").isdigit()):
            raise SystemExit("Groq is missing and authenticated Cloudflare Workers AI fallback context is unavailable.")
        print("GROQ_API_KEY is absent; authenticated Cloudflare Workers AI fallback will be used. Daily free-neuron limits apply.")

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    research_date_us_eastern = parse_editorial_date()
    # Research runs the evening before the US publish slot, so rotate for the actual
    # scheduled publish date rather than the date on which a script happens to be generated.
    editorial_date = args.target_date or (research_date_us_eastern + timedelta(days=1)).isoformat()
    rotation = category_rotation(editorial_date)
    scout_plan = weekly_tool_scout_plan(research_date_us_eastern)
    review = read_json(Path("learning/latest_video_review.json"), {})
    learning = {
        "last_title": review.get("title", ""),
        "decision": review.get("decision", "NONE"),
        "top_improvements": review.get("top_improvements", [])[:5] if isinstance(review.get("top_improvements", []), list) else [],
        "repeat_issues_to_avoid": review.get("repeat_issues_to_avoid", [])[:5] if isinstance(review.get("repeat_issues_to_avoid", []), list) else []}
    trends = youtube_trending(yt_key, yt_token)
    trend_sample = [x for x in trends if x["category"] == "Science & Technology"][:12] + [x for x in trends if x["category"] == "Education"][:10]
    (outdir / "youtube_trend_signals.json").write_text(json.dumps({
        "source": "YouTube Data API v3 videos.list chart=mostPopular", "region": "US",
        "categories": ["Science & Technology", "Education"],
        "editorial_rotation": rotation,
        "quota_note": "Two videos.list chart calls; documented quota cost is 1 unit per call. No extra YouTube API calls were added.",
        "fetched_at_utc": now.isoformat(), "items": trends}, indent=2), encoding="utf-8")

    # The improvement scout is weekly, uses one Tavily query on Sunday, and accepts official docs only.
    improvement_report = {
        "status": "skipped", "scheduled": scout_plan, "sources": [],
        "auto_installs": False, "auto_production_code_edits": False,
        "policy": "Official-source research only; changes to dependencies, permissions, paid services, or production code are never self-applied."
    }
    if scout_plan.get("enabled"):
        try:
            raw_improvements = tavily_search(tv_key, scout_plan["query"], [scout_plan["domain"]])
            official = []
            for source in clean_sources(raw_improvements):
                host = urllib.parse.urlparse(source["url"]).hostname or ""
                if host == scout_plan["domain"] or host.endswith("." + scout_plan["domain"]):
                    official.append(source)
            improvement_report.update({
                "status": "completed" if official else "no_official_results",
                "queried_at_utc": datetime.now(timezone.utc).isoformat(),
                "sources": official[:5],
                "next_action": "Review official sources and emit testable, free-compatible proposals; no package or workflow mutation from web text."
            })
        except Exception as exc:
            improvement_report.update({"status": "failed_non_blocking", "error_type": type(exc).__name__,
                                       "note": "The weekly scout failed safely; daily topic research continues."})
    (outdir / "tool_improvement_research.json").write_text(json.dumps(improvement_report, indent=2, ensure_ascii=False), encoding="utf-8")

    topic = groq_json(
        "You are the US-audience editorial trend strategist for AI Tech Lab. Choose an original explainer in the assigned editorial category; do not copy trending titles. Do not claim search volume or growth when not provided. Return JSON keys: category (one exact category from the supplied rotation), topic, angle, why_now, category_override_reason, research_queries (exactly 2 concise Tavily queries), trend_evidence (matching supplied video titles/URLs), avoid_title_similarity, improvement_recommendations (array of at most 3 objects with idea, source_url, free_tier_impact, validation_test, implementation_mode). Only recommend an improvement if supported by the supplied official documentation; never recommend paid tools, new secrets, broader permissions, or automatic production-code changes. Use the scheduled category by default. Override it only when at least three distinct current US trend videos materially support another listed category; state the evidence and reason. Prefer a distinctive, debate-worthy angle and an evidence-grounded prediction or tension; avoid generic trend recaps.\n\n" + NATURAL_VOICE_GUIDANCE,
        json.dumps({"current_us_youtube_popular_videos": trend_sample, "manual_direction_if_any": args.seed_topic,
                    "target_date_us_eastern": editorial_date, "editorial_category_rotation": rotation,
                    "weekly_official_tool_improvement_research": improvement_report,
                    "previous_video_feedback": learning}, ensure_ascii=False),
        max_tokens=1000)
    candidate_category = str(topic.get("category", rotation["category"])).strip()
    category_names = {x["name"] for x in EDITORIAL_CATEGORIES}
    if candidate_category not in category_names:
        raise SystemExit("Topic strategist did not choose one of the seven exact category names; no package was released.")
    category_decision = resolve_category(candidate_category, rotation, trend_sample)
    if candidate_category != category_decision["category"]:
        raise SystemExit("Topic strategist requested an off-rotation category without three-video live-trend evidence; no package was released.")
    topic["category"] = category_decision["category"]
    topic["category_decision"] = category_decision
    topic["category_rotation_date_us_eastern"] = editorial_date
    if not topic.get("category_override_reason") and category_decision.get("override"):
        topic["category_override_reason"] = "Live US trend evidence passed the three-distinct-video override gate."
    recommendations = topic.get("improvement_recommendations", [])
    if not isinstance(recommendations, list):
        recommendations = []
    checked_recommendations = []
    official_urls = {str(item.get("url", "")) for item in improvement_report.get("sources", [])}
    for item in recommendations[:3]:
        if not isinstance(item, dict):
            continue
        source_url = str(item.get("source_url", "")).strip()
        if scout_plan.get("enabled") and source_url not in official_urls:
            continue
        if not scout_plan.get("enabled"):
            continue
        checked_recommendations.append({
            "idea": str(item.get("idea", ""))[:350],
            "source_url": source_url,
            "free_tier_impact": str(item.get("free_tier_impact", ""))[:250],
            "validation_test": str(item.get("validation_test", ""))[:350],
            "implementation_mode": str(item.get("implementation_mode", "test_required"))[:60],
            "auto_implemented": False
        })
    improvement_report["recommendations"] = checked_recommendations
    improvement_report["policy"] = "Official-source ideas are filtered to exact retrieved official URLs. Recommendations remain pending until they pass offline tests and cost/security checks; no web-derived code is auto-executed."
    improvement_report["proposal_status"] = "proposals_ready_for_review" if checked_recommendations else ("no_supported_proposals" if scout_plan.get("enabled") else "not_scheduled_this_day")
    (outdir / "tool_improvement_research.json").write_text(json.dumps(improvement_report, indent=2, ensure_ascii=False), encoding="utf-8")

    topic_name = re.sub(r"\s+", " ", str(topic.get("topic", ""))).strip()[:180]
    angle = re.sub(r"\s+", " ", str(topic.get("angle", ""))).strip()[:700]
    queries = topic.get("research_queries", [])
    if not topic_name or not angle or not isinstance(queries, list) or len(queries) < 2:
        raise SystemExit("Groq topic selection failed quality checks; no research package was released.")
    queries = [str(q).strip()[:240] for q in queries[:2] if str(q).strip()]
    if len(queries) < 2:
        raise SystemExit("Groq did not produce two useful research queries.")

    raw_results = []
    for query in queries:
        raw_results.extend(tavily_search(tv_key, query))
    sources = clean_sources(raw_results)
    if len(sources) < 4:
        raise SystemExit(f"Tavily returned only {len(sources)} usable HTTPS sources; at least four are required.")
    (outdir / "tavily_evidence.json").write_text(json.dumps({
        "provider": "Tavily Search API", "queries": queries,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(), "sources": sources},
        indent=2, ensure_ascii=False), encoding="utf-8")

    evidence_context = [{"title": s["title"], "url": s["url"], "date": s["published_date"], "evidence": s["content"]} for s in sources]
    draft = groq_json(
        """You are the lead English-language YouTube scriptwriter for AI Tech Lab (USA audience). Use ONLY supplied evidence for factual specifics; never invent numbers, quotes, product capabilities, release dates, or market claims. Explain uncertainty and limitations. Create a fresh 6-minute explainer in the assigned editorial category, not a paraphrase. HUMAN VALUE REQUIREMENT: every video must help a real viewer understand or decide something useful. Identify the target viewer's real question, explain why the development matters in everyday life/work/business, include at least one concrete scenario or decision framework, state practical next steps or what to watch for, explain meaningful trade-offs/limitations, and end with a specific takeaway rather than a generic summary. Do not invent hands-on experience or claim the channel tested a tool unless the supplied evidence proves it. Keep advice proportional to evidence and distinguish facts, analysis, opinion, and forecasts. Return JSON keys: title, script, description, tags (array), hook_candidates (array of 3), claims (array of {claim, source_urls, confidence}), visual_direction (array of {section, visual, movement, overlay}), and chapters (array of {label, approximate_position}). Script must be spoken narration only, 700-900 words, US English, a specific hook, clear story arc, varied sentences, accessible but intelligent, concrete evidence-based examples, balanced caveats and concise CTA. No unsupported superlatives. Do not add production instructions inside narration.

PERSONAL PERSONA: Write like a distinctive, curious US technology analyst—not a generic AI summary bot. Make this video's analysis recognizably original, with unique predictions where the evidence supports them, reasoned hot takes, clearly labelled personal opinions, and cautious futuristic theories when useful. Clearly distinguish opinions and forecasts from verified facts; never invent numbers, quotations, hands-on tests, or human lived experience. Use conversational professional voice, varied sentence lengths, contractions where natural, vivid analogies, specific stakes, and transitions that advance the story. Do not manufacture personal experience. Avoid the same sentence opener repeated three or more times, generic AI hype, list-reading, unnecessary signposting, empty filler, and phrases from the natural-voice guidance.

""" + NATURAL_VOICE_GUIDANCE,
        json.dumps({"editorial_category": topic["category"], "topic": topic_name, "editorial_angle": angle, "why_now": topic.get("why_now", ""),
                    "youtube_trend_context": trend_sample[:12], "tavily_sources": evidence_context,
                    "previous_video_feedback": learning}, ensure_ascii=False), max_tokens=3300)
    title = re.sub(r"\s+", " ", str(draft.get("title", "")).strip())[:100]
    script = re.sub(r"\r\n?", "\n", str(draft.get("script", "")).strip())
    words = len(re.findall(r"\b[\w'-]+\b", script))
    if not title or words < 600 or words > 1000:
        raise SystemExit(f"Groq script failed word-count/title gate ({words} words; title present={bool(title)}).")
    title_similarity = title_similarity_ratio(title, learning.get("last_title", ""))
    if learning.get("last_title") and title_similarity >= 0.62:
        raise SystemExit("Generated title is too similar to the previous delivered title (Jaccard=" + str(title_similarity) + "); no duplicate package was released.")

    hooks = draft.get("hook_candidates", [])
    if not isinstance(hooks, list) or len(hooks) < 2:
        hooks = [script.split(".")[0].strip()]

    audit = groq_json(
        """You are an independent fact-checking editor and human-voice editor. Review the complete script against only the supplied source evidence. Return JSON keys: score (integer 1-10), human_voice_score (integer 1-10), selected_hook (one concise opening line), revised_script (complete spoken script, 650-950 words), unsupported_claims (array of exact unsupported claims), corrections_made (array), robotic_signals (array of specific issues), natural_phrasing_changes (array), decision (PASS or REVISE). Improve the first 15 seconds and transitions, preserve supported facts and natural American English, and revise the narration rather than merely describing problems. Remove or qualify unsupported claims. Never invent evidence. Audit HUMAN VALUE too: the narration must answer a real viewer question, explain practical consequences, include a concrete scenario or usable decision framework, cover meaningful trade-offs/limitations, and provide a specific takeaway or next step. Replace generic recap with useful analysis where needed; never fabricate personal experience, hands-on tests, facts, or outcomes.

Preserve a recognizable editorial point of view and natural spoken rhythm. Vary sentence lengths and openings, use contractions when appropriate, prefer specific concrete language, and avoid canned openings, repeated transitions, inflated certainty, empty hype, fake lived experience, and robotic list-reading. Use a reasoned hot take and a clearly framed forecast only when supported. Distinguish factual claims from commentary.

""" + NATURAL_VOICE_GUIDANCE,
        json.dumps({"title": title, "script": script, "hook_candidates": hooks,
                    "claims_for_audit": draft.get("claims", []), "source_evidence": evidence_context,
                    "trend_basis": topic.get("trend_evidence", [])}, ensure_ascii=False),
        max_tokens=3300, temperature=0.15)
    revised = re.sub(r"\r\n?", "\n", str(audit.get("revised_script", "")).strip())
    revised_words = len(re.findall(r"\b[\w'-]+\b", revised))
    if 600 <= revised_words <= 1000:
        script = revised
    hook_score = int(audit.get("score", 0) or 0)
    try:
        auditor_voice_score = int(audit.get("human_voice_score", 0) or 0)
    except (TypeError, ValueError):
        auditor_voice_score = 0
    if hook_score < 7:
        raise SystemExit(f"Groq hook review scored {hook_score}/10. No publish-ready script package was released.")
    if auditor_voice_score < 7:
        raise SystemExit(f"Independent human-voice audit scored {auditor_voice_score}/10. No publish-ready script package was released.")
    if not script or len(script) < 2500:
        raise SystemExit("Final script did not pass length/content validation.")
    human_voice_qa = evaluate_human_voice(script)
    if human_voice_qa["score"] < 62:
        raise SystemExit("Final narration failed the human-voice style gate (score " + str(human_voice_qa["score"]) + "/100); no production package was released.")

    tags = draft.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    normalized_tags, seen_tags = [], set()
    for tag in tags:
        tag = re.sub(r"\s+", " ", str(tag)).strip(" ,#")[:90]
        if tag and tag.casefold() not in seen_tags:
            seen_tags.add(tag.casefold())
            normalized_tags.append(tag)
    while len(",".join(normalized_tags)) > 480 and normalized_tags:
        normalized_tags.pop()
    if not normalized_tags:
        normalized_tags = ["AI Tech Lab", "artificial intelligence", topic_name[:50]]
    description = re.sub(r"\s+", " ", str(draft.get("description", "")).strip())
    attribution = "\n\nSOURCES & FURTHER READING\n" + "\n".join(f"- {s['title']}: {s['url']}" for s in sources)
    description = (description[:max(0, 4900 - len(attribution))].rstrip() + attribution)[:4900]

    visual_direction = draft.get("visual_direction", [])
    if not isinstance(visual_direction, list):
        visual_direction = []
    claims = draft.get("claims", [])
    if not isinstance(claims, list):
        claims = []
    source_urls = {s["url"] for s in sources}
    claims_checked = []
    for item in claims:
        if not isinstance(item, dict):
            continue
        urls = [str(u) for u in item.get("source_urls", []) if str(u) in source_urls]
        claims_checked.append({"claim": str(item.get("claim", ""))[:500], "source_urls": urls,
                               "confidence": str(item.get("confidence", "unrated"))[:40], "source_linked": bool(urls)})
    package = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "target_audience": "United States",
        "editorial_category": topic["category"], "category_rotation": rotation,
        "category_decision": category_decision, "title_similarity_to_previous": title_similarity,
        "human_voice_qa": human_voice_qa,
        "agent_policy_version": "1.0.0", "tool_improvement_research": improvement_report,
        "brand": "AI Tech Lab", "primary_ai": "Groq", "research_provider": "Tavily Search API",
        "trend_provider": "YouTube Data API v3", "trend_basis": topic, "title": title,
        "hook": str(audit.get("selected_hook", hooks[0] if hooks else ""))[:350],
        "hook_audit": {"score": hook_score, "human_voice_score": auditor_voice_score,
                       "decision": str(audit.get("decision", "")),
                       "corrections_made": audit.get("corrections_made", []),
                       "unsupported_claims_reported": audit.get("unsupported_claims", [])},
        "script_word_count": len(re.findall(r"\b[\w'-]+\b", script)), "script": script,
        "description": description, "tags": normalized_tags, "chapters": draft.get("chapters", []),
        "visual_direction": visual_direction, "claims_review": claims_checked,
        "warnings": ["Claims are grounded in the listed Tavily search results; review factual claims before publication. Kokoro narration is generated automatically and must pass audio QA."],
        "sources": sources, "previous_video_learning_applied": learning}

    used_ai_providers = sorted({str(item.get("provider", "")).lower() for item in _AI_CALL_LOG if item.get("provider")})
    ai_tools = ["Groq"] if "groq" in used_ai_providers else []
    if any("cloudflare" in item or "workers_ai" in item for item in used_ai_providers):
        ai_tools.append("Cloudflare Workers AI fallback")
    scout_status = improvement_report.get("status", "skipped")
    research_runs = [
        {"agent_id": "research_scout", "status": "completed", "actual_tools_used": ["YouTube Data API v3", "Tavily Search API"],
         "evidence_files": ["work/youtube_trend_signals.json", "work/tavily_evidence.json"],
         "details": {"youtube_trend_items": len(trends), "usable_web_sources": len(sources), "region": "US"}},
        {"agent_id": "category_editor", "status": "completed", "actual_tools_used": ["US Eastern calendar", "YouTube trend evidence"],
         "evidence_files": ["work/youtube_trend_signals.json", "work/topic_brief.json"], "details": category_decision},
        {"agent_id": "scriptwriter", "status": "completed", "actual_tools_used": ai_tools,
         "evidence_files": ["work/daily_content_package.json", "work/script.txt"], "details": {"human_voice_score": human_voice_qa["score"], "hook_score": hook_score}},
        {"agent_id": "fact_editor", "status": "completed", "actual_tools_used": ai_tools + ["Tavily source evidence"],
         "evidence_files": ["work/hook_audit.json", "work/tavily_evidence.json"], "details": {"source_linked_claims": sum(1 for x in claims_checked if x["source_linked"]), "unlinked_claims": sum(1 for x in claims_checked if not x["source_linked"])}},
        {"agent_id": "improvement_scout", "status": "completed" if scout_status == "completed" else "skipped" if not scout_plan.get("enabled") else scout_status,
         "actual_tools_used": ["Tavily Search API", scout_plan.get("domain", "official documentation")] if scout_status == "completed" else [],
         "evidence_files": ["work/tool_improvement_research.json"], "details": {"tool": scout_plan.get("tool"), "status": scout_status,
                     "official_source_count": len(improvement_report.get("sources", [])),
                     "recommendations_count": len(checked_recommendations), "no_automatic_code_changes": True}}
    ]
    agent_report = agent_execution_report("research", research_runs, {
        "target_date_us_eastern": editorial_date, "editorial_category": topic["category"],
        "ai_providers_observed": used_ai_providers, "policy_version": "1.0.0"})
    (outdir / "mini_agent_execution_report.json").write_text(json.dumps(agent_report, indent=2, ensure_ascii=False), encoding="utf-8")
    (outdir / "daily_content_package.json").write_text(json.dumps(package, indent=2, ensure_ascii=False), encoding="utf-8")
    (outdir / "topic_brief.json").write_text(json.dumps(topic, indent=2, ensure_ascii=False), encoding="utf-8")
    (outdir / "title.txt").write_text(title, encoding="utf-8")
    (outdir / "script.txt").write_text(script, encoding="utf-8")
    (outdir / "description.txt").write_text(description, encoding="utf-8")
    (outdir / "tags.txt").write_text(",".join(normalized_tags), encoding="utf-8")
    (outdir / "hook_audit.json").write_text(json.dumps(package["hook_audit"], indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        "status": "SCRIPT_PACKAGE_READY_FOR_KOKORO_VOICE_PRODUCTION", "title": title,
        "script_words": package["script_word_count"], "hook_score": hook_score,
        "trend_signals": len(trends), "usable_tavily_sources": len(sources),
        "editorial_category": topic["category"], "rotation_category": rotation["category"],
        "human_voice_score": human_voice_qa["score"], "independent_voice_audit_score": auditor_voice_score,
        "tool_improvement_scout": scout_status,
        "official_tool_improvement_proposals": len(checked_recommendations),
        "agent_report": "work/mini_agent_execution_report.json",
        "source_linked_claims": sum(1 for x in claims_checked if x["source_linked"]),
        "unlinked_claims": sum(1 for x in claims_checked if not x["source_linked"]),
        "next_gate": "Kokoro automatically generates American-English narration; audio QA must pass before rendering."}
    (outdir / "research_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))

if __name__ == "__main__":
    main()
