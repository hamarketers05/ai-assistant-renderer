#!/usr/bin/env python3
"""Build clean, evidence-aware YouTube metadata from the production manifest."""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse
from seo_source_safety import extract_public_urls, sanitize_description

WORK = Path("work")
MANIFEST = json.loads((WORK / "production_manifest.json").read_text(encoding="utf-8"))
TITLE_FILE = WORK / "title.txt"
DESCRIPTION_FILE = WORK / "description.txt"
TAGS_FILE = WORK / "tags.txt"
SCRIPT = (WORK / "script.txt").read_text(encoding="utf-8")
FMT = __import__("os").environ.get("CONTENT_FORMAT", "LONG_VIDEO").upper()
TITLE = re.sub(r"\s+", " ", TITLE_FILE.read_text(encoding="utf-8")).strip()
DESCRIPTION = DESCRIPTION_FILE.read_text(encoding="utf-8").strip()
RAW_TAGS = TAGS_FILE.read_text(encoding="utf-8").strip()
STOP = set("""about after again against also although among another any are around because been before being between both but can could did does doing during each few for from further get got had has have having here how into its itself just more most much must near new nor not now off once only other our out over own same says should since some such than that the their them then there these they thing this those through too under until use used using very was were what when where which while who why will with would your you""".split())


def get_nested(obj, names):
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in {n.lower() for n in names}:
                if isinstance(v, str):
                    found.append(v.strip())
                elif isinstance(v, list):
                    found.extend(str(x).strip() for x in v if isinstance(x, str))
            found.extend(get_nested(v, names))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(get_nested(v, names))
    return [x for x in found if x]


def phrase_list(values):
    result, seen = [], set()
    for raw in values:
        val = re.sub(r"\s+", " ", str(raw)).strip(" ,;|#")
        key = val.casefold()
        if not val or key in seen or len(val) < 3 or len(val) > 90:
            continue
        if not re.search(r"[A-Za-z]", val):
            continue
        seen.add(key)
        result.append(val)
    return result


def clean_title(title):
    title = re.sub(r"(?i)^AI Tech Lab\s*[:|—-]?\s*", "", title).strip()
    generic = re.search(r"(?i)latest trends news topics|latest trends|news topics|trends news", title)
    if generic:
        candidates = get_nested(MANIFEST, ("seo_title", "topic_title", "story_title", "topic", "subject"))
        candidates = [x for x in candidates if len(x) >= 16 and not re.search(r"(?i)latest trends news topics", x)]
        if candidates:
            title = candidates[0]
        else:
            title = re.sub(r"(?i)\s*(latest trends news topics|latest trends|news topics|trends news)\s*", "", title).strip(" -:|")
            if title and not title.endswith("?"):
                title = title + ": What You Need to Know"
    title = re.sub(r"\s+", " ", title).strip(" -:|")
    if not title:
        title = "The Latest AI Technology Shift: What It Means"
    return title[:100].rstrip(" -:|")


def stamp(seconds):
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, sec = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{sec:02d}"
    return f"{minutes}:{sec:02d}"


def chapters():
    result = ["0:00 AI Tech Lab Intro"]
    scenes = []
    path = WORK / "scenes.tsv"
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        cols = line.split("\t")
        if len(cols) < 7:
            continue
        try:
            t = max(0, int(float(cols[1] or 0)) + 4)
        except (TypeError, ValueError):
            continue
        label = re.sub(r"\s+", " ", cols[6] or cols[5] or "Key takeaway").strip(" -|")
        label = re.sub(r"(?i)\b(visual|host|scene|b-roll)\b", "", label).strip()
        if t < 12 or not label:
            continue
        label = label[:58]
        if scenes and t - scenes[-1][0] < 20:
            continue
        scenes.append((t, label))
    result.extend(f"{stamp(t)} {label}" for t, label in scenes[:8])
    return result


def extract_sources():
    urls = []
    # Cite only public HTTPS pages from the manifest and the retained evidence/credit
    # sections of the description. The shared sanitizer rejects signed storage links.
    candidate_text = json.dumps(MANIFEST, ensure_ascii=False) + "\n" + DESCRIPTION
    for url in extract_public_urls(candidate_text):
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if not host:
            continue
        if host.endswith(("youtube.com", "google.com")) and "trends.google.com" not in host:
            continue
        if url not in urls:
            urls.append(url)
    # Preserve the most reliable source list ahead of secondary/community links.
    preferred = ("reuters.com", "apnews.com", "nvidia.com", "microsoft.com", "openai.com",
                 "anthropic.com", "deepmind.google", "blog.google", "nist.gov", "ftc.gov",
                 "whitehouse.gov", "nsf.gov", "nasa.gov", "arxiv.org", "techcrunch.com",
                 "theverge.com", "technologyreview.com", "wired.com", "bloomberg.com")
    urls.sort(key=lambda u: (0 if any(p in urlparse(u).netloc.lower() for p in preferred) else 1, u))
    return urls[:8]


def main():
    global DESCRIPTION
    DESCRIPTION, removed_unsafe_urls = sanitize_description(DESCRIPTION)
    title = clean_title(TITLE)
    if FMT == "SHORT" and "#shorts" not in title.lower():
        suffix = " #Shorts"
        title = title[:100-len(suffix)].rstrip(" -:|") + suffix
    # Keep meaningful LLM-produced copy and source/asset credits; only add a structured,
    # searchable section if it is missing.
    topic = title.strip()
    first_sentences = re.split(r"(?<=[.!?])\s+", DESCRIPTION)
    if not DESCRIPTION or len(DESCRIPTION) < 80:
        DESCRIPTION = (f"{topic} explained clearly: what is changing, how the technology works, "
                       "where the evidence is strong, and what limitations still matter.")
    opening = ("Discover the latest developments behind " + topic.rstrip(".") +
               "—with evidence-backed context, practical examples, key limitations, and what to watch next.")
    if opening[:32].lower() not in DESCRIPTION[:250].lower() and not re.search(r"(?i)what you('ll| will) learn", DESCRIPTION):
        DESCRIPTION = opening + "\n\n" + DESCRIPTION
    if "what you'll learn" not in DESCRIPTION.lower():
        DESCRIPTION += "\n\nWHAT YOU'LL LEARN\n• The core development and why it matters\n• Real-world use cases and practical limits\n• What the available evidence does—and does not—show"
    chapter_lines = chapters()
    if FMT != "SHORT" and len(chapter_lines) >= 3 and "CHAPTERS" not in DESCRIPTION.upper():
        DESCRIPTION += "\n\nCHAPTERS\n" + "\n".join(chapter_lines)
    sources = extract_sources()
    if sources and "SOURCES & FURTHER READING" not in DESCRIPTION.upper():
        DESCRIPTION += "\n\nSOURCES & FURTHER READING\n" + "\n".join(sources)
    if "AI TECH LAB" not in DESCRIPTION.upper():
        DESCRIPTION += "\n\nAI Tech Lab — original explainers on artificial intelligence, emerging technology, research, and the future."
    if "subscribe" not in DESCRIPTION.lower():
        DESCRIPTION += "\n\nSubscribe to AI Tech Lab for evidence-led AI news and future technology explainers."
    if not re.search(r"(?i)#AItechnology|#ArtificialIntelligence", DESCRIPTION):
        DESCRIPTION += "\n\n#ArtificialIntelligence #FutureTechnology #AITechLab"
    if FMT == "SHORT" and "#shorts" not in DESCRIPTION.lower():
        DESCRIPTION += "\n#Shorts"

    existing = [x.strip() for x in re.split(r"[,\n]", RAW_TAGS) if x.strip()]
    meta_tags = get_nested(MANIFEST, ("tags", "keywords", "primary_keyword", "focus_keyword"))
    title_phrases = [title, title.replace(":", ""), "AI Tech Lab", "artificial intelligence",
                     "AI news", "future technology", "AI research", "technology explained"]
    words = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", (title + " " + SCRIPT[:7000]))
    freq = Counter(w.lower() for w in words if w.lower() not in STOP and not w.isdigit())
    ranked = [w for w, count in freq.most_common(30) if count >= 2 and len(w) <= 26]
    tags = phrase_list(existing + meta_tags + title_phrases + ranked)
    # YouTube limits the combined tag text to 500 characters; never stuff unrelated tags.
    final_tags = []
    for tag in tags:
        candidate = final_tags + [tag]
        if len(", ".join(candidate)) <= 495:
            final_tags.append(tag)
        if len(final_tags) >= 25:
            break
    if not final_tags:
        final_tags = ["AI Tech Lab", "artificial intelligence", "future technology"]
    TITLE_FILE.write_text(title, encoding="utf-8")
    DESCRIPTION_FILE.write_text(DESCRIPTION[:4900].rstrip(), encoding="utf-8")
    TAGS_FILE.write_text(", ".join(final_tags), encoding="utf-8")
    report = {
        "format": FMT, "title_characters": len(title), "description_characters": min(len(DESCRIPTION), 4900),
        "tag_count": len(final_tags), "tag_characters": len(", ".join(final_tags)),
        "source_url_count": len(sources), "chapters_added": FMT != "SHORT" and len(chapter_lines) >= 3,
        "unsafe_internal_urls_removed": len(removed_unsafe_urls),
        "title": title, "tags": final_tags, "source_urls": sources,
        "policy": "SEO phrases are derived from supplied script/manifest. No views/rankings/search volumes are invented."
    }
    (WORK / "seo_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("format","title_characters","description_characters","tag_count","tag_characters","source_url_count","chapters_added","title")}))


if __name__ == "__main__":
    main()
