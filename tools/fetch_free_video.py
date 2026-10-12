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
MAX_BYTES = 80 * 1024 * 1024
MAX_API_REQUESTS = 120
MIN_API_INTERVAL_SECONDS = 1.25
STOP = set("""about above after again also although among another any are around because been before being between both but can could did does doing down during each few for from further get got had has have having here how into its itself just more most much must near new nor not now off once only other our out over own same says should since some such than that the their them then there these they thing this those through too under until use used using very was were what when where which while who why will with would your you and the for from with into onto how why when then than that this these those real latest technology artificial intelligence explain explained explains""".split())
ANCHORS = set("ai chip chips chiplet chiplets semiconductor semiconductors processor processors gpu gpus nvidia silicon microchip microchips wafer wafers accelerator accelerators maia inference server servers rack racks datacenter data center megawatt megawatts power electricity cooling compute computing memory networking network bandwidth circuit circuits hardware motherboard transistor transistors".split())
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
    # Remove duplicates and keep the query set small so Commons can be used politely.
    return list(dict.fromkeys(q for q in queries if q))[:4]

def relevance_score(scene_text, title, description):
    """Score on both shared hardware concepts and narrower scene-word overlap."""
    scene_words = set(terms_of(scene_text))
    available = set(terms_of(str(title or "") + " " + str(description or "")))
    scene_anchors = anchor_terms(scene_text)
    shared_anchors = scene_anchors & anchor_terms(str(title or "") + " " + str(description or ""))
    if not shared_anchors:
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

def main():
    global RATE_LIMITED, REQUEST_BUDGET_REACHED
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
        if downloaded >= MIN_LICENSED_CLIPS or downloaded >= MAX_DOWNLOADS:
            break
        if stop_all or RATE_LIMITED or REQUEST_BUDGET_REACHED:
            break
        if len(row) < 7:
            continue
        scene = re.sub(r"[^A-Za-z0-9_-]", "_", row[0])[:80]
        target = Path(f"assets/scene_{scene}.mp4")
        if target.is_file() and target.stat().st_size > 10000:
            continue

        scene_text = re.sub(r"\\s+", " ", f"{row[5]} {row[6]}").strip()
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
        for query in query_candidates:
            if stop_all or RATE_LIMITED or REQUEST_BUDGET_REACHED:
                break
            try:
                results = search_files(query)
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
                        or not re.search(r"\\.(mp4|webm|ogv|ogg|mov|m4v)$", title, re.I)):
                    continue
                seen_titles.add(title)
                score, _, _ = relevance_score(scene_text, title, "")
                candidates.append((score, title))
            candidates.sort(key=lambda item: item[0], reverse=True)

            # Read a few metadata records per shared query; caches ensure that the same
            # candidate isn't fetched repeatedly for every scene.
            for title_score, title in candidates[:4]:
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
                    if score < 0.18 or not matching_anchors:
                        continue
                    specific = scene_anchors & {
                        "chip", "chips", "chiplet", "semiconductor", "processor", "gpu", "nvidia",
                        "silicon", "microchip", "wafer", "accelerator", "maia", "server", "rack",
                        "networking", "bandwidth", "circuit", "hardware", "motherboard", "transistor"
                    }
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
                "-t", "30", "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=30,setsar=1",
                "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
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
                "query": " / ".join(query_candidates), "commercial_use_allowed": True
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
