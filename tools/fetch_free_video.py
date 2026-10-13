#!/usr/bin/env python3
"""Fetch scene-relevant, commercially usable video from Wikimedia Commons, preserving license records."""
from __future__ import annotations
import html, json, re, subprocess, time, urllib.parse, urllib.request
import urllib.error
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
UA = "AI-Tech-Lab-Renderer/1.0 (https://github.com/hamarketers05/ai-assistant-renderer)"
MAX_SCENES, MAX_DOWNLOADS = 48, 8
MIN_LICENSED_CLIPS = 4
TARGET_CLIPS = 8
MAX_BYTES = 80 * 1024 * 1024
MIN_WIDTH, MIN_HEIGHT = 1920, 1080
MAX_API_REQUESTS = 120
MIN_API_INTERVAL_SECONDS = 1.25
STOP = set("""about above after again also although among another any are around because been before being between both but can could did does doing down during each few for from further get got had has have having here how into its itself just more most much must near new nor not now off once only other our out over own same says should since some such than that the their them then there these they thing this those through too under until use used using very was were what when where which while who why will with would your you and the for from with into onto how why when then than that this these those real latest technology artificial intelligence explain explained explains""".split())
ANCHORS = set("ai artificial intelligence automation automated agent agents robot robotic robots robotics cybersecurity cyber security privacy surveillance security fraud software code coding programming algorithm algorithms neural model models developer developers workplace factory industry industries worker workers finance fairness fair ethics ethical governance bias biased oversight accountability transparency transparent explainable explainability safety risk risks autonomy autonomous misinformation disinformation deepfake deepfakes manipulation regulation compliance control chip chips chiplet chiplets semiconductor semiconductors processor processors gpu gpus nvidia silicon microchip microchips wafer wafers accelerator accelerators maia inference server servers rack racks datacenter data center megawatt megawatts power electricity cooling compute computing memory networking network bandwidth circuit circuits hardware motherboard transistor transistors".split())
# One-word matches are accepted only when they name a distinctive hardware concept.
# Generic anchors such as "data", "power", "center", or "network" are insufficient alone.
SPECIFIC_SINGLE_ANCHORS = set("automation agent agents robot robotic robots robotics cybersecurity security privacy surveillance fairness ethics ethical governance transparency transparent explainable explainability fraud software code programming algorithm deepfake chip chips chiplet chiplets semiconductor semiconductors processor processors gpu gpus nvidia silicon microchip microchips wafer wafers accelerator accelerators maia inference server servers rack racks datacenter megawatt megawatts networking bandwidth circuit circuits hardware motherboard transistor transistors".split())
MIN_VIDEO_RELEVANCE = 0.30
API_REQUESTS = 0
LAST_API_REQUEST = 0.0
RATE_LIMITED = False
REQUEST_BUDGET_REACHED = False
SEARCH_CACHE = {}
INFO_CACHE = {}
USED_FILE_TITLES = set()
VIDEO_EXTS = {".mp4", ".webm", ".ogv", ".ogg", ".mov", ".m4v"}

def clean(value):
    if isinstance(value, dict):
        value = value.get("value", "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()

def req_json(url):
    """Serial, cache-friendly MediaWiki requests with Retry-After-aware backoff."""
    global API_REQUESTS, LAST_API_REQUEST, RATE_LIMITED, REQUEST_BUDGET_REACHED
    if API_REQUESTS >= MAX_API_REQUESTS:
        REQUEST_BUDGET_REACHED = True
        raise RuntimeError(f"Commons per-video API budget reached ({MAX_API_REQUESTS} requests)")
    last_error = None
    for attempt in range(3):
        pause = MIN_API_INTERVAL_SECONDS - (time.monotonic() - LAST_API_REQUEST)
        if pause > 0:
            time.sleep(pause)
        LAST_API_REQUEST = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        API_REQUESTS += 1
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError(f"Commons API HTTP {response.status}")
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in (429, 503):
                raise
            retry_after = None
            try:
                retry_after = float(exc.headers.get("Retry-After", ""))
            except (TypeError, ValueError):
                pass
            # Wikimedia guidance: honor Retry-After, otherwise wait at least 5s
            # and back off more on repeat rate-limit responses.
            delay = retry_after if retry_after is not None else max(5.0, 5.0 * (2 ** attempt))
            delay = min(60.0, max(5.0, delay))
            if attempt < 2:
                print(f"Commons API rate limit HTTP {exc.code}; waiting {delay:.1f}s before retry.")
                time.sleep(delay)
                continue
            RATE_LIMITED = True
            raise RuntimeError(f"Commons API remained rate limited after backoff (HTTP {exc.code})") from exc
    raise RuntimeError(f"Commons API request failed after retries: {last_error}")

def terms_of(text):
    out = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", text.lower()):
        if word not in STOP and word not in out:
            out.append(word)
    return out[:12]

def concept_terms(text):
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))

def anchor_terms(text):
    tokens = concept_terms(text)
    expanded = set(tokens)
    aliases = {
        "ai": {"artificial", "intelligence", "automation"},
        "artificial": {"ai", "intelligence"}, "intelligence": {"ai", "artificial"},
        "agent": {"automation", "robot"}, "agents": {"automation", "robot", "robots"},
        "robot": {"automation", "agent"}, "robots": {"automation", "agents"},
        "robotics": {"robot", "automation"}, "robotic": {"robot", "robotics", "automation"},
        "automated": {"automation", "robot"},
        "cybersecurity": {"cyber", "security"}, "cyber": {"security", "cybersecurity"},
        "surveillance": {"privacy", "security"}, "privacy": {"surveillance", "security"},
        "transparent": {"transparency", "explainable"}, "explainable": {"transparency", "explainability"},
        "explainability": {"explainable", "transparency"}, "fair": {"fairness", "ethics"},
        "ethics": {"ethical", "governance", "fairness"}, "ethical": {"ethics", "governance"},
        "accountability": {"oversight", "governance"}, "oversight": {"accountability", "governance"},
        "misinformation": {"disinformation", "deepfake"}, "disinformation": {"misinformation", "deepfake"},
        "deepfakes": {"deepfake", "misinformation"}, "risks": {"risk", "safety"},
        "software": {"code", "algorithm"}, "programming": {"software", "code"},
        "microchip": {"chip", "processor"}, "microchips": {"chip", "processor"},
        "cpu": {"processor"}, "gpus": {"gpu", "processor", "accelerator"},
        "gpu": {"processor", "accelerator"}, "accelerators": {"accelerator", "processor", "chip"},
        "semiconductors": {"semiconductor", "chip"}, "semiconductor": {"chip"},
        "silicon": {"chip", "semiconductor"}, "wafers": {"wafer", "silicon", "chip"},
        "datacenter": {"data", "center", "server"}, "datacenters": {"data", "center", "server"},
        "servers": {"server", "rack"}, "racks": {"rack", "server"},
        "chiplets": {"chiplet", "chip", "silicon"}, "processors": {"processor", "chip"},
        "transistors": {"transistor", "chip"}, "circuits": {"circuit", "hardware"},
    }
    for token in tokens:
        expanded.update(aliases.get(token, set()))
    # Compound phrases often appear hyphenated in scene text and unhyphenated in stock titles.
    if "data-center" in tokens or {"data", "center"} <= tokens:
        expanded.update({"data", "center", "datacenter"})
    return expanded & ANCHORS

def topic_queries(text):
    """Return a small set of reusable searches based on real hardware concepts."""
    anchors = anchor_terms(text)
    queries = []
    # Topic-family searches cover the full AI Tech Lab niche, not only AI chips.
    # Per-file titles/descriptions, resolution, license, and repeat-use checks remain mandatory.
    # For AI/agent scenes, prioritize four focused robotics/automation searches first.
    # Relevance and per-file license/resolution/reuse checks still decide what may be used.
    if anchors & {"ai", "artificial", "intelligence", "automation", "automated", "agent", "agents", "robot", "robots", "robotics", "algorithm", "algorithms", "neural", "model", "models", "ethics", "ethical", "governance", "oversight", "accountability", "safety"}:
        queries.extend(["AI automation robot", "artificial intelligence agent", "robotic arm industrial robot", "factory robot automation"])
    if anchors & {"privacy", "surveillance"}:
        queries.extend(["privacy surveillance technology", "surveillance cameras privacy"])
    if anchors & {"cybersecurity", "cyber", "security", "fraud", "bias", "biased", "misinformation", "deepfake"}:
        queries.extend(["cybersecurity computer security", "computer security surveillance"])
    if anchors & {"software", "code", "coding", "programming", "developer", "developers", "algorithm", "algorithms"}:
        queries.extend(["software developer computer", "computer programming code"])
    if anchors & {"worker", "workers", "workplace", "factory", "industry", "industries", "finance"}:
        queries.extend(["robot automation workplace", "industrial automation robot"])
    if anchors & {"chip", "chips", "chiplet", "semiconductor", "processor", "silicon", "microchip", "wafer", "maia"}:
        queries.extend(["computer chip semiconductor", "microchip processor"])
    if anchors & {"gpu", "nvidia", "accelerator", "inference", "compute", "computing"}:
        queries.append("GPU processor")
    if anchors & {"server", "rack", "datacenter", "data", "center", "network", "networking"}:
        queries.extend(["data center server", "server rack"])
    if anchors & {"megawatt", "power", "electricity", "cooling"}:
        queries.append("data center cooling")
    if anchors & {"memory", "circuit", "motherboard", "transistor", "hardware"}:
        queries.append("computer hardware")
    # Remove duplicates and keep each scene to four focused, reusable API searches.
    return list(dict.fromkeys(q for q in queries if q))[:4]


def curated_titles_for_scene(scene_text):
    """Prioritize a small set of known Commons pages; every file still undergoes all live metadata gates."""
    anchors = anchor_terms(scene_text)
    titles = []
    if anchors & {"privacy", "surveillance"}:
        titles.append("File:Surveillance cameras in public places are an invasion of privacy- WMNF News.webm")
    if anchors & {"cybersecurity", "cyber", "security", "fraud"}:
        titles.append("File:AFN Okinawa Radio around the Region Cyber Security (950168).webm")
    if anchors & {"ai", "artificial", "intelligence", "automation", "automated", "agent", "agents",
                  "robot", "robotic", "robots", "robotics", "algorithm", "algorithms", "neural", "model", "models"}:
        titles.extend([
            "File:Generative AI explained in 2 minutes.webm",
            "File:Lindirobot.webm",
        ])
    if anchors & {"ethics", "ethical", "governance", "fairness", "transparent", "transparency",
                  "explainable", "explainability", "oversight", "accountability", "safety"}:
        titles.append("File:Ética de la IA en la medicina digital - Explicación de por qué es importante una IA transparente y explicable (Spanish redub).webm")
    return list(dict.fromkeys(titles))

def relevance_score(scene_text, title, description):
    """Score on both shared hardware concepts and narrower scene-word overlap."""
    scene_words = set(terms_of(scene_text))
    available = set(terms_of(str(title or "") + " " + str(description or "")))
    scene_anchors = anchor_terms(scene_text)
    shared_anchors = scene_anchors & anchor_terms(str(title or "") + " " + str(description or ""))
    if not shared_anchors:
        return 0.0, sorted(scene_words & available), []
    if len(shared_anchors) < 2 and not (shared_anchors & SPECIFIC_SINGLE_ANCHORS):
        # Preserve generic word matches for diagnostics only; they are not accepted anchors.
        return 0.0, sorted(scene_words & available), []
    word_overlap = len(scene_words & available) / max(1, len(scene_words))
    anchor_overlap = len(shared_anchors) / max(1, len(scene_anchors))
    score = round(min(1.0, 0.65 * anchor_overlap + 0.35 * word_overlap), 3)
    return score, sorted(scene_words & available), sorted(shared_anchors)

def license_ok(label, url):
    label_low = re.sub(r"\s+", " ", label.lower()).strip()
    url_low = url.lower()
    all_text = label_low + " " + url_low
    if any(x in all_text for x in ("by-nc", "by-nd", "noncommercial", "non-commercial", "no derivatives", "no-derivatives")):
        return False, label or "Unverified license", True
    if "public domain" in label_low or "cc0" in label_low or "creativecommons.org/publicdomain" in url_low or "pd-usgov" in label_low:
        return True, label or "Public domain", False
    if "creativecommons.org/licenses/by/" in url_low or "creativecommons.org/licenses/by-sa/" in url_low:
        return True, label or ("CC BY-SA" if "/by-sa/" in url_low else "CC BY"), True
    if re.search(r"\bcc\s*by(?:\s*-?sa)?\b", label_low) and "nc" not in label_low and "nd" not in label_low:
        return True, label, True
    return False, label or "License missing", True

def meta_field(meta, key):
    val = meta.get(key, {})
    return clean(val.get("value", "") if isinstance(val, dict) else val)

def search_files(query):
    key = " ".join(query.lower().split())
    if key in SEARCH_CACHE:
        return SEARCH_CACHE[key]
    params = {"action":"query","format":"json","list":"search","maxlag":2,
              "srsearch":f"filetype:video {query}","srnamespace":6,"srlimit":20,"srprop":"size|wordcount"}
    data = req_json(API + "?" + urllib.parse.urlencode(params))
    result = (data.get("query") or {}).get("search") or []
    SEARCH_CACHE[key] = result
    return result

def file_info(title):
    if title in INFO_CACHE:
        return INFO_CACHE[title]
    params = {"action":"query","format":"json","titles":title,"prop":"imageinfo",
              "iiprop":"url|mime|size|extmetadata","formatversion":2,"maxlag":2}
    data = req_json(API + "?" + urllib.parse.urlencode(params))
    pages = (data.get("query") or {}).get("pages") or []
    if not pages or "missing" in pages[0]:
        INFO_CACHE[title] = None
        return None
    infos = pages[0].get("imageinfo") or []
    result = {"page":pages[0],"info":infos[0]} if infos else None
    INFO_CACHE[title] = result
    return result

def fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as response:
        length = response.headers.get("Content-Length")
        if length and int(length) > MAX_BYTES: raise RuntimeError("File exceeds 80 MiB")
        data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES: raise RuntimeError("File exceeds 80 MiB")
        return data

def self_test():
    irrelevant = relevance_score("Maia data sharing and hardware context", "Packaging data for sharing.webm", "A public health information-sharing training clip")
    relevant_chip = relevance_score("Maia inference chip", "Exposing a Chip on Board (COB).webm", "Close-up video of a silicon chip")
    relevant_power = relevance_score("AI data center power and cooling", "Data center power cooling systems", "Server racks and cooling infrastructure")
    relevant_ai = relevance_score("AI automation and autonomous agents", "Industrial robot automation demonstration", "Robots performing automated tasks")
    ai_queries = topic_queries("AI automation agents oversight")
    curated_queries = curated_titles_for_scene("AI automation agents, privacy and surveillance, cybersecurity, transparent and explainable systems")
    if irrelevant[0] != 0.0 or irrelevant[2]:
        raise SystemExit("Generic-media rejection self-test failed: generic 'data' overlap was accepted.")
    if relevant_chip[0] < MIN_VIDEO_RELEVANCE or not (set(relevant_chip[2]) & SPECIFIC_SINGLE_ANCHORS):
        raise SystemExit("Relevant chip-footage self-test failed.")
    if relevant_power[0] < MIN_VIDEO_RELEVANCE or len(relevant_power[2]) < 2:
        raise SystemExit("Relevant data-center/power-footage self-test failed.")
    if relevant_ai[0] < MIN_VIDEO_RELEVANCE or not (set(relevant_ai[2]) & {"automation", "robot", "robots", "ai", "agent", "agents"}):
        raise SystemExit("Relevant AI automation/agent-footage self-test failed.")
    if not any("automation" in q.lower() or "artificial intelligence" in q.lower() for q in ai_queries):
        raise SystemExit("AI/automation scene did not produce a focused free-media query.")
    required_curated = {
        "File:Surveillance cameras in public places are an invasion of privacy- WMNF News.webm",
        "File:AFN Okinawa Radio around the Region Cyber Security (950168).webm",
        "File:Generative AI explained in 2 minutes.webm",
        "File:Lindirobot.webm",
    }
    if not required_curated.issubset(set(curated_queries)):
        raise SystemExit("Curated free-media candidate self-test failed.")
    if len(ai_queries) < 4 or not any("robotic arm" in q.lower() for q in ai_queries):
        raise SystemExit("AI/agent footage search must inspect expanded Full-HD robotics candidates.")
    print(json.dumps({
        "status": "self_test_passed",
        "minimum_relevance_score": MIN_VIDEO_RELEVANCE,
        "checks": ["generic data-sharing footage rejected", "specific chip footage accepted", "data-center/power footage accepted"]
    }))

def main():
    global RATE_LIMITED, REQUEST_BUDGET_REACHED
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    scenes = Path("work/scenes.tsv")
    if not scenes.is_file():
        raise SystemExit("Missing work/scenes.tsv.")
    log = Path("work/asset_sources.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    log.touch(exist_ok=True)
    rows = [line.rstrip("\n").split("\t") for line in scenes.read_text(encoding="utf-8").splitlines() if line.strip()]
    downloaded, checked, skipped = 0, 0, 0
    stop_all = False

    for row in rows[:MAX_SCENES]:
        if downloaded >= TARGET_CLIPS or downloaded >= MAX_DOWNLOADS:
            break
        if stop_all or RATE_LIMITED or REQUEST_BUDGET_REACHED:
            break
        if len(row) < 7:
            continue
        scene = re.sub(r"[^A-Za-z0-9_-]", "_", row[0])[:80]
        target = Path(f"assets/scene_{scene}.mp4")
        if target.is_file() and target.stat().st_size > 10000:
            continue

        scene_text = re.sub(r"\s+", " ", f"{row[5]} {row[6]}").strip()
        scene_anchors = anchor_terms(scene_text)
        if not scene_anchors:
            skipped += 1
            continue
        query_candidates = topic_queries(scene_text)
        if not query_candidates:
            skipped += 1
            continue

        selected = None
        seen_titles = set()
        curated_titles = set(curated_titles_for_scene(scene_text))
        for query_index, query in enumerate(query_candidates):
            if stop_all or RATE_LIMITED or REQUEST_BUDGET_REACHED:
                break
            try:
                results = search_files(query)
                if query_index == 0 and curated_titles:
                    results = [{"title": title} for title in sorted(curated_titles)] + results
            except Exception as exc:
                print(f"Commons search failed for scene {scene}, query={query!r}: {str(exc)[:140]}")
                if RATE_LIMITED or REQUEST_BUDGET_REACHED:
                    stop_all = True
                continue

            # Rank video candidates by title relevance, but do not require exact title
            # token identity (e.g. "microchip" vs "chip" or "datacenter" vs "data center").
            candidates = []
            for result in results:
                title = str(result.get("title") or "")
                if (not title or title in seen_titles or title in USED_FILE_TITLES
                        or not re.search(r"\.(mp4|webm|ogv|ogg|mov|m4v)$", title, re.I)):
                    continue
                seen_titles.add(title)
                score, _, _ = relevance_score(scene_text, title, "")
                # Candidate priority only decides inspection order; it does not override
                # the live title+description relevance or license/resolution/size checks below.
                if title in curated_titles:
                    score = max(score, 1.0)
                candidates.append((score, title))
            candidates.sort(key=lambda item: item[0], reverse=True)

            # Read a few metadata records per shared query; caches ensure that the same
            # candidate isn't fetched repeatedly for every scene.
            # Search results are sorted by title relevance, but many Commons uploads are
            # 720p/vertical. Inspect up to 20 candidates so eligible native-Full-HD files
            # are not missed merely because a low-resolution match appears near the top.
            for title_score, title in candidates[:20]:
                if stop_all or RATE_LIMITED or REQUEST_BUDGET_REACHED:
                    break
                try:
                    pair = file_info(title)
                    checked += 1
                    if not pair:
                        continue
                    page, info = pair["page"], pair["info"]
                    if not str(info.get("mime") or "").lower().startswith("video/"):
                        continue
                    file_url = str(info.get("url") or "")
                    if Path(urllib.parse.urlparse(file_url).path).suffix.lower() not in VIDEO_EXTS:
                        continue
                    meta = info.get("extmetadata") or {}
                    source_width, source_height = int(info.get("width") or 0), int(info.get("height") or 0)
                    if source_width < MIN_WIDTH or source_height < MIN_HEIGHT:
                        print(f"Commons skipped {title}: native source is below Full HD ({source_width}x{source_height}).")
                        continue
                    label, license_url = meta_field(meta, "LicenseShortName"), meta_field(meta, "LicenseUrl")
                    ok, normalized, attribution = license_ok(label, license_url)
                    if not ok:
                        print(f"Commons skipped {title}: not a verified commercial-use license.")
                        continue
                    creator = meta_field(meta, "Artist") or meta_field(meta, "Credit") or meta_field(meta, "Attribution")
                    if attribution and not creator:
                        print(f"Commons skipped {title}: attribution-required license has no creator metadata.")
                        continue
                    desc = meta_field(meta, "ImageDescription")
                    score, matching_terms, matching_anchors = relevance_score(scene_text, title, desc)
                    if score < MIN_VIDEO_RELEVANCE or not matching_anchors:
                        continue
                    if len(set(matching_anchors)) < 2 and not (set(matching_anchors) & SPECIFIC_SINGLE_ANCHORS):
                        continue
                    specific = scene_anchors & SPECIFIC_SINGLE_ANCHORS
                    if specific and not (specific & set(matching_anchors)):
                        continue
                    source_url = str(info.get("descriptionurl") or "")
                    if not file_url.startswith("https://") or not source_url.startswith("https://commons.wikimedia.org/"):
                        continue
                    size = int(info.get("size") or 0)
                    if size and size > MAX_BYTES:
                        continue
                    selected = {
                        "title": title, "file_url": file_url, "source_url": source_url,
                        "creator": creator, "license": normalized, "license_url": license_url,
                        "source_width": source_width, "source_height": source_height,
                        "attribution": attribution, "relevance_score": score,
                        "matching_terms": matching_terms, "matching_anchors": matching_anchors
                    }
                    break
                except Exception as exc:
                    print(f"Commons metadata skipped for scene {scene}: {str(exc)[:120]}")
                    if RATE_LIMITED or REQUEST_BUDGET_REACHED:
                        stop_all = True
                    break

            if selected or stop_all or RATE_LIMITED or REQUEST_BUDGET_REACHED:
                break

        if not selected:
            skipped += 1
            print(f"No verified, scene-relevant Commons clip for scene {scene}.")
            continue

        try:
            data = fetch_bytes(selected["file_url"])
            if len(data) < 10000:
                raise RuntimeError("Video payload too small")
            ext = Path(urllib.parse.urlparse(selected["file_url"]).path).suffix.lower() or ".webm"
            source = Path(f"work/commons_{scene}{ext}")
            source.write_bytes(data)
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                "-t", "30", "-vf", "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,fps=30,setsar=1",
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target)
            ], check=True, timeout=180)
            if not target.is_file() or target.stat().st_size < 10000:
                raise RuntimeError("FFmpeg output is not usable")
            item = {
                "scene": scene, "provider": "Wikimedia Commons",
                "asset_id": selected["title"],
                "asset_title": selected["title"].removeprefix("File:"),
                "creator": selected["creator"] or "Creator not listed in source metadata",
                "source_url": selected["source_url"], "license_label": selected["license"],
                "license_url": selected["license_url"], "attribution_required": selected["attribution"],
                "relevance_score": selected["relevance_score"],
                "matching_terms": selected["matching_terms"],
                "matching_anchors": selected["matching_anchors"],
                "query": " / ".join(query_candidates), "commercial_use_allowed": True,
                "commercial_use_basis": "Per-file Wikimedia Commons license metadata; only commercial-compatible CC BY/CC BY-SA/CC0/Public Domain accepted.",
                "asset_path": str(target), "source_width": selected["source_width"],
                "source_height": selected["source_height"], "output_resolution": "1920x1080"
            }
            with log.open("a", encoding="utf-8") as out:
                out.write(json.dumps(item, ensure_ascii=False) + "\n")
            USED_FILE_TITLES.add(selected["title"])
            downloaded += 1
            print(f"Commons clip used for scene {scene}: {selected['title']} "
                  f"(relevance={selected['relevance_score']}, anchors={selected['matching_anchors']})")
        except Exception as exc:
            target.unlink(missing_ok=True)
            print(f"Commons download failed for scene {scene}: {str(exc)[:140]}")

    report = {
        "provider": "Wikimedia Commons",
        "scenes_considered": len(rows[:MAX_SCENES]),
        "metadata_items_checked": checked,
        "clips_downloaded": downloaded,
        "minimum_new_licensed_clips_required": MIN_LICENSED_CLIPS,
        "target_new_licensed_clips": TARGET_CLIPS,
        "scenes_without_licensed_footage": skipped,
        "api_requests": API_REQUESTS,
        "rate_limited": RATE_LIMITED,
        "request_budget_reached": REQUEST_BUDGET_REACHED,
        "query_cache_entries": len(SEARCH_CACHE),
        "metadata_cache_entries": len(INFO_CACHE),
        "free_only_policy": True
    }
    Path("work/commons_media_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
if __name__ == "__main__":
    main()
